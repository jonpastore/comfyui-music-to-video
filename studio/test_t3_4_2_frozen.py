"""T3-4.2-frozen: consecutive-frame freeze FLAG/PASS.

docs/TRD-3 §4.2 table: consecutive-frame difference must stay above a
floor; a frozen segment is the failure mode. Still solid colour held
for ≥0.5s FLAGs. A moving source of the same duration PASSes.
measured is the count of freezedetect spans (independent reading),
expected 0, unit spans, remedy re-render-seed.

Mutation: delete the check from check_video → no frozen finding.
Mutation: always PASS → still arm red.
Mutation: measured not equal to freezedetect span count → T3-4 red.
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
    # Solid colour compresses hard; mpeg4 + enough frames stay above
    # MIN_VIDEO_BYTES so size_floor does not hide the frozen check.
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", lavfi,
         "-frames:v", str(frames), "-c:v", "mpeg4", "-q:v", "5",
         "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, (
        f"fixture {path} is {os.path.getsize(path)} bytes — under "
        f"MIN_VIDEO_BYTES; size_floor would hide frozen")
    return path


def _independent_freeze_spans(path):
    """Same freezedetect the check uses; count freeze_start events."""
    return len(qc._stderr_events(
        path, "freezedetect=n=-60dB:d=0.5", r"freeze_start"))


def _fr(findings):
    rows = [f for f in findings if f["check"] == "frozen"]
    assert rows, f"no frozen finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_2_frozen_still_flags_moving_passes(tmp_path, monkeypatch):
    """One variable: still vs moving. Same size, frames, rate, codec."""
    _use_real_mixer(monkeypatch)
    still = _mp4(str(tmp_path / "still.mp4"),
                 "color=c=red:size=320x240:rate=10")
    moving = _mp4(str(tmp_path / "moving.mp4"),
                  "testsrc2=size=320x240:rate=10")

    assert _independent_freeze_spans(still) >= 1, still
    assert _independent_freeze_spans(moving) == 0, moving

    bad = _fr(qc.run(still, "clip", {}))
    assert bad["verdict"] == qc.FLAG, bad
    assert int(bad["measured"]) >= 1, bad
    assert int(bad["expected"]) == 0, bad
    assert bad["unit"] == "spans"
    assert bad["remedy_class"] == qc.REMEDY_RERENDER_SEED
    detail = (bad["detail"] or "").lower()
    assert "frozen" in detail or "freeze" in detail, bad

    good = _fr(qc.run(moving, "clip", {}))
    assert good["verdict"] == qc.PASS, good
    assert int(good["measured"]) == 0, good
    assert int(good["expected"]) == 0, good
    assert good["unit"] == "spans"
    assert good["remedy_class"] == qc.REMEDY_RERENDER_SEED


def test_t3_4_2_frozen_measured_matches_independent(tmp_path, monkeypatch):
    """T3-4: measured equals freezedetect span count, not a free-form string."""
    _use_real_mixer(monkeypatch)
    still = _mp4(str(tmp_path / "still.mp4"),
                 "color=c=blue:size=320x240:rate=10")
    independent = _independent_freeze_spans(still)
    assert independent >= 1, still
    row = _fr(qc.run(still, "clip", {}))
    assert int(row["measured"]) == independent, (row, independent)


def test_t3_4_2_frozen_always_pass_mutation_would_miss_still(
        tmp_path, monkeypatch):
    """Still hold must FLAG — always-PASS is the mutation this catches."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "still.mp4"),
                "color=c=green:size=320x240:rate=10")
    row = _fr(qc.run(path, "clip", {}))
    assert row["verdict"] == qc.FLAG, row
    assert int(row["measured"]) > 0, row
