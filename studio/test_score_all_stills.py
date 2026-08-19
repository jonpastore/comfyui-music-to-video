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


def test_score_system_wardrobe_is_not_identity():
    vision = _real_module("vision")
    text = vision.SCORE_SYSTEM.lower()
    assert "wardrobe does not lower identity" in text
    assert "physical" in text


def test_score_landed_clip_stores_qc_json(monkeypatch, tmp_path):
    clip = str(tmp_path / "c.mp4")
    frame = str(tmp_path / "c.mp4.qc.png")
    open(clip, "wb").write(b"mp4")
    _png(frame)
    monkeypatch.setattr(appmod.vision, "score_candidate", _score)

    def _extract(path, which="first", dest=None):
        dest = dest or (path + ".qc.png")
        open(dest, "wb").write(open(frame, "rb").read())
        return dest

    import build_song
    monkeypatch.setattr(build_song, "extract_video_frame", _extract)
    sid = db.upsert_song("qc-clip", title="QC Clip", duration=8.0)
    db.run("""INSERT INTO clips (song_id, tier, clip_idx, path, status)
              VALUES (?,?,?,?,?)""", sid, "xxx", 0, clip, "done")
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    raw = appmod.score_landed_clip(clip, song, "xxx", 0)
    assert raw
    row = db.one("SELECT qc_json FROM clips WHERE path=?", clip)
    assert row and row["qc_json"]
    got = json.loads(row["qc_json"])
    assert got["confidence"] == 61
    assert got["identity"] == 70


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


def _stub_fix_ref(monkeypatch, src=None):
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


def _dest_qc(path):
    """T3-31 score stored on the landed dest, if any."""
    import jobs
    canon = jobs.canonical_path(path)
    for table in ("anchors", "refs", "assets", "artefacts"):
        row = db.one(f"SELECT qc_json FROM {table} WHERE path=?", canon)
        if row is None and canon != path:
            row = db.one(f"SELECT qc_json FROM {table} WHERE path=?", path)
        if row and row["qc_json"]:
            return json.loads(row["qc_json"])
    return None


def test_refine_generated_still_is_new_bytes(monkeypatch, tmp_path):
    src = _png(str(tmp_path / "src.png"))
    _stub_fix_ref(monkeypatch, src)
    dest = appmod.refine_generated_still(src, lambda m: None)
    assert dest != src
    assert os.path.isfile(dest)
    with open(src, "rb") as f, open(dest, "rb") as g:
        assert f.read() != g.read()


def test_refine_generated_still_stores_qc_json(monkeypatch, tmp_path):
    """Standalone refine dest is a scored still (T3-31). Named landers
    already persist their own dest row; this path must not land NULL."""
    src = _png(str(tmp_path / "src.png"))
    monkeypatch.setattr(appmod.vision, "score_candidate", _score)
    _stub_fix_ref(monkeypatch, src)
    dest = appmod.refine_generated_still(src, lambda m: None)
    assert dest != src
    assert os.path.isfile(dest)
    with open(src, "rb") as f, open(dest, "rb") as g:
        assert f.read() != g.read()
    got = _dest_qc(dest)
    assert got, "standalone refine_generated_still dest landed with no qc_json"
    assert got["confidence"] == 61


def test_h_repair_dest_stores_qc_json(monkeypatch, tmp_path):
    """h_repair dest is a scored still (T3-31). QC does not auto-heal
    (T3-18): dest exists only after approve() queued the repair."""
    import jobs
    import qc_service

    src = _png(str(tmp_path / "broken.png"))
    monkeypatch.setattr(appmod.vision, "score_candidate", _score)

    def _write_candidate(s, dest, args, progress):
        with open(s, "rb") as f:
            payload = f.read()
        with open(dest, "wb") as f:
            f.write(payload + b"-repaired")
        return dest

    monkeypatch.setattr(qc_service, "dispatch_repair", _write_candidate)
    qc_service.record([{
        "path": src, "kind": "image", "tier": 1, "check": "resolution",
        "verdict": "reject", "measured": "64x64", "expected": "896x1216",
        "unit": "px", "detail": "too small", "remedy": "re-render",
    }])
    fid = db.one("SELECT id FROM findings WHERE path=?", src)["id"]
    before = {r["id"] for r in db.q("SELECT id FROM jobs")}
    qc_service.approve(fid)
    jobs_for = []
    for row in db.q("SELECT * FROM jobs ORDER BY id"):
        try:
            args = json.loads(row["args_json"] or "{}")
        except ValueError:
            continue
        if args.get("finding_id") == fid:
            jobs_for.append((row["id"], args))
    assert {jid for jid, _ in jobs_for}.isdisjoint(before)
    assert len(jobs_for) == 1, "approve must enqueue one repair, QC must not"
    args = jobs_for[-1][1]
    dest = args["repair_path"]
    assert dest and dest != src
    assert not os.path.isfile(dest)
    qc_service.h_repair(args, lambda m: None)
    assert os.path.isfile(src)
    assert os.path.isfile(dest)
    assert jobs.canonical_path(dest) != jobs.canonical_path(src)
    got = _dest_qc(dest)
    assert got, "h_repair dest landed with no qc_json"
    assert got["confidence"] == 61


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


