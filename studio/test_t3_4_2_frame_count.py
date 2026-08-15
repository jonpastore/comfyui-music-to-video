"""T3-4.2-frame_count: clip frame count vs the workflow's request.

docs/TRD-3 §4.2 table: frame count is the workflow's request; a truncated
or wrong-length render is the failure mode. When expect names frames,
check_video measures the file via qc._ffprobe_frames (ffprobe nb_frames
/ packet count — not duration*fps) and compares exactly.

Matching count PASSes. 81 frames against 505 requested REJECTs.
measured is the file's frame count, expected is the request, unit frames.
Without expect.frames, check_video emits no frame_count finding.

Not T3-7: that check is latent_8n1 (the model's own step). This criterion
is the plain request match on a normal clip.

Mutation: delete the check from check_video → no frame_count finding.
Mutation: always PASS → 505-vs-81 arm red.
Mutation: measured not equal to _ffprobe_frames → T3-4 red.
Mutation: unit is None → T3-4 red (unit must be recorded).
"""
import os
import subprocess

from conftest import _real_module

import qc

CLIP_FRAMES = 81
WRONG_FRAMES = 505
CLIP_FPS = 16


def _use_real_mixer(monkeypatch):
    real = _real_module("mixer")
    assert real is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real)
    return real


def _mp4(path, frames, fps=CLIP_FPS, size="320x240"):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}",
         "-frames:v", str(frames), "-c:v", "mpeg4", "-q:v", "5",
         "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.getsize(path) >= qc.MIN_VIDEO_BYTES, (
        f"fixture {path} is {os.path.getsize(path)} bytes — under "
        f"MIN_VIDEO_BYTES; size_floor would hide frame_count")
    return path


def _frame_count(findings):
    rows = [f for f in findings if f["check"] == "frame_count"]
    assert rows, f"no frame_count finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_2_frame_count_ffprobe_reports_count(tmp_path, monkeypatch):
    """_ffprobe_frames is the reading. A count that never surfaces cannot be checked."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "81.mp4"), CLIP_FRAMES)
    got = qc._ffprobe_frames(path)
    assert got == CLIP_FRAMES, got


def test_t3_4_2_frame_count_match_passes_505_vs_81_rejects(tmp_path, monkeypatch):
    """One variable: the file frame count against expect.frames.

    Demo case: 81-frame file PASSes frames=81; same file against 505 REJECTs.
    """
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "clip.mp4"), CLIP_FRAMES)

    row = _frame_count(qc.run(
        path, "clip", {"frames": CLIP_FRAMES, "latent_rule": False}))
    assert row["verdict"] == qc.PASS, row
    assert int(row["measured"]) == CLIP_FRAMES, row
    assert int(row["expected"]) == CLIP_FRAMES, row
    assert row["unit"] == "frames"
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert str(CLIP_FRAMES) in detail, row

    row = _frame_count(qc.run(
        path, "clip", {"frames": WRONG_FRAMES, "latent_rule": False}))
    assert row["verdict"] == qc.REJECT, row
    assert int(row["measured"]) == CLIP_FRAMES, row
    assert int(row["expected"]) == WRONG_FRAMES, row
    assert row["unit"] == "frames"
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert str(CLIP_FRAMES) in detail and str(WRONG_FRAMES) in detail, row


def test_t3_4_2_frame_count_measured_matches_ffprobe(tmp_path, monkeypatch):
    """T3-4: measured equals _ffprobe_frames, not a free-form number."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "clip.mp4"), CLIP_FRAMES)
    independent = qc._ffprobe_frames(path)
    assert independent == CLIP_FRAMES, independent
    row = _frame_count(qc.run(
        path, "clip", {"frames": WRONG_FRAMES, "latent_rule": False}))
    assert int(row["measured"]) == independent, (row, independent)
    assert int(row["measured"]) != int(row["expected"]), row


def test_t3_4_2_frame_count_without_expect_emits_nothing(tmp_path, monkeypatch):
    """As requested: no frames request means no frame_count finding.

    latent_8n1 may still fire — that is T3-7, not this criterion.
    """
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "any.mp4"), CLIP_FRAMES)
    findings = qc.run(path, "clip", {"latent_rule": False})
    assert not any(f["check"] == "frame_count" for f in findings), [
        f["check"] for f in findings]


def test_t3_4_2_frame_count_is_not_latent_8n1(tmp_path, monkeypatch):
    """T3-7 owns latent step; this criterion owns request match only."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "clip.mp4"), CLIP_FRAMES)
    findings = qc.run(path, "clip", {"frames": CLIP_FRAMES, "latent_rule": False})
    assert any(f["check"] == "frame_count" for f in findings)
    assert not any(f["check"] == "latent_8n1" for f in findings), [
        f["check"] for f in findings]
