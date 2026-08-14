"""T1-7 four-feature set_duration fixture.

docs/TRD-1 T1-7: a set with at least one echoing item, one black
transition with a hold, one beatmatched join and one trimmed item must
render to within mixer.SET_DURATION_TOLERANCE of mixer.set_duration().
Each of those four has broken the prediction on its own; a one-feature
demo is not this criterion.

T1-8 (displayed length is set_duration's return value) is a UI
differential and lives elsewhere. This file does not restate the
tolerance and does not change mixer.set_duration arithmetic.
"""
import json
import os
import subprocess

import pytest

from conftest import _real_module


mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"

# 120 BPM: a beat every 0.5s, bars at 0, 2, 4, 6, 8.
_GRID = [i * 0.5 for i in range(17)]
_ECHO_MS = 200
_HOLD_S = 1.0


def _ffmpeg(args):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *args],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r


def _wav(path, seconds, freq):
    _ffmpeg([
        "-f", "lavfi",
        "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
        "-c:a", "pcm_s16le", path,
    ])


def _mp4(path, seconds, colour, freq, fps=30):
    _ffmpeg([
        "-f", "lavfi", "-i", f"color=c={colour}:s=320x240:r={fps}:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-shortest", path,
    ])


def _four_feature_items(paths, key):
    echo = json.dumps({"echo_out": {"decay": 0.4, "delay": _ECHO_MS}})
    return [
        {key: paths[0], "transition": "fade", "secs": 1.7,
         "in_secs": 1.0, "out_secs": 6.3,
         "beatmatch": True, "beat_grid": list(_GRID),
         "downbeat_offset": 0, "bpm": 120.0,
         "effects_json": echo},
        {key: paths[1], "transition": "black", "secs": 1.0, "hold": _HOLD_S},
        {key: paths[2], "transition": "cut", "secs": 0.0},
    ]


def _pred(items, key):
    return mixer.set_duration([dict(it) for it in items], key=key)


def _assert_all_four_move_the_prediction(items, key):
    """The four features are in play, not present-but-inert."""
    base = _pred(items, key)

    no_echo = [dict(it) for it in items]
    no_echo[0] = dict(no_echo[0], effects_json=None)
    assert abs(_pred(no_echo, key) - base) >= _ECHO_MS / 1000.0 - 1e-6, (
        "echo did not move set_duration")

    no_hold = [dict(it) for it in items]
    no_hold[1] = dict(no_hold[1], transition="cut", secs=0.0, hold=0.0)
    assert abs(_pred(no_hold, key) - base) >= _HOLD_S - 1e-6, (
        "black hold did not move set_duration")

    no_bm = [dict(it) for it in items]
    no_bm[0] = dict(no_bm[0], beatmatch=False)
    assert abs(_pred(no_bm, key) - base) >= 0.2, (
        "beatmatch snap did not move set_duration")

    no_trim = [dict(it) for it in items]
    dropped = {k: v for k, v in no_trim[0].items()
               if k not in ("in_secs", "out_secs")}
    no_trim[0] = dropped
    assert abs(_pred(no_trim, key) - base) >= 0.5, (
        "trim did not move set_duration")


def _assert_render_matches(items, out_path, key):
    assert mixer.SET_DURATION_TOLERANCE == 0.05, (
        "T1-7 binds the named constant at 0.05s; do not loosen it")
    pred = mixer.set_duration([dict(it) for it in items], key=key)
    if key == "audio":
        mixer.mix_audio([dict(it) for it in items], out_path)
    else:
        mixer.render_set([dict(it) for it in items], out_path)
    actual = mixer.probe(out_path)["duration"]
    gap = abs(actual - pred)
    assert gap <= mixer.SET_DURATION_TOLERANCE, (
        f"T1-7 {key}: predicted {pred:.3f}s rendered {actual:.3f}s "
        f"gap={gap:.3f}s (tol={mixer.SET_DURATION_TOLERANCE})")
    return pred, actual, gap


def test_t1_7_tolerance_is_the_named_constant():
    """TRD-3 T3-11 imports this; restating 0.05 in two places is the defect."""
    assert mixer.SET_DURATION_TOLERANCE == 0.05
    import qc
    src = open(os.path.join(os.path.dirname(__file__), "qc.py"), encoding="utf-8").read()
    assert "mixer.SET_DURATION_TOLERANCE" in src
    assert "<= mixer.SET_DURATION_TOLERANCE" in src


@pytest.mark.slow
def test_t1_7_echo_black_beatmatch_trim_audio_mix(tmp_path):
    """UI prices key='audio'; mix_audio is the file that number names."""
    paths = [
        str(tmp_path / "a.wav"),
        str(tmp_path / "b.wav"),
        str(tmp_path / "c.wav"),
    ]
    _wav(paths[0], 8, 440)
    _wav(paths[1], 6, 330)
    _wav(paths[2], 4, 550)
    items = _four_feature_items(paths, "audio")
    _assert_all_four_move_the_prediction(items, "audio")
    _assert_render_matches(items, str(tmp_path / "set.mp3"), "audio")


@pytest.mark.slow
def test_t1_7_echo_black_beatmatch_trim_video_set(tmp_path):
    """Same four features on render_set; T3-11 probes this artefact."""
    paths = [
        str(tmp_path / "a.mp4"),
        str(tmp_path / "b.mp4"),
        str(tmp_path / "c.mp4"),
    ]
    _mp4(paths[0], 8, "red", 440)
    _mp4(paths[1], 6, "green", 330)
    _mp4(paths[2], 4, "blue", 550)
    items = _four_feature_items(paths, "video")
    _assert_all_four_move_the_prediction(items, "video")
    _assert_render_matches(items, str(tmp_path / "set.mp4"), "video")
