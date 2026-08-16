"""The model catalogue: what is installed, and what each one is FOR.

Three model families were named as string literals inside build_refs.py,
build_song.py and make_anchor.py. Adding the wan2.2 i2v pair meant editing
Python, and nothing anywhere said what a given model was designed for -- so
"which model renders the clips" was a question you answered by reading source.

This module is the answer instead. Each entry is data: a role, a label, the
file, the loader class it goes into, one line on what it is for, and the
caveats that cost this project time to learn. Adding a model later is one dict
entry plus whatever workflow support it needs; it is never a UI change.

When to pick Qwen-Image-Edit 2511 vs LTX/WAN vs a parked Pony/Krea/Flux
family is `docs/DDD-4-7-IDENTITY-AND-RENDERING.md` §1a. A later change
may add optional `family` / `stage` / `when` / `not_for` keys copied
from that section. It does not add Pony, Krea, or Flux as
`role=reference` defaults.

AVAILABILITY IS NOT ASSUMED. It is read from the live ComfyUI /object_info --
the same enum the loader node would validate against -- so a catalogued model
that is not on the box shows as missing in the UI instead of failing forty
minutes into a render. Chat models come from grok.list_models() for the same
reason.

AND THERE IS MORE THAN ONE BOX NOW. Three ComfyUI backends are registered with
SwarmUI, they do not hold the same files, and the same weights are not even
named the same thing on each: peaches calls the Z-Image VAE
`z_image_ae.safetensors` where cerberus calls it `ae.safetensors`, and holds
ACE-Step as `..._fp16` because a Turing card cannot run the bf16 build. A
workflow that names one spelling cannot run on the box that uses the other, and
nothing anywhere said so -- which is how "Z-Image makes the 2080 Ti useful"
survived as a plan for a box that could not have loaded Wayne's workflow.
ALIASES records those spellings and availability is answered PER BACKEND.
"""
import json
import os
import time
import urllib.error
import urllib.request

import db

COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
OBJECT_INFO_TIMEOUT = 10

# What a model is chosen FOR. One role per decision point in the UI.
ROLES = {
    "reference": "Reference stills -- one image per clip, from the anchor",
    "video": "Clips -- the animated 4.8125s segments",
    "refine": "Optional second pass over a rendered clip",
    "artwork": "Album covers, generated from the album look",
    "storyboard": "Writing the shot list from the lyrics",
    "vision": "Reviewing rendered frames, and describing an anchor",
    "audio": "Generative audio repair",
    # NOT the same thing as "vision". A vision model LOOKS at a frame and says
    # something about it; an encoder turns a reference image into features
    # another model conditions on, and never produces words or pixels. They were
    # nearly folded together, which would have put a SigLIP encoder in the list
    # the UI offers for "review these frames" -- the editor promising what the
    # renderer cannot do, one more time.
    "encoder": "Turning a reference image into features a renderer can condition on",
}

# Roles whose models are rendered by one of this repo's own scripts, and so
# carry a "cli" value naming what that script accepts. EVERY catalogued model in
# such a role must have one: a model documented here but not actually wired is
# unfinished work, not a feature, and the UI has no way to be honest about it.
# storyboard and vision are resolved by their own modules at call time.
RENDERED_ROLES = ("reference", "video", "refine", "artwork", "audio")

# loader class -> the input whose enum lists installed files
LOADER_FIELD = {
    "UNETLoader": "unet_name",
    "LoraLoaderModelOnly": "lora_name",
    "VAELoader": "vae_name",
    "CLIPLoader": "clip_name",
    "CheckpointLoaderSimple": "ckpt_name",
    "AudioEncoderLoader": "audio_encoder_name",
    # Added 2026-08-12. Until then nothing here could SEE a clip_vision file:
    # installed() only enumerates the loaders listed in this dict, so a box's
    # image encoders were invisible to catalog(), to by_backend(), and to
    # pipeline._retarget -- which is the thing that rewrites a filename to the
    # spelling a box uses. An encoder that cannot be enumerated cannot be
    # routed, cannot be reported missing, and reads as "not installed anywhere".
    # LTX's latent spatial upscaler, for the two-stage refine. Enumerable since
    # the COMBO shape is parsed -- it publishes its options in the dict form,
    # which is exactly the case that used to read as "not enumerable".
    "LatentUpscaleModelLoader": "model_name",
    "CLIPVisionLoader": "clip_name",
}

# The SAME weights under a different filename on a different box. Availability
# resolves through this, and a workflow targeting a backend must load the name
# THAT box has -- a loader enum is validated against the literal string.
#
# Verified 2026-08-12 by reading /object_info from all three backends directly.
ALIASES = {
    # A 2080 Ti is Turing: it has no bf16 path, so peaches holds an fp16 cast of
    # ACE-Step under its own name. Naming the cerberus spelling in a workflow is
    # what would make the always-on audio box refuse the job.
    "ace_step_v1_3.5b.safetensors": ("ace_step_v1_3.5b_fp16.safetensors",),
    # Z-Image's autoencoder. Cerberus took the upstream name; peaches was
    # provisioned with the model's own name. This one is load-bearing: Z-Image
    # is the ONLY image model the 2080 Ti can run, and the workflow that has
    # actually rendered Z-Image here loads "ae.safetensors".
    "ae.safetensors": ("z_image_ae.safetensors",),
    # Cerberus carries the Qwen VAE at the top level AND under QwenImage/. Same
    # file, two enum entries, and a workflow written against one is refused by a
    # box that only has the other.
    "qwen_image_vae.safetensors": ("QwenImage/qwen_image_vae.safetensors",),
}

# How much a box can be RELIED ON, which is a different question from what it
# holds. Keyed by host, because Swarm's numeric ids renumber when a backend is
# added and its titles are edited by hand.
#
#   stable         always on, and a job sent here is expected to finish
#   opportunistic  may be off, in use by a human, or mid-reprovision. Fine to
#                  send work to; never the only place work can go.
#
# This says nothing about SPEED. Backend 1 is the fastest box here and is still
# opportunistic, because it is somebody's desktop.
# The studio's own box, under the name every OTHER box would call it. Backend 0's
# Swarm address is 127.0.0.1:8188 because the studio runs on that machine, so a
# render served over loopback and one served over the tailnet are the SAME BOX
# under two names.
#
# That matters beyond tidiness: docs/TRD-3 T3-1 groups artefacts by `host`
# precisely because Swarm renumbers backend ids, and until this existed the
# artefacts table carried `127.0.0.1` -- so cerberus reported as two boxes, or as
# a box whose name means "wherever I am". Measured 2026-08-13: all 12 stamped
# artefacts read host=127.0.0.1.
SELF_HOST = "100.103.148.120"
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0", "[::1]"})

BACKEND_STABILITY = {
    # ONE key for cerberus. The loopback spelling used to sit here too and is
    # gone deliberately -- canonical_host() resolves it before any lookup, so a
    # second entry could only ever disagree with this one.
    SELF_HOST: ("stable", "cerberus, the box the studio itself runs on"),
    "100.107.235.105": ("opportunistic", "gamingpc -- a desktop somebody uses"),
    "100.95.184.29": ("opportunistic", "peaches-unraid -- shares a NAS with other services"),
}


def canonical_host(address):
    """The durable identity of a box, from an address or a bare host.

    ONE OWNER FOR THIS, and it is the point of the function existing rather than
    the parsing being inlined. The same three-`split` string lived in
    `backend_stability()` here and in `pipeline._host()` there, which is one
    decision applied in two places -- the shape that produced the T1-20d
    loudnorm defect on 2026-08-13. Both call this now.

    Loopback resolves to SELF_HOST because the studio runs on that box: an
    address of 127.0.0.1 is not "unknown", it is cerberus answering itself.
    Anything else is returned as given, and an unknown box stays unknown -- the
    safe direction to be wrong in is "do not depend on it".
    """
    host = (address or "").split("//")[-1].split(":")[0].split("/")[0].strip().lower()
    if not host:
        return None
    return SELF_HOST if host in _LOOPBACK else host
UNKNOWN_BACKEND = ("opportunistic", "not in BACKEND_STABILITY -- assumed unreliable")

# What a MODEL has been proven to do here, which is a different question again.
#   stable         has rendered real work on this project, end to end
#   opportunistic  catalogued and installed, but the path is unproven or unwritten
# Every catalogue entry must declare one; demo() enforces it, so a model added
# later cannot quietly arrive claiming to be production-ready.
PROVEN = ("stable", "opportunistic")

