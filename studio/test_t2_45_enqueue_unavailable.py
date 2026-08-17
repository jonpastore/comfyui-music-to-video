"""T2-45: mixed-model song refused before enqueue if a named model is False
on every reachable backend.

docs/TRD-2 W2 / T2-45: models.where() is three-valued. False is a
refusal. None is a candidate. Failing at clip 31 of 42 is the outcome
this exists to prevent.

Asserted through start_clips — the handler that enqueues (T6-A10).

Mutation: start_clips enqueues without asking where() → False arm red.
Mutation: treat None as False → None arm red.
Mutation: refuse a single-model song → single-model arm red.
Mutation: pass the cli spelling to where() → mapping arm red.
"""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import build_song
import db
import jobs
import models
import pipeline


S2V_FILE = models.CATALOG["wan22_s2v"]["file"]
LTX_FILE = models.CATALOG["ltx25"]["file"]

FLEET = [
    {"id": "0", "title": "cerberus", "status": "running",
     "address": "http://cerberus:8188"},
    {"id": "2", "title": "peaches", "status": "running",
     "address": "http://peaches:8188"},
    {"id": "9", "title": "ghost", "status": "running",
     "address": "http://ghost:8188"},
]
REACHABLE = FLEET[:2]
INFO = {
    "http://cerberus:8188": {
        "UNETLoader": {"input": {"required": {"unet_name": [[LTX_FILE]]}}},
    },
    "http://peaches:8188": {
        "UNETLoader": {"input": {"required": {"unet_name": [["other.safetensors"]]}}},
    },
}


def _scene(n, video_model=None):
    s = {"scene_number": n, "name": f"Scene {n}", "cue": "Verse",
         "duration_guidance": "5-7 sec", "story": f"story {n}",
         "camera": "wide establishing", "motion": "walk",
         "lighting": "neon", "location": f"loc {n}",
         "image_prompt": f"a rooftop at night, scene {n}",
         "video_motion_prompt": f"motion {n}", "negative_prompt": ""}
    if video_model is not None:
        s["video_model"] = video_model
    return s


def _write_board(sid, slug, tier, scenes):
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    sb = {"title": "T", "album": "A", "version": tier,
          "character_reference": "a sleek black feline DJ",
          "album_world_reference": "neon warehouse",
          "audio_lyrics": "[Verse]\nline\n", "scenes": scenes}
    json_path = os.path.join(outdir, f"{slug}_{tier}.json")
    md_path = os.path.join(outdir, f"{slug}_{tier}.md")
    json.dump(sb, open(json_path, "w"))
    open(md_path, "w").write("# storyboard\n")
    db.run("""INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created)
              VALUES (?,?,?,?,?,?)
              ON CONFLICT(song_id, tier) DO UPDATE SET json_path=excluded.json_path,
              md_path=excluded.md_path, scene_count=excluded.scene_count""",
           sid, tier, json_path, md_path, len(scenes), time.time())
    return json_path


def _a_ref(sid, tier, clip_idx, seed=7000, scene_number=None):
    d = os.path.join(db.DATA, "fixtures")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"ref_{sid}_{tier}_{clip_idx}_{seed}.png")
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    db.run("""INSERT INTO refs (song_id, tier, clip_idx, path, seed, approved, created, origin, scene_number)
              VALUES (?,?,?,?,?,1,?, 'gen', ?)""",
           sid, tier, clip_idx, path, seed, time.time(), scene_number)


def _ready_song(slug, scenes):
    sid = db.upsert_song(slug, title=slug, duration=12.0)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    _write_board(sid, song["slug"], "pg13", scenes)
    heads = build_song.scene_heads(scenes, "ltx25")
    assert heads, "fixture produced no scene heads"
    for sn, ci in heads.items():
        _a_ref(sid, "pg13", ci, seed=17000 + ci, scene_number=sn)
    return sid


def _clips_jobs(sid):
    return [j for j in jobs.recent(1000)
            if j["kind"] == "clips" and j["song_id"] == sid]


def _pin_fleet(info):
    was = models._object_info, models._system_stats, pipeline.swarm_backends
    models._object_info = lambda url=None: info.get(url)
    models._system_stats = lambda url=None: None
    pipeline.swarm_backends = lambda: list(FLEET)
    return was


def _restore_fleet(was):
    models._object_info, models._system_stats, pipeline.swarm_backends = was


