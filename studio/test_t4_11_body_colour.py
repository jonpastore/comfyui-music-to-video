"""T4-11: body-colour render differential harness.

docs/TRD-4 T4-11: charcoal positive wording vs previous negating wording.
Patchy/two-tone region variance must decrease. Missing pair raises
NOT MEASURED. skip is not a reading.

A synthetic two-tone vs uniform pair proves the metric can fail. A real
GPU charcoal-vs-negating pair is a separate flag; flipping it with an
empty hook is the lie. T4_11_REAL_PAIR_MEASURED stays False until that
pair is on disk. Do not flip MEASURED or render a pair here.
"""
import os
import sys

import numpy as np
import pytest
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import qc


def _uniform(h=64, w=64, value=60.0):
    """Flat charcoal-ish sheet. Deleting the fill makes variance undefined."""
    return np.full((h, w, 3), value, dtype="float64")


def _two_tone(h=64, w=64, left=40.0, right=120.0):
    """Left/right split — high region-luma variance. Not a 5090 sheet."""
    arr = np.empty((h, w, 3), dtype="float64")
    arr[:, : w // 2] = left
    arr[:, w // 2 :] = right
    return arr


def _synthetic_pair():
    """Charcoal wording → uniform; negating wording → two-tone.

    Swapping the pair, or returning the same array twice, makes
    decreased go red. It is not a GPU render.
    """
    return _uniform(), _two_tone()


def _png(path, arr):
    Image.fromarray(np.clip(arr, 0, 255).astype("uint8")).save(path)
    return str(path)


def _restore():
    return (
        qc.T4_11_REAL_PAIR,
        qc.T4_11_REAL_PAIR_MEASURED,
        qc.T4_11_REAL_PAIR_SHA256,
        qc.T4_11_REAL_PAIR_SEED,
    )


def _reset(prev):
    (qc.T4_11_REAL_PAIR, qc.T4_11_REAL_PAIR_MEASURED,
     qc.T4_11_REAL_PAIR_SHA256, qc.T4_11_REAL_PAIR_SEED) = prev


def test_t4_11_tests_do_not_skip():
    """A skip call is not a reading. Mutation: insert a skip call → red."""
    src = open(__file__, encoding="utf-8").read()
    skip_call = "pytest" + ".skip("
    skip_mark = "pytest" + ".mark.skip"
    assert skip_call not in src
    assert skip_mark not in src


def test_t4_11_hook_exists():
    """Renderer populate hook. Mutation: delete the names → red."""
    assert hasattr(qc, "T4_11_REAL_PAIR")
    assert hasattr(qc, "T4_11_REAL_PAIR_MEASURED")
    assert hasattr(qc, "T4_11_REAL_PAIR_SHA256")
    assert hasattr(qc, "BODY_COLOUR_DIFFERENTIAL")
    assert hasattr(qc, "BODY_COLOUR_METRIC")
    assert callable(qc.t4_11_real_pair)
    assert callable(qc.record_t4_11_real_pair)
    assert callable(qc.t4_11_pair_sha256)
    assert callable(qc.body_colour_region_variance)
    assert callable(qc.t4_11_body_colour_differential)
    assert callable(qc.t4_11_claim)
    assert callable(qc.accept_t4_11_gpu_pair)
    assert callable(qc.t4_11_finding)


def test_t4_11_real_pair_not_measured():
    """Body-colour on a real charcoal/negating GPU pair is NOT MEASURED.

    Flip T4_11_REAL_PAIR_MEASURED only after that pair is pinned.
    Mutation: set MEASURED True with an empty hook → this goes red.
    """
    assert qc.T4_11_REAL_PAIR_MEASURED is False, (
        "T4-11 real pair is NOT MEASURED; flip only after a GPU pair")
    assert qc.t4_11_real_pair() is None
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t4_11_claim()


def test_t4_11_missing_pair_fail_closed_not_measured():
    """Missing charcoal/negating arrays raise NOT MEASURED. Never 0.0, never skip."""
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t4_11_body_colour_differential(None, None)
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t4_11_body_colour_differential(None, _two_tone())
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.body_colour_region_variance(None)
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t4_11_claim()


def test_t4_11_missing_path_fail_closed(tmp_path):
    """A path that does not exist is NOT MEASURED, not variance 0."""
    missing = str(tmp_path / "nope.png")
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t4_11_body_colour_differential(missing, missing)
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t4_11_pair_sha256(missing, missing)


def test_t4_11_synthetic_uniform_vs_two_tone_decreases():
    """Harness: charcoal uniform < two-tone variance. Mutation: swap → red."""
    charcoal, negating = _synthetic_pair()
    d = qc.t4_11_body_colour_differential(charcoal, negating)
    assert d["variance_charcoal"] < d["variance_negating"], d
    assert d["decreased"] is True, d
    assert d["metric"] == qc.BODY_COLOUR_METRIC, d
    swapped = qc.t4_11_body_colour_differential(negating, charcoal)
    assert swapped["decreased"] is False, swapped


def test_t4_11_identical_sheets_finding_is_flag():
    """The metric can fail: identical sheets are not-decreased FLAG, not PASS."""
    charcoal, negating = _synthetic_pair()
    ok = qc.t4_11_finding(qc.t4_11_body_colour_differential(charcoal, negating))
    assert ok["check"] == qc.BODY_COLOUR_DIFFERENTIAL
    assert ok["verdict"] == qc.PASS, ok
    same = qc.t4_11_finding(qc.t4_11_body_colour_differential(charcoal, charcoal))
    assert same["verdict"] != qc.PASS, same
    assert same["measured"]["decreased"] is False


def test_t4_11_two_tone_vs_uniform_proves_metric_can_fail():
    """Synthetic two-tone (as charcoal) vs uniform does not decrease."""
    charcoal, negating = _two_tone(), _uniform()
    d = qc.t4_11_body_colour_differential(charcoal, negating)
    assert d["decreased"] is False, d
    row = qc.t4_11_finding(d)
    assert row["verdict"] == qc.FLAG, row


def test_t4_11_png_pair_decreases(tmp_path):
    """Variance is on decoded pixels. Mutation: same file twice → not decreased."""
    charcoal_p = _png(tmp_path / "charcoal.png", _uniform())
    negating_p = _png(tmp_path / "negating.png", _two_tone())
    d = qc.t4_11_body_colour_differential(charcoal_p, negating_p)
    assert d["decreased"] is True, d
    same = qc.t4_11_body_colour_differential(charcoal_p, charcoal_p)
    assert same["decreased"] is False, same


def test_t4_11_measured_true_with_empty_hook_is_a_lie():
    """The flag without a pair is the lie the harness exists to catch."""
    prev = qc.T4_11_REAL_PAIR_MEASURED
    try:
        qc.T4_11_REAL_PAIR_MEASURED = True
        with pytest.raises(ValueError, match="NOT MEASURED"):
            qc.t4_11_claim()
    finally:
        qc.T4_11_REAL_PAIR_MEASURED = prev


def test_t4_11_record_hook_round_trip():
    """Deleting record_t4_11_real_pair, or not writing the global, goes red."""
    prev = _restore()
    charcoal, negating = _synthetic_pair()
    try:
        qc.record_t4_11_real_pair(charcoal, negating, seed=5151)
        got = qc.t4_11_real_pair()
        assert got is not None
        d = qc.t4_11_body_colour_differential(*got)
        assert d["decreased"] is True, d
        qc.T4_11_REAL_PAIR_MEASURED = True
        claimed = qc.t4_11_claim()
        assert claimed["variance_charcoal"] == d["variance_charcoal"]
        assert claimed["seed"] == 5151
    finally:
        _reset(prev)
    assert qc.T4_11_REAL_PAIR_MEASURED is False


def test_t4_11_accept_harness_does_not_flip_measured(tmp_path):
    """PNG/harness must not flip T4_11_REAL_PAIR_MEASURED."""
    prev = _restore()
    try:
        charcoal_p = _png(tmp_path / "charcoal.png", _uniform())
        negating_p = _png(tmp_path / "negating.png", _two_tone())
        d = qc.accept_t4_11_gpu_pair(
            charcoal_p, negating_p, seed=1000, source="harness")
        assert d["decreased"] is True, d
        assert d.get("source") == "harness", d
        assert qc.T4_11_REAL_PAIR_MEASURED is False, (
            "harness must not flip the GPU flag")
        assert qc.t4_11_real_pair() is not None
    finally:
        _reset(prev)
    assert qc.T4_11_REAL_PAIR_MEASURED is False


def test_t4_11_accept_source_gpu_flips_only_with_pair(tmp_path):
    """source=gpu is the renderer path. Empty hook still NOT MEASURED."""
    prev = _restore()
    try:
        with pytest.raises(ValueError, match="NOT MEASURED"):
            qc.accept_t4_11_gpu_pair(None, None, seed=1000, source="gpu")
        assert qc.T4_11_REAL_PAIR_MEASURED is False

        charcoal_p = _png(tmp_path / "charcoal.png", _uniform())
        negating_p = _png(tmp_path / "negating.png", _two_tone())
        d = qc.accept_t4_11_gpu_pair(
            charcoal_p, negating_p, seed=1000, source="gpu")
        assert d["decreased"] is True, d
        assert qc.T4_11_REAL_PAIR_MEASURED is True
        claimed = qc.t4_11_claim()
        assert claimed["variance_charcoal"] == d["variance_charcoal"]
        assert claimed["seed"] == 1000
    finally:
        _reset(prev)
    assert qc.T4_11_REAL_PAIR_MEASURED is False


def test_t4_11_wrong_bytes_are_not_the_measured_pair(tmp_path):
    """A different file at the hook is NOT MEASURED. Mutation: drop pin → red."""
    prev = _restore()
    try:
        charcoal_p = _png(tmp_path / "charcoal.png", _uniform())
        negating_p = _png(tmp_path / "negating.png", _two_tone())
        qc.record_t4_11_real_pair(charcoal_p, negating_p, seed=1)
        qc.T4_11_REAL_PAIR_MEASURED = True
        qc.T4_11_REAL_PAIR_SHA256 = ("0" * 64, "0" * 64)
        with pytest.raises(ValueError, match="NOT MEASURED"):
            qc.t4_11_claim()
    finally:
        _reset(prev)


def test_t4_11_real_pair_measured_stays_false():
    """Hold: do not flip MEASURED without a GPU pair on disk."""
    assert qc.T4_11_REAL_PAIR_MEASURED is False
    assert qc.t4_11_real_pair() is None
