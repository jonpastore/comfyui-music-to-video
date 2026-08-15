"""T1-timeline: the set editor has a server-owned time axis.

docs/TRD-1 §1 / ledger "the timeline itself": set_edit is a stack of
forms and `.timeline`/`.tl-block` is a proportional strip with no
ruler. The axis is seconds from mixer.set_duration(), rendered as HTML
by the server. A browser that is not running JS still sees the ticks —
TestClient has no DOM, so ticks invented in app.js cannot pass.

Same differential as T1-8: stub set_duration by a known offset and the
last tick's data-t moves by exactly that offset. A ruler that ignores
set_duration, or that hardcodes 0 and the item length, stays put. A
ruler that ends on the last nice step below the duration (120 for a
125 s set) would also stay put under a +17 s stub.

Joins, lanes and the playhead sit on that same axis. Each is HTML with
data-t in seconds. TestClient has no pointer, so a JS-only handle
cannot pass. Stored secs / stored curve / ?at= are the one variable.
"""
import re

from conftest import _real_module
from fastapi.testclient import TestClient

import app as appmod
import automation
import db
from test_app import _upload_song


_BASE_S = 125.0
_OFFSET_S = 17.0
_PLAY = 10.0
_STUB_ITEM_S = 12.3

mixer = _real_module("mixer")
assert mixer is not None, "mixer.py failed to import"


def _axis_ticks(html):
    """data-t values on the server-rendered ruler. Presence of class=
    timeline is not enough: that strip already exists and has no axis."""
    assert 'class="tl-axis"' in html, "set editor has no .tl-axis ruler"
    ticks = [float(t) for t in re.findall(
        r'class="tl-tick"[^>]*data-t="([^"]+)"', html)]
    if not ticks:
        ticks = [float(t) for t in re.findall(
            r'data-t="([^"]+)"[^>]*class="tl-tick"', html)]
    assert ticks, "tl-axis is present but carries no data-t ticks"
    return ticks


def test_t1_timeline_axis_empty_duration_is_empty():
    """A set with no length must not invent a ruler. [] is honest; a
    0:00–0:00 axis would look like a silent song (TRD-1 T1-15's shape)."""
    assert mixer.timeline_axis(None) == []
    assert mixer.timeline_axis(0) == []
    assert mixer.timeline_axis(-1) == []


def test_t1_timeline_axis_ends_on_duration():
    """The last tick IS the duration, not the last nice step below it.
    125 s with a 30 s step would otherwise end at 120 and a +17 s stub
    would still end at 120 — the differential would be vacuous."""
    ticks = mixer.timeline_axis(_BASE_S)
    assert ticks[0]["t"] == 0.0
    assert ticks[-1]["t"] == _BASE_S
    assert len(ticks) >= 3, ticks
    assert all(ticks[i]["t"] < ticks[i + 1]["t"] for i in range(len(ticks) - 1))


def test_t1_timeline_page_axis_tracks_set_duration_offset(patch_stub):
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T1-Timeline Song")
        client.post("/sets/new", data={"name": "T1-Timeline Set", "mode": "audio"})
        row = db.one("SELECT * FROM sets WHERE name='T1-Timeline Set'")
        assert row is not None
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})

        returns = [_BASE_S]

        def _stub(items, key="video"):
            assert items, "set_duration called with no items"
            return returns[0]

        patch_stub("mixer", set_duration=_stub)

        before = _axis_ticks(client.get(f"/sets/{row['id']}").text)
        assert before[0] == 0.0
        assert before[-1] == _BASE_S, (
            f"last tick {before[-1]!r} is not set_duration()={_BASE_S}")

        returns[0] = _BASE_S + _OFFSET_S
        after = _axis_ticks(client.get(f"/sets/{row['id']}").text)
        assert after[-1] == _BASE_S + _OFFSET_S, (
            f"last tick {after[-1]!r} is not stub offset "
            f"{_BASE_S + _OFFSET_S}")
        assert after[-1] - before[-1] == _OFFSET_S, (
            f"axis moved by {after[-1] - before[-1]}s, not {_OFFSET_S}s "
            f"({before[-1]} -> {after[-1]})")


def _block(item_id, duration, transition="fade", secs=2.0, hold=0.0):
    return {"id": item_id, "duration": duration, "transition": transition,
            "secs": secs, "hold": hold}


def _attr_floats(html, cls, attr="data-t"):
    found = [float(v) for v in re.findall(
        rf'class="{cls}"[^>]*{attr}="([^"]+)"', html)]
    if not found:
        found = [float(v) for v in re.findall(
            rf'{attr}="([^"]+)"[^>]*class="{cls}"', html)]
    return found


def _join_ts(html):
    assert 'class="tl-join"' in html or "class='tl-join'" in html, (
        "set editor has no .tl-join on the axis")
    ts = _attr_floats(html, "tl-join")
    assert ts, "tl-join is present but carries no data-t"
    return ts


