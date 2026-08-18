"""T2-13e: refuse a clip plan that misses the track by more than one clip.

docs/TRD-2 W1-6 / T2-13e: a plan whose clip durations miss the track
length by more than one clip is refused before render, not absorbed by
assemble_song's -t audio_dur clamp. The clamp stays; an overrun is a
signal, not the norm.

Asserted through build_song.clip_plan (THE allocator) and build_song.main
(the writer pipeline.gen_clips shells out to). nclips-only callers have
no track and are display, not render.

Mutation: clip_plan allocates and returns → this fails.
Mutation: main() writes clip jsons then continues → this fails.
Mutation: restore assemble_song's "quantised to 4.8125s so the video
always overruns" comment → the comment arm fails.
"""
import inspect
import json
import sys

import pytest

import build_song
from conftest import _real_module


SCENE = {
    "name": "s", "camera": "wide", "lighting": "neon",
    "video_motion_prompt": "she walks", "negative_prompt": "",
    "duration_guidance": "5 sec", "image_prompt": "a rooftop",
}


def test_t2_13e_refuses_plan_that_misses_track_by_more_than_one_clip(monkeypatch):
    monkeypatch.setattr(build_song, "audio_duration", lambda p: 20.0)
    scenes = [dict(SCENE, scene_number=1)]
    # 1 * CHUNK = 4.8125s vs 20s track: miss 15.2s > one clip
    with pytest.raises(ValueError, match=r"miss"):
        build_song.clip_plan(scenes, audio_path="dummy.mp3", nclips=1)


def test_t2_13e_accepts_plan_within_one_clip(monkeypatch):
    monkeypatch.setattr(build_song, "audio_duration", lambda p: 20.0)
    scenes = [dict(SCENE, scene_number=1)]
    # 5 * CHUNK = 24.0625s, miss 4.0625s < 4.8125s
    plan = build_song.clip_plan(scenes, audio_path="dummy.mp3", nclips=5)
    assert [ci for ci, _, _ in plan] == list(range(5))
    # default nclips is n_clips_for(track) (CHUNK when no length_seconds)
    default = build_song.clip_plan(scenes, audio_path="dummy.mp3")
    assert [ci for ci, _, _ in default] == list(range(5))


def test_t2_13e_miss_of_exactly_one_clip_is_accepted(monkeypatch):
    """'More than one clip' is a strict greater-than."""
    quantum = build_song.CHUNK
    track = 5 * quantum
    monkeypatch.setattr(build_song, "audio_duration", lambda p: track)
    scenes = [dict(SCENE, scene_number=1)]
    plan = build_song.clip_plan(scenes, audio_path="dummy.mp3", nclips=4)
    assert len(plan) == 4


def test_t2_13e_length_seconds_that_miss_the_track_are_refused(monkeypatch):
    monkeypatch.setattr(build_song, "audio_duration", lambda p: 20.0)
    scenes = [dict(SCENE, scene_number=1, length_seconds=30.0)]
    # Forced nclips overshoots; default is n_clips_for and stays in band.
    with pytest.raises(ValueError, match=r"miss"):
        build_song.clip_plan(scenes, audio_path="dummy.mp3", nclips=5)


def test_t2_13e_matching_length_seconds_are_accepted(monkeypatch):
    legal = build_song.clip_seconds(8.0)
    track = 2 * legal
    monkeypatch.setattr(build_song, "audio_duration", lambda p: track)
    scenes = [dict(SCENE, scene_number=1, length_seconds=8.0)]
    # default nclips = n_clips_for(track, 8.0) == 2
    plan = build_song.clip_plan(scenes, audio_path="dummy.mp3")
    assert len(plan) == 2


def test_t2_13e_nclips_only_is_display_and_does_not_refuse():
    """No track → no T2-13e check. storyboard_scenes / demo stay display."""
    scenes = [dict(SCENE, scene_number=1), dict(SCENE, scene_number=2)]
    plan = build_song.clip_plan(scenes, nclips=1)
    assert plan


def test_t2_13e_main_refuses_before_writing_clip_graphs(tmp_path, monkeypatch):
    monkeypatch.setattr(build_song, "audio_duration", lambda p: 2 * build_song.CHUNK)
    sb = {
        "scenes": [
            dict(SCENE, scene_number=1, length_seconds=30.0),
            dict(SCENE, scene_number=2, length_seconds=30.0),
        ],
        "character_reference": "c",
        "album_world_reference": "w",
    }
    storyboard = tmp_path / "sb.json"
    storyboard.write_text(json.dumps(sb))
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"x")
    outdir = tmp_path / "out"

    monkeypatch.setattr(sys, "argv", [
        "build_song.py", "--storyboard", str(storyboard),
        "--audio", str(audio), "--slug", "t213e", "--outdir", str(outdir),
    ])
    with pytest.raises(ValueError, match=r"miss"):
        build_song.main()
    assert not (outdir / "clip_000.json").exists()
    assert not list(outdir.glob("clip_*.json"))


def test_t2_13e_only_skips_full_track_refuse(tmp_path, monkeypatch):
    """A scene-scoped --only render must not die on the whole-song miss."""
    monkeypatch.setattr(build_song, "audio_duration", lambda p: 237.672)
    sb = {
        "scenes": [dict(SCENE, scene_number=1, length_seconds=5.0)],
        "character_reference": "c",
        "album_world_reference": "w",
    }
    storyboard = tmp_path / "sb.json"
    storyboard.write_text(json.dumps(sb))
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"x")
    outdir = tmp_path / "out"
    outdir.mkdir()
    monkeypatch.setattr(sys, "argv", [
        "build_song.py", "--storyboard", str(storyboard),
        "--audio", str(audio), "--slug", "t213eonly",
        "--outdir", str(outdir), "--only", "0",
    ])
    build_song.main()
    assert (outdir / "clip_000.json").exists()


def test_t2_13e_assemble_comment_does_not_assume_chunk_overrun():
    mixer = _real_module("mixer")
    assert mixer is not None, "real mixer.py failed to import"
    src = inspect.getsource(mixer.assemble_song)
    assert "quantised to 4.8125" not in src
    assert "always overruns" not in src
