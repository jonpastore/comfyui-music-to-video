#!/usr/bin/env python3
"""Compose a character anchor: face+hair from one image, outfit+body from another.

Qwen-Image-Edit 2511 takes both as conditioning references (image1 = identity,
image2 = wardrobe), so this is the same workflow build_refs.py already emits --
only the prompt changes. Emits N seeds because composition is seed-dominated
(continuation finding 8); pick the best off the contact sheet.

Anchors must come out as neutral character sheets on plain grey. A wardrobe
reference is usually a lit scene shot, so the prompt rejects its background,
pose and palette explicitly -- negatives are inert at cfg 1.0 (finding 5).

WHO the character is comes from a profile (`--profile profiles/<album>.json`,
key "anchor": identity / wardrobe / body / views). This file holds only the
neutral character-sheet craft, so a second project needs a profile, not a fork.
Without a profile the wording is generic and the two source IMAGES carry the
identity on their own.

usage:
  make_anchor.py --face face.png --outfit wardrobe.jpg --outdir /tmp/wf_anchor \
                 --profile profiles/street_cats.json
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_refs import workflow  # noqa: E402

# Neutral fallbacks. These describe HOW a character sheet is framed, which is
# the same for any project; nothing here names a character, a species or an
# album. Anything that does belongs in the profile.
DEFAULT_IDENTITY = (
    "Her head, face and hair come from the first image; keep that identity exactly."
)
DEFAULT_WARDROBE = (
    "She wears the outfit and accessories of the second image, same hardware and materials."
)
DEFAULT_BODY = (
    "Body colouring and texture are identical head to toe, matching the face: the same "
    "shade on shoulders, arms, torso, hips, thighs and calves, with no lighter or "
    "differently-toned patches anywhere."
)
BACKDROP = (
    "The background is a plain flat neutral grey studio backdrop with soft even lighting and no "
    "scenery: no alley, no wall, no brickwork, no neon, no purple or magenta lighting, no smoke, "
    "no wet ground, not leaning, not seated. Neutral studio character sheet, sharp focus, "
    "high detail, full body head to toe inside the frame."
)
DEFAULT_VIEWS = {
    "front": (
        "FRONT VIEW character reference sheet of a single adult character, standing upright "
        "facing the camera straight on, arms relaxed at their sides, feet apart, head to toe "
        "fully in frame. "),
    "back": (
        "BACK VIEW character reference sheet of a single adult character, seen from directly "
        "behind, back to the camera, standing upright, arms relaxed at their sides, feet apart, "
        "head to toe fully in frame. Rear view, seen from behind, face not visible. "),
}


def load_anchor(profile_path):
    """The profile's "anchor" block, with neutral defaults for anything absent."""
    data = {}
    if profile_path:
        with open(profile_path) as f:
            data = (json.load(f) or {}).get("anchor") or {}
    views = dict(DEFAULT_VIEWS)
    views.update({k: v for k, v in (data.get("views") or {}).items() if v})
    return {
        "identity": data.get("identity") or DEFAULT_IDENTITY,
        "wardrobe": data.get("wardrobe") or DEFAULT_WARDROBE,
        "body": data.get("body") or DEFAULT_BODY,
        "views": views,
    }


def prompt_for(view, anchor=None):
    a = anchor or load_anchor(None)
    return (a["views"][view] + a["wardrobe"] + " " + a["body"] + " "
            + a["identity"] + " " + BACKDROP)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--face", required=True, help="identity source, as named in ComfyUI/input")
    ap.add_argument("--outfit", required=True, help="wardrobe source, as named in ComfyUI/input")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--width", type=int, default=896)
    ap.add_argument("--height", type=int, default=1216)
    ap.add_argument("--view", choices=["front", "back"], default="front")
    ap.add_argument("--prefix", default="anchor_v2")
    ap.add_argument("--profile", help="album profile json; its \"anchor\" block "
                                      "supplies identity/wardrobe/body/views")
    args = ap.parse_args()

    scene = {"image_prompt": prompt_for(args.view, load_anchor(args.profile)),
             "negative_prompt": ""}
    os.makedirs(args.outdir, exist_ok=True)
    for k in range(args.n):
        seed = 4200 + k * 137
        # shot "" so no framing directive is prepended over the character-sheet
        # instruction; the anchor prompt is self-contained
        wf = workflow(scene, args.face, args.outfit, "empty",
                      args.width, args.height, seed, "")
        wf["18"] = {"class_type": "SaveImage", "inputs": {
            "images": ["17", 0],
            "filename_prefix": f"{args.prefix}/{args.view}_s{seed}"}}
        json.dump(wf, open(f"{args.outdir}/{args.view}_{k:02d}_s{seed}.json", "w"))
    print(f"{args.n} {args.view} anchor candidates -> {args.outdir} "
          f"({args.width}x{args.height}, ~{args.n * 15}s to render)")


if __name__ == "__main__":
    main()
