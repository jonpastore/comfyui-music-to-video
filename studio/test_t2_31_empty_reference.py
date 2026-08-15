"""T2-31: save refuses a storyboard whose character_reference is empty.

docs/TRD-2 §5.4: an empty lock renders a stranger in every clip while
every deterministic check still passes. Saving that board is refused.

T2-32: the refusal says identity comes from the text, not the
reference image. A message that suggests attaching a reference teaches
the wrong lesson (TRD-3 T3-28 is the QC-side pair).

Mutation: write_storyboard dumps without the check → writer arm fails.
Mutation: save_scene / _apply_scene_fields write without the check →
save arm fails.
Mutation: message names the reference image as the fix → T2-32 fails.
"""
import json
import os
import tempfile
import time

from fastapi.testclient import TestClient

import app as appmod
import db
from conftest import _real_module


def _grok():
    return _real_module("grok")


def _scene(n):
    return {"scene_number": n, "name": f"Scene {n}", "cue": "Verse",
            "duration_guidance": "5-7 sec", "story": f"story {n}",
            "camera": "wide establishing", "motion": "walk",
            "lighting": "neon", "location": f"loc {n}",
            "image_prompt": f"a rooftop at night, scene {n}",
            "video_motion_prompt": f"motion {n}", "negative_prompt": ""}


def _board(character_reference, scenes=None):
    sb = {"title": "T", "album": "A", "version": "pg13",
          "character_reference": character_reference,
          "album_world_reference": "neon warehouse",
          "audio_lyrics": "[Verse]\nline\n",
          "scenes": scenes or [_scene(1), _scene(2)]}
    return sb


def _write_board(sid, slug, tier, character_reference):
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    sb = _board(character_reference)
    json_path = os.path.join(outdir, f"{slug}_{tier}.json")
    md_path = os.path.join(outdir, f"{slug}_{tier}.md")
    json.dump(sb, open(json_path, "w"))
    open(md_path, "w").write("# storyboard\n")
    db.run("""INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created)
              VALUES (?,?,?,?,?,?)
              ON CONFLICT(song_id, tier) DO UPDATE SET json_path=excluded.json_path,
              md_path=excluded.md_path, scene_count=excluded.scene_count""",
           sid, tier, json_path, md_path, len(sb["scenes"]), time.time())
    return json_path


def _assert_t2_32_message(text):
    low = text.lower()
    assert "text" in low, text
    assert "reference image" in low or "not the reference" in low, text
    assert "identity" in low, text
    assert "swap" not in low
    assert "attach" not in low
    assert "replace the reference" not in low


def test_t2_31_write_storyboard_refuses_empty_character_reference():
    """Real writer raises before creating files. Whitespace is empty."""
    grok = _grok()
    tmp = tempfile.mkdtemp(prefix="t231_")
    for empty in ("", "   ", None):
        sb = _board(empty)
        try:
            grok.write_storyboard(sb, tmp, "t231", "pg13")
            raise AssertionError(f"write_storyboard accepted {empty!r}")
        except ValueError as e:
            _assert_t2_32_message(str(e))
            assert "stranger" in str(e).lower() or "empty" in str(e).lower(), e
    missing = _board("filled")
    del missing["character_reference"]
    try:
        grok.write_storyboard(missing, tmp, "t231", "pg13")
        raise AssertionError("write_storyboard accepted a missing key")
    except ValueError as e:
        _assert_t2_32_message(str(e))
    assert not os.path.exists(os.path.join(tmp, "t231_pg13.json"))
    assert not os.path.exists(os.path.join(tmp, "t231_pg13.md"))


def test_t2_31_write_storyboard_accepts_a_filled_character_reference():
    """Positive half: a refusal-only check stays green when the writer is deleted."""
    grok = _grok()
    tmp = tempfile.mkdtemp(prefix="t231ok_")
    json_path, md_path = grok.write_storyboard(
        _board("a sleek black feline DJ"), tmp, "t231ok", "pg13")
    written = json.load(open(json_path))
    assert written["character_reference"] == "a sleek black feline DJ"
    assert os.path.getsize(md_path) > 0


def test_t2_31_save_scene_refuses_empty_character_reference():
    """POST scene save refuses and does not write. Filled lock still saves."""
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t231-empty", title="T2-31 Save Song",
                             album="T231", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        json_path = _write_board(sid, song["slug"], "pg13", "")
        before = json.load(open(json_path))

        refused = client.post(
            f"/songs/{sid}/storyboard/pg13/scene/1",
            data={"image_prompt": "a neon stairwell, rewritten"})
        assert refused.status_code == 400, refused.text
        _assert_t2_32_message(refused.text)
        after = json.load(open(json_path))
        assert after["scenes"][0]["image_prompt"] == before["scenes"][0]["image_prompt"]
        assert after["character_reference"] == ""

        json.dump(_board("a sleek black feline DJ"), open(json_path, "w"))
        ok = client.post(
            f"/songs/{sid}/storyboard/pg13/scene/1",
            data={"image_prompt": "a neon stairwell, rewritten"})
        assert ok.status_code == 200, ok.text
        written = json.load(open(json_path))
        assert written["scenes"][0]["image_prompt"] == "a neon stairwell, rewritten"
        assert written["character_reference"] == "a sleek black feline DJ"
        assert written["scenes"][1]["image_prompt"] == before["scenes"][1]["image_prompt"]


def test_t2_31_api_scene_edit_refuses_empty_character_reference():
    """JSON scene edit is the same save; a form-only check would miss it."""
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t231-api", title="T2-31 API Song",
                             album="T231", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        json_path = _write_board(sid, song["slug"], "pg13", "   ")
        before = json.load(open(json_path))

        refused = client.post(
            f"/api/songs/{sid}/storyboard/pg13/scene/1",
            json={"image_prompt": "a rewritten alley"})
        assert refused.status_code == 400, refused.text
        _assert_t2_32_message(refused.text)
        after = json.load(open(json_path))
        assert after["scenes"][0]["image_prompt"] == before["scenes"][0]["image_prompt"]
