#!/usr/bin/env python3
"""Build ComfyUI API workflows for one song-version of a Meow P music video.

Reads a storyboard JSON (scenes with image_prompt / video_motion_prompt /
negative_prompt / duration_guidance) and emits one WAN 2.2 S2V workflow per
4.8125s clip, covering the whole track.

Clips are allocated to scenes in proportion to each scene's duration_guidance,
because the guidance describes a single shot per scene and always totals far
less than the song; the ratio is what carries the pacing intent.

usage:
  build_song.py --storyboard rear_entrance_explicit.json \
                --audio "Rear Entrance .mp3" \
                --slug rear_entrance --outdir ~/shots/rear_entrance_explicit
"""
import argparse, json, math, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardrail  # noqa: E402  (applied here, NOT stored in the storyboard)

FPS = 16.0
LEN = 77                 # WAN 2.2 S2V chunk; needs >= 73
CHUNK = LEN / FPS        # 4.8125s
W, H = 832, 480          # 16:9, divisible by 16


def sname(scene):
    """Scene title. Albums disagree on the key: 'name' vs 'scene_name'."""
    return scene.get("name") or scene.get("scene_name") or f"scene {scene['scene_number']}"


def normalize(sb):
    """Map the compact '*_comfy.json' schema onto the keys the builders read.

    That schema names scenes id/section/chunks/prompt and puts the negative at
    the top level as 'negative'. 'chunks' is an explicit clip count per scene,
    so feeding it to duration_guidance makes allocate() reproduce the author's
    intended pacing instead of inferring it.
    """
    for n, s in enumerate(sb.get("scenes", []), 1):
        s.setdefault("scene_number", s.get("id", n))
        s.setdefault("name", s.get("section", f"scene {n}"))
        s.setdefault("image_prompt", s.get("prompt", ""))
        s.setdefault("camera", "")
        if "duration_guidance" not in s and "chunks" in s:
            s["duration_guidance"] = f"{s['chunks']} sec"
    # Strip any guardrail baked into the scene text. It belongs in code now, and
    # leaving a legacy copy in the prompt both duplicates it and trips the minor
    # filter on its own "no children ..." wording.
    embedded = sb.get("global_guardrail", "")
    for s_ in sb.get("scenes", []):
        for f in ("image_prompt", "story", "video_motion_prompt"):
            if s_.get(f):
                s_[f] = guardrail.strip(s_[f], embedded)
    sb.pop("global_guardrail", None)
    # Negative prompts are inert at cfg 1.0 (ComfyUI skips the negative pass),
    # so nothing is gained by carrying them and they only restate policy.
    sb.pop("global_negative_prompt", None)
    sb.pop("negative", None)
    for s_ in sb.get("scenes", []):
        s_.pop("negative_prompt", None)

    sb.setdefault("character_reference", sb.get("style_lock", ""))
    sb.setdefault("album_world_reference", sb.get("style_lock", ""))
    return sb


# Framing only lands if it is an imperative at the FRONT of the prompt. Left
# mid-prompt as "Camera: detail close" it is ignored and every frame comes back
# as the same centered full-body walk -- measured, not assumed.
SHOT_RULES = [  # (substring, directive) -- first match wins, so specific first
    ("macro",        "EXTREME CLOSE-UP MACRO SHOT. Tight framing on a single detail, shallow depth of field, background heavily blurred, no full body in frame."),
    ("detail",       "EXTREME CLOSE-UP SHOT. Tight framing on hands, face or object detail, shallow depth of field, no full body in frame."),
    ("tight",        "EXTREME CLOSE-UP SHOT. Tight framing, shallow depth of field, no full body in frame."),
    ("over-shoulder","OVER-THE-SHOULDER SHOT. Camera behind her shoulder, her back and shoulder framing one side, the scene ahead in focus."),
    ("over shoulder","OVER-THE-SHOULDER SHOT. Camera behind her shoulder, her back and shoulder framing one side, the scene ahead in focus."),
    ("close",        "CLOSE-UP SHOT. Head and shoulders fill the frame, shallow depth of field."),
    ("top-down",     "HIGH-ANGLE OVERHEAD SHOT looking straight down, floor and layout dominant, figures small below."),
    ("overhead",     "HIGH-ANGLE OVERHEAD SHOT looking down from above."),
    ("crowd pov",    "POV SHOT FROM INSIDE THE CROWD, heads and raised hands in the foreground, stage beyond."),
    ("pov",          "FIRST-PERSON POV SHOT, foreground hands or frame edges visible."),
    ("low",          "EXTREME LOW-ANGLE SHOT from ground level looking up, subject towering, ceiling or sky visible."),
    ("crane",        "SWEEPING HIGH CRANE SHOT, camera far above and moving, whole space visible."),
    ("orbit",        "THREE-QUARTER REAR ANGLE SHOT from her side and slightly behind, subject off-centre, background sweeping wide behind her."),
    ("rear",         "TRACKING SHOT FROM BEHIND, following her back as she moves away down the space."),
    ("follow",       "TRACKING SHOT FROM BEHIND, following her as she moves through the space."),
    ("tilt up",      "LOW TILT-UP SHOT rising from floor level to reveal the subject and the space above."),
    ("pullback",     "SLOW PULLBACK SHOT, camera retreating, subject receding into a widening frame."),
    ("long lens",    "LONG-LENS COMPRESSED SHOT from far away, flattened perspective, surveillance feel."),
    ("push",         "SLOW PUSH-IN SHOT, camera advancing toward the subject, medium framing tightening."),
    ("dolly",        "SIDE-ON PROFILE SHOT. Subject in profile moving laterally across the frame, placed off-centre, foreground pipes and fencing sliding past."),
    ("medium hero",  "MEDIUM HERO SHOT from the waist up, subject centered and dominant."),
    ("medium",       "MEDIUM SHOT from the waist up."),
    ("wide",         "VERY WIDE ESTABLISHING SHOT. Subject small and distant, the environment dominates the frame."),
]

