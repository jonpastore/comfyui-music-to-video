"""T1-3: JSON-only export produces the same ffmpeg argv as UI render.

docs/TRD-1 §4.2: an export through the JSON API alone, with no browser,
generates the identical ffmpeg argv to pressing render in the UI for the
same set. The two outputs agree on duration, frame count and integrated
loudness. Compare the command, not the file bytes (ffmpeg writes
creation_time). Fails if any value lives only in the DOM.
"""
import os
import subprocess
import time

from fastapi.testclient import TestClient

from conftest import _real_module, render_set_calls
import app as appmod
import db
import jobs
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


def _mp4(path, seconds, colour, freq, fps=16):
    _ffmpeg([
        "-f", "lavfi", "-i", f"color=c={colour}:s=320x240:r={fps}:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-shortest", path,
    ])


def _wait_job(jid, timeout=30):
    deadline = time.time() + timeout
    row = None
    while time.time() < deadline:
        row = jobs.get(jid)
        if row["status"] in ("done", "failed", "cancelled"):
            return row
        time.sleep(0.05)
    raise TimeoutError(f"job {jid} did not finish: {row}")


def _nb_frames(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-count_frames", "-show_entries", "stream=nb_read_frames",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return int((r.stdout or "0").strip() or 0)


def _json(client, method, path, **kw):
    headers = dict(kw.pop("headers", None) or {})
    headers["Accept"] = "application/json"
    r = getattr(client, method)(path, headers=headers, **kw)
    ctype = (r.headers.get("content-type") or "").split(";")[0].strip()
    assert r.status_code < 400, f"{method.upper()} {path} -> {r.status_code}: {r.text[:400]}"
    assert ctype == "application/json", (
        f"{method.upper()} {path} returned {ctype or 'no content-type'}")
    return r.json()


def test_t1_3_json_export_matches_ui_render_argv(tmp_path):
    """JSON POST /api/sets/{id}/render and UI POST /sets/{id}/render
    emit the same ffmpeg argv. Extra form fields on the UI POST are
    ignored — the stored model is the export.
    """
    assert callable(mixer.render_set_argv)

    clip_a = str(tmp_path / "a.mp4")
    clip_b = str(tmp_path / "b.mp4")
    _mp4(clip_a, 2.0, "red", 220)
    _mp4(clip_b, 2.0, "blue", 880)

    with TestClient(appmod.app) as client:
        song_a = _upload_song(client, "T1-3 Song A")
        song_b = _upload_song(client, "T1-3 Song B")
        created = _json(client, "post", "/api/sets",
                        json={"name": "T1-3 Argv Set", "mode": "video",
                              "tier": "pg13"})
        sid = created.get("set", created).get("id")
        assert sid, created

        _json(client, "post", f"/api/sets/{sid}/items",
              json={"song_id": song_a["id"], "transition": "fade", "secs": 0.4})
        _json(client, "post", f"/api/sets/{sid}/items",
              json={"song_id": song_b["id"], "transition": "cut", "secs": 0})

        items = db.q(
            "SELECT * FROM set_items WHERE set_id=? ORDER BY position", sid)
        assert len(items) == 2
        db.run(
            "UPDATE set_items SET in_secs=?, out_secs=?, gain_db=? WHERE id=?",
            0.25, 1.75, -6.0, items[0]["id"])
        db.run(
            "INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
            song_a["id"], "pg13", clip_a, time.time())
        db.run(
            "INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
            song_b["id"], "pg13", clip_b, time.time())

        before = len(render_set_calls)
        ui = client.post(
            f"/sets/{sid}/render",
            data={"gain_db": "12", "in_secs": "0", "secs": "9",
                  "transition": "cut"})
        assert ui.status_code in (200, 303), ui.text
        ui_job = db.one("SELECT * FROM jobs WHERE kind='render_set' ORDER BY id DESC")
        assert _wait_job(ui_job["id"])["status"] == "done", jobs.get(ui_job["id"])
        assert len(render_set_calls) == before + 1
        ui_items = [dict(it) for it in render_set_calls[-1]]

        js = _json(client, "post", f"/api/sets/{sid}/render")
        assert _wait_job(js["job_id"])["status"] == "done", jobs.get(js["job_id"])
        assert len(render_set_calls) == before + 2
        json_items = [dict(it) for it in render_set_calls[-1]]

    out = str(tmp_path / "compare.mp4")
    ui_argv = mixer.render_set_argv(ui_items, out)
    json_argv = mixer.render_set_argv(json_items, out)
    assert ui_argv == json_argv, (ui_argv, json_argv)
    assert "-ss" in ui_argv and "0.25" in ui_argv
    assert "-to" in ui_argv and "1.75" in ui_argv
    graph = ui_argv[ui_argv.index("-filter_complex") + 1]
    assert "volume=" in graph or "volume=" in "".join(ui_argv)

    ui_out = str(tmp_path / "ui.mp4")
    json_out = str(tmp_path / "json.mp4")
    mixer.render_set([dict(it) for it in ui_items], ui_out)
    mixer.render_set([dict(it) for it in json_items], json_out)

    ui_probe = mixer.probe(ui_out)
    json_probe = mixer.probe(json_out)
    gap = abs(ui_probe["duration"] - json_probe["duration"])
    assert gap <= mixer.SET_DURATION_TOLERANCE, (
        f"T1-3 duration: UI {ui_probe['duration']:.3f}s "
        f"JSON {json_probe['duration']:.3f}s gap={gap:.3f}s")

    ui_frames = _nb_frames(ui_out)
    json_frames = _nb_frames(json_out)
    assert ui_frames == json_frames, (ui_frames, json_frames)
    assert ui_frames > 0

    ui_lufs = effects.measure_loudness(ui_out)["lufs"]
    json_lufs = effects.measure_loudness(json_out)["lufs"]
    lu = abs(ui_lufs - json_lufs)
    assert lu <= 1.0, (
        f"T1-3 loudness: UI {ui_lufs} LUFS JSON {json_lufs} LUFS "
        f"delta={lu:.2f} LU")
