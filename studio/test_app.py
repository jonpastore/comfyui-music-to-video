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
    if extra.get("explicit"):
        fields["explicit"] = "true"  # an absent field is what an unchecked checkbox sends
    client.post("/songs", data=fields, files={"mp3": (f"{title}.mp3", data, "audio/mpeg")})
    return db.one("SELECT * FROM songs WHERE title=?", title)


def _chosen_anchor(album, tier, path="anchor.png", view="front"):
    """Insert a chosen anchors row directly -- the pipeline.gen_anchor path is
    covered by its own test; most refs/reroll tests only need a resolved
    anchor already in place."""
    db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen, created)
              VALUES ('album', ?, ?, ?, ?, 1, ?)""", album, tier, view, path, time.time())


def test_empty_state_pages_200():
    with TestClient(appmod.app) as client:
        for path in ("/", "/playlists", "/tiers", "/jobs", "/anchors"):
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
        assert client.post("/songs/999999/refs", data={"tier": "pg13"}).status_code == 404
        assert client.post("/songs/999999/explicit").status_code == 404
        assert client.post("/anchors/999999/pick").status_code == 404
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
                    data={"song_id": sid, "transition": "fade", "secs": "1.0"})

        r = client.post(f"/playlists/{pl['id']}/render",
                        data={"include_videos": "true", "tier": "pg13"})
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

        # a long song + a big request -> capped, not fanned out unbounded.
        # The bound is the CLIP count (audio length), not the scene count.
        db.run("UPDATE songs SET duration=? WHERE id=?", 5000.0, sid)
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
        song = _upload_song(client, "Limit Song", album="Limit Album")
        sid = song["id"]
        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13"})
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", sid)
        wait_job(job["id"])
        _chosen_anchor("Limit Album", "pg13")

        r = client.post(f"/songs/{sid}/refs", data={"tier": "pg13", "limit": "-100"})
        assert r.status_code in (200, 303), r.text
        job2 = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='refs' ORDER BY id DESC", sid)
        # -100 clamped to 0, and 0 is falsy -> stored as None (unlimited), never negative
        assert json.loads(job2["args_json"])["limit"] is None
        assert json.loads(job2["args_json"])["anchor_path"] == "anchor.png"


def test_explicit_flag_set_at_upload_and_toggled_and_shown():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Explicit Song", explicit=True)
        assert song["explicit"] == 1
        r = client.get(f"/songs/{song['id']}")
        assert "EXPLICIT" in r.text

        clean = _upload_song(client, "Clean Song")
        assert clean["explicit"] == 0
        r2 = client.get(f"/songs/{clean['id']}")
        assert "EXPLICIT" not in r2.text

        r3 = client.post(f"/songs/{song['id']}/explicit")
        assert r3.status_code in (200, 303), r3.text
        assert db.one("SELECT explicit FROM songs WHERE id=?", song["id"])["explicit"] == 0

        r4 = client.post(f"/songs/{song['id']}/explicit")
        assert db.one("SELECT explicit FROM songs WHERE id=?", song["id"])["explicit"] == 1


def test_explicit_not_passed_to_grok_or_pipeline(patch_stub):
    gen_refs_calls = []

    def _gen_refs(slug, tier, sb, anchor, mp3, progress=None, limit=None, guard="", body=""):
        gen_refs_calls.append(dict(slug=slug, tier=tier, anchor=anchor, limit=limit,
                                    guard=guard, body=body))
        return []

    patch_stub("pipeline", gen_refs=_gen_refs)
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Explicit Content Song", album="Explicit Album", explicit=True)
        sid = song["id"]

        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13"})
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", sid)
        wait_job(job["id"])
        assert "explicit" not in grok_calls["args"]["song"]

        _chosen_anchor("Explicit Album", "pg13")
        r = client.post(f"/songs/{sid}/refs", data={"tier": "pg13"})
        assert r.status_code in (200, 303), r.text
        job2 = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='refs' ORDER BY id DESC", sid)
        wait_job(job2["id"])
        assert gen_refs_calls and "explicit" not in gen_refs_calls[0]


def test_anchor_generation_independent_tier_groups_and_picking(patch_stub):
    n_calls = []

    def _gen_anchor(face, outfit, view="front", n=4, progress=None, prefix=None, profile=None):
        # profile carries the ALBUM's look (identity/wardrobe/body) -- the
        # character description is no longer inside make_anchor.py
        n_calls.append(profile)
        return [f"/tmp/anchor_{len(n_calls)}_{i}.png" for i in range(2)]

    patch_stub("pipeline", gen_anchor=_gen_anchor)
    with TestClient(appmod.app) as client:
        files = {"face": ("f.png", b"x", "image/png"), "outfit": ("o.png", b"x", "image/png")}
        base = {"scope_kind": "album", "scope_value": "Street Cats", "view": "front", "n": "2"}

        r1 = client.post("/anchors", data=dict(base, tier="r"), files=files)
        assert r1.status_code in (200, 303), r1.text
        job1 = db.one("SELECT * FROM jobs WHERE kind='anchor' ORDER BY id DESC")
        wait_job(job1["id"])

        r2 = client.post("/anchors", data=dict(base, tier="pg13"), files=files)
        assert r2.status_code in (200, 303), r2.text
        job2 = db.one("SELECT * FROM jobs WHERE kind='anchor' ORDER BY id DESC")
        wait_job(job2["id"])

        r_rows = db.q("""SELECT * FROM anchors WHERE scope_kind='album' AND scope_value='Street Cats'
                          AND tier='r' ORDER BY id""")
        pg_rows = db.q("""SELECT * FROM anchors WHERE scope_kind='album' AND scope_value='Street Cats'
                           AND tier='pg13' ORDER BY id""")
        assert len(r_rows) == 2 and len(pg_rows) == 2

        client.post(f"/anchors/{r_rows[0]['id']}/pick")
        r_chosen = db.q("""SELECT id FROM anchors WHERE scope_kind='album' AND scope_value='Street Cats'
                            AND tier='r' AND chosen=1""")
        assert [x["id"] for x in r_chosen] == [r_rows[0]["id"]]
        pg_chosen = db.q("""SELECT id FROM anchors WHERE scope_kind='album' AND scope_value='Street Cats'
                             AND tier='pg13' AND chosen=1""")
        assert pg_chosen == []  # other group untouched

        # picking a different candidate in the same group: still exactly one chosen
        client.post(f"/anchors/{r_rows[1]['id']}/pick")
        r_chosen2 = db.q("""SELECT id FROM anchors WHERE scope_kind='album' AND scope_value='Street Cats'
                             AND tier='r' AND chosen=1""")
        assert [x["id"] for x in r_chosen2] == [r_rows[1]["id"]]

        # picking in the pg13 group doesn't disturb r's chosen candidate
        client.post(f"/anchors/{pg_rows[0]['id']}/pick")
        r_chosen3 = db.q("""SELECT id FROM anchors WHERE scope_kind='album' AND scope_value='Street Cats'
                             AND tier='r' AND chosen=1""")
        assert [x["id"] for x in r_chosen3] == [r_rows[1]["id"]]


def test_refs_two_tiers_enqueues_two_jobs_with_own_anchors():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Two Tier Song", album="Two Tier Album")
        sid = song["id"]
        for t in ("pg13", "r"):
            client.post(f"/songs/{sid}/storyboard", data={"tier": t})
            job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", sid)
            wait_job(job["id"])
            _chosen_anchor("Two Tier Album", t, path=f"anchor_{t}.png")

        before = len(jobs.recent(1000))
        r = client.post(f"/songs/{sid}/refs", data={"tier": ["pg13", "r"], "limit": "0"})
        assert r.status_code in (200, 303), r.text
        assert len(jobs.recent(1000)) == before + 2

        refs_jobs = db.q("SELECT * FROM jobs WHERE song_id=? AND kind='refs' ORDER BY id DESC LIMIT 2", sid)
        by_tier = {json.loads(j["args_json"])["tier"]: json.loads(j["args_json"]) for j in refs_jobs}
        assert set(by_tier) == {"pg13", "r"}
        assert by_tier["pg13"]["anchor_path"] == "anchor_pg13.png"
        assert by_tier["r"]["anchor_path"] == "anchor_r.png"


def test_refs_tier_without_chosen_anchor_400_names_tier_and_enqueues_nothing():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "No Anchor Song", album="No Anchor Album")
        sid = song["id"]
        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13"})
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", sid)
        wait_job(job["id"])

        before = len(jobs.recent(1000))
        r = client.post(f"/songs/{sid}/refs", data={"tier": "pg13"})
        assert r.status_code == 400, r.text
        assert "pg13" in r.text
        assert len(jobs.recent(1000)) == before


def test_refs_offers_only_tiers_with_a_storyboard_and_one_review_per_tier():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Refs Gate Song")
        sid = song["id"]

        page = client.get(f"/songs/{sid}").text
        assert "No storyboard yet" in page
        assert 'name="tier" value="pg13"' not in page, "offered a tier with nothing to render from"

        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13"})
        wait_job(db.one("SELECT id FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC",
                        sid)["id"])
        page2 = client.get(f"/songs/{sid}").text
        assert 'class="check"><input type="checkbox" name="tier" value="pg13"' in page2
        assert 'value="r"' not in page2.split("Reference images")[1].split("</section>")[0]

        # running the check twice must not list the tier twice
        for note in ("first", "second"):
            db.run("""INSERT INTO assets (song_id, kind, path, meta_json, created)
                      VALUES (?,'review',?,?,?)""",
                   sid, f"/fake/{note}.jpg", '{"tier": "pg13", "flagged": []}', time.time())
        page3 = client.get(f"/songs/{sid}").text
        assert page3.count("nothing flagged") == 1, "the same tier was listed twice"
        assert "second.jpg" in page3, "showed the older review, not the newest"


def test_body_consistency_wording_reaches_every_reference_prompt(patch_stub):
    """Colouring stated once at the top of a prompt does not hold below the
    waist -- pale limbs, and one glute black and the other white. The album's
    body text has to be in EVERY frame's prompt, not only the anchor's."""
    seen = []

    def _gen_refs(slug, tier, sb, anchor, mp3, progress=None, limit=None, guard="", body=""):
        seen.append(body)
        return []

    patch_stub("pipeline", gen_refs=_gen_refs)
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Body Lock Song", album="Body Album")
        sid = song["id"]
        pl = db.run("INSERT INTO playlists (name, kind, created) VALUES (?,'playlist',?)",
                    "Body Album", time.time())
        client.post(f"/playlists/{pl}/profile",
                    data={"body": "black-furred thighs and glutes, no human skin anywhere"})
        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13"})
        wait_job(db.one("SELECT id FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC",
                        sid)["id"])
        _chosen_anchor("Body Album", "pg13")

        client.post(f"/songs/{sid}/refs", data={"tier": "pg13"})
        wait_job(db.one("SELECT id FROM jobs WHERE song_id=? AND kind='refs' ORDER BY id DESC",
                        sid)["id"])
        assert seen and "no human skin anywhere" in seen[-1], seen

    # and it lands in the prompt the image model is actually handed
    import build_refs
    scene = {"scene_number": 1, "image_prompt": "she crosses the alley", "negative_prompt": ""}
    wf = build_refs.workflow(scene, "a.png", None, "empty", 1280, 720, 7000, "WIDE SHOT.",
                             "tier wording", "world", "a black feline woman",
                             "black-furred thighs and glutes, no human skin anywhere")
    assert "no human skin anywhere" in wf["11"]["inputs"]["prompt"]


def test_storyboard_style_note_comes_from_the_album():
    """The per-song style-guide upload moved to the album. Nothing may end up
    sending the model an EMPTY style note because the form moved."""
    from conftest import grok_calls
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Album Look Song", album="Look Album")
        sid = song["id"]
        pl = db.run("INSERT INTO playlists (name, kind, created) VALUES (?,'playlist',?)",
                    "Look Album", time.time())
        client.post(f"/playlists/{pl}/profile",
                    data={"style_text": "grimy neon", "world": "flooded car parks",
                          "render_tail": "16:9 film still"})

        grok_calls.clear()
        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13"})
        wait_job(db.one("SELECT id FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC",
                        sid)["id"])
        note = grok_calls["args"]["style_note"]
        assert "grimy neon" in note and "flooded car parks" in note and "16:9 film still" in note, note

        # a legacy per-song style asset still wins for songs set up before the move
        db.run("""INSERT INTO assets (song_id, kind, path, meta_json, created)
                  VALUES (?,'style','/fake/s.png',?,?)""", sid, '{"note": "the old note"}', time.time())
        grok_calls.clear()
        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13"})
        wait_job(db.one("SELECT id FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC",
                        sid)["id"])
        assert grok_calls["args"]["style_note"] == "the old note"


def test_audio_edit_from_a_prompt_is_recorded_with_its_provenance():
    from conftest import edit_prompt_calls
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Prompt Edit Song")
        sid = song["id"]
        n = len(edit_prompt_calls)

        r = client.post(f"/songs/{sid}/audio",
                        data={"prompt": "cut the giggling in the first 4 seconds"})
        assert r.status_code in (200, 303), r.text
        assert len(edit_prompt_calls) == n + 1
        assert edit_prompt_calls[-1][0] == "cut the giggling in the first 4 seconds"

        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='edit_audio' ORDER BY id DESC", sid)
        args = json.loads(job["args_json"])
        # the model filled the SAME five parameters the form has
        assert args["trim_start"] == 4.0 and args["gain_db"] == 0.0
        # ...and what produced them travels with them
        assert args["prompt"].startswith("cut the giggling")
        assert args["note"] == "cut the first 4s" and args["model"] == "qwen-stub"

        assert wait_job(job["id"])["status"] == "done"
        asset = db.one("""SELECT * FROM assets WHERE song_id=? AND kind='audio_edit'
                          ORDER BY id DESC""", sid)
        meta = json.loads(asset["meta_json"])
        assert meta["trim_start"] == 4.0
        assert meta["prompt"].startswith("cut the giggling")
        assert meta["model"] == "qwen-stub", meta
        # and the page shows it, so an edit can be explained later
        assert "cut the first 4s" in client.get(f"/songs/{sid}").text

        # a hostile prompt result is still clamped by the same validation
        appmod.vision.read_edit_instruction = lambda prompt, duration, progress=None: (
            {"trim_start": -50.0, "trim_end": None, "gain_db": 999.0,
             "fade_in": 0.0, "fade_out": 0.0}, "n", "m")
        r2 = client.post(f"/songs/{sid}/audio", data={"prompt": "destroy it"})
        assert r2.status_code == 400, "out-of-range params from a model must be refused"


def test_song_page_layout_rebuild():
    """The annotated batch: paired cards, one-row fields, model default, job
    timings, a real delete confirmation, and no scene-seconds knob."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Layout Song")
        sid = song["id"]
        page = client.get(f"/songs/{sid}").text

        assert 'class="row-2col"' in page                 # lyrics beside style prompt
        assert page.count('class="stack-form"') >= 3      # save buttons below their boxes
        assert 'class="field-row"' in page                # audio fields on one row
        assert 'name="scene_seconds"' not in page         # the model paces itself now
        assert "highest available" in page
        assert "view reference image gallery" in page or not page.count("approve refs")
        assert 'class="table-scroll"' in page             # jobs scroll, not stretch
        # right-aligned so the times and durations line up down the column
        assert '<th class="num">Start</th>' in page and '<th class="num">Exec</th>' in page
        # delete needs the word typed; a hidden field is not a confirmation
        assert 'name="confirm" placeholder="DELETE"' in page
        assert '<input type="hidden" name="confirm" value="DELETE">' not in page

        # assembling is offered only for tiers that actually have clips
        assert "no clips rendered yet" in page
        db.run("""INSERT INTO clips (song_id, tier, clip_idx, path, status)
                  VALUES (?,'pg13',0,'/fake/c0.mp4','done')""", sid)
        page2 = client.get(f"/songs/{sid}").text
        assert "no clips rendered yet" not in page2
        assert '<option value="pg13">pg13</option>' in page2

        # timings render as clock times, not epochs
        db.run("""INSERT INTO jobs (kind, args_json, status, song_id, created, started, finished)
                  VALUES ('refs','{}','done',?,?,?,?)""", sid, 1000.0, 1000.0, 1123.0)
        page3 = client.get(f"/songs/{sid}").text
        assert "1123" not in page3, "raw epoch leaked into the jobs table"
        assert "2:03" in page3, "exec time (123s) not shown as m:ss"