# Files a loader enumerates that are DELIBERATELY not catalogued. Measured
# against the live boxes 2026-08-13: cerberus enumerates 36 files across the
# seven loaders in LOADER_FIELD, and these are the ones with no entry.
#
# The point of the list is that absence becomes a DECISION instead of a gap.
# docs/TRD-2 T2-35 asserts every enumerated file is either catalogued or named
# here, so a model arriving on a box can no longer be invisible to routing --
# which is how a workflow comes to name a file `where()` says nobody has.
#
# T2-35 also claimed "ae.safetensors is a companion under an alias". It is not:
# it is an ALIASES key and no CATALOG entry names it, because there was no
# Z-Image entry at all until today. That parenthetical was wrong.
IGNORED = {
    "pixel_space":
        "ComfyUI's built-in latent-passthrough VAE, not a file on disk. Enumerated "
        "by VAELoader on every box including ones holding no VAEs at all.",
    "OfficialStableDiffusion/sd_xl_base_1.0.safetensors":
        "SDXL base, from a SwarmUI default install. Nothing here uses it and "
        "Qwen-Image-Edit supersedes it for every reference job.",
    "taeltx2_3.safetensors":
        "Tiny autoencoder for LTX PREVIEW decoding, used by the sampler's live "
        "preview, never by a render. Cataloguing it would offer it as a VAE.",
    # --- the LTX-2 19B family. LTX-2.5 supersedes it: measured stable on two
    # boxes, renders 30s and 60s, and is audio-conditioned.
    "ltx-2-19b-dev-fp8.safetensors":
        "LTX-2 19B base. Superseded by 2.5 and deliberately not wired -- the "
        "camera LoRAs below were the only argument for installing it.",
    "ltx-2-19b-distilled-lora-384.safetensors":
        "Distilled LoRA for the 19B base, which is not wired.",
    "LTX-2/ltx-2-19b-ic-lora-detailer.safetensors":
        "Detailer LoRA for the 19B base, which is not wired.",
    "LTX-2/ltx-2-19b-lora-camera-control-static.safetensors":
        "MEASURED NOT TO WORK on LTX-2.5 (docs/TRD-2 6). Dimensionally "
        "compatible at 4096, applies without error, changes pixels, and produces "
        "no camera move -- a LoRA half-applied over int8-quantised weights.",
    "ltx-2-19b-lora-camera-control-dolly-left.safetensors":
        "Same measurement: neutral prompt, same seed, LoRA off gives a locked "
        "camera (0,0,0,-3,-4) and LoRA on gives incoherent noise (+9,-9,-37,+30). "
        "The `camera` storyboard field stays prose because of this.",
    # --- Qwen LoRAs nobody has measured
    "Qwen-Image-Edit-Unblur-Upscale_15.safetensors":
        "Unblur/upscale LoRA for Qwen-Image-Edit. Never measured here; "
        "make_postproc uses RealESRGAN for upscaling instead.",
    "qwen-edit-skin.safetensors":
        "Skin-detail LoRA for Qwen-Image-Edit. Never measured here.",
    "qwen_3_4b_fp8_mixed.safetensors":
        "Qwen3 4B text encoder. The reference path uses qwen_2.5_vl_7b; this is "
        "a smaller alternative nothing is written against.",
    "ltx-2.5-22b-distilled-transformer-nvfp4.safetensors":
        "The SAME model as ltx25 at a different quantisation -- 17.4 GiB nvfp4 "
        "against 20.03 int8 -- downloaded as the VRAM fallback and named in "
        "ltx25's purpose text and build_song.LTX25_MODEL_NVFP4. Not a second "
        "catalogue entry, because that would put two LTX-2.5s in the picker and "
        "the choice between them is a VRAM decision no scheduler here makes yet.",
    "ZImage/SwarmUI_Z-Image-Turbo-FP8Mix.safetensors":
        "SwarmUI's own copy of the Z-Image checkpoint catalogued as z_image_turbo "
        "-- same weights under SwarmUI's path. See ALIASES.",
}


