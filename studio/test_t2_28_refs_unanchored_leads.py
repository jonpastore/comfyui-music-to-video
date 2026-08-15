"""T2-28: unanchored lead flagged before refs render.

docs/TRD-2 §5.2: a scene naming a character with no chosen anchor is
flagged before rendering. Banner / GET .../cast (T2-30) is not enough —
POST /songs/{id}/refs must 400 and write no refs job when a named lead
has no chosen sheet. Extras/background do not block enqueue.

Mutation: only paint the banner / list on cast, enqueue anyway → miss arm red.
Mutation: refuse every refs POST → match arm red.
Mutation: refuse extras/background the same as leads → extra arm red.
"""
import json
import os
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


def _png(name):
    path = os.path.join(tempfile.mkdtemp(prefix="t228_"), f"{name}.png")
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n")
    return path


def _pick_protagonist(album, tier="pg13"):
    path = _png("prot")
    db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path,
                                   chosen, created, character_id)
              VALUES ('album',?,?,?,?,?,?,NULL)""",
           album, tier, "front", path, 1, time.time())
    return path


def _pick_character(album, name, tier="pg13"):
    db.run("""INSERT INTO characters (scope_value, name, role, identity,
                                      wardrobe, body, created)
              VALUES (?,?,?,?,?,?,?)""",
           album, name, "lead", "", "", "", time.time())
    char = db.one("SELECT * FROM characters WHERE scope_value=? AND name=?",
                  album, name)
    path = _png(name.lower())
    db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path,
                                   chosen, created, character_id)
              VALUES ('album',?,?,?,?,?,?,?)""",
           album, tier, "front", path, 1, time.time(), char["id"])
    return char


def _n_refs_jobs(sid):
    return len(db.q("SELECT id FROM jobs WHERE song_id=? AND kind='refs'", sid))


def test_t2_28_unanchored_lead_refused_before_refs_enqueue():
    """Protagonist sheet alone is not enough: a named unanchored lead is 400."""
    with TestClient(appmod.app) as client:
        album = "T228-Refuse"
        sid = db.upsert_song("t228-refuse", title="T2-28 Refuse",
                             album=album, duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _pick_protagonist(album)
        _write_board(sid, song["slug"], "pg13", [
            _scene(1, [
                {"name": "Nyx", "role": "lead"},
                {"name": "Dancer", "role": "extra"},
                {"name": "Crowd", "role": "background"},
            ]),
            _scene(2, []),
        ])
        # banner/API already list the lead — that is T2-30, not this gate
        cast = client.get(f"/api/songs/{sid}/storyboard/pg13/cast")
        assert cast.status_code == 200, cast.text
        assert "Nyx" in (cast.json().get("unanchored") or []), cast.json()

        before = _n_refs_jobs(sid)
        miss = client.post(f"/songs/{sid}/refs", data={"tier": "pg13"},
                           follow_redirects=False)
        assert miss.status_code == 400, miss.text
        low = miss.text.lower()
        assert "nyx" in low, miss.text
        assert "anchor" in low or "chosen" in low, miss.text
        assert _n_refs_jobs(sid) == before, miss.text


def test_t2_28_anchored_lead_and_unanchored_extra_still_enqueues():
    """Every lead has a sheet → 303. Extra/background without sheets do not block."""
    with TestClient(appmod.app) as client:
        album = "T228-Ok"
        sid = db.upsert_song("t228-ok", title="T2-28 Ok",
                             album=album, duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        _pick_protagonist(album)
        _pick_character(album, "Nyx")
        _write_board(sid, song["slug"], "pg13", [
            _scene(1, [
                {"name": "Nyx", "role": "lead"},
                {"name": "Dancer", "role": "extra"},
                {"name": "Crowd", "role": "background"},
            ]),
            _scene(2, []),
        ])
        cast = client.get(f"/api/songs/{sid}/storyboard/pg13/cast")
        assert cast.status_code == 200, cast.text
        names = cast.json().get("unanchored") or []
        assert "Nyx" not in names, names
        assert "Dancer" not in names, names
        assert "Crowd" not in names, names

        before = _n_refs_jobs(sid)
        ok = client.post(f"/songs/{sid}/refs", data={"tier": "pg13"},
                         follow_redirects=False)
        assert ok.status_code == 303, ok.text
        assert _n_refs_jobs(sid) == before + 1, ok.text
