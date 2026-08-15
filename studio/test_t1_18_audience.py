"""T1-18 / T1-20: three audiences, one data model.

docs/TRD-1 §7. Easy is a feature set, not a CSS class. Switching audience
must persist mode_audience, must not mutate set_items or automation, and
must change the mix: easy engages the master loudnorm (T1-20d's one
application point) so a set with per-item defaults cleared lands near
effects.LOUDNORM_I only when easy is on.

Graph assertions are the cheap half. The measured-loudness differential
is the half that goes red if easy is a stylesheet.
"""
import json
import os
import re
import subprocess
import tempfile

from conftest import _real_module, mix_audio_calls
from fastapi.testclient import TestClient

import app as appmod
import automation
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


def _new_set(client, name="Audience Set"):
    r = client.post("/sets/new", data={"name": name, "mode": "audio"})
    assert r.status_code in (200, 303), r.text
    return db.one("SELECT * FROM sets WHERE name=?", name)


def _items_snapshot(set_id):
    return [dict(r) for r in db.q(
        "SELECT * FROM set_items WHERE set_id=? ORDER BY id", set_id)]


def _auto_snapshot(item_ids):
    if not item_ids:
        return []
    ph = ",".join("?" * len(item_ids))
    return [dict(r) for r in db.q(
        f"SELECT set_item_id, lane, t, value, curve FROM automation "
        f"WHERE set_item_id IN ({ph}) ORDER BY set_item_id, lane, t",
        *item_ids)]


def _cleared(item=None):
    """Per-item defaults off: no loudnorm on the item. T1-18's 'cleared' half."""
    out = {"effects_json": json.dumps({"loudnorm": False})}
    if item:
        out.update(item)
        out["effects_json"] = json.dumps({"loudnorm": False})
    return out


# ------------------------------------------------------------------ T1-20 --

def test_t1_20_mode_audience_column_persists_and_reads_back():
    """Deleting the column, or a write that never stores, fails this."""
    with TestClient(appmod.app) as client:
        row = _new_set(client, "Persist Audience")
        assert row["mode_audience"] == "normal", dict(row)
        r = client.post(f"/sets/{row['id']}", data={
            "name": row["name"], "mode": "audio", "mode_audience": "easy"})
        assert r.status_code in (200, 303), r.text
        again = db.one("SELECT * FROM sets WHERE id=?", row["id"])
        assert again["mode_audience"] == "easy", dict(again)
        r = client.post(f"/sets/{row['id']}", data={
            "name": row["name"], "mode": "audio", "mode_audience": "advanced"})
        assert r.status_code in (200, 303), r.text
        assert db.one("SELECT mode_audience FROM sets WHERE id=?",
                      row["id"])["mode_audience"] == "advanced"


def test_t1_20_switch_does_not_mutate_items_or_automation():
    """easy → advanced → easy. Items and curves stay put. mode_audience moves."""
    with TestClient(appmod.app) as client:
        song1 = _upload_song(client, "Aud Song 1")
        song2 = _upload_song(client, "Aud Song 2")
        row = _new_set(client, "Switch Audience")
        sid = row["id"]
        client.post(f"/sets/{sid}/items",
                    data={"song_id": song1["id"], "transition": "fade", "secs": "1.5"})
        client.post(f"/sets/{sid}/items",
                    data={"song_id": song2["id"], "transition": "cut", "secs": "0"})
        items = db.q("SELECT * FROM set_items WHERE set_id=? ORDER BY position", sid)
        client.post(f"/sets/{sid}/items/{items[0]['id']}",
                    data={"in_secs": "0.5", "out_secs": "2.5", "gain_db": "-3.0",
                          "transition": "fade", "secs": "1.5",
                          "effects_json": '{"eq_kill": {"low_db": -6, "mid_db": 0, "high_db": 2}}'})
        stored = automation.save(items[0]["id"], "gain_db", [(0.0, -6.0), (1.5, 0.0)])
        assert stored, "T1-20 is vacuous without a stored curve"

        before_items = _items_snapshot(sid)
        before_auto = _auto_snapshot([it["id"] for it in items])
        assert before_auto, "automation rows must exist before the switch"

        for audience in ("easy", "advanced", "easy"):
            r = client.post(f"/sets/{sid}", data={
                "name": "Switch Audience", "mode": "audio",
                "mode_audience": audience})
            assert r.status_code in (200, 303), r.text
            got = db.one("SELECT mode_audience FROM sets WHERE id=?", sid)
            assert got["mode_audience"] == audience, audience
            assert _items_snapshot(sid) == before_items, audience
            assert _auto_snapshot([it["id"] for it in items]) == before_auto, audience


def test_t1_20_affordances_easy_is_not_advanced():
    """The half that fails when the switch is a no-op CSS class."""
    easy = appmod.audience_affordances("easy")
    advanced = appmod.audience_affordances("advanced")
    normal = appmod.audience_affordances("normal")
    assert easy, "easy must expose a feature set"
    assert advanced, "advanced must expose a feature set"
    assert easy != advanced
    assert "one_button_master" in easy
    assert "one_button_master" not in advanced
    assert "mastering_chain" in advanced
    assert "mastering_chain" not in easy
    assert "automation_lanes" in advanced
    assert "automation_lanes" not in easy
    assert easy != normal
    assert "effects" in normal and "effects" not in easy


