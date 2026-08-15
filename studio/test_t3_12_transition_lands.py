"""T3-12: each transition lands where the model says, within half a frame.

docs/TRD-3 T3-12: measured from the rendered file, not from the plan.
A check that echoes mixer.transition_times back as "measured" stays
green without looking at the picture. The fail arm is a file whose
join is in the wrong place.

T3-4: finding.measured is an independently computed reading (first
frame that is no longer the outgoing colour), not merely non-null.
T3-27: the check names a remedy class; it is none — measurement only.
"""
import subprocess

from conftest import _real_module

import qc


FPS = 30
HALF_FRAME = 0.5 / FPS


def _ffmpeg(args):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", *args],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r


def _color_mp4(path, seconds, colour, fps=FPS):
    _ffmpeg([
        "-f", "lavfi",
        "-i", f"color=c={colour}:s=160x120:r={fps}:d={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path,
    ])
    return path


def _concat(paths, out):
    """Hard concat, no mixer — so a join can sit where the model does not."""
    lst = out + ".txt"
    with open(lst, "w") as f:
        for p in paths:
            f.write(f"file '{p}'\n")
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])
    return out


def _use_real_mixer(monkeypatch):
    real = _real_module("mixer")
    assert real is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real)
    return real


def _frame_means(path):
    """Independent reading: mean RGB of every frame. Not qc.measure_*."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path,
         "-vf", "scale=8:8,format=rgb24", "-f", "rawvideo", "-"],
        capture_output=True)
    assert r.returncode == 0 and r.stdout, r.stderr
    n = 8 * 8 * 3
    frames = []
    buf = r.stdout
    for i in range(0, len(buf) // n * n, n):
        chunk = buf[i:i + n]
        px = len(chunk) // 3
        frames.append((
            sum(chunk[0::3]) / px,
            sum(chunk[1::3]) / px,
            sum(chunk[2::3]) / px,
        ))
    assert frames, path
    return frames


def _independent_lands(path, fps=FPS):
    """First frame of each new colour regime. One variable: the picture."""
    frames = _frame_means(path)
    lands = []
    prev = frames[0]
    for i in range(1, len(frames)):
        r, g, b = frames[i]
        pr, pg, pb = prev
        delta = ((r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2) ** 0.5
        if delta >= 40.0:
            lands.append(round(i / fps, 4))
            prev = frames[i]
    return lands


def _lands_row(findings):
    rows = [f for f in findings if f["check"] == "transition_lands"]
    assert rows, findings
    return rows[0]


def test_t3_12_cut_lands_where_the_model_says(tmp_path, monkeypatch):
    """2s red then 2s blue, cut. File land is 2.0s; model says 2.0s."""
    mixer = _use_real_mixer(monkeypatch)
    red = _color_mp4(str(tmp_path / "red.mp4"), 2, "red")
    blue = _color_mp4(str(tmp_path / "blue.mp4"), 2, "blue")
    items = [
        {"video": red, "transition": "cut", "secs": 0.0},
        {"video": blue, "transition": "cut", "secs": 0.0},
    ]
    out = str(tmp_path / "set.mp4")
    mixer.render_set(items, out)

    expected = mixer.transition_times(items)
    assert expected == [2.0], expected
    independent = _independent_lands(out)
    assert independent, "no colour jump in the rendered file"
    assert abs(independent[0] - 2.0) <= HALF_FRAME, independent

    found = qc.check_set(out, items)
    row = _lands_row(found)
    assert row["verdict"] == qc.PASS, row
    assert row["unit"] == "s"
    assert row["remedy_class"] == qc.REMEDY_NONE
    assert not qc.is_actionable(row["remedy_class"])
    measured = row["measured"]
    assert measured == independent, (measured, independent)
    assert row["expected"] == [round(t, 4) for t in expected]


def test_t3_12_file_join_off_the_model_is_rejected(tmp_path, monkeypatch):
    """Same model (join at 2s). File is 3s red + 2s blue. Picture says 3s."""
    mixer = _use_real_mixer(monkeypatch)
    red2 = _color_mp4(str(tmp_path / "red2.mp4"), 2, "red")
    red3 = _color_mp4(str(tmp_path / "red3.mp4"), 3, "red")
    blue = _color_mp4(str(tmp_path / "blue.mp4"), 2, "blue")
    items = [
        {"video": red2, "transition": "cut", "secs": 0.0},
        {"video": blue, "transition": "cut", "secs": 0.0},
    ]
    wrong = _concat([red3, blue], str(tmp_path / "wrong.mp4"))

    expected = mixer.transition_times(items)
    assert expected == [2.0], expected
    independent = _independent_lands(wrong)
    assert independent, independent
    assert abs(independent[0] - 3.0) <= HALF_FRAME, independent
    assert abs(independent[0] - expected[0]) > HALF_FRAME

    found = qc.check_set(wrong, items)
    row = _lands_row(found)
    assert row["verdict"] == qc.REJECT, row
    assert row["measured"] == independent
    assert row["expected"] == [round(t, 4) for t in expected]
    assert row["unit"] == "s"


def test_t3_12_each_of_two_joins_is_measured(tmp_path, monkeypatch):
    """Each transition, not only the first. red|green|blue, two cuts."""
    mixer = _use_real_mixer(monkeypatch)
    red = _color_mp4(str(tmp_path / "r.mp4"), 1, "red")
    green = _color_mp4(str(tmp_path / "g.mp4"), 1, "green")
    blue = _color_mp4(str(tmp_path / "b.mp4"), 1, "blue")
    items = [
        {"video": red, "transition": "cut", "secs": 0.0},
        {"video": green, "transition": "cut", "secs": 0.0},
        {"video": blue, "transition": "cut", "secs": 0.0},
    ]
    out = str(tmp_path / "three.mp4")
    mixer.render_set(items, out)

    expected = mixer.transition_times(items)
    assert expected == [1.0, 2.0], expected
    independent = _independent_lands(out)
    assert len(independent) == 2, independent
    assert all(abs(m - e) <= HALF_FRAME for m, e in zip(independent, expected))

    row = _lands_row(qc.check_set(out, items))
    assert row["verdict"] == qc.PASS, row
    assert row["measured"] == independent
    assert row["expected"] == [1.0, 2.0]
