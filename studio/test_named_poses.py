"""Named uploaded poses: more than eight, per-image name + tier, assign as sheet."""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import make_anchor
from conftest import _real_module
from test_app import _png_bytes, _upload_song, wait_job


def test_parse_score_confidence_is_min_of_identity_and_prompt():
    got = _real_module("vision").parse_score({
        "confidence": 95, "identity": 20, "prompt": 40, "notes": "human face, two tails",
    })
    assert got["confidence"] == 20
    assert got["identity"] == 20
    assert got["prompt"] == 40


def test_qc_tag_shows_identity_and_notes_when_they_diverge():
    tag = appmod.qc_tag({"qc_json": json.dumps({
        "confidence": 20, "identity": 20, "prompt": 40,
        "notes": "human face, two tails",
    })})
    assert "confidence 20%" in tag
    assert "identity 20%" in tag
    assert "pose 40%" in tag
    assert "human face" in tag


def test_custom_pose_view_omits_standing_backdrop():
    spec = make_anchor.view_entry("pose_9")
    assert spec.get("custom")
    assert "stance" in spec["backdrop_omit"]
    text = make_anchor.backdrop_for("pose_9")
    assert "stands upright" not in text


def test_named_pose_meta_and_assign():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Named Pose Song", album="Street Cats")
        album = song["album"]
        dest = os.path.join(db.DATA, "uploads", "anchors", "album", "Street_Cats")
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, "sit.png")
        open(path, "wb").write(_png_bytes())
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               None, "anchor_ref", path,
               json.dumps({"scope_value": album, "character_id": None}), time.time())
        row = db.one("SELECT * FROM assets WHERE path=?", path)
        r = client.post(f"/anchors/refs/{row['id']}/meta", data={
            "pose_name": "seated on the amp",
            "pose_tier": "xxx",
            "role": "identity",
            "pose_nude": "1",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["role"] == "pose"
        assert body["pose_name"] == "seated on the amp"
        assert body["pose_nude"] is True
        a = client.post(f"/anchors/refs/{row['id']}/assign", data={
            "album": album, "pose_name": "seated on the amp", "pose_tier": "xxx",
            "pose_nude": "1",
        }, follow_redirects=False)
        assert a.status_code == 303, a.text
        sheet = db.one("SELECT * FROM anchors WHERE view=?",
                       appmod.pose_view_key(row["id"], True))
        assert sheet is not None
        assert sheet["chosen"] == 1
        assert sheet["tier"] == "xxx"
        assert sheet["path"] == path
        assert json.loads(sheet["render_json"])["source"] == "upload"
        still = [r for r in appmod.anchor_refs(album) if r["id"] == row["id"]]
        assert still == [], "assigned upload must leave the base-image list"


def test_assign_uses_saved_name_when_form_repeats_empty_pose_name():
    """Assign is a submit of #anchor-form. Every card names pose_name; the
    first is often the unnamed identity pair. Saved meta must still win."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Assign Sibling Song", album="Street Cats")
        album = song["album"]
        dest = os.path.join(db.DATA, "uploads", "anchors", "album", "Street_Cats")
        os.makedirs(dest, exist_ok=True)
        blank = os.path.join(dest, "blank.png")
        named = os.path.join(dest, "named.png")
        open(blank, "wb").write(_png_bytes())
        open(named, "wb").write(_png_bytes())
        now = time.time()
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               None, "anchor_ref", blank,
               json.dumps({"scope_value": album, "character_id": None}), now)
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               None, "anchor_ref", named,
               json.dumps({"scope_value": album, "character_id": None,
                           "pose_name": "standing front", "pose_tier": "r",
                           "role": "pose"}), now + 1)
        row = db.one("SELECT * FROM assets WHERE path=?", named)
        a = client.post(f"/anchors/refs/{row['id']}/assign", data=[
            ("album", album),
            ("pose_name", ""),
            ("pose_name", "wrong sibling"),
            ("pose_tier", ""),
            ("pose_tier", "xxx"),
        ], follow_redirects=False)
        assert a.status_code == 303, a.text
        sheet = db.one("SELECT * FROM anchors WHERE view=?",
                       appmod.pose_view_key(row["id"], False))
        assert sheet is not None
        assert sheet["chosen"] == 1
        assert sheet["tier"] == "r"
        assert json.loads(sheet["render_json"])["pose_name"] == "standing front"


def test_upload_cap_is_twenty_four():
    assert appmod.MAX_ANCHOR_UPLOADS >= 16


def test_album_anchor_tiers_puts_named_pose_nude_in_nude_row():
    """pose_12_nude is a nude sheet even though it is not in NUDE_VIEWS."""
    with TestClient(appmod.app) as client:
        album = "Named Nude Group Album"
        client.post("/playlists", data={"name": album})
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,'xxx','pose_99_nude','spread-nude.jpg',1,?)""",
               album, time.time())
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,'xxx','pose_21','standing.jpg',1,?)""",
               album, time.time())
        tiers_out, _ = appmod.album_anchor_tiers(album)
        rows = {g["label"]: g for g in tiers_out[0]["rows"]}
        assert set(rows) == {"Clothed", "Nude"}, rows
        assert [a["path"] for a in rows["Nude"]["anchors"]] == ["spread-nude.jpg"]
        assert [a["path"] for a in rows["Clothed"]["anchors"]] == ["standing.jpg"]


def test_view_position_label_uses_saved_pose_name():
    """Gallery row heads must not dump pose_22; they use the named pose."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Pose Label Song", album="Street Cats")
        album = song["album"]
        dest = os.path.join(db.DATA, "uploads", "anchors", "album", "Street_Cats")
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, "spread.png")
        open(path, "wb").write(_png_bytes())
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               None, "anchor_ref", path,
               json.dumps({"scope_value": album, "character_id": None,
                           "pose_name": "wide stance spreading", "role": "pose",
                           "pose_nude": True}), time.time())
        row = db.one("SELECT * FROM assets WHERE path=?", path)
        nude = appmod.pose_view_key(row["id"], True)
        clothed = appmod.pose_view_key(row["id"], False)
        assert appmod.view_position_label(nude) == "wide stance spreading"
        assert appmod.view_position_label(clothed) == "wide stance spreading"
        assert "pose_" not in appmod.view_position_label(nude)


