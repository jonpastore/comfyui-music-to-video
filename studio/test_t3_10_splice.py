"""T3-10: spliced-track duration vs mixer.bridge_seconds() arithmetic.

docs/TRD-3 §4.3: a span within a crossfade of either edge once deleted
audio and lengthened the song — 20 s spliced at 0.1 s came back 20.193 s.
QC checks the artefact against mixer's own prediction, not a restated
formula. T8-6/T8-9 assert at splice time; this asserts on the file.

Both directions, or the check is untested in the direction that matters.
A change to bridge_seconds must move the expected duration.
"""
import os
import subprocess

import pytest

from conftest import _real_module

import qc


mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"


def _ffmpeg(args):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *args],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r


def _tone(path, seconds, freq=440):
    _ffmpeg([
        "-f", "lavfi",
        "-i", f"sine=frequency={freq}:sample_rate=44100:duration={seconds}",
        "-c:a", "libmp3lame", "-b:a", "192k", path,
    ])
    return path


def _bind_real_mixer(monkeypatch):
    """qc.py imported the session stub. T3-10 measures real files."""
    monkeypatch.setattr(qc, "mixer", mixer)


def _splice_finding(path, expect):
    found = [f for f in qc.check_splice(path, expect)
             if f["check"] == "splice_duration"]
    assert found, "T3-10 did not emit splice_duration"
    return found[0]


def test_t3_10_check_splice_is_the_measurement_surface():
    """T3-30: path + expect, no database. Presence of a helper that
    never runs stays green without measuring a splice."""
    assert hasattr(qc, "check_splice")
    src = open(os.path.join(os.path.dirname(__file__), "qc.py"),
               encoding="utf-8").read()
    assert "mixer.spliced_duration" in src
    assert "mixer.SPLICE_DURATION_TOLERANCE" in src
    assert "<= mixer.SPLICE_DURATION_TOLERANCE" in src
    mix_src = open(os.path.join(os.path.dirname(__file__), "mixer.py"),
                   encoding="utf-8").read()
    assert "def spliced_duration" in mix_src
    assert "bridge_seconds" in mix_src[mix_src.index("def spliced_duration"):]


def test_t3_10_tolerance_is_the_named_constant():
    """Imported, not restated. Two copies of 0.12 drift into a check
    that passes while its twin fails — the T3-11 lesson."""
    assert mixer.SPLICE_DURATION_TOLERANCE == 0.12


@pytest.mark.slow
def test_t3_10_correct_edge_splice_passes(tmp_path, monkeypatch):
    """Positive half: a bridge sized by bridge_seconds keeps the
    original length. Start edge and end edge, or it is not either edge."""
    _bind_real_mixer(monkeypatch)
    src = _tone(str(tmp_path / "src.mp3"), 20.0)
    src_len = mixer.probe(src)["duration"]
    for start, end, tag in ((0.0, 1.0, "head"), (src_len - 1.0, src_len, "tail")):
        want = mixer.bridge_seconds(src, start, end)
        bridge = _tone(str(tmp_path / f"br_{tag}.mp3"), want, freq=880)
        out = str(tmp_path / f"ok_{tag}.mp3")
        mixer.splice_bridge(src, bridge, out, start, end)
        row = _splice_finding(out, {"source": src, "start": start, "end": end,
                                    "bridge_len": want})
        assert row["verdict"] == qc.PASS, (tag, row)
        assert row["unit"] == "s"
        gap = abs(row["measured"] - row["expected"])
        assert gap <= mixer.SPLICE_DURATION_TOLERANCE, (tag, row)


@pytest.mark.slow
def test_t3_10_lengthened_20s_at_0_1_is_rejected(tmp_path, monkeypatch):
    """THE case: 20 s spliced at 0.1 s came back 20.193 s. That file
    is a reject. A check that only ever passes is not this criterion."""
    _bind_real_mixer(monkeypatch)
    src = _tone(str(tmp_path / "src20.mp3"), 20.0)
    bad = _tone(str(tmp_path / "long.mp3"), 20.193)
    src_len = mixer.probe(src)["duration"]
    bad_len = mixer.probe(bad)["duration"]
    assert abs(src_len - 20.0) <= 0.15, src_len
    assert abs(bad_len - 20.193) <= 0.15, bad_len
    assert abs(bad_len - src_len) > mixer.SPLICE_DURATION_TOLERANCE

    row = _splice_finding(bad, {"source": src, "start": 0.1, "end": 1.1})
    assert row["verdict"] == qc.REJECT, row
    assert row["unit"] == "s"
    assert abs(row["measured"] - bad_len) <= 0.001, row
    predicted = mixer.spliced_duration(src, 0.1, 1.1)
    assert abs(row["expected"] - predicted) <= 0.001, row
    assert abs(predicted - src_len) <= 0.001, predicted


@pytest.mark.slow
def test_t3_10_bridge_seconds_moves_the_expected(tmp_path, monkeypatch):
    """A change to bridge_seconds moves the outcome. Calling it and
    throwing the result away stays green forever."""
    _bind_real_mixer(monkeypatch)
    src = _tone(str(tmp_path / "src.mp3"), 4.0)
    start, end = 1.0, 2.0
    want = mixer.bridge_seconds(src, start, end)
    out = _tone(str(tmp_path / "out.mp3"), mixer.probe(src)["duration"])
    baseline = _splice_finding(out, {"source": src, "start": start, "end": end,
                                     "bridge_len": want})

    real_bs = mixer.bridge_seconds

    def _shifted(mp3_path, a, b, xfade=mixer.SPLICE_XFADE):
        return real_bs(mp3_path, a, b, xfade=xfade) + 0.5

    monkeypatch.setattr(mixer, "bridge_seconds", _shifted)
    moved = _splice_finding(out, {"source": src, "start": start, "end": end,
                                  "bridge_len": want})
    assert abs(moved["expected"] - (baseline["expected"] - 0.5)) <= 0.001, (
        baseline, moved)
    assert moved["expected"] != baseline["expected"]


def test_t3_10_run_audio_forwards_to_check_splice(monkeypatch):
    """qc.run is the measurement surface (T3-30). A helper the route
    never calls is not the check."""
    src = open(os.path.join(os.path.dirname(__file__), "qc.py"),
               encoding="utf-8").read()
    audio_fn = src[src.index("def check_audio"): src.index("def _norm_ref")]
    assert "check_splice" in audio_fn
    run_fn = src[src.index("def run("): src.index("def worst(")]
    assert "check_audio" in run_fn
