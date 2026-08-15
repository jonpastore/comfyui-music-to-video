"""T3-17-ui: identity-drift scores visible on the QC surface.

docs/TRD-3 T3-17 scores each artefact (compliance, variation, n) as a
tier-2 measurement with no gate. This slice is the operator surface:
GET /qc must show those three numbers for a recorded identity_drift
row. A queue that hides PASS (so the score never appears), a finding
row that only has measured/expected/unit, or a template that omits
variation and n, must go red.
"""
import os
import re

from PIL import Image
from fastapi.testclient import TestClient

import app as appmod
import db
import jobs
import qc
import qc_service


BG = (210, 180, 140)
BLACK = (15, 12, 18)
HUMAN = (210, 170, 150)
SIZE = 32


def _paint(path, colour, standing=True):
    img = Image.new("RGB", (SIZE, SIZE), BG)
    px = img.load()
    if standing:
        cols, rows = range(8, 15), range(4, 28)
    else:
        cols, rows = range(4, 28), range(18, 26)
    for y in rows:
        for x in cols:
            px[x, y] = colour
    img.save(path)
    return str(path)


def _trio(tmp_path):
    anchor = _paint(tmp_path / "anchor.png", BLACK, standing=True)
    her = _paint(tmp_path / "her.png", BLACK, standing=False)
    human = _paint(tmp_path / "human.png", HUMAN, standing=True)
    return anchor, her, human


def test_t3_17_ui_identity_drift_scores_on_qc_surface(tmp_path):
    """Planted compliance / variation / n reach GET /qc unmodified."""
    anchor, _, human = _trio(tmp_path)
    report = qc_service.score_identity_artefact(human, anchor=anchor)
    assert report["tier"] == 2
    assert "compliance" in report and "variation" in report and "n" in report

    row = db.one(
        "SELECT * FROM findings WHERE path=? AND check_name=?",
        jobs.canonical_path(human), qc.IDENTITY_DRIFT)
    assert row, "identity_drift was not recorded"
    assert row["verdict"] == qc.PASS, dict(row)
    fid = row["id"]

    # Default queue used to drop PASS — the score would never reach the page.
    queued = qc_service.queue()
    assert any(r["id"] == fid for r in queued), (
        "identity_drift PASS is missing from the QC queue", queued)

    with TestClient(appmod.app) as client:
        page = client.get("/qc")
        assert page.status_code == 200, page.text
        html = page.text

    assert f'data-finding="{fid}"' in html
    assert f'data-check="{qc.IDENTITY_DRIFT}"' in html or "identity_drift" in html

    m = re.search(
        rf'<article class="finding-row[^"]*" id="finding-{fid}".*?</article>',
        html, re.S)
    assert m, html
    block = m.group(0)

    # Structured attributes — not only buried in free-text detail.
    c_attr = re.search(r'data-compliance="([^"]*)"', block)
    v_attr = re.search(r'data-variation="([^"]*)"', block)
    n_attr = re.search(r'data-n="([^"]*)"', block)
    assert c_attr, block
    assert v_attr, block
    assert n_attr, block

    assert abs(float(c_attr.group(1)) - float(report["compliance"])) < 1e-6, (
        c_attr.group(1), report["compliance"])
    assert abs(float(v_attr.group(1)) - float(report["variation"])) < 1e-6, (
        v_attr.group(1), report["variation"])
    assert int(n_attr.group(1)) == int(report["n"]), (n_attr.group(1), report["n"])

    # Visible labels so the operator can read the three numbers.
    assert "compliance" in block.lower()
    assert "variation" in block.lower()
    assert re.search(r"\bn\b", block) or 'data-field="n"' in block, block
    assert c_attr.group(1) in block
    assert v_attr.group(1) in block
    assert n_attr.group(1) in block


def test_t3_17_ui_enrichment_exposes_scores_on_finding_row(tmp_path):
    """Service row carries compliance / variation / n for the template."""
    anchor, her, _ = _trio(tmp_path)
    report = qc_service.score_identity_artefact(her, anchor=anchor)
    row = db.one(
        "SELECT id FROM findings WHERE path=? AND check_name=?",
        jobs.canonical_path(her), qc.IDENTITY_DRIFT)
    assert row
    got = qc_service.get(row["id"])
    assert got["check_name"] == qc.IDENTITY_DRIFT
    assert "compliance" in got and "variation" in got and "n" in got
    assert abs(float(got["compliance"]) - float(report["compliance"])) < 1e-6
    assert abs(float(got["variation"]) - float(report["variation"])) < 1e-6
    assert int(got["n"]) == int(report["n"])
