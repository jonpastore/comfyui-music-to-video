"""TRD-4 criteria the 2026-08-13 ledger left unverified: T4-8, T4-9, T4-13, T4-18.

T4-5/T4-6/T4-7 already live in test_app.py. This file only covers what that
session marked unverified or partial. Public routes and the real composer —
T6-A10 — not the functions they wrap.

T4-13 is pixels, not the BACKDROP string. Green/magenta cast on a rendered
sheet FLAGs; the colour-temperature lock in the constant is not the proof.
"""
import os
import re
import sys

import pytest
from fastapi.testclient import TestClient

import db
import prompts
import qc
import tiers
import app as appmod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import build_refs
import make_anchor

# Same sentence T4-5/T4-6/T4-7 uses. Both directions, same text, or each
# criterion certifies the other's absence.
EXPLICIT = "She stands fully nude, bare genitalia visible."
PLAIN = "Her entire body is covered in sleek jet-black fur."
BODY_PARTS = (
    "shoulders", "upper arms", "forearms", "hands", "torso",
    "hips", "thighs", "calves", "feet",
)


def _stored_positive(album, tier):
    """The row the save route actually wrote, or None."""
    return prompts.latest(album, "positive", tier)


def test_t4_8_tier_policy_is_re_screened_on_the_stored_row():
    """docs/TRD-4 T4-8. A guard that runs on the submitted box and not on the
    row it wrote is a guard on something else. Read the row back and re-screen
    that text — both directions, same as T4-6/T4-7.
    """
    album = "T4-8 Stored Album"
    with TestClient(appmod.app) as client:
        client.post("/playlists", data={"name": album, "kind": "playlist"})
        base = {"album": album, "text": EXPLICIT, "label": "v1"}

        for tier in ("g", "pg13"):
            r = client.post("/anchors/prompt", data=dict(base, tier=tier))
            assert r.status_code == 400, f"{tier} accepted explicit wording: {r.text[:200]}"
            assert _stored_positive(album, tier) is None, (
                f"{tier} refused the POST but a row landed: "
                f"{(_stored_positive(album, tier) or {}).get('text')!r}")

        for tier in ("r", "xxx"):
            r = client.post("/anchors/prompt",
                            data=dict(base, tier=tier, label=f"v-{tier}"))
            assert r.status_code == 200, f"{tier} refused wording it permits: {r.text[:200]}"
            row = _stored_positive(album, tier)
            assert row is not None, f"{tier} returned 200 but stored nothing"
            stored = row["text"]
            # the check is on THIS, not on what the form claimed to send
            assert tiers.check_tier_policy(stored, tier, "anchor prompt") == stored
            with pytest.raises(ValueError, match=r"does not permit nudity"):
                tiers.check_tier_policy(stored, "g", "anchor prompt")

        r = client.post("/anchors/prompt",
                        data={"album": album, "tier": "g", "label": "plain",
                              "text": PLAIN})
        assert r.status_code == 200, r.text[:200]
        stored = _stored_positive(album, "g")["text"]
        assert tiers.check_tier_policy(stored, "g", "anchor prompt") == stored


def test_t4_9_tier_wording_route_gets_the_same_tier_policy():
    """docs/TRD-4 T4-9. /anchors/tier-wording is the other free-text path to
    the same render. Explicit wording refused at g/pg13 AND accepted at r/xxx
    on that route specifically, then the stored override is re-screened.
    """
    album = "T4-9 Wording Album"
    with TestClient(appmod.app) as client:
        client.post("/playlists", data={"name": album, "kind": "playlist"})

        for tier in ("g", "pg13"):
            r = client.post("/anchors/tier-wording",
                            data={"album": album, "tier": tier, "text": EXPLICIT})
            assert r.status_code == 400, (
                f"{tier} accepted explicit wording on /anchors/tier-wording: "
                f"{r.text[:200]}")
            assert tier in r.text and "nudity" in r.text, r.text[:200]
            assert not tiers.override_text(album, tier), (
                f"{tier} refused the POST but an override landed: "
                f"{tiers.override_text(album, tier)!r}")

        for tier in ("r", "xxx"):
            r = client.post("/anchors/tier-wording",
                            data={"album": album, "tier": tier, "text": EXPLICIT})
            assert r.status_code == 200, (
                f"{tier} refused wording it permits on /anchors/tier-wording: "
                f"{r.text[:200]}")
            stored = tiers.override_text(album, tier)
            assert stored, f"{tier} returned 200 but stored no override"
            assert tiers.check_tier_policy(stored, tier, "tier wording") == stored
            with pytest.raises(ValueError, match=r"does not permit nudity"):
                tiers.check_tier_policy(stored, "g", "tier wording")

        r = client.post("/anchors/tier-wording",
                        data={"album": album, "tier": "g", "text": PLAIN})
        assert r.status_code == 200, r.text[:200]
        stored = tiers.override_text(album, "g")
        assert stored == PLAIN
        assert tiers.check_tier_policy(stored, "g", "tier wording") == stored