CATALOG = {
    "z_image_turbo": {
        "role": "reference",
        "label": "Z-Image Turbo (fp8 mixed)",
        "file": "z_image_turbo_fp8mix.safetensors",
        "loader": "UNETLoader",
        "cli": "zimage",
        "companions": {"ae.safetensors": "VAELoader"},
        "weights_gib": 6.7,
        "proven": "opportunistic",
        "purpose": (
            "Z-Image Turbo. THE ONLY IMAGE MODEL THE 2080 Ti CAN RUN, which is why "
            "it is here at all: measured 2026-08-12, a real 1024x576 render in 60.8s "
            "cold and 8.6s warm on peaches, RGB std 56.2. Per pixel the 5090 is 3.5x "
            "faster, so fp8 storage without fp8 matmul is a tax and not a wall.\n"
            "What conditions it is `reference_latents` through the VAE -- `omni` mode "
            "switches on when len(ref_latents) > 0, NOT on a CLIP encoder. The "
            "checkpoint has 794 tensors and NO siglip_embedder, so a CLIP-vision "
            "encoder wired into TextEncodeZImageOmni loads, does real work (64.0s vs "
            "44.2s) and its output is discarded -- byte-identical PNGs at two "
            "independent seeds. It wants a Z-Image OMNI checkpoint, which is not here.\n"
            "TRAP: `auto_resize_images` scales to ~1MP and rounds to /8, but Z-Image "
            "patchifies 2x2 and needs /16. The album's 896x1216 anchor becomes "
            "880x1192 -> latent 110x149, and 149 is odd: a hard crash in 0.4s, seven "
            "times running. Set it false and feed a /16-clean anchor."),
        "notes": [
            "UNPROVEN FOR ANCHORS. Every anchor this project has rendered came from "
            "Qwen-Image-Edit 2511, which takes the uploaded samples as direct image "
            "conditioning; Z-Image has never been on the anchor path.",
            "Its VAE is spelled differently per box -- ae.safetensors on cerberus, "
            "z_image_ae.safetensors on peaches -- so a workflow naming one is refused "
            "by the other until pipeline._retarget rewrites it. See ALIASES.",
        ],
    },
    "qwen_image_edit_2511": {
        "role": "reference",
        "proven": "stable",   # every reference frame and every anchor this project has rendered
        "weights_gib": 19.12,   # fp8 mixed, one file
        "label": "Qwen-Image-Edit 2511 (fp8 mixed)",
        "file": "qwen_image_edit_2511_fp8mixed.safetensors",
        "loader": "UNETLoader",
        "default": True,
        "cli": "qwen",
        "purpose": (
            "Turns the anchor into this scene's still. An EDIT model, not a text-to-image "
            "model: it takes up to three reference images and keeps the person in them, "
            "which is what holds the character together across fifty frames."),
        "notes": [
            "Takes 1-3 reference images. The anchor holds image1; a scene's named cast "
            "members take image2 and image3.",
            "Steered by naming the slots in the instruction -- \"the face in image 2\". An "
            "unreferenced image is just extra conditioning.",
            "Runs at 4 steps, cfg 1.0 with the Lightning LoRA. At cfg 1.0 ComfyUI skips "
            "the negative pass entirely, so negative prompts are inert -- say what you "
            "want, positively.",
            "Also does the face swaps, inpainting and outpainting (fix_ref.py).",
        ],
        "companions": {
            "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors": "LoraLoaderModelOnly",
            "qwen_2.5_vl_7b_fp8_scaled.safetensors": "CLIPLoader",
            "qwen_image_vae.safetensors": "VAELoader"},
    },
    "wan22_s2v": {
        "role": "video",
        "proven": "stable",   # the original clip path, ~90s per clip on real songs
        "weights_gib": 15.27,   # one file
        "label": "WAN 2.2 S2V 14B (sound to video)",
        "file": "wan2.2_s2v_14B_fp8_scaled.safetensors",
        "loader": "UNETLoader",
        # the --video-model value build_song.py accepts
        "cli": "s2v",
        "ceiling": {
            "seconds": 4.8125,
            "frames": 77,
            "origin": "chosen",
            "kind": "provisional",
        },
        "purpose": (
            "Animates an approved reference frame using THE AUDIO. Takes the scene's motion "
            "prompt, the reference image and a wav2vec2 encoding of that clip's 4.8125 "
            "seconds all at once -- so movement lands on the beat and the mouth moves on "
            "vocal lines."),
        "notes": [
            "The only video model here that is driven by the music. This is why it is the "
            "default and why i2v is not a replacement for it.",
            "One pass, 4 steps with the lightx2v LoRA, ~90s per clip.",
            "Has two inputs the pipeline can now fill: ref_motion (a motion-style clip) "
            "and control_video (a driving clip for pose or structure).",
        ],
        "companions": {
            "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors": "LoraLoaderModelOnly",
            "umt5_xxl_fp8_e4m3fn_scaled.safetensors": "CLIPLoader",
            "wan_2.1_vae.safetensors": "VAELoader",
            "wav2vec2_large_english_fp16.safetensors": "AudioEncoderLoader"},
    },
    "wan22_i2v": {
        "role": "video",
        "proven": "opportunistic",   # the installed 4-step LoRA is a t2v LoRA; steps unre-tuned
        "weights_gib": 26.62,   # 13.31 x2 -- the pair is ONE model split at a denoise boundary
        "label": "WAN 2.2 I2V 14B (image to video, high+low noise)",
        "file": "Wan2.2/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        "loader": "UNETLoader",
        "cli": "i2v",
        "ceiling": {
            "seconds": 4.8125,
            "frames": 77,
            "origin": "chosen",
            "kind": "provisional",
        },
        "purpose": (
            "Animates a still from the prompt alone. Two experts run in sequence: the high-"
            "noise model establishes motion and structure, the low-noise one refines detail "
            "and steadies the frame."),
        "notes": [
            "NO AUDIO INPUT. Choosing this gives up beat sync and mouth movement -- it is "
            "the right pick for an instrumental passage, not for a vocal track.",
            "Needs both files; the pair is one model split at a denoise boundary of 0.900.",
            "The installed 4-step LoRA is a t2v high-noise LoRA, so step counts and quality "
            "need re-tuning here rather than being inherited from the s2v path.",
        ],
        "companions": {
            "Wan2.2/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors": "UNETLoader",
            "umt5_xxl_fp8_e4m3fn_scaled.safetensors": "CLIPLoader",
            "wan_2.1_vae.safetensors": "VAELoader"},
    },
    "ltx25": {
        "role": "video",
        "proven": "stable",   # measured on a real clip on two boxes, 2026-08-12
        "weights_gib": 20.03,   # int8-convrot; the nvfp4 build is 17.4
        "label": "LTX-2.5 22B distilled (audio-conditioned, int8-convrot)",
        "file": "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
        "loader": "UNETLoader",
        "cli": "ltx25",
        "ceiling": {
            "seconds": 15.0,
            "origin": "measured",
            "kind": "cost",
            "card": "cerberus 24GB 5090",
            "date": "2026-08-13",
        },
        "default": True,
        "refine_peak": {
            "variant": "A",
            "peak_gb": None,
            "total_gb": None,
            "host": None,
            "date": None,
            "n_samples": None,
            "origin": "not_measured",
            "method": "pipeline.sample_vram /system_stats during a refine submit",
            "resolution": "832x480",
        },
        "purpose": (
            "The current audio-conditioned path, and the same contract as 2.3: approved "
            "reference frame, scene prompt, and the clip's audio fused as a joint AV latent "
            "so it conditions the motion. 2.5 changed the node graph, not just the weights."),
        "notes": [
            "MEASURED 2026-08-12 on a real clip (approved reference frame + the track's "
            "own audio), 81 frames at 832x480, 8 steps: gamingpc (32 GB desktop 5090) 34.7s "
            "end to end, 4.9s of that sampling, peak 28.3 GB of 31.8. cerberus (24 GB laptop "
            "5090) 38.0s, peak 23.4 GB of 23.9 -- 95.8% of the card, so nothing else may be "
            "resident: run pipeline.free_vram() first, as the clip job already does. "
            "T5-5: variant A refine peak is NOT MEASURED on the box -- the 23.4/23.9 "
            "figure is the base render, not a quoted refine peak.",
            "T5-6 FINDING 2026-08-14: variant B (LTXVLatentUpsampler x2 then re-denoise) "
            "does not fit on cerberus. The measured base already peaks at 23.4 GB of 23.9 "
            "(95.8%) at 832x480, leaving 0.5 GB. The x2 spatial latent is four times the "
            "pixels and the upscaler is 0.3 GiB -- that exceeds the remaining headroom on "
            "the same graph. --refine therefore ships variant A (same-resolution second "
            "pass). The upsampler is not wired.",
            "Needs ComfyUI at 57ce8e1a or later (2026-08-11, 'Add support for LTX 2.5'). "
            "Nothing older has LTXVDualCFGGuider or LTXVDurationPredictor at all.",
            "Needs torch built against CUDA 13. comfy/quant_ops.py disables comfy-kitchen's "
            "CUDA backend when torch.version.cuda < 13, which silently drops the int8-convrot "
            "and nvfp4 matmuls onto the eager backend -- it still renders, just far slower, "
            "and nothing in the UI says so. Check the startup log for "
            "\"comfy_kitchen backend cuda: {'available': True, 'disabled': False}\".",
            "Unlike 2.3, its text encoder loads through a plain CLIPLoader with type 'ltxv' "
            "-- the projection is baked into the 'with-proj' encoder, so there is no second "
            "checkpoints/ file. Its audio VAE likewise loads through a plain VAELoader.",
            "20.03 GiB of weights. int8 DOES fit the 24 GB laptop card, but at 95.8% peak "
            "with no headroom; the nvfp4 build (17.4 GiB) is downloaded alongside it as the "
            "fallback if anything else needs VRAM -- see build_song.LTX25_MODEL_NVFP4.",
            "Licence: LTX-2.x Community Licence, free commercial use under $10M revenue.",
            "THE REFERENCE IMAGE DOES NOT HOLD IDENTITY BY ITSELF. The character has to be "
            "described in the TEXT or the model reverts to its prior, which is an ordinary "
            "human. Measured 2026-08-12 with a one-variable differential -- same reference "
            "(an anthropomorphic black feline woman), same seed, same box, same 15 seconds, "
            "species named in the prompt or not: named, feline throughout; not named, a "
            "human woman by the halfway point, keeping only the harness. A 30s render "
            "failed the same way by a quarter in, and a 60s one held for the full minute "
            "purely because its prompt happened to say \"a black cat\". This is what "
            "build_song's char_lock exists for -- it composes storyboard "
            "`character_reference` into every clip prompt -- so an empty character_reference "
            "renders a stranger and every deterministic check still passes.",
            "CLIP LENGTH: 505 frames (30.00s) and 1009 frames (59.95s) both render on the "
            "24 GB card, verified with ffprobe. The 8n+1 latent rule is the only hard limit "
            "found; VRAM was not the wall it was assumed to be. But cost is SUPERLINEAR -- "
            "257 frames took 46.2s and 505 took 373.1s on the same box, so 2x the frames "
            "cost about 8x the time. Per second of finished video that is 3.0s of compute "
            "at 15s against 12.4s at 30s.",
            "FRAME RATE: this pipeline sends 16.8312, and the model's own nodes default to "
            "25 (LTXVConditioning) and 24 (LTXVDurationPredictor). 16.8312 is not a reading "
            "of LTX at all -- build_song derives it as LTX_LEN/CHUNK so that 81 frames last "
            "exactly the 4.8125s that WAN 2.2 S2V's 77-frame chunk lasts, which kept the "
            "clip allocation identical across models. Measured consequence at 15s, one clip "
            "each: mean pixel change per second is comparable (8.35 at 16.8312, 7.72 at 25), "
            "so it is NOT uniformly slow -- but the SHAPE differs. At 16.8312 the action is "
            "front-loaded and decays (15.4 in the first second down to 4.7 in the last); at "
            "25 it is flat across the clip (8.6 down to 7.7). Consistent with motion authored "
            "for a 4.8s beat finishing early and then coasting. n=1 per side and the two "
            "clips differ in content, so this wants a proper A/B before build_song changes.",
        ],
        "companions": {
            "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors": "CLIPLoader",
            "ltx-2.5-video-vae-bf16.safetensors": "VAELoader",
            "ltx-2.5-audio-vae-bf16.safetensors": "VAELoader"},
    },
    "ltx23": {
        "role": "video",
        "proven": "stable",   # measured on a real clip, 50s, and kept as the 2.5 fallback
        "weights_gib": 21.86,   # fp8_scaled
        "label": "LTX-2.3 22B distilled (audio-conditioned, ~2x faster)",
        "file": "ltx-2.3-22b-distilled_transformer_only_fp8_scaled.safetensors",
        "loader": "UNETLoader",
        "cli": "ltx",
        "ceiling": {
            "seconds": 15.0,
            "origin": "measured",
            "kind": "cost",
            "card": "cerberus 24GB 5090",
            "date": "2026-08-13",
        },
        "purpose": (
            "The other audio-driven video path. Like s2v it takes the approved reference "
            "frame, the scene prompt AND the clip's audio -- but it fuses audio as a joint "
            "AV latent rather than cross-attending it, and it renders about twice as fast."),
        "notes": [
            "MEASURED on this box, not quoted: 81 frames at 832x480, 8 steps, in 45s, peak "
            "18.9 GB of 24.4 GB. WAN s2v is ~90s for the same clip.",
            "LTX latent length must be 8n+1 -- the pipeline's 77 frames is not a legal "
            "value. It renders 81 frames at 16.8312 fps, which is exactly the same 4.8125s "
            "chunk, so the clip allocation is identical whichever model renders it.",
            "The audio half of the sampled latent is discarded: the master mp3 is laid over "
            "the assembled timeline once, which is what stops per-clip audio drifting. The "
            "audio still conditions the MOTION, which is the point.",
            "Its text projection must live in models/checkpoints/, not text_encoders/ -- "
            "LTXAVTextEncoderLoader reads ckpt_name from the checkpoints folder.",
            "Peak VRAM is 95% of the card during text encoding. Nothing else may be "
            "resident: run pipeline.free_vram() first, as the clip job already does.",
            "A REAL clip -- the approved reference frame plus the track's own audio -- "
            "renders in 50s against s2v's ~90s. That is the measurement the default is "
            "based on.",
        ],
        "companions": {
            "gemma_3_12B_it_fp4_mixed.safetensors": "CLIPLoader",
            # BOTH of these load from models/checkpoints/, not from the folder
            # their name suggests: LTXAVTextEncoderLoader and LTXVAudioVAELoader
            # each read ckpt_name from the checkpoints list. Putting them in
            # text_encoders/ and vae/ is what a reasonable person does first,
            # and the node simply refuses to see them there.
            "ltx-2.3_text_projection_bf16.safetensors": "CheckpointLoaderSimple",
            "LTX23_audio_vae_bf16.safetensors": "CheckpointLoaderSimple",
            "LTX23_video_vae_bf16.safetensors": "VAELoader"},
    },
    "wan22_i2v_low": {
        "role": "refine",
        "proven": "opportunistic",   # T3-26 measures this; stays opportunistic until a labelled set improves
        "weights_gib": 13.31,   # the UNET alone
        # WHAT IT ACTUALLY COSTS RESIDENT, and fits() uses this instead. The
        # note below has said 20.5 GB in prose since 2026-08-12 while the
        # arithmetic kept answering from 13.31 -- so fits("wan22_i2v_low",
        # 15.92) said TRUE for ethan's card, on a model that cannot be held
        # there. A note the code does not read is the defect this catalogue
        # exists to prevent, wearing the catalogue's own clothes.
        "resident_gib": 20.5,   # 13.31 UNET + 6.3 umt5 + 0.24 vae
        "label": "WAN 2.2 I2V 14B low-noise (refiner pass)",
        "file": "Wan2.2/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
        "loader": "UNETLoader",
        "default": True,
        "cli": "i2v_low",
        "purpose": (
            "Optional second pass over a clip the s2v model already rendered: re-samples at "
            "low denoise to clean artifacts and sharpen detail, without touching the motion "
            "the audio produced."),
        "notes": [
            "UNPROVEN on s2v output. Both models share wan_2.1_vae so the latents are "
            "compatible, but nothing here has measured whether it helps.",
            "Roughly doubles render time. Render three clips with and three without, and "
            "compare, before committing a song to it.",
            "STAGING THIS COSTS 20.5 GB, not 13.31. The weights are the UNET alone; the "
            "graph build_song.py:456 also loads umt5_xxl_fp8_e4m3fn_scaled (6.3 GB) and "
            "wan_2.1_vae (243 MB). That was not recorded anywhere until 2026-08-12, when "
            "putting the refiner on a second box made the difference matter -- staging the "
            "UNET alone gives a backend that lists the model and then fails at load, which "
            "is the shape of failure this catalogue exists to prevent.",
        ],
        # The text encoder is a COMPANION, not scenery. A missing companion is
        # what `missing` in catalog() is for, and umt5 was absent from this dict
        # while being mandatory in the graph -- so a box holding the UNET and the
        # VAE reported the refiner as fully available.
        "companions": {"wan_2.1_vae.safetensors": "VAELoader",
                       "umt5_xxl_fp8_e4m3fn_scaled.safetensors": "CLIPLoader"},
    },
    "qwen_artwork": {
        "role": "artwork",
        "proven": "stable",   # same weights as the reference path, already rendering covers
        "weights_gib": 19.12,   # the same file as the reference role
        "label": "Qwen-Image-Edit 2511 (local, free)",
        "file": "qwen_image_edit_2511_fp8mixed.safetensors",
        "loader": "UNETLoader",
        "default": True,
        "cli": "qwen",
        "purpose": (
            "Generates the album cover from the album look, on the same model that renders "
            "every reference frame. Given a chosen anchor it uses it as a reference, so the "
            "cover shows the actual protagonist rather than a lookalike."),
        "notes": [
            "Free and local. Runs on the box that is already loaded with this model, so "
            "there is nothing extra to download.",
            "With no anchor it still works as plain text-to-image -- every image input on "
            "TextEncodeQwenImageEditPlus is optional.",
            "Portrait 1024x1024 by default; an album cover is square.",
        ],
        "companions": {
            "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors": "LoraLoaderModelOnly",
            "qwen_2.5_vl_7b_fp8_scaled.safetensors": "CLIPLoader",
            "qwen_image_vae.safetensors": "VAELoader"},
    },
    "ltx25_latent_upscaler": {
        "role": "refine",
        "label": "LTX-2.5 latent spatial upscaler x2",
        "file": "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
        "loader": "LatentUpscaleModelLoader",
        "cli": "ltx_upscale",
        "companions": {},
        "weights_gib": 0.3,
        "proven": "opportunistic",
        "purpose": (
            "Doubles an LTX latent spatially so a second sampler pass can add detail "
            "rather than redistribute it -- LTX's own documented two-stage refine. "
            "Takes (samples, upscale_model, vae) and returns a LATENT, so it goes "
            "between the sampler and VAEDecode, AFTER LTXVSeparateAVLatent: a joint "
            "audio-video latent into a spatial upsampler is not a thing."),
        "notes": [
            "T5-6 2026-08-14: variant B does not fit on cerberus. Recorded on the "
            "ltx25 notes from the measured 23.4/23.9 GB base peak (0.5 GB headroom). "
            "--refine ships variant A. This file stays catalogued so availability "
            "still reads True/False (T5-8); it is not attached to the refine graph.",
            "The WAN refiner (wan22_i2v_low) is NOT an alternative for LTX output: "
            "it is valid only because s2v and i2v-low share wan_2.1_vae. LTX uses "
            "its own video VAE, so handing an LTX latent to WAN is meaningless.",
            "ltx-2-spatial-upscaler-x2-1.0.safetensors sits beside it on cerberus "
            "and is the LTX-2 (19B) counterpart, not this one.",
        ],
    },
    "siglip2_naflex": {
        "role": "encoder",
        # Installed and loading on peaches, and it changes NOTHING it is wired
        # to today. That is not a hedge, it is measured -- see the notes.
        "proven": "opportunistic",
        "weights_gib": 4.23,    # the published file carries a text tower too
        "label": "SigLIP2 so400m patch16 NaFlex (image encoder)",
        "file": "siglip2_so400m_patch16_naflex.safetensors",
        "loader": "CLIPVisionLoader",
        "purpose": (
            "Encodes a reference image into the `siglip_feats` that Z-Image Omni "
            "conditions on. It renders nothing itself and has no CLI: it is a "
            "companion an image model either uses or ignores."),
        "notes": [
            "INERT WITH THE Z-IMAGE WE HAVE, measured 2026-08-12 on peaches at two "
            "independent seeds. Wiring it into TextEncodeZImageOmni costs real work "
            "(47.1s vs 77.5s, and 64.0s vs 44.2s on the other seed -- it loads and "
            "encodes) and the rendered PNGs are BYTE-IDENTICAL with it and without "
            "it. Cause is in the checkpoint, not the wiring: "
            "z_image_turbo_fp8mix.safetensors has 794 tensors and no siglip_embedder, "
            "so comfy/ldm/lumina/model.py:676 drops the features -- `if (not omni) or "
            "self.siglip_embedder is None`. It needs a Z-Image OMNI checkpoint, which "
            "is not installed here and which Comfy-Org does not repackage.",
            "The anchor DOES reach the render without it, by the other path: "
            "reference_latents, from the VAE. Anchor vs no-anchor at one seed differ "
            "by 67.1 mean absolute RGB, and `omni` mode is switched on by "
            "len(ref_latents) > 0, never by this encoder.",
            "WHICH FILE IS NOT A MATTER OF TASTE, and the usual advice is wrong. Two "
            "guides recommend siglip-so400m-patch14-384; that loads as "
            "siglip_vision_model, which never sets image_sizes, and model_base.py "
            "needs image_sizes to build siglip_feats at all. comfy/clip_vision.py "
            "picks the naflex config ONLY when patch_embedding.weight is 2-D. Verified "
            "from this file's own safetensors header before trusting it: [1152, 768], "
            "27 layers, width 1152. Note the config is named ..._base_naflex.json but "
            "its contents are so400m, so the filename is not the guide either.",
            "Peaches only, for now. Nothing on cerberus or gamingpc needs it while "
            "Z-Image Omni is absent, and it is 4.5 GB.",
        ],
        "companions": {},
    },
    "ace_step_v1": {
        "role": "audio",
        "proven": "stable",   # measured 2026-08-12: a real mp3, 9.979s, -14.2 dB mean
        "weights_gib": 7.17,   # bf16; peaches carries an fp16 cast of the same size class
        "label": "ACE-Step v1 3.5B",
        "file": "ace_step_v1_3.5b.safetensors",
        "loader": "CheckpointLoaderSimple",
        "default": True,
        "cli": "ace_step",
        "purpose": (
            "Writes new music from a style tag list and optional lyrics. It is a "
            "GENERATOR, not an editor: it cannot cut a region out of an existing track, "
            "and this entry used to claim it could."),
        "notes": [
            "CORRECTED 2026-08-12, and the old wording had it backwards. This entry said "
            "\"ffmpeg can only trim the ENDS of a track; cutting from the middle needs "
            "this\" -- so ACE-Step was catalogued as the answer to a job it cannot do. "
            "peaches publishes TextEncodeAceStepAudio, EmptyAceStepLatentAudio and "
            "VAEEncodeAudio and NO region or mask node, so denoise below 1.0 "
            "re-synthesises the WHOLE clip, not a span of it.",
            "Cutting from the middle is therefore ffmpeg's job after all: slice out the "
            "span, generate a bridge of exactly that length, splice it back. ACE-Step "
            "supplies the bridge and nothing else.",
            "Whatever it produces is NEW audio, never a shortened original, so the UI has "
            "to say which path ran.",
            "Routed by filename alone: make_audio.py names the fp16 spelling and peaches "
            "is the only box holding a file by that name, so the backend walk lands it "
            "there without any routing rule. See ALIASES.",
            "Generation is measured end to end. The repair/re-synthesis path is built and "
            "graph-checked but has NOT been run against real audio.",
        ],
        "companions": {},
    },
}


