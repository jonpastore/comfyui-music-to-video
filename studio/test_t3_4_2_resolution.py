"""T3-4.2-resolution: clip resolution vs the workflow's request.

docs/TRD-3 §4.2 table: resolution is the workflow's request; a box that
quietly downscaled is the failure mode. When expect names width and
height, check_video measures the file and compares exactly (no soft
tolerance).

Matching size PASSes. 160x120 against 320x240 requested REJECTs.
measured is the file's WxH, expected is the request, unit px.
Without expect width+height, check_video emits no resolution finding.

Mutation: delete the check from check_video → no resolution finding.
Mutation: always PASS → downscaled arm red.
Mutation: measured not equal to mixer.probe width/height → T3-4 red.
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


def _mp4(path, size, frames=30, fps=10):
    # Solid-ish fixtures compress under MIN_VIDEO_BYTES with some
    # encoders; mpeg4 + enough frames keeps them above the floor.
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}",
         "-frames:v", str(frames), "-c:v", "mpeg4", "-q:v", "5",
         "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, (
        f"fixture {path} is {os.path.getsize(path)} bytes — under "
        f"MIN_VIDEO_BYTES; size_floor would hide resolution")
    return path


def _res(findings):
    rows = [f for f in findings if f["check"] == "resolution"]
    assert rows, f"no resolution finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_2_resolution_probe_reports_size(tmp_path, monkeypatch):
    """mixer.probe is the reading. A size that never surfaces cannot be checked."""
    mixer = _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "320x240.mp4"), "320x240")
    info = mixer.probe(path)
    assert int(info["width"]) == 320, info
    assert int(info["height"]) == 240, info


def test_t3_4_2_resolution_match_passes_mismatch_rejects(tmp_path, monkeypatch):
    """One variable: the file size against expect width/height."""
    _use_real_mixer(monkeypatch)
    good = _mp4(str(tmp_path / "ok.mp4"), "320x240")
    bad = _mp4(str(tmp_path / "down.mp4"), "160x120")
    expect = {"width": 320, "height": 240}

    row = _res(qc.run(good, "clip", expect))
    assert row["verdict"] == qc.PASS, row
    assert row["measured"] == "320x240", row
    assert row["expected"] == "320x240", row
    assert row["unit"] == "px"
    assert row["remedy_class"] == qc.REMEDY_RERENDER_PINNED
    detail = (row["detail"] or "").lower()
    assert "320" in detail and "240" in detail, row

    row = _res(qc.run(bad, "clip", expect))
    assert row["verdict"] == qc.REJECT, row
    assert row["measured"] == "160x120", row
    assert row["expected"] == "320x240", row
    assert row["unit"] == "px"
    assert row["remedy_class"] == qc.REMEDY_RERENDER_PINNED
    detail = (row["detail"] or "").lower()
    assert "160" in detail and "320" in detail, row


def test_t3_4_2_resolution_measured_matches_probe(tmp_path, monkeypatch):
    """T3-4: measured equals mixer.probe width×height, not a free-form string."""
    mixer = _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "down.mp4"), "160x120")
    info = mixer.probe(path)
    independent = f"{int(info['width'])}x{int(info['height'])}"
    assert independent == "160x120", independent
    row = _res(qc.run(path, "clip", {"width": 320, "height": 240}))
    assert row["measured"] == independent, (row, independent)


def test_t3_4_2_resolution_without_expect_emits_nothing(tmp_path, monkeypatch):
    """As requested: no width+height request means no resolution finding."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "any.mp4"), "320x240")
    findings = qc.run(path, "clip", {})
    assert not any(f["check"] == "resolution" for f in findings), [
        f["check"] for f in findings]