# Used when the storyboard's camera text is boilerplate that carries no framing
# (hundreds of scenes share two such strings). Rotating by clip index is what
# stops a whole song rendering as one repeated shot.
SHOT_CYCLE = [
    "VERY WIDE ESTABLISHING SHOT. Subject small and distant, the environment dominates the frame.",
    "EXTREME CLOSE-UP SHOT. Tight framing on hands or face, shallow depth of field, no full body in frame.",
    "EXTREME LOW-ANGLE SHOT from ground level looking up, subject towering above the camera.",
    "OVER-THE-SHOULDER SHOT. Camera behind her shoulder, the scene ahead in focus.",
    "HIGH-ANGLE OVERHEAD SHOT looking down, floor and layout dominant.",
    "MEDIUM HERO SHOT from the waist up, subject centered and dominant.",
    "ORBITING SIDE SHOT circling the subject, background sweeping past.",
    "TRACKING SHOT FROM BEHIND, following her through the space.",
]

GENERIC_CAMERA = ("depending on musical energy", "complementary angle")


def shot_directive(scene, i):
    cam = (scene.get("camera") or "").strip().lower()
    if not cam or any(g in cam for g in GENERIC_CAMERA):
        return SHOT_CYCLE[i % len(SHOT_CYCLE)]
    for key, directive in SHOT_RULES:
        # whole-word match: plain substring makes "slow push" hit the "low" rule
        if re.search(r"\b" + re.escape(key) + r"\b", cam):
            return directive
    return SHOT_CYCLE[i % len(SHOT_CYCLE)]


def audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def guidance_seconds(s):
    """Midpoint of a '5-8 sec' style guidance string.

    Decimals are read as decimals. An integer-only \\d+ split "6.4 sec" into 6
    and 4 and returned their midpoint, 5.0 -- so a storyboard whose scene
    lengths are computed rather than hand-written got weights that were wrong,
    silently, in whichever direction the fraction fell ("7.0 sec" -> 3.5). Every
    board written by grok uses whole-second ranges, which is why this never
    showed: those parse identically either way.
    """
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s.get("duration_guidance", ""))]
    return sum(nums) / len(nums) if nums else 6.0


def allocate(scenes, nclips):
    """Clips per scene, proportional to guidance, every scene getting >= 1."""
    w = [guidance_seconds(s) for s in scenes]
    total = sum(w)
    exact = [x / total * nclips for x in w]
    counts = [max(1, int(math.floor(e))) for e in exact]
    # hand out the remainder to the scenes with the largest fractional loss
    while sum(counts) < nclips:
        i = max(range(len(counts)), key=lambda k: exact[k] - counts[k])
        counts[i] += 1
    while sum(counts) > nclips:
        i = max(range(len(counts)), key=lambda k: counts[k] - exact[k])
        if counts[i] > 1:
            counts[i] -= 1
        else:  # everything is at the floor already
            break
    return counts


def clip_plan(scenes, audio_path=None, nclips=None):
    """[(clip_index, scene, shot_directive)] for every clip in the song.

    THE definition of which clip belongs to which scene. build_refs.py,
    build_song.py and reroll_refs.py all need the identical mapping, and it used
    to be copied into all three -- reroll_refs even carried the comment "rebuild
    clip -> (scene, shot) exactly as build_refs --audio did". If the copies ever
    drifted, re-rolling clip 17 would silently regenerate a different scene than
    the one you rejected, which is the kind of bug nobody traces back to an
    allocation loop.

    `nclips` skips the ffprobe when the caller already knows the count -- the
    studio's web layer renders this on every page view and has the duration in
    the songs row. It is an ALTERNATIVE INPUT, not a second implementation:
    everything below is still the one allocation.
    """
    if nclips is None:
        nclips = math.ceil(audio_duration(audio_path) / CHUNK)
    counts = allocate(scenes, nclips)
    plan, i = [], 0
    for scene, n in zip(scenes, counts):
        for _ in range(n):
            plan.append((i, scene, shot_directive(scene, i)))
            i += 1
    return plan


