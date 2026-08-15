"""T2-21: at xxx, no scene carries the mainstream clause.

docs/TRD-2 §4.4: no scene image_prompt or video_motion_prompt contains
"fully clothed, tasteful and non-graphic" or "no explicit gesture", and
the xxx tier's own wording does appear.

The existing direction test only checks the guardrail *sent* to grok.
This one reads the composed scene text. rear-entrance_xxx.json is the
named failing fixture: every scene carries the mainstream lock.

Same recorded model response both arms. The clause is in the fixture,
so the only way it leaves the scenes is if _compose strips it. The
permission sentence is not in the fixture, so the only way it lands
in scene text is if _compose writes it.

Mutation: _compose leaves scene prompts untouched → red.
Mutation: strip the lock and do not stamp the xxx wording → red.
"""
import json
import os

import httpx

import tiers
from conftest import _real_module


FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "rear-entrance_xxx.json")

MAINSTREAM = (
    "fully clothed, tasteful and non-graphic",
    "no explicit gesture",
)


def _grok():
    return _real_module("grok")


def _scenes():
    return json.load(open(FIXTURE))["scenes"]


def _generate(grok, scenes):
    lyrics = "[A]\na\n[B]\nb\n"
    song = {"title": "Rear Entrance", "album": "Street Cats",
            "slug": "rear-entrance", "duration": 16.0, "genre": "pop"}
    orig = httpx.stream
    orig_key = grok._api_key
    orig_ex = grok._exemplar

    class _Resp:
        status_code = 200

        def iter_lines(self):
            body = json.dumps({"scenes": scenes})
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
            lyrics, "xxx", "NOT-THE-CLAUSE", "neon lock", song,
            model="grok-test", scene_seconds=8.0)
    finally:
        httpx.stream = orig
        grok._api_key = orig_key
        grok._exemplar = orig_ex


def test_t2_21_xxx_scene_prompts_drop_mainstream_and_carry_own_wording():
    tiers.ensure_builtins()
    grok = _grok()
    scenes = _scenes()
    own = "Explicit adult content is permitted"
    assert own in (tiers.tier_text("xxx") or "")

    fixture_blob = json.dumps(scenes)
    for phrase in MAINSTREAM:
        assert phrase in fixture_blob, phrase
    assert own not in fixture_blob

    board = _generate(grok, scenes)
    scene_blob = " ".join(
        (s.get("image_prompt") or "") + " " + (s.get("video_motion_prompt") or "")
        for s in board["scenes"])

    for s in board["scenes"]:
        for field in ("image_prompt", "video_motion_prompt"):
            text = s.get(field) or ""
            for phrase in MAINSTREAM:
                assert phrase not in text, (s.get("scene_number"), field, text)

    assert own in scene_blob, scene_blob
