"""T3-4.3-edge: leading and trailing silence on audio takes.

docs/TRD-3 §4.3: leading and trailing silence are measured. Not whole-file
band energy (T3-9). A clean tone PASSes both edges. A half-second null
pad on either edge FLAGs. measured is leading/trailing seconds from
measure_edge_silence, expected EDGE_SILENCE_LIMIT_S, unit s.

Mutation: delete the check from check_audio → no edge_silence finding.
Mutation: always PASS → padded arm red.
Mutation: measured not equal to measure_edge_silence → T3-4 red.
"""
import subprocess

from conftest import _real_module

import qc


def _use_real_probe(monkeypatch):
    real = _real_module("mixer")
    assert real is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real)


def _mk(path, lavfi, extra=None):
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", lavfi]
    if extra:
        cmd.extend(extra)
    cmd.append(path)
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


def _concat(path, pieces):
    """pieces: list of lavfi specs, each generating audio; concat in order."""
    inputs = []
    labels = []
    for i, lavfi in enumerate(pieces):
        inputs.extend(["-f", "lavfi", "-i", lavfi])
        labels.append(f"[{i}]")
    n = len(pieces)
    fc = "".join(labels) + f"concat=n={n}:v=0:a=1"
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", *inputs,
           "-filter_complex", fc, path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


def _edge(findings):
    rows = [f for f in findings if f["check"] == "edge_silence"]
    assert rows, f"no edge_silence finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_3_edge_measure_surface_and_raises():
    """Named measure surface. A non-audio file raises, never 0.0."""
    assert hasattr(qc, "measure_edge_silence"), (
        "T3-4.3-edge lives on qc.measure_edge_silence so edge_silence "
        "cannot be a hardcoded PASS with no reading")
    assert hasattr(qc, "EDGE_SILENCE_LIMIT_S")
    blank = "/tmp/t3_4_3_edge_empty.bin"
    open(blank, "wb").write(b"\x00" * 32)
    try:
        qc.measure_edge_silence(blank)
    except (RuntimeError, ValueError) as e:
        msg = str(e).lower()
        assert "no" in msg or "not measured" in msg or "reading" in msg, e
        assert "0.0" not in str(e).split("for")[0]
    else:
        raise AssertionError("a non-audio file reported edge silence")


def test_t3_4_3_edge_clean_passes_pad_flags(tmp_path, monkeypatch):
    """Clean tone PASSes; 0.5 s leading or trailing null FLAG. One variable."""
    _use_real_probe(monkeypatch)
    clean = _mk(str(tmp_path / "clean.wav"),
                "sine=frequency=440:duration=2", ["-af", "volume=-14dB"])
    lead = _concat(str(tmp_path / "lead.wav"),
                   ["aevalsrc=0:d=0.5", "sine=f=440:d=1.5"])
    trail = _concat(str(tmp_path / "trail.wav"),
                    ["sine=f=440:d=1.5", "aevalsrc=0:d=0.5"])
    both = _concat(str(tmp_path / "both.wav"),
                   ["aevalsrc=0:d=0.5", "sine=f=440:d=1", "aevalsrc=0:d=0.5"])

    good = _edge(qc.run(clean, "audio", {"lufs_tol": 40.0}))
    assert good["verdict"] == qc.PASS, good
    measured = good["measured"]
    assert set(measured) == {"leading", "trailing"}, measured
    assert measured["leading"] <= qc.EDGE_SILENCE_LIMIT_S, measured
    assert measured["trailing"] <= qc.EDGE_SILENCE_LIMIT_S, measured
    assert good["expected"] == qc.EDGE_SILENCE_LIMIT_S
    assert good["unit"] == "s"
    assert good["remedy_class"] == qc.REMEDY_RERENDER

    for path, which in ((lead, "leading"), (trail, "trailing"), (both, "both")):
        row = _edge(qc.run(path, "audio", {"lufs_tol": 40.0}))
        assert row["verdict"] == qc.FLAG, (which, row)
        measured = row["measured"]
        assert set(measured) == {"leading", "trailing"}, measured
        worst = max(measured["leading"], measured["trailing"])
        assert worst > qc.EDGE_SILENCE_LIMIT_S, (which, measured)
        if which == "leading":
            assert measured["leading"] > qc.EDGE_SILENCE_LIMIT_S, measured
        elif which == "trailing":
            assert measured["trailing"] > qc.EDGE_SILENCE_LIMIT_S, measured
        else:
            assert measured["leading"] > qc.EDGE_SILENCE_LIMIT_S, measured
            assert measured["trailing"] > qc.EDGE_SILENCE_LIMIT_S, measured
        assert row["expected"] == qc.EDGE_SILENCE_LIMIT_S
        assert row["unit"] == "s"
        detail = (row["detail"] or "").lower()
        assert "leading" in detail and "trailing" in detail, row


def test_t3_4_3_edge_measured_matches_independent_reading(tmp_path, monkeypatch):
    """T3-4: measured equals measure_edge_silence, not a free-form string."""
    _use_real_probe(monkeypatch)
    path = _concat(str(tmp_path / "pad.wav"),
                   ["aevalsrc=0:d=0.5", "sine=f=440:d=1.5"])
    independent = qc.measure_edge_silence(path)
    assert independent["leading"] > qc.EDGE_SILENCE_LIMIT_S, independent
    row = _edge(qc.run(path, "audio", {"lufs_tol": 40.0}))
    assert abs(float(row["measured"]["leading"])
               - float(independent["leading"])) < 0.05, (row, independent)
    assert abs(float(row["measured"]["trailing"])
               - float(independent["trailing"])) < 0.05, (row, independent)


def test_t3_4_3_edge_short_pad_under_limit_passes(tmp_path, monkeypatch):
    """Sub-limit pad (0.15 s) is not the dead-air failure mode."""
    _use_real_probe(monkeypatch)
    path = _concat(str(tmp_path / "short.wav"),
                   ["aevalsrc=0:d=0.15", "sine=f=440:d=1.7", "aevalsrc=0:d=0.15"])
    row = _edge(qc.run(path, "audio", {"lufs_tol": 40.0}))
    assert row["verdict"] == qc.PASS, row
    measured = row["measured"]
    assert measured["leading"] <= qc.EDGE_SILENCE_LIMIT_S, measured
    assert measured["trailing"] <= qc.EDGE_SILENCE_LIMIT_S, measured


def test_t3_4_3_edge_not_whole_file_band_energy(tmp_path, monkeypatch):
    """T3-9 silence and edge_silence are distinct checks on the same take."""
    _use_real_probe(monkeypatch)
    path = _concat(str(tmp_path / "lead_tone.wav"),
                   ["aevalsrc=0:d=0.5", "sine=f=440:d=1.5"])
    findings = qc.run(path, "audio", {"lufs_tol": 40.0})
    names = {f["check"] for f in findings}
    assert "edge_silence" in names, names
    assert "silence" in names, names
    edge = _edge(findings)
    assert edge["verdict"] == qc.FLAG, edge
    sil = [f for f in findings if f["check"] == "silence"][0]
    # Tone after the pad is live mid-band — T3-9 must not REJECT this file.
    assert sil["verdict"] == qc.PASS, sil
