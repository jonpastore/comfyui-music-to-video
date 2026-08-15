"""T10-3…T10-7: library bulk genre remainder.

POST /songs/genres is the shared entry point the Library page already calls.
Genre fields only — not a second lyrics system.

T10-6 (one transaction) already landed. This file now also asserts the
rest of the surface: blank leaves a field alone, toggle-all is the shown
set, one invalid value refuses the batch, and the pre-write count is the
count that actually changes.
"""
import os
import re
import time

import db
import app as appmod
from fastapi.testclient import TestClient

_APP_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "app.js")


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


def test_t10_6_induced_mid_batch_failure_writes_none():
    """Twelve songs edited and a crash halfway leaves twelve unedited, not six.

    A BEFORE UPDATE trigger raises on the seventh target. Per-row db.run would
    already have committed six; one transaction writes none. A single
    UPDATE … WHERE id IN (…) fires the trigger per row and is still one
    statement, so it stays atomic too.
    """
    ids = _twelve("t10-6-boom")
    other = _control("t10-6-boom")
    boom = int(ids[6])
    db.run("DROP TRIGGER IF EXISTS t10_6_boom")
    db.run(
        f"""CREATE TRIGGER t10_6_boom
            BEFORE UPDATE ON songs
            WHEN NEW.id = {boom}
            BEGIN
              SELECT RAISE(ROLLBACK, 'induced mid-batch failure');
            END""")
    try:
        with TestClient(appmod.app, raise_server_exceptions=False) as client:
            r = client.post("/songs/genres", json={"song_ids": ids, **AFTER})
        assert r.status_code >= 400, r.text
        assert [_fields(sid) for sid in ids] == [BEFORE] * 12, (
            "mid-batch failure wrote a partial library edit; "
            f"stored={[ _fields(sid) for sid in ids ]}")
        assert _fields(other) == BEFORE
    finally:
        db.run("DROP TRIGGER IF EXISTS t10_6_boom")


def test_t10_3_blank_leaves_field_alone_and_nonblank_writes():
    """T10-3: setting only genre2 on twelve songs must not wipe genre.

    The one-sided trap is an endpoint that writes nothing. Same request
    must write the non-blank field. Measured on stored rows before and after.
    """
    ids = _twelve("t10-3")
    other = _control("t10-3")
    assert [_fields(sid) for sid in ids] == [BEFORE] * 12
    with TestClient(appmod.app) as client:
        r = client.post("/songs/genres", json={
            "song_ids": ids,
            "genre": "", "subgenre": "",
            "genre2": AFTER["genre2"], "subgenre2": AFTER["subgenre2"],
        })
    assert r.status_code == 200, r.text
    expected = {**BEFORE, "genre2": AFTER["genre2"],
                "subgenre2": AFTER["subgenre2"]}
    assert [_fields(sid) for sid in ids] == [expected] * 12
    assert _fields(other) == BEFORE


def test_t10_4_toggle_all_is_the_shown_set():
    """T10-4: toggle-all applies to rows currently shown, not every song.

    Hidden rows stay out of the posted set. Filtering, toggling all, and
    counting what changed: 12 shown change, 3 hidden do not.
    """
    shown = _twelve("t10-4-vis")
    hidden = [_control("t10-4-hid1"), _control("t10-4-hid2"),
              _control("t10-4-hid3")]
    js = open(_APP_JS, encoding="utf-8").read()
    assert "function shown()" in js
    shown_fn = js[js.index("function shown()"): js.index("function shown()") + 280]
    assert "offsetParent" in shown_fn, shown_fn
    handler = js[js.index('all.addEventListener("change"'):]
    handler = handler[: handler.index("});") + 3]
    assert "shown()" in handler, handler
    with TestClient(appmod.app) as client:
        page = client.get("/")
        assert page.status_code == 200, page.text
        assert 'id="pick-all"' in page.text
        assert "shown" in page.text.lower()
        r = client.post("/songs/genres", json={"song_ids": shown, **AFTER})
    assert r.status_code == 200, r.text
    assert [_fields(sid) for sid in shown] == [AFTER] * 12
    assert [_fields(sid) for sid in hidden] == [BEFORE] * 3


def test_t10_4_unfiltered_library_lists_every_row():
    """T10-4 positive half: with no filter, toggle-all's shown set is every row."""
    ids = _twelve("t10-4-all")
    with TestClient(appmod.app) as client:
        page = client.get("/")
    assert page.status_code == 200, page.text
    listed = {int(x) for x in re.findall(r'data-song="(\d+)"', page.text)}
    assert set(ids) <= listed, (set(ids) - listed, listed)


def test_t10_5_invalid_genre_refuses_the_whole_batch():
    """T10-5: one invalid value refuses the batch; nothing is written.

    Valid genre + invalid genre2 must not write the valid half.
    """
    ids = _twelve("t10-5-bad")
    with TestClient(appmod.app) as client:
        r = client.post("/songs/genres", json={
            "song_ids": ids,
            "genre": AFTER["genre"], "subgenre": AFTER["subgenre"],
            "genre2": "NotAGenre", "subgenre2": "",
        })
    assert r.status_code == 400, r.text
    assert [_fields(sid) for sid in ids] == [BEFORE] * 12


def test_t10_5_valid_batch_writes_all():
    """T10-5 positive half: a valid batch writes every target row."""
    ids = _twelve("t10-5-ok")
    with TestClient(appmod.app) as client:
        r = client.post("/songs/genres", json={"song_ids": ids, **AFTER})
    assert r.status_code == 200, r.text
    assert [_fields(sid) for sid in ids] == [AFTER] * 12


def test_t10_7_prewrite_count_equals_rows_changed():
    """T10-7: the pre-write count is the count that actually changes.

    Twelve selected, three already the target: preview says 9, write
    changes exactly those nine. A confirmation that says 12 and edits 9
    is the named failure. Preview writes nothing.
    """
    changing = []
    for i in range(9):
        changing.append(db.upsert_song(
            f"t10-7-chg-{i}-{time.time_ns()}",
            title=f"t10-7-chg-{i}", **BEFORE))
    already = []
    for i in range(3):
        already.append(db.upsert_song(
            f"t10-7-had-{i}-{time.time_ns()}",
            title=f"t10-7-had-{i}", **AFTER))
    ids = changing + already
    payload = {"song_ids": ids, **AFTER}
    with TestClient(appmod.app) as client:
        page = client.get("/")
        assert 'id="bulk-count"' in page.text
        pre = client.post("/songs/genres", json={**payload, "preview": True})
        assert pre.status_code == 200, pre.text
        body = pre.json()
        assert body["would_change"] == 9, body
        assert set(body["song_ids"]) == set(changing), body
        assert [_fields(sid) for sid in changing] == [BEFORE] * 9, (
            "preview wrote a row; T10-7's count is before the write")
        assert [_fields(sid) for sid in already] == [AFTER] * 3
        wrote = client.post("/songs/genres", json=payload)
    assert wrote.status_code == 200, wrote.text
    out = wrote.json()
    assert out.get("changed") == 9, out
    assert {u["song_id"] for u in out["updated"]} == set(changing), out
    assert [_fields(sid) for sid in changing] == [AFTER] * 9
    assert [_fields(sid) for sid in already] == [AFTER] * 3