def _t4_18_xxx_front_nude(album):
    """Compose a real xxx front_nude sheet through the studio profile + workflow.

    Slot naming is the rescoped wording (§9.2): image 2 is another photograph
    of the same character, not "the wardrobe reference". PINNED enumerates
    "no minors" by design, so the negation walk is the character sheet — the
    same walk T4-10 uses — not the welded guardrail.
    """
    wardrobe = "A black leather harness and platform boots."
    with TestClient(appmod.app) as client:
        client.post("/playlists", data={"name": album, "kind": "playlist"})
        pid = db.one("SELECT id FROM playlists WHERE name=?", album)["id"]
        r = client.post(f"/playlists/{pid}/profile",
                        data={"identity": "A sleek black feline face, yellow-green eyes.",
                              "wardrobe": wardrobe,
                              "body": make_anchor.DEFAULT_BODY,
                              "style_text": "x", "world": "y", "render_tail": "z"})
        assert r.status_code in (200, 303), r.text[:200]

    fields = appmod.anchor_profile_fields(album)
    assert fields["wardrobe"] == wardrobe
    character = make_anchor.prompt_for(
        "front_nude", make_anchor.anchor_from(fields), n_refs=2)
    # Harness: delete-the-composer must not go green on the absence checks.
    assert character and "FRONT VIEW" in character and "nude" in character.lower(), (
        f"front_nude composer produced no sheet: {character!r}")

    wf = build_refs.workflow(
        {"image_prompt": character, "negative_prompt": ""},
        "face.png", None, "empty", 896, 1216, 1, "",
        guard=tiers.compose_guardrail("xxx", album),
        extra_refs=[(None, "other.png", "")],
    )
    composed = wf["11"]["inputs"]["prompt"]
    assert composed, "workflow produced an empty composed prompt"
    return character, composed, wf, wardrobe


def test_t4_18_no_negation():
    """docs/TRD-4 T4-18 / §6. No negation in the character sheet."""
    character, _, _, _ = _t4_18_xxx_front_nude("T4-18 Negation Album")
    hits = []
    for pat in make_anchor._NEGATION_PATTERNS:
        for m in re.finditer(pat, character, re.I):
            hits.append(character[max(0, m.start() - 24):m.end() + 24])
    assert not hits, f"negation in the front_nude character sheet: {hits}"


def test_t4_18_body_part_list_present():
    """docs/TRD-4 T4-18 / §6. The nine-part body list is in the composed prompt."""
    _, composed, _, _ = _t4_18_xxx_front_nude("T4-18 Body Album")
    missing = [p for p in BODY_PARTS if p not in composed]
    assert not missing, f"body part list incomplete, missing {missing}"


def test_t4_18_both_reference_slots_named():
    """docs/TRD-4 T4-18 / §6. Both reference slots named (graph + prompt)."""
    _, composed, wf, _ = _t4_18_xxx_front_nude("T4-18 Slots Album")
    enc = wf["11"]["inputs"]
    assert "image1" in enc and "image2" in enc, enc
    assert "Image 2 is another photograph of the same character." in composed, composed


def test_t4_18_no_wardrobe_clause():
    """docs/TRD-4 T4-18 / §6. Nude sheet drops the clothed wardrobe clause."""
    _, composed, _, wardrobe = _t4_18_xxx_front_nude("T4-18 Wardrobe Album")
    assert wardrobe not in composed, "the clothed wardrobe leaked onto a nude sheet"


def test_t4_18_no_bare_skin():
    """docs/TRD-4 T4-18 / §6. Composed nude sheet never says 'bare skin'."""
    _, composed, _, _ = _t4_18_xxx_front_nude("T4-18 BareSkin Album")
    assert "bare skin" not in composed.lower(), composed


def test_t4_18_pinned_last():
    """docs/TRD-4 T4-18 / §6. tiers.PINNED is non-empty and welded last."""
    _, composed, _, _ = _t4_18_xxx_front_nude("T4-18 Pinned Album")
    pinned = tiers.PINNED.strip()
    assert pinned, "PINNED was deleted; the weld has nothing to put last"
    assert pinned in composed, "PINNED is missing from the composed prompt"
    assert composed.rstrip().endswith(pinned), (
        f"PINNED is not last: ...{composed[-160:]!r}")


# ------------------------------------------------------------------ T4-13 --
# Lighting lock is a channel-balance differential on pixels. Olive/sage and
# magenta are the reported casts. BACKDROP already says "evenly lit"; that
# string is not this criterion.

OLIVE = (140, 160, 120)
MAGENTA = (180, 110, 180)
NEUTRAL = (128, 128, 128)
FIGURE = (18, 18, 18)


def _rgb_png(path, rgb, size=(64, 64)):
    from PIL import Image
    Image.new("RGB", size, rgb).save(path)
    return str(path)


def _figure_on_wall(path, wall, figure=FIGURE, size=64, inset=6):
    """Black figure on a coloured studio wall. Whole-image mean hides the wall."""
    from PIL import Image
    im = Image.new("RGB", (size, size), wall)
    for y in range(inset, size - inset):
        for x in range(inset, size - inset):
            im.putpixel((x, y), figure)
    im.save(path)
    return str(path)


