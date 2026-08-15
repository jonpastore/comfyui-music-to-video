"""T2-10: a scene over the render ceiling is a clip chain.

docs/TRD-2 T2-10: count is ceil(scene_seconds / ceiling), and clip N+1's
first frame is clip N's last frame — asserted by extracting both frames
and comparing them, not by asserting the chain was planned. The graph
uses LTXVAddGuide (TRD-2 W1-7 / TRD-5 §6), not a from-scratch handoff.
"""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import build_song


SCENE = {
    "scene_number": 1, "name": "s", "camera": "wide", "lighting": "neon",
    "video_motion_prompt": "she walks", "negative_prompt": "",
    "duration_guidance": "30 sec", "image_prompt": "a rooftop",
    "length_seconds": 15.0,
}


def _ffmpeg(args):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *args],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r


def _two_tone_clip(path, last_colour, first_colour="blue", frames=9, fps=16, size="64x64"):
    """First frame one colour, last frame another. 8n+1 frames."""
    seconds = frames / fps
    switch = (frames - 1) / fps
    _ffmpeg([
        "-f", "lavfi",
        "-i", f"color=c={first_colour}:s={size}:r={fps}:d={seconds}",
        "-f", "lavfi",
        "-i", f"color=c={last_colour}:s={size}:r={fps}:d={seconds}",
        "-filter_complex",
        f"[0:v][1:v]overlay=enable='gte(t,{switch:.6f})'",
        "-frames:v", str(frames),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", path,
    ])


def _clip_from_png(path, png, frames=9, fps=16):
    _ffmpeg([
        "-loop", "1", "-i", png,
        "-frames:v", str(frames),
        "-r", str(fps),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", path,
    ])


def _guide_nodes(wf):
    return [n for n in wf.values() if n.get("class_type") == "LTXVAddGuide"]


def test_t2_10_scene_over_ceiling_is_ceil_scene_over_ceiling():
    """30s / 15s LTX cost ceiling = 2. At the ceiling, one clip.

    Mutation: always return 1 → a 30s scene never becomes a chain.
    """
    ceiling = build_song.render_ceiling("ltx25")
    assert ceiling == 15.0
    assert build_song.chain_clip_count(30.0) == 2
    assert build_song.chain_clip_count(30.0, ceiling) == 2
    assert build_song.chain_clip_count(15.0, ceiling) == 1
    assert build_song.chain_clip_count(45.0, ceiling) == 3
    assert build_song.chain_clip_count(32.0, ceiling) == 3
    # Same count as split_to_ceiling / T5-9; n_clips_for is song-level and unchanged.
    assert len(build_song.split_to_ceiling(30.0, "ltx25")) == 2
    assert build_song.n_clips_for(195.792, 30.0) == 7
    plan = build_song.chain_plan(30.0, ceiling)
    assert [p["duration"] for p in plan] == [15.0, 15.0]
    assert plan[0]["depends_on"] is None
    assert plan[1]["depends_on"] == 0


def test_t2_10_clip_n1_first_frame_equals_clip_n_last(tmp_path):
    """The criterion: extract both frames and compare them.

    Mutation: chain_first_frame takes the FIRST frame of N → red vs last.
    Mutation: compare first-to-first → a two-tone predecessor still matches.
    """
    prev = str(tmp_path / "clip_n.mp4")
    nxt = str(tmp_path / "clip_n1.mp4")
    wrong = str(tmp_path / "wrong.mp4")
    _two_tone_clip(prev, last_colour="red", first_colour="blue")
    guide = build_song.chain_first_frame(prev, dest=str(tmp_path / "guide.png"))
    last = build_song.extract_video_frame(prev, "last", dest=str(tmp_path / "last.png"))
    first_of_prev = build_song.extract_video_frame(
        prev, "first", dest=str(tmp_path / "first.png"))
    assert build_song.frame_pixels(guide) == build_song.frame_pixels(last)
    assert build_song.frame_pixels(guide) != build_song.frame_pixels(first_of_prev)

    _clip_from_png(nxt, guide)
    assert build_song.chain_seam_matches(prev, nxt)

    _two_tone_clip(wrong, last_colour="green", first_colour="blue")
    assert not build_song.chain_seam_matches(prev, wrong)


def test_t2_10_successor_graph_uses_ltxv_add_guide(tmp_path):
    """W1-7: do not invent a handoff. Clip N+1 injects N's last frame at index 0.

    Mutation: workflow ignores guide_image / prev_clip → no LTXVAddGuide.
    Mutation: LTXVAddGuide at a non-zero frame_idx → the first frame is not N's last.
    """
    prev = str(tmp_path / "clip_n.mp4")
    _two_tone_clip(prev, last_colour="red", first_colour="blue")
    guide = build_song.chain_first_frame(prev, dest=str(tmp_path / "guide.png"))

    first = build_song.workflow(
        0, SCENE, "ref.png", "song.mp3", "c", "w", "", video_model="ltx25")
    assert _guide_nodes(first) == []

    successor = build_song.workflow(
        1, SCENE, "ref.png", "song.mp3", "c", "w", "",
        video_model="ltx25", prev_clip=prev, guide_image=guide)
    guides = _guide_nodes(successor)
    assert len(guides) == 1, successor
    g = guides[0]["inputs"]
    assert g["frame_idx"] == 0
    assert g["strength"] == 1.0
    assert "positive" in g and "negative" in g and "vae" in g and "latent" in g
    img_id = g["image"][0]
    loaded = successor[img_id]
    while loaded["class_type"] != "LoadImage":
        src = loaded["inputs"].get("image")
        assert src, loaded
        loaded = successor[src[0]]
    assert os.path.basename(loaded["inputs"]["image"]) == "guide.png"

    # DualCFGGuider must consume the guided conditioning, not the pre-guide pair.
    guider = next(n for n in successor.values() if n["class_type"] == "LTXVDualCFGGuider")
    guide_id = next(k for k, n in successor.items() if n["class_type"] == "LTXVAddGuide")
    assert guider["inputs"]["positive"] == [guide_id, 0]
    assert guider["inputs"]["negative"] == [guide_id, 1]
