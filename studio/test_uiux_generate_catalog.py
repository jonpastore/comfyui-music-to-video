"""Generate form: sticky album/tier, missing catalog poses, actor identity."""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import classification
from test_uiux_classification_chips import _album_song, _scene


def test_generate_form_uses_sticky_album_and_missing_poses():
    stamp = f"gen-cat-{time.time_ns()}"
    album, sid, _song = _album_song(stamp, scenes=[
        _scene(1, "standing", "wide"),
        _scene(2, "kneeling", "medium"),
    ])
    prev = classification._DEFAULT_SIDECAR
    classification._DEFAULT_SIDECAR = os.path.join(db.DATA, f"{stamp}-missing.json")
    try:
        with TestClient(appmod.app) as client:
            page = client.get("/anchors", params={
                "scope_value": album, "song_id": sid, "gap_tier": "xxx"})
            assert page.status_code == 200, page.text
            html = page.text
            assert "<select name=\"album\"" not in html
            assert 'type="hidden" name="album"' in html
            assert 'class="view-matrix"' not in html
            assert "Tick at least one" not in html
            assert "need_key" in html or "No missing poses" in html or "Pick a tier chip" in html
            assert "actor-card" in html
            assert "help-tip" in html.split('id="generate-pose"', 1)[1][:800]
            scope = html.split('id="anchor-scope"', 1)[1].split('id="classification-library"', 1)[0]
            for name in ("G", "PG13", "R", "XXX"):
                assert f"gap_tier={name.lower()}" in scope, scope[:800]
            assert 'class="tier-chip on"' in scope
            assert 'hx-target="#anchors-root"' in scope
            assert '<button type="button" class="tier-chip' in scope
            assert 'href="/anchors?' not in scope
            assert 'name="tier"' in html.split('id="anchor-form"', 1)[-1][:1500]
            ghtml = client.get("/anchors", params={
                "scope_value": album, "gap_tier": "g"}).text
            gscope = ghtml.split('id="anchor-scope"', 1)[1][:2500]
            assert 'class="tier-chip on"' in gscope
            assert 'gap_tier=g"' in gscope or "gap_tier=g&" in gscope
            roster = ghtml.split('id="album-pose-roster"', 1)
            if len(roster) > 1:
                assert 'class="tier-tabs"' not in roster[1].split("</section>", 1)[0]
            cat = html.split('id="character-catalog"', 1)
            if len(cat) > 1:
                head = cat[1].split("</summary>", 1)[0]
                assert album not in head
    finally:
        classification._DEFAULT_SIDECAR = prev


def test_preflight_empty_poses_does_not_claim_nude_block():
    with TestClient(appmod.app) as client:
        name = f"PlanEmpty {time.time_ns()}"
        client.post("/playlists", data={"name": name})
        r = client.post("/anchors/plan", data={"album": name, "tier": "pg13"})
    assert r.status_code == 200, r.text
    blockers = " ".join(r.json().get("blockers") or [])
    assert "Tick at least one missing pose" in blockers
    assert "nude" not in blockers.lower()


def test_pg13_missing_poses_include_unset_holes_and_actor_thumbs(tmp_path):
    """Pose-unset PG13 holes populate Generate; any chosen sheet is a thumb.

    Mutation: album_coverage skips unset → empty checklist → red.
    Mutation: identity url requires view=front only → blank Panther → red.
    """
    stamp = f"gen-holes-{time.time_ns()}"
    album, sid, song = _album_song(stamp, scenes=[_scene(1, "standing", "wide")])
    unset = _scene(1, "", "front")
    unset["pose"] = ""
    unset["story"] = "neon street"
    unset["image_prompt"] = "Meow P on a neon street"
    from test_uiux_classification_chips import _write_board
    _write_board(sid, song["slug"], "pg13", [unset, _scene(2, "", "back")], album)
    db.run("""INSERT INTO characters (scope_value, name, created)
              VALUES (?, 'Panther', ?)""", album, time.time())
    crow = db.one("SELECT id FROM characters WHERE scope_value=? AND name='Panther'",
                  album)
    sheet = os.path.join(db.DATA, f"{stamp}-panther.png")
    open(sheet, "wb").write(b"\x89PNG\r\n\x1a\n")
    db.run("""INSERT INTO anchors
              (scope_kind, scope_value, tier, view, path, chosen, created,
               character_id, render_json)
              VALUES ('album',?,'xxx','pose_173_nude',?,1,?,?,?)""",
           album, sheet, time.time(), crow["id"],
           json.dumps({"pose_name": "front squat"}))
    prev = classification._DEFAULT_SIDECAR
    classification._DEFAULT_SIDECAR = os.path.join(db.DATA, f"{stamp}-missing.json")
    try:
        with TestClient(appmod.app) as client:
            client.post("/playlists", data={"name": album})
            page = client.get("/anchors", params={
                "scope_value": album, "song_id": sid, "gap_tier": "pg13"})
        assert page.status_code == 200, page.text
        html = page.text
        form = html.split('id="anchor-form"', 1)[1]
        assert 'name="need_key"' in form
        assert "front" in form.split("missing-pose-list", 1)[-1][:800]
        assert os.path.basename(sheet) in html
        assert 'class="tier-tabs"' not in html.split(
            'id="album-pose-roster"', 1)[-1].split("</section>", 1)[0]
        assert "100 missing" not in html.lower() or "gap_tier=g" in html
        cat = html.split('id="character-catalog"', 1)
        if len(cat) > 1:
            assert "catalog-empty" in cat[1][:500] or "No sheets at" in cat[1][:800]
            assert album not in cat[1].split("</summary>", 1)[0]
    finally:
        classification._DEFAULT_SIDECAR = prev


