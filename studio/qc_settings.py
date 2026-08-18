"""T3-35: named settings remedies for pose / identity FAIL.

Default image FLAG/REJECT is still edit-text (T3-33.a). A pose or
identity FAIL names the settings class the expect diagnoses:
latent / denoise / CFG / pose-match / plate-absent / body-colour.

No pixels, no database, no FastAPI. qc.check_identity_wrong calls
resolve_settings_remedy and puts the class on the finding.
"""

REMEDY_LATENT = "latent"
REMEDY_DENOISE = "denoise"
REMEDY_CFG = "CFG"
REMEDY_POSE_MATCH = "pose-match"
REMEDY_PLATE_ABSENT = "plate-absent"
REMEDY_BODY_COLOUR = "body-colour"

SETTINGS_REMEDY_CLASSES = frozenset({
    REMEDY_LATENT,
    REMEDY_DENOISE,
    REMEDY_CFG,
    REMEDY_POSE_MATCH,
    REMEDY_PLATE_ABSENT,
    REMEDY_BODY_COLOUR,
})

SETTINGS_REMEDY_TEXT = {
    REMEDY_LATENT: "C1 same-pose needs image latent, not empty",
    REMEDY_DENOISE: "use the denoise that matches the latent",
    REMEDY_CFG: "use the asked CFG",
    REMEDY_POSE_MATCH: "C2 pose text must match the asked pose",
    REMEDY_PLATE_ABSENT: (
        "put her photographs as image1; a stranger plate is not identity"),
    REMEDY_BODY_COLOUR: (
        "name charcoal-brown to match the source photos, not jet-black"),
}

_PLATE_KINDS = frozenset({"plate", "stranger"})


def _kind(expect):
    return str(
        expect.get("kind")
        or expect.get("job_kind")
        or expect.get("c1_c2")
        or ""
    ).strip().lower()


def _latent(expect):
    return str(expect.get("latent") or "").strip().lower()


def _norm_pose(text):
    return " ".join(str(text or "").lower().split())


def _image1_kind(expect):
    raw = expect.get("image1_kind")
    if raw:
        return str(raw).strip().lower()
    image1 = expect.get("image1")
    if isinstance(image1, dict):
        return str(image1.get("kind") or "").strip().lower()
    return ""


def plate_absent(expect):
    """Stranger plate as image1, or her photographs missing."""
    expect = expect or {}
    if expect.get("plate_as_image1") or expect.get("missing_her"):
        return True
    if expect.get("her_image1") is False or expect.get("image1_is_her") is False:
        return True
    if _image1_kind(expect) in _PLATE_KINDS:
        return True
    her = expect.get("her_photos")
    if her == [] or her == ():
        return True
    images = expect.get("images")
    if images == [] or images == ():
        return True
    return False


def body_colour_mismatch(expect):
    """Jet-black body wording against charcoal-brown source photos."""
    expect = expect or {}
    flagged = expect.get("body_colour")
    if flagged in ("jet-black", "mismatch", True):
        return True
    text = " ".join(
        str(expect.get(k) or "") for k in ("body", "composed", "prompt"))
    low = text.lower()
    if "jet-black" in low or "jet black" in low:
        return True
    return False


def c1_empty_latent(expect):
    """C1 / same-pose that started from an empty latent."""
    expect = expect or {}
    latent = _latent(expect)
    if latent != "empty":
        return False
    kind = _kind(expect)
    label = str(expect.get("pose_label") or "").strip().lower()
    return kind == "c1" or label == "same-pose"


def c2_pose_mismatch(expect):
    """C2 whose pose text does not match the asked pose."""
    expect = expect or {}
    kind = _kind(expect)
    label = str(expect.get("pose_label") or "").strip().lower()
    if kind != "c2" and label != "new-pose":
        return bool(expect.get("pose_mismatch")) and kind != "c1"
    if expect.get("pose_mismatch"):
        return True
    asked = _norm_pose(expect.get("asked_pose") or expect.get("want_pose"))
    if not asked:
        return False
    used = _norm_pose(expect.get("pose") or expect.get("pose_text"))
    return asked not in used and used not in asked


def denoise_mismatch(expect):
    expect = expect or {}
    if expect.get("denoise_wrong"):
        return True
    used, asked = expect.get("denoise"), expect.get("asked_denoise")
    if used is None or asked is None:
        return False
    return float(used) != float(asked)


def cfg_mismatch(expect):
    expect = expect or {}
    if expect.get("cfg_wrong"):
        return True
    used, asked = expect.get("cfg"), expect.get("asked_cfg")
    if used is None or asked is None:
        return False
    return float(used) != float(asked)


def resolve_settings_remedy(expect):
    """Named settings class for a pose / identity FAIL, or None.

    None means the finding stays edit-text (T3-33.a / T3-28).
    Plate-as-image1 is plate-absent, never a stranger swap.
    """
    expect = expect or {}
    if plate_absent(expect):
        return REMEDY_PLATE_ABSENT
    if body_colour_mismatch(expect):
        return REMEDY_BODY_COLOUR
    if c1_empty_latent(expect):
        return REMEDY_LATENT
    if c2_pose_mismatch(expect):
        return REMEDY_POSE_MATCH
    if denoise_mismatch(expect):
        return REMEDY_DENOISE
    if cfg_mismatch(expect):
        return REMEDY_CFG
    return None
