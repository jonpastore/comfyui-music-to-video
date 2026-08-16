"""T6-A2-arc: HTML page and JSON endpoint report the same arc numbers.

docs/TRD-6 §0.1: GET /playlists/{id}/arc HTML and
GET /api/playlists/{id}/arc report the same song_count, act_count,
premise, has_proposal from arc_service.payload. Two answers means two
implementations. Playlist GET /api/playlists/{id} stays T2-37-shaped.

Distinctive numbers so two empty answers cannot pass. song_count is
service-owned: a template that recomputes from len(arc.songs) fails the
stub arm when the service returns a count that is not the list length.
"""
import os
import re
import time

from fastapi.testclient import TestClient

import app as appmod
import arc
import arc_service
import db

# Distinctive fixture values — not 0/0, not equal to each other.
_N_SONGS = 3
_N_ACTS = 2
_PREMISE = "T6-A2 ZX arc premise brass collar city walk three tracks two acts"
_STUB_SONG_COUNT = 99  # not _N_SONGS — named mutation for len()-recompute


def _song_entry(song_id, position):
    return {
        "song_id": song_id, "position": position,
        "role": f"role {position}", "beat": f"beat {position}",
        "opens": f"opens {position}", "closes": f"closes {position}",
    }


def _write_arc(pid, album, song_ids, premise=_PREMISE):
    assert len(song_ids) == _N_SONGS
    data = {
        "premise": premise,
        "acts": [
            {"name": "Leaving", "songs": song_ids[:2], "turn": "she stops looking back"},
            {"name": "Arrival", "songs": song_ids[2:], "turn": "the city forgets her"},
        ],
        "songs": [_song_entry(sid, i) for i, sid in enumerate(song_ids, 1)],
        "continuity": ["the collar is brass"],
        "album": album,
        "direction": "keep walking",
    }
    titles = {sid: f"Track {i}" for i, sid in enumerate(song_ids, 1)}
    outdir = os.path.join(db.DATA, "arcs", appmod.safe_name(album))
    json_path, md_path = arc.write(data, outdir, appmod.safe_name(album), titles)
    db.run("""INSERT INTO arcs (playlist_id, json_path, md_path, model, prompt, created)
              VALUES (?,?,?,?,?,?)
              ON CONFLICT(playlist_id) DO UPDATE SET json_path=excluded.json_path,
              md_path=excluded.md_path, model=excluded.model, prompt=excluded.prompt,
              created=excluded.created""",
           pid, json_path, md_path, "stub/model", "keep walking", time.time())
    return data


def _write_proposal(pid, album, song_ids):
    outdir = os.path.join(db.DATA, "arcs", appmod.safe_name(album))
    proposal = {
        "premise": "T6-A2 proposal premise not yet accepted",
        "acts": [{"name": "Draft", "songs": song_ids, "turn": "draft turn"}],
        "songs": [_song_entry(sid, i) for i, sid in enumerate(song_ids, 1)],
        "continuity": [],
        "album": album,
    }
    arc.write_proposal(proposal, outdir, appmod.safe_name(album))
    return proposal


def _attr(page, name):
    m = re.search(rf'data-{name}="([^"]*)"', page)
    assert m, f"missing data-{name} on arc page: {page[:500]}"
    return m.group(1)


def test_t6_a2_html_and_json_report_the_same_arc_numbers(monkeypatch):
    """HTML and JSON agree on distinctive meter numbers from one service.

    Real arc: 3 songs / 2 acts / unique premise / proposal present.
    Stub arm: song_count forced to 99 so a template that counts arc.songs
    goes red.
    """
    assert _STUB_SONG_COUNT != _N_SONGS
    assert _N_SONGS != _N_ACTS
    assert _N_SONGS and _N_ACTS

    stamp = time.time_ns()
    album = f"T6-A2 Arc Album {stamp}"
    song_ids = []
    for i in range(_N_SONGS):
        sid = db.upsert_song(
            f"t6a2-arc-{stamp}-{i}", title=f"T6-A2 Arc Track {i + 1}",
            album=album, duration=12.0 + i, lyrics="she leaves")
        song_ids.append(sid)
    pid = db.run(
        "INSERT INTO playlists (name, kind, created) VALUES (?,?,?)",
        album, "playlist", time.time())
    for pos, sid in enumerate(song_ids):
        db.run(
            "INSERT INTO playlist_items (playlist_id, song_id, position) VALUES (?,?,?)",
            pid, sid, pos)

    _write_arc(pid, album, song_ids)
    _write_proposal(pid, album, song_ids)

    with TestClient(appmod.app) as client:
        real = arc_service.payload(pid)
        assert real["song_count"] == _N_SONGS, real
        assert real["act_count"] == _N_ACTS, real
        assert real["premise"] == _PREMISE, real
        assert real["has_proposal"] is True, real

        stub = dict(real)
        stub["song_count"] = _STUB_SONG_COUNT

        def _stub_payload(playlist_id):
            return stub

        monkeypatch.setattr(arc_service, "payload", _stub_payload)
        monkeypatch.setattr(appmod.arc_service, "payload", _stub_payload)

        html = client.get(f"/playlists/{pid}/arc")
        js = client.get(f"/api/playlists/{pid}/arc")

    assert html.status_code == 200, html.text
    page = html.text
    assert js.status_code == 200, js.text
    ctype = (js.headers.get("content-type") or "").split(";")[0].strip()
    assert ctype == "application/json", (
        f"/api/playlists/{{id}}/arc returned "
        f"{ctype or 'no content-type'}, not JSON: {js.text[:200]}")
    assert "<html" not in js.text.lower(), js.text[:200]
    body = js.json()

    html_song_count = int(_attr(page, "song-count"))
    html_act_count = int(_attr(page, "act-count"))
    html_premise = _attr(page, "premise")
    html_has_proposal = _attr(page, "has-proposal")

    # Service-owned count, not len(songs). Template that counts rows → red.
    assert html_song_count == body["song_count"] == _STUB_SONG_COUNT, (
        html_song_count, body.get("song_count"), body)
    assert html_song_count != _N_SONGS, (
        "fixture must keep song_count off list length so len()-recompute fails")
    assert html_act_count == body["act_count"] == _N_ACTS, (
        html_act_count, body.get("act_count"), body)
    assert html_premise == body["premise"] == _PREMISE, (
        html_premise, body.get("premise"), body)
    assert body["has_proposal"] is True, body
    assert html_has_proposal == "true", html_has_proposal
    assert _PREMISE in page
    # T2-37 playlist payload is a different surface; arc JSON still carries arc.
    assert isinstance(body.get("arc"), dict), body
    assert body["arc"].get("premise") == _PREMISE, body
