"""T5-14: T5-A refine stays on the LTX take, not on the s2v hop.

docs/TRD-5 §5a: --refine + needs_lip_sync attaches SplitSigmasDenoise /
_refined SaveVideo only on LTX graphs. Hop successors force refine=False:
no WAN i2v-low refine, no _refined hop SaveVideo. Hop control_video is
the LTX SaveVideo prefix (the _refined one when refine is on).

Mutation: --refine attaches to the s2v successor → red.
Mutation: hop SaveVideo is *_refined → red.
Mutation: hop control_video points at the non-_refined LTX prefix while
LTX SaveVideo is *_refined → red.
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


def _has_i2v_low(wf):
    needle = build_song.I2V_LOW
    for n in wf.values():
        name = (n.get("inputs") or {}).get("unet_name")
        if name == needle:
            return True
    return False


def _emit(tmp_path, monkeypatch, scenes, slug, *, refine=True, audio_s=None):
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
    argv = [
        "build_song.py", "--storyboard", str(storyboard),
        "--audio", str(audio), "--slug", slug, "--outdir", str(outdir),
        "--video-model", "ltx25",
    ]
    if refine:
        argv.append("--refine")
    monkeypatch.setattr(sys, "argv", argv)
    build_song.main()
    return outdir


def _graphs(outdir):
    return sorted(
        p for p in outdir.glob("clip_*.json") if ".expect." not in p.name)


def test_t5_14_refine_plus_lip_attaches_t5a_only_on_ltx(tmp_path, monkeypatch):
    outdir = _emit(tmp_path, monkeypatch, [
        dict(SCENE, scene_number=1, length_seconds=5.0, needs_lip_sync=True),
    ], "t514")
    graphs = _graphs(outdir)
    assert len(graphs) >= 2, graphs

    ltx_wf = json.loads((outdir / "clip_000.json").read_text())
    assert "EmptyLTXVLatentVideo" in _classes(ltx_wf)
    assert "WanSoundImageToVideo" not in _classes(ltx_wf)
    assert "SplitSigmasDenoise" in _classes(ltx_wf), (
        "--refine must attach T5-A (SplitSigmasDenoise) on the LTX take")
    ltx_prefix = _prefix(ltx_wf)
    assert ltx_prefix.endswith("_refined"), ltx_prefix
    assert ltx_prefix == "t514/clip_000_refined"
    assert not _has_i2v_low(ltx_wf), "T5-A is not the WAN i2v-low refiner"

    hop_paths = [p for p in graphs if p.name != "clip_000.json"]
    assert hop_paths
    for path in hop_paths:
        wf = json.loads(path.read_text())
        kinds = _classes(wf)
        assert "WanSoundImageToVideo" in kinds, path
        assert "SplitSigmasDenoise" not in kinds, (
            f"{path}: T5-A attached to the s2v hop")
        assert "EmptyLTXVLatentVideo" not in kinds, (
            f"{path}: third LTX graph on s2v pixels")
        assert not _has_i2v_low(wf), (
            f"{path}: WAN i2v-low refine on the hop")
        hop_prefix = _prefix(wf)
        assert not hop_prefix.endswith("_refined"), (
            f"{path}: hop SaveVideo {hop_prefix!r} must not be _refined")
        assert hop_prefix != ltx_prefix
        loaders = _nodes(wf, "LoadVideosFromFolder")
        assert len(loaders) == 1, path
        control = loaders[0]["inputs"]["video"]
        assert control == ltx_prefix, (
            f"{path}: control_video={control!r} want refined LTX "
            f"SaveVideo path {ltx_prefix!r}")


def test_t5_14_refine_on_hop_is_the_red_mutation(tmp_path, monkeypatch):
    """If main() stops forcing refine=False on hops, this goes red."""
    outdir = _emit(tmp_path, monkeypatch, [
        dict(SCENE, scene_number=1, length_seconds=5.0, needs_lip_sync=True),
    ], "t514mut")
    hops = []
    for path in _graphs(outdir):
        wf = json.loads(path.read_text())
        if "WanSoundImageToVideo" not in _classes(wf):
            continue
        hops.append(wf)
        refined = (
            "SplitSigmasDenoise" in _classes(wf)
            or _has_i2v_low(wf)
            or _prefix(wf).endswith("_refined")
        )
        assert not refined, (
            f"{path.name}: refine attached to the s2v hop "
            f"(prefix={_prefix(wf)!r})")
    assert hops, "needs_lip_sync must emit an s2v hop"


def test_t5_14_labels_do_not_promise_i2v_low_or_unproven_s2v():
    """Labels must not promise WAN refine / unproven-on-s2v for --refine."""
    song = open(os.path.join(HERE, "templates", "song.html")).read()
    app_src = open(os.path.join(HERE, "app.py")).read()
    clips_fn = app_src.split("def h_clips", 1)[1].split("\n@jobs.handler", 1)[0]
    for blob, name in ((song, "song.html"), (clips_fn, "h_clips")):
        low = blob.lower()
        assert "unproven on s2v" not in low, name
        assert "i2v low-noise" not in low, name
        assert "i2v-low refine" not in low, name
