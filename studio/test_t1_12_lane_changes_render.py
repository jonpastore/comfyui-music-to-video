"""T1-12: a drawn lane that does not change the render is a failure.

docs/TRD-1 §5 T1-12. Per remaining lane (gain_db is T1-9b): mix the same
item with the curve and with it flat through mix_audio, and the measured
output differs — pan by L/R energy ratio, lowpass/highpass by band energy.

A constant-amplitude source is required. Programme material would move
the same number the curve does. Asserted through mix_audio (the shared
entry both render paths share item_chains with), not _audio_chain.

A lane wired into the UI and not into the graph is how _apply_beatmatch
was unreachable for a whole session.
"""
import subprocess

import automation
from conftest import _real_module


mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"

_SPAN_S = 4.0
_PAN_CURVE = [(0.0, 0.0), (_SPAN_S, 1.0)]
_LOWPASS_CURVE = [(0.0, 400.0), (_SPAN_S, 400.0)]
_HIGHPASS_CURVE = [(0.0, 4000.0), (_SPAN_S, 4000.0)]
# High-band around the 8 kHz tone; low-band around the 200 Hz tone.
_HIGH_BAND = (4000.0, 12000.0)
_LOW_BAND = (80.0, 400.0)


def _sine(path, seconds, freq=1000):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
         "-c:a", "pcm_s16le", path],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def _two_tone(path, seconds, lo=200, hi=8000):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i",
         f"sine=frequency={lo}:sample_rate=48000:duration={seconds}",
         "-f", "lavfi", "-i",
         f"sine=frequency={hi}:sample_rate=48000:duration={seconds}",
         "-filter_complex",
         "[0][1]amix=inputs=2:normalize=0,aformat=channel_layouts=stereo",
         "-c:a", "pcm_s16le", path],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def _item(audio, auto):
    return {
        "audio": audio,
        "transition": "cut",
        "secs": 0.0,
        "effects_json": {"loudnorm": False},
        "automation": auto,
    }


def _mix(path, auto, out):
    mixer.mix_audio([_item(path, auto)], out)


def test_t1_12_pan_changes_lr_energy(tmp_path):
    """Drawn pan 0→+1 vs flat: L/(L+R) must move toward the right."""
    src = str(tmp_path / "sine.wav")
    curved = str(tmp_path / "pan_curved.mp3")
    flat = str(tmp_path / "pan_flat.mp3")
    _sine(src, _SPAN_S)
    stored = automation.save(1201, "pan", _PAN_CURVE)
    assert stored, "T1-12 is vacuous without a stored pan curve"
    auto = automation.item_audio(1201)
    assert auto["frags"], auto

    _mix(src, auto, curved)
    _mix(src, {"frags": [], "suppress_loudnorm": False}, flat)
    ratio_c = mixer.lr_energy_ratio(curved)
    ratio_f = mixer.lr_energy_ratio(flat)
    assert abs(ratio_c - ratio_f) >= mixer.LR_ENERGY_DELTA, (
        f"pan curve L/(L+R)={ratio_c:.3f} vs flat {ratio_f:.3f}; "
        f"delta {abs(ratio_c - ratio_f):.3f} < {mixer.LR_ENERGY_DELTA}"
    )
    assert ratio_c < ratio_f, (
        f"0→+1 pan should drop L share, got curved {ratio_c:.3f} "
        f"flat {ratio_f:.3f}"
    )


def test_t1_12_lowpass_changes_high_band(tmp_path):
    """Drawn 400 Hz lowpass vs flat: 8 kHz band energy must drop."""
    src = str(tmp_path / "tones.wav")
    curved = str(tmp_path / "lp_curved.mp3")
    flat = str(tmp_path / "lp_flat.mp3")
    _two_tone(src, _SPAN_S)
    stored = automation.save(1202, "lowpass_hz", _LOWPASS_CURVE)
    assert stored, "T1-12 is vacuous without a stored lowpass curve"
    auto = automation.item_audio(1202)
    assert auto["frags"], auto

    _mix(src, auto, curved)
    _mix(src, {"frags": [], "suppress_loudnorm": False}, flat)
    lo, hi = _HIGH_BAND
    e_c = mixer.band_energy(curved, lo, hi)
    e_f = mixer.band_energy(flat, lo, hi)
    assert e_f > 0, "flat high-band energy is 0; the fixture is silent"
    assert e_f / e_c >= mixer.BAND_ENERGY_RATIO, (
        f"lowpass high-band curved={e_c:.6f} flat={e_f:.6f} "
        f"ratio {e_f / e_c:.2f} < {mixer.BAND_ENERGY_RATIO}"
    )


def test_t1_12_highpass_changes_low_band(tmp_path):
    """Drawn 4 kHz highpass vs flat: 200 Hz band energy must drop."""
    src = str(tmp_path / "tones.wav")
    curved = str(tmp_path / "hp_curved.mp3")
    flat = str(tmp_path / "hp_flat.mp3")
    _two_tone(src, _SPAN_S)
    stored = automation.save(1203, "highpass_hz", _HIGHPASS_CURVE)
    assert stored, "T1-12 is vacuous without a stored highpass curve"
    auto = automation.item_audio(1203)
    assert auto["frags"], auto

    _mix(src, auto, curved)
    _mix(src, {"frags": [], "suppress_loudnorm": False}, flat)
    lo, hi = _LOW_BAND
    e_c = mixer.band_energy(curved, lo, hi)
    e_f = mixer.band_energy(flat, lo, hi)
    assert e_f > 0, "flat low-band energy is 0; the fixture is silent"
    assert e_f / e_c >= mixer.BAND_ENERGY_RATIO, (
        f"highpass low-band curved={e_c:.6f} flat={e_f:.6f} "
        f"ratio {e_f / e_c:.2f} < {mixer.BAND_ENERGY_RATIO}"
    )
