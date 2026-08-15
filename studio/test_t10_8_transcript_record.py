"""T10-8: a transcription records which backend produced it and that it is
a transcription rather than supplied text.

docs/TRD-10 T10-8. The two are not the same evidence — TRD-2 storyboard
generation reads lyrics, and a hallucinated line becomes a scene. The
one-sided failure is a check that stays green when only one lyric source
exists. Positive half: one supplied-text case and one transcription case
are both stored and remain distinguishable.
"""
import types
from contextlib import contextmanager

from fastapi.testclient import TestClient

from conftest import _real_module
import app as appmod
import db
from test_app import _upload_song, wait_job


def _lyrics():
    mod = _real_module("lyrics")
    assert mod is not None, "real lyrics.py failed to load"
    return mod


@contextmanager
def _mock_modules(**mapping):
    """Install fake sys.modules entries; None forces ImportError on that name."""
    import sys
    sentinel = object()
    saved = {name: sys.modules.get(name, sentinel) for name in mapping}
    absent = {k for k, v in mapping.items() if v is None}
    present = {k: v for k, v in mapping.items() if v is not None}

    class _Block:
        def find_spec(self, fullname, path=None, target=None):
            root = fullname.split(".")[0]
            if fullname in absent or root in absent:
                raise ImportError(f"blocked {fullname}")
            return None

    block = _Block()
    sys.meta_path.insert(0, block)
    try:
        for name in absent:
            sys.modules.pop(name, None)
        sys.modules.update(present)
        yield
    finally:
        sys.meta_path.remove(block)
        for name, v in saved.items():
            if v is sentinel:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = v
        lyrics = _lyrics()
        lyrics._device_cache.clear()
        lyrics._model_cache.clear()


def test_t10_8_transcribe_result_records_backend(tmp_path, monkeypatch):
    """transcribe() itself names the backend that produced the text."""
    lyrics = _lyrics()

    class _Seg:
        start, end, text = 0.0, 1.0, "hello"

    class _FakeModel:
        def __init__(self, size, device=None, compute_type=None):
            self.device = device

        def transcribe(self, path, vad_filter=False):
            return iter([_Seg()]), types.SimpleNamespace(language="en")

    fake_fw = types.ModuleType("faster_whisper")
    fake_fw.WhisperModel = _FakeModel
    fake_ct2 = types.SimpleNamespace(get_cuda_device_count=lambda: 0)

    import subprocess
    mp3 = tmp_path / "s.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-t", "1", "-i", "anullsrc",
         "-c:a", "libmp3lame", str(mp3)],
        capture_output=True, check=True)

    with _mock_modules(faster_whisper=fake_fw, ctranslate2=fake_ct2,
                       whisper=None):
        out = lyrics.transcribe(str(mp3))
    assert out.get("backend") == "faster-whisper", out
    assert out["text"] == "hello", out


def test_t10_8_transcription_and_supplied_are_stored_distinguishable(
        patch_stub):
    """One transcription and one supplied write both land and stay distinct.

    Shared entry: h_transcribe (job) and POST /songs/{id}/lyrics. The stored
    rows, not the request bodies, are the record.
    """
    backend = "faster-whisper"

    def _transcribe(mp3, progress=None):
        if progress:
            progress("stub")
        return {
            "text": "hi",
            "segments": [{"start": 0, "end": 1, "text": "hi"}],
            "language": "en",
            "model": "medium",
            "device": "cpu",
            "backend": backend,
        }

    patch_stub("lyrics",
               transcribe=_transcribe,
               to_sections=lambda result, gap=3.0: "[Section 1]\nhi\n",
               available=lambda: (True, f"{backend} ready"))

    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-8 Transcribe Song")
        job = db.one(
            "SELECT id FROM jobs WHERE song_id=? AND kind='transcribe'",
            song["id"])
        assert job is not None
        row = wait_job(job["id"])
        assert row["status"] == "done", row

        transcribed = db.one(
            "SELECT lyrics, lyrics_source, lyrics_backend FROM songs WHERE id=?",
            song["id"])
        assert "hi" in (transcribed["lyrics"] or ""), transcribed
        assert transcribed["lyrics_source"] == "transcription", transcribed
        assert transcribed["lyrics_backend"] == backend, transcribed

        supplied_text = "[Verse]\nhuman typed words\n"
        r = client.post(f"/songs/{song['id']}/lyrics",
                        data={"lyrics_text": supplied_text})
        assert r.status_code in (200, 303), r.text

        supplied = db.one(
            "SELECT lyrics, lyrics_source, lyrics_backend FROM songs WHERE id=?",
            song["id"])
        assert supplied["lyrics"] == supplied_text, supplied
        assert supplied["lyrics_source"] == "supplied", supplied
        assert not supplied["lyrics_backend"], supplied

        assert transcribed["lyrics_source"] != supplied["lyrics_source"]
        assert transcribed["lyrics_backend"] != (supplied["lyrics_backend"] or "")


def test_t10_8_store_refuses_transcription_without_backend():
    """A transcription with no backend is not a record — refuse it."""
    sid = db.upsert_song(f"t10-8-nobackend", title="no backend")
    try:
        db.store_lyrics(sid, "words", source="transcription", backend=None)
    except ValueError as e:
        assert "backend" in str(e).lower(), e
    else:
        raise AssertionError("transcription without backend was stored")
    row = db.one(
        "SELECT lyrics, lyrics_source, lyrics_backend FROM songs WHERE id=?",
        sid)
    assert not row["lyrics_source"], row
