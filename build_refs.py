#!/usr/bin/env python3
"""Build ComfyUI API workflows that render one reference image per storyboard scene.

Uses Qwen-Image-Edit 2511 with the Lightning 4-step LoRA. The Meow P anchor is
passed as a conditioning reference image so the character stays the same person
across all 12 scenes -- that is the whole point of using an edit model here
rather than plain text-to-image.

Node recipe is lifted from ComfyUI's own shipped image_qwen_image_edit_2511
template subgraph (ModelSamplingAuraFlow 3.1 / CFGNorm / FluxKontext scaling),
so it matches what the model was packaged to run.

usage:
  build_refs.py --storyboard rear_entrance_explicit.json \
      --slug rear_entrance --anchor meow_p_anchor.png --outdir ~/refs/re_explicit
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardrail  # noqa: E402  (applied here, NOT stored in the storyboard)
from build_song import (allocate, audio_duration, shot_directive, sname,
                        normalize, clip_plan, CHUNK)  # noqa: E402  (shared allocation)

# Lightning LoRA settings: 4 steps at cfg 1.0. NOTE: at cfg 1.0 ComfyUI skips
# the negative pass entirely, so scene negative_prompt has no effect -- the
# guardrail that actually applies is the one baked into image_prompt.
STEPS, CFG = 4, 1.0
SHIFT = 3.1


def single_subject(character=""):
    """Positive anti-duplicate clause, worded from the storyboard's OWN
    character description.

    Negatives are inert at cfg 1.0, so the storyboard's "duplicate character"
    entry does nothing and the protagonist sometimes renders twice. This says
    it positively. It targets the protagonist only -- background crowds are
    called for by several scenes.

    The subject used to be one album's character written into this file. It is
    now the first clause of the storyboard's character_reference, so every
    project describes its own protagonist and nothing here knows about any
    particular one. Falls back to a neutral phrase when a storyboard carries no
    character reference at all.
    """
    who = (character or "").split(",")[0].strip() or "the protagonist"
    return (f" Exactly one {who} in the frame: a single protagonist, "
            "no twin, no duplicate, no second copy.")


def tighten_for_detail(scene, world="", character=""):
    """Detail/macro framing loses to a prompt that enumerates her boots.

    The head-to-toe character lock is what keeps her consistent in shots where
    she is the subject, but on an insert shot she may only be a hand -- or
    absent. So for close framings the lock is replaced by a short identity hint
    and the scene's own action becomes the subject.

    Both the world and the identity hint come from the storyboard being rendered.
    They used to be one album's wardrobe hardcoded here, selected by a
    clean/explicit switch -- two ways to describe wardrobe, neither of them the
    tier that is supposed to own it.
    """
    action = scene.get("story_action") or scene.get("story") or ""
    hint = f"If any part of her is visible: {character}" if character else ""
    return " ".join(p for p in (f"Subject of this shot: {action}", world, hint) if p.strip())


DETAIL_SHOTS = ("EXTREME CLOSE-UP", "CLOSE-UP SHOT")


def scene_cast(scene, cast):
    """[(name, image, desc)] for the supporting characters THIS scene names.

    `cast` holds only characters that have a chosen anchor, so a scene naming
    an extra, a background character, or somebody nobody anchored simply gets
    nothing attached -- which is the intended behaviour. Only a main actor
    needs an anchor, and the storyboard is told exactly that.
    """
    out = []
    for name in (scene.get("characters") or []):
        entry = cast.get(name)
        if entry and entry.get("image"):
            out.append((name, entry["image"], entry.get("desc", "")))
    return out


# Qwen-Image-Edit 2511 is documented as working with 1 to 3 reference images,
# and TextEncodeQwenImageEditPlus exposes exactly image1/image2/image3. The
# anchor always holds slot 1 (it is the identity lock), so at most two more
# references -- a base plate, or cast members -- can be attached.
MAX_REF_IMAGES = 3


def assign_ref_slots(base, extra_refs):
    """[(slot, name, comfy_filename, description)] for the cast members that fit.

    The anchor is always image1 -- it is the identity lock and must not be
    displaced. A base plate, when given, takes image2. Whatever is left goes to
    the cast, and anything past MAX_REF_IMAGES is DROPPED rather than silently
    overwriting a slot: four named actors in one scene is a storyboard problem,
    and the caller reports it (see pipeline.gen_refs).
    """
    slot = 3 if base else 2
    out = []
    for name, img, desc in list(extra_refs or []):
        if slot > MAX_REF_IMAGES:
            break
        out.append((slot, name, img, desc))
        slot += 1
    return out


def cast_clause(slots):
    """Name each extra reference by its SLOT NUMBER.

    Qwen's multi-image mode is steered by referring to "image 1", "image 2" in
    the instruction itself -- an unreferenced image is just extra conditioning
    and the model decides for itself what to do with it. Naming who is in which
    slot is what turns two anchors into two specific characters rather than one
    blended one.
    """
    out = []
    for slot, name, _img, desc in slots:
        who = f"The character in image {slot} is {name}"
        out.append(f"{who}: {desc}." if desc else f"{who}.")
    return (" " + " ".join(out)) if out else ""


def workflow(scene, anchor, base, latent_mode, w, h, seed, shot="",
             guard="", world="", character="", body="", extra_refs=()):
    """guard: tier wording. The pinned clause is appended regardless, HERE --
    this is the chokepoint every storyboard reaches on its way to the image
    model, whoever generated it. Storing the clause in the storyboard JSON only
    covered files our own composer produced; it did nothing for the ones already
    in this repo, for `*_comfy.json` from another tool, or for a hand-edited
    file -- and editing prompts is the documented workflow.

    extra_refs: [(name, comfy_input_filename, description)] for the cast members
    this scene needs beyond the protagonist. They become image2/image3 and are
    named in the prompt by slot -- see cast_clause.
    """
    # shot directive goes FIRST -- framing is ignored when buried mid-prompt
    if shot.startswith(DETAIL_SHOTS):
        pos = shot + " " + tighten_for_detail(scene, world, character)
    else:
        pos = (shot + " " if shot else "") + scene["image_prompt"] + single_subject(character)
    # The body lock goes in EVERY frame, not just the anchor. Colouring stated
    # once at the top of a prompt does not hold below the waist -- that is why
    # frames came back with pale limbs, and with one glute black and the other
    # white, while the anchor itself was fine: this text only ever reached
    # make_anchor. It is the album's `body` field, per body part, positive
    # (negatives are inert at cfg 1.0).
    if body:
        pos += " " + body.strip()
    # Slots are assigned BEFORE the prompt is sealed. The cast clause names who
    # is in image 2 and image 3, so it is prompt text like any other and has to
    # go through build_prompt with everything else -- appending it afterwards
    # would put unscreened character prose into the prompt AND leave it sitting
    # after the pinned clause, which is required to come last.
    slots = assign_ref_slots(base, extra_refs)
    pos += cast_clause(slots)
    pos = guardrail.build_prompt(pos, guard, f"scene {scene.get('scene_number','?')}")
    neg = scene.get("negative_prompt", "")

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
            "clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "7": {"class_type": "LoadImage", "inputs": {"image": anchor}},
        "8": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["7", 0]}},
    }

    # Conditioning: anchor is image1 (identity). A base plate, when supplied, is
    # image2 and sets composition/aspect. Cast members fill whatever slots are
    # left, up to MAX_REF_IMAGES.
    enc = {"clip": ["5", 0], "vae": ["6", 0], "image1": ["8", 0]}
    if base:
        wf["9"] = {"class_type": "LoadImage", "inputs": {"image": base}}
        wf["10"] = {"class_type": "FluxKontextImageScale", "inputs": {"image": ["9", 0]}}
        enc["image2"] = ["10", 0]
    # node ids from 22 up (slot*2+16): 18 is the SaveImage callers append, and
    # 9/10 belong to the base plate.
    for slot, name, img, desc in slots:
        load_id, scale_id = str(slot * 2 + 16), str(slot * 2 + 17)
        wf[load_id] = {"class_type": "LoadImage", "inputs": {"image": img}}
        wf[scale_id] = {"class_type": "FluxKontextImageScale", "inputs": {"image": [load_id, 0]}}
        enc[f"image{slot}"] = [scale_id, 0]

    wf["11"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": dict(enc, prompt=pos)}
    wf["12"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": dict(enc, prompt=neg)}
    wf["13"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {
        "conditioning": ["11", 0], "reference_latents_method": "index_timestep_zero"}}
    wf["14"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {
        "conditioning": ["12", 0], "reference_latents_method": "index_timestep_zero"}}

    if latent_mode == "empty":
        # free-size generation: gives a true 16:9 frame
        wf["15"] = {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}
    else:
        # edit-in-place: output inherits the base/anchor aspect
        src = ["10", 0] if base else ["8", 0]
        wf["15"] = {"class_type": "VAEEncode", "inputs": {"pixels": src, "vae": ["6", 0]}}

    wf["16"] = {"class_type": "KSampler", "inputs": {
        "model": ["4", 0], "seed": seed, "steps": STEPS, "cfg": CFG,
        "sampler_name": "euler", "scheduler": "simple",
        "positive": ["13", 0], "negative": ["14", 0], "latent_image": ["15", 0], "denoise": 1.0}}
    wf["17"] = {"class_type": "VAEDecode", "inputs": {"samples": ["16", 0], "vae": ["6", 0]}}
    return wf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--anchor", required=True, help="identity reference, as named in ComfyUI/input")
    ap.add_argument("--base", help="optional 16:9 composition base, as named in ComfyUI/input")
    ap.add_argument("--latent", choices=["empty", "image"], default="empty")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--scenes", help="comma-separated scene numbers; default all")
    ap.add_argument("--audio", help="mp3 path. Given this, emit one reference per CLIP "
                                    "instead of one per scene, so no two consecutive clips "
                                    "animate the same still.")
    ap.add_argument("--body", default="", help="body-consistency wording for the album "
                                                "(colouring per body part); goes into every prompt")
    ap.add_argument("--guardrail", default="", help="tier wording; the pinned clause is "
                                                    "appended regardless and cannot be disabled")
    ap.add_argument("--cast", help="json file: {name: {image, desc}} of anchored supporting "
                                    "characters. A scene attaches the ones its 'characters' "
                                    "list names; extras and background need no anchor.")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    cast = json.load(open(args.cast)) if args.cast else {}
    sb = normalize(json.load(open(args.storyboard)))
    scenes = sb["scenes"]
    world = sb.get("album_world_reference") or sb.get("world_reference", "")
    character = sb.get("character_reference", "")
    os.makedirs(args.outdir, exist_ok=True)

    if args.audio:
        dur = audio_duration(args.audio)
        plan_clips = clip_plan(scenes, args.audio)
        i = len(plan_clips)
        counts = [sum(1 for _, s, _ in plan_clips if s is sc) for sc in scenes]
        for ci, scene, shot in plan_clips:
            # distinct seed per clip -> a different composition of the same
            # scene, with the anchor still pinning the character
            wf = workflow(scene, args.anchor, args.base, args.latent,
                          args.width, args.height, 7000 + ci,
                          shot, args.guardrail, world, character, args.body,
                          extra_refs=scene_cast(scene, cast))
            wf["18"] = {"class_type": "SaveImage", "inputs": {
                "images": ["17", 0],
                "filename_prefix": f"refs_{args.slug}/clip_{ci:03d}"}}
            with open(f"{args.outdir}/clip_{ci:03d}.json", "w") as f:
                json.dump(wf, f)
        print(f"{args.slug} {dur:.1f}s -> {i} reference images "
              f"across {len(scenes)} scenes ({args.width}x{args.height}), "
              f"~{i*15/60:.0f} min to render")
        for scene, n in zip(scenes, counts):
            print(f"  scene {scene['scene_number']:2d} {sname(scene)[:30]:<32} {n} image(s)")
        return

    want = {int(x) for x in args.scenes.split(",")} if args.scenes else None
    n = 0
    for scene in scenes:
        num = scene["scene_number"]
        if want and num not in want:
            continue
        wf = workflow(scene, args.anchor, args.base, args.latent,
                      args.width, args.height, 7000 + num,
                      shot_directive(scene, num), args.guardrail, world, character,
                      args.body, extra_refs=scene_cast(scene, cast))
        wf["18"] = {"class_type": "SaveImage", "inputs": {
            "images": ["17", 0],
            "filename_prefix": f"refs_{args.slug}/scene_{num:02d}"}}
        with open(f"{args.outdir}/scene_{num:02d}.json", "w") as f:
            json.dump(wf, f)
        n += 1
    print(f"{args.slug} wrote {n} reference-image workflows to {args.outdir} "
          f"(latent={args.latent} {args.width}x{args.height})")


if __name__ == "__main__":
    main()
