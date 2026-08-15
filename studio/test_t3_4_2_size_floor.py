"""T3-4.2-size_floor: clip under MIN_VIDEO_BYTES REJECTs.

docs/TRD-3 §4.2 table: opens, over a floor size. The failure mode is the
38 KB toy that looked like an 827 KB clip — a container and nothing else.
check_video emits size_floor REJECT when the file is under
MIN_VIDEO_BYTES, with measured/expected/unit. A real clip above the
floor is not size_floor-rejected.

Previously only qc.demo() asserted the stub path. This file is the red
test.

Mutation: delete the size_floor branch from check_video → no finding /
wrong check.
Mutation: always PASS / skip under-floor → under arm red.
Mutation: measured not equal to os.path.getsize → T3-4 red.
"""
import os
import subprocess

from conftest import _real_module

import qc


def _use_real_mixer(monkeypatch):
    real = _real_module("mixer")
    assert real is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real)


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
        f"MIN_VIDEO_BYTES")
    return path


def _sf(findings):
    rows = [f for f in findings if f["check"] == "size_floor"]
    assert rows, f"no size_floor finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_2_size_floor_constant_and_remedy():
    """Floor is named; remedy class is re-render (T3-27)."""
    assert hasattr(qc, "MIN_VIDEO_BYTES")
    assert isinstance(qc.MIN_VIDEO_BYTES, int)
    assert qc.MIN_VIDEO_BYTES > 0
    # The 38 KB toy is the motivating case; the floor is a stub floor
    # under a real short clip, not a quality bar on 38 KB itself.
    assert qc.MIN_VIDEO_BYTES < 38 * 1024
    assert qc.CHECK_REMEDY_CLASS["size_floor"] == qc.REMEDY_RERENDER


def test_t3_4_2_size_floor_under_rejects(tmp_path):
    """One variable: file size under MIN_VIDEO_BYTES → REJECT size_floor."""
    # demo() used 100 bytes; t3_32 used 1500. Stay clearly under the floor.
    n = min(100, max(1, qc.MIN_VIDEO_BYTES // 2))
    path = _stub(str(tmp_path / "stub.mp4"), n)
    assert os.path.getsize(path) < qc.MIN_VIDEO_BYTES

    row = _sf(qc.run(path, "clip", {}))
    assert row["verdict"] == qc.REJECT, row
    assert row["measured"] == n, row
    assert row["expected"] == qc.MIN_VIDEO_BYTES, row
    assert row["unit"] == "bytes", row
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert "small" in detail or "nothing" in detail or "container" in detail, row


def test_t3_4_2_size_floor_measured_matches_file_size(tmp_path):
    """T3-4: measured equals os.path.getsize, not a free-form string."""
    n = 500
    assert n < qc.MIN_VIDEO_BYTES
    path = _stub(str(tmp_path / "stub.mp4"), n)
    independent = os.path.getsize(path)
    row = _sf(qc.run(path, "clip", {}))
    assert row["measured"] == independent, (row, independent)
    assert row["measured"] == n


def test_t3_4_2_size_floor_real_clip_not_rejected(tmp_path, monkeypatch):
    """A real clip above the floor is not size_floor-rejected."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "good.mp4"))
    findings = qc.run(path, "clip", {})
    sf = [f for f in findings if f["check"] == "size_floor"]
    assert not sf or sf[0]["verdict"] != qc.REJECT, sf
    # Other checks may FLAG/PASS; size_floor must not short-circuit a good file.
    assert not any(
        f["check"] == "size_floor" and f["verdict"] == qc.REJECT
        for f in findings), findings


def test_t3_4_2_size_floor_under_returns_only_that_finding(tmp_path):
    """Under the floor: early return — size_floor only, no probe-based checks."""
    path = _stub(str(tmp_path / "toy.mp4"), 100)
    findings = qc.run(path, "clip", {})
    assert len(findings) == 1, findings
    assert findings[0]["check"] == "size_floor"
    assert findings[0]["verdict"] == qc.REJECT
