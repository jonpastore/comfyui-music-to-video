"""T2-13e / T2-25 meter honesty: storyboard.html coverage hints.

A 77s board on a 237s track is mismatch=true and bare full-song POST 400s.
coverage.ok compares intent≈rendered only — it must not say "Pacing matches
the track", and the off path must not claim scenes are stretched/compressed
(nothing stretches when full-song refuses). Hint names regenerate / edit
duration_guidance to fill the track, or scene-scoped Render clip.

Mutation: restore "Pacing matches the track" → red.
Mutation: restore "stretched or compressed" → red.
Mutation: drop fill-the-track / Render clip / refuses language → red.
"""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import tiers

_SONG_LENGTH = 237.0
_SCENE_TIME = 77.0
_N_SCENES = 5
_GUIDANCE = _SCENE_TIME / _N_SCENES  # 15.4
_SCENE_SECONDS = 15.0


def _scene(n, guidance):
    return {
        "scene_number": n,
        "name": f"Scene {n}",
        "cue": "Verse",
        "duration_guidance": guidance,
        "story": f"story {n}",
        "camera": "wide",
        "motion": "walk",
        "lighting": "neon",
        "location": f"loc {n}",
        "image_prompt": f"a rooftop at night, scene {n}",
        "video_motion_prompt": f"motion {n}",
        "negative_prompt": "",
        "characters": [],
    }


def _write_board(sid, slug, tier, scenes, scene_seconds):
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


def test_t2_13e_meter_copy_77s_on_237s_is_honest():
    """77s/237s HTML: no false pacing/stretch; fill-track + Render clip hint."""
    tiers.ensure_builtins()
    with TestClient(appmod.app) as client:
        sid = db.upsert_song(
            "t213e-meter-copy", title="T2-13e Meter Copy",
            album="T213E", duration=_SONG_LENGTH)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        scenes = [
            _scene(n, f"{_GUIDANCE:g} sec")
            for n in range(1, _N_SCENES + 1)
        ]
        _write_board(sid, song["slug"], "pg13", scenes, _SCENE_SECONDS)

        meter = client.get(f"/api/songs/{sid}/storyboard/pg13/meter")
        assert meter.status_code == 200, meter.text
        body = meter.json()
        assert body["scene_time"] == _SCENE_TIME, body
        assert body["song_length"] == _SONG_LENGTH, body
        assert body["mismatch"] is True, body

        html = client.get(f"/songs/{sid}/storyboard/pg13")
        assert html.status_code == 200, html.text
        page = html.text

    assert 'id="storyboard-meter"' in page
    assert 'data-mismatch="true"' in page
    assert f'data-scene-time="{_SCENE_TIME:g}"' in page or (
        f'data-scene-time="{_SCENE_TIME}"' in page)
    assert f'data-song-length="{_SONG_LENGTH:g}"' in page or (
        f'data-song-length="{_SONG_LENGTH}"' in page)

    low = page.lower()
    assert "pacing matches the track" not in low, page
    assert "stretched or compressed" not in low, page
    assert "duration_guidance" in page
    assert "fill the track" in low, page
    assert "render clip" in low, page
    assert "refuses" in low, page
