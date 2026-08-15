"""T3-7: frame-count check uses the model's own latent step.

docs/TRD-3 §4.2: not a universal 8n+1. EmptyLTXVLatentVideo step 8
wants 8n+1; WanSoundImageToVideo step 4 makes WAN LEN=77 legal
(4*19+1). Same 77-frame file: frame_step=4 PASSes, frame_step=8
FLAGs naming nearest legal 81.

Mutation: hardcode step 8 → step-4 arm red.
Mutation: always PASS → step-8 arm red.
Mutation: FLAG without expected=81 / detail naming 81 → nearest red.
Mutation: delete latent_8n1 → no finding.

Until this file, both directions lived only in qc.demo().
"""
import os
import subprocess

from conftest import _real_module

import qc

WAN_FRAMES = 77
WAN_FPS = 16
# 77 equidistant from 73 and 81 under step 8; half-to-even lands on 81.
NEAREST_STEP8 = 81


def _use_real_mixer(monkeypatch):
    real = _real_module("mixer")
    assert real is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real)


def _mp4(path, frames, fps):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate={fps}",
         "-frames:v", str(frames), "-c:v", "mpeg4", "-q:v", "5",
         "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, (
        f"fixture {path} is {os.path.getsize(path)} bytes — under "
        f"MIN_VIDEO_BYTES; size_floor would hide latent_8n1")
    return path


def _latent(findings):
    rows = [f for f in findings if f["check"] == "latent_8n1"]
    assert rows, f"no latent_8n1 finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_7_same_77_frame_file_step4_pass_step8_flag_names_81(
        tmp_path, monkeypatch):
    """One file, one variable (frame_step). WAN-legal at 4; illegal at 8."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "wan.mp4"), WAN_FRAMES, WAN_FPS)

    ok = _latent(qc.run(path, "clip", {"frame_step": 4}))
    assert ok["verdict"] == qc.PASS, ok
    assert int(ok["measured"]) == WAN_FRAMES, ok
    assert ok["unit"] == "frames"

    bad = _latent(qc.run(path, "clip", {"frame_step": 8}))
    assert bad["verdict"] == qc.FLAG, bad
    assert int(bad["measured"]) == WAN_FRAMES, bad
    assert int(bad["expected"]) == NEAREST_STEP8, bad
    assert bad["unit"] == "frames"
    detail = bad.get("detail") or ""
    assert str(NEAREST_STEP8) in detail, bad
    assert "nearest" in detail.lower(), bad


def test_t3_7_default_step_is_8_when_frame_step_absent(
        tmp_path, monkeypatch):
    """Unknown model defaults to the LTX step; 77 must FLAG naming 81."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "wan.mp4"), WAN_FRAMES, WAN_FPS)
    row = _latent(qc.run(path, "clip", {}))
    assert row["verdict"] == qc.FLAG, row
    assert int(row["expected"]) == NEAREST_STEP8, row
