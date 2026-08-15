#!/usr/bin/env python3
"""Frame out a storyboard (json + md, clean + explicit) from a lyrics file.

Scene boundaries come from the lyric's own [Section] tags -- the structure is
already in the Suno lyrics, so nothing has to guess it. Scene *count* comes from
the mp3: enough scenes to cover the runtime at --scene-seconds each, split
across sections in proportion to how much lyric each section carries.

Everything album-specific (locations, palettes, camera vocabulary, outfits,
guardrails) lives in a profile json -- see profiles/street_cats.json. Locations
and palettes rotate per scene, which is what stops a whole song rendering as one
purple corridor.

The json is the source of truth: build_refs.py and build_song.py read it. Edit
the prompts there, then `--md-only` to refresh the readable sheet.

usage:
  build_storyboard.py --lyrics "Street Cats/Rear Entrance/lyrics.txt" \
      --audio "Street Cats/Rear Entrance/Rear Entrance.mp3" \
      --profile profiles/street_cats.json --title "Rear Entrance" --track 2 \
      --concept "A secret route around the back of the warehouse." \
      --outdir "Street Cats/Rear Entrance"

  build_storyboard.py --md-only "Street Cats/Rear Entrance/rear_entrance_clean.json"
"""
import argparse, json, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_song import allocate, audio_duration, CHUNK, n_clips_for  # noqa: E402

TAG = re.compile(r"^\s*\[(.+?)\]\s*$")

# checked in order, so a "[Instrumental groove]" lands on mid via "groove"
ENERGY = [
    (("drop", "chorus", "hook", "peak", "climax", "final"), "high"),
    (("build", "pre-", "pre ", "verse", "rap", "bridge", "groove", "chopped"), "mid"),
    (("intro", "outro", "break", "ambient", "pause", "instrumental", "fade", "tail"), "low"),
]


def energy(tag):
    t = tag.lower()
    for keys, e in ENERGY:
        if any(k in t for k in keys):
            return e
    return "mid"


def parse_sections(text):
    """[Tag] opens a section. Runs of tag-only sections (production notes like
    [Dry kick]/[Closed hats]) merge into one instrumental section."""
    secs = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = TAG.match(line)
        if m:
            secs.append({"tag": m.group(1).strip(), "lines": []})
        elif secs:
            secs[-1]["lines"].append(line)
        else:
            secs.append({"tag": "Opening", "lines": [line]})

    merged = []
    for s in secs:
        if not s["lines"] and merged and not merged[-1]["lines"]:
            continue  # fold into the instrumental run already open
        merged.append(s)
    return merged


def slug_of(title):
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def build_scenes(sections, profile, dur, target):
    """One or more scenes per section; count proportional to lyric weight."""
    weights = [len(s["lines"]) or 2 for s in sections]
    # reuse build_song's largest-remainder allocator (it reads a "N sec" string)
    counts = allocate([{"duration_guidance": f"{w} sec"} for w in weights], target)

    locs, pals = profile["locations"], profile["palettes"]
    char = profile["character_base"].replace("{outfit}", profile["outfit"])
    total_w = sum(weights)

    scenes, n = [], 0
    for sec, w, k in zip(sections, weights, counts):
        e = energy(sec["tag"])
        cams = profile["cameras"][e]
        sec_secs = dur * w / total_w
        each = sec_secs / k
        lo, hi = max(3, int(each * 0.8)), max(5, int(each * 1.25))

        for j in range(k):
            # locations and palettes advance on different cycles so a location
            # is not permanently welded to one colour
            loc = locs[n % len(locs)]
            pal = pals[(n * 3) % len(pals)]
            # rotate on the global scene index, not j: most sections yield one
            # scene, so j is always 0 and every section would open on cams[0]
            cam = cams[n % len(cams)]
            motion = profile["motion"][e]
            mood = profile["mood"][e]

            chunk = sec["lines"][j::k] if sec["lines"] else []
            lyric = " / ".join(chunk[:3])
            story = (f"{loc}. Lyric beat: \"{lyric}\"" if lyric
                     else f"{loc}. Instrumental passage: {sec['tag']}.")

            name = sec["tag"] if k == 1 else f"{sec['tag']} {j + 1}"
            n += 1
            scenes.append({
                "scene_number": n,
                "name": name,
                "cue": sec["tag"],
                "energy": e,
                "duration_guidance": f"{lo}-{hi} sec",
                "lyric": lyric,
                "location": loc,
                "palette": pal,
                "story": story,
                "camera": cam,
                "motion": motion,
                "lighting": pal,
                # No guardrail here: build_refs.py/build_song.py attach it when
                # they build the prompt, so it applies to every storyboard rather
                # than only the ones this script wrote. Keeping it out also stops
                # a 40-word clause being duplicated across 20-50 scenes.
                "image_prompt": (
                    f"{mood} {char}. {profile['world']}, {pal}. "
                    f"Scene: {story} Camera: {cam}. Motion context: {motion}. "
                    f"Lighting: {pal}. {profile['render_tail']}"),
                "video_motion_prompt": f"{motion}; {cam}",
            })
    return scenes


