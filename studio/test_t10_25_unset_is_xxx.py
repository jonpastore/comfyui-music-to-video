"""T10-25: there is no tier-less draft.

A work with no tier set is treated as xxx for the minor-policy rule — the
most restrictive, not the least. Asserted through the shared entry points
that write paths use: policy_tier, check_text / build_prompt, and
screen_prompt_field. A check that only unit-tests check_text(None) and
leaves the form guards open stays green wrongly.
"""
import pytest
from fastapi import HTTPException

import app as appmod
import guardrail


CHILD = "a 7 year old child dancing in the garden, fully clothed"


def test_t10_25_policy_tier_unset_is_xxx():
    """The named resolution: unset / blank / whitespace is xxx."""
    assert guardrail.policy_tier(None) == "xxx"
    assert guardrail.policy_tier("") == "xxx"
    assert guardrail.policy_tier("   ") == "xxx"
    assert guardrail.policy_tier("g") == "g"
    assert guardrail.policy_tier("PG13") == "pg13"
    assert guardrail.policy_tier("xxx") == "xxx"
    # Anything unknown stays itself (not silently opened as g/pg13).
    assert guardrail.policy_tier("custom") == "custom"


def test_t10_25_unset_refuses_on_shared_write_paths():
    """Write paths that lack a lock refuse the child string, same as xxx."""
    for tier in (None, "", "   "):
        with pytest.raises(guardrail.ContentRefused):
            guardrail.check_text(CHILD, "draft", tier=tier)
        with pytest.raises(guardrail.ContentRefused):
            guardrail.build_prompt(CHILD, where="draft", tier=tier)
        assert not guardrail.allows_minor_depiction(tier)

    # Form guard used by character / album / draft fields (no tier on the row).
    with pytest.raises(HTTPException) as err:
        appmod.screen_prompt_field(CHILD, "prompt", "view draft")
    assert err.value.status_code == 400
    low = str(err.value.detail).lower()
    assert ("child" in low or "minor" in low or "under 18" in low
            or "year old" in low), err.value.detail

    # Same string accepted only when the lock is named g/pg13 — proves the
    # form guard carries tier, not only check_text.
    assert appmod.screen_prompt_field(CHILD, "prompt", "view draft", tier="g") == CHILD
    with pytest.raises(HTTPException):
        appmod.screen_prompt_field(CHILD, "prompt", "view draft", tier="xxx")
