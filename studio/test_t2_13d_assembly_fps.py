"""T2-13d: every clip of one song is normalised to one output fps.

docs/TRD-2 W1-5 / T2-13d: s2v renders 16.0 and LTX 16.8312; mixed fps is
encoder-parameter drift at assembly. Asserted on the fps of the assembled
file, not of the plan.

Mutation: concat demuxer first-clip-wins → assembled file carries 16.0
when a later clip is 24.0, and this fails.
"""
import subprocess

from conftest import _real_module


mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"


def _ffmpeg(args):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *args],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r


def _clip(path, size="832x480", colour="red", seconds=0.5, fps=16):
    _ffmpeg([
        "-f", "lavfi",
        "-i", f"color=c={colour}:s={size}:r={fps}:d={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", path,
    ])


def _mp3(path, seconds=1.0):
    _ffmpeg([
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={seconds}",
        "-c:a", "libmp3lame", path,
    ])


def test_assembly_fps_uniform_is_unchanged():
    assert mixer.assembly_fps([
        {"fps": 16.0},
        {"fps": 16.0},
    ]) == 16.0


def test_assembly_fps_honours_highest_mixed_rate():
    """First-clip-wins drops the later clip's rate. Honour the highest."""
    got = mixer.assembly_fps([
        {"fps": 16.0},
        {"fps": 24.0},
        {"fps": 16.0},
    ])
    assert got == 24.0, got


def test_assembly_fps_s2v_and_ltx_picks_one_rate():
    got = mixer.assembly_fps([
        {"fps": 16.0},
        {"fps": 16.8312},
    ])
    assert abs(got - 16.8312) < 1e-4, got
    assert abs(got - 16.0) > 0.1


def test_assemble_song_mixed_fps_is_one_rate_on_the_file(tmp_path):
    """The file, not the plan: 16 + 24 + 16 becomes one output fps.

    Concat without fps= keeps the first clip's 16/1. Honouring 24 is
    the mutation this criterion exists to catch.
    """
    slow = str(tmp_path / "s2v.mp4")
    fast = str(tmp_path / "ltx.mp4")
    mp3 = str(tmp_path / "song.mp3")
    out = str(tmp_path / "assembled.mp4")
    _clip(slow, colour="red", fps=16)
    _clip(fast, colour="green", fps=24)
    _mp3(mp3)
    mixer.assemble_song([slow, fast, slow], mp3, out)

    info = mixer.probe(out)
    want = mixer.assembly_fps([
        {"fps": 16.0},
        {"fps": 24.0},
        {"fps": 16.0},
    ])
    assert abs(info["fps"] - want) < 0.05, (
        f"assembled file fps is {info['fps']}, want {want} "
        "(concat first-clip-wins is not normalisation)")
    assert abs(info["fps"] - 16.0) > 0.5, info["fps"]


def test_assemble_song_s2v_ltx_rates_normalise_on_the_file(tmp_path):
    """Named mixed-model rates: 16.0 and 16.8312 become one file fps."""
    s2v = str(tmp_path / "s2v.mp4")
    ltx = str(tmp_path / "ltx.mp4")
    mp3 = str(tmp_path / "song.mp3")
    out = str(tmp_path / "assembled.mp4")
    _clip(s2v, colour="red", fps=16)
    _clip(ltx, colour="green", fps=16.8312)
    _mp3(mp3)
    mixer.assemble_song([s2v, ltx], mp3, out)

    info = mixer.probe(out)
    want = mixer.assembly_fps([
        {"fps": mixer.probe(s2v)["fps"]},
        {"fps": mixer.probe(ltx)["fps"]},
    ])
    assert abs(info["fps"] - want) < 0.05, (
        f"assembled file fps is {info['fps']}, want {want}")
    assert abs(want - 16.0) > 0.1
    assert abs(info["fps"] - 16.0) > 0.1, info["fps"]