def to_md(sb):
    """Render a storyboard as markdown.

    Every field is read with .get(): this is a PRESENTATION function and the
    storyboards it is handed are not all ours. The `*_comfy.json` schema has no
    `energy`, `palette` or `storyboard_strategy`; a hand-edited file can be
    missing anything. Subscripting raised KeyError on all of those, which turned
    "regenerate the markdown" -- both `--md-only` and the studio's in-place scene
    edit -- into a 500 on exactly the third-party files this format is supposed
    to tolerate. A missing field renders blank; it does not take the file down.
    """
    strategy = sb.get("storyboard_strategy") or {}
    scenes = sb.get("scenes") or []
    L = [f"# {sb.get('album', '')} — Track {sb.get('track_number', 0)}: {sb.get('title', '')}",

         f"**Scenes: {len(scenes)}** — {strategy.get('note', '')}", "",
         "## Concept", "", sb.get("concept", ""), "",
         "## Character / world lock", "",
         f"**Character:** `{sb.get('character_reference', '')}`", "",
         f"**Album world:** `{sb.get('album_world_reference', '')}`", "",
         "_Content guardrail is applied in code by `build_refs.py` / "
         "`build_song.py` when the prompt is built (see `guardrail.py`). It is "
         "deliberately absent from this file, which may be third-party generated._", "",
         "## Scenes", ""]
    for s in scenes:
        # 'palette' and 'lighting' are the same field under two names across the
        # schemas this repo has accumulated; prefer whichever is populated.
        lighting = s.get("palette") or s.get("lighting") or ""
        L += [f"### Scene {s.get('scene_number', '?')} — {s.get('name', '')}  "
              f"({s.get('cue', '')}, {s.get('energy', '')})",
              "",
              f"- **Duration:** {s.get('duration_guidance', '')}",
              f"- **Lyric:** {s.get('lyric') or '_instrumental_'}",
              f"- **Location:** {s.get('location', '')}",
              f"- **Camera:** {s.get('camera', '')}",
              f"- **Lighting:** {lighting}",
              f"- **Motion:** {s.get('motion', '')}", "",
              "```text", s.get("image_prompt", ""), "```", ""]
    L += ["## Audio reference — lyrics", "", "```text", sb.get("audio_lyrics", ""), "```", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md-only", help="regenerate the .md beside an already-edited .json")
    ap.add_argument("--lyrics")
    ap.add_argument("--audio")
    ap.add_argument("--profile")
    ap.add_argument("--title")
    ap.add_argument("--track", type=int, default=0)
    ap.add_argument("--concept", default="")
    ap.add_argument("--slug")
    ap.add_argument("--outdir")
    ap.add_argument("--scene-seconds", type=float, default=8.0,
                    help="target seconds of runtime per scene (lower = more scenes)")
    args = ap.parse_args()

    if args.md_only:
        sb = json.load(open(args.md_only))
        out = args.md_only[:-5] + ".md"
        open(out, "w").write(to_md(sb))
        print(f"wrote {out} ({len(sb['scenes'])} scenes)")
        return

    for req in ("lyrics", "audio", "profile", "title", "outdir"):
        if not getattr(args, req):
            ap.error(f"--{req} is required unless --md-only")

    profile = json.load(open(args.profile))
    lyrics = open(args.lyrics).read()
    sections = parse_sections(lyrics)
    dur = audio_duration(args.audio)
    target = max(len(sections), math.ceil(dur / args.scene_seconds))
    slug = args.slug or slug_of(args.title)
    nclips = n_clips_for(dur)
    os.makedirs(args.outdir, exist_ok=True)

    scenes = build_scenes(sections, profile, dur, target)
    sb = {
        "project": profile.get("project", "Music Video Storyboard"),
        "album": profile["album"],
        "track_number": args.track,
        "title": args.title,
        
        "storyboard_strategy": {
            "scene_count": len(scenes),
            "coverage_model": "coverage-based; scenes are shot opportunities, not final clips",
            "note": (f"{dur:.0f}s track -> {nclips} clips of {CHUNK:.2f}s; "
                     f"build_refs.py --audio spreads them over these scenes"),
        },
        "concept": args.concept,
        "audio_lyrics": lyrics,
        "character_reference": profile["character_base"].replace(
            "{outfit}", profile["outfit"]),
        "album_world_reference": profile["world"],
        "scenes": scenes,
    }
    base = os.path.join(args.outdir, slug)
    json.dump(sb, open(base + ".json", "w"), indent=1)
    open(base + ".md", "w").write(to_md(sb))
    print(f"{base}.json / .md — {len(scenes)} scenes")

    print(f"{args.title}: {dur:.0f}s, {len(sections)} lyric sections -> "
          f"{target} scenes, {nclips} clips")


if __name__ == "__main__":
    main()
