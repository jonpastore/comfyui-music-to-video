"""T8-15: song-editor GET /api/songs/{id}/preview is a proxy.

docs/TRD-8 §6: T1-16's rule on this document's surface. Response is
{"is_proxy": true, "not_applied": [...]} from the editor item's effects.
Positive half: add an effect and confirm it appears; a static catalogue
or a removed endpoint fails that.
"""
import json

from fastapi.testclient import TestClient

import app as appmod
import automation
import db


def _song():
    return db.upsert_song("t8-15-preview", title="T8-15 Song Preview", duration=8.0)


def test_t8_15_preview_declares_proxy_and_lists_editor_effect():
    """Endpoint returns proxy data and a non-empty not_applied list when
    the editor item carries an effect the browser does not apply."""
    sid = _song()
    with TestClient(appmod.app) as client:
        before = client.get(f"/api/songs/{sid}/preview")
        assert before.status_code == 200, before.text
        data = before.json()
        assert data["is_proxy"] is True
        assert "echo_out" not in data["not_applied"]
        assert "eq_kill" not in data["not_applied"]

        echo = json.dumps({
            "echo_out": {"decay": 0.5, "delay": 200},
            "loudnorm": False,
        })
        item = automation.editor_item(sid)
        db.run("UPDATE set_items SET effects_json=? WHERE id=?", echo, item)

        after = client.get(f"/api/songs/{sid}/preview")
        assert after.status_code == 200, after.text
        data = after.json()
        assert data["is_proxy"] is True
        assert "echo_out" in data["not_applied"], data
        assert data["not_applied"], "not_applied must be non-empty when effect is set"
        assert "eq_kill" not in data["not_applied"]


def test_t8_15_not_applied_comes_from_editor_item_not_static_list():
    """eq_kill appears only after it is stored on the editor item."""
    sid = _song()
    item = automation.editor_item(sid)
    eq = json.dumps({
        "eq_kill": {"low_db": -6, "mid_db": 0, "high_db": 0},
        "loudnorm": False,
    })
    db.run("UPDATE set_items SET effects_json=? WHERE id=?", eq, item)
    with TestClient(appmod.app) as client:
        r = client.get(f"/api/songs/{sid}/preview")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["is_proxy"] is True
        assert "eq_kill" in data["not_applied"]
        assert "echo_out" not in data["not_applied"]


def test_t8_15_proxy_does_not_list_gain_or_pan():
    """Browser applies gain and position; they stay off not_applied."""
    sid = _song()
    item = automation.editor_item(sid)
    pan = json.dumps({"pan": 0.6, "loudnorm": False})
    db.run("UPDATE set_items SET effects_json=? WHERE id=?", pan, item)
    with TestClient(appmod.app) as client:
        r = client.get(f"/api/songs/{sid}/preview")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["is_proxy"] is True
        assert "pan" not in data["not_applied"]
        assert "gain_db" not in data["not_applied"]


def test_t8_15_missing_song_is_404():
    with TestClient(appmod.app) as client:
        r = client.get("/api/songs/999999/preview")
        assert r.status_code == 404