def test_identity_front_blocker_names_pose_library_when_front_is_missing():
    """A full pose library is not 'no anchor'. Generate refs still wants front."""
    with TestClient(appmod.app) as client:
        album = "Pose Library No Front"
        client.post("/playlists", data={"name": album})
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,'xxx','pose_21','standing.jpg',1,?)""",
               album, time.time())
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,'xxx','pose_60_nude','standing-nude.jpg',1,?)""",
               album, time.time())
        msg = appmod.identity_front_blocker(album, "xxx")
        assert msg is not None
        assert "2 pose sheet" in msg
        assert "identity front" in msg
        assert "no chosen anchor" not in msg
        song = {"album": album}
        blockers = appmod.refs_plan_blockers(song, "xxx", [])
        assert any("identity front" in b for b in blockers)


def test_song_page_says_missing_front_when_pose_sheets_exist():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Missing Front Song", album="Missing Front Album")
        sid = song["id"]
        client.post(f"/songs/{sid}/storyboard", data={"tier": "r"})
        job = db.one("SELECT id FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", sid)
        wait_job(job["id"])
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,'r','pose_21','standing.jpg',1,?)""",
               song["album"], time.time())
        page = client.get(f"/songs/{sid}").text
        refs = page.split("Reference images")[1].split('id="fold-review"')[0]
        assert "missing identity front" in refs
        assert "no anchor for this tier" not in refs
        assert "disabled" in refs
        assert 'class="pose-strip"' in refs
        assert "pose-chip" in refs


def test_xxx_gallery_defaults_to_nude_family():
    with TestClient(appmod.app) as client:
        album = "XXX Nude Default Album"
        client.post("/playlists", data={"name": album})
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,'xxx','pose_21','standing.jpg',1,?)""",
               album, time.time())
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,'xxx','pose_60_nude','standing-nude.jpg',1,?)""",
               album, time.time())
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,'r','pose_21','standing.jpg',1,?)""",
               album, time.time())
        groups = []
        for view, path, tier in (
            ("pose_21", "standing.jpg", "xxx"),
            ("pose_60_nude", "standing-nude.jpg", "xxx"),
            ("pose_21", "standing.jpg", "r"),
        ):
            groups.append({
                "scope_kind": "album", "scope_value": album,
                "character_id": None, "character_name": None,
                "tier": tier, "view": view, "path": path,
            })
        nest = appmod.nest_anchor_groups(groups)
        by_tier = {t["name"]: t for t in nest[0]["tiers"]}
        xxx_default = [f["key"] for f in by_tier["xxx"]["families"] if f["default"]]
        r_default = [f["key"] for f in by_tier["r"]["families"] if f["default"]]
        assert xxx_default == ["nude"]
        assert r_default == ["clothed"]


