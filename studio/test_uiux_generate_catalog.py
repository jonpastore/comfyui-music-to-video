"""Generate form: sticky album/tier, missing catalog poses, actor identity."""
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
    finally:
        classification._DEFAULT_SIDECAR = prev
    assert page.status_code == 200, page.text
    html = page.text
    assert "<select name=\"album\"" not in html
    assert 'type="hidden" name="album"' in html
    assert 'class="view-matrix"' not in html
    assert "Tick at least one" not in html
    assert "need_key" in html or "No missing catalog poses" in html or "Pick a tier chip" in html
    assert "actor-card" in html
    assert "help-tip" in html.split('id="generate-pose"', 1)[1][:800]
    scope = html.split('id="anchor-scope"', 1)[1].split("id=\"classification-library\"", 1)[0]
    for name in ("G", "PG13", "R", "XXX"):
        assert f"gap_tier={name.lower()}\"" in scope or f"gap_tier={name.lower()}&" in scope or \
            f'gap_tier={name.lower()}' in scope, scope[:800]
    assert 'name="tier"' in html.split('id="anchor-form"', 1)[-1][:1500]
    assert "<select name=\"album\"" not in html.split('id="anchor-form"', 1)[-1]


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
