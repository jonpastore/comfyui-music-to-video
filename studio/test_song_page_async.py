"""Song page actions answer JSON when asked, and still 303 a plain form post.

The page must not full-submit to wait on Grok. Same routes as the HTML
forms; Accept: application/json is the fetch path (wants_json).
"""
import os
import re
import time

import httpx
from fastapi.testclient import TestClient

import app as appmod
import db
import jobs
import models
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


def test_list_models_is_cached_and_not_a_120s_wait(monkeypatch):
    """Song page GET must not block on a 22s xAI /models hop."""
    real = _real_module("grok")
    assert real is not None, "grok.py failed to import"
    assert real.MODELS_TIMEOUT <= 10
    real._models_cache["ids"] = None
    real._models_cache["at"] = 0.0
    hits = {"n": 0}

    class _Resp:
        def raise_for_status(self):
            return None
        def json(self):
            return {"data": [{"id": "grok-4.5"}, {"id": "grok-imagine-1"}]}

    def fake_get(*_a, **_k):
        hits["n"] += 1
        return _Resp()

    monkeypatch.setattr(real, "_api_key", lambda: "sk-test")
    monkeypatch.setattr(real.httpx, "get", fake_get)
    assert real.list_models() == ["grok-4.5"]
    assert real.list_models() == ["grok-4.5"]
    assert hits["n"] == 1
    real._models_cache["ids"] = None


def test_list_models_wait_false_does_not_block(monkeypatch):
    """GET /songs uses wait=False so a cold xAI hop cannot own TTFB."""
    real = _real_module("grok")
    assert real is not None, "grok.py failed to import"
    real._models_cache["ids"] = None
    real._models_cache["at"] = 0.0

    def fake_get(*_a, **_k):
        raise RuntimeError("wait=False must not call /models on the request thread")

    monkeypatch.setattr(real, "_api_key", lambda: "sk-test")
    monkeypatch.setattr(real.httpx, "get", fake_get)
    t0 = time.monotonic()
    assert real.list_models(wait=False) == []
    assert time.monotonic() - t0 < 0.5
    real._models_cache["ids"] = ["grok-4.5"]
    real._models_cache["at"] = 0.0
    assert real.list_models(wait=False) == ["grok-4.5"]
    real._models_cache["ids"] = None


def test_song_page_does_not_probe_the_fleet(monkeypatch):
    """GET /songs/{id} must not wait on Swarm or /object_info.

    Measured 2026-08-19: /songs/32 was 22.28s cold because available_on_fleet
    walked every backend (OBJECT_INFO_TIMEOUT=10 each) plus xAI /models.
    """
    def boom(*_a, **_k):
        raise AssertionError("song GET must not probe the fleet")

    monkeypatch.setattr(appmod.pipeline, "swarm_backends", boom)
    monkeypatch.setattr(models, "_object_info", boom)
    monkeypatch.setattr(models, "_system_stats", boom)
    monkeypatch.setattr(models, "available_on_fleet", boom)
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "No Fleet Probe")
        r = client.get(f"/songs/{song['id']}")
    assert r.status_code == 200, r.text
    block = re.search(r'<select name="video_model">(.*?)</select>', r.text, re.S)
    assert block, "song page has no video_model picker"
    assert "disabled" not in block.group(1)


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


def test_song_page_folds_and_storyboard_are_buttons():
    """Long song page: cards collapse; boards are Edit/Approve buttons."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Fold Song")
        sid = song["id"]
        page = client.get(f"/songs/{sid}").text
        assert 'class="card song-fold"' in page
        assert 'id="fold-storyboard"' in page
        assert 'id="fold-words"' in page
        assert 'id="fold-lyrics"' not in page
        assert 'id="refs"' in page
        # lyrics/style start open when empty; analysis open when not analysed
        assert 'id="fold-analysis"' in page
        # delete/jobs start closed
        assert 'id="fold-delete"' in page
        assert 'open' not in page.split('id="fold-delete"')[1][:40]

        # a board turns the links into verb+object buttons
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        jp = os.path.join(outdir, f"{song['slug']}_xxx.json")
        open(jp, "w").write('{"title":"T","scenes":[{"scene_number":1}]}')
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""",
               sid, "xxx", jp, jp + ".md", 1, 0)
        page = client.get(f"/songs/{sid}").text
        assert f"/songs/{sid}/storyboard/xxx/panel" in page
        assert f"/songs/{sid}/approve/xxx" not in page
        assert "Edit XXX scenes" not in page
        assert "approve grid" not in page.lower()
        assert 'class="tier-board"' in page
        assert "expand or collapse" in page.lower()
        # pose plan for a tier lives inside that tier's expand body
        assert "tier-ref-body" in page
        panel = client.get(f"/songs/{sid}/storyboard/xxx/panel")
        assert panel.status_code == 200, panel.text
        assert "board_json" in panel.text
        assert "Save" in panel.text
        assert "Generate" in panel.text
        assert "Scenes and timing" in panel.text
        assert "asked" in panel.text
        assert "timeline" in panel.text
        assert "song 3:13" not in panel.text or "asked" in panel.text
        assert 'id="ref-preview"' in client.get("/").text


