"""T2-24: meter reports this song's clip_seconds, not a constant.

docs/TRD-2 §5.1: GET /api/songs/{id}/storyboard/{tier}/meter reads the
real per-song clip length. Same song at two scene_seconds reports two
clip lengths.

A meter hardcoding 4.8125 s (CHUNK) passes a presence check and fails
this differential. Returning raw scene_seconds also fails: 15.0 is not
the legal 8n+1 length.

Mutation: hardcode clip_seconds to CHUNK → both arms equal, this fails.
Mutation: return scene_seconds unchanged → 15.0 is not clip_seconds(15).
"""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import build_song
import db
import tiers


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


def _meter(client, sid, tier="pg13"):
    r = client.get(f"/api/songs/{sid}/storyboard/{tier}/meter")
    assert r.status_code == 200, r.text
    return r.json()


def test_t2_24_meter_reports_this_songs_clip_seconds():
    """Same song at 15 s and 30 s yields two clip lengths."""
    tiers.ensure_builtins()
    with TestClient(appmod.app) as client:
        sid = db.upsert_song(
            "t224-meter", title="T2-24 Meter Song",
            album="T224", duration=120.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _write_board(sid, song["slug"], "pg13",
                     [_scene(n, "30 sec") for n in (1, 2, 3, 4)])

        reported = []
        for scene_seconds in (15.0, 30.0):
            db.run(
                "UPDATE storyboards SET scene_seconds=? WHERE song_id=? AND tier=?",
                scene_seconds, sid, "pg13")
            meter = _meter(client, sid)
            want = build_song.clip_seconds(scene_seconds)
            assert "clip_seconds" in meter, meter
            assert meter["clip_seconds"] == want, meter
            assert meter["clip_seconds"] != scene_seconds, meter
            assert meter["clip_seconds"] != build_song.CHUNK, meter
            reported.append(meter["clip_seconds"])

        assert reported[0] != reported[1]
        assert build_song.clip_seconds(15.0) != build_song.clip_seconds(30.0)
