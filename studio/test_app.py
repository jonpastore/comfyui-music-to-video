"""Tests for app.py, the web layer only. pipeline/grok/lyrics/mixer are
owned by other modules and stubbed here via sys.modules so the app is
testable in isolation (no real ComfyUI/whisper/xAI/ffmpeg required, except
ffmpeg to synthesize a tiny real mp3 fixture).
"""
import asyncio, json, os, subprocess, sys, tempfile, threading, time

import pytest

# pipeline/grok/lyrics/mixer are stubbed once for the whole session in
# conftest.py (which pytest always imports before this file) -- see its
# docstring for why that has to be the one place it happens.
from conftest import grok_calls  # noqa: F401  (read by test_guardrail_sent_to_grok_contains_pinned)

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
        song = _upload_song(client, "Test Song", album="A", genre="Rock")
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
        assert client.post("/songs/999999/tiers", data={"tier": "pg13"}).status_code == 404
        assert client.post("/songs/999999/tiers/pg13/remove").status_code == 404
        assert client.post("/songs/999999/delete", data={"confirm": "DELETE"}).status_code == 404


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


def test_job_stream_route_is_async():
    # Regression for the anyio-threadpool-exhaustion finding: a sync `def`
    # here gets driven through iterate_in_threadpool, and every open SSE
    # viewer parks a worker thread in time.sleep for the life of the stream --
    # 41 concurrent viewers wedged every other route in the app and it did not
    # recover after the clients disconnected. Must stay async.
    assert asyncio.iscoroutinefunction(appmod.job_stream), \
        "job_stream must be async def or SSE viewers exhaust the threadpool"


def test_render_set_uses_video_key():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Set Song")
        sid = song["id"]
        db.run("INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
               sid, "pg13", song["mp3_path"], time.time())

        client.post("/playlists", data={"name": "Set A", "kind": "playlist"})
        pl = db.one("SELECT * FROM playlists WHERE name='Set A'")
        client.post(f"/playlists/{pl['id']}/items",
                    data={"song_id": sid, "tier": "pg13", "transition": "fade", "secs": "1.0"})

        r = client.post(f"/playlists/{pl['id']}/render")
        assert r.status_code in (200, 303), r.text
        job = db.one("SELECT * FROM jobs WHERE kind='render_set' ORDER BY id DESC")
        row = wait_job(job["id"])
        # the render_set stub asserts on the real "video" key itself; a status
        # of "done" (not "failed") proves the route sent the right shape
        assert row["status"] == "done", row


def test_reroll_clamps_range_and_caps_count():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Reroll Song")
        sid = song["id"]
        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13"})
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", sid)
        wait_job(job["id"])  # scene_count == 2, from the storyboard stub

        # negative / out-of-range indices are dropped, valid ones kept
        r = client.post(f"/songs/{sid}/reroll", data={"tier": "pg13", "clip_idx": ["-5", "0", "999"]})
        assert r.status_code in (200, 303), r.text
        job2 = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='reroll' ORDER BY id DESC", sid)
        assert json.loads(job2["args_json"])["clip_indices"] == [0]

        # nothing valid -> 400, no job enqueued
        before = len(jobs.recent(1000))
        r2 = client.post(f"/songs/{sid}/reroll", data={"tier": "pg13", "clip_idx": ["-1", "999"]})
        assert r2.status_code == 400, r2.text
        assert len(jobs.recent(1000)) == before

        # a big storyboard + a big request -> capped, not fanned out unbounded
        db.run("UPDATE storyboards SET scene_count=? WHERE song_id=? AND tier='pg13'", 1000, sid)
        r3 = client.post(f"/songs/{sid}/reroll",
                          data={"tier": "pg13", "clip_idx": [str(i) for i in range(100)]})
        assert r3.status_code == 400, r3.text


def test_scene_seconds_clamped():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Scene Seconds Song")
        sid = song["id"]

        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13", "scene_seconds": "0.0001"})
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", sid)
        assert json.loads(job["args_json"])["scene_seconds"] == 1.0  # floor

        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13", "scene_seconds": "500"})
        job2 = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", sid)
        assert json.loads(job2["args_json"])["scene_seconds"] == 60.0  # ceiling

        r3 = client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13", "scene_seconds": "nan"})
        assert r3.status_code in (400, 422), r3.text  # rejected, not a 500 / not silently billed


