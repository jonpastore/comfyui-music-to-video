"""T8-16: song-level media bag (the media menu).

docs/TRD-8 §6a. One list — takes, audio_edit, audio_original, assembled
renders — shared by GET /api/songs/{id}/media and the song HTML card.
T6-A2: HTML and JSON report the same distinctive counts/ids.
Picking/using is T8-2, not this surface.

Empty song: empty bag + reason. Positive half: after a take + an
audio_edit + a render, both surfaces show the same n and ids.
"""
import ast
import re
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import media_service


def _fastapi_imports(path):
    tree = ast.parse(open(path).read())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "fastapi" or alias.name.startswith("fastapi."):
                    names.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "fastapi" or node.module.startswith("fastapi."):
                names.append(node.module)
    return names


def _song(title="T8-16 Media"):
    return db.upsert_song(f"t8-16-{time.time_ns()}", title=title, duration=12.3)


def _seed_bag(sid):
    """Distinctive take + audio_edit + audio_original + render."""
    take_id = db.insert_take(
        sid, f"/data/takes/t8-16-{sid}.mp3", "generated",
        tags="dark synthwave", seed=4748, duration=12.3)
    edit_id = db.run(
        "INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
        sid, "audio_edit", f"/data/audio/edit-{sid}.mp3", None, time.time())
    orig_id = db.run(
        "INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
        sid, "audio_original", f"/data/audio/orig-{sid}.mp3", None, time.time())
    render_id = db.run(
        "INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
        sid, "pg13", f"/data/renders/t8-16-{sid}.mp4", time.time())
    return {
        "take": take_id,
        "audio_edit": edit_id,
        "audio_original": orig_id,
        "render": render_id,
    }


def test_t8_16_service_imports_nothing_from_fastapi():
    names = _fastapi_imports(media_service.__file__)
    assert names == [], f"media_service imports FastAPI: {names}"


def test_t8_16_empty_song_has_empty_bag_and_reason():
    """Empty bag is countable: count 0 + reason, not a missing field."""
    sid = _song("T8-16 Empty")
    bag = media_service.list_bag(sid)
    assert bag["song_id"] == sid
    assert bag["count"] == 0
    assert bag["items"] == []
    assert bag["reason"] == media_service.EMPTY_REASON
    assert bag["n_takes"] == 0
    assert bag["n_audio_edits"] == 0
    assert bag["n_audio_original"] == 0
    assert bag["n_renders"] == 0

    with TestClient(appmod.app) as client:
        js = client.get(f"/api/songs/{sid}/media")
        html = client.get(f"/songs/{sid}")
    assert js.status_code == 200, js.text
    body = js.json()
    assert body["count"] == 0
    assert body["items"] == []
    assert body["reason"] == media_service.EMPTY_REASON

    assert html.status_code == 200, html.text
    page = html.text
    assert 'id="media-menu"' in page
    assert f'data-media-count="0"' in page
    assert f'data-media-reason="{media_service.EMPTY_REASON}"' in page
    assert re.search(
        rf'data-media-reason="{re.escape(media_service.EMPTY_REASON)}"', page)


def test_t8_16_missing_song_is_404():
    with TestClient(appmod.app) as client:
        r = client.get("/api/songs/999999999/media")
    assert r.status_code == 404


def test_t8_16_service_lists_take_edit_original_render():
    """Service alone (no request) returns the four kinds with their ids."""
    sid = _song("T8-16 Service")
    ids = _seed_bag(sid)
    bag = media_service.list_bag(sid)
    assert bag["reason"] is None
    assert bag["count"] == 4
    assert bag["n_takes"] == 1
    assert bag["n_audio_edits"] == 1
    assert bag["n_audio_original"] == 1
    assert bag["n_renders"] == 1
    by_kind = {it["kind"]: it for it in bag["items"]}
    assert set(by_kind) == {"take", "audio_edit", "audio_original", "render"}
    assert by_kind["take"]["id"] == ids["take"]
    assert by_kind["audio_edit"]["id"] == ids["audio_edit"]
    assert by_kind["audio_original"]["id"] == ids["audio_original"]
    assert by_kind["render"]["id"] == ids["render"]
    assert by_kind["render"]["tier"] == "pg13"
    assert by_kind["take"]["origin"] == "generated"


def test_t6_a2_html_and_json_report_the_same_media_numbers():
    """T6-A2 on the media menu: same count and kind:id keys on both surfaces.

    Distinctive four-item bag so two empty answers cannot pass.
    """
    sid = _song("T8-16 T6-A2")
    ids = _seed_bag(sid)
    want_keys = {
        f"take:{ids['take']}",
        f"audio_edit:{ids['audio_edit']}",
        f"audio_original:{ids['audio_original']}",
        f"render:{ids['render']}",
    }
    want_n = 4

    with TestClient(appmod.app) as client:
        html = client.get(f"/songs/{sid}")
        js = client.get(f"/api/songs/{sid}/media")

    assert html.status_code == 200, html.text
    assert js.status_code == 200, js.text
    ctype = (js.headers.get("content-type") or "").split(";")[0].strip()
    assert ctype == "application/json", ctype
    assert "<html" not in js.text.lower(), js.text[:200]
    body = js.json()

    assert body["count"] == want_n, body
    assert body["reason"] is None, body
    assert body["n_takes"] == 1
    assert body["n_audio_edits"] == 1
    assert body["n_audio_original"] == 1
    assert body["n_renders"] == 1
    json_keys = {f"{it['kind']}:{it['id']}" for it in body["items"]}
    assert json_keys == want_keys, (json_keys, want_keys)

    page = html.text
    assert 'id="media-menu"' in page
    m_count = re.search(r'id="media-menu"[^>]*data-media-count="(\d+)"', page)
    assert m_count, page[:600]
    html_count = int(m_count.group(1))
    html_keys = set(re.findall(r'data-media-key="([^"]+)"', page))
    # Card count span also carries the number for the eye.
    span = re.search(r'data-media-count[^>]*>(\d+)<', page)
    if span:
        assert int(span.group(1)) == want_n

    assert html_count == body["count"] == want_n, (html_count, body["count"])
    assert html_keys == json_keys == want_keys, (html_keys, json_keys)

    # Per-kind counters on the card match the JSON subcounts.
    for attr, key in (
            ("data-media-n-takes", "n_takes"),
            ("data-media-n-audio-edits", "n_audio_edits"),
            ("data-media-n-audio-original", "n_audio_original"),
            ("data-media-n-renders", "n_renders")):
        m = re.search(rf'{attr}="(\d+)"', page)
        assert m, (attr, page[:600])
        assert int(m.group(1)) == body[key] == 1, (attr, m.group(1), body[key])


def test_t8_16_api_matches_service_without_template():
    """JSON is the service payload, not a second implementation in the route."""
    sid = _song("T8-16 API=service")
    _seed_bag(sid)
    direct = media_service.list_bag(sid)
    with TestClient(appmod.app) as client:
        r = client.get(f"/api/songs/{sid}/media")
    assert r.status_code == 200
    assert r.json() == direct
