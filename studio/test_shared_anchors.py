"""T4-25: one anchors row, any album can reference it. No per-album file copy."""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db
from test_app import _png_bytes


def _album(client, name):
    client.post("/playlists", data={"name": name})
    return name


def _character(album, name, role="partner"):
    db.run("""INSERT INTO characters (scope_value, name, role, identity, created)
              VALUES (?,?,?,?,?)""", album, name, role, f"{name} identity", time.time())
    return db.one("SELECT * FROM characters WHERE scope_value=? AND name=?", album, name)


def test_upload_pose_is_shared_and_visible_to_every_album():
    with TestClient(appmod.app) as client:
        a1 = _album(client, f"Shared Src {time.time_ns()}")
        a2 = _album(client, f"Shared Dst {time.time_ns()}")
        kitty = _character(a1, "Kitty", "lead")
        _character(a2, "Kitty", "lead")
        r = client.post("/anchors/upload-pose",
                        data={"album": a1, "tier": "xxx", "label": "standing front nude",
                              "nude": "1", "character_id": str(kitty["id"])},
                        files={"image": ("kitty-front.png", _png_bytes(), "image/png")},
                        headers={"Accept": "application/json"})
        assert r.status_code == 200, r.text
        body = r.json()
        row = db.one("SELECT * FROM anchors WHERE id=?", body["id"])
        assert row["scope_kind"] == db.SHARED_KIND
        assert row["scope_value"] == db.SHARED_VALUE
        assert row["chosen"] == 1
        assert row["character_id"] == kitty["id"]
        assert "/uploads/anchors/shared/" in (row["path"] or "").replace("\\", "/")
        assert os.path.isfile(row["path"])

        src = appmod.chosen_anchor("album", a1, "xxx", row["view"], kitty["id"])
        assert src["id"] == row["id"]
        dst_kitty = db.one("SELECT * FROM characters WHERE scope_value=? AND name=?",
                           a2, "Kitty")
        dst = appmod.chosen_anchor("album", a2, "xxx", row["view"], dst_kitty["id"])
        assert dst is not None
        assert dst["id"] == row["id"]
        assert dst["path"] == src["path"]

        page = client.get("/anchors", params={"scope_value": a2}).text
        assert "standing front nude" in page or str(row["id"]) in page
        other = client.get("/anchors", params={"scope_value": a1}).text
        assert row["path"] in other or "standing front nude" in other


def test_second_album_does_not_copy_the_shared_file():
    with TestClient(appmod.app) as client:
        a1 = _album(client, f"No Copy A {time.time_ns()}")
        a2 = _album(client, f"No Copy B {time.time_ns()}")
        r = client.post("/anchors/upload-pose",
                        data={"album": a1, "tier": "xxx", "label": "cowgirl panther",
                              "actor_name": ["Meow P", "Panther"]},
                        files={"image": ("cowgirl.png", _png_bytes(), "image/png")},
                        headers={"Accept": "application/json"})
        assert r.status_code == 200, r.text
        sheet_id = r.json()["id"]
        path = db.one("SELECT path FROM anchors WHERE id=?", sheet_id)["path"]
        before = db.q("SELECT id FROM anchors WHERE path=?", path)
        assert len(before) == 1
        page = client.get("/anchors", params={"scope_value": a2})
        assert page.status_code == 200
        after = db.q("SELECT id FROM anchors WHERE path=?", path)
        assert [x["id"] for x in after] == [sheet_id]


def test_album_specific_chosen_wins_over_shared():
    with TestClient(appmod.app) as client:
        album = _album(client, f"Override {time.time_ns()}")
        dest = os.path.join(db.DATA, "uploads", "anchors", "album", "x")
        os.makedirs(dest, exist_ok=True)
        shared = os.path.join(db.shared_anchor_dir(), f"shared_{time.time_ns()}.png")
        local = os.path.join(dest, f"local_{time.time_ns()}.png")
        open(shared, "wb").write(_png_bytes())
        open(local, "wb").write(_png_bytes())
        now = time.time()
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES (?,?,?,?,?,1,?)""",
               db.SHARED_KIND, db.SHARED_VALUE, "xxx", "back_nude", shared, now)
        db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
                  VALUES ('album',?,?,?,?,1,?)""",
               album, "xxx", "back_nude", local, now)
        picked = appmod.chosen_anchor("album", album, "xxx", "back_nude")
        assert picked["path"] == local
        other = _album(client, f"Override Other {time.time_ns()}")
        fallback = appmod.chosen_anchor("album", other, "xxx", "back_nude")
        assert fallback["path"] == shared


def test_assign_as_sheet_writes_shared():
    with TestClient(appmod.app) as client:
        album = _album(client, f"Assign Shared {time.time_ns()}")
        path = os.path.join(db.shared_anchor_dir(), f"assign_{time.time_ns()}.png")
        open(path, "wb").write(_png_bytes())
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               None, "anchor_ref", path,
               json.dumps({"scope_value": album, "character_id": None,
                           "pose_name": "seated nude", "pose_tier": "xxx",
                           "role": "pose", "pose_nude": True}), time.time())
        row = db.one("SELECT * FROM assets WHERE path=?", path)
        a = client.post(f"/anchors/refs/{row['id']}/assign",
                        data={"album": album, "pose_name": "seated nude",
                              "pose_tier": "xxx", "pose_nude": "1"},
                        follow_redirects=False)
        assert a.status_code == 303, a.text
        sheet = db.one("SELECT * FROM anchors WHERE path=?", path)
        assert sheet["scope_kind"] == db.SHARED_KIND
        assert sheet["chosen"] == 1
