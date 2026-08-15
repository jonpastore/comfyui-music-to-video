"""T2-44: save refuses a scene naming a model absent from renderable("video").

docs/TRD-2 §6a: a scene naming a model absent from
models.renderable("video") is refused at save, naming the scene number
and the bad value — not at render time and not silently defaulted.

Absent video_model is not a name (T2-42: the render's --video-model
applies). A cli value such as s2v is present even though it is not a
catalogue key; a check of keys alone would refuse a real renderer.

Mutation: save_scene / _apply_scene_fields write without the check →
save arm fails.
Mutation: silently rewrite the name to default_cli → file changes and
this fails.
Mutation: `named not in renderable("video")` (keys only) → s2v arm fails.
"""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import models


def _scene(n, **extra):
    row = {"scene_number": n, "name": f"Scene {n}", "cue": "Verse",
           "duration_guidance": "5-7 sec", "story": f"story {n}",
           "camera": "wide establishing", "motion": "walk",
           "lighting": "neon", "location": f"loc {n}",
           "image_prompt": f"a rooftop at night, scene {n}",
           "video_motion_prompt": f"motion {n}", "negative_prompt": ""}
    row.update(extra)
    return row


def _board(scenes=None):
    return {"title": "T", "album": "A", "version": "pg13",
            "character_reference": "a sleek black feline DJ",
            "album_world_reference": "neon warehouse",
            "audio_lyrics": "[Verse]\nline\n",
            "scenes": scenes or [_scene(1), _scene(2)]}


def _write_board(sid, slug, tier, scenes=None):
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    sb = _board(scenes)
    json_path = os.path.join(outdir, f"{slug}_{tier}.json")
    md_path = os.path.join(outdir, f"{slug}_{tier}.md")
    json.dump(sb, open(json_path, "w"))
    open(md_path, "w").write("# storyboard\n")
    db.run("""INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created)
              VALUES (?,?,?,?,?,?)
              ON CONFLICT(song_id, tier) DO UPDATE SET json_path=excluded.json_path,
              md_path=excluded.md_path, scene_count=excluded.scene_count""",
           sid, tier, json_path, md_path, len(sb["scenes"]), time.time())
    return json_path


def _assert_t2_44_message(text, num, bad):
    low = text.lower()
    assert f"scene {num}" in low, text
    assert str(bad) in text, text


def test_t2_44_helper_refuses_unknown_and_names_scene_and_value():
    """The catalogue check is the source of truth; HTTP is the caller."""
    try:
        models.refuse_unknown_video_model([
            _scene(1),
            _scene(2, video_model="not-a-model"),
        ])
        raise AssertionError("accepted a model absent from renderable('video')")
    except ValueError as e:
        _assert_t2_44_message(str(e), 2, "not-a-model")
    models.refuse_unknown_video_model([_scene(1), _scene(2)])
    models.refuse_unknown_video_model([_scene(1, video_model=""), _scene(2, video_model="   ")])
    models.refuse_unknown_video_model([_scene(1, video_model="s2v")])
    models.refuse_unknown_video_model([_scene(1, video_model="ltx25")])
    assert "s2v" not in models.renderable("video")
    assert "s2v" in models.renderable("video").values()


def test_t2_44_save_scene_refuses_unknown_model():
    """POST scene save refuses and does not write. A real cli still saves."""
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t244-unknown", title="T2-44 Save Song",
                             album="T244", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        json_path = _write_board(sid, song["slug"], "pg13", [
            _scene(1),
            _scene(2, video_model="not-a-model"),
        ])
        before = json.load(open(json_path))

        refused = client.post(
            f"/songs/{sid}/storyboard/pg13/scene/1",
            data={"image_prompt": "a neon stairwell, rewritten"})
        assert refused.status_code == 400, refused.text
        _assert_t2_44_message(refused.text, 2, "not-a-model")
        after = json.load(open(json_path))
        assert after == before
        assert after["scenes"][1]["video_model"] == "not-a-model"
        assert after["scenes"][1]["video_model"] != models.default_cli("video")

        json.dump(_board([
            _scene(1, video_model="s2v"),
            _scene(2),
        ]), open(json_path, "w"))
        ok = client.post(
            f"/songs/{sid}/storyboard/pg13/scene/1",
            data={"image_prompt": "a neon stairwell, rewritten"})
        assert ok.status_code == 200, ok.text
        written = json.load(open(json_path))
        assert written["scenes"][0]["image_prompt"] == "a neon stairwell, rewritten"
        assert written["scenes"][0]["video_model"] == "s2v"
        assert written["scenes"][1]["image_prompt"] == before["scenes"][1]["image_prompt"]


def test_t2_44_api_scene_edit_refuses_unknown_model():
    """JSON scene edit is the same save; a form-only check would miss it."""
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t244-api", title="T2-44 API Song",
                             album="T244", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        json_path = _write_board(sid, song["slug"], "pg13", [
            _scene(1, video_model="still-not-a-model"),
            _scene(2),
        ])
        before = json.load(open(json_path))

        refused = client.post(
            f"/api/songs/{sid}/storyboard/pg13/scene/1",
            json={"image_prompt": "a rewritten alley"})
        assert refused.status_code == 400, refused.text
        _assert_t2_44_message(refused.text, 1, "still-not-a-model")
        after = json.load(open(json_path))
        assert after == before
        assert after["scenes"][0]["video_model"] == "still-not-a-model"
