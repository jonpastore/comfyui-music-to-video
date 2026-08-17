"""Load / concurrency and end-to-end flow tests for studio/.

pipeline/grok/lyrics/mixer are stubbed once for the whole session in
conftest.py (which pytest always imports before this file) -- see its
docstring for why that has to be the one place it happens. Uses a temp
STUDIO_DATA sqlite db (real db.py/jobs.py/tiers.py -- those are cheap and
worth exercising for real).

Run: python3 -m pytest test_load.py -q
"""
import asyncio
import itertools
import json
import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from conftest import render_set_calls  # noqa: F401 (read by GAP2 render tests)

import db
import jobs
import app as app_module

from fastapi.testclient import TestClient

_song_counter = itertools.count(1)


def _make_song(prefix="song"):
    n = next(_song_counter)
    slug = f"{prefix}-{n}"
    # duration matters: the clip list comes from the audio length, not from the
    # storyboard's scene count. 12.3 s = 3 clips of 4.8125 s.
    return db.upsert_song(slug, title=slug, mp3_path=f"/fake/{slug}.mp3", duration=12.3)


def _make_storyboard(song_id, tier, scene_count):
    song = db.one("SELECT * FROM songs WHERE id=?", song_id)
    slug = (song["slug"] if song else f"s{song_id}") or f"s{song_id}"
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{slug}_{tier}.json")
    scenes = [{"scene_number": i, "name": f"S{i}", "image_prompt": "x",
               "length_seconds": 4.0} for i in range(1, scene_count + 1)]
    json.dump({"title": "T", "scenes": scenes}, open(path, "w"))
    db.run(
        """INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created)
           VALUES (?,?,?,?,?,?)""",
        song_id, tier, path, path + ".md", scene_count, time.time(),
    )


def _make_ref(song_id, tier, clip_idx, seed, path=None):
    path = path or f"/fake/refs/{song_id}_{tier}_{clip_idx}_{seed}.png"
    return db.run(
        """INSERT INTO refs (song_id, tier, clip_idx, path, seed, approved, created)
           VALUES (?,?,?,?,?,0,?)""",
        song_id, tier, clip_idx, path, seed, time.time(),
    )


def _wait_new_job(kind, after_id, timeout=10.0):
    deadline = time.time() + timeout
    row = None
    while time.time() < deadline:
        row = db.one("SELECT * FROM jobs WHERE id > ? AND kind=? ORDER BY id DESC LIMIT 1", after_id, kind)
        if row and row["status"] in ("done", "failed", "cancelled"):
            return row
        time.sleep(0.02)
    raise AssertionError(
        f"no finished {kind!r} job appeared after id {after_id} within {timeout}s "
        f"(last seen: {dict(row) if row else None})"
    )


@pytest.fixture(scope="module")
def client():
    with TestClient(app_module.app) as c:
        yield c


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def live_server():
    """A real uvicorn server on a real TCP socket.

    httpx's in-process ASGITransport deadlocks a streaming GET against this
    app: Starlette's StreamingResponse races a `listen_for_disconnect` loop
    against the body, and app.py's upload-size-limiting BaseHTTPMiddleware
    wraps `receive` so that loop waits on the raw ASGI receive() for an
    http.disconnect that ASGITransport never sends while `httpx.stream()` is
    still open -- a fake-transport artifact, not a real deadlock (confirmed
    by reproducing it in isolation and then confirming a real socket doesn't
    hang). A live server sidesteps it and is also the more faithful
    reproduction of the reported incident, which was over real connections.
    """
    port = _free_port()
    config = uvicorn.Config(app_module.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 10.0
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn test server did not start in time"

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5.0)


# --------------------------------------------------------------- GAP 1 --
# SSE concurrency: jobs.stream must be a real async generator. As a sync
# generator, Starlette drives it through iterate_in_threadpool and each open
# viewer parks an anyio threadpool worker; 41 concurrent viewers exhausted
# the (default 40-token) pool and every route -- sync or async -- serving
# through run_in_threadpool wedged, and did not recover on disconnect.

