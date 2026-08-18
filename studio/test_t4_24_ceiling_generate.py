"""T4-24: ceiling-tier pose generate from pose-gap holes.

docs/TRD-4 §6a: library sheets at the highest ticked tier this run.
If the ceiling allows nudity (r, xxx), generate clothed AND nude
coverage. If it does not (g, pg13), clothed only. No anatomy pass on
a g/pg13 ceiling. Never invent a higher tier than the ceiling.
Replaces sidecar batch_edit.

Mutation: g-only run emits a nude view or an anatomy job → red.
Mutation: r ceiling emits clothed only and calls coverage green → red.
Mutation: r-only invents an xxx job → red.
"""
import ast
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import classification
import db
import make_anchor
import pose_coverage
import pose_generate
import storyboard_service
import tiers


def _banned_imports(path, names):
    tree = ast.parse(open(path).read())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module.split(".")[0])
    return [n for n in found if n in names]


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


def _map_rows(song_id):
    if not db.one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scene_pose_map'"):
        return []
    return list(db.q("SELECT * FROM scene_pose_map WHERE song_id=?", song_id))


def _song(stamp, album, duration=24.0):
    sid = db.upsert_song(stamp, title=f"T4-24 {stamp}", album=album,
                         duration=duration)
    return db.one("SELECT * FROM songs WHERE id=?", sid)


def _job_args(song_id):
    out = []
    for row in db.q("SELECT * FROM jobs WHERE song_id=? ORDER BY id", song_id):
        args = json.loads(row["args_json"] or "{}")
        out.append((row, args))
    return out


def test_t4_24_generate_imports_nothing_from_fastapi_pose_plan_or_batch_edit():
    banned = ("fastapi", "pose_plan", "batch_edit")
    assert _banned_imports(pose_generate.__file__, banned) == []
    assert _banned_imports(pose_coverage.__file__, banned) == []


def test_t4_24_g_only_emits_clothed_no_nude_no_anatomy():
    """g ceiling: clothed only. A nude view or anatomy job is the mutation."""
    tiers.ensure_builtins()
    stamp = f"t424-g-{time.time_ns()}"
    album = f"T424G {stamp}"
    song = _song(stamp, album)
    sid = song["id"]
    _write_board(sid, song["slug"], "g", [
        _scene(1, "standing", "wide"),
        _scene(2, "kneeling", "medium"),
    ], album)
    jobs_before = list(db.q("SELECT id FROM jobs WHERE song_id=?", sid))

    got = storyboard_service.generate_poses(sid, ["g"])

    assert got["tier"] == "g", got
    assert got["coverage"] == "green", got
    assert got["anatomy"] is False, got
    assert got["queued"] == 2, got
    wardrobes = {j["wardrobe"] for j in got["jobs"]}
    views = {j["view"] for j in got["jobs"]}
    assert wardrobes == {"clothed"}, got
    assert not any(make_anchor.is_nude_view(v) for v in views), views
    assert all(j["anatomy"] is False for j in got["jobs"]), got["jobs"]
    assert all(j["tier"] == "g" for j in got["jobs"]), got["jobs"]

    for _row, args in _job_args(sid):
        assert args.get("tier") == "g", args
        assert not make_anchor.is_nude_view(args.get("view")), args
        assert args.get("anatomy") is False, args
        assert args.get("wardrobe") == "clothed", args
        assert args.get("source") == "pose-gap", args
        assert args.get("kind") != "anatomy"
    assert len(_job_args(sid)) == len(jobs_before) + 2
    assert _map_rows(sid) == []


def test_t4_24_pg13_ceiling_is_clothed_only():
    tiers.ensure_builtins()
    stamp = f"t424-pg-{time.time_ns()}"
    album = f"T424P {stamp}"
    song = _song(stamp, album)
    sid = song["id"]
    _write_board(sid, song["slug"], "pg13", [
        _scene(1, "standing", "wide"),
    ], album)
    got = pose_generate.generate(sid, ["pg13"])
    assert got["tier"] == "pg13", got
    assert {j["wardrobe"] for j in got["jobs"]} == {"clothed"}, got
    assert not any(make_anchor.is_nude_view(j["view"]) for j in got["jobs"])
    assert got["anatomy"] is False
    assert all(j["anatomy"] is False for j in got["jobs"])


