"""T2-49: generate is offered album leads without a chosen front.

Album characters (Tiger, Panther) are consistency leads. A missing
identity front blocks Generate refs (T2-28), not the writer. Extras
and background may be named without a row, pose, or anchor.

Mutation: h_storyboard still filters through cast_anchors → a character
with no front never reaches generate.
Mutation: empty _cast_block still says none may be named → extras arm red.
Mutation: classify keeps an invented lead → coerce arm red.
"""
import json
import os
import time

import httpx
from fastapi.testclient import TestClient

import app as appmod
import db
from conftest import _real_module, grok_calls
from test_app import _upload_song


def _grok():
    return _real_module("grok")


def _ensure_album(client, album):
    pl = db.one("SELECT * FROM playlists WHERE name=?", album)
    if pl:
        return pl
    r = client.post("/playlists", data={"name": album})
    assert r.status_code in (200, 303), r.text
    pl = db.one("SELECT * FROM playlists WHERE name=?", album)
    assert pl, album
    return pl


def _add_character(client, album, name, role="partner", identity=""):
    pl = _ensure_album(client, album)
    r = client.post(f"/playlists/{pl['id']}/characters",
                    data={"name": name, "role": role, "identity": identity})
    assert r.status_code in (200, 303), r.text
    return db.one("SELECT * FROM characters WHERE scope_value=? AND name=?",
                  album, name)


def test_t2_49_cast_block_offers_extras_when_album_has_no_leads():
    grok = _grok()
    text = grok._cast_block(())
    low = text.lower()
    assert "extras and background" in low, text
    assert "do not invent a second lead" in low, text
    assert "none may be named" not in low, text
    assert "characters\" key of []" not in text, text


def test_t2_49_cast_block_names_album_members_as_leads():
    grok = _grok()
    text = grok._cast_block([
        ("Tiger", "partner orange-furred tigress"),
        ("Panther", "partner black-furred panther"),
    ])
    assert "Tiger" in text and "Panther" in text, text
    assert "LEADS" in text, text
    assert "extras and background" in text.lower(), text
    assert "Do not invent a new lead" in text, text


def test_t2_49_classify_keeps_album_leads_and_demotes_invented_leads():
    grok = _grok()
    figs = grok.classify_offered_figures(
        [
            {"name": "Tiger", "role": "extra"},
            {"name": "Shirtless man", "role": "lead"},
            {"name": "Crowd", "role": "background"},
            "Ghost",
        ],
        ["Tiger", "Panther"],
    )
    by_name = {f["name"]: f["role"] for f in figs}
    assert by_name == {
        "Tiger": "lead",
        "Shirtless man": "extra",
        "Crowd": "background",
        "Ghost": "extra",
    }, figs


def test_t2_49_generate_offers_album_cast_without_a_chosen_front():
    """The defect: Street Cats Tiger/Panther had identity text and no front."""
    grok_calls.clear()
    with TestClient(appmod.app) as client:
        album = "T249 Cast Album"
        _add_character(client, album, "Tiger", "partner",
                       "orange-furred tigress, striped")
        _add_character(client, album, "Panther", "partner",
                       "black-furred panther-woman")
        song = _upload_song(client, "T249 Offer Song", album=album)
        # No chosen front for either character. cast_anchors would skip both.
        assert not appmod.cast_anchors(album, "xxx")
        offered = appmod.offered_cast(album)
        names = [n for n, _ in offered]
        assert names == ["Panther", "Tiger"], offered

        appmod.h_storyboard(
            {"song_id": song["id"], "tier": "xxx"}, lambda m: None)
        args = grok_calls.get("args") or {}
        got = [n for n, _ in (args.get("cast") or [])]
        assert got == ["Panther", "Tiger"], args


def test_t2_49_form_and_payload_list_album_leads():
    with TestClient(appmod.app) as client:
        album = "T249 Form Album"
        _add_character(client, album, "Tiger", "partner", "orange-furred tigress")
        song = _upload_song(client, "T249 Form Song", album=album)
        html = client.get(f"/songs/{song['id']}/storyboard-form",
                          params={"tier": "xxx"})
        assert html.status_code == 200, html.text
        assert "Tiger" in html.text, html.text
        assert "Album leads" in html.text, html.text
        assert "no identity front at this tier" in html.text, html.text
        assert "extras and background" in html.text.lower(), html.text

        payload = appmod.storyboard_generation_payload(song, "xxx")
        names = [c["name"] for c in payload["album_leads"]]
        assert names == ["Tiger"], payload
        assert payload["album_leads"][0]["has_front"] is False


