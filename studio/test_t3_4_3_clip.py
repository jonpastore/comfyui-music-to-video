"""T3-4.3-clip: audio clipped-sample count FLAG/PASS both ways.

docs/TRD-3 §4.3: generated takes report a clipped-sample count. Samples
at digital full scale (s16 rails) are clipped. Zero rails PASSes.
Any rail hit FLAGs. measured is the independent count, expected 0,
unit samples, remedy loudnorm.

Mutation: delete the check from check_audio → no clipped_samples finding.
Mutation: always PASS → clipped arm red.
Mutation: measured not equal to measure_clipped_samples → T3-4 red.
"""
import os
import subprocess

from conftest import _real_module

import qc


def _use_real_mixer(monkeypatch):
    real = _real_module("mixer")
    assert real is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real)


def _wav(path, lavfi, af=None, duration=None):
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error",
           "-f", "lavfi", "-i", lavfi]
    if duration is not None:
        cmd.extend(["-t", str(duration)])
    if af:
        cmd.extend(["-af", af])
    cmd.extend(["-c:a", "pcm_s16le", path])
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) > 100, path
    return path


def _clip(findings):
    rows = [f for f in findings if f["check"] == "clipped_samples"]
    assert rows, f"no clipped_samples finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_3_clip_measure_surface_and_raises():
    """Named measure surface. A non-audio file raises, never 0 on no data."""
    assert hasattr(qc, "measure_clipped_samples"), (
        "T3-4.3-clip lives on qc.measure_clipped_samples so the check "
        "cannot be a hardcoded PASS with no reading")
    assert hasattr(qc, "CLIPPED_SAMPLES_LIMIT")
    blank = "/tmp/t3_4_3_clip_empty.bin"
    open(blank, "wb").write(b"\x00" * 32)
    try:
        qc.measure_clipped_samples(blank)
    except (RuntimeError, ValueError) as e:
        msg = str(e).lower()
        assert "no" in msg or "not measured" in msg or "fail" in msg, e
    else:
        raise AssertionError("a non-audio file reported clipped-sample count")


def test_t3_4_3_clip_clean_passes_clipped_flags(tmp_path, monkeypatch):
    """Zero rails PASS; hard-clipped sine FLAGs. One variable: amplitude."""
    _use_real_mixer(monkeypatch)
    clean = _wav(str(tmp_path / "clean.wav"),
                 "sine=frequency=440:duration=1:sample_rate=44100",
                 af="volume=-14dB")
    # volume=+20dB on a full-scale sine rails into s16 (measured ~18k rails).
    clipped = _wav(str(tmp_path / "clipped.wav"),
                   "sine=frequency=440:duration=1:sample_rate=44100",
                   af="volume=20dB")

    good = _clip(qc.run(clean, "audio", {"lufs_tol": 40.0}))
    assert good["verdict"] == qc.PASS, good
    assert good["measured"] is not None
    assert int(good["measured"]) <= qc.CLIPPED_SAMPLES_LIMIT, good
    assert good["expected"] == qc.CLIPPED_SAMPLES_LIMIT
    assert good["unit"] == "samples"
    assert good["remedy_class"] == qc.REMEDY_LOUDNORM
    detail = (good["detail"] or "").lower()
    assert "clip" in detail or "rail" in detail or "sample" in detail, good

    bad = _clip(qc.run(clipped, "audio", {"lufs_tol": 40.0}))
    assert bad["verdict"] == qc.FLAG, bad
    assert int(bad["measured"]) > qc.CLIPPED_SAMPLES_LIMIT, bad
    assert bad["expected"] == qc.CLIPPED_SAMPLES_LIMIT
    assert bad["unit"] == "samples"
    assert bad["remedy_class"] == qc.REMEDY_LOUDNORM
    detail = (bad["detail"] or "").lower()
    assert "clip" in detail or "rail" in detail, bad


def test_t3_4_3_clip_measured_matches_independent_reading(tmp_path, monkeypatch):
    """T3-4: measured equals measure_clipped_samples, not a free-form string."""
    _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "rails.wav"),
                "sine=frequency=440:duration=1:sample_rate=44100",
                af="volume=20dB")
    independent = qc.measure_clipped_samples(path)
    assert int(independent) > qc.CLIPPED_SAMPLES_LIMIT, independent
    row = _clip(qc.run(path, "audio", {"lufs_tol": 40.0}))
    assert int(row["measured"]) == int(independent), (row, independent)


def test_t3_4_3_clip_aeval_hard_clip_flags(tmp_path, monkeypatch):
    """aevalsrc 2*sin hits the rails; not a volume-filter-only path."""
    _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "hard.wav"),
                r"aevalsrc=exprs=2*sin(2*PI*440*t):s=44100:d=1")
    row = _clip(qc.run(path, "audio", {"lufs_tol": 40.0}))
    assert row["verdict"] == qc.FLAG, row
    assert int(row["measured"]) > 0, row
