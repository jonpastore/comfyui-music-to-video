"""Refs identity: image1 is the chosen sheet, not a standing 4748 plate.

docs/TRD-2: h_refs / pipeline.gen_refs / build_refs.workflow condition on the
operator's chosen anchors row as image1 (identity lock). A standing plate
(seed 4748, pose plate, base photograph) must not take that slot — plate pose
wins if it is image1, and the chosen sheet is then ignored.

Mutation: pass standing_s4748_plate as --anchor → image1 arm red.
Mutation: swap LoadImage to the plate → image1 arm red.
Mutation: enqueue with plate path while a chosen sheet exists → enqueue arm red.
Mutation: score bases against the plate → score arm red.
"""
import json
import os
import struct
import subprocess
import time
import zlib

from fastapi.testclient import TestClient

from conftest import _accept_pose_map
from conftest import _real_module

import app as appmod
import build_refs
import db
import jobs

_real_pipeline = _real_module("pipeline")

CHOSEN = "chosen_sheet_s129080599.png"
PLATE = "standing_s4748_plate.png"


def _png(path):
    w = h = 8
    rows = b"".join(b"\x00" + bytes([20, 20, 20]) * w for _ in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    open(path, "wb").write(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b""))
    return path


def _mp3(path, seconds=5):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-t", str(seconds), "-i", "anullsrc",
         "-c:a", "libmp3lame", path],
        check=True, capture_output=True)
    return path


def test_build_refs_image1_is_anchor_not_plate():
    """build_refs.workflow: chosen sheet is LoadImage for image1; plate is image2."""
    scene = {"image_prompt": "rooftop neon", "scene_number": 1, "negative_prompt": ""}
    wf = build_refs.workflow(scene, CHOSEN, None, "empty", 1280, 720, 7000)
    assert wf["7"]["inputs"]["image"] == CHOSEN
    assert wf["11"]["inputs"]["image1"] == ["8", 0]
    assert "image2" not in wf["11"]["inputs"]
    assert PLATE not in json.dumps(wf)

    # When a base plate is intentionally supplied it takes image2, never image1.
    wf2 = build_refs.workflow(scene, CHOSEN, PLATE, "empty", 1280, 720, 7000)
    assert wf2["7"]["inputs"]["image"] == CHOSEN
    assert wf2["9"]["inputs"]["image"] == PLATE
    assert wf2["11"]["inputs"]["image1"] == ["8", 0]
    assert wf2["11"]["inputs"]["image2"] == ["10", 0]


def test_gen_refs_writes_chosen_sheet_as_image1(monkeypatch, tmp_path):
    """pipeline.gen_refs → real build_refs.py: every clip graph loads the chosen
    sheet on node 7 / image1. A standing plate name never appears."""
    written = []

    def fake_submit(wf_dir, progress=None):
        for f in sorted(os.listdir(wf_dir)):
            if f.endswith(".json") and not f.endswith(".expect.json"):
                written.append(json.load(open(os.path.join(wf_dir, f))))
        return []

    monkeypatch.setattr(_real_pipeline, "submit_dir", fake_submit)
    sb = {
        "scenes": [{
            "scene_number": 1, "name": "s1", "image_prompt": "a cat on a rooftop",
            "negative_prompt": "", "duration_guidance": "5 sec", "characters": [],
        }],
        "character_reference": "black feline woman",
        "album_world_reference": "neon alley",
    }
    sb_path = str(tmp_path / "sb.json")
    json.dump(sb, open(sb_path, "w"))
    mp3 = _mp3(str(tmp_path / "s.mp3"))
    _real_pipeline.gen_refs("demo", "r", sb_path, CHOSEN, mp3, limit=1)
    assert written, "gen_refs wrote no workflow JSONs"
    for wf in written:
        assert wf["7"]["inputs"]["image"] == CHOSEN, wf["7"]
        assert wf["11"]["inputs"]["image1"] == ["8", 0]
        blob = json.dumps(wf)
        assert PLATE not in blob
        assert "4748" not in blob


