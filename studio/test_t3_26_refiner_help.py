"""T3-26: whether the refiner helps is a fail-closed labelled-set measurement.

docs/TRD-3 T3-26: a refine pass that does not improve the tier-2 score
on a labelled set is reported as not helping, and the finding says so.
Catalogue `proven: opportunistic` is not a measurement. Empty set,
missing files, or missing scores raise NOT MEASURED — never skip, never
assume it helps. A labelled set whose refined scores rise reports help;
always-not-helping stays green forever.
"""
import os

import pytest
from PIL import Image

import db
import models
import qc
import qc_service


def _png(path):
    Image.new("RGB", (8, 8), (20, 20, 20)).save(path)


def _pair_files(tmp_path, n=2):
    pairs = []
    for i in range(n):
        plain = tmp_path / f"plain_{i}.png"
        refined = tmp_path / f"refined_{i}.png"
        _png(plain)
        _png(refined)
        pairs.append({
            "label": f"clip_{i}",
            "plain": str(plain),
            "refined": str(refined),
        })
    return pairs


def test_t3_26_no_improve_finding_says_not_helping(tmp_path):
    """No-op refine on a labelled set: finding says not helping.

    Mutation: hardcode helps=True, or treat opportunistic as a pass.
    """
    pairs = _pair_files(tmp_path)
    scores = {p["plain"]: 0.40 for p in pairs}
    scores.update({p["refined"]: 0.40 for p in pairs})

    report = qc.measure_refiner_help(
        pairs, score_fn=lambda path, label: scores[path])

    assert report["helps"] is False, report
    assert report["delta"] == 0, report
    assert report.get("proven") != "opportunistic", report
    assert models.CATALOG["wan22_i2v_low"]["proven"] == "opportunistic"

    found = qc.refiner_help_finding(report)
    assert found["check"] == qc.REFINER_HELP_CHECK
    assert found["verdict"] != qc.PASS, found
    assert "not helping" in found["detail"].lower(), found


def test_t3_26_worse_score_is_not_helping(tmp_path):
    """A refine that drops the tier-2 score is not a help."""
    pairs = _pair_files(tmp_path)
    scores = {p["plain"]: 0.70 for p in pairs}
    scores.update({p["refined"]: 0.40 for p in pairs})

    report = qc.measure_refiner_help(
        pairs, score_fn=lambda path, label: scores[path])

    assert report["helps"] is False, report
    assert report["delta"] < 0, report
    assert "not helping" in qc.refiner_help_finding(report)["detail"].lower()


def test_t3_26_improved_labelled_set_reports_help(tmp_path):
    """Positive half: a real improvement is reported as helping.

    Mutation: always return helps=False satisfies the refusal forever.
    """
    pairs = _pair_files(tmp_path)
    scores = {p["plain"]: 0.30 + 0.02 * i for i, p in enumerate(pairs)}
    scores.update({p["refined"]: 0.80 + 0.01 * i for i, p in enumerate(pairs)})

    report = qc.measure_refiner_help(
        pairs, score_fn=lambda path, label: scores[path])

    assert report["helps"] is True, report
    assert report["delta"] > 0, report
    assert report["n"] == 2, report
    assert report.get("proven") != "opportunistic", report
    found = qc.refiner_help_finding(report)
    assert found["verdict"] == qc.PASS, found
    assert "not helping" not in found["detail"].lower(), found


def test_t3_26_empty_set_fail_closed_not_measured():
    """Empty labelled set is NOT MEASURED, never opportunistic-helps."""
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.measure_refiner_help([])
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.measure_refiner_help(None)


def test_t3_26_missing_file_fail_closed(tmp_path):
    """A path that is not on disk is NOT MEASURED, not score 0."""
    pairs = _pair_files(tmp_path, n=1)
    os.remove(pairs[0]["refined"])
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.measure_refiner_help(
            pairs, score_fn=lambda path, label: 0.5)


def test_t3_26_missing_score_fail_closed(tmp_path):
    """A score_fn that returns None is NOT MEASURED, never 0.0."""
    pairs = _pair_files(tmp_path, n=1)
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.measure_refiner_help(
            pairs, score_fn=lambda path, label: None)
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.measure_refiner_help(pairs)


def test_t3_26_unlabelled_pair_fail_closed(tmp_path):
    """A pair with no label is not a labelled set."""
    pairs = _pair_files(tmp_path, n=1)
    pairs[0]["label"] = ""
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.measure_refiner_help(
            pairs, score_fn=lambda path, label: 0.5)


def test_t3_26_opportunistic_catalogue_is_not_the_measurement(tmp_path):
    """The catalogue tag is why T3-26 exists. It must not answer helps."""
    assert models.CATALOG["wan22_i2v_low"]["proven"] == "opportunistic"
    pairs = _pair_files(tmp_path)
    report = qc.measure_refiner_help(
        pairs, score_fn=lambda path, label: 0.5)
    assert report["helps"] is False
    assert report.get("proven") == "does_not_help"


def test_t3_26_recorded_finding_says_not_helping(tmp_path):
    """The persisted finding is the one a human reads. Detail names it."""
    pairs = _pair_files(tmp_path)
    report, found = qc_service.record_refiner_help(
        pairs, score_fn=lambda path, label: 0.5)
    assert report["helps"] is False
    assert "not helping" in found["detail"].lower(), found
    row = db.one(
        "SELECT * FROM findings WHERE check_name=?", qc.REFINER_HELP_CHECK)
    assert row, "T3-26 finding was not recorded"
    assert "not helping" in (row["detail"] or "").lower(), dict(row)
    assert row["verdict"] != qc.PASS
