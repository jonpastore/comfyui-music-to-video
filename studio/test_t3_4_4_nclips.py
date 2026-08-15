"""T3-4.4-nclips: assembled song clip count vs build_song.clip_plan.

docs/TRD-3 §4.4: the clip count matches clip_plan. Expected length goes
through build_song.clip_plan (the one allocator), not a second ceil and
not scene_count. Measured is how many clips went into the assemble.

Mutation: delete the nclips check → both arms fail.
Mutation: expected = measured always → mismatch arm stays PASS.
Mutation: use len(scenes) instead of len(clip_plan) → red when a
20-scene board is spread across more clips than scenes.
"""
import inspect
import importlib.util
import os
import subprocess
import sys

from conftest import _real_module

import qc

mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def _load_build_song():
    path = os.path.join(_REPO, "build_song.py")
    spec = importlib.util.spec_from_file_location("_real_build_song_t344", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


build_song = _load_build_song()


def _use_real_mixer(monkeypatch):
    monkeypatch.setattr(qc, "mixer", mixer)


def _scene(n, guidance="4-6 sec", **extra):
    row = {
        "scene_number": n,
        "name": f"s{n}",
        "duration_guidance": guidance,
        "image_prompt": "x",
        "video_motion_prompt": "y",
    }
    row.update(extra)
    return row


def _mp4(path, seconds=1.0, fps=16):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate={fps}:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "48000", "-shortest", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


def _nclips_row(findings):
    rows = [f for f in findings if f["check"] == "nclips"]
    assert rows, findings
    return rows[0]


def test_t3_4_4_nclips_goes_through_clip_plan_not_a_second_ceil():
    """The expected count is len(clip_plan). A local ceil drifts from it."""
    src = inspect.getsource(qc.check_nclips)
    assert "clip_plan" in src
    assert "build_song" in src
    assert "math.ceil" not in src
    assert "CHUNK" not in src


def test_t3_4_4_matching_assembly_passes(tmp_path, monkeypatch):
    """Positive half: assembled clip count equals len(clip_plan) PASSes."""
    _use_real_mixer(monkeypatch)
    scenes = [_scene(i) for i in (1, 2, 3)]
    duration = 24.0  # n_clips_for(24) with default CHUNK ~4.8125 → 5
    want = len(build_song.clip_plan(
        scenes, nclips=build_song.n_clips_for(duration)))
    assert want >= 3, want

    path = _mp4(str(tmp_path / "song.mp4"), seconds=1.0)
    expect = {
        "want_audio": True,
        "nclips": want,
        "scenes": scenes,
        "duration": duration,
    }
    row = _nclips_row(qc.run(path, "song", expect))
    assert row["verdict"] == qc.PASS, row
    assert row["kind"] == "song"
    assert row["measured"] == want
    assert row["expected"] == want
    assert row["unit"] == "clips"
    assert row["remedy_class"] == qc.REMEDY_REASSEMBLE


def test_t3_4_4_mismatch_rejects(tmp_path, monkeypatch):
    """Deliberately broken: assembly used fewer clips than the plan."""
    _use_real_mixer(monkeypatch)
    scenes = [_scene(i) for i in (1, 2, 3)]
    duration = 24.0
    want = len(build_song.clip_plan(
        scenes, nclips=build_song.n_clips_for(duration)))
    measured = want - 2
    assert measured >= 1 and measured != want

    path = _mp4(str(tmp_path / "short.mp4"), seconds=1.0)
    expect = {
        "nclips": measured,
        "scenes": scenes,
        "duration": duration,
    }
    row = _nclips_row(qc.check_nclips(path, expect))
    assert row["verdict"] == qc.REJECT, row
    assert row["measured"] == measured
    assert row["expected"] == want
    assert row["unit"] == "clips"


def test_t3_4_4_scene_count_is_not_the_plan(tmp_path, monkeypatch):
    """A 3-scene board on a long track is not 3 clips. clip_plan spreads
    the board; using scene_count as expected would pass a short assemble."""
    _use_real_mixer(monkeypatch)
    scenes = [_scene(i) for i in (1, 2, 3)]
    duration = 195.792  # classic 41-clip track length at default CHUNK
    plan_n = len(build_song.clip_plan(
        scenes, nclips=build_song.n_clips_for(duration)))
    assert plan_n > len(scenes), (plan_n, len(scenes))

    path = _mp4(str(tmp_path / "long.mp4"), seconds=1.0)
    # assembled only as many clips as scenes — the approve-grid defect shape
    expect = {
        "nclips": len(scenes),
        "scenes": scenes,
        "duration": duration,
    }
    row = _nclips_row(qc.run(path, "song", expect))
    assert row["verdict"] == qc.REJECT, row
    assert row["measured"] == len(scenes)
    assert row["expected"] == plan_n
    assert row["expected"] != len(scenes)


def test_t3_4_4_clips_list_is_measured_count(tmp_path, monkeypatch):
    """measured may be len(expect['clips']) when the assemble lists them."""
    _use_real_mixer(monkeypatch)
    scenes = [_scene(i) for i in (1, 2)]
    duration = 15.0
    want = len(build_song.clip_plan(
        scenes, nclips=build_song.n_clips_for(duration)))
    path = _mp4(str(tmp_path / "listed.mp4"), seconds=1.0)
    expect = {
        "clips": [f"c{i:03d}.mp4" for i in range(want)],
        "scenes": scenes,
        "duration": duration,
    }
    row = _nclips_row(qc.check_nclips(path, expect))
    assert row["verdict"] == qc.PASS, row
    assert row["measured"] == want


def test_t3_4_4_absent_claim_is_not_a_pass(tmp_path, monkeypatch):
    """No nclips/scenes claim → the check does not invent a pass."""
    _use_real_mixer(monkeypatch)
    path = _mp4(str(tmp_path / "bare.mp4"), seconds=1.0)
    found = qc.run(path, "song", {"want_audio": True})
    assert not [f for f in found if f["check"] == "nclips"], found
