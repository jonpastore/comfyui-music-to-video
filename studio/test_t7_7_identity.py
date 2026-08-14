"""T7-7 identity look is human-judged. This file encodes the offline hook only.

docs/TRD-7 T7-7 and DDD-4-7 §4: the sheet must be HER (the chosen identity
ref / UI pair), not the pose-plate person. No threshold, no vision model, no
GPU. The hook fails when the identity path is missing or is the plate; a
named, distinct identity path satisfies the prerequisite. The picture itself
stays a human look.

docs/TRD-4 T4-14: a nude compose that asserts a human body ("human form" in
nude_wardrobe — the measured live-studio collapse) is the same defect as
losing her. The hook flags that compose without rendering.
"""
import os
import sys

import qc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import make_anchor


# Measured live-studio nude_wardrobe from
# docs/reviews/ANCHOR-FIELDS-HUMAN-BODY-grok-2026-08-13.md. That wording
# composed a feline-headed woman with a human body.
HUMAN_FORM_NUDE = (
    "Completely naked adult body, fully bare and exposed, "
    "jet-black skin uncovered over her whole human form."
)


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


def _compose_nude(nude_wardrobe, body=None):
    """Real composer, not a string check on the field alone."""
    anchor = make_anchor.anchor_from({
        "identity": "Adult anthropomorphic black feline woman.",
        "body": body or "Her entire body is covered in sleek jet-black fur.",
        "nude_wardrobe": nude_wardrobe,
    })
    return make_anchor.prompt_for("front_nude", anchor)


def test_t7_7_human_body_compose_flags():
    """T4-14 / T7-7: nude_wardrobe 'human form' is the measured identity collapse.

    A valid identity_path does not save it. The compose itself is the defect.
    No GPU, no pixels.
    """
    composed = _compose_nude(HUMAN_FORM_NUDE)
    assert "human form" in composed.lower(), composed
    found = qc.check_identity_look(SHEET, {
        "identity_path": UI_IDENTITY,
        "plate_path": POSE_PLATE,
        "composed": composed,
        "nude_wardrobe": HUMAN_FORM_NUDE,
    })
    hit = _by_check(found, qc.IDENTITY_LOOK)
    assert hit and hit[0]["verdict"] == qc.FLAG, found
    detail = (hit[0]["detail"] or "").lower()
    assert "human" in detail, hit[0]
    measured = str(hit[0].get("measured") or "").lower()
    assert "human form" in measured or "human form" in detail, hit[0]


def test_t7_7_furred_nude_compose_is_not_a_human_body():
    """T4-14 positive half: default nude compose still writes, without human form."""
    composed = _compose_nude(make_anchor.NUDE_WARDROBE)
    assert "human form" not in composed.lower(), composed
    assert "bare skin" not in composed.lower(), composed
    found = qc.check_identity_look(SHEET, {
        "identity_path": UI_IDENTITY,
        "plate_path": POSE_PLATE,
        "composed": composed,
        "nude_wardrobe": make_anchor.NUDE_WARDROBE,
    })
    hit = _by_check(found, qc.IDENTITY_LOOK)
    assert hit and hit[0]["verdict"] == qc.PASS, found
