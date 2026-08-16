"""T3-4.1-not_blank: image mean level above LUMA_FLOOR.

docs/TRD-3 §4.1: generated stills must not be blank. Measurement is mean
RGB level via qc.measure_mean_level. Floor is LUMA_FLOOR (24.0 levels).
Below the floor REJECTs. At or above PASSes. measured is the independent
mean, expected is LUMA_FLOOR, unit levels, remedy edit-text (T3-33).

Distinct from not_uniform (max per-channel spatial std): solid bright red
PASSes not_blank (mean >> floor) and REJECTs not_uniform (std ~ 0).

Mutation: delete the check from check_image → no not_blank finding.
Mutation: always PASS → solid-black arm red.
Mutation: measured not equal to measure_mean_level → T3-4 red.
Mutation: no CHECK_REMEDY_CLASS entry → finding() raises (T3-27).
"""
import os
import subprocess

from PIL import Image
import numpy as np

import qc


def _png(path, lavfi="testsrc2=size=256x192"):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", lavfi, "-frames:v", "1", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(path), path
    return path


def _solid(path, rgb, size=(64, 64)):
    arr = np.full((size[1], size[0], 3), rgb, dtype="uint8")
    Image.fromarray(arr).save(path)
    return path


def _nb(findings):
    rows = [f for f in findings if f["check"] == "not_blank"]
    assert rows, f"no not_blank finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_1_not_blank_measure_surface_and_raises():
    """The measurement is named. A non-image must raise, never 0.0."""
    assert hasattr(qc, "measure_mean_level"), (
        "T3-4.1-not_blank lives on qc.measure_mean_level so the check "
        "cannot be a hardcoded PASS")
    assert hasattr(qc, "LUMA_FLOOR")
    assert qc.LUMA_FLOOR == 24.0
    blank = "/tmp/t3_4_1_not_blank_empty.bin"
    open(blank, "wb").write(b"\x00" * 32)
    try:
        qc.measure_mean_level(blank)
    except (RuntimeError, ValueError, OSError) as e:
        msg = str(e).lower()
        assert ("no" in msg or "not measured" in msg or "reading" in msg
                or "cannot" in msg or "open" in msg), e
    else:
        raise AssertionError("a non-image reported mean level")


def test_t3_4_1_not_blank_black_rejects_testsrc2_passes(tmp_path):
    """Solid black REJECT (mean < LUMA_FLOOR); testsrc2 PASS."""
    good = _png(str(tmp_path / "ok.png"))
    black = _solid(str(tmp_path / "black.png"), (0, 0, 0))

    g = _nb(qc.run(good, "image", {}))
    assert g["verdict"] == qc.PASS, g
    assert g["measured"] is not None
    assert float(g["measured"]) >= qc.LUMA_FLOOR, g
    assert float(g["expected"]) == qc.LUMA_FLOOR
    assert g["unit"] == "levels"
    assert g["remedy_class"] == qc.REMEDY_EDIT_TEXT
    detail = (g["detail"] or "").lower()
    assert "mean" in detail or "level" in detail or "blank" in detail, g

    row = _nb(qc.run(black, "image", {}))
    assert row["verdict"] == qc.REJECT, row
    assert float(row["measured"]) < qc.LUMA_FLOOR, row
    assert float(row["expected"]) == qc.LUMA_FLOOR
    assert row["unit"] == "levels"
    assert row["remedy_class"] == qc.REMEDY_EDIT_TEXT


def test_t3_4_1_not_blank_measured_matches_independent(tmp_path):
    """T3-4: measured equals measure_mean_level, not a free-form string."""
    path = _solid(str(tmp_path / "black.png"), (0, 0, 0))
    independent = qc.measure_mean_level(path)
    assert independent < qc.LUMA_FLOOR, independent
    row = _nb(qc.run(path, "image", {}))
    assert abs(float(row["measured"]) - float(round(independent, 1))) < 0.05, (
        row, independent)


def test_t3_4_1_not_blank_distinct_from_not_uniform(tmp_path):
    """Solid bright red PASSes not_blank and REJECTs not_uniform.

    One variable: mean level (not_blank) vs spatial std (not_uniform).
    A flat bright fill is not blank — the model drew colour; it is still
    uniform and must fail the other check.
    """
    path = _solid(str(tmp_path / "red.png"), (200, 20, 20))
    findings = qc.run(path, "image", {})
    nb = _nb(findings)
    assert nb["verdict"] == qc.PASS, nb
    assert float(nb["measured"]) >= qc.LUMA_FLOOR, nb

    nu = [f for f in findings if f["check"] == "not_uniform"]
    assert nu, f"no not_uniform finding: {[f['check'] for f in findings]}"
    assert nu[0]["verdict"] == qc.REJECT, nu[0]
    assert float(nu[0]["measured"]) <= qc.UNIFORM_STD_FLOOR, nu[0]


def test_t3_4_1_not_blank_always_pass_mutation_would_miss_black(tmp_path):
    """Solid black must REJECT — always-PASS is the mutation this catches."""
    path = _solid(str(tmp_path / "black.png"), (0, 0, 0))
    row = _nb(qc.run(path, "image", {}))
    assert row["verdict"] == qc.REJECT, row
    assert float(row["measured"]) < qc.LUMA_FLOOR, row


def test_t3_4_1_not_blank_in_check_remedy_class():
    """T3-27: not_blank names a remedy class before a finding can be emitted."""
    assert "not_blank" in qc.CHECK_REMEDY_CLASS, (
        "not_blank not in CHECK_REMEDY_CLASS — T3-4.1-not_blank not wired")
    assert qc.CHECK_REMEDY_CLASS["not_blank"] == qc.REMEDY_EDIT_TEXT
