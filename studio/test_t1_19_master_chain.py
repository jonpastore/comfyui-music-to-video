"""T1-19: one-button master is a named, versioned chain recorded on the render.

docs/TRD-1 §7 / §8a. Easy reuses _master_lines (T1-20c). This slice is the
other half: what ran is a named versioned record, readable afterwards, and
changing a parameter moves the output — recording metadata over a no-op
fails the measured half.
"""
import json
import os
import subprocess
import tempfile

from conftest import _real_module, mix_audio_calls
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


def test_t1_19_one_button_master_is_named_and_versioned():
    """A hidden set of values has no name and no version."""
    chain = mixer.one_button_master()
    assert chain["name"] and isinstance(chain["name"], str), chain
    assert isinstance(chain["version"], int) and chain["version"] >= 1, chain
    params = chain["params"]
    assert params["I"] == effects.LOUDNORM_I, params
    assert params["TP"] == effects.LOUDNORM_TP, params
    assert params["LRA"] == effects.LOUDNORM_LRA, params

    easy = [_cleared({"mode_audience": "easy"})]
    applied = mixer.applied_master_chain(easy)
    assert applied == chain, (applied, chain)
    off = mixer.applied_master_chain([_cleared({"mode_audience": "normal"})])
    assert off is None, off


def test_t1_19_changing_parameter_moves_graph_and_output(tmp_path):
    """The recorded chain is the one that ran. Metadata over a no-op fails."""
    src = _hot_sine(tmp_path / "hot.wav")
    easy = _cleared({"audio": src, "transition": "cut", "secs": 0,
                     "mode_audience": "easy"})
    moved_i = -23.0
    default = mixer.applied_master_chain([easy])
    other = mixer.applied_master_chain(
        [dict(easy, master_params={"I": moved_i})])
    assert default["name"] == other["name"]
    assert default["version"] == other["version"]
    assert default["params"]["I"] != other["params"]["I"], (default, other)
    assert other["params"]["I"] == moved_i

    default_lines, default_tag = mixer._master_lines([easy], [], "a0")
    other_lines, other_tag = mixer._master_lines(
        [dict(easy, master_params={"I": moved_i})], [], "a0")
    assert default_tag == other_tag == "master"
    assert default_lines != other_lines, default_lines
    assert f"I={default['params']['I']:.1f}" in default_lines[-1]
    assert f"I={moved_i:.1f}" in other_lines[-1]

    out_a = str(tmp_path / "default.mp3")
    out_b = str(tmp_path / "moved.mp3")
    mixer.mix_audio([easy], out_a)
    mixer.mix_audio([dict(easy, master_params={"I": moved_i})], out_b)
    loud_a = effects.measure_loudness(out_a)
    loud_b = effects.measure_loudness(out_b)
    assert abs(loud_a["lufs"] - default["params"]["I"]) <= 1.0, loud_a
    assert abs(loud_b["lufs"] - moved_i) <= 1.0, loud_b
    assert abs(loud_a["lufs"] - loud_b["lufs"]) > 1.0, (loud_a, loud_b)


def test_t1_19_render_records_the_chain_that_ran():
    """What easy applied is on the render row and readable afterwards.

    Easy-off with no curve records nothing: stamping the default chain on
    every render would pass the 'readable' half while the master never ran.
    """
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T1-19 Chain Song")
        row = _new_set(client, "T1-19 Chain Set")
        sid = row["id"]
        client.post(f"/sets/{sid}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})

        client.post(f"/sets/{sid}", data={
            "name": row["name"], "mode": "audio", "mode_audience": "normal"})
        r = client.post(f"/sets/{sid}/render")
        assert r.status_code in (200, 303), r.text
        job = db.one("SELECT * FROM jobs WHERE kind='render_set' ORDER BY id DESC")
        assert _wait_job(job["id"])["status"] == "done"
        off_asset = db.one("SELECT * FROM assets WHERE kind='set' ORDER BY id DESC")
        off_meta = json.loads(off_asset["meta_json"] or "{}")
        assert not off_meta.get("master_chain"), off_meta

        client.post(f"/sets/{sid}", data={
            "name": row["name"], "mode": "audio", "mode_audience": "easy"})
        r = client.post(f"/sets/{sid}/render")
        assert r.status_code in (200, 303), r.text
        job = db.one("SELECT * FROM jobs WHERE kind='render_set' ORDER BY id DESC")
        assert _wait_job(job["id"])["status"] == "done"
        on_asset = db.one("SELECT * FROM assets WHERE kind='set' ORDER BY id DESC")
        on_meta = json.loads(on_asset["meta_json"] or "{}")
        recorded = on_meta.get("master_chain")
        expect = mixer.one_button_master()
        assert recorded == expect, (recorded, expect)

        page = client.get(f"/sets/{sid}").text
        assert expect["name"] in page
        assert f"v{expect['version']}" in page
        assert str(expect["params"]["I"]) in page
