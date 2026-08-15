"""T8-5: audio generate bounds accept just-under and name the bound on refuse.

docs/TRD-8 §3 / §8. The audio path bounds what it accepts (MAX_TAGS,
MAX_LYRICS, MAX_AUDIO_SECS) and says which bound refused. Refuse-only is
one-sided: it stays green if everything is refused with any label. Positive
half: values just under each constant are accepted (enqueued); just over
are 400 naming that bound.
"""
from fastapi.testclient import TestClient

import app as appmod
import db
from test_app import _upload_song


def test_t8_5_just_under_accepted_just_over_names_bound():
    """Each of the three constants: just under accepted, just over names it."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T8-5 Bounds Song", album="T8-5 Album")
        sid = song["id"]
        mid = {
            "tags": "dark synthwave, 120 bpm",
            "lyrics": "a short lyric line",
            "seconds": "12",
            "n": "1",
        }

        # --- positive half: just under (at the inclusive ceiling) is accepted ---
        for field, value, why in (
            ("tags", "t" * appmod.MAX_TAGS, "tags at MAX_TAGS"),
            ("lyrics", "l" * appmod.MAX_LYRICS, "lyrics at MAX_LYRICS"),
            ("seconds", f"{appmod.MAX_AUDIO_SECS:g}", "seconds at MAX_AUDIO_SECS"),
        ):
            before = db.one(
                "SELECT COUNT(*) c FROM jobs WHERE song_id=? AND kind='audio'", sid)["c"]
            r = client.post(f"/songs/{sid}/audio/generate", data={**mid, field: value})
            assert r.status_code in (200, 303), (
                f"{why} was refused: {r.status_code} {r.text[:300]}")
            after = db.one(
                "SELECT COUNT(*) c FROM jobs WHERE song_id=? AND kind='audio'", sid)["c"]
            assert after == before + 1, f"{why} never enqueued an audio job"

        # --- refuse half: just over is 400 and the body names that bound ---
        for field, value, token, bound, why in (
            ("tags", "t" * (appmod.MAX_TAGS + 1), "tags", appmod.MAX_TAGS,
             "tags over MAX_TAGS"),
            ("lyrics", "l" * (appmod.MAX_LYRICS + 1), "lyrics", appmod.MAX_LYRICS,
             "lyrics over MAX_LYRICS"),
            ("seconds", f"{appmod.MAX_AUDIO_SECS + 1:g}", "seconds",
             appmod.MAX_AUDIO_SECS, "seconds over MAX_AUDIO_SECS"),
        ):
            before = db.one(
                "SELECT COUNT(*) c FROM jobs WHERE song_id=? AND kind='audio'", sid)["c"]
            r = client.post(f"/songs/{sid}/audio/generate", data={**mid, field: value})
            assert r.status_code == 400, f"{why} was accepted: {r.text[:300]}"
            body = r.text.lower()
            assert token in body, f"{why} response did not name {token!r}: {r.text[:300]}"
            assert f"{bound:g}" in body or str(int(bound)) in body, (
                f"{why} response did not name bound {bound}: {r.text[:300]}")
            after = db.one(
                "SELECT COUNT(*) c FROM jobs WHERE song_id=? AND kind='audio'", sid)["c"]
            assert after == before, f"{why} still enqueued an audio job"
