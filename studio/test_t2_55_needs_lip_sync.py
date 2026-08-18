"""T2-55: needs_lip_sync is the directorial lip-sync fact beside camera.

docs/TRD-2 T2-55: lives beside camera (not instead of it), editable,
readable over JSON. True → LTX first then the decoded s2v hop (T5-12).
False / absent → LTX only. It does not skip LTX.

Mutation: needs_lip_sync=true emits only an s2v graph → red.
Mutation: the flag is omitted from _scene_json → GET arm red.
Mutation: false → no hop → red if a hop appears.
"""
import json
import os
import sys
import time

from fastapi.testclient import TestClient

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app as appmod
import build_song
import db


SCENE = {
    "name": "s", "camera": "wide", "lighting": "neon",
    "video_motion_prompt": "she walks", "negative_prompt": "",
    "duration_guidance": "5 sec", "image_prompt": "a rooftop",
}


def _scene(n, needs_lip_sync=None, camera="wide establishing"):
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
    if needs_lip_sync is not None:
        s["needs_lip_sync"] = needs_lip_sync
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


def _classes(wf):
    return {n.get("class_type") for n in wf.values()}


def _emit(tmp_path, monkeypatch, scenes, slug):
    monkeypatch.setattr(
        build_song, "audio_duration",
        lambda p: build_song.CHUNK * max(len(scenes), 1))
    sb = {
        "scenes": scenes,
        "character_reference": "c",
        "album_world_reference": "w",
    }
    storyboard = tmp_path / "sb.json"
    storyboard.write_text(json.dumps(sb))
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"x")
    outdir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "build_song.py", "--storyboard", str(storyboard),
        "--audio", str(audio), "--slug", slug, "--outdir", str(outdir),
        "--video-model", "ltx25",
    ])
    build_song.main()
    return outdir


def _hop_graphs(outdir):
    return sorted(
        p for p in outdir.glob("clip_*.json") if ".expect." not in p.name)


def test_t2_55_field_is_editable_beside_camera():
    assert "needs_lip_sync" in appmod.EDITABLE_SCENE_FIELDS
    assert "needs_lip_sync" in appmod.SHORT_SCENE_FIELDS
    assert "needs_lip_sync" in appmod.BOOL_SCENE_FIELDS
    cam = appmod.EDITABLE_SCENE_FIELDS.index("camera")
    lip = appmod.EDITABLE_SCENE_FIELDS.index("needs_lip_sync")
    assert lip == cam + 2, appmod.EDITABLE_SCENE_FIELDS
    assert appmod.EDITABLE_SCENE_FIELDS[cam + 1] == "video_model"


def test_t2_55_scene_json_carries_needs_lip_sync_beside_camera():
    """GET returns the flag next to video_model/camera. Absent → false."""
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t255-json", title="T2-55 JSON Song",
                             album="T255", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _write_board(sid, song["slug"], "pg13", [
            _scene(1, needs_lip_sync=True, camera="wide establishing"),
            _scene(2, camera="close"),
        ])
        r = client.get(f"/api/songs/{sid}/storyboard/pg13")
        assert r.status_code == 200, r.text
        scenes = r.json()["scenes"]
        one = next(s for s in scenes if s.get("num") == 1)
        two = next(s for s in scenes if s.get("num") == 2)
        assert one["needs_lip_sync"] is True, one
        assert one["camera"] == "wide establishing", one
        assert two["needs_lip_sync"] is False, two
        keys = list(one.keys())
        assert "camera" in keys and "needs_lip_sync" in keys, keys
        assert keys.index("video_model") == keys.index("camera") + 1, keys
        assert keys.index("needs_lip_sync") == keys.index("video_model") + 1, keys


def test_t2_55_needs_lip_sync_is_editable_through_scene_fields():
    assert "needs_lip_sync" in appmod.EDITABLE_SCENE_FIELDS
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t255-edit", title="T2-55 Edit Song",
                             album="T255", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        json_path = _write_board(sid, song["slug"], "pg13", [
            _scene(1, camera="wide establishing"),
            _scene(2, needs_lip_sync=True, camera="close"),
        ])
        r = client.post(
            f"/api/songs/{sid}/storyboard/pg13/scene/1",
            json={"needs_lip_sync": True})
        assert r.status_code == 200, r.text
        payload = r.json()
        one = next(s for s in payload["scenes"] if s.get("num") == 1)
        two = next(s for s in payload["scenes"] if s.get("num") == 2)
        assert one["needs_lip_sync"] is True, one
        assert two["needs_lip_sync"] is True, two
        assert payload.get("scene", {}).get("needs_lip_sync") is True
        written = json.load(open(json_path))
        assert written["scenes"][0]["needs_lip_sync"] is True
        assert written["scenes"][1]["needs_lip_sync"] is True
        cleared = client.post(
            f"/api/songs/{sid}/storyboard/pg13/scene/2",
            json={"needs_lip_sync": False})
        assert cleared.status_code == 200, cleared.text
        written = json.load(open(json_path))
        assert written["scenes"][1]["needs_lip_sync"] is False


