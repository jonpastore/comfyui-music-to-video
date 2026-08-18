"""T2-50: analyze-for-poses writes a coverage list, not a bind.

docs/TRD-2 §6b: a ceiling-tier board yields (pose, view, wardrobe,
exposure) per scene. Analyze does not attach files, write refs, enqueue
a refs job, or write scene_pose_map. It does not reuse pose_plan
auto-bind.

Mutation: analyze inserts a map row or a refs job → red.
Mutation: 3-scene kneeling/standing/all-fours yields fewer needs → red.
Mutation: pose_coverage imports pose_plan → red.
"""
import ast
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import pose_coverage
import storyboard_service
import tiers


def _fastapi_or_pose_plan_imports(path):
    tree = ast.parse(open(path).read())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split(".")[0])
    return [n for n in names if n in ("fastapi", "pose_plan")]


def _scene(n, pose, camera):
    return {
        "scene_number": n,
        "name": f"Scene {n}",
        "cue": "Verse",
        "duration_guidance": "8 sec",
        "story": f"{pose} in the alley",
        "camera": camera,
        "motion": "hold",
        "lighting": "neon",
        "location": f"loc {n}",
        "pose": pose,
        "image_prompt": f"Meow P {pose} in a neon alley",
        "video_motion_prompt": f"motion {n}",
        "negative_prompt": "",
        "characters": [],
    }


def _write_board(sid, slug, tier, scenes):
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    sb = {
        "title": "T",
        "album": "T250",
        "version": tier,
        "character_reference": "a sleek black feline DJ",
        "scenes": scenes,
    }
    json_path = os.path.join(outdir, f"{slug}_{tier}.json")
    md_path = os.path.join(outdir, f"{slug}_{tier}.md")
    json.dump(sb, open(json_path, "w"))
    open(md_path, "w").write("# storyboard\n")
    db.run(
        """INSERT INTO storyboards
           (song_id, tier, json_path, md_path, scene_count, created, scene_seconds)
           VALUES (?,?,?,?,?,?,?)""",
        sid, tier, json_path, md_path, len(scenes), time.time(), 8.0)
    return json_path


def _map_rows(song_id, tier):
    if not db.one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scene_pose_map'"):
        return []
    return list(db.q(
        "SELECT * FROM scene_pose_map WHERE song_id=? AND tier=?",
        song_id, tier))


def test_t2_50_pose_coverage_imports_nothing_from_fastapi_or_pose_plan():
    banned = _fastapi_or_pose_plan_imports(pose_coverage.__file__)
    assert banned == [], f"pose_coverage imports bind stack: {banned}"


def test_t2_50_coverage_list_from_board_writes_no_map_or_refs():
    """A 3-scene board yields those three needs and zero map/refs rows."""
    tiers.ensure_builtins()
    stamp = f"t250-{time.time_ns()}"
    sid = db.upsert_song(
        stamp, title="T2-50 Coverage Song", album=f"T250 {stamp}",
        duration=24.0)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    scenes = [
        _scene(1, "kneeling", "medium"),
        _scene(2, "standing", "wide"),
        _scene(3, "all fours", "from behind"),
    ]
    json_path = _write_board(sid, song["slug"], "xxx", scenes)
    jobs_before = list(db.q("SELECT id, kind FROM jobs WHERE song_id=?", sid))
    refs_before = db.one("SELECT COUNT(*) AS n FROM refs WHERE song_id=?", sid)["n"]

    got = storyboard_service.analyze_poses(sid, "xxx")

    needs = got.get("needs")
    assert isinstance(needs, list) and len(needs) == 3, got
    assert got["n_scenes"] == 3, got
    assert got["song_id"] == sid, got
    assert got["tier"] == "xxx", got
    by_pose = {item["pose"]: item for item in needs}
    assert set(by_pose) == {"kneeling", "standing", "all-fours"}, by_pose
    for item in needs:
        assert item["view"], item
        assert item["wardrobe"], item
        assert item["exposure"], item
        for key in ("pose", "view", "wardrobe", "exposure"):
            assert isinstance(item[key], str) and item[key].strip(), item
    assert by_pose["all-fours"]["view"] == "3qtr-rear", by_pose["all-fours"]
    assert by_pose["kneeling"]["scene_number"] == 1
    assert by_pose["standing"]["scene_number"] == 2
    assert by_pose["all-fours"]["scene_number"] == 3

    stored = storyboard_service.pose_coverage_list(sid, "xxx")
    assert stored["needs"] == needs, stored

    again = storyboard_service.analyze_poses(sid, "xxx")
    assert again["n_scenes"] == 3, again
    n_rows = db.one(
        "SELECT COUNT(*) AS n FROM pose_coverage WHERE song_id=? AND tier=?",
        sid, "xxx")["n"]
    assert n_rows == 3, n_rows

    assert _map_rows(sid, "xxx") == []
    assert not db.one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='scene_pose_map'")
    assert db.one("SELECT COUNT(*) AS n FROM refs WHERE song_id=?", sid)["n"] == refs_before
    jobs_after = list(db.q("SELECT id, kind FROM jobs WHERE song_id=?", sid))
    assert jobs_after == jobs_before, jobs_after
    assert not any(r["kind"] == "refs" for r in jobs_after)

    board = json.load(open(json_path))
    for scene in board["scenes"]:
        assert not scene.get("pose_sheet_id"), scene

    with TestClient(appmod.app) as client:
        posted = client.post(f"/api/songs/{sid}/storyboard/xxx/analyze-poses")
        assert posted.status_code == 200, posted.text
        body = posted.json()
        assert body["n_scenes"] == 3, body
        assert {item["pose"] for item in body["needs"]} == {
            "kneeling", "standing", "all-fours"}
        listed = client.get(f"/api/songs/{sid}/storyboard/xxx/pose-coverage")
        assert listed.status_code == 200, listed.text
        assert listed.json()["needs"] == body["needs"]

    assert _map_rows(sid, "xxx") == []
    assert db.one("SELECT COUNT(*) AS n FROM refs WHERE song_id=?", sid)["n"] == refs_before
    assert list(db.q("SELECT id, kind FROM jobs WHERE song_id=?", sid)) == jobs_before