def test_t2_45_named_cli_maps_to_catalogue_key():
    """where() keys the catalogue. A scene stores the renderer cli."""
    assert models.video_key("s2v") == "wan22_s2v"
    assert models.video_key("wan22_s2v") == "wan22_s2v"
    assert models.video_key("ltx25") == "ltx25"
    assert models.video_key("") is None
    scenes = [_scene(1, "s2v"), _scene(2, "ltx25")]
    assert models.named_video_keys(scenes, default="ltx25") == [
        "wan22_s2v", "ltx25"]
    omitted = [_scene(1, "s2v"), _scene(2)]
    assert models.named_video_keys(omitted, default="ltx25") == [
        "wan22_s2v", "ltx25"]
    single = [_scene(1, "s2v"), _scene(2, "s2v")]
    assert models.named_video_keys(single, default="ltx25") == ["wan22_s2v"]


def test_t2_45_false_on_every_reachable_is_unavailable():
    """Real where(): cerberus+peaches answered and lack s2v → refuse."""
    was = _pin_fleet(INFO)
    try:
        assert models.where("wan22_s2v", REACHABLE) == []
        assert models.unavailable_on_reachable("wan22_s2v", REACHABLE) is True
        assert models.unavailable_on_reachable("ltx25", REACHABLE) is False
        mixed = [_scene(1, "s2v"), _scene(2, "ltx25")]
        assert models.mixed_unavailable(mixed, REACHABLE, default="ltx25") == [
            "wan22_s2v"]
        assert models.mixed_unavailable(
            [_scene(1, "s2v"), _scene(2, "s2v")], REACHABLE,
            default="s2v") == []
    finally:
        _restore_fleet(was)


def test_t2_45_none_is_a_candidate_not_a_refusal():
    """A ghost that never answered keeps the mixed song enqueueable."""
    was = _pin_fleet(INFO)
    try:
        ghost = models.where("wan22_s2v", FLEET)
        assert ghost and ghost[0]["id"] == "9", ghost
        assert ghost[0]["confirmed"] is False
        assert models.unavailable_on_reachable("wan22_s2v", FLEET) is False
        mixed = [_scene(1, "s2v"), _scene(2, "ltx25")]
        assert models.mixed_unavailable(mixed, FLEET, default="ltx25") == []
        assert models.unavailable_on_reachable("wan22_s2v", None) is False
        assert models.unavailable_on_reachable("wan22_s2v", []) is False
        assert models.mixed_unavailable(mixed, None, default="ltx25") == []
    finally:
        _restore_fleet(was)


def test_t2_45_start_clips_refuses_before_enqueue():
    """POST /clips is 400 and no clips job is written."""
    was = _pin_fleet(INFO)
    try:
        pipeline.swarm_backends = lambda: list(REACHABLE)
        with TestClient(appmod.app) as client:
            sid = _ready_song("t245-false", [
                _scene(1, "s2v"), _scene(2, "ltx25")])
            before = _clips_jobs(sid)
            r = client.post(f"/songs/{sid}/clips",
                            data={"tier": "pg13", "video_model": "ltx25"},
                            follow_redirects=False)
            assert r.status_code == 400, r.text
            assert "wan22_s2v" in r.text
            assert "enqueue" in r.text.lower() or "unavailable" in r.text.lower()
            assert _clips_jobs(sid) == before
    finally:
        _restore_fleet(was)


def test_t2_45_start_clips_enqueues_when_none_is_a_candidate():
    """The ghost is a candidate. Mixed song still enqueues."""
    was = _pin_fleet(INFO)
    try:
        with TestClient(appmod.app) as client:
            sid = _ready_song("t245-none", [
                _scene(1, "s2v"), _scene(2, "ltx25")])
            before = len(_clips_jobs(sid))
            r = client.post(f"/songs/{sid}/clips",
                            data={"tier": "pg13", "video_model": "ltx25"},
                            follow_redirects=False)
            assert r.status_code == 303, r.text
            assert len(_clips_jobs(sid)) == before + 1
    finally:
        _restore_fleet(was)


def test_t2_45_single_model_song_is_not_this_check():
    """T2-45 is the mixed-model gate. One named model still enqueues."""
    was = _pin_fleet(INFO)
    try:
        pipeline.swarm_backends = lambda: list(REACHABLE)
        with TestClient(appmod.app) as client:
            sid = _ready_song("t245-single", [
                _scene(1, "s2v"), _scene(2, "s2v")])
            before = len(_clips_jobs(sid))
            r = client.post(f"/songs/{sid}/clips",
                            data={"tier": "pg13", "video_model": "s2v"},
                            follow_redirects=False)
            assert r.status_code == 303, r.text
            assert len(_clips_jobs(sid)) == before + 1
    finally:
        _restore_fleet(was)
