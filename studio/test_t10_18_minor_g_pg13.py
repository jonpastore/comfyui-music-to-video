"""T10-18: at g and pg13 a minor may be referenced and depicted.

The niece case, end to end: a song referencing a child generates, and
its G-tier video composes. Deleting the filter cannot stay green — the
explicit path still refuses the same string (T10-22's paired half).

Asserted through the shared entry points: POST /audio/generate, scene
save, guardrail.check_text, and build_song.workflow / build_refs.workflow.
A clips job through the pipeline stub would not reach the prompt builder.
"""
import json
import re

import pytest
from fastapi.testclient import TestClient

import app as appmod
import build_refs
import build_song
import db
import guardrail
from test_app import _real_storyboard, _scene, _upload_song, wait_job


NIECE_LYRICS = "[Verse]\nfor my 7 year old niece, a child dancing in the garden\n"
NIECE_STILL = "a 7 year old child dancing in the garden, fully clothed"
NIECE_MOTION = "the 7 year old child twirls in the garden"


def _prompt_text(wf):
    for node in wf.values():
        inputs = node.get("inputs") or {}
        if "text" in inputs:
            return inputs["text"]
        if "prompt" in inputs:
            return inputs["prompt"]
    raise AssertionError("workflow has no prompt text")


def test_t10_18_check_text_accepts_g_and_pg13_refuses_elsewhere():
    """The shared screen. Unset tier is xxx (T10-25)."""
    for lock in ("g", "pg13"):
        assert guardrail.check_text(NIECE_STILL, "scene", tier=lock) == NIECE_STILL
    for locked_out in (None, "", "r", "xxx", "custom"):
        with pytest.raises(guardrail.ContentRefused):
            guardrail.check_text(NIECE_STILL, "scene", tier=locked_out)


def test_t10_18_pinned_age_never_below_floor():
    """T10-18c: 18 is the floor; PINNED currently says 21."""
    assert guardrail.PINNED_AGE_FLOOR == 18
    ages = [int(n) for n in re.findall(r"at least (\d+) years", guardrail.PINNED)]
    assert ages, "PINNED lost its minimum-age clause"
    assert min(ages) >= guardrail.PINNED_AGE_FLOOR


def test_t10_18_niece_song_generates_and_g_video_renders():
    """A child-referencing song generates; G (and pg13) depict; r/xxx refuse."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Niece Song", album="Niece Album")
        sid, slug = song["id"], song["slug"]

        r = client.post(f"/songs/{sid}/audio/generate", data={
            "tags": "gentle ukulele, nursery rhyme for children",
            "lyrics": NIECE_LYRICS,
            "seconds": "12",
            "n": "1",
        })
        assert r.status_code in (200, 303), r.text
        audio = wait_job(db.one(
            "SELECT id FROM jobs WHERE song_id=? AND kind='audio' ORDER BY id DESC",
            sid)["id"])
        assert audio["status"] == "done", audio
        take = db.one(
            "SELECT * FROM assets WHERE song_id=? AND kind='audio_gen' ORDER BY id DESC",
            sid)
        assert take, "the niece song generated nothing"
        assert "child" in db.jset(take).get("lyrics", "")

        for lock in ("g", "pg13"):
            json_path, _ = _real_storyboard(sid, lock, slug, [_scene(1)])
            saved = client.post(
                f"/songs/{sid}/storyboard/{lock}/scene/1",
                data={"image_prompt": NIECE_STILL,
                      "video_motion_prompt": NIECE_MOTION})
            assert saved.status_code == 200, (lock, saved.text)
            on_disk = json.load(open(json_path))
            assert on_disk["scenes"][0]["image_prompt"] == NIECE_STILL
            assert on_disk["scenes"][0]["video_motion_prompt"] == NIECE_MOTION

            scene = on_disk["scenes"][0]
            video = build_song.workflow(
                0, scene, "c.png", "song.mp3", "c", "w", "",
                video_model="ltx25", tier=lock)
            vtext = _prompt_text(video)
            assert "child" in vtext, (lock, vtext)
            still = build_refs.workflow(
                scene, "a.png", None, "empty", 1280, 720, 7000,
                "WIDE SHOT.", "", tier=lock)
            stext = _prompt_text(still)
            assert "child" in stext, (lock, stext)

        json_path, _ = _real_storyboard(sid, "r", slug, [_scene(1)])
        refused = client.post(
            f"/songs/{sid}/storyboard/r/scene/1",
            data={"image_prompt": NIECE_STILL})
        assert refused.status_code == 400, refused.text
        assert json.load(open(json_path))["scenes"][0]["image_prompt"] != NIECE_STILL

        with pytest.raises(guardrail.ContentRefused):
            build_song.workflow(
                0, dict(_scene(1), video_motion_prompt=NIECE_MOTION),
                "c.png", "song.mp3", "c", "w", "", video_model="ltx25")
        with pytest.raises(guardrail.ContentRefused):
            build_song.workflow(
                0, dict(_scene(1), video_motion_prompt=NIECE_MOTION),
                "c.png", "song.mp3", "c", "w", "", video_model="ltx25",
                tier="xxx")
