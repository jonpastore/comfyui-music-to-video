"""T10-6: a library bulk edit is one transaction (T6-14 on this surface).

POST /songs/genres is the shared entry point the Library page already calls.
The positive half writes every target row; an induced mid-batch failure
writes none. Measured on stored rows so an endpoint that always refuses
cannot stay green.
"""
import time

import db
import app as appmod
from fastapi.testclient import TestClient


BEFORE = {
    "genre": "Rock",
    "subgenre": "Classic Rock",
    "genre2": "Electronic",
    "subgenre2": "Techno (Peak Time / Driving)",
}
AFTER = {
    "genre": "Electronic",
    "subgenre": "House",
    "genre2": "Dance",
    "subgenre2": "Trance",
}


def _fields(sid):
    row = db.one(
        "SELECT genre, subgenre, genre2, subgenre2 FROM songs WHERE id=?", sid)
    return {k: row[k] or "" for k in BEFORE}


def _twelve(prefix):
    ids = []
    for i in range(12):
        ids.append(db.upsert_song(
            f"{prefix}-{i}-{time.time_ns()}",
            title=f"{prefix}-{i}",
            **BEFORE))
    return ids


def _control(prefix):
    return db.upsert_song(
        f"{prefix}-ctrl-{time.time_ns()}", title=f"{prefix}-ctrl", **BEFORE)


def test_t10_6_successful_multi_row_bulk_writes_all_target_rows():
    """A successful twelve-row edit writes all twelve. Refusing every write
    would keep the crash-rollback half green."""
    ids = _twelve("t10-6-ok")
    other = _control("t10-6-ok")
    with TestClient(appmod.app) as client:
        r = client.post("/songs/genres", json={"song_ids": ids, **AFTER})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {u["song_id"] for u in body["updated"]} == set(ids)
    assert [_fields(sid) for sid in ids] == [AFTER] * 12
    assert _fields(other) == BEFORE


class _ConnProxy:
    def __init__(self, conn, execute):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "execute", execute)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _fail_on_nth_songs_update(n):
    """Raise before the nth UPDATE of songs, via db.conn().execute / db.run.

    A single `UPDATE songs SET … WHERE id IN (…)` is already one statement
    and counts as one — that shape is atomic, so the first (only) write
    is the one that fails and stored rows stay put.
    """
    state = {"n": 0, "on": True}
    real_conn = db.conn

    def wrapped_conn():
        c = real_conn()

        def execute(sql, *args, **kwargs):
            if state["on"]:
                text = sql if isinstance(sql, str) else ""
                head = text.strip().upper().split()
                if head[:2] == ["UPDATE", "SONGS"]:
                    state["n"] += 1
                    if state["n"] >= n:
                        raise RuntimeError("induced mid-batch failure")
            return c.execute(sql, *args, **kwargs)

        return _ConnProxy(c, execute)

    db.conn = wrapped_conn

    def restore():
        state["on"] = False
        db.conn = real_conn

    return restore


def test_t10_6_induced_mid_batch_failure_writes_none():
    """Twelve songs edited and a crash halfway leaves twelve unedited, not six."""
    ids = _twelve("t10-6-boom")
    other = _control("t10-6-boom")
    restore = _fail_on_nth_songs_update(7)
    try:
        with TestClient(appmod.app, raise_server_exceptions=False) as client:
            r = client.post("/songs/genres", json={"song_ids": ids, **AFTER})
        assert r.status_code >= 400, r.text
        assert [_fields(sid) for sid in ids] == [BEFORE] * 12, (
            "mid-batch failure wrote a partial library edit; "
            f"stored={[ _fields(sid) for sid in ids ]}")
        assert _fields(other) == BEFORE
    finally:
        restore()
