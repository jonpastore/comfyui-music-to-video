"""How long a clip can LTX-2.5 actually render, per box?

Jon's call: force 30s first and fall back. 30s at 16.8312 fps is 505 frames, and
LTX requires 8n+1, so 505 = 8*63+1 is legal -- the question is VRAM, not the
frame rule. Day 8 measured 81 frames peaking at 23.4 GB of 23.9 on cerberus and
28.3 of 31.8 on gamingpc, so the latent has very little room to grow.

Submits DIRECTLY to a box's ComfyUI rather than through Swarm: an OOM comes back
as a readable error in /history here, where Swarm reports "no images generated"
and loses the reason.
"""
import json
import sys
import time
import urllib.request

FPS = 16.8312
# 8n+1, descending. 30s first per the brief, then the steps back to known-good.
LADDER = [505, 425, 337, 257, 169, 81]

BOXES = {
    "gamingpc": "http://100.107.235.105:8188",
    "cerberus": "http://100.103.148.120:8188",
}


def post(url, path, payload, timeout=60):
    req = urllib.request.Request(f"{url}{path}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def get(url, path, timeout=30):
    with urllib.request.urlopen(f"{url}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode())


def build(base, frames, prefix):
    wf = json.loads(json.dumps(base))
    secs = frames / FPS
    for node in wf.values():
        ct = node["class_type"]
        if ct == "EmptyLTXVLatentVideo":
            node["inputs"]["length"] = frames
        elif ct == "TrimAudioDuration":
            node["inputs"]["duration"] = round(secs, 4)
        elif ct == "SaveVideo":
            node["inputs"]["filename_prefix"] = prefix
        elif ct == "RandomNoise":
            node["inputs"]["noise_seed"] = 700000 + frames
    return wf, secs


def render(url, wf, budget=1800):
    pid = post(url, "/prompt", {"prompt": wf, "client_id": f"cm{time.time()}"})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < budget:
        h = get(url, f"/history/{pid}")
        if h.get(pid):
            st = h[pid].get("status", {})
            if st.get("status_str") == "error" or not h[pid].get("outputs"):
                msgs = [m for m in st.get("messages", []) if m and m[0] == "execution_error"]
                why = ""
                if msgs:
                    d = msgs[0][1]
                    why = f"{d.get('exception_type','')}: {str(d.get('exception_message',''))[:200]}"
                return None, time.time() - t0, why or "no outputs"
            out = h[pid]["outputs"]
            names = [f["filename"] for o in out.values() for f in o.get("images", [])]
            return names, time.time() - t0, ""
        time.sleep(5)
    return None, time.time() - t0, "timed out"


base = json.load(open(sys.argv[1]))
only = sys.argv[2] if len(sys.argv) > 2 else None

for box, url in BOXES.items():
    if only and box != only:
        continue
    print(f"\n===== {box} {url}")
    try:
        stats = get(url, "/system_stats")
        dev = stats["devices"][0]
        print(f"  {dev['name']}  {dev['vram_total'] / 2**30:.2f} GiB")
    except Exception as e:
        print("  unreachable:", e)
        continue
    for frames in LADDER:
        wf, secs = build(base, frames, f"clipmax_{box}_{frames}")
        names, took, why = render(url, wf)
        if names:
            print(f"  {frames:4d} frames ({secs:5.2f}s)  OK   {took:6.1f}s  {names}")
            print(f"  --> {box} ceiling is at least {secs:.2f}s")
            break
        print(f"  {frames:4d} frames ({secs:5.2f}s)  FAIL {took:6.1f}s  {why}")
    else:
        print(f"  --> {box} rendered nothing on the whole ladder")