# /object_info is a large response and it is asked for on every page that names
# a model. Installed models change when someone copies a file onto the box, not
# per request, so a short cache keeps a page render from waiting on the network
# each time -- including the OBJECT_INFO_TIMEOUT wait when ComfyUI is down.
_CACHE_TTL = 30.0
_cache = {}   # url -> {"at": monotonic, "info": dict|None}


def _object_info(url=None):
    """The live node/model listing for one ComfyUI, or None if it did not answer.

    Cached PER URL. There are three backends and the whole point of asking each
    one separately is that their answers differ; one shared slot would have made
    the last box asked the answer for all of them.

    FAILURES are cached too, and deliberately: a down ComfyUI would otherwise
    make every page that names a model pay the connection attempt -- up to
    OBJECT_INFO_TIMEOUT each, on a filtered network -- which turns one dead
    service into a studio that appears to hang. With three backends that is
    three times the wait, so it matters more than it did.
    """
    url = url or COMFY
    now = time.monotonic()
    hit = _cache.get(url)
    if hit and now - hit["at"] < _CACHE_TTL:
        return hit["info"]
    try:
        with urllib.request.urlopen(f"{url}/object_info", timeout=OBJECT_INFO_TIMEOUT) as r:
            info = json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError):
        # ComfyUI being down is not an error here: the catalogue still lists what
        # each model is for, availability just reads "unknown" instead of a lie
        # in either direction.
        info = None
    _cache[url] = {"at": now, "info": info}
    return info


