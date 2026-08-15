"""T8-13: the song editor reads and writes the shared automation model.

docs/TRD-8 §6. Same automation rows, automation.MAX_POINTS, RDP
decimation, linear and hold only. The positive half: an edit written
in the song editor is consumed by automation.item_audio — absent or
read-only editor is not the check.
"""
from fastapi.testclient import TestClient

import app as appmod
import automation
import db


def _song():
    return db.upsert_song("t8-13-editor", title="T8-13 Song Editor", duration=12.3)


def test_t8_13_song_editor_write_is_consumed_by_item_audio():
    """POST the song editor; the stored curve is automation rows and
    item_audio emits it. A missing write path fails this."""
    sid = _song()
    ramp = [(i * 0.01, -12.0 + 12.0 * (i / 300.0)) for i in range(301)]
    with TestClient(appmod.app) as client:
        r = client.post(
            f"/api/songs/{sid}/automation/gain_db",
            json={"points": ramp, "curve": "linear"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        stored = body["points"]
        assert 2 <= len(stored) <= automation.MAX_POINTS, stored
        assert body["curve"] == "linear"
        assert body["lane"] == "gain_db"

        got = client.get(f"/api/songs/{sid}/automation/gain_db")
        assert got.status_code == 200, got.text
        assert got.json()["points"] == stored
        assert got.json()["curve"] == "linear"

        rows = db.q(
            "SELECT t, value, curve FROM automation WHERE set_item_id IN ("
            "  SELECT si.id FROM set_items si JOIN sets s ON s.id = si.set_id"
            "  WHERE s.mode = ? AND si.song_id = ?)"
            " ORDER BY t",
            automation.SONG_EDITOR_MODE, sid)
        assert rows, "song editor write did not land in automation rows"
        assert [(r["t"], r["value"]) for r in rows] == [tuple(p) for p in stored]
        assert {r["curve"] for r in rows} == {"linear"}

        audio = body.get("automation") or got.json().get("automation")
        assert audio, "shared path did not consume the written curve"
        assert audio["frags"], audio
        assert "asendcmd" in audio["frags"][0]
        assert audio["suppress_loudnorm"] is True

        item = db.one(
            "SELECT si.id FROM set_items si JOIN sets s ON s.id = si.set_id"
            " WHERE s.mode = ? AND si.song_id = ?",
            automation.SONG_EDITOR_MODE, sid)
        shared = automation.item_audio(item["id"])
        assert shared["frags"] == audio["frags"]
        assert shared["suppress_loudnorm"] is True


def test_t8_13_song_editor_uses_rdp_cap_and_hold_only():
    """Same limits and modes as the set timeline. A second curve model
    that accepted bezier or kept every mouse point fails this."""
    sid = _song()
    drag = [(i * 0.016, -3.0 + (i % 7) * 0.05) for i in range(300)]
    with TestClient(appmod.app) as client:
        held = client.post(
            f"/api/songs/{sid}/automation/gain_db",
            json={"points": [(0.0, -6.0), (3.0, 0.0)], "curve": "hold"},
        )
        assert held.status_code == 200, held.text
        assert held.json()["curve"] == "hold"
        assert len(held.json()["points"]) == 2

        refuse = client.post(
            f"/api/songs/{sid}/automation/gain_db",
            json={"points": [(0.0, -6.0), (3.0, 0.0)], "curve": "bezier"},
        )
        assert refuse.status_code == 400, refuse.text
        assert "linear" in refuse.text and "hold" in refuse.text
        still = client.get(f"/api/songs/{sid}/automation/gain_db")
        assert still.json()["curve"] == "hold"
        assert still.json()["points"] == held.json()["points"]

        dense = client.post(
            f"/api/songs/{sid}/automation/gain_db",
            json={"points": drag},
        )
        assert dense.status_code == 200, dense.text
        assert len(dense.json()["points"]) <= automation.MAX_POINTS
        direct = automation.decimate(drag, "gain_db")
        assert [tuple(p) for p in dense.json()["points"]] == direct
