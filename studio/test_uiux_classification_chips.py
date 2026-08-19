"""UIUX 7a.7: Anchors page chips from classification_json + ceiling holes.

GET /anchors shows keepers (usable≠skip) and the open song's pose-gap
holes. Import/save seed an empty library so T4-23 holes close without
GPU. Stays off _scene_row / _storyboard_panel.

Mutation: omit keeper chips from anchors.html → red.
Mutation: skip usable painted as a keeper → red.
Mutation: sidecar-only (not imported) closes a hole on the page → red.
"""
import ast
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import classification
import db
import tiers

_JS = os.path.join(os.path.dirname(appmod.__file__), "static", "app.js")
_ANCHORS = os.path.join(os.path.dirname(appmod.__file__), "templates", "anchors.html")
_SCENE_ROW = os.path.join(os.path.dirname(appmod.__file__), "templates", "_scene_row.html")
_SB_PANEL = os.path.join(
    os.path.dirname(appmod.__file__), "templates", "_storyboard_panel.html")


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
        "usable": "pose",
    }
    row.update(over)
    return row


def _album_song(stamp, scenes=None):
    tiers.ensure_builtins()
    album = f"Chips {stamp}"
    sid = db.upsert_song(
        stamp, title=f"Chips Song {stamp}", album=album, duration=16.0)
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    if scenes is None:
        scenes = [
            _scene(1, "kneeling", "medium"),
            _scene(2, "standing", "wide"),
        ]
    _write_board(sid, song["slug"], "xxx", scenes, album)
    return album, sid, song


def test_uiux_anchors_shows_keeper_chips_and_holes():
    """Keepers render as chips; uncovered ceiling needs are hole chips."""
    stamp = f"uiux-chips-{time.time_ns()}"
    album, sid, _song = _album_song(stamp)
    classification.save(album, {"images": [
        _image("kneel-front", pose="kneel", view="front", wardrobe="clothed",
               usable="pose"),
        _image("stand-skip", pose="stand", view="front", wardrobe="clothed",
               usable="skip"),
    ]})
    with TestClient(appmod.app) as client:
        page = client.get("/anchors", params={"scope_value": album, "song_id": sid})
    assert page.status_code == 200, page.text
    html = page.text
    assert 'id="classification-library"' in html
    assert 'id="class-keeper-chips"' in html
    assert 'data-pose="kneel"' in html
    assert 'data-view="front"' in html
    assert 'data-wardrobe="clothed"' in html
    assert 'data-usable="pose"' in html
    assert "kneel / front / clothed" not in html
    assert 'class="keeper-row-name">kneel</span>' in html
    assert 'id="pose-gap-holes"' in html
    assert 'class="tag class-chip hole warn-tag js-hole-pick"' in html
    assert 'data-pose="standing"' in html
    assert "XXX · clothed · standing · front" in html
    assert 'id="pose-gap-tier"' in html
    assert 'data-usable="skip"' not in html
    assert "stand-skip" not in html
    assert 'id="classification-from-sheets"' in html
    assert 'id="hole-pick"' in html
    assert f'value="{sid}"' in html
    assert "<summary>" in html.split('id="classification-library"', 1)[1]
    assert "Pose catalog" in html
    assert 'id="anchor-scope"' in html
    assert '<h1 class="visually-hidden">Anchors</h1>' in html
    assert "help-tip" in html.split('id="anchor-scope"', 1)[1][:2500]
    assert "Character catalog" in html
    assert '<p class="hint">This album' not in html
    album_at = html.find('id="class-album"')
    song_at = html.find('id="pose-gap-song"')
    assert album_at != -1 and song_at != -1 and album_at < song_at
    assert 'class="tier-chip' in html
    assert "js-keeper-preview" in html
    assert "keeper-row" in html
    assert "Does not generate a new sheet" in html
    assert "No file, no GPU" not in html
    assert "no pose named" not in html
    assert 'id="keeper-preview"' not in html
    assert 'id="pose-preview"' in html
    src = open(_ANCHORS).read()
    assert 'id="character-catalog"' in src
    assert 'id="character-catalog" open' not in src


