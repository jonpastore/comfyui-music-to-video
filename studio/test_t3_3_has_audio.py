"""T3-3: silent LTX clip must not emit has_audio; song without audio REJECTS.

docs/TRD-3 §2: LTX-2.5 clips are silent by design (audio conditions the
latent, then is discarded). A clip with no audio stream must not be
flagged for has_audio. kind=song defaults want_audio; an assembled
song with no audio stream REJECTs has_audio (remedy re-assemble).

Previously only qc.demo() asserted both halves. T3-4.4-av only asserts
that clips skip av_sync/has_audio; the song REJECT arm lived in demo.

Mutation: always emit has_audio on clips → clip arm red.
Mutation: delete the has_audio REJECT under want_audio → song arm red.
Mutation: kind=song without setdefault want_audio → song arm red.
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


def _silent_mp4(path, frames=81, fps=16.8312, size="320x240"):
    """Silent video container — LTX-shaped (no audio stream)."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}",
         "-frames:v", str(frames), "-pix_fmt", "yuv420p",
         "-an", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, (
        f"fixture {path} is {os.path.getsize(path)} bytes — under "
        f"MIN_VIDEO_BYTES; size_floor would hide has_audio")
    return path


def _song_with_audio(path, video_s=2, audio_s=2, fps=10):
    """Assembled-song shape: video + audio streams."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i",
         f"color=c=blue:size=320x240:rate={fps}:duration={video_s}",
         "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={audio_s}",
         "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac",
         "-map", "0:v", "-map", "1:a", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES
    return path


def _has_audio_rows(findings):
    return [f for f in findings if f["check"] == "has_audio"]


def test_t3_3_remedy_class_named():
    """has_audio names re-assemble (T3-27)."""
    assert qc.CHECK_REMEDY_CLASS["has_audio"] == qc.REMEDY_REASSEMBLE


def test_t3_3_silent_clip_does_not_emit_has_audio(tmp_path, monkeypatch):
    """One variable: kind=clip on a silent LTX-shaped file → no has_audio."""
    mixer = _use_real_mixer(monkeypatch)
    path = _silent_mp4(str(tmp_path / "ltx_clip.mp4"))
    info = mixer.probe(path)
    assert info["has_audio"] is False, info
    assert info["has_video"] is True, info

    findings = qc.run(path, "clip", {})
    assert not _has_audio_rows(findings), findings

    # Explicit expect without want_audio must also stay quiet.
    findings2 = qc.run(path, "clip", {
        "frames": 81, "fps": 16.8312, "width": 320, "height": 240,
        "duration": 81 / 16.8312,
    })
    assert not _has_audio_rows(findings2), findings2


def test_t3_3_song_without_audio_rejects_has_audio(tmp_path, monkeypatch):
    """Same silent file as kind=song REJECTs has_audio (want_audio default)."""
    mixer = _use_real_mixer(monkeypatch)
    path = _silent_mp4(str(tmp_path / "assembled_silent.mp4"))
    assert mixer.probe(path)["has_audio"] is False

    findings = qc.run(path, "song", {})
    rows = _has_audio_rows(findings)
    assert rows, f"no has_audio finding: {[f['check'] for f in findings]}"
    row = rows[0]
    assert row["verdict"] == qc.REJECT, row
    assert row["remedy_class"] == qc.REMEDY_REASSEMBLE
    detail = (row["detail"] or "").lower()
    assert "audio" in detail, row


def test_t3_3_song_with_audio_does_not_reject_has_audio(tmp_path, monkeypatch):
    """Positive half: assembled song that has an audio stream is not REJECT
    on has_audio. av_sync may still run; has_audio must not fire REJECT."""
    mixer = _use_real_mixer(monkeypatch)
    path = _song_with_audio(str(tmp_path / "assembled.mp4"))
    assert mixer.probe(path)["has_audio"] is True

    findings = qc.run(path, "song", {})
    bad = [f for f in _has_audio_rows(findings) if f["verdict"] == qc.REJECT]
    assert not bad, bad


def test_t3_3_clip_with_want_audio_true_rejects_when_silent(
        tmp_path, monkeypatch):
    """want_audio is opt-in: a silent clip asked for audio REJECTs has_audio."""
    _use_real_mixer(monkeypatch)
    path = _silent_mp4(str(tmp_path / "asked.mp4"))
    findings = qc.check_video(path, {"want_audio": True}, kind="clip")
    rows = _has_audio_rows(findings)
    assert rows and rows[0]["verdict"] == qc.REJECT, findings