def test_audio_edit_valid_creates_asset_and_keeps_original():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Edit Song")
        sid = song["id"]
        original_path = song["mp3_path"]

        before = len(jobs.recent(1000))
        r = client.post(f"/songs/{sid}/audio",
                         data={"trim_start": "0.5", "trim_end": "2.5", "gain_db": "-3",
                               "fade_in": "0.2", "fade_out": "0.2"})
        assert r.status_code in (200, 303), r.text
        assert len(jobs.recent(1000)) == before + 1

        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='edit_audio' ORDER BY id DESC", sid)
        row = wait_job(job["id"])
        assert row["status"] == "done", row

        asset = db.one("SELECT * FROM assets WHERE song_id=? AND kind='audio_edit'", sid)
        assert asset is not None
        meta = json.loads(asset["meta_json"])
        assert meta["gain_db"] == -3.0

        # the original upload must still exist untouched -- edit_audio always
        # writes to a fresh path, never overwrites mp3_path in place
        assert os.path.isfile(original_path)
        song2 = db.one("SELECT * FROM songs WHERE id=?", sid)
        assert song2["mp3_path"] == original_path  # not swapped until "use" is called


@pytest.mark.parametrize("bad_fields", [
    {"trim_start": "nan"},
    {"trim_start": "inf"},
    {"trim_start": "-1"},
    {"trim_end": "0.1", "trim_start": "5"},   # trim_end <= trim_start
    {"trim_end": "5", "trim_start": "5"},     # trim_end == trim_start
    {"gain_db": "9999"},
    {"gain_db": "-9999"},
    {"fade_in": "-0.5"},
    {"fade_out": "-0.5"},
])
def test_audio_edit_rejects_hostile_params(bad_fields):
    with TestClient(appmod.app) as client:
        song = _upload_song(client, f"Hostile {bad_fields}")
        sid = song["id"]
        before = len(jobs.recent(1000))
        r = client.post(f"/songs/{sid}/audio", data=bad_fields)
        assert r.status_code == 400, r.text
        assert len(jobs.recent(1000)) == before, "a job was enqueued despite an invalid param"
        assert db.one("SELECT id FROM assets WHERE song_id=? AND kind='audio_edit'", sid) is None


def test_audio_edit_use_and_revert():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Use Revert Song")
        sid = song["id"]
        original_path = song["mp3_path"]

        r = client.post(f"/songs/{sid}/audio", data={"trim_start": "0", "gain_db": "2"})
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='edit_audio' ORDER BY id DESC", sid)
        wait_job(job["id"])
        asset = db.one("SELECT * FROM assets WHERE song_id=? AND kind='audio_edit'", sid)

        r2 = client.post(f"/songs/{sid}/audio/{asset['id']}/use")
        assert r2.status_code in (200, 303), r2.text
        song2 = db.one("SELECT * FROM songs WHERE id=?", sid)
        assert song2["mp3_path"] == asset["path"]

        r3 = client.post(f"/songs/{sid}/audio/revert")
        assert r3.status_code in (200, 303), r3.text
        song3 = db.one("SELECT * FROM songs WHERE id=?", sid)
        assert song3["mp3_path"] == original_path


def test_audio_edit_unknown_song_404():
    with TestClient(appmod.app) as client:
        assert client.post("/songs/999999/audio", data={"gain_db": "1"}).status_code == 404
        assert client.post("/songs/999999/audio/1/use").status_code == 404
        assert client.post("/songs/999999/audio/revert").status_code == 404


def test_refs_limit_clamped():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Limit Song")
        sid = song["id"]
        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13"})
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", sid)
        wait_job(job["id"])
        db.run("UPDATE songs SET anchor_path=? WHERE id=?", "anchor.png", sid)

        r = client.post(f"/songs/{sid}/refs", data={"tier": "pg13", "limit": "-100"})
        assert r.status_code in (200, 303), r.text
        job2 = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='refs' ORDER BY id DESC", sid)
        # -100 clamped to 0, and 0 is falsy -> stored as None (unlimited), never negative
        assert json.loads(job2["args_json"])["limit"] is None


