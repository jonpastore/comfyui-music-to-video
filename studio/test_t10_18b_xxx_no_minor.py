"""T10-18b: at xxx a minor reference is refused everywhere including lyrics;
a clean xxx work still generates and renders.

The one-sided failure is a check that stays green if xxx is unreachable.
Both halves go through the shared entry points: guardrail.check_text,
POST /songs/{id}/lyrics, POST /songs/{id}/audio/generate, scene save,
and build_song.workflow / build_refs.workflow.
"""
import json

import pytest
from fastapi.testclient import TestClient

import app as appmod
import build_refs
import build_song
import db
import guardrail
import lyrics
from test_app import _real_storyboard, _scene, _upload_song, wait_job


CHILD_LYRICS = "[Verse]\nfor my 7 year old niece, a child dancing in the garden\n"
CHILD_STILL = "a 7 year old child dancing in the garden, fully clothed"
CHILD_MOTION = "the 7 year old child twirls in the garden"
CHILD_TAGS = "nursery rhyme for children"

CLEAN_LYRICS = "[Verse]\nalley cat prowls under neon rain\n"
CLEAN_STILL = "adult anthropomorphic cat-woman on the rooftop at night"
CLEAN_MOTION = "she walks the ledge, tail aside, fully adult proportions"
CLEAN_TAGS = "dark synthwave, adult club anthem"


def _prompt_text(wf):
    for node in wf.values():
        inputs = node.get("inputs") or {}
        if "text" in inputs:
            return inputs["text"]
        if "prompt" in inputs:
            return inputs["prompt"]
    raise AssertionError("workflow has no prompt text")


def test_t10_18b_check_text_and_lyrics_screen_refuse_at_xxx():
    """Shared screen: xxx refuses minors in every named surface, lyrics too."""
    for where in ("lyrics", "scene", "storyboard direction", "tags"):
        with pytest.raises(guardrail.ContentRefused):
            guardrail.check_text(CHILD_STILL, where, tier="xxx")
    with pytest.raises(guardrail.ContentRefused):
        lyrics.screen(CHILD_LYRICS, tier="xxx")
    # positive: clean text at xxx is not a refuse
    assert lyrics.screen(CLEAN_LYRICS, tier="xxx") == CLEAN_LYRICS
    # g may still mention (T10-18); r mention is T10-18a — not refused here
    assert lyrics.screen(CHILD_LYRICS, tier="g") == CHILD_LYRICS
    assert lyrics.screen(CHILD_LYRICS, tier="r") == CHILD_LYRICS
    assert guardrail.refuses_minor_everywhere("xxx")
    assert not guardrail.refuses_minor_everywhere("r")
    assert not guardrail.refuses_minor_everywhere("g")
    # T10-25: unset resolves to xxx, so the same refuse-everywhere rule applies.
    assert guardrail.refuses_minor_everywhere(None)


