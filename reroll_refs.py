#!/usr/bin/env python3
"""Best-of-N re-roll for specific reference-image clips (finding 8: seed variance,
not setting tuning). Rebuilds the exact scene+shot for each target clip index
and emits N workflows with distinct seeds, so we can pick the best composition.

Output prefix: reroll_<slug>/clip_<iii>_s<seed>  (separate from the
committed refs_<slug>/ set, so nothing is overwritten until a pick).

usage:
  reroll_refs.py --storyboard rear_entrance_clean.json \
      --slug rear_entrance --audio "Rear Entrance.mp3" \
      --anchor meow_p_anchor_clean.png --clips 0,4,17,20,27,32,33,37,40 \
      --outdir reroll/re_clean
"""
import argparse, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_song import clip_plan, clip_chain_plan, normalize, CHUNK, shot_directive
from build_refs import workflow, scene_cast

SEED_OFFSETS = [8000, 9000, 10000, 11000]  # default when no range is given


def seed_plan(n, lo, hi, mode="equal"):
    """n seeds in [lo, hi], inclusive. equal = even gaps; fib = growing gaps."""
    n, lo, hi = int(n), int(lo), int(hi)
    if n < 1:
        raise ValueError("need at least one image")
    if hi < lo:
        raise ValueError("seed max must be >= seed min")
    if n > (hi - lo + 1):
        raise ValueError(f"{n} seeds cannot fit in {lo}..{hi}")
    if n == 1:
        return [lo]
    if mode == "fib":
        steps = []
        a, b = 1, 1
        for _ in range(n - 1):
            steps.append(a)
            a, b = b, a + b
        span = hi - lo
        total = sum(steps)
        out = [lo]
        acc = 0
        for i, s in enumerate(steps):
            acc += s
            out.append(hi if i == len(steps) - 1 else lo + round(span * acc / total))
    else:
        out = [lo + round(i * (hi - lo) / (n - 1)) for i in range(n)]
    # rounding can collide; walk forward into free values inside the range
    seen = set()
    fixed = []
    nxt = lo
    for s in out:
        s = max(lo, min(hi, int(s)))
        if s in seen:
            s = nxt
            while s in seen and s <= hi:
                s += 1
            if s > hi:
                raise ValueError(f"{n} unique seeds cannot fit in {lo}..{hi}")
        seen.add(s)
        fixed.append(s)
        nxt = s + 1
    return fixed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--anchor", required=True)
    ap.add_argument("--clips", required=True, help="comma-separated clip indices")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    # These four were MISSING, and their absence was silent. A re-rolled frame
    # was built with guard="", body="", character="", world="" -- so it lost the
    # tier's wording, the album's body-consistency wording (the fix for pale
    # limbs and mismatched glutes), the anti-duplicate clause, and the world
    # lock. Every re-roll therefore came back subtly different from the frame it
    # replaced, in exactly the way the re-roll was meant to fix.
    ap.add_argument("--guardrail", default="", help="tier wording; the pinned clause is "
                                                    "appended regardless")
    ap.add_argument("--body", default="", help="album body-consistency wording, per body part")
    ap.add_argument("--cast", help="json file: {name: {image, desc}} of anchored characters")
    ap.add_argument("--bases", help="json {scene_number: comfy_filename} pose plates")
    ap.add_argument("--note", default="", help="what to change about this clip, appended to "
                                                "its prompt only -- turns a blind re-roll into "
                                                "a correction")
    ap.add_argument("--n", type=int, default=0, help="how many stills; 0 = the four offsets")
    ap.add_argument("--seed-min", type=int, default=8000)
    ap.add_argument("--seed-max", type=int, default=11000)
    ap.add_argument("--step", choices=("equal", "fib"), default="equal")
    args = ap.parse_args()

    # normalize() like build_refs/build_song: strips any guardrail baked into
    # legacy scene text and maps the older storyboard schemas
    sb = normalize(json.load(open(args.storyboard)))
    scenes = sb["scenes"]
    world = sb.get("album_world_reference") or sb.get("world_reference", "")
    character = sb.get("character_reference", "")
    cast = json.load(open(args.cast)) if args.cast else {}
    per_scene_base = {}
    if args.bases:
        per_scene_base = {int(k): v for k, v in json.load(open(args.bases)).items() if v}
    # same mapping build_refs used -- shared, not re-derived, so a re-roll of
    # clip N can never target a different scene than the one you rejected
    clip_scene = {}
    for rec in clip_chain_plan(scenes):
        sn = rec.get("scene_number")
        scene = next(s for s in scenes if s.get("scene_number") == sn)
        clip_scene[rec["clip_idx"]] = (scene, shot_directive(scene, rec["clip_idx"]))
    if not clip_scene:
        clip_scene = {ci: (scene, shot) for ci, scene, shot in clip_plan(scenes, args.audio)}

    want = [int(x) for x in args.clips.split(",")]
    if args.n:
        seeds = seed_plan(args.n, args.seed_min, args.seed_max, args.step)
    else:
        seeds = list(SEED_OFFSETS)
    os.makedirs(args.outdir, exist_ok=True)
    made = 0
    for ci in want:
        scene, shot = clip_scene[ci]
        if args.note:
            # a COPY: the note applies to this clip's re-roll, and the scene
            # object is shared with every other clip allocated to that scene
            scene = dict(scene)
            scene["image_prompt"] = f"{scene.get('image_prompt', '')} {args.note}".strip()
        for seed in seeds:
            if not args.n:
                seed = seed + ci
            plate = per_scene_base.get(int(scene.get("scene_number") or 0))
            wf = workflow(scene, args.anchor, plate, "empty",
                          args.width, args.height, seed, shot,
                          args.guardrail, world, character, args.body,
                          extra_refs=scene_cast(scene, cast))
            wf["18"] = {"class_type": "SaveImage", "inputs": {
                "images": ["17", 0],
                "filename_prefix": f"reroll_{args.slug}/clip_{ci:03d}_s{seed}"}}
            with open(f"{args.outdir}/clip_{ci:03d}_s{seed}.json", "w") as f:
                json.dump(wf, f)
            made += 1
    print(f"{args.slug} wrote {made} re-roll workflows "
          f"({len(want)} clips x {len(seeds)} seeds) to {args.outdir}")

if __name__ == "__main__":
    main()