def _by_check(findings, name):
    return [f for f in findings if f["check"] == name]


def test_t4_13_tests_do_not_skip():
    """A skip call is not a reading. Mutation: insert a skip call → red."""
    src = open(__file__, encoding="utf-8").read()
    skip_call = "pytest" + ".skip("
    skip_mark = "pytest" + ".mark.skip"
    assert skip_call not in src
    assert skip_mark not in src


def test_t4_13_olive_cast_flags(tmp_path):
    """Reported defect: olive/sage backdrop FLAGs on pixels, not on text."""
    sheet = _rgb_png(tmp_path / "olive.png", OLIVE)
    found = qc.check_image(sheet, {})
    hit = _by_check(found, qc.LIGHTING_LOCK)
    assert hit and hit[0]["verdict"] == qc.FLAG, found
    assert hit[0]["measured"] is not None
    assert float(hit[0]["measured"]) > qc.LIGHTING_CAST_LIMIT


def test_t4_13_magenta_cast_flags(tmp_path):
    """The other named symptom. Magenta is |cast| the other way."""
    sheet = _rgb_png(tmp_path / "magenta.png", MAGENTA)
    found = qc.check_image(sheet, {})
    hit = _by_check(found, qc.LIGHTING_LOCK)
    assert hit and hit[0]["verdict"] == qc.FLAG, found
    assert float(hit[0]["measured"]) > qc.LIGHTING_CAST_LIMIT


def test_t4_13_neutral_grey_passes(tmp_path):
    """Even neutral studio lighting: balanced channels PASS."""
    sheet = _figure_on_wall(tmp_path / "neutral.png", NEUTRAL)
    found = qc.check_image(sheet, {})
    hit = _by_check(found, qc.LIGHTING_LOCK)
    assert hit and hit[0]["verdict"] == qc.PASS, found
    assert float(hit[0]["measured"]) <= qc.LIGHTING_CAST_LIMIT


def test_t4_13_backdrop_string_is_not_the_criterion(tmp_path):
    """BACKDROP already carries the lock words. That is not T4-13.

    Mutation: a test that only greps BACKDROP stays green on an olive sheet.
    """
    assert "evenly lit" in make_anchor.BACKDROP
    assert "Even neutral studio lighting" in make_anchor.BACKDROP
    sheet = _rgb_png(tmp_path / "olive.png", OLIVE)
    found = qc.check_image(sheet, {})
    hit = _by_check(found, qc.LIGHTING_LOCK)
    assert hit and hit[0]["verdict"] == qc.FLAG, (
        "olive sheet passed because BACKDROP contains the lighting lock")


def test_t4_13_figure_on_olive_wall_flags(tmp_path):
    """Whole-image mean is not the metric. A black figure on an olive wall
    averages toward equal channels and would hide the defect.
    """
    sheet = _figure_on_wall(tmp_path / "figure_olive.png", OLIVE)
    import numpy as np
    from PIL import Image
    arr = np.asarray(Image.open(sheet).convert("RGB"), dtype="float64")
    whole = arr.mean(axis=(0, 1))
    whole_cast = abs(whole[1] - (whole[0] + whole[2]) / 2.0)
    assert whole_cast < qc.LIGHTING_CAST_LIMIT, (
        f"fixture is not load-bearing: whole-image cast {whole_cast} already FLAGs")
    found = qc.check_image(sheet, {})
    hit = _by_check(found, qc.LIGHTING_LOCK)
    assert hit and hit[0]["verdict"] == qc.FLAG, found


def test_t4_13_missing_path_not_measured():
    """No pixels is NOT MEASURED, never cast 0.0."""
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.backdrop_channel_means("/no/such/sheet.png")
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t4_13_claim()


def test_t4_13_real_sheet_not_measured():
    """T4-13 on a current GPU sheet is NOT MEASURED.

    Flip T4_13_REAL_SHEET_MEASURED only after a rendered sheet is pointed at.
    Mutation: set MEASURED True with an empty hook → this goes red.
    """
    assert qc.T4_13_REAL_SHEET_MEASURED is False, (
        "T4-13 real sheet is NOT MEASURED; flip only after a render")
    assert qc.t4_13_real_sheet_path() is None
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.t4_13_claim()


def test_t4_13_measured_true_with_empty_hook_is_a_lie():
    """The flag without a path is the lie the harness exists to catch."""
    prev = qc.T4_13_REAL_SHEET_MEASURED
    try:
        qc.T4_13_REAL_SHEET_MEASURED = True
        with pytest.raises(ValueError, match="NOT MEASURED"):
            qc.t4_13_claim()
    finally:
        qc.T4_13_REAL_SHEET_MEASURED = prev


def test_t4_13_through_run(tmp_path):
    """Studio QC entry is qc.run. Same olive sheet, same FLAG."""
    sheet = _rgb_png(tmp_path / "olive.png", OLIVE)
    found = qc.run(sheet, "image", {})
    hit = _by_check(found, qc.LIGHTING_LOCK)
    assert hit and hit[0]["verdict"] == qc.FLAG, found
