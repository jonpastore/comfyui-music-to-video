"""T3-4.3-true-peak: true peak FLAG/PASS vs LOUDNORM_TP.

docs/TRD-3 §4.3: generated takes report true peak. Measurement is
effects.measure_loudness (the one implementation; TRD-1 T1-25). Ceiling
is effects.LOUDNORM_TP with effects.TRUE_PEAK_TOLERANCE_DB headroom.
Under the ceiling PASSes. Over the ceiling FLAGs. measured is the
independent true_peak_db, expected is LOUDNORM_TP, unit dBFS, remedy
loudnorm.

Mutation: delete the check from check_audio → no true_peak finding.
Mutation: always PASS → hot arm red.
Mutation: measured not equal to measure_loudness true_peak_db → T3-4 red.
"""
import os
import subprocess

from conftest import _real_module

import effects
import qc


def _use_real_mixer(monkeypatch):
    real = _real_module("mixer")
    assert real is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real)


def _wav(path, lavfi, af=None):
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error",
           "-f", "lavfi", "-i", lavfi]
    if af:
        cmd.extend(["-af", af])
    cmd.extend(["-c:a", "pcm_s16le", path])
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) > 100, path
    return path


def _tp(findings):
    rows = [f for f in findings if f["check"] == "true_peak"]
    assert rows, f"no true_peak finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_3_true_peak_ceiling_constants():
    """Ceiling is effects.LOUDNORM_TP; headroom is TRUE_PEAK_TOLERANCE_DB."""
    assert effects.LOUDNORM_TP == -1.5
    assert effects.TRUE_PEAK_TOLERANCE_DB == 0.5
    assert hasattr(effects, "measure_loudness")


def test_t3_4_3_true_peak_under_passes_over_flags(tmp_path, monkeypatch):
    """One variable: true peak vs LOUDNORM_TP + TRUE_PEAK_TOLERANCE_DB."""
    _use_real_mixer(monkeypatch)
    # lavfi sine sits ~−18 dBFS true peak — under the −1.0 ceiling.
    quiet = _wav(str(tmp_path / "quiet.wav"),
                 "sine=frequency=440:duration=1:sample_rate=48000")
    # +20 dB rails true peak to 0.0 dBFS — over the ceiling.
    hot = _wav(str(tmp_path / "hot.wav"),
               "sine=frequency=440:duration=1:sample_rate=48000",
               af="volume=20dB")

    ceiling = effects.LOUDNORM_TP + effects.TRUE_PEAK_TOLERANCE_DB
    q = effects.measure_loudness(quiet)
    h = effects.measure_loudness(hot)
    assert q["true_peak_db"] is not None and q["true_peak_db"] <= ceiling, q
    assert h["true_peak_db"] is not None and h["true_peak_db"] > ceiling, h

    good = _tp(qc.run(quiet, "audio", {"lufs_tol": 40.0}))
    assert good["verdict"] == qc.PASS, good
    assert good["measured"] is not None
    assert float(good["measured"]) <= ceiling, good
    assert float(good["expected"]) == effects.LOUDNORM_TP, good
    assert good["unit"] == "dBFS"
    assert good["remedy_class"] == qc.REMEDY_LOUDNORM
    detail = (good["detail"] or "").lower()
    assert "db" in detail or "peak" in detail or "ceiling" in detail, good

    bad = _tp(qc.run(hot, "audio", {"lufs_tol": 40.0}))
    assert bad["verdict"] == qc.FLAG, bad
    assert float(bad["measured"]) > ceiling, bad
    assert float(bad["expected"]) == effects.LOUDNORM_TP, bad
    assert bad["unit"] == "dBFS"
    assert bad["remedy_class"] == qc.REMEDY_LOUDNORM
    detail = (bad["detail"] or "").lower()
    assert "db" in detail or "peak" in detail or "ceiling" in detail, bad


def test_t3_4_3_true_peak_measured_matches_effects(tmp_path, monkeypatch):
    """T3-4: measured equals effects.measure_loudness true_peak_db."""
    _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "hot.wav"),
                "sine=frequency=440:duration=1:sample_rate=48000",
                af="volume=20dB")
    independent = effects.measure_loudness(path)["true_peak_db"]
    assert independent is not None
    row = _tp(qc.run(path, "audio", {"lufs_tol": 40.0}))
    assert float(row["measured"]) == float(independent), (row, independent)


def test_t3_4_3_true_peak_always_pass_mutation_would_miss_hot(
        tmp_path, monkeypatch):
    """Hot true peak must FLAG — always-PASS is the mutation this catches."""
    _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "hot.wav"),
                "sine=frequency=1000:duration=1:sample_rate=48000",
                af="volume=20dB")
    row = _tp(qc.run(path, "audio", {"lufs_tol": 40.0}))
    assert row["verdict"] == qc.FLAG, row
    assert float(row["measured"]) > (
        effects.LOUDNORM_TP + effects.TRUE_PEAK_TOLERANCE_DB), row
