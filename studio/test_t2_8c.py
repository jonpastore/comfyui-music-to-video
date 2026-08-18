"""T2-8c: every scene names the lyric sections it spans.

docs/TRD-2 §3.4: every section is named by exactly one scene. This is
the coverage guarantee the deleted one-per-section floor provided,
asserted on the names instead of a count.

Mutation: drop the coverage check in validate → unnamed / double-named
arms go green. Mutation: _compose does not stamp lyric_sections → the
compose arm fails.
"""
import copy
from collections import Counter

import pytest

from conftest import _real_module
from build_storyboard import parse_sections


DUR = 195.792
N = 7
N_SECTIONS = 25


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


def _lyrics(n=N_SECTIONS):
    return "\n".join(f"[Sec{i}]\nline {i}" for i in range(1, n + 1))


def _board(grok, lyrics=None, n_scenes=N, duration=DUR, scene_seconds=30.0):
    lyrics = lyrics if lyrics is not None else _lyrics()
    scenes = [_scene(i) for i in range(1, n_scenes + 1)]
    song = {"title": "T", "album": "A", "slug": "t",
            "duration": duration, "genre": "pop"}
    return grok._compose(
        song, "pg13", "g", "note", lyrics,
        scenes, n_scenes, scene_seconds)


def _expected_tags(lyrics):
    return [s["tag"] for s in parse_sections(lyrics)]


def test_t2_8c_compose_names_every_section_once():
    grok = _grok()
    lyrics = _lyrics()
    sb = _board(grok, lyrics=lyrics)
    expected = _expected_tags(lyrics)
    assert len(expected) == N_SECTIONS
    named = []
    for s in sb["scenes"]:
        names = s["lyric_sections"]
        assert isinstance(names, list)
        named.extend(names)
    assert named == expected
    assert grok.validate(sb, exemplar={}, expect_scenes=N) is None


def test_t2_8c_a_four_section_scene_lists_all_four():
    grok = _grok()
    sb = _board(grok)
    four = [s for s in sb["scenes"] if len(s["lyric_sections"]) == 4]
    assert four, sb["scenes"]
    for s in four:
        assert len(s["lyric_sections"]) == 4
        assert len(set(s["lyric_sections"])) == 4


def test_t2_8c_unnamed_section_fails_validate():
    grok = _grok()
    sb = _board(grok)
    grok.validate(sb, exemplar={}, expect_scenes=N)
    broken = copy.deepcopy(sb)
    taken = broken["scenes"][0]["lyric_sections"].pop()
    assert taken
    with pytest.raises(ValueError, match="not named"):
        grok.validate(broken, exemplar={}, expect_scenes=N)


def test_t2_8c_double_named_section_fails_validate():
    grok = _grok()
    sb = _board(grok)
    broken = copy.deepcopy(sb)
    stolen = broken["scenes"][0]["lyric_sections"][0]
    broken["scenes"][1]["lyric_sections"].append(stolen)
    with pytest.raises(ValueError, match="more than one scene"):
        grok.validate(broken, exemplar={}, expect_scenes=N)


def test_t2_8c_missing_field_fails_validate():
    grok = _grok()
    sb = _board(grok)
    broken = copy.deepcopy(sb)
    del broken["scenes"][2]["lyric_sections"]
    with pytest.raises(ValueError, match="missing lyric_sections"):
        grok.validate(broken, exemplar={}, expect_scenes=N)


def test_t2_8c_repeated_tags_stay_distinct():
    grok = _grok()
    lyrics = "[Verse]\none\n[Chorus]\ntwo\n[Verse]\nthree\n"
    sb = _board(grok, lyrics=lyrics, n_scenes=2, duration=16.0, scene_seconds=8.0)
    named = [tag for s in sb["scenes"] for tag in s["lyric_sections"]]
    assert Counter(named) == Counter(["Verse", "Chorus", "Verse"])
    assert grok.validate(sb, exemplar={}, expect_scenes=2) is None
    broken = copy.deepcopy(sb)
    for s in broken["scenes"]:
        s["lyric_sections"] = [t for t in s["lyric_sections"] if t != "Verse"]
    with pytest.raises(ValueError, match="not named"):
        grok.validate(broken, exemplar={}, expect_scenes=2)


def test_compose_fills_empty_video_motion_from_motion_and_camera():
    grok = _grok()
    raw = [_scene(1)]
    raw[0]["video_motion_prompt"] = ""
    raw[0]["motion"] = "walks"
    raw[0]["camera"] = "wide"
    sb = grok._compose(
        {"title": "T", "album": "A", "duration": 10},
        "r", "g", "note", "[Verse]\na", raw, 1, 5.0)
    got = sb["scenes"][0]["video_motion_prompt"]
    assert "walks" in got
    assert "wide" in got
