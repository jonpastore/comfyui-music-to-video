"""T2-8b: scenes tile the song.

docs/TRD-2 §3.4: start times ascend, each scene's end equals the next
scene's start, the first starts at 0 and the last ends at the song
duration ± tolerance. An overlap or a gap fails.

Mutation: drop the tiling check in validate → gap/overlap arms go green
(the board is accepted). Mutation: _compose does not stamp start/end →
the compose arm fails.
"""
import copy

import pytest

from conftest import _real_module


DUR = 195.792
N = 7


def _grok():
    return _real_module("grok")


def _scene(n, cam=None):
    cams = ("wide", "close", "medium", "low angle", "high angle",
            "over shoulder", "tracking")
    return {
        "scene_number": n, "name": f"S{n}", "cue": "Verse",
        "duration_guidance": "28-30 sec", "story": f"story {n}",
        "camera": cam or cams[(n - 1) % len(cams)],
        "motion": "walk", "lighting": "neon", "location": f"loc {n}",
        "image_prompt": f"a rooftop {n}", "video_motion_prompt": f"m{n}",
        "negative_prompt": "blurry",
    }


def _board(grok, scenes=None, duration=DUR, scene_seconds=30.0):
    scenes = scenes or [_scene(i) for i in range(1, N + 1)]
    song = {"title": "T", "album": "A", "slug": "t",
            "duration": duration, "genre": "pop"}
    return grok._compose(
        song, "pg13", "g", "note", "[Verse]\nwords",
        scenes, len(scenes), scene_seconds)


def _spans(sb):
    return [(float(s["start"]), float(s["end"])) for s in sb["scenes"]]


def test_t2_8b_compose_tiles_the_song():
    grok = _grok()
    sb = _board(grok)
    spans = _spans(sb)
    assert spans[0][0] == 0.0
    for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
        assert a0 < b0
        assert a1 == b0
    assert spans[-1][1] == pytest.approx(DUR, abs=grok.TILE_TOLERANCE_S)
    assert sb["duration"] == pytest.approx(DUR)
    assert grok.validate(sb, exemplar={}, expect_scenes=N) is None


def test_t2_8b_gap_fails_validate():
    grok = _grok()
    sb = _board(grok)
    grok.validate(sb, exemplar={}, expect_scenes=N)
    broken = copy.deepcopy(sb)
    broken["scenes"][3]["start"] = broken["scenes"][2]["end"] + 1.5
    with pytest.raises(ValueError, match="gap"):
        grok.validate(broken, exemplar={}, expect_scenes=N)


def test_t2_8b_overlap_fails_validate():
    grok = _grok()
    sb = _board(grok)
    broken = copy.deepcopy(sb)
    broken["scenes"][3]["start"] = broken["scenes"][2]["end"] - 1.5
    with pytest.raises(ValueError, match="overlap"):
        grok.validate(broken, exemplar={}, expect_scenes=N)


def test_t2_8b_starts_must_ascend():
    grok = _grok()
    sb = _board(grok)
    broken = copy.deepcopy(sb)
    broken["scenes"][0]["start"] = 10.0
    broken["scenes"][0]["end"] = 40.0
    broken["scenes"][1]["start"] = 5.0
    broken["scenes"][1]["end"] = 50.0
    with pytest.raises(ValueError, match="ascend"):
        grok.validate(broken, exemplar={}, expect_scenes=N)


def test_t2_8b_first_must_start_at_zero():
    grok = _grok()
    sb = _board(grok)
    broken = copy.deepcopy(sb)
    shift = 2.0
    for s in broken["scenes"]:
        s["start"] += shift
        s["end"] += shift
    with pytest.raises(ValueError, match="gap"):
        grok.validate(broken, exemplar={}, expect_scenes=N)


def test_t2_8b_last_must_end_at_duration():
    grok = _grok()
    sb = _board(grok)
    short = copy.deepcopy(sb)
    short["scenes"][-1]["end"] = DUR - 2.0
    with pytest.raises(ValueError, match="gap"):
        grok.validate(short, exemplar={}, expect_scenes=N)
    long = copy.deepcopy(sb)
    long["scenes"][-1]["end"] = DUR + 2.0
    with pytest.raises(ValueError, match="overlap"):
        grok.validate(long, exemplar={}, expect_scenes=N)
