"""T1-9b: a drawn gain curve survives to the audio.

docs/TRD-1 §5.0(c) / T1-9b. The curve already reaches the filter graph
(T1-9a). This is the RMS-per-second differential: mix a constant-amplitude
sine with a -12 dB → 0 dB ramp through mix_audio, and the measured slope
must match the drawn one within mixer.GAIN_CURVE_SLOPE_TOLERANCE.

A constant sine is required. RMS slope on program material is not a
proxy for gain — the source would move the same number the curve does.

Asserted through mix_audio (the shared entry both render paths share
item_chains with), not _audio_chain. Leaving per-item loudnorm on
flattens the slope past the same bound.
"""
import os
import subprocess

import automation
from conftest import _real_module


mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"

# Drawn endpoints. Duration is the item length; t is item-relative.
_SPAN_S = 6.0
_START_DB = -12.0
_END_DB = 0.0
_CURVE = [(0.0, _START_DB), (_SPAN_S, _END_DB)]
_DRAWN_SLOPE = (_END_DB - _START_DB) / _SPAN_S  # +2.0 dB/s


def _sine(path, seconds, freq=1000):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
         "-c:a", "pcm_s16le", path],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def _item(audio, auto):
    return {"audio": audio, "transition": "cut", "secs": 0.0, "automation": auto}


def test_t1_9b_rms_per_second_refuses_a_subsecond_file(tmp_path):
    """An empty series would make any slope check pass. Refuse instead."""
    src = str(tmp_path / "short.wav")
    _sine(src, 0.3)
    try:
        mixer.rms_per_second(src)
    except RuntimeError as e:
        assert "complete second" in str(e), e
    else:
        raise AssertionError("a sub-second file produced an RMS series")


def test_t1_9b_drawn_gain_curve_slope_reaches_the_audio(tmp_path):
    """mix_audio of a -12→0 ramp on a flat sine: RMS/s slope matches drawn."""
    src = str(tmp_path / "sine.wav")
    out = str(tmp_path / "curved.mp3")
    _sine(src, _SPAN_S)
    stored = automation.save(1, "gain_db", _CURVE)
    assert stored, "T1-9b is vacuous without a stored curve"
    auto = automation.item_audio(1)
    assert auto["suppress_loudnorm"] is True, auto
    assert auto["frags"], auto

    mixer.mix_audio([_item(src, auto)], out)
    buckets = mixer.rms_per_second(out)
    assert len(buckets) >= 4, f"need several whole seconds, got {len(buckets)}"
    measured = mixer.rms_slope(buckets)
    assert abs(measured - _DRAWN_SLOPE) <= mixer.GAIN_CURVE_SLOPE_TOLERANCE, (
        f"drawn slope {_DRAWN_SLOPE:.3f} dB/s, measured {measured:.3f} "
        f"from { [round(v, 2) for v in buckets] }; "
        f"tolerance {mixer.GAIN_CURVE_SLOPE_TOLERANCE}"
    )


def test_t1_9b_per_item_loudnorm_flattens_the_slope(tmp_path):
    """The mutation T1-9b is written to catch: loudnorm left on, slope dies.

    Same sine, same stored fragment, suppress_loudnorm forced off so the
    item keeps parse_effects' loudnorm and the master does not engage.
    The happy-path bound must not also pass this render.
    """
    src = str(tmp_path / "sine.wav")
    out = str(tmp_path / "flattened.mp3")
    _sine(src, _SPAN_S)
    frag = automation.fragment("gain_db", _CURVE)
    auto = {"frags": [frag], "suppress_loudnorm": False}

    mixer.mix_audio([_item(src, auto)], out)
    measured = mixer.rms_slope(mixer.rms_per_second(out))
    assert abs(measured - _DRAWN_SLOPE) > mixer.GAIN_CURVE_SLOPE_TOLERANCE, (
        f"per-item loudnorm left on still measured {measured:.3f} dB/s "
        f"against drawn {_DRAWN_SLOPE:.3f}; T1-9b cannot fail"
    )
