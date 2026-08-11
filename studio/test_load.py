"""Load / concurrency and end-to-end flow tests for studio/.

Stubs pipeline, grok, lyrics, mixer via sys.modules *before* app.py is
imported, so this needs no GPU, no network and no ComfyUI. Uses a temp
STUDIO_DATA sqlite db (real db.py/jobs.py/tiers.py -- those are cheap and
worth exercising for real).

Run: python3 -m pytest test_load.py -q
"""
import asyncio
import itertools
import os
import sys
import tempfile
import time
import types

import httpx
import pytest

STUDIO_DIR = os.path.dirname(os.path.abspath(__file__))
if STUDIO_DIR not in sys.path:
    sys.path.insert(0, STUDIO_DIR)

_DATA_DIR = tempfile.mkdtemp(prefix="studio_test_load_")
os.environ["STUDIO_DATA"] = _DATA_DIR


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


_stub(
    "pipeline",
    COMFY_INPUT=os.path.join(_DATA_DIR, "comfy_input"),
    COMFY_OUTPUT=os.path.join(_DATA_DIR, "comfy_output"),
    install_input=lambda path, name=None: os.path.basename(path),
    gen_anchor=lambda *a, **k: [],
    gen_refs=lambda *a, **k: [],
    reroll=lambda *a, **k: [],
    gen_clips=lambda *a, **k: [],
)
_stub(
    "grok",
    list_models=lambda: [],
    generate_storyboard=lambda *a, **k: {"scenes": []},
    write_storyboard=lambda *a, **k: ("/fake/sb.json", "/fake/sb.md"),
)
_stub(
    "lyrics",
    available=lambda: (True, ""),
    transcribe=lambda *a, **k: {},
    to_sections=lambda *a, **k: "",
    estimate_duration=lambda *a, **k: 120.0,
)

# render_set contract worth pinning: real mixer.render_set raises on empty
# items and every item must carry "video" (a past bug passed "path", which
# would KeyError here exactly like it would against the real function).
_render_set_calls = []


def _fake_render_set(items, out_path, progress=None):
    if not items:
        raise ValueError("items is empty")
    for it in items:
        _ = it["video"]
    _render_set_calls.append(items)
    with open(out_path, "wb") as f:
        f.write(b"fake-video")
    return out_path


_stub(
    "mixer",
    render_set=_fake_render_set,
    assemble_song=lambda *a, **k: None,
)

import db  # noqa: E402
import jobs  # noqa: E402
import app as app_module  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_song_counter = itertools.count(1)


def _make_song(prefix="song"):
    n = next(_song_counter)
    slug = f"{prefix}-{n}"
    return db.upsert_song(slug, title=slug, mp3_path=f"/fake/{slug}.mp3")


def _make_storyboard(song_id, tier, scene_count):
    db.run(
        """INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created)
           VALUES (?,?,?,?,?,?)""",
        song_id, tier, "/fake/sb.json", "/fake/sb.md", scene_count, time.time(),
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


# --------------------------------------------------------------- GAP 1 --
# SSE concurrency: jobs.stream must be a real async generator. As a sync
# generator, Starlette drives it through iterate_in_threadpool and each open
# viewer parks an anyio threadpool worker; 41 concurrent viewers exhausted
# the (default 40-token) pool and every route -- sync or async -- serving
# through run_in_threadpool wedged, and did not recover on disconnect.

def test_sse_concurrency_does_not_starve_other_routes(client):
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
        transport = httpx.ASGITransport(app=app_module.app)
        timeout = httpx.Timeout(10.0)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=timeout) as ac:
            n_viewers = 45
            hold_seconds = 1.5
            tasks = [asyncio.create_task(_hold_stream(ac, hold_seconds)) for _ in range(n_viewers)]
            await asyncio.sleep(0.3)  # let every viewer connect and hit its first sleep

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
# Playlist + genre flows: kind column, ordering, reorder, render_set item
# shape ("video" key, not "path"), and clean refusal instead of a 500.

def test_playlist_and_genre_flow_ordering(client):
    r1 = client.post("/playlists", data={"name": "Chill Mix", "kind": "playlist"}, follow_redirects=False)
    assert r1.status_code == 303
    r2 = client.post("/playlists", data={"name": "Synthwave", "kind": "genre"}, follow_redirects=False)
    assert r2.status_code == 303

    playlist = db.one("SELECT * FROM playlists WHERE name=? AND kind='playlist'", "Chill Mix")
    genre = db.one("SELECT * FROM playlists WHERE name=? AND kind='genre'", "Synthwave")
    assert playlist is not None and genre is not None
    assert playlist["kind"] == "playlist"
    assert genre["kind"] == "genre"

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
           s2, "r", "/fake/renders/two.mp4", time.time())

    pl = db.run("INSERT INTO playlists (name, kind) VALUES (?, 'playlist')", f"RenderTest-{s1}")
    client.post(f"/playlists/{pl}/items", data={"song_id": s1, "tier": "pg13"}, follow_redirects=False)
    client.post(f"/playlists/{pl}/items", data={"song_id": s2, "tier": "r"}, follow_redirects=False)

    before_max = db.one("SELECT COALESCE(MAX(id),0) AS m FROM jobs")["m"]
    r = client.post(f"/playlists/{pl}/render", follow_redirects=False)
    assert r.status_code == 303

    job = _wait_new_job("render_set", before_max)
    assert job["status"] == "done", (job["status"], job["error"])

    assert _render_set_calls, "mixer.render_set was never called"
    called_items = _render_set_calls[-1]
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
    client.post(f"/playlists/{pl}/items", data={"song_id": s1, "tier": "pg13"}, follow_redirects=False)

    r = client.post(f"/playlists/{pl}/render", follow_redirects=False)
    assert r.status_code == 400, r.text
    assert "render" in r.text.lower()

    assert client.get("/playlists").status_code == 200


# --------------------------------------------------------------- GAP 3 --
# Approval grid: multiple ref candidates for one clip_idx (what reroll
# produces), approve-toggle semantics, the _clip_tile htmx partial, and the
# /clips gate that refuses while any clip index lacks an approved ref.

def test_approval_grid_multi_candidate_and_clip_gating(client):
    sid = _make_song("approve")
    tier = "pg13"
    _make_storyboard(sid, tier, scene_count=3)

    ref0a = _make_ref(sid, tier, 0, seed=111)
    ref0b = _make_ref(sid, tier, 0, seed=222)  # reroll-style second candidate, same clip_idx
    ref1 = _make_ref(sid, tier, 1, seed=333)
    ref2 = _make_ref(sid, tier, 2, seed=444)

    grid = client.get(f"/songs/{sid}/approve/{tier}")
    assert grid.status_code == 200
    assert "Clip 0" in grid.text and "Clip 1" in grid.text and "Clip 2" in grid.text

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
    assert "1" in r3.text and "2" in r3.text

    client.post(f"/songs/{sid}/refs/1/approve", data={"tier": tier, "ref_id": ref1})
    client.post(f"/songs/{sid}/refs/2/approve", data={"tier": tier, "ref_id": ref2})

    r4 = client.post(f"/songs/{sid}/clips", data={"tier": tier}, follow_redirects=False)
    assert r4.status_code == 303, r4.text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
