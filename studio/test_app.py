"""Tests for app.py, the web layer only. pipeline/grok/lyrics/mixer are
owned by other modules and stubbed here via sys.modules so the app is
testable in isolation (no real ComfyUI/whisper/xAI/ffmpeg required, except
ffmpeg to synthesize a tiny real mp3 fixture).
"""
import json, os, subprocess, sys, tempfile, time, types

import pytest

# --- point db at a scratch dir BEFORE any project module (which imports db) loads ---
TMP = tempfile.mkdtemp()
os.environ["STUDIO_DATA"] = TMP

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


grok_calls = {}


def _fake_generate_storyboard(lyrics_text, tier, guardrail, style_note, song, model, scene_seconds, progress):
    grok_calls["guardrail"] = guardrail
    grok_calls["args"] = dict(lyrics=lyrics_text, tier=tier, style_note=style_note,
                               song=song, model=model, scene_seconds=scene_seconds)
    return {"scenes": [{"scene_number": 1}, {"scene_number": 2}]}


def _fake_write_storyboard(sb, outdir, slug, tier):
    os.makedirs(outdir, exist_ok=True)
    json_path = os.path.join(outdir, f"{slug}_{tier}.json")
    md_path = os.path.join(outdir, f"{slug}_{tier}.md")
    json.dump(sb, open(json_path, "w"))
    with open(md_path, "w") as f:
        f.write("# storyboard\n")
    return json_path, md_path


_stub("grok",
      list_models=lambda: ["grok-x"],
      generate_storyboard=_fake_generate_storyboard,
      write_storyboard=_fake_write_storyboard)

_stub("lyrics",
      available=lambda: (True, "stub ready"),
      transcribe=lambda mp3, progress=None: {"segments": [{"start": 0, "end": 1, "text": "hi"}]},
      to_sections=lambda result, gap=3.0: "[Section 1]\nhi\n",
      estimate_duration=lambda mp3: 12.3)

_stub("mixer",
      probe=lambda p: {"duration": 12.3},
      assemble_song=lambda clip_paths, mp3, out, progress, fade: open(out, "w").close(),
      edit_audio=lambda *a, **k: None,
      render_set=lambda items, out, progress: open(out, "w").close(),
      set_duration=lambda items: items)

PIPE_DIR = tempfile.mkdtemp()
os.makedirs(os.path.join(PIPE_DIR, "input"), exist_ok=True)
os.makedirs(os.path.join(PIPE_DIR, "output"), exist_ok=True)

_stub("pipeline",
      COMFY_INPUT=os.path.join(PIPE_DIR, "input"),
      COMFY_OUTPUT=os.path.join(PIPE_DIR, "output"),
      install_input=lambda local_path, name=None: (name or os.path.basename(local_path)),
      submit_dir=lambda wf_dir, progress=None: [],
      collect=lambda prefix_dir, pattern="*.png": [],
      gen_anchor=lambda face, outfit, view="front", n=4, progress=None, prefix=None: [],
      gen_refs=lambda slug, tier, sb, anchor, mp3, progress=None: [],
      reroll=lambda slug, tier, sb, anchor, mp3, idxs, progress=None: [],
      stage_refs=lambda slug, tier, ref_paths: [],
      gen_clips=lambda slug, tier, sb, mp3, ref_paths, progress=None: [],
      contact_sheet=lambda src, out, cols=6: out)

import db      # real
import tiers   # real
import jobs    # real
import app as appmod

from fastapi.testclient import TestClient


def _mp3_bytes(seconds=1):
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-t", str(seconds), "-i", "anullsrc",
                     "-c:a", "libmp3lame", path], capture_output=True, check=True)
    data = open(path, "rb").read()
    os.remove(path)
    return data


def wait_job(jid, timeout=10):
    deadline = time.time() + timeout
    row = None
    while time.time() < deadline:
        row = jobs.get(jid)
        if row["status"] in ("done", "failed", "cancelled"):
            return row
        time.sleep(0.05)
    raise TimeoutError(f"job {jid} did not finish: {row}")


def _upload_song(client, title, **extra):
    data = _mp3_bytes()
    fields = {"title": title, "album": extra.get("album", ""), "genre": extra.get("genre", "")}
    client.post("/songs", data=fields, files={"mp3": (f"{title}.mp3", data, "audio/mpeg")})
    return db.one("SELECT * FROM songs WHERE title=?", title)


def test_empty_state_pages_200():
    with TestClient(appmod.app) as client:
        for path in ("/", "/playlists", "/tiers", "/jobs"):
            r = client.get(path)
            assert r.status_code == 200, (path, r.text)