def test_t4_24_r_ceiling_emits_clothed_and_nude_and_is_green():
    """r must plan both wardrobes. Clothed-only + coverage green is the mutation."""
    tiers.ensure_builtins()
    stamp = f"t424-r-{time.time_ns()}"
    album = f"T424R {stamp}"
    song = _song(stamp, album)
    sid = song["id"]
    _write_board(sid, song["slug"], "pg13", [
        _scene(1, "standing", "wide"),
    ], album)
    _write_board(sid, song["slug"], "r", [
        _scene(1, "kneeling", "medium"),
        _scene(2, "standing", "wide"),
        _scene(3, "all fours", "from behind", wardrobe="nude"),
    ], album)
    classification.save(album, {"images": [
        _image("kneel-front", pose="kneel", view="front", wardrobe="clothed",
               usable="pose"),
    ]})

    clothed_only = [
        {"pose": "standing", "view": "front", "wardrobe": "clothed"},
        {"pose": "all-fours", "view": "3qtr-rear", "wardrobe": "clothed"},
    ]
    holes = [
        {"pose": "standing", "view": "front", "wardrobe": "clothed"},
        {"pose": "all-fours", "view": "3qtr-rear", "wardrobe": "nude"},
    ]
    assert pose_generate.coverage_status("r", clothed_only, holes) != "green"

    got = storyboard_service.generate_poses(sid, ["r"])

    assert got["tier"] == "r", got
    assert got["coverage"] == "green", got
    assert got["anatomy"] is False, got
    wardrobes = {j["wardrobe"] for j in got["jobs"]}
    views = {j["view"] for j in got["jobs"]}
    poses = {j["pose"] for j in got["jobs"]}
    assert wardrobes == {"clothed", "nude"}, got
    assert any(make_anchor.is_nude_view(v) for v in views), views
    assert any(not make_anchor.is_nude_view(v) for v in views), views
    assert poses == {"standing", "all-fours"}, poses
    assert "kneeling" not in poses
    assert all(j["tier"] == "r" for j in got["jobs"]), got["jobs"]
    assert all(j["anatomy"] is False for j in got["jobs"]), got["jobs"]
    assert got["queued"] == 4, got

    for _row, args in _job_args(sid):
        assert args.get("tier") == "r", args
        assert args.get("tier") != "xxx", args
        assert args.get("anatomy") is False, args
        assert args.get("source") == "pose-gap", args
    assert _map_rows(sid) == []


def test_t4_24_xxx_ceiling_emits_both_wardrobes():
    tiers.ensure_builtins()
    stamp = f"t424-x-{time.time_ns()}"
    album = f"T424X {stamp}"
    song = _song(stamp, album, duration=8.0)
    sid = song["id"]
    _write_board(sid, song["slug"], "xxx", [
        _scene(1, "standing", "wide"),
    ], album)
    got = pose_generate.generate(sid, ["xxx"])
    assert got["tier"] == "xxx", got
    assert got["coverage"] == "green", got
    assert {j["wardrobe"] for j in got["jobs"]} == {"clothed", "nude"}, got
    assert {j["view"] for j in got["jobs"]} == {"front", "front_nude"}, got


def test_t4_24_never_invents_a_higher_tier_than_the_run_ceiling():
    """r+pg13 generates at r, not xxx. r-only does not emit pg13 jobs."""
    tiers.ensure_builtins()
    stamp = f"t424-hi-{time.time_ns()}"
    album = f"T424H {stamp}"
    song = _song(stamp, album)
    sid = song["id"]
    _write_board(sid, song["slug"], "xxx", [
        _scene(1, "standing", "wide"),
    ], album)
    got = pose_generate.generate(sid, ["pg13", "r"])
    assert got["tier"] == "r", got
    assert all(j["tier"] == "r" for j in got["jobs"]), got
    assert all(j["tier"] != "xxx" for j in got["jobs"]), got
    assert pose_generate.ceiling_of(["pg13", "r"]) == "r"
    assert pose_generate.ceiling_of(["g"]) == "g"

    stamp2 = f"t424-ro-{time.time_ns()}"
    album2 = f"T424RO {stamp2}"
    song2 = _song(stamp2, album2, duration=8.0)
    _write_board(song2["id"], song2["slug"], "r", [
        _scene(1, "standing", "wide"),
    ], album2)
    r_only = pose_generate.generate(song2["id"], ["r"])
    assert {j["tier"] for j in r_only["jobs"]} == {"r"}, r_only
    assert all(j["tier"] != "pg13" for j in r_only["jobs"])
    assert all(j["tier"] != "xxx" for j in r_only["jobs"])


def test_t4_24_empty_tiers_refused():
    tiers.ensure_builtins()
    stamp = f"t424-empty-{time.time_ns()}"
    album = f"T424E {stamp}"
    song = _song(stamp, album, duration=8.0)
    _write_board(song["id"], song["slug"], "g", [
        _scene(1, "standing", "wide"),
    ], album)
    try:
        pose_generate.generate(song["id"], [])
        raise AssertionError("empty tiers must be refused")
    except ValueError as e:
        assert "tier" in str(e).lower(), e


def test_t4_24_api_enqueues_at_the_run_ceiling():
    tiers.ensure_builtins()
    stamp = f"t424-api-{time.time_ns()}"
    album = f"T424A {stamp}"
    song = _song(stamp, album, duration=8.0)
    sid = song["id"]
    _write_board(sid, song["slug"], "xxx", [
        _scene(1, "standing", "wide"),
    ], album)
    with TestClient(appmod.app) as client:
        posted = client.post(
            f"/api/songs/{sid}/pose-generate",
            json={"tiers": ["g"]})
        assert posted.status_code == 200, posted.text
        body = posted.json()
        assert body["tier"] == "g", body
        assert body["coverage"] == "green", body
        assert {j["wardrobe"] for j in body["jobs"]} == {"clothed"}, body
        assert not any(make_anchor.is_nude_view(j["view"]) for j in body["jobs"])
        assert body["anatomy"] is False
        refused = client.post(
            f"/api/songs/{sid}/pose-generate",
            json={"tiers": []})
        assert refused.status_code == 400, refused.text
        assert "tier" in refused.json()["detail"].lower()
    assert _map_rows(sid) == []
