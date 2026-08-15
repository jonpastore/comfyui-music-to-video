"""T3-4.1-opens: image opens via PIL — missing/unreadable REJECT.

docs/TRD-3 §4.1: anchors/refs/candidates must open. A missing path or
bytes that PIL cannot identify REJECTs `opens` (tier-1, no judgement).
A real PNG is not an opens reject. Images deliberately have no size
floor — a blank 1×1 PNG is tiny because PNG compresses uniform data;
PIL open answers "is this an image", not byte count (size_floor is
§4.2 / T3-4.2-size_floor for clips).

Mutation: delete the missing-path branch → no opens finding.
Mutation: delete the PIL except branch → junk PASSes or other checks run.
Mutation: apply MIN_VIDEO_BYTES / size_floor to images → tiny real PNG
is wrongly rejected as opens or size_floor.
Mutation: always PASS opens → missing/junk arms red.
"""
import os

from PIL import Image
import numpy as np

import qc


def _png(path, size=(64, 64), color=(40, 80, 160)):
    """Non-uniform RGB so not_uniform/not_blank stay out of the way."""
    w, h = size
    arr = np.zeros((h, w, 3), dtype="uint8")
    arr[..., 0] = color[0]
    arr[..., 1] = color[1]
    arr[..., 2] = color[2]
    for x in range(min(8, w)):
        for y in range(min(8, h)):
            arr[y, x] = (
                min(255, color[0] + x * 10),
                min(255, color[1] + y * 5),
                color[2],
            )
    Image.fromarray(arr, mode="RGB").save(path)
    return path


def _opens(findings):
    rows = [f for f in findings if f["check"] == "opens"]
    assert rows, f"no opens finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_1_opens_remedy_class():
    """T3-27: opens names re-render before a finding can be emitted."""
    assert "opens" in qc.CHECK_REMEDY_CLASS, (
        "opens not in CHECK_REMEDY_CLASS — T3-4.1-opens not wired")
    assert qc.CHECK_REMEDY_CLASS["opens"] == qc.REMEDY_RERENDER


def test_t3_4_1_opens_missing_rejects():
    """One variable: path does not exist → REJECT opens only."""
    path = "/tmp/t3_4_1_opens_no_such_file.png"
    assert not os.path.isfile(path)
    findings = qc.run(path, "image", {})
    assert len(findings) == 1, findings
    row = _opens(findings)
    assert row["verdict"] == qc.REJECT, row
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert "exist" in detail or "missing" in detail or "not found" in detail, row


def test_t3_4_1_opens_unreadable_rejects(tmp_path):
    """One variable: bytes that PIL cannot open → REJECT opens."""
    path = str(tmp_path / "junk.bin")
    with open(path, "wb") as f:
        f.write(b"not an image file at all\x00\x01\x02")
    assert os.path.isfile(path)
    findings = qc.run(path, "image", {})
    assert len(findings) == 1, findings
    row = _opens(findings)
    assert row["verdict"] == qc.REJECT, row
    assert row["remedy_class"] == qc.REMEDY_RERENDER
    detail = (row["detail"] or "").lower()
    assert "open" in detail or "identify" in detail or "cannot" in detail, row


def test_t3_4_1_opens_real_png_not_opens_reject(tmp_path):
    """A real PNG is not an opens reject — PIL path, not size floor."""
    path = _png(str(tmp_path / "ok.png"))
    findings = qc.run(path, "image", {})
    opens = [f for f in findings if f["check"] == "opens"]
    assert not any(f["verdict"] == qc.REJECT for f in opens), opens
    # Must reach image content checks (PIL succeeded).
    assert any(f["check"] in ("not_uniform", "not_blank", "alpha")
               for f in findings), [f["check"] for f in findings]


def test_t3_4_1_opens_tiny_png_not_size_floor(tmp_path):
    """Images have no size floor: tiny real PNG is not opens/size_floor REJECT.

    A 1×1 PNG is well under MIN_VIDEO_BYTES; applying the clip floor would
    reject a blank render with the wrong reason.
    """
    path = str(tmp_path / "tiny.png")
    Image.new("RGB", (1, 1), (0, 0, 0)).save(path)
    n = os.path.getsize(path)
    assert n < qc.MIN_VIDEO_BYTES, (n, qc.MIN_VIDEO_BYTES)
    findings = qc.run(path, "image", {})
    assert not any(
        f["check"] == "opens" and f["verdict"] == qc.REJECT
        for f in findings), findings
    assert not any(
        f["check"] == "size_floor" and f["verdict"] == qc.REJECT
        for f in findings), findings
    # Content checks may REJECT blank/black — that is not opens.
    assert any(f["check"] in ("not_blank", "not_uniform", "alpha")
               for f in findings), [f["check"] for f in findings]
