"""Who is holding the one GPU, and taking it back before a render.

ComfyUI and ollama share ONE 24 GB card on cerberus, and neither knows the other
exists. ollama's unit sets `OLLAMA_KEEP_ALIVE=24h`
(`/etc/systemd/system/ollama.service.d/override.conf`), so ANY local-model call
-- a vision pass, a classifier, someone's chat -- pins ~22 GB for a DAY. ComfyUI
is then handed 254 MiB, OOMs, and SEGFAULTS: that is what the studio's
`ConnectionResetError` job failures were, and why a batch of twelve sheets could
"succeed" and write no images at all. Diagnosing it cost three render batches.
It should cost nothing, so `preflight()` runs before every submit.

Neither direction stops a service or needs root:

    python3 gpu.py status     who holds the card, and when the pin expires
    python3 gpu.py comfy      unload ollama's models -- ollama reloads on demand
    python3 gpu.py ollama     unload ComfyUI's models -- it reloads on the next render

An unloaded model is a cold start, not lost work, which is why preflight() is
allowed to take the card back on its own rather than only complaining.
"""
import json, os, time, urllib.request

COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

# ponytail: a floor, not a model-aware estimate. Two measurements bracket it --
# 0.25 GB free was the OOM-and-segfault, 3.5 GB free rendered a full sheet with
# ComfyUI's own weights already resident. Nothing here can know what the NEXT
# workflow will ask for; raise it if a render OOMs above the floor.
MIN_FREE_GB = float(os.environ.get("STUDIO_MIN_FREE_VRAM_GB", 1.0))
GB = 1024 ** 3