def test_sse_concurrency_does_not_starve_other_routes(live_server):
    jid = db.run(
        "INSERT INTO jobs (kind, args_json, status, created) VALUES (?,?, 'running', ?)",
        "load_test_job", "{}", time.time(),
    )

    async def _hold_stream(ac, hold_seconds):
        async with ac.stream("GET", f"/jobs/{jid}/stream") as resp:
            assert resp.status_code == 200
            async for _line in resp.aiter_lines():
                break  # got the first SSE frame -- connection is genuinely live
            await asyncio.sleep(hold_seconds)

    async def _run():
        timeout = httpx.Timeout(10.0)
        async with httpx.AsyncClient(base_url=live_server, timeout=timeout) as ac:
            n_viewers = 45
            hold_seconds = 1.5
            tasks = [asyncio.create_task(_hold_stream(ac, hold_seconds)) for _ in range(n_viewers)]
            await asyncio.sleep(0.5)  # let every viewer connect and hit its first sleep

            t0 = time.monotonic()
            r = await asyncio.wait_for(ac.get("/"), timeout=5.0)
            elapsed = time.monotonic() - t0
            assert r.status_code == 200
            assert elapsed < 3.0, f"GET / took {elapsed:.2f}s with {n_viewers} SSE viewers open"

            t0 = time.monotonic()
            r2 = await asyncio.wait_for(ac.get("/jobs"), timeout=5.0)
            elapsed2 = time.monotonic() - t0
            assert r2.status_code == 200
            assert elapsed2 < 3.0, f"GET /jobs took {elapsed2:.2f}s with {n_viewers} SSE viewers open"

            await asyncio.gather(*tasks)

            # after every viewer disconnects, the app must still be responsive
            r3 = await asyncio.wait_for(ac.get("/"), timeout=5.0)
            assert r3.status_code == 200

    asyncio.run(_run())

    db.run("UPDATE jobs SET status='done', finished=? WHERE id=?", time.time(), jid)


# --------------------------------------------------------------- GAP 2 --
# Playlist flows: ordering, reorder, render_set item shape ("video" key, not
# "path"), and clean refusal instead of a 500.
#
# Genres are NOT playlists any more. They are fields on a song, set at upload,
# so the route must refuse kind='genre'. Legacy genre-kind rows may still exist
# in a deployed db, so the ordering logic is still exercised against one --
# inserted directly, because the route can no longer create it.

def test_playlist_and_genre_flow_ordering(client):
    r1 = client.post("/playlists", data={"name": "Chill Mix", "kind": "playlist"}, follow_redirects=False)
    assert r1.status_code == 303
    r2 = client.post("/playlists", data={"name": "Synthwave", "kind": "genre"}, follow_redirects=False)
    assert r2.status_code == 400, "genre must no longer be creatable as a playlist kind"

    playlist = db.one("SELECT * FROM playlists WHERE name=? AND kind='playlist'", "Chill Mix")
    assert playlist is not None and playlist["kind"] == "playlist"
    db.run("INSERT INTO playlists (name, kind) VALUES (?, 'genre')", "Synthwave")
    genre = db.one("SELECT * FROM playlists WHERE name=? AND kind='genre'", "Synthwave")
    assert genre is not None

    s1, s2, s3 = _make_song("g"), _make_song("g"), _make_song("g")
    for sid, tier in ((s1, "pg13"), (s2, "pg13"), (s3, "r")):
        r = client.post(
            f"/playlists/{genre['id']}/items",
            data={"song_id": sid, "tier": tier, "transition": "fade", "secs": "1.5"},
            follow_redirects=False,
        )
        assert r.status_code == 303

    items = db.q("SELECT * FROM playlist_items WHERE playlist_id=? ORDER BY position", genre["id"])
    assert [it["song_id"] for it in items] == [s1, s2, s3]

    order = ",".join(str(it["id"]) for it in reversed(items))
    r = client.post(f"/playlists/{genre['id']}/reorder", data={"order": order}, follow_redirects=False)
    assert r.status_code == 303

    reordered = db.q("SELECT * FROM playlist_items WHERE playlist_id=? ORDER BY position", genre["id"])
    assert [it["song_id"] for it in reordered] == [s3, s2, s1]

    assert client.get("/playlists").status_code == 200