def test_builtin_tiers_exist_from_startup_not_from_visiting_a_page():
    """A fresh database used to have an empty tiers table until some page
    called all_tiers(), so every tier-validating route 400'd 'no such tier'."""
    db.run("DELETE FROM tiers WHERE builtin=1")
    assert db.q("SELECT name FROM tiers WHERE builtin=1") == []
    with TestClient(appmod.app) as client:          # startup, nothing else
        names = {r["name"] for r in db.q("SELECT name FROM tiers WHERE builtin=1")}
        assert {"pg13", "r"} <= names, names
        # and the validator that used to fail now passes without a page visit
        assert appmod.valid_tier_or_400("pg13") == "pg13"
        assert client.get("/").status_code == 200


def test_style_prompt_saved_and_shown_and_never_sent_to_grok():
    from conftest import grok_calls
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Style Song")
        sid = song["id"]
        text = "Dark warehouse tech house, 128 BPM, rolling sub, spoken female hook."
        r = client.post(f"/songs/{sid}/style-text", data={"style_text": text})
        assert r.status_code in (200, 303), r.text
        assert db.one("SELECT style_text FROM songs WHERE id=?", sid)["style_text"] == text
        assert text in client.get(f"/songs/{sid}").text          # editable, not write-only

        # it describes AUDIO. The storyboard model must not receive it -- that
        # is the text that was just stripped out of every storyboard on disk.
        grok_calls.clear()
        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13"})
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", sid)
        wait_job(job["id"])
        assert grok_calls, "storyboard job never reached grok"
        assert "128 BPM" not in json.dumps(grok_calls, default=str)


