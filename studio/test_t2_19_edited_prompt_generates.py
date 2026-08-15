"""T2-19: editing the storyboard prompt and generating uses the edited text.

docs/TRD-2 §4.2: generate with two different prompts, confirm two different
storyboards — not that the field posts (that is T2-17).

Both arms use the SAME recorded model response. The tokens are not in that
fixture, so the only way each lands on its board is if generate_storyboard
carries the direction through (messages to the model AND the returned board).

Mutation: drop direction before messages / return → red.
Mutation: hardcode one direction for every generate → the other arm fails.
"""
import json

import httpx

from conftest import _real_module


TOKEN_A = "ZXQ-HEIST-4748-brass-vault"
TOKEN_B = "ZXQ-CLUB-5151-neon-floor"

SCENES = [
    {"scene_number": 1, "name": "Verse 1", "cue": "Verse",
     "duration_guidance": "4-8 sec", "story": "s1", "camera": "wide",
     "motion": "walk", "lighting": "neon", "location": "alley",
     "image_prompt": "a rooftop 1", "video_motion_prompt": "m1",
     "negative_prompt": "blurry"},
    {"scene_number": 2, "name": "Chorus 1", "cue": "Chorus",
     "duration_guidance": "4-8 sec", "story": "s2", "camera": "close",
     "motion": "walk", "lighting": "amber", "location": "roof",
     "image_prompt": "a rooftop 2", "video_motion_prompt": "m2",
     "negative_prompt": "blurry"},
]


def _grok():
    return _real_module("grok")


def _generate(grok, direction):
    """One generate against a fixed fixture; returns (board, request body)."""
    lyrics = "[A]\na\n[B]\nb\n"
    song = {"title": "T", "album": "A", "slug": "t", "duration": 16.0, "genre": "pop"}
    orig = httpx.stream
    orig_key = grok._api_key
    orig_ex = grok._exemplar
    sent = {}

    class _Resp:
        status_code = 200

        def iter_lines(self):
            body = json.dumps({"scenes": SCENES})
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
            model="grok-test", scene_seconds=8.0, direction=direction)
        return board, sent.get("json")
    finally:
        httpx.stream = orig
        grok._api_key = orig_key
        grok._exemplar = orig_ex


def test_t2_19_two_prompts_produce_two_different_storyboards():
    grok = _grok()
    fixture_blob = json.dumps(SCENES)
    assert TOKEN_A not in fixture_blob
    assert TOKEN_B not in fixture_blob

    board_a, req_a = _generate(grok, TOKEN_A)
    board_b, req_b = _generate(grok, TOKEN_B)

    blob_a = json.dumps(board_a)
    blob_b = json.dumps(board_b)
    assert TOKEN_A in blob_a, board_a
    assert TOKEN_B in blob_b, board_b
    assert TOKEN_A not in blob_b, board_b
    assert TOKEN_B not in blob_a, board_a
    assert board_a != board_b

    # The edit reaches the model, not only a field on the returned board.
    assert req_a is not None and req_b is not None
    msg_a = json.dumps(req_a.get("messages") or [])
    msg_b = json.dumps(req_b.get("messages") or [])
    assert TOKEN_A in msg_a, msg_a
    assert TOKEN_B in msg_b, msg_b
    assert TOKEN_A not in msg_b
    assert TOKEN_B not in msg_a
    assert msg_a != msg_b
