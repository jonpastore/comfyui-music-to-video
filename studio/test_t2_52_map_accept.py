"""T2-52: Accept is required per scene, same shape as T2-15.

docs/TRD-2 §6b: rejecting a draft leaves the previous accepted binding
(or none). Accepting persists status=accepted. Generate refs reads only
accepted bindings; start_refs from an empty map, draft, or rejected row
writes no still.

Mutation: generate refs from a draft row → red.
Mutation: generate refs with an empty map → red.
Mutation: reject overwrites the previous accepted keeper → red.
Mutation: accept does not persist → accept arm red.
"""
import json
import os
import tempfile
import time

from fastapi.testclient import TestClient

import app as appmod
import classification
import db
import scene_pose_map
import tiers


def _scene(n, pose, camera="medium"):
    return {
        "scene_number": n,
        "name": f"Scene {n}",
        "cue": "Verse",
        "duration_guidance": "8 sec",
        "story": f"{pose} in the alley",
        "camera": camera,
        "motion": "hold",
        "lighting": "neon",
        "location": f"loc {n}",
        "pose": pose,
        "wardrobe": "clothed",
        "image_prompt": f"Meow P {pose} in a neon alley",
        "video_motion_prompt": f"motion {n}",
        "negative_prompt": "",
        "characters": [],
    }


def _write_board(sid, slug, tier, scenes, album):
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    sb = {
        "title": "T",
        "album": album,
        "version": tier,
        "character_reference": "a sleek black feline DJ",
        "scenes": scenes,
    }
    json_path = os.path.join(outdir, f"{slug}_{tier}.json")
    md_path = os.path.join(outdir, f"{slug}_{tier}.md")
    json.dump(sb, open(json_path, "w"))
    open(md_path, "w").write("# storyboard\n")
    db.run(
        """INSERT INTO storyboards
           (song_id, tier, json_path, md_path, scene_count, created, scene_seconds)
           VALUES (?,?,?,?,?,?,?)""",
        sid, tier, json_path, md_path, len(scenes), time.time(), 8.0)
    return json_path


def _png(name):
    path = os.path.join(tempfile.mkdtemp(prefix="t252_"), f"{name}.png")
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n")
    return path


def _image(iid, path, **over):
    row = {
        "id": iid,
        "path": path,
        "kind": "operator",
        "view": "front",
        "pose": "kneel",
        "wardrobe": "clothed",
        "usable": "pose",
    }
    row.update(over)
    return row


def _map(sid, tier="r"):
    return list(db.q(
        "SELECT * FROM scene_pose_map WHERE song_id=? AND tier=?", sid, tier))


def _refs_n(sid):
    return db.one("SELECT COUNT(*) AS n FROM refs WHERE song_id=?", sid)["n"]


def _refs_jobs(sid):
    return list(db.q(
        "SELECT * FROM jobs WHERE song_id=? AND kind='refs'", sid))


def _front(album, tier="r"):
    path = _png("front")
    db.run(
        """INSERT INTO anchors (scope_kind, scope_value, tier, view, path,
                               chosen, created, character_id)
           VALUES ('album',?,?,?,?,?,?,NULL)""",
        album, tier, "front", path, 1, time.time())
    return path


