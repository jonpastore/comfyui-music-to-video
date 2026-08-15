"""T2-30: unanchored warning fires only for leads.

docs/TRD-2 §5.3: only leads need anchors. An extra or background figure
without an anchor is not a problem and must not be reported as one.

Mutation: list every unanchored name → extra/background appear → red.
Mutation: never list anyone → lead arm red.
Mutation: fix the API list but still paint warn-tag on extras in the
scene row / page banner → HTML arm red.
"""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db


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


def _write_board(sid, slug, tier, scenes):
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    sb = {
        "title": "T",
        "album": "A",
        "version": tier,
        "character_reference": "a sleek black feline DJ",
        "album_world_reference": "neon warehouse",
        "audio_lyrics": "[Verse]\nline\n",
        "scenes": scenes,
    }
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


def _mixed_cast_board(sid, slug, tier):
    """Lead + extra + background, none anchored. Plus a bare legacy name."""
    return _write_board(sid, slug, tier, [
        _scene(1, [
            {"name": "Nyx", "role": "lead"},
            {"name": "Dancer", "role": "extra"},
            {"name": "Crowd", "role": "background"},
            "Ghost",  # legacy bare name → lead
        ]),
        _scene(2, []),
    ])


def test_t2_30_cast_api_lists_only_unanchored_leads():
    """GET .../cast unanchored is leads only. Extras/background stay out."""
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t230-cast", title="T2-30 Cast Song",
                             album="T230", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _mixed_cast_board(sid, song["slug"], "pg13")
        r = client.get(f"/api/songs/{sid}/storyboard/pg13/cast")
        assert r.status_code == 200, r.text
        payload = r.json()
        names = payload.get("unanchored") or []
        assert "Nyx" in names, payload
        assert "Ghost" in names, payload  # bare name is a legacy lead
        assert "Dancer" not in names, payload
        assert "Crowd" not in names, payload
        # full storyboard payload shares the same list
        full = client.get(f"/api/songs/{sid}/storyboard/pg13")
        assert full.status_code == 200, full.text
        assert set(full.json().get("unanchored") or []) == set(names), full.json()


def test_t2_30_anchored_lead_is_not_reported():
    """A lead with a chosen anchor does not appear in unanchored."""
    import tempfile

    with TestClient(appmod.app) as client:
        album = "T230-Anchored"
        sid = db.upsert_song("t230-anch", title="T2-30 Anchored Lead",
                             album=album, duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        db.run("""INSERT INTO characters (scope_value, name, role, identity,
                                          wardrobe, body, created)
                  VALUES (?,?,?,?,?,?,?)""",
               album, "Nyx", "lead", "", "", "", time.time())
        char = db.one("SELECT * FROM characters WHERE scope_value=? AND name=?",
                      album, "Nyx")
        path = os.path.join(tempfile.mkdtemp(prefix="t230_"), "nyx.png")
        open(path, "wb").write(b"\x89PNG\r\n\x1a\n")
        db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path,
                                       chosen, created, character_id)
                  VALUES ('album',?,?,?,?,?,?,?)""",
               album, "pg13", "front", path, 1, time.time(), char["id"])
        _write_board(sid, song["slug"], "pg13", [
            _scene(1, [
                {"name": "Nyx", "role": "lead"},
                {"name": "Dancer", "role": "extra"},
            ]),
            _scene(2, []),
        ])
        r = client.get(f"/api/songs/{sid}/storyboard/pg13/cast")
        assert r.status_code == 200, r.text
        names = r.json().get("unanchored") or []
        assert "Nyx" not in names, names
        assert "Dancer" not in names, names


def test_t2_30_html_warns_only_for_leads():
    """Page banner and scene chips cry wolf only for unanchored leads."""
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t230-html", title="T2-30 HTML Song",
                             album="T230H", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _mixed_cast_board(sid, song["slug"], "pg13")
        r = client.get(f"/songs/{sid}/storyboard/pg13")
        assert r.status_code == 200, r.text
        html = r.text
        assert "Named in scenes but not anchored" in html, html
        assert "Nyx" in html
        assert "Ghost" in html
        # banner names only the leads — extras/background must not appear
        # in the warning sentence (they may still appear as neutral chips)
        warn_start = html.find("Named in scenes but not anchored")
        warn_end = html.find("</p>", warn_start)
        assert warn_start >= 0 and warn_end > warn_start, html
        banner = html[warn_start:warn_end]
        assert "Nyx" in banner, banner
        assert "Ghost" in banner, banner
        assert "Dancer" not in banner, banner
        assert "Crowd" not in banner, banner
        # chip for an unanchored lead carries the warn styling / "no anchor"
        assert "no anchor" in html
        # Dancer chip must not say "no anchor" (would cry wolf for extras)
        # Find the Dancer tag content between its open/close span.
        import re
        tags = re.findall(
            r'<span class="tag[^"]*"[^>]*>.*?</span>', html, flags=re.S)
        dancer_tags = [t for t in tags if "Dancer" in t]
        assert dancer_tags, html
        for t in dancer_tags:
            assert "no anchor" not in t, t
            assert "warn-tag" not in t, t
        nyx_tags = [t for t in tags if "Nyx" in t]
        assert nyx_tags, html
        assert any("no anchor" in t and "warn-tag" in t for t in nyx_tags), nyx_tags
