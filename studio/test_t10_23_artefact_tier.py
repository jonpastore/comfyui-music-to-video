"""T10-23: a g/pg13 child depiction cannot be selected as ref/anchor/plate/init
by an r/xxx work; the artefact's tier travels with the file.

docs/TRD-10 T10-23. T10-18 permits DEPICTING a minor at g/pg13. The side
channel is: render under that lock, attach the file as a reference / plate /
init on an explicit work. Text rules still hold; a child's likeness reaches
the explicit path. Closing it means the artefact carries content_tier, and
selection into r/xxx refuses and names the source.

One-sided failure: a check that stays green if selection never runs, or if
nothing is ever stamped. Positive half: a non-child artefact still selects
into r/xxx, and a child-locked artefact still selects into g/pg13.
"""
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

import app as appmod
import db
import guardrail
from test_app import _upload_song


def test_t10_23_check_artefact_use_refuses_child_on_explicit():
    """Shared screen. Unset work tier is xxx (T10-25). Refusal names the source."""
    for art in ("g", "pg13"):
        for work in ("r", "xxx", None, "", "custom"):
            with pytest.raises(guardrail.ContentRefused) as err:
                guardrail.check_artefact_use(
                    art, work, role="reference", source="niece_g_frame.png")
            msg = str(err.value).lower()
            assert "niece_g_frame.png" in msg or art in msg, msg
            assert art in msg or "child" in msg or "lock" in msg, msg
            for role in ("anchor", "plate", "init"):
                with pytest.raises(guardrail.ContentRefused):
                    guardrail.check_artefact_use(art, "xxx", role=role,
                                                 source="src")


def test_t10_23_child_artefact_still_selects_into_locked_work():
    """Positive half: g/pg13 may still use their own artefacts."""
    for art in ("g", "pg13"):
        for work in ("g", "pg13"):
            assert guardrail.check_artefact_use(
                art, work, role="reference", source="ok.png") is None


def test_t10_23_explicit_artefact_selects_into_explicit():
    """Positive half: non-child artefacts are not locked out of r/xxx."""
    for art in ("r", "xxx", None, ""):
        for work in ("r", "xxx"):
            assert guardrail.check_artefact_use(
                art, work, role="plate", source="adult.png") is None


def test_t10_23_content_tier_travels_with_meta():
    """Stamp is on the artefact meta, not inferred from the project it is pasted into."""
    meta = guardrail.stamp_content_tier({"scope_value": "Other Album"}, "g")
    assert guardrail.content_tier_of(meta) == "g"
    assert meta["content_tier"] == "g"
    # reading from a row-shaped dict also works
    assert guardrail.content_tier_of({"tier": "pg13"}) == "pg13"
    assert guardrail.content_tier_of({"meta_json": json.dumps({"content_tier": "g"})}) == "g"


def test_t10_23_use_as_ref_stamps_and_explicit_assign_refuses():
    """Click-path: g sheet → use-as-ref → assign as r sheet is refused; g assign ok."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-23 Niece", album="T10-23 Album")
        album = song["album"]
        path = os.path.join(db.DATA, "t10_23_niece_g.png")
        open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        now = time.time()
        db.run("""INSERT INTO anchors
                  (scope_kind, scope_value, tier, view, path, chosen, created)
                  VALUES ('album',?,?,?,?,1,?)""",
               album, "g", "front", path, now)
        anchor = db.one(
            "SELECT * FROM anchors WHERE path=? AND tier='g' ORDER BY id DESC", path)
        assert anchor

        r = client.post(f"/anchors/{anchor['id']}/use-as-ref")
        assert r.status_code in (200, 303), r.text
        asset = db.one(
            "SELECT * FROM assets WHERE kind='anchor_ref' AND path=? ORDER BY id DESC",
            path)
        assert asset, "use-as-ref did not create an asset row"
        meta = db.jset(asset)
        assert guardrail.content_tier_of(meta) == "g", meta
        assert guardrail.content_tier_of(asset) == "g"

        # Explicit assign as sheet: the side channel. Must refuse and name source.
        # pose_name only — tier comes from the form so content_tier stays g.
        db.run(
            "UPDATE assets SET meta_json=? WHERE id=?",
            json.dumps({**meta, "pose_name": "standing"}),
            asset["id"])
        refused = client.post(f"/anchors/refs/{asset['id']}/assign",
                              data={"album": album, "tier": "r", "pose_name": "standing"})
        assert refused.status_code == 400, refused.text
        low = refused.text.lower()
        assert "g" in low or "child" in low or "pg13" in low or "lock" in low, refused.text
        assert "source" in low or "t10_23_niece_g" in low, refused.text

        # Same artefact into a locked work is still allowed.
        ok = client.post(f"/anchors/refs/{asset['id']}/assign",
                         data={"album": album, "tier": "g", "pose_name": "standing"})
        assert ok.status_code in (200, 303), ok.text
        sheet = db.one(
            """SELECT * FROM anchors WHERE path=? AND tier='g' AND view LIKE 'pose_%'
               ORDER BY id DESC""", path)
        assert sheet, "g assign should have written a chosen sheet"


def test_t10_23_collect_refuses_child_ref_for_explicit_tier():
    """Selection for anchor generation: a g-stamped ref cannot feed r jobs."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-23 Collect", album="T10-23 Collect Album")
        album = song["album"]
        path = os.path.join(db.DATA, "t10_23_collect_g.png")
        open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        meta = guardrail.stamp_content_tier(
            {"scope_value": album, "character_id": None}, "g")
        aid = db.run(
            "INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
            None, "anchor_ref", path, json.dumps(meta), time.time())
        with pytest.raises(Exception) as err:
            appmod._collect_anchor_ref_paths(
                album, None, [str(aid)], work_tiers=["r"])
        msg = str(err.value).lower()
        assert "g" in msg or "child" in msg or "lock" in msg, msg

        # Positive: same ref into g is fine.
        paths = appmod._collect_anchor_ref_paths(
            album, None, [str(aid)], work_tiers=["g"])
        assert path in paths or os.path.abspath(path) in [
            os.path.abspath(p) for p in paths]