def test_song_tier_ratings_add_remove_noop_and_independent_of_storyboards():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Rating Song")
        sid = song["id"]

        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13"})
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", sid)
        wait_job(job["id"])
        assert db.one("SELECT id FROM storyboards WHERE song_id=? AND tier='pg13'", sid)

        r1 = client.post(f"/songs/{sid}/tiers", data={"tier": "pg13"})
        assert r1.status_code in (200, 303), r1.text
        r2 = client.post(f"/songs/{sid}/tiers", data={"tier": "pg13"})  # duplicate add is a no-op
        assert r2.status_code in (200, 303), r2.text
        rows = db.q("SELECT * FROM song_tiers WHERE song_id=?", sid)
        assert len(rows) == 1, rows

        r3 = client.post(f"/songs/{sid}/tiers/pg13/remove")
        assert r3.status_code in (200, 303), r3.text
        assert db.one("SELECT tier FROM song_tiers WHERE song_id=? AND tier='pg13'", sid) is None
        # removing the rating must not cascade into the storyboard generated for that tier
        assert db.one("SELECT id FROM storyboards WHERE song_id=? AND tier='pg13'", sid) is not None


def test_song_tier_unknown_tier_400():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Bad Tier Song")
        r = client.post(f"/songs/{song['id']}/tiers", data={"tier": "not-a-tier"})
        assert r.status_code == 400, r.text


def test_delete_song_requires_confirm():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "No Confirm Song")
        sid = song["id"]
        r = client.post(f"/songs/{sid}/delete")
        assert r.status_code == 400, r.text
        assert db.one("SELECT id FROM songs WHERE id=?", sid) is not None


def test_delete_song_removes_row_and_files():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Delete Me Song")
        sid = song["id"]
        mp3_path = song["mp3_path"]
        assert os.path.isfile(mp3_path)
        # let the auto-enqueued transcribe job finish, or the delete's
        # own no-active-job guard (correctly) refuses it
        wait_job(db.one("SELECT id FROM jobs WHERE song_id=? AND kind='transcribe'", sid)["id"])

        # a storyboard with real files under db.DATA, so the delete has more
        # than the mp3 to clean up
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        json_path = os.path.join(outdir, "sb.json")
        md_path = os.path.join(outdir, "sb.md")
        open(json_path, "w").close()
        open(md_path, "w").close()
        db.run("""INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created)
                  VALUES (?,?,?,?,?,?)""", sid, "pg13", json_path, md_path, 2, time.time())

        r = client.post(f"/songs/{sid}/delete", data={"confirm": "DELETE"})
        assert r.status_code in (200, 303), r.text
        assert db.one("SELECT id FROM songs WHERE id=?", sid) is None
        assert db.one("SELECT id FROM storyboards WHERE song_id=?", sid) is None
        assert not os.path.isfile(mp3_path)
        assert not os.path.isfile(json_path)
        assert not os.path.isfile(md_path)


def test_delete_song_refused_while_job_running():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Busy Song")
        sid = song["id"]
        db.run("INSERT INTO jobs (kind, args_json, status, song_id, created) VALUES (?,?, 'running', ?, ?)",
               "storyboard", "{}", sid, time.time())
        r = client.post(f"/songs/{sid}/delete", data={"confirm": "DELETE"})
        assert r.status_code == 409, r.text
        assert db.one("SELECT id FROM songs WHERE id=?", sid) is not None


def test_delete_song_never_removes_files_outside_data_root():
    with TestClient(appmod.app) as client:
        fd, outside_path = tempfile.mkstemp(prefix="studio_outside_", suffix=".mp3")
        os.close(fd)
        with open(outside_path, "wb") as f:
            f.write(b"not real audio")
        sid = db.upsert_song("outside-song", title="Outside Song", mp3_path=outside_path)

        r = client.post(f"/songs/{sid}/delete", data={"confirm": "DELETE"})
        assert r.status_code in (200, 303), r.text
        assert db.one("SELECT id FROM songs WHERE id=?", sid) is None
        assert os.path.isfile(outside_path), "delete followed a path outside db.DATA"
        os.remove(outside_path)


