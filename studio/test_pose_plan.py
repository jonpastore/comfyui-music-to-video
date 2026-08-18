"""Scene pose → chosen sheet → refs image2.

image1 stays the identity front. A bound pose sheet takes image2.
"""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import pose_plan
from test_app import _png_bytes, _upload_song, wait_job


def test_pose_plan_imports_nothing_from_fastapi():
    import ast
    src = ast.parse(open(pose_plan.__file__).read())
    mods = []
    for node in src.body:
        if isinstance(node, ast.Import):
            mods.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module.split(".")[0])
    assert "fastapi" not in mods


def _sheet(album, tier, view, path, pose_name, nude=False):
    aid = db.run(
        "INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
        None, "anchor_ref", path,
        json.dumps({"scope_value": album, "pose_name": pose_name, "role": "pose",
                    "pose_nude": nude}), time.time())
    view_key = view if view == "front" else appmod.pose_view_key(aid, nude)
    rid = db.run(
        """INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created,render_json)
           VALUES ('album',?,?,?,?,1,?,?)""",
        album, tier, view_key, path, time.time(),
        json.dumps({"source": "upload", "asset_id": aid, "pose_name": pose_name}))
    return db.one("SELECT * FROM anchors WHERE id=?", rid)


def _board(tmp, scenes):
    path = os.path.join(tmp, "sb.json")
    json.dump({"title": "T", "album": "A", "version": "xxx", "scenes": scenes},
              open(path, "w"))
    return path


def test_match_prefers_all_fours_over_standing():
    standing = {"id": 1, "view": "front", "render_json": json.dumps({"pose_name": "standing"}),
                "path": "stand.jpg"}
    fours = {"id": 2, "view": "pose_9_nude", "render_json": json.dumps({"pose_name": "all fours look back"}),
             "path": "af.jpg"}
    sheet, score = pose_plan.match_sheet(
        "on hands and knees in the doorway, looking back",
        [standing, fours], prefer_nude=True)
    assert sheet["id"] == 2, (sheet, score)
    assert score >= pose_plan._MIN_SCORE


def test_match_cowgirl_not_standing():
    standing = {"id": 1, "view": "pose_1", "render_json": json.dumps({"pose_name": "standing"}),
                "path": "s.jpg"}
    cow = {"id": 2, "view": "pose_2_nude", "render_json": json.dumps({"pose_name": "cowgirl"}),
           "path": "c.jpg"}
    sheet, _ = pose_plan.match_sheet(
        "Sitting on a partner, facing the camera, riding",
        [standing, cow], prefer_nude=True)
    assert sheet["id"] == 2


