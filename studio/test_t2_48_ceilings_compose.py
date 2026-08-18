"""T2-48: hop 0 splits on the LTX ceiling; tiles still compose.

docs/TRD-2 W2 / T2-48: a 30 s LTX take splits on the LTX ceiling.
A 30 s needs_lip_sync scene is those LTX parts plus per-part s2v
windows (clip_chain_plan / split_to_ceiling(s2v)). T5-11: a scene
marked s2v still splits on LTX as hop 0, not on CHUNK.

Mutation: clips_for_scene treats video_model=s2v as hop 0 → the
s2v-marked arm is 7 x CHUNK and this fails.
Mutation: _compose does not stamp clips / validate skips tiling → a
gapped chain is accepted.
Mutation: 30 s needs_lip_sync omits per-part s2v windows → red.
"""
import json
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


def _tiles(clips, seconds, origin=0.0):
    assert clips, "no clips to tile"
    assert abs(clips[0]["start_s"] - origin) < 1e-9
    for a, b in zip(clips, clips[1:]):
        assert abs(a["end_s"] - b["start_s"]) < 1e-9, (a, b)
    assert abs(clips[-1]["end_s"] - (origin + seconds)) < 1e-6
    assert abs(sum(c["duration_s"] for c in clips) - seconds) < 1e-9


def test_t2_48_30s_s2v_mark_splits_on_ltx_ceiling_as_hop0():
    scene = dict(SCENE, scene_number=1, video_model="s2v", length_seconds=30.0)
    clips = build_song.clips_for_scene(scene)
    assert [round(c["duration_s"], 6) for c in clips] == [15.0, 15.0]
    assert all(c["model"] == "ltx25" for c in clips)
    assert len(clips) != 7, "s2v mark must not take the s2v ceiling as hop 0"
    _tiles(clips, 30.0)


def test_t2_48_30s_ltx25_splits_into_15s_and_tiles():
    scene = dict(SCENE, scene_number=2, video_model="ltx25", length_seconds=30.0)
    clips = build_song.clips_for_scene(scene)
    assert [round(c["duration_s"], 6) for c in clips] == [15.0, 15.0]
    assert all(c["model"] == "ltx25" for c in clips)
    _tiles(clips, 30.0)


def test_t2_48_30s_needs_lip_sync_ltx_then_s2v_windows_per_part():
    scene = dict(SCENE, scene_number=1, needs_lip_sync=True, length_seconds=30.0)
    plan = build_song.clip_chain_plan([scene])
    ltx = [p for p in plan if p["model"] == "ltx25"]
    hops = [p for p in plan if p["model"] == "s2v"]
    assert [round(c["duration_s"], 6) for c in ltx] == [15.0, 15.0]
    assert all(c["model"] == "ltx25" for c in ltx)
    _tiles(ltx, 30.0)
    assert hops, "needs_lip_sync must append s2v hop windows"
    for part in ltx:
        part_hops = [h for h in hops if h["control_clip_idx"] == part["clip_idx"]]
        want = build_song.split_to_ceiling(part["duration_s"], "s2v")
        assert [round(h["duration_s"], 6) for h in part_hops] == [
            round(w, 6) for w in want
        ]
        _tiles(part_hops, part["duration_s"], origin=part["start_s"])


def test_t2_48_mixed_scenes_hop0_uses_ltx_ceiling():
    scenes = [
        dict(SCENE, scene_number=1, video_model="s2v", length_seconds=30.0),
        dict(SCENE, scene_number=2, video_model="ltx25", length_seconds=30.0),
    ]
    plan = build_song.clips_for_scenes(scenes)
    marked = [c for c in plan if c["scene_number"] == 1]
    ltx = [c for c in plan if c["scene_number"] == 2]
    assert len(marked) == 2
    assert len(ltx) == 2
    assert all(c["model"] == "ltx25" for c in marked)
    assert all(c["model"] == "ltx25" for c in ltx)
    _tiles(marked, 30.0)
    assert abs(ltx[0]["start_s"] - marked[-1]["end_s"]) < 1e-6
    assert abs(ltx[-1]["end_s"] - 60.0) < 1e-6
    for a, b in zip(ltx, ltx[1:]):
        assert abs(a["end_s"] - b["start_s"]) < 1e-9


def test_t2_48_compose_stamps_ltx_tiles_on_s2v_mark():
    grok = _real_module("grok")
    raw = [
        dict(SCENE, scene_number=1, video_model="s2v", camera="wide"),
        dict(SCENE, scene_number=2, video_model="ltx25", camera="close"),
    ]
    song = {"title": "T", "album": "A", "duration": 60.0, "genre": "pop"}
    board = grok._compose(song, "pg13", "", "style", "[Verse]\na", raw, 2, 30.0)
    marked = board["scenes"][0]
    ltx = board["scenes"][1]
    assert marked["video_model"] == "s2v"
    assert ltx["video_model"] == "ltx25"
    assert [round(c["duration_s"], 6) for c in marked["clips"]] == [15.0, 15.0]
    assert [round(c["duration_s"], 6) for c in ltx["clips"]] == [15.0, 15.0]
    assert all(c["model"] == "ltx25" for c in marked["clips"])
    _tiles(marked["clips"], 30.0)
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


def test_t2_48_main_emits_ltx_graphs_for_s2v_mark(tmp_path, monkeypatch):
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
    assert len(graphs) == 4

    def _classes(path):
        wf = json.loads(path.read_text())
        return {n.get("class_type") for n in wf.values()}

    for path in graphs:
        classes = _classes(path)
        assert "EmptyLTXVLatentVideo" in classes, path
        assert "WanSoundImageToVideo" not in classes
        expect = json.loads(path.with_name(path.name.replace(".json", ".expect.json")).read_text())
        want = build_song.clip_seconds(15.0)
        assert abs(expect["duration"] - want) < 0.05, expect