def test_transcribe_frees_comfyui_vram_first():
    """ComfyUI keeps ~21.5 GB of the shared 24 GB card resident, which is what
    made every real transcribe job die with CUDA OOM."""
    from conftest import free_vram_calls
    with TestClient(appmod.app) as client:
        n = len(free_vram_calls)
        song = _upload_song(client, "VRAM Song")
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='transcribe'", song["id"])
        assert wait_job(job["id"])["status"] == "done"
        assert len(free_vram_calls) == n + 1


def test_empty_playlist_render_refused_at_the_route():
    with TestClient(appmod.app) as client:
        r = client.post("/playlists", data={"name": "Empty Set", "kind": "playlist"})
        assert r.status_code in (200, 303), r.text
        pl = db.one("SELECT * FROM playlists WHERE name='Empty Set'")
        before = len(jobs.recent(1000))
        r2 = client.post(f"/playlists/{pl['id']}/render")
        # used to enqueue a job whose only outcome was to fail inside mixer
        assert r2.status_code == 400, r2.text
        assert len(jobs.recent(1000)) == before


def test_jobs_page_refresh_interval_follows_the_queue_and_the_control():
    with TestClient(appmod.app) as client:
        # idle queue -> the slow poll
        assert appmod.jobs_refresh_secs("auto", busy=False) == 60
        assert appmod.jobs_refresh_secs("auto", busy=True) == 10
        assert appmod.jobs_refresh_secs("off", busy=True) == 0
        assert appmod.jobs_refresh_secs("30", busy=True) == 30
        # a hand-edited URL must not become a hot loop, or a 10-hour timer
        assert appmod.jobs_refresh_secs("0", busy=False) == 5
        assert appmod.jobs_refresh_secs("999999", busy=False) == 3600
        assert appmod.jobs_refresh_secs("banana", busy=False) == 60

        idle = client.get("/jobs")
        assert 'hx-trigger="every 60s"' in idle.text, idle.text[:400]

        # something running -> the page polls 6x faster, without being asked
        db.run("""INSERT INTO jobs (kind, args_json, status, created, started)
                  VALUES ('refs','{}','running',?,?)""", time.time(), time.time())
        busy = client.get("/jobs")
        assert 'hx-trigger="every 10s"' in busy.text

        off = client.get("/jobs?refresh=off")
        assert "hx-trigger" not in off.text and "hx-get" not in off.text
        assert ">off<" in off.text  # the control still reports its own state

        fixed = client.get("/jobs?refresh=15")
        assert 'hx-trigger="every 15s"' in fixed.text
        assert 'hx-get="/jobs?refresh=15&partial=1"' in fixed.text  # interval survives the poll

        # the poll returns the panel alone, not a second whole document
        part = client.get("/jobs?refresh=15&partial=1")
        assert part.status_code == 200
        assert "<html" not in part.text and 'id="jobs-panel"' in part.text

        db.run("UPDATE jobs SET status='done' WHERE status='running'")


