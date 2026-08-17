"""T3-31 / T4-19: vision scores each candidate against bases + prompt."""
import json

import db
import app as appmod
from conftest import _real_module


def test_parse_score_clamps_and_requires_an_int():
    parse = _real_module("vision").parse_score
    got = parse({
        "confidence": 140, "identity": -3, "prompt": 80.4, "notes": "her face",
    })
    assert got["confidence"] == 100
    assert got["identity"] == 0
    assert got["prompt"] == 80
    assert got["notes"] == "her face"
    empty = parse({"confidence": "nope"})
    assert empty["confidence"] is None


def test_score_candidate_uses_bases_and_prompt(monkeypatch, tmp_path):
    real = _real_module("vision")
    seen = {}

    def fake_ask(paths, system, user_text, progress=None):
        seen["paths"] = list(paths)
        seen["user"] = user_text
        text = json.dumps({"confidence": 72, "identity": 70, "prompt": 75,
                           "notes": "same black cat-woman, standing"})
        return text, {"provider": "local", "backend": "local", "fallback": False}

    monkeypatch.setattr(real, "ask_images", fake_ask)
    cand = tmp_path / "cand.png"
    base = tmp_path / "base.png"
    cand.write_bytes(b"x")
    base.write_bytes(b"y")
    got = real.score_candidate(str(cand), [str(base)], "FRONT VIEW of Meow P")
    assert seen["paths"][0] == str(cand)
    assert str(base) in seen["paths"]
    assert "FRONT VIEW of Meow P" in seen["user"]
    assert got["confidence"] == 70
    assert got["backend"]


def test_h_anchor_stores_qc_json_and_does_not_add_bases(monkeypatch, tmp_path):
    sheet = tmp_path / "sheet.png"
    sheet.write_bytes(b"png")
    base = tmp_path / "base.png"
    base.write_bytes(b"base")
    scored = []

    def fake_score(path, bases, prompt, progress=None):
        scored.append((path, list(bases), prompt))
        return {"confidence": 64, "identity": 60, "prompt": 70,
                "notes": "ok", "backend": "stub"}

    monkeypatch.setattr(appmod.pipeline, "gen_anchor",
                        lambda *a, **k: [str(sheet)])
    monkeypatch.setattr(appmod.vision, "score_candidate", fake_score)
    before = {r["id"] for r in db.q("SELECT id FROM assets WHERE kind='anchor_ref'")}
    appmod.h_anchor({
        "scope_kind": "album", "scope_value": "QC Album",
        "tier": "xxx", "view": "back_nude", "n": 1,
        "images": [str(base)], "prompt": "kneeling, tail aside",
        "character_id": None, "render": {"cfg": 2.0, "steps": 50},
    }, lambda m: None)
    row = db.one("SELECT * FROM anchors WHERE path=?", str(sheet))
    assert row, "candidate was not stored"
    qc = json.loads(row["qc_json"])
    assert qc["confidence"] == 64
    assert scored[0][1] == [str(base)]
    assert "kneeling" in scored[0][2]
    after = {r["id"] for r in db.q("SELECT id FROM assets WHERE kind='anchor_ref'")}
    assert after == before, "generate must not add base images"


def test_candidate_tile_shows_confidence():
    html = appmod.templates.get_template("_anchor_group.html").render(
        request=None,
        g={"scope_kind": "album", "scope_value": "Street Cats",
           "character_name": None, "character_id": None,
           "tier": "xxx", "view": "back_nude", "unpicked": 0,
           "candidates": [{
               "id": 1, "path": "/tmp/c.png", "chosen": 0, "run_id": None,
               "render_json": None,
               "qc_json": json.dumps({"confidence": 81, "notes": "her"}),
           }]},
        media_url=lambda p: "/media?p=" + p,
    )
    assert "81%" in html
    assert "confidence" in html.lower() or "vision" in html.lower()


def test_qc_tag_does_not_hide_xai_or_local_failure_as_unknown():
    xai = appmod.qc_tag({"qc_json": json.dumps({
        "confidence": None, "identity": None, "prompt": None,
        "error": "xAI chat request failed (400): Incorrect API key",
        "backend": "xai",
    })})
    assert xai
    assert "unknown" not in xai.lower()
    assert "xai" in xai.lower()

    local = appmod.qc_tag({"qc_json": json.dumps({
        "confidence": None, "identity": None, "prompt": None,
        "error": "local vision model qwen3-vl failed (503): boom",
        "backend": "local",
    })})
    assert local
    assert "unknown" not in local.lower()
    assert "local" in local.lower()

    assert appmod.qc_tag({"qc_json": None}) == ""
    assert appmod.qc_tag({"qc_json": json.dumps({"confidence": None})}) == ""
    assert appmod.qc_tag({"qc_json": json.dumps({"confidence": 64})}) == "confidence 64%"


def test_score_candidate_does_not_hide_xai_or_local_failure(monkeypatch, tmp_path):
    real = _real_module("vision")
    cand = tmp_path / "cand.png"
    cand.write_bytes(b"x")

    monkeypatch.setattr(real, "available", lambda: ("xai", "no local vision model"))
    monkeypatch.setattr(real, "ask_images", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("xAI chat request failed (400): Incorrect API key")))
    xai = real.score_candidate(str(cand), [], "FRONT VIEW")
    assert xai["confidence"] is None
    assert "xai" in (xai.get("error") or "").lower()
    assert "unknown" not in (xai.get("error") or "").lower()
    assert xai["backend"] == "xai"

    # available() said local; the exception is from the xAI fallback. The
    # stored backend must follow the exception, not the hope.
    monkeypatch.setattr(real, "available", lambda: ("local", "qwen3-vl via gateway"))
    xai_after_local = real.score_candidate(str(cand), [], "FRONT VIEW")
    assert xai_after_local["confidence"] is None
    assert "xai" in (xai_after_local.get("error") or "").lower()
    assert xai_after_local["backend"] == "xai"

    monkeypatch.setattr(real, "ask_images", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("local vision model qwen3-vl failed (503): boom")))
    local = real.score_candidate(str(cand), [], "FRONT VIEW")
    assert local["confidence"] is None
    assert "local" in (local.get("error") or "").lower()
    assert "unknown" not in (local.get("error") or "").lower()
    assert local["backend"] == "local"


def test_candidate_tile_shows_named_vision_failure():
    html = appmod.templates.get_template("_anchor_group.html").render(
        request=None,
        g={"scope_kind": "album", "scope_value": "Street Cats",
           "character_name": None, "character_id": None,
           "tier": "xxx", "view": "back_nude", "unpicked": 0,
           "candidates": [{
               "id": 2, "path": "/tmp/c.png", "chosen": 0, "run_id": None,
               "render_json": None,
               "qc_json": json.dumps({
                   "confidence": None,
                   "error": "xAI chat request failed (400): Incorrect API key",
                   "backend": "xai",
               }),
           }]},
        media_url=lambda p: "/media?p=" + p,
    )
    low = html.lower()
    assert "unknown" not in low
    assert "xai" in low
