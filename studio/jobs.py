"""Serialized job queue. One worker thread, so two GPU jobs never overlap.

There is exactly one RTX 5090 behind this, and ComfyUI itself queues internally,
but reference renders, clip renders and ffmpeg passes all contend for it. A
single worker is the whole concurrency policy -- do not add a second.

Handlers register with @handler("kind") and receive (args: dict, progress: callable).
Anything they print via progress() is visible in the UI and appended to the log.
"""
import json, os, threading, time, traceback

import db

LOGS = os.path.join(db.DATA, "logs")
_handlers = {}
_wake = threading.Event()

# A ComfyUI restart takes a few seconds; a batch should survive one.
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECS = 5.0
# Matched on the message pipeline._get/_post raise, not on the exception type:
# both come back as RuntimeError, and only the unreachable one is worth retrying.
_TRANSIENT = ("cannot reach comfyui", "connection refused", "connection reset",
              "temporarily unavailable", "timed out")


def _is_transient(exc):
    """Whether a failure is worth retrying. Deliberately narrow: a workflow
    ComfyUI REFUSED is a real error, and retrying it just fails more slowly."""
    return any(t in str(exc).lower() for t in _TRANSIENT)
_worker = None


def handler(kind):
    def deco(fn):
        _handlers[kind] = fn
        return fn
    return deco


def enqueue(kind, args=None, song_id=None):
    if kind not in _handlers:
        raise ValueError(f"no handler registered for job kind {kind!r}")
    jid = db.run(
        "INSERT INTO jobs (kind, args_json, song_id, status, created) VALUES (?,?,?, 'queued', ?)",
        kind, json.dumps(args or {}), song_id, time.time())
    _wake.set()
    return jid


def get(jid):
    return db.one("SELECT * FROM jobs WHERE id=?", jid)


def recent(limit=50):
    return db.q("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", limit)


def active():
    return db.one("SELECT * FROM jobs WHERE status='running' ORDER BY id LIMIT 1")


class Cancelled(Exception):
    """Raised inside a handler when the user asked for the job to stop."""


# Human labels for the job list. "refs" told the user nothing about which song
# or how far along it was.
LABELS = {
    "transcribe": "Transcribe lyrics",
    "analyse": "Analyse audio (bpm/key/energy)",
    "anchor": "Generate anchor candidates",
    "storyboard": "Write storyboard (Grok)",
    "refs": "Render reference images",
    "reroll": "Re-roll reference images",
    "clips": "Render video clips",
    "render_song": "Assemble song video",
    "render_set": "Render playlist set",
    "edit_audio": "Edit audio",
}


def describe(row):
    """One human-readable line for a job: what it is, for which song and tier."""
    import json as _json
    label = LABELS.get(row["kind"], row["kind"])
    try:
        args = _json.loads(row["args_json"] or "{}")
    except ValueError:
        args = {}
    bits = []
    if row["song_id"]:
        song = db.one("SELECT title FROM songs WHERE id=?", row["song_id"])
        if song:
            bits.append(song["title"])
    if args.get("tier"):
        bits.append(f"[{args['tier']}]")
    if args.get("view"):
        bits.append(args["view"])
    if args.get("limit"):
        bits.append(f"first {args['limit']}")
    return f"{label} — {' '.join(bits)}" if bits else label


def cancel(jid):
    """Stop a job. Queued ones die immediately; running ones stop cooperatively.

    A running job cannot be killed outright -- it may be mid-ComfyUI-submit or
    mid-ffmpeg -- so it is marked 'cancelling' and the next progress() call
    inside the handler raises Cancelled. Every long loop here already reports
    per item (submit_dir per workflow, ffmpeg per stage), so this stops a
    41-image render within one image instead of ten minutes, with no changes
    needed in pipeline.py or mixer.py.
    """
    row = get(jid)
    if row is None:
        raise ValueError(f"no such job: {jid}")
    if row["status"] == "queued":
        db.run("UPDATE jobs SET status='cancelled', finished=? WHERE id=? AND status='queued'",
               time.time(), jid)
    elif row["status"] == "running":
        db.run("UPDATE jobs SET status='cancelling' WHERE id=? AND status='running'", jid)
    else:
        raise ValueError(f"job {jid} is already {row['status']}")
    return get(jid)["status"]


