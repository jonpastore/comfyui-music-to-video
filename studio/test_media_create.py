"""Media nav: New Song is a new song; New Image is local t2i."""
import json
import os

from fastapi.testclient import TestClient

import app as appmod
import db
from test_app import _upload_song


def test_media_page_and_nav():
    with TestClient(appmod.app) as client:
        page = client.get("/media")
        assert page.status_code == 200, page.text
        assert "New Song" in page.text
        assert "New Image" in page.text
        assert 'action="/media/songs"' in page.text
        assert 'action="/media/images"' in page.text
        home = client.get("/")
        assert 'href="/media"' in home.text
        assert ">Media<" in home.text
        nav = client.get("/api/nav")
        assert nav.status_code == 200
        hrefs = [x["href"] for x in nav.json()["links"]]
        assert hrefs[:2] == ["/", "/media"]


def test_new_song_enqueues_as_new_song(monkeypatch):
    monkeypatch.setattr(appmod.pipeline, "gen_audio",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("audio must not run in this test")))
    with TestClient(appmod.app) as client:
        r = client.post("/media/songs", data={
            "title": "Alley Steam",
            "album": "Street Cats",
            "tags": "dark synthwave, wet alley",
            "lyrics": "[verse] steam",
            "seconds": "24",
            "n": "1",
        }, follow_redirects=False)
        assert r.status_code in (200, 303), r.text
        song = db.one("SELECT * FROM songs WHERE title=?", "Alley Steam")
        assert song is not None
        assert song["mp3_path"] in (None, "")
        assert song["style_text"] == "dark synthwave, wet alley"
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='audio'",
                     song["id"])
        assert job is not None
        args = json.loads(job["args_json"])
        assert args["as_new_song"] is True
        assert args["tags"] == "dark synthwave, wet alley"
        assert args["seconds"] == 24.0


def test_new_song_refuses_empty_tags():
    with TestClient(appmod.app) as client:
        r = client.post("/media/songs", data={
            "title": "No Tags", "tags": "   ",
        }, follow_redirects=False)
        assert r.status_code == 400, r.text
        assert "style tag" in r.text.lower()


def test_first_take_on_new_song_becomes_original(monkeypatch, tmp_path):
    src = tmp_path / "take.mp3"
    src.write_bytes(b"ID3fake")

    def fake_audio(*a, **k):
        return [str(src)]

    monkeypatch.setattr(appmod.pipeline, "gen_audio", fake_audio)
    sid = db.upsert_song("media-birth", title="Birth Song", album="A")
    out = appmod.h_audio({
        "song_id": sid, "tags": "synth", "lyrics": "", "seconds": 12,
        "n": 1, "as_new_song": True,
    }, lambda m: None)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    assert song["mp3_path"]
    assert os.path.isfile(song["mp3_path"])
    assert out["path"] == song["mp3_path"]
    orig = db.one("SELECT * FROM assets WHERE song_id=? AND kind='audio_original'",
                  sid)
    assert orig is not None
    assert orig["path"] == song["mp3_path"]


def test_existing_song_take_does_not_overwrite_mp3(monkeypatch, tmp_path):
    src = tmp_path / "take2.mp3"
    src.write_bytes(b"ID3fake")
    monkeypatch.setattr(appmod.pipeline, "gen_audio", lambda *a, **k: [str(src)])
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Keep Upload")
    before = db.one("SELECT mp3_path FROM songs WHERE id=?", song["id"])["mp3_path"]
    appmod.h_audio({
        "song_id": song["id"], "tags": "synth", "lyrics": "", "seconds": 8,
        "n": 1,
    }, lambda m: None)
    after = db.one("SELECT mp3_path FROM songs WHERE id=?", song["id"])["mp3_path"]
    assert after == before


def test_song_page_points_at_media_not_generate_take():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "No Gen Fold")
        page = client.get(f"/songs/{song['id']}")
    assert page.status_code == 200
    assert "Generate take" not in page.text
    assert "/media#new-song" in page.text
    assert "Replace a span" in page.text


def test_new_image_enqueues_t2i(monkeypatch):
    monkeypatch.setattr(appmod.pipeline, "gen_artwork",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("t2i must not run in this test")))
    with TestClient(appmod.app) as client:
        r = client.post("/media/images", data={
            "prompt": "standing three-quarter, grey studio",
            "album": "Street Cats",
            "size": "896x1216",
            "n": "1",
        }, follow_redirects=False)
        assert r.status_code in (200, 303), r.text
        job = db.one("SELECT * FROM jobs WHERE kind='t2i' ORDER BY id DESC")
        assert job is not None
        args = json.loads(job["args_json"])
        assert args["prompt"] == "standing three-quarter, grey studio"
        assert args["width"] == 896 and args["height"] == 1216
        assert args["lightning"] is False


def test_new_image_refuses_empty_prompt():
    with TestClient(appmod.app) as client:
        r = client.post("/media/images", data={"prompt": "  "},
                        follow_redirects=False)
        assert r.status_code == 400
