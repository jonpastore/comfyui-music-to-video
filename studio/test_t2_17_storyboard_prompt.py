"""T2-17: storyboard generation prompt is API-visible, defaulted from the tier.

docs/TRD-2 §4.2: GET /api/songs/{id}/storyboard/{tier} returns the generation
prompt, defaulted from the tier, editable before generating.

The half that the edit REACHES the model is T2-19. This file asserts the
prompt is returned, that two tiers default two different strings, that a
stored edit is what GET returns, and that POST accepts a replacement
prompt. Mutation: hardcode one prompt for every tier → red.
"""
import json

from fastapi.testclient import TestClient

import app as appmod
import db
from test_app import _upload_song


def test_t2_17_payload_defaults_from_the_tier():
    """Service function, no HTTP: g and r cannot share one hardcoded string."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T2-17 Payload Song", album="T2-17 Album")
    g = appmod.storyboard_generation_payload(song, "g")
    r = appmod.storyboard_generation_payload(song, "r")
    assert g["prompt"], "g-tier prompt was empty"
    assert r["prompt"], "r-tier prompt was empty"
    assert g["prompt"] != r["prompt"]
    assert "Tone and wardrobe (g tier)" in g["prompt"]
    assert "General-audience music-video tone" in g["prompt"]
    assert "Tone and wardrobe (r tier)" in r["prompt"]
    assert "Mature after-hours nightlife tone" in r["prompt"]
    assert "Mainstream music-video tone" not in r["prompt"]


def test_t2_17_api_returns_the_tier_defaulted_prompt():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T2-17 API Song", album="T2-17 Album")
        sid = song["id"]
        g = client.get(f"/api/songs/{sid}/storyboard/g")
        r = client.get(f"/api/songs/{sid}/storyboard/r")
        assert g.status_code == 200, g.text
        assert r.status_code == 200, r.text
        assert (g.headers.get("content-type") or "").split(";")[0] == "application/json"
        gp, rp = g.json()["prompt"], r.json()["prompt"]
        assert gp != rp
        assert "Tone and wardrobe (g tier)" in gp
        assert "Tone and wardrobe (r tier)" in rp
        assert "Mature after-hours nightlife tone" in rp


def test_t2_17_html_form_and_json_show_the_same_prompt():
    """One defaulting function; a second string in the API is the defect."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T2-17 Same Prompt Song")
        sid = song["id"]
        html = client.get(f"/songs/{sid}/storyboard-form", params={"tier": "r"})
        js = client.get(f"/api/songs/{sid}/storyboard/r")
        assert html.status_code == 200, html.text
        assert js.status_code == 200, js.text
        prompt = js.json()["prompt"]
        assert prompt
        assert prompt == appmod.storyboard_form_ctx(song, "r")["direction"]
        assert "Tone and wardrobe (r tier)" in html.text
        assert "Mature after-hours nightlife tone" in html.text


def test_t2_17_stored_edit_is_what_get_returns():
    """After a generate stores a prompt, GET returns that text, not the default."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T2-17 Stored Song")
        sid = song["id"]
        before = client.get(f"/api/songs/{sid}/storyboard/r")
        assert before.status_code == 200, before.text
        default = before.json()["prompt"]
        assert default
        assert "A heist, not a club night." not in default

        db.run(
            """INSERT INTO storyboards (song_id, tier, json_path, md_path,
                                        scene_count, created, prompt)
               VALUES (?,?,?,?,?,?,?)""",
            sid, "r", "/tmp/t2-17.json", "/tmp/t2-17.md", 0, 0,
            "A heist, not a club night.")

        after = client.get(f"/api/songs/{sid}/storyboard/r")
        assert after.status_code == 200, after.text
        assert after.json()["prompt"] == "A heist, not a club night."
        assert after.json()["prompt"] != default


def test_t2_17_post_accepts_an_edited_prompt():
    """Editable: the replacement prompt is what the generate job is handed."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T2-17 Edit Song")
        sid = song["id"]
        r = client.post(f"/api/songs/{sid}/storyboard/r",
                        json={"prompt": "A heist, not a club night."})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["prompt"] == "A heist, not a club night."
        job = db.one(
            "SELECT * FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC",
            sid)
        assert job is not None, "edit was not enqueued"
        assert json.loads(job["args_json"])["direction"] == "A heist, not a club night."


def test_t2_17_missing_song_is_404():
    with TestClient(appmod.app) as client:
        r = client.get("/api/songs/999999/storyboard/r")
        assert r.status_code == 404