def test_scenes_lists_every_rendered_clip_on_a_split_scene():
    """A long scene is several files. The row must list each, not only the head."""
    import json as _json
    import storyboard_service
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Split Clip Song")
        sid = song["id"]
        db.run("UPDATE songs SET duration=30 WHERE id=?", sid)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        scenes = [{
            "scene_number": 1, "name": "Long", "length_seconds": 30.0,
            "video_model": "ltx25", "image_prompt": "alley",
            "character_reference": "her",
        }]
        jp = os.path.join(outdir, f"{song['slug']}_xxx.json")
        _json.dump({"title": "T", "character_reference": "her", "scenes": scenes},
                   open(jp, "w"))
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""", sid, "xxx", jp, jp + ".md", 1, 0)
        for i in (0, 1):
            path = os.path.join(db.DATA, f"c{i}.mp4")
            open(path, "wb").write(b"x")
            db.run("INSERT INTO clips (song_id,tier,clip_idx,path,status) VALUES (?,?,?,?,?)",
                   sid, "xxx", i, path, "done")
        rows, n = storyboard_service.scenes(
            song, {"scenes": scenes}, "xxx")
        assert n >= 2, n
        assert [v["clip_idx"] for v in rows[0]["videos"]] == [0, 1]
        assert rows[0]["videos"][0]["scene_num"] == 1
        assert "motion" in rows[0]["videos"][0]
        still = os.path.join(db.DATA, "still0.png")
        open(still, "wb").write(b"\x89PNG\r\n\x1a\n")
        db.run("""INSERT INTO refs (song_id,tier,clip_idx,path,seed,approved,created,scene_number)
                  VALUES (?,?,?,?,?,?,?,?)""",
               sid, "xxx", 0, still, 42, 1, 1.0, 1)
        page = client.get(f"/songs/{sid}/storyboard/xxx").text
        strip = page.split('class="media-strip scene-clips"', 1)[-1]
        assert 'class="clip-play"' in strip
        assert 'preload="metadata"' in strip
        assert "video class=\"lazy-src\"" not in strip
        assert "data-src=" not in strip.split("</div>", 1)[0]
        assert 'src="' in strip
        assert "poster=" in strip
        assert 'class="clip-poster"' in strip
        assert "clip-frame clip-tile js-clip-preview" in strip
        assert "js-clip-del" in strip
        gone = client.post(
            f"/songs/{sid}/clips/0/delete",
            json={"tier": "xxx"}, headers=J)
        assert gone.status_code == 200, gone.text
        assert gone.json()["deleted"] == 0
        assert not os.path.isfile(os.path.join(db.DATA, "c0.mp4"))
        assert os.path.isfile(os.path.join(db.DATA, "c1.mp4"))
        rows2, _ = storyboard_service.scenes(
            db.one("SELECT * FROM songs WHERE id=?", sid),
            {"scenes": scenes}, "xxx")
        assert [v["clip_idx"] for v in rows2[0]["videos"]] == [1]


def test_scene_row_reads_clip_jobs_when_chip_is_qc():
    """The chip is the latest job of any kind. A queued QC must not hide a
    failed or in-flight clip render on the scene strip."""
    import json as _json
    import storyboard_service
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Clip Job State Song")
        sid = song["id"]
        db.run("UPDATE songs SET duration=8 WHERE id=?", sid)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        scenes = [{
            "scene_number": 1, "name": "One", "length_seconds": 5.0,
            "video_model": "ltx25", "image_prompt": "alley",
        }]
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        jp = os.path.join(outdir, f"{song['slug']}_xxx.json")
        _json.dump({"title": "T", "character_reference": "her", "scenes": scenes},
                   open(jp, "w"))
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""", sid, "xxx", jp, jp + ".md", 1, 0)
        db.run("""INSERT INTO jobs (kind, args_json, song_id, status, error, created)
                  VALUES (?,?,?,?,?,?)""",
               "clips",
               _json.dumps({"tier": "xxx", "scene_number": 1, "clip_idx": 0, "n": 1}),
               sid, "failed",
               "ValueError: clip plan 77.0000s misses track 237.6720s",
               1.0)
        db.run("""INSERT INTO jobs (kind, args_json, song_id, status, created)
                  VALUES (?,?,?,?,?)""",
               "qc", _json.dumps({"tier": "xxx"}), sid, "queued", 2.0)
        rows, _ = storyboard_service.scenes(song, {"scenes": scenes}, "xxx")
        assert rows[0]["videos"] == []
        assert rows[0]["clip_pending"] == []
        assert len(rows[0]["clip_failed"]) == 1
        assert rows[0]["clip_failed"][0]["status"] == "failed"
        assert "clip plan 77.0000s" in rows[0]["clip_failed"][0]["error"]
        page = client.get(f"/songs/{sid}/storyboard/xxx").text
        assert "clip-failed" in page
        assert "job #" in page
        assert "No clips yet." not in page.split("scene-clips", 1)[-1].split("</div>", 1)[0]
        assert "js-clip-fail-dismiss" in page
        storyboard_service.dismiss_clip_job(sid, "xxx", 1, rows[0]["clip_failed"][0]["id"])
        rows2, _ = storyboard_service.scenes(song, _json.load(open(jp)), "xxx")
        assert rows2[0]["clip_failed"] == []


