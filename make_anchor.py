#!/usr/bin/env python3
"""Compose a character anchor sheet from one or more reference images.

REFERENCES ARE AN UNORDERED SET. This used to demand exactly one face image and
exactly one outfit image, in that order, and worded the prompt as "from the
first image" / "of the second image". That made a single photograph carrying
both -- the common case -- unusable, and three references impossible. Now any
number are attached, the prompt describes what to take from them collectively,
and with more than one COMPOSITE tells the model they are ONE character rather
than several to line up side by side.

Qwen-Image-Edit 2511 takes up to three images as conditioning references, so
this is the same workflow build_refs.py already emits -- only the prompt
changes. Emits N seeds because composition is seed-dominated
(continuation finding 8); pick the best off the contact sheet.

Anchors must come out as neutral character sheets on plain grey. A wardrobe
reference is usually a lit scene shot, so the prompt rejects its background,
pose and palette explicitly -- negatives are inert at cfg 1.0 (finding 5).

WHO the character is comes from a profile (`--profile profiles/<album>.json`,
key "anchor": identity / wardrobe / body / views). This file holds only the
neutral character-sheet craft, so a second project needs a profile, not a fork.
Without a profile the wording is generic and the source IMAGES carry the
identity on their own.

usage:
  make_anchor.py --images face.png,wardrobe.jpg --outdir /tmp/wf_anchor \
                 --profile profiles/street_cats.json
"""
import argparse
import random, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_refs import workflow  # noqa: E402

# Neutral fallbacks. These describe HOW a character sheet is framed, which is
# the same for any project; nothing here names a character, a species or an
# album. Anything that does belongs in the profile.
#
# NOT slot-specific. These used to say "from the first image" and "of the second
# image", which forced the caller to supply exactly one face and exactly one
# outfit in that order. References are now an unordered SET -- one image may
# carry both, or five may carry parts of each -- so the wording describes what
# to take from them collectively and lets the model compose.
DEFAULT_IDENTITY = (
    "Her head, face and hair are those of the character in the reference images; keep that "
    "identity exactly."
)
DEFAULT_WARDROBE = (
    "She wears the outfit and accessories shown in the reference images, same hardware and "
    "materials."
)
# Prepended when more than one reference is attached, so the model is told they
# describe ONE character rather than several to place side by side -- the
# failure mode of an unlabelled multi-image reference is a group shot.
COMPOSITE = (
    "All of the reference images show the SAME single character from different angles or in "
    "different outfits. Combine them into one coherent character; do not place several "
    "figures in the frame."
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
    # Nude variants. A tier that permits nudity still needs the character's body
    # to stay the SAME body -- without a nude reference the image model invents
    # one below the neckline, which is the pale-limbs failure in a new place.
    # Only generated for a tier whose allow_nudity is set; the studio gates it.
    "front_nude": (
        "FRONT VIEW nude character reference sheet of a single adult character, standing "
        "upright facing the camera straight on, arms relaxed at their sides, feet apart, head "
        "to toe fully in frame. "),
    "back_nude": (
        "BACK VIEW nude character reference sheet of a single adult character, seen from "
        "directly behind, back to the camera, standing upright, arms relaxed at their sides, "
        "feet apart, head to toe fully in frame. Rear view, seen from behind, face not "
        "visible. "),
}

# Replaces the wardrobe clause on a nude view. Positive wording throughout --
# negatives are inert at cfg 1.0, so "no clothing" would do nothing; what works
# is describing bare skin as the thing that is there. The wardrobe IMAGE is
# still attached because they carry build and proportion, so the prompt says
# which part of them to take and which to ignore.
NUDE_WARDROBE = (
    "She is fully nude: bare skin over the whole body, no garments, no underwear, no straps "
    "and no accessories. Take her build and proportions from the reference images but none "
    "of their clothing."
)

NUDE_VIEWS = ("front_nude", "back_nude")


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


def prompt_for(view, anchor=None, n_refs=1):
    a = anchor or load_anchor(None)
    # On a nude view the album's wardrobe wording is the one thing that must NOT
    # be used -- it describes the outfit, and including it produces a clothed
    # sheet however the view is worded. The BODY clause stays: colouring per
    # body part is exactly as load-bearing here as anywhere else.
    wardrobe = NUDE_WARDROBE if view in NUDE_VIEWS else a["wardrobe"]
    parts = [a["views"][view], wardrobe, a["body"], a["identity"]]
    if n_refs > 1:
        # several unlabelled references are read as several PEOPLE unless the
        # prompt says otherwise
        parts.insert(1, COMPOSITE)
    parts.append(BACKDROP)
    return " ".join(p.strip() for p in parts if p and p.strip())