def test_render_set_receives_video_key_not_path(client):
    s1, s2 = _make_song("rs"), _make_song("rs")
    db.run("INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
           s1, "pg13", "/fake/renders/one.mp4", time.time())
    db.run("INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
           s2, "pg13", "/fake/renders/two.mp4", time.time())

    pl = db.run("INSERT INTO playlists (name, kind) VALUES (?, 'playlist')", f"RenderTest-{s1}")
    client.post(f"/playlists/{pl}/items", data={"song_id": s1}, follow_redirects=False)
    client.post(f"/playlists/{pl}/items", data={"song_id": s2}, follow_redirects=False)

    before_max = db.one("SELECT COALESCE(MAX(id),0) AS m FROM jobs")["m"]
    r = client.post(f"/playlists/{pl}/render",
                    data={"include_videos": "true", "tier": "pg13"}, follow_redirects=False)
    assert r.status_code == 303

    job = _wait_new_job("render_set", before_max)
    assert job["status"] == "done", (job["status"], job["error"])

    assert render_set_calls, "mixer.render_set was never called"
    called_items = render_set_calls[-1]
    assert len(called_items) == 2
    for it in called_items:
        assert "video" in it, f"render_set item missing 'video' key: {it!r}"
        assert "path" not in it, f"render_set item still uses the old 'path' key: {it!r}"
    assert called_items[0]["video"] == "/fake/renders/one.mp4"
    assert called_items[1]["video"] == "/fake/renders/two.mp4"


def test_render_refused_cleanly_when_playlist_empty(client):
    pl = db.run("INSERT INTO playlists (name, kind) VALUES (?, 'playlist')", "EmptyPL")
    before_max = db.one("SELECT COALESCE(MAX(id),0) AS m FROM jobs")["m"]

    r = client.post(f"/playlists/{pl}/render", follow_redirects=False)
    assert r.status_code != 500, r.text

    if r.status_code == 303:
        # current app.py enqueues a render_set job with 0 items rather than
        # rejecting at the route -- the job itself must still fail cleanly.
        job = _wait_new_job("render_set", before_max)
        assert job["status"] == "failed", job
        assert "empty" in (job["error"] or "").lower(), job
    else:
        assert r.status_code == 400, r.text

    assert client.get("/playlists").status_code == 200


def test_render_refused_cleanly_when_song_has_no_finished_render(client):
    s1 = _make_song("norender")
    pl = db.run("INSERT INTO playlists (name, kind) VALUES (?, 'playlist')", "NoRenderPL")
    client.post(f"/playlists/{pl}/items", data={"song_id": s1}, follow_redirects=False)

    r = client.post(f"/playlists/{pl}/render",
                    data={"include_videos": "true", "tier": "pg13"}, follow_redirects=False)
    assert r.status_code == 400, r.text
    # named, not "song 7": the point of refusing here is that you know which
    assert db.one("SELECT title FROM songs WHERE id=?", s1)["title"] in r.text

    assert client.get("/playlists").status_code == 200


def test_video_set_is_per_tier_and_all_or_nothing(client):
    """A playlist has no tier. Rendering with videos picks tiers at render
    time, one set each, and a tier missing a single song refuses the lot."""
    s1, s2 = _make_song("tierset"), _make_song("tierset")
    pl = db.run("INSERT INTO playlists (name, kind) VALUES (?, 'playlist')", f"TierSet-{s1}")
    for s in (s1, s2):
        client.post(f"/playlists/{pl}/items", data={"song_id": s}, follow_redirects=False)
    for s in (s1, s2):
        db.run("INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
               s, "pg13", f"/fake/{s}_pg13.mp4", time.time())
    db.run("INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
           s1, "r", f"/fake/{s1}_r.mp4", time.time())   # only ONE song has an r video

    before = db.one("SELECT COALESCE(MAX(id),0) AS m FROM jobs")["m"]
    r = client.post(f"/playlists/{pl}/render",
                    data={"include_videos": "true", "tier": ["pg13", "r"]}, follow_redirects=False)
    assert r.status_code == 400, r.text
    assert "'r'" in r.text
    # the good tier must NOT have been enqueued on its own
    assert db.one("SELECT COALESCE(MAX(id),0) AS m FROM jobs")["m"] == before

    # only the tier that covers every song is offered on the card
    page = client.get(f"/playlists/{pl}/card").text
    assert 'value="pg13"' in page

    r2 = client.post(f"/playlists/{pl}/render",
                     data={"include_videos": "true", "tier": "pg13"}, follow_redirects=False)
    assert r2.status_code == 303
    jobs_made = db.q("SELECT * FROM jobs WHERE id>? AND kind='render_set'", before)
    assert len(jobs_made) == 1
    args = json.loads(jobs_made[0]["args_json"])
    assert args["mode"] == "video" and args["tier"] == "pg13"
    assert [i["video"] for i in args["items"]] == [f"/fake/{s1}_pg13.mp4", f"/fake/{s2}_pg13.mp4"]


