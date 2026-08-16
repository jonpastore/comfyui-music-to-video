"""T6-A2-playlists: HTML page and JSON endpoint report the same playlist numbers.

docs/TRD-6 §0.1: GET /playlists HTML card and GET /api/playlists/{id}
report the same song_count and total_secs from playlist_service.numbers.
Two answers means two implementations. Arc on the payload stays T2-37
(only when defined).

Distinctive numbers so two empty answers cannot pass. song_count is
service-owned: a template that recomputes from len(rows) fails the
stub arm when the service returns a count that is not the list length.
"""
import re
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import playlist_service

# Distinctive fixture — not 0, not equal to song_count.
_DURATIONS = (11.5, 22.25, 7.0)
_N_SONGS = len(_DURATIONS)
_TOTAL_SECS = sum(_DURATIONS)  # 40.75
_STUB_SONG_COUNT = 99  # not _N_SONGS — named mutation for len()-recompute


def _attr(page, name, pid=None):
    if pid is not None:
        m = re.search(
            rf'id="playlist-{pid}"[^>]*data-{name}="([^"]*)"', page)
        if not m:
            m = re.search(
                rf'data-{name}="([^"]*)"[^>]*id="playlist-{pid}"', page)
    else:
        m = re.search(rf'data-{name}="([^"]*)"', page)
    assert m, f"missing data-{name} on playlist card: {page[:500]}"
    return m.group(1)


def test_t6_a2_html_and_json_report_the_same_playlist_numbers(monkeypatch):
    """HTML and JSON agree on distinctive card numbers from one service.

    Real playlist: 3 songs / 11.5+22.25+7.0=40.75s.
    Stub arm: song_count forced to 99 so a template that counts rows goes red.
    """
    assert _STUB_SONG_COUNT != _N_SONGS
    assert _TOTAL_SECS != _N_SONGS
    assert _TOTAL_SECS == 40.75
    assert _N_SONGS and _TOTAL_SECS

    stamp = time.time_ns()
    album = f"T6-A2 Playlist Album {stamp}"
    song_ids = []
    for i, dur in enumerate(_DURATIONS):
        sid = db.upsert_song(
            f"t6a2-pl-{stamp}-{i}", title=f"T6-A2 Playlist Track {i + 1}",
            album=album, duration=dur, lyrics="she leaves")
        song_ids.append(sid)
    pid = db.run(
        "INSERT INTO playlists (name, kind, created) VALUES (?,?,?)",
        album, "playlist", time.time())
    for pos, sid in enumerate(song_ids):
        db.run(
            "INSERT INTO playlist_items (playlist_id, song_id, position) VALUES (?,?,?)",
            pid, sid, pos)

    with TestClient(appmod.app) as client:
        real = playlist_service.numbers(pid)
        assert real["song_count"] == _N_SONGS, real
        assert real["total_secs"] == _TOTAL_SECS, real

        stub = dict(real)
        stub["song_count"] = _STUB_SONG_COUNT

        def _stub_numbers(playlist_id):
            return stub

        monkeypatch.setattr(playlist_service, "numbers", _stub_numbers)
        monkeypatch.setattr(appmod.playlist_service, "numbers", _stub_numbers)

        html = client.get("/playlists")
        js = client.get(f"/api/playlists/{pid}")

    assert html.status_code == 200, html.text
    page = html.text
    assert js.status_code == 200, js.text
    ctype = (js.headers.get("content-type") or "").split(";")[0].strip()
    assert ctype == "application/json", (
        f"/api/playlists/{{id}} returned "
        f"{ctype or 'no content-type'}, not JSON: {js.text[:200]}")
    assert "<html" not in js.text.lower(), js.text[:200]
    body = js.json()

    assert f'id="playlist-{pid}"' in page, page[:800]
    html_song_count = int(_attr(page, "song-count", pid))
    html_total_secs = float(_attr(page, "total-secs", pid))

    # Service-owned count, not len(rows). Template that counts rows → red.
    assert html_song_count == body["song_count"] == _STUB_SONG_COUNT, (
        html_song_count, body.get("song_count"), body)
    assert html_song_count != _N_SONGS, (
        "fixture must keep song_count off list length so len()-recompute fails")
    assert html_total_secs == body["total_secs"] == _TOTAL_SECS, (
        html_total_secs, body.get("total_secs"), body)
    assert body["total_secs"] != body["song_count"], body
    # T2-37: no arc on this fixture → field omitted, not null.
    assert "arc" not in body, body
