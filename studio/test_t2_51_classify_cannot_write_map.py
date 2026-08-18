"""T4-23 / T2-51 mutation: gap and classify never write scene_pose_map.

docs/TRD-4 §6a T4-23: gap reads the open song's ceiling board, compares
classification_json keepers (usable≠skip), and emits coverage holes only.

docs/TRD-2 §6b T2-51: classify, even with the same tags, writes no map
row. Draft map is a later call.

Mutation: gap or classify upserts a map row → red.
Mutation: a covered need appears in holes → red.
Mutation: gap reads a lower board when a higher ceiling exists → red.
Mutation: usable=skip closes a hole → red.
"""
import ast
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import classification
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


def _scene(n, pose, camera, wardrobe="clothed"):
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
        "wardrobe": wardrobe,
        "image_prompt": f"Meow P {pose} in a neon alley",
        "video_motion_prompt": f"motion {n}",
        "negative_prompt": "",
        "characters": [],
    }


def _write_board(sid, slug, tier, scenes, album):
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    sb = {
        "title": "T",
        "album": album,
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


def _image(iid, **over):
    row = {
        "id": iid,
        "path": f"{iid}.jpg",
        "kind": "operator",
        "view": "front",
        "pose": "standing",
        "wardrobe": "clothed",
        "usable": "pose",
    }
    row.update(over)
    return row


def _map_rows(song_id, tier=None):
    if not db.one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scene_pose_map'"):
        return []
    if tier is None:
        return list(db.q("SELECT * FROM scene_pose_map WHERE song_id=?", song_id))
    return list(db.q(
        "SELECT * FROM scene_pose_map WHERE song_id=? AND tier=?",
        song_id, tier))


def _coverage_n(song_id):
    return db.one(
        "SELECT COUNT(*) AS n FROM pose_coverage WHERE song_id=?", song_id)["n"]


def test_t4_23_gap_imports_nothing_from_fastapi_or_pose_plan():
    banned = _fastapi_or_pose_plan_imports(pose_coverage.__file__)
    assert banned == [], f"pose_coverage imports bind stack: {banned}"
    banned = _fastapi_or_pose_plan_imports(classification.__file__)
    assert banned == [], f"classification imports bind stack: {banned}"


def test_t4_23_gap_emits_holes_only_and_classify_writes_no_map():
    """Ceiling xxx needs vs keepers: covered stays out; skip and missing are holes."""
    tiers.ensure_builtins()
    stamp = f"t423-{time.time_ns()}"
    album = f"T423 {stamp}"
    sid = db.upsert_song(
        stamp, title="T4-23 Gap Song", album=album, duration=24.0)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    # Lower board would hide the all-fours hole if gap read the wrong tier.
    _write_board(sid, song["slug"], "pg13", [
        _scene(1, "standing", "wide"),
    ], album)
    _write_board(sid, song["slug"], "xxx", [
        _scene(1, "kneeling", "medium"),
        _scene(2, "standing", "wide"),
        _scene(3, "all fours", "from behind", wardrobe="nude"),
    ], album)
    jobs_before = list(db.q("SELECT id, kind FROM jobs WHERE song_id=?", sid))
    refs_before = db.one("SELECT COUNT(*) AS n FROM refs WHERE song_id=?", sid)["n"]
    cov_before = _coverage_n(sid)

    classified = classification.save(album, {"images": [
        _image("kneel-front", pose="kneel", view="front", wardrobe="clothed",
               usable="pose"),
        _image("stand-skip", pose="stand", view="front", wardrobe="clothed",
               usable="skip"),
    ]})
    assert classified["version_number"] == 1
    assert _map_rows(sid) == []
    assert not db.one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='scene_pose_map'")

    got = storyboard_service.pose_gap(sid)

    assert got["song_id"] == sid, got
    assert got["album"] == album, got
    assert got["tier"] == "xxx", got
    assert got["n_needs"] == 3, got
    assert got["n_covered"] == 1, got
    assert got["n_holes"] == 2, got
    assert "needs" not in got, got
    holes = got["holes"]
    assert isinstance(holes, list) and len(holes) == 2, got
    by_pose = {h["pose"]: h for h in holes}
    assert set(by_pose) == {"standing", "all-fours"}, by_pose
    assert "kneeling" not in by_pose, by_pose
    assert by_pose["standing"]["view"] == "front", by_pose["standing"]
    assert by_pose["standing"]["wardrobe"] == "clothed", by_pose["standing"]
    assert by_pose["standing"]["scenes"] == [2], by_pose["standing"]
    assert by_pose["all-fours"]["view"] == "3qtr-rear", by_pose["all-fours"]
    assert by_pose["all-fours"]["wardrobe"] == "nude", by_pose["all-fours"]
    assert by_pose["all-fours"]["scenes"] == [3], by_pose["all-fours"]

    assert _coverage_n(sid) == cov_before
    assert _map_rows(sid) == []
    assert not db.one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='scene_pose_map'")
    assert db.one("SELECT COUNT(*) AS n FROM refs WHERE song_id=?", sid)["n"] == refs_before
    assert list(db.q("SELECT id, kind FROM jobs WHERE song_id=?", sid)) == jobs_before


def test_t4_23_sidecar_does_not_close_a_hole():
    """A matching sidecar is not a keeper until it is in sqlite."""
    tiers.ensure_builtins()
    stamp = f"t423-side-{time.time_ns()}"
    album = f"T423S {stamp}"
    sid = db.upsert_song(
        stamp, title="T4-23 Sidecar Song", album=album, duration=8.0)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    _write_board(sid, song["slug"], "xxx", [
        _scene(1, "standing", "wide"),
    ], album)
    import tempfile
    tmp = tempfile.mkdtemp(prefix="t423_")
    side = os.path.join(tmp, "image-classification.json")
    json.dump({"images": [
        _image("sidecar-stand", pose="stand", view="front", wardrobe="clothed",
               usable="pose"),
    ]}, open(side, "w"))

    empty = storyboard_service.pose_gap(sid)
    assert empty["n_holes"] == 1, empty
    assert empty["holes"][0]["pose"] == "standing"

    classification.import_sidecar(album, side)
    filled = storyboard_service.pose_gap(sid)
    assert filled["n_holes"] == 0, filled
    assert filled["n_covered"] == 1, filled
    assert filled["holes"] == []
    assert _map_rows(sid) == []


def test_t2_51_classify_and_gap_leave_an_existing_map_untouched():
    """If the map table already exists, neither classify nor gap inserts."""
    tiers.ensure_builtins()
    db.run("""CREATE TABLE IF NOT EXISTS scene_pose_map (
                id INTEGER PRIMARY KEY,
                song_id INTEGER NOT NULL,
                tier TEXT NOT NULL,
                scene_number INTEGER NOT NULL,
                keeper_id TEXT,
                path TEXT,
                status TEXT)""")
    try:
        stamp = f"t251-{time.time_ns()}"
        album = f"T251 {stamp}"
        sid = db.upsert_song(
            stamp, title="T2-51 Map Guard", album=album, duration=8.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _write_board(sid, song["slug"], "r", [
            _scene(1, "kneeling", "medium"),
        ], album)
        before = _map_rows(sid)
        assert before == []

        classification.save(album, {"images": [
            _image("kneel", pose="kneel", view="front", usable="pose"),
        ]})
        got = storyboard_service.pose_gap(sid)
        assert got["n_holes"] == 0, got
        assert _map_rows(sid) == []
        n = db.one("SELECT COUNT(*) AS n FROM scene_pose_map")["n"]
        assert n == 0, n
    finally:
        db.run("DROP TABLE IF EXISTS scene_pose_map")


def test_t4_23_api_returns_holes_only():
    tiers.ensure_builtins()
    stamp = f"t423-api-{time.time_ns()}"
    album = f"T423A {stamp}"
    sid = db.upsert_song(
        stamp, title="T4-23 API Song", album=album, duration=16.0)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    _write_board(sid, song["slug"], "xxx", [
        _scene(1, "kneeling", "medium"),
        _scene(2, "standing", "wide"),
    ], album)
    classification.save(album, {"images": [
        _image("kneel", pose="kneeling", view="front", usable="identity"),
    ]})
    with TestClient(appmod.app) as client:
        posted = client.get(f"/api/songs/{sid}/pose-gap")
        assert posted.status_code == 200, posted.text
        body = posted.json()
        assert body["tier"] == "xxx", body
        assert body["n_holes"] == 1, body
        assert [h["pose"] for h in body["holes"]] == ["standing"]
        assert "needs" not in body
    assert _map_rows(sid) == []
    assert _coverage_n(sid) == 0
