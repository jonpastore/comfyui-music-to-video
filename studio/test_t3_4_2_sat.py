"""T3-4.2-sat: clip channel-saturation check (NaN / green garbage).

docs/TRD-3 §4.2 table: channel saturation must stay in range. The failure
mode is a dead sampler that emits NaN and encodes as solid green garbage.
A normal moving source PASSes. A solid green (or lime) clip FLAGs.
measured is an independent green-dominance reading, not a presence bit.

Mutation: delete the check from check_video → no channel_sat finding.
Mutation: always PASS → green arm red.
Mutation: measured not equal to measure_channel_sat → T3-4 red.
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
    # Solid-colour clips compress under MIN_VIDEO_BYTES with the
    # default encoder; mpeg4 + enough frames keeps them above the floor.
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", lavfi,
         "-frames:v", str(frames), "-c:v", "mpeg4", "-q:v", "5",
         "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, (
        f"fixture {path} is {os.path.getsize(path)} bytes — under "
        f"MIN_VIDEO_BYTES; size_floor would hide channel_sat")
    return path


def _sat(findings):
    rows = [f for f in findings if f["check"] == "channel_sat"]
    assert rows, f"no channel_sat finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_2_sat_measure_surface_and_raises():
    """The measurement is named. A non-video must raise, never 0.0."""
    assert hasattr(qc, "measure_channel_sat"), (
        "T3-4.2-sat lives on qc.measure_channel_sat so the check cannot "
        "be a hardcoded PASS")
    assert hasattr(qc, "CHANNEL_SAT_LIMIT")
    blank = "/tmp/t3_4_2_sat_empty.bin"
    open(blank, "wb").write(b"\x00" * 32)
    try:
        qc.measure_channel_sat(blank)
    except (RuntimeError, ValueError) as e:
        msg = str(e).lower()
        assert "no" in msg or "not measured" in msg or "reading" in msg, e
    else:
        raise AssertionError("a non-video reported channel saturation")


def test_t3_4_2_sat_green_garbage_flags_normal_passes(tmp_path, monkeypatch):
    """Solid green / lime FLAG; testsrc2 PASS. One variable: the pixels."""
    _use_real_mixer(monkeypatch)
    good = _mp4(str(tmp_path / "good.mp4"),
                "testsrc2=size=320x240:rate=10")
    green = _mp4(str(tmp_path / "green.mp4"),
                 "color=c=green:size=320x240:rate=10")
    lime = _mp4(str(tmp_path / "lime.mp4"),
                "color=c=0x00FF00:size=320x240:rate=10")

    g = _sat(qc.run(good, "clip", {}))
    assert g["verdict"] == qc.PASS, g
    assert g["measured"] is not None
    assert g["measured"] <= qc.CHANNEL_SAT_LIMIT, g
    assert g["expected"] == qc.CHANNEL_SAT_LIMIT
    assert g["unit"] == "levels"
    assert g["remedy_class"] == qc.REMEDY_RERENDER_SEED

    for path, label in ((green, "green"), (lime, "lime")):
        row = _sat(qc.run(path, "clip", {}))
        assert row["verdict"] == qc.FLAG, (label, row)
        assert row["measured"] > qc.CHANNEL_SAT_LIMIT, (label, row)
        assert row["expected"] == qc.CHANNEL_SAT_LIMIT
        assert row["unit"] == "levels"
        detail = (row["detail"] or "").lower()
        assert "green" in detail or "garbage" in detail or "sat" in detail, row


def test_t3_4_2_sat_measured_matches_independent_reading(tmp_path, monkeypatch):
    """T3-4: measured equals measure_channel_sat, not a free-form string."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "lime.mp4"),
                "color=c=0x00FF00:size=320x240:rate=10")
    independent = qc.measure_channel_sat(path)
    assert independent["max"] > qc.CHANNEL_SAT_LIMIT, independent
    row = _sat(qc.run(path, "clip", {}))
    assert abs(float(row["measured"]) - float(independent["max"])) < 0.05, (
        row, independent)


def test_t3_4_2_sat_gray_and_black_are_not_green_garbage(tmp_path, monkeypatch):
    """Uniform gray/black are not the green-garbage failure mode."""
    _use_real_mixer(monkeypatch)
    for name, color in (("gray", "0x808080"), ("black", "black")):
        path = _mp4(str(tmp_path / f"{name}.mp4"),
                    f"color=c={color}:size=320x240:rate=10")
        row = _sat(qc.run(path, "clip", {}))
        assert row["verdict"] == qc.PASS, (name, row)
        assert row["measured"] <= qc.CHANNEL_SAT_LIMIT, (name, row)
