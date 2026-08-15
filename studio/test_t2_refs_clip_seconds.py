"""T2-refs-length wave 2: each ref graph honours clip_seconds / legal_frames.

docs/TRD-2 T2-12a / T2-13 / refs-length: wave 1 fixed clip COUNT via
n_clips_for. Wave 2: every generated reference workflow records the legal
clip duration for THAT clip — clip_seconds(length_seconds) and
legal_frames at LTX_FPS — not CHUNK.

build_refs writes clip_NNN.expect.json beside each graph; pipeline.gen_refs
stamps those expects onto landed refs (same path gen_clips uses).

Mutation: write duration=CHUNK / frames=81 for a 8.0 s scene → red.
Mutation: omit expect sidecars → red.
Mutation: gen_refs drops expects without stamping → stamp arm red.
"""
import json
import math
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import build_refs
import build_song
from conftest import _real_module

_real_pipeline = _real_module("pipeline")


SCENE = {
    "name": "s", "camera": "wide", "lighting": "neon",
    "video_motion_prompt": "she walks", "negative_prompt": "",
    "duration_guidance": "8 sec", "image_prompt": "a rooftop",
    "characters": [],
}


def _mp3(path, seconds=5):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-t", str(seconds), "-i", "anullsrc",
         "-c:a", "libmp3lame", path],
        check=True, capture_output=True)
    return path


def _want(scene_seconds):
    seconds = build_song.clip_seconds(scene_seconds)
    frames = build_song.legal_frames(seconds, build_song.LTX_FPS)
    return {
        "duration": round(seconds, 4),
        "frames": frames,
        "fps": round(build_song.LTX_FPS, 4),
    }


def test_ref_expect_honours_clip_seconds_not_chunk():
    """build_refs.ref_expect uses legal 8n+1 length, not CHUNK."""
    scene_seconds = 8.0
    want = _want(scene_seconds)
    assert want["frames"] != build_song.LTX25_LEN
    assert want["duration"] != round(build_song.CHUNK, 4)
    assert (want["frames"] - 1) % 8 == 0

    got = build_refs.ref_expect(
        dict(SCENE, length_seconds=scene_seconds), 1280, 720)
    assert got["duration"] == want["duration"]
    assert got["frames"] == want["frames"]
    assert got["fps"] == want["fps"]
    assert got["width"] == 1280
    assert got["height"] == 720
    assert got["duration"] != round(build_song.CHUNK, 4)
    assert got["frames"] != build_song.LTX25_LEN


def test_ref_expect_missing_length_stays_chunk():
    """NULL length_seconds is pre-T2-12a; keep CHUNK timing."""
    got = build_refs.ref_expect(dict(SCENE), 1280, 720)
    assert got["duration"] == round(build_song.CHUNK, 4)
    assert got["frames"] == build_song.LTX25_LEN


