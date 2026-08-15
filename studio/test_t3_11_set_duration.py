"""T3-11: rendered set duration vs mixer.set_duration() on the artefact.

docs/TRD-3 T3-11: the rendered set's duration equals mixer.set_duration()'s
prediction within mixer.SET_DURATION_TOLERANCE — imported, not restated.
T1-7 asserts this at build time; this file asserts it through qc.run /
qc.check_set on the artefact. Both directions: a matching file PASSes and
a file off by more than the named constant REJECTs.

Mutation: delete duration_matches_prediction → both arms fail.
Mutation: compare against DURATION_TOL_S (0.10) or a restated 0.05 →
the just-outside arm stays PASS.
Mutation: stop calling mixer.set_duration → expected is no longer the
renderer’s own arithmetic.
"""
import inspect
import os
import subprocess

from conftest import _real_module

import qc


mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"


def _use_real_mixer(monkeypatch):
    monkeypatch.setattr(qc, "mixer", mixer)


def _mp4(path, seconds, fps=30):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate={fps}:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "48000", "-shortest", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


def _item(path, **extra):
    row = {"video": path, "transition": "cut", "secs": 0.0}
    row.update(extra)
    return row


def _prediction_row(findings):
    rows = [f for f in findings if f["check"] == "duration_matches_prediction"]
    assert rows, findings
    return rows[0]


def test_t3_11_check_set_imports_named_tolerance_not_restated():
    """Two copies of 0.05 are the defect T3-11 exists to stop."""
    src = inspect.getsource(qc.check_set)
    assert "mixer.set_duration" in src
    assert "mixer.SET_DURATION_TOLERANCE" in src
    assert "<= mixer.SET_DURATION_TOLERANCE" in src
    assert "0.05" not in src
    assert "DURATION_TOL_S" not in src
    assert mixer.SET_DURATION_TOLERANCE == qc.mixer.SET_DURATION_TOLERANCE


def test_t3_11_matching_artefact_passes(tmp_path, monkeypatch):
    """Positive half: a file whose probed length is the prediction PASSes."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "set.mp4"), 2)
    items = [_item(path)]
    predicted = mixer.set_duration(items, key="video")
    actual = mixer.probe(path)["duration"]
    assert abs(actual - predicted) <= mixer.SET_DURATION_TOLERANCE, (
        f"fixture itself is off: actual={actual} predicted={predicted}")

    row = _prediction_row(qc.run(path, "set", items=items))
    assert row["verdict"] == qc.PASS, row
    assert row["kind"] == "set"
    assert row["measured"] == round(actual, 3)
    assert row["expected"] == round(predicted, 3)
    assert row["unit"] == "s"
    assert row["remedy_class"] == qc.REMEDY_NONE


def test_t3_11_mismatch_beyond_tolerance_rejects(tmp_path, monkeypatch):
    """Deliberately broken artefact: prediction moved by more than
    SET_DURATION_TOLERANCE. T1-7's matching render is not this half."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "set.mp4"), 2)
    items = [_item(path, in_secs=1.0)]
    predicted = mixer.set_duration(items, key="video")
    actual = mixer.probe(path)["duration"]
    gap = abs(actual - predicted)
    assert gap > mixer.SET_DURATION_TOLERANCE, (
        f"fixture is not broken: gap={gap} tol={mixer.SET_DURATION_TOLERANCE}")

    row = _prediction_row(qc.check_set(path, items))
    assert row["verdict"] == qc.REJECT, row
    assert row["measured"] == round(actual, 3)
    assert row["expected"] == round(predicted, 3)
    assert row["unit"] == "s"


def test_t3_11_just_inside_passes_just_outside_rejects(tmp_path, monkeypatch):
    """The named constant is the one variable. DURATION_TOL_S (0.10) would
    pass both sides; a restated looser bound stays green here."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "set.mp4"), 2)
    actual = mixer.probe(path)["duration"]
    tol = mixer.SET_DURATION_TOLERANCE
    inside = [_item(path, in_secs=tol * 0.6)]
    outside = [_item(path, in_secs=tol * 1.4)]

    in_pred = mixer.set_duration(inside, key="video")
    out_pred = mixer.set_duration(outside, key="video")
    assert abs(actual - in_pred) <= tol, (actual, in_pred, tol)
    assert abs(actual - out_pred) > tol, (actual, out_pred, tol)

    in_row = _prediction_row(qc.run(path, "set", items=inside))
    out_row = _prediction_row(qc.run(path, "set", items=outside))
    assert in_row["verdict"] == qc.PASS, in_row
    assert out_row["verdict"] == qc.REJECT, out_row
    assert in_row["expected"] == round(in_pred, 3)
    assert out_row["expected"] == round(out_pred, 3)