def test_saved_bind_wins_over_auto():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Bind Win Song", album="Bind Win Album")
        dest = os.path.join(db.DATA, "pose-plan")
        os.makedirs(dest, exist_ok=True)
        stand = os.path.join(dest, "stand.png")
        kneel = os.path.join(dest, "kneel.png")
        open(stand, "wb").write(_png_bytes())
        open(kneel, "wb").write(_png_bytes())
        a_stand = _sheet(song["album"], "xxx", "pose_x", stand, "standing")
        a_kneel = _sheet(song["album"], "xxx", "pose_y", kneel, "kneeling look back", nude=True)
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        jp = os.path.join(outdir, f"{song['slug']}_xxx.json")
        json.dump({
            "title": "T", "album": song["album"], "version": "xxx",
            "scenes": [{
                "scene_number": 1, "name": "One", "image_prompt": "a wet alley",
                "camera": "medium", "pose": "on all fours, looking back",
                "pose_sheet_id": a_stand["id"],
                "duration_guidance": "5s",
            }],
        }, open(jp, "w"))
        open(os.path.join(outdir, f"{song['slug']}_xxx.md"), "w").write("# sb\n")
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""",
               song["id"], "xxx", jp, os.path.join(outdir, f"{song['slug']}_xxx.md"),
               1, time.time())
        p = pose_plan.plan(song, "xxx")
        assert p["scenes"][0]["sheet_id"] == a_stand["id"]
        assert p["scenes"][0]["source"] == "saved"
        assert a_kneel["id"] != a_stand["id"]


def test_auto_bind_all_fours_scene():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Auto Bind Song", album="Auto Bind Album")
        dest = os.path.join(db.DATA, "pose-plan")
        os.makedirs(dest, exist_ok=True)
        stand = os.path.join(dest, "stand2.png")
        fours = os.path.join(dest, "fours.png")
        open(stand, "wb").write(_png_bytes())
        open(fours, "wb").write(_png_bytes())
        _sheet(song["album"], "xxx", "front", stand, "standing")
        a_fours = _sheet(song["album"], "xxx", "pose_z", fours, "all fours look back", nude=True)
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        jp = os.path.join(outdir, f"{song['slug']}_xxx.json")
        json.dump({
            "title": "T", "album": song["album"], "version": "xxx",
            "scenes": [{
                "scene_number": 1, "name": "Doggy",
                "image_prompt": "On hands and knees, looking back",
                "camera": "three-quarter rear",
                "pose": "on all fours, looking back, tail up",
                "duration_guidance": "5s",
            }],
        }, open(jp, "w"))
        open(os.path.join(outdir, f"{song['slug']}_xxx.md"), "w").write("# sb\n")
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""",
               song["id"], "xxx", jp, os.path.join(outdir, f"{song['slug']}_xxx.md"),
               1, time.time())
        p = pose_plan.plan(song, "xxx")
        assert p["scenes"][0]["sheet_id"] == a_fours["id"]
        assert p["scenes"][0]["source"] == "auto"
        assert p["n_bound"] == 1
        api = client.get(f"/api/songs/{song['id']}/pose-plan/xxx")
        assert api.status_code == 200, api.text
        assert api.json()["scenes"][0]["sheet_id"] == a_fours["id"]


def test_build_refs_bases_file_sets_image2(tmp_path):
    sb = {
        "scenes": [
            {"scene_number": 1, "name": "s1", "image_prompt": "alley",
             "negative_prompt": "", "duration_guidance": "5 sec", "characters": []},
            {"scene_number": 2, "name": "s2", "image_prompt": "doorway",
             "negative_prompt": "", "duration_guidance": "5 sec", "characters": []},
        ],
        "character_reference": "black feline woman",
        "album_world_reference": "neon",
        "version": "xxx",
    }
    sb_path = tmp_path / "sb.json"
    json.dump(sb, open(sb_path, "w"))
    bases = tmp_path / "bases.json"
    json.dump({"1": "allfours_plate.png"}, open(bases, "w"))
    out = tmp_path / "wf"
    out.mkdir()
    import subprocess, sys
    subprocess.check_call([
        sys.executable, os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                     "build_refs.py"),
        "--storyboard", str(sb_path), "--slug", "demo",
        "--anchor", "identity_front.png", "--bases", str(bases),
        "--outdir", str(out),
    ])
    wf1 = json.load(open(out / "scene_01.json"))
    wf2 = json.load(open(out / "scene_02.json"))
    assert wf1["7"]["inputs"]["image"] == "identity_front.png"
    assert wf1["11"]["inputs"]["image1"] == ["8", 0]
    assert wf1["9"]["inputs"]["image"] == "allfours_plate.png"
    assert wf1["11"]["inputs"]["image2"] == ["10", 0]
    assert "image2" not in wf2["11"]["inputs"]
    assert "9" not in wf2


