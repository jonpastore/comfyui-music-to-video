#!/usr/bin/env python3
"""Compose a new Meow P anchor: face+hair from one image, outfit+body from another.

Qwen-Image-Edit 2511 takes both as conditioning references (image1 = identity,
image2 = wardrobe), so this is the same workflow build_refs.py already emits --
only the prompt changes. Emits N seeds because composition is seed-dominated
(continuation finding 8); pick the best off the contact sheet.

Anchors must come out as neutral character sheets on plain grey. The wardrobe
reference is a lit alley shot, so the prompt rejects its background, pose and
palette explicitly -- negatives are inert at cfg 1.0 (finding 5).

usage:
  make_anchor.py --face meow_p_anchor_explicit.png \
                 --outfit meow_p_grok_reference.jpg --outdir /tmp/wf_anchor
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_refs import workflow  # noqa: E402

# Two failures drove this wording:
#  1. The identity source wears full-length pants and wins any implicit
#     argument, so the shorts have to be stated before identity and forced
#     positively -- negatives are inert at cfg 1.0 (finding 5).
#  2. Every seed that produced real shorts rendered the exposed legs as tan
#     HUMAN skin. Fur colour has to be re-asserted per body part; one mention
#     of "black-furred" at the top does not hold below the waist.
FUR = (
    "Her entire body is covered in the same sleek jet-black fur as her face, uniformly: "
    "black-furred shoulders, black-furred arms, black-furred torso and stomach, black-furred "
    "hips, black-furred glutes, black-furred thighs, black-furred knees and calves. Every "
    "exposed part of her is black fur of exactly the same shade and texture as her face. "
    "She has no human skin anywhere: no tan skin, no brown skin, no beige skin, no pale skin, "
    "no lighter skin tone on the legs or body. Fur colour is identical head to toe."
)

WARDROBE = (
    "She is wearing a minimal black leather bikini outfit, exactly the hardware style of the "
    "second image but far briefer: a small black leather bikini top, a brief bra-cut triangle "
    "top with thin straps and small gold rings, covering only the bust. "
    "On her hips she wears high-cut black leather bikini bottoms, cut high over the hip bone "
    "like a swimsuit brief, the leg openings cut high and narrow so her glutes and the full "
    "length of her thighs and hips are uncovered black fur. Not shorts, not boy shorts, not "
    "a full-coverage brief: high-cut bikini bottoms only. "
    "Accessories from the second image: a wide black studded belt with a large gold buckle "
    "sitting low on the hips, heavy draped gold chain swags across the chest and hips, a gold "
    "chain choker, buckled leather straps fastened around one bare black-furred thigh, gold "
    "hoop earrings, black platform lace-up knee-high boots reaching just below the knee, "
    "gold-toned hardware throughout, athletic muscular build."
)

IDENTITY = (
    "Her head, face and hair come from the first image: sleek black feline face, yellow-green "
    "almond eyes, feline ears, long wavy black hair with subtle purple highlights, long black tail."
)

BACKDROP = (
    "The background is a plain flat neutral grey studio backdrop with soft even lighting and no "
    "scenery: no alley, no wall, no brickwork, no neon, no purple or magenta lighting, no smoke, "
    "no wet ground, not leaning, not seated. Neutral studio character sheet, sharp focus, "
    "high detail, full body head to toe inside the frame."
)

VIEWS = {
    "front": (
        "FRONT VIEW character reference sheet of a single adult anthropomorphic black feline "
        "woman, standing upright facing the camera straight on, arms relaxed at her sides, feet "
        "apart, head to toe fully in frame. "),
    "back": (
        "BACK VIEW character reference sheet of a single adult anthropomorphic black feline "
        "woman, seen from directly behind, her back to the camera, standing upright, arms "
        "relaxed at her sides, feet apart, head to toe fully in frame. Her long black hair falls "
        "down her back, her long black tail hangs behind her, and the high-cut bikini bottoms "
        "leave her black-furred glutes and the backs of her thighs uncovered. Rear view, "
        "seen from behind, face not visible. "),
}


def prompt_for(view):
    return VIEWS[view] + WARDROBE + " " + FUR + " " + IDENTITY + " " + BACKDROP


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
    args = ap.parse_args()

    scene = {"image_prompt": prompt_for(args.view), "negative_prompt": ""}
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
