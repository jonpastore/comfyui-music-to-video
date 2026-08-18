"""Storyboard panel chrome: toolbar, scene editors, readable JSON.

Approved UIUX review (sb-1..sb-6): scenes are the work surface; raw JSON
is closed; toolbar is one baseline; Generate is secondary; approve sits
above the scene list.
"""
import json
import os
import re
import time

from fastapi.testclient import TestClient

import app as appmod
import db
from test_app import _upload_song


def _board(sid, slug, scenes, **top):
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    sb = {
        "title": "T",
        "album": "A",
        "version": "xxx",
        "character_reference": "Meow P — black feline DJ",
        "album_world_reference": "neon warehouse",
        "audio_lyrics": "[Verse]\nline\n",
        "scenes": scenes,
    }
    sb.update(top)
    json_path = os.path.join(outdir, f"{slug}_xxx.json")
    json.dump(sb, open(json_path, "w"), ensure_ascii=False)
    open(json_path + ".md", "w").write("# sb\n")
    db.run(
        """INSERT INTO storyboards (song_id, tier, json_path, md_path,
                                    scene_count, created)
           VALUES (?,?,?,?,?,?)""",
        sid, "xxx", json_path, json_path + ".md", len(scenes), time.time())
    return json_path


def _scene(n, **extra):
    s = {
        "scene_number": n, "name": f"Scene {n}", "cue": "Verse",
        "duration_guidance": "5-7 sec", "story": f"story {n}",
        "camera": "wide establishing", "motion": "walk",
        "lighting": "neon", "location": f"loc {n}", "pose": "standing",
        "image_prompt": f"a rooftop at night, scene {n}",
        "video_motion_prompt": f"motion {n}", "negative_prompt": "",
        "characters": [],
    }
    s.update(extra)
    return s


def test_sb_panel_toolbar_and_closed_json():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "SB Panel UI Song", album="SB Panel Album")
        _board(song["id"], song["slug"], [_scene(1), _scene(2)])
        page = client.get(f"/songs/{song['id']}/storyboard/xxx/panel")
        assert page.status_code == 200, page.text
        html = page.text
        assert 'class="sb-toolbar"' in html
        assert "Snapshot" in html
        assert "Name this version" in html
        assert "Delete version" in html
        assert "data-created=" in html or "No snapshots yet" in html
        assert 'form="sb-gen-xxx" class="secondary"' in html or \
               'class="secondary"\n              title="Rewrites every scene' in html
        assert "rebuilds every scene from the stored direction" in html.lower()
        assert 'class="sb-raw-json"' in html
        assert "<details class=\"sb-raw-json\" open" not in html
        assert 'name="board_json"' in html
        assert "Meow P — black feline DJ" in html
        assert "\\u2014" not in html
        approve_at = html.find("Approve remaining")
        scenes_at = html.find("Scenes and timing")
        json_at = html.find("Raw board JSON")
        assert 0 < json_at < approve_at < scenes_at, (json_at, approve_at, scenes_at)
        assert "Save JSON" in html
        assert "Save lock" in html
        assert "Save JSON: writes the raw board file" in html
        assert "version it the same way album prompts" in html
        assert "Board toolbar" in html
        assert "What these numbers mean" in html
        assert "Extras and background may be named" not in html
        assert "wide low-ceiling" not in html or 'name="location"' in html
        assert "<p class=\"meta\">" not in html
        for tag in re.findall(r'<(?:button|a)\b[^>]*icon-btn[^>]*>', html):
            assert "title=" in tag, tag
        assert html.count('class="scene"') == 2
        assert "scene-list-head" in html
        assert ">Time<" in html
        assert ">Pose<" in html
        assert "Save plate" in html or "Save scene" in html
        assert 'id="scene-1"' in html
        assert 'name="camera"' in html
        assert 'name="pose"' in html
        assert "<textarea" in html and 'name="pose"' in html
        assert 'name="image_prompt"' in html
        assert "<details class=\"scene\" id=\"scene-1\" open" not in html
        js = open(os.path.join(os.path.dirname(__file__), "static", "app.js")).read()
        assert "applyRerollChip" in js
        assert "ref-frame clip-tile still-pending" in js
        assert "still-skeleton" in js.split("paintRerollPlaceholders", 1)[1]
        css = open(os.path.join(os.path.dirname(__file__), "static", "style.css")).read()
        assert "aspect-ratio: 3 / 4" in css.split(".still-pending .still-skeleton", 1)[1][:280]
        assert "refreshSceneEl" in js
        assert "if (!el || !jobId) return" not in js
        assert "seekNonBlackFrame" in js
        assert "js-stills-delete" in js


def test_sb_panel_scene_fields_write_the_stored_json():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "SB Scene Fields Song")
        path = _board(song["id"], song["slug"], [_scene(1)])
        r = client.post(
            f"/songs/{song['id']}/storyboard/xxx/scene/1",
            data={"name": "Alley", "camera": "low close", "pose": "kneeling",
                  "story": "she waits", "image_prompt": "wet alley at night"})
        assert r.status_code == 200, r.text
        written = json.load(open(path))
        one = written["scenes"][0]
        assert one["name"] == "Alley"
        assert one["camera"] == "low close"
        assert one["pose"] == "kneeling"
        assert one["story"] == "she waits"
        assert one["image_prompt"] == "wet alley at night"


def test_sb_panel_lock_writes_identity_without_json_blob():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "SB Lock Song")
        path = _board(song["id"], song["slug"], [_scene(1)])
        r = client.post(
            f"/songs/{song['id']}/storyboard/xxx/lock",
            data={"character_reference": "orange-furred tigress, striped",
                  "album_world_reference": "rain-slick docks"})
        assert r.status_code in (200, 303), r.text
        written = json.load(open(path))
        assert written["character_reference"] == "orange-furred tigress, striped"
        assert written["album_world_reference"] == "rain-slick docks"
        assert written["scenes"][0]["name"] == "Scene 1"
