"""T2-11: a chained clip is not ready until its predecessor has landed.

docs/TRD-2 T2-11: the queue expresses ready separately from queued; a chain
handed out in the wrong order is the race this exists to catch. T6-2 is the
depends_on primitive on jobs._claim. This criterion is that start_clips wires
it for scene chains (T2-48 over-ceiling splits).

Asserted through start_clips — the handler that enqueues (T6-A10).

Mutation: start_clips enqueues one batch clips job with no depends_on → red.
Mutation: enqueue with depends_on but _claim ignores it → T6-2 already red;
this test still fails on the missing _depends_on in args_json.
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


FLEET = [
    {"id": "0", "title": "cerberus", "status": "running",
     "address": "http://cerberus:8188"},
]
INFO = {
    "http://cerberus:8188": {
        "UNETLoader": {"input": {"required": {"unet_name": [
            [models.CATALOG["ltx25"]["file"]]
        ]}}},
    },
}


def _scene(n, length_seconds, video_model="ltx25"):
    return {
        "scene_number": n, "name": f"Scene {n}", "cue": "Verse",
        "duration_guidance": f"{length_seconds} sec", "story": f"story {n}",
        "camera": "wide establishing", "motion": "walk",
        "lighting": "neon", "location": f"loc {n}",
        "image_prompt": f"a rooftop at night, scene {n}",
        "video_motion_prompt": f"motion {n}", "negative_prompt": "",
        "length_seconds": float(length_seconds),
        "video_model": video_model,
    }


def _write_board(sid, slug, tier, scenes, scene_seconds):
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
    db.run("""INSERT INTO storyboards
                (song_id, tier, json_path, md_path, scene_count, scene_seconds, created)
              VALUES (?,?,?,?,?,?,?)
              ON CONFLICT(song_id, tier) DO UPDATE SET
                json_path=excluded.json_path, md_path=excluded.md_path,
                scene_count=excluded.scene_count,
                scene_seconds=excluded.scene_seconds""",
           sid, tier, json_path, md_path, len(scenes), scene_seconds, time.time())
    return json_path


def _a_ref(sid, tier, clip_idx, seed=7000):
    d = os.path.join(db.DATA, "fixtures")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"ref_{sid}_{tier}_{clip_idx}_{seed}.png")
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    db.run("""INSERT INTO refs (song_id, tier, clip_idx, path, seed, approved, created, origin)
              VALUES (?,?,?,?,?,1,?, 'gen')""",
           sid, tier, clip_idx, path, seed, time.time())


def _clips_jobs(sid):
    return [j for j in jobs.recent(1000)
            if j["kind"] == "clips" and j["song_id"] == sid]


def _depends_on(job):
    try:
        args = json.loads(job["args_json"] or "{}")
    except ValueError:
        args = {}
    return args.get("_depends_on")


def _pin_fleet():
    was = models._object_info, models._system_stats, pipeline.swarm_backends
    models._object_info = lambda url=None: INFO.get(url)
    models._system_stats = lambda url=None: None
    pipeline.swarm_backends = lambda: list(FLEET)
    return was


def _restore_fleet(was):
    models._object_info, models._system_stats, pipeline.swarm_backends = was


def test_t2_11_clip_chain_plan_marks_successor_depends_on():
    """T2-48 30s ltx25 → two clips; second depends on first.

    Mutation: always depends_on=None → start_clips can stay a single job.
    """
    scenes = [_scene(1, 30.0)]
    plan = build_song.clip_chain_plan(scenes, "ltx25")
    assert len(plan) == 2, plan
    assert plan[0]["clip_idx"] == 0 and plan[0]["depends_on"] is None
    assert plan[1]["clip_idx"] == 1 and plan[1]["depends_on"] == 0
    # Independent first clips of two scenes do not wait on each other.
    two = build_song.clip_chain_plan(
        [_scene(1, 15.0), _scene(2, 15.0)], "ltx25")
    assert [p["depends_on"] for p in two] == [None, None], two


def _park_foreign_jobs(keep_ids):
    """Cancel other queued/running jobs so _claim only sees keep_ids.

    Shared studio.db + single worker (T6-1) leave foreign work that would
    steal the next claim. Production claim semantics are unchanged.
    """
    keep = tuple(keep_ids)
    if not keep:
        return
    placeholders = ",".join("?" * len(keep))
    now = time.time()
    db.run(
        f"""UPDATE jobs SET status='cancelled', finished=?
            WHERE status IN ('queued','running','cancelling')
              AND id NOT IN ({placeholders})""",
        now, *keep)
    # Worker may already have taken the chain head; put keep back to queued.
    db.run(
        f"""UPDATE jobs SET status='queued', started=NULL, finished=NULL,
                   error=NULL, progress=NULL
            WHERE id IN ({placeholders})""",
        *keep)


def test_t2_11_start_clips_wires_depends_on_and_claim_waits():
    """POST /clips enqueues the chain with depends_on; _claim skips the
    successor until the predecessor is done.

    Mutation: one batch job, no _depends_on → red.
    Mutation: wire depends_on but claim ignores it → successor pulled early.
    """
    was = _pin_fleet()
    cap_was = jobs._capability_where
    jobs._capability_where = None
    try:
        scenes = [_scene(1, 30.0)]
        plan = build_song.clip_chain_plan(scenes, "ltx25")
        assert any(p["depends_on"] is not None for p in plan), plan

        # duration matches the scene so the storyboard is in-tolerance for T2-25
        sid = db.upsert_song("t211-chain", title="Chain", duration=30.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _write_board(sid, song["slug"], "pg13", scenes, scene_seconds=30.0)
        for p in plan:
            _a_ref(sid, "pg13", p["clip_idx"], seed=9000 + p["clip_idx"])

        before = _clips_jobs(sid)
        with TestClient(appmod.app) as client:
            r = client.post(
                f"/songs/{sid}/clips",
                data={"tier": "pg13", "video_model": "ltx25"},
                follow_redirects=False)
        assert r.status_code == 303, r.text
        created = [j for j in _clips_jobs(sid) if j not in before
                   and j["id"] not in {b["id"] for b in before}]
        # re-fetch: before is stale row objects
        created = sorted(
            [j for j in _clips_jobs(sid)
             if j["id"] not in {b["id"] for b in before}],
            key=lambda j: j["id"])
        assert len(created) == 2, (
            f"expected one job per chain clip, got {len(created)}: "
            f"{[(j['id'], _depends_on(j), j['args_json']) for j in created]}")

        by_clip = {}
        for j in created:
            args = json.loads(j["args_json"] or "{}")
            by_clip[args["clip_idx"]] = j
        assert set(by_clip) == {0, 1}, by_clip.keys()
        pred = by_clip[0]
        succ = by_clip[1]
        assert _depends_on(pred) is None, pred["args_json"]
        assert _depends_on(succ) == pred["id"], (
            f"successor job {succ['id']} depends_on={_depends_on(succ)}, "
            f"want predecessor job {pred['id']}")

        # Isolate from leftover queued work. Stop the single worker so it
        # cannot snatch the chain head after enqueue wakes it (T6-1).
        jobs.stop()
        _park_foreign_jobs([pred["id"], succ["id"]])
        # Regression: a foreign running job must not hide the chain head.
        foreign = jobs.enqueue("clips", {"who": "t211-foreign-running"},
                               song_id=None)
        db.run("UPDATE jobs SET status='running', started=? WHERE id=?",
               time.time(), foreign)

        # T6-2 primitive: ready ≠ queued
        first = jobs._claim()
        assert first is not None and first["id"] == pred["id"], (
            f"_claim handed out {first['id'] if first else None}, not the "
            f"chain head {pred['id']}")
        assert jobs._claim() is None, (
            "successor was pulled before its predecessor landed")
        assert jobs.get(succ["id"])["status"] == "queued"
        assert jobs.get(foreign)["status"] == "running"

        db.run("UPDATE jobs SET status='done', finished=? WHERE id=?",
               time.time(), pred["id"])
        pulled = jobs._claim()
        assert pulled is not None and pulled["id"] == succ["id"], (
            f"predecessor done but successor {succ['id']} not pulled "
            f"(got {pulled['id'] if pulled else None})")
    finally:
        jobs._capability_where = cap_was
        try:
            jobs.start()
        except Exception:
            pass
        _restore_fleet(was)


def test_t2_11_no_chain_still_one_batch_job():
    """Scenes under the ceiling stay one clips job — not a per-clip rewrite.

    Mutation: always fan out one job per clip → red here and T2-45.
    """
    was = _pin_fleet()
    try:
        scenes = [_scene(1, 10.0), _scene(2, 10.0)]
        plan = build_song.clip_chain_plan(scenes, "ltx25")
        assert all(p["depends_on"] is None for p in plan), plan

        sid = db.upsert_song("t211-batch", title="Batch", duration=20.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _write_board(sid, song["slug"], "pg13", scenes, scene_seconds=10.0)
        n = appmod.clip_count(song, 10.0)
        assert n > 0
        for i in range(n):
            _a_ref(sid, "pg13", i, seed=9100 + i)

        before_ids = {j["id"] for j in _clips_jobs(sid)}
        with TestClient(appmod.app) as client:
            r = client.post(
                f"/songs/{sid}/clips",
                data={"tier": "pg13", "video_model": "ltx25"},
                follow_redirects=False)
        assert r.status_code == 303, r.text
        created = [j for j in _clips_jobs(sid) if j["id"] not in before_ids]
        assert len(created) == 1, created
        assert _depends_on(created[0]) is None
        args = json.loads(created[0]["args_json"] or "{}")
        assert "clip_idx" not in args, args
    finally:
        _restore_fleet(was)