def cancel_requested(jid):
    row = db.one("SELECT status FROM jobs WHERE id=?", jid)
    return bool(row) and row["status"] == "cancelling"


def _claim():
    """Take the oldest queued job, atomically.

    SELECT-then-UPDATE lost a concurrent cancel: click Cancel in the gap between
    the two statements and cancel() matched (status was still 'queued'), wrote
    'cancelled', and the worker then overwrote it with 'running' and ran the job
    anyway -- the UI said cancelled while the GPU worked. BEGIN IMMEDIATE takes
    the write lock up front so a cancel on another connection waits, and the
    guard on status makes the update a no-op if it already landed.
    """
    c = db.conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            c.execute("COMMIT")
            return None
        cur = c.execute(
            "UPDATE jobs SET status='running', started=? WHERE id=? AND status='queued'",
            (time.time(), row["id"]))
        c.execute("COMMIT")
        return row if cur.rowcount == 1 else None
    except Exception:
        c.execute("ROLLBACK")
        raise


def _run_one(row, attempt=1):
    jid = row["id"]
    os.makedirs(LOGS, exist_ok=True)
    log_path = os.path.join(LOGS, f"job_{jid}.log")
    db.run("UPDATE jobs SET log_path=? WHERE id=?", log_path, jid)
    log = open(log_path, "a", buffering=1)

    def progress(msg):
        # also the cancellation checkpoint: handlers already call this between
        # items, so cooperative cancel costs them nothing
        if cancel_requested(jid):
            raise Cancelled()
        msg = str(msg).rstrip()
        log.write(msg + "\n")
        db.run("UPDATE jobs SET progress=? WHERE id=?", msg[:500], jid)

    try:
        args = json.loads(row["args_json"] or "{}")
        progress(f"start {row['kind']}")
        result = _handlers[row["kind"]](args, progress)
        db.run("UPDATE jobs SET status='done', finished=?, progress=? WHERE id=?",
               time.time(), json.dumps(result)[:500] if result else "done", jid)
        progress("done")
    except Cancelled:
        db.run("UPDATE jobs SET status='cancelled', finished=?, progress=? WHERE id=?",
               time.time(), "cancelled by user", jid)
        log.write("cancelled by user\n")
    except Exception as e:
        # A TRANSIENT failure is retried in place. ComfyUI is restarted often
        # (a deploy, a model change, a crash) and a restart takes seconds -- but
        # the worker takes the next job immediately, fails to reach it, and
        # moves on, so ONE restart window destroys a whole batch in about a
        # second. Nine anchor sheets were lost to a five-second gap this way:
        # every job failed at 19:01:58, ComfyUI answered again at 19:02:03.
        #
        # Only "cannot reach" is retried. A workflow ComfyUI actively REFUSED is
        # a real error and retrying it just fails three times more slowly.
        msg = f"{type(e).__name__}: {e}"
        if attempt < MAX_ATTEMPTS and _is_transient(e):
            wait = RETRY_BACKOFF_SECS * attempt
            log.write(f"{msg}\n-- transient, retrying in {wait:.0f}s "
                      f"(attempt {attempt + 1} of {MAX_ATTEMPTS})\n")
            db.run("UPDATE jobs SET progress=? WHERE id=?",
                   f"unreachable, retrying in {wait:.0f}s "
                   f"({attempt + 1}/{MAX_ATTEMPTS})", jid)
            log.close()
            time.sleep(wait)
            return _run_one(row, attempt=attempt + 1)
        db.run("UPDATE jobs SET status='failed', finished=?, error=? WHERE id=?",
               time.time(), msg[:2000], jid)
        log.write(traceback.format_exc())
    finally:
        log.close()


