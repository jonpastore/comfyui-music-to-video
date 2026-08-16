"""T3-4.1-alpha: image alpha is not fully transparent.

docs/TRD-3 §4.1: anchors/refs/candidates must open, match resolution,
not be uniform/blank/flat, and alpha must not be fully transparent.
A fully transparent RGBA sheet is a blank render by another name —
tier-1 REJECT, no judgement.

RGB without an alpha channel is treated as fully opaque (PASS).
measured is max alpha (0–255), expected ALPHA_MIN, unit levels.
remedy class edit-text (T3-33).

Mutation: delete the check from check_image → no alpha finding.
Mutation: always PASS → transparent arm red.
Mutation: measured not equal to measure_alpha → T3-4 red.
Mutation: no CHECK_REMEDY_CLASS entry → finding() raises (T3-27).
"""
import os

from PIL import Image
import numpy as np

import qc


def _rgb(path, size=(64, 64), color=(40, 80, 160)):
    Image.fromarray(
        np.full((size[1], size[0], 3), color, dtype="uint8")
    ).save(path)
    return path


def _rgba(path, size=(64, 64), rgb=(40, 80, 160), alpha=255):
    arr = np.zeros((size[1], size[0], 4), dtype="uint8")
    arr[..., 0] = rgb[0]
    arr[..., 1] = rgb[1]
    arr[..., 2] = rgb[2]
    arr[..., 3] = alpha
    Image.fromarray(arr, mode="RGBA").save(path)
    return path


def _alpha(findings):
    rows = [f for f in findings if f["check"] == "alpha"]
    assert rows, f"no alpha finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_1_alpha_measure_surface_and_raises():
    """The measurement is named. A non-image must raise, never 0.0."""
    assert hasattr(qc, "measure_alpha"), (
        "T3-4.1-alpha lives on qc.measure_alpha so the check cannot "
        "be a hardcoded PASS")
    assert hasattr(qc, "ALPHA_MIN")
    blank = "/tmp/t3_4_1_alpha_empty.bin"
    open(blank, "wb").write(b"\x00" * 32)
    try:
        qc.measure_alpha(blank)
    except (RuntimeError, ValueError) as e:
        msg = str(e).lower()
        assert "no" in msg or "not measured" in msg or "alpha" in msg, e
    else:
        raise AssertionError("a non-image reported alpha")


def test_t3_4_1_alpha_transparent_rejects_opaque_passes(tmp_path):
    """One variable: fully transparent alpha vs any opacity."""
    opaque_rgb = _rgb(str(tmp_path / "rgb.png"))
    opaque_rgba = _rgba(str(tmp_path / "opaque.png"), alpha=255)
    partial = _rgba(str(tmp_path / "partial.png"), alpha=128)
    clear = _rgba(str(tmp_path / "clear.png"), alpha=0)

    for path, label in (
        (opaque_rgb, "rgb"),
        (opaque_rgba, "rgba-255"),
        (partial, "rgba-128"),
    ):
        row = _alpha(qc.run(path, "image", {}))
        assert row["verdict"] == qc.PASS, (label, row)
        assert float(row["measured"]) >= qc.ALPHA_MIN, (label, row)
        assert row["expected"] == qc.ALPHA_MIN
        assert row["unit"] == "levels"
        assert row["remedy_class"] == qc.REMEDY_EDIT_TEXT

    row = _alpha(qc.run(clear, "image", {}))
    assert row["verdict"] == qc.REJECT, row
    assert float(row["measured"]) < qc.ALPHA_MIN, row
    assert row["expected"] == qc.ALPHA_MIN
    assert row["unit"] == "levels"
    assert row["remedy_class"] == qc.REMEDY_EDIT_TEXT
    detail = (row["detail"] or "").lower()
    assert "transparent" in detail or "alpha" in detail, row


def test_t3_4_1_alpha_measured_matches_independent_reading(tmp_path):
    """T3-4: measured equals measure_alpha max, not a free-form string."""
    path = _rgba(str(tmp_path / "clear.png"), alpha=0)
    independent = qc.measure_alpha(path)
    assert independent["max"] < qc.ALPHA_MIN, independent
    row = _alpha(qc.run(path, "image", {}))
    assert abs(float(row["measured"]) - float(independent["max"])) < 0.05, (
        row, independent)


def test_t3_4_1_alpha_rgb_is_fully_opaque(tmp_path):
    """No alpha channel is not fully transparent — max is 255."""
    path = _rgb(str(tmp_path / "no_a.png"))
    reading = qc.measure_alpha(path)
    assert reading["max"] == 255.0, reading
    row = _alpha(qc.run(path, "image", {}))
    assert row["verdict"] == qc.PASS, row
    assert float(row["measured"]) == 255.0, row


def test_t3_4_1_alpha_in_check_remedy_class():
    """T3-27: alpha names a remedy class before a finding can be emitted."""
    assert "alpha" in qc.CHECK_REMEDY_CLASS, (
        "alpha not in CHECK_REMEDY_CLASS — T3-4.1-alpha not wired")
    assert qc.CHECK_REMEDY_CLASS["alpha"] == qc.REMEDY_EDIT_TEXT
