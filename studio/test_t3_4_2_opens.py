"""T3-4.2-opens: unreadable / no-video-stream REJECTs opens.

docs/TRD-3 §4.2 table: opens, over a floor size. size_floor owns the
under-MIN_VIDEO_BYTES arm (test_t3_4_2_size_floor.py). This criterion
is the post-floor arms demo never hits: a file large enough to pass the
byte floor but (a) unreadable by ffprobe, or (b) readable with no video
stream. Both REJECTs opens with remedy re-render.

A real clip with a video stream is not opens-rejected. Missing path
also REJECTs opens.

Mutation: delete the probe-except opens return → unreadable arm red.
Mutation: delete the has_video opens return → no-video arm red.
Mutation: collapse opens into size_floor only → both arms red.
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


def _stub(path, n_bytes):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x00" * n_bytes)
    return path


def _mp4(path, lavfi="testsrc2=size=320x240:rate=10", frames=30):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", lavfi,
         "-frames:v", str(frames), "-c:v", "mpeg4", "-q:v", "5",
         "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, (
        f"fixture {path} is {os.path.getsize(path)} bytes — under "
        f"MIN_VIDEO_BYTES; size_floor would hide opens")
    return path


def _audio_only(path, seconds=1.0):
    """Readable container with audio and no video stream."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "aac", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, (
        f"fixture {path} is {os.path.getsize(path)} bytes — under "
        f"MIN_VIDEO_BYTES; size_floor would hide opens")
    return path


def _opens(findings):
    rows = [f for f in findings if f["check"] == "opens"]
    assert rows, f"no opens finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_2_opens_remedy_class():
    """opens is a named check with re-render class (T3-27)."""
    assert qc.CHECK_REMEDY_CLASS["opens"] == qc.REMEDY_RERENDER


def test_t3_4_2_opens_unreadable_rejects(tmp_path, monkeypatch):
    """One variable: bytes above MIN_VIDEO_BYTES that ffprobe cannot read."""
    _use_real_mixer(monkeypatch)
    n = qc.MIN_VIDEO_BYTES + 100
    path = _stub(str(tmp_path / "garbage.mp4"), n)
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES

    findings = qc.run(path, "clip", {})
    # Must not be size_floor — that arm returns early under the floor only.
    assert not any(f["check"] == "size_floor" for f in findings), findings
    row = _opens(findings)
    assert row["verdict"] == qc.REJECT, row
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert "ffprobe" in detail or "cannot read" in detail or "read" in detail, row
    # Early return: opens only.
    assert findings[0]["check"] == "opens"
    assert len(findings) == 1, findings


def test_t3_4_2_opens_no_video_stream_rejects(tmp_path, monkeypatch):
    """One variable: readable file with no video stream → REJECT opens."""
    mixer = _use_real_mixer(monkeypatch)
    path = _audio_only(str(tmp_path / "audio_only.mp4"))
    info = mixer.probe(path)
    assert info["has_video"] is False, info
    assert info.get("has_audio") is True, info

    findings = qc.run(path, "clip", {})
    assert not any(f["check"] == "size_floor" for f in findings), findings
    row = _opens(findings)
    assert row["verdict"] == qc.REJECT, row
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert "no video" in detail or "video stream" in detail, row
    assert findings[0]["check"] == "opens"
    assert len(findings) == 1, findings


def test_t3_4_2_opens_missing_file_rejects(tmp_path):
    """Missing path REJECTs opens (no size_floor, no probe)."""
    path = str(tmp_path / "missing.mp4")
    assert not os.path.isfile(path)
    findings = qc.run(path, "clip", {})
    row = _opens(findings)
    assert row["verdict"] == qc.REJECT, row
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert "exist" in detail or "missing" in detail, row
    assert len(findings) == 1 and findings[0]["check"] == "opens"


def test_t3_4_2_opens_real_clip_not_rejected(tmp_path, monkeypatch):
    """A real clip with a video stream is not opens-rejected."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "good.mp4"))
    findings = qc.run(path, "clip", {})
    opens = [f for f in findings if f["check"] == "opens"]
    assert not opens or opens[0]["verdict"] != qc.REJECT, opens
    assert not any(
        f["check"] == "opens" and f["verdict"] == qc.REJECT
        for f in findings), findings