def test_scene_prompt_placeholder_and_version_and_draft():
    import json as _json
    import storyboard_service
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Prompt Tools Song")
        sid = song["id"]
        scenes = [{
            "scene_number": 1, "name": "One", "story": "she waits",
            "camera": "wide", "motion": "walks", "lighting": "neon",
            "location": "alley", "pose": "standing",
            "image_prompt": "alley still", "video_motion_prompt": "",
            "negative_prompt": "",
        }]
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        jp = os.path.join(outdir, f"{song['slug']}_xxx.json")
        _json.dump({"title": "T", "character_reference": "her", "scenes": scenes},
                   open(jp, "w"))
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""", sid, "xxx", jp, jp + ".md", 1, 0)
        page = client.get(f"/songs/{sid}/storyboard/xxx").text
        assert 'placeholder="What happens in this shot' in page
        assert "Stills and clips share this box" in page
        assert "js-scene-draft" in page
        assert "js-scene-ver" in page
        assert '<span class="hint">Stills and clips' not in page
        saved = client.post(
            f"/songs/{sid}/storyboard/xxx/scene/1/field-version",
            json={"field": "story", "text": "she waits in steam", "label": "steam"},
            headers={"Accept": "application/json"})
        assert saved.status_code == 200, saved.text
        assert saved.json()["n"] == 1
        import vision
        vision.ask_text = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline"))
        drafted = storyboard_service.draft_scene_field(sid, "xxx", 1, "video_motion_prompt")
        assert "walks" in drafted["text"]
        applied = client.post(
            f"/songs/{sid}/storyboard/xxx/scene/1/field-version/apply",
            json={"field": "story", "n": 1},
            headers={"Accept": "application/json"})
        assert applied.status_code == 200, applied.text
        assert applied.json()["text"] == "she waits in steam"
        written = _json.load(open(jp))
        assert written["scenes"][0]["story"] == "she waits in steam"
        assert written["scenes"][0]["field_current"]["story"] == 1
        page2 = client.get(f"/songs/{sid}/storyboard/xxx").text
        assert 'value="1" selected' in page2 or "selected>steam" in page2 or 'selected' in page2
        assert "js-pv-pick" in client.get(f"/songs/{sid}").text
        import prompts
        client.post(f"/songs/{sid}/lyrics",
                    data={"lyrics_text": "first verse"}, headers=J)
        client.post(f"/songs/{sid}/lyrics",
                    data={"lyrics_text": "second verse"}, headers=J)
        vers = prompts.versions(f"song:{sid}", "song_lyrics")
        assert len(vers) == 2
        first = [v for v in vers if v["text"] == "first verse"][0]
        picked = client.post("/prompt-versions/select",
                             json={"id": first["id"]}, headers=J)
        assert picked.status_code == 200, picked.text
        assert prompts.recalled(f"song:{sid}", "song_lyrics")["text"] == "first verse"
        again = client.get(f"/songs/{sid}").text
        assert "first verse" in again


def test_storyboard_save_and_restore_roundtrip():
    """CRUD on the live board: save JSON, snapshot, edit, restore."""
    import json as _json
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Board CRUD Song")
        sid = song["id"]
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        board = {
            "title": "T", "character_reference": "her, adult feline woman",
            "scenes": [{
                "scene_number": 1, "name": "One",
                "image_prompt": "alley", "story": "walk",
            }],
        }
        jp = os.path.join(outdir, f"{song['slug']}_r.json")
        _json.dump(board, open(jp, "w"))
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""",
               sid, "r", jp, jp.replace(".json", ".md"), 1, 0)
        snap = client.post(f"/songs/{sid}/storyboard/r/versions",
                           data={"label": "keep"}, headers=J)
        assert snap.status_code == 200, snap.text
        assert snap.json()["version"]["n"] == 1
        board["scenes"][0]["name"] = "Two"
        saved = client.post(f"/songs/{sid}/storyboard/r/save",
                            data={"board_json": _json.dumps(board)}, headers=J)
        assert saved.status_code == 200, saved.text
        assert _json.load(open(jp))["scenes"][0]["name"] == "Two"
        rest = client.post(f"/songs/{sid}/storyboard/r/versions/restore",
                           data={"n": "1"}, headers=J)
        assert rest.status_code == 200, rest.text
        assert _json.load(open(jp))["scenes"][0]["name"] == "One"
        assert rest.json()["versions"]
        gone = client.post(f"/songs/{sid}/storyboard/r/versions/delete",
                           data={"n": "1"}, headers=J)
        assert gone.status_code == 200, gone.text
        assert gone.json()["deleted"] == 1
        assert gone.json()["versions"] == []
        assert client.post(f"/songs/{sid}/storyboard/r/versions/delete",
                           data={"n": "1"}, headers=J).status_code == 404
        one = client.get(f"/songs/{sid}/storyboard/r/scene/1")
        assert one.status_code == 200, one.text
        assert 'id="scene-1"' in one.text
        assert 'open' in one.text