def _loop():
    """Must never exit. start() runs once from the FastAPI lifespan hook, so if
    this thread dies nothing restarts it: every later job sits 'queued' forever,
    the UI shows no error, and the app looks merely slow. _run_one catches
    Exception, but the log-file open sits outside its try and a BaseException
    (SystemExit, KeyboardInterrupt) passes straight through -- hence the belt
    here as well as the braces there."""
    row = None
    while True:
        try:
            row = _claim()
            if row is None:
                _wake.wait(2.0)
                _wake.clear()
                continue
            _run_one(row)
        except BaseException as e:  # noqa: BLE001 -- deliberate, see docstring
            try:
                if row is not None:
                    db.run("UPDATE jobs SET status='failed', finished=?, error=? WHERE id=?",
                           time.time(), f"worker error: {type(e).__name__}: {e}"[:2000],
                           row["id"])
            except Exception:
                pass
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            time.sleep(1.0)  # don't spin if the failure is immediate and repeating


def start():
    """Idempotent. Requeues anything left 'running' by a crash."""
    global _worker
    if _worker and _worker.is_alive():
        return _worker
    db.run("UPDATE jobs SET status='queued', started=NULL WHERE status='running'")
    db.run("UPDATE jobs SET status='cancelled', finished=? WHERE status='cancelling'", time.time())
    _worker = threading.Thread(target=_loop, daemon=True, name="studio-worker")
    _worker.start()
    return _worker


async def stream(jid):
    """SSE body for one job. Polls sqlite -- fine at this scale.

    MUST stay an async generator with an awaited sleep. As a sync generator
    Starlette drives it through iterate_in_threadpool, where each open stream
    holds one of the 40 anyio worker tokens ~100% of the time; every sync route
    shares that pool, so 41 concurrent viewers wedged the whole app and did not
    recover when the clients disconnected. Awaiting yields the thread.

    ponytail: 0.5s poll, swap for a condition variable if the job list gets long.
    """
    import asyncio
    last = None
    while True:
        row = get(jid)
        if row is None:
            yield "event: gone\ndata: {}\n\n"
            return
        payload = {"id": row["id"], "status": row["status"], "progress": row["progress"],
                   "error": row["error"]}
        blob = json.dumps(payload)
        if blob != last:
            yield f"data: {blob}\n\n"
            last = blob
        if row["status"] in ("done", "failed", "cancelled"):
            return
        await asyncio.sleep(0.5)


