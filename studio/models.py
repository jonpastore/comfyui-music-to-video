"""The model catalogue: what is installed, and what each one is FOR.

Three model families were named as string literals inside build_refs.py,
build_song.py and make_anchor.py. Adding the wan2.2 i2v pair meant editing
Python, and nothing anywhere said what a given model was designed for -- so
"which model renders the clips" was a question you answered by reading source.

This module is the answer instead. Each entry is data: a role, a label, the
file, the loader class it goes into, one line on what it is for, and the
caveats that cost this project time to learn. Adding a model later is one dict
entry plus whatever workflow support it needs; it is never a UI change.

AVAILABILITY IS NOT ASSUMED. It is read from the live ComfyUI /object_info --
the same enum the loader node would validate against -- so a catalogued model
that is not on the box shows as missing in the UI instead of failing forty
minutes into a render. Chat models come from grok.list_models() for the same
reason.
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
}

CATALOG = {
    "qwen_image_edit_2511": {
        "role": "reference",
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
        "label": "WAN 2.2 S2V 14B (sound to video)",
        "file": "wan2.2_s2v_14B_fp8_scaled.safetensors",
        "loader": "UNETLoader",
        # the --video-model value build_song.py accepts
        "cli": "s2v",
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
        "label": "WAN 2.2 I2V 14B (image to video, high+low noise)",
        "file": "Wan2.2/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        "loader": "UNETLoader",
        "cli": "i2v",
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
    "ltx23": {
        "role": "video",
        "label": "LTX-2.3 22B distilled (audio-conditioned, ~2x faster)",
        "file": "ltx-2.3-22b-distilled_transformer_only_fp8_scaled.safetensors",
        "loader": "UNETLoader",
        "cli": "ltx",
        "default": True,
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
        ],
        "companions": {"wan_2.1_vae.safetensors": "VAELoader"},
    },
    "qwen_artwork": {
        "role": "artwork",
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
    "ace_step_v1": {
        "role": "audio",
        "label": "ACE-Step v1 3.5B",
        "file": "ace_step_v1_3.5b.safetensors",
        "loader": "CheckpointLoaderSimple",
        "default": True,
        "cli": "ace_step",
        "purpose": (
            "Generative audio. The deterministic editor (ffmpeg) can only trim the ENDS of "
            "a track; cutting from the middle needs this."),
        "notes": [
            "It RE-SYNTHESISES the region rather than removing it, so the result is new "
            "audio, not a shorter original. The UI must say which path ran.",
            "Downloaded and the nodes are present, but no workflow is written yet.",
        ],
        "companions": {},
    },
}


# /object_info is a large response and it is asked for on every page that names
# a model. Installed models change when someone copies a file onto the box, not
# per request, so a short cache keeps a page render from waiting on the network
# each time -- including the OBJECT_INFO_TIMEOUT wait when ComfyUI is down.
_CACHE_TTL = 30.0
_cache = {"at": 0.0, "info": None, "fetched": False}


def _object_info():
    """The live node/model listing, or None if ComfyUI could not be asked.

    FAILURES are cached too, and deliberately: a down ComfyUI would otherwise
    make every page that names a model pay the connection attempt -- up to
    OBJECT_INFO_TIMEOUT each, on a filtered network -- which turns one dead
    service into a studio that appears to hang.
    """
    now = time.monotonic()
    if _cache["fetched"] and now - _cache["at"] < _CACHE_TTL:
        return _cache["info"]
    try:
        with urllib.request.urlopen(f"{COMFY}/object_info", timeout=OBJECT_INFO_TIMEOUT) as r:
            info = json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError):
        # ComfyUI being down is not an error here: the catalogue still lists what
        # each model is for, availability just reads "unknown" instead of a lie
        # in either direction.
        info = None
    _cache.update(at=now, info=info, fetched=True)
    return info


def installed(object_info=None):
    """{loader_class: {filenames} | None} as ComfyUI itself reports them, or None.

    Three distinct answers, and conflating any two of them produces a wrong
    signal in a direction that matters:

      None (the whole dict)  ComfyUI could not be asked.
      None (one loader)      that loader does not publish an enumerable list.
                             AudioEncoderLoader reports the literal "COMBO"
                             rather than filenames, and treating that as an
                             empty set reported wav2vec2 -- which IS installed --
                             as missing. A false "missing" sends you hunting for
                             a file that is already there.
      set()                  asked, enumerable, and genuinely nothing installed.
    """
    info = object_info if object_info is not None else _object_info()
    if info is None:
        return None
    out = {}
    for loader, field in LOADER_FIELD.items():
        node = info.get(loader) or {}
        spec = (node.get("input", {}).get("required", {}) or {}).get(field)
        # spec[0] is the enum list for a normal combo; anything else (the string
        # "COMBO", a missing node) means it cannot be enumerated from here
        out[loader] = set(spec[0]) if spec and isinstance(spec[0], list) else None
    return out


def catalog(role=None, object_info=None):
    """The catalogue, annotated with what is actually on the box.

    `available` is True/False when ComfyUI answered and None when it did not,
    or when that loader publishes no enumerable list.

    `missing` names the companion files a model needs that are genuinely absent
    -- an entry whose LoRA is missing renders, badly, at the wrong step count,
    which is far worse than refusing. A companion whose loader cannot be
    enumerated is NOT listed: unknown is not missing.
    """
    have = installed(object_info)
    out = []
    for key, m in CATALOG.items():
        if role and m["role"] != role:
            continue
        entry = dict(m, key=key, role_label=ROLES.get(m["role"], m["role"]))
        if have is None:
            entry["available"], entry["missing"] = None, []
        else:
            pool = have.get(m["loader"])
            entry["available"] = None if pool is None else (m["file"] in pool)
            entry["missing"] = [name for name, loader in m["companions"].items()
                                if have.get(loader) is not None and name not in have[loader]]
        out.append(entry)
    return out


def get(key):
    return CATALOG.get(key)


def renderable(role):
    """{catalogue key: the value the renderer accepts} for this role.

    Every catalogued model in a RENDERED_ROLE has a "cli" value, so this is the
    whole role -- it exists to map catalogue keys onto what the script expects,
    not to filter out models that were never finished.
    """
    return {k: m["cli"] for k, m in CATALOG.items() if m["role"] == role and m.get("cli")}


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

    # every catalogue entry is complete -- a half-filled one renders a blank
    # "what is it for" in the UI, which is the whole point of the module
    for key, m in CATALOG.items():
        for field in ("role", "label", "file", "loader", "purpose", "notes", "companions"):
            assert m.get(field) is not None, f"{key} has no {field}"
        assert m["role"] in ROLES, f"{key} has unknown role {m['role']}"
        assert m["loader"] in LOADER_FIELD, f"{key} has unknown loader {m['loader']}"
        assert m["purpose"].strip(), f"{key} does not say what it is for"

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
    _object_info = lambda: None
    try:
        assert installed() is None, "an unreachable ComfyUI reported an empty install"
        for e in catalog():
            assert e["available"] is None, e
            assert e["missing"] == [], e
    finally:
        _object_info = real

    # role filtering
    assert {e["key"] for e in catalog(role="video", object_info=fake)} == {
        "wan22_s2v", "wan22_i2v", "ltx23"}

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
    # LTX is the default: measured at ~50s for a real clip against s2v's ~90s
    assert default_for("video") == "ltx23"
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
    assert default_for("video") == "ltx23", "a stale setting wedged the role"

    print("models.py OK")


if __name__ == "__main__":
    demo()
