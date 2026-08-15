"""T2-27: each scene JSON carries its reference image next to the description.

docs/TRD-2 §5.2: GET /api/songs/{id}/storyboard/{tier} scenes carry the
per-scene stills alongside the editable fields (image_prompt / story /
video_motion_prompt). Payload presence only — the HTML strip already
exists; this is the JSON a client that is not that page can read.

Mutation: omit refs on the scene object → red.
Mutation: return refs only at the top of the payload → red.
Mutation: copy another scene's still onto this scene → red.
A still for another tier stays out.
"""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import tiers


def _scene(n, characters=None):
    return {
        "scene_number": n,
        "name": f"Scene {n}",
        "cue": "Verse",
        "duration_guidance": "12 sec",
        "story": f"story {n}",
        "camera": "wide",
        "motion": "walk",
        "lighting": "neon",
        "location": f"loc {n}",
        "image_prompt": f"a rooftop at night, scene {n}",
        "video_motion_prompt": f"motion {n}",
        "negative_prompt": "",
        "characters": list(characters or []),
    }


def _write_board(sid, slug, tier, scenes, scene_seconds=12.0):
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
        """INSERT INTO storyboards
           (song_id, tier, json_path, md_path, scene_count, created, scene_seconds)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(song_id, tier) DO UPDATE SET
           json_path=excluded.json_path, md_path=excluded.md_path,
           scene_count=excluded.scene_count, scene_seconds=excluded.scene_seconds""",
        sid, tier, json_path, md_path, len(scenes), time.time(), scene_seconds)
    return json_path


def _ref(sid, tier, clip_idx, path, seed, approved=1):
    db.run(
        """INSERT INTO refs (song_id, tier, clip_idx, path, seed, approved, created)
           VALUES (?,?,?,?,?,?,?)""",
        sid, tier, clip_idx, path, seed, approved, time.time())


def _by_num(payload):
    scenes = payload.get("scenes")
    assert isinstance(scenes, list) and scenes, payload
    out = {}
    for scene in scenes:
        assert isinstance(scene, dict), scene
        num = scene.get("scene_number", scene.get("num"))
        assert num, scene
        assert num not in out, f"duplicate scene: {num}"
        out[num] = scene
    return out


def _ref_paths(scene):
    """Every still path hanging off this scene object. Missing key → empty."""
    refs = scene.get("refs")
    if not isinstance(refs, list):
        return []
    paths = []
    for item in refs:
        if not isinstance(item, dict):
            continue
        if item.get("path"):
            paths.append(item["path"])
        for cand in item.get("candidates") or []:
            if isinstance(cand, dict) and cand.get("path"):
                paths.append(cand["path"])
    return paths


def test_t2_27_scene_json_carries_its_reference_next_to_description():
    """Two scenes, two stills: each scene JSON has only its own image."""
    tiers.ensure_builtins()
    album = "T227 Album"
    scene_seconds = 12.0
    with TestClient(appmod.app) as client:
        sid = db.upsert_song(
            "t227-scene-refs", title="T2-27 Scene Refs Song",
            album=album, duration=24.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _write_board(sid, song["slug"], "pg13", [_scene(1), _scene(2)],
                     scene_seconds=scene_seconds)

        nclips = appmod.clip_count(song, scene_seconds)
        assert nclips >= 2, nclips
        rows, _ = appmod.storyboard_scenes(
            song, {"scenes": [_scene(1), _scene(2)]}, "pg13",
            scene_seconds=scene_seconds)
        by_row = {r["num"]: r for r in rows}
        clips1 = list(by_row[1]["clips"])
        clips2 = list(by_row[2]["clips"])
        assert clips1 and clips2, (clips1, clips2)
        assert set(clips1).isdisjoint(set(clips2)), (clips1, clips2)

        path1 = "/tmp/t227_scene1.png"
        path2 = "/tmp/t227_scene2.png"
        other_tier = "/tmp/t227_other_tier.png"
        _ref(sid, "pg13", clips1[0], path1, 5151)
        _ref(sid, "pg13", clips2[0], path2, 129080599)
        _ref(sid, "r", clips1[0], other_tier, 4748)

        r = client.get(f"/api/songs/{sid}/storyboard/pg13")
        assert r.status_code == 200, r.text
        payload = r.json()
        scenes = _by_num(payload)

        s1, s2 = scenes[1], scenes[2]
        # alongside the editable description, not a sibling of scenes[]
        for scene in (s1, s2):
            assert "refs" in scene, scene
            assert isinstance(scene["refs"], list), scene
            assert scene.get("image_prompt"), scene
            assert scene.get("story"), scene
            assert scene.get("video_motion_prompt") is not None, scene
        # A top-level refs list is not this: the still belongs on the scene.

        p1, p2 = _ref_paths(s1), _ref_paths(s2)
        assert path1 in p1, (s1, p1)
        assert path2 not in p1, p1
        assert path2 in p2, (s2, p2)
        assert path1 not in p2, p2
        assert other_tier not in p1 and other_tier not in p2

        urls1 = []
        for item in s1["refs"]:
            if item.get("url"):
                urls1.append(item["url"])
            for cand in item.get("candidates") or []:
                if isinstance(cand, dict) and cand.get("url"):
                    urls1.append(cand["url"])
        assert urls1, s1
        assert all(u.startswith("/media/") for u in urls1), urls1