def test_start_refs_freezes_pose_bases(monkeypatch):
    seen = []

    def _gen_refs(slug, tier, sb, anchor, mp3, progress=None, limit=None,
                  guard="", body="", cast=None, bases=None):
        seen.append({"anchor": anchor, "bases": bases})
        return []

    monkeypatch.setattr(appmod.pipeline, "gen_refs", _gen_refs)
    monkeypatch.setattr(appmod.pipeline, "install_input",
                        lambda p, name=None: os.path.basename(p))
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Freeze Pose Song", album="Freeze Pose Album")
        dest = os.path.join(db.DATA, "pose-plan")
        os.makedirs(dest, exist_ok=True)
        front = os.path.join(dest, "front-id.png")
        plate = os.path.join(dest, "plate-af.png")
        open(front, "wb").write(_png_bytes())
        open(plate, "wb").write(_png_bytes())
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,'xxx','front',?,1,?)""",
               song["album"], front, time.time())
        a_plate = _sheet(song["album"], "xxx", "pose_q", plate, "all fours", nude=True)
        client.post(f"/songs/{song['id']}/storyboard", data={"tier": "xxx"})
        job = db.one("SELECT id FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC",
                     song["id"])
        wait_job(job["id"])
        sb_row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier='xxx'", song["id"])
        sb = json.load(open(sb_row["json_path"]))
        sb["scenes"][0]["pose"] = "on all fours, looking back"
        json.dump(sb, open(sb_row["json_path"], "w"))
        r = client.post(f"/songs/{song['id']}/refs", data={"tier": "xxx"},
                        follow_redirects=False)
        assert r.status_code == 303, r.text
        job = db.one("SELECT * FROM jobs WHERE song_id=? AND kind='refs' ORDER BY id DESC",
                     song["id"])
        args = json.loads(job["args_json"])
        assert args["anchor_path"] == front
        assert args["pose_bases"], args
        assert a_plate["path"] in args["pose_bases"].values()
        page = client.get(f"/songs/{song['id']}").text
        assert "pose plan" in page.lower()
        assert "pose-plan" in page


def test_album_coverage_rolls_up_songs_and_clear_unsets_keeper():
    with TestClient(appmod.app) as client:
        album = "Coverage Album"
        client.post("/playlists", data={"name": album})
        song = _upload_song(client, "Coverage Song", album=album)
        dest = os.path.join(db.DATA, "pose-plan")
        os.makedirs(dest, exist_ok=True)
        plate = os.path.join(dest, "cov-af.png")
        open(plate, "wb").write(_png_bytes())
        a = _sheet(album, "xxx", "pose_cov", plate, "all fours", nude=True)
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        jp = os.path.join(outdir, f"{song['slug']}_xxx.json")
        json.dump({
            "title": "T", "album": album, "version": "xxx",
            "character_reference": "her",
            "scenes": [{
                "scene_number": 1, "name": "One", "image_prompt": "doorway",
                "camera": "rear", "pose": "on all fours, looking back",
                "duration_guidance": "5s",
            }],
        }, open(jp, "w"))
        open(os.path.join(outdir, f"{song['slug']}_xxx.md"), "w").write("# sb\n")
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""",
               song["id"], "xxx", jp, os.path.join(outdir, f"{song['slug']}_xxx.md"),
               1, time.time())
        cov = client.get(f"/api/albums/{album}/pose-coverage/xxx")
        assert cov.status_code == 200, cov.text
        body = cov.json()
        assert body["n_needed"] >= 1
        assert body["n_have"] >= 1
        page = client.get(f"/anchors?scope_value={album}").text
        assert "album-pose-roster" in page
        assert "pose-sheet-row" in page
        css = open(os.path.join(os.path.dirname(__file__), "static", "style.css")).read()
        assert ".pose-sheet-row" in css
        assert "flex-flow: row nowrap" in css
        assert "pose-keeper-form" in page
        assert "pose-roster-open" in page
        assert "Save this assignment" in page
        assert "js-pose-brief" in page or "missing" in page
        assert "pick a sheet or generate a prompt" not in page
        assert "Missing:" not in page
        assert "pose-ph" in page or "pose-roster-open" in page
        css = open(os.path.join(os.path.dirname(__file__), "static", "style.css")).read()
        assert ".pose-roster" in css and "overflow-y: auto" in css
        assert "Use as this pose" in page
        assert "Use as reference" not in page
        assert "Catatonic" not in page
        cleared = client.post(f"/anchors/{a['id']}/clear", follow_redirects=False)
        assert cleared.status_code == 303
        assert db.one("SELECT chosen FROM anchors WHERE id=?", a["id"])["chosen"] == 0
        cov2 = pose_plan.album_coverage(album, "xxx")
        key = cov2["needed"][0]["key"]
        setk = client.post("/anchors/keeper", data={
            "album": album, "tier": "xxx", "key": key, "sheet_id": str(a["id"]),
        }, follow_redirects=False)
        assert setk.status_code == 303, setk.text
        assert db.one("SELECT chosen FROM anchors WHERE id=?", a["id"])["chosen"] == 1
        sb = json.load(open(jp))
        assert sb["scenes"][0].get("pose_sheet_id") == a["id"]
        assert cov2["needed"][0]["character_label"]
        assert "pose-who" in page


