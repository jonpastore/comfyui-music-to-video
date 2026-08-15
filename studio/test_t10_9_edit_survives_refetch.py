"""T10-9: edited lyrics survive a re-fetch; explicit re-transcribe replaces.

docs/TRD-10 T10-9. Human correction of a Whisper draft must not be discarded
by a later re-fetch. The one-sided trap is a check that stays green when
re-fetch is impossible. Paired positive: an explicit re-transcribe does
replace the edit, and says it will.
"""
import json
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import lyrics
from test_app import _upload_song, wait_job


EDITED = "[Section 1]\nhuman correction that must survive\n"


def _song_with_transcript(client, title):
    song = _upload_song(client, title)
    jid = db.one(
        "SELECT id FROM jobs WHERE song_id=? AND kind='transcribe'",
        song["id"])["id"]
    row = wait_job(jid)
    assert row["status"] == "done", row
    song = db.one("SELECT * FROM songs WHERE id=?", song["id"])
    assert "hi" in (song["lyrics"] or ""), song["lyrics"]
    return song


def test_t10_9_edit_survives_a_refetch():
    """Saving lyrics then re-fetching must leave the human text in place.

    Re-fetch is a real second transcribe job without force — not a no-op
    path. If re-fetch were impossible this half would stay green forever.
    """
    with TestClient(appmod.app) as client:
        song = _song_with_transcript(client, f"t10-9-keep-{time.time_ns()}")
        r = client.post(
            f"/songs/{song['id']}/lyrics",
            data={"lyrics_text": EDITED})
        assert r.status_code in (200, 303), r.text
        stored = db.one(
            "SELECT lyrics, lyrics_edited, lyrics_source FROM songs WHERE id=?",
            song["id"])
        assert stored["lyrics"] == EDITED, stored["lyrics"]
        assert int(stored["lyrics_edited"] or 0) == 1
        assert stored["lyrics_source"] == "supplied", stored

        assert lyrics.may_replace_lyrics(dict(stored), force=False) is False
        result = appmod.h_transcribe({"song_id": song["id"]}, lambda _m: None)
        after = db.one(
            "SELECT lyrics, lyrics_edited FROM songs WHERE id=?",
            song["id"])
        assert after["lyrics"] == EDITED, (
            f"re-fetch discarded the edit: {after['lyrics']!r}")
        assert int(after["lyrics_edited"] or 0) == 1
        assert result.get("kept_edit") is True, result


def test_t10_9_explicit_retranscribe_replaces_and_says_so():
    """force=True re-transcribe overwrites the edit. The surface says so."""
    with TestClient(appmod.app) as client:
        song = _song_with_transcript(client, f"t10-9-force-{time.time_ns()}")
        r = client.post(
            f"/songs/{song['id']}/lyrics",
            data={"lyrics_text": EDITED})
        assert r.status_code in (200, 303), r.text
        assert db.one("SELECT lyrics FROM songs WHERE id=?",
                      song["id"])["lyrics"] == EDITED

        page = client.get(f"/songs/{song['id']}")
        assert page.status_code == 200, page.text
        body = page.text.lower()
        assert "re-transcribe" in body or "retranscribe" in body, page.text
        assert "replace" in body, (
            "explicit re-transcribe must say it will replace edits")

        r2 = client.post(f"/songs/{song['id']}/retranscribe")
        assert r2.status_code in (200, 303), r2.text
        job = db.one(
            "SELECT * FROM jobs WHERE song_id=? AND kind='transcribe' "
            "ORDER BY id DESC", song["id"])
        assert job is not None
        args = json.loads(job["args_json"] or "{}")
        assert args.get("force") is True, args
        row = wait_job(job["id"])
        assert row["status"] == "done", row

        after = db.one(
            "SELECT lyrics, lyrics_edited, lyrics_source FROM songs WHERE id=?",
            song["id"])
        assert after["lyrics"] != EDITED, after["lyrics"]
        assert "hi" in (after["lyrics"] or ""), after["lyrics"]
        assert int(after["lyrics_edited"] or 0) == 0
        assert after["lyrics_source"] == "transcription", after

        edited_row = {"lyrics_edited": 1, "lyrics": EDITED}
        assert lyrics.may_replace_lyrics(edited_row, force=True) is True
        assert lyrics.REPLACE_WARNING and "replace" in lyrics.REPLACE_WARNING.lower()
