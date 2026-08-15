"""T3-4.2-duration: clip duration vs the workflow's request (frames/fps).

docs/TRD-3 §4.2 table: duration is the workflow's own frame count ÷ fps;
truncated render and 2.3-vs-2.5 graph mismatch are the failure modes.
When expect.duration is set, check_video measures the file via
mixer.probe and compares within DURATION_TOL_S.

Matching length PASSes. Wrong length REJECTs.
measured is the file's seconds (probe), expected is the request, unit s.
Without expect.duration, check_video emits no duration finding.

Assembled-song duration vs songs.duration is T3-4.4-mp3.
Audio takes are T3-4.3-duration.

Mutation: delete the check from check_video → no duration finding.
Mutation: always PASS → mismatch arm red.
Mutation: measured not equal to mixer.probe duration (rounded) → T3-4 red.
Mutation: unit is None → T3-4 red (unit must be recorded).
"""
import os
import subprocess

from conftest import _real_module

import qc


def _use_real_mixer(monkeypatch):
    real = _real_module("mixer")
    assert real is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real)
    return real


def _mp4(path, fps, frames, size="320x240"):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}",
         "-frames:v", str(frames), "-c:v", "mpeg4", "-q:v", "5",
         "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, (
        f"fixture {path} is {os.path.getsize(path)} bytes — under "
        f"MIN_VIDEO_BYTES; size_floor would hide duration")
    return path


def _dur(findings):
    rows = [f for f in findings if f["check"] == "duration"]
    assert rows, f"no duration finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_2_duration_probe_reports_seconds(tmp_path, monkeypatch):
    """mixer.probe duration is the reading. frames/fps that never surface cannot be checked."""
    mixer = _use_real_mixer(monkeypatch)
    fps, frames = 16.0, 32
    path = _mp4(str(tmp_path / "two_s.mp4"), fps, frames)
    info = mixer.probe(path)
    assert "duration" in info, info
    assert abs(info["duration"] - (frames / fps)) <= qc.DURATION_TOL_S, info


def test_t3_4_2_duration_match_passes_mismatch_rejects(tmp_path, monkeypatch):
    """One variable: the file length against expect.duration (workflow frames/fps)."""
    _use_real_mixer(monkeypatch)
    fps, frames = 16.0, 32
    path = _mp4(str(tmp_path / "clip.mp4"), fps, frames)
    want = frames / fps  # 2.0 s — what the workflow asked for
    expect_ok = {"duration": want, "latent_rule": False}
    expect_bad = {"duration": 9.0, "latent_rule": False}

    row = _dur(qc.run(path, "clip", expect_ok))
    assert row["verdict"] == qc.PASS, row
    assert abs(float(row["measured"]) - want) <= qc.DURATION_TOL_S, row
    assert abs(float(row["expected"]) - want) <= qc.DURATION_TOL_S, row
    assert row["unit"] == "s"
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert "workflow" in detail or "s" in detail, row

    row = _dur(qc.run(path, "clip", expect_bad))
    assert row["verdict"] == qc.REJECT, row
    assert abs(float(row["measured"]) - want) <= qc.DURATION_TOL_S, row
    assert float(row["expected"]) == 9.0, row
    assert row["unit"] == "s"
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert "9" in detail and ("2" in detail or "workflow" in detail), row


def test_t3_4_2_duration_measured_matches_probe(tmp_path, monkeypatch):
    """T3-4: measured equals mixer.probe duration (rounded like the finding)."""
    mixer = _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "short.mp4"), 16.0, 16)
    independent = round(float(mixer.probe(path)["duration"]), 3)
    row = _dur(qc.run(path, "clip", {"duration": 9.0, "latent_rule": False}))
    assert float(row["measured"]) == independent, (row, independent)
    assert row["unit"] == "s"
    assert abs(float(row["measured"]) - float(row["expected"])) > qc.DURATION_TOL_S, row


def test_t3_4_2_duration_without_expect_emits_nothing(tmp_path, monkeypatch):
    """As requested: no duration request means no duration finding."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "any.mp4"), 16.0, 16)
    findings = qc.run(path, "clip", {"latent_rule": False})
    assert not any(f["check"] == "duration" for f in findings), [
        f["check"] for f in findings]


def test_t3_4_2_duration_tolerance_boundary(tmp_path, monkeypatch):
    """Just-inside DURATION_TOL_S PASSes; just-outside REJECTs. Named constant."""
    mixer = _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "one.mp4"), 16.0, 16)
    actual = float(mixer.probe(path)["duration"])
    tol = qc.DURATION_TOL_S
    inside = actual + tol * 0.5
    outside = actual + tol + 0.01

    row = _dur(qc.run(path, "clip", {"duration": inside, "latent_rule": False}))
    assert row["verdict"] == qc.PASS, row

    row = _dur(qc.run(path, "clip", {"duration": outside, "latent_rule": False}))
    assert row["verdict"] == qc.REJECT, row
    assert float(row["expected"]) == outside, row
