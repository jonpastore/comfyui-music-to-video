"""T2-13c: approve grid shows every clip when scenes < clip_count.

docs/TRD-2 W1-3 / T2-13c: a song whose storyboard has fewer scenes than
clips still shows every clip in the approve grid. The named regression:
using scene_count hid clips 20..40 and let clip generation start with
two thirds of its references missing.

Asserted on GET /songs/{id}/approve/{tier} — the page the operator sees.

Mutation: approve_context ranges over storyboards.scene_count → clip 20
missing and this fails.
"""
import inspect
import time

import build_song
import db
import app as appmod

from fastapi.testclient import TestClient


def test_t2_13c_approve_grid_lists_every_clip_when_storyboard_is_short():
    duration = 195.792
    scene_count = 20
    with TestClient(appmod.app) as client:
        sid = db.upsert_song(
            "t213c-short-sb", title="T2-13c Grid Song",
            album="T213c", duration=duration)
        db.run("""INSERT INTO storyboards (song_id, tier, json_path, md_path,
                                           scene_count, created)
                  VALUES (?,?,?,?,?,?)""",
               sid, "pg13", "/fake/t213c.json", "/fake/t213c.md",
               scene_count, time.time())
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        want = build_song.n_clips_for(duration)
        assert want == 41, want
        assert scene_count < want
        assert appmod.clip_count(song) == want
        assert appmod.clip_count(song) != scene_count

        page = client.get(f"/songs/{sid}/approve/pg13").text
        assert page
        assert "No storyboard/refs yet" not in page
        assert f'data-nclips="{want}"' in page
        assert f'data-nclips="{scene_count}"' not in page
        for i in range(want):
            assert f'data-clip="{i}"' in page, f"clip {i} missing from approve grid"
        assert f'data-clip="{want}"' not in page
        assert f"of {want} approved" in page


def test_t2_13c_approve_context_does_not_range_over_scene_count():
    """Mutation: for i in range(scene_count) in approve_context → red."""
    src = inspect.getsource(appmod.approve_context)
    assert "scene_count" not in src
    assert "clip_count(" in src