def demo():
    import tempfile
    db.DATA = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(db.DATA, "t.db")
    db._local.__dict__.clear()
    globals()["LOGS"] = os.path.join(db.DATA, "logs")

    order = []

    @handler("slow")
    def _slow(args, progress):
        order.append(("start", args["n"]))
        time.sleep(0.15)
        progress(f"working {args['n']}")
        order.append(("end", args["n"]))
        return {"n": args["n"]}

    @handler("boom")
    def _boom(args, progress):
        raise RuntimeError("expected failure")

    start()
    a, b = enqueue("slow", {"n": 1}), enqueue("slow", {"n": 2})
    c = enqueue("boom", {})
    deadline = time.time() + 15
    while time.time() < deadline:
        if all(get(j)["status"] in ("done", "failed") for j in (a, b, c)):
            break
        time.sleep(0.05)

    assert get(a)["status"] == "done", get(a)["status"]
    assert get(b)["status"] == "done"
    assert get(c)["status"] == "failed"
    assert "expected failure" in get(c)["error"]
    # serialization: job 1 must fully finish before job 2 starts
    assert order == [("start", 1), ("end", 1), ("start", 2), ("end", 2)], order
    assert os.path.exists(get(a)["log_path"])
    try:
        enqueue("nope", {})
        raise AssertionError("unregistered kind was accepted")
    except ValueError:
        pass

    # --- cancellation ---
    # a queued job dies immediately
    slow_started = threading.Event()
    release = threading.Event()

    @handler("blocker")
    def _blocker(args, progress):
        slow_started.set()
        release.wait(10)
        for i in range(50):          # long loop, reports per item like the real ones
            progress(f"step {i}")
            time.sleep(0.02)
        return {"finished": True}

    q1 = enqueue("blocker", {})
    q2 = enqueue("slow", {"n": 3})
    assert slow_started.wait(5), "worker never picked up the blocker"
    assert cancel(q2) == "cancelled", "queued job was not cancelled outright"
    release.set()

    # a RUNNING job stops cooperatively at its next progress() call
    b = enqueue("blocker", {})
    slow_started.clear()
    assert slow_started.wait(10), "second blocker never started"
    release.clear()
    time.sleep(0.05)
    assert cancel(b) == "cancelling", "running job should go to 'cancelling'"
    release.set()
    deadline = time.time() + 10
    while time.time() < deadline and get(b)["status"] not in ("cancelled", "done", "failed"):
        time.sleep(0.05)
    assert get(b)["status"] == "cancelled", f"running job did not stop: {get(b)['status']}"
    assert get(q1)["status"] == "done", "the first blocker should have completed normally"

    for bad in (999999,):
        try:
            cancel(bad)
            raise AssertionError("cancelling an unknown job was accepted")
        except ValueError:
            pass
    try:
        cancel(q2)               # already cancelled
        raise AssertionError("cancelling a finished job was accepted")
    except ValueError:
        pass

    # --- a cancel must never be overwritten by the claim (lost-cancel race) ---
    # Hold the worker so the victim genuinely sits queued; cancelling a job that
    # the worker has already picked up tests nothing about _claim().
    gate_started, gate_open = threading.Event(), threading.Event()

    @handler("gate")
    def _gate(args, progress):
        gate_started.set()
        gate_open.wait(15)
        return {}

    enqueue("gate", {})
    assert gate_started.wait(10), "gate job never started"
    victim = enqueue("slow", {"n": 99})
    assert get(victim)["status"] == "queued", get(victim)["status"]
    assert cancel(victim) == "cancelled"
    gate_open.set()
    deadline = time.time() + 10
    while time.time() < deadline and get(victim)["status"] == "cancelled":
        time.sleep(0.1)          # give the worker every chance to wrongly claim it
    assert get(victim)["status"] == "cancelled", \
        f"claim resurrected a cancelled job: {get(victim)['status']}"

    # --- describe ---
    db.run("INSERT INTO songs (title, slug, created) VALUES (?,?,?)", "Rear Entrance", "re", 0)
    sid = db.one("SELECT id FROM songs WHERE slug='re'")["id"]
    # insert directly: "refs" is registered by app.py, not here, and describe()
    # only reads the row
    dj = db.run("INSERT INTO jobs (kind, args_json, song_id, status, created) "
                "VALUES (?,?,?, 'queued', ?)",
                "refs", json.dumps({"tier": "r", "limit": 5}), sid, time.time())
    text = describe(get(dj))
    assert "Render reference images" in text, text
    assert "Rear Entrance" in text and "[r]" in text and "first 5" in text, text
    # an unknown kind falls back to the raw kind rather than blowing up
    dk = db.run("INSERT INTO jobs (kind, status, created) VALUES ('mystery','queued',?)", time.time())
    assert describe(get(dk)) == "mystery"

    # stream() must be an ASYNC generator. As a sync one it burns an anyio
    # threadpool worker per open viewer and 41 of them deadlock every route.
    import asyncio, inspect
    assert inspect.isasyncgenfunction(stream), \
        "jobs.stream must be an async generator or SSE viewers exhaust the threadpool"

    async def _drain():
        out = []
        async for chunk in stream(a):      # job a is already 'done'
            out.append(chunk)
        return out

    frames = asyncio.run(_drain())
    assert frames and any('"status": "done"' in f for f in frames), frames

    async def _gone():
        return [c async for c in stream(999999)]
    assert asyncio.run(_gone()) == ["event: gone\ndata: {}\n\n"], "unknown id must terminate"

    print("jobs.py OK")


if __name__ == "__main__":
    demo()
