"""T10-13: classify_sheet output attaches to a finding, never a pass/fail.

docs/TRD-10 T10-13. TRD-3 §10 owns the prohibition — a VLM may write a
description attached to a finding; it may not be the verdict. The
one-sided failure is a check that stays green if classify_sheet is
never called. The positive half requires the call and the reason text
on a finding whose verdict is not derived from the flagged list.
"""
import json
import os
import tempfile
import time

from fastapi.testclient import TestClient

from conftest import classify_calls

import app as appmod
import db
import jobs
import qc
import qc_service
from test_app import _upload_song, wait_job


def test_t10_13_classify_sheet_is_called_and_text_attaches_to_a_finding():
    """Deleting classify_sheet keeps 'never a verdict' green.

    The call must happen and its reason must land on a finding.
    """
    n = len(classify_calls)
    sheet = os.path.join(db.DATA, f"t1013_called_{time.time_ns()}.jpg")
    open(sheet, "wb").close()
    verdict = appmod.vision.classify_sheet(sheet, note="T10-13")
    assert len(classify_calls) == n + 1, "classify_sheet was not called"
    assert any(
        (f.get("reason") == "two of her") for f in verdict.get("flagged") or []
    ), verdict
    qc_service.attach_sheet_review(sheet, verdict)
    row = db.one(
        "SELECT * FROM findings WHERE path=? AND check_name=?",
        jobs.canonical_path(sheet), qc.SHEET_REVIEW)
    assert row, "classify_sheet ran but no finding was recorded"
    assert "two of her" in (row["detail"] or ""), row["detail"]
    assert row["verdict"] == qc.PASS, row["verdict"]


def test_t10_13_flagged_output_is_not_a_fail_verdict():
    """The one variable is the flagged list. Both arms are PASS."""
    sheet_a = os.path.join(db.DATA, f"t1013_empty_{time.time_ns()}.jpg")
    sheet_b = os.path.join(db.DATA, f"t1013_flagged_{time.time_ns()}.jpg")
    open(sheet_a, "wb").close()
    open(sheet_b, "wb").close()
    empty = {"flagged": [], "cells_seen": 4, "backend": "local"}
    flagged = {"flagged": [{"clip": 1, "issue": "broken", "reason": "two of her"}],
               "cells_seen": 4, "backend": "local"}
    qa = qc_service.attach_sheet_review(sheet_a, empty)
    qb = qc_service.attach_sheet_review(sheet_b, flagged)
    assert qa["verdict"] == qc.PASS, qa
    assert qb["verdict"] == qc.PASS, qb
    assert qb["verdict"] not in (qc.FLAG, qc.REJECT)
    ra = db.one("SELECT * FROM findings WHERE path=?", jobs.canonical_path(sheet_a))
    rb = db.one("SELECT * FROM findings WHERE path=?", jobs.canonical_path(sheet_b))
    assert ra["verdict"] == qc.PASS and rb["verdict"] == qc.PASS
    assert "two of her" in (rb["detail"] or ""), rb["detail"]
    assert ra["verdict"] == rb["verdict"], "flagged list became the verdict"


def test_t10_13_classify_job_attaches_the_called_text():
    """The live surface: POST /classify calls classify_sheet and attaches."""
    from conftest import contact_sheet_calls
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-13 Review")
        sid = song["id"]
        d = tempfile.mkdtemp()
        for i in range(2):
            open(os.path.join(d, f"src{i}.png"), "w").close()
            db.run("""INSERT INTO refs (song_id, tier, clip_idx, path, seed, approved, created)
                      VALUES (?,'pg13',?,?,?,?,?)""",
                   sid, i, os.path.join(d, f"src{i}.png"), i, 1, time.time())
        n = len(classify_calls)
        r = client.post(f"/songs/{sid}/classify", data={"tier": "pg13"})
        assert r.status_code in (200, 303), r.text
        job = db.one(
            "SELECT * FROM jobs WHERE song_id=? AND kind='classify' ORDER BY id DESC",
            sid)
        row = wait_job(job["id"])
        assert row["status"] == "done", row
        assert len(classify_calls) > n, "h_classify never called classify_sheet"
        assert contact_sheet_calls, "no contact sheet was built"
        asset = db.one("SELECT * FROM assets WHERE song_id=? AND kind='review'", sid)
        assert asset, "review asset missing"
        sheet = asset["path"]
        found = db.one(
            "SELECT * FROM findings WHERE path=? AND check_name=?",
            jobs.canonical_path(sheet), qc.SHEET_REVIEW)
        assert found, "classify job wrote no finding for the sheet"
        assert "two of her" in (found["detail"] or ""), found["detail"]
        assert found["verdict"] == qc.PASS, found["verdict"]
        meta = json.loads(asset["meta_json"])
        assert meta["flagged"][0]["reason"] == "two of her"
