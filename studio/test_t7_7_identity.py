"""T7-7 identity look is human-judged. This file encodes the offline hook only.

docs/TRD-7 T7-7 and DDD-4-7 §4: the sheet must be HER (the chosen identity
ref / UI pair), not the pose-plate person. No threshold, no vision model, no
GPU. The hook fails when the identity path is missing or is the plate; a
named, distinct identity path satisfies the prerequisite. The picture itself
stays a human look.

docs/TRD-4 T4-14: a nude compose that asserts a human body ("human form" in
nude_wardrobe — the measured live-studio collapse) is the same defect as
losing her. The hook flags that compose through check_image / qc.run /
qc_service.run_artefact on the composer output (`composed` or the studio
`prompt` key), not the raw field. A clean album field must not hide a dirty
compose. A missing identity_path must not hide the human-body reason.
The live-studio body clause ("Human woman's body") is the same collapse.
No GPU.
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


HARNESS = "A black leather harness and platform boots."


def _sheet(tmp_path):
    """Real image so the hook is asserted through check_image / qc.run."""
    from PIL import Image
    path = tmp_path / "sheet.png"
    Image.new("RGB", (32, 32), (80, 80, 80)).save(path)
    return str(path)


def _compose_nude(nude_wardrobe, body=None, wardrobe=None):
    """Real composer, not a string check on the field alone."""
    anchor = make_anchor.anchor_from({
        "identity": "Adult anthropomorphic black feline woman.",
        "body": body or "Her entire body is covered in sleek jet-black fur.",
        "wardrobe": wardrobe or HARNESS,
        "nude_wardrobe": nude_wardrobe,
    })
    return make_anchor.prompt_for("front_nude", anchor)


def _human_body_hit(found):
    """The FLAG reason is the human-body compose, not a missing identity_path."""
    hit = _by_check(found, qc.IDENTITY_LOOK)
    assert hit and hit[0]["verdict"] == qc.FLAG, found
    blob = f"{hit[0].get('detail')} {hit[0].get('measured')}".lower()
    assert "human form" in blob, hit[0]
    return hit[0]


def test_t7_7_human_body_compose_flags(tmp_path):
    """T4-14 / T7-7: nude_wardrobe 'human form' is the measured identity collapse.

    Shared entry (check_image), composer output only — a field-only hook that
    never reads the composed prompt must go red. A valid identity_path does
    not save it. No GPU, no pixels.
    """
    composed = _compose_nude(HUMAN_FORM_NUDE)
    assert "human form" in composed.lower(), composed
    assert "leather harness" not in composed.lower(), composed
    found = qc.check_image(_sheet(tmp_path), {
        "identity_path": UI_IDENTITY,
        "plate_path": POSE_PLATE,
        "composed": composed,
    })
    _human_body_hit(found)


def test_t7_7_human_body_prompt_key_flags(tmp_path):
    """The studio's sent text is `prompt`. Same collapse, same FLAG."""
    composed = _compose_nude(HUMAN_FORM_NUDE)
    assert "human form" in composed.lower(), composed
    found = qc.check_image(_sheet(tmp_path), {
        "identity_path": UI_IDENTITY,
        "plate_path": POSE_PLATE,
        "prompt": composed,
    })
    _human_body_hit(found)


def test_t7_7_human_body_compose_flags_without_identity_path(tmp_path):
    """The compose is the defect. Missing identity_path must not hide it.

    Ordinary image QC with no keys stays silent (test above). A composed
    human-form prompt is not ordinary QC — it must FLAG as human form,
    not as a missing identity_path and not as no finding at all.
    """
    composed = _compose_nude(HUMAN_FORM_NUDE)
    assert "human form" in composed.lower(), composed
    found = qc.check_image(_sheet(tmp_path), {"composed": composed})
    _human_body_hit(found)


def test_t7_7_human_body_compose_flags_through_run(tmp_path):
    """Studio QC entry is qc.run. Same compose, same FLAG, no identity_path."""
    composed = _compose_nude(HUMAN_FORM_NUDE)
    assert "human form" in composed.lower(), composed
    found = qc.run(_sheet(tmp_path), "image", {"composed": composed})
    _human_body_hit(found)


def test_t7_7_dirty_compose_flags_even_if_nude_wardrobe_field_is_clean(tmp_path):
    """Composer output is the artefact. A clean album field must not hide it.

    A hook that only reads expect['nude_wardrobe'] stays green on the
    measured collapse once the field is reset and the sent prompt is not.
    """
    composed = _compose_nude(HUMAN_FORM_NUDE)
    assert "human form" in composed.lower(), composed
    assert HUMAN_FORM_NUDE.lower() not in make_anchor.NUDE_WARDROBE.lower()
    found = qc.check_image(_sheet(tmp_path), {
        "identity_path": UI_IDENTITY,
        "plate_path": POSE_PLATE,
        "composed": composed,
        "nude_wardrobe": make_anchor.NUDE_WARDROBE,
    })
    _human_body_hit(found)