def test_h_refs_scores_vs_chosen_anchor(monkeypatch, tmp_path):
    """Each landed ref is score_candidate'd with the chosen anchor as bases.
    Storing any qc_json is not enough: empty bases or the job plate still
    write a row."""
    chosen = _png(str(tmp_path / "chosen_anchor.png"))
    plate = _png(str(tmp_path / "standing_plate.png"))
    ref = _png(str(tmp_path / "ref.png"))
    seen = []

    def fake_score(path, bases, prompt="", progress=None):
        seen.append((path, list(bases or []), prompt))
        return {"confidence": 61, "identity": 70, "prompt": 55,
                "notes": "scored", "backend": "stub"}

    monkeypatch.setattr(appmod.vision, "score_candidate", fake_score)
    monkeypatch.setattr(appmod.pipeline, "install_input",
                        lambda p, name=None: os.path.basename(p))
    monkeypatch.setattr(appmod.pipeline, "gen_refs",
                        lambda *a, **k: [{"clip_idx": 0, "path": ref, "seed": 9}])
    album = f"QC Refs Score {time.time_ns()}"
    sid = db.run(
        "INSERT INTO songs (title, album, slug, created) VALUES (?,?,?,?)",
        "QC Refs Score", album, f"qc-refs-score-{time.time_ns()}", time.time())
    db.run("INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created) "
           "VALUES (?,?,?,?,?,?)", sid, "xxx", "/sb.json", "/sb.md", 1, time.time())
    db.run(
        """INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen,
                                created, character_id)
           VALUES (?,?,?,?,?,1,?,?)""",
        "album", album, "xxx", "front", chosen, time.time(), None)
    # Job may carry a standing plate for gen; scoring must still use the chosen sheet.
    appmod.h_refs({
        "song_id": sid, "tier": "xxx", "anchor_path": plate, "refine": False,
    }, lambda m: None)
    row = db.one("SELECT * FROM refs WHERE path=?", ref)
    assert row and row["qc_json"], "ref landed without qc_json"
    assert seen, "score_candidate never ran"
    path, bases, prompt = seen[0]
    assert path == ref
    assert bases == [chosen], f"ref scored vs {bases!r}, not chosen anchor"
    assert plate not in bases
    assert ref not in bases


def test_h_reroll_stores_qc_json(monkeypatch, tmp_path):
    """h_reroll is a named still lander (T3-31). The generate row must
    carry qc_json + confidence; named landers already persist their own
    dest. Refine is off so this is the reroll itself, not a sibling."""
    sheet = _png(str(tmp_path / "reroll.png"))
    anchor = _png(str(tmp_path / "anchor.png"))
    monkeypatch.setattr(appmod.vision, "score_candidate", _score)
    monkeypatch.setattr(appmod.pipeline, "install_input",
                        lambda p, name=None: os.path.basename(p))
    monkeypatch.setattr(appmod.pipeline, "reroll",
                        lambda *a, **k: [{"clip_idx": 0, "path": sheet, "seed": 11}])
    album = f"QC Reroll {time.time_ns()}"
    sid = db.run(
        "INSERT INTO songs (title, album, slug, created) VALUES (?,?,?,?)",
        "QC Reroll", album, f"qc-reroll-{time.time_ns()}", time.time())
    db.run("INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created) "
           "VALUES (?,?,?,?,?,?)", sid, "xxx", "/sb.json", "/sb.md", 1, time.time())
    db.run(
        """INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen,
                                created, character_id)
           VALUES (?,?,?,?,?,1,?,?)""",
        "album", album, "xxx", "front", anchor, time.time(), None)
    appmod.h_reroll({
        "song_id": sid, "tier": "xxx", "clip_indices": [0], "refine": False,
    }, lambda m: None)
    row = db.one("SELECT * FROM refs WHERE path=?", sheet)
    assert row, "reroll was not stored"
    assert row["qc_json"], "h_reroll still lander has no qc_json"
    assert json.loads(row["qc_json"])["confidence"] == 61
    assert row["origin"] == "reroll"


