"""T3-8: an interpolated clip is one frame short and must not be flagged.

docs/TRD-3 §4.2: RIFE returns (n-1)*m+1 frames, not n*m. 77 doubled is
153. make_postproc.out_fps writes fps*((n-1)*m+1)/n so duration stays
the source length. At naive 32 fps the same 153 frames is 4.781 s where
the source was 4.8125 s — silent drift. Latent-rule exemption alone is
not this criterion: duration, fps and frame_count must PASS on the
compensated file.

Mutation: delete expect_interpolated → no surface.
Mutation: frames = n*m in the expect → frame_count rejects a correct
RIFE file.
Mutation: fps = source*m (not out_fps) → fps flags a compensated file
and duration drifts on the naive one.
Mutation: only assert no latent_8n1 → the three length checks never run.
"""
import os
import subprocess
import sys

from conftest import _real_module

import qc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import make_postproc  # noqa: E402


# The measured case in make_postproc / TRD-3 T3-8.
SRC_FRAMES = 77
SRC_FPS = 16.0
MULTIPLIER = 2
RIFE_FRAMES = (SRC_FRAMES - 1) * MULTIPLIER + 1  # 153


def _use_real_mixer(monkeypatch):
    real = _real_module("mixer")
    assert real is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real)


def _mp4(path, frames, fps):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate={fps}",
         "-frames:v", str(frames), "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


def _by_check(findings):
    return {f["check"]: f for f in findings}


def test_t3_8_expect_interpolated_is_rife_math_not_n_times_m():
    """The expect surface owns RIFE arithmetic. n*m is the bug."""
    assert hasattr(qc, "expect_interpolated"), (
        "T3-8 lives on qc.expect_interpolated so callers cannot invent "
        "n*m frames or fps*m")
    exp = qc.expect_interpolated(SRC_FRAMES, SRC_FPS, MULTIPLIER)
    assert exp["frames"] == RIFE_FRAMES
    assert exp["frames"] != SRC_FRAMES * MULTIPLIER
    assert abs(exp["fps"] - make_postproc.out_fps(SRC_FPS, SRC_FRAMES, MULTIPLIER)) < 1e-9
    assert abs(exp["fps"] - SRC_FPS * MULTIPLIER) > 0.01
    assert abs(exp["duration"] - SRC_FRAMES / SRC_FPS) < 1e-9
    assert exp["interpolated"] is True


def test_t3_8_compensated_clip_passes_duration_fps_frame_count(
        tmp_path, monkeypatch):
    """Positive half: (n-1)*m+1 frames at out_fps keeps source length.

    Latent exemption is required and not sufficient — all three length
    checks must PASS by name.
    """
    _use_real_mixer(monkeypatch)
    out_fps = make_postproc.out_fps(SRC_FPS, SRC_FRAMES, MULTIPLIER)
    path = _mp4(str(tmp_path / "rife.mp4"), RIFE_FRAMES, out_fps)
    expect = qc.expect_interpolated(SRC_FRAMES, SRC_FPS, MULTIPLIER)
    rows = _by_check(qc.run(path, "clip", expect))

    for name in ("duration", "frame_count", "fps"):
        assert name in rows, (name, sorted(rows))
        assert rows[name]["verdict"] == qc.PASS, rows[name]
    assert rows["frame_count"]["measured"] == RIFE_FRAMES
    assert rows["frame_count"]["expected"] == RIFE_FRAMES
    assert abs(rows["fps"]["measured"] - out_fps) <= qc.FPS_TOL
    assert abs(rows["duration"]["measured"] - SRC_FRAMES / SRC_FPS) <= qc.DURATION_TOL_S
    # Latent rule is exempt; a 153-frame clip is not 8n+1.
    assert "latent_8n1" not in rows


def test_t3_8_naive_double_fps_is_flagged(tmp_path, monkeypatch):
    """Negative half: 153 frames at 32 fps is the silent-drift case.

    Source was 4.8125 s; 153/32 = 4.781 s. Duration tol alone may still
    pass one clip (0.031 < 0.10); fps against out_fps must FLAG.
    """
    _use_real_mixer(monkeypatch)
    naive_fps = SRC_FPS * MULTIPLIER
    path = _mp4(str(tmp_path / "naive.mp4"), RIFE_FRAMES, naive_fps)
    expect = qc.expect_interpolated(SRC_FRAMES, SRC_FPS, MULTIPLIER)
    rows = _by_check(qc.run(path, "clip", expect))
    assert rows["frame_count"]["verdict"] == qc.PASS, rows["frame_count"]
    assert rows["fps"]["verdict"] != qc.PASS, rows["fps"]
    assert abs(rows["fps"]["measured"] - naive_fps) <= qc.FPS_TOL
    want_fps = make_postproc.out_fps(SRC_FPS, SRC_FRAMES, MULTIPLIER)
    assert abs(rows["fps"]["expected"] - want_fps) <= qc.FPS_TOL
    assert abs(rows["fps"]["measured"] - want_fps) > qc.FPS_TOL


def test_t3_8_nm_frame_expect_rejects_correct_rife_file(tmp_path, monkeypatch):
    """If expect lies with n*m, the correct RIFE file is rejected — that
    is the wrong-expect direction T3-8 stops operators from writing."""
    _use_real_mixer(monkeypatch)
    out_fps = make_postproc.out_fps(SRC_FPS, SRC_FRAMES, MULTIPLIER)
    path = _mp4(str(tmp_path / "rife.mp4"), RIFE_FRAMES, out_fps)
    wrong = dict(qc.expect_interpolated(SRC_FRAMES, SRC_FPS, MULTIPLIER))
    wrong["frames"] = SRC_FRAMES * MULTIPLIER  # 154 — the n*m trap
    rows = _by_check(qc.run(path, "clip", wrong))
    assert rows["frame_count"]["verdict"] == qc.REJECT, rows["frame_count"]
    assert rows["frame_count"]["measured"] == RIFE_FRAMES
    assert rows["frame_count"]["expected"] == SRC_FRAMES * MULTIPLIER