def test_gap_tier_select_reads_that_board():
    stamp = f"uiux-tier-{time.time_ns()}"
    album, sid, song = _album_song(stamp, scenes=[_scene(1, "standing", "wide")])
    _write_board(sid, song["slug"], "r", [_scene(1, "kneeling", "medium")], album)
    prev = classification._DEFAULT_SIDECAR
    classification._DEFAULT_SIDECAR = os.path.join(db.DATA, f"{stamp}-missing.json")
    try:
        with TestClient(appmod.app) as client:
            xxx = client.get("/anchors", params={"scope_value": album, "song_id": sid})
            r = client.get("/anchors", params={
                "scope_value": album, "song_id": sid, "gap_tier": "r"})
        assert "XXX · clothed · standing · front" in xxx.text
        assert "R · clothed · kneeling · front" in r.text
    finally:
        classification._DEFAULT_SIDECAR = prev


def test_uiux_import_seeds_empty_library_and_closes_holes():
    """Empty library shows the hole; import (no GPU) seeds keepers and closes it."""
    stamp = f"uiux-import-{time.time_ns()}"
    album, sid, _song = _album_song(stamp, scenes=[_scene(1, "standing", "wide")])
    side = os.path.join(db.DATA, f"{stamp}-image-classification.json")
    json.dump({"images": [
        _image("sidecar-stand", pose="stand", view="front", wardrobe="clothed",
               usable="pose"),
    ]}, open(side, "w"))
    # Hold default auto-seed so this case exercises explicit import only.
    prev = classification._DEFAULT_SIDECAR
    classification._DEFAULT_SIDECAR = os.path.join(db.DATA, f"{stamp}-missing.json")
    try:
        with TestClient(appmod.app) as client:
            empty = client.get("/anchors", params={"scope_value": album, "song_id": sid})
            assert empty.status_code == 200, empty.text
            assert 'id="class-keepers-empty"' in empty.text
            assert 'data-pose="standing"' in empty.text
            assert "No tagged keepers on this album yet" in empty.text

            seeded = client.post(
                f"/api/albums/{album}/classification/import", json={"path": side})
            assert seeded.status_code == 200, seeded.text
            assert [im["id"] for im in seeded.json()["images"]] == ["sidecar-stand"]

            filled = client.get("/anchors", params={"scope_value": album, "song_id": sid})
        assert filled.status_code == 200, filled.text
        html = filled.text
        assert 'data-id="sidecar-stand"' in html
        assert 'class="keeper-row-name">stand</span>' in html
        assert 'id="pose-gap-empty"' in html
        assert "No ceiling holes for this song." in html
        assert 'class="tag class-chip hole warn-tag"' not in html
    finally:
        classification._DEFAULT_SIDECAR = prev


def test_uiux_save_seeds_empty_library():
    """POST classification save is what the Save control posts; page then chips."""
    stamp = f"uiux-save-{time.time_ns()}"
    album, sid, _song = _album_song(stamp, scenes=[_scene(1, "kneeling", "medium")])
    document = {"images": [
        _image("saved-kneel", pose="kneel", view="front", wardrobe="clothed",
               usable="identity"),
    ]}
    prev = classification._DEFAULT_SIDECAR
    classification._DEFAULT_SIDECAR = os.path.join(db.DATA, f"{stamp}-missing.json")
    try:
        with TestClient(appmod.app) as client:
            empty = client.get("/anchors", params={"scope_value": album, "song_id": sid})
            assert 'id="class-keepers-empty"' in empty.text
            posted = client.post(
                f"/api/albums/{album}/classification", json=document)
            assert posted.status_code == 200, posted.text
            page = client.get("/anchors", params={"scope_value": album, "song_id": sid})
        assert page.status_code == 200, page.text
        assert 'data-id="saved-kneel"' in page.text
        assert 'data-usable="identity"' in page.text
        assert "No ceiling holes for this song." in page.text
    finally:
        classification._DEFAULT_SIDECAR = prev


