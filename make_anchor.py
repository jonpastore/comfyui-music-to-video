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
COMPOSITE_HEAD = (
    "All of the reference images show the SAME single character from different angles or in "
    "different outfits. Combine them into one coherent character: exactly one figure, alone "
    "in the frame, "
)
COMPOSITE_STANCE = "standing by herself."
COMPOSITE = COMPOSITE_HEAD + COMPOSITE_STANCE
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
# BACKDROP is studio + lighting + focus. Stance and crop live on the VIEW so a
# seated or portrait sheet does not argue with "stands upright" / "head to toe".
# Split into named parts that concatenate to the shipped sentence, so the four
# existing views omit nothing and compose byte-identical. docs/TRD-7 §9.1.
BACKDROP_PARTS = (
    ("studio",
     "The background is one flat sheet of neutral mid-grey, evenly lit and completely empty, "),
    ("floor",
     "with the floor the same unbroken grey as the wall behind her and a soft contact shadow "
     "under her feet. "),
    ("stance",
     "She stands upright and unsupported in an empty studio, clear of the "
     "edges of the frame. "),
    ("light",
     "Even neutral studio lighting, white balanced, daylight colour "
     "temperature, the same light on both sides of her. Clean neutral studio character "
     "sheet, crisp air, sharp focus, high detail, "),
    ("crop",
     "full body head to toe inside the frame."),
)
BACKDROP = "".join(p for _, p in BACKDROP_PARTS)

