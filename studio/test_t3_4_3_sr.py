"""T3-4.3-sr: sample rate as requested on generated takes.

docs/TRD-3 §4.3: sample rate and channel count as requested. This slice
is sample rate only. check_audio previously emitted no sample_rate
finding; when expect names sample_rate, the artefact's rate is measured
and compared exactly (Hz, no soft tolerance).

Matching rate PASSes. 44100 against 48000 requested REJECTs.
measured is the file's rate, expected is the request, unit Hz.
Without expect sample_rate, check_audio emits no sample_rate finding.

Mutation: delete the check from check_audio → no sample_rate finding.
Mutation: always PASS → mismatch arm red.
Mutation: measured not equal to mixer.probe sample_rate → T3-4 red.
"""
import os
import subprocess

from conftest import _real_module

import qc


def _use_real_mixer(monkeypatch):
    real = _real_module("mixer")
    assert real is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real)
    return real


def _wav(path, sample_rate, seconds=1.0, freq=440):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi",
         "-i", f"sine=frequency={freq}:sample_rate={sample_rate}:duration={seconds}",
         "-c:a", "pcm_s16le", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(path) and os.path.getsize(path) > 0
    return path


def _sr(findings):
    rows = [f for f in findings if f["check"] == "sample_rate"]
    assert rows, f"no sample_rate finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_3_sr_probe_reports_sample_rate(tmp_path, monkeypatch):
    """mixer.probe is the reading. A rate that never surfaces cannot be checked."""
    mixer = _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "sr48.wav"), 48000)
    info = mixer.probe(path)
    assert "sample_rate" in info, info
    assert int(info["sample_rate"]) == 48000, info


def test_t3_4_3_sr_match_passes_mismatch_rejects(tmp_path, monkeypatch):
    """One variable: the file rate against expect.sample_rate."""
    _use_real_mixer(monkeypatch)
    good = _wav(str(tmp_path / "ok.wav"), 48000)
    bad = _wav(str(tmp_path / "bad.wav"), 44100)
    expect = {"sample_rate": 48000, "lufs_tol": 40.0}

    row = _sr(qc.run(good, "audio", expect))
    assert row["verdict"] == qc.PASS, row
    assert int(row["measured"]) == 48000, row
    assert int(row["expected"]) == 48000, row
    assert row["unit"] == "Hz"
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert "48000" in detail and ("hz" in detail or "sample" in detail), row

    row = _sr(qc.run(bad, "audio", expect))
    assert row["verdict"] == qc.REJECT, row
    assert int(row["measured"]) == 44100, row
    assert int(row["expected"]) == 48000, row
    assert row["unit"] == "Hz"
    assert row["remedy_class"] == qc.REMEDY_RERENDER


def test_t3_4_3_sr_measured_matches_probe(tmp_path, monkeypatch):
    """T3-4: measured equals mixer.probe sample_rate, not a free-form string."""
    mixer = _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "sr44.wav"), 44100)
    independent = int(mixer.probe(path)["sample_rate"])
    assert independent == 44100, independent
    row = _sr(qc.run(path, "audio", {"sample_rate": 48000, "lufs_tol": 40.0}))
    assert int(row["measured"]) == independent, (row, independent)


def test_t3_4_3_sr_without_expect_emits_nothing(tmp_path, monkeypatch):
    """As requested: no request means no sample_rate finding."""
    _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "any.wav"), 48000)
    findings = qc.run(path, "audio", {"lufs_tol": 40.0})
    assert not any(f["check"] == "sample_rate" for f in findings), [
        f["check"] for f in findings]
