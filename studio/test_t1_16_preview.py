"""T1-16 preview endpoint is a proxy and lists what it does not apply.

docs/TRD-1 §6.2: the response is {"is_proxy": true, "not_applied": [...]}
so the warning is data every client carries. Asserted by adding an
effect to an item and confirming it appears in not_applied; a static
list fails that. The browser plays source files with gain and position;
it does not mirror the ffmpeg chain.
"""
import json

from fastapi.testclient import TestClient

from conftest import _real_module
import app as appmod
import db
from test_app import _upload_song


def _mixer():
    mx = _real_module("mixer")
    assert mx is not None, "mixer.py failed to import"
    return mx


def test_t1_16_preview_proxy_declares_itself():
    payload = _mixer().preview_proxy([])
    assert payload["is_proxy"] is True
    assert payload["not_applied"] == []


def test_t1_16_adding_an_effect_lists_it_unused_keys_stay_off():
    """A static catalogue of every effect stays green. Adding echo_out
    must make that key appear, and eq_kill must stay off until added."""
    mx = _mixer()
    empty = mx.preview_proxy([{"effects_json": None}])
    assert empty["is_proxy"] is True
    assert "echo_out" not in empty["not_applied"]
    assert "eq_kill" not in empty["not_applied"]

    with_echo = mx.preview_proxy([{
        "effects_json": json.dumps({
            "echo_out": {"decay": 0.5, "delay": 200},
            "loudnorm": False,
        }),
    }])
    assert with_echo["is_proxy"] is True
    assert "echo_out" in with_echo["not_applied"]
    assert "eq_kill" not in with_echo["not_applied"]

    with_eq = mx.preview_proxy([{
        "effects_json": json.dumps({
            "eq_kill": {"low_db": -6, "mid_db": 0, "high_db": 0},
            "loudnorm": False,
        }),
    }])
    assert "eq_kill" in with_eq["not_applied"]
    assert "echo_out" not in with_eq["not_applied"]


def test_t1_16_proxy_applies_gain_and_position_so_they_are_not_listed():
    payload = _mixer().preview_proxy([{
        "effects_json": json.dumps({"pan": 0.6, "loudnorm": False}),
    }])
    assert payload["is_proxy"] is True
    assert "pan" not in payload["not_applied"]
    assert "gain_db" not in payload["not_applied"]


def test_t1_16_preview_endpoint_lists_added_effect():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T1-16 Preview Song")
        client.post("/sets/new", data={"name": "T1-16 Preview Set", "mode": "audio"})
        row = db.one("SELECT * FROM sets WHERE name=?", "T1-16 Preview Set")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})
        item = db.one("SELECT * FROM set_items WHERE set_id=?", row["id"])

        before = client.get(f"/api/sets/{row['id']}/preview")
        assert before.status_code == 200, before.text
        data = before.json()
        assert data["is_proxy"] is True
        assert "echo_out" not in data["not_applied"]

        echo = json.dumps({"echo_out": {"decay": 0.5, "delay": 200},
                           "loudnorm": False})
        r = client.post(f"/sets/{row['id']}/items/{item['id']}",
                        data={"transition": "cut", "secs": "0", "effects_json": echo})
        assert r.status_code in (200, 303), r.text

        after = client.get(f"/api/sets/{row['id']}/preview")
        assert after.status_code == 200, after.text
        data = after.json()
        assert data["is_proxy"] is True
        assert "echo_out" in data["not_applied"]
        assert "eq_kill" not in data["not_applied"]


def test_t1_16_missing_set_is_404():
    with TestClient(appmod.app) as client:
        r = client.get("/api/sets/999999/preview")
        assert r.status_code == 404
