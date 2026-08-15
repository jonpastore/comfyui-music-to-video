"""T2-14: arc wand refuses an empty theme and runs with a non-empty one.

docs/TRD-2 §4.1: a wand that fires without a theme produces a generic arc.
Refusal alone is satisfied by deleting the wand, so this also asserts a
non-empty theme produces an arc. T2-15 (reject leaves the previous arc;
accept saves) and T2-16 (never writes more than one song without
confirmation; with confirmation writes exactly those songs) are the rest
of the same wand.

Mutation: drop require_theme → empty generate is green and this fails.
Mutation: write the proposal straight into arcs/ on generate → T2-15 reject
re-read is no longer the previous file. Mutation: apply two songs with
confirm=False → T2-16 stays green only while the apply path is missing.
"""
import json
import os
import tempfile
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app as appmod
import arc
import db
from test_app import wait_job


def _songs(n=2, album="Wand Album"):
    return [{"id": i + 1, "title": f"Track {i + 1}", "lyrics": f"lyrics {i + 1}"}
            for i in range(n)]


def _raw(song_ids, premise="A cat crosses a city and does not come back the same."):
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


def _album(name, n=2):
    db.run("INSERT INTO playlists (name, kind, created) VALUES (?, 'playlist', ?)",
           name, time.time())
    pid = db.one("SELECT id FROM playlists WHERE name=? AND kind='playlist'", name)["id"]
    ids = []
    for i in range(n):
        sid = db.upsert_song(f"{name}-{i}", title=f"{name} {i}", album=name,
                             lyrics=f"lyrics {i}")
        db.run("""INSERT INTO playlist_items
                  (playlist_id, song_id, position, transition, secs)
                  VALUES (?,?,?,?,?)""", pid, sid, i, "fade", 2.0)
        ids.append(sid)
    return pid, ids


def test_t2_14_wand_refuses_empty_theme_and_runs_with_one():
    songs = _songs()
    with pytest.raises(ValueError, match="theme"):
        arc.require_theme("")
    with pytest.raises(ValueError, match="theme"):
        arc.require_theme("   ")
    with pytest.raises(ValueError, match="theme"):
        arc.generate("Wand Album", songs, direction="")
    with pytest.raises(ValueError, match="theme"):
        arc.generate("Wand Album", songs, direction=" \n\t ")

    raw = _raw([s["id"] for s in songs])

    def fake_chat_json(system, user, **kw):
        assert "colder than it started" in user
        return raw, "xai/stub"

    with patch.object(arc.chat, "chat_json", fake_chat_json):
        data, used = arc.generate(
            "Wand Album", songs, direction="colder than it started")
    assert used == "xai/stub"
    assert data["premise"] == raw["premise"]
    assert [s["song_id"] for s in data["songs"]] == [1, 2]
    assert data["direction"] == "colder than it started"


def test_t2_15_reject_leaves_previous_accept_saves():
    songs = _songs()
    previous = _raw([1, 2], premise="The previous story stays until accepted.")
    proposed = _raw([1, 2], premise="A new proposal must not land on reject.")
    titles = {1: "Track 1", 2: "Track 2"}
    d = tempfile.mkdtemp()
    slug = "wand_album"
    jp, _mp = arc.write(previous, d, slug, titles)
    before = open(jp).read()

    prop_path = arc.write_proposal(proposed, d, slug)
    assert os.path.isfile(prop_path)
    assert json.load(open(jp))["premise"] == previous["premise"]

    arc.discard_proposal(d, slug)
    assert not os.path.isfile(prop_path)
    after_reject = open(jp).read()
    assert after_reject == before, "reject rewrote the committed arc"

    arc.write_proposal(proposed, d, slug)
    cjp, _cmp = arc.commit_proposal(proposed, d, slug, titles)
    arc.discard_proposal(d, slug)
    saved = json.load(open(cjp))
    assert saved["premise"] == proposed["premise"]
    assert open(cjp).read() != before


