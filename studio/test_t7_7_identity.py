"""T7-7 identity look is human-judged. This file encodes the offline hook only.

docs/TRD-7 T7-7 and DDD-4-7 §4: the sheet must be HER (the chosen identity
ref / UI pair), not the pose-plate person. No threshold, no vision model, no
GPU. The hook fails when the identity path is missing or is the plate; a
named, distinct identity path satisfies the prerequisite. The picture itself
stays a human look.
"""
import os

import qc


UI_IDENTITY = "/refs/meowp_ui_front.png"
POSE_PLATE = "/plates/pose_plate.png"
SHEET = "/out/front_sheet.png"


def _by_check(findings, name):
    return [f for f in findings if f["check"] == name]


def test_t7_7_identity_look_hook_exists():
    """The finding kind is a named QC check, not a comment in a doc."""
    assert qc.IDENTITY_LOOK == "identity_look"
    assert callable(qc.check_identity_look)


def test_t7_7_missing_identity_path_flags():
    """The hook cannot run without a named identity ref."""
    found = qc.check_identity_look(SHEET, {})
    hit = _by_check(found, qc.IDENTITY_LOOK)
    assert hit, found
    assert hit[0]["verdict"] == qc.FLAG, hit[0]
    assert hit[0]["measured"] in (None, "", "None")
    assert "identity" in (hit[0]["detail"] or "").lower()


def test_t7_7_asked_without_a_path_flags():
    found = qc.check_identity_look(SHEET, {"identity_look": True})
    hit = _by_check(found, qc.IDENTITY_LOOK)
    assert hit and hit[0]["verdict"] == qc.FLAG, found


def test_t7_7_empty_identity_path_flags():
    found = qc.check_identity_look(SHEET, {"identity_path": "   "})
    hit = _by_check(found, qc.IDENTITY_LOOK)
    assert hit and hit[0]["verdict"] == qc.FLAG, found


def test_t7_7_plate_as_identity_flags():
    """Chosen identity ref vs plate: the plate person is the failure."""
    found = qc.check_identity_look(SHEET, {
        "identity_path": POSE_PLATE,
        "plate_path": POSE_PLATE,
    })
    hit = _by_check(found, qc.IDENTITY_LOOK)
    assert hit and hit[0]["verdict"] == qc.FLAG, found
    assert hit[0]["measured"] == os.path.normpath(POSE_PLATE)


def test_t7_7_chosen_identity_ref_is_not_the_plate():
    """UI pair as image1, plate as image2: the hook's prerequisite holds.

    This is not a claim that the pixels look like her — T7-7 stays human.
    """
    found = qc.check_identity_look(SHEET, {
        "identity_path": UI_IDENTITY,
        "plate_path": POSE_PLATE,
    })
    hit = _by_check(found, qc.IDENTITY_LOOK)
    assert hit and hit[0]["verdict"] == qc.PASS, found
    assert hit[0]["measured"] == os.path.normpath(UI_IDENTITY)
    assert "meowp_ui_front.png" in str(hit[0]["measured"])


def test_t7_7_unasked_image_qc_does_not_emit_the_hook(tmp_path):
    """Ordinary image QC (no identity keys) must not invent a look verdict."""
    sheet = tmp_path / "sheet.png"
    from PIL import Image
    Image.new("RGB", (32, 32), (80, 80, 80)).save(sheet)
    found = qc.check_image(str(sheet), {})
    assert _by_check(found, qc.IDENTITY_LOOK) == []
