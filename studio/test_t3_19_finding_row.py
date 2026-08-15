"""T3-19 finding-row UI: measured / expected / unit, editable remedy, approve.

docs/TRD-3 T3-19: the remedy is editable before approval, and the edited
text is what runs. A differential: approve the same finding twice with two
different remedy texts and confirm two different jobs were submitted —
not by checking that the form posted.

The service half is test_t3_19_two_remedy_texts_are_two_jobs. This is
the HTML atom the operator sees (UIUX finding-row; T3-4 numbers, T3-27
button only when actionable).
"""
import json
import os
import re
import time

import db
import qc_service
import app as appmod

from fastapi.testclient import TestClient


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


def _record(tag, *, check="duration", measured="4.8", expected="30.0",
            unit="s", remedy="re-render", kind="clip", verdict="reject"):
    path = os.path.join(db.DATA, f"t319_{tag}_{time.time_ns()}.mp4")
    qc_service.record([{
        "path": path, "kind": kind, "tier": 1, "check": check,
        "verdict": verdict, "measured": measured, "expected": expected,
        "unit": unit, "detail": f"{check} {measured} vs {expected} {unit}",
        "remedy": remedy,
    }])
    return db.one("SELECT id FROM findings WHERE path=?", path)["id"]


def test_t3_19_finding_row_shows_measured_expected_unit_and_editable_remedy():
    """The planted numbers reach the page unmodified (T3-4 / T6-A4)."""
    fid = _record(
        "row", measured="4.8125", expected="30.0000", unit="s",
        remedy="re-render clip at 505 frames")
    with TestClient(appmod.app) as client:
        page = client.get("/qc")
        assert page.status_code == 200, page.text
        html = page.text
        assert 'class="finding-row' in html or "finding-row" in html, html
        assert f'data-finding="{fid}"' in html
        assert 'data-measured="4.8125"' in html
        assert 'data-expected="30.0000"' in html
        assert 'data-unit="s"' in html
        assert "4.8125" in html
        assert "30.0000" in html
        assert ">s<" in html or 'data-unit="s"' in html
        assert "re-render clip at 505 frames" in html
        assert f'action="/qc/findings/{fid}/approve"' in html
        assert "<textarea" in html
        assert "Approve" in html


def test_t3_19_html_approve_submits_the_edited_text():
    """Two form approvals, two wordings, two jobs. Not that the form posted."""
    fid = _record("edit", remedy="first wording")
    with TestClient(appmod.app) as client:
        r1 = client.post(
            f"/qc/findings/{fid}/approve",
            data={"text": "re-render clip at 505 frames"},
            follow_redirects=False)
        assert r1.status_code in (200, 303), r1.text
        r2 = client.post(
            f"/qc/findings/{fid}/approve",
            data={"text": "upscale the existing clip instead"},
            follow_redirects=False)
        assert r2.status_code in (200, 303), r2.text

    jobs_for = _jobs_for(fid)
    assert len(jobs_for) == 2, jobs_for
    remedies = [args["remedy"] for _, args in jobs_for]
    assert remedies == [
        "re-render clip at 505 frames",
        "upscale the existing clip instead",
    ], remedies


def test_t3_19_non_actionable_row_has_no_approve_button():
    """T3-27 / UIUX: false actionable is why the button must not exist."""
    fid = _record(
        "none", check="duration_matches_prediction", kind="set",
        measured="10.0", expected="12.0", unit="s",
        remedy="this check has no remedy — it cannot be approved")
    row = qc_service.get(fid)
    assert row["actionable"] is False, row
    with TestClient(appmod.app) as client:
        html = client.get("/qc").text
        assert f'data-finding="{fid}"' in html
        assert 'data-measured="10.0"' in html
        assert 'data-expected="12.0"' in html
        assert 'data-unit="s"' in html
        assert f'action="/qc/findings/{fid}/approve"' not in html
        assert f'id="finding-{fid}"' in html
        m = re.search(
            rf'<article class="finding-row[^"]*" id="finding-{fid}".*?</article>',
            html, re.S)
        assert m, html
        assert "Approve" not in m.group(0), m.group(0)