# The two video paths. s2v is the default and the only one driven by the audio;
# see studio/models.py for what each is designed for.
S2V_MODEL = "wan2.2_s2v_14B_fp8_scaled.safetensors"
I2V_HIGH = "Wan2.2/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
I2V_LOW = "Wan2.2/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"
LIGHTX2V_LORA = "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors"

# Wan 2.2's two experts are one model split at a denoise boundary of 0.900: the
# high-noise expert lays down motion and structure, the low-noise one refines.
# With STEPS_I2V total steps the switch lands at this step index.
STEPS_I2V = 8
I2V_BOUNDARY = 0.900
I2V_SWITCH = max(1, round(STEPS_I2V * (1.0 - I2V_BOUNDARY)))

# The optional refiner pass over an s2v clip: re-sample at low denoise with the
# i2v low-noise expert. UNPROVEN -- both share wan_2.1_vae so the latents are
# compatible, but nothing has measured whether it helps. Off by default.
REFINE_DENOISE = 0.25
REFINE_STEPS = 6


# ---- LTX-2.3 -------------------------------------------------------------
# A second video family, measured on this box rather than assumed: 81 frames at
# 832x480 in 45s against WAN s2v's ~90s, peak 18.9 GB of 24.4 GB.
LTX_MODEL = "ltx-2.3-22b-distilled_transformer_only_fp8_scaled.safetensors"
LTX_TEXT_ENCODER = "gemma_3_12B_it_fp4_mixed.safetensors"
# LTXAVTextEncoderLoader reads ckpt_name from models/checkpoints/, NOT from
# text_encoders/ -- the text projection has to live there or the node refuses.
LTX_TEXT_PROJECTION = "ltx-2.3_text_projection_bf16.safetensors"
LTX_VIDEO_VAE = "LTX23_video_vae_bf16.safetensors"
LTX_AUDIO_VAE = "LTX23_audio_vae_bf16.safetensors"

# LTX latent length must be 8n+1 (the node declares min 9, step 8), so the
# pipeline's 77 frames is NOT a legal value. 81 is, and at 16.8312 fps it is
# exactly CHUNK -- which is what keeps the clip allocation identical across
# models. Changing CHUNK per model would change the clip count, and every
# already-approved reference frame is keyed to a clip index.
LTX_LEN = 81
LTX_FPS = LTX_LEN / CHUNK          # 16.8312...
LTX_STEPS = 8
LTX_MAX_SHIFT, LTX_BASE_SHIFT = 2.05, 0.95


# ---- LTX-2.5 -------------------------------------------------------------
# NOT a retarget of the 2.3 constants: 2.5 changed the graph, not just the
# weights, and every difference below was read off ComfyUI's own shipped
# template (Comfy-Org/workflow_templates video_ltx2_5_i2v.json) rather than
# guessed at.
#
#   - the text encoder loads through a PLAIN CLIPLoader with type "ltxv".
#     2.3 needed LTXAVTextEncoderLoader because its projection was a second
#     file in checkpoints/; 2.5's encoder is "with-proj" -- the projection is
#     baked in and there is no second file.
#   - the audio VAE loads through a plain VAELoader, not LTXVAudioVAELoader,
#     so it does NOT need to sit in checkpoints/ the way 2.3's did.
#   - sampling is SamplerCustomAdvanced + LTXVDualCFGGuider + ManualSigmas,
#     not SamplerCustom + LTXVScheduler, and there is no ModelSamplingLTXV.
LTX25_MODEL = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
# The nvfp4 build is downloaded alongside it (17.4 GiB against 20.03) as the
# fallback for the 24 GB laptop card. Swap LTX25_MODEL to it if int8 will not fit.
LTX25_MODEL_NVFP4 = "ltx-2.5-22b-distilled-transformer-nvfp4.safetensors"
LTX25_TEXT_ENCODER = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
LTX25_VIDEO_VAE = "ltx-2.5-video-vae-bf16.safetensors"
LTX25_AUDIO_VAE = "ltx-2.5-audio-vae-bf16.safetensors"

# Verbatim from the template's stage-1 schedule: 9 values, so 8 steps, and it
# already terminates at 0.0. The template splits the render into a half-res base
# pass and an upsampled refine pass; this pipeline renders once at W x H, which
# is what the 2.3 path measured at and what keeps clip timing comparable.
LTX25_SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
LTX25_IMG_COMPRESSION = 18       # LTXVPreprocess, template value
LTX25_VIDEO_CFG = LTX25_AUDIO_CFG = 1.0

# Same 8n+1 latent rule as 2.3, so the same 81 frames at 16.8312 fps: exactly
# one CHUNK. The clip allocation must not move -- every approved reference frame
# is keyed to a clip index.
LTX25_LEN = LTX_LEN
LTX25_FPS = LTX_FPS