def test_upload_mp3_creates_song_and_enqueues_transcribe():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Test Song", album="A", genre="G")
        assert song is not None
        assert song["mp3_path"] and os.path.isfile(song["mp3_path"])
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='transcribe'", song["id"])
        assert job is not None
        row = wait_job(job["id"])
        assert row["status"] == "done", row
        song = db.one("SELECT * FROM songs WHERE id=?", song["id"])
        assert "hi" in (song["lyrics"] or "")


def test_custom_tier_and_builtin_delete_protection():
    with TestClient(appmod.app) as client:
        r = client.post("/tiers", data={"name": "gritty2", "guardrail": "raw"})
        assert r.status_code in (200, 303)
        names = [t["name"] for t in tiers.all_tiers()]
        assert "gritty2" in names

        r2 = client.post("/tiers/pg13/delete")
        assert r2.status_code == 400
        names2 = [t["name"] for t in tiers.all_tiers()]
        assert "pg13" in names2


def test_guardrail_sent_to_grok_contains_pinned():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Guard Song")
        wait_job(db.one("SELECT id FROM jobs WHERE song_id=? AND kind='transcribe'", song["id"])["id"])

        r = client.post(f"/songs/{song['id']}/storyboard",
                         data={"tier": "pg13", "model": "", "scene_seconds": "4.0"})
        assert r.status_code in (200, 303)
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", song["id"])
        row = wait_job(job["id"])
        assert row["status"] == "done", row

        assert tiers.PINNED in grok_calls["guardrail"]
        assert grok_calls["guardrail"].endswith(tiers.PINNED)
        sb_row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier='pg13'", song["id"])
        assert sb_row and sb_row["scene_count"] == 2


def test_clips_refused_without_approved_refs():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Clip Song")
        r = client.post(f"/songs/{song['id']}/storyboard", data={"tier": "pg13"})
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", song["id"])
        wait_job(job["id"])

        before = len(jobs.recent(1000))
        r = client.post(f"/songs/{song['id']}/clips", data={"tier": "pg13"})
        assert r.status_code == 400, r.text
        after = len(jobs.recent(1000))
        assert after == before, "a job was enqueued despite missing approved refs"


def test_media_traversal_blocked():
    with TestClient(appmod.app) as client:
        r = client.get("/media/../../../../../../etc/passwd")
        assert r.status_code in (403, 404), r.status_code
        assert "root:" not in r.text


def test_oversized_upload_rejected():
    with TestClient(appmod.app) as client:
        big = b"0" * (appmod.MAX_MP3 + 1)
        r = client.post("/songs", data={"title": "Big"}, files={"mp3": ("big.mp3", big, "audio/mpeg")})
        assert r.status_code == 413, r.status_code
        assert db.one("SELECT id FROM songs WHERE title=?", "Big") is None


def test_unknown_id_404_not_500():
    with TestClient(appmod.app) as client:
        for path in ("/songs/999999", "/songs/999999/storyboard/pg13", "/songs/999999/approve/pg13",
                     "/jobs/999999/stream", "/jobs/999999/log"):
            r = client.get(path)
            assert r.status_code == 404, (path, r.status_code)

        assert client.post("/songs/999999/lyrics", data={"lyrics_text": "x"}).status_code == 404
        assert client.post("/songs/999999/clips", data={"tier": "pg13"}).status_code == 404
        assert client.post("/playlists/999999/items",
                            data={"song_id": 1, "tier": "pg13"}).status_code == 404
        assert client.post("/playlists/999999/render").status_code == 404


def test_playlist_crud_smoke():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Playlist Song")
        r = client.post("/playlists", data={"name": "My Set", "kind": "playlist"})
        assert r.status_code in (200, 303)
        pl = db.one("SELECT * FROM playlists WHERE name='My Set'")
        assert pl is not None

        r2 = client.post(f"/playlists/{pl['id']}/items",
                          data={"song_id": song["id"], "tier": "pg13", "transition": "fade", "secs": "2.0"})
        assert r2.status_code in (200, 303)
        item = db.one("SELECT * FROM playlist_items WHERE playlist_id=?", pl["id"])
        assert item is not None and item["song_id"] == song["id"]

        r3 = client.get("/playlists")
        assert r3.status_code == 200
        assert "My Set" in r3.text


if __name__ == "__main__":
    # plain-script fallback if pytest is unavailable
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"{t.__name__} OK")
        except Exception:
            failed += 1
            print(f"{t.__name__} FAILED")
            traceback.print_exc()
    if failed:
        sys.exit(1)
    print("test_app.py OK")
