"""T3-4.3-duration: audio duration as requested on generated takes.

docs/TRD-3 §4.3: duration against what was requested. Previously only
qc.demo() asserted the mismatch arm. When expect.duration is set,
check_audio measures the artefact via mixer.probe and compares within
DURATION_TOL_S.

Matching length PASSes. Wrong length REJECTs.
measured is the file's seconds, expected is the request, unit s.
Without expect duration, check_audio emits no duration finding.

Mutation: delete the check from check_audio → no duration finding.
Mutation: always PASS → mismatch arm red.
Mutation: measured not equal to mixer.probe duration (rounded) → T3-4 red.
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


def _wav(path, seconds, sample_rate=44100, freq=440):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi",
         "-i", f"sine=frequency={freq}:sample_rate={sample_rate}:duration={seconds}",
         "-c:a", "pcm_s16le", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(path) and os.path.getsize(path) > 0
    return path


def _dur(findings):
    rows = [f for f in findings if f["check"] == "duration"]
    assert rows, f"no duration finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_3_duration_probe_reports_seconds(tmp_path, monkeypatch):
    """mixer.probe duration is the reading. A length that never surfaces cannot be checked."""
    mixer = _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "three.wav"), 3.0)
    info = mixer.probe(path)
    assert "duration" in info, info
    assert abs(info["duration"] - 3.0) <= qc.DURATION_TOL_S, info


def test_t3_4_3_duration_match_passes_mismatch_rejects(tmp_path, monkeypatch):
    """One variable: the file length against expect.duration."""
    _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "tone.wav"), 3.0)
    expect_ok = {"duration": 3.0, "lufs_tol": 40.0}
    expect_bad = {"duration": 9.0, "lufs_tol": 40.0}

    row = _dur(qc.run(path, "audio", expect_ok))
    assert row["verdict"] == qc.PASS, row
    assert abs(float(row["measured"]) - 3.0) <= qc.DURATION_TOL_S, row
    assert float(row["expected"]) == 3.0, row
    assert row["unit"] == "s"
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert "s" in detail and ("3" in detail or "requested" in detail), row

    row = _dur(qc.run(path, "audio", expect_bad))
    assert row["verdict"] == qc.REJECT, row
    assert abs(float(row["measured"]) - 3.0) <= qc.DURATION_TOL_S, row
    assert float(row["expected"]) == 9.0, row
    assert row["unit"] == "s"
    assert row["remedy_class"] == qc.REMEDY_RERENDER


def test_t3_4_3_duration_measured_matches_probe(tmp_path, monkeypatch):
    """T3-4: measured equals mixer.probe duration (rounded like the finding)."""
    mixer = _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "two.wav"), 2.0)
    independent = round(float(mixer.probe(path)["duration"]), 3)
    row = _dur(qc.run(path, "audio", {"duration": 9.0, "lufs_tol": 40.0}))
    assert float(row["measured"]) == independent, (row, independent)
    assert row["unit"] == "s"


def test_t3_4_3_duration_without_expect_emits_nothing(tmp_path, monkeypatch):
    """As requested: no request means no duration finding."""
    _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "any.wav"), 1.0)
    findings = qc.run(path, "audio", {"lufs_tol": 40.0})
    assert not any(f["check"] == "duration" for f in findings), [
        f["check"] for f in findings]


def test_t3_4_3_duration_tolerance_boundary(tmp_path, monkeypatch):
    """Just-inside DURATION_TOL_S PASSes; just-outside REJECTs. Named constant."""
    _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "one.wav"), 1.0)
    # Probe once so the expect offsets are relative to the real file length.
    mixer = _use_real_mixer(monkeypatch)
    actual = float(mixer.probe(path)["duration"])
    tol = qc.DURATION_TOL_S
    inside = actual + tol * 0.5
    outside = actual + tol + 0.01

    row = _dur(qc.run(path, "audio", {"duration": inside, "lufs_tol": 40.0}))
    assert row["verdict"] == qc.PASS, row

    row = _dur(qc.run(path, "audio", {"duration": outside, "lufs_tol": 40.0}))
    assert row["verdict"] == qc.REJECT, row
    assert float(row["expected"]) == outside, row