def ltx25_workflow(i, scene, ref_image, audio_file, char_lock, world_lock, guard, with_audio=True):
    """LTX-2.5, the audio-conditioned path -- same contract as ltx_workflow.

    The audio is encoded from the master mp3 and fused as a joint AV latent so
    it conditions the MOTION; only the video half is decoded, because the mp3 is
    laid over the assembled timeline once and per-clip audio would otherwise
    drift. That is unchanged from 2.3. What changed is the node graph; see the
    constants above.
    """
    motion = scene.get("video_motion_prompt") or scene.get("motion", "")
    pos = (f"{shot_directive(scene, i)} {char_lock} {world_lock} Motion: {motion} "
           f"Camera: {scene.get('camera','')} Lighting: {scene.get('lighting','')}")
    pos = guardrail.build_prompt(pos, guard, f"scene {i}")
    start = round(i * CHUNK, 4)

    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": LTX25_MODEL,
                                                      "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": LTX25_TEXT_ENCODER, "type": "ltxv", "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": pos}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": scene.get("negative_prompt", "")}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": LTX25_VIDEO_VAE}},
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": LTX25_AUDIO_VAE}},
        "7": {"class_type": "LoadImage", "inputs": {"image": ref_image}},
        "8": {"class_type": "ImageScale", "inputs": {
            "image": ["7", 0], "upscale_method": "lanczos", "width": W, "height": H,
            "crop": "center"}},
        # 2.5 puts a compression preprocess in front of the conditioning image;
        # the template runs it on every path, including i2v.
        "9": {"class_type": "LTXVPreprocess", "inputs": {
            "image": ["8", 0], "img_compression": LTX25_IMG_COMPRESSION}},
        "10": {"class_type": "EmptyLTXVLatentVideo", "inputs": {
            "width": W, "height": H, "length": LTX25_LEN, "batch_size": 1}},
        # strength 1.0, not the template's 0.7: that 0.7 belongs to its half-res
        # base pass. Here the approved reference frame IS the first frame, which
        # is the whole mechanism carrying the character into the clip.
        "11": {"class_type": "LTXVImgToVideoInplace", "inputs": {
            "vae": ["5", 0], "image": ["9", 0], "latent": ["10", 0],
            "strength": 1.0, "bypass": False}},
        "12": {"class_type": "LTXVConditioning", "inputs": {
            "positive": ["3", 0], "negative": ["4", 0], "frame_rate": round(LTX25_FPS, 4)}},
    }

    latent = ["11", 0]
    if with_audio:
        wf["13"] = {"class_type": "LoadAudio", "inputs": {"audio": audio_file}}
        wf["14"] = {"class_type": "TrimAudioDuration", "inputs": {
            "audio": ["13", 0], "start_index": start, "duration": round(CHUNK, 4)}}
        wf["15"] = {"class_type": "LTXVAudioVAEEncode", "inputs": {
            "audio": ["14", 0], "audio_vae": ["6", 0]}}
        wf["16"] = {"class_type": "LTXVConcatAVLatent", "inputs": {
            "video_latent": ["11", 0], "audio_latent": ["15", 0]}}
        latent = ["16", 0]

    # DualCFGGuider takes both halves of LTXVConditioning: slot 0 positive,
    # slot 1 negative.
    wf["17"] = {"class_type": "LTXVDualCFGGuider", "inputs": {
        "model": ["1", 0], "positive": ["12", 0], "negative": ["12", 1],
        "video_cfg": LTX25_VIDEO_CFG, "audio_cfg": LTX25_AUDIO_CFG}}
    wf["18"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral"}}
    wf["19"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": LTX25_SIGMAS}}
    wf["20"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": 1000 + i}}
    wf["21"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
        "noise": ["20", 0], "guider": ["17", 0], "sampler": ["18", 0],
        "sigmas": ["19", 0], "latent_image": latent}}

    if with_audio:
        wf["22"] = {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["21", 0]}}
        sampled = ["22", 0]
    else:
        sampled = ["21", 0]

    wf["23"] = {"class_type": "VAEDecode", "inputs": {"samples": sampled, "vae": ["5", 0]}}
    wf["24"] = {"class_type": "CreateVideo", "inputs": {
        "images": ["23", 0], "fps": round(LTX25_FPS, 4)}}
    return wf


def ltx_workflow(i, scene, ref_image, audio_file, char_lock, world_lock, guard, with_audio=True):
    """LTX-2.3, the audio-conditioned path.

    Audio is fused as a JOINT AV LATENT (LTXVConcatAVLatent) rather than
    cross-attended like WAN s2v's wav2vec2 conditioning -- a different mechanism
    for the same purpose, which is why it had to be measured rather than
    assumed. The sampled latent is split again and only the VIDEO half is
    decoded: this pipeline lays the master mp3 over the assembled timeline once,
    so per-clip audio cannot drift. The audio still CONDITIONS the motion, which
    is the whole reason for using this path over plain i2v.
    """
    motion = scene.get("video_motion_prompt") or scene.get("motion", "")
    pos = (f"{shot_directive(scene, i)} {char_lock} {world_lock} Motion: {motion} "
           f"Camera: {scene.get('camera','')} Lighting: {scene.get('lighting','')}")
    pos = guardrail.build_prompt(pos, guard, f"scene {i}")
    start = round(i * CHUNK, 4)

    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": LTX_MODEL,
                                                      "weight_dtype": "default"}},
        "2": {"class_type": "ModelSamplingLTXV", "inputs": {
            "model": ["1", 0], "max_shift": LTX_MAX_SHIFT, "base_shift": LTX_BASE_SHIFT}},
        "3": {"class_type": "LTXAVTextEncoderLoader", "inputs": {
            "text_encoder": LTX_TEXT_ENCODER, "ckpt_name": LTX_TEXT_PROJECTION,
            "device": "default"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": pos}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": ""}},
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": LTX_VIDEO_VAE}},
        "7": {"class_type": "LoadImage", "inputs": {"image": ref_image}},
        "8": {"class_type": "ImageScale", "inputs": {
            "image": ["7", 0], "upscale_method": "lanczos", "width": W, "height": H,
            "crop": "center"}},
        # the approved reference frame is the first frame, exactly as ref_image
        # is for s2v -- it is what carries the character into the clip
        "9": {"class_type": "LTXVImgToVideo", "inputs": {
            "positive": ["4", 0], "negative": ["5", 0], "vae": ["6", 0],
            "image": ["8", 0], "width": W, "height": H, "length": LTX_LEN,
            "batch_size": 1, "strength": 1.0}},
        "10": {"class_type": "LTXVConditioning", "inputs": {
            "positive": ["9", 0], "negative": ["9", 1], "frame_rate": round(LTX_FPS, 4)}},
        "11": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "12": {"class_type": "LTXVScheduler", "inputs": {
            "steps": LTX_STEPS, "max_shift": LTX_MAX_SHIFT, "base_shift": LTX_BASE_SHIFT,
            "stretch": True, "terminal": 0.1, "latent": ["9", 2]}},
    }

    latent = ["9", 2]
    if with_audio:
        wf["13"] = {"class_type": "LTXVAudioVAELoader", "inputs": {"ckpt_name": LTX_AUDIO_VAE}}
        wf["14"] = {"class_type": "LoadAudio", "inputs": {"audio": audio_file}}
        wf["15"] = {"class_type": "TrimAudioDuration", "inputs": {
            "audio": ["14", 0], "start_index": start, "duration": round(CHUNK, 4)}}
        wf["16"] = {"class_type": "LTXVAudioVAEEncode", "inputs": {
            "audio": ["15", 0], "audio_vae": ["13", 0]}}
        wf["17"] = {"class_type": "LTXVConcatAVLatent", "inputs": {
            "video_latent": ["9", 2], "audio_latent": ["16", 0]}}
        latent = ["17", 0]

    wf["18"] = {"class_type": "SamplerCustom", "inputs": {
        "model": ["2", 0], "add_noise": True, "noise_seed": 1000 + i, "cfg": 1.0,
        "positive": ["10", 0], "negative": ["10", 1], "sampler": ["11", 0],
        "sigmas": ["12", 0], "latent_image": latent}}

    if with_audio:
        # split the joint latent and keep the VIDEO half. The audio half is
        # discarded on purpose -- the master mp3 is laid over the assembled
        # timeline once, which is what stops per-clip audio drifting.
        wf["19"] = {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["18", 0]}}
        sampled = ["19", 0]
    else:
        sampled = ["18", 0]

    wf["20"] = {"class_type": "VAEDecode", "inputs": {"samples": sampled, "vae": ["6", 0]}}
    # silent, and at the fps that makes LTX_LEN frames last exactly CHUNK
    wf["21"] = {"class_type": "CreateVideo", "inputs": {
        "images": ["20", 0], "fps": round(LTX_FPS, 4)}}
    return wf


