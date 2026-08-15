"""T3-4.2-fps: clip fps vs the workflow's request.

docs/TRD-3 §4.2 table: fps is the workflow's request; a box that
quietly re-timed is the failure mode. When expect names fps,
check_video measures the file via mixer.probe and compares within
FPS_TOL.

Matching rate PASSes. Mismatch FLAGs (not REJECT — retime is not a
hard reject). measured is the file's fps, expected is the request,
unit fps. Without expect.fps, check_video emits no fps finding.

T3-8 owns interpolated RIFE out_fps only; this criterion is the
plain request match on a normal clip.

Mutation: delete the check from check_video → no fps finding.
Mutation: always PASS → retimed arm red.
Mutation: measured not equal to mixer.probe fps → T3-4 red.
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


def _mp4(path, fps, frames=30, size="320x240"):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}",
         "-frames:v", str(frames), "-c:v", "mpeg4", "-q:v", "5",
         "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, (
        f"fixture {path} is {os.path.getsize(path)} bytes — under "
        f"MIN_VIDEO_BYTES; size_floor would hide fps")
    return path


def _fps(findings):
    rows = [f for f in findings if f["check"] == "fps"]
    assert rows, f"no fps finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_2_fps_probe_reports_rate(tmp_path, monkeypatch):
    """mixer.probe is the reading. A rate that never surfaces cannot be checked."""
    mixer = _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "16fps.mp4"), 16)
    info = mixer.probe(path)
    assert abs(float(info["fps"]) - 16.0) <= qc.FPS_TOL, info


def test_t3_4_2_fps_match_passes_mismatch_flags(tmp_path, monkeypatch):
    """One variable: the file rate against expect.fps."""
    _use_real_mixer(monkeypatch)
    good = _mp4(str(tmp_path / "ok.mp4"), 16)
    bad = _mp4(str(tmp_path / "retimed.mp4"), 24)
    expect = {"fps": 16.0, "latent_rule": False}

    row = _fps(qc.run(good, "clip", expect))
    assert row["verdict"] == qc.PASS, row
    assert abs(float(row["measured"]) - 16.0) <= qc.FPS_TOL, row
    assert abs(float(row["expected"]) - 16.0) <= qc.FPS_TOL, row
    assert row["unit"] == "fps"
    assert row["remedy_class"] == qc.REMEDY_RERENDER_PINNED
    detail = (row["detail"] or "").lower()
    assert "16" in detail and "fps" in detail, row

    row = _fps(qc.run(bad, "clip", expect))
    assert row["verdict"] == qc.FLAG, row
    assert abs(float(row["measured"]) - 24.0) <= qc.FPS_TOL, row
    assert abs(float(row["expected"]) - 16.0) <= qc.FPS_TOL, row
    assert row["unit"] == "fps"
    assert row["remedy_class"] == qc.REMEDY_RERENDER_PINNED
    detail = (row["detail"] or "").lower()
    assert "24" in detail and "16" in detail, row


def test_t3_4_2_fps_measured_matches_probe(tmp_path, monkeypatch):
    """T3-4: measured equals mixer.probe fps, not a free-form number."""
    mixer = _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "retimed.mp4"), 24)
    independent = float(mixer.probe(path)["fps"])
    assert abs(independent - 24.0) <= qc.FPS_TOL, independent
    row = _fps(qc.run(path, "clip", {"fps": 16.0, "latent_rule": False}))
    assert abs(float(row["measured"]) - independent) <= qc.FPS_TOL, (
        row, independent)
    assert abs(float(row["measured"]) - float(row["expected"])) > qc.FPS_TOL, row


def test_t3_4_2_fps_without_expect_emits_nothing(tmp_path, monkeypatch):
    """As requested: no fps request means no fps finding."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "any.mp4"), 16)
    findings = qc.run(path, "clip", {"latent_rule": False})
    assert not any(f["check"] == "fps" for f in findings), [
        f["check"] for f in findings]
