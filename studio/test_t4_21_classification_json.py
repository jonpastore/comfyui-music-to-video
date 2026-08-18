"""T4-21 / T4-22: classification_json lives in sqlite, not a sidecar.

docs/TRD-4 §6a: album + character_id (NULL = protagonist), versioned
document, same fields as anchor5/image-classification.json. Queryable
by view / pose / wardrobe / usable. Sidecars may seed an import; they
are not the runtime source.

Mutation: the only store is a sidecar file → red.
Mutation: library() reads image-classification.json once a DB document
exists → red.
"""
import ast
import json
import os
import tempfile
import time

from fastapi.testclient import TestClient

import app as appmod
import classification
import db


def _fastapi_imports(path):
    tree = ast.parse(open(path).read())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split(".")[0])
    return [n for n in names if n == "fastapi"]


def _image(iid, **over):
    row = {
        "id": iid,
        "path": f"{iid}.jpg",
        "kind": "operator",
        "view": "front",
        "pose": "stand",
        "wardrobe": "clothed",
        "usable": "identity",
        "notes": f"note {iid}",
        "seed": 4748,
    }
    row.update(over)
    return row


def _opens_in(fn_name):
    tree = ast.parse(open(classification.__file__).read())
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != fn_name:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                if child.func.id == "open":
                    hits.append(fn_name)
    return hits


def test_t4_21_classification_imports_nothing_from_fastapi():
    assert _fastapi_imports(classification.__file__) == []


def test_t4_21_table_exists_in_sqlite():
    row = db.one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='classification_json'")
    assert row, "classification_json table missing"


def test_t4_21_save_and_query_by_view_pose_wardrobe_usable():
    album = f"T421 {time.time_ns()}"
    document = {"images": [
        _image("front-stand", view="front", pose="stand", wardrobe="clothed",
               usable="identity"),
        _image("back-kneel", view="back", pose="kneel", wardrobe="nude",
               usable="pose", seed=5151),
        _image("side-skip", view="side", pose="sit", wardrobe="clothed",
               usable="skip"),
    ]}
    saved = classification.save(album, document)
    assert saved["album"] == album
    assert saved["character_id"] is None
    assert saved["version_number"] == 1
    assert {im["id"] for im in saved["images"]} == {
        "front-stand", "back-kneel", "side-skip"}

    by_view = classification.query(album, view="back")
    assert [im["id"] for im in by_view["images"]] == ["back-kneel"]
    by_pose = classification.query(album, pose="sit")
    assert [im["id"] for im in by_pose["images"]] == ["side-skip"]
    by_ward = classification.query(album, wardrobe="nude")
    assert [im["id"] for im in by_ward["images"]] == ["back-kneel"]
    by_use = classification.query(album, usable="skip")
    assert [im["id"] for im in by_use["images"]] == ["side-skip"]
    stacked = classification.query(album, view="front", pose="stand",
                                   wardrobe="clothed", usable="identity")
    assert [im["id"] for im in stacked["images"]] == ["front-stand"]


def test_t4_21_fields_match_sidecar_shape():
    album = f"T421-fields {time.time_ns()}"
    src = _image("tense", view="front", pose="crouch", wardrobe="clothed",
                 usable="identity", notes="wide stance", seed=129080599,
                 kind="operator", path="tense.jpg")
    classification.save(album, {"images": [src], "body": "charcoal-brown"})
    lib = classification.library(album)
    assert lib["document"]["body"] == "charcoal-brown"
    got = lib["images"][0]
    for key in ("id", "path", "kind", "view", "pose", "wardrobe", "usable",
                "notes", "seed"):
        assert key in got, got
        assert got[key] == src[key], (key, got[key], src[key])