def test_t10_18b_xxx_refuses_minor_everywhere_including_lyrics():
    """HTTP surfaces of an xxx work refuse the child string, lyrics included."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-18b Dirty", album="T10-18b Album")
        sid, slug = song["id"], song["slug"]
        _real_storyboard(sid, "xxx", slug, [_scene(1)])

        r = client.post(f"/songs/{sid}/lyrics", data={"lyrics_text": CHILD_LYRICS})
        assert r.status_code == 400, r.text
        low = r.text.lower()
        assert "child" in low or "minor" in low or "year" in low, r.text[:400]
        row = db.one("SELECT lyrics FROM songs WHERE id=?", sid)
        assert (row["lyrics"] or "") != CHILD_LYRICS

        before = db.one(
            "SELECT COUNT(*) c FROM jobs WHERE song_id=? AND kind='audio'", sid)["c"]
        r = client.post(f"/songs/{sid}/audio/generate", data={
            "tags": CHILD_TAGS, "lyrics": CHILD_LYRICS, "seconds": "12", "n": "1",
        })
        assert r.status_code == 400, r.text
        after = db.one(
            "SELECT COUNT(*) c FROM jobs WHERE song_id=? AND kind='audio'", sid)["c"]
        assert after == before, "child lyrics still enqueued audio at xxx"

        for field, value in (("image_prompt", CHILD_STILL),
                             ("video_motion_prompt", CHILD_MOTION)):
            r = client.post(
                f"/songs/{sid}/storyboard/xxx/scene/1", data={field: value})
            assert r.status_code == 400, (field, r.text)
            low = r.text.lower()
            assert "child" in low or "minor" in low or "year" in low, r.text[:400]


def test_t10_18b_xxx_storyboard_refuses_existing_child_lyrics():
    """Escalation path: dirty lyrics already on the song block an xxx board."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-18b Escalate", album="T10-18b Album")
        sid = song["id"]
        # No xxx board yet — supplied lyrics land (T10-16 / T10-18 niece case).
        r = client.post(f"/songs/{sid}/lyrics", data={"lyrics_text": CHILD_LYRICS})
        assert r.status_code in (200, 303), r.text
        assert db.one("SELECT lyrics FROM songs WHERE id=?", sid)["lyrics"] == CHILD_LYRICS

        before = db.one(
            "SELECT COUNT(*) c FROM jobs WHERE song_id=? AND kind='storyboard'",
            sid)["c"]
        r = client.post(
            f"/songs/{sid}/storyboard",
            data={"tier": "xxx", "direction": "adult alley at night"},
        )
        assert r.status_code == 400, r.text
        low = r.text.lower()
        assert "child" in low or "minor" in low or "year" in low, r.text[:400]
        after = db.one(
            "SELECT COUNT(*) c FROM jobs WHERE song_id=? AND kind='storyboard'",
            sid)["c"]
        assert after == before, "xxx storyboard enqueued despite child lyrics"


def test_t10_18b_clean_xxx_generates_and_renders():
    """Positive half: a clean xxx work still generates and renders normally."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-18b Clean", album="T10-18b Album")
        sid, slug = song["id"], song["slug"]

        r = client.post(f"/songs/{sid}/lyrics", data={"lyrics_text": CLEAN_LYRICS})
        assert r.status_code in (200, 303), r.text

        r = client.post(f"/songs/{sid}/audio/generate", data={
            "tags": CLEAN_TAGS, "lyrics": CLEAN_LYRICS, "seconds": "12", "n": "1",
        })
        assert r.status_code in (200, 303), r.text
        audio = wait_job(db.one(
            "SELECT id FROM jobs WHERE song_id=? AND kind='audio' ORDER BY id DESC",
            sid)["id"])
        assert audio["status"] == "done", audio

        json_path, _ = _real_storyboard(sid, "xxx", slug, [_scene(1)])
        # lyrics save still allowed when clean + xxx board present
        r = client.post(f"/songs/{sid}/lyrics", data={"lyrics_text": CLEAN_LYRICS})
        assert r.status_code in (200, 303), r.text

        r = client.post(
            f"/songs/{sid}/storyboard/xxx/scene/1",
            data={"image_prompt": CLEAN_STILL,
                  "video_motion_prompt": CLEAN_MOTION})
        assert r.status_code == 200, r.text
        on_disk = json.load(open(json_path))
        assert on_disk["scenes"][0]["image_prompt"] == CLEAN_STILL
        assert on_disk["scenes"][0]["video_motion_prompt"] == CLEAN_MOTION

        scene = on_disk["scenes"][0]
        # Compose must not raise ContentRefused on clean adult text at xxx.
        video = build_song.workflow(
            0, scene, "c.png", "song.mp3", "c", "w", "",
            video_model="ltx25", tier="xxx")
        vtext = _prompt_text(video)
        assert "ledge" in vtext or "walks" in vtext, vtext

        still = build_refs.workflow(
            scene, "a.png", None, "empty", 1280, 720, 7000,
            "WIDE SHOT.", "", tier="xxx")
        stext = _prompt_text(still)
        assert "cat-woman" in stext or "rooftop" in stext, stext

        # clean audio still enqueues after the xxx board exists
        r = client.post(f"/songs/{sid}/audio/generate", data={
            "tags": CLEAN_TAGS, "lyrics": CLEAN_LYRICS, "seconds": "12", "n": "1",
        })
        assert r.status_code in (200, 303), r.text
