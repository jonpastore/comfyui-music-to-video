"""T2-9: scene_seconds is monotonic.

docs/TRD-2 §3.4: for the same song, a larger scene_seconds never returns
more scenes. The old max(len(sections), ceil(duration / scene_seconds))
returned the section floor for every request below that floor, so a longer
quantum could not shrink the count.

grok.demo already asserts this; this is the pytest that can go red.

Mutation: restore max(len(sections), ...) in generate_storyboard → both
requests pin 5 scenes against a 2-scene and 1-scene fixture; validate
rejects and the retry loop raises RuntimeError.
Mutation: re-apply the one-per-section floor on the pinned validate path
→ same red path from the other end.
"""
import json

import httpx

from conftest import _real_module


DUR = 16.0
MANY = "[A]\na\n[B]\nb\n[C]\nc\n[D]\nd\n[E]\ne\n"
SONG = {"title": "T", "album": "A", "slug": "t", "duration": DUR, "genre": "pop"}


def _grok():
    return _real_module("grok")


def _scene(n, cam="wide", cue="Verse"):
    return {
        "scene_number": n, "name": f"{cue} {n}", "cue": cue,
        "duration_guidance": "4-8 sec", "story": f"story {n}",
        "camera": cam, "motion": "walk", "lighting": "neon",
        "location": f"loc {n}", "image_prompt": f"a rooftop {n}",
        "video_motion_prompt": f"m{n}", "negative_prompt": "blurry",
    }


def _generate(grok, scene_seconds, scenes):
    """Pinned generate; three identical fixture answers for the retry loop."""
    orig = httpx.stream
    orig_key = grok._api_key
    orig_ex = grok._exemplar
    body = json.dumps({"scenes": scenes})

    class _Resp:
        status_code = 200

        def iter_lines(self):
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
            MANY, "pg13", "TEST GUARD", "neon lock", SONG,
            model="grok-test", scene_seconds=scene_seconds)
    finally:
        httpx.stream = orig
        grok._api_key = orig_key
        grok._exemplar = orig_ex


def test_t2_9_larger_quantum_never_returns_more_scenes():
    grok = _grok()
    from build_storyboard import parse_sections

    assert len(parse_sections(MANY)) == 5, "fixture drifted"

    # 16s song: 8s/scene → 2, 16s/scene → 1. Both below the 5-section floor
    # that the old max() made unreachable.
    two = [_scene(1, "wide", "A"), _scene(2, "close", "B")]
    one = [_scene(1, "wide", "A")]

    sb_short = _generate(grok, 8.0, two)
    sb_long = _generate(grok, 16.0, one)

    assert len(sb_short["scenes"]) == 2, len(sb_short["scenes"])
    assert len(sb_long["scenes"]) == 1, len(sb_long["scenes"])
    assert len(sb_long["scenes"]) <= len(sb_short["scenes"]), (
        "scene_seconds is not monotonic: larger quantum returned more scenes"
    )


def test_t2_9_n_clips_for_is_monotonic():
    """Same property on the count formula itself (no network)."""
    from build_song import n_clips_for

    durations = (16.0, 41.0, 195.792)
    quanta = (4.0, 8.0, 15.0, 16.0, 30.0)
    for dur in durations:
        counts = [n_clips_for(dur, q) for q in quanta]
        for i in range(len(counts) - 1):
            assert counts[i + 1] <= counts[i], (
                f"dur={dur} quanta={quanta[i]}→{counts[i]} "
                f"then {quanta[i + 1]}→{counts[i + 1]}"
            )
