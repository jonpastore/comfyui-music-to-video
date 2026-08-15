"""T1-11: two automation points at the same t are refused at the API.

docs/TRD-1 §5.1. Two values at one instant have no defined render. The
module demo already refuses; this is the route the client posts to.
"""
from fastapi.testclient import TestClient

import app as appmod
import db


_SAME_T = 2.25


def test_t1_11_same_t_is_refused_at_the_api_naming_the_time():
    """POST two gain_db points at one t is 400 and the body names that t."""
    sid = db.upsert_song("t1-11-same-t", title="T1-11 Same T", duration=12.3)
    with TestClient(appmod.app) as client:
        created = client.post("/api/sets", json={"name": "T1-11 Same T Set",
                                                 "mode": "audio"})
        assert created.status_code == 200, created.text
        set_id = created.json()["set"]["id"]
        added = client.post(f"/api/sets/{set_id}/items",
                            json={"song_id": sid, "transition": "cut", "secs": 0})
        assert added.status_code == 200, added.text
        items = added.json()["items"]
        assert items, added.json()
        item_id = items[0]["id"]

        r = client.post(
            f"/api/sets/{set_id}/items/{item_id}/automation/gain_db",
            json={"points": [[_SAME_T, -3.0], [_SAME_T, -6.0]]},
        )
        assert r.status_code == 400, r.text
        assert f"t={_SAME_T}" in r.text, r.text
        assert db.q(
            "SELECT * FROM automation WHERE set_item_id=?", item_id) == []
