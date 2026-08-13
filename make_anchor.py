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
import build_refs  # noqa: E402
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
    "different outfits. Combine them into one coherent character: exactly one figure, alone "
    "in the frame, standing by herself."
)
DEFAULT_BODY = (
    "Her entire body from shoulders to feet carries the same colouring and texture as her "
    "face, uniform in shade on shoulders, upper arms, forearms, hands, torso, hips, thighs, "
    "calves and feet, every part the same single tone."
)
# POSITIVE ONLY, and that is the whole point of the rewrite.
#
# This clause used to read "...and no scenery: no alley, no wall, no brickwork,
# no neon, no purple or magenta lighting, no smoke, no wet ground". Every sheet
# this studio ever rendered came back with smoke drifting around the edges and a
# wet-looking haze across the bottom, and the reason was those two phrases: a
# diffusion model does not process negation in the positive prompt, so "no
# smoke" is an instruction to draw smoke and "no wet ground" is an instruction
# to draw a wet floor. Reported as "why are all the images cloudy around the
# edges and bottom" -- the cloud was the prompt.
#
# Absences belong in the NEGATIVE prompt, which is where they have been moved.
# That works only above cfg 1.0, which is a further reason quality mode is the
# default: in fast mode ComfyUI skips the negative pass and there is nowhere for
# an absence to live at all.
BACKDROP = (
    "The background is one flat sheet of neutral mid-grey, evenly lit and completely empty, "
    "with the floor the same unbroken grey as the wall behind her and a soft contact shadow "
    "under her feet. She stands upright and unsupported in an empty studio, clear of the "
    "edges of the frame. Even neutral studio lighting, white balanced, daylight colour "
    "temperature, the same light on both sides of her. Clean neutral studio character "
    "sheet, crisp air, sharp focus, high detail, full body head to toe inside the frame."
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

# The nude swap, and the one clause in this file that has to be overridable per
# character.
#
# "bare skin over the whole body" is WRONG for a furred, scaled or otherwise
# non-human character, and it is wrong in a way that fights the body clause
# rather than being merely unhelpful. On Street Cats the two arrived in one
# prompt as "bare skin over the whole body" beside "her entire body is covered
# in the same sleek jet-black fur, uniformly" -- directly contradictory, and a
# fixed-seed CFG sweep on 2026-08-12 measured exactly what that produces: at
# cfg 1.0 the longer fur clause partly wins, and as guidance rises the model
# follows "bare skin" harder until two of three seeds render a human body with
# a cat's head. No cfg value satisfies both clauses, which is why the sweep
# found no good answer and why the fix is here rather than in the sampler.
#
# A profile can replace it outright.
#
# It must ASSERT nudity, positively, and name no garment at all.
#
# The first attempt at fixing the bare-skin contradiction replaced it with a
# list of negations -- "no garments, no underwear, no straps, no accessories" --
# and measured worse: on a fixed seed at cfg 1.0 and 2.0 the sheet came back
# WEARING a leather harness, trousers and boots, where the old wording had at
# least produced a nude body. The reason is the rule this project already
# states in its own wardrobe field: say what is WORN, never what is absent.
# A diffusion model does not process negation in the positive prompt, so naming
# garments there makes them MORE likely to appear, and "her fur is her only
# covering" contributed a clothing word on top.
#
# So: every clause here is a positive statement about a bare body, the word for
# the surface comes from the BODY clause rather than from here, and no garment
# is mentioned even to forbid it. The negative prompt is where absent things
# belong -- and it only applies above cfg 1.0, which is its own reason to keep
# quality mode the default.
NUDE_WARDROBE = (
    "She is completely nude, undressed and bare, her whole body uncovered and fully exposed "
    "from shoulders to feet, with her natural body surface continuing unbroken over her "
    "chest, stomach, hips, thighs and legs exactly as the body description states. Take her "
    "build and proportions from the reference images, and her surface from the body "
    "description."
)

# What a nude sheet is asked to DEPICT, as opposed to what it is asked to omit.
# Empty by default and supplied per profile, because it is the one clause whose
# right wording is a decision about the work rather than about the craft.
#
# Nothing in this pipeline filters adult anatomical language: guardrail.py's
# MINOR_TERMS refuses references to MINORS and nothing else, and a tier that
# permits explicit content says so in its own wording. But permitting is not
# requesting -- NUDE_WARDROBE above only ever said what was ABSENT, so a nude
# sheet came back anatomically featureless. That is the model's prior filling a
# gap in the prompt, not a filter, and the gap is this field.
DEFAULT_ANATOMY = ""

def is_nude_view(view):
    """Whether this view drops the wardrobe wording. DERIVED, not enumerated.

    A view is nude because of what it IS. It used to be a literal tuple here
    and a second literal set in studio/app.py -- two hand-kept copies of one
    fact, so adding a nude view to one and not the other rendered it at `g`
    WITH the album's wardrobe wording and never skipped it in anchor_plan: a
    tier violation produced by an omission. docs/TRD-7 T7-1 and T7-2.
    """
    return str(view or "").endswith("_nude")


# Kept as a name because callers read it, but DERIVED from the view table so it
# cannot fall out of step with it.
NUDE_VIEWS = tuple(v for v in DEFAULT_VIEWS if is_nude_view(v))


# Every constant in this file that becomes part of a POSITIVE prompt. The one
# defect this file keeps producing is negation in the positive: "no smoke" drew
# smoke on every sheet for the life of the project, and a nude clause built from
# "no garments, no underwear, no straps" put a leather harness on a nude sheet.
# A diffusion model has no NOT. Absences belong in the negative prompt, which is
# applied only above cfg 1.0 -- so a negation written here does not merely fail,
# it actively instructs.
POSITIVE_CONSTANTS = ("COMPOSITE", "DEFAULT_IDENTITY", "DEFAULT_WARDROBE", "DEFAULT_BODY",
                     "BACKDROP", "NUDE_WARDROBE")

# Phrases that read as "draw this" however they are meant. Checked by demo().
_NEGATION_PATTERNS = (r"\bno\s+\w", r"\bnot\s+\w", r"\bwithout\s+\w",
                     r"\bnever\s+\w", r"\bfree\s+of\b", r"\bavoid\b")

# NO EXCEPTIONS. This was ("DEFAULT_BODY",), on the argument that a denied
# PROPERTY of a subject already in frame cannot summon an object the way "no
# alley" summons an alley -- so "no lighter or differently-toned patches" was
# allowed to stand.
#
# The argument is defensible and the OUTPUT refuted it: lighter fur patches and
# two-tone limbs are exactly what that clause denied, at cfg 4.5 / 28 steps
# where the negative prompt is live. A reasoned exception losing to an
# observation is the observation winning. DEFAULT_BODY is a pure positive
# assertion now, and it NAMES THE PARTS -- "identical head to toe" is a summary
# a model can satisfy by averaging, and a list is not. docs/TRD-4 T4-10, T4-11.
_NEGATION_ALLOWED = ()


def load_anchor(profile_path):
    """The profile's "anchor" block, with neutral defaults for anything absent."""
    data = {}
    if profile_path:
        with open(profile_path) as f:
            data = (json.load(f) or {}).get("anchor") or {}
    return anchor_from(data)


def anchor_from(data):
    """Defaults filled in around a raw anchor dict, from wherever it came.

    Split out from load_anchor so a caller holding the fields already -- the
    studio composes them from the database -- gets the identical merge without
    writing a temp file. It matters most for `views`: a profile that defines
    only front and back must still answer for front_nude and back_nude, and a
    caller that overlaid its own partial dict on top of the result instead of
    going through here would raise a KeyError on the first nude sheet.
    """
    data = data or {}
    views = dict(DEFAULT_VIEWS)
    views.update({k: v for k, v in (data.get("views") or {}).items() if v})
    return {
        "identity": data.get("identity") or DEFAULT_IDENTITY,
        "wardrobe": data.get("wardrobe") or DEFAULT_WARDROBE,
        "body": data.get("body") or DEFAULT_BODY,
        # The nude swap, per character. A furred or scaled subject needs its own
        # wording here or the default fights its body clause -- see NUDE_WARDROBE.
        "nude_wardrobe": data.get("nude_wardrobe") or NUDE_WARDROBE,
        # What a nude sheet DEPICTS. Empty unless the profile says otherwise.
        "anatomy": data.get("anatomy") or DEFAULT_ANATOMY,
        "views": views,
    }


def prompt_for(view, anchor=None, n_refs=1):
    a = anchor or load_anchor(None)
    # On a nude view the album's wardrobe wording is the one thing that must NOT
    # be used -- it describes the outfit, and including it produces a clothed
    # sheet however the view is worded. The BODY clause stays: colouring per
    # body part is exactly as load-bearing here as anywhere else.
    nude = view in NUDE_VIEWS
    wardrobe = a.get("nude_wardrobe", NUDE_WARDROBE) if nude else a["wardrobe"]
    parts = [a["views"][view], wardrobe, a["body"], a["identity"]]
    # The anatomy clause applies to nude views only, and goes AFTER the body
    # clause so it reads as detail on the surface the body clause just
    # established rather than as a competing description of it.
    if nude and a.get("anatomy"):
        parts.insert(3, a["anatomy"])
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
    ap.add_argument("--mode", choices=("fast", "quality"), default="fast",
                    help="fast = the Lightning 4-step LoRA at cfg 1.0, where a NEGATIVE "
                         "PROMPT IS INERT. quality = LoRA off, more steps, cfg > 1, where "
                         "the negative actually applies -- the direct lever against colour "
                         "drift, at roughly a minute a sheet instead of fifteen seconds.")
    ap.add_argument("--negative", default="", help="negative prompt. Silently dropped in "
                                                    "fast mode, because ComfyUI does not "
                                                    "apply it at cfg 1.0 -- see --mode.")
    ap.add_argument("--ref-method", dest="ref_method", default=None,
                    choices=list(build_refs.REF_METHODS),
                    help="how references are folded into the latent. THE reference-adherence "
                         "knob for this architecture; there is no IP-Adapter to weight.")
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--cfg", type=float, default=None)
    ap.add_argument("--sampler", dest="sampler_name", default=None,
                    choices=list(build_refs.SAMPLERS))
    ap.add_argument("--scheduler", default=None, choices=list(build_refs.SCHEDULERS))
    ap.add_argument("--denoise", type=float, default=None)
    ap.add_argument("--lora-strength", dest="lora_strength", type=float, default=None,
                    help="Lightning LoRA weight. Above 0 with cfg > 1 is mush; the modes "
                         "set it for you.")
    args = ap.parse_args()

    settings = build_refs.sampler_settings(
        args.mode, steps=args.steps, cfg=args.cfg, sampler_name=args.sampler_name,
        scheduler=args.scheduler, denoise=args.denoise, lora_strength=args.lora_strength)

    images = [x.strip() for x in args.images.split(",") if x.strip()]
    scene = {"image_prompt": args.prompt.strip() or prompt_for(
                 args.view, load_anchor(args.profile), len(images)),
             "negative_prompt": args.negative.strip()}
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
                      # name=None: these are more photographs of the SAME
                      # character, not cast members. They used to be auto-named
                      # "reference 3", which build_refs.cast_clause turned into
                      # "The character in image 3 is reference 3." -- a second
                      # person asserted into a prompt whose composite clause
                      # says all the references show one. docs/TRD-7 T7-10.
                      extra_refs=[(None, img, "")
                                  for img in images[2:]],
                      settings=settings, ref_method=args.ref_method)
        wf["18"] = {"class_type": "SaveImage", "inputs": {
            "images": ["17", 0],
            "filename_prefix": f"{args.prefix}/{args.view}_s{seed}"}}
        json.dump(wf, open(f"{args.outdir}/{args.view}_{k:02d}_s{seed}.json", "w"))
    per = 15 if settings["lora_strength"] else 60
    note = "" if build_refs.negative_applies(settings) else \
        " -- negative prompt INERT at cfg 1.0, use --mode quality for it to apply"
    print(f"{args.n} {args.view} anchor candidates -> {args.outdir} "
          f"({args.width}x{args.height}, {args.mode} mode: {settings['steps']} steps "
          f"cfg {settings['cfg']}, ~{args.n * per}s to render){note}")


if __name__ == "__main__":
    main()
