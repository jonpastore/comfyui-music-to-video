"""T3-17: identity drift is scored per artefact, whatever caused it.

docs/TRD-3 T3-17: the draft scoped this to an empty character_reference,
but T2-31 refuses that at save. The reachable failure is a non-empty
reference plus text that does not name the species — an ordinary human
by the halfway point. The score is against the chosen anchor and does
not care which cause produced the gap. Tier 1 cannot see it; tier 2
is the only tier that can.

No threshold, no gate, no UI. A scorer that only runs on an empty
reference, that aggregates two artefacts into one number, that lives
inside qc.run, or that ignores the chosen anchor, must go red.
"""
import os
import subprocess

from PIL import Image

import db
import jobs
import qc
import qc_service


BG = (210, 180, 140)
BLACK = (15, 12, 18)
TABBY = (180, 110, 55)
HUMAN = (210, 170, 150)
SIZE = 32


def _paint(path, colour, standing=True):
    img = Image.new("RGB", (SIZE, SIZE), BG)
    px = img.load()
    if standing:
        cols, rows = range(8, 15), range(4, 28)
    else:
        cols, rows = range(4, 28), range(18, 26)
    for y in rows:
        for x in cols:
            px[x, y] = colour
    img.save(path)
    return str(path)


def _trio(tmp_path):
    """Chosen anchor + same-identity still + human-looking still."""
    anchor = _paint(tmp_path / "anchor.png", BLACK, standing=True)
    her = _paint(tmp_path / "her.png", BLACK, standing=False)
    human = _paint(tmp_path / "human.png", HUMAN, standing=True)
    return anchor, her, human


def _mp4(tmp_path, name, colours):
    """Tiny clip: one painted frame per colour, in order."""
    frames = []
    for i, colour in enumerate(colours):
        frames.append(_paint(tmp_path / f"{name}_{i:02d}.png", colour,
                             standing=(i % 2 == 0)))
    dest = str(tmp_path / name)
    pattern = str(tmp_path / f"{name}_%02d.png")
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-framerate", "8", "-i", pattern,
         "-frames:v", str(len(frames)), "-pix_fmt", "yuv420p", dest],
        check=True, capture_output=True)
    return dest


def _by_check(findings, name):
    return [f for f in findings if f["check"] == name]


def test_t3_17_score_function_exists():
    """The score is a named function, not a comment in the TRD."""
    assert qc.IDENTITY_DRIFT == "identity_drift"
    assert callable(qc.score_identity_artefact)


def test_t3_17_matching_still_scores_higher_than_human(tmp_path):
    """The measured collapse: her vs an ordinary human, same anchor."""
    anchor, her, human = _trio(tmp_path)
    s_her = qc.score_identity_artefact(her, anchor)
    s_human = qc.score_identity_artefact(human, anchor)
    assert s_her["path"] == her
    assert s_human["path"] == human
    assert s_her["anchor"] == anchor
    assert s_human["anchor"] == anchor
    assert s_her["score"] > s_human["score"], (s_her, s_human)
    assert s_her["compliance"] > s_human["compliance"], (s_her, s_human)
    assert s_her["n"] == 1 and s_human["n"] == 1
    assert s_her["variation"] == 0.0
    assert s_her["threshold"] is None
    assert s_human["threshold"] is None
    assert s_her["tier"] == 2
    assert "verdict" not in s_her


def test_t3_17_nonempty_reference_without_species_still_scores(tmp_path):
    """The reachable cause: non-empty ref, text that does not name species.

    A scorer that only runs when character_reference is empty is the
    unreachable-state test T2-31 already closed.
    """
    anchor, her, human = _trio(tmp_path)
    expect = {
        "anchor_path": anchor,
        "character_reference": anchor,
        "prompt": "standing in an alley, leather harness",
    }
    assert expect["character_reference"], expect
    assert "feline" not in expect["prompt"].lower()
    assert "cat" not in expect["prompt"].lower()

    report = qc_service.score_identity_artefact(human, expect=expect)
    assert report["path"] == human
    assert report["anchor"] == anchor
    assert report["n"] >= 1
    assert report["score"] < qc.score_identity_artefact(her, anchor)["score"]


def test_t3_17_same_pixels_same_score_whatever_the_cause(tmp_path):
    """Cause is not an input. Same artefact, same anchor, same score."""
    anchor, _, human = _trio(tmp_path)
    a = qc.score_identity_artefact(human, anchor)
    b = qc_service.score_identity_artefact(
        human, expect={
            "anchor_path": anchor,
            "character_reference": anchor,
            "prompt": "standing in an alley",
        })
    c = qc_service.score_identity_artefact(
        human, expect={
            "anchor_path": anchor,
            "character_reference": anchor,
            "prompt": "anthropomorphic black feline woman, standing",
        })
    assert a["score"] == b["score"] == c["score"], (a, b, c)


def test_t3_17_score_follows_the_chosen_anchor(tmp_path):
    """Swap the chosen anchor and the ranking flips. Hardcoding her fails."""
    her_anchor = _paint(tmp_path / "her_anchor.png", BLACK, standing=True)
    tabby_anchor = _paint(tmp_path / "tabby_anchor.png", TABBY, standing=True)
    her = _paint(tmp_path / "her.png", BLACK, standing=False)
    tabby = _paint(tmp_path / "tabby.png", TABBY, standing=False)

    vs_her = (
        qc.score_identity_artefact(her, her_anchor)["score"],
        qc.score_identity_artefact(tabby, her_anchor)["score"],
    )
    vs_tabby = (
        qc.score_identity_artefact(her, tabby_anchor)["score"],
        qc.score_identity_artefact(tabby, tabby_anchor)["score"],
    )
    assert vs_her[0] > vs_her[1], vs_her
    assert vs_tabby[1] > vs_tabby[0], vs_tabby


