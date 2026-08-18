"""T2-42: a scene may carry video_model; absent, the job --video-model applies.

docs/TRD-2 W2 / T2-42: the field is a fact on the scene, not a render
setting. T2-43 places it beside camera, editable through
EDITABLE_SCENE_FIELDS and readable over JSON like every other scene field.

Mutation: omit video_model from _scene_json → GET arm red.
Mutation: invent the job default onto an unmarked scene → absent arm red.
Mutation: leave video_model off EDITABLE_SCENE_FIELDS → save arm red.
Mutation: show it anywhere except beside camera → HTML arm red.
"""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import build_song
import db


def _scene(n, video_model=None, camera="wide establishing"):
    s = {
        "scene_number": n,
        "name": f"Scene {n}",
        "cue": "Verse",
        "duration_guidance": "5-7 sec",
        "story": f"story {n}",
        "camera": camera,
        "motion": "walk",
        "lighting": "neon",
        "location": f"loc {n}",
        "image_prompt": f"a rooftop at night, scene {n}",
        "video_motion_prompt": f"motion {n}",
        "negative_prompt": "",
    }
    if video_model is not None:
        s["video_model"] = video_model
    return s


def _write_board(sid, slug, tier, scenes):
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    sb = {
        "title": "T",
        "album": "A",
        "version": tier,
        "character_reference": "a sleek black feline DJ",
        "album_world_reference": "neon warehouse",
        "audio_lyrics": "[Verse]\nline\n",
        "scenes": scenes,
    }
    json_path = os.path.join(outdir, f"{slug}_{tier}.json")
    md_path = os.path.join(outdir, f"{slug}_{tier}.md")
    json.dump(sb, open(json_path, "w"))
    open(md_path, "w").write("# storyboard\n")
    db.run(
        """INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(song_id, tier) DO UPDATE SET json_path=excluded.json_path,
           md_path=excluded.md_path, scene_count=excluded.scene_count""",
        sid, tier, json_path, md_path, len(scenes), time.time())
    return json_path


def test_t2_42_absent_scene_takes_the_job_video_model():
    """T5-11: hop 0 is ltx25. The field still posts; it does not skip LTX."""
    unmarked = {"length_seconds": 5.0}
    marked = {"length_seconds": 5.0, "video_model": "s2v"}
    lip = {"length_seconds": 5.0, "needs_lip_sync": True}
    assert build_song.clips_for_scene(unmarked, default_model="ltx25")[0]["model"] == "ltx25"
    assert build_song.clips_for_scene(marked, default_model="ltx25")[0]["model"] == "ltx25"
    assert build_song.clips_for_scene(unmarked, default_model="s2v")[0]["model"] == "ltx25"
    assert build_song.clips_for_scene(lip, default_model="s2v")[0]["model"] == "ltx25"


def test_t2_42_json_carries_video_model_beside_camera():
    """GET returns the field next to camera. An unmarked scene stays empty."""
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t242-json", title="T2-42 JSON Song",
                             album="T242", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _write_board(sid, song["slug"], "pg13", [
            _scene(1, video_model="s2v", camera="wide establishing"),
            _scene(2, camera="close"),
        ])
        r = client.get(f"/api/songs/{sid}/storyboard/pg13")
        assert r.status_code == 200, r.text
        scenes = r.json()["scenes"]
        one = next(s for s in scenes if s.get("num") == 1)
        two = next(s for s in scenes if s.get("num") == 2)
        assert one["video_model"] == "s2v", one
        assert one["camera"] == "wide establishing", one
        assert two["video_model"] == "", two
        assert two["camera"] == "close", two
        keys = list(one.keys())
        assert "camera" in keys and "video_model" in keys, keys
        assert keys.index("video_model") == keys.index("camera") + 1, keys


def test_t2_42_video_model_is_editable_through_scene_fields():
    """T2-43: EDITABLE_SCENE_FIELDS + JSON save. A form-only write is not this."""
    assert "video_model" in appmod.EDITABLE_SCENE_FIELDS
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t242-edit", title="T2-42 Edit Song",
                             album="T242", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        json_path = _write_board(sid, song["slug"], "pg13", [
            _scene(1, camera="wide establishing"),
            _scene(2, video_model="ltx25", camera="close"),
        ])
        r = client.post(
            f"/api/songs/{sid}/storyboard/pg13/scene/1",
            json={"video_model": "s2v"})
        assert r.status_code == 200, r.text
        payload = r.json()
        one = next(s for s in payload["scenes"] if s.get("num") == 1)
        two = next(s for s in payload["scenes"] if s.get("num") == 2)
        assert one["video_model"] == "s2v", one
        assert two["video_model"] == "ltx25", two
        assert payload.get("scene", {}).get("video_model") == "s2v", payload.get("scene")
        written = json.load(open(json_path))
        assert written["scenes"][0]["video_model"] == "s2v"
        assert written["scenes"][1]["video_model"] == "ltx25"
        assert written["scenes"][0]["camera"] == "wide establishing"
        assert written["scenes"][1]["image_prompt"] == "a rooftop at night, scene 2"


def test_t2_42_scene_row_shows_video_model_beside_camera():
    """HTML: the field sits next to camera and the form can edit it."""
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t242-html", title="T2-42 HTML Song",
                             album="T242", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        json_path = _write_board(sid, song["slug"], "pg13", [
            _scene(1, video_model="s2v", camera="wide establishing"),
            _scene(2, camera="close"),
        ])
        page = client.get(f"/songs/{sid}/storyboard/pg13")
        assert page.status_code == 200, page.text
        start = page.text.find('id="scene-1"')
        end = page.text.find('id="scene-2"')
        assert start != -1, page.text
        html = page.text[start:end if end != -1 else None]
        assert 'name="camera"' in html, html
        assert 'name="video_model"' in html, html
        cam_at = html.index('name="camera"')
        model_at = html.index('name="video_model"')
        assert cam_at < model_at, html[cam_at:model_at + 40]
        assert 'value="wide establishing"' in html
        assert 'value="s2v"' in html
        saved = client.post(
            f"/songs/{sid}/storyboard/pg13/scene/2",
            data={"video_model": "i2v"})
        assert saved.status_code == 200, saved.text
        assert 'name="video_model"' in saved.text
        assert "i2v" in saved.text
        written = json.load(open(json_path))
        assert written["scenes"][1]["video_model"] == "i2v"
        assert written["scenes"][0]["video_model"] == "s2v"
