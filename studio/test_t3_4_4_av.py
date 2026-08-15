"""T3-4.4-av: assembled song audio and video stream durations agree.

docs/TRD-3 §4.4: on an assembled song, audio and video stream durations
must agree within DURATION_TOL_S. Clips stay silent by design and do not
opt in. kind=song sets want_audio; the check is av_sync.

A matching pair PASSes (gap 0). Video 2s / audio 3s FLAGs (gap 1.0s).
measured is the abs gap in seconds, expected 0.0, unit s, remedy
re-assemble.

Mutation: delete the check from check_video → no av_sync finding.
Mutation: always PASS → mismatch arm red.
Mutation: measured not equal to measure_av_durations gap → T3-4 red.
"""
import os
import subprocess

from conftest import _real_module

import qc


def _use_real_mixer(monkeypatch):
    real = _real_module("mixer")
    assert real is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real)


def _song_mp4(path, video_s, audio_s, fps=10):
    """Assemble a minimal song-shaped container: mpeg4 + aac."""
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
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, (
        f"fixture {path} is {os.path.getsize(path)} bytes — under "
        f"MIN_VIDEO_BYTES; size_floor would hide av_sync")
    return path


def _av(findings):
    rows = [f for f in findings if f["check"] == "av_sync"]
    assert rows, f"no av_sync finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_4_av_measure_surface_and_raises():
    """Named measure surface. A non-media file raises, never a silent skip."""
    assert hasattr(qc, "measure_av_durations"), (
        "T3-4.4-av lives on qc.measure_av_durations so av_sync cannot "
        "be a hardcoded PASS with no reading")
    blank = "/tmp/t3_4_4_av_empty.bin"
    open(blank, "wb").write(b"\x00" * 32)
    try:
        qc.measure_av_durations(blank)
    except (RuntimeError, ValueError) as e:
        msg = str(e).lower()
        assert "no" in msg or "not measured" in msg or "fail" in msg, e
    else:
        raise AssertionError("a non-media file reported av durations")


def test_t3_4_4_av_match_passes_mismatch_flags(tmp_path, monkeypatch):
    """Matching streams PASS; 1s gap FLAGs. One variable: stream lengths."""
    _use_real_mixer(monkeypatch)
    matched = _song_mp4(str(tmp_path / "match.mp4"), video_s=2, audio_s=2)
    mismatched = _song_mp4(str(tmp_path / "mismatch.mp4"), video_s=2, audio_s=3)

    good = _av(qc.run(matched, "song", {}))
    assert good["verdict"] == qc.PASS, good
    assert good["measured"] is not None
    assert float(good["measured"]) <= qc.DURATION_TOL_S, good
    assert good["expected"] == 0.0
    assert good["unit"] == "s"
    assert good["remedy_class"] == qc.REMEDY_REASSEMBLE
    detail = (good["detail"] or "").lower()
    assert "video" in detail and "audio" in detail, good

    bad = _av(qc.run(mismatched, "song", {}))
    assert bad["verdict"] == qc.FLAG, bad
    assert float(bad["measured"]) > qc.DURATION_TOL_S, bad
    assert abs(float(bad["measured"]) - 1.0) < 0.05, bad
    assert bad["expected"] == 0.0
    assert bad["unit"] == "s"
    assert bad["remedy_class"] == qc.REMEDY_REASSEMBLE
    detail = (bad["detail"] or "").lower()
    assert "video" in detail and "audio" in detail, bad


def test_t3_4_4_av_measured_matches_independent_reading(tmp_path, monkeypatch):
    """T3-4: measured equals abs(video-audio) from measure_av_durations."""
    _use_real_mixer(monkeypatch)
    path = _song_mp4(str(tmp_path / "gap.mp4"), video_s=2, audio_s=3)
    independent = qc.measure_av_durations(path)
    gap = abs(independent["video"] - independent["audio"])
    assert gap > qc.DURATION_TOL_S, independent
    row = _av(qc.run(path, "song", {}))
    assert abs(float(row["measured"]) - gap) < 0.05, (row, independent)


def test_t3_4_4_av_clip_without_want_audio_skips_av_sync(tmp_path, monkeypatch):
    """Clips are silent by design; av_sync is song-only unless want_audio."""
    _use_real_mixer(monkeypatch)
    path = _song_mp4(str(tmp_path / "clip_shape.mp4"), video_s=2, audio_s=3)
    findings = qc.run(path, "clip", {})
    assert not any(f["check"] == "av_sync" for f in findings), findings
    assert not any(f["check"] == "has_audio" for f in findings), findings


def test_t3_4_4_av_song_defaults_want_audio(tmp_path, monkeypatch):
    """kind=song sets want_audio so av_sync runs without an expect flag."""
    _use_real_mixer(monkeypatch)
    path = _song_mp4(str(tmp_path / "song.mp4"), video_s=2, audio_s=2)
    findings = qc.run(path, "song", {})
    assert any(f["check"] == "av_sync" for f in findings), [
        f["check"] for f in findings]