def main():
    ap = argparse.ArgumentParser()
    # An unordered SET of references, comma separated, as named in ComfyUI/input.
    # Not face-then-outfit: one image often carries both, and forcing the caller
    # to split them made a perfectly good single reference unusable. Qwen takes
    # three, so anything past the third is dropped by the caller with a warning.
    # Empty is valid and means text-to-image -- every image input on
    # TextEncodeQwenImageEditPlus is optional (see build_refs.workflow), which is
    # what album artwork with no reference uses.
    ap.add_argument("--images", default="", help="comma-separated reference images, "
                                                  "as named in ComfyUI/input")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--width", type=int, default=896)
    ap.add_argument("--height", type=int, default=1216)
    ap.add_argument("--view", choices=list(DEFAULT_VIEWS), default="front")
    ap.add_argument("--prefix", default="anchor_v2")
    ap.add_argument("--seed", type=int, default=None,
                    help="base seed. Omitted means a RANDOM base, which is what makes "
                         "re-rolling produce different candidates -- pass one only to "
                         "reproduce a specific sheet.")
    ap.add_argument("--profile", help="album profile json; its \"anchor\" block "
                                      "supplies identity/wardrobe/body/views")
    ap.add_argument("--prompt", default="", help="use this prompt verbatim instead of the "
                                                  "one composed from the profile and view")
    ap.add_argument("--guardrail", default="", help="tier wording. The pinned clause is "
                                                    "appended regardless; this adds the tier's "
                                                    "own, which an anchor never used to get.")
    args = ap.parse_args()

    images = [x.strip() for x in args.images.split(",") if x.strip()]
    scene = {"image_prompt": args.prompt.strip() or prompt_for(
                 args.view, load_anchor(args.profile), len(images)),
             "negative_prompt": ""}
    os.makedirs(args.outdir, exist_ok=True)
    # A RANDOM base unless one is pinned. This was `4200 + k * 137`, a fixed
    # sequence, so every anchor job this studio has ever run used the same six
    # seeds. Two consequences, both reported as bugs:
    #
    #   - "there is not much variation" -- same seeds and same prompt produce
    #     the same images, so re-rolling a sheet could not give you anything new,
    #     however many times you pressed it.
    #   - eleven jobs wrote six files. An identical workflow is a cache hit in
    #     ComfyUI: it returns the cached node output and never re-runs SaveImage,
    #     while /history still reports success. The job looks done and no image
    #     appears.
    #
    # The filename carries the seed, so a random base also stops separate runs
    # colliding in the shared output directory.
    base = args.seed if args.seed is not None else random.randrange(1, 2**31 - 1)
    for k in range(args.n):
        seed = base + k * 137
        # shot "" so no framing directive is prepended over the character-sheet
        # instruction; the anchor prompt is self-contained.
        # The guardrail is attached by workflow() -> guardrail.build_prompt, the
        # same chokepoint every other prompt goes through. It used to be called
        # with guard="" here, so an anchor got PINNED but never its TIER's
        # wording -- which is what a nude anchor needs to be permitted at all.
        # slot 1 is the identity lock, slot 2 the composition plate, slot 3 spare
        # -- build_refs.workflow owns that assignment, so the list is simply
        # handed over in order
        wf = workflow(scene, images[0] if images else "",
                      images[1] if len(images) > 1 else None, "empty",
                      args.width, args.height, seed, "", args.guardrail,
                      extra_refs=[(f"reference {i + 3}", img, "")
                                  for i, img in enumerate(images[2:])])
        wf["18"] = {"class_type": "SaveImage", "inputs": {
            "images": ["17", 0],
            "filename_prefix": f"{args.prefix}/{args.view}_s{seed}"}}
        json.dump(wf, open(f"{args.outdir}/{args.view}_{k:02d}_s{seed}.json", "w"))
    print(f"{args.n} {args.view} anchor candidates -> {args.outdir} "
          f"({args.width}x{args.height}, ~{args.n * 15}s to render)")


if __name__ == "__main__":
    main()
