"""T3-35: pose / identity FAIL names a settings remedy class.

Named classes: latent / denoise / CFG / pose-match / plate-absent /
body-colour. Expect-driven: C1 + empty latent → latent; C2 pose
mismatch → pose-match; stranger or missing-her image1 → plate-absent
(never swap-stranger); jet-black vs charcoal → body-colour.

Mutation: plate-as-image1 FAIL still only edit-text → red.
T3-33.a: blank / uniform / alpha stay edit-text.
"""
from PIL import Image
import numpy as np

import qc
import qc_settings


PATH = "/out/t335_sheet.png"


def _solid(path, rgb, size=(64, 64)):
    arr = np.full((size[1], size[0], 3), rgb, dtype="uint8")
    Image.fromarray(arr).save(path)
    return path


def _rgba(path, alpha, size=(32, 32)):
    arr = np.zeros((size[1], size[0], 4), dtype="uint8")
    arr[..., 3] = alpha
    Image.fromarray(arr, "RGBA").save(path)
    return path


def _iw(expect, kind="image"):
    return qc.check_identity_wrong(PATH, expect, kind=kind)


def test_t3_35_named_settings_classes_exist():
    """The six names are the product, not a comment."""
    assert qc.REMEDY_LATENT == "latent"
    assert qc.REMEDY_DENOISE == "denoise"
    assert qc.REMEDY_CFG == "CFG"
    assert qc.REMEDY_POSE_MATCH == "pose-match"
    assert qc.REMEDY_PLATE_ABSENT == "plate-absent"
    assert qc.REMEDY_BODY_COLOUR == "body-colour"
    assert qc.SETTINGS_REMEDY_CLASSES == frozenset({
        "latent", "denoise", "CFG", "pose-match", "plate-absent", "body-colour",
    })
    assert qc.SETTINGS_REMEDY_CLASSES == qc_settings.SETTINGS_REMEDY_CLASSES
    for cls in qc.SETTINGS_REMEDY_CLASSES:
        assert cls in qc_settings.SETTINGS_REMEDY_TEXT, cls
        assert qc_settings.SETTINGS_REMEDY_TEXT[cls]


def test_t3_35_c1_empty_latent_is_latent():
    """C1 same-pose that used empty latent is latent, not edit-text."""
    found = _iw({"identity_wrong": True, "kind": "c1", "latent": "empty"})
    assert found and found[0]["remedy_class"] == qc.REMEDY_LATENT, found
    assert found[0]["remedy_class"] != qc.REMEDY_EDIT_TEXT
    assert "latent" in (found[0].get("remedy") or "").lower()
    same = _iw({
        "pose_fail": True, "pose_label": "same-pose", "latent": "empty",
    })
    assert same and same[0]["remedy_class"] == qc.REMEDY_LATENT, same
    ok = qc.resolve_settings_remedy({"kind": "c1", "latent": "image"})
    assert ok is None, ok


def test_t3_35_c2_pose_mismatch_is_pose_match():
    """C2 whose pose text is not the asked pose is pose-match."""
    found = _iw({
        "pose_fail": True,
        "kind": "c2",
        "pose": "standing upright, arms relaxed",
        "asked_pose": "kneeling",
    })
    assert found and found[0]["remedy_class"] == qc.REMEDY_POSE_MATCH, found
    assert found[0]["remedy_class"] != qc.REMEDY_EDIT_TEXT
    assert "pose" in (found[0].get("remedy") or "").lower()
    match = qc.resolve_settings_remedy({
        "kind": "c2", "pose": "kneeling on the floor", "asked_pose": "kneeling",
    })
    assert match is None, match


def test_t3_35_stranger_image1_is_plate_absent():
    """A stranger plate as image1 is plate-absent, never swap-stranger."""
    found = _iw({
        "identity_wrong": True,
        "image1": "stranger-plate.jpg",
        "image1_kind": "plate",
    })
    assert found and found[0]["remedy_class"] == qc.REMEDY_PLATE_ABSENT, found
    remedy = (found[0].get("remedy") or "").lower()
    assert found[0]["remedy_class"] != qc.REMEDY_EDIT_TEXT
    assert not qc.proposes_reference_swap(found[0].get("remedy")), found[0]
    assert "swap" not in remedy
    assert "stranger" not in remedy or "not" in remedy
    missing = _iw({"identity_wrong": True, "her_photos": [], "kind": "c2"})
    assert missing and missing[0]["remedy_class"] == qc.REMEDY_PLATE_ABSENT, missing


