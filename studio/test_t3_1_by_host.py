"""TDD for docs/TRD-3 T3-1: per-box QC report groups by host.

NULL host is an explicit unattributed bucket with a count. A report
that only ever emits unattributed stays green without grouping.
Tests call qc_service.by_host -- the function the route forwards to
(T6-A10), not a helper it wraps.
"""
import os
import tempfile

import db
import jobs
import qc_service


def _isolate():
    data = tempfile.mkdtemp(prefix="t31_")
    was = (db.DATA, db.DB_PATH, jobs.LOGS)
    db.DATA = data
    db.DB_PATH = os.path.join(data, "t.db")
    db._local.__dict__.clear()
    jobs.LOGS = os.path.join(data, "logs")
    return data, was


def _restore(was):
    db.DATA, db.DB_PATH, jobs.LOGS = was
    db._local.__dict__.clear()


def _land(data, name, host, backend=None):
    path = os.path.join(data, name)
    with open(path, "wb") as f:
        f.write(b"x")
    return jobs.land(path, host=host, backend=backend)


def _counts(report):
    return {g["host"]: g["n"] for g in report}


def test_t3_1_report_groups_two_hosts_with_counts():
    """Positive half: two hosts are two groups with the planted counts.
    A crippled report that only ever emits unattributed fails here."""
    data, was = _isolate()
    try:
        _land(data, "c1.png", "cerberus", backend="1")
        _land(data, "c2.png", "cerberus", backend="1")
        _land(data, "c3.png", "cerberus", backend="9")
        _land(data, "p1.png", "peaches", backend="1")
        _land(data, "p2.png", "peaches", backend="2")

        report = qc_service.by_host()
        counts = _counts(report)
        assert counts.get("cerberus") == 3, report
        assert counts.get("peaches") == 2, report
        named = {g["host"] for g in report if g["n"] and g["host"] != "unattributed"}
        assert named == {"cerberus", "peaches"}, report
    finally:
        _restore(was)


def test_t3_1_null_host_is_unattributed_bucket():
    """NULL host artefacts appear in an explicit unattributed bucket.
    Silently dropping them would make the fleet look cleaner."""
    data, was = _isolate()
    try:
        _land(data, "c1.png", "cerberus")
        _land(data, "u1.png", None)
        _land(data, "u2.png", None)

        report = qc_service.by_host()
        counts = _counts(report)
        assert counts.get("cerberus") == 1, report
        assert counts.get("unattributed") == 2, report
        bucket = [g for g in report if g["host"] == "unattributed"]
        assert len(bucket) == 1 and bucket[0]["n"] == 2, report
    finally:
        _restore(was)
