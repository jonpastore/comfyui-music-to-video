"""T3-32: tier 1 over a song's artefacts needs no GPU and no backend.

docs/TRD-3 §8: measurement completes without contacting a box, and it
must not sit behind renders on the one worker thread. A helper that
never runs, or a jobs.enqueue that returns before the worker starts,
stays green without measuring anything.
"""
import inspect
import os
import tempfile
import threading
import time

from PIL import Image

import db
import jobs
import models
import pipeline
import qc
import qc_service


def _isolate():
    data = tempfile.mkdtemp(prefix="t332_")
    was = (db.DATA, db.DB_PATH, jobs.LOGS)
    db.DATA = data
    db.DB_PATH = os.path.join(data, "t.db")
    db._local.__dict__.clear()
    jobs.LOGS = os.path.join(data, "logs")
    return data, was


def _restore(was):
    db.DATA, db.DB_PATH, jobs.LOGS = was
    db._local.__dict__.clear()


def _tiny_png(path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    Image.new("RGB", (8, 8), (40, 40, 40)).save(path)
    return path


def _small_video(path):
    """Under qc.MIN_VIDEO_BYTES so check_video records size_floor without
    probing. The measurement still ran; a skip would write nothing."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x00" * 1500)
    return path


def _song_with_artefacts(data, slug="t332"):
    render = _small_video(os.path.join(data, "assembled.mp4"))
    clip = _small_video(os.path.join(data, "clip_000.mp4"))
    ref = _tiny_png(os.path.join(data, "ref_000.png"))
    sid = db.upsert_song(slug, title="T3-32 Song", duration=12.3)
    now = time.time()
    db.run("INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
           sid, "r", render, now)
    db.run("""INSERT INTO clips (song_id, tier, clip_idx, path, status)
              VALUES (?,?,?,?,?)""", sid, "r", 0, clip, "done")
    db.run("""INSERT INTO refs (song_id, tier, clip_idx, path, seed, created)
              VALUES (?,?,?,?,?,?)""", sid, "r", 0, ref, 1, now)
    return sid, {"song": render, "clip": clip, "image": ref}


def _boom(*_a, **_k):
    raise AssertionError("T3-32 contacted a GPU or a backend")


def _ban_gpu_and_backend(monkeypatch):
    monkeypatch.setattr(pipeline, "submit_dir", _boom)
    monkeypatch.setattr(pipeline, "gen_clips", _boom)
    monkeypatch.setattr(pipeline, "gen_refs", _boom)
    monkeypatch.setattr(pipeline, "fix_ref", _boom)
    monkeypatch.setattr(pipeline, "gen_postproc", _boom)
    monkeypatch.setattr(pipeline, "free_vram", _boom)
    monkeypatch.setattr(pipeline, "swarm_backends", _boom)
    monkeypatch.setattr(models, "where", _boom)
    import gpu
    monkeypatch.setattr(gpu, "preflight", _boom)
    monkeypatch.setattr(gpu, "vram", _boom)


def test_t3_32_run_song_measures_every_artefact_without_gpu_or_backend(
        monkeypatch):
    """Positive half: assembled + clip + ref are checked, findings land,
    and no GPU/backend seam is touched. A no-op that returns zeros
    without walking the song stays green otherwise."""
    data, was = _isolate()
    try:
        _ban_gpu_and_backend(monkeypatch)
        sid, paths = _song_with_artefacts(data)
        assert hasattr(qc_service, "run_song"), (
            "T3-32 measurement lives on qc_service.run_song, the function "
            "the route forwards to")
        out = qc_service.run_song(sid, "r")
        assert out["artefacts"] == 3, out
        assert out["checks"] >= 3, out
        assert out[qc.REJECT] >= 2, out
        kinds = {r["kind"] for r in db.q("SELECT DISTINCT kind FROM findings")}
        assert kinds == {"song", "clip", "image"}, kinds
        for kind, path in paths.items():
            row = db.one("SELECT * FROM findings WHERE path=?",
                         jobs.canonical_path(path))
            assert row is not None, f"no finding for {kind} {path}"
        assert db.one("SELECT id FROM jobs WHERE kind='qc'") is None
    finally:
        _restore(was)


def test_t3_32_measurement_completes_while_the_worker_is_blocked(monkeypatch):
    """The measurement stage must not queue behind renders. Enqueueing a
    qc job and returning stays green until someone waits for it."""
    data, was = _isolate()
    started = threading.Event()
    release = threading.Event()
    try:
        _ban_gpu_and_backend(monkeypatch)
        sid, _paths = _song_with_artefacts(data, slug="t332-blocked")

        @jobs.handler("t332_block")
        def _block(args, progress):
            started.set()
            if not release.wait(15):
                raise AssertionError("blocker was never released")

        jobs.start()
        jobs.enqueue("t332_block", {"who": "render"})
        assert started.wait(5), "blocker never took the worker"
        assert jobs.active() is not None

        t0 = time.time()
        out = qc_service.run_song(sid, "r")
        elapsed = time.time() - t0
        assert out["artefacts"] == 3, out
        assert elapsed < 5.0, (
            f"tier-1 sat behind the worker for {elapsed:.2f}s")
        assert jobs.active() is not None, "measurement consumed the worker"
        assert db.one("SELECT id FROM jobs WHERE kind='qc'") is None
        assert db.one("SELECT COUNT(*) AS n FROM findings")["n"] >= 3
    finally:
        release.set()
        jobs.stop()
        _restore(was)


def test_t3_32_start_qc_forwards_to_run_song_and_does_not_enqueue():
    """The operator path is the measurement stage. A route that still
    jobs.enqueue('qc') puts QC behind the one worker thread."""
    import app as appmod
    src = inspect.getsource(appmod.start_qc)
    assert "run_song" in src, src
    assert "enqueue" not in src, src
    assert "run_song" in inspect.getsource(appmod.h_qc)