def test_uiux_sidecar_alone_does_not_paint_keepers_or_close_holes():
    """A random sidecar on disk is not the library; only default auto-seed / import."""
    stamp = f"uiux-side-{time.time_ns()}"
    album, sid, _song = _album_song(stamp, scenes=[_scene(1, "standing", "wide")])
    side = os.path.join(db.DATA, f"{stamp}-only.json")
    json.dump({"images": [
        _image("disk-only", pose="stand", view="front", wardrobe="clothed",
               usable="pose"),
    ]}, open(side, "w"))
    prev = classification._DEFAULT_SIDECAR
    classification._DEFAULT_SIDECAR = os.path.join(db.DATA, f"{stamp}-missing.json")
    try:
        with TestClient(appmod.app) as client:
            page = client.get("/anchors", params={"scope_value": album, "song_id": sid})
        assert page.status_code == 200, page.text
        assert 'data-id="disk-only"' not in page.text
        assert 'id="class-keepers-empty"' in page.text
        assert 'data-pose="standing"' in page.text
        assert "js-hole-pick" in page.text
    finally:
        classification._DEFAULT_SIDECAR = prev


def test_uiux_live_empty_auto_seeds_from_default_sidecar():
    """Empty DB + default sidecar present → /anchors seeds one version (no GPU)."""
    stamp = f"uiux-autoseed-{time.time_ns()}"
    album, sid, _song = _album_song(stamp, scenes=[_scene(1, "standing", "wide")])
    side = os.path.join(db.DATA, f"{stamp}-default.json")
    json.dump({"images": [
        _image("auto-stand", pose="stand", view="front", wardrobe="clothed",
               usable="pose"),
    ]}, open(side, "w"))
    prev = classification._DEFAULT_SIDECAR
    classification._DEFAULT_SIDECAR = side
    try:
        assert classification.library(album)["images"] == []
        with TestClient(appmod.app) as client:
            page = client.get("/anchors", params={"scope_value": album, "song_id": sid})
            again = client.get("/anchors", params={"scope_value": album, "song_id": sid})
        assert page.status_code == 200, page.text
        assert 'data-id="auto-stand"' in page.text
        assert 'class="keeper-row-name">stand</span>' in page.text
        assert 'id="pose-gap-empty"' in page.text
        assert again.status_code == 200, again.text
        assert 'data-id="auto-stand"' in again.text
        vers = classification.versions(album)
        assert [v["version_number"] for v in vers] == [1]
    finally:
        classification._DEFAULT_SIDECAR = prev


def test_sheets_api_skips_missing_files_and_names_actors(tmp_path):
    album = f"Sheets {time.time_ns()}"
    good = str(tmp_path / "ok.png")
    open(good, "wb").write(b"\x89PNG\r\n\x1a\n")
    db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created,render_json)
              VALUES ('album',?,'xxx','front',?,1,?,?)""",
           album, good, time.time(),
           json.dumps({"pose_name": "cowgirl", "actors": ["Meow P", "Panther"]}))
    db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created)
              VALUES ('album',?,'xxx','pose_14','/no/such/pose14.png',1,?)""",
           album, time.time())
    with TestClient(appmod.app) as client:
        r = client.get(f"/api/albums/{album}/sheets")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n"] == 1
    assert body["sheets"][0]["actors"] == ["Meow P", "Panther"]
    assert "pose_14" not in str(body)


def test_uiux_js_wires_import_and_save():
    """The page tags from sheets and opens the hole picker."""
    js = open(_JS).read()
    assert "function initClassificationLibrary" in js
    assert "initClassificationLibrary()" in js
    assert "/classification/from-sheets" in js
    assert "/classification/keeper" in js
    assert "js-hole-pick" in js
    assert "js-keeper-preview" in js
    assert 'id === "pose-preview"' in js or "pose-preview" in js
    assert "holdClosed" in js
    assert "pose unset" in js
    assert "no pose named" not in open(_ANCHORS).read()
    assert "Generate anchors" in open(_ANCHORS).read()
    assert "requestSubmit" in js


