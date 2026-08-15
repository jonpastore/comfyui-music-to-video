"""T2-46: a scene requesting ref_motion or control_video pins to cerberus.

docs/TRD-2 W2 / T2-46: both load through LoadVideosFromFolder, a kjnodes
node present on cerberus and absent on gamingpc (verified against both
/object_info). The rest of the song must still route freely.

Asserted through pipeline._attempt_plan — the walk submit_swarm uses
(T6-A10). A scene field is the request; the node in the graph is why
the pin exists.

Mutation: _attempt_plan ignores LoadVideosFromFolder → pin arm red.
Mutation: pin every clip → free-route arm red.
Mutation: pin to gamingpc → pin arm red.
Mutation: main() still applies --ref-motion to every clip → scene-only
arm red.
"""
import json
import sys

from conftest import _real_module

import build_song
import models

pipeline = _real_module("pipeline")
assert pipeline is not None, "real pipeline.py failed to import"


SCENE = {
    "name": "s", "camera": "wide", "lighting": "neon",
    "video_motion_prompt": "she walks", "negative_prompt": "",
    "duration_guidance": "5 sec", "image_prompt": "a rooftop",
}

FLEET = [
    {"id": "0", "title": "cerberus", "status": "running",
     "address": "http://127.0.0.1:8188"},
    {"id": "1", "title": "gamingpc", "status": "running",
     "address": "http://100.107.235.105:8188"},
]


def _classes(wf):
    return {n.get("class_type") for n in wf.values() if isinstance(n, dict)}


def _pin_fleet():
    was = pipeline.swarm_backends
    pipeline.swarm_backends = lambda: list(FLEET)
    return was


def _restore_fleet(was):
    pipeline.swarm_backends = was


def test_t2_46_scene_request_is_ref_motion_or_control_video():
    """The scene field is the request. Empty / other keys are not."""
    assert models.scene_requests_driving({"ref_motion": "/m.mp4"}) is True
    assert models.scene_requests_driving({"control_video": "/c.mp4"}) is True
    assert models.scene_requests_driving(
        {"ref_motion": "/m.mp4", "control_video": "/c.mp4"}) is True
    assert models.scene_requests_driving({"video_model": "s2v"}) is False
    assert models.scene_requests_driving({"ref_motion": "", "control_video": ""}) is False
    assert models.scene_requests_driving({}) is False
    assert models.scene_requests_driving(None) is False


def test_t2_46_cerberus_id_is_title_or_self_host_not_gamingpc():
    """Swarm ids renumber; title and canonical host are the durable names."""
    assert models.cerberus_backend_id(FLEET) == "0"
    by_title = [{"id": "4", "title": "cerberus",
                 "address": "http://cerberus:8188"}]
    assert models.cerberus_backend_id(by_title) == "4"
    by_loopback = [{"id": "7", "title": "local",
                    "address": "http://127.0.0.1:8188"}]
    assert models.cerberus_backend_id(by_loopback) == "7"
    gaming = [{"id": "1", "title": "gamingpc",
               "address": "http://100.107.235.105:8188"}]
    assert models.cerberus_backend_id(gaming) is None
    assert models.cerberus_backend_id(None) is None
    assert models.cerberus_backend_id([]) is None


def test_t2_46_driven_graph_pins_to_cerberus_plain_still_free_draws():
    """LoadVideosFromFolder walks cerberus only. The other clip still
    starts with SwarmUI's own choice so two 5090s load-balance."""
    driven = build_song.workflow(
        0, dict(SCENE, scene_number=1, video_model="s2v"),
        "c.png", "song.mp3", "c", "w", "",
        video_model="s2v", ref_motion="/m.mp4")
    plain = build_song.workflow(
        1, dict(SCENE, scene_number=2, video_model="ltx25"),
        "c.png", "song.mp3", "c", "w", "",
        video_model="ltx25")
    assert "LoadVideosFromFolder" in _classes(driven)
    assert "LoadVideosFromFolder" not in _classes(plain)

    was = _pin_fleet()
    try:
        driven_plan = list(pipeline._attempt_plan(driven))
        plain_plan = list(pipeline._attempt_plan(plain))
        assert driven_plan == ["0"], driven_plan
        assert "1" not in driven_plan, "gamingpc lacks kjnodes; do not offer it"
        assert plain_plan[0] is None, plain_plan
        assert "1" in plain_plan, plain_plan
        assert list(pipeline._attempt_plan())[0] is None
    finally:
        _restore_fleet(was)


def test_t2_46_control_video_is_the_same_pin():
    """Either driving input is the request. One without the other still pins."""
    wf = build_song.workflow(
        0, dict(SCENE, scene_number=1),
        "c.png", "song.mp3", "c", "w", "",
        video_model="s2v", control_video="/c.mp4")
    assert "LoadVideosFromFolder" in _classes(wf)
    was = _pin_fleet()
    try:
        assert list(pipeline._attempt_plan(wf)) == ["0"]
    finally:
        _restore_fleet(was)


def test_t2_46_main_applies_driving_only_to_the_requesting_scene(
        tmp_path, monkeypatch):
    """One job, two scenes: only the scene that asked gets the node.

    Job-level --ref-motion is not this check. A scene field is.
    """
    monkeypatch.setattr(build_song, "audio_duration",
                        lambda p: 2 * build_song.CHUNK)
    sb = {
        "scenes": [
            dict(SCENE, scene_number=1, video_model="s2v",
                 ref_motion="/m.mp4"),
            dict(SCENE, scene_number=2, video_model="ltx25"),
        ],
        "character_reference": "c",
        "album_world_reference": "w",
    }
    storyboard = tmp_path / "sb.json"
    storyboard.write_text(json.dumps(sb))
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"x")
    outdir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "build_song.py", "--storyboard", str(storyboard),
        "--audio", str(audio), "--slug", "t246", "--outdir", str(outdir),
        "--video-model", "ltx25",
    ])
    build_song.main()

    driven = json.loads((outdir / "clip_000.json").read_text())
    rest = json.loads((outdir / "clip_001.json").read_text())
    assert "LoadVideosFromFolder" in _classes(driven)
    assert "LoadVideosFromFolder" not in _classes(rest)

    was = _pin_fleet()
    try:
        assert list(pipeline._attempt_plan(driven)) == ["0"]
        assert list(pipeline._attempt_plan(rest))[0] is None
    finally:
        _restore_fleet(was)
