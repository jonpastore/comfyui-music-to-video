"""Does identity drift more in a 30s clip than a 15s one?

The 60s clip that prompted this question was a back view walking away in a dark
alley -- the easiest possible case, and one that physically CANNOT show face
drift. This uses scene 4 of the xxx storyboard, "Front Door Dismissed": an
over-shoulder look back with eye contact and a half-smile. The face is in frame.

Everything is held constant except length: same reference image (a real chosen-
tier anchor), same prompt, same seed, same box. Only the frame count changes.
Both run on gamingpc because cerberus is busy, and running them on DIFFERENT
boxes would confound the comparison with the 2.59x WSL tax.
"""
import json
import sys
import time
import urllib.request

URL = "http://100.107.235.105:8188"      # gamingpc
FPS = 16.8312
SEED = 424242
REF = "driftref.png"
LENGTHS = [(257, "15s"), (505, "30s")]   # 8n+1, 15.27s and 30.00s

PROMPT = (
    "over-shoulder glance upward then back to the door; slow look back, knowing "
    "half-smile; camera movement: over-shoulder; sensual confident after-hours "
    "nightlife body language, flirtatious eye contact, sultry knowing attitude, "
    "fully clothed, tasteful and non-graphic, no explicit gesture; stable "
    "character identity, stable anatomy, natural hair, cloth and tail physics")


def post(path, payload, timeout=60):
    req = urllib.request.Request(f"{URL}{path}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def get(path, timeout=30):
    with urllib.request.urlopen(f"{URL}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode())


base = json.load(open(sys.argv[1]))
for frames, label in LENGTHS:
    wf = json.loads(json.dumps(base))
    for node in wf.values():
        ct = node["class_type"]
        if ct == "EmptyLTXVLatentVideo":
            node["inputs"]["length"] = frames
        elif ct == "TrimAudioDuration":
            node["inputs"]["duration"] = round(frames / FPS, 4)
        elif ct == "LoadImage":
            node["inputs"]["image"] = REF
        elif ct == "SaveVideo":
            node["inputs"]["filename_prefix"] = f"drift_{label}"
        elif ct == "RandomNoise":
            node["inputs"]["noise_seed"] = SEED          # SAME seed both runs
        elif ct == "CLIPTextEncode" and "blurry" not in node["inputs"].get("text", ""):
            node["inputs"]["text"] = PROMPT
    t0 = time.time()
    pid = post("/prompt", {"prompt": wf, "client_id": f"drift{frames}"})["prompt_id"]
    while time.time() - t0 < 3600:
        h = get(f"/history/{pid}")
        if h.get(pid):
            outs = h[pid].get("outputs") or {}
            names = [f["filename"] for o in outs.values() for f in o.get("images", [])]
            print(f"{label:4} {frames:4d} frames  {time.time() - t0:6.1f}s  "
                  f"{names or 'FAILED ' + str(h[pid].get('status', {}))[:140]}")
            break
        time.sleep(5)
    else:
        print(f"{label} timed out")