# ONE table. Adding a view is one entry: label (UI), framing (camera+pose+crop),
# pose (the replaceable stance clause inside framing), backdrop_omit (which
# BACKDROP_PARTS to drop). `pose` on the profile REPLACES that clause — it must
# not sit beside "standing upright, arms relaxed at their sides". docs/TRD-7
# T7-1, T7-16.
VIEWS = {
    "front": {
        "label": "front, clothed",
        "framing": (
            "FRONT VIEW character reference sheet of a single adult character, standing upright "
            "facing the camera straight on, arms relaxed at their sides, feet apart, head to toe "
            "fully in frame. "),
        "pose": "standing upright facing the camera straight on, arms relaxed at their sides, "
                "feet apart, ",
        "camera": "FRONT VIEW character reference sheet of a single adult character, ",
    },
    "back": {
        "label": "back, clothed",
        "framing": (
            "BACK VIEW character reference sheet of a single adult character, seen from directly "
            "behind, back to the camera, standing upright, arms relaxed at their sides, feet apart, "
            "head to toe fully in frame. Rear view, seen from behind, face not visible. "),
        "pose": "standing upright, arms relaxed at their sides, feet apart, ",
        "camera": "BACK VIEW character reference sheet of a single adult character, seen from "
                  "directly behind, back to the camera, ",
    },
    "front_nude": {
        "label": "front, nude",
        "framing": (
            "FRONT VIEW nude character reference sheet of a single adult character, standing "
            "upright facing the camera straight on, arms relaxed at their sides, feet apart, head "
            "to toe fully in frame. "),
        "pose": "standing upright facing the camera straight on, arms relaxed at their sides, "
                "feet apart, ",
        "camera": "FRONT VIEW nude character reference sheet of a single adult character, ",
    },
    "back_nude": {
        "label": "back, nude",
        "framing": (
            "BACK VIEW nude character reference sheet of a single adult character, seen from "
            "directly behind, back to the camera, standing upright, arms relaxed at their sides, "
            "feet apart, head to toe fully in frame. Rear view, seen from behind, face not "
            "visible. "),
        "pose": "standing upright, arms relaxed at their sides, feet apart, ",
        "camera": "BACK VIEW nude character reference sheet of a single adult character, seen from "
                  "directly behind, back to the camera, ",
    },
    "three_quarter": {
        "label": "three-quarter, clothed",
        "framing": (
            "THREE-QUARTER VIEW character reference sheet of a single adult character, "
            "body turned forty-five degrees, face toward the camera, standing, head to toe "
            "fully in frame. "),
        "pose": "standing, ",
        "camera": "THREE-QUARTER VIEW character reference sheet of a single adult character, "
                  "body turned forty-five degrees, face toward the camera, ",
    },
    "three_quarter_nude": {
        "label": "three-quarter, nude",
        "framing": (
            "THREE-QUARTER VIEW nude character reference sheet of a single adult character, "
            "body turned forty-five degrees, face toward the camera, standing, head to toe "
            "fully in frame. "),
        "pose": "standing, ",
        "camera": "THREE-QUARTER VIEW nude character reference sheet of a single adult character, "
                  "body turned forty-five degrees, face toward the camera, ",
    },
    "profile": {
        "label": "profile, clothed",
        "framing": (
            "PROFILE VIEW character reference sheet of a single adult character, "
            "full side view, standing, head to toe fully in frame. "),
        "pose": "standing, ",
        "camera": "PROFILE VIEW character reference sheet of a single adult character, "
                  "full side view, ",
    },
    "profile_nude": {
        "label": "profile, nude",
        "framing": (
            "PROFILE VIEW nude character reference sheet of a single adult character, "
            "full side view, standing, head to toe fully in frame. "),
        "pose": "standing, ",
        "camera": "PROFILE VIEW nude character reference sheet of a single adult character, "
                  "full side view, ",
    },
    "seated": {
        "label": "seated, clothed",
        "framing": (
            "SEATED VIEW character reference sheet of a single adult character, "
            "sitting facing the camera, head to toe fully in frame. "),
        "pose": "sitting facing the camera, ",
        "camera": "SEATED VIEW character reference sheet of a single adult character, ",
        "backdrop_omit": ("stance",),
    },
    "seated_nude": {
        "label": "seated, nude",
        "framing": (
            "SEATED VIEW nude character reference sheet of a single adult character, "
            "sitting facing the camera, head to toe fully in frame. "),
        "pose": "sitting facing the camera, ",
        "camera": "SEATED VIEW nude character reference sheet of a single adult character, ",
        "backdrop_omit": ("stance",),
    },
    "portrait": {
        "label": "portrait, clothed",
        "framing": (
            "PORTRAIT VIEW character reference sheet of a single adult character, "
            "head and shoulders, face toward the camera. "),
        "pose": "",
        "camera": "PORTRAIT VIEW character reference sheet of a single adult character, ",
        "backdrop_omit": ("stance", "crop", "floor"),
    },
    "portrait_nude": {
        "label": "portrait, nude",
        "framing": (
            "PORTRAIT VIEW nude character reference sheet of a single adult character, "
            "head and shoulders, face toward the camera. "),
        "pose": "",
        "camera": "PORTRAIT VIEW nude character reference sheet of a single adult character, ",
        "backdrop_omit": ("stance", "crop", "floor"),
    },
    "on_all_fours": {
        "label": "on all fours, clothed",
        "framing": (
            "ON ALL FOURS character reference sheet of a single adult character, "
            "on hands and knees, hips toward the camera, back arched, tail lifted aside, "
            "head turned to look back, knees apart, head to toe fully in frame. "),
        "pose": "on hands and knees, hips toward the camera, back arched, tail lifted aside, "
                "head turned to look back, knees apart, ",
        "camera": "ON ALL FOURS character reference sheet of a single adult character, ",
        "backdrop_omit": ("stance",),
    },
    "on_all_fours_nude": {
        "label": "on all fours, nude",
        "framing": (
            "ON ALL FOURS nude character reference sheet of a single adult character, "
            "on hands and knees, hips toward the camera, back arched, tail lifted aside, "
            "head turned to look back, knees apart, head to toe fully in frame. "),
        "pose": "on hands and knees, hips toward the camera, back arched, tail lifted aside, "
                "head turned to look back, knees apart, ",
        "camera": "ON ALL FOURS nude character reference sheet of a single adult character, ",
        "backdrop_omit": ("stance",),
    },
}

# Compat: callers and tests still read a key→framing map.
DEFAULT_VIEWS = {k: v["framing"] for k, v in VIEWS.items()}


