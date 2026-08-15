"""T5-2: MAD on decoded frames, refine-on vs off, same seed.

docs/TRD-5 T5-2: the differential is on the OUTPUT, not the graph.
Graph inequality is T5-1. skip is not a reading. Missing frames raise
NOT MEASURED.

A synthetic / lavfi pair proves the metric can fail. A real same-seed
GPU pair is a separate flag; flipping it with an empty hook is the lie.
"""
import os
import subprocess
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import build_song
import qc


SCENE = {
    "scene_number": 1, "name": "s", "camera": "wide", "lighting": "neon",
    "video_motion_prompt": "she walks", "negative_prompt": "",
    "duration_guidance": "5 sec", "image_prompt": "a rooftop",
}


def _synthetic_pair():
    """Same scene, refine-on adds high-frequency detail.

    Deleting the offset, or returning the same array twice, makes MAD
    and sharpness go red. It is not a 5090 clip.
    """
    n, h, w = 2, 16, 16
    yy, xx = np.ogrid[0:h, 0:w]
    ramp = (xx + yy).astype("float64")
    plain = np.broadcast_to(ramp[..., None], (n, h, w, 3)).copy()
    refined = plain.copy()
    refined[:, 0::2, 0::2] += 50.0
    refined[:, 1::2, 1::2] += 50.0
    return plain, refined


def _lavfi_mp4(path, filt):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", filt,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


def test_t5_2_tests_do_not_skip():
    """A skip call is not a reading. Mutation: insert a skip call → red."""
    src = open(__file__, encoding="utf-8").read()
    skip_call = "pytest" + ".skip("
    skip_mark = "pytest" + ".mark.skip"
    assert skip_call not in src
    assert skip_mark not in src


def test_t5_2_synthetic_decode_fixture_mad_gt_zero_and_sharpness_up():
    """Harness: MAD > 0 and Laplacian variance moves up on a decode pair.

    Mutation: both arrays identical → MAD == 0.
    """
    plain, refined = _synthetic_pair()
    d = qc.t5_2_refine_differential(plain, refined)
    assert d["mad"] > 0, d
    assert d["sharpness_on"] > d["sharpness_off"], d


def test_t5_2_identical_frames_mad_is_zero():
    """The metric can fail: a no-op pair is MAD == 0, not a free pass."""
    plain, _ = _synthetic_pair()
    assert qc.mean_absolute_difference(plain, plain) == 0.0


def test_t5_2_missing_frames_fail_closed_not_measured():
    """Missing decode arrays raise NOT MEASURED. Never 0.0, never skip."""
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t5_2_refine_differential(None, None)
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.mean_absolute_difference(None, _synthetic_pair()[0])
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t5_2_claim()


def test_t5_2_missing_video_path_fail_closed(tmp_path):
    """A path that does not exist is NOT MEASURED, not MAD 0."""
    missing = str(tmp_path / "nope.mp4")
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.decode_video_frames(missing)
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t5_2_refine_differential(missing, missing)


def test_t5_2_decoded_lavfi_pair_mad_gt_zero(tmp_path):
    """MAD is on decoded frames, not graph nodes.

    Same seed/scene stand-in: gray field vs testsrc2 (high-frequency).
    Mutation: decode both from the same file → MAD == 0.
    """
    plain_p = _lavfi_mp4(
        str(tmp_path / "off.mp4"), "color=c=gray:s=32x32:r=8:d=0.25")
    refined_p = _lavfi_mp4(
        str(tmp_path / "on.mp4"), "testsrc2=size=32x32:rate=8:duration=0.25")
    d = qc.t5_2_refine_differential(plain_p, refined_p)
    assert d["mad"] > 0, d
    assert d["sharpness_on"] > d["sharpness_off"], d
    same = qc.t5_2_refine_differential(plain_p, plain_p)
    assert same["mad"] == 0.0, same


def test_t5_2_graph_inequality_is_not_the_criterion():
    """T5-1 already asserts the graph grows. That is not T5-2."""
    plain = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="ltx25")
    refined = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "",
        video_model="ltx25", refine=True)
    assert refined != plain
    assert qc.T5_2_REAL_CLIP_MEASURED is False
    assert qc.t5_2_real_clip_frames() is None
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t5_2_claim()


def test_t5_2_real_clip_hook_exists():
    """Renderer populate hook. Mutation: delete the names → red."""
    assert hasattr(qc, "T5_2_REAL_CLIP_FRAMES")
    assert hasattr(qc, "T5_2_REAL_CLIP_MEASURED")
    assert callable(qc.t5_2_real_clip_frames)
    assert callable(qc.record_t5_2_real_clip)
    assert callable(qc.t5_2_claim)


def test_t5_2_real_clip_mad_not_measured():
    """T5-2 on a real same-seed GPU pair is NOT MEASURED.

    Flip T5_2_REAL_CLIP_MEASURED only after that pair is decoded.
    Mutation: set MEASURED True with an empty hook → this goes red.
    """
    frames = qc.t5_2_real_clip_frames()
    assert qc.T5_2_REAL_CLIP_MEASURED is False, (
        "T5-2 real clip is NOT MEASURED; flip only after a GPU pair")
    assert frames is None, "hook populated but MEASURED is still False"
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t5_2_claim()


def test_t5_2_measured_true_with_empty_hook_is_a_lie():
    """The flag without frames is the lie the harness exists to catch."""
    prev = qc.T5_2_REAL_CLIP_MEASURED
    try:
        qc.T5_2_REAL_CLIP_MEASURED = True
        with pytest.raises(ValueError, match="NOT MEASURED"):
            qc.t5_2_claim()
    finally:
        qc.T5_2_REAL_CLIP_MEASURED = prev


def test_t5_2_record_hook_round_trip():
    """Deleting record_t5_2_real_clip, or not writing the global, goes red."""
    prev_frames = qc.T5_2_REAL_CLIP_FRAMES
    prev_flag = qc.T5_2_REAL_CLIP_MEASURED
    prev_seed = qc.T5_2_REAL_CLIP_SEED
    plain, refined = _synthetic_pair()
    try:
        qc.record_t5_2_real_clip(plain, refined, seed=4748)
        got = qc.t5_2_real_clip_frames()
        assert got is not None
        d = qc.t5_2_refine_differential(*got)
        assert d["mad"] > 0, d
        assert d["sharpness_on"] > d["sharpness_off"], d
        qc.T5_2_REAL_CLIP_MEASURED = True
        claimed = qc.t5_2_claim()
        assert claimed["mad"] == d["mad"]
        assert claimed["seed"] == 4748
    finally:
        qc.T5_2_REAL_CLIP_FRAMES = prev_frames
        qc.T5_2_REAL_CLIP_MEASURED = prev_flag
        qc.T5_2_REAL_CLIP_SEED = prev_seed