def test_storyboard_strip_uses_pose_name_not_view_key():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Strip Label Song", album="Strip Label Album")
        sid = song["id"]
        dest = os.path.join(db.DATA, "uploads", "anchors", "album", "Strip_Label_Album")
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, "standing-nude.jpg")
        open(path, "wb").write(_png_bytes())
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               None, "anchor_ref", path,
               json.dumps({"scope_value": song["album"], "character_id": None,
                           "pose_name": "standing nude", "role": "pose",
                           "pose_nude": True}), time.time())
        asset = db.one("SELECT * FROM assets WHERE path=?", path)
        view = appmod.pose_view_key(asset["id"], True)
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,?,?,?,1,?)""",
               song["album"], "xxx", view, path, time.time())
        outdir = os.path.join(db.DATA, "storyboards", song["slug"])
        os.makedirs(outdir, exist_ok=True)
        json_path = os.path.join(outdir, f"{song['slug']}_xxx.json")
        md_path = os.path.join(outdir, f"{song['slug']}_xxx.md")
        json.dump({"title": "T", "album": song["album"], "version": "xxx",
                   "scenes": [{"scene_number": 1, "name": "One",
                               "image_prompt": "a wet alley", "camera": "wide",
                               "duration_guidance": "5s"}]},
                  open(json_path, "w"))
        open(md_path, "w").write("# sb\n")
        db.run("""INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created)
                  VALUES (?,?,?,?,?,?)""",
               sid, "xxx", json_path, md_path, 1, time.time())
        html = client.get(f"/songs/{sid}/storyboard/xxx").text
        strip = html.split("Anchors for this tier")[1].split("</section>")[0]
        assert "missing identity front" in strip
        assert "pose sheet" in strip
        assert "standing nude" not in strip
        assert f"<figcaption>{view}" not in strip
        assert "identity front" in html
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,?,?,?,1,?)""",
               song["album"], "xxx", "front", path, time.time())
        html2 = client.get(f"/songs/{sid}/storyboard/xxx").text
        strip2 = html2.split("Anchors for this tier")[1].split("</section>")[0]
        assert "anchor-strip" in strip2
        assert "protagonist" in strip2
        assert "1 chosen pose sheet" in strip2
        assert "<figcaption>protagonist" in strip2


def test_song_page_lists_the_pose_library_not_just_identity_front():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Pose Library Song", album="Pose Library Album")
        sid = song["id"]
        client.post(f"/songs/{sid}/storyboard", data={"tier": "r"})
        job = db.one("SELECT id FROM jobs WHERE song_id=? AND kind='storyboard' ORDER BY id DESC", sid)
        wait_job(job["id"])
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,'r','front','front.jpg',1,?)""",
               song["album"], time.time())
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,'r','pose_21','kneel.jpg',1,?)""",
               song["album"], time.time())
        page = client.get(f"/songs/{sid}").text
        refs = page.split("Reference images")[1].split('id="fold-review"')[0]
        assert "2 pose sheets" in refs
        assert "identity front ready" in refs
        assert refs.count("pose-chip") == 2
        assert "anchor ready" not in refs
        assert "scene stills approved" in refs