def test_t3_17_two_artefacts_are_two_reports(tmp_path):
    """Per artefact, not one aggregate over the batch."""
    anchor, her, human = _trio(tmp_path)
    qc_service.score_identity_artefact(her, anchor=anchor)
    qc_service.score_identity_artefact(human, anchor=anchor)
    her_p = jobs.canonical_path(her)
    human_p = jobs.canonical_path(human)
    rows = db.q(
        "SELECT path, check_name, tier FROM findings WHERE check_name=?",
        qc.IDENTITY_DRIFT)
    paths = {r["path"] for r in rows}
    assert her_p in paths and human_p in paths, rows
    assert all(r["tier"] == 2 for r in rows), rows
    assert len(rows) >= 2, rows


def test_t3_17_tier1_run_cannot_see_it(tmp_path):
    """qc.run is tier 1. Identity drift is not a tier-1 finding."""
    anchor, her, _ = _trio(tmp_path)
    found = qc.run(her, "image", {"anchor_path": anchor})
    assert _by_check(found, qc.IDENTITY_DRIFT) == []
    assert all(f.get("tier") != 2 for f in found), found


def test_t3_17_run_artefact_records_tier2_score(tmp_path):
    """Studio QC entry is run_artefact. A helper it never calls stays green."""
    anchor, her, human = _trio(tmp_path)
    found = qc_service.run_artefact(human, "image", {"anchor_path": anchor})
    hit = _by_check(found, qc.IDENTITY_DRIFT)
    assert hit, found
    assert hit[0]["tier"] == 2, hit[0]
    assert hit[0]["verdict"] == qc.PASS, hit[0]
    assert hit[0].get("threshold") is None
    assert hit[0]["unit"] == "pct", hit[0]
    assert hit[0]["measured"] is not None
    assert hit[0].get("remedy_class") == qc.REMEDY_NONE, hit[0]
    assert not qc.is_actionable(hit[0]["remedy_class"])

    row = db.one(
        "SELECT * FROM findings WHERE path=? AND check_name=?",
        jobs.canonical_path(human), qc.IDENTITY_DRIFT)
    assert row, "identity_drift was not recorded"
    assert row["tier"] == 2, dict(row)
    assert row["verdict"] == qc.PASS, dict(row)

    her_found = qc_service.run_artefact(her, "image", {"anchor_path": anchor})
    her_hit = _by_check(her_found, qc.IDENTITY_DRIFT)
    assert her_hit, her_found
    assert float(her_hit[0]["measured"]) > float(hit[0]["measured"]), (
        her_hit[0], hit[0])


def test_t3_17_clip_variation_catches_human_by_halfway(tmp_path):
    """Chained-clip drift: her then human has more variation than her throughout."""
    anchor = _paint(tmp_path / "anchor.png", BLACK, standing=True)
    stable = _mp4(tmp_path, "stable.mp4", [BLACK] * 8)
    drifted = _mp4(tmp_path, "drifted.mp4", [BLACK] * 4 + [HUMAN] * 4)
    s_stable = qc.score_identity_artefact(stable, anchor)
    s_drifted = qc.score_identity_artefact(drifted, anchor)
    assert s_stable["n"] >= 2 and s_drifted["n"] >= 2
    assert s_drifted["variation"] > s_stable["variation"], (s_stable, s_drifted)
    assert s_stable["score"] > s_drifted["score"], (s_stable, s_drifted)
    assert s_stable["threshold"] is None
    assert s_drifted["threshold"] is None


def test_t3_17_missing_chosen_anchor_raises(tmp_path):
    """A score without an anchor is a measurement that did not happen."""
    _, her, _ = _trio(tmp_path)
    try:
        qc.score_identity_artefact(her, "")
    except (RuntimeError, ValueError) as e:
        assert "anchor" in str(e).lower(), e
    else:
        raise AssertionError("identity drift scored with no chosen anchor")
    try:
        qc.score_identity_artefact(her, None)
    except (RuntimeError, ValueError) as e:
        assert "anchor" in str(e).lower(), e
    else:
        raise AssertionError("identity drift scored with a None anchor")


def test_t3_17_missing_artefact_raises(tmp_path):
    anchor, _, _ = _trio(tmp_path)
    missing = str(tmp_path / "gone.png")
    try:
        qc.score_identity_artefact(missing, anchor)
    except (RuntimeError, ValueError) as e:
        assert "exist" in str(e).lower() or "missing" in str(e).lower() or "gone" in str(e).lower(), e
    else:
        raise AssertionError("a missing artefact produced a score")


def test_t3_17_scoring_does_not_enqueue_a_repair(tmp_path):
    """T3-18: a score is a measurement. It never auto-heals."""
    anchor, _, human = _trio(tmp_path)
    before = db.q("SELECT id FROM jobs WHERE kind='repair'")
    qc_service.run_artefact(human, "image", {"anchor_path": anchor})
    after = db.q("SELECT id FROM jobs WHERE kind='repair'")
    assert [r["id"] for r in after] == [r["id"] for r in before]
