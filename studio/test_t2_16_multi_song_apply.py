"""T2-16: multi-song arc apply needs confirmation; with confirm writes exactly
those songs.

docs/TRD-2 §4.1: the wand never writes to more than one song at a time without
confirmation. Outside review: do not auto-apply an LLM rewrite across every
song in an album. Positive half: with confirmation it writes to exactly the
songs confirmed, asserted by count.

Mutation: apply two songs with confirm empty → 400 arm red if the guard is
dropped. Mutation: confirm writes every song in the arc → count arm red.
"""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import arc
import db


def _arc_body(song_ids, premise="A cat crosses a city and does not come back."):
    return {
        "premise": premise,
        "acts": [{"name": "Leaving", "songs": list(song_ids),
                  "turn": "she stops looking back"}],
        "songs": [{"song_id": sid, "position": i + 1,
                   "role": f"role {i + 1}", "beat": f"beat {i + 1}",
                   "opens": f"opens {i + 1}", "closes": f"closes {i + 1}"}
                  for i, sid in enumerate(song_ids)],
        "continuity": ["the collar is always brass"],
    }


def _album(n=3):
    stamp = f"t216-{time.time_ns()}"
    name = f"T2-16 Album {stamp}"
    db.run("INSERT INTO playlists (name, kind, created) VALUES (?, 'playlist', ?)",
           name, time.time())
    pid = db.one("SELECT id FROM playlists WHERE name=? AND kind='playlist'",
                 name)["id"]
    ids = []
    for i in range(n):
        sid = db.upsert_song(f"{stamp}-{i}", title=f"{name} {i}", album=name,
                             lyrics=f"lyrics {i}")
        db.run("""INSERT INTO playlist_items
                  (playlist_id, song_id, position, transition, secs)
                  VALUES (?,?,?,?,?)""", pid, sid, i, "fade", 2.0)
        ids.append(sid)
    return pid, ids, name


def test_t2_16_http_two_songs_need_confirm_and_write_exactly_those():
    pid, sids, name = _album(3)
    assert len(sids) == 3
    data = _arc_body(sids)
    pl = db.one("SELECT * FROM playlists WHERE id=?", pid)
    outdir, slug = appmod.album_arc_dir(pl)
    titles = {sid: f"Track {i}" for i, sid in enumerate(sids)}
    jp, mp = arc.write(data, outdir, slug, titles)
    db.run("""INSERT INTO arcs (playlist_id, json_path, md_path, model, prompt, created)
              VALUES (?,?,?,?,?,?)""",
           pid, jp, mp, "test/stub", "theme", time.time())

    applied = os.path.join(outdir, "applied")
    pair = f"{sids[0]},{sids[1]}"

    with TestClient(appmod.app) as client:
        no_confirm = client.post(
            f"/playlists/{pid}/arc/apply",
            data={"song_ids": pair, "confirm": ""})
        assert no_confirm.status_code == 400, no_confirm.text
        assert "confirm" in no_confirm.text.lower()
        assert not os.path.isdir(applied) or os.listdir(applied) == []

        confirmed = client.post(
            f"/playlists/{pid}/arc/apply",
            data={"song_ids": pair, "confirm": "1"})
        assert confirmed.status_code in (200, 303), confirmed.text

    written = sorted(os.listdir(applied))
    assert written == [f"{sids[0]}.json", f"{sids[1]}.json"], written
    assert not os.path.isfile(os.path.join(applied, f"{sids[2]}.json"))
    assert json.load(open(os.path.join(applied, f"{sids[0]}.json")))["beat"] == "beat 1"
    assert json.load(open(os.path.join(applied, f"{sids[1]}.json")))["beat"] == "beat 2"
