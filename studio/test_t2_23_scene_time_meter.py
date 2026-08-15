"""T2-23: API reports total scene time against song length and flags a miss.

docs/TRD-2 §5.1: GET /api/songs/{id}/storyboard/{tier}/meter reports the
sum of scene time against the song duration, and flags a mismatch beyond
a stated tolerance.

Both arms: an in-tolerance board returns the numbers and is NOT flagged;
a deliberately short board IS. Returning the two numbers and never
flagging satisfies the presence half alone (T6-A1 already does that).

Mutation: always return the numbers, never set mismatch → miss arm fails.
Mutation: always set mismatch → match arm fails.
Mutation: report rendered clip total as song_length → song_length is not
the song duration.
"""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
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


def test_t2_23_meter_reports_scene_time_against_song_length_and_flags_a_miss():
    """In-tolerance is not flagged; a 20s board on a 120s song is."""
    tiers.ensure_builtins()
    song_length = 120.0
    with TestClient(appmod.app) as client:
        sid = db.upsert_song(
            "t223-meter", title="T2-23 Meter Song",
            album="T223", duration=song_length)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)

        _write_board(sid, song["slug"], "pg13",
                     [_scene(n, "30 sec") for n in (1, 2, 3, 4)])
        match = _meter(client, sid)
        assert match["scene_time"] == 120.0, match
        assert match["song_length"] == song_length, match
        assert match["song_length"] == song["duration"], match
        assert match["tolerance"] == appmod.SCENE_TIME_TOLERANCE, match
        assert match["mismatch"] is False, match

        _write_board(sid, song["slug"], "pg13",
                     [_scene(n, "5 sec") for n in (1, 2, 3, 4)])
        miss = _meter(client, sid)
        assert miss["scene_time"] == 20.0, miss
        assert miss["song_length"] == song_length, miss
        assert miss["tolerance"] == appmod.SCENE_TIME_TOLERANCE, miss
        allowed = song_length * miss["tolerance"]
        assert abs(miss["scene_time"] - miss["song_length"]) > allowed
        assert miss["mismatch"] is True, miss
