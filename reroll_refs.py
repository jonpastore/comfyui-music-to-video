#!/usr/bin/env python3
"""Best-of-N re-roll for specific reference-image clips (finding 8: seed variance,
not setting tuning). Rebuilds the exact scene+shot for each target clip index
and emits N workflows with distinct seeds, so we can pick the best composition.

Output prefix: reroll_<slug>_<version>/clip_<iii>_s<seed>  (separate from the
committed refs_<slug>_<version>/ set, so nothing is overwritten until a pick).

usage:
  reroll_refs.py --storyboard rear_entrance_clean.json --version clean \
      --slug rear_entrance --audio "Rear Entrance.mp3" \
      --anchor meow_p_anchor_clean.png --clips 0,4,17,20,27,32,33,37,40 \
      --outdir reroll/re_clean
"""
import argparse, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_song import clip_plan, CHUNK
from build_refs import workflow

SEED_OFFSETS = [8000, 9000, 10000, 11000]  # 4 alternates, distinct from base 7000+i

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--version", required=True, choices=["clean", "explicit"])
    ap.add_argument("--slug", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--anchor", required=True)
    ap.add_argument("--clips", required=True, help="comma-separated clip indices")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    sb = json.load(open(args.storyboard))
    scenes = sb["scenes"]
    # same mapping build_refs used -- shared, not re-derived, so a re-roll of
    # clip N can never target a different scene than the one you rejected
    clip_scene = {ci: (scene, shot) for ci, scene, shot in clip_plan(scenes, args.audio)}

    want = [int(x) for x in args.clips.split(",")]
    os.makedirs(args.outdir, exist_ok=True)
    made = 0
    for ci in want:
        scene, shot = clip_scene[ci]
        for off in SEED_OFFSETS:
            seed = off + ci
            wf = workflow(scene, args.anchor, None, "empty",
                          args.width, args.height, seed, args.version, shot)
            wf["18"] = {"class_type": "SaveImage", "inputs": {
                "images": ["17", 0],
                "filename_prefix": f"reroll_{args.slug}_{args.version}/clip_{ci:03d}_s{seed}"}}
            with open(f"{args.outdir}/clip_{ci:03d}_s{seed}.json", "w") as f:
                json.dump(wf, f)
            made += 1
    print(f"{args.slug} [{args.version}] wrote {made} re-roll workflows "
          f"({len(want)} clips x {len(SEED_OFFSETS)} seeds) to {args.outdir}")

if __name__ == "__main__":
    main()
