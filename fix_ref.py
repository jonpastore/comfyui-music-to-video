#!/usr/bin/env python3
"""Repair one already-rendered reference frame instead of re-rolling it.

Three modes, all on Qwen-Image-Edit 2511 -- the model that rendered the frame in
the first place. No extra model, no custom node: cerberus has no ReActor,
IPAdapter or InstantID, and does not need them, because a multi-image edit model
IS a face swapper when you tell it which image the face comes from.

  face      image1 = the frame, image2 = a face source. The instruction names
            both slots and forbids everything else from moving. Qwen's
            multi-image mode is steered by referring to "image 1"/"image 2" in
            the instruction itself; an unreferenced image is just extra
            conditioning the model interprets however it likes.

  inpaint   a painted mask constrains sampling to one region
            (InpaintModelConditioning). TextEncodeQwenImageEditPlus has no mask
            input of its own -- verified against the live /object_info -- so
            this is the wiring, not a convenience.

  outpaint  ImagePadForOutpaint emits the padded image AND the matching mask,
            into the same conditioning node. Extends a crop rather than
            regenerating it.

Why re-rolling is not good enough: a re-roll is a new seed, so it throws away
the composition you liked to fix the one thing you did not. This keeps the frame
and changes the part you point at.

usage:
  fix_ref.py --mode face --image clip_018.png --face nyx_anchor.png \
      --slug back-alley-pussy_r --clip 18 --seed 12345 --outdir /tmp/wf
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardrail  # noqa: E402  (applied here, the same chokepoint as build_refs)
from build_refs import STEPS, CFG, SHIFT  # noqa: E402  (one set of sampler settings)

MODES = ("face", "inpaint", "outpaint")

# Constraint clauses. Qwen-Image-Edit 2511's documented failure mode is
# OVER-editing -- asked for a face it will also restyle the outfit and relight
# the scene -- and the documented cure is to say what must not change. These are
# defaults the UI prefills and the user can edit.
INSTRUCTION = {
    "face": ("Replace the face of the person in image 1 with the face of the person in "
             "image 2. Keep the head shape, hair and body of image 1. Do not change pose, "
             "clothing, framing, background or lighting."),
    "inpaint": ("Repair only the masked region of image 1 so it matches the rest of the "
                "frame. Do not change pose, clothing, framing, background or lighting "
                "outside the masked region."),
    "outpaint": ("Extend image 1 into the new empty area, continuing the same scene, "
                 "perspective and lighting. Do not change anything in the original area."),
}

# Outpaint padding is capped: ImagePadForOutpaint takes up to 16384px per side,
# and a careless 4000px pad is an out-of-memory crash on the one shared GPU
# rather than a picture.
MAX_PAD = 1024


def build(mode, image, w, h, seed, instruction, guard="", body="",
          face=None, mask=None, pad=(0, 0, 0, 0), feathering=40):
    """The workflow for one repair. Returns the API-format dict.

    `instruction` is the editable text; the pinned clause and the tier wording
    are attached HERE by guardrail.build_prompt, exactly as build_refs.workflow
    does it. A repair prompt is a prompt: routing it around the chokepoint would
    make "fix this frame" the one path into the image model with no guardrail on
    it.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if mode == "face" and not face:
        raise ValueError("face mode needs --face")
    if mode == "inpaint" and not mask:
        raise ValueError("inpaint mode needs --mask")
    if mode == "outpaint" and not any(pad):
        raise ValueError("outpaint mode needs a non-zero pad on at least one side")

    pos = instruction or INSTRUCTION[mode]
    # The album's body wording goes into a repair too. A face swap that leaves
    # the limbs unspecified is exactly the prompt that came back with pale legs;
    # the rule is the same here as in build_refs -- state colouring per body
    # part, positively, in EVERY prompt.
    if body:
        pos += " " + body.strip()
    pos = guardrail.build_prompt(pos, guard, f"{mode} repair")

    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "qwen_image_edit_2511_fp8mixed.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["1", 0],
            "lora_name": "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
            "strength_model": 1.0}},
        "3": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["2", 0], "shift": SHIFT}},
        "4": {"class_type": "CFGNorm", "inputs": {"model": ["3", 0], "strength": 1.0}},
        "5": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image",
            "device": "default"}},
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "7": {"class_type": "LoadImage", "inputs": {"image": image}},
        "8": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["7", 0]}},
    }

    enc = {"clip": ["5", 0], "vae": ["6", 0], "image1": ["8", 0]}
    if mode == "face":
        wf["9"] = {"class_type": "LoadImage", "inputs": {"image": face}}
        wf["10"] = {"class_type": "FluxKontextImageScale", "inputs": {"image": ["9", 0]}}
        enc["image2"] = ["10", 0]

    wf["11"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": dict(enc, prompt=pos)}
    wf["12"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": dict(enc, prompt="")}
    wf["13"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {
        "conditioning": ["11", 0], "reference_latents_method": "index_timestep_zero"}}
    wf["14"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {
        "conditioning": ["12", 0], "reference_latents_method": "index_timestep_zero"}}

    if mode == "face":
        positive, negative, latent = ["13", 0], ["14", 0], ["15", 0]
        wf["15"] = {"class_type": "EmptySD3LatentImage", "inputs": {
            "width": w, "height": h, "batch_size": 1}}
    else:
        # Masked repair. The UNSCALED image (node 7) is the pixels, because the
        # mask was painted against the frame as saved -- running it through
        # FluxKontextImageScale first would move the pixels out from under the
        # mask by however much that node decided to resize.
        if mode == "inpaint":
            wf["20"] = {"class_type": "LoadImageMask", "inputs": {
                "image": mask, "channel": "red"}}
            pixels, mask_in = ["7", 0], ["20", 0]
        else:
            left, top, right, bottom = (min(int(p), MAX_PAD) for p in pad)
            wf["20"] = {"class_type": "ImagePadForOutpaint", "inputs": {
                "image": ["7", 0], "left": left, "top": top, "right": right,
                "bottom": bottom, "feathering": feathering}}
            pixels, mask_in = ["20", 0], ["20", 1]
        wf["21"] = {"class_type": "InpaintModelConditioning", "inputs": {
            "positive": ["13", 0], "negative": ["14", 0], "vae": ["6", 0],
            "pixels": pixels, "mask": mask_in, "noise_mask": True}}
        # its own three outputs replace the conditioning AND the latent: this is
        # what confines sampling to the masked region
        positive, negative, latent = ["21", 0], ["21", 1], ["21", 2]

    wf["16"] = {"class_type": "KSampler", "inputs": {
        "model": ["4", 0], "seed": seed, "steps": STEPS, "cfg": CFG,
        "sampler_name": "euler", "scheduler": "simple",
        "positive": positive, "negative": negative, "latent_image": latent, "denoise": 1.0}}
    wf["17"] = {"class_type": "VAEDecode", "inputs": {"samples": ["16", 0], "vae": ["6", 0]}}
    return wf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=MODES)
    ap.add_argument("--image", required=True, help="the frame to repair, as named in ComfyUI/input")
    ap.add_argument("--face", help="face source for --mode face, as named in ComfyUI/input")
    ap.add_argument("--mask", help="mask png for --mode inpaint, as named in ComfyUI/input")
    ap.add_argument("--pad", default="0,0,0,0", help="outpaint pad: left,top,right,bottom")
    ap.add_argument("--feathering", type=int, default=40)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--clip", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--instruction", default="", help="defaults to the mode's own wording")
    ap.add_argument("--guardrail", default="", help="tier wording; the pinned clause is "
                                                    "appended regardless and cannot be disabled")
    ap.add_argument("--body", default="", help="album body-consistency wording")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    pad = tuple(int(x) for x in args.pad.split(","))
    if len(pad) != 4:
        ap.error("--pad must be four comma-separated numbers: left,top,right,bottom")

    wf = build(args.mode, args.image, args.width, args.height, args.seed,
               args.instruction, args.guardrail, args.body,
               face=args.face, mask=args.mask, pad=pad, feathering=args.feathering)
    wf["18"] = {"class_type": "SaveImage", "inputs": {
        "images": ["17", 0],
        # same clip_NNN_sSEED shape reroll_refs uses, so pipeline._clip_records
        # reads the clip index and seed back out of the filename unchanged
        "filename_prefix": f"fix_{args.slug}/clip_{args.clip:03d}_s{args.seed}"}}
    os.makedirs(args.outdir, exist_ok=True)
    out = os.path.join(args.outdir, f"clip_{args.clip:03d}_s{args.seed}.json")
    with open(out, "w") as f:
        json.dump(wf, f)
    print(f"{args.mode} repair for clip {args.clip} -> {out}")


