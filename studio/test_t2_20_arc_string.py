"""T2-20: a distinctive arc string appears in the generated storyboard.

docs/TRD-2 §4.3: a distinctive string from the arc appears in the generated
board, and does NOT appear when the arc is absent. "Differs" cannot fail —
two generations (or two fixtures) always differ, so this takes T2-21's
shape: specific arc content is present, and absent when the arc is.

Both arms use the SAME recorded model response. The token is not in that
fixture, so the only way it lands on the board is if generate_storyboard
carries the arc through.

Mutation: generate_storyboard drops arc_ctx before _compose → red.
Mutation: always stamp the token → the absent-arc arm fails.
"""
import json

import httpx

from conftest import _real_module


TOKEN = "ZXQ-ARC-4748-brass-collar"

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


def _generate(grok, arc_ctx):
    lyrics = "[A]\na\n[B]\nb\n"
    song = {"title": "T", "album": "A", "slug": "t", "duration": 16.0, "genre": "pop"}
    orig = httpx.stream
    orig_key = grok._api_key
    orig_ex = grok._exemplar

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

    grok._api_key = lambda: "test-key"
    grok._exemplar = lambda: ({"scenes": []}, "", False)
    httpx.stream = lambda *a, **k: _Resp()
    try:
        return grok.generate_storyboard(
            lyrics, "pg13", "TEST GUARD", "neon lock", song,
            model="grok-test", scene_seconds=8.0, arc_ctx=arc_ctx)
    finally:
        httpx.stream = orig
        grok._api_key = orig_key
        grok._exemplar = orig_ex


def test_t2_20_distinctive_arc_string_present_only_when_arc_is():
    grok = _grok()
    assert TOKEN not in json.dumps(SCENES)

    with_arc = _generate(grok, {
        "premise": "A cat crosses a city.",
        "role": "the door closing",
        "beat": TOKEN,
        "opens": "a shut door",
        "closes": "headlights",
        "continuity": ["the collar is always brass"],
    })
    without = _generate(grok, None)

    assert TOKEN in json.dumps(with_arc), with_arc
    assert TOKEN not in json.dumps(without), without
