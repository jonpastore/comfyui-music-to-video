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

# Roles where a model has to be WIRED to a renderer before it can be chosen.
# A model in one of these is catalogued the moment it is worth documenting, but
# only becomes selectable once it carries a "cli" value naming what the renderer
# accepts -- see renderable(). Roles outside this set (storyboard, vision) are
# resolved by their own module at call time and have nothing to wire.
WIRED_ROLES = ("video", "artwork")

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
        "default": True,
        # the --video-model value build_song.py accepts. Absent = catalogued but
        # not renderable yet, so the clip form must not offer it.
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
        "label": "LTX-2.3 22B distilled (evaluation candidate -- NOT INSTALLED)",
        "file": "ltx-2.3-22b-distilled_transformer_only_fp8_scaled.safetensors",
        "loader": "UNETLoader",
        "purpose": (
            "Candidate replacement for the WAN video pass: reported at roughly 3x the speed "
            "for the same clip length, up to 1080p, and -- unlike i2v -- it has a NATIVE "
            "audio path, so it is the only alternative that could replace s2v without "
            "giving up beat sync and lip movement."),
        "notes": [
            "All 37 LTX node classes are ALREADY present on cerberus, including the audio "
            "path (LTXVAudioVAELoader / LTXVAudioVAEEncode / LTXVConcatAVLatent / "
            "LTXVReferenceAudio). Only the weights are missing -- same state ACE-Step is in.",
            "Audio is fused as a joint AV latent rather than bolted on, which is a different "
            "mechanism from s2v's wav2vec2 conditioning and has to be judged, not assumed.",
            "~9.5GB at FP4-mixed, or fp8 with offloading on a 24GB card. Offloading would "
            "eat the speed advantage, so the fp8-vs-fp4 choice is part of the test.",
            "UNVERIFIED for this pipeline: whether it can produce the exact 77-frame / "
            "4.8125s chunk the whole allocation is built on, and whether it holds character "
            "identity from a reference frame as well as the anchor+s2v path does.",
            "Needs ~30GB: transformer, gemma_3_12B text encoder, text projection, video VAE, "
            "audio VAE, taeltx2_3.safetensors (required by every LTX workflow).",
        ],
        "companions": {},
    },
    "wan22_i2v_low": {
        "role": "refine",
        "label": "WAN 2.2 I2V 14B low-noise (refiner pass)",
        "file": "Wan2.2/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
        "loader": "UNETLoader",
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
    """{catalogue key: the value the renderer accepts} for models in this role
    that are actually WIRED.

    A model can be catalogued before it is wired -- that is how an evaluation
    candidate is documented without pretending it works. Only entries with a
    "cli" value may be offered as a render choice; anything else would be
    submitted under some other model's name.
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


def set_default(role, key):
    if key not in CATALOG:
        raise ValueError(f"no such model: {key}")
    if CATALOG[key]["role"] != role:
        raise ValueError(f"{key} is a {CATALOG[key]['role']} model, not {role}")
    # A catalogued-but-unwired model has no renderer value, so making it the
    # default would set a preference the render form cannot honour -- it would
    # quietly fall back to whichever option the browser selected first.
    if role in WIRED_ROLES and not CATALOG[key].get("cli"):
        raise ValueError(f"{key} is catalogued for evaluation but not wired to the "
                          f"renderer yet, so it cannot be the default")
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
    assert renderable("video") == {"wan22_s2v": "s2v", "wan22_i2v": "i2v"}
    assert renderable("artwork") == {"qwen_artwork": "qwen"}
    for key, m in CATALOG.items():
        if m.get("cli"):
            assert m["role"] in WIRED_ROLES, f"{key} has a cli value but {m['role']} has no renderer"
        elif m["role"] in WIRED_ROLES:
            # catalogued for evaluation only -- must not be selectable as a
            # render choice or made the default
            assert key not in renderable(m["role"])

    # defaults: the marked one, then a remembered override, then rejection of junk
    assert default_for("video") == "wan22_s2v"
    set_default("video", "wan22_i2v")
    assert default_for("video") == "wan22_i2v"
    for bad, why in (("nonexistent_model", "unknown key"), ("qwen_image_edit_2511", "wrong role"),
                     ("ltx23", "catalogued but not wired to the renderer")):
        try:
            set_default("video", bad)
            raise AssertionError(f"set_default accepted {why}")
        except ValueError:
            pass
    # a stale setting pointing at something no longer catalogued falls back
    db.run("UPDATE settings SET value='deleted_model' WHERE key='model.video'")
    assert default_for("video") == "wan22_s2v", "a stale setting wedged the role"

    print("models.py OK")


if __name__ == "__main__":
    demo()
