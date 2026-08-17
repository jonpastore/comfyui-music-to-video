"""T6-A3: service modules import nothing from FastAPI; tests call them directly.

docs/TRD-6 §0.1. A route handler contains no arithmetic, no defaulting
and no decision. If a test can only reach the logic through a request,
the logic is in the wrong place.

Kill: add `from fastapi import HTTPException` to sets_service (or any of
arc / playlist / cleanup / media service) → import scan goes red.
Differential: default mode / scene_seconds clamp / meter mismatch live
in the service. Calling the service with no request must produce them.
A handler that still writes `or "audio"` or `or 4.0` is the defect.
"""
import ast
import inspect
import json
import os
import tempfile
import time

import arc_service
import cleanup_service
import db
import jobs
import library_service
import media_service
import playlist_service
import sets_service
import storyboard_service
import storyboard_versions
import tiers


def _ensure_handlers():
    if "render_set" not in jobs._handlers:
        @jobs.handler("render_set")
        def _t6_a3_render_set(args, progress):
            return args
    if "storyboard" not in jobs._handlers:
        @jobs.handler("storyboard")
        def _t6_a3_storyboard(args, progress):
            return args


def _job_args(jid):
    row = jobs.get(jid)
    raw = row["args_json"] if "args_json" in row.keys() else row["args"]
    return raw if isinstance(raw, dict) else json.loads(raw)


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


def test_t6_a3_sets_service_imports_nothing_from_fastapi():
    names = _fastapi_imports(sets_service.__file__)
    assert names == [], f"sets_service imports FastAPI: {names}"


def test_t6_a3_storyboard_service_imports_nothing_from_fastapi():
    names = _fastapi_imports(storyboard_service.__file__)
    assert names == [], f"storyboard_service imports FastAPI: {names}"


def test_t6_a3_storyboard_versions_imports_nothing_from_fastapi():
    names = _fastapi_imports(storyboard_versions.__file__)
    assert names == [], f"storyboard_versions imports FastAPI: {names}"


def test_t6_a3_arc_service_imports_nothing_from_fastapi():
    names = _fastapi_imports(arc_service.__file__)
    assert names == [], f"arc_service imports FastAPI: {names}"


def test_t6_a3_playlist_service_imports_nothing_from_fastapi():
    names = _fastapi_imports(playlist_service.__file__)
    assert names == [], f"playlist_service imports FastAPI: {names}"


def test_t6_a3_cleanup_service_imports_nothing_from_fastapi():
    names = _fastapi_imports(cleanup_service.__file__)
    assert names == [], f"cleanup_service imports FastAPI: {names}"


def test_t6_a3_media_service_imports_nothing_from_fastapi():
    names = _fastapi_imports(media_service.__file__)
    assert names == [], f"media_service imports FastAPI: {names}"


def test_t6_a3_library_service_imports_nothing_from_fastapi():
    names = _fastapi_imports(library_service.__file__)
    assert names == [], f"library_service imports FastAPI: {names}"


def test_t6_a3_create_set_and_add_item_without_a_request():
    """Defaults and payload numbers are decided in the service, not a route."""
    stamp = f"t6a3-set-{time.time_ns()}"
    mp3 = os.path.join(tempfile.mkdtemp(prefix="t6a3_"), "loop.mp3")
    with open(mp3, "wb") as f:
        f.write(b"ID3")
    sid = db.upsert_song(stamp, title="T6-A3 Track", mp3_path=mp3, duration=12.3)

    set_id = sets_service.create(stamp)
    row = sets_service.get(set_id)
    assert row["mode"] == "video", (
        f"create() without mode returned {row['mode']!r}; the service must "
        f"default (handler defaulting is the T6-A3 defect)")

    payload = sets_service.payload(set_id)
    assert payload["count"] == 0, payload
    assert payload["set"]["id"] == set_id

    sets_service.add_item(set_id, sid)
    added = sets_service.payload(set_id)
    assert added["count"] == 1, added
    item = added["items"][0]
    assert item["song_id"] == sid
    assert item["transition"] == "fade", (
        f"add_item() without transition returned {item['transition']!r}")
    assert float(item["secs"]) == 2.0, item["secs"]
    assert added["total_secs"] is not None or added["duration_error"]

    _ensure_handlers()
    audio_id = sets_service.create(stamp + "-audio", mode="audio")
    sets_service.add_item(audio_id, sid)
    jid = sets_service.enqueue_render(audio_id)
    assert jid, jid
    job = jobs.get(jid)
    assert job["kind"] == "render_set", job