def _playhead_t(html):
    assert 'class="tl-playhead"' in html or "class='tl-playhead'" in html, (
        "set editor has no .tl-playhead on the axis")
    ts = _attr_floats(html, "tl-playhead")
    assert ts, "tl-playhead is present but carries no data-t"
    assert len(ts) == 1, ts
    return ts[0]


def test_t1_timeline_joins_empty_when_one_item_or_no_clock():
    """A lone item has no handover. A clockless set must not invent one."""
    assert mixer.timeline_joins([], _BASE_S) == []
    assert mixer.timeline_joins([_block(1, _PLAY)], _BASE_S) == []
    assert mixer.timeline_joins(
        [_block(1, _PLAY), _block(2, _PLAY)], 0) == []
    assert mixer.timeline_joins(
        [_block(1, _PLAY), _block(2, _PLAY)], None) == []


def test_t1_timeline_joins_sit_at_overlap_start():
    """Join t is the start of the overlap, walked with _advance.

    fade 2s on two 10s items: next starts at 8, join is there. A cut
    lands at 10. A marker parked at 50% of the set would stay put when
    only secs changes.
    """
    fade = mixer.timeline_joins(
        [_block(1, _PLAY, "fade", 2.0), _block(2, _PLAY)], 18.0)
    assert len(fade) == 1, fade
    assert fade[0]["t"] == 8.0, fade[0]
    assert fade[0]["item_id"] == 1
    assert fade[0]["secs"] == 2.0
    assert fade[0]["transition"] == "fade"
    assert fade[0]["pct"] == 100.0 * 8.0 / 18.0

    cut = mixer.timeline_joins(
        [_block(1, _PLAY, "cut", 0.0), _block(2, _PLAY)], 20.0)
    assert cut[0]["t"] == 10.0, cut[0]

    longer = mixer.timeline_joins(
        [_block(1, _PLAY, "fade", 4.0), _block(2, _PLAY)], 16.0)
    assert longer[0]["t"] == 6.0, longer[0]
    assert fade[0]["t"] - longer[0]["t"] == 2.0


def test_t1_timeline_page_joins_track_stored_secs():
    """HTML joins are the stored handover. Changing secs moves data-t.

    TestClient has no drag; the write is the same form the pointer
    submits. A label inside .tl-block that ignores secs stays put.
    """
    with TestClient(appmod.app) as client:
        a = _upload_song(client, "T1-Join A")
        b = _upload_song(client, "T1-Join B")
        client.post("/sets/new", data={"name": "T1-Join Set", "mode": "audio"})
        row = db.one("SELECT * FROM sets WHERE name='T1-Join Set'")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": a["id"], "transition": "fade", "secs": "2"})
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": b["id"], "transition": "cut", "secs": "0"})
        first = db.one(
            "SELECT * FROM set_items WHERE set_id=? ORDER BY position",
            row["id"])
        html = client.get(f"/sets/{row['id']}").text
        join_html = html.split('class="tl-join"', 1)[-1][:200]
        if 'class="tl-join"' not in html:
            join_html = html.split("class='tl-join'", 1)[-1][:200]
        assert 'draggable="true"' in join_html
        before = _join_ts(html)
        assert before == [mixer.timeline_joins(
            [_block(first["id"], _STUB_ITEM_S, "fade", 2.0),
             _block(0, _STUB_ITEM_S)],
            _STUB_ITEM_S + _STUB_ITEM_S - 2.0)[0]["t"]]

        r = client.post(f"/sets/{row['id']}/items/{first['id']}/join",
                        data={"secs": "4"})
        assert r.status_code in (200, 303), r.text
        stored = db.one(
            "SELECT secs, gain_db, transition FROM set_items WHERE id=?",
            first["id"])
        assert stored["secs"] == 4.0
        assert stored["transition"] == "fade", "join POST must not reset the kind"
        assert (stored["gain_db"] or 0) == 0, "join POST must not wipe gain"

        after = _join_ts(client.get(f"/sets/{row['id']}").text)
        assert after[0] == mixer.timeline_joins(
            [_block(first["id"], _STUB_ITEM_S, "fade", 4.0),
             _block(0, _STUB_ITEM_S)],
            _STUB_ITEM_S + _STUB_ITEM_S - 4.0)[0]["t"]
        assert before[0] - after[0] == 2.0, (before, after)


def test_t1_timeline_playhead_empty_without_clock():
    assert mixer.timeline_playhead(0, None) is None
    assert mixer.timeline_playhead(0, 0) is None
    assert mixer.timeline_playhead(5, -1) is None


def test_t1_timeline_playhead_clamps_to_duration():
    """Default is 0. Off-axis times are clipped, not wrapped or dropped."""
    zero = mixer.timeline_playhead(None, _BASE_S)
    assert zero["t"] == 0.0
    assert zero["pct"] == 0.0
    mid = mixer.timeline_playhead(17.0, _BASE_S)
    assert mid["t"] == 17.0
    assert mid["pct"] == 100.0 * 17.0 / _BASE_S
    assert mixer.timeline_playhead(-4, _BASE_S)["t"] == 0.0
    assert mixer.timeline_playhead(200, _BASE_S)["t"] == _BASE_S
    assert mixer.timeline_playhead(200, _BASE_S + _OFFSET_S)["t"] == (
        _BASE_S + _OFFSET_S)


