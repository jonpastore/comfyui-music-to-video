"""T3-4.2-luma: mean luma per frame above LUMA_FLOOR.

docs/TRD-3 §4.2 table: mean luma per frame must sit above a floor. The
failure mode is black frames from a dead sampler. A solid black clip
REJECTs with measured < LUMA_FLOOR. A normal moving source PASSes.
measured is the mean YAVG, expected is LUMA_FLOOR, unit Y.

Mutation: delete the check from check_video → no luma finding.
Mutation: always PASS → black arm red.
Mutation: measured not equal to measure_luma mean → T3-4 red.
Mutation: measured >= LUMA_FLOOR on black → floor calibration red.

Until this file, the black REJECT path lived only in qc.demo().
"""
import os
import subprocess

from conftest import _real_module

import qc


def _use_real_mixer(monkeypatch):
    real = _real_module("mixer")
    assert real is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real)


def _mp4(path, lavfi, frames=30, fps=10):
    # Solid-colour clips compress under MIN_VIDEO_BYTES with some
    # encoders; mpeg4 + enough frames keeps them above the floor.
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", lavfi,
         "-frames:v", str(frames), "-c:v", "mpeg4", "-q:v", "5",
         "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, (
        f"fixture {path} is {os.path.getsize(path)} bytes — under "
        f"MIN_VIDEO_BYTES; size_floor would hide luma")
    return path


def _luma(findings):
    rows = [f for f in findings if f["check"] == "luma"]
    assert rows, f"no luma finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_2_luma_measure_surface_and_raises():
    """The measurement is named. A non-video must raise, never 0.0."""
    assert hasattr(qc, "measure_luma"), (
        "T3-4.2-luma lives on qc.measure_luma so the check cannot "
        "be a hardcoded PASS")
    assert hasattr(qc, "LUMA_FLOOR")
    assert qc.LUMA_FLOOR == 24.0
    blank = "/tmp/t3_4_2_luma_empty.bin"
    open(blank, "wb").write(b"\x00" * 32)
    try:
        qc.measure_luma(blank)
    except (RuntimeError, ValueError) as e:
        msg = str(e).lower()
        assert "no" in msg or "not measured" in msg or "reading" in msg, e
    else:
        raise AssertionError("a non-video reported mean luma")


def test_t3_4_2_luma_black_rejects_normal_passes(tmp_path, monkeypatch):
    """Solid black REJECT (measured < LUMA_FLOOR); testsrc2 PASS."""
    _use_real_mixer(monkeypatch)
    good = _mp4(str(tmp_path / "good.mp4"),
                "testsrc2=size=320x240:rate=10")
    black = _mp4(str(tmp_path / "black.mp4"),
                 "color=c=black:size=320x240:rate=10")

    g = _luma(qc.run(good, "clip", {}))
    assert g["verdict"] == qc.PASS, g
    assert g["measured"] is not None
    assert float(g["measured"]) >= qc.LUMA_FLOOR, g
    assert float(g["expected"]) == qc.LUMA_FLOOR, g
    assert g["unit"] == "Y"
    assert g["remedy_class"] == qc.REMEDY_RERENDER_SEED

    row = _luma(qc.run(black, "clip", {}))
    assert row["verdict"] == qc.REJECT, row
    assert row["measured"] is not None
    assert float(row["measured"]) < qc.LUMA_FLOOR, row
    assert float(row["expected"]) == qc.LUMA_FLOOR, row
    assert row["unit"] == "Y"
    assert row["remedy_class"] == qc.REMEDY_RERENDER_SEED
    detail = (row["detail"] or "").lower()
    assert "luma" in detail or "black" in detail or "floor" in detail, row


def test_t3_4_2_luma_measured_matches_independent_reading(tmp_path, monkeypatch):
    """T3-4: measured equals measure_luma mean, not a free-form string."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "black.mp4"),
                "color=c=black:size=320x240:rate=10")
    independent = qc.measure_luma(path)
    assert independent["mean"] < qc.LUMA_FLOOR, independent
    row = _luma(qc.run(path, "clip", {}))
    assert abs(float(row["measured"]) - float(independent["mean"])) < 0.05, (
        row, independent)


def test_t3_4_2_luma_always_pass_mutation_would_miss_black(
        tmp_path, monkeypatch):
    """Black must REJECT — always-PASS is the mutation this catches."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "black.mp4"),
                "color=c=black:size=320x240:rate=10")
    row = _luma(qc.run(path, "clip", {}))
    assert row["verdict"] == qc.REJECT, row
    assert float(row["measured"]) < qc.LUMA_FLOOR, row
