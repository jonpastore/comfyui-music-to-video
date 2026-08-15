"""T3-4.3-ch: audio channel count as requested.

docs/TRD-3 §4.3: channel count as requested. mixer.probe must expose
channels (ffprobe nb/channels). check_audio emits `channels` when
expect carries channels. Stereo vs request 2 PASSes. Mono vs request 2
REJECTs. measured equals the independent probe reading.

Mutation: probe without channels → KeyError / no reading.
Mutation: delete the check from check_audio → no channels finding.
Mutation: always PASS → mono-vs-2 arm red.
Mutation: measured not equal to probe channels → T3-4 red.
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


def _wav(path, channels, seconds=0.5, rate=44100):
    """Minimal PCM take. One variable: channel count."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i",
         f"sine=frequency=440:sample_rate={rate}:duration={seconds}",
         "-ac", str(channels), path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(path) and os.path.getsize(path) > 0
    return path


def _ch(findings):
    rows = [f for f in findings if f["check"] == "channels"]
    assert rows, f"no channels finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_3_ch_probe_exposes_channels(tmp_path, monkeypatch):
    """Probe has a channels field. Mono is 1, stereo is 2. Not a silent 0."""
    mixer = _use_real_mixer(monkeypatch)
    mono = _wav(str(tmp_path / "mono.wav"), channels=1)
    stereo = _wav(str(tmp_path / "stereo.wav"), channels=2)
    m = mixer.probe(mono)
    s = mixer.probe(stereo)
    assert "channels" in m, m
    assert "channels" in s, s
    assert m["channels"] == 1, m
    assert s["channels"] == 2, s


def test_t3_4_3_ch_probe_no_audio_is_zero_not_missing(tmp_path, monkeypatch):
    """Video-only has channels 0. The field is still present."""
    mixer = _use_real_mixer(monkeypatch)
    path = str(tmp_path / "silent.mp4")
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=black:size=64x64:rate=10:duration=0.3",
         "-an", "-c:v", "mpeg4", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    info = mixer.probe(path)
    assert "channels" in info, info
    assert info["channels"] == 0, info
    assert info["has_audio"] is False


def test_t3_4_3_ch_match_passes_mismatch_rejects(tmp_path, monkeypatch):
    """Stereo vs request 2 PASSes. Mono vs request 2 REJECTs. One variable."""
    _use_real_mixer(monkeypatch)
    stereo = _wav(str(tmp_path / "stereo.wav"), channels=2)
    mono = _wav(str(tmp_path / "mono.wav"), channels=1)

    good = _ch(qc.run(stereo, "audio", {"channels": 2, "lufs_tol": 40.0}))
    assert good["verdict"] == qc.PASS, good
    assert good["measured"] == 2, good
    assert good["expected"] == 2, good
    assert good["unit"] == "ch"
    assert good["remedy_class"] == qc.REMEDY_RERENDER
    detail = (good["detail"] or "").lower()
    assert "channel" in detail or "2" in detail, good

    bad = _ch(qc.run(mono, "audio", {"channels": 2, "lufs_tol": 40.0}))
    assert bad["verdict"] == qc.REJECT, bad
    assert bad["measured"] == 1, bad
    assert bad["expected"] == 2, bad
    assert bad["unit"] == "ch"
    assert bad["remedy_class"] == qc.REMEDY_RERENDER
    detail = (bad["detail"] or "").lower()
    assert "1" in detail and "2" in detail, bad


def test_t3_4_3_ch_measured_matches_independent_probe(tmp_path, monkeypatch):
    """T3-4: measured equals mixer.probe channels, not a free-form string."""
    mixer = _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "mono.wav"), channels=1)
    independent = mixer.probe(path)["channels"]
    assert independent == 1, independent
    row = _ch(qc.run(path, "audio", {"channels": 2, "lufs_tol": 40.0}))
    assert row["measured"] == independent, (row, independent)


def test_t3_4_3_ch_without_expect_skips_channels(tmp_path, monkeypatch):
    """No channels in expect → no channels finding (like duration)."""
    _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "stereo.wav"), channels=2)
    findings = qc.run(path, "audio", {"lufs_tol": 40.0})
    assert not any(f["check"] == "channels" for f in findings), [
        f["check"] for f in findings]
