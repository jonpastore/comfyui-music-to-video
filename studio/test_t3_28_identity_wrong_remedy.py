"""T3-28: identity-wrong never proposes swapping the reference image.

docs/TRD-3 §6.2: identity wrong from the first frame is fixed by editing
the text, then re-rendering. Swapping the reference image will not fix
it — measured 2026-08-12 (species named or not, same reference, same
seed, same box). A remedy that says otherwise teaches a false lesson.

T3-30: the check is callable with a path and an expectation, no database.
"""
import os
import time

import db
import qc
import qc_service


CLIP = "/out/identity_wrong_clip.mp4"


def _by_check(findings, name):
    return [f for f in findings if f["check"] == name]


def _record_identity_wrong(path, remedy):
    qc_service.record([{
        "path": path, "kind": "clip", "tier": 2, "check": qc.IDENTITY_WRONG,
        "verdict": "flag", "measured": "human by halfway", "expected": "feline",
        "unit": None, "detail": "identity is wrong from the first frame",
        "remedy": remedy,
    }])
    return db.one("SELECT * FROM findings WHERE path=? AND check_name=?",
                  path, qc.IDENTITY_WRONG)


def test_t3_28_check_is_callable_without_a_database():
    """T3-30: path + expect, no request, no db, no app."""
    assert qc.IDENTITY_WRONG == "identity_wrong"
    assert callable(qc.check_identity_wrong)
    found = qc.check_identity_wrong(CLIP, {"identity_wrong": True})
    hit = _by_check(found, qc.IDENTITY_WRONG)
    assert hit and hit[0]["verdict"] == qc.FLAG, found
    assert hit[0]["path"] == CLIP


def test_t3_28_default_remedy_edits_the_text_not_the_reference():
    """The proposed remedy is edit the text, then re-render."""
    found = qc.check_identity_wrong(CLIP, {"identity_wrong": True})
    hit = _by_check(found, qc.IDENTITY_WRONG)
    assert hit, found
    remedy = (hit[0].get("remedy") or "").lower()
    assert "text" in remedy, hit[0]
    assert "re-render" in remedy, hit[0]
    assert not qc.proposes_reference_swap(hit[0].get("remedy")), hit[0]
    assert "swap" not in remedy
    assert "reference image" not in remedy or "not the reference" in remedy


def test_t3_28_unasked_check_emits_nothing():
    """Ordinary QC must not invent an identity-wrong finding."""
    assert qc.check_identity_wrong(CLIP, {}) == []
    assert qc.check_identity_wrong(CLIP, None) == []


def test_t3_28_run_emits_identity_wrong_on_the_shared_entry():
    """Assert through qc.run. A standalone helper the runner never calls
    stays green after the hook is deleted."""
    found = qc.run(CLIP, "clip", {"identity_wrong": True})
    hit = _by_check(found, qc.IDENTITY_WRONG)
    assert hit and hit[0]["verdict"] == qc.FLAG, found
    assert "text" in (hit[0].get("remedy") or "").lower()
    assert not qc.proposes_reference_swap(hit[0].get("remedy")), hit[0]
    assert _by_check(qc.run(CLIP, "clip", {}), qc.IDENTITY_WRONG) == []


def test_t3_28_proposes_reference_swap_detects_the_false_lesson():
    """The detector is the thing under test — a hard-coded False stays green."""
    assert qc.proposes_reference_swap("swap the reference image")
    assert qc.proposes_reference_swap("Swap the reference and re-render")
    assert qc.proposes_reference_swap("replace the reference image")
    assert qc.proposes_reference_swap("attach a reference image")
    assert not qc.proposes_reference_swap(
        "edit the text, then re-render. identity comes from the text, "
        "not the reference image")
    assert not qc.proposes_reference_swap("re-render with a different seed")
    assert not qc.proposes_reference_swap("")


def test_t3_28_identity_wrong_remedy_refuses_a_swap():
    """The qc.py function is the refuse — not only the service wrapper."""
    try:
        qc.identity_wrong_remedy("swap the reference image")
    except ValueError as e:
        msg = str(e).lower()
        assert "reference" in msg, e
        assert "text" in msg, e
    else:
        raise AssertionError("identity_wrong_remedy accepted a reference swap")
    legal = qc.identity_wrong_remedy("name the species in the prompt, then re-render")
    assert "species" in legal.lower()
    assert not qc.proposes_reference_swap(legal)


def test_t3_28_record_refuses_a_reference_swap_remedy():
    """Persisting the false lesson is the studio proposing it."""
    path = os.path.join(db.DATA, f"t328_record_{time.time_ns()}.mp4")
    try:
        _record_identity_wrong(path, "swap the reference image")
    except ValueError as e:
        msg = str(e).lower()
        assert "reference" in msg, e
        assert "text" in msg, e
    else:
        raise AssertionError("identity-wrong stored a swap-the-reference remedy")
    assert db.one("SELECT id FROM findings WHERE path=?", path) is None


def test_t3_28_set_remedy_refuses_a_reference_swap():
    """An edited remedy that teaches the false lesson is refused."""
    path = os.path.join(db.DATA, f"t328_edit_{time.time_ns()}.mp4")
    row = _record_identity_wrong(
        path, "edit the text, then re-render")
    try:
        qc_service.set_remedy(row["id"], "swap the reference image")
    except ValueError as e:
        msg = str(e).lower()
        assert "text" in msg and "reference" in msg, e
    else:
        raise AssertionError("set_remedy accepted a reference-swap on identity-wrong")
    landed = qc_service.get(row["id"])
    assert not qc.proposes_reference_swap(landed["remedy"]), landed["remedy"]
    assert "edit the text" in (landed["remedy"] or "").lower()


def test_t3_28_legal_text_edit_remedy_is_stored():
    """Positive half: the right remedy is accepted and read back.

    A refusal-only guard stays green if identity-wrong findings cannot
    be recorded at all.
    """
    path = os.path.join(db.DATA, f"t328_ok_{time.time_ns()}.mp4")
    legal = "edit the text, then re-render"
    row = _record_identity_wrong(path, legal)
    assert row["check_name"] == qc.IDENTITY_WRONG
    assert row["remedy"] == legal
    edited = "name the species in the prompt, then re-render"
    after = qc_service.set_remedy(row["id"], edited)
    assert after["remedy"] == edited
    assert qc_service.get(row["id"])["remedy"] == edited


def test_t3_28_other_findings_may_still_name_a_reference():
    """The ban is identity-wrong's. Duration can still say re-render."""
    path = os.path.join(db.DATA, f"t328_other_{time.time_ns()}.mp4")
    qc_service.record([{
        "path": path, "kind": "clip", "tier": 1, "check": "duration",
        "verdict": "reject", "measured": "4.8", "expected": "30.0",
        "unit": "s", "detail": "short render",
        "remedy": "re-render with the corrected request",
    }])
    row = db.one("SELECT * FROM findings WHERE path=?", path)
    qc_service.set_remedy(row["id"], "re-render pinned to a box that honours it")
    assert "re-render" in qc_service.get(row["id"])["remedy"]
