"""T2-14b: planner clip-length text is derived from planning.

docs/TRD-2 W1-4 / T2-14b: compose for one song at two scene_seconds
and the TIMING blocks differ in their clip-length statement.

Mutation: swap 4.8125 for 15.0 and keep the sentence shape → T2-14a
passes and this fails, which is why it is separate.

Asserted on the return value of grok._user_prompt (the string sent).
"""
import re

import build_song
from conftest import _real_module


def _grok():
    return _real_module("grok")


def _timing_block(text):
    match = re.search(r"TIMING.*?(?:\n\n|\Z)", text, re.S)
    assert match, text
    return match.group(0)


def _clip_length_statement(text):
    """The TIMING line that states clip length, not track length or clip count."""
    lines = [
        line for line in _timing_block(text).splitlines()
        if re.search(r"clip length", line, re.I)
    ]
    assert lines, _timing_block(text)
    return "\n".join(lines)


def test_t2_14b_clip_length_text_is_derived_from_planning():
    grok = _grok()
    song = {"title": "T", "album": "A", "duration": 195.792, "genre": "pop"}
    lyrics = "[Verse]\nwords"
    statements = []
    for scene_seconds in (15.0, 30.0):
        n_scenes = build_song.n_clips_for(song["duration"], scene_seconds)
        text = grok._user_prompt(
            lyrics, song, "pg13", n_scenes, scene_seconds=scene_seconds)
        stmt = _clip_length_statement(text)
        want = build_song.clip_seconds(scene_seconds)
        assert any(
            form in stmt
            for form in (f"{want:.4f}", f"{want:.2f}", f"{want:g}", f"{want:.1f}")
        ), (stmt, want)
        statements.append(stmt)
    assert statements[0] != statements[1]
    assert build_song.clip_seconds(15.0) != build_song.clip_seconds(30.0)
