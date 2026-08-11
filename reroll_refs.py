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
from build_song import clip_plan, normalize, CHUNK
from build_refs import workflow, scene_cast

SEED_OFFSETS = [8000, 9000, 10000, 11000]  # 4 alternates, distinct from base 7000+i

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
    ap.add_argument("--note", default="", help="what to change about this clip, appended to "
                                                "its prompt only -- turns a blind re-roll into "
                                                "a correction")
    args = ap.parse_args()

    # normalize() like build_refs/build_song: strips any guardrail baked into
    # legacy scene text and maps the older storyboard schemas
    sb = normalize(json.load(open(args.storyboard)))
    scenes = sb["scenes"]
    world = sb.get("album_world_reference") or sb.get("world_reference", "")
    character = sb.get("character_reference", "")
    cast = json.load(open(args.cast)) if args.cast else {}
    # same mapping build_refs used -- shared, not re-derived, so a re-roll of
    # clip N can never target a different scene than the one you rejected
    clip_scene = {ci: (scene, shot) for ci, scene, shot in clip_plan(scenes, args.audio)}

    want = [int(x) for x in args.clips.split(",")]
    os.makedirs(args.outdir, exist_ok=True)
    made = 0
    for ci in want:
        scene, shot = clip_scene[ci]
        if args.note:
            # a COPY: the note applies to this clip's re-roll, and the scene
            # object is shared with every other clip allocated to that scene
            scene = dict(scene)
            scene["image_prompt"] = f"{scene.get('image_prompt', '')} {args.note}".strip()
        for off in SEED_OFFSETS:
            seed = off + ci
            wf = workflow(scene, args.anchor, None, "empty",
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
          f"({len(want)} clips x {len(SEED_OFFSETS)} seeds) to {args.outdir}")

if __name__ == "__main__":
    main()
