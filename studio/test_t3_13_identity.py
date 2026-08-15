"""T3-13: identity score over zimage_sweep, report only.

docs/TRD-3 T3-13: run the score over the 12 known-bad and 6 known-good
images, and report overlap, separation, and every individual file. No
threshold, no gate, no UI. Deleting the report, skipping a file, or
shipping a threshold must go red.

The fixture uses the recorded seed names. Scores are injected so the
overlap/separation arithmetic is the thing under test, not a GPU
extractor.
"""
import json
import os

import pytest
from PIL import Image

import db
import qc
import qc_service


STEPS = (4, 6, 8, 10, 12, 16)
BAD_SEEDS = (29364380, 29364517)
GOOD_SEEDS = (29364654,)


def _png(path):
    Image.new("RGB", (8, 8), (20, 20, 20)).save(path)


def _sweep(tmp_path):
    root = tmp_path / "zimage_sweep"
    root.mkdir()
    paths = []
    for seed in BAD_SEEDS + GOOD_SEEDS:
        for st in STEPS:
            p = root / f"st{st:02d}_s{seed}_00001_.png"
            _png(p)
            paths.append(str(p))
    return str(root), paths


def _by_label(root):
    files = sorted(os.listdir(root))
    good, bad = [], []
    for name in files:
        path = os.path.join(root, name)
        if any(f"_s{s}_" in name for s in GOOD_SEEDS):
            good.append(path)
        else:
            bad.append(path)
    return good, bad


def test_t3_13_separated_sweep_reports_zero_overlap(tmp_path):
    """12 bad + 6 good, ranges do not touch: overlap is 0, no threshold."""
    root, _ = _sweep(tmp_path)
    good, bad = _by_label(root)
    assigned = {}
    for i, path in enumerate(sorted(good)):
        assigned[path] = 0.80 + 0.02 * i
    for i, path in enumerate(sorted(bad)):
        assigned[path] = 0.10 + 0.01 * i

    report = qc.score_zimage_sweep(root, score_fn=lambda p, label: assigned[p])

    assert report["n_good"] == 6, report
    assert report["n_bad"] == 12, report
    assert report["threshold"] is None, report
    assert len(report["scores"]) == 18, report["scores"]
    names = {os.path.basename(row["path"]) for row in report["scores"]}
    assert names == {os.path.basename(p) for p in assigned}, names
    assert {row["label"] for row in report["scores"] if row["label"] == "good"}
    assert sum(1 for row in report["scores"] if row["label"] == "good") == 6
    assert sum(1 for row in report["scores"] if row["label"] == "bad") == 12
    for row in report["scores"]:
        assert row["score"] == assigned[row["path"]], row
        assert row["seed"] in BAD_SEEDS + GOOD_SEEDS, row

    assert report["overlap"] == 0
    assert report["separation"] == pytest.approx(0.695)


def test_t3_13_overlapping_sweep_reports_the_intersection(tmp_path):
    """If overlap is hardcoded to 0, this fixture is the one that goes red."""
    root, _ = _sweep(tmp_path)
    good, bad = _by_label(root)
    assigned = {}
    for i, path in enumerate(sorted(good)):
        assigned[path] = 0.40 + 0.06 * i
    for i, path in enumerate(sorted(bad)):
        assigned[path] = 0.50 + 0.025 * i

    report = qc.score_zimage_sweep(root, score_fn=lambda p, label: assigned[p])

    assert report["n_good"] == 6
    assert report["n_bad"] == 12
    assert report["threshold"] is None, report
    assert report["overlap"] == pytest.approx(0.20 / 0.375)
    goods = [assigned[p] for p in good]
    bads = [assigned[p] for p in bad]
    expected_sep = (sum(goods) / 6) - (sum(bads) / 12)
    assert report["separation"] == pytest.approx(expected_sep)


def test_t3_13_missing_file_raises_instead_of_a_partial_report(tmp_path):
    root, paths = _sweep(tmp_path)
    os.remove(paths[0])
    try:
        qc.score_zimage_sweep(root, score_fn=lambda p, label: 0.5)
    except RuntimeError as e:
        assert "18" in str(e) or "12" in str(e) or "6" in str(e), e
    else:
        raise AssertionError("a 17-file sweep produced a report")


def test_t3_13_unknown_seed_raises(tmp_path):
    root, _ = _sweep(tmp_path)
    stray = os.path.join(root, "st04_s99999999_00001_.png")
    _png(stray)
    try:
        qc.score_zimage_sweep(root, score_fn=lambda p, label: 0.5)
    except RuntimeError as e:
        assert "99999999" in str(e), e
    else:
        raise AssertionError("an unknown seed was scored silently")


def test_t3_13_stores_calibration_without_a_threshold(tmp_path):
    """The deliverable is the row. A threshold on it is the T3-13 failure."""
    root, _ = _sweep(tmp_path)
    good, bad = _by_label(root)
    assigned = {}
    for i, path in enumerate(sorted(good)):
        assigned[path] = 0.80 + 0.02 * i
    for i, path in enumerate(sorted(bad)):
        assigned[path] = 0.10 + 0.01 * i

    row = qc_service.run_zimage_calibration(
        root, score_fn=lambda p, label: assigned[p])
    assert row["dataset"] == "zimage_sweep"
    assert row["n_good"] == 6
    assert row["n_bad"] == 12
    assert row["threshold"] is None, dict(row)
    assert row["overlap"] == 0
    assert row["separation"] == pytest.approx(0.695)
    scores = json.loads(row["scores_json"])
    assert len(scores) == 18, scores
    landed = qc_service.latest_calibration("zimage_sweep")
    assert landed["id"] == row["id"]
    assert landed["threshold"] is None


def test_t3_13_refuses_to_store_a_threshold():
    try:
        qc_service.record_calibration({
            "metric": "identity_cosine_v1",
            "dataset": "zimage_sweep",
            "n_good": 6, "n_bad": 12,
            "overlap": 0.0, "separation": 0.5,
            "scores": [{"path": "a.png", "label": "good", "score": 0.9,
                        "seed": 29364654}],
            "threshold": 0.5,
        })
    except ValueError as e:
        assert "threshold" in str(e).lower(), e
    else:
        raise AssertionError("a threshold was stored on a T3-13 row")


def test_t3_13_identity_embed_scores_a_file_against_itself(tmp_path):
    """The score exists as a function, not only as an injected callback."""
    path = tmp_path / "self.png"
    _png(path)
    vec = qc.identity_embed(str(path))
    assert len(vec) >= 3, vec
    assert qc.identity_score(str(path), vec) == pytest.approx(1.0)
    assert db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='calibrations'")
