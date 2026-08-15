"""T6-A9: A refusal or a presence is half a criterion.

docs/TRD-6 §0.4. "X is refused" and "the payload carries Y" both stay
green when the whole feature is deleted, because a feature that does not
exist refuses everything and a field nobody reads is still present.
Every such criterion is paired with a positive case, or marked
**provisional** and says what it cannot yet distinguish.

Kill: offer only the refusal half (or only a presence assert) as the
whole criterion → `require_pair` raises HalfCriterion. A deleted feature
keeps every refuse-only check green; a field nobody reads keeps every
presence-only check green. Vacuous green is not a complete criterion.
"""
import os
import tempfile

import pytest

import db
import jobs


class HalfCriterion(AssertionError):
    """Raised when only the refusal or presence half is offered as proof."""


def require_pair(*, half, positive=None, provisional=False, gap=None,
                 label="T6-A9"):
    """Pair a refusal/presence half with a positive case.

    `half` is the outcome of the refuse-or-presence check (must be true —
    the half that would stay green if the feature were deleted).
    `positive` is the outcome of the feature-exercising case (must be true
    for a complete criterion).

    Provisional criteria omit the positive case only when `gap` names what
    they cannot yet distinguish.
    """
    if provisional:
        if not gap or not str(gap).strip():
            raise HalfCriterion(
                f"{label}: provisional without naming what it cannot "
                f"yet distinguish")
        return {"provisional": True, "gap": gap, "half": half}
    if not half:
        raise HalfCriterion(
            f"{label}: refusal/presence half did not hold "
            f"(half={half!r})")
    if not positive:
        raise HalfCriterion(
            f"{label}: refusal or presence is half a criterion; "
            f"pair a positive case (positive={positive!r})")
    return {"half": half, "positive": positive, "paired": True}


def test_t6_a9_refusal_only_is_half():
    """Refuse-everything stays green without a positive accept case.

    Mutation: delete the feature under test; every input is refused. The
    refusal half alone remains true. require_pair must refuse that as a
    complete criterion.
    """
    always_refused = True  # feature deleted → everything refused
    with pytest.raises(HalfCriterion, match="half a criterion|positive"):
        require_pair(half=always_refused, positive=None)
    with pytest.raises(HalfCriterion, match="half a criterion|positive"):
        require_pair(half=always_refused, positive=False)


def test_t6_a9_presence_only_is_half():
    """A field nobody reads is still present — presence alone is not evidence.

    Mutation: stop reading the field. ` "Y" in payload ` stays green. The
    positive half is that the field is consumed and changes an outcome.
    """
    payload = {"expect_json": {"width": 100}, "unused": "still here"}
    presence = "expect_json" in payload  # stays green if never read
    with pytest.raises(HalfCriterion, match="half a criterion|positive"):
        require_pair(half=presence, positive=None)


def test_t6_a9_pair_accepts_both_halves():
    """Refusal half + positive accept is a complete criterion."""
    refused_over = True
    accepted_at_bound = True
    report = require_pair(half=refused_over, positive=accepted_at_bound)
    assert report["paired"] is True
    assert report["half"] is True
    assert report["positive"] is True


def test_t6_a9_provisional_must_name_the_gap():
    """Provisional is allowed only when the gap is named."""
    with pytest.raises(HalfCriterion, match="provisional|distinguish"):
        require_pair(half=True, provisional=True, gap=None)
    with pytest.raises(HalfCriterion, match="provisional|distinguish"):
        require_pair(half=True, provisional=True, gap="  ")
    report = require_pair(
        half=True,
        provisional=True,
        gap="no cloning path yet — cannot distinguish accept from refuse",
    )
    assert report["provisional"] is True
    assert "cloning" in report["gap"]


def _isolate():
    data = tempfile.mkdtemp(prefix="t6a9_")
    db.DATA = data
    db.DB_PATH = os.path.join(data, "t.db")
    db._local.__dict__.clear()
    jobs.LOGS = os.path.join(data, "logs")
    jobs._capability_where = None
    if "t6a9" not in jobs._handlers:
        @jobs.handler("t6a9")
        def _t6a9(args, progress):
            return args
    return data


def test_t6_a9_t6_2_pairs_refuse_early_with_successor_ready():
    """Product exemplar: T6-2's refuse-early half needs its positive.

    Half: a chained successor is not claimed while its predecessor is
    still open (ready ≠ queued). That half alone stays green if nothing
    is ever claimed after a land. Positive: once the predecessor has
    landed, the successor becomes ready and is pulled.
    Shared entry: jobs._claim (T6-A10).
    """
    _isolate()

    pred = jobs.enqueue("t6a9", {"who": "pred"})
    succ = jobs.enqueue("t6a9", {"who": "succ"}, depends_on=pred)
    later = jobs.enqueue("t6a9", {"who": "later"})

    first = jobs._claim()
    assert first is not None and first["id"] == pred
    second = jobs._claim()
    assert second is not None and second["id"] == later
    refused_early = jobs._claim() is None
    assert jobs.get(succ)["status"] == "queued"

    db.run("UPDATE jobs SET status='done', finished=? WHERE id=?", 1.0, pred)
    pulled = jobs._claim()
    successor_ready = pulled is not None and pulled["id"] == succ

    with pytest.raises(HalfCriterion, match="half a criterion|positive"):
        require_pair(half=refused_early, positive=None)

    report = require_pair(
        half=refused_early,
        positive=successor_ready,
        label="T6-A9/T6-2",
    )
    assert report["paired"] is True
