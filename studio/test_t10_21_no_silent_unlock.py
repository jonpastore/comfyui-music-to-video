"""T10-21: removing a minor reference does not silently unlock.

Unlocking is an explicit act on an empty re-screen result. Prior renders
keep their attribution after unlock so a work cannot be laundered from
child-safe to explicit by an edit.

docs/TRD-10-LIBRARY-LYRICS-AND-THE-ADVICE-SURFACES.md T10-21.
"""
import json
import time

import pytest
from fastapi.testclient import TestClient

import app as appmod
import db
import guardrail
from test_app import _real_storyboard, _scene, _upload_song


NIECE = "a 7 year old child dancing in the garden, fully clothed"
CLEAN = "a sleek black feline DJ on a neon rooftop at night"


def _lock_with_niece_scene(client, title):
    song = _upload_song(client, title, album=f"{title}-album")
    sid, slug = song["id"], song["slug"]
    _real_storyboard(sid, "g", slug, [_scene(1)])
    r = client.post(
        f"/songs/{sid}/storyboard/g/scene/1",
        data={"image_prompt": NIECE})
    assert r.status_code == 200, r.text
    row = db.one("SELECT minor_locked FROM songs WHERE id=?", sid)
    assert row is not None
    assert int(row["minor_locked"] or 0) == 1, (
        "accepting a minor reference at g must lock the work")
    return song


def test_t10_21_clearing_reference_does_not_silently_unlock():
    """Edit out the child wording; the work stays locked until unlock."""
    with TestClient(appmod.app) as client:
        song = _lock_with_niece_scene(
            client, f"t10-21-silent-{time.time_ns()}")
        sid = song["id"]

        cleared = client.post(
            f"/songs/{sid}/storyboard/g/scene/1",
            data={"image_prompt": CLEAN})
        assert cleared.status_code == 200, cleared.text
        after = db.one("SELECT minor_locked FROM songs WHERE id=?", sid)
        assert int(after["minor_locked"] or 0) == 1, (
            "removing the reference silently unlocked the work")


def test_t10_21_explicit_unlock_on_cleaned_work_succeeds():
    """Positive half: explicit unlock after a clean re-screen succeeds."""
    with TestClient(appmod.app) as client:
        song = _lock_with_niece_scene(
            client, f"t10-21-unlock-{time.time_ns()}")
        sid = song["id"]

        client.post(
            f"/songs/{sid}/storyboard/g/scene/1",
            data={"image_prompt": CLEAN})
        assert int(db.one(
            "SELECT minor_locked FROM songs WHERE id=?", sid)["minor_locked"]) == 1

        r = client.post(f"/songs/{sid}/unlock-minor")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("unlocked") is True, body
        after = db.one("SELECT minor_locked FROM songs WHERE id=?", sid)
        assert int(after["minor_locked"] or 0) == 0


def test_t10_21_unlock_refuses_while_reference_remains():
    """Empty result is required; leftover child wording blocks unlock."""
    with TestClient(appmod.app) as client:
        song = _lock_with_niece_scene(
            client, f"t10-21-refuse-{time.time_ns()}")
        sid = song["id"]

        r = client.post(f"/songs/{sid}/unlock-minor")
        assert r.status_code == 400, r.text
        low = r.text.lower()
        assert "child" in low or "minor" in low or "unlock" in low, r.text
        assert int(db.one(
            "SELECT minor_locked FROM songs WHERE id=?", sid)["minor_locked"]) == 1


def test_t10_21_prior_renders_keep_attribution_after_unlock():
    """Renders made while locked keep minor-lock attribution after unlock."""
    with TestClient(appmod.app) as client:
        song = _lock_with_niece_scene(
            client, f"t10-21-attr-{time.time_ns()}")
        sid = song["id"]

        meta = appmod.attributed_meta_for_song(sid, "g", {"kind": "still"})
        key = guardrail.MINOR_LOCK_ATTRIBUTION_KEY
        assert key in meta and meta[key].get("locked_depict") is True, meta
        aid = db.run(
            "INSERT INTO assets (song_id, kind, path, meta_json, created) "
            "VALUES (?,?,?,?,?)",
            sid, "ref", f"/tmp/t10-21-{sid}.png",
            json.dumps(meta), time.time())

        client.post(
            f"/songs/{sid}/storyboard/g/scene/1",
            data={"image_prompt": CLEAN})
        unlocked = client.post(f"/songs/{sid}/unlock-minor")
        assert unlocked.status_code == 200, unlocked.text
        assert unlocked.json().get("unlocked") is True

        stored = db.jset(db.one("SELECT * FROM assets WHERE id=?", aid))
        assert key in stored, stored
        assert stored[key].get("locked_depict") is True, stored
        assert int(db.one(
            "SELECT minor_locked FROM songs WHERE id=?", sid)["minor_locked"]) == 0
