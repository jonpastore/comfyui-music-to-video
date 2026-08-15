"""T3-9: a silent or near-silent take is rejected on band energy.

docs/TRD-3 §4.3: measured low/mid/high band energies, not peak
volumedetect and not aspectralstats. A 1-sample click reads peak
about -20 dB (above SILENCE_FLOOR_DB) and band means below -70.
Peak volumedetect would pass that file. T3-9 must reject it.

A 440 Hz tone is not silent: the mid band is live. Digital silence
and a -70 dB tone are. A missing reading raises, never 0.0.
"""
import re
import subprocess

from conftest import _real_module

import qc


def _mk(path, lavfi, extra=None):
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", lavfi]
    if extra:
        cmd.extend(extra)
    cmd.append(path)
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


def _peak_db(path):
    """Independent peak. Peak volumedetect is the measurement T3-9 refuses."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "info", "-i", path,
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.search(r"max_volume:\s*(-?(?:\d+(?:\.\d+)?|inf)) dB", r.stderr or "")
    assert m, r.stderr[-400:]
    return float(m.group(1))


def _silence(findings):
    rows = [f for f in findings if f["check"] == "silence"]
    assert rows, findings
    return rows[0]


def _use_real_probe(monkeypatch):
    real_mixer = _real_module("mixer")
    assert real_mixer is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real_mixer)


def test_t3_9_measure_band_energy_returns_low_mid_high_and_raises(tmp_path):
    """Three named bands, or it is not the measurement. No reading raises."""
    assert hasattr(qc, "measure_band_energy"), (
        "T3-9 lives on qc.measure_band_energy so silence cannot fall "
        "back to peak volumedetect")
    tone = _mk(str(tmp_path / "tone440.wav"),
               "sine=frequency=440:duration=2", ["-af", "volume=-14dB"])
    bands = qc.measure_band_energy(tone)
    assert set(bands) == {"low", "mid", "high"}, bands
    assert bands["mid"] > qc.SILENCE_FLOOR_DB, bands
    assert bands["mid"] > bands["low"] + 6, bands
    assert bands["mid"] > bands["high"] + 20, bands

    blank = tmp_path / "empty.bin"
    blank.write_bytes(b"\x00" * 32)
    try:
        qc.measure_band_energy(str(blank))
    except RuntimeError as e:
        assert "no" in str(e).lower() and "low" in str(e).lower(), e
        assert "0.0" not in str(e).split("for")[0]
    else:
        raise AssertionError("a file with no audio reported band energy")


def test_t3_9_silent_and_near_silent_takes_are_rejected(tmp_path, monkeypatch):
    """Digital silence and a -70 dB tone are empty, not quiet."""
    _use_real_probe(monkeypatch)
    quiet = _mk(str(tmp_path / "silence.wav"),
                "anullsrc=r=44100:cl=stereo", ["-t", "2"])
    near = _mk(str(tmp_path / "near.wav"),
               "sine=frequency=440:duration=2", ["-af", "volume=-70dB"])
    for path in (quiet, near):
        row = _silence(qc.run(path, "audio", {}))
        assert row["verdict"] == qc.REJECT, row
        measured = row["measured"]
        assert set(measured) == {"low", "mid", "high"}, measured
        assert max(measured.values()) <= qc.SILENCE_FLOOR_DB, row
        assert row["expected"] == qc.SILENCE_FLOOR_DB
        assert row["unit"] == "dB"
        detail = row["detail"].lower()
        assert "low" in detail and "mid" in detail and "high" in detail, row


def test_t3_9_tone_passes_on_the_live_mid_band(tmp_path, monkeypatch):
    """A 440 Hz take is not silent. Mid is the band that says so."""
    _use_real_probe(monkeypatch)
    tone = _mk(str(tmp_path / "tone.wav"),
               "sine=frequency=440:duration=2", ["-af", "volume=-14dB"])
    row = _silence(qc.run(tone, "audio", {"lufs_tol": 40.0}))
    assert row["verdict"] == qc.PASS, row
    measured = row["measured"]
    assert measured["mid"] > qc.SILENCE_FLOOR_DB, measured
    assert measured["mid"] == max(measured.values()), measured


def test_t3_9_click_rejected_despite_loud_peak(tmp_path, monkeypatch):
    """One sample at -20 dB peak, otherwise silent. Peak would pass."""
    _use_real_probe(monkeypatch)
    click = _mk(str(tmp_path / "click.wav"),
                r"aevalsrc=0.1*eq(n\,100):s=44100:d=3")
    peak = _peak_db(click)
    assert peak > qc.SILENCE_FLOOR_DB, (
        f"fixture peak {peak} dB is not above the floor — this test "
        "cannot prove T3-9 is not peak volumedetect")
    row = _silence(qc.run(click, "audio", {"lufs_tol": 40.0}))
    assert row["verdict"] == qc.REJECT, row
    measured = row["measured"]
    assert max(measured.values()) <= qc.SILENCE_FLOOR_DB, measured
    assert "peak" not in (row["detail"] or "").lower(), row
