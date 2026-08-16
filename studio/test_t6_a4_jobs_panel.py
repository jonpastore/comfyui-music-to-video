"""T6-A4 / jobs panel: elapsed is service-owned, not template-computed.

docs/TRD-6 §0.1: no template computes. Stub jobs_ctx with elapsed `12.7s`
(not int of a raw seconds fixture); the HTML page shows that string
unmodified. A template that does `%.0f` of 12.7 → `13s` goes red.

Distinctive numbers so two empty answers cannot pass.
"""
import re

from fastapi.testclient import TestClient

import app as appmod

_T6_A4_ELAPSED = "12.7s"
_T6_A4_DESC = "STUB-JOB-77"
# What "%.0f"|format(12.7)+"s" would print — must not appear.
_ROUNDED = "13s"


def test_t6_a4_jobs_panel_shows_stubbed_elapsed_unmodified(monkeypatch):
    """Stub jobs_ctx elapsed=12.7s; /jobs shows it. Rounded 13s is absent."""
    row = {
        "job": {
            "id": 77,
            "status": "running",
            "kind": "t6",
            "progress": "sheet 3/9",
            "error": None,
        },
        "desc": _T6_A4_DESC,
        "elapsed": _T6_A4_ELAPSED,
        "cancelable": True,
    }
    stub = {
        "jobs": [row],
        "active": row["job"],
        "refresh": "off",
        "refresh_secs": 0,
        "refresh_choices": appmod.JOBS_REFRESH_CHOICES,
        "comfy": None,
        "swarm": [],
        "render_backend": "comfy",
    }
    monkeypatch.setattr(appmod, "jobs_ctx", lambda refresh="auto": stub)

    with TestClient(appmod.app) as client:
        r = client.get("/jobs")
        r_partial = client.get("/jobs?partial=1")

    assert r.status_code == 200, r.text
    assert r_partial.status_code == 200, r_partial.text
    for html in (r.text, r_partial.text):
        assert _T6_A4_ELAPSED in html, html
        assert _T6_A4_DESC in html, html
        assert _ROUNDED not in html, html
        m = re.search(r'data-elapsed="([^"]*)"', html)
        assert m, f"missing data-elapsed on jobs panel: {html[:500]}"
        assert m.group(1) == _T6_A4_ELAPSED, m.group(1)
