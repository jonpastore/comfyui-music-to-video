"""T10-19: escalation re-screens the whole work at the destination tier
and names the blocking reference.

A g work mentioning a child cannot become xxx at all, and cannot become r
while the reference sits in any field that reaches a render prompt. A clean
work escalates normally (positive half). Deleting the re-screen, or refusing
without naming the field, must turn this red.
"""
import json

import pytest
from fastapi.testclient import TestClient

import app as appmod
import db
import guardrail
import storyboard_service
import tiers
from test_app import _real_storyboard, _scene, _upload_song


NIECE_LYRICS = "[Verse]\nfor my 7 year old niece, a child dancing in the garden\n"
NIECE_PROMPT = "a 7 year old child dancing in the garden, fully clothed"
CLEAN_LYRICS = "[Verse]\nan adult night on the rooftop\n"
CLEAN_PROMPT = "an adult woman dancing on a rooftop at night"


def test_t10_19_screen_escalation_names_blocking_field():
    """Pure screen: destination rule + named field. Mutation: drop the name."""
    with pytest.raises(guardrail.ContentRefused) as err:
        guardrail.screen_escalation(
            [("image_prompt", NIECE_PROMPT), ("lyrics", NIECE_LYRICS)],
            "r",
        )
    msg = str(err.value).lower()
    assert "image_prompt" in msg, msg
    assert "child" in msg or "7 year" in msg or "year old" in msg, msg

    with pytest.raises(guardrail.ContentRefused) as err:
        guardrail.screen_escalation(
            [("lyrics", NIECE_LYRICS)],
            "xxx",
        )
    msg = str(err.value).lower()
    assert "lyrics" in msg, msg
    assert "child" in msg or "7 year" in msg or "year old" in msg, msg


def test_t10_19_r_allows_lyrics_only_mention_blocks_prompt_fields():
    """g with lyrics-only child may become r; prompt field still blocks r."""
    guardrail.screen_escalation([("lyrics", NIECE_LYRICS)], "r")

    with pytest.raises(guardrail.ContentRefused) as err:
        guardrail.screen_escalation(
            [("lyrics", NIECE_LYRICS), ("video_motion_prompt", NIECE_PROMPT)],
            "r",
        )
    assert "video_motion_prompt" in str(err.value).lower()


def test_t10_19_clean_work_escalates_to_r_and_xxx():
    """Positive half: lock cannot be lifted is one-sided without this."""
    clean = [
        ("lyrics", CLEAN_LYRICS),
        ("image_prompt", CLEAN_PROMPT),
        ("video_motion_prompt", "she turns toward the camera"),
    ]
    guardrail.screen_escalation(clean, "r")
    guardrail.screen_escalation(clean, "xxx")


def test_t10_19_work_with_prompt_child_cannot_enqueue_r_or_xxx():
    """At the moment of escalation (storyboard enqueue) the whole work is
    re-screened and the blocking reference is named."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-19 Niece Block", album="T10-19 Album")
        sid, slug = song["id"], song["slug"]
        db.store_lyrics(sid, CLEAN_LYRICS, source="supplied")
        scenes = [dict(_scene(1), image_prompt=NIECE_PROMPT)]
        _real_storyboard(sid, "g", slug, scenes)

        with pytest.raises(tiers.ContentRefused) as err:
            storyboard_service.enqueue(sid, "r", direction="adult club night")
        msg = str(err.value).lower()
        assert "image_prompt" in msg or "scene" in msg, msg
        assert "child" in msg or "7 year" in msg or "year old" in msg, msg

        with pytest.raises(tiers.ContentRefused) as err:
            storyboard_service.enqueue(sid, "xxx", direction="adult club night")
        msg = str(err.value).lower()
        assert "child" in msg or "7 year" in msg or "year old" in msg, msg


def test_t10_19_work_with_lyrics_child_cannot_become_xxx_can_become_r():
    """xxx re-screens everything including lyrics; r allows lyrics-only."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-19 Lyrics Only", album="T10-19 Album B")
        sid, slug = song["id"], song["slug"]
        db.store_lyrics(sid, NIECE_LYRICS, source="supplied")
        _real_storyboard(sid, "g", slug, [_scene(1)])

        with pytest.raises(tiers.ContentRefused) as err:
            storyboard_service.enqueue(sid, "xxx", direction="")
        assert "lyrics" in str(err.value).lower(), str(err.value)

        jid = storyboard_service.enqueue(sid, "r", direction="adult performance")
        assert jid
        job = db.one("SELECT * FROM jobs WHERE id=?", jid)
        assert job["kind"] == "storyboard"
        args = json.loads(job["args_json"] or "{}")
        assert args.get("tier") == "r"


def test_t10_19_clean_song_escalates_via_enqueue():
    """Positive half through the shared entry point."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-19 Clean", album="T10-19 Album C")
        sid, slug = song["id"], song["slug"]
        db.store_lyrics(sid, CLEAN_LYRICS, source="supplied")
        _real_storyboard(sid, "g", slug, [dict(_scene(1), image_prompt=CLEAN_PROMPT)])

        jid_r = storyboard_service.enqueue(sid, "r", direction="night set")
        jid_x = storyboard_service.enqueue(sid, "xxx", direction="night set")
        assert jid_r and jid_x


def test_t10_19_enable_nudity_rescreens_locked_tier_work():
    """Enabling nudity is an escalation path; refuses naming the reference."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-19 Nude Esc", album="T10-19 Album D")
        sid, slug = song["id"], song["slug"]
        db.store_lyrics(sid, CLEAN_LYRICS, source="supplied")
        _real_storyboard(
            sid, "g", slug,
            [dict(_scene(1), image_prompt=NIECE_PROMPT)],
        )

        with pytest.raises(tiers.ContentRefused) as err:
            tiers.set_allow_nudity("g", True)
        msg = str(err.value).lower()
        assert "child" in msg or "7 year" in msg or "year old" in msg, msg
        assert not tiers.allows_nudity("g")


def test_t10_19_http_storyboard_escalation_names_block():
    """HTML/API path: POST storyboard at higher tier returns 400 with the name."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-19 HTTP", album="T10-19 Album E")
        sid, slug = song["id"], song["slug"]
        db.store_lyrics(sid, CLEAN_LYRICS, source="supplied")
        _real_storyboard(
            sid, "g", slug,
            [dict(_scene(1), image_prompt=NIECE_PROMPT)],
        )
        r = client.post(
            f"/songs/{sid}/storyboard",
            data={"tier": "xxx", "direction": "adult night", "scene_seconds": "4"},
        )
        assert r.status_code == 400, r.text
        low = r.text.lower()
        assert "child" in low or "7 year" in low or "year old" in low or "minor" in low, r.text[:400]
        assert "image_prompt" in low or "scene" in low or "escalat" in low, r.text[:400]