def test_t2_52_accept_persists_reject_restores_refs_refuse_draft(monkeypatch, tmp_path):
    tiers.ensure_builtins()
    stamp = f"t252-{time.time_ns()}"
    album = f"T252 {stamp}"
    sid = db.upsert_song(
        stamp, title="T2-52 Map Song", album=album, duration=8.0)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    _write_board(sid, song["slug"], "r", [
        _scene(1, "kneeling", "medium"),
    ], album)
    keeper_a = _png("kneel-a")
    keeper_b = _png("kneel-b")
    classification.save(album, {"images": [
        _image("kneel-a", keeper_a),
    ]})
    _front(album, "r")

    still_out = str(tmp_path / "ref_out.png")

    def _gen_refs(slug, tier, sb, anchor, mp3, progress=None, limit=None,
                  guard="", body="", cast=None, bases=None, anchors=None):
        open(still_out, "wb").write(b"\x89PNG\r\n\x1a\n")
        return [{"clip_idx": 0, "path": still_out, "seed": 7000}]

    monkeypatch.setattr(appmod.pipeline, "gen_refs", _gen_refs)
    monkeypatch.setattr(appmod.pipeline, "install_input",
                        lambda p, name=None: os.path.basename(p))
    monkeypatch.setattr(
        appmod, "refine_generated_still",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no refine")))
    monkeypatch.setattr(
        appmod.vision, "score_candidate",
        lambda path, bases, prompt="", progress=None: {
            "confidence": 80, "identity": 80, "prompt": 70,
            "notes": "", "backend": "local"})

    with TestClient(appmod.app) as client:
        drafted = client.post(f"/api/songs/{sid}/storyboard/r/pose-map")
        assert drafted.status_code == 200, drafted.text
        body = drafted.json()
        assert body["n_draft"] == 1, body
        assert body["scenes"][0]["keeper_id"] == "kneel-a", body
        assert body["scenes"][0]["status"] == "draft", body

        before_jobs = _refs_jobs(sid)
        before_refs = _refs_n(sid)
        refused = client.post(f"/songs/{sid}/refs", data={"tier": "r"})
        assert refused.status_code == 400, refused.text
        assert "draft" in refused.text.lower() or "Accept" in refused.text
        assert _refs_jobs(sid) == before_jobs
        assert _refs_n(sid) == before_refs

        accepted = client.post(
            f"/api/songs/{sid}/storyboard/r/scene/1/pose-map/accept")
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "accepted", accepted.json()
        stored = _map(sid, "r")
        assert len(stored) == 1 and stored[0]["status"] == "accepted"
        assert stored[0]["keeper_id"] == "kneel-a"

        landed = client.post(
            f"/songs/{sid}/refs", data={"tier": "r"}, follow_redirects=False)
        assert landed.status_code in (200, 303), landed.text
        jobs = _refs_jobs(sid)
        assert len(jobs) == 1, jobs
        args = json.loads(jobs[0]["args_json"])
        assert keeper_a in (args.get("anchors") or {}).values(), args
        assert keeper_a not in (args.get("pose_bases") or {}).values(), args

        appmod.h_refs(args, lambda m: None)
        assert _refs_n(sid) == 1
        ref = db.one("SELECT * FROM refs WHERE song_id=?", sid)
        assert ref["path"] == still_out, dict(ref)
        assert os.path.isfile(still_out)

        classification.save(album, {"images": [
            _image("kneel-b", keeper_b),
        ]})
        redrafted = client.post(f"/api/songs/{sid}/storyboard/r/pose-map")
        assert redrafted.status_code == 200, redrafted.text
        draft_row = redrafted.json()["scenes"][0]
        assert draft_row["status"] == "draft", draft_row
        assert draft_row["keeper_id"] == "kneel-b", draft_row

        rejected = client.post(
            f"/api/songs/{sid}/storyboard/r/scene/1/pose-map/reject")
        assert rejected.status_code == 200, rejected.text
        restored = rejected.json()
        assert restored["status"] == "accepted", restored
        assert restored["keeper_id"] == "kneel-a", restored
        disk = _map(sid, "r")[0]
        assert disk["status"] == "accepted"
        assert disk["keeper_id"] == "kneel-a"
        assert disk["path"] == keeper_a

        classification.save(album, {"images": [
            _image("kneel-b", keeper_b),
        ]})
        client.post(f"/api/songs/{sid}/storyboard/r/pose-map")
        client.post(f"/api/songs/{sid}/storyboard/r/scene/1/pose-map/reject")
        # After reject of a draft that replaced A, A stays. Draft again B
        # then reject with no further accept still leaves A.
        listed = scene_pose_map.listed(sid, "r")
        assert listed["scenes"][0]["keeper_id"] == "kneel-a"
        assert listed["scenes"][0]["status"] == "accepted"


def test_t2_52_start_refs_refuses_rejected(monkeypatch):
    tiers.ensure_builtins()
    stamp = f"t252-rej-{time.time_ns()}"
    album = f"T252R {stamp}"
    sid = db.upsert_song(
        stamp, title="T2-52 Reject Song", album=album, duration=8.0)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    _write_board(sid, song["slug"], "r", [
        _scene(1, "kneeling", "medium"),
    ], album)
    classification.save(album, {"images": [
        _image("kneel-x", _png("kneel-x")),
    ]})
    _front(album, "r")

    with TestClient(appmod.app) as client:
        client.post(f"/api/songs/{sid}/storyboard/r/pose-map")
        rejected = client.post(
            f"/api/songs/{sid}/storyboard/r/scene/1/pose-map/reject")
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected", rejected.json()

        before = _refs_n(sid)
        refused = client.post(f"/songs/{sid}/refs", data={"tier": "r"})
        assert refused.status_code == 400, refused.text
        assert "rejected" in refused.text.lower() or "Accept" in refused.text
        assert _refs_n(sid) == before
        assert _refs_jobs(sid) == []


def test_t2_52_start_refs_refuses_empty_map():
    """No draft+Accept → start_refs 400s and writes no refs job."""
    tiers.ensure_builtins()
    stamp = f"t252-empty-{time.time_ns()}"
    album = f"T252E {stamp}"
    sid = db.upsert_song(
        stamp, title="T2-52 Empty Map Song", album=album, duration=8.0)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    _write_board(sid, song["slug"], "r", [
        _scene(1, "kneeling", "medium"),
    ], album)
    _front(album, "r")
    assert _map(sid, "r") == []

    with TestClient(appmod.app) as client:
        before = _refs_n(sid)
        refused = client.post(f"/songs/{sid}/refs", data={"tier": "r"})
        assert refused.status_code == 400, refused.text
        assert "empty" in refused.text.lower() or "Accept" in refused.text
        assert _refs_n(sid) == before
        assert _refs_jobs(sid) == []
        assert _map(sid, "r") == []
