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


def _finding_with_file(tag, payload=b"broken-clip-bytes"):
    """A real artefact on disk plus one reject, so h_repair has something
    to write beside. approve() only names the dest; this is the half that
    has to produce it."""
    src = _new_path(tag)
    with open(src, "wb") as f:
        f.write(payload)
    qc_service.record([{
        "path": src, "kind": "clip", "tier": 1, "check": "duration",
        "verdict": "reject", "measured": "4.8", "expected": "30.0",
        "unit": "s", "detail": "short render", "remedy": "re-render",
    }])
    fid = db.one("SELECT id FROM findings WHERE path=?", src)["id"]
    qc_service.approve(fid)
    _, args = _jobs_for(fid)[-1]
    return fid, src, args


def test_t3_6_h_repair_writes_a_new_candidate():
    """T3-6 positive half: after h_repair runs, dest exists, dest != src,
    the original is still there, and finding.repair_path is the dest.

    Naming a dest on the job is not producing one. The stub returned
    metadata and wrote nothing."""
    fid, src, args = _finding_with_file("repair_src")
    dest = args["repair_path"]
    assert dest and dest != src
    assert not os.path.isfile(dest)

    qc_service.h_repair(args, lambda m: None)

    assert os.path.isfile(src), "repair deleted or overwrote the original"
    assert os.path.isfile(dest), (
        "h_repair wrote no new file -- GPU work is still missing")
    assert not os.path.samefile(src, dest)
    with open(src, "rb") as f:
        original = f.read()
    assert original == b"broken-clip-bytes", "repair mutated the source"
    row = qc_service.get(fid)
    assert row["repair_path"] == dest
    assert row["repair_path"] != src
    assert row["status"] == qc_service.REPAIRED
    landed = db.one("SELECT * FROM artefacts WHERE path=?", dest)
    assert landed and landed["status"] == "landed", landed


def test_t3_6_h_repair_refuses_overwrite():
    """T3-6: dest equal to src is refused before anything is written."""
    fid, src, args = _finding_with_file("overwrite_src")
    args = dict(args)
    args["repair_path"] = src
    try:
        qc_service.h_repair(args, lambda m: None)
    except ValueError as e:
        assert "overwrite" in str(e).lower() or "new candidate" in str(e).lower(), e
    else:
        raise AssertionError("h_repair accepted dest == src")
    assert os.path.isfile(src)
    assert qc_service.get(fid)["repair_path"] in (None, "")


def test_t3_h_repair_fails_when_no_file_written(monkeypatch):
    """A writer that produces nothing must not flip the finding to repaired.
    The old stub returned metadata and claimed success."""
    fid, src, args = _finding_with_file("no_write")
    dest = args["repair_path"]
    monkeypatch.setattr(qc_service, "produce_repair",
                        lambda *a, **k: dest)
    try:
        qc_service.h_repair(args, lambda m: None)
    except RuntimeError as e:
        assert "no new file" in str(e).lower() or "gpu" in str(e).lower(), e
    else:
        raise AssertionError("h_repair succeeded without writing dest")
    assert not os.path.isfile(dest)
    assert os.path.isfile(src)
    row = qc_service.get(fid)
    assert row["repair_path"] in (None, "")
    assert row["status"] != qc_service.REPAIRED
