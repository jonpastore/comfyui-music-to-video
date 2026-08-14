"""TDD for docs/TRD-3 T3-18 / T3-6 / T3-19: approve() is the human sign-off.

The route in app.api_qc_approve calls qc_service.approve and decides nothing
else (T6-A10). These tests call that same function -- not a helper it wraps,
and not the HTTP layer, which is just a 501-or-forward.
"""
import json
import os
import time

import db
import qc_service


def _new_path(tag):
    return os.path.join(db.DATA, f"qc_approve_{tag}_{time.time_ns()}.mp4")


def _jobs_for(fid):
    out = []
    for row in db.q("SELECT * FROM jobs ORDER BY id"):
        try:
            args = json.loads(row["args_json"] or "{}")
        except ValueError:
            continue
        if args.get("finding_id") == fid:
            out.append((row, args))
    return out


def test_t3_18_qc_enqueues_nothing_until_approve():
    """Same broken artefact: QC writes findings and zero jobs; approve()
    on one of them enqueues exactly one repair."""
    path = _new_path("missing")
    before = {r["id"] for r in db.q("SELECT id FROM jobs")}

    found = qc_service.run_artefact(path, "clip")
    assert found and all(f["verdict"] != "pass" for f in found), found
    assert {r["id"] for r in db.q("SELECT id FROM jobs")} == before, \
        "QC enqueued a job on its own -- it must never auto-heal"

    row = db.one("SELECT * FROM findings WHERE path=? AND verdict != 'pass'", path)
    assert row, "a failing check did not reach the findings table"

    qc_service.approve(row["id"])

    fresh = [r for r in db.q("SELECT * FROM jobs") if r["id"] not in before]
    assert len(fresh) == 1, fresh
    assert len(_jobs_for(row["id"])) == 1
    assert qc_service.get(row["id"])["status"] == qc_service.APPROVED


def test_t3_6_repair_path_is_a_new_candidate():
    """A repair names a dest that is not the artefact it is repairing."""
    path = _new_path("overwrite")
    qc_service.run_artefact(path, "clip")
    row = db.one("SELECT * FROM findings WHERE path=?", path)
    qc_service.approve(row["id"])

    _, args = _jobs_for(row["id"])[-1]
    assert args["path"] == path
    assert args["repair_path"], args
    assert args["repair_path"] != path, \
        "a repair must write a new candidate, never overwrite"
    landed = qc_service.get(row["id"])["repair_path"]
    assert landed in (None, "") or landed != path


def test_t3_19_two_remedy_texts_are_two_jobs():
    """The edited remedy is what is queued -- two wordings, two jobs."""
    path = _new_path("remedy")
    qc_service.record([{
        "path": path, "kind": "clip", "tier": 1, "check": "duration",
        "verdict": "reject", "measured": "4.8", "expected": "30.0",
        "unit": "s", "detail": "short render", "remedy": "first wording",
    }])
    fid = db.one("SELECT id FROM findings WHERE path=?", path)["id"]

    qc_service.set_remedy(fid, "re-render clip at 505 frames")
    qc_service.approve(fid)
    qc_service.set_remedy(fid, "upscale the existing clip instead")
    qc_service.approve(fid)

    jobs_for = _jobs_for(fid)
    assert len(jobs_for) == 2, jobs_for
    remedies = [args["remedy"] for _, args in jobs_for]
    assert remedies == [
        "re-render clip at 505 frames",
        "upscale the existing clip instead",
    ], remedies
