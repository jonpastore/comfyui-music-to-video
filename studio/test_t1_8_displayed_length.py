"""T1-8 displayed set length is mixer.set_duration()'s return value.

docs/TRD-1 T1-8: the number on the set editor is the return value of
mixer.set_duration() and no other arithmetic exists. Verified by an
offset-stub differential, not by grepping for the call: change
set_duration's result by a known offset and the UI number moves by
exactly that offset.
"""
import re

from fastapi.testclient import TestClient

import app as appmod
import db
from test_app import _upload_song


_BASE_S = 125.0
_OFFSET_S = 17.0


def _parse_running_length(html):
    m = re.search(r"running length <strong>([^<]+)</strong>", html)
    assert m, "set editor did not display a running length"
    return m.group(1).strip()


def _hms_to_secs(text):
    parts = [int(p) for p in text.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise AssertionError(f"unparseable hms {text!r}")


def test_t1_8_displayed_length_tracks_set_duration_offset(patch_stub):
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T1-8 Length Song")
        client.post("/sets/new", data={"name": "T1-8 Length Set", "mode": "audio"})
        row = db.one("SELECT * FROM sets WHERE name='T1-8 Length Set'")
        assert row is not None
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})

        returns = [_BASE_S]

        def _stub(items, key="video"):
            assert items, "set_duration called with no items"
            return returns[0]

        patch_stub("mixer", set_duration=_stub)

        before = _parse_running_length(client.get(f"/sets/{row['id']}").text)
        assert before == appmod.hms(_BASE_S), (
            f"displayed {before!r} is not hms({_BASE_S})={appmod.hms(_BASE_S)!r}")

        returns[0] = _BASE_S + _OFFSET_S
        after = _parse_running_length(client.get(f"/sets/{row['id']}").text)
        assert after == appmod.hms(_BASE_S + _OFFSET_S), (
            f"displayed {after!r} is not hms({_BASE_S + _OFFSET_S})="
            f"{appmod.hms(_BASE_S + _OFFSET_S)!r}")

        moved = _hms_to_secs(after) - _hms_to_secs(before)
        assert moved == _OFFSET_S, (
            f"UI moved by {moved}s, not the stub offset {_OFFSET_S}s "
            f"({before} -> {after})")
