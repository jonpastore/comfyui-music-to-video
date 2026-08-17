"""T2-13c: approve grid lists every scene, not every 4.8s slice.

docs/TRD-2 T2-13c: operator tiles are scenes. clip_chain_plan may split a
long scene for the renderer (T2-10) but those parts are not tiles.

Mutation: range over storyboards.scene_count or clip_count for tiles →
wrong number of scene-group cards.
"""
import inspect
import json
import os
import time

import build_song
import db
import app as appmod

from fastapi.testclient import TestClient


def _board(sid, slug, scenes):
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{slug}_pg13.json")
    json.dump({"title": "T", "scenes": scenes}, open(path, "w"))
    db.run("""INSERT INTO storyboards (song_id, tier, json_path, md_path,
                                       scene_count, created)
              VALUES (?,?,?,?,?,?)""",
           sid, "pg13", path, path + ".md", len(scenes), time.time())
    return path


def test_t2_13c_approve_grid_lists_every_scene_not_every_clip():
    duration = 195.792
    scene_count = 20
    with TestClient(appmod.app) as client:
        sid = db.upsert_song(
            "t213c-short-sb", title="T2-13c Grid Song",
            album="T213c", duration=duration)
        scenes = [{
            "scene_number": n, "name": f"S{n}",
            "image_prompt": f"scene {n}",
            "length_seconds": 9.8,
        } for n in range(1, scene_count + 1)]
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _board(sid, song["slug"], scenes)
        want_clips = build_song.n_clips_for(duration)
        assert want_clips == 41, want_clips
        assert scene_count < want_clips
        assert appmod.clip_count(song) == want_clips

        plan = build_song.clip_chain_plan(scenes, "ltx25")
        assert len(plan) == scene_count, len(plan)

        page = client.get(f"/songs/{sid}/storyboard/pg13/panel").text
        assert page
        assert page.count('class="scene"') == scene_count
        assert f'data-nclips="{len(plan)}"' in page
        assert f'data-nclips="{want_clips}"' not in page
        assert "Part 1" not in page
        assert "Clip #0" not in page
        assert "Reference stills" in page
        assert "album plates" not in page or "Pose plate" in page
        assert "no candidates yet" not in page


def test_t2_13c_approve_context_does_not_range_over_scene_count():
    """Mutation: for i in range(scene_count) in approve_context → red."""
    src = inspect.getsource(appmod.approve_context)
    assert "scene_count" not in src
    assert "storyboard_service.scenes" in src


def test_remap_legacy_refs_moves_clip_plan_rows_onto_heads():
    """Song-3 shape: 4.8s allocator stills become one candidate pile per scene.

    Mutation: assign by clip_idx==head → old clip 3 (scene 2) lands on
    scene 4. Mutation: skip the remap → 7000-seed rows stay invisible.
    """
    import storyboard_service
    duration = 19.25
    scenes = [{
        "scene_number": n, "name": f"S{n}",
        "image_prompt": f"scene {n}",
    } for n in (1, 2)]
    sid = db.upsert_song("t213c-remap", title="Remap", album="T", duration=duration)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    _board(sid, song["slug"], scenes)
    nclips = appmod.clip_count(song)
    assert nclips == 4, nclips
    plan = build_song.clip_plan(scenes, nclips=nclips)
    old = {}
    for ci, sc, _ in plan:
        old.setdefault(sc["scene_number"], []).append(ci)
    assert old[1] == [0, 1] and old[2] == [2, 3], old
    heads = build_song.scene_heads(scenes, "ltx25")
    assert heads == {1: 0, 2: 1}, heads
    for i in range(4):
        db.run("""INSERT INTO refs (song_id, tier, clip_idx, path, seed, approved, created)
                  VALUES (?,?,?,?,?,1,?)""",
               sid, "pg13", i, f"/tmp/remap_{i}.png", 7000 + i, time.time())
    out = storyboard_service.remap_legacy_refs(song, "pg13")
    assert out["moved"] + out["stamped"] == 4, out
    assert out["skipped"] == 0, out
    assert out["moved"] >= 2, out
    again = storyboard_service.remap_legacy_refs(song, "pg13")
    assert again["moved"] == 0 and again["stamped"] == 0, again
    rows = db.q("SELECT clip_idx, scene_number, seed FROM refs WHERE song_id=? ORDER BY seed",
                sid)
    by_scene = {}
    for r in rows:
        by_scene.setdefault(r["scene_number"], []).append((r["clip_idx"], r["seed"]))
    assert set(ci for ci, _ in by_scene[1]) == {0}, by_scene
    assert {s for _, s in by_scene[1]} == {7000, 7001}, by_scene
    assert set(ci for ci, _ in by_scene[2]) == {1}, by_scene
    assert {s for _, s in by_scene[2]} == {7002, 7003}, by_scene
    staged = appmod._approved_scene_ref_paths(song, "pg13")
    assert {r["clip_idx"] for r in staged} == {0, 1}, staged


def test_stamp_ref_scenes_skips_clip_plan_era_seeds():
    """Live 7000+ci rows must not be hung on a chain head.

    Mutation: stamp any NULL row whose clip_idx equals a head → ref 5
    becomes scene 6 on a 20×9.8s board.
    """
    import storyboard_service
    duration = 195.792
    scenes = [{
        "scene_number": n, "name": f"S{n}",
        "image_prompt": f"scene {n}", "length_seconds": 9.8,
    } for n in range(1, 21)]
    sid = db.upsert_song("t213c-stamp", title="Stamp", album="T", duration=duration)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    _board(sid, song["slug"], scenes)
    for i in range(41):
        db.run("""INSERT INTO refs (song_id, tier, clip_idx, path, seed, approved, created)
                  VALUES (?,?,?,?,?,1,?)""",
               sid, "pg13", i, f"/tmp/old_{i}.png", 7000 + i, time.time())
    n = storyboard_service.stamp_ref_scenes(song, "pg13")
    assert n == 0, n
    rows = db.q("SELECT clip_idx, scene_number FROM refs WHERE song_id=?", sid)
    assert all(r["scene_number"] is None for r in rows)
    staged = appmod._approved_scene_ref_paths(song, "pg13")
    assert staged == []
