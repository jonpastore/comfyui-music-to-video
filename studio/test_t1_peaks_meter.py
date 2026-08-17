"""Set timeline draws mixer.peaks; live loudness is on-demand.

Peaks: .tl-block uses data-peaks / data-reason, not waveform_png as a
background-image. GET /api/sets/{id} reports the same pairs (T6-A2) and
does not remux.

Live meter: GET /api/sets/{id}/loudness remuxes and names I/TP via
mixer.export_loudness. Default GET /api/sets/{id} does not mix.
"""
import json
import os
import re

from conftest import _real_module
from fastapi.testclient import TestClient

import app as appmod
import db
import sets_service
from test_app import _upload_song


effects = _real_module("effects")
mixer = _real_module("mixer")
assert effects is not None
assert mixer is not None


def _new_set(client, name):
    r = client.post("/sets/new", data={"name": name, "mode": "audio"})
    assert r.status_code in (200, 303), r.text
    return db.one("SELECT * FROM sets WHERE name=?", name)


def test_t1_timeline_draws_peaks_not_png_background():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Peaks Timeline Song")
        row = _new_set(client, "Peaks Timeline Set")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})
        page = client.get(f"/sets/{row['id']}").text
        assert "has-wave" in page, page[:800]
        assert "data-peaks=" in page
        assert f'data-song="{song["id"]}"' in page
        assert not re.search(r"background-image:\s*url\([^)]*waveform", page), page[:800]
        m = re.search(r"data-peaks='(\[[^\']*\])'", page) or re.search(
            r'data-peaks="(\[[^\"]*\])"', page)
        assert m, "data-peaks missing"
        pairs = json.loads(m.group(1))
        assert pairs and all(len(p) == 2 for p in pairs), pairs


def test_t1_15_empty_envelope_surfaces_reason_on_timeline():
    with TestClient(appmod.app) as client:
        sid = db.upsert_song("t1-peaks-no-audio", title="No Audio Peaks Timeline")
        db.run("UPDATE songs SET mp3_path=? WHERE id=?", "/no/such/file.mp3", sid)
        row = _new_set(client, "Empty Peaks Set")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": sid, "transition": "cut", "secs": "0"})
        page = client.get(f"/sets/{row['id']}").text
        assert re.search(r'data-reason="(missing|no_audio|unreadable)"', page), page[:800]
        assert "tl-wave-reason" in page or "wave-empty" in page


def test_t6_a2_html_and_json_report_the_same_peaks():
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T6-A2 Peaks Song")
        row = _new_set(client, "T6-A2 Peaks Set")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})
        html = client.get(f"/sets/{row['id']}")
        js = client.get(f"/api/sets/{row['id']}")
    assert html.status_code == 200 and js.status_code == 200
    body = js.json()
    assert "timeline" in body and body["timeline"]
    tl = body["timeline"][0]
    assert tl["song_id"] == song["id"]
    assert tl["n"] == len(tl["pairs"])
    assert tl["reason"] is None
    assert tl["pairs"]
    assert "loudness" not in body, "default GET remuxed the set"
    m = re.search(r"data-peaks='(\[[^\']*\])'", html.text) or re.search(
        r'data-peaks="(\[[^\"]*\])"', html.text)
    assert m
    assert json.loads(m.group(1)) == tl["pairs"]


def test_api_sets_get_does_not_call_mix_audio(monkeypatch):
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("GET /api/sets remuxed")

    monkeypatch.setattr(sets_service.mixer, "mix_audio", boom)
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "No Remux Song")
        row = _new_set(client, "No Remux Set")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})
        r = client.get(f"/api/sets/{row['id']}")
    assert r.status_code == 200, r.text
    assert called["n"] == 0


def test_live_loudness_reuses_export_loudness_numbers(monkeypatch, tmp_path):
    song_path = tmp_path / "tone.wav"
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:sample_rate=48000:duration=1",
         "-c:a", "pcm_s16le", str(song_path)],
        capture_output=True, check=True)

    seen = {}
    real_export = mixer.export_loudness

    def _wrap(path, items=None):
        rec = real_export(path, items)
        seen["rec"] = rec
        return rec

    monkeypatch.setattr(appmod.mixer, "export_loudness", _wrap)
    monkeypatch.setattr(sets_service.mixer, "export_loudness", _wrap)
    monkeypatch.setattr(sets_service.mixer, "mix_audio",
                        lambda items, out, progress=None: (
                            open(out, "wb").write(open(song_path, "rb").read()) or out))

    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Live Meter Song")
        db.run("UPDATE songs SET mp3_path=? WHERE id=?", str(song_path), song["id"])
        row = _new_set(client, "Live Meter Set")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})
        rec = sets_service.live_loudness(db.one("SELECT * FROM sets WHERE id=?", row["id"]))
        js = client.get(f"/api/sets/{row['id']}/loudness")
    assert rec is not None and "rec" in seen
    assert rec["lufs"] == seen["rec"]["lufs"]
    assert rec["flagged"] == seen["rec"]["flagged"]
    assert rec["source"] == "live_mix"
    assert js.status_code == 200
    assert js.json()["loudness"]["lufs"] == rec["lufs"]


def test_live_loudness_hot_mix_is_flagged(monkeypatch):
    """Off-target arm goes through live_loudness, not a handmade dict."""
    hot = {
        "lufs": -3.0, "true_peak_db": 0.0,
        "target_lufs": effects.LOUDNORM_I,
        "target_true_peak_db": effects.LOUDNORM_TP,
        "flagged": True,
    }

    monkeypatch.setattr(sets_service.mixer, "mix_audio",
                        lambda items, out, progress=None: out)
    monkeypatch.setattr(sets_service.mixer, "export_loudness",
                        lambda path, items=None: dict(hot))

    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Hot Mix Song")
        row = _new_set(client, "Hot Mix Set")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})
        rec = sets_service.live_loudness(db.one("SELECT * FROM sets WHERE id=?", row["id"]))
        js = client.get(f"/api/sets/{row['id']}/loudness").json()
    assert rec["flagged"] is True
    assert rec["lufs"] == -3.0
    assert js["loudness"]["flagged"] is True
    assert abs(rec["lufs"] - rec["target_lufs"]) > effects.LOUDNESS_TOLERANCE_LU


def test_live_loudness_empty_set_is_none():
    with TestClient(appmod.app) as client:
        row = _new_set(client, "Empty Loud Set")
        js = client.get(f"/api/sets/{row['id']}").json()
        meter = client.get(f"/api/sets/{row['id']}/loudness").json()
        page = client.get(f"/sets/{row['id']}").text
    assert "loudness" not in js or js.get("loudness") is None
    assert meter["loudness"] is None
    assert 'data-meter="loudness"' not in page


def test_join_drag_handler_still_targets_tl_join():
    js = open(os.path.join(os.path.dirname(__file__), "static", "app.js"),
              encoding="utf-8").read()
    assert ".tl-join" in js
    assert "pointerdown" in js
    assert "/join" in js
    assert "drawTlWaves" in js
    assert "data-peaks" in js
    assert "data-meter-url" in open(
        os.path.join(os.path.dirname(__file__), "templates", "_set_editor.html"),
        encoding="utf-8").read()
