"""refs-length: build_refs / reroll_refs honour clip_seconds via n_clips_for.

docs/TRD-2 T2-13 / §3.4: clip count has one implementation — n_clips_for.
clip_plan is THE allocator shared by build_refs.py, reroll_refs.py and
build_song.py. Its default when only audio is known must be
n_clips_for(track, scene quantum), not ceil(track / CHUNK).

Defect: default nclips = ceil(track / CHUNK) forced a 30 s-quantum board on
a ~196 s track into 41 ref slots instead of n_clips_for(..., 30) == 7.

Mutation: restore math.ceil(track / CHUNK) in clip_plan → 195.792 s / 30 s
board yields 41 and this fails.
Mutation: ignore scene length_seconds and always pass None → same red.
"""
import inspect
import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import build_song


SCENE = {
    "name": "s", "camera": "wide", "lighting": "neon",
    "video_motion_prompt": "she walks", "negative_prompt": "",
    "duration_guidance": "5 sec", "image_prompt": "a rooftop",
}


def test_clip_plan_default_honours_n_clips_for_not_chunk(monkeypatch):
    track = 195.792
    monkeypatch.setattr(build_song, "audio_duration", lambda p: track)
    scenes = [
        dict(SCENE, scene_number=i, length_seconds=30.0)
        for i in range(1, 8)
    ]
    plan = build_song.clip_plan(scenes, audio_path="dummy.mp3")
    want = build_song.n_clips_for(track, 30.0)
    assert want == 7
    assert want != math.ceil(track / build_song.CHUNK)
    assert len(plan) == want
    assert [ci for ci, _, _ in plan] == list(range(want))


def test_clip_plan_default_none_length_stays_chunk(monkeypatch):
    """Pre-T2-12a boards have no length_seconds; keep CHUNK timing."""
    track = 195.792
    monkeypatch.setattr(build_song, "audio_duration", lambda p: track)
    scenes = [dict(SCENE, scene_number=1)]
    plan = build_song.clip_plan(scenes, audio_path="dummy.mp3")
    assert len(plan) == build_song.n_clips_for(track)
    assert len(plan) == math.ceil(track / build_song.CHUNK)


def test_clip_plan_default_uses_n_clips_for_source():
    """clip_plan must not re-derive ceil(track / CHUNK)."""
    src = inspect.getsource(build_song.clip_plan)
    assert "ceil(track / CHUNK)" not in src
    assert "n_clips_for" in src


def test_build_refs_and_reroll_call_clip_plan_not_chunk_count():
    """build_refs / reroll_refs share clip_plan; they do not ceil / CHUNK."""
    import re
    forbidden = re.compile(r"ceil\s*\([^)\n]*CHUNK")
    for name in ("build_refs.py", "reroll_refs.py"):
        path = os.path.join(ROOT, name)
        text = open(path, encoding="utf-8").read()
        assert "clip_plan" in text, name
        assert not forbidden.search(text), name
