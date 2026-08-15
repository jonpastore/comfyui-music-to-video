"""T2-13b: approved refs survive re-planning the same storyboard.

docs/TRD-2 F-3 / T2-13b: read `refs` before and after re-planning the same
storyboard and assert the set of approved (clip_idx, seed) is identical.
That is the check that stops a re-plan quietly invalidating a human's
approvals.

Mutation: h_storyboard deletes or unapproves refs → this fails.
Mutation: remap clip_idx on re-plan → this fails.
"""
import time

from fastapi.testclient import TestClient

import app as appmod
import db
from test_app import _upload_song, wait_job


def _approved_keys(sid, tier):
    return {(r["clip_idx"], r["seed"]) for r in db.q(
        "SELECT clip_idx, seed FROM refs WHERE song_id=? AND tier=? AND approved=1",
        sid, tier)}


def test_t2_13b_approved_refs_survive_replan():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T2-13b Replan Song")
        sid = song["id"]
        db.run("UPDATE songs SET duration=? WHERE id=?", 20.0, sid)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)

        r = client.post(f"/songs/{sid}/storyboard",
                        data={"tier": "pg13", "scene_seconds": "4.0"})
        assert r.status_code in (200, 303), r.text
        first = db.one(
            "SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC",
            sid)
        row = wait_job(first["id"])
        assert row["status"] == "done", row

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

        r2 = client.post(f"/songs/{sid}/storyboard",
                         data={"tier": "pg13", "scene_seconds": "4.0"})
        assert r2.status_code in (200, 303), r2.text
        second = db.one(
            "SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC",
            sid)
        assert second["id"] != first["id"], "re-plan did not enqueue a new storyboard job"
        row2 = wait_job(second["id"])
        assert row2["status"] == "done", row2

        after = _approved_keys(sid, "pg13")
        assert after == before, (before, after)
