"""T2-47: one job, two scenes (s2v + ltx25) emit each model's frames/fps.

docs/TRD-2 W2 / T2-47: one storyboard, two scenes, one marked s2v and
one left ltx25, rendered in a single job — and the two output clips
carry the models' own frame counts and fps. Asserting the plan holds
two model names proves the field posts, not that two renderers ran.

Asserted through build_song.main() — the writer pipeline.gen_clips /
h_clips shells out to (T6-A10).

Mutation: main() passes args.video_model to every clip → both expects
match ltx25 and this fails.
Mutation: write two model names on a plan and skip the graphs → this
fails (no clip_NNN.expect.json / family nodes).
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


def test_t2_47_one_job_two_scenes_carry_each_models_frames_and_fps(
        tmp_path, monkeypatch):
    monkeypatch.setattr(build_song, "audio_duration",
                        lambda p: 2 * build_song.CHUNK)
    sb = {
        "scenes": [
            dict(SCENE, scene_number=1, video_model="s2v"),
            dict(SCENE, scene_number=2),
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
        "--audio", str(audio), "--slug", "t247", "--outdir", str(outdir),
        "--video-model", "ltx25",
    ])
    build_song.main()

    wan_path = outdir / "clip_000.json"
    ltx_path = outdir / "clip_001.json"
    wan_expect_path = outdir / "clip_000.expect.json"
    ltx_expect_path = outdir / "clip_001.expect.json"
    assert wan_path.is_file() and ltx_path.is_file()
    assert wan_expect_path.is_file() and ltx_expect_path.is_file()

    wan_wf = json.loads(wan_path.read_text())
    ltx_wf = json.loads(ltx_path.read_text())
    wan_expect = json.loads(wan_expect_path.read_text())
    ltx_expect = json.loads(ltx_expect_path.read_text())

    wan_classes = _classes(wan_wf)
    ltx_classes = _classes(ltx_wf)
    assert "WanSoundImageToVideo" in wan_classes, wan_classes
    assert "EmptyLTXVLatentVideo" in ltx_classes, ltx_classes
    assert "WanSoundImageToVideo" not in ltx_classes
    assert "EmptyLTXVLatentVideo" not in wan_classes

    assert wan_expect == build_song.expect_from_workflow(wan_wf)
    assert ltx_expect == build_song.expect_from_workflow(ltx_wf)
    assert wan_expect["frames"] == build_song.LEN
    assert wan_expect["fps"] == build_song.FPS
    assert ltx_expect["frames"] == build_song.LTX25_LEN
    assert ltx_expect["fps"] == round(build_song.LTX25_FPS, 4)
    assert wan_expect["frames"] != ltx_expect["frames"]
    assert wan_expect["fps"] != ltx_expect["fps"]