def test_t4_21_versioned_per_album_and_character():
    album = f"T421-ver {time.time_ns()}"
    cid = db.run(
        """INSERT INTO characters (scope_value, name, role, identity, created)
           VALUES (?,?,?,?,?)""",
        album, "Nyx", "rival", "a rival DJ", time.time())
    v1 = classification.save(album, {"images": [_image("p-front")]})
    v2 = classification.save(album, {"images": [_image("p-back", view="back")]})
    other = classification.save(
        album, {"images": [_image("nyx-side", view="side")]}, character_id=cid)
    assert v1["version_number"] == 1
    assert v2["version_number"] == 2
    assert other["version_number"] == 1
    assert other["character_id"] == cid
    nums = [r["version_number"] for r in classification.versions(album)]
    assert nums == [2, 1]
    proto = classification.library(album)
    assert [im["id"] for im in proto["images"]] == ["p-back"]
    nyx = classification.library(album, character_id=cid)
    assert [im["id"] for im in nyx["images"]] == ["nyx-side"]
    assert proto["id"] != nyx["id"]


def test_t4_21_sidecar_is_not_the_store():
    """A sidecar on disk is not the album library until imported."""
    album = f"T421-side {time.time_ns()}"
    tmp = tempfile.mkdtemp(prefix="t421_")
    side = os.path.join(tmp, "image-classification.json")
    json.dump({"images": [_image("sidecar-only", view="front")]}, open(side, "w"))

    lib = classification.library(album)
    assert lib["images"] == [], lib
    assert lib["version_number"] is None
    n = db.one(
        "SELECT COUNT(*) AS n FROM classification_json WHERE album=?",
        album)["n"]
    assert n == 0

    imported = classification.import_sidecar(album, side)
    assert [im["id"] for im in imported["images"]] == ["sidecar-only"]
    json.dump({"images": [_image("sidecar-mutated", view="back")]}, open(side, "w"))
    after = classification.library(album)
    assert [im["id"] for im in after["images"]] == ["sidecar-only"], after
    assert after["version_number"] == 1


def test_t4_22_db_document_wins_over_sidecar():
    album = f"T422 {time.time_ns()}"
    classification.save(album, {"images": [_image("from-db", view="front")]})
    tmp = tempfile.mkdtemp(prefix="t422_")
    side = os.path.join(tmp, "image-classification.json")
    json.dump({"images": [_image("from-file", view="back")]}, open(side, "w"))
    lib = classification.library(album)
    assert [im["id"] for im in lib["images"]] == ["from-db"]
    assert all(im["id"] != "from-file" for im in lib["images"])


def test_t4_22_only_import_sidecar_reads_a_file():
    assert _opens_in("import_sidecar") == ["import_sidecar"]
    for name in ("library", "query", "save", "latest", "versions"):
        assert _opens_in(name) == [], f"{name} opens a file"


def test_t4_21_api_roundtrip():
    album = f"T421-api-{time.time_ns()}"
    document = {"images": [
        _image("api-front", view="front", usable="identity"),
        _image("api-skip", view="side", usable="skip"),
    ]}
    with TestClient(appmod.app) as client:
        posted = client.post(f"/api/albums/{album}/classification", json=document)
        assert posted.status_code == 200, posted.text
        body = posted.json()
        assert body["version_number"] == 1
        assert {im["id"] for im in body["images"]} == {"api-front", "api-skip"}

        listed = client.get(f"/api/albums/{album}/classification")
        assert listed.status_code == 200, listed.text
        assert {im["id"] for im in listed.json()["images"]} == {
            "api-front", "api-skip"}

        filtered = client.get(
            f"/api/albums/{album}/classification", params={"usable": "skip"})
        assert filtered.status_code == 200, filtered.text
        assert [im["id"] for im in filtered.json()["images"]] == ["api-skip"]

        vers = client.get(f"/api/albums/{album}/classification/versions")
        assert vers.status_code == 200, vers.text
        assert [v["version_number"] for v in vers.json()] == [1]

        tmp = tempfile.mkdtemp(prefix="t421api_")
        side = os.path.join(tmp, "seed.json")
        json.dump({"images": [_image("imported", view="back")]}, open(side, "w"))
        seeded = client.post(
            f"/api/albums/{album}/classification/import", json={"path": side})
        assert seeded.status_code == 200, seeded.text
        assert seeded.json()["version_number"] == 2
        assert [im["id"] for im in seeded.json()["images"]] == ["imported"]