def test_tag_from_anchors_and_keeper_close_a_hole(tmp_path):
    stamp = f"tag-sheets-{time.time_ns()}"
    album, sid, _song = _album_song(stamp, scenes=[_scene(1, "standing", "wide")])
    path = str(tmp_path / "stand.png")
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n")
    db.run("""INSERT INTO anchors (scope_kind,scope_value,tier,view,path,chosen,created,render_json)
              VALUES ('album',?,'xxx','front',?,1,?,?)""",
           album, path, time.time(), json.dumps({"pose_name": "standing"}))
    prev = classification._DEFAULT_SIDECAR
    classification._DEFAULT_SIDECAR = str(tmp_path / "missing.json")
    try:
        with TestClient(appmod.app) as client:
            tagged = client.post(f"/api/albums/{album}/classification/from-sheets")
            assert tagged.status_code == 200, tagged.text
            assert tagged.json()["images"]
            sheets = client.get(f"/api/albums/{album}/sheets", params={"family": "clothed"})
            assert sheets.status_code == 200
            assert sheets.json()["n"] >= 1
            page = client.get("/anchors", params={"scope_value": album, "song_id": sid})
        assert page.status_code == 200
        assert "No ceiling holes for this song." in page.text
    finally:
        classification._DEFAULT_SIDECAR = prev


def test_add_keeper_tags_one_sheet(tmp_path):
    stamp = f"one-keep-{time.time_ns()}"
    album = f"One {stamp}"
    path = str(tmp_path / "k.png")
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n")
    got = classification.add_keeper(album, {
        "id": "anchor-1", "path": path, "kind": "operator",
        "view": "front", "pose": "seated", "wardrobe": "nude", "usable": "pose",
    })
    assert any(im["pose"] == "seated" and im["wardrobe"] == "nude"
               for im in got["images"])


def test_group_rows_one_row_per_pose():
    imgs = [
        _image("a", pose="kneel", view="front", wardrobe="clothed",
               usable="pose", path="a.jpg"),
        _image("b", pose="kneel", view="front", wardrobe="clothed",
               usable="identity", path="b.jpg"),
        _image("c", pose="kneel nude", view="pose_91_nude", wardrobe="nude",
               usable="pose", path="c.jpg"),
        _image("d", pose="stand", view="pose_77", wardrobe="clothed",
               usable="pose", path="d.jpg"),
    ]
    imgs[0]["url"] = "/media/a.jpg"
    imgs[1]["url"] = "/media/b.jpg"
    imgs[2]["url"] = "/media/c.jpg"
    got = classification.group_rows(imgs)
    assert [g["pose"] for g in got] == ["kneel", "stand"]
    assert got[0]["n_clothed"] == 2 and got[0]["n_nude"] == 1
    assert got[0]["urls"] == ["/media/a.jpg", "/media/b.jpg", "/media/c.jpg"]
    assert got[0]["view"] == "front"
    assert got[1]["view"] == ""
    assert classification.pose_label("3qtr nude") == "3qtr"
    same = [
        _image("x", pose="back", view="front", wardrobe="clothed", path="/tmp/a.jpg"),
        _image("y", pose="back", view="front", wardrobe="clothed", path="/tmp/a.jpg"),
    ]
    same[0]["url"] = "/media/a.jpg"
    same[1]["url"] = "/media/a.jpg"
    one = classification.group_rows(same)
    assert one[0]["n_clothed"] == 1


def test_keeper_chips_group_and_resolve_basename():
    """Two same-pose keepers → one chip; sidecar basename becomes /media/."""
    stamp = f"uiux-group-{time.time_ns()}"
    album, sid, _song = _album_song(stamp, scenes=[_scene(1, "kneeling", "medium")])
    a = os.path.join(db.DATA, f"{stamp}-a.jpg")
    b = os.path.join(db.DATA, f"{stamp}-b.jpg")
    open(a, "wb").write(b"\x89PNG\r\n\x1a\n")
    open(b, "wb").write(b"\x89PNG\r\n\x1a\n")
    classification.save(album, {"images": [
        _image("keep-a", path=os.path.basename(a), pose="kneel", view="front",
               wardrobe="clothed", usable="pose"),
        _image("keep-b", path=os.path.basename(b), pose="kneel", view="front",
               wardrobe="clothed", usable="identity"),
    ]})
    with TestClient(appmod.app) as client:
        page = client.get("/anchors", params={"scope_value": album, "song_id": sid})
    assert page.status_code == 200, page.text
    html = page.text
    assert html.count('class="keeper-row js-keeper-preview"') == 1
    assert "clothed ×2" in html
    assert "kneel / front / clothed" not in html
    assert "data-urls=" in html
    assert "/media/" in html
    assert os.path.basename(a) in html


