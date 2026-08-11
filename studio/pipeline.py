#!/usr/bin/env python3
"""Wraps the repo-root CLI scripts (make_anchor.py, build_refs.py, build_song.py,
reroll_refs.py, make_contact_sheet.py) and does the actual ComfyUI submission
they leave out: those scripts only write API-format workflow JSONs into an
--outdir, they never render. submit_dir() reimplements cerberus's
~/bin/submit_all.sh (POST /prompt, poll /history/<id>) in Python so the studio
UI gets per-item progress instead of one opaque shell run.

Every gen_* wrapper: (1) write workflow JSONs to a scratch dir via the real
CLI script, (2) submit_dir() them, (3) collect() the rendered outputs from
COMFY_OUTPUT.
"""
import glob, json, os, re, shutil, subprocess, sys, tempfile, time
import urllib.error, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.environ.get("STUDIO_SCRIPTS", os.path.dirname(ROOT))
COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
COMFY_INPUT = os.environ.get("COMFY_INPUT", os.path.expanduser("~/ComfyUI/input"))
COMFY_OUTPUT = os.environ.get("COMFY_OUTPUT", os.path.expanduser("~/ComfyUI/output"))

POLL_SECS = 2.0
# A WAN clip legitimately takes ~90s; this is a "ComfyUI vanished" backstop,
# not a render-time budget. There is exactly ONE job worker (studio/jobs.py),
# so a submit that never resolves wedges the whole queue -- must not hang.
SUBMIT_TIMEOUT = float(os.environ.get("SUBMIT_TIMEOUT", 1800))
MAX_POLL_ERRORS = 3  # consecutive connection failures before giving up on a poll

# build_refs.py / build_song.py take --version {clean,explicit}; apply_outfit()
# in build_song.py is the ONLY thing --version affects, and it's a no-op
# unless version == "explicit" (see build_song.apply_outfit). Our tiers
# (pg13/r/custom, from studio/tiers.py) are a separate axis -- guardrail
# wording, not wardrobe -- so we always pass "clean" here and fold the tier
# into the --slug we pass instead, keeping it in paths/filenames only.
VERSION = "clean"


def _slug_tier(slug, tier):
    return f"{slug}_{tier}"


def _run_script(script, args, progress=None):
    progress = progress or (lambda msg: None)
    path = os.path.join(SCRIPTS, script)
    try:
        r = subprocess.run([sys.executable, path, *args],
                            check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{script} failed: {e.stderr.strip()[-2000:]}") from e
    for line in r.stdout.splitlines():
        progress(line)
    return r.stdout


def _post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {}
    except urllib.error.URLError as e:
        raise RuntimeError(f"cannot reach ComfyUI at {COMFY} ({e.reason}) -- is it running?") from e


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"cannot reach ComfyUI at {COMFY} ({e.reason}) -- is it running?") from e


def install_input(local_path, name=None):
    name = name or os.path.basename(local_path)
    os.makedirs(COMFY_INPUT, exist_ok=True)
    shutil.copy(local_path, os.path.join(COMFY_INPUT, name))
    return name


def submit_dir(wf_dir, progress=None):
    progress = progress or (lambda msg: None)
    files = sorted(f for f in os.listdir(wf_dir) if f.endswith(".json"))
    ids = []
    for i, name in enumerate(files, 1):
        wf = json.load(open(os.path.join(wf_dir, name)))
        start = time.time()
        resp = _post(f"{COMFY}/prompt", {"prompt": wf})
        pid = resp.get("prompt_id")
        if not pid:
            raise RuntimeError(f"submit rejected: {name}: {resp}")
        errors = 0
        while True:
            if time.time() - start > SUBMIT_TIMEOUT:
                raise RuntimeError(
                    f"{name} (prompt {pid}) did not finish within {SUBMIT_TIMEOUT:.0f}s")
            try:
                hist = _get(f"{COMFY}/history/{pid}")
                errors = 0
            except RuntimeError:
                errors += 1
                if errors >= MAX_POLL_ERRORS:
                    raise
                time.sleep(POLL_SECS)
                continue
            if hist:
                break
            time.sleep(POLL_SECS)
        ids.append(pid)
        progress(f"{i}/{len(files)} {os.path.splitext(name)[0]} {time.time()-start:.0f}s")
    return ids


def _submit_and_collect(wf_dir, prefix_dir, pattern, progress):
    """submit_dir() + collect(), returning only files that appeared during
    THIS submit. ComfyUI's SaveImage/SaveVideo never overwrite -- they bump a
    counter suffix -- so a prefix dir reused across runs (anchor_v2 already
    has 6-16 images from earlier sessions) would otherwise mix old and new
    candidates into one result."""
    before = set(collect(prefix_dir, pattern))
    submit_dir(wf_dir, progress)
    return [p for p in collect(prefix_dir, pattern) if p not in before]


