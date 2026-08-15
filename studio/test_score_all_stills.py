"""Every generated still is scored (T3-31) and can be repaired as a new file.

Vision is advisory. A refine/repair writes dest != src (T3-6 / T3-23).
It does not overwrite the generate."""
import json
import os
import time

import db
import app as appmod
from conftest import _real_module


def _png(path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + os.urandom(8))
    return path


def _score(path, bases, prompt="", progress=None):
    return {"confidence": 61, "identity": 70, "prompt": 55,
            "notes": "scored", "backend": "stub"}


def test_score_generated_still_json_and_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(appmod.vision, "score_candidate", _score)
    p = _png(str(tmp_path / "a.png"))
    raw = appmod.score_generated_still(p, [p], "FRONT VIEW")
    got = json.loads(raw)
    assert got["confidence"] == 61

    def boom(*a, **k):
        raise RuntimeError("no local vision model (litellm /models empty or 503)")

    monkeypatch.setattr(appmod.vision, "score_candidate", boom)
    failed = json.loads(appmod.score_generated_still(p, [], "x"))
    assert failed["confidence"] is None
    assert "no local vision model" in failed["error"]


def test_refine_generated_still_is_new_bytes(monkeypatch, tmp_path):
    src = _png(str(tmp_path / "src.png"))

    def _fix_ref(*a, **kw):
        image_path = kw.get("image_path") or (a[4] if len(a) > 4 else src)
        out = image_path + ".fixed"
        with open(image_path, "rb") as f:
            payload = f.read()
        with open(out, "wb") as f:
            f.write(payload + b"-fixed")
        return [{"path": out, "clip_idx": 0, "seed": 1}]

    monkeypatch.setattr(appmod.pipeline, "fix_ref", _fix_ref)
    monkeypatch.setattr(appmod.qc_service, "dispatch_repair",
                        lambda src, dest, args, progress:
                        appmod.qc_service._invoke_actuator(
                            "fix_ref", src, dest, args, progress))
    dest = appmod.refine_generated_still(src, lambda m: None)
    assert dest != src
    assert os.path.isfile(dest)
    with open(src, "rb") as f, open(dest, "rb") as g:
        assert f.read() != g.read()


def test_h_refs_stores_qc_json(monkeypatch, tmp_path):
    sheet = _png(str(tmp_path / "ref.png"))
    monkeypatch.setattr(appmod.vision, "score_candidate", _score)
    monkeypatch.setattr(appmod.pipeline, "install_input",
                        lambda p, name=None: os.path.basename(p))
    monkeypatch.setattr(appmod.pipeline, "gen_refs",
                        lambda *a, **k: [{"clip_idx": 0, "path": sheet, "seed": 9}])
    sid = db.run(
        "INSERT INTO songs (title, album, slug, created) VALUES (?,?,?,?)",
        "QC Refs", "QC Album", f"qc-refs-{time.time_ns()}", time.time())
    db.run("INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created) "
           "VALUES (?,?,?,?,?,?)", sid, "xxx", "/sb.json", "/sb.md", 1, time.time())
    appmod.h_refs({
        "song_id": sid, "tier": "xxx", "anchor_path": sheet, "refine": False,
    }, lambda m: None)
    row = db.one("SELECT * FROM refs WHERE path=?", sheet)
    assert row, "ref was not stored"
    assert row["qc_json"], "generated ref has no vision score"
    assert json.loads(row["qc_json"])["confidence"] == 61


def test_h_fix_ref_stores_qc_json(monkeypatch, tmp_path):
    src = _png(str(tmp_path / "broken.png"))
    out = _png(str(tmp_path / "fixed.png"))
    monkeypatch.setattr(appmod.vision, "score_candidate", _score)
    monkeypatch.setattr(appmod.pipeline, "fix_ref",
                        lambda *a, **k: [{"clip_idx": 0, "path": out, "seed": 3}])
    sid = db.run(
        "INSERT INTO songs (title, album, slug, created) VALUES (?,?,?,?)",
        "QC Fix", "QC Album", f"qc-fix-{time.time_ns()}", time.time())
    appmod.h_fix_ref({
        "song_id": sid, "tier": "xxx", "clip_idx": 0, "mode": "face",
        "image_path": src, "seed": 3, "refine": False,
    }, lambda m: None)
    row = db.one("SELECT * FROM refs WHERE path=?", out)
    assert row
    assert json.loads(row["qc_json"])["confidence"] == 61


def test_h_fix_anchor_stores_qc_json(monkeypatch, tmp_path):
    src = _png(str(tmp_path / "anchor.png"))
    out = _png(str(tmp_path / "anchor_fixed.png"))
    monkeypatch.setattr(appmod.vision, "score_candidate", _score)
    monkeypatch.setattr(appmod.pipeline, "fix_ref",
                        lambda *a, **k: [{"clip_idx": 0, "path": out, "seed": 7}])
    aid = db.run(
        """INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen,
                                created, character_id)
           VALUES (?,?,?,?,?,0,?,?)""",
        "album", f"QC FixAnchor {time.time_ns()}", "xxx", "front", src, time.time(), None)
    appmod.h_fix_anchor({
        "anchor_id": aid, "mode": "inpaint", "seed": 7,
        "instruction": "tail aside, expose vulva",
    }, lambda m: None)
    src_row = db.one("SELECT * FROM anchors WHERE id=?", aid)
    new_row = db.one("SELECT * FROM anchors WHERE path=?", out)
    assert src_row, "source candidate must stay"
    assert src_row["path"] == src
    assert new_row, "fix must land a new candidate"
    assert new_row["id"] != aid
    assert new_row["qc_json"], "h_fix_anchor still lands a new candidate with no qc_json"
    assert json.loads(new_row["qc_json"])["confidence"] == 61


