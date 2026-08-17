"""Song page actions answer JSON when asked, and still 303 a plain form post.

The page must not full-submit to wait on Grok. Same routes as the HTML
forms; Accept: application/json is the fetch path (wants_json).
"""
import os

import httpx
from fastapi.testclient import TestClient

import app as appmod
import db
import jobs
from conftest import _real_module
from test_app import _upload_song

J = {"Accept": "application/json"}


def test_grok_idle_timeout_is_long_enough_for_reasoning():
    """120s was a false stall on first token. Default is 600 unless pinned."""
    real = _real_module("grok")
    assert real is not None, "grok.py failed to import"
    assert real.STREAM_TIMEOUT >= 600 or "XAI_STREAM_TIMEOUT" in os.environ
    assert "timed out" in real._comms_error(
        "timed out", "grok-test", 12.5, 0, "sk-secret", "Read timed out"
    ).args[0]
    msg = real._comms_error(
        "timed out", "grok-test", 12.5, 0, "sk-secret", "sk-secret leaked"
    ).args[0]
    assert "sk-secret" not in msg


def test_grok_chat_timeout_names_model_elapsed_chars(monkeypatch):
    real = _real_module("grok")
    assert real is not None, "grok.py failed to import"
    monkeypatch.setattr(real, "_api_key", lambda: "sk-secret")

    def boom(*a, **k):
        raise httpx.ReadTimeout("Read timed out")

    monkeypatch.setattr(real.httpx, "stream", boom)
    notes = []
    try:
        real._chat("grok-test", [{"role": "user", "content": "hi"}], notes.append)
    except RuntimeError as e:
        text = str(e)
        assert "timed out" in text
        assert "model=grok-test" in text
        assert "elapsed=" in text
        assert "chars=0" in text
        assert "sk-secret" not in text
    else:
        raise AssertionError("timeout did not raise")
    assert any("POST grok-test" in n for n in notes)


def test_api_song_returns_state():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Async State Song")
        r = client.get(f"/api/songs/{song['id']}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["song"]["id"] == song["id"]
        assert body["song"]["title"] == "Async State Song"
        assert "storyboards" in body and "jobs" in body
        assert "active_job" in body


def test_song_page_storyboard_form_is_dual_path():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Async Storyboard Song")
        sid = song["id"]
        page = client.get(f"/songs/{sid}")
        assert page.status_code == 200, page.text
        assert 'id="song-page"' in page.text
        assert f'action="/songs/{sid}/storyboard"' in page.text

        plain = client.post(
            f"/songs/{sid}/storyboard",
            data={"tier": "r", "direction": "a neon alley after hours"},
            follow_redirects=False)
        assert plain.status_code == 303, plain.text

        js = client.post(
            f"/songs/{sid}/storyboard",
            data={"tier": "xxx", "direction": "a neon alley after hours"},
            headers=J)
        assert js.status_code == 200, js.text
        assert (js.headers.get("content-type") or "").split(";")[0] == "application/json"
        body = js.json()
        assert body["job_id"]
        assert body["kind"] == "storyboard"
        assert body["tier"] == "xxx"
        job = jobs.get(body["job_id"])
        assert job["kind"] == "storyboard"
        assert job["song_id"] == sid


def test_song_page_mutations_answer_json():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Async Mutate Song")
        sid = song["id"]

        exp = client.post(f"/songs/{sid}/explicit", headers=J)
        assert exp.status_code == 200, exp.text
        assert exp.json()["explicit"] in (0, 1)

        lyr = client.post(
            f"/songs/{sid}/lyrics",
            data={"lyrics_text": "[Verse]\nhello"},
            headers=J)
        assert lyr.status_code == 200, lyr.text
        assert lyr.json()["ok"] is True
        assert "[Verse]" in lyr.json()["lyrics"]

        st = client.post(
            f"/songs/{sid}/style-text",
            data={"style_text": "dark synthwave"},
            headers=J)
        assert st.status_code == 200, st.text
        assert st.json()["style_text"] == "dark synthwave"

        db.run("UPDATE songs SET bpm=120, downbeat_offset=0 WHERE id=?", sid)
        off = client.post(
            f"/songs/{sid}/downbeat-offset",
            data={"downbeat_offset": "2"},
            headers=J)
        assert off.status_code == 200, off.text
        assert off.json()["downbeat_offset"] == 2

        an = client.post(f"/songs/{sid}/analyse", headers=J)
        assert an.status_code == 200, an.text
        assert an.json()["kind"] == "analyse"
        assert an.json()["job_id"]

        qc = client.post(f"/songs/{sid}/qc", headers=J)
        assert qc.status_code == 200, qc.text
        assert qc.json()["ok"] is True


def test_song_page_js_intercepts_forms():
    src = open(os.path.join(os.path.dirname(__file__), "static", "app.js")).read()
    assert "function initSongPage(" in src
    assert "initSongPage()" in src
    assert "function watchJob(jobId, targetId, onDone)" in src
