"""UIUX §8 / T6-A2-nav: one list drives the topbar and GET /api/nav.

docs/UIUX-DEFINITION-AND-STYLE-GUIDE.md §8: the nav matches the agreed order,
asserted against one list that both base.html and the API read.

HTML <nav> hrefs/labels == JSON links. A distinctive probe monkeypatched into
nav_service.LINKS appears in both surfaces. Mutation: hardcode the old eight
links in the template → probe missing → red.
"""
import os
import re

from fastapi.testclient import TestClient

import app as appmod
import nav_service

# Distinctive so a hardcoded old-eight template cannot pass by coincidence.
_PROBE_HREF = "/__uiux_nav_probe_x7k__"
_PROBE_LABEL = "UiuxNavProbeX7k"


def _nav_block(html):
    m = re.search(r"<nav\b[^>]*>(.*?)</nav>", html, re.S | re.I)
    assert m, f"no <nav> in page: {html[:600]}"
    return m.group(1)


def _nav_anchors(nav_html):
    """Ordered top-level (href, label) pairs. Submenu links sit in .nav-sub."""
    stripped = re.sub(r'<span class="nav-sub">.*?</span>', "", nav_html, flags=re.S)
    return [
        (m.group(1), m.group(2).strip())
        for m in re.finditer(
            r'<a\b[^>]*\bhref="([^"]*)"[^>]*>(.*?)</a>',
            stripped, re.S | re.I)
    ]


def test_uiux_nav_html_and_json_share_one_list(monkeypatch):
    """Probe in LINKS appears in GET / <nav> and GET /api/nav; lists match.

    Hardcoding the old eight <a> tags in base.html drops the probe → red.
    """
    probe = {"href": _PROBE_HREF, "label": _PROBE_LABEL}
    assert probe not in nav_service.LINKS
    extended = list(nav_service.LINKS) + [probe]
    monkeypatch.setattr(nav_service, "LINKS", extended)
    # app imports the same module object; keep both names explicit.
    monkeypatch.setattr(appmod.nav_service, "LINKS", extended)

    with TestClient(appmod.app) as client:
        page = client.get("/")
        js = client.get("/api/nav")

    assert page.status_code == 200, page.text
    assert js.status_code == 200, js.text
    ctype = (js.headers.get("content-type") or "").split(";")[0].strip()
    assert ctype == "application/json", (
        f"/api/nav returned {ctype or 'no content-type'}, not JSON: "
        f"{js.text[:200]}")
    assert "<html" not in js.text.lower(), js.text[:200]
    body = js.json()
    assert "links" in body, body
    json_links = body["links"]
    assert isinstance(json_links, list), json_links

    nav_html = _nav_block(page.text)
    html_pairs = _nav_anchors(nav_html)
    json_pairs = [(x["href"], x["label"]) for x in json_links]

    assert html_pairs == json_pairs, (html_pairs, json_pairs)
    assert (_PROBE_HREF, _PROBE_LABEL) in html_pairs, (
        f"probe missing from HTML <nav> — template may hardcode links: "
        f"{html_pairs}")
    assert (_PROBE_HREF, _PROBE_LABEL) in json_pairs, (
        f"probe missing from /api/nav: {json_pairs}")

    # Baseline destinations stay in today's order before the probe.
    expected_base = [
        ("/", "Library"),
        ("/media", "Media"),
        ("/anchors", "Anchors"),
        ("/playlists", "Playlists"),
        ("/sets", "Sets"),
        ("/tiers", "Tiers"),
        ("/models", "Models"),
        ("/jobs", "Jobs"),
        ("/config", "Config"),
    ]
    assert html_pairs[:9] == expected_base, html_pairs[:9]
    assert "nav a.current" in open(
        os.path.join(os.path.dirname(__file__), "static", "style.css")).read()
    assert html_pairs[9] == (_PROBE_HREF, _PROBE_LABEL)
    assert 'class="nav-sub"' in nav_html
    assert 'href="/media?new=song"' in nav_html
    assert 'href="/media?new=image"' in nav_html
    assert 'aria-haspopup="true"' in nav_html
    assert 'aria-expanded="false"' in nav_html
    js = open(
        os.path.join(os.path.dirname(__file__), "static", "app.js")).read()
    assert "function initNavDrop" in js
    assert "initNavDrop()" in js
    assert "HOLD_MS = 2000" in js
    assert 'classList.contains("pinned")' in js
    assert "OPEN_MS = 300" in js
    assert "ArrowDown" in js
    assert "ArrowUp" in js
    assert "ArrowLeft" in js
    assert "ArrowRight" in js
    assert 'key === "Enter"' in js
    assert "subItems" in js