def test_reroll_stills_show_on_the_scene_row():
    """A finished reroll used to sit in refs while the open scene kept the
    first gen still. The scene fragment must list every candidate."""
    import json as _json
    import time
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Reroll Visible Song")
        sid = song["id"]
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        jp = os.path.join(outdir, f"{song['slug']}_r.json")
        _json.dump({
            "title": "T", "character_reference": "her, adult feline woman",
            "scenes": [{"scene_number": 1, "name": "One",
                        "image_prompt": "alley", "story": "walk",
                        "duration_guidance": "5s"}],
        }, open(jp, "w"))
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""",
               sid, "r", jp, jp.replace(".json", ".md"), 1, 0)
        dest = os.path.join(db.DATA, "refs")
        os.makedirs(dest, exist_ok=True)
        now = time.time()
        for seed, origin in ((17000, "gen"), (8000, "reroll"), (9500, "reroll")):
            path = os.path.join(dest, f"r{seed}.png")
            open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
            db.run("""INSERT INTO refs (song_id,tier,clip_idx,path,seed,approved,
                                        created,origin,scene_number)
                      VALUES (?,?,?,?,?,0,?,?,?)""",
                   sid, "r", 0, path, seed, now, origin, 1)
        html = client.get(f"/songs/{sid}/storyboard/r/scene/1").text
        assert "still · 17000" in html
        assert "still · 8000" in html
        assert "still · 9500" in html
        assert ">reroll<" in html
        assert "js-still-select" in html
        assert "js-stills-delete" in html
        assert "Use this still as the scene reference" in html
        assert "Delete this still" in html
        assert "Fix face, inpaint, or outpaint this still" in html
        assert "btn-sm js-approve" not in html


def test_job_json_reports_reroll_clips():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Job Json Song")
        jid = jobs.enqueue("reroll", {"song_id": song["id"], "tier": "xxx",
                                      "clip_indices": [0], "n": 4},
                           song_id=song["id"])
        r = client.get(f"/jobs/{jid}", headers=J)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == jid
        assert body["kind"] == "reroll"
        assert body["clip_indices"] == [0]
        assert body["n"] == 4
        chip = client.get("/queue?chip=1").text
        assert f'data-job-id="{jid}"' in chip
        assert 'data-kind="reroll"' in chip
        assert 'data-clips="0"' in chip


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
    # Catch-all: #song-page form submit → api() unless hx-* or /jobs/.
    assert 'page.addEventListener("submit"' in src
    assert "e.preventDefault()" in src
    assert "hasAttribute(\"hx-post\")" in src
    assert "new FormData(form)" in src
    assert "api(dest, fd)" in src
    assert 'form.classList.contains("clip-bar")' in src
    assert 'form.classList.contains("reroll-bar")' in src
    assert 'fd.set(name, el.value)' in src
    assert "saving scene" in src


# High-traffic song actions that must not bare-POST a full reload.
_SONG_ASYNC_ACTIONS = (
    "/lyrics",
    "/style-text",
    "/refs",
    "/clips",
    "/render",
    "/qc",
)


def test_song_page_high_traffic_forms_are_song_async():
    """Generate refs / clips / render / lyrics / style / QC stay in-page.

    Each form is marked `.song-async` under `#song-page`. initSongPage
    preventDefaults and posts Accept: application/json. A bare method=post
    without the class (or without the intercept) is the reload bug.
    """
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Song Async Forms")
        sid = song["id"]
        page = client.get(f"/songs/{sid}").text
        assert 'id="song-page"' in page
        for suffix in _SONG_ASYNC_ACTIONS:
            action = f"/songs/{sid}{suffix}"
            assert f'action="{action}"' in page, action
            # The opening form tag for this action carries song-async.
            idx = page.find(f'action="{action}"')
            assert idx > 0, action
            tag_start = page.rfind("<form", 0, idx)
            tag_end = page.find(">", idx)
            assert tag_end > tag_start, action
            tag = page[tag_start:tag_end + 1]
            assert "song-async" in tag, tag
            assert 'method="post"' in tag
            assert "hx-post" not in tag  # fetch path, not htmx fragment swap
    src = open(os.path.join(os.path.dirname(__file__), "static", "app.js")).read()
    assert "function initSongPage(" in src
    assert "new FormData(form)" in src
    assert "api(dest, fd)" in src
    assert 'form.classList.contains("reroll-bar")' in src


def test_scene_reroll_and_approve_are_song_async():
    """Reroll + still approve live on the hx-loaded scene row, still in-page."""
    import json as _json
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Scene Async Forms")
        sid = song["id"]
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        jp = os.path.join(outdir, f"{song['slug']}_r.json")
        _json.dump({
            "title": "T", "character_reference": "her",
            "scenes": [{"scene_number": 1, "name": "One",
                        "image_prompt": "alley", "story": "walk",
                        "duration_guidance": "5s"}],
        }, open(jp, "w"))
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""",
               sid, "r", jp, jp.replace(".json", ".md"), 1, 0)
        dest = os.path.join(db.DATA, "refs")
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, "async_still.png")
        open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        db.run("""INSERT INTO refs (song_id,tier,clip_idx,path,seed,approved,
                                    created,origin,scene_number)
                  VALUES (?,?,?,?,?,0,?,?,?)""",
               sid, "r", 0, path, 42, 1.0, "gen", 1)
        html = client.get(f"/songs/{sid}/storyboard/r/scene/1").text
        assert 'action="/songs/%d/reroll"' % sid in html or f'action="/songs/{sid}/reroll"' in html
        assert "reroll-bar" in html and "song-async" in html
        assert "still-pick" in html and "song-async" in html
        assert f'/songs/{sid}/refs/' in html and "/approve" in html


