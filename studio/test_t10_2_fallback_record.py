"""T10-2: a paid fallback says so in the record.

docs/TRD-10 T10-2. Cost must be attributable after the fact, not inferred
from a bill. The one-sided failure is a check that stays green when the
paid path is never taken or nothing is recorded. The positive half: one
local call and one fallback call both record the provider, and the
fallback is marked.
"""
import json

from conftest import _real_module


def _sheet(tmp_path, name="sheet.jpg"):
    p = tmp_path / name
    p.write_bytes(b"\xff\xd8\xff")  # minimal jpeg-ish bytes; never decoded here
    return str(p)


def test_t10_2_local_call_records_provider(monkeypatch, tmp_path):
    """Local success records provider=local and is not marked fallback."""
    real = _real_module("vision")
    assert real is not None, "vision.py failed to import"
    sheet = _sheet(tmp_path)

    monkeypatch.setattr(real, "local_model", lambda: "qwen3-vl")
    monkeypatch.setattr(real, "available", lambda: ("local", "qwen3-vl via gateway"))

    def _local(model, image_path, system, user_text):
        return json.dumps({"flagged": [], "cells_seen": 4})

    monkeypatch.setattr(real, "_ask_local", _local)
    seen = {"xai": 0}

    def _no_xai(*a, **k):
        seen["xai"] += 1
        raise AssertionError("paid path must not run when local succeeds")

    # grok is the session stub; callables are not pre-bound on it.
    monkeypatch.setattr(real.grok, "_chat", _no_xai, raising=False)

    rec = real.classify_sheet(sheet)
    assert seen["xai"] == 0
    provider = rec.get("provider") or rec.get("backend")
    assert provider == "local", rec
    assert rec.get("fallback") is False, rec


def test_t10_2_paid_fallback_records_provider_and_is_marked(monkeypatch, tmp_path):
    """Local failure -> xAI: provider is the paid path, and fallback is marked."""
    real = _real_module("vision")
    sheet = _sheet(tmp_path, "fallback.jpg")

    monkeypatch.setattr(real, "local_model", lambda: "qwen3-vl")
    monkeypatch.setattr(real, "available", lambda: ("local", "qwen3-vl via gateway"))

    def _boom(model, image_path, system, user_text):
        raise RuntimeError("local vision model qwen3-vl failed (503): boom")

    monkeypatch.setattr(real, "_ask_local", _boom)

    def _xai(model, messages, progress=None):
        return json.dumps({"flagged": [], "cells_seen": 3})

    monkeypatch.setattr(real.grok, "_chat", _xai, raising=False)
    monkeypatch.setattr(real.grok, "_resolve_model", lambda m: m, raising=False)
    monkeypatch.setattr(real.grok, "VISION_MODEL", "grok-vision-stub", raising=False)

    rec = real.classify_sheet(sheet)
    provider = rec.get("provider") or rec.get("backend")
    assert provider == "xai", rec
    # The positive half: the fallback is marked, not inferred from backend alone.
    assert rec.get("fallback") is True, rec


def test_t10_2_score_candidate_records_actual_provider_after_fallback(
        monkeypatch, tmp_path):
    """score_candidate success-after-fallback must not keep available()'s hope."""
    real = _real_module("vision")
    cand = tmp_path / "cand.png"
    cand.write_bytes(b"x")

    monkeypatch.setattr(real, "available", lambda: ("local", "qwen3-vl via gateway"))
    monkeypatch.setattr(real, "local_model", lambda: "qwen3-vl")
    monkeypatch.setattr(real, "_env", lambda: ("http://gw/v1", "k"))

    def bad_post(url, headers=None, json=None, timeout=None):
        raise RuntimeError("local vision model qwen3-vl failed (503): boom")

    monkeypatch.setattr(real.httpx, "post", bad_post)

    def _xai(model, messages, progress=None):
        return json.dumps({
            "confidence": 70, "identity": 80, "prompt": 75, "notes": "ok",
        })

    monkeypatch.setattr(real.grok, "_chat", _xai, raising=False)
    monkeypatch.setattr(real.grok, "_resolve_model", lambda m: m, raising=False)
    monkeypatch.setattr(real.grok, "VISION_MODEL", "grok-vision-stub", raising=False)

    rec = real.score_candidate(str(cand), [], "FRONT VIEW")
    # parse_score clamps confidence to min(identity, prompt, confidence)
    assert rec.get("confidence") == 70, rec
    provider = rec.get("provider") or rec.get("backend")
    assert provider == "xai", rec
    assert rec.get("fallback") is True, rec
