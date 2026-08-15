"""T5-5: peak VRAM of the shipped refine variant, measured on the box.

docs/TRD-5 T5-5: recorded in models.py beside the 23.4/23.9 base figure.
A number quoted rather than measured fails review. skip is not a reading.
Missing samples raise NOT MEASURED.

The 23.4/23.9 figure is the BASE render. Copying it onto refine_peak with
origin=measured and same_as_base=True is the quote this harness exists to
catch. Graph-only is T5-1. B-does-not-fit is T5-6.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from conftest import _real_module

import models

pipeline = _real_module("pipeline")
assert pipeline is not None, "real pipeline.py failed to import"


def _notes():
    return " ".join(models.CATALOG["ltx25"]["notes"])


def test_t5_5_tests_do_not_skip():
    """A skip call is not a reading. Mutation: insert a skip call → red."""
    src = open(__file__, encoding="utf-8").read()
    skip_call = "pytest" + ".skip("
    skip_mark = "pytest" + ".mark.skip"
    assert skip_call not in src
    assert skip_mark not in src


def test_t5_5_empty_samples_raise_not_measured():
    """No samples is NOT MEASURED, never peak 0.0, never the base 23.4."""
    with pytest.raises(ValueError, match="NOT MEASURED"):
        pipeline.peak_from_samples(None)
    with pytest.raises(ValueError, match="NOT MEASURED"):
        pipeline.peak_from_samples([])
    with pytest.raises(ValueError, match="NOT MEASURED"):
        pipeline.peak_from_samples([None, {}])
    with pytest.raises(ValueError, match="NOT MEASURED"):
        pipeline.t5_5_claim()


def test_t5_5_harness_peak_is_max_used_gb():
    """Harness: peak is the max used_gb in the sample list.

    Mutation: return the first sample, or 23.4, → this goes red.
    """
    samples = [
        {"used_gb": 18.1, "total_gb": 23.9, "host": "cerberus"},
        {"used_gb": 22.7, "total_gb": 23.9, "host": "cerberus"},
        {"used_gb": 21.0, "total_gb": 23.9, "host": "cerberus"},
    ]
    peak = pipeline.peak_from_samples(samples)
    assert peak["peak_gb"] == 22.7, peak
    assert peak["total_gb"] == 23.9, peak
    assert peak["host"] == "cerberus", peak
    assert peak["n_samples"] == 3, peak
    assert peak["origin"] == "measured", peak


def test_t5_5_measured_true_with_empty_hook_is_a_lie():
    """The flag without samples is the lie the harness exists to catch."""
    prev_flag = pipeline.T5_5_MEASURED
    prev_samples = pipeline.T5_5_SAMPLES
    try:
        pipeline.T5_5_SAMPLES = None
        pipeline.T5_5_MEASURED = True
        with pytest.raises(ValueError, match="NOT MEASURED"):
            pipeline.t5_5_claim()
    finally:
        pipeline.T5_5_MEASURED = prev_flag
        pipeline.T5_5_SAMPLES = prev_samples


def test_t5_5_record_hook_round_trip():
    """Deleting record_t5_5_peak, or not writing the samples, goes red."""
    prev_flag = pipeline.T5_5_MEASURED
    prev_samples = pipeline.T5_5_SAMPLES
    samples = [
        {"used_gb": 19.2, "free_gb": 4.7, "total_gb": 23.9,
         "host": "100.103.148.120"},
        {"used_gb": 23.1, "free_gb": 0.8, "total_gb": 23.9,
         "host": "100.103.148.120"},
    ]
    try:
        pipeline.record_t5_5_peak(samples, variant="A", resolution="832x480")
        got = pipeline.t5_5_reading()
        assert got["peak_gb"] == 23.1, got
        assert got["variant"] == "A", got
        assert got["n_samples"] == 2, got
        pipeline.T5_5_MEASURED = True
        claimed = pipeline.t5_5_claim()
        assert claimed["peak_gb"] == 23.1, claimed
        assert claimed["variant"] == "A", claimed
    finally:
        pipeline.T5_5_MEASURED = prev_flag
        pipeline.T5_5_SAMPLES = prev_samples


def test_t5_5_catalogue_does_not_quote_the_base_figure():
    """origin=measured + same_as_base / no samples is a quoted 23.4.

    Mutation: copy the base 23.4/23.9 onto refine_peak and mark it
    measured → this goes red.
    """
    peak = models.refine_peak("ltx25")
    assert peak["variant"] == "A", peak
    quoted = (
        peak.get("origin") == "measured"
        and (
            peak.get("same_as_base") is True
            or not peak.get("n_samples")
            or not peak.get("host")
            or not peak.get("date")
        )
    )
    assert not quoted, (
        "T5-5: a number quoted rather than measured fails review: %r" % peak
    )
    if peak.get("origin") == "measured":
        assert isinstance(peak.get("peak_gb"), (int, float))
        assert peak["peak_gb"] > 0
        assert peak.get("n_samples", 0) >= 2
    else:
        assert peak.get("origin") == "not_measured", peak
        with pytest.raises(ValueError, match="NOT MEASURED"):
            pipeline.t5_5_claim()


def test_t5_5_notes_sit_beside_23_4_and_do_not_quote_it():
    """The refine sentence lives next to 23.4/23.9. It must not claim
    A's peak is that figure unless a sample hook populated it.
    """
    neighbour = None
    for note in models.CATALOG["ltx25"]["notes"]:
        if "23.4" in note and "23.9" in note:
            neighbour = note
            break
    assert neighbour is not None, "base 23.4/23.9 figure missing from ltx25 notes"
    assert "T5-5" in neighbour, neighbour
    blob = neighbour.lower()
    assert "peak is that same measured 23.4" not in blob, neighbour
    peak = models.refine_peak("ltx25")
    if peak.get("origin") != "measured":
        assert "not measured" in blob, neighbour


def test_t5_5_free_vram_and_sample_vram_exist():
    """Measure with pipeline.free_vram before the render (T9-15 / T5-5)."""
    assert hasattr(pipeline, "free_vram")
    assert callable(pipeline.free_vram)
    assert hasattr(pipeline, "sample_vram")
    assert callable(pipeline.sample_vram)


def test_t5_5_submit_records_pre_render_vram(monkeypatch, tmp_path):
    """T9-15 consumed: a submit result carries the pre-render reading.

    Mutation: drop LAST_RENDER_VRAM → this goes red.
    Does not talk to a live box; sample_vram is stubbed.
    """
    readings = [
        {"used_gb": 4.0, "free_gb": 19.9, "total_gb": 23.9,
         "host": "100.103.148.120", "at": 1.0},
        {"used_gb": 21.5, "free_gb": 2.4, "total_gb": 23.9,
         "host": "100.103.148.120", "at": 2.0},
        {"used_gb": 20.0, "free_gb": 3.9, "total_gb": 23.9,
         "host": "100.103.148.120", "at": 3.0},
    ]
    idx = {"i": 0}

    def fake_sample():
        i = min(idx["i"], len(readings) - 1)
        rec = readings[i]
        idx["i"] += 1
        return rec

    monkeypatch.setattr(pipeline, "sample_vram", fake_sample)
    monkeypatch.setattr(pipeline, "RENDER_BACKEND", "comfy")
    monkeypatch.setattr(pipeline.gpu, "preflight", lambda progress=None: None)
    monkeypatch.setattr(pipeline, "submit_dir", lambda *a, **k: ["pid"])
    monkeypatch.setattr(pipeline, "collect", lambda *a, **k: [])
    monkeypatch.setattr(pipeline, "_stamp", lambda *a, **k: None)

    wf = tmp_path / "wf.json"
    wf.write_text('{"1": {"inputs": {"filename_prefix": "clip_t55/c"}}}')
    pipeline._submit_and_collect(str(tmp_path), "clip_t55", "*.mp4", None)
    rec = pipeline.LAST_RENDER_VRAM
    assert rec is not None, "submit did not record a VRAM reading"
    assert rec["pre"] is not None, rec
    assert rec["pre"]["used_gb"] == 4.0, rec
    assert rec["peak"]["peak_gb"] == 21.5, rec
    assert rec["peak"]["origin"] == "measured", rec
