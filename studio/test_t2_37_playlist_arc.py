"""T2-37: playlist payload carries the album arc when one is defined.

docs/TRD-2 §7: the playlist payload carries the album's arc when one is
defined, so a row can show it. Asserted on the payload, not the rendered
row. A playlist WITHOUT an arc omits the field — "always present"
(including null) cannot pass.

Mutation: always include `arc` (null or empty) → absent arm red.
Mutation: drop `arc` from the with-arc payload → present arm red.
Mutation: include a key but never the stored premise → present arm red.
"""
import time

from fastapi.testclient import TestClient

import app as appmod
import db


PREMISE = "T2-37 ZX arc premise brass collar city walk"


def _arc(song_id, album, premise=PREMISE):
    return {
        "premise": premise,
        "acts": [{"name": "Night", "songs": [song_id], "turn": "she leaves"}],
        "songs": [{
            "song_id": song_id, "position": 1,
            "role": "the door", "beat": "she leaves",
            "opens": "a shut door", "closes": "headlights",
        }],
        "continuity": ["the collar is brass"],
        "album": album,
        "direction": "keep walking",
    }


def _playlist(name):
    sid = db.upsert_song(
        f"t237-{name}-{time.time_ns()}",
        title="T2-37 Track",
        album=name,
        duration=12.0,
        lyrics="she leaves",
    )
    pid = db.run(
        "INSERT INTO playlists (name, kind, created) VALUES (?,?,?)",
        name, "playlist", time.time())
    db.run(
        "INSERT INTO playlist_items (playlist_id, song_id, position) VALUES (?,?,?)",
        pid, sid, 0)
    return pid, sid


def _payload(client, pid):
    """Playlist payload a row can show. Must be JSON, not the HTML card."""
    r = client.get(f"/api/playlists/{pid}")
    assert r.status_code == 200, r.text
    assert "application/json" in (r.headers.get("content-type") or ""), r.headers
    return r.json()


def test_t2_37_playlist_payload_carries_arc_when_defined_omits_when_none():
    stamp = time.time_ns()
    with_name = f"T2-37 With Arc {stamp}"
    without_name = f"T2-37 No Arc {stamp}"
    pid_with, sid = _playlist(with_name)
    pid_without, _ = _playlist(without_name)

    with TestClient(appmod.app) as client:
        bare = _payload(client, pid_without)
        assert "arc" not in bare, bare

        landed = client.post(f"/api/playlists/{pid_with}/arc",
                             json=_arc(sid, with_name))
        assert landed.status_code == 200, landed.text

        body = _payload(client, pid_with)
        assert "arc" in body, body
        arc = body["arc"]
        assert isinstance(arc, dict), arc
        assert arc.get("premise") == PREMISE, arc
        # a client that only checks key presence without reading content fails here
        assert PREMISE in (arc.get("premise") or "")

        still_bare = _payload(client, pid_without)
        assert "arc" not in still_bare, still_bare
