"""T10-18: at g and pg13 a minor may be referenced and depicted.

T10-18a: at r, a minor may be mentioned in lyrics/narrative only; that
mention must never reach a render prompt. An r work still generates and
renders, with the reference absent from every prompt string.

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
NIECE_NARRATIVE = "a story about a child who learns to dance"
NIECE_STILL = "a 7 year old child dancing in the garden, fully clothed"
NIECE_MOTION = "the 7 year old child twirls in the garden"
ADULT_STILL = "an adult woman dancing on a rooftop at night, fully clothed"
ADULT_MOTION = "the adult woman turns toward the city lights"


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


def test_t10_18a_r_mentions_lyrics_narrative_never_render():
    """T10-18a: at r, lyrics/narrative may mention; render fields refuse.

    Mutation: drop the r+field_kind allowance and check_text refuses lyrics;
    drop the refuse half and a child lands in the composed prompt.
    """
    assert guardrail.MENTION_FIELD_KINDS == frozenset({"lyrics", "narrative"})
    assert guardrail.allows_minor_mention("r", field_kind="lyrics")
    assert guardrail.allows_minor_mention("r", field_kind="narrative")
    assert not guardrail.allows_minor_mention("r", field_kind="image_prompt")
    assert not guardrail.allows_minor_mention("r")
    assert not guardrail.allows_minor_mention("xxx", field_kind="lyrics")
    assert not guardrail.allows_minor_mention(None, field_kind="lyrics")

    assert guardrail.check_text(
        NIECE_LYRICS, "lyrics", tier="r", field_kind="lyrics") == NIECE_LYRICS
    assert guardrail.check_text(
        NIECE_NARRATIVE, "narrative", tier="r",
        field_kind="narrative") == NIECE_NARRATIVE

    for kind in (None, "image_prompt", "video_motion_prompt", "scene", "character"):
        with pytest.raises(guardrail.ContentRefused):
            guardrail.check_text(NIECE_STILL, "scene", tier="r", field_kind=kind)
    with pytest.raises(guardrail.ContentRefused):
        guardrail.check_text(
            NIECE_LYRICS, "lyrics", tier="xxx", field_kind="lyrics")
    with pytest.raises(guardrail.ContentRefused):
        guardrail.build_prompt(NIECE_STILL, tier="r")


def test_t10_18a_r_work_generates_and_renders_without_child_in_prompt():
    """An r work with the mention in lyrics generates its song AND renders.

    The reference is absent from every composed prompt string. Adult scene
    text still builds; child scene text is still refused at the prompt wall.
    """
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "R Niece Song", album="R Niece Album")
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
        assert take, "the r work generated nothing"
        assert "child" in db.jset(take).get("lyrics", "")

        json_path, _ = _real_storyboard(sid, "r", slug, [_scene(1)])
        saved = client.post(
            f"/songs/{sid}/storyboard/r/scene/1",
            data={"image_prompt": ADULT_STILL,
                  "video_motion_prompt": ADULT_MOTION})
        assert saved.status_code == 200, saved.text
        on_disk = json.load(open(json_path))
        assert on_disk["scenes"][0]["image_prompt"] == ADULT_STILL

        scene = on_disk["scenes"][0]
        video = build_song.workflow(
            0, scene, "c.png", "song.mp3", "c", "w", "",
            video_model="ltx25", tier="r")
        # PINNED enumerates "children"; strip it so we only score scene text.
        vtext = guardrail.strip(_prompt_text(video)).lower()
        assert "child" not in vtext, vtext
        assert "7 year" not in vtext, vtext
        assert "niece" not in vtext, vtext
        assert "adult woman" in vtext, vtext
        still = build_refs.workflow(
            scene, "a.png", None, "empty", 1280, 720, 7000,
            "WIDE SHOT.", "", tier="r")
        stext = guardrail.strip(_prompt_text(still)).lower()
        assert "child" not in stext, stext
        assert "7 year" not in stext, stext
        assert "niece" not in stext, stext
        assert "adult woman" in stext, stext

        refused = client.post(
            f"/songs/{sid}/storyboard/r/scene/1",
            data={"image_prompt": NIECE_STILL})
        assert refused.status_code == 400, refused.text
        assert json.load(open(json_path))["scenes"][0]["image_prompt"] == ADULT_STILL
        with pytest.raises(guardrail.ContentRefused):
            build_song.workflow(
                0, dict(scene, video_motion_prompt=NIECE_MOTION),
                "c.png", "song.mp3", "c", "w", "",
                video_model="ltx25", tier="r")
