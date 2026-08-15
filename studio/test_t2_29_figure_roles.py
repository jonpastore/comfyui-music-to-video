"""T2-29: every named scene figure carries lead / extra / background.

docs/TRD-2 §5.3: generation classifies each named figure. Presence and
classification, not use (T2-30 is the unanchored-lead warning).

Mutation: _compose still coerces characters to strings / drops dicts →
compose arm fails.
Mutation: write_storyboard dumps a figure with no role or a free-text
role → writer arm fails.
Mutation: GET .../cast returns names without role → API arm fails.
"""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db
from conftest import _real_module


ROLES = ("lead", "extra", "background")


def _grok():
    return _real_module("grok")


def _scene(n, characters=None):
    return {
        "scene_number": n,
        "name": f"Scene {n}",
        "cue": "Verse",
        "duration_guidance": "5-7 sec",
        "story": f"story {n}",
        "camera": "wide establishing",
        "motion": "walk",
        "lighting": "neon",
        "location": f"loc {n}",
        "image_prompt": f"a rooftop at night, scene {n}",
        "video_motion_prompt": f"motion {n}",
        "negative_prompt": "",
        "characters": characters if characters is not None else [],
    }


def _board(scenes):
    return {
        "title": "T",
        "album": "A",
        "version": "pg13",
        "character_reference": "a sleek black feline DJ",
        "album_world_reference": "neon warehouse",
        "audio_lyrics": "[Verse]\nline\n",
        "scenes": scenes,
    }


def _write_board(sid, slug, tier, scenes):
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    sb = _board(scenes)
    json_path = os.path.join(outdir, f"{slug}_{tier}.json")
    md_path = os.path.join(outdir, f"{slug}_{tier}.md")
    json.dump(sb, open(json_path, "w"))
    open(md_path, "w").write("# storyboard\n")
    db.run(
        """INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(song_id, tier) DO UPDATE SET json_path=excluded.json_path,
           md_path=excluded.md_path, scene_count=excluded.scene_count""",
        sid, tier, json_path, md_path, len(scenes), time.time())
    return json_path


def test_t2_29_compose_keeps_classified_figures():
    """Dict figures survive compose. String coercion hid the role."""
    grok = _grok()
    scenes = [
        _scene(1, [
            {"name": "Nyx", "role": "lead"},
            {"name": "Dancer", "role": "extra"},
            {"name": "Crowd", "role": "background"},
        ]),
        _scene(2, []),
    ]
    board = grok._compose(
        {"title": "T", "album": "A", "slug": "t", "duration": 16.0, "genre": "pop"},
        "pg13", "TEST GUARD", "neon lock", "[Verse]\nline\n",
        scenes, 2, 8.0, character_reference="a sleek black feline DJ")
    figs = board["scenes"][0]["characters"]
    assert all(isinstance(f, dict) for f in figs), figs
    by_name = {f["name"]: f["role"] for f in figs}
    assert by_name == {"Nyx": "lead", "Dancer": "extra", "Crowd": "background"}, figs
    assert set(by_name.values()) == set(ROLES)
    assert board["scenes"][1]["characters"] == []


def test_t2_29_write_storyboard_refuses_unclassified_and_accepts_the_three_roles():
    """A named figure with no role, or a free-text role, does not write."""
    import tempfile

    grok = _grok()
    tmp = tempfile.mkdtemp(prefix="t229_")
    missing = _board([_scene(1, [{"name": "Nyx"}]), _scene(2, [])])
    try:
        grok.write_storyboard(missing, tmp, "t229", "pg13")
        raise AssertionError("write_storyboard accepted a named figure with no role")
    except ValueError as e:
        text = str(e).lower()
        assert "nyx" in text, e
        assert "role" in text, e
        assert "lead" in text and "extra" in text and "background" in text, e
    assert not os.path.exists(os.path.join(tmp, "t229_pg13.json"))

    bad = _board([_scene(1, [{"name": "Nyx", "role": "antagonist"}]), _scene(2, [])])
    try:
        grok.write_storyboard(bad, tmp, "t229", "pg13")
        raise AssertionError("write_storyboard accepted a free-text role")
    except ValueError as e:
        assert "antagonist" in str(e).lower() or "role" in str(e).lower(), e
    assert not os.path.exists(os.path.join(tmp, "t229_pg13.json"))

    ok = _board([_scene(1, [
        {"name": "Nyx", "role": "lead"},
        {"name": "Dancer", "role": "extra"},
        {"name": "Crowd", "role": "background"},
    ]), _scene(2, [])])
    json_path, md_path = grok.write_storyboard(ok, tmp, "t229ok", "pg13")
    written = json.load(open(json_path))
    by_name = {f["name"]: f["role"] for f in written["scenes"][0]["characters"]}
    assert by_name == {"Nyx": "lead", "Dancer": "extra", "Crowd": "background"}
    assert os.path.getsize(md_path) > 0


def test_t2_29_cast_api_returns_role_on_every_named_figure():
    """GET .../cast carries the classification. Names-only would pass T6-A1."""
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t229-cast", title="T2-29 Cast Song",
                             album="T229", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _write_board(sid, song["slug"], "pg13", [
            _scene(1, [
                {"name": "Nyx", "role": "lead"},
                {"name": "Dancer", "role": "extra"},
                {"name": "Crowd", "role": "background"},
            ]),
            _scene(2, []),
        ])
        r = client.get(f"/api/songs/{sid}/storyboard/pg13/cast")
        assert r.status_code == 200, r.text
        payload = r.json()
        scenes = payload.get("scenes") or []
        assert scenes, payload
        one = next(s for s in scenes if s.get("num") == 1)
        figs = one.get("cast") or []
        assert figs, one
        by_name = {f["name"]: f["role"] for f in figs}
        assert by_name == {"Nyx": "lead", "Dancer": "extra", "Crowd": "background"}, figs
        for f in figs:
            assert f["role"] in ROLES, f
        two = next(s for s in scenes if s.get("num") == 2)
        assert two.get("cast") == []


def test_t2_29_scene_cast_still_resolves_named_figures():
    """Dict figures must still select anchors. String coercion hid this.

    Cast slots are leads only (see test_cast_slots_*): background must not
    take image2/3 even when a sheet is present. Bare names stay legacy leads.
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import build_refs

    scene = {"characters": [
        {"name": "Nyx", "role": "lead"},
        {"name": "Crowd", "role": "background"},
        "Ghost",
    ]}
    cast = {
        "Nyx": {"image": "nyx.png", "desc": "a white-furred rival"},
        "Ghost": {"image": "ghost.png", "desc": "a grey tom"},
        "Crowd": {"image": "crowd.png", "desc": "background"},
    }
    got = build_refs.scene_cast(scene, cast)
    assert [n for n, _, _ in got] == ["Nyx", "Ghost"], got