def test_t2_55_scene_row_shows_needs_lip_sync_beside_camera():
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t255-html", title="T2-55 HTML Song",
                             album="T255", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        json_path = _write_board(sid, song["slug"], "pg13", [
            _scene(1, needs_lip_sync=True, camera="wide establishing"),
            _scene(2, camera="close"),
        ])
        page = client.get(f"/songs/{sid}/storyboard/pg13")
        assert page.status_code == 200, page.text
        start = page.text.find('id="scene-1"')
        end = page.text.find('id="scene-2"')
        assert start != -1, page.text
        html = page.text[start:end if end != -1 else None]
        assert 'name="camera"' in html, html
        assert 'name="needs_lip_sync"' in html, html
        cam_at = html.index('name="camera"')
        lip_at = html.index('name="needs_lip_sync"')
        assert cam_at < lip_at, html[cam_at:lip_at + 40]
        assert 'type="checkbox"' in html[lip_at - 30:lip_at + 80]
        assert "checked" in html[lip_at - 30:lip_at + 120]
        saved = client.post(
            f"/songs/{sid}/storyboard/pg13/scene/2",
            data={"camera": "close", "needs_lip_sync": "true",
                  "name": "Scene 2", "cue": "Verse",
                  "duration_guidance": "5-7 sec", "motion": "walk",
                  "lighting": "neon", "location": "loc 2",
                  "story": "story 2", "image_prompt": "a rooftop",
                  "video_motion_prompt": "motion 2",
                  "negative_prompt": ""})
        assert saved.status_code == 200, saved.text
        written = json.load(open(json_path))
        assert written["scenes"][1]["needs_lip_sync"] is True
        assert written["scenes"][0]["needs_lip_sync"] is True


def test_t2_55_true_is_ltx_then_hop_not_s2v_only():
    """Mutation: true emits only an s2v graph → red."""
    scene = dict(SCENE, scene_number=1, length_seconds=5.0, needs_lip_sync=True)
    hop0 = build_song.clips_for_scene(scene, default_model="s2v")[0]
    assert hop0["model"] == "ltx25", hop0
    plan = build_song.clip_chain_plan([scene])
    models = [p["model"] for p in plan]
    assert models[0] == "ltx25", models
    assert "s2v" in models, models
    assert models != ["s2v"]


def test_t2_55_false_and_absent_are_ltx_only(tmp_path, monkeypatch):
    """Mutation: false → no hop. Absent → no hop."""
    for flag in (False, None):
        scene = dict(SCENE, scene_number=1, length_seconds=5.0)
        if flag is not None:
            scene["needs_lip_sync"] = flag
        plan = build_song.clip_chain_plan([scene])
        assert [p["model"] for p in plan] == ["ltx25"], plan

    outdir = _emit(tmp_path, monkeypatch, [
        dict(SCENE, scene_number=1, length_seconds=5.0, needs_lip_sync=False),
    ], "t255-false")
    graphs = _hop_graphs(outdir)
    assert len(graphs) == 1, graphs
    kinds = _classes(json.loads(graphs[0].read_text()))
    assert "EmptyLTXVLatentVideo" in kinds, kinds
    assert "WanSoundImageToVideo" not in kinds


def test_t2_55_true_emit_is_ltx_then_s2v(tmp_path, monkeypatch):
    outdir = _emit(tmp_path, monkeypatch, [
        dict(SCENE, scene_number=1, length_seconds=5.0, needs_lip_sync=True),
    ], "t255-true")
    graphs = _hop_graphs(outdir)
    assert len(graphs) >= 2, graphs
    ltx = json.loads((outdir / "clip_000.json").read_text())
    assert "EmptyLTXVLatentVideo" in _classes(ltx)
    assert "WanSoundImageToVideo" not in _classes(ltx)
    hop_kinds = []
    for path in graphs:
        if path.name == "clip_000.json":
            continue
        hop_kinds.append(_classes(json.loads(path.read_text())))
    assert hop_kinds, graphs
    assert any("WanSoundImageToVideo" in k for k in hop_kinds), hop_kinds