def demo():
    """Self-check: every mode wires up, and none of them escapes the guardrail."""
    import guardrail as g

    # --- face: the source lands in image2 and is named in the instruction ---
    wf = build("face", "clip_018.png", 1280, 720, 42, "", "tier wording",
               body="black fur head to toe", face="nyx.png")
    prompt = wf["11"]["inputs"]["prompt"]
    assert wf["11"]["inputs"]["image1"] == ["8", 0]
    assert wf["11"]["inputs"]["image2"] == ["10", 0]
    assert wf["9"]["inputs"]["image"] == "nyx.png"
    assert "image 1" in prompt and "image 2" in prompt
    assert "Do not change pose" in prompt, "the anti-over-edit constraint was dropped"
    assert "black fur head to toe" in prompt, "the body lock was dropped"
    # the one chokepoint, exactly once, last
    assert g.PINNED.strip() in prompt
    assert prompt.count("No minors") == 1
    assert prompt.rstrip().endswith(g.PINNED.strip())
    assert wf["16"]["inputs"]["latent_image"] == ["15", 0]
    assert wf["15"]["class_type"] == "EmptySD3LatentImage"

    # --- inpaint: sampling is confined by InpaintModelConditioning ---
    wf = build("inpaint", "clip_018.png", 1280, 720, 43, "", mask="mask.png")
    assert wf["20"]["class_type"] == "LoadImageMask"
    assert wf["21"]["class_type"] == "InpaintModelConditioning"
    # the UNSCALED frame, or the mask no longer lines up with the pixels
    assert wf["21"]["inputs"]["pixels"] == ["7", 0], wf["21"]["inputs"]["pixels"]
    assert wf["21"]["inputs"]["mask"] == ["20", 0]
    for key, want in (("positive", ["21", 0]), ("negative", ["21", 1]),
                      ("latent_image", ["21", 2])):
        assert wf["16"]["inputs"][key] == want, (key, wf["16"]["inputs"][key])

    # --- outpaint: pad node supplies both the pixels and the mask ---
    wf = build("outpaint", "clip_018.png", 1280, 720, 44, "", pad=(256, 0, 256, 0))
    assert wf["20"]["class_type"] == "ImagePadForOutpaint"
    assert wf["20"]["inputs"]["left"] == 256 and wf["20"]["inputs"]["right"] == 256
    assert wf["21"]["inputs"]["pixels"] == ["20", 0]
    assert wf["21"]["inputs"]["mask"] == ["20", 1]
    # a careless pad is clamped, not sent to the GPU as an OOM
    huge = build("outpaint", "c.png", 1280, 720, 45, "", pad=(99999, 0, 0, 0))
    assert huge["20"]["inputs"]["left"] == MAX_PAD

    # --- refusals: each mode needs its own input, and content is screened ---
    for mode, kwargs, why in (("face", {}, "no face source"),
                              ("inpaint", {}, "no mask"),
                              ("outpaint", {"pad": (0, 0, 0, 0)}, "no padding"),
                              ("nonsense", {}, "unknown mode")):
        try:
            build(mode, "c.png", 1280, 720, 1, "", **kwargs)
            raise AssertionError(f"accepted a {mode} repair with {why}")
        except ValueError:
            pass
    try:
        build("face", "c.png", 1280, 720, 1, "make her look like a schoolgirl", face="f.png")
        raise AssertionError("a repair instruction referencing minors was accepted")
    except g.ContentRefused:
        pass

    print("fix_ref.py OK")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        demo()
    else:
        main()