def test_t3_35_plate_as_image1_fail_is_not_only_edit_text():
    """Mutation: only edit-text on a plate-as-image1 FAIL → red."""
    found = _iw({"identity_wrong": True, "plate_as_image1": True})
    assert found, found
    assert found[0]["remedy_class"] == qc.REMEDY_PLATE_ABSENT, found[0]
    assert found[0]["remedy_class"] != qc.REMEDY_EDIT_TEXT, (
        "plate-as-image1 FAIL still only edit-text")
    via_run = [
        f for f in qc.run(PATH, "image", {
            "identity_wrong": True, "plate_as_image1": True,
        })
        if f["check"] == qc.IDENTITY_WRONG
    ]
    assert via_run and via_run[0]["remedy_class"] == qc.REMEDY_PLATE_ABSENT, via_run


def test_t3_35_jet_black_vs_charcoal_is_body_colour():
    """Jet-black body vs charcoal-brown source photos is body-colour."""
    found = _iw({
        "identity_wrong": True,
        "body": "Her entire body is covered in sleek jet-black fur.",
    })
    assert found and found[0]["remedy_class"] == qc.REMEDY_BODY_COLOUR, found
    assert found[0]["remedy_class"] != qc.REMEDY_EDIT_TEXT
    text = (found[0].get("remedy") or "").lower()
    assert "charcoal" in text
    assert "jet-black" in text
    charcoal = qc.resolve_settings_remedy({
        "body": "covered in the same sleek charcoal-brown fur",
    })
    assert charcoal is None, charcoal


def test_t3_35_denoise_and_cfg_are_named():
    """Denoise and CFG exist as named classes when expect diagnoses them."""
    den = qc.resolve_settings_remedy({"denoise": 0.55, "asked_denoise": 1.0})
    assert den == qc.REMEDY_DENOISE, den
    cfg = qc.resolve_settings_remedy({"cfg": 7.0, "asked_cfg": 2.0})
    assert cfg == qc.REMEDY_CFG, cfg
    found = _iw({"identity_wrong": True, "denoise_wrong": True})
    assert found and found[0]["remedy_class"] == qc.REMEDY_DENOISE, found


def test_t3_35_plain_identity_wrong_stays_edit_text():
    """No settings diagnosis: T3-28 / T3-33.a still edit the text."""
    found = _iw({"identity_wrong": True})
    assert found and found[0]["remedy_class"] == qc.REMEDY_EDIT_TEXT, found
    assert "text" in (found[0].get("remedy") or "").lower()
    assert not qc.proposes_reference_swap(found[0].get("remedy"))


def test_t3_35_blank_uniform_alpha_stay_edit_text(tmp_path):
    """T3-33.a: dead-still content findings stay a prompt rewrite."""
    black = _solid(str(tmp_path / "black.png"), (0, 0, 0))
    red = _solid(str(tmp_path / "red.png"), (200, 20, 20))
    clear = _rgba(str(tmp_path / "clear.png"), alpha=0)
    for path, check in (
        (black, "not_blank"),
        (red, "not_uniform"),
        (clear, "alpha"),
    ):
        hit = [f for f in qc.run(path, "image", {}) if f["check"] == check]
        assert hit and hit[0]["verdict"] == qc.REJECT, (check, hit)
        assert hit[0]["remedy_class"] == qc.REMEDY_EDIT_TEXT, hit[0]
        assert hit[0]["remedy_class"] not in qc.SETTINGS_REMEDY_CLASSES
    assert qc.CHECK_REMEDY_CLASS["not_blank"] == qc.REMEDY_EDIT_TEXT
    assert qc.CHECK_REMEDY_CLASS["not_uniform"] == qc.REMEDY_EDIT_TEXT
    assert qc.CHECK_REMEDY_CLASS["alpha"] == qc.REMEDY_EDIT_TEXT
