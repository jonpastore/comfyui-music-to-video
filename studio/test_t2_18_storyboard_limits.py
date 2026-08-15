"""T2-18: limits and guardrails travel with the generation prompt.

docs/TRD-2 §4.2: GET /api/songs/{id}/storyboard/{tier} returns the same
limits that are enforced — the tier's pinned clause, the character bound,
and that PINNED is added at use time and cannot be edited out.

Positive half (pairing table): the returned max_characters is the one
enforced. Submit text one character over it; the 400 quotes that number.
Mutation: return a hard-coded cap the server does not enforce → red.
Mutation: enforce a different number than the payload → red.
"""
from fastapi.testclient import TestClient

import app as appmod
import tiers
from test_app import _upload_song


def test_t2_18_payload_carries_the_limits_and_pinned():
    """Limits/guardrails are part of the same response as the prompt."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T2-18 Payload Song", album="T2-18 Album")
    body = appmod.storyboard_generation_payload(song, "r")
    assert body["prompt"], "prompt was empty"
    assert body["max_characters"] == appmod.grok.MAX_DIRECTION
    assert body["max_characters"] > 0
    assert body["pinned"] == tiers.PINNED.strip()
    assert "No minors" in body["pinned"] or "at least 21" in body["pinned"]
    assert body["pinned_added_at_use"] is True
    assert body["pinned_editable"] is False
    assert body["tier_text"], "tier tone wording was empty"


def test_t2_18_api_returns_the_enforced_character_cap():
    """GET returns max_characters; one character over is 400 quoting it."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T2-18 Cap Song", album="T2-18 Album")
        sid = song["id"]
        r = client.get(f"/api/songs/{sid}/storyboard/r")
        assert r.status_code == 200, r.text
        assert (r.headers.get("content-type") or "").split(";")[0] == "application/json"
        body = r.json()
        assert "prompt" in body
        cap = body["max_characters"]
        assert isinstance(cap, int) and cap > 0
        assert body["pinned"] == tiers.PINNED.strip()
        assert body["pinned_added_at_use"] is True
        assert body["pinned_editable"] is False

        over = client.post(
            f"/api/songs/{sid}/storyboard/r",
            json={"prompt": "x" * (cap + 1)},
        )
        assert over.status_code == 400, over.text
        assert str(cap) in over.text, (
            f"refusal must quote the returned cap {cap}; got {over.text!r}")
        assert str(cap + 1) in over.text, (
            f"refusal must name the submitted length {cap + 1}; got {over.text!r}")

        ok = client.post(
            f"/api/songs/{sid}/storyboard/r",
            json={"prompt": "x" * cap},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["prompt"] == "x" * cap


def test_t2_18_returned_cap_matches_check_direction():
    """Payload cap and check_direction refuse on the same number."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T2-18 Match Song")
    cap = appmod.storyboard_generation_payload(song, "g")["max_characters"]
    try:
        appmod.check_direction("y" * (cap + 1))
    except Exception as e:
        assert getattr(e, "status_code", None) == 400
        assert str(cap) in str(e.detail)
    else:
        raise AssertionError(
            f"check_direction accepted {cap + 1} characters; cap is {cap}")
    assert appmod.check_direction("y" * cap) == "y" * cap
