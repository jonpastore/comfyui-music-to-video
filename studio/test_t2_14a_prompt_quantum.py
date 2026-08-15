"""T2-14a: planner user prompt has no fixed clip quantum.

docs/TRD-2 W1-4 / T2-14a: for a song planned with variable clip lengths
the composed prompt contains no fixed clip quantum — not the CHUNK value
in any formatting, not "Nothing shorter or longer can be produced", and
no instruction to round duration_guidance to multiples of a constant.

Asserted on the return value of grok._user_prompt (the string sent).

Mutation: restore any one of the three sentences → this fails.
"""
import re

import build_song
from conftest import _real_module


def _grok():
    return _real_module("grok")


def test_t2_14a_user_prompt_has_no_fixed_clip_quantum():
    grok = _grok()
    song = {"title": "T", "album": "A", "duration": 195.792, "genre": "pop"}
    text = grok._user_prompt("[Verse]\nwords", song, "pg13", 7)

    chunk = build_song.CHUNK
    for form in (f"{chunk:.4f}", f"{chunk:.2f}", f"{chunk:.1f}", f"{chunk:g}", str(chunk)):
        assert form not in text, form
    assert "4.8125" not in text
    assert "Nothing shorter or longer can be produced" not in text
    assert not re.search(
        r"duration_guidance[\s\S]{0,160}multiple", text, re.IGNORECASE)
    assert "multiple of" not in text.lower()


def test_t2_14a_system_prompt_has_no_fixed_clip_quantum():
    """Planner system prompt also must not name the old 4.8125 s quantum."""
    grok = _grok()
    for scene_seconds in (None, 30.0):
        text = grok._system_prompt("tier", "style", 7, scene_seconds)
        assert "4.8125" not in text
        assert "Nothing shorter or longer can be produced" not in text