def test_render_clip_writes_the_onscreen_motion_before_enqueue():
    """Render clip used the last saved JSON, not the motion box."""
    import json as _json
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Flush Motion Song")
        sid = song["id"]
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        jp = os.path.join(outdir, f"{song['slug']}_xxx.json")
        _json.dump({
            "title": "T",
            "character_reference": "black feline woman, yellow slit pupils",
            "scenes": [{"scene_number": 1, "name": "One",
                        "image_prompt": "alley", "story": "stand",
                        "duration_guidance": "5s",
                        "video_motion_prompt": "OLD MOTION she walks off",
                        "negative_prompt": "old neg",
                        "length_seconds": 5.0}],
        }, open(jp, "w"))
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""",
               sid, "xxx", jp, jp.replace(".json", ".md"), 1, 0)
        dest = os.path.join(db.DATA, "refs")
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, "flush_still.png")
        open(path, "wb").write(b"\x89PNG\r\n\x1a\x0a" + b"\x00" * 16)
        db.run("""INSERT INTO refs (song_id,tier,clip_idx,path,seed,approved,
                                    created,origin,scene_number)
                  VALUES (?,?,?,?,?,1,?,?,?)""",
               sid, "xxx", 0, path, 42, 1.0, "gen", 1)
        want = ("She holds still in the wet alley. Camera locked wide-low, "
                "no cut, no walk-off.")
        r = client.post(
            f"/songs/{sid}/clips",
            data={"tier": "xxx", "scene": "1", "head_only": "true",
                  "video_motion_prompt": want, "negative_prompt": "human nose"},
            headers=J, follow_redirects=False)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("kind") == "clips"
        saved = _json.load(open(jp))
        assert saved["scenes"][0]["video_motion_prompt"] == want
        assert saved["scenes"][0]["negative_prompt"] == "human nose"
        assert "OLD MOTION" not in saved["scenes"][0]["video_motion_prompt"]


def test_song_page_qc_findings_are_expandable_chips_not_cards():
    """P0-4: song-page findings are small expandable chips, not finding-row cards."""
    import time
    import qc_service
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Song QC Chips")
        sid = song["id"]
        path = os.path.join(db.DATA, f"chip_{time.time_ns()}.mp4")
        open(path, "wb").write(b"not-a-real-video")
        # Tie the finding path to this song so song_page includes it.
        db.run("""INSERT INTO clips (song_id,tier,clip_idx,path,status)
                  VALUES (?,?,?,?,?)""", sid, "r", 0, path, "done")
        qc_service.record([{
            "path": path, "kind": "clip", "tier": 1, "check": "duration",
            "verdict": "reject", "measured": "4.8", "expected": "30.0",
            "unit": "s", "detail": "duration 4.8 vs 30.0 s",
            "remedy": "re-render clip",
        }])
        page = client.get(f"/songs/{sid}").text
        assert 'id="fold-qc"' in page
        assert "finding-chip" in page
        assert "finding-chips" in page
        assert 'class="finding-row' not in page.split('id="fold-qc"', 1)[-1].split('id="fold-jobs"', 1)[0]
        assert "duration" in page
        assert "Approve repair" in page
        # /qc keeps the full finding-row atom
        qc_page = client.get("/qc").text
        assert "finding-row" in qc_page
        fold = page.split('id="fold-qc"', 1)[-1].split('id="fold-jobs"', 1)[0]
        assert 'action="/qc/findings/' in fold
        assert "song-async" in fold
        assert "finding-chip-summary" in fold


def test_qc_finding_approve_form_answers_json(monkeypatch):
    """Song chips post the HTML approve route with Accept: JSON; no 303."""
    import time
    import qc_service
    # Do not enqueue real repair jobs — actuator suites share the same
    # monkeypatched gen_postproc/fix_ref collectors.
    monkeypatch.setattr(jobs, "enqueue", lambda *a, **k: 0)
    path = os.path.join(db.DATA, f"approve_json_{time.time_ns()}.mp4")
    open(path, "wb").write(b"x")
    qc_service.record([{
        "path": path, "kind": "clip", "tier": 1, "check": "duration",
        "verdict": "reject", "measured": "1.0", "expected": "5.0",
        "unit": "s", "detail": "duration 1.0 vs 5.0 s",
        "remedy": "re-render clip",
    }])
    fid = db.one("SELECT id FROM findings WHERE path=?",
                 jobs.canonical_path(path))["id"]
    with TestClient(appmod.app) as client:
        plain = client.post(
            f"/qc/findings/{fid}/approve",
            data={"text": "re-render clip"},
            follow_redirects=False)
        assert plain.status_code == 303, plain.text
    path2 = os.path.join(db.DATA, f"approve_json2_{time.time_ns()}.mp4")
    open(path2, "wb").write(b"x")
    qc_service.record([{
        "path": path2, "kind": "clip", "tier": 1, "check": "duration",
        "verdict": "reject", "measured": "1.0", "expected": "5.0",
        "unit": "s", "detail": "duration 1.0 vs 5.0 s",
        "remedy": "re-render clip",
    }])
    fid2 = db.one("SELECT id FROM findings WHERE path=?",
                  jobs.canonical_path(path2))["id"]
    with TestClient(appmod.app) as client:
        js = client.post(
            f"/qc/findings/{fid2}/approve",
            data={"text": "re-render clip"},
            headers=J)
        assert js.status_code == 200, js.text
        body = js.json()
        assert body["ok"] is True
        assert body["id"] == fid2