def test_t2_49_generate_applies_offered_cast_and_names_them_in_the_prompt():
    """Recorded response with an invented lead and an album name as extra."""
    grok = _grok()
    scenes = [{
        "scene_number": 1, "name": "Verse 1", "cue": "Verse",
        "duration_guidance": "4-8 sec", "story": "duet", "camera": "wide",
        "motion": "walk", "lighting": "neon", "location": "alley",
        "image_prompt": "a rooftop 1", "video_motion_prompt": "m1",
        "negative_prompt": "blurry",
        "characters": [
            {"name": "Tiger", "role": "extra"},
            {"name": "Shirtless man", "role": "lead"},
            {"name": "Crowd", "role": "background"},
        ],
    }, {
        "scene_number": 2, "name": "Chorus 1", "cue": "Chorus",
        "duration_guidance": "4-8 sec", "story": "alone", "camera": "close",
        "motion": "walk", "lighting": "amber", "location": "roof",
        "image_prompt": "a rooftop 2", "video_motion_prompt": "m2",
        "negative_prompt": "blurry", "characters": [],
    }]
    lyrics = "[A]\na\n[B]\nb\n"
    song = {"title": "T", "album": "A", "slug": "t", "duration": 16.0, "genre": "pop"}
    orig = httpx.stream
    orig_key = grok._api_key
    orig_ex = grok._exemplar
    sent = {}

    class _Resp:
        status_code = 200

        def iter_lines(self):
            body = json.dumps({"scenes": scenes, "character_reference": "a sleek black feline DJ"})
            yield "data: " + json.dumps({"choices": [{"delta": {"content": body}}]})
            yield "data: [DONE]"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _stream(*a, **k):
        sent["json"] = k.get("json")
        return _Resp()

    grok._api_key = lambda: "test-key"
    grok._exemplar = lambda: ({"scenes": []}, "", False)
    httpx.stream = _stream
    try:
        board = grok.generate_storyboard(
            lyrics, "pg13", "TEST GUARD", "neon lock", song,
            model="grok-test", scene_seconds=8.0,
            cast=[("Tiger", "partner orange-furred tigress")])
    finally:
        httpx.stream = orig
        grok._api_key = orig_key
        grok._exemplar = orig_ex

    by_name = {f["name"]: f["role"] for f in board["scenes"][0]["characters"]}
    assert by_name == {
        "Tiger": "lead",
        "Shirtless man": "extra",
        "Crowd": "background",
    }, board["scenes"][0]["characters"]
    assert board["album_leads"] == ["Tiger"], board
    messages = json.dumps((sent.get("json") or {}).get("messages") or [])
    assert "Tiger" in messages, messages
    assert "LEADS" in messages, messages
    assert "Shirtless man" not in messages


def test_t2_49_board_marks_unused_album_leads():
    with TestClient(appmod.app) as client:
        album = "T249 Unused Album"
        _add_character(client, album, "Panther", "partner", "black-furred panther")
        song = _upload_song(client, "T249 Unused Song", album=album)
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        sb = {
            "title": "T", "album": album, "version": "xxx",
            "character_reference": "a sleek black feline DJ",
            "album_world_reference": "neon warehouse",
            "audio_lyrics": "[Verse]\nline\n",
            "scenes": [{
                "scene_number": 1, "name": "Alone", "cue": "Verse",
                "duration_guidance": "5-7 sec", "story": "she walks",
                "camera": "wide establishing", "motion": "walk",
                "lighting": "neon", "location": "alley",
                "image_prompt": "a rooftop at night, scene 1",
                "video_motion_prompt": "walk", "negative_prompt": "",
                "characters": [],
            }],
        }
        json_path = os.path.join(outdir, f"{song['slug']}_xxx.json")
        json.dump(sb, open(json_path, "w"))
        db.run(
            """INSERT INTO storyboards (song_id, tier, json_path, md_path,
                                        scene_count, created)
               VALUES (?,?,?,?,?,?)""",
            song["id"], "xxx", json_path, json_path + ".md", 1, time.time())
        open(json_path + ".md", "w").write("# sb\n")

        page = client.get(f"/songs/{song['id']}/storyboard/xxx")
        assert page.status_code == 200, page.text
        assert "Panther" in page.text
        assert "not named on this board" in page.text

        api = client.get(f"/api/songs/{song['id']}/storyboard/xxx/cast")
        assert api.status_code == 200, api.text
        leads = api.json().get("album_leads") or []
        assert [c["name"] for c in leads] == ["Panther"], leads
        assert leads[0]["used"] is False
        assert leads[0]["has_front"] is False
