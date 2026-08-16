"""T6-A2 / storyboard: HTML page and JSON endpoint report the same numbers.

docs/TRD-6 §0.1: GET /songs/{id}/storyboard/{tier} HTML and
GET /api/songs/{id}/storyboard/{tier} report the same scene_time,
song_length, clip_seconds, scene_count and mismatch from
storyboard_service.payload. Two answers means two implementations.

Distinctive numbers so two empty answers cannot pass. scene_count is
service-owned: a template that recomputes from len(scene_rows) fails the
stub arm when the service returns a count that is not the list length.
"""
import json
import os
import re
import time

from fastapi.testclient import TestClient

import app as appmod
import build_song
import db
import storyboard_service
import tiers

# Distinctive fixture values — not 0/0, not CHUNK, not equal to each other.
_SONG_LENGTH = 120.0
_SCENE_GUIDANCE = 17.0  # five scenes → scene_time 85
_N_SCENES = 5
_SCENE_TIME = _SCENE_GUIDANCE * _N_SCENES  # 85.0
_SCENE_SECONDS = 15.0
_CLIP_SECONDS = build_song.clip_seconds(_SCENE_SECONDS)
_STUB_SCENE_COUNT = 99  # not _N_SCENES — named mutation for len()-recompute


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
        """INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count,
                                    scene_seconds, created)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(song_id, tier) DO UPDATE SET json_path=excluded.json_path,
           md_path=excluded.md_path, scene_count=excluded.scene_count,
           scene_seconds=excluded.scene_seconds""",
        sid, tier, json_path, md_path, len(scenes), scene_seconds, time.time())
    return json_path


def _attr(page, name):
    m = re.search(rf'data-{name}="([^"]*)"', page)
    assert m, f"missing data-{name} on storyboard page: {page[:500]}"
    return m.group(1)


def test_t6_a2_html_and_json_report_the_same_storyboard_numbers(monkeypatch):
    """HTML and JSON agree on distinctive meter numbers from one service.

    Real board: 5×17s guidance on 120s song, scene_seconds=15 → legal
    clip_seconds, mismatch True. Stub arm: scene_count forced to 99 so a
    template that counts scene_rows goes red.
    """
    tiers.ensure_builtins()
    assert _CLIP_SECONDS != _SCENE_SECONDS
    assert _CLIP_SECONDS != build_song.CHUNK
    assert _SCENE_TIME != _SONG_LENGTH
    assert _STUB_SCENE_COUNT != _N_SCENES

    with TestClient(appmod.app) as client:
        sid = db.upsert_song(
            "t6a2-sb", title="T6-A2 Storyboard Song",
            album="T6A2SB", duration=_SONG_LENGTH)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        scenes = [_scene(n, f"{_SCENE_GUIDANCE:g} sec")
                  for n in range(1, _N_SCENES + 1)]
        _write_board(sid, song["slug"], "pg13", scenes, _SCENE_SECONDS)

        # Capture real service numbers first, then stub scene_count off list length.
        real = storyboard_service.payload(sid, "pg13")
        assert real["scene_time"] == _SCENE_TIME, real
        assert real["song_length"] == _SONG_LENGTH, real
        assert real["clip_seconds"] == _CLIP_SECONDS, real
        assert real["scene_count"] == _N_SCENES, real
        assert real["mismatch"] is True, real

        stub = dict(real)
        stub["scene_count"] = _STUB_SCENE_COUNT

        def _stub_payload(song_id, tier):
            return stub

        monkeypatch.setattr(storyboard_service, "payload", _stub_payload)
        monkeypatch.setattr(appmod.storyboard_service, "payload", _stub_payload)

        html = client.get(f"/songs/{sid}/storyboard/pg13")
        js = client.get(f"/api/songs/{sid}/storyboard/pg13")

    assert html.status_code == 200, html.text
    page = html.text
    assert js.status_code == 200, js.text
    ctype = (js.headers.get("content-type") or "").split(";")[0].strip()
    assert ctype == "application/json", (
        f"/api/songs/{{id}}/storyboard/{{tier}} returned "
        f"{ctype or 'no content-type'}, not JSON: {js.text[:200]}")
    assert "<html" not in js.text.lower(), js.text[:200]
    body = js.json()

    html_scene_time = float(_attr(page, "scene-time"))
    html_song_length = float(_attr(page, "song-length"))
    html_clip_seconds = float(_attr(page, "clip-seconds"))
    html_scene_count = int(_attr(page, "scene-count"))
    html_mismatch = _attr(page, "mismatch")

    assert html_scene_time == body["scene_time"] == _SCENE_TIME, (
        html_scene_time, body.get("scene_time"), body)
    assert html_song_length == body["song_length"] == _SONG_LENGTH, (
        html_song_length, body.get("song_length"), body)
    assert html_clip_seconds == body["clip_seconds"] == _CLIP_SECONDS, (
        html_clip_seconds, body.get("clip_seconds"), body)
    # Service-owned count, not len(scenes). Template that counts rows → red.
    assert html_scene_count == body["scene_count"] == _STUB_SCENE_COUNT, (
        html_scene_count, body.get("scene_count"), body)
    assert html_scene_count != _N_SCENES, (
        "fixture must keep scene_count off list length so len()-recompute fails")
    assert body["mismatch"] is True, body
    assert html_mismatch == "true", html_mismatch
    assert str(_SCENE_TIME) in page or f"{_SCENE_TIME:g}" in page
    assert str(_SONG_LENGTH) in page or f"{_SONG_LENGTH:g}" in page
