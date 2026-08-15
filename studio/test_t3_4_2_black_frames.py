"""T3-4.2-black_frames: some frames below LUMA_FLOOR while mean PASSes.

docs/TRD-3 §4.2 table: mean luma per frame above a floor catches black
frames from a dead sampler. Whole-clip mean below the floor REJECTs
`luma`. When mean still PASSes but some frames sit below LUMA_FLOOR,
`check_video` FLAGs `black_frames` (not a silent pass on partial black).

measured is the dark-frame count, expected 0, unit frames, remedy
re-render-seed. Clean moving source emits no black_frames finding.
All-black is the luma REJECT path, not black_frames.

Mutation: delete the black_frames branch from check_video → no finding.
Mutation: always skip when dark>0 → partial-black arm red.
Mutation: measured not equal to independent dark count → T3-4 red.
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
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", lavfi,
         "-frames:v", str(frames), "-c:v", "mpeg4", "-q:v", "5",
         "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, (
        f"fixture {path} is {os.path.getsize(path)} bytes — under "
        f"MIN_VIDEO_BYTES; size_floor would hide black_frames")
    return path


def _partial_black(path, black_frames=5, bright_frames=25, fps=10):
    """Bright content with a few leading black frames; mean stays above floor."""
    td = os.path.dirname(path)
    black = os.path.join(td, "_bf_black.mp4")
    bright = os.path.join(td, "_bf_bright.mp4")
    _mp4(black, f"color=c=black:size=320x240:rate={fps}",
         frames=black_frames, fps=fps)
    _mp4(bright, f"testsrc2=size=320x240:rate={fps}",
         frames=bright_frames, fps=fps)
    lst = os.path.join(td, "_bf_list.txt")
    with open(lst, "w") as f:
        f.write(f"file '{black}'\nfile '{bright}'\n")
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, path
    return path


def _bf(findings):
    rows = [f for f in findings if f["check"] == "black_frames"]
    assert rows, f"no black_frames finding: {[f['check'] for f in findings]}"
    return rows[0]


def _dark_count(path):
    """Independent reading: frames with mean Y below LUMA_FLOOR."""
    luma = qc._readings(path, "signalstats", "lavfi.signalstats.YAVG")
    return sum(1 for v in luma if v < qc.LUMA_FLOOR), luma


def test_t3_4_2_black_frames_floor_constant():
    """Floor is LUMA_FLOOR; limited-range black (~16) is below it."""
    assert qc.LUMA_FLOOR == 24.0
    assert 16.0 < qc.LUMA_FLOOR


def test_t3_4_2_black_frames_partial_flags_clean_silent(
        tmp_path, monkeypatch):
    """One variable: some dark frames while mean still PASSes."""
    _use_real_mixer(monkeypatch)
    mixed = _partial_black(str(tmp_path / "partial.mp4"))
    clean = _mp4(str(tmp_path / "clean.mp4"),
                 "testsrc2=size=320x240:rate=10")

    dark, luma = _dark_count(mixed)
    mean = sum(luma) / len(luma)
    assert dark > 0, (dark, luma[:8])
    assert mean >= qc.LUMA_FLOOR, mean

    row = _bf(qc.run(mixed, "clip", {}))
    assert row["verdict"] == qc.FLAG, row
    assert int(row["measured"]) == dark, row
    assert int(row["expected"]) == 0, row
    assert row["unit"] == "frames"
    assert row["remedy_class"] == qc.REMEDY_RERENDER_SEED
    detail = (row["detail"] or "").lower()
    assert "black" in detail or "floor" in detail or "below" in detail, row

    luma_row = [f for f in qc.run(mixed, "clip", {}) if f["check"] == "luma"]
    assert luma_row and luma_row[0]["verdict"] == qc.PASS, luma_row

    clean_findings = qc.run(clean, "clip", {})
    assert not any(f["check"] == "black_frames" for f in clean_findings), [
        f["check"] for f in clean_findings]
    clean_luma = [f for f in clean_findings if f["check"] == "luma"]
    assert clean_luma and clean_luma[0]["verdict"] == qc.PASS, clean_luma


def test_t3_4_2_black_frames_measured_matches_independent(
        tmp_path, monkeypatch):
    """T3-4: measured equals independent dark-frame count, not free-form."""
    _use_real_mixer(monkeypatch)
    path = _partial_black(str(tmp_path / "partial.mp4"),
                          black_frames=7, bright_frames=23)
    independent, _ = _dark_count(path)
    assert independent > 0
    row = _bf(qc.run(path, "clip", {}))
    assert int(row["measured"]) == independent, (row, independent)


def test_t3_4_2_black_frames_all_black_is_luma_reject_not_black_frames(
        tmp_path, monkeypatch):
    """All-black mean fails: REJECT luma. black_frames only when mean PASSes."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "black.mp4"),
                "color=c=black:size=320x240:rate=10")
    findings = qc.run(path, "clip", {})
    luma = [f for f in findings if f["check"] == "luma"]
    assert luma and luma[0]["verdict"] == qc.REJECT, findings
    assert float(luma[0]["measured"]) < qc.LUMA_FLOOR, luma[0]
    assert not any(f["check"] == "black_frames" for f in findings), [
        f["check"] for f in findings]
