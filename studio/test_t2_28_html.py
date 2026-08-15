"""T2-28-html: storyboard Generate refs is marked, not disabled.

docs/TRD-2 T2-28 + UIUX §7a.3 / plan-panel: a control the backend cannot
honour is marked (button.blocked), never disabled, and the reason names
the unanchored lead in the plan panel above it. Banner alone is not this.

Mutation: disable the button → disabled arm red.
Mutation: block without naming the lead in .plan-blocker → name arm red.
Mutation: list an extra as a blocker → extra arm red.
Mutation: omit plan-panel / Generate refs on the storyboard page → present arm red.
"""
import json
import os
import re
import tempfile
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


def _album_anchor(album, tier):
    """Protagonist chosen sheet so the missing-protagonist gate is not the
    only blocker under test — T2-28 is about a named lead without a sheet."""
    path = os.path.join(tempfile.mkdtemp(prefix="t228_"), "prot.png")
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n")
    db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path,
                                   chosen, created, character_id)
              VALUES ('album',?,?,?,?,?,?,NULL)""",
           album, tier, "front", path, 1, time.time())


def _refs_form(html):
    """The Generate refs control on the storyboard page (not the song page)."""
    # Prefer the form that posts to /refs for this song and lives with a plan panel.
    m = re.search(
        r'<form[^>]*action="[^"]*/refs"[^>]*>.*?</form>',
        html, flags=re.S | re.I)
    assert m, "storyboard page has no Generate refs form posting to /refs"
    return m.group(0)


def _generate_btn(form_html):
    m = re.search(
        r'<button\b([^>]*)>\s*Generate refs\s*</button>',
        form_html, flags=re.S | re.I)
    assert m, form_html
    return m.group(0), m.group(1)


def test_t2_28_html_generate_refs_marked_names_unanchored_lead():
    """Unanchored lead: button.blocked, not disabled; plan-blocker names them."""
    with TestClient(appmod.app) as client:
        album = "T228H"
        sid = db.upsert_song("t228-html", title="T2-28 HTML Song",
                             album=album, duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _album_anchor(album, "pg13")
        _write_board(sid, song["slug"], "pg13", [
            _scene(1, [
                {"name": "Nyx", "role": "lead"},
                {"name": "Dancer", "role": "extra"},
                {"name": "Crowd", "role": "background"},
            ]),
            _scene(2, []),
        ])
        r = client.get(f"/songs/{sid}/storyboard/pg13")
        assert r.status_code == 200, r.text
        html = r.text
        form = _refs_form(html)
        assert "plan-panel" in form or "plan-panel" in html, html
        # plan-blocker names the unanchored lead
        blockers = re.findall(
            r'class="plan-blocker"[^>]*>(.*?)</p>', html, flags=re.S)
        blocker_text = " ".join(b.strip() for b in blockers)
        assert "Nyx" in blocker_text, (blockers, html)
        assert "Dancer" not in blocker_text, blockers
        assert "Crowd" not in blocker_text, blockers
        btn, attrs = _generate_btn(form if "Generate refs" in form else html)
        assert "disabled" not in attrs.lower().split() and \
            not re.search(r'\bdisabled\b', attrs), (
                "Generate refs must be marked, never disabled: " + btn)
        assert re.search(r'\bblocked\b', attrs), (
            "Generate refs must carry button.blocked when a lead is unanchored: "
            + btn)


def test_t2_28_html_anchored_lead_is_not_blocked():
    """When every named lead has a chosen sheet, Generate refs is not blocked."""
    with TestClient(appmod.app) as client:
        album = "T228H-ok"
        sid = db.upsert_song("t228-html-ok", title="T2-28 HTML Ok",
                             album=album, duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _album_anchor(album, "pg13")
        db.run("""INSERT INTO characters (scope_value, name, role, identity,
                                          wardrobe, body, created)
                  VALUES (?,?,?,?,?,?,?)""",
               album, "Nyx", "lead", "", "", "", time.time())
        char = db.one("SELECT * FROM characters WHERE scope_value=? AND name=?",
                      album, "Nyx")
        path = os.path.join(tempfile.mkdtemp(prefix="t228n_"), "nyx.png")
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
        r = client.get(f"/songs/{sid}/storyboard/pg13")
        assert r.status_code == 200, r.text
        html = r.text
        form = _refs_form(html)
        btn, attrs = _generate_btn(form if "Generate refs" in form else html)
        assert not re.search(r'\bblocked\b', attrs), btn
        assert "disabled" not in attrs.lower().split() and \
            not re.search(r'\bdisabled\b', attrs), btn
        blockers = re.findall(
            r'class="plan-blocker"[^>]*>(.*?)</p>', html, flags=re.S)
        assert not any("Nyx" in b for b in blockers), blockers


def _n_refs_jobs(sid):
    return len(db.q("SELECT id FROM jobs WHERE song_id=? AND kind='refs'", sid))


def test_t2_28_post_refs_refuses_unanchored_lead():
    """POST /songs/{id}/refs 400s and writes no refs job when a lead lacks a sheet.

    Mutation: only paint the banner / plan-panel, enqueue anyway → red.
    Mutation: refuse extras the same way → extra arm would fail a clean board
    that only names unanchored extras (not asserted here; T2-30).
    """
    with TestClient(appmod.app) as client:
        album = "T228-post"
        sid = db.upsert_song("t228-post", title="T2-28 POST Song",
                             album=album, duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _album_anchor(album, "pg13")
        _write_board(sid, song["slug"], "pg13", [
            _scene(1, [
                {"name": "Nyx", "role": "lead"},
                {"name": "Dancer", "role": "extra"},
            ]),
            _scene(2, []),
        ])
        before = _n_refs_jobs(sid)
        miss = client.post(f"/songs/{sid}/refs", data={"tier": "pg13"},
                           follow_redirects=False)
        assert miss.status_code == 400, miss.text
        assert "Nyx" in miss.text, miss.text
        assert _n_refs_jobs(sid) == before

        # extras alone do not block: lead anchored, extra unanchored → enqueues
        db.run("""INSERT INTO characters (scope_value, name, role, identity,
                                          wardrobe, body, created)
                  VALUES (?,?,?,?,?,?,?)""",
               album, "Nyx", "lead", "", "", "", time.time())
        char = db.one("SELECT * FROM characters WHERE scope_value=? AND name=?",
                      album, "Nyx")
        path = os.path.join(tempfile.mkdtemp(prefix="t228p_"), "nyx.png")
        open(path, "wb").write(b"\x89PNG\r\n\x1a\n")
        db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path,
                                       chosen, created, character_id)
                  VALUES ('album',?,?,?,?,?,?,?)""",
               album, "pg13", "front", path, 1, time.time(), char["id"])
        before_ok = _n_refs_jobs(sid)
        ok = client.post(f"/songs/{sid}/refs", data={"tier": "pg13"},
                         follow_redirects=False)
        assert ok.status_code == 303, ok.text
        assert _n_refs_jobs(sid) == before_ok + 1