def test_h_reroll_scores_vs_chosen_anchor(monkeypatch, tmp_path):
    """h_reroll lands are scored vs the chosen anchor, not the reroll bytes."""
    sheet = _png(str(tmp_path / "reroll.png"))
    anchor = _png(str(tmp_path / "anchor.png"))
    seen = []

    def fake_score(path, bases, prompt="", progress=None):
        seen.append((path, list(bases or []), prompt))
        return {"confidence": 61, "identity": 70, "prompt": 55,
                "notes": "scored", "backend": "stub"}

    monkeypatch.setattr(appmod.vision, "score_candidate", fake_score)
    monkeypatch.setattr(appmod.pipeline, "install_input",
                        lambda p, name=None: os.path.basename(p))
    monkeypatch.setattr(appmod.pipeline, "reroll",
                        lambda *a, **k: [{"clip_idx": 0, "path": sheet, "seed": 11}])
    album = f"QC Reroll Score {time.time_ns()}"
    sid = db.run(
        "INSERT INTO songs (title, album, slug, created) VALUES (?,?,?,?)",
        "QC Reroll Score", album, f"qc-reroll-score-{time.time_ns()}", time.time())
    db.run("INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created) "
           "VALUES (?,?,?,?,?,?)", sid, "xxx", "/sb.json", "/sb.md", 1, time.time())
    db.run(
        """INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen,
                                created, character_id)
           VALUES (?,?,?,?,?,1,?,?)""",
        "album", album, "xxx", "front", anchor, time.time(), None)
    appmod.h_reroll({
        "song_id": sid, "tier": "xxx", "clip_indices": [0], "refine": False,
    }, lambda m: None)
    assert seen, "score_candidate never ran"
    path, bases, _prompt = seen[0]
    assert path == sheet
    assert bases == [anchor], f"reroll scored vs {bases!r}, not chosen anchor"
    assert sheet not in bases


def test_h_reroll_lands_each_still_before_reroll_returns(monkeypatch, tmp_path):
    """1 of 4 done is in refs while the other three are still rendering."""
    sheet1 = _png(str(tmp_path / "reroll1.png"))
    sheet2 = _png(str(tmp_path / "reroll2.png"))
    anchor = _png(str(tmp_path / "anchor.png"))
    mid = []

    def fake_reroll(*a, **k):
        on_still = k.get("on_still")
        first = {"clip_idx": 0, "path": sheet1, "seed": 8000}
        if on_still:
            on_still(first)
            mid.append(db.one("SELECT * FROM refs WHERE path=?", sheet1))
        return [first, {"clip_idx": 0, "path": sheet2, "seed": 9000}]

    monkeypatch.setattr(appmod.vision, "score_candidate", _score)
    monkeypatch.setattr(appmod.pipeline, "install_input",
                        lambda p, name=None: os.path.basename(p))
    monkeypatch.setattr(appmod.pipeline, "reroll", fake_reroll)
    album = f"QC Reroll Mid {time.time_ns()}"
    sid = db.run(
        "INSERT INTO songs (title, album, slug, created) VALUES (?,?,?,?)",
        "QC Reroll Mid", album, f"qc-reroll-mid-{time.time_ns()}", time.time())
    db.run("INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created) "
           "VALUES (?,?,?,?,?,?)", sid, "xxx", "/sb.json", "/sb.md", 1, time.time())
    db.run(
        """INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen,
                                created, character_id)
           VALUES (?,?,?,?,?,1,?,?)""",
        "album", album, "xxx", "front", anchor, time.time(), None)
    appmod.h_reroll({
        "song_id": sid, "tier": "xxx", "clip_indices": [0], "refine": False,
    }, lambda m: None)
    assert mid and mid[0], "first still was not in refs before reroll returned"
    assert mid[0]["path"] == sheet1
    assert mid[0]["origin"] == "reroll"
    assert db.one("SELECT * FROM refs WHERE path=?", sheet2)


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


def test_h_fix_ref_scores_vs_chosen_anchor(monkeypatch, tmp_path):
    """fix_ref dest is scored vs the chosen anchor, not the broken source."""
    src = _png(str(tmp_path / "broken.png"))
    out = _png(str(tmp_path / "fixed.png"))
    anchor = _png(str(tmp_path / "chosen_anchor.png"))
    seen = []

    def fake_score(path, bases, prompt="", progress=None):
        seen.append((path, list(bases or []), prompt))
        return {"confidence": 61, "identity": 70, "prompt": 55,
                "notes": "scored", "backend": "stub"}

    monkeypatch.setattr(appmod.vision, "score_candidate", fake_score)
    monkeypatch.setattr(appmod.pipeline, "fix_ref",
                        lambda *a, **k: [{"clip_idx": 0, "path": out, "seed": 3}])
    album = f"QC Fix Score {time.time_ns()}"
    sid = db.run(
        "INSERT INTO songs (title, album, slug, created) VALUES (?,?,?,?)",
        "QC Fix Score", album, f"qc-fix-score-{time.time_ns()}", time.time())
    db.run(
        """INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen,
                                created, character_id)
           VALUES (?,?,?,?,?,1,?,?)""",
        "album", album, "xxx", "front", anchor, time.time(), None)
    appmod.h_fix_ref({
        "song_id": sid, "tier": "xxx", "clip_idx": 0, "mode": "face",
        "image_path": src, "seed": 3, "refine": False,
    }, lambda m: None)
    row = db.one("SELECT * FROM refs WHERE path=?", out)
    assert row and row["qc_json"]
    assert seen, "score_candidate never ran"
    path, bases, _prompt = seen[0]
    assert path == out
    assert bases == [anchor], f"fix_ref scored vs {bases!r}, not chosen anchor"
    assert src not in bases


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
