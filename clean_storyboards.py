#!/usr/bin/env python3
"""Strip guardrail text out of storyboard .json/.md files on disk.

The content guardrail lives in guardrail.py and is attached by build_refs.py /
build_song.py when a prompt is built. Storyboards written before that move carry
it twice over: a top-level "global_guardrail" field, and a copy pasted into every
scene's image_prompt. Both are dead weight, and worse, the copy inside the scene
text enumerates forbidden terms ("no minors, no children...") which is exactly
what the minor filter matches -- so a legacy file could refuse its own scenes.

build_song.normalize() already strips this at LOAD time so nothing breaks. This
script does it to the files themselves, so what is on disk matches what the
pipeline actually uses.

Removes, per file:
  - the top-level "global_guardrail" key
  - that same string wherever it appears in image_prompt / story /
    video_motion_prompt
  - guardrail.PINNED, if a file was written while the clause was being injected

Rewrites the sibling .md from the cleaned .json when one exists, so the readable
sheet cannot drift from the data.

usage:
  clean_storyboards.py "Catatonic/**/*.json" ...      # dry run, prints a summary
  clean_storyboards.py --apply "Catatonic/**/*.json"  # actually rewrite
  clean_storyboards.py --apply --all                  # every storyboard in the repo
"""
import argparse, glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardrail  # noqa: E402
from build_storyboard import to_md  # noqa: E402

SCENE_FIELDS = ("image_prompt", "story", "video_motion_prompt", "name")

MIN_BOILERPLATE = 120   # chars; shorter shared tails are legitimate style wording


def _common_tail(values):
    """Longest suffix shared by EVERY value, or "".

    The copy of the guardrail inside the scenes is often not the same string as
    the file's own global_guardrail field -- storyboards were written with a
    paraphrase -- so exact matching removes the field and leaves the duplication.
    What is reliable is that boilerplate is identical in every scene: a long
    shared suffix across all of them is the guardrail plus render tail, and
    nothing scene-specific survives that test.
    """
    values = [v for v in values if isinstance(v, str) and v.strip()]
    if len(values) < 3:
        return ""
    shortest = min(len(v) for v in values)
    n = 0
    while n < shortest and len({v[-(n + 1)] for v in values}) == 1:
        n += 1
    tail = values[0][-n:] if n else ""
    # only start at a sentence boundary so we never bite into scene wording
    m = re.search(r"[.!?]\s", tail)
    return tail[m.end():].strip() if m else ""


# Policy wording. Everything else in the shared tail is STYLE and must survive:
# the render tail ("photorealistic cinematic 3D frame, high detail, 16:9") is
# part of image_prompt and is NOT re-added by build_refs, so removing it would
# quietly degrade every image the pipeline produces.
POLICY_MARKERS = ("no nudity", "adults only", "adult-only", "adult only",
                  "fully clothed", "no explicit", "no sexual", "no simulated",
                  "coercion", "fetish", "non-graphic", "body-part emphasis",
                  "suggestive posing", "intimate anatomy", "clearly adult",
                  "no visible drug", "drug use")


def _policy_sentences(tail):
    """The policy sentences within a shared tail, as one contiguous string.

    Returned only if the policy sentences are contiguous, so removing them
    cannot reorder or corrupt whatever style wording sits around them.
    """
    parts = re.split(r"(?<=[.!?])\s+", tail)
    flags = [any(m in p.lower() for m in POLICY_MARKERS) for p in parts]
    if not any(flags):
        return ""
    first, last = flags.index(True), len(flags) - 1 - flags[::-1].index(True)
    if not all(flags[first:last + 1]):
        return ""          # interleaved with style text -- too risky, skip
    return " ".join(parts[first:last + 1]).strip()


