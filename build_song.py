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
                --audio "Rear Entrance .mp3" --version explicit \
                --slug rear_entrance --outdir ~/shots/rear_entrance_explicit
"""
import argparse, json, math, os, re, subprocess, sys

FPS = 16.0
LEN = 77                 # WAN 2.2 S2V chunk; needs >= 73
CHUNK = LEN / FPS        # 4.8125s
W, H = 832, 480          # 16:9, divisible by 16


# The storyboards lock the outfit as a jacket, which matches the clean anchor.
# The explicit anchor is the Street Cats cover look (harness top, no jacket), so
# the wording is swapped for that cut -- otherwise the prompt argues with the
# reference image and the jacket flickers in and out between scenes.
OUTFIT_EXPLICIT = ("black leather harness top, black leather pants with gold buckles and straps, "
                   "black thigh-high lace-up boots")
OUTFIT_JACKET_PHRASES = [
    "black leather street/club jacket, fitted black pants, black boots",
    "black leather street/club jacket, fitted black pants",
    "black futuristic clubwear with gold hardware, black boots",   # Catatonic wording
    "black futuristic clubwear with gold hardware",
    "fully clothed black leather streetwear",
]


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
        s.setdefault("negative_prompt", sb.get("negative", sb.get("global_negative_prompt", "")))
        s.setdefault("camera", "")
        if "duration_guidance" not in s and "chunks" in s:
            s["duration_guidance"] = f"{s['chunks']} sec"
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


def apply_outfit(text, version):
    if version != "explicit":
        return text
    for phrase in OUTFIT_JACKET_PHRASES:
        text = text.replace(phrase, OUTFIT_EXPLICIT)
    return text


def audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def guidance_seconds(s):
    """Midpoint of a '5-8 sec' style guidance string."""
    nums = [int(x) for x in re.findall(r"\d+", s.get("duration_guidance", ""))]
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


def workflow(i, scene, ref_image, audio_file, char_lock, world_lock, guardrail):
    motion = scene.get("video_motion_prompt") or scene.get("motion", "")
    pos = f"{shot_directive(scene, i)} {char_lock} {world_lock} Motion: {motion} Camera: {scene.get('camera','')} Lighting: {scene.get('lighting','')} {guardrail}"
    neg = scene.get("negative_prompt", "")
    start = round(i * CHUNK, 4)
    return {
        "1":  {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_s2v_14B_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "2":  {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors", "strength_model": 1.0}},
        "3":  {"class_type": "ModelSamplingSD3", "inputs": {"model": ["2", 0], "shift": 8.0}},
        "4":  {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "5":  {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": pos}},
        "6":  {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": neg}},
        "7":  {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "8":  {"class_type": "AudioEncoderLoader", "inputs": {"audio_encoder_name": "wav2vec2_large_english_fp16.safetensors"}},
        "9":  {"class_type": "LoadAudio", "inputs": {"audio": audio_file}},
        "10": {"class_type": "TrimAudioDuration", "inputs": {"audio": ["9", 0], "start_index": start, "duration": round(CHUNK, 4)}},
        "11": {"class_type": "AudioEncoderEncode", "inputs": {"audio_encoder": ["8", 0], "audio": ["10", 0]}},
        "12": {"class_type": "LoadImage", "inputs": {"image": ref_image}},
        "13": {"class_type": "ImageScale", "inputs": {"image": ["12", 0], "upscale_method": "lanczos", "width": W, "height": H, "crop": "center"}},
        "14": {"class_type": "WanSoundImageToVideo", "inputs": {"positive": ["5", 0], "negative": ["6", 0], "vae": ["7", 0], "width": W, "height": H, "length": LEN, "batch_size": 1, "audio_encoder_output": ["11", 0], "ref_image": ["13", 0]}},
        "15": {"class_type": "KSampler", "inputs": {"model": ["3", 0], "seed": 1000 + i, "steps": 4, "cfg": 1.0, "sampler_name": "uni_pc", "scheduler": "simple", "positive": ["14", 0], "negative": ["14", 1], "latent_image": ["14", 2], "denoise": 1.0}},
        "16": {"class_type": "VAEDecode", "inputs": {"samples": ["15", 0], "vae": ["7", 0]}},
        # silent: the master mp3 is laid over the assembled timeline once, so
        # per-clip audio cannot drift.
        "17": {"class_type": "CreateVideo", "inputs": {"images": ["16", 0], "fps": FPS}},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--audio", required=True, help="path to the mp3 (for duration)")
    ap.add_argument("--audio-name", help="filename as it appears in ComfyUI/input (defaults to basename of --audio)")
    ap.add_argument("--version", required=True, choices=["clean", "explicit"])
    ap.add_argument("--slug", required=True, help="short song id, e.g. rear_entrance")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    sb = normalize(json.load(open(args.storyboard)))
    scenes = sb["scenes"]
    dur = audio_duration(args.audio)
    nclips = math.ceil(dur / CHUNK)
    counts = allocate(scenes, nclips)

    audio_name = args.audio_name or os.path.basename(args.audio)
    char = apply_outfit(sb.get("character_reference", ""), args.version)
    # newer album-wide storyboards renamed this field
    world = sb.get("album_world_reference") or sb.get("world_reference", "")
    guard = sb.get("global_guardrail", "")

    os.makedirs(args.outdir, exist_ok=True)
    i = 0
    plan = []
    for scene, n in zip(scenes, counts):
        for _ in range(n):
            # one reference per clip (build_refs.py --audio), so consecutive
            # clips in a scene are different compositions rather than the same still
            ref = f"{args.slug}_{args.version}_clip_{i:03d}.png"
            wf = workflow(i, scene, ref, audio_name, char, world, guard)
            wf["18"] = {"class_type": "SaveVideo", "inputs": {
                "video": ["17", 0],
                "filename_prefix": f"{args.slug}_{args.version}/clip_{i:03d}",
                "format": "auto", "codec": "auto"}}
            with open(f"{args.outdir}/clip_{i:03d}.json", "w") as f:
                json.dump(wf, f)
            i += 1
        plan.append((scene["scene_number"], sname(scene), n, ref))

    print(f"{args.slug} [{args.version}] {dur:.1f}s -> {nclips} clips of {CHUNK:.4f}s")
    for num, name, n, ref in plan:
        print(f"  scene {num:2d} {name[:28]:<30} {n} clip(s)  <- {ref}")


if __name__ == "__main__":
    main()
