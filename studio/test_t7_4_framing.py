"""T7-4: two views of one tier differ only by the framing clause.

docs/TRD-7 T7-4: compose two views and diff. Identical but for the framing
sentence and, on a nude view, the wardrobe swap. The check is the compose
itself — a string existing in VIEWS is T7-3, not this. Mutation: inject a
view-only extra clause into prompt_for → remainders diverge and this goes red.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import make_anchor

from fastapi.testclient import TestClient

import app as appmod
import db


# Distinct tokens so nude_wardrobe cannot contain wardrobe as a substring.
IDENTITY = "ID-CLAUSE-T74"
BODY = "BODY-CLAUSE-T74"
WARDROBE = "CLOTHED-WARDROBE-T74"
NUDE_WARDROBE = "NUDE-SWAP-T74"
ANATOMY = "ANATOMY-CLAUSE-T74"


def _anchor():
    return make_anchor.anchor_from({
        "identity": IDENTITY,
        "body": BODY,
        "wardrobe": WARDROBE,
        "nude_wardrobe": NUDE_WARDROBE,
        "anatomy": ANATOMY,
    })


def _framing(view, anchor):
    text = (anchor.get("views") or {}).get(view) or make_anchor.DEFAULT_VIEWS[view]
    return make_anchor.apply_pose(view, text, anchor.get("pose")).strip()


def _without_framing(view, composed, anchor):
    clause = _framing(view, anchor)
    assert composed.count(clause) == 1, (
        f"{view}: framing clause must appear exactly once, got "
        f"{composed.count(clause)} in {composed!r}")
    return composed.replace(clause, "", 1).strip()


def _compose(view, anchor, n_refs=1):
    return make_anchor.prompt_for(view, anchor, n_refs=n_refs)


def _omit_key(view):
    return tuple(make_anchor._omit(view))


def _tier_groups():
    """Views that share clothing family and backdrop omit — one remainder."""
    groups = {}
    for view in make_anchor.VIEWS:
        key = (make_anchor.is_nude_view(view), _omit_key(view))
        groups.setdefault(key, []).append(view)
    return groups


def test_t7_4_two_views_of_one_tier_differ_only_by_framing():
    """Clothed pair: front vs back. Remainder after stripping framing matches."""
    a = _anchor()
    front = _compose("front", a)
    back = _compose("back", a)
    assert front != back
    assert _without_framing("front", front, a) == _without_framing("back", back, a)
    rest = _without_framing("front", front, a)
    assert WARDROBE in rest
    assert NUDE_WARDROBE not in rest
    assert ANATOMY not in rest
    assert IDENTITY in rest and BODY in rest


def test_t7_4_nude_pair_swaps_wardrobe_and_still_only_framing():
    """Nude pair of the same tier: framing differs; remainder is the swap."""
    a = _anchor()
    front = _compose("front_nude", a)
    back = _compose("back_nude", a)
    assert front != back
    front_rest = _without_framing("front_nude", front, a)
    back_rest = _without_framing("back_nude", back, a)
    assert front_rest == back_rest
    assert NUDE_WARDROBE in front_rest
    assert WARDROBE not in front_rest
    assert ANATOMY in front_rest
    assert IDENTITY in front_rest and BODY in front_rest


def test_t7_4_every_same_omit_pair_shares_a_remainder():
    """Honesty check across the table, not one lucky pair.

    Views that omit different BACKDROP parts (portrait / seated) are T7-5.
    Same omit + same clothing family must still share one remainder.
    """
    a = _anchor()
    for (nude, omit), views in _tier_groups().items():
        if len(views) < 2:
            continue
        remainders = {
            view: _without_framing(view, _compose(view, a), a) for view in views
        }
        first = remainders[views[0]]
        for view, rest in remainders.items():
            assert rest == first, (
                f"{view} remainder drifted from {views[0]} "
                f"(nude={nude}, omit={omit})\n"
                f"  {views[0]}: {first!r}\n  {view}: {rest!r}")
        if nude:
            assert NUDE_WARDROBE in first and WARDROBE not in first
        else:
            assert WARDROBE in first and NUDE_WARDROBE not in first


def test_t7_4_nude_swap_is_the_only_extra_difference_on_one_camera():
    """Same camera, clothed vs nude: framing + wardrobe swap (+ anatomy)."""
    a = _anchor()
    clothed = _without_framing("front", _compose("front", a), a)
    nude = _without_framing("front_nude", _compose("front_nude", a), a)
    assert WARDROBE in clothed and NUDE_WARDROBE not in clothed
    assert NUDE_WARDROBE in nude and WARDROBE not in nude
    assert ANATOMY not in clothed and ANATOMY in nude

    def core(text):
        for token in (WARDROBE, NUDE_WARDROBE, ANATOMY):
            text = text.replace(token, "")
        return " ".join(text.split())

    assert core(clothed) == core(nude), (core(clothed), core(nude))


def test_t7_4_studio_preview_path_agrees(patch_stub):
    """Shared studio entry: default_anchor_prompt is prompt_for, not a twin."""
    a = _anchor()
    with TestClient(appmod.app) as client:
        client.post("/playlists", data={"name": "T74 Album"})
        pid = db.one("SELECT id FROM playlists WHERE name='T74 Album'")["id"]
        r = client.post(f"/playlists/{pid}/profile", data={
            "identity": IDENTITY,
            "body": BODY,
            "wardrobe": WARDROBE,
            "nude_wardrobe": NUDE_WARDROBE,
            "anatomy": ANATOMY,
            "style_text": "x",
            "world": "y",
            "render_tail": "z",
        })
        assert r.status_code in (200, 303), r.text
        front = appmod.default_anchor_prompt("T74 Album", "front")
        back = appmod.default_anchor_prompt("T74 Album", "back")
        front_nude = appmod.default_anchor_prompt("T74 Album", "front_nude")
        back_nude = appmod.default_anchor_prompt("T74 Album", "back_nude")
        assert front == _compose("front", a)
        assert back == _compose("back", a)
        assert _without_framing("front", front, a) == _without_framing("back", back, a)
        assert (_without_framing("front_nude", front_nude, a)
                == _without_framing("back_nude", back_nude, a))
        assert WARDROBE in front and NUDE_WARDROBE not in front
        assert NUDE_WARDROBE in front_nude and WARDROBE not in front_nude
