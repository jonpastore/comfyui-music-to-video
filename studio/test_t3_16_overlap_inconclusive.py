"""T3-16: overlapping distributions report inconclusive and build no gate.

docs/TRD-3 T3-16: if the good/bad ranges overlap, the report says
inconclusive and the identity gate is not built. A threshold on that
report is the failure this criterion exists to prevent. A function that
always says inconclusive (even when the ranges do not touch) must go
red; so must one that ships a gate or a threshold anyway.
"""
import os

from PIL import Image

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
    for seed in BAD_SEEDS + GOOD_SEEDS:
        for st in STEPS:
            _png(root / f"st{st:02d}_s{seed}_00001_.png")
    return str(root)


def _by_label(root):
    good, bad = [], []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if any(f"_s{s}_" in name for s in GOOD_SEEDS):
            good.append(path)
        else:
            bad.append(path)
    return good, bad


def _overlapping_assigned(root):
    good, bad = _by_label(root)
    assigned = {}
    for i, path in enumerate(sorted(good)):
        assigned[path] = 0.40 + 0.06 * i
    for i, path in enumerate(sorted(bad)):
        assigned[path] = 0.50 + 0.025 * i
    return assigned


def _separated_assigned(root):
    good, bad = _by_label(root)
    assigned = {}
    for i, path in enumerate(sorted(good)):
        assigned[path] = 0.80 + 0.02 * i
    for i, path in enumerate(sorted(bad)):
        assigned[path] = 0.10 + 0.01 * i
    return assigned


def test_t3_16_overlapping_report_is_inconclusive_and_builds_no_gate(tmp_path):
    """The overlapping fixture is the one that goes red if the word is
    missing, a threshold is invented, or a gate is installed."""
    root = _sweep(tmp_path)
    assigned = _overlapping_assigned(root)
    measured = qc.score_zimage_sweep(root, score_fn=lambda p, label: assigned[p])
    assert measured["overlap"] > 0, measured

    report = qc_service.identity_calibration_report(measured)
    assert report["verdict"] == "inconclusive", report
    assert report["threshold"] is None, report
    assert report["gate"] is False, report

    gate = qc_service.build_identity_gate(measured)
    assert gate["built"] is False, gate
    assert gate["verdict"] == "inconclusive", gate
    assert gate["threshold"] is None, gate


def test_t3_16_overlapping_stored_row_does_not_earn_a_gate(tmp_path):
    """The persisted T3-13 row is the shared entry: overlap still decides."""
    root = _sweep(tmp_path)
    assigned = _overlapping_assigned(root)
    row = qc_service.run_zimage_calibration(
        root, score_fn=lambda p, label: assigned[p])
    assert row["overlap"] > 0, dict(row)
    assert row["threshold"] is None, dict(row)

    gate = qc_service.build_identity_gate(row)
    assert gate["built"] is False, gate
    assert gate["verdict"] == "inconclusive", gate
    assert gate["threshold"] is None, gate


def test_t3_16_threshold_on_overlap_is_refused():
    """Reporting a threshold that splits noise is the T3-16 failure."""
    try:
        qc_service.build_identity_gate({
            "overlap": 0.2,
            "separation": 0.01,
            "threshold": 0.5,
            "n_good": 6,
            "n_bad": 12,
        })
    except ValueError as e:
        assert "inconclusive" in str(e).lower() or "overlap" in str(e).lower(), e
    else:
        raise AssertionError("a threshold was accepted on overlapping distributions")


def test_t3_16_separated_report_is_not_inconclusive(tmp_path):
    """Always saying inconclusive stays green on overlap. This fixture
    is the one that goes red."""
    root = _sweep(tmp_path)
    assigned = _separated_assigned(root)
    measured = qc.score_zimage_sweep(root, score_fn=lambda p, label: assigned[p])
    assert measured["overlap"] == 0, measured

    report = qc_service.identity_calibration_report(measured)
    assert report["verdict"] != "inconclusive", report
    assert report["verdict"] == "separated", report

    gate = qc_service.build_identity_gate(measured)
    assert gate["verdict"] != "inconclusive", gate
    assert gate["built"] is False, gate
    assert gate["threshold"] is None, gate


def test_t3_16_set_threshold_refuses_overlap():
    """T3-16 rides on T3-14: the setter itself will not store a split of noise."""
    import tempfile
    import db

    data = tempfile.mkdtemp(prefix="t316_")
    was = (db.DATA, db.DB_PATH)
    db.DATA = data
    db.DB_PATH = os.path.join(data, "t.db")
    db._local.__dict__.clear()
    try:
        qc_service.record_calibration({
            "metric": qc.IDENTITY_METRIC,
            "dataset": "zimage_sweep",
            "n_good": 6, "n_bad": 12,
            "overlap": 0.2, "separation": 0.01,
            "scores": [{"path": "a.png", "label": "good", "score": 0.5,
                        "seed": 29364654}],
        })
        try:
            qc_service.set_threshold(0.5)
        except ValueError as e:
            msg = str(e).lower()
            assert "inconclusive" in msg or "overlap" in msg, e
        else:
            raise AssertionError("set_threshold stored a number on overlapping ranges")
        landed = qc_service.latest_calibration("zimage_sweep")
        assert landed["threshold"] is None, dict(landed)
    finally:
        db.DATA, db.DB_PATH = was
        db._local.__dict__.clear()