def _system_stats(url=None):
    """{'vram_gib': float} for one backend, or None if it did not answer.

    Same per-URL cache and same failure policy as _object_info: a box being off
    is not an error, it is an unknown.
    """
    url = url or COMFY
    key = f"stats:{url}"
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit["at"] < _CACHE_TTL:
        return hit["info"]
    info = None
    try:
        with urllib.request.urlopen(f"{url}/system_stats", timeout=OBJECT_INFO_TIMEOUT) as r:
            data = json.loads(r.read())
        dev = (data.get("devices") or [{}])[0]
        total = dev.get("vram_total")
        if total:
            info = {"vram_gib": round(total / 2 ** 30, 2), "gpu": dev.get("name", "")}
    except (urllib.error.URLError, OSError, ValueError, IndexError, TypeError):
        info = None
    _cache[key] = {"at": now, "info": info}
    return info


def fits(key, vram_gib):
    """Does this model's weight file fit on a card of this size?

    True / False / None-when-unknown, and it is a FLOOR check, not a prediction
    of peak VRAM. ComfyUI streams weights it cannot hold, so False means "this
    box would move the whole file across PCIe every step", not "it will refuse".
    The direction that matters is the one it is certain about: LTX-2.3 is 21.86
    GiB on disk and peaks at 18.9 during a render, so weights are not an upper
    bound on anything -- but a 15.27 GiB UNET on a 10.58 GiB card is 1.44x the
    card and no amount of scheduling makes that resident.

    Per-model caveats about how close to the ceiling a model runs are in its
    notes, measured, and this does not try to replace them.
    """
    m = CATALOG.get(key)
    if not m or not vram_gib or not m.get("weights_gib"):
        return None
    # resident_gib when the real cost has been MEASURED and differs, because a
    # graph loads more than its UNET: the refiner is 13.31 of weights and 20.5
    # resident once its umt5 text encoder and VAE are counted, and answering
    # from the UNET alone said an unstageable model fits.
    return m.get("resident_gib", m["weights_gib"]) <= vram_gib


def refine_peak(model="ltx25"):
    """Catalogue record for the shipped refine variant's peak VRAM (T5-5).

    Lives on the catalogue row beside the 23.4/23.9 base figure. A quoted
    number with origin=measured and no samples is not a reading.
    """
    rec = CATALOG.get(model)
    peak = rec.get("refine_peak") if rec else None
    if not peak:
        raise ValueError("T5-5 refine peak VRAM is NOT MEASURED")
    return peak


def weight_available(path=None, *, expected_bytes=None):
    """True only when on-disk bytes look complete (T9-13a).

    A file is not a model. installed() reads the loader enum, never the bytes,
    so a truncated weight at a real filename reports available and fails at
    load. This is the byte check the enum cannot make:

      - path=None / missing file → False (enum-only is not availability)
      - epoch mtime → False (rsync --partial sets mtime only on completion)
      - size short of expected_bytes → False (--inplace keeps a live mtime)
    """
    if not path or not os.path.isfile(path):
        return False
    try:
        st = os.stat(path)
    except OSError:
        return False
    # rsync --partial leaves mtime at the epoch until the transfer completes.
    if st.st_mtime <= 0:
        return False
    if expected_bytes is not None and st.st_size < int(expected_bytes):
        return False
    return True


def staging_files(key):
    """Primary weight plus every companion, one act (T9-13b).

    Reads CATALOG.companions. A path that hardcodes the list stages whatever
    the last person remembered; a box holding the UNET and VAE without the
    text encoder reports available and fails at load.
    """
    m = CATALOG.get(key)
    if not m:
        raise ValueError(f"no such model: {key}")
    files = [m["file"]]
    files.extend(m.get("companions") or ())
    return files


# T9-13c — restart mid-transfer publishes a truncated model. Order is not optional.
# Safety rests on the idle queue, not Swarm's connect-time cache (unreadable).
STAGING_SEQUENCE = (
    "transfer",
    "checksums",
    "queues_idle",
    "restart_swarm",
    "render",
)


def staging_allows(step, done=()):
    """True only when every prior STAGING_SEQUENCE step is in done (T9-13c).

    transfer → checksums → queues_idle → restart_swarm → render.

    Restarting SwarmUI before checksums pass publishes a partial weight at a
    real filename to the router. The idle queue is the verified protection;
    Swarm's cached model list cannot be read back via ListBackends.
    """
    if step not in STAGING_SEQUENCE:
        raise ValueError(f"unknown staging step: {step!r}")
    need = STAGING_SEQUENCE[:STAGING_SEQUENCE.index(step)]
    have = set(done)
    return all(s in have for s in need)


def spellings(name):
    """Every filename these same weights are known by. Canonical name first.

    SYMMETRIC, and it was not until 2026-08-12. ALIASES is written one way round
    -- canonical key, other spellings in the value -- and reading it literally
    made this answer depend on which end of the pair you asked from:
    `resolve("ace_step_v1_3.5b.safetensors", peaches_pool)` found the fp16 cast,
    while `resolve("ace_step_v1_3.5b_fp16.safetensors", cerberus_pool)` returned
    None. That is the direction the live workflows actually ask from --
    make_audio.py names the fp16 spelling on purpose -- so the function was
    answering "cerberus does not have ACE-Step" about a box that has it.

    An alias group is a set of names for one file. Which one the dict happened
    to key on is bookkeeping, not a fact about the weights.
    """
    for canon, alts in ALIASES.items():
        group = (canon,) + tuple(alts)
        if name in group:
            # asked-for name first: an exact match must still win over an alias,
            # or a box holding BOTH spellings gets handed the other one.
            return (name,) + tuple(s for s in group if s != name)
    return (name,)


def resolve(name, pool):
    """The spelling of `name` that THIS box has, or None if it has none.

    A loader enum is validated against the literal string, so knowing a box has
    the model is not enough -- a workflow sent there has to name the file the
    way that box names it.
    """
    if pool is None:
        return None
    for spelling in spellings(name):
        if spelling in pool:
            return spelling
    return None


def _enum_options(spec):
    """The filenames a required-input spec offers, or None if it is not a list
    of them. Handles both of ComfyUI's combo shapes -- see installed()."""
    if not spec or not isinstance(spec, list):
        return None
    if isinstance(spec[0], list):                       # ["a.safetensors", ...]
        return set(spec[0])
    if (spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict)
            and isinstance(spec[1].get("options"), list)):
        return set(spec[1]["options"])
    return None


def installed(object_info=None, url=None):
    """{loader_class: {filenames} | None} as ComfyUI itself reports them, or None.

    `url` picks the backend; None means this studio's own COMFY.

    Three distinct answers, and conflating any two of them produces a wrong
    signal in a direction that matters:

      None (the whole dict)  ComfyUI could not be asked.
      None (one loader)      that loader does not publish an enumerable list.
                             A false "missing" sends you hunting for a file that
                             is already there, which is why this is not set().
      set()                  asked, enumerable, and genuinely nothing installed.

    TWO ENUM SHAPES, and the second one arrived under us. ComfyUI used to put
    the options in spec[0] as a plain list. It now also emits
    ``["COMBO", {"options": [...], ...}]`` -- 433 fields on cerberus use that
    shape as of 2026-08-13, INCLUDING AudioEncoderLoader, which this docstring
    used as its example of a loader that "reports the literal COMBO rather than
    filenames". That was true when it was written and is no longer: the files
    are right there in the dict.

    Reading only spec[0] therefore answered "cannot be enumerated" for loaders
    whose contents were perfectly readable -- models.installed() saw 7 files on
    a box where a shape-aware diff sees 36. Both shapes are read now, and None
    still means what it says: genuinely not enumerable.
    """
    info = object_info if object_info is not None else _object_info(url)
    if info is None:
        return None
    out = {}
    for loader, field in LOADER_FIELD.items():
        node = info.get(loader) or {}
        spec = (node.get("input", {}).get("required", {}) or {}).get(field)
        out[loader] = _enum_options(spec)
    return out


def catalog(role=None, object_info=None, url=None):
    """The catalogue, annotated with what is actually on one box.

    `available` is True/False when ComfyUI answered and None when it did not,
    or when that loader publishes no enumerable list.

    `missing` names the companion files a model needs that are genuinely absent
    -- an entry whose LoRA is missing renders, badly, at the wrong step count,
    which is far worse than refusing. A companion whose loader cannot be
    enumerated is NOT listed: unknown is not missing.

    `file_here` and `companions_here` give the spellings THIS box uses, which is
    what a workflow aimed at it has to name. On the studio's own box they are
    almost always the canonical names; on peaches, three of them are not.
    """
    have = installed(object_info, url)
    out = []
    for key, m in CATALOG.items():
        if role and m["role"] != role:
            continue
        entry = dict(m, key=key, role_label=ROLES.get(m["role"], m["role"]))
        if have is None:
            entry.update(available=None, missing=[], file_here=None, companions_here={})
        else:
            pool = have.get(m["loader"])
            found = resolve(m["file"], pool)
            entry["available"] = None if pool is None else bool(found)
            entry["file_here"] = found
            entry["companions_here"] = {
                name: resolve(name, have.get(loader))
                for name, loader in m["companions"].items()}
            entry["missing"] = [name for name, loader in m["companions"].items()
                                if have.get(loader) is not None
                                and not resolve(name, have[loader])]
        out.append(entry)
    return out


def backend_stability(address):
    """(stability, why) for a backend address. Unknown boxes are opportunistic:
    the safe direction to be wrong in is "do not depend on it"."""
    return BACKEND_STABILITY.get(canonical_host(address), UNKNOWN_BACKEND)


def backend_empty(row):
    """True when a reachable backend holds none of the catalogue (T9-9).

    Measured 2026-08-12: a box listed running with models/ at 8 KB refused a
    real workflow in 0.6s. Unreachable is a different signal -- unknown is not
    empty. Confirmed presence of any catalogued model is stocked.
    """
    if not row.get("reachable"):
        return False
    return not any(e.get("available") is True for e in row.get("models") or [])