def test_build_refs_writes_expect_per_clip(tmp_path, monkeypatch):
    """build_refs --audio writes clip_NNN.expect.json beside each graph."""
    scene_seconds = 8.0
    track = 24.0  # three legal ~8 s clips
    want = _want(scene_seconds)
    scenes = [
        dict(SCENE, scene_number=i, length_seconds=scene_seconds)
        for i in range(1, 4)
    ]
    sb = {
        "scenes": scenes,
        "character_reference": "black feline woman",
        "album_world_reference": "neon alley",
        "version": "r",
    }
    sb_path = tmp_path / "sb.json"
    sb_path.write_text(json.dumps(sb))
    mp3 = _mp3(str(tmp_path / "s.mp3"), seconds=int(track))
    outdir = tmp_path / "out"
    outdir.mkdir()

    monkeypatch.setattr(build_song, "audio_duration", lambda p: track)
    # build_refs imports clip_plan from build_song at load; re-bind on module
    import build_refs as br
    monkeypatch.setattr(br, "audio_duration", lambda p: track)
    monkeypatch.setattr(
        br, "clip_plan",
        lambda scenes, audio=None, nclips=None: build_song.clip_plan(
            scenes, audio_path=audio or "x.mp3", nclips=nclips))

    # Invoke main via argv
    argv = [
        "build_refs.py",
        "--storyboard", str(sb_path),
        "--slug", "demo",
        "--anchor", "chosen.png",
        "--audio", mp3,
        "--outdir", str(outdir),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    br.main()

    expects = sorted(outdir.glob("clip_*.expect.json"))
    graphs = sorted(p for p in outdir.glob("clip_*.json")
                    if not p.name.endswith(".expect.json"))
    assert graphs, "no ref graphs written"
    assert expects, "no expect sidecars written"
    assert len(expects) == len(graphs)
    n_want = build_song.n_clips_for(track, scene_seconds)
    assert len(expects) == n_want
    assert n_want != math.ceil(track / build_song.CHUNK)

    for path in expects:
        got = json.loads(path.read_text())
        assert got["duration"] == want["duration"], path
        assert got["frames"] == want["frames"], path
        assert got["fps"] == want["fps"], path
        assert got["duration"] != round(build_song.CHUNK, 4)
        assert got["frames"] != build_song.LTX25_LEN


def test_gen_refs_stamps_expect_from_clip_seconds(monkeypatch, tmp_path):
    """pipeline.gen_refs reads expect sidecars and stamps landed refs."""
    scene_seconds = 8.0
    want = _want(scene_seconds)
    stamped = []

    def fake_submit(wf_dir, progress=None):
        expects = sorted(
            f for f in os.listdir(wf_dir) if f.endswith(".expect.json"))
        assert expects, f"gen_refs saw no expect sidecars in {os.listdir(wf_dir)}"
        for f in expects:
            got = json.load(open(os.path.join(wf_dir, f)))
            assert got["duration"] == want["duration"], got
            assert got["frames"] == want["frames"], got
            assert got["duration"] != round(build_song.CHUNK, 4)
        # pretend one landed png per clip graph
        paths = []
        for f in sorted(os.listdir(wf_dir)):
            if f.endswith(".json") and not f.endswith(".expect.json"):
                m = __import__("re").match(r"clip_(\d+)\.json$", f)
                if m:
                    p = str(tmp_path / f"refs_demo_r_clip_{int(m.group(1)):03d}_00001_.png")
                    open(p, "wb").write(b"\x89PNG\r\n\x1a\n")
                    paths.append(p)
        return paths

    def fake_stamp(records, expects, progress=None):
        stamped.append({"records": list(records), "expects": dict(expects)})

    monkeypatch.setattr(_real_pipeline, "submit_dir", fake_submit)
    monkeypatch.setattr(_real_pipeline, "_stamp_expect", fake_stamp)
    monkeypatch.setattr(build_song, "audio_duration", lambda p: 8.0)

    sb = {
        "scenes": [dict(SCENE, scene_number=1, length_seconds=scene_seconds)],
        "character_reference": "black feline woman",
        "album_world_reference": "neon alley",
    }
    sb_path = str(tmp_path / "sb.json")
    json.dump(sb, open(sb_path, "w"))
    mp3 = _mp3(str(tmp_path / "s.mp3"), seconds=8)

    # build_refs.main also needs audio_duration; it imports from build_song
    import build_refs as br
    monkeypatch.setattr(br, "audio_duration", lambda p: 8.0)

    _real_pipeline.gen_refs("demo", "r", sb_path, "chosen.png", mp3, limit=1)
    assert stamped, "gen_refs never stamped expects"
    expects = stamped[0]["expects"]
    assert expects, "stamped empty expects"
    for exp in expects.values():
        assert exp["duration"] == want["duration"]
        assert exp["frames"] == want["frames"]
        assert exp["duration"] != round(build_song.CHUNK, 4)
