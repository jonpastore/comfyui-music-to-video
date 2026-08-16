#!/usr/bin/env python3
"""Song-level media bag: takes, audio_edit, audio_original, assembled renders.

docs/TRD-8 T8-16 / TRD-1 §11 media menu. One list the HTML card and
GET /api/songs/{id}/media share (T6-A2). Picking/using a take is T8-2,
not this module. Imports nothing from FastAPI (T6-A3).

    python3 media_service.py      # self-check against a temporary database
"""
import os
import time

import db

EMPTY_REASON = "empty"

# Kind order for the bag list: generation candidates, edits, original, video.
_KIND_ORDER = ("take", "audio_edit", "audio_original", "render")


def _json_row(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return {k: row[k] for k in row.keys()}


def require_song(song_id):
    song = db.one("SELECT * FROM songs WHERE id=?", song_id)
    if not song:
        raise LookupError(f"no such song: {song_id}")
    return song


def _item(kind, row_id, path, *, label=None, extra=None):
    out = {
        "kind": kind,
        "id": int(row_id),
        "path": path or "",
        "label": label or "",
    }
    if extra:
        out.update(extra)
    return out


def list_bag(song_id):
    """Song-level media bag: one list + counts. Empty bag carries reason.

    Items are takes, audio_edit assets, audio_original assets, and assembled
    renders. Source-row ids stay on each item; kind disambiguates collisions
    across tables. No pick/use decision lives here.
    """
    require_song(song_id)
    items = []

    for t in db.list_takes(song_id):
        origin = t["origin"] or "generated"
        items.append(_item(
            "take", t["id"], t["path"],
            label=f"take #{t['id']} ({origin})",
            extra={
                "origin": origin,
                "picked": bool(t["picked"]),
                "duration": t["duration"],
                "seed": t["seed"],
            },
        ))

    for a in db.q(
            "SELECT * FROM assets WHERE song_id=? AND kind='audio_edit' ORDER BY id",
            song_id):
        items.append(_item(
            "audio_edit", a["id"], a["path"],
            label=f"audio_edit #{a['id']}",
        ))

    for a in db.q(
            "SELECT * FROM assets WHERE song_id=? AND kind='audio_original' ORDER BY id",
            song_id):
        items.append(_item(
            "audio_original", a["id"], a["path"],
            label=f"audio_original #{a['id']}",
        ))

    for r in db.q(
            "SELECT * FROM renders WHERE song_id=? ORDER BY id",
            song_id):
        items.append(_item(
            "render", r["id"], r["path"],
            label=f"render #{r['id']} ({r['tier']})",
            extra={"tier": r["tier"]},
        ))

    n_takes = sum(1 for it in items if it["kind"] == "take")
    n_audio_edits = sum(1 for it in items if it["kind"] == "audio_edit")
    n_audio_original = sum(1 for it in items if it["kind"] == "audio_original")
    n_renders = sum(1 for it in items if it["kind"] == "render")
    count = len(items)
    return {
        "song_id": int(song_id),
        "items": items,
        "count": count,
        "reason": EMPTY_REASON if count == 0 else None,
        "n_takes": n_takes,
        "n_audio_edits": n_audio_edits,
        "n_audio_original": n_audio_original,
        "n_renders": n_renders,
    }


def _selfcheck():
    """Exercise empty + populated bag without FastAPI."""
    data = os.environ.get("STUDIO_DATA") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data-media-selfcheck")
    os.environ["STUDIO_DATA"] = data
    os.makedirs(data, exist_ok=True)
    import importlib
    importlib.reload(db)
    db.init()
    sid = db.upsert_song(f"media-sc-{time.time_ns()}", title="media selfcheck")
    empty = list_bag(sid)
    assert empty["count"] == 0 and empty["reason"] == EMPTY_REASON, empty
    assert empty["items"] == [], empty
    db.insert_take(sid, "/t.mp3", "generated", tags="x")
    db.run(
        "INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
        sid, "audio_edit", "/e.mp3", None, time.time())
    db.run(
        "INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
        sid, "audio_original", "/o.mp3", None, time.time())
    db.run(
        "INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
        sid, "pg13", "/r.mp4", time.time())
    bag = list_bag(sid)
    assert bag["count"] == 4, bag
    assert bag["reason"] is None, bag
    assert bag["n_takes"] == 1 and bag["n_audio_edits"] == 1, bag
    assert bag["n_audio_original"] == 1 and bag["n_renders"] == 1, bag
    kinds = [it["kind"] for it in bag["items"]]
    assert kinds == list(_KIND_ORDER), kinds
    print("media_service selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
