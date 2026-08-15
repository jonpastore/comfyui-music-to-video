"""T2-22: save refuses a storyboard carrying another tier's wording.

docs/TRD-2 §4.4: the generated board's guardrail field is verbatim
tiers.compose_guardrail(tier). A board that carries another tier's
clause is refused at save.

Both arms use the SAME recorded model response. The clause is not in
that fixture, so the only way it lands on the board is if _compose
stamps compose_guardrail(tier).

Mutation: _compose does not stamp guardrail → generation arm fails.
Mutation: stamp the passed-in guardrail argument → generation arm fails
when that argument is not compose_guardrail(tier).
Mutation: save_scene writes without the foreign-clause check → save arm
fails.
"""
import json
import os
import time

import httpx
from fastapi.testclient import TestClient

import app as appmod
import db
import tiers
from conftest import _real_module


SCENES = [
    {"scene_number": 1, "name": "Verse 1", "cue": "Verse",
     "duration_guidance": "4-8 sec", "story": "s1", "camera": "wide",
     "motion": "walk", "lighting": "neon", "location": "alley",
     "image_prompt": "a rooftop 1", "video_motion_prompt": "m1",
     "negative_prompt": "blurry"},
    {"scene_number": 2, "name": "Chorus 1", "cue": "Chorus",
     "duration_guidance": "4-8 sec", "story": "s2", "camera": "close",
     "motion": "walk", "lighting": "amber", "location": "roof",
     "image_prompt": "a rooftop 2", "video_motion_prompt": "m2",
     "negative_prompt": "blurry"},
]


def _grok():
    return _real_module("grok")


def _generate(grok, tier, guardrail):
    lyrics = "[A]\na\n[B]\nb\n"
    song = {"title": "T", "album": "A", "slug": "t", "duration": 16.0, "genre": "pop"}
    orig = httpx.stream
    orig_key = grok._api_key
    orig_ex = grok._exemplar

    class _Resp:
        status_code = 200

        def iter_lines(self):
            body = json.dumps({"scenes": SCENES})
            yield "data: " + json.dumps({"choices": [{"delta": {"content": body}}]})
            yield "data: [DONE]"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    grok._api_key = lambda: "test-key"
    grok._exemplar = lambda: ({"scenes": []}, "", False)
    httpx.stream = lambda *a, **k: _Resp()
    try:
        return grok.generate_storyboard(
            lyrics, tier, guardrail, "neon lock", song,
            model="grok-test", scene_seconds=8.0)
    finally:
        httpx.stream = orig
        grok._api_key = orig_key
        grok._exemplar = orig_ex


def _scene(n):
    return {"scene_number": n, "name": f"Scene {n}", "cue": "Verse",
            "duration_guidance": "5-7 sec", "story": f"story {n}",
            "camera": "wide establishing", "motion": "walk",
            "lighting": "neon", "location": f"loc {n}",
            "image_prompt": f"a rooftop at night, scene {n}",
            "video_motion_prompt": f"motion {n}", "negative_prompt": ""}


def _write_board(sid, slug, tier, scenes, extra=None):
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    sb = {"title": "T", "album": "A", "version": tier,
          "character_reference": "a sleek black feline DJ",
          "album_world_reference": "neon warehouse",
          "audio_lyrics": "[Verse]\nline\n", "scenes": scenes}
    if extra:
        sb.update(extra)
    json_path = os.path.join(outdir, f"{slug}_{tier}.json")
    md_path = os.path.join(outdir, f"{slug}_{tier}.md")
    json.dump(sb, open(json_path, "w"))
    open(md_path, "w").write("# storyboard\n")
    db.run("""INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created)
              VALUES (?,?,?,?,?,?)
              ON CONFLICT(song_id, tier) DO UPDATE SET json_path=excluded.json_path,
              md_path=excluded.md_path, scene_count=excluded.scene_count""",
           sid, tier, json_path, md_path, len(scenes), time.time())
    return json_path


def test_t2_22_generated_guardrail_is_compose_guardrail_verbatim():
    """The field is compose_guardrail(tier), not the argument and not another tier."""
    tiers.ensure_builtins()
    grok = _grok()
    want_xxx = tiers.compose_guardrail("xxx")
    want_pg13 = tiers.compose_guardrail("pg13")
    assert want_xxx != want_pg13
    assert want_xxx not in json.dumps(SCENES)
    assert want_pg13 not in json.dumps(SCENES)

    xxx = _generate(grok, "xxx", "NOT-THE-CLAUSE")
    pg13 = _generate(grok, "pg13", "NOT-THE-CLAUSE")

    assert xxx["guardrail"] == want_xxx, xxx.get("guardrail")
    assert pg13["guardrail"] == want_pg13, pg13.get("guardrail")
    assert xxx["guardrail"] != pg13["guardrail"]
    assert "NOT-THE-CLAUSE" not in xxx["guardrail"]
    assert "NOT-THE-CLAUSE" not in pg13["guardrail"]


def test_t2_22_save_refuses_another_tiers_wording():
    """POST scene save refuses pg13's clause on an xxx board and does not write."""
    tiers.ensure_builtins()
    foreign = tiers.tier_text("pg13")
    assert "Mainstream" in foreign
    own = tiers.tier_text("xxx")
    assert foreign != own

    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t222-foreign", title="T2-22 Save Song",
                             album="T222", duration=16.0)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        json_path = _write_board(sid, song["slug"], "xxx", [_scene(1), _scene(2)])
        before = json.load(open(json_path))

        refused = client.post(
            f"/songs/{sid}/storyboard/xxx/scene/1",
            data={"image_prompt": f"a neon stairwell. {foreign}"})
        assert refused.status_code == 400, refused.text
        assert "pg13" in refused.text.lower() or "wording" in refused.text.lower()
        after = json.load(open(json_path))
        assert after["scenes"][0]["image_prompt"] == before["scenes"][0]["image_prompt"]

        ok = client.post(
            f"/songs/{sid}/storyboard/xxx/scene/1",
            data={"image_prompt": "a neon stairwell, rewritten"})
        assert ok.status_code == 200, ok.text
        written = json.load(open(json_path))
        assert written["scenes"][0]["image_prompt"] == "a neon stairwell, rewritten"
        assert written["scenes"][1]["image_prompt"] == before["scenes"][1]["image_prompt"]
