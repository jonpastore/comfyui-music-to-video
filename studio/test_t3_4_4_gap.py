"""T3-4.4-gap: no black gap at an assembled song join.

docs/TRD-3 §4.4: assembled song videos get everything in 4.2, plus no
black gap at a join. A hard cut between two non-black clips PASSes. A
black stretch sitting on a planned join REJECTS.

Not T3-12 (set transition lands). Not whole-file black_frames. The
join times come from the assembly plan (joins / clip_durations), not
from guessing the picture.

T3-4: measured is an independently counted black-span hit, not merely
non-null. T3-27: remedy_class is re-assemble.
"""
import subprocess

from conftest import _real_module

import qc


FPS = 10
# Two frames at 10 fps is 0.2 s — long enough to be a gap, short of a scene.
BLACK_S = 0.3


def _ffmpeg(args):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", *args],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r


def _color(path, seconds, colour, fps=FPS):
    _ffmpeg([
        "-f", "lavfi",
        "-i", f"color=c={colour}:s=160x120:r={fps}:d={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path,
    ])
    return path


def _concat(paths, out):
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


def _independent_black_hits(path, joins, fps=FPS):
    """Independent reading: consecutive frames below LUMA_FLOOR that
    cover a join. Not qc.measure_*. Mean RGB ≈ Y for pure colours."""
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
        mean = sum(chunk) / len(chunk)
        frames.append(mean)
    assert frames, path
    # limited-range black is ~16; floor matches qc.LUMA_FLOOR
    floor = qc.LUMA_FLOOR
    spans = []
    i = 0
    while i < len(frames):
        if frames[i] < floor:
            j = i
            while j < len(frames) and frames[j] < floor:
                j += 1
            if j - i >= 2:
                spans.append((i / fps, j / fps))
            i = j
        else:
            i += 1
    half = 0.5 / fps
    hits = []
    for j in joins:
        for start, end in spans:
            if start - half <= j <= end + half:
                hits.append(round(j, 4))
                break
    return hits


def _gap_row(findings):
    rows = [f for f in findings if f["check"] == "join_black_gap"]
    assert rows, findings
    return rows[0]


def test_t3_4_4_clean_hard_cut_passes(tmp_path, monkeypatch):
    """1s red | 1s blue. Join at 1.0s. No black span → PASS."""
    _use_real_mixer(monkeypatch)
    red = _color(str(tmp_path / "red.mp4"), 1.0, "red")
    blue = _color(str(tmp_path / "blue.mp4"), 1.0, "blue")
    out = _concat([red, blue], str(tmp_path / "clean.mp4"))
    joins = [1.0]
    independent = _independent_black_hits(out, joins)
    assert independent == [], independent

    expect = {"joins": joins, "want_audio": False}
    found = qc.run(out, "song", expect)
    row = _gap_row(found)
    assert row["verdict"] == qc.PASS, row
    assert row["kind"] == "song"
    assert row["unit"] == "spans"
    assert row["expected"] == 0
    assert row["measured"] == 0
    assert row["remedy_class"] == qc.REMEDY_REASSEMBLE
    assert qc.is_actionable(row["remedy_class"])


def test_t3_4_4_black_insert_at_join_rejects(tmp_path, monkeypatch):
    """1s red | 0.3s black | 1s blue. Planned join is where the clips
    should meet (1.0s). Black covers that join → REJECT."""
    _use_real_mixer(monkeypatch)
    red = _color(str(tmp_path / "red.mp4"), 1.0, "red")
    black = _color(str(tmp_path / "blk.mp4"), BLACK_S, "black")
    blue = _color(str(tmp_path / "blue.mp4"), 1.0, "blue")
    out = _concat([red, black, blue], str(tmp_path / "gapped.mp4"))
    joins = [1.0]
    independent = _independent_black_hits(out, joins)
    assert independent == [1.0], independent

    expect = {"joins": joins, "want_audio": False}
    row = _gap_row(qc.check_join_black_gap(out, expect, kind="song"))
    assert row["verdict"] == qc.REJECT, row
    assert row["measured"] == len(independent)
    assert row["expected"] == 0
    assert row["unit"] == "spans"
    assert row["measured"] == independent.__len__()
    assert row["remedy_class"] == qc.REMEDY_REASSEMBLE


def test_t3_4_4_clip_durations_drive_joins(tmp_path, monkeypatch):
    """clip_durations of the plan are the join source — not a second clock."""
    _use_real_mixer(monkeypatch)
    a = _color(str(tmp_path / "a.mp4"), 0.8, "red")
    b = _color(str(tmp_path / "b.mp4"), 0.8, "green")
    blk = _color(str(tmp_path / "blk.mp4"), BLACK_S, "black")
    c = _color(str(tmp_path / "c.mp4"), 0.8, "blue")
    # Plan said two joins at 0.8 and 1.6; black was inserted only at the
    # first seam. Second join is a clean cut after black+green? Layout:
    # a(0.8) | black(0.3) | b(0.8) | c(0.8). Plan joins from clip_durations
    # [0.8, 0.8, 0.8] → 0.8, 1.6. Black covers 0.8; 1.6 is mid-b after
    # the black shifted everything. Use joins from the plan that ignore
    # the inserted black: first seam only is what we assert fails.
    out = _concat([a, blk, b, c], str(tmp_path / "two.mp4"))
    expect = {"clip_durations": [0.8, 0.8, 0.8], "want_audio": False}
    # join_times_from plan: 0.8, 1.6 — black is at [0.8, 1.1], hits 0.8
    independent = _independent_black_hits(out, [0.8, 1.6])
    assert 0.8 in independent, independent

    row = _gap_row(qc.run(out, "song", expect))
    assert row["verdict"] == qc.REJECT, row
    assert row["measured"] >= 1
    assert row["expected"] == 0


def test_t3_4_4_without_joins_check_does_not_run(tmp_path, monkeypatch):
    """No assembly plan → no join_black_gap row. Vacuous green is refused."""
    _use_real_mixer(monkeypatch)
    red = _color(str(tmp_path / "red.mp4"), 0.5, "red")
    blue = _color(str(tmp_path / "blue.mp4"), 0.5, "blue")
    out = _concat([red, blue], str(tmp_path / "noplan.mp4"))
    found = qc.run(out, "song", {"want_audio": False})
    assert not [f for f in found if f["check"] == "join_black_gap"], found
