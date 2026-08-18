"""T2-53 / T7-22: one location plate per location key.

docs/TRD-2 §6b: two scenes with the same key load the same path; a
generated plate is stored. Unset / studio has no plate. A character
sheet or anchor_ref is not a plate.

docs/TRD-7 T7-22: a location plate is never build_refs --anchor / image1.

Mutation: two scenes with the same key load two different plates → red.
Mutation: a character sheet path is stored as the location plate → red.
Mutation: a location plate path is passed as --anchor → red.
"""
import ast
import json
import os
import sys
import tempfile
import time

import pytest

import db
import location_plates

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import build_refs


def _fastapi_imports(path):
    tree = ast.parse(open(path).read())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split(".")[0])
    return [n for n in names if n == "fastapi"]


def _png(name):
    path = os.path.join(tempfile.mkdtemp(prefix="t253_"), f"{name}.png")
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n")
    return path


def test_t2_53_location_plates_imports_nothing_from_fastapi():
    assert _fastapi_imports(location_plates.__file__) == []


def test_t2_53_table_exists_in_sqlite():
    row = db.one(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='location_plates'")
    assert row, "location_plates table missing"


def test_t2_53_reuse_same_key_same_path_unset_studio_has_none():
    """Two scenes with the same key load the same path. studio/unset do not."""
    stamp = f"t253-{time.time_ns()}"
    album = f"T253 {stamp}"
    sid = db.upsert_song(stamp, title="T2-53 Song", album=album)
    alley = _png("alley")
    dock = _png("dock")
    row = location_plates.set_plate("album", album, "Neon  Alley", alley)
    assert row["path"] == alley
    assert row["location_key"] == "neon alley"
    location_plates.set_plate("song", str(sid), "dock", dock)

    scenes = [
        {"scene_number": 1, "location": "neon alley"},
        {"scene_number": 2, "location": "Neon Alley"},
        {"scene_number": 3, "location": "studio"},
        {"scene_number": 4, "location": "unset"},
        {"scene_number": 5, "location": ""},
        {"scene_number": 6, "location": "dock"},
    ]
    album_got = location_plates.for_scenes("album", album, scenes)
    assert album_got[1] == alley
    assert album_got[2] == alley
    assert album_got[1] == album_got[2]
    assert 3 not in album_got
    assert 4 not in album_got
    assert 5 not in album_got
    assert location_plates.get_plate("album", album, "studio") is None
    assert location_plates.get_plate("album", album, "unset") is None
    assert location_plates.get_plate("album", album, "") is None
    assert location_plates.get_plate("song", str(sid), "dock") == dock
    assert location_plates.get_plate("album", album, "dock") is None
    with pytest.raises(ValueError, match="unset/studio"):
        location_plates.set_plate("album", album, "studio", alley)
    with pytest.raises(ValueError, match="unset/studio"):
        location_plates.set_plate("album", album, "unset", alley)


def test_t2_53_refuses_character_sheet_and_anchor_ref_as_plate():
    """A character sheet or anchor_ref path is not stored as a plate."""
    stamp = f"t253-sheet-{time.time_ns()}"
    album = f"T253 {stamp}"
    sheet = _png("front_sheet")
    ref = _png("anchor_ref")
    other = _png("alley_ok")
    db.run(
        """INSERT INTO anchors (scope_kind, scope_value, tier, view, path,
                               chosen, created)
           VALUES ('album',?,?,?,?,?,?)""",
        album, "r", "front", sheet, 1, time.time())
    db.run(
        """INSERT INTO assets (song_id, kind, path, meta_json, created)
           VALUES (NULL, 'anchor_ref', ?, ?, ?)""",
        ref, json.dumps({"album": album, "role": "pose"}), time.time())
    with pytest.raises(ValueError, match="character sheet|anchor_ref"):
        location_plates.set_plate("album", album, "neon alley", sheet)
    with pytest.raises(ValueError, match="character sheet|anchor_ref"):
        location_plates.set_plate("album", album, "neon alley", ref)
    assert location_plates.get_plate("album", album, "neon alley") is None
    location_plates.set_plate("album", album, "neon alley", other)
    assert location_plates.get_plate("album", album, "neon alley") == other


def test_t7_22_build_refs_refuses_location_plate_as_anchor(tmp_path, monkeypatch):
    """A stored location plate cannot be --anchor or workflow image1."""
    stamp = f"t253-id-{time.time_ns()}"
    album = f"T253 {stamp}"
    plate = _png("loc_plate")
    keeper = _png("keeper")
    location_plates.set_plate("album", album, "rooftop", plate)
    scene = {"image_prompt": "rooftop neon", "scene_number": 1,
             "negative_prompt": ""}
    with pytest.raises(ValueError, match="location plate"):
        build_refs.workflow(scene, plate, None, "empty", 1280, 720, 7000)
    wf = build_refs.workflow(scene, keeper, plate, "empty", 1280, 720, 7000)
    assert wf["7"]["inputs"]["image"] == keeper
    assert wf["9"]["inputs"]["image"] == plate
    assert wf["11"]["inputs"]["image1"] == ["8", 0]

    sb = tmp_path / "sb.json"
    json.dump({
        "scenes": [{
            "scene_number": 1, "name": "s1", "image_prompt": "rooftop",
            "negative_prompt": "", "characters": [],
        }],
        "character_reference": "black feline woman",
        "version": "r",
    }, open(sb, "w"))
    out = tmp_path / "wf"
    out.mkdir()
    monkeypatch.setattr(sys, "argv", [
        "build_refs.py", "--storyboard", str(sb), "--slug", "demo",
        "--anchor", plate, "--outdir", str(out),
    ])
    with pytest.raises(ValueError, match="location plate"):
        build_refs.main()
    assert list(out.iterdir()) == []

    anchors = tmp_path / "anchors.json"
    json.dump({"1": plate}, open(anchors, "w"))
    monkeypatch.setattr(sys, "argv", [
        "build_refs.py", "--storyboard", str(sb), "--slug", "demo",
        "--anchor", keeper, "--anchors", str(anchors),
        "--outdir", str(out),
    ])
    with pytest.raises(ValueError, match="location plate"):
        build_refs.main()
    assert list(out.iterdir()) == []