def view_entry(view):
    """Shipped VIEWS row, or a named custom pose (pose_<id> / pose_<id>_nude)."""
    if view in VIEWS:
        return VIEWS[view]
    key = str(view or "")
    nude = key.endswith("_nude")
    raw = key[:-5] if nude else key
    if raw.startswith("pose_"):
        name = raw[5:].replace("_", " ").strip() or "custom pose"
    else:
        name = raw.replace("_", " ").strip() or "custom pose"
    kind = "nude " if nude else ""
    return {
        "label": f"{name}, {'nude' if nude else 'clothed'}",
        "framing": (
            f"{name.upper()} {kind}character reference sheet of a single adult character, "
            f"{name}, head to toe fully in frame. "),
        "pose": f"{name}, ",
        "camera": f"{name.upper()} {kind}character reference sheet of a single adult character, ",
        "backdrop_omit": ("stance",),
        "custom": True,
    }


def _omit(view):
    return view_entry(view).get("backdrop_omit") or ()


def _pose_clause(text):
    text = " ".join((text or "").split())
    if not text:
        return ""
    text = text.rstrip(".,; ")
    return (text + ", ") if text else ""


def apply_pose(view, framing, pose):
    """Replace the view's pose clause. Never append beside it.

    Two contradictory positives do not average (Day 4). docs/TRD-7 T7-16.
    """
    clause = _pose_clause(pose)
    if not clause or not framing:
        return framing
    spec = view_entry(view)
    default = spec.get("pose") or ""
    if default and default in framing:
        return framing.replace(default, clause, 1)
    # overlays may reword the camera but still carry a shipped stance
    for token in (
        "standing upright facing the camera straight on, arms relaxed at their sides, "
        "feet apart, ",
        "standing upright, arms relaxed at their sides, feet apart, ",
        "sitting facing the camera, ",
        "on hands and knees, hips toward the camera, back arched, tail lifted aside, "
        "head turned to look back, knees apart, ",
        "standing, ",
    ):
        if token in framing:
            return framing.replace(token, clause, 1)
    camera = spec.get("camera") or ""
    if camera and framing.startswith(camera):
        return camera + clause + framing[len(camera):]
    needle = "character, "
    idx = framing.find(needle)
    if idx != -1:
        at = idx + len(needle)
        return framing[:at] + clause + framing[at:]
    return framing


def backdrop_for(view, text=None):
    """BACKDROP with this view's omitted parts removed.

    An album override (text is not the constant) is used as written — stripping
    clauses the operator typed would be a second composer. docs/TRD-7 T7-5.
    """
    if text is not None and text != BACKDROP:
        return text
    omit = _omit(view)
    return "".join(p for k, p in BACKDROP_PARTS if k not in omit)


def composite_for(view, text=None):
    """COMPOSITE without 'standing' when the view omitted stance.

    Two references is the normal generate. Leaving 'standing by herself' in
    COMPOSITE put seated/portrait beside a standing clause. T7-5.
    """
    if text is not None and text != COMPOSITE:
        return text
    if "stance" in _omit(view):
        return COMPOSITE_HEAD + "by herself."
    return COMPOSITE

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
        # The studio and the multi-reference clause, per album. Constants with
        # no override until now, and both reach every sheet -- an album shot
        # against a black cyclorama had nowhere to say so, and a project whose
        # references are stills rather than photographs could not reword what
        # "the same character" means. docs/TRD-7 T7-14, T7-15.
        "backdrop": data.get("backdrop") or BACKDROP,
        "composite": data.get("composite") or COMPOSITE,
        # Optional, per-sheet. Empty is the view's own stance. docs/TRD-7 T7-16.
        "pose": (data.get("pose") or "").strip(),
        "views": views,
    }