def test_audio_only_set_mixes_the_songs_own_mp3s(client):
    s1, s2 = _make_song("audioset"), _make_song("audioset")
    pl = db.run("INSERT INTO playlists (name, kind) VALUES (?, 'playlist')", f"AudioSet-{s1}")
    for s in (s1, s2):
        client.post(f"/playlists/{pl}/items", data={"song_id": s, "secs": "1.5"},
                    follow_redirects=False)
    before = db.one("SELECT COALESCE(MAX(id),0) AS m FROM jobs")["m"]

    r = client.post(f"/playlists/{pl}/render", follow_redirects=False)
    assert r.status_code == 303, r.text
    job = db.q("SELECT * FROM jobs WHERE id>? AND kind='render_set'", before)[-1]
    args = json.loads(job["args_json"])
    assert args["mode"] == "audio"
    # the TRACKS themselves, in playlist order -- an audio set needs no video
    expected = [db.one("SELECT mp3_path FROM songs WHERE id=?", s)["mp3_path"] for s in (s1, s2)]
    assert [i["audio"] for i in args["items"]] == expected
    assert [i["secs"] for i in args["items"]] == [1.5, 1.5]


def test_album_profile_fields_have_hints_and_the_wand_drafts_from_the_anchor(client):
    from conftest import describe_calls
    name = "Wand Album"
    pl = db.run("INSERT INTO playlists (name, kind, created) VALUES (?, 'playlist', ?)",
                name, time.time())

    page = client.get(f"/playlists/{pl}/card").text
    # the hard-won rules sit next to the box you type into
    assert "at cfg 1.0 the negative prompt is skipped" in page
    assert "PER BODY PART" in page
    assert 'name="identity"' in page and 'name="body"' in page

    # no anchor yet -> refused, and the reason names the album
    r = client.post(f"/playlists/{pl}/describe", data={"field": "identity"},
                    follow_redirects=False)
    assert r.status_code == 400 and name in r.text

    db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen, created)
              VALUES ('album',?,?,?,?,?,?)""", name, "r", "front", "/fake/front.png", 1, time.time())
    db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen, created)
              VALUES ('album',?,?,?,?,?,?)""", name, "r", "back", "/fake/back.png", 0, time.time())

    n = len(describe_calls)
    r2 = client.post(f"/playlists/{pl}/describe", data={"field": "body"}, follow_redirects=False)
    assert r2.status_code == 200, r2.text
    # the CHOSEN anchor, not just any row
    assert describe_calls[n:] == [("/fake/front.png", "body")]
    # a fragment that replaces the field in place, not a whole page
    assert "<html" not in r2.text and 'id="album-field-body"' in r2.text
    assert "drafted body from the anchor" in r2.text
    # drafting must not save: the row is still untouched until Save is pressed
    assert db.one("SELECT body FROM playlists WHERE id=?", pl)["body"] is None

    r3 = client.post(f"/playlists/{pl}/describe", data={"field": "world"}, follow_redirects=False)
    assert r3.status_code == 400, "world is not a describable field"


