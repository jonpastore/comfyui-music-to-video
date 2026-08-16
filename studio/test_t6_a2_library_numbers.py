"""T6-A2-library: HTML page and JSON endpoint report the same library numbers.

docs/TRD-6 §0.1 / TRD-10: GET / and GET /songs HTML and GET /api/songs report
the same song_count from library_service.numbers. Two answers means two
implementations. GET /songs must be 200 (never 405). POST /songs upload stays.

Distinctive numbers so two empty answers cannot pass. song_count is
service-owned: a template that recomputes from len(songs) fails the
stub arm when the service returns a count that is not the list length.
"""
import re
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import library_service

_N_SONGS = 3
_STUB_SONG_COUNT = 99  # not _N_SONGS — named mutation for len()-recompute


def _attr(page, name):
    m = re.search(rf'id="library"[^>]*data-{name}="([^"]*)"', page)
    if not m:
        m = re.search(rf'data-{name}="([^"]*)"[^>]*id="library"', page)
    if not m:
        m = re.search(rf'data-{name}="([^"]*)"', page)
    assert m, f"missing data-{name} on library: {page[:500]}"
    return m.group(1)


def test_t6_a2_html_and_json_report_the_same_library_numbers(monkeypatch):
    """HTML and JSON agree on distinctive library numbers from one service.

    Real library: 3 songs. Stub arm: song_count forced to 99 so a template
    that counts rows goes red. GET /songs is 200, never 405.
    """
    assert _STUB_SONG_COUNT != _N_SONGS
    assert _N_SONGS and _STUB_SONG_COUNT

    stamp = time.time_ns()
    song_ids = []
    for i in range(_N_SONGS):
        sid = db.upsert_song(
            f"t6a2-lib-{stamp}-{i}", title=f"T6-A2 Library Track {i + 1}",
            album=f"T6-A2 Library Album {stamp}", duration=10.0 + i,
            lyrics="she leaves")
        song_ids.append(sid)
    assert len(song_ids) == _N_SONGS

    with TestClient(appmod.app) as client:
        real = library_service.numbers()
        # At least the three we planted (other tests may leave rows).
        assert real["song_count"] >= _N_SONGS, real

        stub = dict(real)
        stub["song_count"] = _STUB_SONG_COUNT

        def _stub_numbers():
            return stub

        monkeypatch.setattr(library_service, "numbers", _stub_numbers)
        monkeypatch.setattr(appmod.library_service, "numbers", _stub_numbers)

        root = client.get("/")
        songs_html = client.get("/songs")
        js = client.get("/api/songs")

    assert root.status_code == 200, root.text
    assert songs_html.status_code == 200, songs_html.text
    assert songs_html.status_code != 405
    page = songs_html.text
    assert root.status_code != 405

    assert js.status_code == 200, js.text
    ctype = (js.headers.get("content-type") or "").split(";")[0].strip()
    assert ctype == "application/json", (
        f"/api/songs returned {ctype or 'no content-type'}, not JSON: "
        f"{js.text[:200]}")
    assert "<html" not in js.text.lower(), js.text[:200]
    body = js.json()

    assert 'id="library"' in page, page[:800]
    html_song_count = int(_attr(page, "song-count"))

    # Service-owned count, not len(rows). Template that counts rows → red.
    assert html_song_count == body["song_count"] == _STUB_SONG_COUNT, (
        html_song_count, body.get("song_count"), body)
    assert html_song_count != _N_SONGS, (
        "fixture must keep song_count off list length so len()-recompute fails")
    # Root HTML shares the same service-owned count.
    root_count = int(_attr(root.text, "song-count"))
    assert root_count == _STUB_SONG_COUNT, root_count