def test_album_coverage_splits_the_same_pose_by_character():
    """Tiger crouching is not the album lead crouching."""
    with TestClient(appmod.app) as client:
        album = f"Who Pose {time.time_ns()}"
        client.post("/playlists", data={"name": album})
        pl = db.one("SELECT id FROM playlists WHERE name=?", album)["id"]
        db.run("UPDATE playlists SET style_text=? WHERE id=?",
               "Meow P — alley nights", pl)
        client.post(f"/playlists/{pl}/characters",
                    data={"name": "Tiger", "role": "partner"})
        tiger = db.one("SELECT * FROM characters WHERE scope_value=? AND name=?",
                       album, "Tiger")
        song = _upload_song(client, "Who Pose Song", album=album)
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        jp = os.path.join(outdir, f"{song['slug']}_xxx.json")
        json.dump({
            "title": "T", "album": album, "version": "xxx",
            "character_reference": "Meow P",
            "scenes": [
                {"scene_number": 1, "name": "Her", "pose": "crouching",
                 "image_prompt": "crouch", "characters": [],
                 "duration_guidance": "4s"},
                {"scene_number": 2, "name": "Him", "pose": "crouching",
                 "image_prompt": "crouch",
                 "characters": [{"name": "Tiger", "role": "lead"}],
                 "duration_guidance": "4s"},
            ],
        }, open(jp, "w"))
        open(os.path.join(outdir, f"{song['slug']}_xxx.md"), "w").write("# sb\n")
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""",
               song["id"], "xxx", jp, os.path.join(outdir, f"{song['slug']}_xxx.md"),
               2, time.time())
        cov = pose_plan.album_coverage(album, "xxx")
        labels = {g["character_label"] for g in cov["needed"]}
        assert "Meow P" in labels, labels
        assert "Tiger" in labels, labels
        assert len(cov["needed"]) == 2
        assert len(cov["people"]) == 2
        page = client.get(f"/anchors?scope_value={album}").text
        assert "Meow P" in page
        assert "Tiger" in page
        assert "pose-who-tab" in page
        assert tiger["id"]


def test_bind_route_overrides_auto():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Override Pose Song", album="Override Pose Album")
        dest = os.path.join(db.DATA, "pose-plan")
        os.makedirs(dest, exist_ok=True)
        a = os.path.join(dest, "a.png")
        b = os.path.join(dest, "b.png")
        open(a, "wb").write(_png_bytes())
        open(b, "wb").write(_png_bytes())
        s1 = _sheet(song["album"], "r", "pose_a", a, "standing")
        s2 = _sheet(song["album"], "r", "pose_b", b, "kneeling")
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        jp = os.path.join(outdir, f"{song['slug']}_r.json")
        json.dump({
            "title": "T", "album": song["album"], "version": "r",
            "character_reference": "her",
            "scenes": [{
                "scene_number": 1, "name": "One", "image_prompt": "alley",
                "camera": "wide", "pose": "standing in the rain",
                "duration_guidance": "5s",
                "cue": "x", "story": "s", "motion": "m", "lighting": "l",
                "video_motion_prompt": "v", "negative_prompt": "",
            }],
        }, open(jp, "w"))
        open(os.path.join(outdir, f"{song['slug']}_r.md"), "w").write("# sb\n")
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""",
               song["id"], "r", jp, os.path.join(outdir, f"{song['slug']}_r.md"),
               1, time.time())
        r = client.post(
            f"/songs/{song['id']}/storyboard/r/scene/1/pose-sheet",
            data={"sheet_id": str(s2["id"])}, follow_redirects=False)
        assert r.status_code == 303, r.text
        sb = json.load(open(jp))
        assert sb["scenes"][0]["pose_sheet_id"] == s2["id"]
        p = pose_plan.plan(song, "r")
        assert p["scenes"][0]["sheet_id"] == s2["id"]
        assert p["scenes"][0]["source"] == "saved"
        assert s1["id"] != s2["id"]


