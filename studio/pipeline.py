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
import glob, json, os, re, shutil, subprocess, sys, tempfile, threading, time
import urllib.error, urllib.parse, urllib.request

import gpu
import models   # for the catalogue's default renderer; imports db only, no cycle

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
# Attempts per WORKFLOW on the comfy path, for an unreachable ComfyUI only.
# Two: the point is to survive a restart window, not to keep trying forever.
COMFY_ATTEMPTS = int(os.environ.get("COMFY_ATTEMPTS", 2))

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
    """Put a file where a workflow's LoadImage/LoadAudio will find it BY NAME.

    With more than one backend that means every box that could be handed the
    job, because SwarmUI picks the backend and the studio does not get to know
    which. Hence SWARM_INPUT_DIRS: unset, this is exactly the single-box copy it
    has always been.
    """
    name = name or os.path.basename(local_path)
    os.makedirs(COMFY_INPUT, exist_ok=True)
    shutil.copy(local_path, os.path.join(COMFY_INPUT, name))
    for dest in SWARM_INPUT_DIRS:
        # NOT fatal. A part-time box that is off cannot receive this file -- but
        # it cannot receive a job either, because SwarmUI will not route to a
        # backend that is down, so failing the render here would refuse work the
        # remaining boxes can do. A box that is UP and rejects the copy is the
        # case worth having in the journal, which is why this is not silent.
        try:
            # --chmod=F664 is not tidiness. peaches runs ComfyUI in Docker as
            # uid 1025 while this copies as uid 1000, so a file arriving 0600
            # is unreadable there -- and ComfyUI reports that as
            # "ModelMMAP allocation failed", which reads as an out-of-memory
            # error and sent a whole session looking at VRAM. Measured
            # 2026-08-12; the fix is one flag here.
            subprocess.run(["rsync", "-a", "--chmod=F664",
                            local_path, f"{dest.rstrip('/')}/{name}"],
                           check=True, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            err = getattr(e, "stderr", "") or str(e)
            print(f"could not stage {name} to {dest}: {err.strip()[-300:]}", file=sys.stderr)
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


def comfy_queue():
    """{"running": n, "pending": n} from ComfyUI's own /queue, or None if it did
    not answer.

    The studio's queue is NOT ComfyUI's. This app serialises its own jobs
    through one worker because the card fits one render at a time -- but ComfyUI
    is unauthenticated and anyone on the tailnet can submit to it directly, and
    the studio would then submit alongside them onto a card already holding a
    23.5 GB transformer. "Nothing running" on the Jobs page has only ever meant
    "nothing of OURS is running"; this is the other half of the answer.

    Attribution is deliberately not attempted: ComfyUI's queue entries carry no
    identity, so a count that claimed to know whose work it was would be made up.
    """
    try:
        q = _get(f"{COMFY}/queue")
    except Exception:
        return None
    return {"running": len(q.get("queue_running") or []),
            "pending": len(q.get("queue_pending") or [])}


SWARM = os.environ.get("SWARM_URL", "http://127.0.0.1:7801")
# comfy | swarm. DEFAULT comfy, deliberately: unset must mean exactly today's
# behaviour, so this ships without a flag day. Only "swarm" routes renders
# through SwarmUI and therefore onto more than one box.
RENDER_BACKEND = os.environ.get("RENDER_BACKEND", "comfy")
# Where a remote backend's COMFY_INPUT lives, as rsync destinations:
#   SWARM_INPUT_DIRS="gamingpc:/home/jon/ComfyUI/input,peaches:/mnt/user/comfy/input"
# There is NO upload API in SwarmUI -- `UploadImage` answers HTTP 400 and is not
# in the RegisterAPICall list (measured 2026-08-12) -- so reference images
# reaching another box is a filesystem problem, not an API one. Empty (the
# default) means single-box, which is what the comfy path has always been.
SWARM_INPUT_DIRS = [d.strip() for d in os.environ.get("SWARM_INPUT_DIRS", "").split(",") if d.strip()]
# A ceiling on attempts per workflow, or 0 for "one free draw, then every
# running backend in turn". See _attempt_plan for why that is the shape.
RENDER_ATTEMPTS = int(os.environ.get("RENDER_ATTEMPTS", 0))

_swarm_sid = None


def _swarm_post(path, payload, timeout=30):
    """POST to SwarmUI. Separate from _post because a generation is not a 30s
    request -- GenerateText2Image BLOCKS for the whole render (a clip is ~90s),
    and _post's socket timeout would abandon every one of them."""
    req = urllib.request.Request(SWARM + path, data=json.dumps(payload).encode(),
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {}
    except urllib.error.URLError as e:
        raise RuntimeError(f"cannot reach SwarmUI at {SWARM} ({e.reason}) -- is it running?") from e


def _swarm_session(renew=False):
    """One session, reused. GetNewSession per submit would be a request per
    workflow for a value that does not change; expiry is handled where it shows
    up (an invalid_session_id error) rather than guessed at ahead of time."""
    global _swarm_sid
    if renew or not _swarm_sid:
        _swarm_sid = _swarm_post("/API/GetNewSession", {}).get("session_id")
        if not _swarm_sid:
            raise RuntimeError(f"SwarmUI at {SWARM} would not issue a session")
    return _swarm_sid


def _swarm_call(path, payload, timeout=30):
    """_swarm_post with the session attached, renewed once if it has expired.

    Sessions do expire, and the caller that discovers it is whichever one ran
    next -- a Jobs page that went permanently blank, or a render refused after
    an idle night. SwarmUI's own SwarmSwarmBackend.cs:154 recovers from exactly
    this error_id the same way.
    """
    data = _swarm_post(path, {**payload, "session_id": _swarm_session()}, timeout)
    if isinstance(data, dict) and data.get("error_id") == "invalid_session_id":
        data = _swarm_post(path, {**payload, "session_id": _swarm_session(renew=True)}, timeout)
    return data


def swarm_backends():
    """[{id, title, status, address}] from SwarmUI, or None if it did not answer.

    A SIBLING of comfy_queue(), not a replacement (SWARM_PIPELINE_PLAN.md phase
    4). With two backends there are two answers, and collapsing them into one
    number re-creates exactly the confusion comfy_queue's docstring was written
    to end.

    Worth having before any of the routing work: a backend sitting IDLE because
    the VPN dropped, or registered but empty, is the single most useful thing
    this page could say, and today nothing in the studio can say it. Measured
    2026-08-12: backend 1 was reachable, "running", and had no models at all --
    it failed a real workflow in 0.6s. Only a page that lists it gives anyone a
    reason to look.

    Best effort: SwarmUI not running is not an error for a studio that talks to
    ComfyUI directly, which is still the only path that renders anything.
    """
    try:
        data = _swarm_call("/API/ListBackends", {})
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    out = []
    for key, b in sorted(data.items(), key=lambda kv: str(kv[0])):
        if not isinstance(b, dict):
            continue
        out.append({"id": key, "title": b.get("title") or b.get("type") or "?",
                    "status": b.get("status") or "?",
                    "address": (b.get("settings") or {}).get("Address") or ""})
    return out or None


def _say(progress, msg):
    """Report from inside CLEANUP, where the reporter itself may raise.

    jobs.py's progress() raises Cancelled on EVERY call once a cancel has been
    requested -- which is exactly when this code runs. Calling it straight meant
    the /queue delete threw Cancelled out of abandon() before /interrupt was
    ever tried, so a cancelled job kept the GPU: the precise outcome the cancel
    work exists to prevent. Cleanup must never be abortable by its own logging.
    """
    if not progress:
        return
    try:
        progress(msg)
    except BaseException:
        pass


def abandon(pid, progress=None):
    """Tell ComfyUI to stop making something nobody is waiting for any more.

    Removes it from the pending queue AND interrupts it if it is the one
    running. /interrupt takes a prompt_id and no-ops when that prompt is not
    the running one, so this can never stop another client's render -- which
    matters, because ComfyUI is unauthenticated and the studio is not
    necessarily its only caller.

    Best effort, and deliberately silent about the shape of the answer: both
    endpoints return an empty 200 body, which _post cannot decode. A cancel
    must not fail because the acknowledgement was empty.
    """
    for url, payload in ((f"{COMFY}/queue", {"delete": [pid]}),
                         (f"{COMFY}/interrupt", {"prompt_id": pid})):
        try:
            _post(url, payload)
        except Exception as e:
            _say(progress, f"could not stop ComfyUI prompt {pid}: {e}")


def _submit_one(wf, name, progress, cancelled):
    """POST one workflow and wait for it. Returns its prompt_id.

    Split out of submit_dir so a single workflow can be retried without
    re-running the eighty that already rendered.
    """
    start = time.time()
    resp = _post(f"{COMFY}/prompt", {"prompt": wf})
    pid = resp.get("prompt_id")
    if not pid:
        raise RuntimeError(f"submit rejected: {name}: {resp}")
    errors = 0
    try:
        while True:
            if cancelled and cancelled():
                # jobs.py's progress raises Cancelled here, which is the
                # normal exit; the handler below then stops ComfyUI. The
                # raise is for a caller that supplied a checkpoint but a
                # progress that does not stop the job -- having decided to
                # abandon the render, never return as though it had run.
                progress(f"cancelled -- stopping {os.path.splitext(name)[0]} in ComfyUI")
                raise RuntimeError(f"cancelled while rendering {name}")
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
    except BaseException:
        # Stopped waiting, for ANY reason -- cancel, timeout, ComfyUI gone.
        # Leaving it running means the GPU keeps working on output nothing
        # will ever collect, and the file it eventually writes is exactly
        # the orphan that used to be swept up by the NEXT job.
        abandon(pid, progress)
        raise
    return pid


def submit_dir(wf_dir, progress=None):
    progress = progress or (lambda msg: None)
    # jobs.py attaches this to the progress it passes in. Without it the poll
    # loop in _submit_one has no cancellation checkpoint at all: progress() is
    # the checkpoint and it is only called once a workflow FINISHES, so a cancel
    # during a single 90-second render did nothing until that render was done
    # -- and ComfyUI kept the GPU and wrote the file anyway.
    cancelled = getattr(progress, "cancelled", None)
    files = sorted(f for f in os.listdir(wf_dir) if f.endswith(".json"))
    ids = []
    for i, name in enumerate(files, 1):
        wf = json.load(open(os.path.join(wf_dir, name)))
        start = time.time()
        for attempt in range(1, COMFY_ATTEMPTS + 1):
            try:
                pid = _submit_one(wf, name, progress, cancelled)
                break
            except RuntimeError as e:
                # ONE workflow is retried, not the job. jobs.py already retries
                # the whole job when ComfyUI is unreachable, and that is the
                # wrong grain for a render: a five-second restart window during
                # clip 60 of 80 throws away 59 finished clips and an hour of
                # GPU to recover ninety seconds of work.
                #
                # Narrow on purpose. A cancel is what the user asked for; a
                # workflow ComfyUI REFUSED (a missing model, a bad graph) is a
                # real error and retrying it just fails more slowly; a timeout
                # has already spent SUBMIT_TIMEOUT and would spend it again.
                # Only "could not reach it" earns another go.
                if attempt >= COMFY_ATTEMPTS or "cannot reach comfyui" not in str(e).lower():
                    raise
                progress(f"{name}: {e} -- retrying ({attempt + 1}/{COMFY_ATTEMPTS})")
                time.sleep(POLL_SECS)
        ids.append(pid)
        progress(f"{i}/{len(files)} {os.path.splitext(name)[0]} {time.time()-start:.0f}s")
    return ids


def submitted_prefixes(wf_dir):
    """The basename of every filename_prefix in the workflows about to be
    submitted -- i.e. the names ComfyUI will actually write.

    `make_anchor.py` writes `anchor_v2/front_s<seed>`, `build_refs.py` writes
    `refs_<slug>/clip_<n>`; ComfyUI appends `_00001_.png` to whichever it is
    given. Reading them out is how a collected file can be tied back to the
    job that asked for it.
    """
    out = set()
    for name in sorted(f for f in os.listdir(wf_dir) if f.endswith(".json")):
        try:
            wf = json.load(open(os.path.join(wf_dir, name)))
        except (ValueError, OSError):
            continue
        for node in (wf.values() if isinstance(wf, dict) else []):
            if not isinstance(node, dict):
                continue
            p = (node.get("inputs") or {}).get("filename_prefix")
            if isinstance(p, str) and p:
                out.add(os.path.basename(p))
    return out


def _wf_prefix(wf):
    """The basename of this ONE workflow's filename_prefix, or "".

    submitted_prefixes() answers the same question for a whole directory; this
    is the per-workflow form, because on the swarm path each generation's output
    has to be written back under the name THAT workflow asked for.
    """
    for node in (wf.values() if isinstance(wf, dict) else []):
        if not isinstance(node, dict):
            continue
        p = (node.get("inputs") or {}).get("filename_prefix")
        if isinstance(p, str) and p:
            return os.path.basename(p)
    return ""


def _attempt_plan():
    """Which backend to ask, in order: None (SwarmUI's own choice) then each
    running backend pinned, until one of them can run the workflow.

    Because curating models per box is the routing policy, and a policy that
    only says where a job CAN succeed is not routing -- SwarmUI still picks the
    backend, and a miss is not requeued: PleaseRedirectException is thrown only
    when the websocket fails to CONNECT (ComfyUIAPIAbstractBackend.cs:295-303).
    A failure after the socket is up sets that backend idle and rethrows
    (:575-582). So the studio does the walk.

    Measured 2026-08-12, and this is why blind retries were not enough: an
    anchor submitted unpinned to a fleet where one box of three holds
    Qwen-Image-Edit was refused twice in a row with "No images were generated".
    Each miss costs about a second, at validation, before any GPU work.

    A generator on purpose: the backend list is only fetched once something has
    actually failed, so the ordinary path is one API call as before.
    """
    yield None
    ids = [b["id"] for b in (swarm_backends() or []) if b.get("status") == "running"]
    left = (RENDER_ATTEMPTS - 1) if RENDER_ATTEMPTS else len(ids)
    for i in ids[:max(0, left)]:
        yield i


def _swarm_generate(wf_text, progress, cancelled, backend=None):
    """One workflow through SwarmUI. Returns its images[] entries.

    GenerateText2Image blocks for the whole render, so the request runs on a
    thread and this polls the cancel checkpoint beside it. Without that, a
    cancel during a 90-second clip would do nothing until the clip was finished
    -- the exact defect submit_dir's poll loop was rewritten to fix, and it must
    not come back through the other door. InterruptAll is scoped to OUR session
    (other_sessions stays false), so it cannot stop somebody else's render.
    """
    box = {}
    payload = {"images": 1, "comfyworkflowraw": wf_text}
    if backend is not None:
        payload["exactbackendid"] = backend

    def run():
        try:
            box["r"] = _swarm_call("/API/GenerateText2Image", payload, timeout=SUBMIT_TIMEOUT)
        except BaseException as e:      # noqa: BLE001 -- re-raised on the caller's thread
            box["e"] = e

    t = threading.Thread(target=run, daemon=True, name="swarm-generate")
    t.start()
    start = time.time()
    while t.is_alive():
        stop = ("cancelled while rendering" if cancelled and cancelled() else
                f"did not finish within {SUBMIT_TIMEOUT:.0f}s"
                if time.time() - start > SUBMIT_TIMEOUT else "")
        if stop:
            _say(progress, f"{stop} -- interrupting SwarmUI")
            try:
                _swarm_call("/API/InterruptAll", {"other_sessions": False})
            except Exception as e:
                _say(progress, f"could not interrupt SwarmUI: {e}")
            raise RuntimeError(stop)
        t.join(POLL_SECS)
    if "e" in box:
        raise box["e"]
    resp = box.get("r") or {}
    if resp.get("error") or resp.get("error_id"):
        raise RuntimeError(f"SwarmUI refused it: {resp.get('error') or resp['error_id']}")
    return resp.get("images") or []


def _swarm_fetch(entry, out_dir, prefix):
    """Write one images[] entry into out_dir under the name the COMFY path would
    have produced: <prefix>_00001_.<ext>, the next free counter.

    This mapping is the whole reason collect() cannot simply be pointed at
    SwarmUI's own output. Swarm names files `0120001--unknown.png`, which
    carries none of the `clip_(\\d+)` or seed information that seven gen_*
    wrappers parse straight out of basenames.

    Both documented forms are handled (T2IAPI.cs:72): a View/... path to GET,
    and the data: URI it says can appear "in some cases".
    """
    if entry.startswith("data:"):
        import base64
        head, _, b64 = entry.partition(",")
        ext = "." + (head.split("/", 1)[-1].split(";")[0] or "png")
        blob = base64.b64decode(b64)
    else:
        ext = os.path.splitext(urllib.parse.urlsplit(entry).path)[1] or ".png"
        url = entry if entry.startswith("http") else f"{SWARM}/{entry.lstrip('/')}"
        try:
            with urllib.request.urlopen(url, timeout=300) as r:
                blob = r.read()
        except urllib.error.URLError as e:
            raise RuntimeError(f"cannot reach SwarmUI at {SWARM} to fetch {entry} ({e.reason})") from e
    n = 1
    while os.path.exists(os.path.join(out_dir, f"{prefix}_{n:05d}_{ext}")):
        n += 1
    dest = os.path.join(out_dir, f"{prefix}_{n:05d}_{ext}")
    with open(dest, "wb") as f:
        f.write(blob)
    return dest


def submit_swarm(wf_dir, prefix_dir, pattern, progress=None):
    """submit_dir + collect for RENDER_BACKEND=swarm, and they cannot be split.

    The comfy path DISCOVERS its outputs by globbing a directory; SwarmUI NAMES
    them in the response, and that response is the only authority -- a render on
    another box never touches this filesystem, and a collect() that globbed
    would return an empty list and read as a bad render rather than as a job
    that went somewhere else. Which is why this is one function.

    On a LOCAL backend the rendering ComfyUI still writes its own file into
    COMFY_OUTPUT (measured 2026-08-12: both copies exist and are not
    byte-identical). That file is preferred where it appears, so backend 0
    produces the same filenames under either RENDER_BACKEND instead of a
    downloaded duplicate beside an orphan.
    """
    progress = progress or (lambda msg: None)
    cancelled = getattr(progress, "cancelled", None)
    files = sorted(f for f in os.listdir(wf_dir) if f.endswith(".json"))
    out_dir = os.path.join(COMFY_OUTPUT, prefix_dir)
    os.makedirs(out_dir, exist_ok=True)
    seen = set(collect(prefix_dir, pattern))
    got = []
    for i, name in enumerate(files, 1):
        if cancelled and cancelled():
            progress(f"cancelled -- not submitting {os.path.splitext(name)[0]}")
            raise RuntimeError(f"cancelled while rendering {name}")
        text = open(os.path.join(wf_dir, name)).read()
        prefix = _wf_prefix(json.loads(text)) or os.path.splitext(name)[0]
        start = time.time()
        entries, last = None, None
        for pin in _attempt_plan():
            try:
                entries = _swarm_generate(text, progress, cancelled, pin)
                break
            except RuntimeError as e:
                # A cancel is not a failure to retry, and it is the one thing
                # here that must never be retried -- the user asked for this to
                # stop, and a second attempt would hand the GPU straight back.
                if "cancelled" in str(e).lower():
                    raise
                last = e
                # Every miss is logged WITH THE BOX IT MISSED ON. A silent
                # retry that halves throughput is worse than a failure because
                # nobody goes looking, and one that does not say where it went
                # leaves the model-curation policy unmeasurable.
                progress(f"{name}: refused by "
                         f"{'backend ' + str(pin) if pin is not None else 'SwarmUI'}: {e}")
        if entries is None:
            raise last or RuntimeError(f"no backend would run {name}")
        mine = [p for p in collect(prefix_dir, pattern)
                if p not in seen and os.path.basename(p).startswith(prefix + "_")]
        got += mine or [_swarm_fetch(e, out_dir, prefix) for e in entries]
        seen |= set(collect(prefix_dir, pattern))
        progress(f"{i}/{len(files)} {os.path.splitext(name)[0]} {time.time()-start:.0f}s")
    return sorted(got, key=lambda p: _natkey(os.path.basename(p)))


def _submit_and_collect(wf_dir, prefix_dir, pattern, progress):
    """submit_dir() + collect(), returning only the files THIS submit asked for.

    Two filters, and both are load-bearing.

    NEW SINCE WE STARTED, because ComfyUI's SaveImage/SaveVideo never overwrite
    -- they bump a counter suffix -- so a prefix dir reused across runs
    (anchor_v2 already has 6-16 images from earlier sessions) would otherwise
    mix old and new candidates into one result.

    AND NAMED BY ONE OF OUR OWN PREFIXES, because "new" is not the same as
    "ours". A cancelled job's workflow used to keep rendering inside ComfyUI
    and write its image after the studio had stopped waiting; the NEXT job's
    before/after diff then swept that file up and filed it under a different
    tier, view and prompt. Measured: job 170 was cancelled, ComfyUI wrote
    front_s1580385877 at 22:17:19, and job 171 -- which submitted seed
    s2002116300 and nothing else -- returned both. Harmless there because both
    were the same sheet. A cancelled XXX nude landing in a G group is not.

    Anything else that appears is REPORTED, not silently dropped: this directory
    is shared with anyone else who can reach an unauthenticated ComfyUI.

    RENDER_BACKEND=swarm replaces both filters with submit_swarm(), which needs
    neither: on that path the response NAMES its outputs, so there is nothing to
    diff and nothing to attribute. What stays shared is everything either path
    can get wrong the same way -- the card, and the cleanup of what a stopped
    run managed to write. This function is also the ONLY place that branches on
    the backend: the seven gen_* wrappers above do not know there is one.
    """
    # One guard for all seven gen_* wrappers, not a copy per caller: every one
    # of them reaches a renderer through here, and a starved card fails them all
    # the same way -- an OOM that presents as a job which succeeded and wrote
    # nothing. gpu.preflight takes the card back from ollama or refuses with
    # the numbers; it never refuses because something was unreachable.
    swarm = RENDER_BACKEND == "swarm"
    if swarm:
        # The local card is one backend of three here and SwarmUI decides which
        # one runs this. Refusing every render because THIS card is full would
        # be a wrong answer for a job bound for gamingpc -- so ollama is still
        # asked for the card back (backend 0 is this card), but a full card is
        # no longer grounds to refuse.
        if gpu.ollama_holding():
            gpu.release_ollama(progress)
    else:
        gpu.preflight(progress)
    mine = submitted_prefixes(wf_dir)
    before = set(collect(prefix_dir, pattern))
    try:
        if swarm:
            return submit_swarm(wf_dir, prefix_dir, pattern, progress)
        submit_dir(wf_dir, progress)
    except BaseException:
        # Garbage-collect what a cancelled or failed run did manage to write.
        # Only files matching OUR prefixes and newer than our start, so this
        # can never remove a candidate belonging to another job.
        for p in _mine_only(collect(prefix_dir, pattern), before, mine):
            try:
                os.remove(p)
                _say(progress, f"removed {os.path.basename(p)}, written by a run that stopped")
            except OSError:
                pass
        raise
    fresh = [p for p in collect(prefix_dir, pattern) if p not in before]
    if not mine:
        return fresh            # no prefix to match on: better than losing the render
    ours = _mine_only(fresh, before, mine)
    stray = [p for p in fresh if p not in ours]
    if stray and progress:
        progress(f"ignored {len(stray)} file(s) in {prefix_dir} written by something else: "
                 + ", ".join(os.path.basename(p) for p in stray[:4]))
    return ours


def _mine_only(paths, before, mine):
    if not mine:
        return []
    # WITH the counter separator. ComfyUI appends "_00001_", so bare-prefix
    # matching makes seed front_s52862573 also claim front_s528625731's file --
    # seeds are random and vary in length, so one being a prefix of another is
    # ordinary. The consequence is the cross-sheet leak this function exists to
    # stop, so the one character matters.
    keep = tuple(m + "_" for m in mine)
    return [p for p in paths
            if p not in before and os.path.basename(p).startswith(keep)]


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


# What the anchor form may send through to make_anchor.py. Named here so the
# route, the form and the renderer cannot drift apart about which knobs exist.
# key -> the flag make_anchor.py actually declares. An explicit map, not
# k.replace("_", "-"): that rule gives --sampler-name, which argparse rejects,
# and the failure would land at render time on a job the form said was fine.
ANCHOR_RENDER_FLAGS = {"mode": "--mode", "negative": "--negative",
                       "ref_method": "--ref-method", "steps": "--steps",
                       "cfg": "--cfg", "sampler_name": "--sampler",
                       "scheduler": "--scheduler", "denoise": "--denoise",
                       # The BASE seed. Omitted means make_anchor draws a random
                       # one, which is what makes a second click of Generate
                       # produce different sheets, and that stays the default.
                       # A CFG sweep must pin it: with a fresh random base at
                       # every guidance value, the images differ by seed AND by
                       # cfg at once, and nothing in the result is attributable
                       # to the knob being swept.
                       "seed": "--seed"}
ANCHOR_RENDER_KEYS = tuple(ANCHOR_RENDER_FLAGS)


def gen_anchor(images, view="front", n=8, progress=None, prefix=None, profile=None,
               guard="", prompt="", render=None):
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
    # Render settings, straight through to the CLI. Absent means make_anchor's
    # own defaults, which are exactly today's behaviour -- this cannot change a
    # render nobody asked to change.
    render = {k: v for k, v in (render or {}).items()
              if k in ANCHOR_RENDER_KEYS and v not in (None, "")}
    flags = []
    for k, v in sorted(render.items()):
        flags += [ANCHOR_RENDER_FLAGS[k], str(v)]
    if render and progress:
        progress("render settings: " + ", ".join(f"{k}={v}" for k, v in sorted(render.items())))
    args = ["--images", ",".join(names),
            "--n", str(n), "--view", view, "--prefix", prefix, *flags,
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
              video_model=None, ref_motion=None, control_video=None, refine=False):
    """video_model: a renderer value from models.renderable("video") --
    'ltx25' (default) and 'ltx' are the audio-conditioned LTX paths, 's2v' is
    WAN's, and 'i2v' is prompt-driven with no audio at all. None means "ask the
    catalogue", so this default cannot drift from the one the song page offers.
    See studio/models.py for what each is designed for."""
    video_model = video_model or models.default_cli("video")
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
    global _post, _get, COMFY_OUTPUT, COMFY_INPUT, POLL_SECS

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

    # --- one unreachable moment costs ONE workflow, not the whole job -------
    # jobs.py retries the job; that is the wrong grain for a render. A restart
    # window during clip 60 of 80 used to throw away 59 finished clips.
    posts = []

    def flaky_post(url, payload):
        posts.append(url)
        if url.endswith("/prompt") and len(posts) == 1:
            raise RuntimeError("cannot reach ComfyUI at http://x (Connection refused)")
        return {"prompt_id": "pid-r"}

    real_poll_secs = POLL_SECS
    POLL_SECS = 0.01
    _post, _get = flaky_post, (lambda url: {"pid-r": {}})
    try:
        with tempfile.TemporaryDirectory() as d:
            json.dump({"_name": "r"}, open(os.path.join(d, "clip_r.json"), "w"))
            said = []
            assert submit_dir(d, said.append) == ["pid-r"]
            assert any("retrying (2/2)" in m for m in said), said

        # ...but a workflow ComfyUI REFUSED is a real error, not a blip, and
        # retrying it only fails more slowly
        refusals = []

        def refusing_post(url, payload):
            refusals.append(url)
            return {"error": "invalid prompt"}

        _post = refusing_post
        with tempfile.TemporaryDirectory() as d:
            json.dump({"_name": "x"}, open(os.path.join(d, "clip_x.json"), "w"))
            try:
                submit_dir(d)
                raise AssertionError("a refused workflow was accepted")
            except RuntimeError as e:
                assert "submit rejected" in str(e), e
        assert len(refusals) == 1, f"a refusal was retried: {refusals}"
    finally:
        _post, _get = real_post, real_get
        POLL_SECS = real_poll_secs

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

    # --- a cancel reaches the poll loop, and ComfyUI is TOLD ---
    # The whole defect: progress() was the only cancellation checkpoint and it
    # is called once a workflow finishes, so a cancel during a 90s render did
    # nothing until the render was over -- and ComfyUI was never told at all.
    stopped = []

    def cancel_post(url, payload):
        if url.endswith("/prompt"):
            return {"prompt_id": "pid-x"}
        stopped.append((url.rsplit("/", 1)[-1], payload))
        return {}

    def prog(msg):
        pass
    prog.cancelled = lambda: True

    _post, _get = cancel_post, (lambda url: {})      # history never fills in
    # Short, so that a submit_dir which IGNORES the cancel fails this case in
    # seconds with "did not finish within", instead of sitting here for the real
    # 1800s backstop and looking like a hang rather than a broken cancel.
    SUBMIT_TIMEOUT = 5
    try:
        with tempfile.TemporaryDirectory() as d:
            json.dump({"_name": "c"}, open(os.path.join(d, "wf.json"), "w"))
            t0 = time.time()
            try:
                submit_dir(d, prog)
                raise AssertionError("a cancelled submit returned as though it had rendered")
            except RuntimeError as e:
                assert "cancelled while rendering" in str(e), \
                    f"the cancel was not what stopped it: {e}"
            assert time.time() - t0 < 2, \
                "the cancel waited for the render instead of stopping it"
    finally:
        _post, _get = real_post, real_get
        SUBMIT_TIMEOUT = real_timeout
    assert [u for u, _ in stopped] == ["queue", "interrupt"], stopped

    # --- cleanup must survive a progress() that raises -----------------------
    # jobs.py's progress raises Cancelled on EVERY call once a cancel is
    # requested, which is exactly when abandon() runs. Reporting the first
    # failure used to throw out of the loop before /interrupt was tried, so the
    # GPU kept rendering a job the user had cancelled.
    class _Boom(Exception):
        pass

    def raising(msg):
        raise _Boom()

    hit = []
    _post_real = globals()["_post"]

    def _dead(url, payload):
        hit.append(url.rsplit("/", 1)[-1])
        raise RuntimeError("ComfyUI gone")

    globals()["_post"] = _dead
    try:
        abandon("pid-y", raising)          # must NOT raise
    finally:
        globals()["_post"] = _post_real
    assert hit == ["queue", "interrupt"], \
        f"cleanup stopped at the first failure because its own logging raised: {hit}"
    assert stopped[0][1] == {"delete": ["pid-x"]}, stopped
    # targeted, so it can never interrupt another client's render
    assert stopped[1][1] == {"prompt_id": "pid-x"}, stopped

    # --- a collected file must be one THIS submit asked for ---
    real_submit = globals()["submit_dir"]
    real_out = COMFY_OUTPUT
    import gpu
    real_preflight = gpu.preflight
    gpu.preflight = lambda progress=None: None
    try:
        with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as d:
            COMFY_OUTPUT = out
            os.makedirs(os.path.join(out, "anchor_v2"))
            sheet = lambda n: os.path.join(out, "anchor_v2", n)
            open(sheet("front_s111_00001_.png"), "w").close()      # an earlier run
            json.dump({"1": {"inputs": {"filename_prefix": "anchor_v2/front_s999"}}},
                      open(os.path.join(d, "wf.json"), "w"))
            assert submitted_prefixes(d) == {"front_s999"}, submitted_prefixes(d)

            def writing_submit(wf_dir, progress=None):
                open(sheet("front_s999_00001_.png"), "w").close()   # ours
                open(sheet("front_s777_00001_.png"), "w").close()   # a cancelled job's
                return ["pid"]

            globals()["submit_dir"] = writing_submit
            said = []
            got = _submit_and_collect(d, "anchor_v2", "*.png", said.append)
            assert [os.path.basename(p) for p in got] == ["front_s999_00001_.png"], got
            assert any("front_s777" in m for m in said), \
                f"a file written by something else was dropped in silence: {said}"

            # --- and what a stopped run wrote is collected as garbage ---
            def failing_submit(wf_dir, progress=None):
                open(sheet("front_s999_00002_.png"), "w").close()
                raise RuntimeError("cancelled while rendering wf.json")

            globals()["submit_dir"] = failing_submit
            try:
                _submit_and_collect(d, "anchor_v2", "*.png", said.append)
                raise AssertionError("a cancelled submit returned a result")
            except RuntimeError:
                pass
            left = sorted(os.path.basename(p) for p in collect("anchor_v2", "*.png"))
            assert "front_s999_00002_.png" not in left, f"the cancelled run's file survived: {left}"
            assert "front_s111_00001_.png" in left, f"GC ate an earlier run's sheet: {left}"
            assert "front_s777_00001_.png" in left, f"GC ate another job's file: {left}"
    finally:
        globals()["submit_dir"] = real_submit
        COMFY_OUTPUT = real_out
        gpu.preflight = real_preflight

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

    # --- RENDER_BACKEND: the seam, and the flag day that must not happen -----
    # The acceptance criterion from SWARM_PIPELINE_PLAN.md phase 2 is that both
    # paths produce the SAME FILENAMES, because _clip_records parses clip_(\d+)
    # and a seed out of basenames and seven wrappers depend on it.
    global RENDER_BACKEND
    real_backend, real_poll = RENDER_BACKEND, POLL_SECS
    real_submit_swarm, real_submit = globals()["submit_swarm"], globals()["submit_dir"]
    real_swarm_call = globals()["_swarm_call"]
    real_out = COMFY_OUTPUT
    real_preflight, real_holding = gpu.preflight, gpu.ollama_holding
    gpu.preflight = lambda progress=None: None
    gpu.ollama_holding = lambda: []
    real_urlopen = urllib.request.urlopen

    class _Blob:
        def __init__(self, b): self.b = b
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self.b

    def _never(*a, **kw):
        raise AssertionError("_submit_and_collect took the other backend's path")

    def _swarm(gen):
        """A fake SwarmUI: three running backends, and `gen` for everything
        else. ListBackends has to answer, because the retry walk is what turns
        "this box has no such model" into "some other box does"."""
        def call(path, payload, timeout=30):
            if path.endswith("ListBackends"):
                return {str(i): {"status": "running", "title": f"box{i}"} for i in range(3)}
            return gen(path, payload, timeout)
        return call

    try:
        with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as d:
            COMFY_OUTPUT = out
            sheets = os.path.join(out, "anchor_v2")
            os.makedirs(sheets)
            json.dump({"1": {"inputs": {"filename_prefix": "anchor_v2/front_s42"}}},
                      open(os.path.join(d, "wf.json"), "w"))

            # 1. unset means comfy, and comfy must not touch SwarmUI at all
            RENDER_BACKEND = "comfy"
            globals()["submit_swarm"] = _never

            def writing_submit(wf_dir, progress=None):
                open(os.path.join(sheets, "front_s42_00001_.png"), "w").close()
                return ["pid"]

            globals()["submit_dir"] = writing_submit
            comfy_got = _submit_and_collect(d, "anchor_v2", "*.png", lambda m: None)
            assert [os.path.basename(p) for p in comfy_got] == ["front_s42_00001_.png"], comfy_got

            # 2. swarm on a LOCAL backend: the rendering ComfyUI wrote the file
            # itself, so that one is the result -- not a downloaded duplicate
            # beside an orphan nobody collects.
            os.remove(comfy_got[0])
            RENDER_BACKEND = "swarm"
            globals()["submit_swarm"] = real_submit_swarm
            globals()["submit_dir"] = _never

            def local_backend(path, payload, timeout=30):
                open(os.path.join(sheets, "front_s42_00001_.png"), "w").close()
                return {"images": ["View/local/raw/2026-08-12/0120001--unknown.png"]}

            globals()["_swarm_call"] = _swarm(local_backend)
            swarm_got = _submit_and_collect(d, "anchor_v2", "*.png", lambda m: None)
            assert [os.path.basename(p) for p in swarm_got] \
                   == [os.path.basename(p) for p in comfy_got], (swarm_got, comfy_got)
            assert os.listdir(sheets) == ["front_s42_00001_.png"], \
                f"a local render was downloaded a second time: {os.listdir(sheets)}"

            # 3. swarm on a REMOTE backend: nothing lands on this filesystem, so
            # the response is the only authority and the download must be
            # written under the name the WORKFLOW asked for.
            os.remove(swarm_got[0])
            globals()["_swarm_call"] = _swarm(lambda path, payload, timeout=30: {
                "images": ["View/local/raw/2026-08-12/0120001--unknown.png"]})
            urllib.request.urlopen = lambda url, timeout=None: _Blob(b"PNGDATA")
            remote_got = _submit_and_collect(d, "anchor_v2", "*.png", lambda m: None)
            assert [os.path.basename(p) for p in remote_got] == ["front_s42_00001_.png"], remote_got
            assert open(remote_got[0], "rb").read() == b"PNGDATA"

            # 4. a box that does not hold the model refuses in about a second,
            # and the job moves to the NEXT box rather than re-rolling the same
            # dice. Measured on the real fleet: unpinned twice in a row landed
            # on backends without Qwen-Image-Edit and the whole render was lost.
            os.remove(remote_got[0])
            tries, payloads = [], []

            def flaky(path, payload, timeout=30):
                tries.append(path)
                payloads.append(payload)
                if len(tries) == 1:
                    return {"error": "Model in folder 'vae' with filename 'x' not found."}
                return {"images": ["View/local/raw/2026-08-12/0120001--unknown.png"]}

            globals()["_swarm_call"] = _swarm(flaky)
            said = []
            got = _submit_and_collect(d, "anchor_v2", "*.png", said.append)
            assert len(tries) == 2, tries
            assert payloads[0].get("exactbackendid") is None, \
                "the first draw must be SwarmUI's own, or two 5090s never load-balance"
            assert payloads[1]["exactbackendid"] == "0", payloads
            assert [os.path.basename(p) for p in got] == ["front_s42_00001_.png"], got
            assert any("refused by SwarmUI" in m for m in said), said

            # 5. and when NO box can run it, the walk covers every one of them
            # and then stops, rather than either giving up early or looping.
            os.remove(got[0])
            tries.clear()
            payloads.clear()

            def dead_model(path, payload, timeout=30):
                tries.append(path)
                payloads.append(payload)
                return {"error": "no model"}

            globals()["_swarm_call"] = _swarm(dead_model)
            try:
                _submit_and_collect(d, "anchor_v2", "*.png", said.append)
                raise AssertionError("a workflow no backend can run returned a result")
            except RuntimeError as e:
                assert "no model" in str(e), e
            # one free draw, then EVERY running backend in turn -- a policy that
            # stops before reaching the box holding the model is not a policy
            assert len(tries) == 4, tries
            assert [q.get("exactbackendid") for q in payloads] == [None, "0", "1", "2"], payloads
            assert os.listdir(sheets) == [], os.listdir(sheets)

            # 6. a cancel MID-GENERATION reaches the render, and is the one
            # failure never retried -- a second attempt hands the GPU straight
            # back to work the user stopped. Cancelled only from the second
            # check on, so this goes through the retry loop rather than
            # stopping at the top of it, which is where a cancel that IS
            # retried would otherwise hide.
            POLL_SECS = 0.05
            gens, asked, polls = [], [], []

            def cancel_mid(path, payload, timeout=30):
                if path.endswith("GenerateText2Image"):
                    gens.append(path)
                    time.sleep(3)
                    return {"images": []}
                asked.append(path)
                return {}

            def prog(msg):
                pass

            prog.cancelled = lambda: bool(polls.append(None)) or len(polls) > 1

            globals()["_swarm_call"] = _swarm(cancel_mid)
            t0 = time.time()
            try:
                _submit_and_collect(d, "anchor_v2", "*.png", prog)
                raise AssertionError("a cancelled submit returned as though it had rendered")
            except RuntimeError as e:
                assert "cancelled" in str(e).lower(), e
            assert time.time() - t0 < 1.5, \
                "the cancel waited for the render instead of stopping it"
            assert len(gens) == 1, f"the cancel was retried: {len(gens)} generations"
            assert any("InterruptAll" in a for a in asked), asked
    finally:
        RENDER_BACKEND, POLL_SECS = real_backend, real_poll
        globals()["submit_swarm"], globals()["submit_dir"] = real_submit_swarm, real_submit
        globals()["_swarm_call"] = real_swarm_call
        COMFY_OUTPUT = real_out
        gpu.preflight, gpu.ollama_holding = real_preflight, real_holding
        urllib.request.urlopen = real_urlopen

    # --- both documented forms of images[] (T2IAPI.cs:72) --------------------
    with tempfile.TemporaryDirectory() as out:
        import base64
        got = _swarm_fetch("data:image/png;base64," + base64.b64encode(b"INLINE").decode(),
                           out, "clip_007")
        assert os.path.basename(got) == "clip_007_00001_.png", got
        assert open(got, "rb").read() == b"INLINE"
        # and a second output of the same workflow does not overwrite the first
        urllib.request.urlopen = lambda url, timeout=None: _Blob(b"MP4")
        try:
            two = _swarm_fetch("View/local/raw/2026-08-12/0120002--unknown.mp4", out, "clip_007")
        finally:
            urllib.request.urlopen = real_urlopen
        assert os.path.basename(two) == "clip_007_00001_.mp4", two

    # --- inputs reach every box that could be handed the job -----------------
    real_dirs = SWARM_INPUT_DIRS
    real_run = subprocess.run
    real_in2 = COMFY_INPUT
    pushed = []
    globals()["SWARM_INPUT_DIRS"] = ["box:/comfy/input"]
    try:
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as inp:
            COMFY_INPUT = inp
            p = os.path.join(src, "ref.png")
            open(p, "w").write("x")
            subprocess.run = lambda cmd, **kw: pushed.append(cmd)
            assert install_input(p, "clip_003.png") == "clip_003.png"
            assert os.path.exists(os.path.join(inp, "clip_003.png"))
            assert pushed and pushed[0][:2] == ["rsync", "-a"], pushed
            assert pushed[0][-1] == "box:/comfy/input/clip_003.png", pushed
            # the mode is load-bearing: peaches' container is uid 1025 and a
            # file arriving 0600 fails there as "ModelMMAP allocation failed",
            # which looks like an OOM and is not one
            assert "--chmod=F664" in pushed[0], pushed

            # a box that is off must not fail a render the other boxes can do
            def dead(cmd, **kw):
                raise subprocess.CalledProcessError(255, cmd, stderr="ssh: connect refused")

            subprocess.run = dead
            assert install_input(p) == "ref.png"
    finally:
        subprocess.run = real_run
        globals()["SWARM_INPUT_DIRS"] = real_dirs
        COMFY_INPUT = real_in2

    print("pipeline.py OK")


if __name__ == "__main__":
    demo()
