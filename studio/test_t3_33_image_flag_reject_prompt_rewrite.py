"""T3-33.a: image FLAG/REJECT remedies are the next prompt rewrite.

T3-28 already does this for identity-wrong ("edit the text"). The rest
of image QC must not propose "re-render with a different seed". A seed
change does not draw a figure the prompt did not ask for.

Structural findings (opens / resolution / size_floor) stay re-render
or pinned — a missing file is not a prompt defect. Video luma /
black_frames / frozen / channel_sat stay seed; this criterion is image.
"""
from PIL import Image
import numpy as np

import qc


def _solid(path, rgb, size=(64, 64)):
    arr = np.full((size[1], size[0], 3), rgb, dtype="uint8")
    Image.fromarray(arr).save(path)
    return path


def _rgba(path, alpha, size=(32, 32)):
    arr = np.zeros((size[1], size[0], 4), dtype="uint8")
    arr[..., 3] = alpha
    Image.fromarray(arr, "RGBA").save(path)
    return path


def _flag_reject(findings):
    return [f for f in findings if f["verdict"] in (qc.FLAG, qc.REJECT)]


def test_t3_33_image_content_checks_are_edit_text():
    """The map is the class approve() runs. Seed on these is the old world."""
    assert qc.IMAGE_PROMPT_REWRITE_CHECKS, "no image prompt-rewrite checks"
    for check in qc.IMAGE_PROMPT_REWRITE_CHECKS:
        assert check in qc.CHECK_REMEDY_CLASS, check
        assert qc.CHECK_REMEDY_CLASS[check] == qc.REMEDY_EDIT_TEXT, (
            check, qc.CHECK_REMEDY_CLASS[check])
        assert check not in qc.IMAGE_STRUCTURAL_CHECKS, check


def test_t3_33_video_seed_remedies_are_unchanged():
    """T3-33.a is image QC. Clip luma / freeze / sat stay seed."""
    for check in ("luma", "black_frames", "frozen", "channel_sat"):
        assert qc.CHECK_REMEDY_CLASS[check] == qc.REMEDY_RERENDER_SEED, check


def test_t3_33_check_image_flag_reject_is_prompt_rewrite(tmp_path):
    """A dead still's FLAG/REJECT remedy is edit the text, never a seed."""
    black = _solid(str(tmp_path / "black.png"), (0, 0, 0))
    found = qc.run(black, "image", {})
    bad = _flag_reject(found)
    assert bad, found
    for row in bad:
        text = (row.get("remedy") or "").lower()
        assert "different seed" not in text, row
        if row["check"] in qc.IMAGE_STRUCTURAL_CHECKS:
            continue
        assert row["remedy_class"] == qc.REMEDY_EDIT_TEXT, row
        assert "text" in text, row


def test_t3_33_transparent_and_flat_are_prompt_rewrites(tmp_path):
    """Alpha and not_uniform REJECTs carry the same class as T3-28."""
    clear = _rgba(str(tmp_path / "clear.png"), alpha=0)
    red = _solid(str(tmp_path / "red.png"), (200, 20, 20))
    for path, check in ((clear, "alpha"), (red, "not_uniform")):
        hit = [f for f in qc.run(path, "image", {}) if f["check"] == check]
        assert hit and hit[0]["verdict"] == qc.REJECT, (check, hit)
        text = (hit[0].get("remedy") or "").lower()
        assert hit[0]["remedy_class"] == qc.REMEDY_EDIT_TEXT, hit[0]
        assert "text" in text, hit[0]
        assert "different seed" not in text, hit[0]


def test_t3_33_identity_wrong_and_lighting_and_portrait(tmp_path):
    """T3-28 plus the other image FLAG paths share edit-the-text."""
    path = _solid(str(tmp_path / "black.png"), (0, 0, 0))
    found = qc.run(path, "image", {"identity_wrong": True})
    iw = [f for f in found if f["check"] == qc.IDENTITY_WRONG]
    assert iw and iw[0]["verdict"] == qc.FLAG, found
    assert "text" in (iw[0].get("remedy") or "").lower()
    assert iw[0]["remedy_class"] == qc.REMEDY_EDIT_TEXT

    olive = _solid(str(tmp_path / "olive.png"), (140, 160, 120))
    light = qc.check_channel_balance(olive)
    assert light and light[0]["check"] == qc.LIGHTING_LOCK, light
    text = (light[0].get("remedy") or "").lower()
    assert light[0]["remedy_class"] == qc.REMEDY_EDIT_TEXT, light[0]
    assert "text" in text, light[0]
    assert "different seed" not in text, light[0]

    fig = str(tmp_path / "fullbody.png")
    from PIL import Image
    im = Image.new("RGB", (96, 128), (140, 140, 140))
    for y in range(8, 124):
        for x in range(24, 72):
            im.putpixel((x, y), (18, 18, 18))
    im.save(fig)
    port = qc.check_portrait_crop(fig, {"portrait_crop": True})
    assert port and port[0]["verdict"] == qc.FLAG, port
    text = (port[0].get("remedy") or "").lower()
    assert port[0]["remedy_class"] == qc.REMEDY_EDIT_TEXT, port[0]
    assert "text" in text, port[0]
    assert "different seed" not in text, port[0]


def test_t3_33_structural_opens_is_not_a_prompt_rewrite():
    """A missing file is not fixed by editing the text."""
    found = qc.run("/no/such/image.png", "image", {})
    hit = [f for f in found if f["check"] == "opens"]
    assert hit and hit[0]["verdict"] == qc.REJECT, found
    assert hit[0]["remedy_class"] == qc.REMEDY_RERENDER, hit[0]
    assert "different seed" not in (hit[0].get("remedy") or "").lower()
