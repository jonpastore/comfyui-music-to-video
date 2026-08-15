"""T3-4.1-resolution: image resolution vs the workflow's request.

docs/TRD-3 §4.1: resolution as requested on anchors/refs/candidates.
When expect names width and height, check_image measures the file
(PIL size) and compares exactly (no soft tolerance).

Matching size PASSes. 160x120 against 320x240 requested REJECTs.
measured is the file's WxH, expected is the request, unit px.
Without expect width+height, check_image emits no resolution finding.

Mutation: delete the check from check_image → no resolution finding.
Mutation: always PASS → downscaled arm red.
Mutation: measured not equal to PIL size → T3-4 red.
Mutation: unit is None → T3-4 red (unit must be recorded; T3-4 names
resolution and check_image used to pass unit=None).
"""
from PIL import Image

import qc


def _png(path, size, colour=(40, 80, 120)):
    # Non-uniform, non-blank so not_uniform / not_blank stay out of the way.
    w, h = size
    im = Image.new("RGB", (w, h), colour)
    # Slight gradient so std is not zero.
    px = im.load()
    for x in range(min(8, w)):
        for y in range(min(8, h)):
            px[x, y] = (colour[0] + x * 10, colour[1] + y * 5, colour[2])
    im.save(path)
    return str(path)


def _res(findings):
    rows = [f for f in findings if f["check"] == "resolution"]
    assert rows, f"no resolution finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_4_1_resolution_match_passes_mismatch_rejects(tmp_path):
    """One variable: the image size against expect width/height."""
    good = _png(tmp_path / "ok.png", (320, 240))
    bad = _png(tmp_path / "down.png", (160, 120))
    expect = {"width": 320, "height": 240}

    row = _res(qc.run(good, "image", expect))
    assert row["verdict"] == qc.PASS, row
    assert row["measured"] == "320x240", row
    assert row["expected"] == "320x240", row
    assert row["unit"] == "px", row
    assert row["remedy_class"] == qc.REMEDY_RERENDER_PINNED
    detail = (row["detail"] or "").lower()
    assert "320" in detail and "240" in detail, row

    row = _res(qc.run(bad, "image", expect))
    assert row["verdict"] == qc.REJECT, row
    assert row["measured"] == "160x120", row
    assert row["expected"] == "320x240", row
    assert row["unit"] == "px", row
    assert row["remedy_class"] == qc.REMEDY_RERENDER_PINNED
    detail = (row["detail"] or "").lower()
    assert "160" in detail and "320" in detail, row


def test_t3_4_1_resolution_measured_matches_pil(tmp_path):
    """T3-4: measured equals PIL size WxH, not a free-form string."""
    path = _png(tmp_path / "down.png", (160, 120))
    with Image.open(path) as im:
        independent = f"{im.size[0]}x{im.size[1]}"
    assert independent == "160x120", independent
    row = _res(qc.run(path, "image", {"width": 320, "height": 240}))
    assert row["measured"] == independent, (row, independent)
    assert row["unit"] == "px", row


def test_t3_4_1_resolution_without_expect_emits_nothing(tmp_path):
    """As requested: no width+height request means no resolution finding."""
    path = _png(tmp_path / "any.png", (320, 240))
    findings = qc.run(path, "image", {})
    assert not any(f["check"] == "resolution" for f in findings), [
        f["check"] for f in findings]
