"""T3-34: C1/C2 pose-gap landings are scored like an anchor.

Pose-gap generate enqueues studio `anchor` jobs (`source=pose-gap`)
with the decided pose clause as `prompt`. Each C1/C2 `h_anchor`
landing calls `score_candidate` and stores `qc_json` (confidence,
identity, prompt). Advisory, not a gate.

Mutation: skip `score_candidate` on C2 → red.
Mutation: empty enqueue prompt → red.
"""
import json
import os
import time

import app as appmod
import classification
import db
import pose_generate
import tiers


def _scene(n, pose, camera, wardrobe="clothed"):
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
        "wardrobe": wardrobe,
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


def _image(iid, **over):
    row = {
        "id": iid,
        "path": f"{iid}.jpg",
        "kind": "operator",
        "view": "front",
        "pose": "standing",
        "wardrobe": "clothed",
        "usable": "identity",
    }
    row.update(over)
    return row


def _song(stamp, album):
    sid = db.upsert_song(stamp, title=f"T3-34 {stamp}", album=album,
                         duration=24.0)
    return db.one("SELECT * FROM songs WHERE id=?", sid)


def _job_args(song_id):
    out = []
    for row in db.q("SELECT * FROM jobs WHERE song_id=? ORDER BY id", song_id):
        out.append((row, json.loads(row["args_json"] or "{}")))
    return out


def _pose_gap_c1_c2(stamp):
    """Standing-nude hole + standing clothed keeper = C1; kneeling = C2."""
    tiers.ensure_builtins()
    album = f"T334 {stamp}"
    song = _song(stamp, album)
    sid = song["id"]
    _write_board(sid, song["slug"], "r", [
        _scene(1, "standing", "wide", wardrobe="nude"),
        _scene(2, "kneeling", "medium"),
    ], album)
    classification.save(album, {"images": [
        _image("her-stand", path="her-stand.jpg", pose="standing",
               view="front", wardrobe="clothed"),
    ]})
    got = pose_generate.generate(sid, ["r"])
    return song, got, _job_args(sid)


def test_t3_34_pose_gap_enqueue_prompt_is_decided_pose_clause():
    """Pose-gap jobs carry the decided pose clause, not an empty prompt."""
    stamp = f"t334-p-{time.time_ns()}"
    _song_row, got, jobs = _pose_gap_c1_c2(stamp)
    kinds = {j["job_kind"] for j in got["jobs"]}
    assert kinds == {"c1", "c2"}, got["jobs"]
    standing = pose_generate.pose_clause("standing")
    kneeling = pose_generate.pose_clause("kneeling")
    assert standing, standing
    assert kneeling, kneeling
    by_kind = {}
    for _row, args in jobs:
        assert args.get("source") == "pose-gap", args
        prompt = args.get("prompt") or ""
        assert prompt.strip(), f"empty pose-gap enqueue prompt: {args}"
        assert prompt == args.get("pose"), args
        by_kind[args.get("job_kind")] = args
    assert by_kind["c1"]["prompt"] == standing, by_kind["c1"]
    assert by_kind["c2"]["prompt"] == kneeling, by_kind["c2"]


def test_t3_34_c1_c2_landings_call_score_candidate_and_store_qc_json(
        monkeypatch, tmp_path):
    """C1 and C2 h_anchor landings must call score_candidate.

    Mutation: skip score_candidate on C2 → red.
    """
    stamp = f"t334-l-{time.time_ns()}"
    _song_row, got, jobs = _pose_gap_c1_c2(stamp)
    kinds = {j["job_kind"] for j in got["jobs"]}
    assert "c1" in kinds and "c2" in kinds, got["jobs"]

    seen = []
    n = {"i": 0}

    def fake_score(path, bases, prompt="", progress=None):
        seen.append({"path": path, "bases": list(bases or []),
                     "prompt": prompt})
        return {"confidence": 64, "identity": 60, "prompt": 70,
                "notes": "ok", "backend": "stub"}

    def fake_gen(*_a, **k):
        n["i"] += 1
        sheet = tmp_path / f"sheet-{n['i']}.png"
        sheet.write_bytes(b"png")
        return [str(sheet)]

    monkeypatch.setattr(appmod.pipeline, "gen_anchor", fake_gen)
    monkeypatch.setattr(appmod.vision, "score_candidate", fake_score)

    landed = {}
    for _row, args in jobs:
        args = dict(args)
        args["refine"] = False
        appmod.h_anchor(args, lambda _m: None)
        kind = args.get("job_kind")
        landed[kind] = args

    assert "c1" in landed and "c2" in landed, landed
    by_prompt = {s["prompt"]: s for s in seen}
    for kind, args in landed.items():
        clause = args.get("prompt") or ""
        assert clause, f"{kind} landing had empty prompt: {args}"
        hit = by_prompt.get(clause)
        assert hit, (
            f"score_candidate never ran for {kind} "
            f"(prompt={clause!r}): {seen}")
        row = db.one("SELECT * FROM anchors WHERE path=?", hit["path"])
        assert row, f"{kind} landing was not stored"
        assert row["qc_json"], f"{kind} landed with no qc_json"
        qc = json.loads(row["qc_json"])
        assert qc.get("confidence") == 64, qc
        assert qc.get("identity") == 60, qc
        assert qc.get("prompt") == 70, qc
        assert hit["bases"] == list(args.get("images") or [])

    c2_clause = landed["c2"]["prompt"]
    assert any(s["prompt"] == c2_clause for s in seen), (
        "score_candidate skipped on C2: " + repr(seen))