def test_create_genre_playlist_rejected():
    with TestClient(appmod.app) as client:
        r = client.post("/playlists", data={"name": "Some Genre", "kind": "genre"})
        assert r.status_code == 400, r.text
        assert db.one("SELECT id FROM playlists WHERE name=? AND kind='genre'", "Some Genre") is None


def test_genre_subgenre_validation():
    with TestClient(appmod.app) as client:
        r = client.post("/songs", data={"title": "Genre Song", "genre": "Rock", "subgenre": "Hard Rock"},
                         files={"mp3": ("g.mp3", _mp3_bytes(), "audio/mpeg")})
        assert r.status_code in (200, 303), r.text
        song = db.one("SELECT * FROM songs WHERE title=?", "Genre Song")
        assert song["genre"] == "Rock" and song["subgenre"] == "Hard Rock"

        # subgenre that belongs to a different genre
        r2 = client.post("/songs", data={"title": "Bad Genre Song", "genre": "Rock", "subgenre": "Trap"},
                          files={"mp3": ("b.mp3", _mp3_bytes(), "audio/mpeg")})
        assert r2.status_code == 400, r2.text
        assert db.one("SELECT id FROM songs WHERE title=?", "Bad Genre Song") is None

        # unknown genre outright
        r3 = client.post("/songs", data={"title": "Unknown Genre Song", "genre": "NotAGenre"},
                          files={"mp3": ("u.mp3", _mp3_bytes(), "audio/mpeg")})
        assert r3.status_code == 400, r3.text
        assert db.one("SELECT id FROM songs WHERE title=?", "Unknown Genre Song") is None


# A handler that blocks until released, used to hold the single worker thread
# so a second enqueued job reliably stays 'queued' long enough to cancel it --
# with the instant stub handlers, a lone job finishes before a test could ever
# observe it queued.
_release_blocker = threading.Event()
_blocker_started = threading.Event()


@jobs.handler("test_blocker")
def _test_blocker(args, progress):
    _blocker_started.set()
    _release_blocker.wait(10)
    return {}


def test_cancel_queued_job_returns_303_and_cancelled():
    with TestClient(appmod.app) as client:
        _release_blocker.clear()
        _blocker_started.clear()
        holder_jid = jobs.enqueue("test_blocker", {})
        assert _blocker_started.wait(5), "blocker job never started"
        victim_jid = jobs.enqueue("test_blocker", {})  # sits queued behind the holder
        assert jobs.get(victim_jid)["status"] == "queued"

        r = client.post(f"/jobs/{victim_jid}/cancel")
        assert r.status_code in (200, 303), r.text
        assert jobs.get(victim_jid)["status"] == "cancelled"

        _release_blocker.set()
        wait_job(holder_jid)


def test_cancel_unknown_job_400():
    with TestClient(appmod.app) as client:
        r = client.post("/jobs/999999/cancel")
        assert r.status_code == 400, r.text


def test_cancel_already_finished_job_400():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Cancel Finished Song")
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='transcribe'", song["id"])
        wait_job(job["id"])
        r = client.post(f"/jobs/{job['id']}/cancel")
        assert r.status_code == 400, r.text


def test_jobs_page_renders_all_statuses_and_uses_describe():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Jobs Page Song")
        sid = song["id"]
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='transcribe'", sid)
        wait_job(job["id"])  # -> done, and its describe() line names this song

        for kind, status in (("storyboard", "failed"), ("refs", "cancelled"),
                              ("clips", "cancelling"), ("render_song", "queued")):
            db.run("INSERT INTO jobs (kind, args_json, song_id, status, created) VALUES (?,?,?,?,?)",
                   kind, "{}", sid, status, time.time())

        r = client.get("/jobs")
        assert r.status_code == 200, r.text
        assert "cancelling" in r.text
        assert "Jobs Page Song" in r.text  # from jobs.describe(), not just the raw kind


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