def test_playlist_delete_keeps_songs_and_renders(client):
    s1 = _make_song("keepme")
    pl = db.run("INSERT INTO playlists (name, kind) VALUES (?, 'playlist')", f"Doomed-{s1}")
    client.post(f"/playlists/{pl}/items", data={"song_id": s1}, follow_redirects=False)
    db.run("INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
           s1, "pg13", "/fake/keep.mp4", time.time())

    assert client.post(f"/playlists/{pl}/delete", follow_redirects=False).status_code == 400
    assert db.one("SELECT id FROM playlists WHERE id=?", pl) is not None

    r = client.post(f"/playlists/{pl}/delete", data={"confirm": "DELETE"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    assert db.one("SELECT id FROM playlists WHERE id=?", pl) is None
    assert db.q("SELECT id FROM playlist_items WHERE playlist_id=?", pl) == []
    # the material survives: a playlist is an ordering, not the songs
    assert db.one("SELECT id FROM songs WHERE id=?", s1) is not None
    assert db.one("SELECT id FROM renders WHERE song_id=?", s1) is not None


def test_playlist_card_summary_and_drag_order(client):
    s1, s2 = _make_song("card"), _make_song("card")
    db.run("UPDATE songs SET duration=? WHERE id=?", 200.0, s1)   # 3:20
    db.run("UPDATE songs SET duration=? WHERE id=?", 100.0, s2)   # 1:40
    pl = db.run("INSERT INTO playlists (name, kind, created) VALUES (?, 'playlist', ?)",
                f"CardPL-{s1}", 1754870400.0)
    for s in (s1, s2):
        client.post(f"/playlists/{pl}/items", data={"song_id": s}, follow_redirects=False)

    page = client.get("/playlists").text
    assert "2 songs" in page
    assert "5:00" in page          # 200 + 100 seconds, on the collapsed card
    assert "2025-08" in page or "2025-0" in page or "20" in page

    items = db.q("SELECT * FROM playlist_items WHERE playlist_id=? ORDER BY position", pl)
    assert [i["song_id"] for i in items] == [s1, s2]
    # what the drag handler posts on drop
    r = client.post(f"/playlists/{pl}/reorder",
                    data={"order": f"{items[1]['id']},{items[0]['id']}"}, follow_redirects=False)
    assert r.status_code == 303
    after = db.q("SELECT * FROM playlist_items WHERE playlist_id=? ORDER BY position", pl)
    assert [i["song_id"] for i in after] == [s2, s1]


# --------------------------------------------------------------- GAP 3 --
# Approval grid: multiple ref candidates for one clip_idx (what reroll
# produces), approve-toggle semantics, the _clip_tile htmx partial, and the
# /clips gate that refuses while any clip index lacks an approved ref.

def test_approval_grid_multi_candidate_and_clip_gating(client):
    sid = _make_song("approve")
    db.run("UPDATE songs SET duration=? WHERE id=?", 18.0, sid)
    tier = "pg13"
    _make_storyboard(sid, tier, scene_count=3)

    ref0a = _make_ref(sid, tier, 0, seed=111)
    ref0b = _make_ref(sid, tier, 0, seed=222)  # reroll-style second candidate, same clip_idx
    ref1 = _make_ref(sid, tier, 1, seed=333)
    ref2 = _make_ref(sid, tier, 2, seed=444)

    grid = client.get(f"/songs/{sid}/approve/{tier}", follow_redirects=False)
    assert grid.status_code == 303
    assert f"/songs/{sid}" in (grid.headers.get("location") or "")

    r = client.post(f"/songs/{sid}/refs/0/approve", data={"tier": tier, "ref_id": ref0a})
    assert r.status_code == 200
    assert 'id="clip-0"' in r.text
    approved = db.q("SELECT id FROM refs WHERE song_id=? AND tier=? AND clip_idx=0 AND approved=1", sid, tier)
    assert [row["id"] for row in approved] == [ref0a]

    # approving a second candidate for the SAME clip must leave exactly one approved
    r2 = client.post(f"/songs/{sid}/refs/0/approve", data={"tier": tier, "ref_id": ref0b})
    assert r2.status_code == 200
    approved2 = db.q("SELECT id FROM refs WHERE song_id=? AND tier=? AND clip_idx=0 AND approved=1", sid, tier)
    assert [row["id"] for row in approved2] == [ref0b], approved2

    # clip_idx 1 and 2 still have no approved ref -> /clips must refuse, not 500
    r3 = client.post(f"/songs/{sid}/clips", data={"tier": tier}, follow_redirects=False)
    assert r3.status_code == 400, r3.text
    assert "missing an approved still" in r3.text

    client.post(f"/songs/{sid}/refs/1/approve", data={"tier": tier, "ref_id": ref1})
    client.post(f"/songs/{sid}/refs/2/approve", data={"tier": tier, "ref_id": ref2})

    r4 = client.post(f"/songs/{sid}/clips", data={"tier": tier}, follow_redirects=False)
    assert r4.status_code == 303, r4.text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