def _natkey(name):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def collect(prefix_dir, pattern="*.png"):
    files = glob.glob(os.path.join(COMFY_OUTPUT, prefix_dir, pattern))
    return sorted(files, key=lambda p: _natkey(os.path.basename(p)))


def gen_anchor(face, outfit, view="front", n=8, progress=None, prefix=None):
    face_name = install_input(face)
    outfit_name = install_input(outfit)
    prefix = prefix or "anchor_v2"  # matches make_anchor.py's own default
    with tempfile.TemporaryDirectory() as wf_dir:
        _run_script("make_anchor.py", [
            "--face", face_name, "--outfit", outfit_name, "--outdir", wf_dir,
            "--n", str(n), "--view", view, "--prefix", prefix,
        ], progress)
        return _submit_and_collect(wf_dir, prefix, "*.png", progress)


def _clip_records(paths, seed_re=r"clip_(\d+)"):
    out = []
    for p in paths:
        m = re.search(seed_re, os.path.basename(p))
        if m:
            out.append((p, m))
    return out


def gen_refs(slug, tier, storyboard_json, anchor_name, mp3_path, progress=None, limit=None):
    """limit=N renders only the first N clips.

    A full song is 40-80 references at ~15 s each, so committing to the whole
    set costs 10-20 minutes of the single GPU. limit lets you look at the first
    few and judge the storyboard before spending that.
    """
    bs = _slug_tier(slug, tier)
    with tempfile.TemporaryDirectory() as wf_dir:
        _run_script("build_refs.py", [
            "--storyboard", storyboard_json, "--version", VERSION, "--slug", bs,
            "--anchor", anchor_name, "--audio", mp3_path, "--outdir", wf_dir,
        ], progress)
        if limit:
            keep = sorted(f for f in os.listdir(wf_dir) if f.endswith(".json"))[:int(limit)]
            for f in os.listdir(wf_dir):
                if f.endswith(".json") and f not in keep:
                    os.remove(os.path.join(wf_dir, f))
            if progress:
                progress(f"limited to first {len(keep)} of the song's clips")
        paths = _submit_and_collect(wf_dir, f"refs_{bs}_{VERSION}", "*.png", progress)
    return [{"clip_idx": int(m.group(1)), "path": p, "seed": 7000 + int(m.group(1))}
            for p, m in _clip_records(paths)]


def reroll(slug, tier, storyboard_json, anchor_name, mp3_path, clip_indices, progress=None):
    bs = _slug_tier(slug, tier)
    with tempfile.TemporaryDirectory() as wf_dir:
        _run_script("reroll_refs.py", [
            "--storyboard", storyboard_json, "--version", VERSION, "--slug", bs,
            "--audio", mp3_path, "--anchor", anchor_name,
            "--clips", ",".join(str(c) for c in clip_indices), "--outdir", wf_dir,
        ], progress)
        paths = _submit_and_collect(wf_dir, f"reroll_{bs}_{VERSION}", "*.png", progress)
    return [{"clip_idx": int(m.group(1)), "path": p, "seed": int(m.group(2))}
            for p, m in _clip_records(paths, r"clip_(\d+)_s(\d+)")]


def stage_refs(slug, tier, ref_paths):
    """Copy approved per-clip refs into COMFY_INPUT under the names
    build_song.py's clip loop expects: <slug>_<tier>_<version>_clip_NNN.png
    (see build_song.main: ref = f"{args.slug}_{args.version}_clip_{i:03d}.png")."""
    bs = _slug_tier(slug, tier)
    return [install_input(rec["path"], f"{bs}_{VERSION}_clip_{rec['clip_idx']:03d}.png")
            for rec in ref_paths]


def gen_clips(slug, tier, storyboard_json, mp3_path, ref_paths, progress=None):
    # ref_paths must be staged before build_song.py runs -- it references
    # them by name inside the workflow, it doesn't take them as CLI input.
    stage_refs(slug, tier, ref_paths)
    install_input(mp3_path)  # WanSoundImageToVideo's LoadAudio needs it in COMFY_INPUT too
    bs = _slug_tier(slug, tier)
    with tempfile.TemporaryDirectory() as wf_dir:
        _run_script("build_song.py", [
            "--storyboard", storyboard_json, "--audio", mp3_path, "--version", VERSION,
            "--slug", bs, "--outdir", wf_dir,
        ], progress)
        paths = _submit_and_collect(wf_dir, f"{bs}_{VERSION}", "*.mp4", progress)
    return [{"clip_idx": int(m.group(1)), "path": p} for p, m in _clip_records(paths)]


