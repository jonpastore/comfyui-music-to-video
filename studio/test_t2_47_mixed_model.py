"""T2-47: one job keeps each renderer's native frames/fps.

docs/TRD-2 W2 / T2-47: two renderers in one job, each clip's own
frames/fps. T5-11 retired s2v-as-first: clip_000 of a marked s2v
scene is ltx25. Mixed native frames are the T5-12 hop: one
needs_lip_sync job writes LTX hop0 .expect.json 81@LTX25_FPS and
s2v hop .expect.json 77@16.0.

Asserted through build_song.main() — the writer pipeline.gen_clips /
h_clips shells out to (T6-A10).

Mutation: main() emits WanSoundImageToVideo as hop 0 → hop0-not-Wan
arm red.
Mutation: both .expect.json share one frames/fps → mixed-native arm
red.
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


def _graphs(outdir):
    return sorted(
        p for p in outdir.glob("clip_*.json") if ".expect." not in p.name)


def _emit(tmp_path, monkeypatch, scenes, slug, audio_s):
    monkeypatch.setattr(build_song, "audio_duration", lambda p: audio_s)
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


def test_t2_47_one_job_s2v_mark_still_emits_ltx_first(
        tmp_path, monkeypatch):
    outdir = _emit(tmp_path, monkeypatch, [
        dict(SCENE, scene_number=1, video_model="s2v"),
        dict(SCENE, scene_number=2),
    ], "t247", audio_s=2 * build_song.CHUNK)

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


def test_t2_47_one_job_needs_lip_sync_emits_mixed_native_expect(
        tmp_path, monkeypatch):
    """LTX hop0 81@LTX25_FPS and s2v hop 77@16.0 must differ."""
    outdir = _emit(tmp_path, monkeypatch, [
        dict(SCENE, scene_number=1, needs_lip_sync=True),
    ], "t247mix", audio_s=build_song.CHUNK)

    graphs = _graphs(outdir)
    hop0_path = outdir / "clip_000.json"
    hop0_expect_path = outdir / "clip_000.expect.json"
    assert hop0_path.is_file() and hop0_expect_path.is_file()

    hop0_wf = json.loads(hop0_path.read_text())
    hop0_expect = json.loads(hop0_expect_path.read_text())
    hop0_classes = _classes(hop0_wf)
    assert "EmptyLTXVLatentVideo" in hop0_classes, hop0_classes
    assert "WanSoundImageToVideo" not in hop0_classes
    assert hop0_expect == build_song.expect_from_workflow(hop0_wf)
    assert hop0_expect["frames"] == build_song.LTX25_LEN
    assert hop0_expect["fps"] == round(build_song.LTX25_FPS, 4)

    hops = []
    for path in graphs:
        if path.name == "clip_000.json":
            continue
        wf = json.loads(path.read_text())
        if "WanSoundImageToVideo" not in _classes(wf):
            continue
        expect_path = path.with_name(path.name.replace(".json", ".expect.json"))
        assert expect_path.is_file(), expect_path
        expect = json.loads(expect_path.read_text())
        assert expect == build_song.expect_from_workflow(wf)
        hops.append((path, expect))
    assert hops, "needs_lip_sync must emit an s2v hop beside hop 0"

    ltx_pair = (hop0_expect["frames"], hop0_expect["fps"])
    want_s2v = (build_song.LEN, float(build_song.FPS))
    assert want_s2v == (77, 16.0)
    assert ltx_pair != want_s2v, (
        "mixed native frames must differ; one fps/frames for both "
        "renderers is the leftover T2-47 exists to close")
    for path, expect in hops:
        pair = (expect["frames"], expect["fps"])
        assert pair == want_s2v, (path, expect)
        assert pair != ltx_pair, (path, expect, hop0_expect)