def test_t6_a3_storyboard_meter_without_a_request():
    """Mismatch arithmetic lives in the service. 20s of scenes on 120s is a miss."""
    tiers.ensure_builtins()
    stamp = f"t6a3-sb-{time.time_ns()}"
    sid = db.upsert_song(stamp, title="T6-A3 Board", duration=120.0, lyrics="she leaves")
    outdir = os.path.join(db.DATA, "storyboards", stamp)
    os.makedirs(outdir, exist_ok=True)
    scenes = [{
        "scene_number": 1, "name": "the door",
        "image_prompt": "she stands at the door",
        "video_motion_prompt": "she walks out",
        "story": "the door closing",
        "characters": ["Unknown Lead"],
        "duration_guidance": "20 sec",
        "negative_prompt": "",
        "camera": "wide",
    }]
    sb = {
        "title": "T", "album": "A", "version": "pg13",
        "character_reference": "a sleek black feline DJ",
        "scenes": scenes,
    }
    json_path = os.path.join(outdir, f"{stamp}_pg13.json")
    json.dump(sb, open(json_path, "w"))
    db.run(
        """INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count,
                                    scene_seconds, created)
           VALUES (?,?,?,?,?,?,?)""",
        sid, "pg13", json_path, json_path, 1, 4.0, time.time())

    meter = storyboard_service.meter(sid, "pg13")
    assert meter["song_length"] == 120.0, meter
    assert meter["mismatch"] is True, meter
    assert meter["clip_seconds"] != 4.0, (
        f"meter returned raw scene_seconds {meter.get('clip_seconds')}; "
        f"legal clip length is decided in the service")

    tight = storyboard_service.scene_time_report(120.0, 120.0)
    assert tight["mismatch"] is False, tight


def test_t6_a3_enqueue_storyboard_clamps_without_a_request():
    """scene_seconds clamp is a service decision. 100 must become 60."""
    tiers.ensure_builtins()
    _ensure_handlers()
    stamp = f"t6a3-enq-{time.time_ns()}"
    sid = db.upsert_song(stamp, title="T6-A3 Enqueue", duration=12.3)
    jid = storyboard_service.enqueue(sid, "pg13", scene_seconds=100)
    args = _job_args(jid)
    assert args["scene_seconds"] == 60.0, args
    omitted = storyboard_service.enqueue(sid, "pg13")
    oargs = _job_args(omitted)
    assert oargs["scene_seconds"] is None, oargs


def test_t6_a3_handlers_do_not_default_or_decide():
    """The named JSON handlers forward. Defaulting / arithmetic in the
    handler is the defect: a mobile client would not see it."""
    import app as appmod

    create_src = inspect.getsource(appmod.api_sets_create)
    assert 'or "audio"' not in create_src and "or 'audio'" not in create_src, (
        "api_sets_create still defaults mode; move it to sets_service.create")
    assert 'or "video"' not in create_src and "or 'video'" not in create_src, (
        "api_sets_create still defaults mode; move it to sets_service.create")

    add_src = inspect.getsource(appmod.api_set_add_item)
    assert 'or "fade"' not in add_src and "or 'fade'" not in add_src, (
        "api_set_add_item still defaults transition")
    assert "2.0" not in add_src, (
        "api_set_add_item still defaults secs")

    gen_src = inspect.getsource(appmod.api_start_storyboard)
    assert "4.0" not in gen_src, (
        "api_start_storyboard still defaults scene_seconds")

    meter_src = inspect.getsource(appmod.api_storyboard_meter)
    assert "scene_time_report" not in meter_src, (
        "api_storyboard_meter still computes the miss flag")
    assert "clip_seconds" not in meter_src, (
        "api_storyboard_meter still derives clip length")
