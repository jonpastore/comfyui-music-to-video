"""T10-16: image/video surfaces refuse the child string the audio path accepts.

docs/TRD-10 T10-16 cites T8-4. A lyric or tag mentioning a child is accepted
on the audio path; the **explicit** image path still refuses the same string.
T10-18 is the g/pg13 exception (depiction permitted where nudity cannot be
reached). The one-sided failure is a check that stays green if nothing is
screened anywhere — the positive half requires the explicit path still refuse.
"""
import os
import sys

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as appmod
import db
import tiers
from test_app import _real_storyboard, _scene, _upload_song

# Measured phrase that used to come back ContentRefused on the audio path
# (TRD-8 §3 / 1cac5bb). Same string for both halves.
CHILD = "nursery rhyme for children"

# Explicit path: T10-18 permits the same string at g/pg13.
EXPLICIT_TIER = "xxx"


def test_t10_16_same_string_audio_accepts_image_and_video_refuse():
    """Both halves, one string. Screening everything or nothing fails this."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-16 Child Song", album="T10-16 Album")
        sid = song["id"]

        # --- audio half: tags AND lyrics with the child string are accepted ---
        before = db.one(
            "SELECT COUNT(*) c FROM jobs WHERE song_id=? AND kind='audio'", sid)["c"]
        r = client.post(
            f"/songs/{sid}/audio/generate",
            data={"tags": CHILD, "lyrics": f"a song for children: {CHILD}",
                  "seconds": "12", "n": "1"},
        )
        assert r.status_code in (200, 303), (
            f"audio path refused the child string: {r.status_code} {r.text[:300]}")
        after = db.one(
            "SELECT COUNT(*) c FROM jobs WHERE song_id=? AND kind='audio'", sid)["c"]
        assert after == before + 1, "accepted tags never enqueued an audio job"

        # --- image half: storyboard direction on the explicit path ---
        sb_before = db.one(
            "SELECT COUNT(*) c FROM jobs WHERE song_id=? AND kind='storyboard'",
            sid)["c"]
        r_img = client.post(
            f"/songs/{sid}/storyboard",
            data={"tier": EXPLICIT_TIER, "direction": CHILD},
        )
        assert r_img.status_code == 400, (
            f"image path accepted the child string as direction: {r_img.text[:300]}")
        low = r_img.text.lower()
        assert "child" in low or "nursery" in low or "minor" in low, r_img.text[:300]
        sb_after = db.one(
            "SELECT COUNT(*) c FROM jobs WHERE song_id=? AND kind='storyboard'",
            sid)["c"]
        assert sb_after == sb_before, "refused direction still enqueued a storyboard"

        # --- scene fields that feed image and video renders ---
        _real_storyboard(sid, EXPLICIT_TIER, song["slug"] or f"t10-16-{sid}", [_scene(1)])
        for field in ("image_prompt", "video_motion_prompt"):
            r_sc = client.post(
                f"/songs/{sid}/storyboard/{EXPLICIT_TIER}/scene/1",
                data={field: CHILD},
            )
            assert r_sc.status_code == 400, (
                f"scene {field} accepted the child string: {r_sc.text[:300]}")
            low = r_sc.text.lower()
            assert "child" in low or "nursery" in low or "minor" in low, r_sc.text[:300]

        # --- shared form guard used by character/album image-prompt fields ---
        with pytest.raises(HTTPException) as err:
            appmod.screen_prompt_field(CHILD, "image_prompt", "scene")
        assert err.value.status_code == 400
        detail = str(err.value.detail).lower()
        assert "child" in detail or "nursery" in detail or "minor" in detail, detail


def test_t10_16_make_audio_still_has_no_image_guardrail():
    """Workflow writer must not re-bind the image guardrail (T8-4 half)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    import make_audio
    assert "guardrail" not in make_audio.__dict__, (
        "the image guardrail is back on the audio path; it refuses nursery rhymes")
    kids = make_audio.workflow(
        CHILD, "the little kids sang", 30, 1, "audio_kids/take_000_s1")
    assert kids["2"]["inputs"]["tags"] == CHILD
    assert kids["2"]["inputs"]["lyrics"] == "the little kids sang"
    # positive half of "not screening everything": the image guard still fires
    with pytest.raises(tiers.ContentRefused):
        tiers.check_text(CHILD, "image path")
