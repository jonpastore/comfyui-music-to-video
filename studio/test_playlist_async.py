"""Playlist POSTs stay on the page; the committed arc is editable + versioned."""
import json
import os
import time

import arc
import db

from fastapi.testclient import TestClient

import app as appmod


HX = {"HX-Request": "true"}


def _song(title="hx-track"):
    return db.upsert_song(f"{title}-{time.time_ns()}", title=title,
                          mp3_path=f"/fake/{title}.mp3", duration=12.3,
                          lyrics="she walks the wet street")


def _playlist(name=None):
    album = name or f"HX Album {time.time_ns()}"
    pid = db.run("INSERT INTO playlists (name, kind, created) VALUES (?,?,?)",
                 album, "playlist", time.time())
    return pid, album


def _commit_arc(pid, sid, album, premise="The night gets colder."):
    data = {
        "premise": premise,
        "acts": [{"name": "Night", "songs": [sid], "turn": "she leaves"}],
        "songs": [{
            "song_id": sid, "position": 1,
            "role": "the door", "beat": "she leaves through rain",
            "opens": "a shut door", "closes": "headlights",
        }],
        "continuity": ["the collar is brass"],
        "album": album,
        "direction": "keep walking",
    }
    with TestClient(appmod.app) as client:
        r = client.post(f"/api/playlists/{pid}/arc", json=data)
        assert r.status_code == 200, r.text
    return data


def test_playlist_mutations_are_htmx_not_full_reload():
    sid = _song()
    pid, album = _playlist()
    with TestClient(appmod.app) as client:
        added = client.post(f"/playlists/{pid}/items",
                            data={"song_id": sid}, headers=HX)
        assert added.status_code == 200, added.text
        assert "<html" not in added.text.lower()
        assert "pl-fold" in added.text
        assert "hx-post=" in added.text
        assert "closest .playlist-body" in added.text
        assert "Save album look" in added.text
        assert ">Identity<" in added.text
        assert 'data-look="lead"' not in added.text
        assert "song-arc-beat" not in added.text or "aria-expanded" in added.text
        assert "song-actions" in added.text

        items = db.q("SELECT * FROM playlist_items WHERE playlist_id=?", pid)
        assert len(items) == 1
        saved = client.post(f"/playlists/{pid}/items/{items[0]['id']}",
                            data={"transition": "cut", "secs": "0.5"},
                            headers=HX)
        assert saved.status_code == 200, saved.text
        assert "pl-fold" in saved.text
        row = db.one("SELECT * FROM playlist_items WHERE id=?", items[0]["id"])
        assert row["transition"] == "cut"

        look = client.post(f"/playlists/{pid}/profile",
                           data={"identity": "black cat woman, gold eyes"},
                           headers=HX)
        assert look.status_code == 200, look.text
        assert "pl-fold" in look.text
        assert db.one("SELECT identity FROM playlists WHERE id=?", pid)["identity"]

        gone = client.post(f"/playlists/{pid}/items/{items[0]['id']}/delete",
                           headers=HX)
        assert gone.status_code == 200, gone.text
        assert db.q("SELECT id FROM playlist_items WHERE playlist_id=?", pid) == []


def test_save_character_hx_does_not_303():
    pid, album = _playlist()
    cid = db.run(
        "INSERT INTO characters (scope_value, name, created) VALUES (?,?,?)",
        album, "Tiger", time.time())
    with TestClient(appmod.app) as client:
        r = client.post(f"/characters/{cid}/save",
                        data={"identity": "orange tiger, striped",
                              "figure_role_present": "1",
                              "figure_role": "lead"},
                        headers=HX)
        assert r.status_code == 200, r.text
        assert r.headers.get("location") is None
        assert "Save Tiger" in r.text
        assert db.one("SELECT identity FROM characters WHERE id=?", cid)["identity"]