def test_t1_20_page_easy_hides_advanced_controls():
    """Affordance sets reach the HTML. A CSS class with the same fields fails."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Page Aud Song")
        row = _new_set(client, "Page Audience")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})
        client.post(f"/sets/{row['id']}", data={
            "name": "Page Audience", "mode": "audio", "mode_audience": "easy"})
        easy_page = client.get(f"/sets/{row['id']}").text
        assert 'name="mode_audience"' in easy_page
        assert 'value="easy"' in easy_page
        assert "one-button master" in easy_page.lower() or "one button master" in easy_page.lower()
        assert "textarea" not in easy_page or 'name="effects_json"' not in easy_page.split("textarea")[0]
        assert 'textarea name="effects_json"' not in easy_page.replace("\n", " ")
        assert 'type="hidden" name="gain_db"' in easy_page
        assert not re.search(r'<input[^>]*type="number"[^>]*name="gain_db"', easy_page)
        assert not re.search(r'<input[^>]*name="gain_db"[^>]*type="number"', easy_page)

        client.post(f"/sets/{row['id']}", data={
            "name": "Page Audience", "mode": "audio", "mode_audience": "advanced"})
        adv_page = client.get(f"/sets/{row['id']}").text
        assert 'textarea name="effects_json"' in adv_page.replace("\n", " ")
        assert re.search(r'<input[^>]*name="gain_db"', adv_page)
        assert "loudnorm" in adv_page.lower()


# ------------------------------------------------------------------ T1-18 --

def test_t1_18_easy_engages_master_and_strips_item_loudnorm():
    """Filter-graph half. A no-op easy leaves neither master nor a differential."""
    cleared = _cleared()
    off = [dict(cleared, mode_audience="normal")]
    on = [dict(cleared, mode_audience="easy")]

    assert not mixer.master_engaged(off)
    assert mixer.master_engaged(on)

    off_chains = mixer.item_chains(off)
    on_chains = mixer.item_chains(on)
    off_master, off_tag = mixer._master_lines(off, [], "a0")
    on_master, on_tag = mixer._master_lines(on, [], "a0")

    assert all(c.count("loudnorm") == 0 for c in off_chains), off_chains
    assert off_master == [] and off_tag == "a0", (off_master, off_tag)

    assert all(c.count("loudnorm") == 0 for c in on_chains), on_chains
    assert on_tag == "master"
    assert sum(l.count("loudnorm") for l in on_master) == 1
    assert effects.loudnorm_filter() in on_master[-1]


def test_t1_18_easy_master_is_the_same_chain_as_a_gain_curve():
    """T1-20c: easy's one-button master is _master_lines, not a second impl."""
    easy = [_cleared({"mode_audience": "easy"})]
    curved = [{"automation": {"suppress_loudnorm": True}}]
    easy_lines, easy_tag = mixer._master_lines(easy, [], "a0")
    curve_lines, curve_tag = mixer._master_lines(curved, [], "a0")
    assert easy_lines == curve_lines
    assert easy_tag == curve_tag == "master"


def test_t1_18_easy_is_not_a_second_loudnorm_on_default_items():
    """T1-20d: easy-on + default items still has exactly one loudnorm per path."""
    its = [{"mode_audience": "easy"}, {"mode_audience": "easy"}]
    per = [c.count("loudnorm") for c in mixer.item_chains(its)]
    mls, _ = mixer._master_lines(its, [], "a0")
    n_master = sum(l.count("loudnorm") for l in mls)
    assert n_master == 1
    assert max(p + n_master for p in per) == 1, (per, n_master)


def test_t1_18_render_stamps_mode_audience_on_items():
    """The T1-20d lesson: the decision has to reach the call site, not just exist."""
    with TestClient(appmod.app) as client:
        song = _upload_song(client, "Stamp Aud Song")
        row = _new_set(client, "Stamp Audience")
        client.post(f"/sets/{row['id']}/items",
                    data={"song_id": song["id"], "transition": "cut", "secs": "0"})
        client.post(f"/sets/{row['id']}", data={
            "name": "Stamp Audience", "mode": "audio", "mode_audience": "easy"})
        before = len(mix_audio_calls)
        r = client.post(f"/sets/{row['id']}/render")
        assert r.status_code in (200, 303), r.text
        job = db.one("SELECT * FROM jobs WHERE kind='render_set' ORDER BY id DESC")
        jrow = _wait_job(job["id"])
        assert jrow["status"] == "done", jrow
        assert len(mix_audio_calls) == before + 1
        sent = mix_audio_calls[-1]
        assert sent, "render sent no items"
        assert all(it.get("mode_audience") == "easy" for it in sent), sent


def test_t1_18_easy_loudness_lands_near_target_and_cleared_off_does_not(tmp_path):
    """Same items, easy on vs off, defaults cleared. Measured, not the graph.

    A hot sine with loudnorm off sits far from -16 LUFS. Easy must pull it
    to LOUDNORM_I ± 1.0 LU. If easy is a CSS class, both sides miss or both
    hit and this fails.
    """
    src = tmp_path / "hot.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "sine=frequency=1000:sample_rate=48000:duration=3",
         "-af", "volume=20dB", "-c:a", "pcm_s16le", str(src)],
        capture_output=True, check=True)
    base = _cleared({"audio": str(src), "transition": "cut", "secs": 0})
    easy_out = str(tmp_path / "easy.mp3")
    off_out = str(tmp_path / "off.mp3")
    mixer.mix_audio([dict(base, mode_audience="easy")], easy_out)
    mixer.mix_audio([dict(base, mode_audience="normal")], off_out)
    easy = effects.measure_loudness(easy_out)
    off = effects.measure_loudness(off_out)
    assert abs(easy["lufs"] - effects.LOUDNORM_I) <= 1.0, (
        f"easy integrated {easy['lufs']} LUFS, want {effects.LOUDNORM_I} ± 1.0")
    assert abs(off["lufs"] - effects.LOUDNORM_I) > 1.0, (
        f"easy-off with defaults cleared landed at {off['lufs']} LUFS, "
        f"within 1.0 LU of {effects.LOUDNORM_I} — easy did not change the output")
