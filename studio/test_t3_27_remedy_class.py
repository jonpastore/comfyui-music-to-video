"""TDD for docs/TRD-3 T3-27: every check names a remedy class.

The class is ACTIONABLE where one exists — approve() puts it on the
job and the actuator pick uses it, not the edited remedy text. A
check with no remedy says so and approve refuses, rather than
offering a button that does nothing.

Presence of a field is the one-sided half. These tests are the
positive half.
"""
import json
import os
import time

import db
import qc
import qc_service


def _new_path(tag):
    return os.path.join(db.DATA, f"t327_{tag}_{time.time_ns()}.bin")


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


def test_t3_27_every_check_names_a_remedy_class():
    """Every named check carries a class. An unknown check raises
    rather than emitting a finding a reviewer cannot act on."""
    assert qc.CHECK_REMEDY_CLASS, "no check declared a remedy class"
    for check, cls in qc.CHECK_REMEDY_CLASS.items():
        f = qc.finding("/x", "clip", check, qc.PASS, "ok")
        assert f["remedy_class"] == cls, (check, f)
        assert f["remedy_class"], check
    try:
        qc.finding("/x", "clip", "brand_new_check", qc.FLAG, "x")
    except ValueError as e:
        assert "remedy class" in str(e).lower(), e
    else:
        raise AssertionError("a check with no remedy class was accepted")


def test_t3_27_run_findings_all_name_a_class():
    """qc.run is the measurement surface (T3-30). Every finding it
    returns names a class, including the opens-reject on a missing
    file."""
    for kind in ("clip", "image", "audio"):
        found = qc.run(f"/no/such/{kind}.bin", kind)
        assert found, kind
        assert all(f.get("remedy_class") for f in found), found


def test_t3_27_set_duration_says_no_remedy():
    """duration_matches_prediction is a model/graph bug, never a
    re-render. The class is none and the text says so."""
    f = qc.finding(
        "/s.mp4", "set", "duration_matches_prediction", qc.REJECT,
        "rendered 10s against a predicted 12s", 10.0, 12.0, "s")
    assert f["remedy_class"] == qc.REMEDY_NONE
    assert not qc.is_actionable(f["remedy_class"])
    text = (f["remedy"] or "").lower()
    assert "no remedy" in text or "not a re-render" in text, f


def test_t3_27_approve_uses_the_class_not_the_remedy_text():
    """Positive half: the approve path uses the class. Same kind,
    opposite wording — the class is the one variable."""
    path = _new_path("edit")
    qc_service.record([{
        "path": path, "kind": "image", "tier": 1, "check": "identity_look",
        "verdict": "flag", "measured": "plate", "expected": "identity ref",
        "unit": None, "detail": "wrong identity",
        "remedy": "upscale pass",
        "remedy_class": qc.REMEDY_EDIT_TEXT,
    }])
    fid = db.one("SELECT id FROM findings WHERE path=?", path)["id"]
    qc_service.approve(fid)
    _, args = _jobs_for(fid)[-1]
    assert args["remedy_class"] == qc.REMEDY_EDIT_TEXT, args
    assert args["remedy"] == "upscale pass"
    actuator, _key = qc_service._repair_actuator_and_key(args)
    assert actuator == "fix_ref", (
        "approve sniffed the remedy text instead of using the class: "
        f"{actuator} from {args}")

    path2 = _new_path("upscale")
    qc_service.record([{
        "path": path2, "kind": "image", "tier": 1, "check": "not_uniform",
        "verdict": "reject", "measured": "0.1", "expected": "1.0",
        "unit": "levels", "detail": "flat",
        "remedy": "condition the sheet on the chosen identity ref",
        "remedy_class": qc.REMEDY_UPSCALE,
    }])
    fid2 = db.one("SELECT id FROM findings WHERE path=?", path2)["id"]
    qc_service.approve(fid2)
    _, args2 = _jobs_for(fid2)[-1]
    assert args2["remedy_class"] == qc.REMEDY_UPSCALE, args2
    actuator2, _key2 = qc_service._repair_actuator_and_key(args2)
    assert actuator2 == "gen_postproc", (
        "approve sniffed the remedy text instead of using the class: "
        f"{actuator2} from {args2}")


def test_t3_27_no_remedy_refuses_approve():
    """A check that names no remedy cannot be approved — that is the
    button that would do nothing. The queue says so."""
    path = _new_path("none")
    qc_service.record([{
        "path": path, "kind": "set", "tier": 1,
        "check": "duration_matches_prediction",
        "verdict": "reject", "measured": "10.0", "expected": "12.0",
        "unit": "s", "detail": "model/graph divergence",
        "remedy": "this check has no remedy — it cannot be approved",
        "remedy_class": qc.REMEDY_NONE,
    }])
    fid = db.one("SELECT id FROM findings WHERE path=?", path)["id"]
    row = qc_service.get(fid)
    assert row["remedy_class"] == qc.REMEDY_NONE
    assert row["actionable"] is False
    queued = [r for r in qc_service.queue() if r["id"] == fid]
    assert queued and queued[0]["actionable"] is False, queued
    try:
        qc_service.approve(fid)
    except ValueError as e:
        assert "no remedy" in str(e).lower(), e
    else:
        raise AssertionError("approve offered a button that does nothing")
    assert not _jobs_for(fid)
