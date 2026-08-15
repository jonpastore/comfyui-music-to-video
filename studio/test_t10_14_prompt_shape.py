"""T10-14: match-question prompt shapes are refused; describe-what-differs is not.

docs/TRD-10 T10-14. A model asked "does this match?" answers yes — the shape
that produced 41.1-vs-64.7. The one-sided failure is a check that stays green
if no match question is ever sent. The positive half requires the accepted
shape "describe what differs" on the same surface, returning non-verdict text.
"""
import json

import pytest

from conftest import _real_module


def _vision():
    real = _real_module("vision")
    assert real is not None, "vision.py failed to import"
    return real


def test_t10_14_does_this_match_is_refused_as_prompt_shape():
    """Deleting the gate keeps 'never ask match?' green by not asking."""
    vision = _vision()
    for q in (
        "Does this match the reference?",
        "does this match?",
        "do these match the reference",
        "is this a match",
    ):
        with pytest.raises(ValueError) as err:
            vision.prompt_shape(q)
        text = str(err.value).lower()
        assert "match" in text or "prompt shape" in text or "t10-14" in text, err.value
        assert "describe what differs" in text, (
            "refusal must name the accepted shape so the caller can recover")


def test_t10_14_describe_what_differs_is_accepted():
    """The positive half of the one-sided refusal: this shape is not refused."""
    vision = _vision()
    got = vision.prompt_shape(vision.DESCRIBE_DIFFERS)
    assert got == vision.DESCRIBE_DIFFERS
    got2 = vision.prompt_shape("describe what differs")
    assert "describe what differs" in got2.lower()


def test_t10_14_same_surface_returns_non_verdict_text(monkeypatch, tmp_path):
    """describe_what_differs accepts the shape and returns text, never a verdict.

    Match questions on the same surface still refuse. A return that is a
    pass/fail dict would reintroduce the failure T10-13 already closed.
    """
    vision = _vision()
    sheet = tmp_path / "sheet.jpg"
    sheet.write_bytes(b"x")

    def fake_ask(path, system, user_text, progress=None, prefer_local=True):
        assert vision.DESCRIBE_DIFFERS in user_text.lower(), user_text
        assert not vision._MATCH_SHAPE.search(user_text), user_text
        text = json.dumps({
            "flagged": [{"clip": 1, "issue": "broken", "reason": "two of her"}],
            "cells_seen": 4,
        })
        return text, {"provider": "local", "backend": "local", "fallback": False}

    monkeypatch.setattr(vision, "ask", fake_ask)
    monkeypatch.setattr(vision, "available", lambda: ("local", "stub"))

    with pytest.raises(ValueError) as err:
        vision.describe_what_differs(
            str(sheet), question="Does this match the reference?")
    assert "match" in str(err.value).lower() or "prompt shape" in str(err.value).lower()

    text = vision.describe_what_differs(str(sheet))
    assert isinstance(text, str), f"verdict structure returned: {text!r}"
    assert "two of her" in text, text
    low = text.lower()
    assert "pass" not in low and "fail" not in low and "reject" not in low, text
    # not a JSON verdict blob either
    assert not text.strip().startswith("{"), text


def test_t10_14_classify_sheet_asks_describe_what_differs(monkeypatch, tmp_path):
    """The live call site must not send a match question to the model."""
    vision = _vision()
    sheet = tmp_path / "sheet.jpg"
    sheet.write_bytes(b"x")
    seen = {}

    def fake_ask(path, system, user_text, progress=None, prefer_local=True):
        seen["user"] = user_text
        return (json.dumps({"flagged": [], "cells_seen": 2}),
                {"provider": "local", "backend": "local", "fallback": False})

    monkeypatch.setattr(vision, "ask", fake_ask)
    monkeypatch.setattr(vision, "available", lambda: ("local", "stub"))
    got = vision.classify_sheet(str(sheet), note="T10-14")
    assert got["flagged"] == []
    assert vision.DESCRIBE_DIFFERS in seen["user"].lower(), seen
    assert not vision._MATCH_SHAPE.search(seen["user"]), seen
