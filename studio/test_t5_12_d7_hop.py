"""T5-12: D7 hop graph — decoded s2v after LTX on needs_lip_sync.

docs/TRD-5 §5a: control_video = LTX frames via LoadVideosFromFolder
(not LoadVideo, not an LTX latent); ref_image = scene still; distinct
SaveVideo prefix so the LTX take is not overwritten; depends_on = LTX
predecessor. Unmarked stays LTX-only. T5-13 skip_first_frames and
T3-37 GPU look are not this slice.

Mutation: control_video is LoadVideo or an LTX latent → red.
Mutation: hop overwrites the LTX SaveVideo prefix → red.
Mutation: ref_image is not the scene still → red.
Mutation: unmarked emits a hop / needs_lip_sync skips LTX → red.
"""
import json
import os
import sys

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


def _classes(wf):
    return {n.get("class_type") for n in wf.values()}


def _nodes(wf, class_type):
    return [n for n in wf.values() if n.get("class_type") == class_type]


def _prefix(wf):
    return next(n["inputs"]["filename_prefix"] for n in wf.values()
                if n.get("class_type") == "SaveVideo")


def _emit(tmp_path, monkeypatch, scenes, slug, audio_s=None):
    n = max(len(scenes), 1)
    monkeypatch.setattr(
        build_song, "audio_duration",
        lambda p: audio_s if audio_s is not None else build_song.CHUNK * n)
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


def _graphs(outdir):
    return sorted(
        p for p in outdir.glob("clip_*.json") if ".expect." not in p.name)


def test_t5_12_plan_appends_s2v_windows_with_ltx_depends_on():
    scene = dict(SCENE, scene_number=1, length_seconds=5.0, needs_lip_sync=True)
    plan = build_song.clip_chain_plan([scene])
    ltx = [p for p in plan if p["model"] == "ltx25"]
    hops = [p for p in plan if p["model"] == "s2v"]
    assert len(ltx) == 1, ltx
    assert ltx[0]["depends_on"] is None
    assert hops, "needs_lip_sync must append s2v hop windows"
    assert all(h["depends_on"] == ltx[0]["clip_idx"] for h in hops), hops
    assert all(h.get("control_clip_idx") == ltx[0]["clip_idx"] for h in hops)
    want = build_song.split_to_ceiling(5.0, "s2v")
    assert [round(h["duration_s"], 6) for h in hops] == [round(w, 6) for w in want]


def test_t5_12_unmarked_plan_is_ltx_only():
    scene = dict(SCENE, scene_number=1, length_seconds=5.0)
    plan = build_song.clip_chain_plan([scene])
    assert len(plan) == 1
    assert plan[0]["model"] == "ltx25"
    assert all(p["model"] != "s2v" for p in plan)


def test_t5_12_video_model_s2v_alone_is_not_a_hop():
    scene = dict(SCENE, scene_number=1, length_seconds=5.0, video_model="s2v")
    plan = build_song.clip_chain_plan([scene])
    assert [p["model"] for p in plan] == ["ltx25"]


def test_t5_12_emit_hop_uses_loadvideosfromfolder_on_ltx_prefix(tmp_path, monkeypatch):
    outdir = _emit(tmp_path, monkeypatch, [
        dict(SCENE, scene_number=1, length_seconds=5.0, needs_lip_sync=True),
    ], "t512")
    graphs = _graphs(outdir)
    assert len(graphs) >= 2, graphs
    ltx_wf = json.loads((outdir / "clip_000.json").read_text())
    assert "EmptyLTXVLatentVideo" in _classes(ltx_wf)
    assert "WanSoundImageToVideo" not in _classes(ltx_wf)
    ltx_prefix = _prefix(ltx_wf)
    assert ltx_prefix == "t512/clip_000"

    hop_paths = [p for p in graphs if p.name != "clip_000.json"]
    assert hop_paths
    for path in hop_paths:
        wf = json.loads(path.read_text())
        kinds = _classes(wf)
        assert "WanSoundImageToVideo" in kinds, path
        assert "LoadVideosFromFolder" in kinds, path
        assert "LoadVideo" not in kinds, path
        assert "EmptyLTXVLatentVideo" not in kinds, path
        loaders = _nodes(wf, "LoadVideosFromFolder")
        assert len(loaders) == 1, path
        assert loaders[0]["inputs"]["video"] == ltx_prefix, (
            f"{path}: control_video={loaders[0]['inputs']['video']!r} "
            f"want LTX SaveVideo path {ltx_prefix!r}")
        s2v = _nodes(wf, "WanSoundImageToVideo")[0]
        assert s2v["inputs"]["control_video"] == [
            next(k for k, n in wf.items()
                 if n.get("class_type") == "LoadVideosFromFolder"),
            0,
        ]
        hop_prefix = _prefix(wf)
        assert hop_prefix != ltx_prefix, "hop must not overwrite the LTX take"
        assert hop_prefix.startswith("t512/clip_")


def test_t5_12_hop_ref_image_is_scene_still(tmp_path, monkeypatch):
    outdir = _emit(tmp_path, monkeypatch, [
        dict(SCENE, scene_number=1, length_seconds=5.0, needs_lip_sync=True),
    ], "t512ref")
    heads = build_song.scene_heads([
        dict(SCENE, scene_number=1, length_seconds=5.0, needs_lip_sync=True),
    ])
    head = heads[1]
    want = f"t512ref_clip_{head:03d}.png"
    for path in _graphs(outdir):
        wf = json.loads(path.read_text())
        if "WanSoundImageToVideo" not in _classes(wf):
            continue
        load = _nodes(wf, "LoadImage")[0]
        assert load["inputs"]["image"] == want, (
            f"{path}: ref_image={load['inputs']['image']!r} want scene still {want!r}")


def test_t5_12_unmarked_emit_is_ltx_only(tmp_path, monkeypatch):
    outdir = _emit(tmp_path, monkeypatch, [
        dict(SCENE, scene_number=1, length_seconds=5.0),
        dict(SCENE, scene_number=2, length_seconds=5.0),
    ], "t512plain")
    graphs = _graphs(outdir)
    assert len(graphs) == 2
    for path in graphs:
        kinds = _classes(json.loads(path.read_text()))
        assert "EmptyLTXVLatentVideo" in kinds, path
        assert "WanSoundImageToVideo" not in kinds
        assert "LoadVideosFromFolder" not in kinds


def test_t5_12_30s_lip_ltx_chain_then_hops_per_part():
    scene = dict(SCENE, scene_number=1, length_seconds=30.0, needs_lip_sync=True)
    plan = build_song.clip_chain_plan([scene])
    ltx = [p for p in plan if p["model"] == "ltx25"]
    hops = [p for p in plan if p["model"] == "s2v"]
    assert len(ltx) == 2
    assert ltx[0]["depends_on"] is None and ltx[1]["depends_on"] == 0
    assert hops
    for h in hops:
        assert h["depends_on"] in {ltx[0]["clip_idx"], ltx[1]["clip_idx"]}
        assert h["control_clip_idx"] == h["depends_on"]
    # each LTX part gets its own s2v window set
    for part in ltx:
        part_hops = [h for h in hops if h["control_clip_idx"] == part["clip_idx"]]
        want = build_song.split_to_ceiling(part["duration_s"], "s2v")
        assert len(part_hops) == len(want), (part, part_hops)
