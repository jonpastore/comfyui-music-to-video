"""T7-23: use-as-ref / map / image1 only from keepers with usable≠skip.

usable=skip never enters a slot.

Mutation: a skip row is chosen as a map keeper or image1 → red.
"""
import json
import os
import tempfile
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as appmod
import classification
import db
import scene_pose_map
import tiers


def _png(name):
    path = os.path.join(tempfile.mkdtemp(prefix="t723_"), f"{name}.png")
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n")
    return path


def _image(iid, path, usable="pose", **over):
    row = {
        "id": iid,
        "path": path,
        "kind": "operator",
        "view": "front",
        "pose": "stand",
        "wardrobe": "clothed",
        "usable": usable,
    }
    row.update(over)
    return row


def _anchor(album, path, tier="r", view="front"):
    return db.run(
        """INSERT INTO anchors (scope_kind, scope_value, tier, view, path,
                               chosen, created)
           VALUES ('album',?,?,?,?,?,?)""",
        album, tier, view, path, 1, time.time())


def _ref_asset(album, path):
    return db.run(
        "INSERT INTO assets (song_id, kind, path, meta_json, created) "
        "VALUES (?,?,?,?,?)",
        None, "anchor_ref", path,
        json.dumps({"scope_value": album, "character_id": None}),
        time.time())


def test_t7_23_refuse_skip_by_path_or_id():
    """Helper: skip chosen → red; usable≠skip and unclassified → green."""
    album = f"T723 {time.time_ns()}"
    keep = _png("keep")
    skip = _png("skip")
    classification.save(album, {"images": [
        _image("keep-id", keep, usable="identity"),
        _image("skip-id", skip, usable="skip"),
    ]})
    classification.refuse_skip(album, path=keep)
    classification.refuse_skip(album, image_id="keep-id")
    classification.refuse_skip(album, path=_png("unclassified"))
    with pytest.raises(ValueError, match="usable=skip"):
        classification.refuse_skip(album, path=skip)
    with pytest.raises(ValueError, match="usable=skip"):
        classification.refuse_skip(album, image_id="skip-id")


def test_t7_23_use_as_ref_refuses_skip_allows_keeper():
    album = f"T723-ref {time.time_ns()}"
    skip = _png("skip-sheet")
    keep = _png("keep-sheet")
    skip_id = _anchor(album, skip)
    keep_id = _anchor(album, keep)
    classification.save(album, {"images": [
        _image("skip-sheet", skip, usable="skip"),
        _image("keep-sheet", keep, usable="identity"),
    ]})
    with pytest.raises(HTTPException) as err:
        appmod._use_anchor_as_ref(skip_id)
    assert err.value.status_code == 400
    assert "usable=skip" in str(err.value.detail)
    assert db.one(
        "SELECT id FROM assets WHERE kind='anchor_ref' AND path=?",
        skip) is None

    payload = appmod._use_anchor_as_ref(keep_id)
    assert payload["path"] == keep
    assert db.one(
        "SELECT id FROM assets WHERE kind='anchor_ref' AND path=?",
        keep)


def test_t7_23_collect_ref_paths_refuses_skip_allows_keeper():
    album = f"T723-col {time.time_ns()}"
    skip = _png("skip-ref")
    keep = _png("keep-ref")
    skip_aid = _ref_asset(album, skip)
    keep_aid = _ref_asset(album, keep)
    classification.save(album, {"images": [
        _image("skip-ref", skip, usable="skip"),
        _image("keep-ref", keep, usable="pose"),
    ]})
    with pytest.raises(HTTPException) as err:
        appmod._collect_anchor_ref_paths(album, None, [str(skip_aid)])
    assert err.value.status_code == 400
    assert "usable=skip" in str(err.value.detail)

    paths = appmod._collect_anchor_ref_paths(album, None, [str(keep_aid)])
    assert keep in paths or os.path.abspath(keep) in [
        os.path.abspath(p) for p in paths]


def test_t7_23_upsert_draft_and_accepted_bases_refuse_skip():
    """A skip row chosen as a map keeper or image1 is red."""
    tiers.ensure_builtins()
    stamp = f"t723-map-{time.time_ns()}"
    album = f"T723 {stamp}"
    sid = db.upsert_song(stamp, title="T7-23 Map Song", album=album)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    skip = _png("skip-keep")
    keep = _png("keep-keep")
    classification.save(album, {"images": [
        _image("skip-keep", skip, usable="skip"),
        _image("keep-keep", keep, usable="pose"),
    ]})
    now = time.time()
    with pytest.raises(ValueError, match="usable=skip"):
        scene_pose_map._upsert_draft(
            sid, "r", 1, {"id": "skip-keep", "path": skip}, now, album=album)
    assert not list(db.q(
        "SELECT * FROM scene_pose_map WHERE song_id=?", sid))

    scene_pose_map._upsert_draft(
        sid, "r", 1, {"id": "keep-keep", "path": keep}, now, album=album)
    row = db.one(
        "SELECT * FROM scene_pose_map WHERE song_id=? AND scene_number=1",
        sid)
    assert row["keeper_id"] == "keep-keep"
    assert row["path"] == keep

    db.run(
        """UPDATE scene_pose_map SET status='accepted', updated=?
           WHERE song_id=? AND tier='r' AND scene_number=1""",
        time.time(), sid)
    bases = scene_pose_map.accepted_bases(song, "r")
    assert bases[1] == keep

    db.run(
        """INSERT INTO scene_pose_map
           (song_id, tier, scene_number, keeper_id, path, status,
            prev_keeper_id, prev_path, created, updated)
           VALUES (?,?,?,?,?,'accepted',NULL,NULL,?,?)""",
        sid, "r", 2, "skip-keep", skip, time.time(), time.time())
    with pytest.raises(ValueError, match="usable=skip"):
        scene_pose_map.accepted_bases(song, "r")


def test_t7_23_http_use_as_ref_refuses_skip():
    album = f"T723-http {time.time_ns()}"
    skip = _png("http-skip")
    aid = _anchor(album, skip)
    classification.save(album, {"images": [
        _image("http-skip", skip, usable="skip"),
    ]})
    with TestClient(appmod.app) as client:
        refused = client.post(f"/api/anchors/{aid}/use-as-ref")
        assert refused.status_code == 400, refused.text
        assert "usable=skip" in refused.text.lower()
