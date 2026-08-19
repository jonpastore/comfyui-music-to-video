"""Media nav: New Song is a new song; New Image is local t2i."""
import json
import os

from fastapi.testclient import TestClient

import app as appmod
import db
from test_app import _upload_song


def test_media_page_and_nav():
    with TestClient(appmod.app) as client:
        hub = client.get("/media")
        assert hub.status_code == 200, hub.text
        assert 'href="/media?new=song"' in hub.text
        assert 'href="/media?new=image"' in hub.text
        assert 'action="/media/songs"' not in hub.text
        assert 'action="/media/images"' not in hub.text
        song = client.get("/media", params={"new": "song"})
        assert song.status_code == 200, song.text
        assert 'action="/media/songs"' in song.text
        assert 'action="/media/images"' not in song.text
        image = client.get("/media", params={"new": "image"})
        assert image.status_code == 200, image.text
        assert 'action="/media/images"' in image.text
        assert 'action="/media/songs"' not in image.text
        assert 'name="style_lora"' in image.text
        assert 'id="civitai-loras"' in image.text
        assert "/models/civitai" in image.text
        assert "no studio graph" in image.text
        assert "flux2_t2i" in image.text
        home = client.get("/")
        assert 'href="/media"' in home.text
        assert ">Media<" in home.text
        assert 'href="/media?new=song"' in home.text
        assert 'href="/media?new=image"' in home.text
        nav = client.get("/api/nav")
        assert nav.status_code == 200
        links = nav.json()["links"]
        hrefs = [x["href"] for x in links]
        assert hrefs[:2] == ["/", "/media"]
        media = next(x for x in links if x["href"] == "/media")
        kids = [(c["href"], c["label"]) for c in media["children"]]
        assert kids == [("/media?new=song", "New Song"),
                        ("/media?new=image", "New Image")]
        crumb = client.get("/media", params={"new": "image"})
        assert "Media / Images" in crumb.text
        crumb_s = client.get("/media", params={"new": "song"})
        assert "Media / Songs" in crumb_s.text
        assert 'class="current"' in crumb.text


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
    assert "/media?new=song" in page.text
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
        assert args.get("style_lora") == ""


def test_new_image_refuses_unwired_flux2():
    with TestClient(appmod.app) as client:
        r = client.post("/media/images", data={
            "prompt": "a cat", "model": "flux2_t2i",
        }, follow_redirects=False)
        assert r.status_code == 400, r.text
        assert "no studio t2i graph" in r.text.lower() or "graph" in r.text.lower()


def test_new_image_enqueues_style_lora(monkeypatch, tmp_path):
    monkeypatch.setattr(appmod.pipeline, "gen_artwork",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("t2i must not run in this test")))
    monkeypatch.setattr(appmod.civitai, "list_installed",
                        lambda **k: ["qwen-edit-skin.safetensors"])
    with TestClient(appmod.app) as client:
        r = client.post("/media/images", data={
            "prompt": "grey studio",
            "style_lora": "qwen-edit-skin.safetensors",
            "style_lora_strength": "0.8",
        }, follow_redirects=False)
        assert r.status_code in (200, 303), r.text
    args = json.loads(db.one("SELECT args_json FROM jobs WHERE kind='t2i' ORDER BY id DESC")["args_json"])
    assert args["style_lora"] == "qwen-edit-skin.safetensors"
    assert args["style_lora_strength"] == 0.8


def test_style_lora_is_absent_from_the_default_graph():
    import build_refs
    wf = build_refs.workflow(
        {"image_prompt": "a cat", "negative_prompt": ""},
        "", None, "empty", 896, 1216, 1)
    assert "2b" not in wf
    assert wf["3"]["inputs"]["model"] == ["2", 0]


def test_style_lora_adds_a_second_loader():
    import build_refs
    wf = build_refs.workflow(
        {"image_prompt": "a cat", "negative_prompt": ""},
        "", None, "empty", 896, 1216, 1,
        style_lora="qwen-edit-skin.safetensors", style_lora_strength=0.7)
    assert wf["2b"]["inputs"]["lora_name"] == "qwen-edit-skin.safetensors"
    assert wf["2b"]["inputs"]["strength_model"] == 0.7
    assert wf["3"]["inputs"]["model"] == ["2b", 0]


def test_list_installed_skips_video_loras(tmp_path, monkeypatch):
    import civitai
    d = tmp_path / "loras"
    d.mkdir()
    (d / "qwen-edit-skin.safetensors").write_bytes(b"x")
    (d / "ltx-2-19b-ic-lora-detailer.safetensors").write_bytes(b"x")
    (d / "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors").write_bytes(b"x")
    monkeypatch.setattr(civitai, "lora_dir", lambda: str(d))
    got = civitai.list_installed()
    assert got == ["qwen-edit-skin.safetensors"]


def test_new_image_refuses_empty_prompt():
    with TestClient(appmod.app) as client:
        r = client.post("/media/images", data={"prompt": "  "},
                        follow_redirects=False)
        assert r.status_code == 400


def test_recent_images_select_and_delete(tmp_path):
    dest = tmp_path / "t2i"
    dest.mkdir()
    keep = dest / "keep.png"
    drop = dest / "drop.png"
    keep.write_bytes(b"\x89PNG\r\n\x1a\n")
    drop.write_bytes(b"\x89PNG\r\n\x1a\n")
    kid = db.run(
        "INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
        None, "t2i", str(keep), json.dumps({"prompt": "keep me"}), 1)
    did = db.run(
        "INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
        None, "t2i", str(drop), json.dumps({"prompt": "drop me"}), 2)
    with TestClient(appmod.app) as client:
        page = client.get("/media", params={"new": "image"})
        assert page.status_code == 200
        assert 'id="recent-images"' in page.text
        assert 'class="js-t2i-select"' in page.text
        assert 'class="danger btn-sm js-t2i-delete"' in page.text
        assert f'value="{did}"' in page.text
        gone = client.post("/media/images/delete", json={"ids": [did]},
                           headers={"Accept": "application/json"})
        assert gone.status_code == 200, gone.text
        assert gone.json()["deleted"] == [did]
    assert db.one("SELECT id FROM assets WHERE id=?", did) is None
    assert db.one("SELECT id FROM assets WHERE id=?", kid) is not None
    assert keep.is_file()
