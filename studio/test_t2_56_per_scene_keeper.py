"""T2-56: gen_refs image1 is the accepted keeper for that scene.

docs/TRD-2 §6b: two accepted scenes with two keepers produce two
different image1 paths. One album front for every scene fails this.
Draft or rejected scenes still refuse generate. Keepers are identity
(image1), not also stuffed into pose_bases (image2).

Mutation: every scene's image1 is the album front → red.
Mutation: draft/rejected still generates → red.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

from fastapi.testclient import TestClient

from conftest import _real_module

import app as appmod
import classification
import db
import tiers

_real_pipeline = _real_module("pipeline")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONT = "album_front_t256.png"
KEEPER_A = "keeper_kneel_t256.png"
KEEPER_B = "keeper_stand_t256.png"


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
    path = os.path.join(tempfile.mkdtemp(prefix="t256_"), f"{name}.png")
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


def _front(album, tier="r"):
    path = _png("front")
    db.run(
        """INSERT INTO anchors (scope_kind, scope_value, tier, view, path,
                               chosen, created, character_id)
           VALUES ('album',?,?,?,?,?,?,NULL)""",
        album, tier, "front", path, 1, time.time())
    return path


def _refs_n(sid):
    return db.one("SELECT COUNT(*) AS n FROM refs WHERE song_id=?", sid)["n"]


def _refs_jobs(sid):
    return list(db.q(
        "SELECT * FROM jobs WHERE song_id=? AND kind='refs'", sid))


def _accept_map(sid, tier, num, kid, path):
    now = time.time()
    db.run(
        """INSERT INTO scene_pose_map
           (song_id, tier, scene_number, keeper_id, path, status,
            prev_keeper_id, prev_path, created, updated)
           VALUES (?,?,?,?,?,'accepted',NULL,NULL,?,?)""",
        sid, tier, num, kid, path, now, now)


def test_build_refs_anchors_file_sets_per_scene_image1(tmp_path):
    sb = {
        "scenes": [
            {"scene_number": 1, "name": "s1", "image_prompt": "kneeling",
             "negative_prompt": "", "duration_guidance": "5 sec",
             "characters": []},
            {"scene_number": 2, "name": "s2", "image_prompt": "standing",
             "negative_prompt": "", "duration_guidance": "5 sec",
             "characters": []},
        ],
        "character_reference": "black feline woman",
        "album_world_reference": "neon",
        "version": "r",
    }
    sb_path = tmp_path / "sb.json"
    json.dump(sb, open(sb_path, "w"))
    anchors = tmp_path / "anchors.json"
    json.dump({"1": KEEPER_A, "2": KEEPER_B}, open(anchors, "w"))
    out = tmp_path / "wf"
    out.mkdir()
    subprocess.check_call([
        sys.executable, os.path.join(REPO, "build_refs.py"),
        "--storyboard", str(sb_path), "--slug", "demo",
        "--anchor", FRONT, "--anchors", str(anchors),
        "--outdir", str(out),
    ])
    wf1 = json.load(open(out / "scene_01.json"))
    wf2 = json.load(open(out / "scene_02.json"))
    img1 = wf1["7"]["inputs"]["image"]
    img2 = wf2["7"]["inputs"]["image"]
    assert img1 == KEEPER_A, wf1["7"]
    assert img2 == KEEPER_B, wf2["7"]
    assert img1 != img2
    assert img1 != FRONT and img2 != FRONT
    assert wf1["11"]["inputs"]["image1"] == ["8", 0]
    assert wf2["11"]["inputs"]["image1"] == ["8", 0]
    assert "image2" not in wf1["11"]["inputs"]
    assert "image2" not in wf2["11"]["inputs"]


def test_gen_refs_anchors_write_different_image1(monkeypatch, tmp_path):
    written = []

    def fake_submit(wf_dir, progress=None):
        for f in sorted(os.listdir(wf_dir)):
            if f.endswith(".json") and not f.endswith(".expect.json"):
                written.append(json.load(open(os.path.join(wf_dir, f))))
        return []

    monkeypatch.setattr(_real_pipeline, "submit_dir", fake_submit)
    monkeypatch.setattr(_real_pipeline, "install_input",
                        lambda p, name=None: os.path.basename(p))
    sb = {
        "scenes": [
            {"scene_number": 1, "name": "s1", "image_prompt": "kneeling",
             "negative_prompt": "", "duration_guidance": "8 sec",
             "characters": []},
            {"scene_number": 2, "name": "s2", "image_prompt": "standing",
             "negative_prompt": "", "duration_guidance": "8 sec",
             "characters": []},
        ],
        "character_reference": "black feline woman",
        "album_world_reference": "neon alley",
        "version": "r",
    }
    sb_path = str(tmp_path / "sb.json")
    json.dump(sb, open(sb_path, "w"))
    mp3 = str(tmp_path / "s.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-t", "16", "-i", "anullsrc",
         "-c:a", "libmp3lame", mp3],
        check=True, capture_output=True)
    keep_a = str(tmp_path / KEEPER_A)
    keep_b = str(tmp_path / KEEPER_B)
    open(keep_a, "wb").write(b"\x89PNG\r\n\x1a\n")
    open(keep_b, "wb").write(b"\x89PNG\r\n\x1a\n")
    _real_pipeline.gen_refs(
        "demo", "r", sb_path, FRONT, mp3,
        anchors={1: keep_a, 2: keep_b})
    assert len(written) == 2, written
    images = [wf["7"]["inputs"]["image"] for wf in written]
    assert images == [KEEPER_A, KEEPER_B], images
    assert FRONT not in images
    assert images[0] != images[1]


def test_t2_56_accepted_keepers_are_per_scene_image1(monkeypatch, tmp_path):
    tiers.ensure_builtins()
    stamp = f"t256-{time.time_ns()}"
    album = f"T256 {stamp}"
    sid = db.upsert_song(
        stamp, title="T2-56 Keeper Song", album=album, duration=16.0)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    _write_board(sid, song["slug"], "r", [
        _scene(1, "kneeling", "medium"),
        _scene(2, "standing", "wide"),
    ], album)
    keeper_a = _png("kneel-a")
    keeper_b = _png("stand-b")
    classification.save(album, {"images": [
        _image("kneel-a", keeper_a, pose="kneel"),
        _image("stand-b", keeper_b, pose="stand"),
    ]})
    front = _front(album, "r")
    _accept_map(sid, "r", 1, "kneel-a", keeper_a)
    _accept_map(sid, "r", 2, "stand-b", keeper_b)

    seen = []
    still_out = str(tmp_path / "ref_out.png")

    def _gen_refs(slug, tier, sb, anchor, mp3, progress=None, limit=None,
                  guard="", body="", cast=None, bases=None, anchors=None):
        seen.append({"anchor": anchor, "bases": bases, "anchors": anchors})
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
        landed = client.post(
            f"/songs/{sid}/refs", data={"tier": "r"}, follow_redirects=False)
        assert landed.status_code in (200, 303), landed.text
        jobs = _refs_jobs(sid)
        assert len(jobs) == 1, jobs
        args = json.loads(jobs[0]["args_json"])
        identity = args.get("anchors") or {}
        plates = args.get("pose_bases") or {}
        assert set(identity.values()) == {keeper_a, keeper_b}, args
        assert keeper_a not in plates.values(), args
        assert keeper_b not in plates.values(), args
        assert args["anchor_path"] == front
        assert identity[1] != identity[2] if 1 in identity else (
            identity["1"] != identity["2"])

        appmod.h_refs(args, lambda m: None)
        assert seen, "h_refs never called gen_refs"
        handed = seen[0]["anchors"] or {}
        assert set(handed.values()) == {keeper_a, keeper_b}, seen
        assert (seen[0]["bases"] or {}) == {}
        names = list(handed.values())
        assert names[0] != names[1]
        assert front not in handed.values()


def test_t2_56_draft_and_rejected_still_refuse(monkeypatch):
    tiers.ensure_builtins()
    stamp = f"t256-bad-{time.time_ns()}"
    album = f"T256B {stamp}"
    sid = db.upsert_song(
        stamp, title="T2-56 Draft Song", album=album, duration=8.0)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    _write_board(sid, song["slug"], "r", [
        _scene(1, "kneeling", "medium"),
    ], album)
    classification.save(album, {"images": [
        _image("kneel-x", _png("kneel-x")),
    ]})
    _front(album, "r")

    with TestClient(appmod.app) as client:
        drafted = client.post(f"/api/songs/{sid}/storyboard/r/pose-map")
        assert drafted.status_code == 200, drafted.text
        assert drafted.json()["n_draft"] == 1, drafted.json()

        before = _refs_n(sid)
        refused = client.post(f"/songs/{sid}/refs", data={"tier": "r"})
        assert refused.status_code == 400, refused.text
        assert "draft" in refused.text.lower() or "Accept" in refused.text
        assert _refs_n(sid) == before
        assert _refs_jobs(sid) == []

        rejected = client.post(
            f"/api/songs/{sid}/storyboard/r/scene/1/pose-map/reject")
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected", rejected.json()
        refused2 = client.post(f"/songs/{sid}/refs", data={"tier": "r"})
        assert refused2.status_code == 400, refused2.text
        assert "rejected" in refused2.text.lower() or "Accept" in refused2.text
        assert _refs_n(sid) == before
        assert _refs_jobs(sid) == []
