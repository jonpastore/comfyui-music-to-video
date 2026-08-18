"""T3-37: D7 pair look harness — lips + her + LTX blocking.

docs/TRD-3 T3-37: same-scene LTX-only vs LTX+s2v-control. Missing pair
raises NOT MEASURED. skip is not a reading. Do not rank on warm px.
Silent hop omit (no control_video, no finding) is refused.

A synthetic / lavfi pair proves the metric can fail. A real GPU pair is
a separate flag; flipping it with an empty hook is the lie.
T3_37_REAL_PAIR_MEASURED stays False until that pair is on disk.
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

import qc


def _synthetic_pair():
    """Same scene: hop adds motion relative to LTX.

    Deleting the offset, or returning the same array twice, makes MAD
    go red. It is not a 5090 clip.
    """
    n, h, w = 2, 16, 16
    yy, xx = np.ogrid[0:h, 0:w]
    ramp = (xx + yy).astype("float64")
    ltx = np.broadcast_to(ramp[..., None], (n, h, w, 3)).copy()
    hop = ltx.copy()
    hop[:, 0::2, 0::2] += 40.0
    hop[:, 1::2, 1::2] += 40.0
    return ltx, hop


def _lavfi_mp4(path, filt):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", filt,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


def _restore():
    return (
        qc.T3_37_REAL_PAIR,
        qc.T3_37_REAL_PAIR_MEASURED,
        qc.T3_37_REAL_PAIR_SHA256,
        qc.T3_37_REAL_PAIR_SEED,
    )


def _reset(prev):
    (qc.T3_37_REAL_PAIR, qc.T3_37_REAL_PAIR_MEASURED,
     qc.T3_37_REAL_PAIR_SHA256, qc.T3_37_REAL_PAIR_SEED) = prev


def test_t3_37_tests_do_not_skip():
    """A skip call is not a reading. Mutation: insert a skip call → red."""
    src = open(__file__, encoding="utf-8").read()
    skip_call = "pytest" + ".skip("
    skip_mark = "pytest" + ".mark.skip"
    assert skip_call not in src
    assert skip_mark not in src


def test_t3_37_hook_exists():
    """Renderer populate hook. Mutation: delete the names → red."""
    assert hasattr(qc, "T3_37_REAL_PAIR")
    assert hasattr(qc, "T3_37_REAL_PAIR_MEASURED")
    assert hasattr(qc, "T3_37_REAL_PAIR_SHA256")
    assert hasattr(qc, "D7_LOOK")
    assert hasattr(qc, "D7_HOP_OMIT")
    assert callable(qc.t3_37_real_pair)
    assert callable(qc.record_t3_37_real_pair)
    assert callable(qc.t3_37_pair_sha256)
    assert callable(qc.t3_37_d7_look_differential)
    assert callable(qc.t3_37_claim)
    assert callable(qc.accept_t3_37_gpu_pair)
    assert callable(qc.t3_37_finding)
    assert callable(qc.t3_37_hop_omit_finding)
    assert callable(qc.check_d7_hop_omit)
    assert callable(qc.t3_37_require_hop_finding)


def test_t3_37_real_pair_not_measured():
    """D7 look on a real same-scene GPU pair is NOT MEASURED.

    Flip T3_37_REAL_PAIR_MEASURED only after that pair is pinned.
    Mutation: set MEASURED True with an empty hook → this goes red.
    """
    assert qc.T3_37_REAL_PAIR_MEASURED is False, (
        "T3-37 real pair is NOT MEASURED; flip only after a GPU pair")
    assert qc.t3_37_real_pair() is None
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t3_37_claim()


def test_t3_37_missing_pair_fail_closed_not_measured():
    """Missing LTX/hop arrays raise NOT MEASURED. Never 0.0, never skip."""
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t3_37_d7_look_differential(None, None)
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t3_37_d7_look_differential(None, _synthetic_pair()[1])
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t3_37_claim()


def test_t3_37_missing_video_path_fail_closed(tmp_path):
    """A path that does not exist is NOT MEASURED, not MAD 0."""
    missing = str(tmp_path / "nope.mp4")
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t3_37_d7_look_differential(missing, missing)
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t3_37_pair_sha256(missing, missing)


def test_t3_37_refuses_warm_px_ranking():
    """Mutation: mark D7 built from a warm-px score → red."""
    ltx, hop = _synthetic_pair()
    for metric in ("warm_px", "warm-px", "warm", "warmpx"):
        with pytest.raises(ValueError, match="warm_px"):
            qc.t3_37_d7_look_differential(ltx, hop, metric=metric)
    with pytest.raises(ValueError, match="warm_px"):
        qc.accept_t3_37_gpu_pair(ltx, hop, metric="warm_px", source="harness")
    with pytest.raises(ValueError, match="warm_px"):
        qc.t3_37_finding({"mad": 1.0, "lips_moved": True, "metric": "warm_px"})


def test_t3_37_synthetic_pair_mad_gt_zero():
    """Harness: MAD > 0 on a decode pair. Mutation: identical → MAD == 0."""
    ltx, hop = _synthetic_pair()
    d = qc.t3_37_d7_look_differential(ltx, hop)
    assert d["mad"] > 0, d
    assert d["lips_moved"] is True, d
    assert d["metric"] == "lips_motion", d
    same = qc.t3_37_d7_look_differential(ltx, ltx)
    assert same["mad"] == 0.0, same
    assert same["lips_moved"] is False, same


def test_t3_37_identical_frames_finding_is_flag():
    """The finding can fail: identical frames are MAD 0 FLAG, not PASS."""
    ltx, hop = _synthetic_pair()
    ok = qc.t3_37_finding(qc.t3_37_d7_look_differential(ltx, hop))
    assert ok["check"] == qc.D7_LOOK
    assert ok["verdict"] == qc.PASS, ok
    bad = qc.t3_37_finding(qc.t3_37_d7_look_differential(ltx, ltx))
    assert bad["verdict"] != qc.PASS, bad
    assert bad["measured"]["mad"] == 0.0


def test_t3_37_decoded_lavfi_pair_mad_gt_zero(tmp_path):
    """MAD is on decoded frames. Mutation: same file twice → MAD == 0."""
    ltx_p = _lavfi_mp4(
        str(tmp_path / "ltx.mp4"), "color=c=gray:s=32x32:r=8:d=0.25")
    hop_p = _lavfi_mp4(
        str(tmp_path / "hop.mp4"), "testsrc2=size=32x32:rate=8:duration=0.25")
    d = qc.t3_37_d7_look_differential(ltx_p, hop_p)
    assert d["mad"] > 0, d
    same = qc.t3_37_d7_look_differential(ltx_p, ltx_p)
    assert same["mad"] == 0.0, same


def test_t3_37_measured_true_with_empty_hook_is_a_lie():
    """The flag without a pair is the lie the harness exists to catch."""
    prev = qc.T3_37_REAL_PAIR_MEASURED
    try:
        qc.T3_37_REAL_PAIR_MEASURED = True
        with pytest.raises(ValueError, match="NOT MEASURED"):
            qc.t3_37_claim()
    finally:
        qc.T3_37_REAL_PAIR_MEASURED = prev


def test_t3_37_record_hook_round_trip():
    """Deleting record_t3_37_real_pair, or not writing the global, goes red."""
    prev = _restore()
    ltx, hop = _synthetic_pair()
    try:
        qc.record_t3_37_real_pair(ltx, hop, seed=5151)
        got = qc.t3_37_real_pair()
        assert got is not None
        d = qc.t3_37_d7_look_differential(*got)
        assert d["mad"] > 0, d
        qc.T3_37_REAL_PAIR_MEASURED = True
        claimed = qc.t3_37_claim()
        assert claimed["mad"] == d["mad"]
        assert claimed["seed"] == 5151
    finally:
        _reset(prev)
    assert qc.T3_37_REAL_PAIR_MEASURED is False


def test_t3_37_accept_harness_does_not_flip_measured(tmp_path):
    """Lavfi/harness must not flip T3_37_REAL_PAIR_MEASURED."""
    prev = _restore()
    try:
        ltx_p = _lavfi_mp4(
            str(tmp_path / "ltx.mp4"), "color=c=gray:s=32x32:r=8:d=0.25")
        hop_p = _lavfi_mp4(
            str(tmp_path / "hop.mp4"), "testsrc2=size=32x32:rate=8:duration=0.25")
        d = qc.accept_t3_37_gpu_pair(
            ltx_p, hop_p, seed=1000, source="harness")
        assert d["mad"] > 0, d
        assert d.get("source") == "harness", d
        assert qc.T3_37_REAL_PAIR_MEASURED is False, (
            "lavfi/harness must not flip the GPU flag")
        assert qc.t3_37_real_pair() is not None
    finally:
        _reset(prev)
    assert qc.T3_37_REAL_PAIR_MEASURED is False


def test_t3_37_accept_source_gpu_flips_only_with_pair(tmp_path):
    """source=gpu is the renderer path. Empty hook still NOT MEASURED."""
    prev = _restore()
    try:
        with pytest.raises(ValueError, match="NOT MEASURED"):
            qc.accept_t3_37_gpu_pair(None, None, seed=1000, source="gpu")
        assert qc.T3_37_REAL_PAIR_MEASURED is False

        ltx_p = _lavfi_mp4(
            str(tmp_path / "ltx.mp4"), "color=c=gray:s=32x32:r=8:d=0.25")
        hop_p = _lavfi_mp4(
            str(tmp_path / "hop.mp4"), "testsrc2=size=32x32:rate=8:duration=0.25")
        d = qc.accept_t3_37_gpu_pair(ltx_p, hop_p, seed=1000, source="gpu")
        assert d["mad"] > 0, d
        assert qc.T3_37_REAL_PAIR_MEASURED is True
        claimed = qc.t3_37_claim()
        assert claimed["mad"] == d["mad"]
        assert claimed["seed"] == 1000
    finally:
        _reset(prev)
    assert qc.T3_37_REAL_PAIR_MEASURED is False


def test_t3_37_wrong_bytes_are_not_the_measured_pair(tmp_path):
    """A different file at the hook is NOT MEASURED. Mutation: drop pin → red."""
    prev = _restore()
    try:
        ltx_p = _lavfi_mp4(
            str(tmp_path / "ltx.mp4"), "color=c=gray:s=32x32:r=8:d=0.25")
        hop_p = _lavfi_mp4(
            str(tmp_path / "hop.mp4"), "testsrc2=size=32x32:rate=8:duration=0.25")
        qc.record_t3_37_real_pair(ltx_p, hop_p, seed=1)
        qc.T3_37_REAL_PAIR_MEASURED = True
        qc.T3_37_REAL_PAIR_SHA256 = ("0" * 64, "0" * 64)
        with pytest.raises(ValueError, match="NOT MEASURED"):
            qc.t3_37_claim()
    finally:
        _reset(prev)


def test_t3_37_hop_omit_emits_finding():
    """Fallback s2v-from-still is a finding. Mutation: return [] → red."""
    row = qc.t3_37_hop_omit_finding(
        "scene1.mp4",
        expect={"needs_lip_sync": True, "hop_omitted": True})
    assert row["check"] == qc.D7_HOP_OMIT
    assert row["verdict"] == qc.FLAG
    assert row["measured"]["hop_omitted"] is True

    found = qc.check_d7_hop_omit(
        "scene1.mp4",
        {"needs_lip_sync": True, "hop_omitted": True})
    assert found and found[0]["check"] == qc.D7_HOP_OMIT

    silent = qc.check_d7_hop_omit(
        "scene1.mp4",
        {"needs_lip_sync": True, "control_video": "ltx_frames/",
         "hop_omitted": False})
    assert silent == []

    unmarked = qc.check_d7_hop_omit("scene1.mp4", {"needs_lip_sync": False})
    assert unmarked == []


def test_t3_37_hop_omit_s2v_from_still_without_control_video():
    """s2v_from_still + no control_video is hop omit."""
    found = qc.check_d7_hop_omit(
        "scene1.mp4",
        {"needs_lip_sync": True, "s2v_from_still": True, "control_video": None})
    assert found and found[0]["check"] == qc.D7_HOP_OMIT


def test_t3_37_silent_hop_omit_refused():
    """Mutation: hop omitted with no finding → red."""
    expect = {"needs_lip_sync": True, "hop_omitted": True}
    with pytest.raises(ValueError, match="hop omitted with no finding"):
        qc.t3_37_require_hop_finding([], expect)
    with pytest.raises(ValueError, match="hop omitted with no finding"):
        qc.t3_37_require_hop_finding(
            [{"check": qc.D7_LOOK, "verdict": qc.PASS}], expect)
    rows = qc.check_d7_hop_omit("scene1.mp4", expect)
    assert qc.t3_37_require_hop_finding(rows, expect) == rows


def test_t3_37_real_pair_measured_stays_false():
    """Hold: do not flip MEASURED without a GPU pair on disk."""
    assert qc.T3_37_REAL_PAIR_MEASURED is False
    assert qc.t3_37_real_pair() is None
