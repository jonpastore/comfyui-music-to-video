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


def cancel(jid):
    """Only queued jobs can be cancelled; a running subprocess is left alone."""
    db.run("UPDATE jobs SET status='cancelled', finished=? WHERE id=? AND status='queued'",
           time.time(), jid)


def _claim():
    """Take the oldest queued job. Single worker, so no locking contest."""
    row = db.one("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1")
    if not row:
        return None
    db.run("UPDATE jobs SET status='running', started=? WHERE id=?", time.time(), row["id"])
    return row


def _run_one(row):
    jid = row["id"]
    os.makedirs(LOGS, exist_ok=True)
    log_path = os.path.join(LOGS, f"job_{jid}.log")
    db.run("UPDATE jobs SET log_path=? WHERE id=?", log_path, jid)
    log = open(log_path, "a", buffering=1)

    def progress(msg):
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
    except Exception as e:
        db.run("UPDATE jobs SET status='failed', finished=?, error=? WHERE id=?",
               time.time(), f"{type(e).__name__}: {e}"[:2000], jid)
        log.write(traceback.format_exc())
    finally:
        log.close()


def _loop():
    while True:
        row = _claim()
        if row is None:
            _wake.wait(2.0)
            _wake.clear()
            continue
        _run_one(row)


def start():
    """Idempotent. Requeues anything left 'running' by a crash."""
    global _worker
    if _worker and _worker.is_alive():
        return _worker
    db.run("UPDATE jobs SET status='queued', started=NULL WHERE status='running'")
    _worker = threading.Thread(target=_loop, daemon=True, name="studio-worker")
    _worker.start()
    return _worker


def stream(jid):
    """SSE body for one job. Polls sqlite -- fine at this scale.
    ponytail: 0.5s poll, swap for a condition variable if the job list gets long."""
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
        time.sleep(0.5)


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
    print("jobs.py OK")


if __name__ == "__main__":
    demo()