def clean_md(path, policy):
    """Strip the same text out of the readable sheet.

    These .md files predate to_md()'s schema, so regenerating them from the json
    raises on a missing key -- an earlier version swallowed that and left the
    markdown still advertising a guardrail the json no longer had. Editing the
    text directly is what actually keeps the two in step.
    """
    with open(path) as f:
        md = f.read()
    before = md
    # whole sections that only exist to restate policy
    md = re.sub(r"\n#+ Global negative prompt\n+```text\n.*?\n```\n", "\n",
                md, flags=re.S)
    md = re.sub(r"\n#+ Guardrail\n+(_.*?_\n+)?```text\n.*?\n```\n", "\n",
                md, flags=re.S)
    if policy:
        md = md.replace(policy, "")
    md = re.sub(r"[ \t]{2,}", " ", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    if md == before:
        return False
    with open(path, "w") as f:
        f.write(md)
    return True


def clean_file(path):
    """Return (changed, removed_field, scenes_touched, chars_saved, cleaned_dict)."""
    with open(path) as f:
        try:
            sb = json.load(f)
        except json.JSONDecodeError:
            return False, False, 0, 0, None, ""
    if not isinstance(sb, dict) or "scenes" not in sb:
        return False, False, 0, 0, None, ""

    declared = (sb.get("global_guardrail") or "").strip()
    before = len(json.dumps(sb))
    touched = 0

    scenes = [s for s in (sb.get("scenes") or []) if isinstance(s, dict)]
    shared = _policy_sentences(_common_tail([s.get("image_prompt") for s in scenes]))
    if len(shared) < MIN_BOILERPLATE:
        shared = ""

    for scene in sb.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        hit = False
        for field in SCENE_FIELDS:
            val = scene.get(field)
            if not isinstance(val, str) or not val:
                continue
            cleaned = guardrail.strip(val, declared)
            if shared and field == "image_prompt" and shared in cleaned:
                cleaned = re.sub(r"\s{2,}", " ", cleaned.replace(shared, " ")).strip()
            if cleaned != val:
                scene[field] = cleaned
                hit = True
        touched += 1 if hit else 0

    had_field = "global_guardrail" in sb
    sb.pop("global_guardrail", None)
    # Negative prompts are INERT on this stack: the image and video passes both
    # run at cfg 1.0, where ComfyUI skips the negative conditioning entirely.
    # They enumerate the same policy terms, once per scene, and do nothing.
    # build_refs/build_song already default the field to "" when absent.
    had_field = sb.pop("global_negative_prompt", None) is not None or had_field
    for scene in scenes:
        if scene.pop("negative_prompt", None) is not None:
            touched += 1 if not scene.get("_np_counted") else 0
    saved = before - len(json.dumps(sb))
    return (had_field or touched > 0), had_field, touched, saved, sb, shared


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patterns", nargs="*", help="glob(s) of storyboard .json files")
    ap.add_argument("--all", action="store_true",
                    help="every *.json under the repo, excluding studio/ and workflows")
    ap.add_argument("--apply", action="store_true", help="rewrite files (default: dry run)")
    args = ap.parse_args()

    repo = os.path.dirname(os.path.abspath(__file__))
    paths = []
    if args.all:
        paths = [p for p in glob.glob(os.path.join(repo, "**", "*.json"), recursive=True)
                 if "/studio/" not in p and "/profiles/" not in p and "/.git/" not in p]
    for pat in args.patterns:
        paths += glob.glob(pat, recursive=True)
    paths = sorted(set(paths))
    if not paths:
        ap.error("no files matched")

    changed = md_written = total_scenes = total_saved = 0
    for p in paths:
        ok, had_field, scenes, saved, sb, shared_for_md = clean_file(p)
        if not ok:
            continue
        changed += 1
        total_scenes += scenes
        total_saved += saved
        print(f"  {'rewrite' if args.apply else 'would clean'} {os.path.relpath(p, repo)}"
              f"  [{'field+' if had_field else ''}{scenes} scenes, -{saved} chars]")
        if not args.apply:
            continue
        with open(p, "w") as f:
            json.dump(sb, f, indent=1)
        md = p[:-5] + ".md"
        if os.path.exists(md) and clean_md(md, shared_for_md):
            md_written += 1

    print(f"\n{changed} of {len(paths)} files carried guardrail text "
          f"({total_scenes} scenes, {total_saved // 1024} KB)")
    if args.apply:
        print(f"rewrote {changed} json, {md_written} md")
    else:
        print("dry run -- re-run with --apply to rewrite")


if __name__ == "__main__":
    main()