def test_classify_reviews_only_approved_refs_and_reports_flags():
    from conftest import classify_calls, contact_sheet_calls
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Review Song")
        sid = song["id"]

        # nothing approved yet -> refused at the route, no job
        before = len(jobs.recent(1000))
        r = client.post(f"/songs/{sid}/classify", data={"tier": "pg13"})
        assert r.status_code == 400, r.text
        assert len(jobs.recent(1000)) == before

        d = tempfile.mkdtemp()
        for i in range(3):
            open(os.path.join(d, f"src{i}.png"), "w").close()
        # clips 0 and 1 approved, clip 2 NOT -- the sheet must show two frames
        for i in range(3):
            db.run("""INSERT INTO refs (song_id, tier, clip_idx, path, seed, approved, created)
                      VALUES (?,'pg13',?,?,?,?,?)""",
                   sid, i, os.path.join(d, f"src{i}.png"), i, 1 if i < 2 else 0, time.time())

        n_sheets = len(contact_sheet_calls)
        r2 = client.post(f"/songs/{sid}/classify", data={"tier": "pg13"})
        assert r2.status_code in (200, 303), r2.text
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='classify' ORDER BY id DESC", sid)
        row = wait_job(job["id"])
        assert row["status"] == "done", row

        assert contact_sheet_calls[n_sheets:] == [["clip_000.png", "clip_001.png"]]
        assert classify_calls[-1]["note"] == "Review Song (pg13 tier)"

        asset = db.one("SELECT * FROM assets WHERE song_id=? AND kind='review'", sid)
        meta = json.loads(asset["meta_json"])
        assert meta["tier"] == "pg13"
        assert meta["flagged"] == [{"clip": 1, "issue": "broken", "reason": "two of her"}]

        page = client.get(f"/songs/{sid}").text
        assert "1 flagged" in page and "clip 1 (broken)" in page


def test_clips_form_offers_only_tiers_with_full_approved_refs():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Ready Tier Song")
        sid = song["id"]
        client.post(f"/songs/{sid}/storyboard", data={"tier": "pg13"})
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", sid)
        wait_job(job["id"])

        r = client.get(f"/songs/{sid}")
        assert "no tier has fully approved refs yet" in r.text

        # 3 clips, from the 12.3 s stub duration -- NOT the storyboard's 2
        # scenes. Approving only the first two must leave the tier unoffered.
        for i in range(2):
            db.run("""INSERT INTO refs (song_id, tier, clip_idx, path, seed, approved, created)
                      VALUES (?,'pg13',?,?,?,1,?)""", sid, i, f"r{i}.png", i, time.time())
        assert "no tier has fully approved refs yet" in client.get(f"/songs/{sid}").text
        db.run("""INSERT INTO refs (song_id, tier, clip_idx, path, seed, approved, created)
                  VALUES (?,'pg13',2,'r2.png',2,1,?)""", sid, time.time())

        r2 = client.get(f"/songs/{sid}")
        assert "no tier has fully approved refs yet" not in r2.text


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
