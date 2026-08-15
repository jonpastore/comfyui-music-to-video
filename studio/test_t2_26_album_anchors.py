"""T2-26: storyboard JSON returns album anchors per character.

docs/TRD-2 §5.2: GET /api/songs/{id}/storyboard/{tier} returns the
album's chosen anchor images grouped per character, so any client can
show them at the top of the page. Payload presence only — the HTML
strip is not this criterion (T2-27 is per-scene refs).

Mutation: omit anchors → red.
Mutation: return a flat list of images with no character grouping → red.
Mutation: return only the protagonist when a cast member is chosen → red.
Mutation: include an unchosen candidate, another album, or another tier → red.
"""
import json
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import tiers


def _scene(n, characters=None):
    return {
        "scene_number": n,
        "name": f"Scene {n}",
        "cue": "Verse",
        "duration_guidance": "5 sec",
        "story": f"story {n}",
        "camera": "wide",
        "motion": "walk",
        "lighting": "neon",
        "location": f"loc {n}",
        "image_prompt": f"a rooftop at night, scene {n}",
        "video_motion_prompt": f"motion {n}",
        "negative_prompt": "",
        "characters": list(characters or []),
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


def _character(album, name):
    db.run("""INSERT INTO characters (scope_value, name, role, identity, wardrobe, body, created)
              VALUES (?,?,?,?,?,?,?)""",
           album, name, "lead", "", "", "", time.time())
    return db.one("SELECT * FROM characters WHERE scope_value=? AND name=?", album, name)


def _anchor(album, tier, path, view="front", chosen=1, character_id=None):
    db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen, created,
                                    character_id)
              VALUES ('album',?,?,?,?,?,?,?)""",
           album, tier, view, path, chosen, time.time(), character_id)


def _by_character(payload):
    """Index the T2-26 groups. A flat list of images has no character key."""
    groups = payload.get("anchors")
    assert isinstance(groups, list), payload
    out = {}
    for group in groups:
        assert isinstance(group, dict), group
        name = group.get("character")
        assert name, group
        assert name not in out, f"duplicate character group: {name}"
        images = group.get("images")
        assert isinstance(images, list) and images, group
        out[name] = group
    return out


def test_t2_26_storyboard_json_returns_album_anchors_per_character():
    """Two characters' chosen sheets are grouped; noise is not."""
    tiers.ensure_builtins()
    album = "T226 Album"
    other = "T226 Other Album"
    with TestClient(appmod.app) as client:
        sid = db.upsert_song(
            "t226-anchors", title="T2-26 Anchor Song",
            album=album, duration=24.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        nyx = _character(album, "Nyx")
        _character(album, "Ghost")
        _anchor(album, "pg13", "/tmp/t226_prot_front.png", view="front")
        _anchor(album, "pg13", "/tmp/t226_prot_back.png", view="back")
        _anchor(album, "pg13", "/tmp/t226_nyx_front.png", view="front",
                character_id=nyx["id"])
        _anchor(album, "pg13", "/tmp/t226_nyx_old.png", view="front",
                chosen=0, character_id=nyx["id"])
        _anchor(album, "r", "/tmp/t226_prot_r.png", view="front")
        _anchor(other, "pg13", "/tmp/t226_other.png", view="front")

        _write_board(sid, song["slug"], "pg13",
                     [_scene(1, ["Nyx", "Ghost"]), _scene(2)])

        r = client.get(f"/api/songs/{sid}/storyboard/pg13")
        assert r.status_code == 200, r.text
        payload = r.json()
        groups = _by_character(payload)
        assert set(groups) == {"protagonist", "Nyx"}, groups
        assert [g["character"] for g in payload["anchors"]][0] == "protagonist"

        prot = {img["view"]: img for img in groups["protagonist"]["images"]}
        assert set(prot) == {"front", "back"}, prot
        assert prot["front"]["path"] == "/tmp/t226_prot_front.png"
        assert prot["back"]["path"] == "/tmp/t226_prot_back.png"
        assert groups["protagonist"].get("character_id") is None

        nyx_imgs = groups["Nyx"]["images"]
        assert len(nyx_imgs) == 1, nyx_imgs
        assert nyx_imgs[0]["path"] == "/tmp/t226_nyx_front.png"
        assert nyx_imgs[0]["view"] == "front"
        assert groups["Nyx"].get("character_id") == nyx["id"]

        paths = [img["path"] for g in payload["anchors"] for img in g["images"]]
        assert "/tmp/t226_nyx_old.png" not in paths
        assert "/tmp/t226_prot_r.png" not in paths
        assert "/tmp/t226_other.png" not in paths

        for img in prot.values():
            assert img.get("url"), img
            assert img["url"].startswith("/media/"), img
        assert nyx_imgs[0]["url"].startswith("/media/"), nyx_imgs[0]

        assert "Ghost" not in groups
