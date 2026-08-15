"""T1-24: adding an export format is a row, not a code change.

docs/TRD-1 §9: the format list is a table of ffmpeg parameter sets.
Asserted by adding a test-only row and rendering through it. Asserting
the table is a table proves nothing reaches ffmpeg — the unique codec
and metadata from that row must be in the argv _run_ffmpeg received
and in the file it wrote.
"""
import os
import subprocess

from conftest import _real_module


mixer = _real_module("mixer")
assert mixer is not None, "mixer.py failed to import"


_FMT = "t1_24_probe"
_COMMENT = "t1-24-row"
_ROW = (
    "-c:v", "mpeg4",
    "-q:v", "8",
    "-pix_fmt", "yuv420p",
    "-c:a", "libmp3lame",
    "-b:a", "96k",
    "-metadata", f"comment={_COMMENT}",
)


def _ffmpeg(args):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *args],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r


def _mp4(path, seconds=1.0):
    _ffmpeg([
        "-f", "lavfi", "-i", f"color=c=red:s=320x240:r=16:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-shortest", path,
    ])


def _probe_field(path, entries, extra=None):
    cmd = ["ffprobe", "-v", "error", *(extra or []),
           "-show_entries", entries, "-of", "csv=p=0", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return (r.stdout or "").strip()


def test_t1_24_test_only_format_row_reaches_ffmpeg(tmp_path):
    """A row inserted into EXPORT_FORMATS is the encode. Display-only
    tables stay green until this render uses mpeg4 + the comment tag."""
    assert isinstance(mixer.EXPORT_FORMATS, dict)
    assert _FMT not in mixer.EXPORT_FORMATS
    shipped = list(mixer.EXPORT_FORMATS[mixer.DEFAULT_EXPORT_FORMAT])
    assert "mpeg4" not in shipped
    assert _COMMENT not in " ".join(shipped)

    clip = str(tmp_path / "in.mp4")
    out = str(tmp_path / "out.mp4")
    _mp4(clip)
    items = [{"video": clip, "audio": clip, "transition": "cut", "secs": 0.0}]

    captured = []
    orig_run = mixer._run_ffmpeg

    def _spy(args, progress=None, total_duration=None, stage="ffmpeg"):
        captured.append(list(args))
        return orig_run(args, progress, total_duration=total_duration, stage=stage)

    mixer.EXPORT_FORMATS[_FMT] = _ROW
    mixer._run_ffmpeg = _spy
    try:
        mixer.render_set(items, out, fmt=_FMT)
    finally:
        mixer._run_ffmpeg = orig_run
        mixer.EXPORT_FORMATS.pop(_FMT, None)

    assert os.path.isfile(out), "render_set wrote no file"
    assert captured, "_run_ffmpeg was not called — nothing reached ffmpeg"
    argv = captured[-1]
    for token in _ROW:
        assert token in argv, f"{token!r} from the test row missing in ffmpeg argv: {argv}"
    assert "libx264" not in argv

    vcodec = _probe_field(out, "stream=codec_name",
                          ["-select_streams", "v:0"])
    acodec = _probe_field(out, "stream=codec_name",
                          ["-select_streams", "a:0"])
    comment = _probe_field(out, "format_tags=comment")
    assert vcodec == "mpeg4", f"video codec {vcodec!r} — table did not reach ffmpeg"
    assert acodec == "mp3", f"audio codec {acodec!r} — table did not reach ffmpeg"
    assert comment == _COMMENT, f"metadata {comment!r} — table did not reach ffmpeg"
