"""T3-4.3-dc: generated-take DC offset check.

docs/TRD-3 §4.3: DC offset is measured on audio takes, bridges, and
edits. A clean tone has abs mean sample near 0 and PASSes. A take with
a large constant bias FLAGs. measured is the abs mean sample as a
fraction of full scale, not a presence bit.

Mutation: delete the check from check_audio → no dc_offset finding.
Mutation: always PASS → offset arm red.
Mutation: measured not equal to measure_dc_offset → T3-4 red.
"""
import os
import subprocess

from conftest import _real_module

import qc


def _use_real_mixer(monkeypatch):
    real = _real_module("mixer")
    assert real is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real)


def _wav(path, lavfi, extra=None):
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", lavfi]
    if extra:
        cmd.extend(extra)
    cmd.append(path)
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(path) and os.path.getsize(path) > 0, path
    return path


def _dc(findings):
    rows = [f for f in findings if f["check"] == "dc_offset"]
    assert rows, f"no dc_offset finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_3_dc_measure_surface_and_raises():
    """Named measure surface. A non-audio file raises, never 0.0."""
    assert hasattr(qc, "measure_dc_offset"), (
        "T3-4.3-dc lives on qc.measure_dc_offset so dc_offset cannot "
        "be a hardcoded PASS with no reading")
    assert hasattr(qc, "DC_OFFSET_LIMIT")
    blank = "/tmp/t3_4_3_dc_empty.bin"
    open(blank, "wb").write(b"\x00" * 32)
    try:
        qc.measure_dc_offset(blank)
    except (RuntimeError, ValueError) as e:
        msg = str(e).lower()
        assert "no" in msg or "not measured" in msg or "reading" in msg, e
        assert "0.0" not in str(e).split("for")[0]
    else:
        raise AssertionError("a non-audio file reported DC offset")


def test_t3_4_3_dc_offset_flags_clean_passes(tmp_path, monkeypatch):
    """Clean tone PASS; large constant bias FLAG. One variable: mean sample."""
    _use_real_mixer(monkeypatch)
    clean = _wav(str(tmp_path / "clean.wav"),
                 "sine=frequency=440:duration=2",
                 ["-af", "volume=-14dB"])
    # dcshift injects a constant bias. 0.15 FS is well above the limit.
    biased = _wav(str(tmp_path / "biased.wav"),
                  "sine=frequency=440:duration=2",
                  ["-af", "volume=-14dB,dcshift=shift=0.15"])

    good = _dc(qc.run(clean, "audio", {"lufs_tol": 40.0}))
    assert good["verdict"] == qc.PASS, good
    assert good["measured"] is not None
    assert float(good["measured"]) <= qc.DC_OFFSET_LIMIT, good
    assert good["expected"] == qc.DC_OFFSET_LIMIT
    assert good["unit"] == "FS"
    assert good["remedy_class"] == qc.REMEDY_RERENDER
    detail = (good["detail"] or "").lower()
    assert "dc" in detail or "offset" in detail, good

    bad = _dc(qc.run(biased, "audio", {"lufs_tol": 40.0}))
    assert bad["verdict"] == qc.FLAG, bad
    assert float(bad["measured"]) > qc.DC_OFFSET_LIMIT, bad
    assert abs(float(bad["measured"]) - 0.15) < 0.02, bad
    assert bad["expected"] == qc.DC_OFFSET_LIMIT
    assert bad["unit"] == "FS"
    assert bad["remedy_class"] == qc.REMEDY_RERENDER
    detail = (bad["detail"] or "").lower()
    assert "dc" in detail or "offset" in detail, bad


def test_t3_4_3_dc_measured_matches_independent_reading(tmp_path, monkeypatch):
    """T3-4: measured equals measure_dc_offset, not a free-form string."""
    _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "biased.wav"),
                "sine=frequency=440:duration=2",
                ["-af", "volume=-14dB,dcshift=shift=0.15"])
    independent = qc.measure_dc_offset(path)
    assert float(independent) > qc.DC_OFFSET_LIMIT, independent
    row = _dc(qc.run(path, "audio", {"lufs_tol": 40.0}))
    assert abs(float(row["measured"]) - float(independent)) < 1e-4, (
        row, independent)


def test_t3_4_3_dc_pure_dc_flags(tmp_path, monkeypatch):
    """A constant sample is pure offset, not a quiet tone."""
    _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "const.wav"),
                "aevalsrc=0.08:s=44100:d=2")
    row = _dc(qc.run(path, "audio", {"lufs_tol": 40.0}))
    assert row["verdict"] == qc.FLAG, row
    assert float(row["measured"]) > qc.DC_OFFSET_LIMIT, row
    assert abs(float(row["measured"]) - 0.08) < 0.01, row
