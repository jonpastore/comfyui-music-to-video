"""T3-14: a threshold cannot be set without a stored T3-13 calibration.

docs/TRD-3 T3-14: attempting to set one with no calibration row is
refused, naming why. Paired positive: WITH a T3-13 row a threshold CAN
be set. Deleting the setter satisfies the refusal forever. T3-16 rides
with the setter: overlap does not earn a number.
"""
import os
import tempfile

import db
import qc
import qc_service


def _isolate():
    data = tempfile.mkdtemp(prefix="t314_")
    was = (db.DATA, db.DB_PATH)
    db.DATA = data
    db.DB_PATH = os.path.join(data, "t.db")
    db._local.__dict__.clear()
    return data, was


def _restore(was):
    db.DATA, db.DB_PATH = was
    db._local.__dict__.clear()


def _t313_row(dataset="zimage_sweep", overlap=0.0):
    return qc_service.record_calibration({
        "metric": qc.IDENTITY_METRIC,
        "dataset": dataset,
        "n_good": 6, "n_bad": 12,
        "overlap": overlap, "separation": 0.5,
        "scores": [{"path": "a.png", "label": "good", "score": 0.9,
                    "seed": 29364654}],
        "threshold": None,
    })


def test_t3_14_set_threshold_refused_without_calibration():
    """No T3-13 row: the setter refuses and names why."""
    data, was = _isolate()
    try:
        assert qc_service.latest_calibration("zimage_sweep") is None
        try:
            qc_service.set_threshold(0.5)
        except ValueError as e:
            msg = str(e).lower()
            assert "calibrat" in msg, e
            assert "t3-13" in msg, e
        else:
            raise AssertionError("a threshold was set with no calibration row")
        row = qc_service.latest_calibration("zimage_sweep")
        assert row is None or row["threshold"] is None, dict(row or {})
    finally:
        _restore(was)


def test_t3_14_set_threshold_with_stored_t3_13_calibration():
    """Positive half: WITH a T3-13 row a threshold CAN be set.
    Deleting set_threshold keeps the refusal green forever."""
    data, was = _isolate()
    try:
        stored = _t313_row()
        assert stored["threshold"] is None, dict(stored)
        landed = qc_service.set_threshold(0.42)
        assert landed["id"] == stored["id"], dict(landed)
        assert float(landed["threshold"]) == 0.42, dict(landed)
        again = qc_service.latest_calibration("zimage_sweep")
        assert again["id"] == stored["id"]
        assert float(again["threshold"]) == 0.42, dict(again)
    finally:
        _restore(was)


def test_t3_14_other_dataset_is_not_a_t3_13_calibration():
    """A calibrations row that is not the T3-13 report does not unlock it."""
    data, was = _isolate()
    try:
        _t313_row(dataset="not_zimage_sweep")
        try:
            qc_service.set_threshold(0.5)
        except ValueError as e:
            assert "calibrat" in str(e).lower(), e
            assert "t3-13" in str(e).lower(), e
        else:
            raise AssertionError("a non-T3-13 row unlocked the threshold")
        assert qc_service.latest_calibration("zimage_sweep") is None
    finally:
        _restore(was)
