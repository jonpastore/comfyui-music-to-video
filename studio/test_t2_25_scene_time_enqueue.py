"""T2-25: scene-time mismatch is refused before full-song clips enqueue.

docs/TRD-2 §5.1 / T2-13e seam: a song whose scenes do not sum to its
duration is flagged before any full-song render is queued. GET /meter
already flags (T2-23); this is the gate that would have caught the
scene_seconds defect on the first generation instead of the hundredth.

Scene-scoped Render clip (scene= / clip_idx=) matches build_song --only
and still enqueues on a short board; bare full-song POST stays 400.

Both arms: an in-tolerance board still enqueues; a deliberately short
board is 400 and writes no clips job.

Mutation: only flag on GET /meter, enqueue anyway → miss arm fails.
Mutation: always refuse clips → match arm fails.
Mutation: refuse with a generic 400 that missing-refs already returns
→ message arm fails.
Mutation: scene-scoped POST still refuse a short board → seam arm fails.
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


def _write_board(sid, slug, tier, scenes, scene_seconds=30.0):
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


def _approve_refs(sid, tier, scenes):
    heads = build_song.scene_heads(scenes, "ltx25")
    for sn, ci in heads.items():
        db.run(
            """INSERT INTO refs
               (song_id, tier, clip_idx, path, seed, approved, created, scene_number)
               VALUES (?,?,?,?,?,?,?,?)""",
            sid, tier, ci, f"/fake/t225_{sid}_{ci}.png", 17000 + ci, 1, time.time(), sn)


def _n_clips_jobs(sid):
    return len(db.q("SELECT id FROM jobs WHERE song_id=? AND kind='clips'", sid))


def test_t2_25_mismatch_refused_before_clips_enqueue():
    """In-tolerance still queues; 20s of guidance on a 120s song does not."""
    tiers.ensure_builtins()
    song_length = 120.0
    scene_seconds = 30.0
    with TestClient(appmod.app) as client:
        sid = db.upsert_song(
            "t225-enqueue", title="T2-25 Enqueue Song",
            album="T225", duration=song_length)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        scenes = [_scene(n, "30 sec") for n in (1, 2, 3, 4)]
        _write_board(sid, song["slug"], "pg13", scenes, scene_seconds=scene_seconds)
        _approve_refs(sid, "pg13", scenes)
        match_meter = client.get(f"/api/songs/{sid}/storyboard/pg13/meter")
        assert match_meter.status_code == 200, match_meter.text
        assert match_meter.json()["mismatch"] is False, match_meter.json()
        before_match = _n_clips_jobs(sid)
        match = client.post(f"/songs/{sid}/clips", data={"tier": "pg13"},
                            follow_redirects=False)
        assert match.status_code == 303, match.text
        assert _n_clips_jobs(sid) == before_match + 1

        _write_board(sid, song["slug"], "pg13",
                     [_scene(n, "5 sec") for n in (1, 2, 3, 4)],
                     scene_seconds=scene_seconds)
        miss_meter = client.get(f"/api/songs/{sid}/storyboard/pg13/meter")
        assert miss_meter.status_code == 200, miss_meter.text
        miss_body = miss_meter.json()
        assert miss_body["scene_time"] == 20.0, miss_body
        assert miss_body["song_length"] == song_length, miss_body
        assert miss_body["mismatch"] is True, miss_body
        before_miss = _n_clips_jobs(sid)
        miss = client.post(f"/songs/{sid}/clips", data={"tier": "pg13"},
                           follow_redirects=False)
        assert miss.status_code == 400, miss.text
        low = miss.text.lower()
        assert "scene time" in low or "scene_time" in low, miss.text
        assert "120" in miss.text, miss.text
        assert _n_clips_jobs(sid) == before_miss, miss.text


def test_t2_25_scene_scoped_skips_mismatch_refuse():
    """Short board + scene=/clip_idx= still enqueues; bare full-song 400s.

    T2-13e/T2-25 seam: Render clip matches build_song --only.
    Mutation: scene-scoped still refuse → this fails.
    Mutation: bare full-song enqueue → full-song arm fails.
    """
    tiers.ensure_builtins()
    song_length = 120.0
    scene_seconds = 30.0
    with TestClient(appmod.app) as client:
        sid = db.upsert_song(
            "t225-scene-scoped", title="T2-25 Scene Scoped",
            album="T225", duration=song_length)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        short = [_scene(n, "5 sec") for n in (1, 2, 3, 4)]
        _write_board(sid, song["slug"], "pg13", short, scene_seconds=scene_seconds)
        _approve_refs(sid, "pg13", short)
        meter = client.get(f"/api/songs/{sid}/storyboard/pg13/meter")
        assert meter.status_code == 200, meter.text
        assert meter.json()["mismatch"] is True, meter.json()

        before = _n_clips_jobs(sid)
        by_scene = client.post(
            f"/songs/{sid}/clips",
            data={"tier": "pg13", "scene": "1"},
            follow_redirects=False)
        assert by_scene.status_code == 303, by_scene.text
        assert _n_clips_jobs(sid) == before + 1, by_scene.text

        before_clip = _n_clips_jobs(sid)
        by_idx = client.post(
            f"/songs/{sid}/clips",
            data={"tier": "pg13", "clip_idx": "0"},
            follow_redirects=False)
        assert by_idx.status_code == 303, by_idx.text
        assert _n_clips_jobs(sid) == before_clip + 1, by_idx.text

        before_full = _n_clips_jobs(sid)
        full = client.post(f"/songs/{sid}/clips", data={"tier": "pg13"},
                           follow_redirects=False)
        assert full.status_code == 400, full.text
        low = full.text.lower()
        assert "scene time" in low or "scene_time" in low, full.text
        assert _n_clips_jobs(sid) == before_full, full.text
