"""T1-25: an export names measured integrated loudness and true peak.

docs/TRD-1 §9. Both halves: an in-tolerance render records its numbers and
is NOT flagged; a deliberately out-of-tolerance one IS. Writing numbers
and never flagging satisfies the first half alone. Measurement lives in
effects.py beside LOUDNORM_I / loudnorm_filter(); the export path names
the same object on the asset row.
"""
import json
import os
import subprocess
import tempfile

from conftest import _real_module
from fastapi.testclient import TestClient

import app as appmod
import db
import jobs


effects = _real_module("effects")
mixer = _real_module("mixer")
assert effects is not None, "effects.py failed to import"
assert mixer is not None, "mixer.py failed to import"


def _mp3_bytes(seconds=1):
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-t", str(seconds), "-i", "anullsrc",
         "-c:a", "libmp3lame", path],
        capture_output=True, check=True)
    data = open(path, "rb").read()
    os.remove(path)
    return data


def _upload_song(client, title):
    client.post("/songs", data={"title": title, "album": "", "genre": ""},
                files={"mp3": (f"{title}.mp3", _mp3_bytes(), "audio/mpeg")})
    return db.one("SELECT * FROM songs WHERE title=?", title)


def _wait_job(jid, timeout=10):
    import time
    deadline = time.time() + timeout
    row = None
    while time.time() < deadline:
        row = jobs.get(jid)
        if row["status"] in ("done", "failed", "cancelled"):
            return row
        time.sleep(0.05)
    raise TimeoutError(f"job {jid} did not finish: {row}")


def _new_set(client, name):
    r = client.post("/sets/new", data={"name": name, "mode": "audio"})
    assert r.status_code in (200, 303), r.text
    return db.one("SELECT * FROM sets WHERE name=?", name)


def _cleared(item=None):
    out = {"effects_json": json.dumps({"loudnorm": False})}
    if item:
        out.update(item)
        out["effects_json"] = json.dumps({"loudnorm": False})
    return out


def _hot_sine(path, seconds=3):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=1000:sample_rate=48000:duration={seconds}",
         "-af", "volume=20dB", "-c:a", "pcm_s16le", str(path)],
        capture_output=True, check=True)
    return str(path)


def test_t1_25_in_tolerance_records_numbers_and_is_not_flagged(tmp_path):
    """A render that lands on its own target names I/TP and is not flagged."""
    src = _hot_sine(tmp_path / "hot.wav")
    items = [{"audio": src, "transition": "cut", "secs": 0}]
    out = str(tmp_path / "ok.mp3")
    mixer.mix_audio(items, out)
    rec = mixer.export_loudness(out, items)
    measured = effects.measure_loudness(out)
    assert rec["lufs"] == measured["lufs"], rec
    assert rec["true_peak_db"] == measured["true_peak_db"], rec
    assert rec["target_lufs"] == effects.LOUDNORM_I, rec
    assert rec["target_true_peak_db"] == effects.LOUDNORM_TP, rec
    assert abs(rec["lufs"] - rec["target_lufs"]) <= effects.LOUDNESS_TOLERANCE_LU, rec
    assert rec["flagged"] is False, rec


def test_t1_25_out_of_tolerance_is_flagged(tmp_path):
    """Writing numbers and never flagging is the mutation this catches."""
    src = _hot_sine(tmp_path / "hot.wav")
    items = [_cleared({"audio": src, "transition": "cut", "secs": 0,
                       "mode_audience": "normal"})]
    out = str(tmp_path / "hot.mp3")
    mixer.mix_audio(items, out)
    rec = mixer.export_loudness(out, items)
    measured = effects.measure_loudness(out)
    assert rec["lufs"] == measured["lufs"], rec
    assert rec["true_peak_db"] == measured["true_peak_db"], rec
    assert abs(rec["lufs"] - rec["target_lufs"]) > effects.LOUDNESS_TOLERANCE_LU, rec
    assert rec["flagged"] is True, rec


def test_t1_25_flags_against_own_target_not_the_default(tmp_path):
    """Tolerance is of the render's own target, not a hardcoded -16."""
    src = _hot_sine(tmp_path / "hot.wav")
    items = [{"audio": src, "transition": "cut", "secs": 0}]
    out = str(tmp_path / "ok.mp3")
    mixer.mix_audio(items, out)
    on_default = effects.export_loudness(out, I=effects.LOUDNORM_I)
    assert on_default["flagged"] is False, on_default
    against_broadcast = effects.export_loudness(out, I=-23.0)
    assert against_broadcast["target_lufs"] == -23.0, against_broadcast
    assert against_broadcast["flagged"] is True, against_broadcast


def test_t1_25_render_names_loudness_on_the_asset_row(monkeypatch):
    """The export path writes the measurement onto assets.meta_json."""
    named = {
        "lufs": -15.4,
        "true_peak_db": -1.7,
        "target_lufs": -16.0,
        "target_true_peak_db": -1.5,
        "flagged": False,
    }
    seen = {}

    def _fake(path, items=None):
        seen["path"] = path
        return dict(named)

    monkeypatch.setattr(appmod.mixer, "export_loudness", _fake)
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T1-25 Loud Song")
        row = _new_set(client, "T1-25 Loud Set")
        sid = row["id"]
        client.post(f"/sets/{sid}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})
        r = client.post(f"/sets/{sid}/render")
        assert r.status_code in (200, 303), r.text
        job = db.one("SELECT * FROM jobs WHERE kind='render_set' ORDER BY id DESC")
        assert _wait_job(job["id"])["status"] == "done"
        asset = db.one("SELECT * FROM assets WHERE kind='set' ORDER BY id DESC")
        meta = json.loads(asset["meta_json"] or "{}")
        assert meta.get("loudness") == named, meta
        assert seen.get("path") == asset["path"], seen

        hot = dict(named, lufs=-3.0, flagged=True)
        monkeypatch.setattr(appmod.mixer, "export_loudness",
                            lambda path, items=None: dict(hot))
        r = client.post(f"/sets/{sid}/render")
        assert r.status_code in (200, 303), r.text
        job = db.one("SELECT * FROM jobs WHERE kind='render_set' ORDER BY id DESC")
        assert _wait_job(job["id"])["status"] == "done"
        flagged = db.one("SELECT * FROM assets WHERE kind='set' ORDER BY id DESC")
        flagged_meta = json.loads(flagged["meta_json"] or "{}")
        assert flagged_meta["loudness"]["flagged"] is True, flagged_meta
        assert flagged_meta["loudness"]["lufs"] == -3.0, flagged_meta
        page = client.get(f"/sets/{sid}").text
        assert "-3.0" in page
        assert "off target" in page
