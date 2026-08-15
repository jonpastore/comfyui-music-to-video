"""T7-3: new views are one VIEWS entry each — framing, UI, and compose.

docs/TRD-7 T7-3: three_quarter, profile, seated, portrait, on_all_fours
(each with a nude parallel) ship as single positive framing sentences.
Positive half offline: each composes with its framing clause exactly once
and appears in the anchor form. GPU sheet renders are NOT MEASURED here.

Mutation: drop a required key from VIEWS, or hand-keep ANCHOR_VIEWS as a
second map that omits a VIEWS label → red. Adding a probe row only to VIEWS
and re-deriving labels is enough for UI + compose (one table entry).
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import make_anchor

from fastapi.testclient import TestClient

import app as appmod


# T7-3 minimum set — clothed + nude parallel for each camera.
REQUIRED_NEW_VIEWS = (
    "three_quarter", "three_quarter_nude",
    "profile", "profile_nude",
    "seated", "seated_nude",
    "portrait", "portrait_nude",
    "on_all_fours", "on_all_fours_nude",
)

# Camera-relationship tokens the framing must name (case-insensitive).
FRAMING_MARKERS = {
    "three_quarter": ("forty-five", "face"),
    "three_quarter_nude": ("forty-five", "face"),
    "profile": ("side",),
    "profile_nude": ("side",),
    "seated": ("sitt",),
    "seated_nude": ("sitt",),
    "portrait": ("head", "shoulder"),
    "portrait_nude": ("head", "shoulder"),
    "on_all_fours": ("hands", "hips", "tail"),
    "on_all_fours_nude": ("hands", "hips", "tail"),
}

_NEGATION = re.compile(r"\b(no|not|without|never)\s+\w", re.I)


def _framing(view):
    return make_anchor.VIEWS[view]["framing"].strip()


def test_t7_3_required_views_are_views_table_entries():
    """Each required view is one VIEWS row with label + framing."""
    for view in REQUIRED_NEW_VIEWS:
        assert view in make_anchor.VIEWS, f"missing VIEWS entry: {view}"
        entry = make_anchor.VIEWS[view]
        assert entry.get("label"), f"{view}: empty label"
        framing = (entry.get("framing") or "").strip()
        assert framing, f"{view}: empty framing"
        assert framing.endswith("."), f"{view}: framing is not a sentence: {framing!r}"
        assert not _NEGATION.search(framing), (
            f"{view}: negation in framing (T4-10 / T7-3): {framing!r}")
        low = framing.lower()
        for marker in FRAMING_MARKERS[view]:
            assert marker in low, f"{view}: framing missing {marker!r}: {framing!r}"
        assert make_anchor.is_nude_view(view) == view.endswith("_nude")


def test_t7_3_anchor_views_derive_from_views_only():
    """ANCHOR_VIEWS / DEFAULT_VIEWS are projections — not a second hand map."""
    assert set(appmod.ANCHOR_VIEWS) == set(make_anchor.VIEWS)
    assert appmod.ANCHOR_VIEWS == {
        k: v["label"] for k, v in make_anchor.VIEWS.items()
    }
    assert make_anchor.DEFAULT_VIEWS == {
        k: v["framing"] for k, v in make_anchor.VIEWS.items()
    }
    for view in REQUIRED_NEW_VIEWS:
        assert view in appmod.ANCHOR_VIEWS
        assert appmod.ANCHOR_VIEWS[view] == make_anchor.VIEWS[view]["label"]


def test_t7_3_each_new_view_composes_framing_exactly_once():
    """Compose path: framing clause appears once (T7-3 positive half offline)."""
    anchor = make_anchor.anchor_from({
        "identity": "ID-T73",
        "body": "BODY-T73",
        "wardrobe": "CLOTHED-T73",
        "nude_wardrobe": "NUDE-T73",
        "anatomy": "ANATOMY-T73",
    })
    for view in REQUIRED_NEW_VIEWS:
        composed = make_anchor.prompt_for(view, anchor)
        clause = _framing(view)
        assert composed.count(clause) == 1, (
            f"{view}: framing count {composed.count(clause)} in {composed!r}")
        assert "ID-T73" in composed and "BODY-T73" in composed
        if make_anchor.is_nude_view(view):
            assert "NUDE-T73" in composed and "CLOTHED-T73" not in composed
            assert "ANATOMY-T73" in composed
        else:
            assert "CLOTHED-T73" in composed and "NUDE-T73" not in composed


def test_t7_3_new_views_appear_in_anchor_form(patch_stub):
    """UI iterates ANCHOR_VIEWS: every required key is a matrix checkbox."""
    with TestClient(appmod.app) as client:
        client.post("/playlists", data={"name": "T73 Views Album"})
        form = client.get(
            "/anchors/form", params={"album": "T73 Views Album"}
        ).text
        for view in REQUIRED_NEW_VIEWS:
            assert f'value="{view}"' in form, f"{view} missing from form"
            label = appmod.ANCHOR_VIEWS[view]
            short = label.split(",")[0].strip()
            assert short.lower() in form.lower(), (
                f"{view} label {short!r} not shown in form")


def test_t7_3_one_table_entry_reaches_ui_and_compose(patch_stub):
    """Adding a view is one VIEWS row; re-derive labels → UI + compose see it.

    Mutation: if ANCHOR_VIEWS were a frozen hand map, injecting only into
    VIEWS would leave the form without the probe key.
    """
    key = "_t73_probe"
    entry = {
        "label": "probe, clothed",
        "framing": (
            "PROBE VIEW character reference sheet of a single adult character, "
            "facing the camera, head to toe fully in frame. "),
        "pose": "facing the camera, ",
        "camera": "PROBE VIEW character reference sheet of a single adult character, ",
    }
    assert key not in make_anchor.VIEWS
    make_anchor.VIEWS[key] = entry
    make_anchor.DEFAULT_VIEWS[key] = entry["framing"]
    # Same derivation app uses at import — one table, two projections.
    derived = {k: v["label"] for k, v in make_anchor.VIEWS.items()}
    prev_label = appmod.ANCHOR_VIEWS.get(key)
    appmod.ANCHOR_VIEWS[key] = derived[key]
    try:
        assert key in derived and derived[key] == "probe, clothed"
        composed = make_anchor.prompt_for(key, make_anchor.anchor_from({
            "identity": "ID-PROBE",
            "body": "BODY-PROBE",
            "wardrobe": "W-PROBE",
        }))
        assert composed.count(entry["framing"].strip()) == 1
        assert "ID-PROBE" in composed
        with TestClient(appmod.app) as client:
            client.post("/playlists", data={"name": "T73 Probe Album"})
            form = client.get(
                "/anchors/form", params={"album": "T73 Probe Album"}
            ).text
            assert f'value="{key}"' in form, (
                "probe view not in form after one VIEWS entry + label projection")
            assert "probe" in form.lower()
    finally:
        del make_anchor.VIEWS[key]
        del make_anchor.DEFAULT_VIEWS[key]
        if prev_label is None:
            appmod.ANCHOR_VIEWS.pop(key, None)
        else:
            appmod.ANCHOR_VIEWS[key] = prev_label
