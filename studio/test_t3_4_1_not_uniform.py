"""T3-4.1-not_uniform: uniform / single flat colour REJECTs.

docs/TRD-3 §4.1: generated stills must not be uniform or a single flat
colour. Measurement is RGB pixel standard deviation via
qc.measure_pixel_std. Floor is UNIFORM_STD_FLOOR (1.0 levels). Below
the floor REJECTs. Above PASSes. measured is the independent std,
expected is UNIFORM_STD_FLOOR, unit levels, remedy edit-text (T3-33).

Mutation: delete the check from check_image → no not_uniform finding.
Mutation: always PASS → flat-colour arm red.
Mutation: measured not equal to measure_pixel_std → T3-4 red.
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


def _nu(findings):
    rows = [f for f in findings if f["check"] == "not_uniform"]
    assert rows, f"no not_uniform finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_1_not_uniform_measure_surface_and_raises():
    """The measurement is named. A non-image must raise, never 0.0."""
    assert hasattr(qc, "measure_pixel_std"), (
        "T3-4.1-not_uniform lives on qc.measure_pixel_std so the check "
        "cannot be a hardcoded PASS")
    assert hasattr(qc, "UNIFORM_STD_FLOOR")
    assert qc.UNIFORM_STD_FLOOR == 1.0
    blank = "/tmp/t3_4_1_not_uniform_empty.bin"
    open(blank, "wb").write(b"\x00" * 32)
    try:
        qc.measure_pixel_std(blank)
    except (RuntimeError, ValueError, OSError) as e:
        msg = str(e).lower()
        assert ("no" in msg or "not measured" in msg or "reading" in msg
                or "cannot" in msg or "open" in msg), e
    else:
        raise AssertionError("a non-image reported pixel std")


def test_t3_4_1_not_uniform_flat_rejects_varied_passes(tmp_path):
    """One variable: flat colour vs colour-bar still. Flat REJECTs."""
    good = _png(str(tmp_path / "ok.png"))
    black = _solid(str(tmp_path / "black.png"), (0, 0, 0))
    red = _solid(str(tmp_path / "red.png"), (200, 20, 20))
    gray = _solid(str(tmp_path / "gray.png"), (128, 128, 128))

    g = _nu(qc.run(good, "image", {}))
    assert g["verdict"] == qc.PASS, g
    assert g["measured"] is not None
    assert float(g["measured"]) > qc.UNIFORM_STD_FLOOR, g
    assert float(g["expected"]) == qc.UNIFORM_STD_FLOOR
    assert g["unit"] == "levels"
    assert g["remedy_class"] == qc.REMEDY_EDIT_TEXT
    detail = (g["detail"] or "").lower()
    assert "std" in detail or "uniform" in detail or "dev" in detail, g

    for path, label in ((black, "black"), (red, "red"), (gray, "gray")):
        row = _nu(qc.run(path, "image", {}))
        assert row["verdict"] == qc.REJECT, (label, row)
        assert float(row["measured"]) <= qc.UNIFORM_STD_FLOOR, (label, row)
        assert float(row["expected"]) == qc.UNIFORM_STD_FLOOR
        assert row["unit"] == "levels"
        assert row["remedy_class"] == qc.REMEDY_EDIT_TEXT


def test_t3_4_1_not_uniform_measured_matches_independent(tmp_path):
    """T3-4: measured equals measure_pixel_std, not a free-form string."""
    path = _solid(str(tmp_path / "flat.png"), (40, 80, 160))
    independent = qc.measure_pixel_std(path)
    assert independent <= qc.UNIFORM_STD_FLOOR, independent
    row = _nu(qc.run(path, "image", {}))
    assert abs(float(row["measured"]) - float(round(independent, 2))) < 0.05, (
        row, independent)


def test_t3_4_1_not_uniform_always_pass_mutation_would_miss_flat(tmp_path):
    """Single flat colour must REJECT — always-PASS is the mutation this catches."""
    path = _solid(str(tmp_path / "flat.png"), (255, 0, 0))
    row = _nu(qc.run(path, "image", {}))
    assert row["verdict"] == qc.REJECT, row
    assert float(row["measured"]) <= qc.UNIFORM_STD_FLOOR, row