def test_set_links_use_caption_not_filename():
    pid, _album = _playlist()
    path = "/tmp/Street_Cats__arc_mix_example.mp3"
    db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
           None, "set", path,
           json.dumps({"playlist_id": pid, "mode": "audio"}), 1755400000.0)
    with TestClient(appmod.app) as client:
        card = client.get(f"/playlists/{pid}/card").text
    assert 'class="set-chip"' in card
    assert "Audio mix" in card
    assert ">Street_Cats__arc_mix_example.mp3<" not in card


def test_arc_edit_saves_and_restores_a_snapshot():
    sid = _song("arc-edit")
    pid, album = _playlist()
    db.run("INSERT INTO playlist_items (playlist_id, song_id, position) VALUES (?,?,?)",
           pid, sid, 0)
    _commit_arc(pid, sid, album, "The night gets colder.")
    outdir, slug = appmod.album_arc_dir(db.one("SELECT * FROM playlists WHERE id=?", pid))
    assert arc.list_snapshots(outdir) == []

    with TestClient(appmod.app) as client:
        card = client.get(f"/playlists/{pid}/card").text
        assert 'name="premise"' in card
        assert "Save arc" in card
        assert "she leaves through rain" in card

        saved = client.post(f"/playlists/{pid}/arc/save",
                            data={"premise": "The morning is worse.",
                                  "continuity": "the collar is brass",
                                  f"role_{sid}": "the door",
                                  f"beat_{sid}": "she does not go back",
                                  f"opens_{sid}": "a shut door",
                                  f"closes_{sid}": "headlights"},
                            headers=HX)
        assert saved.status_code == 200, saved.text
        assert "The morning is worse." in saved.text
        assert "she does not go back" in saved.text
        assert "arc-song-edit" in saved.text

    data = appmod._load_arc(pid)
    assert data["premise"] == "The morning is worse."
    assert data["songs"][0]["beat"] == "she does not go back"
    versions = arc.list_snapshots(outdir)
    assert versions, versions
    assert versions[0]["n"] == 1

    with TestClient(appmod.app) as client:
        restored = client.post(f"/playlists/{pid}/arc/restore",
                               data={"snapshot": "1"}, headers=HX)
        assert restored.status_code == 200, restored.text
        assert "The night gets colder." in restored.text
    assert appmod._load_arc(pid)["premise"] == "The night gets colder."


def test_date_hx_returns_the_label_text():
    pid, _album = _playlist()
    with TestClient(appmod.app) as client:
        r = client.post(f"/playlists/{pid}/date",
                        data={"released": "2024-06-01"}, headers=HX)
        assert r.status_code == 200, r.text
        assert r.text.strip() == "2024-06-01"
        assert "<html" not in r.text.lower()


def test_playlist_card_has_hx_on_look_and_songs():
    sid = _song("wired")
    pid, album = _playlist()
    cid = db.run(
        "INSERT INTO characters (scope_value, name, created) VALUES (?,?,?)",
        album, "Tiger", time.time())
    with TestClient(appmod.app) as client:
        client.post(f"/playlists/{pid}/items", data={"song_id": sid})
        card = client.get(f"/playlists/{pid}/card").text
    assert f'hx-post="/characters/{cid}/save"' in card
    assert f'hx-post="/playlists/{pid}/profile"' in card
    assert f'hx-post="/playlists/{pid}/items"' in card
    assert "closest .playlist-body" in card
    assert ">Identity<" in card
    assert 'data-look="identity"' in card
    assert 'data-cast="world"' in card
    assert "Sheet wording" in card
    assert f'hx-get="/playlists/{pid}/sheets' not in card
    assert "fold-cover-" not in card
    assert "<h2>Cover</h2>" not in card


def test_playlist_anchors_have_keeper_save_and_family_tabs():
    pid, album = _playlist()
    with TestClient(appmod.app) as client:
        gal = client.get(f"/playlists/{pid}/anchors").text
    assert "family-tabs" in gal or "None yet" in gal
    assert "data-filter" in gal or "None yet" in gal
    assert "Keeper" not in gal or "pose-roster" in gal


def test_playlist_js_reloads_anchors_after_in_page_save():
    js = open(os.path.join(os.path.dirname(__file__), "static", "app.js")).read()
    assert "fillDeferredFold" in js
    assert "htmx.ajax" in js