def accept_backend(row):
    """Refuse registering a backend that holds no catalogued models (T9-9).

    Staging weights is a prerequisite. An empty box is a hazard Swarm's free
    draw would hand real jobs; curation only routes around it after a refusal.
    Returns the row when stocked (or not-yet-asked). Raises ValueError when
    empty.
    """
    if backend_empty(row):
        label = row.get("title") or row.get("id") or "?"
        raise ValueError(
            f"backend {label!r} holds no catalogued models; "
            "stage weights before registering")
    return row


def by_backend(backends, role=None):
    """The catalogue answered separately for every backend.

    `backends` is what pipeline.swarm_backends() returns -- [{id, title, status,
    address}] -- and is passed IN rather than fetched, because pipeline imports
    this module and the cycle would be real. app.py holds both and wires them.

    Returns [{id, title, status, address, stability, why, reachable, empty,
    hazard, models}], where models is the catalog() list for that box.
    `reachable` distinguishes "Swarm says running but its ComfyUI would not
    answer us" from "answered". `empty` / `hazard="empty"` flag a reachable
    box that holds none of the catalogue -- registered, listed as running, and
    useless, which is exactly what backend 1 did on 2026-08-12 (T9-9).
    """
    out = []
    for b in (backends or []):
        address = b.get("address") or None
        info = _object_info(address)
        stats = _system_stats(address) or {}
        stability, why = backend_stability(address)
        entries = catalog(role=role, object_info=info)
        for e in entries:
            # INSTALLED and FITS are different failures with different fixes:
            # one is a download, the other is a card. Peaches holds neither
            # wan22 file, but even if it did, a 15.27 GiB UNET does not go on
            # a 10.58 GiB 2080 Ti.
            e["fits"] = fits(e["key"], stats.get("vram_gib"))
        row = dict(b, stability=stability, stability_why=why,
                   reachable=info is not None,
                   vram_gib=stats.get("vram_gib"), gpu=stats.get("gpu", ""),
                   models=entries)
        empty = backend_empty(row)
        row["empty"] = empty
        row["hazard"] = "empty" if empty else None
        out.append(row)
    return out


def where(key, backends):
    """Which backends can run this model, best first.

    Ordering is the fallback order: stable boxes before opportunistic ones, and
    within each, the ones that answered before the ones that did not. It is a
    RECOMMENDATION for pipeline's retry walk, not a schedule -- Swarm decides
    where an unpinned job lands, and a model being present is not a promise the
    box is free.
    """
    rows = []
    for b in by_backend(backends):
        entry = next((e for e in b["models"] if e["key"] == key), None)
        if not entry:
            continue
        # UNKNOWN IS NOT MISSING, and this used to conflate them. `available` is
        # False when a box was asked and does not have the model, and None when
        # it could not be asked at all -- and `if not entry["available"]` dropped
        # both, so a box that simply did not answer was reported as one that
        # cannot run the model.
        #
        # In the worst direction, too: this function is the scheduler's
        # capability contract, and it answered "no box can run this" when the
        # truth was "the box I could not reach can". Backend 0's address is
        # 127.0.0.1:8188 as Swarm reports it, so anything querying from a box
        # that is not cerberus cannot reach it -- and cerberus is the stable box
        # holding the models the others do not.
        #
        # installed() has documented this rule since it was written ("a false
        # 'missing' sends you hunting for a file that is already there"). where()
        # was the one place that broke it.
        if entry["available"] is False:
            continue
        rows.append({"id": b["id"], "title": b["title"], "address": b["address"],
                     "stability": b["stability"], "file_here": entry["file_here"],
                     "fits": entry["fits"], "vram_gib": b["vram_gib"],
                     # True = asked and it has it. None = could not ask. A caller
                     # that needs certainty filters on this; one that needs a
                     # candidate list does not.
                     "confirmed": entry["available"] is True,
                     "reachable": b["reachable"]})
    # A box that holds the file but cannot hold it IN THE CARD goes last rather
    # than being dropped: it can still render, by streaming, and "slow" is a
    # different answer from "cannot". Unknown fit sorts with the ones that fit,
    # because unknown is not a reason to demote a box.
    #
    # Confirmed boxes come before unconfirmed ones: an unreachable box is a
    # candidate, not a recommendation, and a caller taking the first row should
    # get one that was actually asked whenever such a row exists.
    return sorted(rows, key=lambda r: (not r["confirmed"], r["fits"] is False,
                                       r["stability"] != "stable", str(r["id"])))


def video_key(name):
    """Catalogue key for a scene or job video_model (cli or key).

    Scenes store the renderer value (`s2v`, `ltx25`). where() keys the
    catalogue (`wan22_s2v`, `ltx25`). Both spellings resolve.
    """
    name = (name or "").strip()
    if not name:
        return None
    if name in CATALOG and CATALOG[name]["role"] == "video":
        return name
    for key, cli in renderable("video").items():
        if cli == name:
            return key
    return None


def named_video_keys(scenes, default=None):
    """Distinct catalogue keys a clips job will actually run.

    A scene with no video_model takes `default` (the job's --video-model).
    Unknown names are kept so T2-45 can still refuse them.
    """
    keys = []
    seen = set()
    fallback = video_key(default)
    if fallback is None:
        fallback = (default or "").strip() or None
    for scene in scenes or []:
        raw = (scene or {}).get("video_model")
        key = video_key(raw) if raw not in (None, "") else fallback
        if raw not in (None, "") and key is None:
            key = str(raw).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def available_on_fleet(key, backends):
    """Fleet-wide availability for one catalogue key.

    True  — a reachable backend confirmed it (where() has confirmed).
    False — every reachable backend was asked and lacks it (where() empty
            after at least one box answered). A refusal, not a candidate.
    None  — no box could be asked, or only unasked boxes remain. A
            candidate, not a refusal. Empty / missing backends are this,
            not False — that is the T6-A6 / T2-34 collapse.
    """
    if not backends:
        return None
    rows = where(key, backends)
    if any(r.get("confirmed") for r in rows):
        return True
    if rows:
        return None
    return False


def unavailable_on_reachable(key, backends):
    """True when every reachable backend answered False for this key.

    where() already drops False and keeps None. An empty where() list
    plus at least one backend means we asked and nobody has it. An
    empty fleet is not a refusal — nobody was asked. None is a
    candidate.
    """
    if not backends:
        return False
    return not where(key, backends)


def mixed_unavailable(scenes, backends, default=None):
    """Named models a mixed-model song cannot run anywhere reachable.

    Empty → enqueue. Non-empty → refuse those keys before enqueue.
    A single-model song is not this check: failing at clip 0 is
    obvious; T2-45 exists to stop failing at clip 31 of 42.
    """
    keys = named_video_keys(scenes, default=default)
    if len(keys) < 2:
        return []
    return [k for k in keys if unavailable_on_reachable(k, backends)]


def scene_requests_driving(scene):
    """True when a scene asked for ref_motion or control_video.

    T2-46: those inputs load through LoadVideosFromFolder (kjnodes),
    present on cerberus and absent on gamingpc.
    """
    if not isinstance(scene, dict):
        return False
    return any(str(scene.get(k) or "").strip()
               for k in ("ref_motion", "control_video"))


def cerberus_backend_id(backends):
    """Swarm backend id for cerberus, or None if the fleet did not name it.

    Ids renumber. Title `cerberus` and SELF_HOST (loopback) are the
    durable names. gamingpc is never this answer.
    """
    for b in backends or []:
        if not isinstance(b, dict) or b.get("id") is None:
            continue
        title = (b.get("title") or "").strip().lower()
        host = canonical_host(b.get("address"))
        if title == "cerberus" or host == SELF_HOST:
            return str(b["id"])
    return None


def get(key):
    return CATALOG.get(key)


def renderable(role):
    """{catalogue key: the value the renderer accepts} for this role.

    Every catalogued model in a RENDERED_ROLE has a "cli" value, so this is the
    whole role -- it exists to map catalogue keys onto what the script expects,
    not to filter out models that were never finished.
    """
    return {k: m["cli"] for k, m in CATALOG.items() if m["role"] == role and m.get("cli")}


def refuse_unknown_video_model(scenes):
    """T2-44: a scene naming a model absent from renderable("video") is
    refused at save, naming the scene number and the bad value.

    Absent or blank is not a name (T2-42: the render's --video-model applies).
    Catalogue keys and cli values both count as present: s2v is what scenes
    store, wan22_s2v is the catalogue key, and a keys-only check would refuse
    a real renderer.
    """
    wired = renderable("video")
    allowed = set(wired) | set(wired.values())
    for scene in scenes or ():
        if not isinstance(scene, dict):
            continue
        named = scene.get("video_model")
        if named is None:
            continue
        named = str(named).strip()
        if not named:
            continue
        if named not in allowed:
            raise ValueError(
                f"scene {scene.get('scene_number')} names video_model={named!r} "
                f"absent from models.renderable(\"video\")")


def default_for(role):
    """The remembered choice for a role, else the entry marked default, else the
    first catalogued one. Never returns something absent from the catalogue: a
    stale setting pointing at a deleted model would otherwise wedge every render
    for that role."""
    row = db.one("SELECT value FROM settings WHERE key=?", f"model.{role}")
    if row and row["value"] in CATALOG and CATALOG[row["value"]]["role"] == role:
        return row["value"]
    for key, m in CATALOG.items():
        if m["role"] == role and m.get("default"):
            return key
    for key, m in CATALOG.items():
        if m["role"] == role:
            return key
    return None


def default_cli(role):
    """The value the RENDERER wants for this role's default -- default_for()
    returns a catalogue key, and the scripts take a "cli" value. Callers that
    hardcoded one of these drifted from the catalogue the moment a default
    moved, which is exactly how the song page came to offer a default that
    /songs/{id}/clips answered with a 400."""
    return renderable(role).get(default_for(role))


