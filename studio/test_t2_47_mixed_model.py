"""T2-47 retargeted: hop 0 is LTX even when a scene is marked s2v.

docs/TRD-2 W2 / T2-47 asked for two renderers in one job (s2v + ltx25
native frames/fps). T5-11 retired s2v-as-first: clip_000 of a marked
s2v scene is ltx25. Mixed native frames return with the T5-12 hop.

Asserted through build_song.main() — the writer pipeline.gen_clips /
h_clips shells out to (T6-A10).

Mutation: main() emits WanSoundImageToVideo as hop 0 for video_model=s2v
→ this fails.
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


def test_t2_47_one_job_s2v_mark_still_emits_ltx_first(
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

    first_path = outdir / "clip_000.json"
    second_path = outdir / "clip_001.json"
    first_expect_path = outdir / "clip_000.expect.json"
    second_expect_path = outdir / "clip_001.expect.json"
    assert first_path.is_file() and second_path.is_file()
    assert first_expect_path.is_file() and second_expect_path.is_file()

    first_wf = json.loads(first_path.read_text())
    second_wf = json.loads(second_path.read_text())
    first_expect = json.loads(first_expect_path.read_text())
    second_expect = json.loads(second_expect_path.read_text())

    first_classes = _classes(first_wf)
    second_classes = _classes(second_wf)
    assert "EmptyLTXVLatentVideo" in first_classes, first_classes
    assert "EmptyLTXVLatentVideo" in second_classes, second_classes
    assert "WanSoundImageToVideo" not in first_classes
    assert "WanSoundImageToVideo" not in second_classes

    assert first_expect == build_song.expect_from_workflow(first_wf)
    assert second_expect == build_song.expect_from_workflow(second_wf)
    assert first_expect["frames"] == build_song.LTX25_LEN
    assert first_expect["fps"] == round(build_song.LTX25_FPS, 4)
    assert second_expect["frames"] == build_song.LTX25_LEN
    assert second_expect["fps"] == round(build_song.LTX25_FPS, 4)
