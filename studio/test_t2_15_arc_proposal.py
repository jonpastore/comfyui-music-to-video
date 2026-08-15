"""T2-15: arc proposal is not saved until accept; reject leaves the previous
arc on disk.

docs/TRD-2 §4.1: propose does not write the committed file. Rejecting
leaves the previous arc untouched, verified by re-reading that file.
Accepting does save — deleting the write would keep the first two
arms green.

Mutation: propose calls write / _persist_arc → propose arm fails.
Mutation: reject overwrites or deletes the committed file → reject arm
fails.
Mutation: accept does not write the file → accept arm fails.
"""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db


PREV = "A cat crosses a city at night and does not come back the same."
NEXT = "She takes the last train and the city forgets her name."


def _arc(song_id, premise, album):
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


def _disk(pid):
    row = db.one("SELECT json_path FROM arcs WHERE playlist_id=?", pid)
    assert row and row["json_path"] and os.path.isfile(row["json_path"]), row
    path = row["json_path"]
    with open(path) as f:
        raw = f.read()
    return path, raw, json.loads(raw)


def test_t2_15_propose_does_not_write_reject_leaves_disk_accept_saves(monkeypatch):
    stamp = f"t215-{time.time_ns()}"
    album = f"T2-15 Album {stamp}"
    sid = db.upsert_song(stamp, title="Arc Track", album=album,
                         duration=12.3, lyrics="she leaves")
    pid = db.run(
        "INSERT INTO playlists (name, kind, created) VALUES (?,?,?)",
        album, "playlist", time.time())
    db.run("INSERT INTO playlist_items (playlist_id, song_id, position) VALUES (?,?,?)",
           pid, sid, 0)

    def _fake_generate(album_name, songs, direction="", backend=None, model=None,
                       progress=None, transitions=None):
        return _arc(songs[0]["id"], NEXT, album_name), "stub/model"

    monkeypatch.setattr(appmod.arc, "generate", _fake_generate)

    with TestClient(appmod.app) as client:
        accepted = client.post(f"/api/playlists/{pid}/arc",
                               json=_arc(sid, PREV, album))
        assert accepted.status_code == 200, accepted.text
        path, before, prev = _disk(pid)
        assert prev["premise"] == PREV, prev

        proposed = client.post(f"/api/playlists/{pid}/arc/propose",
                               json={"direction": "keep walking"})
        assert proposed.status_code == 200, proposed.text
        body = proposed.json()
        proposal = body.get("proposal") or body.get("arc")
        assert proposal and proposal.get("premise") == NEXT, body

        mid_path, mid_raw, mid = _disk(pid)
        assert mid_path == path
        assert mid_raw == before, "propose wrote the committed arc file"
        assert mid["premise"] == PREV, mid

        rejected = client.post(f"/api/playlists/{pid}/arc/reject")
        assert rejected.status_code == 200, rejected.text
        after_path, after_raw, after = _disk(pid)
        assert after_path == path
        assert after_raw == before, "reject changed the committed arc file"
        assert after["premise"] == PREV, after

        landed = client.post(f"/api/playlists/{pid}/arc", json=proposal)
        assert landed.status_code == 200, landed.text
        _, saved_raw, saved = _disk(pid)
        assert saved_raw != before, "accept left the previous arc on disk"
        assert saved["premise"] == NEXT, saved
        assert PREV not in saved_raw