def test_t7_7_human_body_compose_flags_through_run_artefact(tmp_path):
    """Studio persistence path. Same nude_wardrobe human-form compose, FLAG stored."""
    import db
    import jobs
    import qc_service

    composed = _compose_nude(HUMAN_FORM_NUDE)
    assert "human form" in composed.lower(), composed
    sheet = _sheet(tmp_path)
    found = qc_service.run_artefact(sheet, "image", {"composed": composed})
    _human_body_hit(found)
    path = jobs.canonical_path(sheet)
    row = db.one(
        "SELECT * FROM findings WHERE path=? AND check_name=?",
        path, qc.IDENTITY_LOOK)
    assert row, "identity_look FLAG was not recorded"
    assert row["verdict"] == qc.FLAG, dict(row)
    blob = f"{row['detail']} {row['measured']}".lower()
    assert "human form" in blob, dict(row)


def test_t7_7_back_nude_human_form_compose_flags(tmp_path):
    """The collapse is not front-only. Same nude_wardrobe, back_nude compose."""
    anchor = make_anchor.anchor_from({
        "identity": "Adult anthropomorphic black feline woman.",
        "body": "Her entire body is covered in sleek jet-black fur.",
        "wardrobe": HARNESS,
        "nude_wardrobe": HUMAN_FORM_NUDE,
    })
    composed = make_anchor.prompt_for("back_nude", anchor)
    assert "human form" in composed.lower(), composed
    assert "leather harness" not in composed.lower(), composed
    found = qc.check_image(_sheet(tmp_path), {
        "identity_path": UI_IDENTITY,
        "plate_path": POSE_PLATE,
        "composed": composed,
    })
    _human_body_hit(found)


# Measured live-studio body from the same review. Nude_wardrobe can be the
# default furred clause and the sheet still collapses if body asserts a
# human woman. T4-14: body not human skin.
LIVE_STUDIO_BODY = (
    "Human woman's body with human anatomy, human proportions and human "
    "musculature, smooth jet-black skin with a deep near-black sheen "
    "matching her face, uniform jet-black colouring across shoulders, arms, "
    "breasts, torso, stomach, hips, glutes, thighs, knees, calves, human "
    "hands with fingers and human feet with toes."
)


def test_t7_7_live_studio_body_compose_flags(tmp_path):
    """T4-14 other half: live-studio body wording is a human-body compose.

    Default nude_wardrobe stays. The body clause is what asserts a human
    woman. A hook that only searches 'human form' in nude_wardrobe stays
    green. No GPU.
    """
    composed = _compose_nude(make_anchor.NUDE_WARDROBE, body=LIVE_STUDIO_BODY)
    assert "human form" not in composed.lower(), composed
    assert "human woman's body" in composed.lower(), composed
    assert "leather harness" not in composed.lower(), composed
    found = qc.check_image(_sheet(tmp_path), {
        "identity_path": UI_IDENTITY,
        "plate_path": POSE_PLATE,
        "composed": composed,
    })
    hit = _by_check(found, qc.IDENTITY_LOOK)
    assert hit and hit[0]["verdict"] == qc.FLAG, found
    blob = f"{hit[0].get('detail')} {hit[0].get('measured')}".lower()
    assert "human woman's body" in blob or "human anatomy" in blob, hit[0]


def test_t7_7_live_studio_body_field_flags(tmp_path):
    """Same collapse on the album body field. No pre-baked composed string.

    A hook that only reads composed/prompt/nude_wardrobe stays green when
    the studio stores the fields the composer actually used.
    """
    assert "human form" not in LIVE_STUDIO_BODY.lower()
    found = qc.check_image(_sheet(tmp_path), {
        "identity_path": UI_IDENTITY,
        "plate_path": POSE_PLATE,
        "nude_wardrobe": make_anchor.NUDE_WARDROBE,
        "body": LIVE_STUDIO_BODY,
    })
    hit = _by_check(found, qc.IDENTITY_LOOK)
    assert hit and hit[0]["verdict"] == qc.FLAG, found
    blob = f"{hit[0].get('detail')} {hit[0].get('measured')}".lower()
    assert "human woman's body" in blob or "human anatomy" in blob, hit[0]


def test_t7_7_furred_nude_compose_is_not_a_human_body(tmp_path):
    """T4-14 positive half: default nude compose still writes, without human form."""
    composed = _compose_nude(make_anchor.NUDE_WARDROBE)
    assert "human form" not in composed.lower(), composed
    assert "bare skin" not in composed.lower(), composed
    assert "leather harness" not in composed.lower(), composed
    found = qc.check_image(_sheet(tmp_path), {
        "identity_path": UI_IDENTITY,
        "plate_path": POSE_PLATE,
        "composed": composed,
    })
    hit = _by_check(found, qc.IDENTITY_LOOK)
    assert hit and hit[0]["verdict"] == qc.PASS, found
