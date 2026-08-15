"""T2-13b: approved refs survive re-planning the same storyboard.

docs/TRD-2 F-3 / T2-13b: read `refs` before and after re-planning the same
storyboard and assert the set of approved (clip_idx, seed) is identical.
That is the check that stops a re-plan quietly invalidating a human's
approvals.

Asserted through h_storyboard — the handler the route enqueues (T6-A10).
A TestClient wait on the shared worker stays green while another file's
_isolate leaves that worker on a different DB.

Mutation: h_storyboard deletes or unapproves refs → this fails.
Mutation: remap clip_idx on re-plan → this fails.
"""
import os
import tempfile
import time

import app as appmod
import db
import jobs


def _isolate():
    data = tempfile.mkdtemp(prefix="t213b_")
    was = (db.DATA, db.DB_PATH, jobs.LOGS)
    db.DATA = data
    db.DB_PATH = os.path.join(data, "t.db")
    db._local.__dict__.clear()
    jobs.LOGS = os.path.join(data, "logs")
    return data, was


def _restore(was):
    db.DATA, db.DB_PATH, jobs.LOGS = was
    db._local.__dict__.clear()


def _approved_keys(sid, tier):
    return {(r["clip_idx"], r["seed"]) for r in db.q(
        "SELECT clip_idx, seed FROM refs WHERE song_id=? AND tier=? AND approved=1",
        sid, tier)}


def test_t2_13b_approved_refs_survive_replan():
    data, was = _isolate()
    try:
        sid = db.run(
            """INSERT INTO songs (title, album, slug, duration, lyrics, created)
               VALUES (?,?,?,?,?,?)""",
            "T2-13b Replan Song", "T213b", "t213b-replan", 20.0,
            "[A]\none\n[B]\ntwo\n", time.time())
        args = {"song_id": sid, "tier": "pg13", "scene_seconds": 4.0}
        appmod.h_storyboard(args, lambda m: None)

        now = time.time()
        db.run("""INSERT INTO refs (song_id, tier, clip_idx, path, seed, approved, created)
                  VALUES (?,?,?,?,?,?,?)""",
               sid, "pg13", 0, "/fake/clip_000_s5151.png", 5151, 1, now)
        db.run("""INSERT INTO refs (song_id, tier, clip_idx, path, seed, approved, created)
                  VALUES (?,?,?,?,?,?,?)""",
               sid, "pg13", 1, "/fake/clip_001_s129080599.png", 129080599, 1, now)
        db.run("""INSERT INTO refs (song_id, tier, clip_idx, path, seed, approved, created)
                  VALUES (?,?,?,?,?,?,?)""",
               sid, "pg13", 0, "/fake/clip_000_s4748.png", 4748, 0, now)

        before = _approved_keys(sid, "pg13")
        assert before == {(0, 5151), (1, 129080599)}, before

        appmod.h_storyboard(args, lambda m: None)

        after = _approved_keys(sid, "pg13")
        assert after == before, (before, after)
    finally:
        _restore(was)
