"""T2-48: per-scene model and per-model ceilings compose.

docs/TRD-2 W2 / T2-48: a 30 s scene marked s2v splits into s2v-sized
clips, a 30 s scene on ltx25 into 15 s ones, and each tiles its own
scene exactly (T2-8b).

Mutation: clips_for_scene ignores video_model → both scenes take the
job default ceiling and the s2v arm is 2 x 15 s.
Mutation: main() still allocates by CHUNK and hands the 30 s scene to
workflow → honour_ceiling raises, or both families emit the same count.
Mutation: _compose does not stamp clips / validate skips tiling → a
gapped chain is accepted.
"""
import json
import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import build_song
from conftest import _real_module


SCENE = {
    "name": "s", "cue": "Verse", "story": "she walks",
    "camera": "wide", "motion": "walk", "lighting": "neon",
    "video_motion_prompt": "she walks", "negative_prompt": "",
    "duration_guidance": "30 sec", "image_prompt": "a rooftop",
}


def _tiles(clips, seconds):
    assert clips, "no clips to tile"
    assert abs(clips[0]["start_s"] - 0.0) < 1e-9
    for a, b in zip(clips, clips[1:]):
        assert abs(a["end_s"] - b["start_s"]) < 1e-9, (a, b)
    assert abs(clips[-1]["end_s"] - seconds) < 1e-6
    assert abs(sum(c["duration_s"] for c in clips) - seconds) < 1e-9


def test_t2_48_30s_s2v_splits_on_s2v_size_and_tiles():
    scene = dict(SCENE, scene_number=1, video_model="s2v", length_seconds=30.0)
    clips = build_song.clips_for_scene(scene)
    limit = build_song.clip_ceiling("s2v")["seconds"]
    assert limit == build_song.CHUNK
    assert len(clips) == math.ceil(30.0 / limit)
    assert len(clips) != math.ceil(30.0 / 15.0), "s2v must not take the ltx25 ceiling"
    assert all(c["duration_s"] <= limit + 1e-9 for c in clips)
    assert all(c["model"] == "s2v" for c in clips)
    _tiles(clips, 30.0)


def test_t2_48_30s_ltx25_splits_into_15s_and_tiles():
    scene = dict(SCENE, scene_number=2, video_model="ltx25", length_seconds=30.0)
    clips = build_song.clips_for_scene(scene)
    assert [round(c["duration_s"], 6) for c in clips] == [15.0, 15.0]
    assert all(c["model"] == "ltx25" for c in clips)
    _tiles(clips, 30.0)


def test_t2_48_mixed_scenes_each_use_own_ceiling():
    scenes = [
        dict(SCENE, scene_number=1, video_model="s2v", length_seconds=30.0),
        dict(SCENE, scene_number=2, video_model="ltx25", length_seconds=30.0),
    ]
    plan = build_song.clips_for_scenes(scenes)
    s2v = [c for c in plan if c["scene_number"] == 1]
    ltx = [c for c in plan if c["scene_number"] == 2]
    assert len(s2v) == math.ceil(30.0 / build_song.CHUNK)
    assert len(ltx) == 2
    assert len(s2v) != len(ltx)
    assert all(c["model"] == "s2v" for c in s2v)
    assert all(c["model"] == "ltx25" for c in ltx)
    _tiles(s2v, 30.0)
    assert abs(ltx[0]["start_s"] - s2v[-1]["end_s"]) < 1e-6
    assert abs(ltx[-1]["end_s"] - 60.0) < 1e-6
    for a, b in zip(ltx, ltx[1:]):
        assert abs(a["end_s"] - b["start_s"]) < 1e-9


def test_t2_48_compose_stamps_per_model_tiles():
    grok = _real_module("grok")
    raw = [
        dict(SCENE, scene_number=1, video_model="s2v", camera="wide"),
        dict(SCENE, scene_number=2, video_model="ltx25", camera="close"),
    ]
    song = {"title": "T", "album": "A", "duration": 60.0, "genre": "pop"}
    board = grok._compose(song, "pg13", "", "style", "[Verse]\na", raw, 2, 30.0)
    s2v = board["scenes"][0]
    ltx = board["scenes"][1]
    assert s2v["video_model"] == "s2v"
    assert ltx["video_model"] == "ltx25"
    assert len(s2v["clips"]) == math.ceil(30.0 / build_song.CHUNK)
    assert [round(c["duration_s"], 6) for c in ltx["clips"]] == [15.0, 15.0]
    _tiles(s2v["clips"], 30.0)
    _tiles(ltx["clips"], 30.0)
    grok.validate(board, exemplar={}, expect_scenes=2)


def test_t2_48_validate_refuses_untiled_clips():
    grok = _real_module("grok")
    raw = [
        dict(SCENE, scene_number=1, video_model="s2v", camera="wide"),
        dict(SCENE, scene_number=2, video_model="ltx25", camera="close"),
    ]
    song = {"title": "T", "album": "A", "duration": 60.0, "genre": "pop"}
    board = grok._compose(song, "pg13", "", "style", "[Verse]\na", raw, 2, 30.0)
    board["scenes"][1]["clips"] = [dict(c) for c in board["scenes"][1]["clips"]]
    board["scenes"][1]["clips"][1]["start_s"] += 1.0
    board["scenes"][1]["clips"][1]["end_s"] += 1.0
    with pytest.raises(ValueError, match="tile"):
        grok.validate(board, exemplar={}, expect_scenes=2)


def test_t2_48_main_emits_s2v_sized_and_15s_graphs(tmp_path, monkeypatch):
    monkeypatch.setattr(build_song, "audio_duration", lambda p: 60.0)
    sb = {
        "scenes": [
            dict(SCENE, scene_number=1, video_model="s2v", length_seconds=30.0),
            dict(SCENE, scene_number=2, video_model="ltx25", length_seconds=30.0),
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
        "--audio", str(audio), "--slug", "t248", "--outdir", str(outdir),
        "--video-model", "ltx25",
    ])
    build_song.main()

    graphs = sorted(p for p in outdir.glob("clip_*.json") if ".expect." not in p.name)
    s2v_n = math.ceil(30.0 / build_song.CHUNK)
    assert len(graphs) == s2v_n + 2

    def _classes(path):
        wf = json.loads(path.read_text())
        return {n.get("class_type") for n in wf.values()}

    s2v_graphs = graphs[:s2v_n]
    ltx_graphs = graphs[s2v_n:]
    for path in s2v_graphs:
        classes = _classes(path)
        assert "WanSoundImageToVideo" in classes, path
        assert "EmptyLTXVLatentVideo" not in classes
    for path in ltx_graphs:
        classes = _classes(path)
        assert "EmptyLTXVLatentVideo" in classes, path
        assert "WanSoundImageToVideo" not in classes
        expect = json.loads(path.with_name(path.name.replace(".json", ".expect.json")).read_text())
        want = build_song.clip_seconds(15.0)
        assert abs(expect["duration"] - want) < 0.05, expect