def chat_default():
    """The remembered xAI chat model for storyboards, or "" for "highest available".

    Not a CATALOGUE key: xAI model ids are discovered at runtime from
    /v1/models, so there is nothing local to validate against and nothing local
    to describe. The setting is stored here because this is where every other
    remembered model choice lives.
    """
    row = db.one("SELECT value FROM settings WHERE key='model.storyboard'")
    return (row["value"] if row else "") or ""


def set_chat_default(key):
    db.run("INSERT INTO settings (key, value) VALUES ('model.storyboard', ?) "
           "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key or "").strip())
    return key


def set_default(role, key):
    if key not in CATALOG:
        raise ValueError(f"no such model: {key}")
    if CATALOG[key]["role"] != role:
        raise ValueError(f"{key} is a {CATALOG[key]['role']} model, not {role}")
    db.run("INSERT INTO settings (key, value) VALUES (?,?) "
           "ON CONFLICT(key) DO UPDATE SET value=excluded.value", f"model.{role}", key)
    return key


def demo():
    import os as _os
    import tempfile

    db.DATA = tempfile.mkdtemp()
    db.DB_PATH = _os.path.join(db.DATA, "t.db")
    db._local.__dict__.clear()

    # The refiner does NOT fit ethan's 15.92 GiB card, and fits() must say so.
    # It answered True until 2026-08-13 because it read the UNET's 13.31 and not
    # the 20.5 the graph actually loads -- a number its own notes carried.
    assert fits("wan22_i2v_low", 15.92) is False, \
        "fits() is answering from weights_gib again; the refiner needs 20.5 GiB resident"
    assert fits("wan22_i2v_low", 23.42) is True, "the refiner does fit a 24 GB card"
    assert fits("z_image_turbo", 15.92) is True, "Z-Image is 6.7 GiB and fits ethan"

    # T5-5: a quoted 23.4 with origin=measured is not a reading.
    peak = refine_peak("ltx25")
    assert peak["variant"] == "A", peak
    if peak.get("origin") == "measured":
        assert peak.get("n_samples", 0) >= 2, peak
        assert peak.get("host") and peak.get("date"), peak
        assert peak.get("same_as_base") is not True, peak
    else:
        assert peak.get("origin") == "not_measured", peak

    # IGNORED is a decision list, not a dumping ground: every entry carries a
    # reason, and nothing is both catalogued and ignored.
    for f, why in IGNORED.items():
        assert why and len(why) > 40, f"IGNORED[{f}] has no real reason"
    catalogued = {m["file"] for m in CATALOG.values() if m.get("file")}
    for m in CATALOG.values():
        catalogued |= set(m.get("companions") or {})
    both = catalogued & set(IGNORED)
    assert not both, f"catalogued AND ignored: {sorted(both)}"

    # every catalogue entry is complete -- a half-filled one renders a blank
    # "what is it for" in the UI, which is the whole point of the module
    for key, m in CATALOG.items():
        for field in ("role", "label", "file", "loader", "purpose", "notes",
                      "companions", "proven", "weights_gib"):
            assert m.get(field) is not None, f"{key} has no {field}"
        assert m["role"] in ROLES, f"{key} has unknown role {m['role']}"
        assert m["loader"] in LOADER_FIELD, f"{key} has unknown loader {m['loader']}"
        assert m["purpose"].strip(), f"{key} does not say what it is for"
        # A model arriving with no honest answer to "has this rendered anything
        # here" is the one that gets picked as a default and discovered later.
        assert m["proven"] in PROVEN, f"{key} claims proven={m['proven']!r}"

    # exactly one default per role that has one
    for role in ROLES:
        defaults = [k for k, m in CATALOG.items() if m["role"] == role and m.get("default")]
        assert len(defaults) <= 1, f"{role} has {len(defaults)} defaults"

    # availability against a stubbed object_info: present, absent, and unknown.
    # AudioEncoderLoader publishes the literal "COMBO" instead of a list, which
    # is exactly what the real box does -- and what once made an INSTALLED
    # wav2vec2 report as missing.
    fake = {
        "UNETLoader": {"input": {"required": {"unet_name": [
            ["qwen_image_edit_2511_fp8mixed.safetensors",
             "wan2.2_s2v_14B_fp8_scaled.safetensors"]]}}},
        "LoraLoaderModelOnly": {"input": {"required": {"lora_name": [
            ["Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"]]}}},
        "VAELoader": {"input": {"required": {"vae_name": [["qwen_image_vae.safetensors"]]}}},
        "AudioEncoderLoader": {"input": {"required": {"audio_encoder_name": ["COMBO"]}}},
    }
    have = installed(fake)
    assert have["AudioEncoderLoader"] is None, "a non-enumerable loader read as empty"
    assert have["CLIPLoader"] is None, "an absent node read as empty"

    got = {e["key"]: e for e in catalog(object_info=fake)}
    assert got["qwen_image_edit_2511"]["available"] is True
    assert got["wan22_s2v"]["available"] is True
    assert got["wan22_i2v"]["available"] is False, "claimed an uninstalled model was present"
    # genuinely absent companions are NAMED, not just counted: the fixture's
    # LoraLoaderModelOnly and VAELoader are both enumerable and both lack theirs
    assert sorted(got["wan22_s2v"]["missing"]) == [
        "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
        "wan_2.1_vae.safetensors"], got["wan22_s2v"]["missing"]
    # ...and one whose loader cannot be enumerated is NOT called missing
    assert "wav2vec2_large_english_fp16.safetensors" not in got["wan22_s2v"]["missing"]
    assert "umt5_xxl_fp8_e4m3fn_scaled.safetensors" not in got["wan22_s2v"]["missing"]

    # ComfyUI unreachable is "unknown", never "missing". Stubbed rather than
    # inferred from this box's network state, so the assertion means the same
    # thing on a laptop and on cerberus.
    global _object_info
    real = _object_info
    _object_info = lambda url=None: None
    try:
        assert installed() is None, "an unreachable ComfyUI reported an empty install"
        for e in catalog():
            assert e["available"] is None, e
            assert e["missing"] == [], e
            assert e["file_here"] is None, e
    finally:
        _object_info = real

    # role filtering
    assert {e["key"] for e in catalog(role="video", object_info=fake)} == {
        "wan22_s2v", "wan22_i2v", "ltx23", "ltx25"}
    # the default is the one the renderer gets told to use, and it must be a
    # value the renderer actually accepts -- these drifted apart once already
    assert default_for("video") == "ltx25"
    assert default_cli("video") == "ltx25"
    assert default_cli("video") in renderable("video").values()

    # Only models the renderer can actually be told to use carry a "cli" value.
    # A catalogued-but-unwired one (ltx23) must NOT reach the clip form -- the
    # song page used to map "anything that is not s2v" to i2v, so adding a third
    # video model would silently have rendered it as i2v.
    # EVERY catalogued model in a rendered role is wired. A model documented
    # here but not actually renderable is unfinished work, and there is no
    # honest way for the UI to offer it -- so the invariant is checked rather
    # than worked around.
    for key, m in CATALOG.items():
        if m["role"] in RENDERED_ROLES:
            assert m.get("cli"), (
                f"{key} is catalogued for the {m['role']} role but carries no cli value, "
                f"so nothing can render it. Wire it or remove it.")
            assert key in renderable(m["role"]), key
        else:
            assert not m.get("cli"), f"{key} has a cli value but {m['role']} has no renderer"

    # defaults: the marked one, then a remembered override, then rejection of junk
    # LTX is the default -- 2.5 since the upgrade; 2.3 measured ~50s for a real
    # clip against s2v's ~90s and stays catalogued as the fallback
    assert default_for("video") == "ltx25"
    set_default("video", "wan22_i2v")
    assert default_for("video") == "wan22_i2v"
    for bad, why in (("nonexistent_model", "unknown key"), ("qwen_image_edit_2511", "wrong role")):
        try:
            set_default("video", bad)
            raise AssertionError(f"set_default accepted {why}")
        except ValueError:
            pass
    # a stale setting pointing at something no longer catalogued falls back
    db.run("UPDATE settings SET value='deleted_model' WHERE key='model.video'")
    assert default_for("video") == "ltx25", "a stale setting wedged the role"

    # --- more than one box -------------------------------------------------
    # ALIASES exists because the SAME weights are spelled differently per box.
    # These fixtures are the real enums, trimmed: read from all three backends'
    # /object_info on 2026-08-12.
    cerberus = {
        "UNETLoader": {"input": {"required": {"unet_name": [
            ["qwen_image_edit_2511_fp8mixed.safetensors", "z_image_turbo_fp8mix.safetensors"]]}}},
        "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [
            ["ace_step_v1_3.5b.safetensors"]]}}},
        "VAELoader": {"input": {"required": {"vae_name": [
            ["ae.safetensors", "qwen_image_vae.safetensors"]]}}},
    }
    peaches = {
        "UNETLoader": {"input": {"required": {"unet_name": [
            ["z_image_turbo_fp8mix.safetensors", "flux-2-klein-4b-fp8.safetensors"]]}}},
        "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [
            ["ace_step_v1_3.5b_fp16.safetensors"]]}}},
        "VAELoader": {"input": {"required": {"vae_name": [
            ["z_image_ae.safetensors", "flux2-vae.safetensors"]]}}},
    }
    # The bug this whole section exists to stop: peaches HAS ACE-Step, and a
    # catalogue that only knows the cerberus spelling reports it missing on the
    # one box that is always on and can actually run it.
    assert resolve("ace_step_v1_3.5b.safetensors",
                   installed(peaches)["CheckpointLoaderSimple"]) == \
        "ace_step_v1_3.5b_fp16.safetensors"
    assert resolve("ae.safetensors", installed(peaches)["VAELoader"]) == "z_image_ae.safetensors"
    assert resolve("ae.safetensors", installed(cerberus)["VAELoader"]) == "ae.safetensors"
    assert resolve("ae.safetensors", installed(peaches)["UNETLoader"]) is None, \
        "resolved a VAE out of the UNET enum"
    assert resolve("nothing_has_this.safetensors", set()) is None
    assert resolve("anything", None) is None, "an unenumerable loader read as a hit"

    # AND THE OTHER DIRECTION, which is the one the live workflows ask from.
    # make_audio.py names the fp16 spelling deliberately, so asking "can
    # cerberus run this?" asks from the non-canonical end -- and until this was
    # symmetric the answer was None, i.e. "the box holding ACE-Step does not
    # have ACE-Step". ALIASES keys on one name for bookkeeping; the weights do
    # not know which one that is.
    assert resolve("ace_step_v1_3.5b_fp16.safetensors",
                   installed(cerberus)["CheckpointLoaderSimple"]) == \
        "ace_step_v1_3.5b.safetensors", "an alias group is only readable one way round"
    assert resolve("z_image_ae.safetensors",
                   installed(cerberus)["VAELoader"]) == "ae.safetensors"
    assert set(spellings("ace_step_v1_3.5b_fp16.safetensors")) == \
        set(spellings("ace_step_v1_3.5b.safetensors")), \
        "the same two files disagree about how many names they have"
    # the name you asked for still wins when a box holds both, or a retarget
    # would rewrite a filename that was already correct
    assert spellings("ae.safetensors")[0] == "ae.safetensors"
    assert resolve("z_image_ae.safetensors",
                   {"ae.safetensors", "z_image_ae.safetensors"}) == "z_image_ae.safetensors"
    assert spellings("unaliased.safetensors") == ("unaliased.safetensors",)

    # An encoder is not a renderer and must never be offered as one. It has no
    # cli by construction (encoder is not in RENDERED_ROLES, which the invariant
    # below already enforces), and it must not drift into the `vision` role,
    # where default_for would hand it to "review these frames" -- a job it
    # cannot do, because it emits features and never words.
    enc = CATALOG["siglip2_naflex"]
    assert enc["role"] == "encoder" and enc["role"] != "vision", enc["role"]
    assert not enc.get("cli") and not enc.get("default"), enc
    assert default_for("encoder") == "siglip2_naflex", default_for("encoder")
    # and the loader it names has to be one installed() can actually enumerate,
    # or the fleet page reports an installed encoder as missing everywhere
    assert enc["loader"] in LOADER_FIELD, enc["loader"]
    peaches_vis = {"CLIPVisionLoader": {"input": {"required": {"clip_name": [
        ["siglip2_so400m_patch16_naflex.safetensors"]]}}}}
    assert installed(peaches_vis)["CLIPVisionLoader"] == \
        {"siglip2_so400m_patch16_naflex.safetensors"}, "clip_vision is not enumerable"

    ace_there = next(e for e in catalog(object_info=peaches) if e["key"] == "ace_step_v1")
    assert ace_there["available"] is True, "the fp16 cast read as a missing model"
    assert ace_there["file_here"] == "ace_step_v1_3.5b_fp16.safetensors", (
        "available, but a workflow aimed at that box would still name the file it "
        "does not have")
    ace_here = next(e for e in catalog(object_info=cerberus) if e["key"] == "ace_step_v1")
    assert ace_here["file_here"] == "ace_step_v1_3.5b.safetensors"

    # a box is judged on dependability, not on speed or on what it holds
    assert backend_stability("http://100.107.235.105:8188")[0] == "opportunistic", \
        "the fastest box here is somebody's desktop"
    assert backend_stability("http://127.0.0.1:8188")[0] == "stable"

    # ONE BOX, ONE IDENTITY. The loopback and tailnet spellings of cerberus must
    # canonicalise to the same string, because docs/TRD-3 T3-1 groups artefacts
    # by `host` and two spellings report one box as two. Asserted through
    # canonical_host -- the shared entry point -- rather than through each
    # caller, so a caller that stops using it cannot stay green (the T1-20d
    # lesson, 2026-08-13).
    assert canonical_host("http://127.0.0.1:8188") == SELF_HOST
    assert canonical_host("localhost") == SELF_HOST
    assert canonical_host("http://100.103.148.120:8188") == SELF_HOST
    assert canonical_host("http://127.0.0.1:8188") == canonical_host(
        "http://100.103.148.120:8188"), "loopback and tailnet must be one box"
    # An unknown box stays unknown and is NOT rewritten to self.
    assert canonical_host("http://100.107.235.105:8188") == "100.107.235.105"
    assert canonical_host(None) is None and canonical_host("") is None
    # And the stability table must carry exactly one cerberus key, or the two
    # could drift apart again.
    assert sum(1 for h in BACKEND_STABILITY if canonical_host(h) == SELF_HOST) == 1, \
        "cerberus must appear once in BACKEND_STABILITY"
    assert backend_stability("http://10.0.0.99:8188") == UNKNOWN_BACKEND, \
        "an unlisted box was assumed dependable"
    assert backend_stability(None)[0] == "opportunistic"
    assert backend_stability("")[0] == "opportunistic"

    # by_backend/where over a stubbed fleet: one stable box with the canonical
    # spelling, one opportunistic box with the alias, one that does not answer.
    fleet = [{"id": "0", "title": "cerberus", "status": "running",
              "address": "http://127.0.0.1:8188"},
             {"id": "2", "title": "peaches", "status": "running",
              "address": "http://100.95.184.29:8188"},
             {"id": "9", "title": "ghost", "status": "running",
              "address": "http://10.0.0.99:8188"}]
    _object_info = lambda url=None: {"http://127.0.0.1:8188": cerberus,
                                     "http://100.95.184.29:8188": peaches}.get(url)
    global _system_stats
    real_stats = _system_stats
    # measured 2026-08-12 off each box's own /system_stats
    _system_stats = lambda url=None: {
        "http://127.0.0.1:8188": {"vram_gib": 23.42, "gpu": "RTX 5090 Laptop"},
        "http://100.95.184.29:8188": {"vram_gib": 10.58, "gpu": "RTX 2080 Ti"},
    }.get(url)
    try:
        rows = by_backend(fleet)
        assert [r["reachable"] for r in rows] == [True, True, False], rows
        assert rows[2]["models"], "an unreachable box lost the catalogue as well"
        assert all(e["available"] is None for e in rows[2]["models"]), \
            "a box that never answered reported models as missing"
        found = where("ace_step_v1", fleet)
        assert [r["id"] for r in found[:2]] == ["0", "2"], found
        assert found[0]["stability"] == "stable", "fallback did not put the always-on box first"
        assert [r["file_here"] for r in found[:2]] == [
            "ace_step_v1_3.5b.safetensors", "ace_step_v1_3.5b_fp16.safetensors"], found
        assert [r["confirmed"] for r in found[:2]] == [True, True]

        # UNKNOWN IS NOT MISSING. The ghost never answered, so it is a CANDIDATE
        # rather than a refusal -- listed, marked unconfirmed, and sorted last.
        # This conflation made where() answer "no box can run this" when the
        # truth was "the box I could not reach can", which is the worst direction
        # for the scheduler's capability contract to be wrong in. It is not
        # hypothetical: backend 0's Swarm address is 127.0.0.1:8188, so anything
        # querying from a box that is not cerberus cannot reach the stable box
        # that holds the models the others do not.
        ghost = where("qwen_image_edit_2511", [fleet[2]])
        assert len(ghost) == 1, "an unreachable box was reported as unable"
        assert ghost[0]["confirmed"] is False and ghost[0]["reachable"] is False, ghost
        mixed = where("qwen_image_edit_2511", fleet)
        assert [r["confirmed"] for r in mixed] == sorted(
            [r["confirmed"] for r in mixed], reverse=True), "unconfirmed sorted before confirmed"
        # a box that WAS asked and does not have it is still dropped
        assert all(r["id"] != "2" for r in where("qwen_image_edit_2511", fleet)), \
            "peaches answered and lacks the model, so it is a refusal, not an unknown"
        assert where("qwen_image_edit_2511", None) == []

        # INSTALLED and FITS are separate answers, and the 2080 Ti needs both.
        # 15.27 GiB of s2v weights do not go on a 10.58 GiB card -- that is
        # 1.44x, and no scheduling makes it resident. It is not a dtype problem:
        # fp8 runs on Turing, which is how peaches became the ACE-Step box.
        assert fits("wan22_s2v", 10.58) is False
        assert fits("wan22_i2v_low", 10.58) is False, "the REFINER does not fit either"
        assert fits("ace_step_v1", 10.58) is True
        assert fits("wan22_s2v", 23.42) is True
        # the i2v pair is one model: sized as both files, because both load
        assert fits("wan22_i2v", 23.42) is False, "13.31 x2 was sized as one file"
        assert fits("wan22_s2v", None) is None, "a box that never answered got a verdict"
        assert fits("no_such_model", 23.42) is None
        # a weights file is a FLOOR, never a peak: 2.3 is 21.86 on disk and was
        # measured peaking at 18.9 during a real render
        assert fits("ltx23", 23.42) is True

        peach_rows = by_backend([fleet[1]])[0]
        ace = next(e for e in peach_rows["models"] if e["key"] == "ace_step_v1")
        assert ace["available"] and ace["fits"], ace
        assert peach_rows["vram_gib"] == 10.58
    finally:
        _object_info = real
        _system_stats = real_stats

    print("models.py OK")


if __name__ == "__main__":
    demo()