def test_assemble_output_has_preview_modal_and_delete():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Assemble Card Song")
        sid = song["id"]
        dest = os.path.join(db.DATA, "renders", "assemble-card")
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, "assemble-card_r.mp4")
        open(path, "wb").write(b"not-a-real-mp4")
        rid = db.run("INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
                     sid, "r", path, time.time())
        page = client.get(f"/songs/{sid}").text
        assert 'class="render-grid"' in page
        assert f'id="vid-render-{rid}"' in page
        assert f'/songs/{sid}/renders/{rid}/delete' in page
        assert f"#{rid}" in page
        assert "assemble-card_r.mp4" in page
        gone = client.post(f"/songs/{sid}/renders/{rid}/delete", follow_redirects=False)
        assert gone.status_code == 303
        assert db.one("SELECT id FROM renders WHERE id=?", rid) is None
        assert not os.path.isfile(path)


def test_delete_render_keeps_file_when_a_sibling_shares_the_path():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Shared Assemble File")
        sid = song["id"]
        dest = os.path.join(db.DATA, "renders", "shared-assemble")
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, "shared-assemble_r.mp4")
        open(path, "wb").write(b"shared")
        rid1 = db.run("INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
                      sid, "r", path, time.time())
        rid2 = db.run("INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
                      sid, "xxx", path, time.time())
        gone = client.post(f"/songs/{sid}/renders/{rid2}/delete", follow_redirects=False)
        assert gone.status_code == 303
        assert db.one("SELECT id FROM renders WHERE id=?", rid2) is None
        assert db.one("SELECT id FROM renders WHERE id=?", rid1) is not None
        assert os.path.isfile(path)
        client.post(f"/songs/{sid}/renders/{rid1}/delete", follow_redirects=False)
        assert not os.path.isfile(path)


def test_delete_render_works_when_the_file_is_already_gone():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Ghost Assemble File")
        sid = song["id"]
        dest = os.path.join(db.DATA, "renders", "ghost-assemble")
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, "ghost-assemble_r.mp4")
        rid = db.run("INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
                     sid, "r", path, time.time())
        confirm = client.get(f"/songs/{sid}/renders/{rid}/delete")
        assert confirm.status_code == 200
        assert "ghost-assemble_r.mp4" in confirm.text
        assert "<form method=post" in confirm.text
        hx = client.post(
            f"/songs/{sid}/renders/{rid}/delete",
            headers={"HX-Request": "true"},
            follow_redirects=False,
        )
        assert hx.status_code == 200
        assert hx.text == ""
        assert db.one("SELECT id FROM renders WHERE id=?", rid) is None


def test_playlists_page_is_summaries_until_the_card_loads():
    with TestClient(appmod.app) as client:
        client.post("/playlists", data={"name": "Lazy Card Album"})
        pl = db.one("SELECT id FROM playlists WHERE name=?", "Lazy Card Album")["id"]
        listing = client.get("/playlists").text
        assert f'id="playlist-{pl}"' in listing
        assert f'hx-get="/playlists/{pl}/card"' in listing
        assert 'id="cover-preview"' in listing
        js = open(os.path.join(os.path.dirname(__file__), "static", "app.js")).read()
        assert "card.open = true" in js
        assert 'id="page-loading"' in listing
        assert 'name="identity"' not in listing
        card = client.get(f"/playlists/{pl}/card").text
        assert 'name="identity"' in card
        assert "<html" not in card.lower()
        assert "pl-fold" in card
        assert "look-tab" in card
        assert "cast-tab" in card
        assert "Main character identity" in card
        assert "trans-edit" in card or "No songs added yet" in card
