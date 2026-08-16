"""Named uploaded poses: more than eight, per-image name + tier, assign as sheet."""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import make_anchor
from conftest import _real_module
from test_app import _png_bytes, _upload_song


def test_parse_score_confidence_is_min_of_identity_and_prompt():
    got = _real_module("vision").parse_score({
        "confidence": 95, "identity": 20, "prompt": 40, "notes": "human face, two tails",
    })
    assert got["confidence"] == 20
    assert got["identity"] == 20
    assert got["prompt"] == 40


def test_qc_tag_shows_identity_and_notes_when_they_diverge():
    tag = appmod.qc_tag({"qc_json": json.dumps({
        "confidence": 20, "identity": 20, "prompt": 40,
        "notes": "human face, two tails",
    })})
    assert "20% match" in tag
    assert "id 20%" in tag
    assert "pose 40%" in tag
    assert "human face" in tag


def test_custom_pose_view_omits_standing_backdrop():
    spec = make_anchor.view_entry("pose_9")
    assert spec.get("custom")
    assert "stance" in spec["backdrop_omit"]
    text = make_anchor.backdrop_for("pose_9")
    assert "stands upright" not in text


def test_named_pose_meta_and_assign():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Named Pose Song", album="Street Cats")
        album = song["album"]
        dest = os.path.join(db.DATA, "uploads", "anchors", "album", "Street_Cats")
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, "sit.png")
        open(path, "wb").write(_png_bytes())
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               None, "anchor_ref", path,
               json.dumps({"scope_value": album, "character_id": None}), time.time())
        row = db.one("SELECT * FROM assets WHERE path=?", path)
        r = client.post(f"/anchors/refs/{row['id']}/meta", data={
            "pose_name": "seated on the amp",
            "pose_tier": "xxx",
            "role": "identity",
            "pose_nude": "1",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["role"] == "pose"
        assert body["pose_name"] == "seated on the amp"
        assert body["pose_nude"] is True
        a = client.post(f"/anchors/refs/{row['id']}/assign", data={
            "album": album, "pose_name": "seated on the amp", "pose_tier": "xxx",
            "pose_nude": "1",
        }, follow_redirects=False)
        assert a.status_code == 303, a.text
        sheet = db.one("SELECT * FROM anchors WHERE view=?",
                       appmod.pose_view_key(row["id"], True))
        assert sheet is not None
        assert sheet["chosen"] == 1
        assert sheet["tier"] == "xxx"
        assert sheet["path"] == path
        assert json.loads(sheet["render_json"])["source"] == "upload"


def test_assign_uses_saved_name_when_form_repeats_empty_pose_name():
    """Assign is a submit of #anchor-form. Every card names pose_name; the
    first is often the unnamed identity pair. Saved meta must still win."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Assign Sibling Song", album="Street Cats")
        album = song["album"]
        dest = os.path.join(db.DATA, "uploads", "anchors", "album", "Street_Cats")
        os.makedirs(dest, exist_ok=True)
        blank = os.path.join(dest, "blank.png")
        named = os.path.join(dest, "named.png")
        open(blank, "wb").write(_png_bytes())
        open(named, "wb").write(_png_bytes())
        now = time.time()
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               None, "anchor_ref", blank,
               json.dumps({"scope_value": album, "character_id": None}), now)
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               None, "anchor_ref", named,
               json.dumps({"scope_value": album, "character_id": None,
                           "pose_name": "standing front", "pose_tier": "r",
                           "role": "pose"}), now + 1)
        row = db.one("SELECT * FROM assets WHERE path=?", named)
        a = client.post(f"/anchors/refs/{row['id']}/assign", data=[
            ("album", album),
            ("pose_name", ""),
            ("pose_name", "wrong sibling"),
            ("pose_tier", ""),
            ("pose_tier", "xxx"),
        ], follow_redirects=False)
        assert a.status_code == 303, a.text
        sheet = db.one("SELECT * FROM anchors WHERE view=?",
                       appmod.pose_view_key(row["id"], False))
        assert sheet is not None
        assert sheet["chosen"] == 1
        assert sheet["tier"] == "r"
        assert json.loads(sheet["render_json"])["pose_name"] == "standing front"


def test_upload_cap_is_twenty_four():
    assert appmod.MAX_ANCHOR_UPLOADS >= 16
