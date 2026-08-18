"""T5-11: every scene's first clip graph is ltx25.

docs/TRD-5 §5a: needs_lip_sync does not skip LTX. Unmarked scenes are
LTX only. T5-12 hop is not this slice.

Mutation: video_model=s2v or needs_lip_sync=true as the first hop → red.
Mutation: first hop emits WanSoundImageToVideo → red.
"""
import json
import sys

import build_song


SCENE = {
    "name": "s", "camera": "wide", "lighting": "neon",
    "video_motion_prompt": "she walks", "negative_prompt": "",
    "duration_guidance": "5 sec", "image_prompt": "a rooftop",
}


def _classes(wf):
    return {n.get("class_type") for n in wf.values()}


def _emit(tmp_path, monkeypatch, scenes, slug):
    monkeypatch.setattr(build_song, "audio_duration",
                        lambda p: build_song.CHUNK * max(len(scenes), 1))
    sb = {
        "scenes": scenes,
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
        "--audio", str(audio), "--slug", slug, "--outdir", str(outdir),
        "--video-model", "ltx25",
    ])
    build_song.main()
    return outdir


def _first_graph(outdir):
    path = outdir / "clip_000.json"
    assert path.is_file(), list(outdir.iterdir())
    return json.loads(path.read_text())


def test_t5_11_plan_hop0_is_ltx25_when_marked_s2v_or_lip():
    s2v = {"length_seconds": 5.0, "video_model": "s2v"}
    lip = {"length_seconds": 5.0, "needs_lip_sync": True}
    both = {"length_seconds": 5.0, "video_model": "s2v", "needs_lip_sync": True}
    unmarked = {"length_seconds": 5.0}
    for scene in (s2v, lip, both, unmarked):
        rec = build_song.clips_for_scene(scene, default_model="s2v")[0]
        assert rec["model"] == "ltx25", scene


def test_t5_11_emit_s2v_mark_is_not_hop0(tmp_path, monkeypatch):
    outdir = _emit(tmp_path, monkeypatch, [
        dict(SCENE, scene_number=1, video_model="s2v"),
    ], "t511-s2v")
    wf = _first_graph(outdir)
    kinds = _classes(wf)
    assert "EmptyLTXVLatentVideo" in kinds, kinds
    assert "WanSoundImageToVideo" not in kinds
    graphs = list(outdir.glob("clip_*.json"))
    hop_graphs = [p for p in graphs if ".expect." not in p.name]
    assert len(hop_graphs) == 1


def test_t5_11_emit_needs_lip_sync_is_not_hop0(tmp_path, monkeypatch):
    outdir = _emit(tmp_path, monkeypatch, [
        dict(SCENE, scene_number=1, needs_lip_sync=True),
    ], "t511-lip")
    wf = _first_graph(outdir)
    kinds = _classes(wf)
    assert "EmptyLTXVLatentVideo" in kinds, kinds
    assert "WanSoundImageToVideo" not in kinds
    hop_graphs = [p for p in outdir.glob("clip_*.json") if ".expect." not in p.name]
    assert len(hop_graphs) == 1


def test_t5_11_unmarked_is_ltx_only(tmp_path, monkeypatch):
    outdir = _emit(tmp_path, monkeypatch, [
        dict(SCENE, scene_number=1),
        dict(SCENE, scene_number=2),
    ], "t511-plain")
    hop_graphs = sorted(
        p for p in outdir.glob("clip_*.json") if ".expect." not in p.name)
    assert len(hop_graphs) == 2
    for path in hop_graphs:
        kinds = _classes(json.loads(path.read_text()))
        assert "EmptyLTXVLatentVideo" in kinds, path
        assert "WanSoundImageToVideo" not in kinds