def test_t1_timeline_page_playhead_tracks_at_and_duration(patch_stub):
    """?at= is the playhead. Clamped to stubbed set_duration(), so a
    hardcoded 0 or an unclamped 200 both fail the offset."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T1-Playhead Song")
        client.post("/sets/new", data={"name": "T1-Playhead Set", "mode": "audio"})
        row = db.one("SELECT * FROM sets WHERE name='T1-Playhead Set'")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})

        returns = [_BASE_S]

        def _stub(items, key="video"):
            return returns[0]

        patch_stub("mixer", set_duration=_stub)

        default = _playhead_t(client.get(f"/sets/{row['id']}").text)
        assert default == 0.0

        at = _playhead_t(client.get(f"/sets/{row['id']}", params={"at": 17}).text)
        assert at == 17.0

        hi = _playhead_t(client.get(f"/sets/{row['id']}", params={"at": 200}).text)
        assert hi == _BASE_S, hi

        returns[0] = _BASE_S + _OFFSET_S
        moved = _playhead_t(
            client.get(f"/sets/{row['id']}", params={"at": 200}).text)
        assert moved == _BASE_S + _OFFSET_S, moved
        assert moved - hi == _OFFSET_S


def test_t1_timeline_lanes_place_item_relative_points_on_set_axis():
    """t on the lane is set-relative. A point at item-local 1s on the
    second item of a 2s fade sits at 9, not 1."""
    items = [_block(1, _PLAY, "fade", 2.0), _block(2, _PLAY)]
    curves = {2: {"gain_db": [(1.0, -6.0), (4.0, 0.0)]}}
    ranges = {"gain_db": (-60.0, 24.0), "pan": (-1.0, 1.0)}
    lanes = mixer.timeline_lanes(items, 18.0, curves, ranges=ranges)
    names = [ln["name"] for ln in lanes]
    assert "gain_db" in names, lanes
    gain = next(ln for ln in lanes if ln["name"] == "gain_db")
    assert [p["t"] for p in gain["points"]] == [9.0, 12.0], gain
    assert [p["value"] for p in gain["points"]] == [-6.0, 0.0]
    assert gain["points"][0]["item_id"] == 2
    assert gain["points"][0]["pct"] == 100.0 * 9.0 / 18.0


def test_t1_timeline_page_lane_points_track_stored_curve():
    """A stored curve is HTML. Moving the row moves data-t. Presence of
    .tl-lanes alone would pass if we never drew a point."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T1-Lane Song")
        client.post("/sets/new", data={"name": "T1-Lane Set", "mode": "audio"})
        row = db.one("SELECT * FROM sets WHERE name='T1-Lane Set'")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})
        item = db.one("SELECT * FROM set_items WHERE set_id=?", row["id"])

        empty = client.get(f"/sets/{row['id']}").text
        assert 'class="tl-lanes"' in empty, "normal audience must show lanes"
        assert 'data-lane="gain_db"' in empty
        assert not _attr_floats(empty, "tl-lane-pt")

        automation.save(item["id"], "gain_db", [(1.0, -12.0), (5.0, 0.0)])
        before = client.get(f"/sets/{row['id']}").text
        ts = _attr_floats(before, "tl-lane-pt")
        vs = _attr_floats(before, "tl-lane-pt", "data-value")
        assert ts == [1.0, 5.0], ts
        assert vs == [-12.0, 0.0], vs

        automation.save(item["id"], "gain_db", [(3.0, -12.0), (5.0, 0.0)])
        after = _attr_floats(client.get(f"/sets/{row['id']}").text, "tl-lane-pt")
        assert after == [3.0, 5.0], after
        assert after[0] - ts[0] == 2.0


def test_t1_timeline_easy_omits_lanes():
    """Easy is an affordance set. A CSS hide that still emits .tl-lanes
    would fail T1-18's 'easy is not a stylesheet' pairing."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T1-Easy Lane Song")
        client.post("/sets/new", data={"name": "T1-Easy Lane Set", "mode": "audio"})
        row = db.one("SELECT * FROM sets WHERE name='T1-Easy Lane Set'")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})
        item = db.one("SELECT * FROM set_items WHERE set_id=?", row["id"])
        automation.save(item["id"], "gain_db", [(1.0, -6.0)])
        client.post(f"/sets/{row['id']}", data={
            "name": "T1-Easy Lane Set", "mode": "audio", "mode_audience": "easy"})
        html = client.get(f"/sets/{row['id']}").text
        assert 'class="tl-lanes"' not in html
        assert 'class="tl-lane-pt"' not in html
        assert automation.read(item["id"], "gain_db"), (
            "omitting lanes must not delete the stored curve")
