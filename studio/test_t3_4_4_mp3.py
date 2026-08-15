"""T3-4.4-mp3: assembled song duration vs source mp3 / songs.duration.

docs/TRD-3 §4.4: the assembled duration matches the source mp3 within
tolerance. Authority is songs.duration (T6-13a) — that criterion only
asserts the expect dict. This file asserts REJECT on the media when the
render misses the track, and PASS when it matches.

Tolerance is qc.DURATION_TOL_S (imported, not restated). Both directions
on real files, or the check is untested in the direction that matters.

Mutation: drop expect duration from run_song → mismatch arm never fires.
Mutation: always PASS duration → mismatch arm red.
Mutation: compare against a restated 0.5s → just-outside stays green.
"""
import os
import subprocess
import tempfile
import time

from conftest import _real_module

import db
import jobs
import qc
import qc_service


mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"


def _use_real_mixer(monkeypatch):
    monkeypatch.setattr(qc, "mixer", mixer)


def _mp4(path, seconds, fps=10):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i",
         f"testsrc2=size=320x240:rate={fps}:duration={seconds}",
         "-f", "lavfi", "-i",
         f"sine=frequency=440:sample_rate=48000:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "48000", "-shortest", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, path
    return path


def _duration_row(findings):
    rows = [f for f in findings if f["check"] == "duration"]
    assert rows, f"no duration finding: {[f['check'] for f in findings]}"
    return rows[0]


def _isolate():
    data = tempfile.mkdtemp(prefix="t344_")
    was = (db.DATA, db.DB_PATH, jobs.LOGS)
    db.DATA = data
    db.DB_PATH = os.path.join(data, "t.db")
    db._local.__dict__.clear()
    jobs.LOGS = os.path.join(data, "logs")
    return data, was


def _restore(was):
    db.DATA, db.DB_PATH, jobs.LOGS = was
    db._local.__dict__.clear()


def test_t3_4_4_mp3_tolerance_is_duration_tol_s():
    """Named constant, not a restated 0.10 or a looser 0.5."""
    assert qc.DURATION_TOL_S == 0.10
    src = open(os.path.join(os.path.dirname(__file__), "qc.py"),
               encoding="utf-8").read()
    # song path must use the named constant (check_video duration arm)
    assert "DURATION_TOL_S" in src
    assert "abs(d - want) <= DURATION_TOL_S" in src


def test_t3_4_4_mp3_matching_assembled_passes(tmp_path, monkeypatch):
    """Positive half: file length == songs.duration PASSes duration."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "ok.mp4"), 2.0)
    actual = mixer.probe(path)["duration"]
    row = _duration_row(qc.run(path, "song", {"duration": actual}))
    assert row["verdict"] == qc.PASS, row
    assert row["kind"] == "song"
    assert row["measured"] == round(actual, 3)
    assert row["expected"] == round(actual, 3)
    assert row["unit"] == "s"
    detail = (row["detail"] or "").lower()
    assert "source mp3" in detail or "songs.duration" in detail, row


def test_t3_4_4_mp3_mismatch_beyond_tolerance_rejects(tmp_path, monkeypatch):
    """THE case T6-13a does not cover: media misses the track → REJECT."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "short.mp4"), 2.0)
    actual = mixer.probe(path)["duration"]
    want = actual + qc.DURATION_TOL_S + 0.25
    assert abs(actual - want) > qc.DURATION_TOL_S

    row = _duration_row(qc.run(path, "song", {"duration": want}))
    assert row["verdict"] == qc.REJECT, row
    assert row["kind"] == "song"
    assert row["measured"] == round(actual, 3)
    assert row["expected"] == round(want, 3)
    assert row["unit"] == "s"
    detail = (row["detail"] or "").lower()
    assert "source mp3" in detail or "songs.duration" in detail, row


def test_t3_4_4_mp3_just_inside_passes_just_outside_rejects(
        tmp_path, monkeypatch):
    """DURATION_TOL_S is the one variable. A restated looser bound stays green."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "edge.mp4"), 2.0)
    actual = mixer.probe(path)["duration"]
    tol = qc.DURATION_TOL_S
    inside = actual + tol * 0.6
    outside = actual + tol * 1.4
    assert abs(actual - inside) <= tol
    assert abs(actual - outside) > tol

    in_row = _duration_row(qc.run(path, "song", {"duration": inside}))
    out_row = _duration_row(qc.run(path, "song", {"duration": outside}))
    assert in_row["verdict"] == qc.PASS, in_row
    assert out_row["verdict"] == qc.REJECT, out_row
    assert in_row["expected"] == round(inside, 3)
    assert out_row["expected"] == round(outside, 3)


def test_t3_4_4_mp3_run_song_rejects_when_render_misses_track(monkeypatch):
    """Service path: songs.duration is expected; a short render REJECTs."""
    _use_real_mixer(monkeypatch)
    data, was = _isolate()
    try:
        path = _mp4(os.path.join(data, "assembled.mp4"), 2.0)
        actual = mixer.probe(path)["duration"]
        track = actual + 1.0  # well past DURATION_TOL_S
        assert abs(actual - track) > qc.DURATION_TOL_S

        sid = db.upsert_song("t344-miss", title="Miss", duration=track)
        db.run(
            "INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
            sid, "r", path, time.time())

        out = qc_service.run_song(sid, "r")
        assert out["artefacts"] >= 1, out
        assert out[qc.REJECT] >= 1, out

        row = db.one(
            "SELECT * FROM findings WHERE path=? AND check_name=?",
            jobs.canonical_path(path), "duration")
        assert row is not None, "run_song did not record a duration finding"
        assert row["verdict"] == qc.REJECT, row
        assert row["kind"] == "song"
        assert float(row["measured"]) == round(actual, 3)
        assert float(row["expected"]) == round(track, 3)
        assert row["unit"] == "s"
    finally:
        _restore(was)


def test_t3_4_4_mp3_run_song_passes_when_render_matches_track(monkeypatch):
    """Positive service half: matching assembled length is a duration PASS."""
    _use_real_mixer(monkeypatch)
    data, was = _isolate()
    try:
        path = _mp4(os.path.join(data, "assembled.mp4"), 2.0)
        actual = mixer.probe(path)["duration"]

        sid = db.upsert_song("t344-ok", title="Ok", duration=actual)
        db.run(
            "INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
            sid, "r", path, time.time())

        out = qc_service.run_song(sid, "r")
        assert out["artefacts"] >= 1, out

        row = db.one(
            "SELECT * FROM findings WHERE path=? AND check_name=?",
            jobs.canonical_path(path), "duration")
        assert row is not None, "run_song did not record a duration finding"
        assert row["verdict"] == qc.PASS, row
        assert float(row["measured"]) == round(actual, 3)
        assert float(row["expected"]) == round(actual, 3)
    finally:
        _restore(was)