def test_t2_16_apply_needs_confirm_for_more_than_one_song():
    songs = _songs(3)
    data = _raw([1, 2, 3])
    d = tempfile.mkdtemp()
    with pytest.raises(ValueError, match="confirm"):
        arc.apply_summaries(data, d, [1, 2], confirm=False)

    written = arc.apply_summaries(data, d, [1], confirm=False)
    assert written == [1]
    assert os.path.isfile(os.path.join(d, "applied", "1.json"))
    assert not os.path.isfile(os.path.join(d, "applied", "2.json"))

    written = arc.apply_summaries(data, d, [2, 3], confirm=True)
    assert written == [2, 3]
    assert os.path.isfile(os.path.join(d, "applied", "2.json"))
    assert os.path.isfile(os.path.join(d, "applied", "3.json"))
    assert json.load(open(os.path.join(d, "applied", "2.json")))["beat"] == "beat 2"


def test_t2_14_route_refuses_empty_theme_and_propose_does_not_save():
    pid, sids = _album("T214 Empty")
    with TestClient(appmod.app) as client:
        empty = client.post(f"/playlists/{pid}/arc", data={"theme": ""})
        assert empty.status_code == 400, empty.text
        assert "theme" in empty.text.lower()
        assert db.one("SELECT id FROM arcs WHERE playlist_id=?", pid) is None

        raw = _raw(sids, premise="Proposal premise must not be the saved arc.")

        def fake_generate(album, songs, direction="", **kw):
            assert direction == "a city that gets colder"
            out = dict(raw)
            out["album"] = album
            out["direction"] = direction
            return out, "xai/stub"

        with patch.object(appmod.chat, "available", lambda: ["xai"]), \
             patch.object(appmod.arc, "generate", fake_generate):
            r = client.post(f"/playlists/{pid}/arc",
                            data={"theme": "a city that gets colder"})
            assert r.status_code in (200, 303), r.text
            job = db.one("SELECT id FROM jobs WHERE kind='arc' ORDER BY id DESC")
            assert job, "non-empty theme did not run the wand"
            row = wait_job(job["id"])
            assert row["status"] == "done", row["error"]

        assert db.one("SELECT id FROM arcs WHERE playlist_id=?", pid) is None, \
            "propose wrote the committed arc before accept"

        pl = db.one("SELECT * FROM playlists WHERE id=?", pid)
        outdir = os.path.join(db.DATA, "arcs", appmod.safe_name(pl["name"]))
        slug = appmod.safe_name(pl["name"])
        proposal = arc.load_proposal(outdir, slug)
        assert proposal is not None
        assert proposal["premise"] == raw["premise"]

        previous = _raw(sids, premise="Disk arc that reject must leave alone.")
        jp, _mp = arc.write(previous, outdir, slug)
        db.run("""INSERT INTO arcs (playlist_id, json_path, md_path, model, prompt, created)
                  VALUES (?,?,?,?,?,?)""",
               pid, jp, _mp, "test/stub", "old", time.time())
        before = open(jp).read()

        rejected = client.post(f"/playlists/{pid}/arc/reject")
        assert rejected.status_code in (200, 303), rejected.text
        assert open(jp).read() == before
        assert arc.load_proposal(outdir, slug) is None
        saved = json.load(open(jp))
        assert saved["premise"] == previous["premise"]

        arc.write_proposal(proposal, outdir, slug)
        accepted = client.post(f"/playlists/{pid}/arc/accept")
        assert accepted.status_code in (200, 303), accepted.text
        row = db.one("SELECT * FROM arcs WHERE playlist_id=?", pid)
        assert row is not None
        assert json.load(open(row["json_path"]))["premise"] == proposal["premise"]
        assert not os.path.isdir(os.path.join(outdir, "applied")) or \
            os.listdir(os.path.join(outdir, "applied")) == []

        no_confirm = client.post(
            f"/playlists/{pid}/arc/apply",
            data={"song_ids": f"{sids[0]},{sids[1]}", "confirm": ""})
        assert no_confirm.status_code == 400, no_confirm.text
        assert not os.path.isdir(os.path.join(outdir, "applied")) or \
            os.listdir(os.path.join(outdir, "applied")) == []

        confirmed = client.post(
            f"/playlists/{pid}/arc/apply",
            data={"song_ids": f"{sids[0]},{sids[1]}", "confirm": "1"})
        assert confirmed.status_code in (200, 303), confirmed.text
        written = sorted(os.listdir(os.path.join(outdir, "applied")))
        assert written == [f"{sids[0]}.json", f"{sids[1]}.json"], written
        extra = os.path.join(outdir, "applied", f"{sids[2]}.json") if len(sids) > 2 else None
        if extra:
            assert not os.path.isfile(extra)
