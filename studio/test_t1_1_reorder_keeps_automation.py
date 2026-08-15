"""T1-1: reorder or trim leaves stored automation (lane, t, value) unchanged.

docs/TRD-1 §4.1. t is item-relative, so a set-relative rewrite on
reorder/trim is the mutation this fails. T1-2 / T6-10 only cover
delete. Empty-table "unchanged" is not the check: rows must exist
before the compare, and the edit itself must have landed.
"""
import os
import subprocess
import tempfile

from fastapi.testclient import TestClient

import app as appmod
import automation
import db


def _mp3_bytes(seconds=2):
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-t", str(seconds), "-i", "anullsrc",
         "-c:a", "libmp3lame", path],
        capture_output=True, check=True)
    data = open(path, "rb").read()
    os.remove(path)
    return data


def _upload_song(client, title):
    client.post("/songs", data={"title": title, "album": "", "genre": ""},
                files={"mp3": (f"{title}.mp3", _mp3_bytes(), "audio/mpeg")})
    return db.one("SELECT * FROM songs WHERE title=?", title)


def _new_set(client, name):
    r = client.post("/sets/new", data={"name": name, "mode": "audio"})
    assert r.status_code in (200, 303), r.text
    return db.one("SELECT * FROM sets WHERE name=?", name)


def _auto_triples(item_ids):
    """(lane, t, value) per stored point, ordered. The T1-1 compare."""
    if not item_ids:
        return []
    ph = ",".join("?" * len(item_ids))
    return [(r["lane"], r["t"], r["value"]) for r in db.q(
        f"SELECT lane, t, value FROM automation "
        f"WHERE set_item_id IN ({ph}) ORDER BY set_item_id, lane, t",
        *item_ids)]


def _store_curves(items):
    """Distinct stored curves so an empty table cannot pass the compare."""
    a = automation.save(items[0]["id"], "gain_db", [(0.0, -6.0), (0.8, 0.0)])
    b = automation.save(items[1]["id"], "pan", [(0.0, -0.4), (0.5, 0.3)])
    assert a and b, "T1-1 is vacuous without a stored curve"
    triples = _auto_triples([it["id"] for it in items])
    assert triples, "automation rows must exist before the compare"
    assert len(triples) >= 4, triples
    return triples


def test_t1_1_reorder_leaves_automation_lane_t_value_unchanged():
    """POST /sets/{id}/reorder must not rewrite (lane, t, value)."""
    with TestClient(appmod.app) as client:
        song1 = _upload_song(client, "T1-1 Reorder Song 1")
        song2 = _upload_song(client, "T1-1 Reorder Song 2")
        row = _new_set(client, "T1-1 Reorder Set")
        sid = row["id"]
        client.post(f"/sets/{sid}/items",
                    data={"song_id": song1["id"], "transition": "cut", "secs": "0"})
        client.post(f"/sets/{sid}/items",
                    data={"song_id": song2["id"], "transition": "cut", "secs": "0"})
        items = db.q("SELECT * FROM set_items WHERE set_id=? ORDER BY position", sid)
        assert len(items) == 2, items
        before = _store_curves(items)
        before_order = [it["id"] for it in items]

        r = client.post(f"/sets/{sid}/reorder",
                        data={"order": f"{items[1]['id']},{items[0]['id']}"})
        assert r.status_code in (200, 303), r.text
        after_order = [it["id"] for it in db.q(
            "SELECT id FROM set_items WHERE set_id=? ORDER BY position", sid)]
        assert after_order == [items[1]["id"], items[0]["id"]], after_order
        assert after_order != before_order, "reorder was a no-op"

        after = _auto_triples([it["id"] for it in items])
        assert after, "reorder deleted the stored curve"
        assert after == before


def test_t1_1_trim_leaves_automation_lane_t_value_unchanged():
    """Changing in_secs / out_secs / secs must not rewrite (lane, t, value)."""
    with TestClient(appmod.app) as client:
        song1 = _upload_song(client, "T1-1 Trim Song 1")
        song2 = _upload_song(client, "T1-1 Trim Song 2")
        row = _new_set(client, "T1-1 Trim Set")
        sid = row["id"]
        client.post(f"/sets/{sid}/items",
                    data={"song_id": song1["id"], "transition": "cut", "secs": "0"})
        client.post(f"/sets/{sid}/items",
                    data={"song_id": song2["id"], "transition": "fade", "secs": "0.4"})
        items = db.q("SELECT * FROM set_items WHERE set_id=? ORDER BY position", sid)
        first = items[0]
        assert first["in_secs"] is None or first["in_secs"] == 0
        before = _store_curves(items)

        r = client.post(f"/sets/{sid}/items/{first['id']}",
                        data={"in_secs": "0.25", "out_secs": "1.5", "gain_db": "0",
                              "transition": "cut", "secs": "0"})
        assert r.status_code in (200, 303), r.text
        edited = db.one("SELECT * FROM set_items WHERE id=?", first["id"])
        assert edited["in_secs"] == 0.25, dict(edited)
        assert edited["out_secs"] == 1.5, dict(edited)
        assert edited["secs"] == 0.0, dict(edited)

        after = _auto_triples([it["id"] for it in items])
        assert after, "trim deleted the stored curve"
        assert after == before