def prompt_for(view, anchor=None, n_refs=1):
    a = anchor or load_anchor(None)
    # On a nude view the album's wardrobe wording is the one thing that must NOT
    # be used -- it describes the outfit, and including it produces a clothed
    # sheet however the view is worded. The BODY clause stays: colouring per
    # body part is exactly as load-bearing here as anywhere else.
    nude = is_nude_view(view)
    wardrobe = a.get("nude_wardrobe", NUDE_WARDROBE) if nude else a["wardrobe"]
    framing = (a.get("views") or {}).get(view) or view_entry(view).get("framing") or ""
    framing = apply_pose(view, framing, a.get("pose"))
    parts = [framing, wardrobe, a["body"], a["identity"]]
    # The anatomy clause applies to nude views only, and goes AFTER the body
    # clause so it reads as detail on the surface the body clause just
    # established rather than as a competing description of it.
    if nude and a.get("anatomy"):
        parts.insert(3, a["anatomy"])
    if n_refs > 1:
        # several unlabelled references are read as several PEOPLE unless the
        # prompt says otherwise
        parts.insert(1, composite_for(view, a.get("composite") or COMPOSITE))
    parts.append(backdrop_for(view, a.get("backdrop") or BACKDROP))
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
    ap.add_argument("--view", choices=list(VIEWS), default="front")
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
    ap.add_argument("--latent", choices=("empty", "image"), default="empty",
                    help="empty = generate from noise at --width x --height, the character "
                         "sheet case. image = VAEEncode the FIRST reference and denoise from "
                         "it, which is what makes --denoise below 1.0 mean anything: it "
                         "refines an existing sheet instead of returning partly-undenoised "
                         "noise. In image mode the output inherits the reference's size and "
                         "--width/--height are ignored.")
    args = ap.parse_args()
    if args.latent == "image" and not args.images:
        # build_refs.workflow falls back to an empty latent when there is no
        # image to encode, so this would silently render the other mode -- and
        # at denoise 0.55 that is noise, an hour later, with nothing saying why.
        ap.error("--latent image needs at least one reference image to encode")

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
        #
        # NO COMPOSITION PLATE, and base=None is the whole of it. This used to
        # be `images[1]`, so whichever photograph happened to be picked second
        # was silently promoted to the plate that sets composition -- a role the
        # form never mentioned and the caller could not choose. It contradicted
        # this file's own model of its input: the references are an unordered SET
        # of photographs of ONE character (see COMPOSITE), not a face and a
        # layout. With latent_mode "empty" the plate did nothing a plain
        # reference does not, so the concept is gone rather than exposed.
        # An anchor sheet has no composition to inherit. docs/TRD-7 T7-9.
        wf = workflow(scene, images[0] if images else "",
                      None, args.latent,
                      args.width, args.height, seed, "", args.guardrail,
                      # name=None: these are more photographs of the SAME
                      # character, not cast members. They used to be auto-named
                      # "reference 3", which build_refs.cast_clause turned into
                      # "The character in image 3 is reference 3." -- a second
                      # person asserted into a prompt whose composite clause
                      # says all the references show one. docs/TRD-7 T7-10.
                      extra_refs=[(None, img, "")
                                  for img in images[1:]],
                      settings=settings, ref_method=args.ref_method)
        wf["18"] = {"class_type": "SaveImage", "inputs": {
            "images": ["17", 0],
            "filename_prefix": f"{args.prefix}/{args.view}_s{seed}"}}
        json.dump(wf, open(f"{args.outdir}/{args.view}_{k:02d}_s{seed}.json", "w"))
    per = 15 if settings["lora_strength"] else 60
    note = "" if build_refs.negative_applies(settings) else \
        " -- negative prompt INERT at cfg 1.0, use --mode quality for it to apply"
    # The size is only true in "empty" mode: an encoded latent inherits the
    # reference's dimensions and --width/--height do nothing. Printing them
    # anyway is the same lie the denoise labels used to tell.
    size = (f"{args.width}x{args.height}" if args.latent == "empty"
            else "size inherited from the reference")
    print(f"{args.n} {args.view} anchor candidates -> {args.outdir} "
          f"({size}, {args.mode} mode: {settings['steps']} steps "
          f"cfg {settings['cfg']}, ~{args.n * per}s to render){note}")


if __name__ == "__main__":
    main()