def test_bind_route_json_reports_source():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Json Bind Song", album="Json Bind Album")
        dest = os.path.join(db.DATA, "pose-plan")
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, "json-bind.png")
        open(path, "wb").write(_png_bytes())
        sheet = _sheet(song["album"], "r", "pose_stand", path, "standing")
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        jp = os.path.join(outdir, f"{song['slug']}_r.json")
        json.dump({
            "title": "T", "album": song["album"], "version": "r",
            "character_reference": "her",
            "scenes": [{
                "scene_number": 1, "name": "One", "image_prompt": "alley",
                "camera": "wide", "pose": "standing",
                "duration_guidance": "5s",
                "cue": "x", "story": "s", "motion": "m", "lighting": "l",
                "video_motion_prompt": "v", "negative_prompt": "",
            }],
        }, open(jp, "w"))
        open(os.path.join(outdir, f"{song['slug']}_r.md"), "w").write("# sb\n")
        db.run("""INSERT INTO storyboards (song_id,tier,json_path,md_path,scene_count,created)
                  VALUES (?,?,?,?,?,?)""",
               song["id"], "r", jp, os.path.join(outdir, f"{song['slug']}_r.md"),
               1, time.time())
        r = client.post(
            f"/songs/{song['id']}/storyboard/r/scene/1/pose-sheet",
            data={"sheet_id": str(sheet["id"])},
            headers={"Accept": "application/json"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["source"] == "saved"
        assert body["sheet_id"] == sheet["id"]
        assert body["url"]
        page = client.get(f"/songs/{song['id']}/storyboard/r").text
        assert "saved bind" not in page
        assert "Use this plate" not in page
        assert "Save this plate for the scene" in page
        assert "help-tip" in page
        assert "data-help=" in page
        assert "Pinned" in page
        assert "Save scene 1" in page
        assert "Save plate" in page
        assert "Save scene" in page
        assert "icon-btn" in page
        assert "scene-preview" in page
        assert "Reference stills" in page
        assert "Pose plate" in page
        assert ">Clips<" in page or ">Clips</h4>" in page
        assert "First clip only" in page
        assert "What First clip only means" in page
        assert 'class="clip-bar"' in page
        assert 'class="clips-head"' in page
        assert "When does S2V happen?" in page
        assert "WAN S2V is a later hop" not in page or "data-help=" in page
        assert ">Reroll<" in page
        assert "What to change" in page
        assert 'class="reroll-form reroll-bar"' in page
        assert "js-ref-preview thumb-open" in page
        assert 'name="seed_min"' in page
        assert "lazy-src" in page
        assert "data-src=" in page
        assert "pose-row" in page
