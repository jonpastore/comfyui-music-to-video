"""Two 30-second clips at once, one per 5090.

Answers the question Jon actually asked -- can the fleet render 2x30s in
parallel -- and incidentally settles a fair warm-vs-warm comparison between the
two boxes, which the sequential ladder could not: gamingpc's 419.1s was its
first LTX-2.5 render of the day and included pulling 20 GiB off disk, while
cerberus had rendered the same model repeatedly and had it in page cache.

Both boxes are torch 2.11.0+cu130 / comfy 0.32.0, so the CUDA-13 quantised-
kernel trap is NOT the explanation for the 2.7x gap.
"""
import json
import sys
import threading
import time
import urllib.request

FPS = 16.8312
FRAMES = 505
BOXES = {"cerberus": "http://100.103.148.120:8188",
         "gamingpc": "http://100.107.235.105:8188"}


def post(url, path, payload, timeout=60):
    req = urllib.request.Request(f"{url}{path}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def get(url, path, timeout=30):
    with urllib.request.urlopen(f"{url}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode())


def run(box, url, base, seed, results):
    wf = json.loads(json.dumps(base))
    for node in wf.values():
        ct = node["class_type"]
        if ct == "EmptyLTXVLatentVideo":
            node["inputs"]["length"] = FRAMES
        elif ct == "TrimAudioDuration":
            node["inputs"]["duration"] = round(FRAMES / FPS, 4)
        elif ct == "SaveVideo":
            node["inputs"]["filename_prefix"] = f"par30_{box}"
        elif ct == "RandomNoise":
            # a DIFFERENT seed per box, or ComfyUI's execution cache answers the
            # second one instantly and the whole measurement is of nothing
            node["inputs"]["noise_seed"] = seed
    t0 = time.time()
    try:
        pid = post(url, "/prompt", {"prompt": wf, "client_id": f"par{seed}"})["prompt_id"]
    except Exception as e:
        results[box] = ("submit failed", 0.0, str(e)[:120])
        return
    while time.time() - t0 < 3600:
        h = get(url, f"/history/{pid}")
        if h.get(pid):
            outs = h[pid].get("outputs") or {}
            names = [f["filename"] for o in outs.values() for f in o.get("images", [])]
            results[box] = ("OK" if names else "FAILED", time.time() - t0, names or
                            str(h[pid].get("status", {}))[:160])
            return
        time.sleep(5)
    results[box] = ("timeout", time.time() - t0, "")


base = json.load(open(sys.argv[1]))
results = {}
threads = [threading.Thread(target=run, args=(b, u, base, 810000 + i, results))
           for i, (b, u) in enumerate(BOXES.items())]

print(f"submitting {FRAMES} frames ({FRAMES / FPS:.2f}s) to both boxes at once")
wall = time.time()
for t in threads:
    t.start()
for t in threads:
    t.join()
wall = time.time() - wall

for box, (status, took, extra) in results.items():
    print(f"  {box:9} {status:6} {took:7.1f}s  {extra}")
print(f"  WALL CLOCK for both: {wall:.1f}s")
ok = [t for s, t, _ in results.values() if s == "OK"]
if len(ok) == 2:
    print(f"  --> 60 seconds of finished video in {wall:.1f}s "
          f"({2 * FRAMES / FPS / wall:.2f}x realtime across the fleet)")
