"""TRD-4 criteria the 2026-08-13 ledger left unverified: T4-8, T4-9, T4-18.

T4-5/T4-6/T4-7 already live in test_app.py. This file only covers what that
session marked unverified or partial. Public routes and the real composer —
T6-A10 — not the functions they wrap.
"""
import os
import re
import sys

import pytest
from fastapi.testclient import TestClient

import db
import prompts
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