def workflow(i, scene, ref_image, audio_file, char_lock, world_lock, guard,
             video_model="s2v", ref_motion=None, control_video=None, refine=False):
    """Same rule as build_refs.workflow: the pinned clause is attached HERE, at
    the point the prompt is built, not read out of the storyboard JSON.

    video_model:
      "s2v"  WanSoundImageToVideo -- the prompt, the reference frame AND this
             clip's 4.8125s of audio. The only path with beat sync and mouth
             movement, which is why it is the default.
      "i2v"  WanImageToVideo with the high->low expert pair. No audio input at
             all: prompt-driven motion only.

    ref_motion / control_video are s2v's two optional inputs, unused until now:
    a motion-style reference clip, and a driving clip for pose or structure.

    refine=True adds a low-denoise second pass with the i2v low-noise expert.
    """
    motion = scene.get("video_motion_prompt") or scene.get("motion", "")
    pos = f"{shot_directive(scene, i)} {char_lock} {world_lock} Motion: {motion} Camera: {scene.get('camera','')} Lighting: {scene.get('lighting','')}"
    pos = guardrail.build_prompt(pos, guard, f"scene {i}")
    neg = scene.get("negative_prompt", "")
    start = round(i * CHUNK, 4)

    if video_model in ("ltx", "ltx25"):
        # a separate builder per family: LTX shares none of WAN's node graph, and
        # 2.5 shares little enough of 2.3's that folding them together would put
        # branches everywhere -- which is how all three end up subtly wrong.
        build = ltx25_workflow if video_model == "ltx25" else ltx_workflow
        return build(i, scene, ref_image, audio_file, char_lock, world_lock, guard)

    wf = {
        "4":  {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "5":  {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": pos}},
        "6":  {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": neg}},
        "7":  {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "12": {"class_type": "LoadImage", "inputs": {"image": ref_image}},
        "13": {"class_type": "ImageScale", "inputs": {"image": ["12", 0], "upscale_method": "lanczos", "width": W, "height": H, "crop": "center"}},
    }

    if video_model == "i2v":
        # two experts, two KSamplerAdvanced stages, one latent handed between
        # them. add_noise=disable on the second: the noise is already there.
        wf["1"] = {"class_type": "UNETLoader", "inputs": {"unet_name": I2V_HIGH, "weight_dtype": "default"}}
        wf["2"] = {"class_type": "UNETLoader", "inputs": {"unet_name": I2V_LOW, "weight_dtype": "default"}}
        wf["3"] = {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 8.0}}
        wf["3b"] = {"class_type": "ModelSamplingSD3", "inputs": {"model": ["2", 0], "shift": 8.0}}
        wf["14"] = {"class_type": "WanImageToVideo", "inputs": {
            "positive": ["5", 0], "negative": ["6", 0], "vae": ["7", 0],
            "width": W, "height": H, "length": LEN, "batch_size": 1,
            "start_image": ["13", 0]}}
        wf["15"] = {"class_type": "KSamplerAdvanced", "inputs": {
            "model": ["3", 0], "add_noise": "enable", "noise_seed": 1000 + i,
            "steps": STEPS_I2V, "cfg": 1.0, "sampler_name": "uni_pc", "scheduler": "simple",
            "positive": ["14", 0], "negative": ["14", 1], "latent_image": ["14", 2],
            "start_at_step": 0, "end_at_step": I2V_SWITCH, "return_with_leftover_noise": "enable"}}
        wf["15b"] = {"class_type": "KSamplerAdvanced", "inputs": {
            "model": ["3b", 0], "add_noise": "disable", "noise_seed": 1000 + i,
            "steps": STEPS_I2V, "cfg": 1.0, "sampler_name": "uni_pc", "scheduler": "simple",
            "positive": ["14", 0], "negative": ["14", 1], "latent_image": ["15", 0],
            "start_at_step": I2V_SWITCH, "end_at_step": STEPS_I2V,
            "return_with_leftover_noise": "disable"}}
        sampled = ["15b", 0]
    else:
        wf["1"] = {"class_type": "UNETLoader", "inputs": {"unet_name": S2V_MODEL, "weight_dtype": "default"}}
        wf["2"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": LIGHTX2V_LORA, "strength_model": 1.0}}
        wf["3"] = {"class_type": "ModelSamplingSD3", "inputs": {"model": ["2", 0], "shift": 8.0}}
        wf["8"] = {"class_type": "AudioEncoderLoader", "inputs": {"audio_encoder_name": "wav2vec2_large_english_fp16.safetensors"}}
        wf["9"] = {"class_type": "LoadAudio", "inputs": {"audio": audio_file}}
        wf["10"] = {"class_type": "TrimAudioDuration", "inputs": {"audio": ["9", 0], "start_index": start, "duration": round(CHUNK, 4)}}
        wf["11"] = {"class_type": "AudioEncoderEncode", "inputs": {"audio_encoder": ["8", 0], "audio": ["10", 0]}}
        s2v = {"positive": ["5", 0], "negative": ["6", 0], "vae": ["7", 0],
               "width": W, "height": H, "length": LEN, "batch_size": 1,
               "audio_encoder_output": ["11", 0], "ref_image": ["13", 0]}
        # The node's two optional inputs, left empty until now. Both are IMAGE
        # (a frame batch), NOT the VIDEO type -- so the loader has to be one that
        # decodes to frames. LoadVideo returns VIDEO and would be rejected at
        # submit; LoadVideosFromFolder (kjnodes) takes a path and returns IMAGE.
        # frame_load_cap = LEN because the clip is exactly that many frames and
        # loading a whole 4-minute driving video per clip is wasted decode.
        for node_id, path, key in (("20", ref_motion, "ref_motion"),
                                    ("21", control_video, "control_video")):
            if not path:
                continue
            wf[node_id] = {"class_type": "LoadVideosFromFolder", "inputs": {
                "video": path, "force_rate": FPS, "custom_width": W, "custom_height": H,
                "frame_load_cap": LEN, "skip_first_frames": 0, "select_every_nth": 1,
                "output_type": "batch", "grid_max_columns": 4, "add_label": False}}
            s2v[key] = [node_id, 0]
        wf["14"] = {"class_type": "WanSoundImageToVideo", "inputs": s2v}
        wf["15"] = {"class_type": "KSampler", "inputs": {"model": ["3", 0], "seed": 1000 + i, "steps": 4, "cfg": 1.0, "sampler_name": "uni_pc", "scheduler": "simple", "positive": ["14", 0], "negative": ["14", 1], "latent_image": ["14", 2], "denoise": 1.0}}
        sampled = ["15", 0]

    if refine:
        # low-denoise second pass with the i2v LOW-noise expert. It re-samples
        # the latent s2v produced, so the audio-driven motion is preserved and
        # only detail is touched. Both models use wan_2.1_vae, which is what
        # makes handing the latent over valid at all.
        wf["30"] = {"class_type": "UNETLoader", "inputs": {"unet_name": I2V_LOW, "weight_dtype": "default"}}
        wf["31"] = {"class_type": "ModelSamplingSD3", "inputs": {"model": ["30", 0], "shift": 8.0}}
        wf["32"] = {"class_type": "KSampler", "inputs": {
            "model": ["31", 0], "seed": 2000 + i, "steps": REFINE_STEPS, "cfg": 1.0,
            "sampler_name": "uni_pc", "scheduler": "simple",
            "positive": ["14", 0], "negative": ["14", 1], "latent_image": sampled,
            "denoise": REFINE_DENOISE}}
        sampled = ["32", 0]

    wf["16"] = {"class_type": "VAEDecode", "inputs": {"samples": sampled, "vae": ["7", 0]}}
    # silent: the master mp3 is laid over the assembled timeline once, so
    # per-clip audio cannot drift.
    wf["17"] = {"class_type": "CreateVideo", "inputs": {"images": ["16", 0], "fps": FPS}}
    return wf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--audio", required=True, help="path to the mp3 (for duration)")
    ap.add_argument("--audio-name", help="filename as it appears in ComfyUI/input (defaults to basename of --audio)")
    ap.add_argument("--slug", required=True, help="short song id, e.g. rear_entrance")
    ap.add_argument("--video-model", choices=["s2v", "i2v", "ltx", "ltx25"], default="ltx25",
                    help="ltx25 (default) and ltx are the audio-conditioned LTX paths -- "
                          "2.5 and 2.3 respectively. s2v is WAN's audio-driven path (beat "
                          "sync and mouth movement). i2v is prompt-driven only, NO audio.")
    ap.add_argument("--ref-motion", help="s2v only: a motion-style reference clip (path)")
    ap.add_argument("--control-video", help="s2v only: a driving clip for pose/structure (path)")
    ap.add_argument("--refine", action="store_true",
                    help="add an unproven low-denoise pass with the i2v low-noise expert")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    sb = normalize(json.load(open(args.storyboard)))
    scenes = sb["scenes"]
    dur = audio_duration(args.audio)
    plan_clips = clip_plan(scenes, args.audio)
    nclips = len(plan_clips)

    audio_name = args.audio_name or os.path.basename(args.audio)
    char = sb.get("character_reference", "")
    # newer album-wide storyboards renamed this field
    world = sb.get("album_world_reference") or sb.get("world_reference", "")
    guard = sb.get("global_guardrail", "")

    os.makedirs(args.outdir, exist_ok=True)
    per_scene = {}
    for i, scene, _shot in plan_clips:
        # one reference per clip (build_refs.py --audio), so consecutive clips in
        # a scene are different compositions rather than the same still
        ref = f"{args.slug}_clip_{i:03d}.png"
        wf = workflow(i, scene, ref, audio_name, char, world, guard,
                      video_model=args.video_model, ref_motion=args.ref_motion,
                      control_video=args.control_video, refine=args.refine)
        # Attach the save to whichever node actually produces the VIDEO, found by
        # class rather than by a per-family id table. That table was
        # `"21" if video_model == "ltx" else "17"`, so ltx25 silently took the
        # WAN id and every workflow was rejected with
        #   received_type(GUIDER) mismatch input_type(VIDEO)
        # -- a whole render's worth of JSONs, refused one at a time. Every new
        # family would have re-earned that bug; asking the graph does not.
        video_node = next(k for k, n in wf.items() if n["class_type"] == "CreateVideo")
        wf["99"] = {"class_type": "SaveVideo", "inputs": {
            "video": [video_node, 0],
            "filename_prefix": f"{args.slug}/clip_{i:03d}",
            "format": "auto", "codec": "auto"}}
        with open(f"{args.outdir}/clip_{i:03d}.json", "w") as f:
            json.dump(wf, f)
        n_so_far, _ = per_scene.get(scene["scene_number"], (0, ref))
        per_scene[scene["scene_number"]] = (n_so_far + 1, ref)
    plan = [(num, sname(next(s for _, s, _ in plan_clips if s["scene_number"] == num)), n, ref)
            for num, (n, ref) in per_scene.items()]

    print(f"{args.slug} {dur:.1f}s -> {nclips} clips of {CHUNK:.4f}s "
          f"[{args.video_model}{', refined' if args.refine else ''}]")
    if args.video_model == "i2v":
        print("  NOTE: i2v has no audio input -- no beat sync, no mouth movement on vocals.")
    for num, name, n, ref in plan:
        print(f"  scene {num:2d} {name[:28]:<30} {n} clip(s)  <- {ref}")


def demo():
    """Self-check: both video paths wire up, and the guardrail lands once."""
    import guardrail as g

    scene = {"scene_number": 1, "name": "s", "camera": "wide", "lighting": "neon",
             "video_motion_prompt": "she walks", "negative_prompt": "", "duration_guidance": "5 sec",
             "image_prompt": "a rooftop"}

    # --- s2v: audio in, one sampler, the reference frame as ref_image ---
    wf = workflow(0, scene, "clip_000.png", "song.mp3", "a black cat", "a neon alley",
                  "tier wording")
    s2v = wf["14"]
    assert s2v["class_type"] == "WanSoundImageToVideo"
    assert s2v["inputs"]["audio_encoder_output"] == ["11", 0], "the audio was disconnected"
    assert s2v["inputs"]["ref_image"] == ["13", 0]
    assert wf["1"]["inputs"]["unet_name"] == S2V_MODEL
    assert wf["15"]["class_type"] == "KSampler"
    assert wf["16"]["inputs"]["samples"] == ["15", 0]
    prompt = wf["5"]["inputs"]["text"]
    assert g.PINNED.strip() in prompt and prompt.count("No minors") == 1
    assert "she walks" in prompt and "a black cat" in prompt

    # the two optional inputs stay ABSENT unless asked for -- an empty string
    # would be a filename ComfyUI then fails to open
    assert "ref_motion" not in s2v["inputs"] and "control_video" not in s2v["inputs"]
    driven = workflow(0, scene, "c.png", "song.mp3", "c", "w", "", ref_motion="/m.mp4",
                      control_video="/c.mp4")["14"]["inputs"]
    assert driven["ref_motion"] == ["20", 0] and driven["control_video"] == ["21", 0]

    # --- i2v: NO audio, two experts, the boundary between them ---
    iw = workflow(0, scene, "clip_000.png", "song.mp3", "c", "w", "", video_model="i2v")
    assert iw["14"]["class_type"] == "WanImageToVideo"
    assert "audio_encoder_output" not in iw["14"]["inputs"], "i2v has no audio input at all"
    assert iw["14"]["inputs"]["start_image"] == ["13", 0]
    assert iw["1"]["inputs"]["unet_name"] == I2V_HIGH
    assert iw["2"]["inputs"]["unet_name"] == I2V_LOW
    hi, lo = iw["15"]["inputs"], iw["15b"]["inputs"]
    assert hi["add_noise"] == "enable" and lo["add_noise"] == "disable", \
        "the second expert must not re-noise a latent that already carries it"
    assert hi["end_at_step"] == lo["start_at_step"] == I2V_SWITCH, "the experts do not meet"
    assert lo["end_at_step"] == STEPS_I2V
    assert lo["latent_image"] == ["15", 0], "the low-noise pass did not receive the high-noise latent"
    assert iw["16"]["inputs"]["samples"] == ["15b", 0]

    # --- refiner: appended AFTER whichever path ran, at low denoise ---
    rw = workflow(0, scene, "c.png", "song.mp3", "c", "w", "", refine=True)
    assert rw["32"]["inputs"]["latent_image"] == ["15", 0], "the refiner did not receive the clip"
    assert rw["32"]["inputs"]["denoise"] == REFINE_DENOISE
    assert 0 < REFINE_DENOISE < 1, "a refiner at denoise 1.0 is not a refiner"
    assert rw["30"]["inputs"]["unet_name"] == I2V_LOW
    assert rw["16"]["inputs"]["samples"] == ["32", 0], "the refined latent was not the one decoded"
    # ...and it still carries the audio-driven motion it is refining
    assert rw["14"]["inputs"]["audio_encoder_output"] == ["11", 0]

    # --- allocation: every clip belongs to exactly one scene, none lost ---
    scenes = [dict(scene, scene_number=n, duration_guidance=f"{n*4}-{n*4+2} sec")
              for n in (1, 2, 3)]
    for nclips in (3, 7, 41, 50):
        plan = clip_plan(scenes, nclips=nclips)
        assert [ci for ci, _, _ in plan] == list(range(nclips)), nclips
        assert len({s["scene_number"] for _, s, _ in plan}) == 3, "a scene got no clips"

    print("build_song.py OK")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        demo()
    else:
        main()