def contact_sheet(src_dir, out_jpg, cols=6):
    _run_script("make_contact_sheet.py", [src_dir, out_jpg, str(cols)])
    return out_jpg


def demo():
    global _post, _get, COMFY_OUTPUT, COMFY_INPUT

    # --- submit_dir against a fake ComfyUI server ---
    real_post, real_get = _post, _get
    history_hits = {}

    def fake_post(url, payload):
        if payload["prompt"].get("_name") == "bad":
            return {}  # rejected: no prompt_id
        return {"prompt_id": "pid-" + payload["prompt"]["_name"]}

    def fake_get(url):
        pid = url.rsplit("/", 1)[-1]
        history_hits[pid] = history_hits.get(pid, 0) + 1
        return {} if history_hits[pid] < 2 else {pid: {"outputs": {}}}

    _post, _get = fake_post, fake_get
    try:
        with tempfile.TemporaryDirectory() as d:
            for n in ("a", "b"):
                json.dump({"_name": n}, open(os.path.join(d, f"clip_{n}.json"), "w"))
            seen = []
            ids = submit_dir(d, progress=lambda m: seen.append(m))
            assert len(seen) == 2, seen
            assert len(ids) == 2, ids

        with tempfile.TemporaryDirectory() as d:
            json.dump({"_name": "bad"}, open(os.path.join(d, "clip_bad.json"), "w"))
            try:
                submit_dir(d)
                raise AssertionError("rejected submit did not raise")
            except RuntimeError as e:
                assert "clip_bad.json" in str(e), e
    finally:
        _post, _get = real_post, real_get

    # --- submit_dir must time out, not hang, if history never fills in ---
    global SUBMIT_TIMEOUT
    real_timeout = SUBMIT_TIMEOUT
    SUBMIT_TIMEOUT = 0.2
    _post, _get = fake_post, (lambda url: {})  # always pending
    try:
        with tempfile.TemporaryDirectory() as d:
            json.dump({"_name": "stuck"}, open(os.path.join(d, "clip_stuck.json"), "w"))
            t0 = time.time()
            try:
                submit_dir(d)
                raise AssertionError("submit_dir did not time out")
            except RuntimeError as e:
                assert "clip_stuck.json" in str(e), e
            assert time.time() - t0 < 5, "timeout took far longer than SUBMIT_TIMEOUT"
    finally:
        _post, _get = real_post, real_get
        SUBMIT_TIMEOUT = real_timeout

    # --- collect() natural sort ---
    real_out = COMFY_OUTPUT
    with tempfile.TemporaryDirectory() as out_root:
        COMFY_OUTPUT = out_root
        pdir = os.path.join(out_root, "prefix")
        os.makedirs(pdir)
        for n in ("clip_10_x.png", "clip_2_x.png"):
            open(os.path.join(pdir, n), "w").close()
        files = [os.path.basename(p) for p in collect("prefix")]
        assert files == ["clip_2_x.png", "clip_10_x.png"], files
    COMFY_OUTPUT = real_out

    # --- install_input ---
    real_in = COMFY_INPUT
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as inp:
        COMFY_INPUT = inp
        p = os.path.join(src, "face pic.png")
        open(p, "w").write("x")
        name = install_input(p)
        assert name == "face pic.png", name
        assert os.path.exists(os.path.join(inp, "face pic.png"))
    COMFY_INPUT = real_in

    # --- real build_refs.py through gen_refs(), submit_dir stubbed ---
    real_submit_dir = globals()["submit_dir"]
    written = {}

    def fake_submit_dir(wf_dir, progress=None):
        written["files"] = sorted(os.listdir(wf_dir))
        return [f"pid-{i}" for i in range(len(written["files"]))]

    globals()["submit_dir"] = fake_submit_dir
    try:
        with tempfile.TemporaryDirectory() as work:
            storyboard = {"scenes": [
                {"scene_number": 1, "name": "s1", "image_prompt": "a cat on a rooftop",
                 "negative_prompt": "", "duration_guidance": "5 sec"},
            ]}
            sb_path = os.path.join(work, "sb.json")
            json.dump(storyboard, open(sb_path, "w"))
            mp3_path = os.path.join(work, "silent.mp3")
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-t", "10", "-i", "anullsrc",
                             mp3_path], check=True, capture_output=True)
            gen_refs("demo", "pg13", sb_path, "anchor.png", mp3_path)
        assert written.get("files"), "no workflow JSONs written"
        assert all(f.endswith(".json") for f in written["files"]), written["files"]
    finally:
        globals()["submit_dir"] = real_submit_dir

    print("pipeline.py OK")


if __name__ == "__main__":
    demo()
