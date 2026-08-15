"""T3-4.3-loudness: check_audio loudness FLAG/PASS via effects.measure_loudness.

docs/TRD-3 §4.3: integrated loudness is measured once in effects.py
(TRD-1 T1-25). check_audio must call that owner — not a second ebur128
path. Within LOUDNESS_TOLERANCE_LU of the target PASSes; outside FLAGs.
measured equals the independent effects.measure_loudness reading.

Mutation: always PASS → off-target arm red.
Mutation: always FLAG → on-target arm red.
Mutation: measured not from measure_loudness → T3-4 / equality red.
Mutation: delete loudness check → no loudness finding.
"""
import os
import subprocess

from conftest import _real_module

import qc


def _use_real_stack(monkeypatch):
    """Real mixer.probe + effects.measure_loudness — not the conftest stubs."""
    real_fx = _real_module("effects")
    real_mx = _real_module("mixer")
    assert real_fx is not None, "real effects.py failed to import"
    assert real_mx is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "effects", real_fx)
    monkeypatch.setattr(qc, "mixer", real_mx)
    return real_fx


def _tone(path, volume_db, seconds=3.0, rate=48000):
    """Minimal PCM take. One variable: volume (loudness)."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi",
         "-i", f"sine=frequency=1000:sample_rate={rate}:duration={seconds}",
         "-af", f"volume={volume_db}dB",
         "-c:a", "pcm_s16le", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(path) and os.path.getsize(path) > 0
    return path


def _loud(findings):
    rows = [f for f in findings if f["check"] == "loudness"]
    assert rows, f"no loudness finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_3_loudness_uses_effects_measure_loudness(tmp_path, monkeypatch):
    """Measured on the finding equals independent effects.measure_loudness."""
    real = _use_real_stack(monkeypatch)
    path = _tone(str(tmp_path / "tone.wav"), volume_db=0)
    independent = real.measure_loudness(path)
    row = _loud(qc.run(path, "audio", {
        "lufs": independent["lufs"],
        "lufs_tol": real.LOUDNESS_TOLERANCE_LU,
    }))
    assert row["measured"] == independent["lufs"], (row, independent)
    assert row["unit"] == "LUFS"
    assert row["expected"] == independent["lufs"]
    assert row["remedy_class"] == qc.REMEDY_LOUDNORM


def test_t3_4_3_loudness_on_target_passes(tmp_path, monkeypatch):
    """Within tolerance of the named target PASSes. One variable: gap to target."""
    real = _use_real_stack(monkeypatch)
    path = _tone(str(tmp_path / "ok.wav"), volume_db=-6)
    measured = real.measure_loudness(path)["lufs"]
    row = _loud(qc.run(path, "audio", {
        "lufs": measured,
        "lufs_tol": real.LOUDNESS_TOLERANCE_LU,
    }))
    assert row["verdict"] == qc.PASS, row
    assert abs(row["measured"] - measured) < 1e-9, row
    assert row["unit"] == "LUFS"
    detail = (row["detail"] or "").lower()
    assert "lufs" in detail, row


def test_t3_4_3_loudness_off_target_flags(tmp_path, monkeypatch):
    """Outside LOUDNESS_TOLERANCE_LU FLAGs. Always-PASS is the mutation."""
    real = _use_real_stack(monkeypatch)
    # Hot sine: well above streaming target when loudnorm is not applied.
    path = _tone(str(tmp_path / "hot.wav"), volume_db=20)
    measured = real.measure_loudness(path)["lufs"]
    target = real.LOUDNORM_I
    assert abs(measured - target) > real.LOUDNESS_TOLERANCE_LU, (
        f"fixture not off-target: measured {measured} vs {target}")

    row = _loud(qc.run(path, "audio", {
        "lufs": target,
        "lufs_tol": real.LOUDNESS_TOLERANCE_LU,
    }))
    assert row["verdict"] == qc.FLAG, row
    assert row["measured"] == measured, row
    assert row["expected"] == target, row
    assert row["unit"] == "LUFS"
    assert row["remedy_class"] == qc.REMEDY_LOUDNORM
    detail = (row["detail"] or "").lower()
    assert "lufs" in detail, row


def test_t3_4_3_loudness_default_target_is_loudnorm_i(tmp_path, monkeypatch):
    """No expect.lufs → target is effects.LOUDNORM_I (not a free-form number)."""
    real = _use_real_stack(monkeypatch)
    path = _tone(str(tmp_path / "hot.wav"), volume_db=20)
    measured = real.measure_loudness(path)["lufs"]
    assert abs(measured - real.LOUDNORM_I) > real.LOUDNESS_TOLERANCE_LU

    row = _loud(qc.run(path, "audio", {}))
    assert row["verdict"] == qc.FLAG, row
    assert row["expected"] == real.LOUDNORM_I, row
    assert row["measured"] == measured, row
