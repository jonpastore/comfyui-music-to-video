"""T2-14c: planner TIMING still states track length and sum-to-track.

docs/TRD-2 W1-4 / T2-14c: the composed prompt still states the track
length and still requires scene durations to sum to approximately it.
_user_prompt's docstring records why: without the duration it invents
scene times that do not add up to the track.

Mutation: delete the TIMING block wholesale → T2-14a passes and this fails.

Asserted on the return value of grok._user_prompt (the string sent).
"""
import re

from conftest import _real_module


def _grok():
    return _real_module("grok")


def _timing_block(text):
    match = re.search(r"TIMING.*?(?:\n\n|\Z)", text, re.S)
    assert match, text
    return match.group(0)


def test_t2_14c_timing_states_track_length_and_sum_to_track():
    grok = _grok()
    song = {"title": "T", "album": "A", "duration": 195.792, "genre": "pop"}
    text = grok._user_prompt("[Verse]\nwords", song, "pg13", 7)
    timing = _timing_block(text)

    assert re.search(r"track length", timing, re.I)
    assert "195.8" in timing
    assert "3:15" in timing
    assert re.search(r"add up to roughly\s+196", timing, re.I)
