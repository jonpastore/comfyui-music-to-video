"""T3-4.3-opens: check_audio opens — missing/unreadable/no-audio-stream REJECT.

docs/TRD-3 §4.3 lists opens for generated takes, bridges, and edits.
check_audio already REJECTs opens when the path is missing, ffprobe
cannot read the file, or the container has no audio stream. A real
take with an audio stream is not opens-rejected. No named red test
existed until this file.

Mutation: delete the missing-path opens return → no opens finding.
Mutation: delete the probe-except opens return → unreadable arm red.
Mutation: delete the has_audio opens return → no-audio arm red.
Mutation: always PASS opens → missing/unreadable/no-audio arms red.
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


def _stub(path, n_bytes=64):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x00" * n_bytes)
    return path


def _wav(path, seconds=1.0, sample_rate=44100, freq=440):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi",
         "-i", f"sine=frequency={freq}:sample_rate={sample_rate}:duration={seconds}",
         "-c:a", "pcm_s16le", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(path) and os.path.getsize(path) > 0
    return path


def _video_only(path, frames=30):
    """Readable container with video and no audio stream."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10",
         "-frames:v", str(frames), "-c:v", "mpeg4", "-q:v", "5",
         "-an", "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(path) and os.path.getsize(path) > 0
    return path


def _opens(findings):
    rows = [f for f in findings if f["check"] == "opens"]
    assert rows, f"no opens finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_3_opens_remedy_class():
    """opens is a named check with re-render class (T3-27)."""
    assert "opens" in qc.CHECK_REMEDY_CLASS, (
        "opens not in CHECK_REMEDY_CLASS — T3-4.3-opens not wired")
    assert qc.CHECK_REMEDY_CLASS["opens"] == qc.REMEDY_RERENDER


def test_t3_4_3_opens_missing_file_rejects(tmp_path):
    """One variable: path does not exist → REJECT opens only."""
    path = str(tmp_path / "missing.wav")
    assert not os.path.isfile(path)
    findings = qc.run(path, "audio", {})
    row = _opens(findings)
    assert row["verdict"] == qc.REJECT, row
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert "exist" in detail or "missing" in detail, row
    assert len(findings) == 1 and findings[0]["check"] == "opens"


def test_t3_4_3_opens_unreadable_rejects(tmp_path, monkeypatch):
    """One variable: bytes ffprobe cannot read → REJECT opens."""
    _use_real_mixer(monkeypatch)
    path = _stub(str(tmp_path / "garbage.wav"), 128)
    findings = qc.run(path, "audio", {})
    row = _opens(findings)
    assert row["verdict"] == qc.REJECT, row
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert "ffprobe" in detail or "cannot read" in detail or "read" in detail, row
    assert findings[0]["check"] == "opens"
    assert len(findings) == 1, findings


def test_t3_4_3_opens_no_audio_stream_rejects(tmp_path, monkeypatch):
    """One variable: readable file with no audio stream → REJECT opens."""
    mixer = _use_real_mixer(monkeypatch)
    path = _video_only(str(tmp_path / "video_only.mp4"))
    info = mixer.probe(path)
    assert info.get("has_audio") is False, info
    assert info.get("has_video") is True, info

    findings = qc.run(path, "audio", {})
    row = _opens(findings)
    assert row["verdict"] == qc.REJECT, row
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert "no audio" in detail or "audio stream" in detail, row
    assert findings[0]["check"] == "opens"
    assert len(findings) == 1, findings


def test_t3_4_3_opens_real_take_not_rejected(tmp_path, monkeypatch):
    """A real take with an audio stream is not opens-rejected."""
    mixer = _use_real_mixer(monkeypatch)
    path = _wav(str(tmp_path / "good.wav"), 1.0)
    info = mixer.probe(path)
    assert info.get("has_audio") is True, info

    findings = qc.run(path, "audio", {"lufs_tol": 40.0})
    opens = [f for f in findings if f["check"] == "opens"]
    assert not opens or opens[0]["verdict"] != qc.REJECT, opens
    assert not any(
        f["check"] == "opens" and f["verdict"] == qc.REJECT
        for f in findings), findings
    # Must reach post-opens checks (probe + has_audio succeeded).
    assert any(
        f["check"] in ("loudness", "true_peak", "clipped_samples",
                       "dc_offset", "edge_silence", "band_energy")
        for f in findings), [f["check"] for f in findings]
