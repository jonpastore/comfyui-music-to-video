"""T2-54: ceiling + ticked-lower backfill of boards.

docs/TRD-2 §6b: the run's ceiling is the highest ticked tier. Every
lower ticked tier gets its own board (that tier's guardrail + the
wardrobe it permits). Unticked tiers get nothing. Never invent a
higher tier than the ceiling.

r+pg13 writes both; r-only does not write pg13; g ceiling writes a
clothed g board and no nude / r / xxx.

Mutation: r-only writes a pg13 board → red.
Mutation: g ceiling writes a nude view or r/xxx board → red.
"""
import ast
import json
import os
import time

import db
import make_anchor
import storyboard_backfill
import storyboard_service
import tiers


def _fastapi_imports(path):
    tree = ast.parse(open(path).read())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split(".")[0])
    return [n for n in names if n == "fastapi"]


def _scene(n, pose, camera="wide", wardrobe="clothed", view="front"):
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
        "view": view,
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


def _song(stamp, album, duration=24.0):
    sid = db.upsert_song(stamp, title=f"T2-54 {stamp}", album=album,
                         duration=duration)
    return db.one("SELECT * FROM songs WHERE id=?", sid)


def _tiers(sid):
    return {r["tier"] for r in db.q(
        "SELECT tier FROM storyboards WHERE song_id=?", sid)}


def _load(sid, tier):
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?",
                 sid, tier)
    assert row, f"missing {tier} board"
    with open(row["json_path"]) as f:
        return json.load(f)


def test_t2_54_backfill_imports_nothing_from_fastapi():
    assert _fastapi_imports(storyboard_backfill.__file__) == []


def test_t2_54_r_and_pg13_writes_both():
    """r+pg13 writes both boards. pg13 gets pg13 guardrail and clothed only."""
    tiers.ensure_builtins()
    stamp = f"t254-both-{time.time_ns()}"
    album = f"T254B {stamp}"
    song = _song(stamp, album)
    sid = song["id"]
    _write_board(sid, song["slug"], "r", [
        _scene(1, "standing", wardrobe="clothed", view="front"),
        _scene(2, "kneeling", wardrobe="nude", view="front_nude"),
    ], album)

    got = storyboard_service.backfill(sid, ["pg13", "r"])

    assert got["ceiling"] == "r", got
    assert set(got["written"]) == {"pg13", "r"}, got
    assert _tiers(sid) == {"pg13", "r"}
    assert "g" not in _tiers(sid)
    assert "xxx" not in _tiers(sid)

    want_r = tiers.compose_guardrail("r", album)
    want_pg13 = tiers.compose_guardrail("pg13", album)
    r_board = _load(sid, "r")
    pg13_board = _load(sid, "pg13")
    assert r_board["guardrail"] == want_r, r_board.get("guardrail")
    assert pg13_board["guardrail"] == want_pg13, pg13_board.get("guardrail")
    assert r_board["version"] == "r"
    assert pg13_board["version"] == "pg13"
    assert {s["wardrobe"] for s in r_board["scenes"]} == {"clothed", "nude"}
    assert {s["wardrobe"] for s in pg13_board["scenes"]} == {"clothed"}
    assert any(make_anchor.is_nude_view(s.get("view")) for s in r_board["scenes"])
    assert not any(make_anchor.is_nude_view(s.get("view"))
                   for s in pg13_board["scenes"])


def test_t2_54_r_only_does_not_write_pg13():
    """r-only writes r. A pg13 row is the mutation."""
    tiers.ensure_builtins()
    stamp = f"t254-ro-{time.time_ns()}"
    album = f"T254RO {stamp}"
    song = _song(stamp, album, duration=8.0)
    sid = song["id"]
    _write_board(sid, song["slug"], "r", [
        _scene(1, "standing", wardrobe="nude", view="front_nude"),
    ], album)

    got = storyboard_backfill.backfill(sid, ["r"])

    assert got["ceiling"] == "r", got
    assert got["written"] == ["r"], got
    assert _tiers(sid) == {"r"}
    assert "pg13" not in _tiers(sid)
    assert "g" not in _tiers(sid)
    assert "xxx" not in _tiers(sid)
    assert not os.path.isfile(
        os.path.join(db.DATA, "storyboards", song["slug"],
                     f"{song['slug']}_pg13.json"))
    r_board = _load(sid, "r")
    assert r_board["guardrail"] == tiers.compose_guardrail("r", album)
    assert {s["wardrobe"] for s in r_board["scenes"]} == {"nude"}


def test_t2_54_g_ceiling_writes_clothed_g_no_nude_r_xxx():
    """g writes a clothed g board. Nude view or r/xxx board is the mutation."""
    tiers.ensure_builtins()
    stamp = f"t254-g-{time.time_ns()}"
    album = f"T254G {stamp}"
    song = _song(stamp, album, duration=8.0)
    sid = song["id"]
    _write_board(sid, song["slug"], "g", [
        _scene(1, "standing", wardrobe="nude", view="front_nude"),
        _scene(2, "kneeling", wardrobe="naked", view="back_nude"),
    ], album)

    got = storyboard_service.backfill(sid, ["g"])

    assert got["ceiling"] == "g", got
    assert got["written"] == ["g"], got
    assert _tiers(sid) == {"g"}
    assert _tiers(sid).isdisjoint({"r", "xxx", "pg13"})
    g_board = _load(sid, "g")
    assert g_board["guardrail"] == tiers.compose_guardrail("g", album)
    assert g_board["version"] == "g"
    wardrobes = {s["wardrobe"] for s in g_board["scenes"]}
    views = {s.get("view") for s in g_board["scenes"]}
    assert wardrobes == {"clothed"}, g_board
    assert "nude" not in wardrobes
    assert not any(make_anchor.is_nude_view(v) for v in views), views
    for name in ("r", "xxx", "pg13"):
        assert not os.path.isfile(
            os.path.join(db.DATA, "storyboards", song["slug"],
                         f"{song['slug']}_{name}.json"))