def test_page_tier_keepers_are_chosen_sheets_and_chips_are_buttons(tmp_path):
    """Sticky XXX chip shows that tier's chosen sheet, not the class copy.

    Mutation: tagged keepers stay the album-wide classification dump → red.
    Mutation: chip is <a href> (full navigation) → red.
    """
    stamp = f"uiux-chosen-{time.time_ns()}"
    album, sid, _song = _album_song(stamp, scenes=[_scene(1, "standing", "wide")])
    class_path = os.path.join(db.DATA, f"{stamp}-class.png")
    chosen_path = os.path.join(db.DATA, f"{stamp}-xxx.png")
    open(class_path, "wb").write(b"\x89PNG\r\n\x1a\n")
    open(chosen_path, "wb").write(b"\x89PNG\r\n\x1a\n")
    classification.save(album, {"images": [
        _image("class-stand", path=class_path, pose="stand", view="front",
               wardrobe="clothed", usable="pose"),
    ]})
    db.run("""INSERT INTO anchors
              (scope_kind, scope_value, tier, view, path, chosen, created, render_json)
              VALUES ('album',?,'xxx','front_nude',?,1,?,?)""",
           album, chosen_path, time.time(), json.dumps({"pose_name": "stand"}))
    prev = classification._DEFAULT_SIDECAR
    classification._DEFAULT_SIDECAR = os.path.join(db.DATA, f"{stamp}-missing.json")
    try:
        with TestClient(appmod.app) as client:
            xxx = client.get("/anchors", params={
                "scope_value": album, "song_id": sid, "gap_tier": "xxx"})
            bare = client.get("/anchors", params={
                "scope_value": album, "song_id": sid})
    finally:
        classification._DEFAULT_SIDECAR = prev
    assert xxx.status_code == 200, xxx.text
    html = xxx.text
    chips = html.split('id="class-keeper-chips"', 1)[1].split("Missing on this song", 1)[0]
    assert os.path.basename(chosen_path) in chips
    assert os.path.basename(class_path) not in chips
    assert 'loading="lazy"' not in chips
    scope = html.split('id="anchor-scope"', 1)[1].split('id="classification-library"', 1)[0]
    assert '<button type="button" class="tier-chip' in scope
    assert 'href="/anchors?' not in scope
    assert 'hx-target="#anchors-root"' in scope
    assert os.path.basename(class_path) in bare.text


def test_unspecified_hole_says_pose_unset_not_scene_dump():
    stamp = f"uiux-unset-{time.time_ns()}"
    scenes = []
    for n in (1, 2, 3):
        s = _scene(n, "", "wide")
        s["story"] = "neon street at night"
        s["image_prompt"] = "Meow P in a neon street at night"
        s["pose"] = ""
        scenes.append(s)
    album, sid, _song = _album_song(stamp, scenes=scenes)
    prev = classification._DEFAULT_SIDECAR
    classification._DEFAULT_SIDECAR = os.path.join(db.DATA, f"{stamp}-missing.json")
    try:
        with TestClient(appmod.app) as client:
            page = client.get("/anchors", params={"scope_value": album, "song_id": sid})
    finally:
        classification._DEFAULT_SIDECAR = prev
    assert page.status_code == 200, page.text
    html = page.text
    assert "pose unset" in html
    assert "no pose named" not in html
    assert "3 scenes" in html
    assert "scenes 1, 2, 3" not in html


def test_uiux_stays_off_scene_row_and_storyboard_panel():
    """This surface is the anchors page, not the storyboard fragments."""
    html = open(_ANCHORS).read()
    assert "_scene_row.html" not in html
    assert "_storyboard_panel.html" not in html
    assert os.path.isfile(_SCENE_ROW)
    assert os.path.isfile(_SB_PANEL)
    names = [
        node.name for node in ast.walk(ast.parse(open(appmod.__file__).read()))
        if isinstance(node, ast.FunctionDef)
    ]
    assert "_anchors_classification_ctx" in names
