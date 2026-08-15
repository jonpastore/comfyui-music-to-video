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
"""
import re

from conftest import _real_module
from fastapi.testclient import TestClient

import app as appmod
import db
from test_app import _upload_song


_BASE_S = 125.0
_OFFSET_S = 17.0

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
