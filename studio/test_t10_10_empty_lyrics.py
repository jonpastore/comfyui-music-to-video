"""T10-10: empty lyrics vs fetch-failed are two stored states.

docs/TRD-10 T10-10: an empty result is explicit rather than an empty
string. A song with no lyrics and a song whose fetch failed are
different states, and T2-8c's section coverage cannot tell them apart
otherwise.

Positive half (TRD8910 review): one song with genuinely no lyrics and
one failed fetch are stored as two different explicit states.

Mutation: both land as lyrics="" with no status → states collide.
Mutation: only one path writes a status → the other arm stays green.
"""
from fastapi.testclient import TestClient

from conftest import _real_module
import app as appmod
import db
from test_app import _upload_song, wait_job


def _lyrics():
    mod = _real_module("lyrics")
    assert mod is not None, "real lyrics.py failed to load"
    return mod


def test_t10_10_empty_and_fetch_failed_are_distinct_stored_states():
    """Both empty outcomes store, and the stored statuses differ.

    Text may be blank for both — the discriminator is lyrics_status, not
    whether lyrics is the empty string.
    """
    empty_id = db.upsert_song("t10-10-empty", title="no lyrics")
    failed_id = db.upsert_song("t10-10-failed", title="fetch failed")

    db.store_lyrics(empty_id, "", source="transcription",
                    backend="faster-whisper", status="empty")
    db.store_lyrics(failed_id, "", source="transcription",
                    backend="faster-whisper", status="fetch_failed")

    empty = db.one(
        "SELECT lyrics, lyrics_status, lyrics_source FROM songs WHERE id=?",
        empty_id)
    failed = db.one(
        "SELECT lyrics, lyrics_status, lyrics_source FROM songs WHERE id=?",
        failed_id)

    assert (empty["lyrics"] or "") == ""
    assert (failed["lyrics"] or "") == ""
    assert empty["lyrics_status"] == "empty", empty
    assert failed["lyrics_status"] == "fetch_failed", failed
    assert empty["lyrics_status"] != failed["lyrics_status"]


def test_t10_10_section_state_tells_empty_from_fetch_failed():
    """T2-8c's section-coverage entry must see two states, not one blank.

    lyrics.section_state is the shared read: both rows can have blank
    lyrics text and still disagree on status.
    """
    lyrics = _lyrics()
    empty_id = db.upsert_song("t10-10-sec-empty", title="sec empty")
    failed_id = db.upsert_song("t10-10-sec-failed", title="sec failed")

    db.store_lyrics(empty_id, "", source="transcription",
                    backend="faster-whisper", status="empty")
    db.store_lyrics(failed_id, "", source="transcription",
                    backend="faster-whisper", status="fetch_failed")

    empty = db.one("SELECT * FROM songs WHERE id=?", empty_id)
    failed = db.one("SELECT * FROM songs WHERE id=?", failed_id)

    assert lyrics.section_state(empty) == "empty"
    assert lyrics.section_state(failed) == "fetch_failed"
    assert lyrics.section_state(empty) != lyrics.section_state(failed)


def test_t10_10_transcribe_empty_stores_empty_not_bare_string(patch_stub):
    """A successful transcription with no vocal text lands status=empty."""
    def _transcribe(mp3, progress=None):
        if progress:
            progress("stub empty")
        return {
            "text": "",
            "segments": [],
            "language": "en",
            "model": "medium",
            "device": "cpu",
            "backend": "faster-whisper",
        }

    patch_stub("lyrics",
               transcribe=_transcribe,
               to_sections=lambda result, gap=3.0: "",
               available=lambda: (True, "faster-whisper ready"),
               result_status=lambda text, failed=False: (
                   "fetch_failed" if failed
                   else ("empty" if not (text or "").strip() else "ok")),
               section_state=lambda song: song["lyrics_status"],
               may_replace_lyrics=lambda song, force=False: True)

    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-10 Empty Transcribe")
        job = db.one(
            "SELECT id FROM jobs WHERE song_id=? AND kind='transcribe'",
            song["id"])
        assert job is not None
        row = wait_job(job["id"])
        assert row["status"] == "done", row

        stored = db.one(
            "SELECT lyrics, lyrics_status, lyrics_source, lyrics_backend "
            "FROM songs WHERE id=?",
            song["id"])
        assert (stored["lyrics"] or "") == ""
        assert stored["lyrics_status"] == "empty", stored
        assert stored["lyrics_source"] == "transcription", stored
        assert stored["lyrics_backend"] == "faster-whisper", stored


def test_t10_10_transcribe_failure_stores_fetch_failed(patch_stub):
    """A failed fetch/transcription lands status=fetch_failed on the row.

    The job still fails — the point is the song records why lyrics are
    blank, not that the failure is swallowed.
    """
    def _transcribe(mp3, progress=None):
        raise RuntimeError("whisper backend exploded")

    patch_stub("lyrics",
               transcribe=_transcribe,
               to_sections=lambda result, gap=3.0: "",
               available=lambda: (True, "faster-whisper ready"),
               result_status=lambda text, failed=False: (
                   "fetch_failed" if failed
                   else ("empty" if not (text or "").strip() else "ok")),
               section_state=lambda song: song["lyrics_status"],
               may_replace_lyrics=lambda song, force=False: True)

    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-10 Failed Transcribe")
        job = db.one(
            "SELECT id FROM jobs WHERE song_id=? AND kind='transcribe'",
            song["id"])
        assert job is not None
        row = wait_job(job["id"])
        assert row["status"] == "failed", row

        stored = db.one(
            "SELECT lyrics, lyrics_status FROM songs WHERE id=?",
            song["id"])
        assert (stored["lyrics"] or "") == ""
        assert stored["lyrics_status"] == "fetch_failed", stored


def test_t10_10_result_status_classifies_without_storing():
    """result_status is the pure classifier: failed / blank / present."""
    lyrics = _lyrics()
    assert lyrics.result_status("", failed=True) == "fetch_failed"
    assert lyrics.result_status("", failed=False) == "empty"
    assert lyrics.result_status("   ", failed=False) == "empty"
    assert lyrics.result_status("[Verse]\nhi\n", failed=False) == "ok"
    # failed wins over non-empty text — a partial buffer is not a success
    assert lyrics.result_status("leftover", failed=True) == "fetch_failed"