def test_h_refs_and_start_refs_use_chosen_sheet_not_plate(monkeypatch, tmp_path):
    """POST /songs/{id}/refs freezes the chosen anchors path; h_refs stages that
    path and hands it to gen_refs; score bases are the chosen sheet. A standing
    plate asset on the album must not become image1 or the score base."""
    chosen_path = _png(str(tmp_path / CHOSEN))
    plate_path = _png(str(tmp_path / PLATE))
    seen = []
    score_bases = []

    def _gen_refs(slug, tier, sb, anchor, mp3, progress=None, limit=None,
                  guard="", body="", cast=None, bases=None, anchors=None):
        seen.append({"anchor": anchor, "slug": slug, "tier": tier})
        out = str(tmp_path / "ref_out.png")
        _png(out)
        return [{"clip_idx": 0, "path": out, "seed": 7000}]

    monkeypatch.setattr(appmod.pipeline, "gen_refs", _gen_refs)
    monkeypatch.setattr(appmod.pipeline, "install_input",
                        lambda p, name=None: os.path.basename(p))
    monkeypatch.setattr(appmod.vision, "score_candidate",
                        lambda path, bases, prompt="", progress=None: (
                            score_bases.append(list(bases)) or
                            {"confidence": 80, "identity": 80, "prompt": 70,
                             "notes": "", "backend": "local"}))

    with TestClient(appmod.app) as client:
        album = f"Refs Identity {time.time_ns()}"
        db.run(
            """INSERT INTO assets (song_id, kind, path, meta_json, created)
               VALUES (NULL, 'anchor_ref', ?, ?, ?)""",
            plate_path,
            json.dumps({"album": album, "role": "pose", "name": "standing 4748"}),
            time.time())
        client.post("/playlists", data={"name": album})
        mp3_bytes = open(_mp3(str(tmp_path / "song.mp3")), "rb").read()
        client.post(
            "/songs",
            data={"title": "Refs Identity Song", "album": album},
            files={"mp3": ("song.mp3", mp3_bytes, "audio/mpeg")})
        song = db.one("SELECT * FROM songs WHERE title=?", "Refs Identity Song")
        sid = song["id"]
        client.post(f"/songs/{sid}/storyboard", data={"tier": "r"})
        jid = db.one(
            "SELECT id FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC",
            sid)["id"]
        deadline = time.time() + 10
        while time.time() < deadline:
            row = jobs.get(jid)
            if row["status"] in ("done", "failed", "cancelled"):
                break
            time.sleep(0.05)
        assert jobs.get(jid)["status"] == "done", jobs.get(jid)

        db.run(
            """INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen, created)
               VALUES ('album', ?, 'r', 'front', ?, 1, ?)""",
            album, chosen_path, time.time())
        db.run(
            """INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen, created)
               VALUES ('album', ?, 'r', 'front', ?, 0, ?)""",
            album, plate_path, time.time())
        _accept_pose_map(sid, "r", path=chosen_path)

        before = len(jobs.recent(1000))
        r = client.post(f"/songs/{sid}/refs", data={"tier": "r", "limit": "1"})
        assert r.status_code in (200, 303), r.text
        assert len(jobs.recent(1000)) == before + 1
        job = db.one(
            "SELECT * FROM jobs WHERE song_id=? AND kind='refs' ORDER BY id DESC", sid)
        args = json.loads(job["args_json"])
        assert args["anchor_path"] == chosen_path, args
        assert args["anchor_path"] != plate_path
        assert PLATE not in args["anchor_path"]

        appmod.h_refs(args, lambda m: None)
        mine = [s for s in seen if s.get("slug") == song["slug"]]
        assert mine, f"h_refs never called gen_refs for this song: {seen}"
        assert mine[-1]["anchor"] == CHOSEN, mine
        assert mine[-1]["anchor"] != PLATE
        assert score_bases and score_bases[-1] == [chosen_path], score_bases
        assert plate_path not in (score_bases[-1] or [])