def _get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _post(url, payload, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def vram():
    """(free_bytes, total_bytes) for the render device, or None if ComfyUI did
    not answer. `/system_stats` reports the DEVICE's free memory, so ollama's
    share is already subtracted -- which is the only reason this is worth
    reading rather than torch's own accounting."""
    try:
        dev = (_get(f"{COMFY}/system_stats").get("devices") or [])[0]
    except Exception:
        return None
    return dev.get("vram_free"), dev.get("vram_total")


def ollama_holding():
    """[{name, bytes, expires}] for models currently resident, newest keep-alive
    first. Empty when ollama is idle or absent -- it is not an error for the
    render box not to be running one."""
    try:
        models = _get(f"{OLLAMA}/api/ps").get("models") or []
    except Exception:
        return []
    return [{"name": m.get("model") or m.get("name") or "?",
             "bytes": m.get("size_vram") or 0,
             "expires": m.get("expires_at") or ""}
            for m in models if (m.get("size_vram") or 0) > 0]


def release_ollama(progress=None, timeout=10.0):
    """Unload every resident ollama model. Returns the bytes it was holding.

    `keep_alive: 0` on a generate with no prompt is what `ollama stop` does, and
    it needs no root -- which matters, because the 24h keep-alive lives in a
    SYSTEM unit this app cannot edit.

    Then WAITS for the memory. The unload is asynchronous: measured on cerberus,
    `/api/ps` still listed a 1.9 GB model in the same second the request
    returned, and released it by the next. Reading the card straight after the
    request is how preflight() would refuse a render over memory that was about
    to come back.
    """
    held = ollama_holding()
    freed = 0
    for m in held:
        try:
            _post(f"{OLLAMA}/api/generate", {"model": m["name"], "keep_alive": 0})
            freed += m["bytes"]
            if progress:
                progress(f"unloaded ollama model {m['name']} -- {m['bytes'] / GB:.1f} GB "
                         f"it was pinned to hold until {m['expires'] or 'unknown'}")
        except Exception as e:
            if progress:
                progress(f"could not unload ollama model {m['name']}: {e}")
    deadline = time.monotonic() + timeout
    while ollama_holding() and time.monotonic() < deadline:
        time.sleep(0.25)
    return freed


def preflight(progress=None):
    """Take the card back before a render, or refuse with the numbers.

    Best effort about REACHING things -- a ComfyUI too old for /system_stats or
    an absent ollama must not fail a render that would have worked. Not best
    effort about the result: if the card is genuinely too full after ollama has
    let go, this raises rather than letting ComfyUI OOM, because an OOM here
    presents as a job that succeeded with no images.
    """
    held = ollama_holding()
    if held:
        release_ollama(progress)

    v = vram()
    if not v or not v[0]:
        return                      # nothing readable; not a reason to refuse
    free, total = v
    if free >= MIN_FREE_GB * GB:
        return
    who = ", ".join(f"{m['name']} holding {m['bytes'] / GB:.1f} GB" for m in ollama_holding())
    raise RuntimeError(
        f"the GPU has {free / GB:.1f} GB free of {total / GB:.1f} GB, and a render needs at "
        f"least {MIN_FREE_GB:.1f} GB"
        + (f"; ollama still has {who}" if who else "")
        + ". Run `python3 gpu.py comfy` on the render box, or free it another way, and "
          "start this again.")


def give_to_ollama(progress=None):
    """The other direction: ComfyUI drops its ~20 GB of weights so a local model
    can have the card. It reloads them on the next render, so this costs one
    slow render, not a restart."""
    import pipeline          # local: pipeline imports THIS module for preflight
    return pipeline.free_vram(progress)


def status():
    lines = []
    v = vram()
    if v and v[0]:
        lines.append(f"GPU: {v[0] / GB:.1f} GB free of {v[1] / GB:.1f} GB")
    else:
        lines.append(f"GPU: ComfyUI at {COMFY} did not answer /system_stats")
    held = ollama_holding()
    if held:
        for m in held:
            lines.append(f"ollama: {m['name']} holding {m['bytes'] / GB:.1f} GB "
                         f"until {m['expires'] or 'unknown'}")
    else:
        lines.append("ollama: nothing resident")
    return "\n".join(lines)


def demo():
    """Self-check against a fake card. The real one cannot be asked to be full
    on demand, and the branch that matters is the refusal."""
    real_get, real_post = globals()["_get"], globals()["_post"]
    # one fake card: `free` is what ComfyUI reports, `models` what ollama admits
    # to holding, and `returns` whether unloading actually gives the memory back
    card = {"free": 0.25, "models": [], "returns": 0.0, "pending": 0}
    calls, said = [], []

    def _g(url, timeout=5):
        if url.endswith("/system_stats"):
            return {"devices": [{"vram_free": int(card["free"] * GB),
                                 "vram_total": int(24 * GB)}]}
        # ollama lets go a moment AFTER it answers, so /api/ps keeps listing the
        # model for a few reads -- measured on cerberus, still resident in the
        # same second, gone by the next
        if card["pending"] > 0:
            card["pending"] -= 1
            if card["pending"] == 0:
                card["models"] = []
                card["free"] += card["returns"]
        return {"models": card["models"]}

    def _p(url, payload, timeout=30):
        calls.append(payload)
        card["pending"] = 3
        return b""

    globals()["_get"], globals()["_post"] = _g, _p

    # 1. the measured failure: 21.9 GB pinned, 0.25 GB free. ollama is asked to
    #    let go, and when the memory does NOT come back the render is refused
    #    with both numbers rather than left to OOM.
    card.update(free=0.25, returns=0.0,
                models=[{"model": "qwen3.6:27b", "size_vram": int(21.9 * GB),
                         "expires_at": "2026-08-12T21:40:00Z"}])
    try:
        preflight(said.append)
        raise AssertionError("a card with 0.25 GB free was accepted for a render")
    except RuntimeError as e:
        assert "0.2 GB free" in str(e) and "24.0 GB" in str(e), str(e)
    assert calls and calls[0]["keep_alive"] == 0, calls
    assert any("21.9 GB" in s and "qwen3.6:27b" in s for s in said), said

    # 2. THE DIFFERENTIAL: identical call, identical starting free memory, the
    #    only change being that unloading actually returns the 21.9 GB. No
    #    refusal. A preflight that always refused would pass test 1 alone.
    #    It also only passes if release_ollama WAITS -- the fake card is still
    #    listing the model, and still reporting 0.25 GB free, on the first read
    #    after the unload returns.
    calls.clear()
    card.update(free=0.25, returns=21.9, pending=0,
                models=[{"model": "qwen3.6:27b", "size_vram": int(21.9 * GB),
                         "expires_at": ""}])
    preflight(said.append)                      # must not raise
    assert calls, "ollama was never asked to let go"
    assert not card["models"], "the wait for the memory did not happen"

    # 3. a full card with nothing resident still refuses -- and does not blame
    #    ollama for memory it is not holding
    card.update(free=0.1, returns=0.0, models=[])
    try:
        preflight(None)
        raise AssertionError("a full card with no ollama models was accepted")
    except RuntimeError as e:
        assert "ollama" not in str(e), str(e)

    # 4. a card with room is not touched at all
    calls.clear()
    card.update(free=8.0, models=[])
    preflight(None)
    assert not calls, "a healthy card was interfered with"

    # 5. an unreachable ComfyUI never fails a render on its own
    globals()["_get"] = lambda url, timeout=5: (_ for _ in ()).throw(OSError("refused"))
    preflight(None)

    globals()["_get"], globals()["_post"] = real_get, real_post
    print("gpu.py demo OK")


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    if cmd == "status":
        print(status())
    elif cmd == "comfy":
        freed = release_ollama(print)
        print(f"freed {freed / GB:.1f} GB for ComfyUI")
        print(status())
    elif cmd == "ollama":
        give_to_ollama(print)
        print(status())
    elif cmd == "demo":
        demo()
    else:
        raise SystemExit(f"usage: gpu.py [status|comfy|ollama|demo] (not {cmd!r})")
