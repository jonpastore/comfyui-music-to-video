"""T5-7: mixed clip geometry at song assembly.

docs/TRD-5 T5-7: a 1664x960 clip among 832x480 siblings must not silently
letterbox, and the x2 size must not be dropped. Same-aspect mixed sizes
honour the largest; mixed aspect is refused by name.
"""
import subprocess

import pytest

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


def _clip(path, size, colour, seconds=0.5, fps=16):
    _ffmpeg([
        "-f", "lavfi",
        "-i", f"color=c={colour}:s={size}:r={fps}:d={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", path,
    ])


def _mp3(path, seconds=2.0):
    _ffmpeg([
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={seconds}",
        "-c:a", "libmp3lame", path,
    ])


def _frame_rgb(path, t, w, h):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", path,
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    )
    assert r.returncode == 0, r.stderr
    want = w * h * 3
    assert len(r.stdout) == want, (len(r.stdout), want)
    return r.stdout


def _rgb_at(buf, w, x, y):
    i = (y * w + x) * 3
    return buf[i], buf[i + 1], buf[i + 2]


def _samples(buf, w, h):
    return {
        "tl": _rgb_at(buf, w, 4, 4),
        "tr": _rgb_at(buf, w, w - 5, 4),
        "bl": _rgb_at(buf, w, 4, h - 5),
        "br": _rgb_at(buf, w, w - 5, h - 5),
        "c": _rgb_at(buf, w, w // 2, h // 2),
    }


def _is_red(px):
    r, g, b = px
    return r > 160 and g < 80 and b < 80


def _is_green(px):
    r, g, b = px
    # lavfi green through yuv420p lands near (0, 127, 0), not (0, 255, 0)
    return g > 100 and g > r + 40 and g > b + 40


def _is_black(px):
    return max(px) < 40


def test_assembly_geometry_honours_largest_same_aspect():
    """A 1664x960 B clip among 832x480 siblings keeps the x2 size."""
    got = mixer.assembly_geometry([
        {"width": 832, "height": 480},
        {"width": 1664, "height": 960},
        {"width": 832, "height": 480},
    ])
    assert got == (1664, 960), got


def test_assembly_geometry_uniform_is_unchanged():
    assert mixer.assembly_geometry([
        {"width": 832, "height": 480},
        {"width": 832, "height": 480},
    ]) == (832, 480)


def test_assembly_geometry_refuses_mixed_aspect():
    """Letterbox is the silent path. Mixed aspect is named and refused."""
    with pytest.raises(ValueError, match=r"aspect|letterbox") as err:
        mixer.assembly_geometry([
            {"width": 832, "height": 480},
            {"width": 640, "height": 480},
        ])
    msg = str(err.value)
    assert "832x480" in msg and "640x480" in msg, msg


def test_assembly_scale_filter_has_no_pad():
    """force_original_aspect_ratio=decrease + pad is the silent letterbox."""
    line = mixer.assembly_scale_filter(0, 1664, 960)
    assert "1664" in line and "960" in line, line
    assert "pad=" not in line, line
    assert "force_original_aspect_ratio" not in line, line
    assert "scale=" in line, line


def test_assemble_song_mixed_res_does_not_letterbox_or_drop(tmp_path):
    """Pixels, not the graph: 832 siblings scaled to 1664 fill the frame.

    First-clip-wins concat drops the 1664 size. scale+pad to max letterboxes
    the 832 clips (black corners). Either is this criterion going red.
    """
    small = str(tmp_path / "small.mp4")
    big = str(tmp_path / "big.mp4")
    mp3 = str(tmp_path / "song.mp3")
    out = str(tmp_path / "assembled.mp4")
    _clip(small, "832x480", "red")
    _clip(big, "1664x960", "green")
    _mp3(mp3)
    mixer.assemble_song([small, big, small], mp3, out)

    info = mixer.probe(out)
    assert (info["width"], info["height"]) == (1664, 960), (
        f"x2 geometry dropped: assembled {info['width']}x{info['height']}"
    )

    first = _samples(_frame_rgb(out, 0.2, 1664, 960), 1664, 960)
    mid = _samples(_frame_rgb(out, 0.7, 1664, 960), 1664, 960)

    assert any(_is_black(first[k]) for k in ("tl", "tr", "bl", "br")) is False, (
        f"832 sibling was letterboxed at assembly: {first}"
    )
    assert all(_is_red(first[k]) for k in first), first
    assert all(_is_green(mid[k]) for k in mid), mid


def test_assemble_song_refuses_mixed_aspect(tmp_path):
    a = str(tmp_path / "wide.mp4")
    b = str(tmp_path / "squareish.mp4")
    mp3 = str(tmp_path / "song.mp3")
    _clip(a, "832x480", "red")
    _clip(b, "640x480", "green")
    _mp3(mp3)
    with pytest.raises(ValueError, match=r"aspect|letterbox"):
        mixer.assemble_song([a, b], mp3, str(tmp_path / "out.mp4"))