def test_apply_keeper_same_file_two_albums_two_tiers(tmp_path):
    """One file, two albums, two tiers — no second copy on disk."""
    import tiers
    tiers.ensure_builtins()
    path = str(tmp_path / "shared-kneel.png")
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n")
    a1, a2 = f"KeepA {time.time_ns()}", f"KeepB {time.time_ns()}"
    with TestClient(appmod.app) as client:
        assert client.post("/playlists", data={"name": a1}).status_code in (200, 303)
        assert client.post("/playlists", data={"name": a2}).status_code in (200, 303)
        r = client.post("/api/keepers/apply", json={
            "path": path, "pose": "kneel", "wardrobe": "clothed",
            "albums": [a1, a2], "tiers": ["r", "xxx"],
        })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n"] == 4
    rows = db.q("SELECT * FROM anchors WHERE path=?", path)
    assert len(rows) == 4
    assert {row["scope_value"] for row in rows} == {a1, a2}
    assert {row["tier"] for row in rows} == {"r", "xxx"}
    assert all(row["chosen"] == 1 for row in rows)
    assert os.path.isfile(path)
    libs = classification.library(a1)["images"] + classification.library(a2)["images"]
    assert sum(1 for im in libs if im["path"] == path) == 2


def test_roster_badge_says_g_needs_n_when_gap_tier_g():
    """Sticky G + missing coverage → 'G needs N', not a bare 'N missing'.

    Mutation: warn-tag stays '{{ miss.n }} missing' with page_tier → red.
    """
    stamp = f"g-needs-{time.time_ns()}"
    album, sid, _song = _album_song(stamp, scenes=[
        _scene(1, "standing", "wide"),
        _scene(2, "kneeling", "medium"),
    ])
    from test_uiux_classification_chips import _write_board
    _write_board(sid, _song["slug"], "g", [
        _scene(1, "standing", "wide"),
        _scene(2, "kneeling", "medium"),
    ], album)
    prev = classification._DEFAULT_SIDECAR
    classification._DEFAULT_SIDECAR = os.path.join(db.DATA, f"{stamp}-gneeds.json")
    try:
        with TestClient(appmod.app) as client:
            html = client.get("/anchors", params={
                "scope_value": album, "song_id": sid, "gap_tier": "g"}).text
        roster = html.split('id="album-pose-roster"', 1)
        assert len(roster) > 1, html[:600]
        head = roster[1].split("</summary>", 1)[0]
        assert "G needs" in head, head
        assert "missing" not in head.lower() or "G needs" in head
    finally:
        classification._DEFAULT_SIDECAR = prev


def test_anchors_failed_retry_is_not_full_page_form():
    """Failed-job Retry on /anchors must not be a bare method=post /retry form.

    Mutation: restore <form method=\"post\" action=\"/jobs/{{ j.id }}/retry\">
    without hx / data-job-retry → red.
    """
    import re
    src = open(os.path.join(os.path.dirname(appmod.__file__),
                            "templates", "anchors.html")).read()
    failed = src.split("failed-jobs", 1)[1].split("</details>", 1)[0]
    bare = re.search(
        r'<form\b[^>]*\baction="/jobs/\{\{\s*j\.id\s*\}\}/retry"[^>]*>', failed)
    if bare:
        tag = bare.group(0)
        assert "hx-post" in tag or "hx-get" in tag, tag
    assert 'data-job-retry="/jobs/{{ j.id }}/retry"' in failed or (
        bare and ("hx-post" in bare.group(0) or "hx-get" in bare.group(0))), failed[:500]
