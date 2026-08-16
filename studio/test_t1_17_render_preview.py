"""T1-17 render preview is a real ffmpeg span, not the waveform picture.

docs/TRD-1 §6.2: a "render preview" produces a bounded ffmpeg render
(default 20 s around the playhead) through the same mix_audio/render_set
path as the full render, and is the only preview that claims to be
accurate. Asserted by rendering the same span twice — preview vs full
render then cut — and comparing measured loudness and duration.
mixer.waveform_png() stays the picture.
"""
import os
import subprocess

from fastapi.testclient import TestClient

from conftest import _real_module
import app as appmod
import db
from test_app import _upload_song


effects = _real_module("effects")
mixer = _real_module("mixer")
assert effects is not None, "effects.py failed to import"
assert mixer is not None, "mixer.py failed to import"


def _ffmpeg(args):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *args],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r


def _wav(path, seconds, freq, volume_db=0.0):
    af = f"volume={volume_db}dB" if volume_db else "anull"
    _ffmpeg([
        "-f", "lavfi",
        "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
        "-af", af, "-c:a", "pcm_s16le", path,
    ])


def _cut(src, dst, start, span):
    """Independent cut of a mix. Not mixer.render_preview: if preview
    shared this helper, a wrong window would pass both sides."""
    _ffmpeg([
        "-i", src, "-ss", f"{start:.6f}", "-t", f"{span:.6f}",
        "-c:a", "libmp3lame", "-b:a", "320k", dst,
    ])


def test_t1_17_default_span_is_20s_around_the_playhead():
    assert mixer.PREVIEW_SPAN == 20.0
    assert mixer.preview_window(50, 100) == (40.0, 60.0)
    assert mixer.preview_window(0, 100) == (0.0, 20.0)
    assert mixer.preview_window(100, 100) == (80.0, 100.0)
    assert mixer.preview_window(10, 15) == (0.0, 15.0)
    assert mixer.preview_window(8, 16, secs=4) == (6.0, 10.0)


def test_t1_17_preview_is_not_a_proxy():
    """T1-16's GET /preview is the proxy. This one claims accuracy."""
    assert callable(mixer.render_preview)


def test_t1_17_preview_matches_cut_from_full(tmp_path):
    """Same span twice: preview vs full mix then cut. Wrong window fails.

    Two items, cut join, no loudnorm. Quiet 220 Hz then loud 880 Hz.
    Playhead on the join, 4 s window = 2 s quiet + 2 s loud. A preview
    that took the first 4 s (all quiet) or the last 4 s (all loud)
    cannot match the cut's loudness.
    """
    quiet = str(tmp_path / "quiet.wav")
    loud = str(tmp_path / "loud.wav")
    _wav(quiet, 6, 220, volume_db=-18)
    _wav(loud, 6, 880, volume_db=0)
    items = [
        {"audio": quiet, "transition": "cut", "secs": 0,
         "effects_json": '{"loudnorm": false}'},
        {"audio": loud, "transition": "cut", "secs": 0,
         "effects_json": '{"loudnorm": false}'},
    ]
    at, secs = 6.0, 4.0
    start, end = mixer.preview_window(at, mixer.set_duration(items, key="audio"),
                                      secs=secs)
    assert (start, end) == (4.0, 8.0), (start, end)

    preview = str(tmp_path / "preview.mp3")
    result = mixer.render_preview(items, preview, at=at, secs=secs, key="audio")
    assert result["is_proxy"] is False, result
    assert result["secs"] == secs
    assert result["start"] == start and result["end"] == end
    assert os.path.isfile(preview)

    full = str(tmp_path / "full.mp3")
    mixer.mix_audio([dict(it) for it in items], full)
    cut = str(tmp_path / "cut.mp3")
    _cut(full, cut, start, end - start)

    pred = mixer.probe(preview)["duration"]
    actual = mixer.probe(cut)["duration"]
    gap = abs(pred - actual)
    assert gap <= mixer.SET_DURATION_TOLERANCE, (
        f"T1-17 duration: preview {pred:.3f}s cut {actual:.3f}s "
        f"gap={gap:.3f}s (tol={mixer.SET_DURATION_TOLERANCE})")

    loud_p = effects.measure_loudness(preview)
    loud_c = effects.measure_loudness(cut)
    lu = abs(loud_p["lufs"] - loud_c["lufs"])
    assert lu <= 1.0, (
        f"T1-17 loudness: preview {loud_p['lufs']} LUFS "
        f"cut {loud_c['lufs']} LUFS delta={lu:.2f} LU")


def test_t1_17_waveform_png_is_still_the_picture():
    """The static picture stays waveform_png. Peaks are numbers; this is not."""
    src = open(os.path.join(os.path.dirname(__file__), "mixer.py"),
               encoding="utf-8").read()
    assert "def waveform_png(" in src
    page = open(os.path.join(os.path.dirname(__file__), "templates",
                             "set_edit.html"), encoding="utf-8").read()
    assert "background-image" in page
    assert "data-peaks=" in page or "tl-wave" in page


def test_t1_17_preview_endpoint_is_accurate_and_defaults_to_20s():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T1-17 Preview Song")
        client.post("/sets/new", data={"name": "T1-17 Preview Set", "mode": "audio"})
        row = db.one("SELECT * FROM sets WHERE name=?", "T1-17 Preview Set")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})

        defaulted = client.get(f"/api/sets/{row['id']}/preview/render")
        assert defaulted.status_code == 200, defaulted.text
        data = defaulted.json()
        assert data["is_proxy"] is False, data
        assert data["secs"] == mixer.PREVIEW_SPAN
        assert os.path.isfile(data["path"])

        bounded = client.get(
            f"/api/sets/{row['id']}/preview/render",
            params={"at": 1.0, "secs": 4.0})
        assert bounded.status_code == 200, bounded.text
        data = bounded.json()
        assert data["is_proxy"] is False
        assert data["at"] == 1.0
        assert data["secs"] == 4.0

        proxy = client.get(f"/api/sets/{row['id']}/preview")
        assert proxy.status_code == 200
        assert proxy.json()["is_proxy"] is True


def test_t1_17_missing_set_is_404_empty_is_400():
    with TestClient(appmod.app) as client:
        r = client.get("/api/sets/999999/preview/render")
        assert r.status_code == 404
        client.post("/sets/new", data={"name": "T1-17 Empty Set", "mode": "audio"})
        row = db.one("SELECT * FROM sets WHERE name=?", "T1-17 Empty Set")
        r = client.get(f"/api/sets/{row['id']}/preview/render")
        assert r.status_code == 400
