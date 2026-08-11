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
# Album profile json (profiles/<album>.json). Carries the things that are
# specific to one project -- character, wardrobe, world, locations -- so no
# script has to. Unset is valid: the pipeline then stays generic.
PROFILE = os.environ.get("STUDIO_PROFILE", "")

POLL_SECS = 2.0
# A WAN clip legitimately takes ~90s; this is a "ComfyUI vanished" backstop,
# not a render-time budget. There is exactly ONE job worker (studio/jobs.py),
# so a submit that never resolves wedges the whole queue -- must not hang.
SUBMIT_TIMEOUT = float(os.environ.get("SUBMIT_TIMEOUT", 1800))
# The poll loop is bounded by SUBMIT_TIMEOUT, but the CLI script run was not.
# A child blocking forever wedges the single worker, and per jobs._loop nothing
# else is coming to rescue the queue.
SCRIPT_TIMEOUT = float(os.environ.get("SCRIPT_TIMEOUT", 600))
MAX_POLL_ERRORS = 3  # consecutive connection failures before giving up on a poll

def _slug_tier(slug, tier):
    return f"{slug}_{tier}"


def _run_script(script, args, progress=None):
    progress = progress or (lambda msg: None)
    path = os.path.join(SCRIPTS, script)
    try:
        r = subprocess.run([sys.executable, path, *args], check=True,
                            capture_output=True, text=True, timeout=SCRIPT_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{script} did not finish within {SCRIPT_TIMEOUT:.0f}s") from None
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


def free_vram(progress=None):
    """Ask ComfyUI to unload its models. Returns True if it answered.

    Whisper and ComfyUI share ONE 24 GB card, and ComfyUI keeps ~21.5 GB
    resident between renders -- which is why every transcribe job on this box
    died with "CUDA failed with error out of memory" while nvidia-smi showed
    the GPU at 0% utilisation. Freeing here is the actual fix; lyrics.py's CPU
    fallback is the safety net for when it is not enough.

    Best effort by design: a ComfyUI that is down or too old for /free must not
    fail a transcription, it just means the fallback does the work.
    """
    req = urllib.request.Request(
        f"{COMFY}/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
    except Exception as e:
        if progress:
            progress(f"could not free ComfyUI VRAM ({e}) -- continuing")
        return False
    if progress:
        progress("asked ComfyUI to unload its models")
    return True


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


# Qwen-Image-Edit 2511 conditions on at most three reference images. Anything
# past the third is dropped HERE, loudly, rather than silently ignored by the
# encoder -- uploading five and being told nothing is worse than uploading five
# and being told two were not used.
MAX_ANCHOR_REFS = 3


def gen_anchor(images, view="front", n=8, progress=None, prefix=None, profile=None,
               guard="", prompt=""):
    """images: an unordered list of local reference paths, 0-3 used.

    Not face-then-outfit. One photograph often carries both, and demanding they
    be split made that image unusable; three references were impossible. The
    prompt describes what to take from them collectively (make_anchor.COMPOSITE)
    and the model composes.

    profile: the album's look, as {"anchor": {identity, wardrobe, body, views}}.
    WHO the character is is not in make_anchor.py any more -- it comes from the
    album, which is edited in the UI. The dict is written to a temp file because
    the CLI script takes a --profile path, which is also how it is used outside
    the studio. STUDIO_PROFILE is the fallback for a checkout with no database.
    """
    images = list(images or [])
    if len(images) > MAX_ANCHOR_REFS and progress:
        progress(f"{len(images)} references given; using the first {MAX_ANCHOR_REFS} "
                 f"-- the model conditions on no more than that")
    names = [install_input(p) for p in images[:MAX_ANCHOR_REFS]]
    prefix = prefix or "anchor_v2"  # matches make_anchor.py's own default
    args = ["--images", ",".join(names),
            "--n", str(n), "--view", view, "--prefix", prefix,
            # the TIER's wording. An anchor was previously built with guard=""
            # -- it got PINNED and nothing else, which is why a nude anchor for
            # an adult tier had no wording permitting it.
            "--guardrail", guard]
    if prompt:
        args += ["--prompt", prompt]
    with tempfile.TemporaryDirectory() as wf_dir:
        if profile:
            prof_path = os.path.join(wf_dir, "album_profile.json")
            with open(prof_path, "w") as f:
                json.dump(profile, f)
            args += ["--profile", prof_path]
        elif PROFILE:
            args += ["--profile", PROFILE]
        elif progress:
            progress("no album look set -- generic character-sheet wording")
        _run_script("make_anchor.py", [*args, "--outdir", wf_dir], progress)
        # the profile json sits in wf_dir; submit_dir only reads *.json
        # workflows, so it must not be left where they are
        if profile:
            os.remove(prof_path)
        return _submit_and_collect(wf_dir, prefix, "*.png", progress)


def _clip_records(paths, seed_re=r"clip_(\d+)"):
    out = []
    for p in paths:
        m = re.search(seed_re, os.path.basename(p))
        if m:
            out.append((p, m))
    return out


def gen_refs(slug, tier, storyboard_json, anchor_name, mp3_path, progress=None,
             limit=None, guard="", body="", cast=None):
    """limit=N renders only the first N clips.

    A full song is 40-80 references at ~15 s each, so committing to the whole
    set costs 10-20 minutes of the single GPU. limit lets you look at the first
    few and judge the storyboard before spending that.

    cast: {name: {"path": local anchor path, "desc": one line}} for the album's
    anchored supporting characters. Each anchor is copied into ComfyUI's input
    dir here -- build_refs.py names images, it does not move them.
    """
    bs = _slug_tier(slug, tier)
    args = ["--storyboard", storyboard_json, "--slug", bs,
            "--anchor", anchor_name, "--audio", mp3_path,
            "--guardrail", guard, "--body", body]
    with tempfile.TemporaryDirectory() as wf_dir:
        cast_path = None
        if cast:
            staged = {name: {"image": install_input(c["path"]), "desc": c.get("desc", "")}
                      for name, c in cast.items() if c.get("path")}
            # the cast file must live OUTSIDE wf_dir: submit_dir() posts every
            # *.json in there as a workflow, and this one is not one.
            fd, cast_path = tempfile.mkstemp(suffix=".json", prefix="cast_")
            with os.fdopen(fd, "w") as f:
                json.dump(staged, f)
            args += ["--cast", cast_path]
            if progress:
                progress(f"cast anchors staged: {', '.join(sorted(staged)) or 'none'}")
        try:
            _run_script("build_refs.py", [*args, "--outdir", wf_dir], progress)
        finally:
            if cast_path:
                os.remove(cast_path)
        if limit:
            keep = sorted(f for f in os.listdir(wf_dir) if f.endswith(".json"))[:int(limit)]
            for f in os.listdir(wf_dir):
                if f.endswith(".json") and f not in keep:
                    os.remove(os.path.join(wf_dir, f))
            if progress:
                progress(f"limited to first {len(keep)} of the song's clips")
        paths = _submit_and_collect(wf_dir, f"refs_{bs}", "*.png", progress)
    return [{"clip_idx": int(m.group(1)), "path": p, "seed": 7000 + int(m.group(1))}
            for p, m in _clip_records(paths)]


def reroll(slug, tier, storyboard_json, anchor_name, mp3_path, clip_indices, progress=None,
           guard="", body="", note="", cast=None):
    """guard/body are NOT optional in practice, whatever the defaults say.

    They were absent entirely until now, so every re-rolled frame was built
    without the tier's wording and without the album's body-consistency
    wording -- the frame you re-rolled to fix came back with the very drift the
    body text exists to prevent.

    note is the per-clip correction: "she is facing away, turn her toward the
    camera". It is appended to THIS clip's prompt only, which is what makes a
    re-roll a correction rather than another spin of the same wheel.
    """
    bs = _slug_tier(slug, tier)
    args = ["--storyboard", storyboard_json, "--slug", bs,
            "--audio", mp3_path, "--anchor", anchor_name,
            "--clips", ",".join(str(c) for c in clip_indices),
            "--guardrail", guard, "--body", body, "--note", note]
    with tempfile.TemporaryDirectory() as wf_dir:
        cast_path = None
        if cast:
            staged = {name: {"image": install_input(c["path"]), "desc": c.get("desc", "")}
                      for name, c in cast.items() if c.get("path")}
            fd, cast_path = tempfile.mkstemp(suffix=".json", prefix="cast_")
            with os.fdopen(fd, "w") as f:
                json.dump(staged, f)
            args += ["--cast", cast_path]
        try:
            _run_script("reroll_refs.py", [*args, "--outdir", wf_dir], progress)
        finally:
            if cast_path:
                os.remove(cast_path)
        paths = _submit_and_collect(wf_dir, f"reroll_{bs}", "*.png", progress)
    return [{"clip_idx": int(m.group(1)), "path": p, "seed": int(m.group(2))}
            for p, m in _clip_records(paths, r"clip_(\d+)_s(\d+)")]


def stage_refs(slug, tier, ref_paths):
    """Copy approved per-clip refs into COMFY_INPUT under the names
    build_song.py's clip loop expects: <slug>_<tier>_<version>_clip_NNN.png
    (see build_song.main: ref = f"{args.slug}_{args.version}_clip_{i:03d}.png")."""
    bs = _slug_tier(slug, tier)
    return [install_input(rec["path"], f"{bs}_clip_{rec['clip_idx']:03d}.png")
            for rec in ref_paths]


def gen_clips(slug, tier, storyboard_json, mp3_path, ref_paths, progress=None, limit=None,
              video_model="s2v", ref_motion=None, control_video=None, refine=False):
    """video_model: 's2v' (default, audio-driven) or 'i2v' (prompt-driven, no
    audio at all). See studio/models.py for what each is designed for."""
    # ref_paths must be staged before build_song.py runs -- it references
    # them by name inside the workflow, it doesn't take them as CLI input.
    stage_refs(slug, tier, ref_paths)
    install_input(mp3_path)  # WanSoundImageToVideo's LoadAudio needs it in COMFY_INPUT too
    bs = _slug_tier(slug, tier)
    args = ["--storyboard", storyboard_json, "--audio", mp3_path,
            "--slug", bs, "--video-model", video_model]
    # driving clips are read by PATH (LoadVideosFromFolder takes a string), so
    # unlike the images they are not installed into COMFY_INPUT
    if ref_motion:
        args += ["--ref-motion", ref_motion]
    if control_video:
        args += ["--control-video", control_video]
    if refine:
        args.append("--refine")
    with tempfile.TemporaryDirectory() as wf_dir:
        _run_script("build_song.py", [*args, "--outdir", wf_dir], progress)
        if limit:
            # a full song is 40-80 clips at ~90s each on one GPU; limit lets you
            # confirm the chain end to end before committing an hour to it
            keep = sorted(f for f in os.listdir(wf_dir) if f.endswith(".json"))[:int(limit)]
            for f in os.listdir(wf_dir):
                if f.endswith(".json") and f not in keep:
                    os.remove(os.path.join(wf_dir, f))
            if progress:
                progress(f"limited to first {len(keep)} clips")
        paths = _submit_and_collect(wf_dir, f"{bs}", "*.mp4", progress)
    return [{"clip_idx": int(m.group(1)), "path": p} for p, m in _clip_records(paths)]


def fix_ref(slug, tier, clip_idx, mode, image_path, seed, progress=None,
            face_path=None, mask_path=None, pad=(0, 0, 0, 0), instruction="",
            guard="", body="", feathering=40):
    """Repair one reference frame: face swap, inpaint or outpaint.

    Returns the same [{clip_idx, path, seed}] shape gen_refs/reroll return, so
    the caller inserts it as another candidate for that clip and the existing
    approve flow needs no change.
    """
    bs = _slug_tier(slug, tier)
    image_name = install_input(image_path)
    args = ["--mode", mode, "--image", image_name, "--slug", bs,
            "--clip", str(clip_idx), "--seed", str(seed),
            "--instruction", instruction, "--guardrail", guard, "--body", body,
            "--pad", ",".join(str(int(p)) for p in pad), "--feathering", str(int(feathering))]
    if face_path:
        args += ["--face", install_input(face_path)]
    if mask_path:
        args += ["--mask", install_input(mask_path)]
    with tempfile.TemporaryDirectory() as wf_dir:
        _run_script("fix_ref.py", [*args, "--outdir", wf_dir], progress)
        paths = _submit_and_collect(wf_dir, f"fix_{bs}", "*.png", progress)
    return [{"clip_idx": int(m.group(1)), "path": p, "seed": int(m.group(2))}
            for p, m in _clip_records(paths, r"clip_(\d+)_s(\d+)")]


def gen_artwork(slug, prompt, progress=None, anchor_path=None, source_path=None,
                guard="", n=1, size=1024):
    """Album cover from the album look. Three modes, one workflow:

      neither given   text-to-image. Every image input on
                      TextEncodeQwenImageEditPlus is optional, so with none
                      attached the reference model is a plain t2i model.
      anchor_path     the cover shows this album's actual protagonist rather
                      than a lookalike built from the same words.
      source_path     an existing cover as the second reference, so the prompt
                      MODIFIES it instead of starting over.

    make_anchor.py is reused rather than a fourth script written: a cover and a
    character sheet are the same request -- this prompt, these references, this
    size -- and it already takes --prompt and --guardrail.
    """
    prefix = f"artwork_{slug}"
    refs = [p for p in (anchor_path, source_path) if p]
    args = ["--n", str(n), "--prefix", prefix, "--view", "front",
            "--width", str(size), "--height", str(size),
            "--prompt", prompt, "--guardrail", guard,
            "--images", ",".join(install_input(p) for p in refs)]
    with tempfile.TemporaryDirectory() as wf_dir:
        _run_script("make_anchor.py", [*args, "--outdir", wf_dir], progress)
        return _submit_and_collect(wf_dir, prefix, "*.png", progress)


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

    # --- free_vram: never fatal, whatever ComfyUI does ---
    seen = []
    real_urlopen = urllib.request.urlopen

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        seen.append((req.full_url, json.loads(req.data)))
        return _Resp()

    urllib.request.urlopen = fake_urlopen
    try:
        assert free_vram() is True
        assert seen[0][0].endswith("/free"), seen
        assert seen[0][1] == {"unload_models": True, "free_memory": True}, seen

        def dead(req, timeout=None):
            raise urllib.error.URLError("connection refused")

        urllib.request.urlopen = dead
        notes = []
        # a ComfyUI that is down must not fail the transcription that called this
        assert free_vram(progress=notes.append) is False
        assert notes and "could not free" in notes[0], notes
    finally:
        urllib.request.urlopen = real_urlopen

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
