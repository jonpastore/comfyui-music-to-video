"""T6-A4 / storyboard: meter fill_pct is service-owned, not template-computed.

docs/TRD-6 §0.1: no template computes. Stub storyboard_service.payload with a
fill_pct that is not intent/rendered*100 of the fixture; the HTML page shows
that value unmodified as the meter width. A template that recomputes from
coverage.intent / coverage.rendered is a second implementation.

Distinctive numbers so two empty answers cannot pass.
"""
import json
import os
import re
import time

from fastapi.testclient import TestClient

import app as appmod
import build_song
import db
import storyboard_service
import tiers

# Distinctive fixture — same shape as T6-A2 so the T6-A2 numbers stay on the page.
_SONG_LENGTH = 120.0
_SCENE_GUIDANCE = 17.0  # five scenes → scene_time 85
_N_SCENES = 5
_SCENE_TIME = _SCENE_GUIDANCE * _N_SCENES  # 85.0
_SCENE_SECONDS = 15.0
_CLIP_SECONDS = build_song.clip_seconds(_SCENE_SECONDS)
# Stub fill that is NOT min(100, intent/rendered*100). intent 85 / rendered
# from real payload is not 37.5% — recomputing in the template goes red.
_STUB_FILL_PCT = 37.5
_STUB_SCENE_COUNT = 99


def _scene(n, guidance):
    return {
        "scene_number": n,
        "name": f"Scene {n}",
        "cue": "Verse",
        "duration_guidance": guidance,
        "story": f"story {n}",
        "camera": "wide",
        "motion": "walk",
        "lighting": "neon",
        "location": f"loc {n}",
        "image_prompt": f"a rooftop at night, scene {n}",
        "video_motion_prompt": f"motion {n}",
        "negative_prompt": "",
        "characters": [],
    }


def _write_board(sid, slug, tier, scenes, scene_seconds):
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
        """INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count,
                                    scene_seconds, created)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(song_id, tier) DO UPDATE SET json_path=excluded.json_path,
           md_path=excluded.md_path, scene_count=excluded.scene_count,
           scene_seconds=excluded.scene_seconds""",
        sid, tier, json_path, md_path, len(scenes), scene_seconds, time.time())
    return json_path


def _attr(page, name):
    m = re.search(rf'data-{name}="([^"]*)"', page)
    assert m, f"missing data-{name} on storyboard page: {page[:500]}"
    return m.group(1)


def _meter_width(page):
    m = re.search(
        r'id="storyboard-meter".*?class="meter-fill"[^>]*style="width:\s*([^"%]+)\s*%"',
        page, re.DOTALL)
    assert m, f"missing meter-fill width on storyboard page: {page[:800]}"
    return m.group(1).strip()


def test_t6_a4_storyboard_page_shows_stubbed_fill_pct_unmodified(monkeypatch):
    """Stub fill_pct=37.5; page shows it. Recomputed intent/rendered width is absent."""
    tiers.ensure_builtins()
    assert _CLIP_SECONDS != _SCENE_SECONDS
    assert _SCENE_TIME != _SONG_LENGTH
    assert _STUB_SCENE_COUNT != _N_SCENES

    with TestClient(appmod.app) as client:
        sid = db.upsert_song(
            "t6a4-sb", title="T6-A4 Storyboard Song",
            album="T6A4SB", duration=_SONG_LENGTH)
        song = db.one("SELECT * FROM songs WHERE id=?", sid)
        scenes = [_scene(n, f"{_SCENE_GUIDANCE:g} sec")
                  for n in range(1, _N_SCENES + 1)]
        _write_board(sid, song["slug"], "pg13", scenes, _SCENE_SECONDS)

        real = storyboard_service.payload(sid, "pg13")
        assert real["scene_time"] == _SCENE_TIME, real
        assert real["song_length"] == _SONG_LENGTH, real
        assert real["clip_seconds"] == _CLIP_SECONDS, real
        assert real["scene_count"] == _N_SCENES, real
        assert real["mismatch"] is True, real
        cov = real["coverage"]
        assert "fill_pct" in cov, cov
        # Real fill must differ from the stub so a template recompute goes red.
        real_fill = cov["fill_pct"]
        assert real_fill != _STUB_FILL_PCT, (real_fill, _STUB_FILL_PCT)
        if cov["rendered"]:
            recomputed = min(100.0, (cov["intent"] / cov["rendered"]) * 100.0)
        else:
            recomputed = 0.0
        assert recomputed == real_fill, (recomputed, real_fill)
        assert recomputed != _STUB_FILL_PCT

        stub_cov = dict(cov)
        stub_cov["fill_pct"] = _STUB_FILL_PCT
        stub = dict(real)
        stub["coverage"] = stub_cov
        stub["scene_count"] = _STUB_SCENE_COUNT

        def _stub_payload(song_id, tier):
            return stub

        monkeypatch.setattr(storyboard_service, "payload", _stub_payload)
        monkeypatch.setattr(appmod.storyboard_service, "payload", _stub_payload)

        html = client.get(f"/songs/{sid}/storyboard/pg13")

    assert html.status_code == 200, html.text
    page = html.text

    # T6-A4: meter width is the stub, not intent/rendered*100.
    width = _meter_width(page)
    assert width == str(_STUB_FILL_PCT) or width == f"{_STUB_FILL_PCT:g}", width
    assert _attr(page, "fill-pct") == str(_STUB_FILL_PCT) or _attr(
        page, "fill-pct") == f"{_STUB_FILL_PCT:g}"
    # Recomputed real fill must not appear as the width.
    assert str(recomputed) not in page or width == str(_STUB_FILL_PCT)
    # Stronger: no meter-fill style carries the recomputed percentage.
    bad = re.search(
        r'class="meter-fill"[^>]*style="width:\s*'
        + re.escape(f"{recomputed}")
        + r'\s*%"',
        page)
    assert bad is None, f"template recomputed fill_pct in style: {bad.group(0)}"
    # Common float truncations of intent/rendered must not be the width either.
    for frag in ("70.83", "70.833", f"{recomputed:.2f}", f"{recomputed:.1f}"):
        assert f"width: {frag}%" not in page, frag
        assert f'width: {frag}%' not in page, frag

    # T6-A2 numbers still carried on #storyboard-meter from the same stub.
    assert float(_attr(page, "scene-time")) == _SCENE_TIME
    assert float(_attr(page, "song-length")) == _SONG_LENGTH
    assert float(_attr(page, "clip-seconds")) == _CLIP_SECONDS
    assert int(_attr(page, "scene-count")) == _STUB_SCENE_COUNT
    assert _attr(page, "mismatch") == "true"