def test_h_artwork_stores_qc_json(monkeypatch, tmp_path):
    cover = _png(str(tmp_path / "cover.png"))
    monkeypatch.setattr(appmod.vision, "score_candidate", _score)
    monkeypatch.setattr(appmod.pipeline, "gen_artwork",
                        lambda *a, **k: [cover])
    pid = db.run(
        "INSERT INTO playlists (name, kind, created) VALUES (?,'playlist',?)",
        f"QC Art {time.time_ns()}", time.time())
    appmod.h_artwork({
        "playlist_id": pid, "refine": False,
    }, lambda m: None)
    row = db.one("SELECT * FROM assets WHERE path=?", cover)
    assert row
    assert json.loads(row["qc_json"])["confidence"] == 61


def test_h_artwork_refine_scores_generate_and_sibling(monkeypatch, tmp_path):
    """Default refine must not drop the generate: both covers are scored assets."""
    cover = _png(str(tmp_path / "cover.png"))
    scored = []

    def fake_score(path, bases, prompt="", progress=None):
        scored.append(path)
        return {"confidence": 50, "identity": 50, "prompt": 50,
                "notes": "ok", "backend": "stub"}

    def _fix_ref(*a, **kw):
        image_path = kw.get("image_path") or a[4]
        out = image_path + ".fixed"
        with open(image_path, "rb") as f:
            payload = f.read()
        with open(out, "wb") as f:
            f.write(payload + b"-fixed")
        return [{"path": out, "clip_idx": 0, "seed": 1}]

    monkeypatch.setattr(appmod.vision, "score_candidate", fake_score)
    monkeypatch.setattr(appmod.pipeline, "gen_artwork", lambda *a, **k: [cover])
    monkeypatch.setattr(appmod.pipeline, "fix_ref", _fix_ref)
    monkeypatch.setattr(appmod.qc_service, "dispatch_repair",
                        lambda src, dest, args, progress:
                        appmod.qc_service._invoke_actuator(
                            "fix_ref", src, dest, args, progress))
    pid = db.run(
        "INSERT INTO playlists (name, kind, created) VALUES (?,'playlist',?)",
        f"QC Art Refine {time.time_ns()}", time.time())
    appmod.h_artwork({"playlist_id": pid, "refine": True}, lambda m: None)
    rows = [r for r in db.q("SELECT * FROM assets WHERE kind='artwork' ORDER BY id")
            if json.loads(r["meta_json"] or "{}").get("playlist_id") == pid]
    assert len(rows) == 2, [r["path"] for r in rows]
    paths = [r["path"] for r in rows]
    assert cover in paths, "generate is not a scored assets row"
    assert any(p != cover for p in paths)
    assert os.path.isfile(cover)
    assert all(os.path.isfile(r["path"]) for r in rows)
    with open(rows[0]["path"], "rb") as f, open(rows[1]["path"], "rb") as g:
        assert f.read() != g.read()
    assert all(json.loads(r["qc_json"])["confidence"] == 50 for r in rows)
    assert cover in scored


def test_h_anchor_refine_writes_sibling_not_overwrite(monkeypatch, tmp_path):
    sheet = _png(str(tmp_path / "sheet.png"))
    scored = []

    def fake_score(path, bases, prompt="", progress=None):
        scored.append(path)
        return {"confidence": 50, "identity": 50, "prompt": 50,
                "notes": "ok", "backend": "stub"}

    def _fix_ref(*a, **kw):
        image_path = kw.get("image_path") or a[4]
        out = image_path + ".fixed"
        with open(image_path, "rb") as f:
            payload = f.read()
        with open(out, "wb") as f:
            f.write(payload + b"-fixed")
        return [{"path": out, "clip_idx": 0, "seed": 1}]

    monkeypatch.setattr(appmod.vision, "score_candidate", fake_score)
    monkeypatch.setattr(appmod.pipeline, "gen_anchor", lambda *a, **k: [sheet])
    monkeypatch.setattr(appmod.pipeline, "fix_ref", _fix_ref)
    monkeypatch.setattr(appmod.qc_service, "dispatch_repair",
                        lambda src, dest, args, progress:
                        appmod.qc_service._invoke_actuator(
                            "fix_ref", src, dest, args, progress))
    appmod.h_anchor({
        "scope_kind": "album", "scope_value": "QC Album",
        "tier": "xxx", "view": "front", "n": 1,
        "images": [], "prompt": "FRONT VIEW", "character_id": None,
        "refine": True,
    }, lambda m: None)
    rows = db.q("SELECT * FROM anchors WHERE scope_value='QC Album' AND view='front' "
                "ORDER BY id")
    assert len(rows) == 2, [r["path"] for r in rows]
    assert rows[0]["path"] == sheet
    assert rows[1]["path"] != sheet
    assert os.path.isfile(rows[1]["path"])
    with open(rows[0]["path"], "rb") as f, open(rows[1]["path"], "rb") as g:
        assert f.read() != g.read()
    assert all(json.loads(r["qc_json"])["confidence"] == 50 for r in rows)
    assert sheet in scored
