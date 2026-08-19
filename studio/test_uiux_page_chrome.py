"""Nav already names the page. A second h1 that repeats it is gone.

Unique titles (song name, New Image, Publishing) stay visible.
Page help sits on the far right of the first toolbar, not beside the title.

Mutation: put <h1>Library</h1> back on index.html → red.
Mutation: leave Anchors help on the h1, not in #anchor-scope → red.
"""
import os
import re

from fastapi.testclient import TestClient

import app as appmod

_TEMPL = os.path.join(os.path.dirname(appmod.__file__), "templates")


def _h1(html):
    m = re.search(r"<h1\b([^>]*)>(.*?)</h1>", html, re.S)
    assert m, html[:400]
    return m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()


def test_nav_pages_hide_the_duplicate_h1():
    with TestClient(appmod.app) as client:
        pages = {
            "/": "Library",
            "/anchors": "Anchors",
            "/playlists": "Playlists",
            "/sets": "Sets",
            "/jobs": "Jobs",
            "/models": "Models",
            "/tiers": "Content tiers",
            "/media": "Media",
        }
        for path, title in pages.items():
            html = client.get(path).text
            attrs, text = _h1(html)
            assert "visually-hidden" in attrs, (path, attrs, text)
            assert title.lower() in text.lower(), (path, text)


def test_unique_titles_stay_visible():
    with TestClient(appmod.app) as client:
        image = client.get("/media", params={"new": "image"}).text
        attrs, text = _h1(image)
        assert "visually-hidden" not in attrs
        assert text == "New Image"
        song = client.get("/media", params={"new": "song"}).text
        attrs, text = _h1(song)
        assert "visually-hidden" not in attrs
        assert text == "New Song"
        pub = client.get("/config").text
        attrs, text = _h1(pub)
        assert "visually-hidden" not in attrs
        assert "Publishing" in text


def test_anchors_help_sits_on_the_right_of_the_toolbar():
    src = open(os.path.join(_TEMPL, "anchors.html")).read()
    assert "page_title(\"Anchors\")" in src
    assert 'id="anchor-scope"' in src
    scope = src.split('id="anchor-scope"', 1)[1]
    assert "help_tip(\"Anchors\"" in scope
    assert "<h1>Anchors" not in src
    css = open(os.path.join(os.path.dirname(appmod.__file__), "static", "style.css")).read()
    assert ".anchor-scope > .help-tip" in css
    assert "margin-left: auto" in css
    macros = open(os.path.join(_TEMPL, "_macros.html")).read()
    assert "macro page_title" in macros


def test_anchors_retry_and_roster_badge_are_in_page():
    """No bare /jobs/.../retry form on Anchors; roster names the sticky tier.

    Mutation: bare method=post action=/jobs/{{ j.id }}/retry in anchors.html → red.
    Mutation: warn-tag is only '{{ miss.n }} missing' when page_tier is set → red.
    """
    src = open(os.path.join(_TEMPL, "anchors.html")).read()
    failed = src.split("failed-jobs", 1)[1].split("</details>", 1)[0]
    assert 'data-job-retry="/jobs/{{ j.id }}/retry"' in failed
    assert not re.search(
        r'<form\b[^>]*\bmethod="post"[^>]*\baction="/jobs/\{\{\s*j\.id\s*\}\}/retry"',
        failed)
    roster = src.split('id="album-pose-roster"', 1)[1]
    assert "page_tier | tiername }} needs" in roster or \
        "{{ page_tier | tiername }} needs" in roster
    group = open(os.path.join(_TEMPL, "_anchor_group.html")).read()
    assert 'class="clear-anchor' in group
    js = open(os.path.join(os.path.dirname(appmod.__file__), "static", "app.js")).read()
    assert "data-job-retry" in js
    assert ".clear-anchor" in js
    assert ".pose-keeper-form" in js
