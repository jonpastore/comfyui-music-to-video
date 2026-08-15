"""T8-1, T8-2, T8-3, T8-2a, T8-10, T8-11: a take records the ask and the voice.

insert_take / pick live here. The audio job's land path is asserted in
test_t8_1_gen_audio_lands_as_take_and_keeps_the_ask -- a take that only
exists as an assets row cannot say what it was asked for after the song
moves. T8-10 is insert_voice: no row without a recorded source and a
recorded consent state, and the refusal names which is missing. T8-11 is
h_audio: a take generated with a voice records which, and one generated
without records that too.
"""
import os
import time

import pytest

import db


def _song(**fields):
    slug = fields.pop("slug", f"take-song-{time.time_ns()}")
    fields.setdefault("title", slug)
    return db.upsert_song(slug, **fields)


def test_takes_voices_take_voices_tables_exist():
    names = {r["name"] for r in db.q(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('takes','voices','take_voices')")}
    assert names == {"takes", "voices", "take_voices"}


def test_t8_1_take_keeps_original_tags_after_song_changes():
    sid = _song(style_text="drums, 128 bpm warehouse", lyrics="[verse]\nmeow",
                mp3_path="/orig.mp3")
    tid = db.insert_take(
        sid, "/takes/a.mp3", "generated",
        tags="drums, 128 bpm warehouse", lyrics="[verse]\nmeow",
        seed=42, duration=30.0, params={"cfg": 4.0, "steps": 50, "denoise": 1.0})
    slug = db.one("SELECT slug FROM songs WHERE id=?", sid)["slug"]
    db.upsert_song(slug, style_text="CHANGED tags", lyrics="CHANGED lyrics")
    take = db.get_take(tid)
    assert take["tags"] == "drums, 128 bpm warehouse"
    assert take["lyrics"] == "[verse]\nmeow"
    assert take["seed"] == 42
    assert take["duration"] == 30.0
    assert db.jset(take, "params_json") == {"cfg": 4.0, "steps": 50, "denoise": 1.0}
    song = db.one("SELECT style_text, lyrics FROM songs WHERE id=?", sid)
    assert song["style_text"] == "CHANGED tags"
    assert song["lyrics"] == "CHANGED lyrics"


def test_t8_2_insert_never_writes_songs_mp3_path():
    sid = _song(mp3_path="/keep/me.mp3")
    db.insert_take(sid, "/takes/new.mp3", "generated", tags="x")
    assert db.one("SELECT mp3_path FROM songs WHERE id=?", sid)["mp3_path"] == "/keep/me.mp3"


def test_t8_2_pick_is_a_separate_act_and_both_takes_remain_listed():
    sid = _song(mp3_path="/keep/me.mp3")
    a = db.insert_take(sid, "/takes/a.mp3", "generated", tags="a")
    b = db.insert_take(sid, "/takes/b.mp3", "generated", tags="b")
    assert {t["id"] for t in db.list_takes(sid)} == {a, b}
    assert all(t["picked"] == 0 for t in db.list_takes(sid))
    db.pick_take(b)
    listed = {t["id"]: t for t in db.list_takes(sid)}
    assert set(listed) == {a, b}
    assert listed[a]["picked"] == 0
    assert listed[b]["picked"] == 1
    assert listed[a]["path"] == "/takes/a.mp3"
    assert listed[b]["path"] == "/takes/b.mp3"
    # picking records the pick; it does not write the take over the song
    assert db.one("SELECT mp3_path FROM songs WHERE id=?", sid)["mp3_path"] == "/keep/me.mp3"


def test_t8_2_picking_one_song_does_not_unpick_another():
    s1 = _song(mp3_path="/s1.mp3")
    s2 = _song(mp3_path="/s2.mp3")
    a = db.insert_take(s1, "/s1/a.mp3", "generated", tags="a")
    b = db.insert_take(s2, "/s2/b.mp3", "generated", tags="b")
    db.pick_take(a)
    db.pick_take(b)
    assert db.get_take(a)["picked"] == 1
    assert db.get_take(b)["picked"] == 1


def test_t8_2_use_is_not_the_pick_and_both_takes_stay_listed():
    """T8-2: pick is a separate act; Use does not write songs.mp3_path.

    Both takes remain listed and playable after a second generation and
    after the pick. The Use route on an audio_gen asset is not the pick.
    """
    import app as appmod
    from urllib.parse import quote

    from fastapi.testclient import TestClient

    sid = _song(style_text="drums, 128 bpm warehouse", lyrics="[verse]\nmeow",
                mp3_path="/keep/me.mp3")
    _gen_audio(sid, seed=42)
    _gen_audio(sid, seed=43)
    listed = db.list_takes(sid)
    assert len(listed) == 2, "expected two takes after a second generation"
    first, second = listed
    keep = "/keep/me.mp3"

    gen = db.one("SELECT * FROM assets WHERE song_id=? AND kind='audio_gen' AND path=?",
                 sid, second["path"])
    assert gen is not None

    with TestClient(appmod.app) as client:
        used = client.post(f"/songs/{sid}/audio/{gen['id']}/use")
        assert used.status_code == 400, used.text
        assert "pick" in used.text.lower()
        assert db.one("SELECT mp3_path FROM songs WHERE id=?", sid)["mp3_path"] == keep

        picked = client.post(
            f"/songs/{sid}/takes/{second['id']}/pick",
            headers={"Accept": "application/json"})
        assert picked.status_code == 200, picked.text
        body = picked.json()
        assert body["picked"] == second["id"]
        by_id = {t["id"]: t for t in body["takes"]}
        assert set(by_id) == {first["id"], second["id"]}
        assert by_id[first["id"]]["picked"] is False
        assert by_id[second["id"]]["picked"] is True

        page = client.get(f"/songs/{sid}")
        assert page.status_code == 200, page.text

    rows = {t["id"]: t for t in db.list_takes(sid)}
    assert set(rows) == {first["id"], second["id"]}
    assert rows[first["id"]]["picked"] == 0
    assert rows[second["id"]]["picked"] == 1
    assert db.one("SELECT mp3_path FROM songs WHERE id=?", sid)["mp3_path"] == keep

    for take in rows.values():
        assert os.path.isfile(take["path"])
        src = "/media/" + quote(os.path.realpath(take["path"]), safe="/")
        assert src in page.text


def test_t8_3_take_records_generated_resynthesised_or_bridged():
    sid = _song()
    g = db.insert_take(sid, "/g.mp3", "generated")
    r = db.insert_take(sid, "/r.mp3", "resynthesised")
    b = db.insert_take(sid, "/b.mp3", "bridged")
    listed = {t["id"]: t["origin"] for t in db.list_takes(sid)}
    assert listed == {g: "generated", r: "resynthesised", b: "bridged"}
    with pytest.raises(ValueError, match="origin"):
        db.insert_take(sid, "/x.mp3", "repaint")


def test_t8_2a_song_style_text_is_copied_onto_the_take():
    sid = _song(style_text="drums, 128 bpm warehouse")
    tid = db.insert_take(sid, "/t.mp3", "generated")
    assert db.get_take(tid)["tags"] == "drums, 128 bpm warehouse"
    slug = db.one("SELECT slug FROM songs WHERE id=?", sid)["slug"]
    db.upsert_song(slug, style_text="CHANGED")
    assert db.get_take(tid)["tags"] == "drums, 128 bpm warehouse"


def test_voice_and_take_voice_rows_can_be_stored():
    vid = db.insert_voice("lead", "local", source="own recording", consent="own")
    sid = _song()
    tid = db.insert_take(sid, "/t.mp3", "generated", duration=20.0)
    db.assign_take_voice(tid, vid, start_secs=0, end_secs=20.0)
    rows = db.list_take_voices(tid)
    assert len(rows) == 1
    assert rows[0]["voice_id"] == vid
    assert rows[0]["start_secs"] == 0
    assert rows[0]["end_secs"] == 20.0


def test_t8_10_insert_without_source_fails_naming_source():
    with pytest.raises(ValueError, match="source"):
        db.insert_voice(f"v-{time.time_ns()}", "local", source="", consent="own")
    with pytest.raises(ValueError, match="source"):
        db.insert_voice(f"v-{time.time_ns()}", "local", source=None, consent="own")
    with pytest.raises(ValueError, match="source"):
        db.insert_voice(f"v-{time.time_ns()}", "local", source="   ", consent="own")


def test_t8_10_insert_without_consent_fails_naming_consent():
    with pytest.raises(ValueError, match="consent"):
        db.insert_voice(f"v-{time.time_ns()}", "local",
                        source="own recording", consent="")
    with pytest.raises(ValueError, match="consent"):
        db.insert_voice(f"v-{time.time_ns()}", "local",
                        source="own recording", consent=None)
    with pytest.raises(ValueError, match="consent"):
        db.insert_voice(f"v-{time.time_ns()}", "local",
                        source="own recording", consent="   ")


def test_t8_10_voice_with_source_and_consent_is_stored_and_usable():
    name = f"v-{time.time_ns()}"
    vid = db.insert_voice(name, "local", source="own recording", consent="own")
    voice = db.get_voice(vid)
    assert voice["name"] == name
    assert voice["kind"] == "local"
    assert voice["source"] == "own recording"
    assert voice["consent"] == "own"
    sid = _song()
    tid = db.insert_take(sid, "/t8-10.mp3", "generated", duration=10.0)
    db.assign_take_voice(tid, vid, start_secs=0, end_secs=10.0)
    rows = db.list_take_voices(tid)
    assert len(rows) == 1
    assert rows[0]["voice_id"] == vid
    assert db.get_voice(vid)["consent"] == "own"


def test_t8_1_gen_audio_lands_as_take_and_keeps_the_ask():
    """T8-1: the audio job writes takes, not a pointer at a song that moves.

    Changing the song after generate must leave the take's tags/lyrics/seed/
    duration/params as they were sent. Landing must not write songs.mp3_path
    (T8-2 / T6-A5).
    """
    import app as appmod

    sid = _song(style_text="drums, 128 bpm warehouse", lyrics="[verse]\nmeow",
                mp3_path="/keep/me.mp3")
    appmod.h_audio({
        "song_id": sid,
        "tags": "drums, 128 bpm warehouse",
        "lyrics": "[verse]\nmeow",
        "seconds": 12.0,
        "n": 1,
        "seed": 42,
        "denoise": 0.7,
    }, lambda _m: None)

    listed = db.list_takes(sid)
    assert len(listed) == 1, "gen_audio landed no takes row"
    take = listed[0]
    assert take["tags"] == "drums, 128 bpm warehouse"
    assert take["lyrics"] == "[verse]\nmeow"
    assert take["seed"] == 42
    assert take["duration"] == 12.0
    assert take["origin"] == "generated"
    assert db.jset(take, "params_json")["denoise"] == 0.7
    assert take["path"] and os.path.isfile(take["path"])
    assert os.path.realpath(take["path"]).startswith(os.path.realpath(db.DATA))
    assert db.one("SELECT mp3_path FROM songs WHERE id=?", sid)["mp3_path"] == "/keep/me.mp3"

    slug = db.one("SELECT slug FROM songs WHERE id=?", sid)["slug"]
    db.upsert_song(slug, style_text="CHANGED tags", lyrics="CHANGED lyrics")
    take = db.get_take(take["id"])
    assert take["tags"] == "drums, 128 bpm warehouse"
    assert take["lyrics"] == "[verse]\nmeow"
    assert take["seed"] == 42
    assert take["duration"] == 12.0
    assert db.jset(take, "params_json")["denoise"] == 0.7
    song = db.one("SELECT style_text, lyrics, mp3_path FROM songs WHERE id=?", sid)
    assert song["style_text"] == "CHANGED tags"
    assert song["lyrics"] == "CHANGED lyrics"
    assert song["mp3_path"] == "/keep/me.mp3"


def _gen_audio(sid, *, seed, voice_id=None):
    import app as appmod

    args = {
        "song_id": sid,
        "tags": "drums, 128 bpm warehouse",
        "lyrics": "[verse]\nmeow",
        "seconds": 12.0,
        "n": 1,
        "seed": seed,
        "denoise": 0.7,
    }
    if voice_id is not None:
        args["voice_id"] = voice_id
    appmod.h_audio(args, lambda _m: None)


def test_t8_11_generation_records_which_voice():
    """T8-11: generation writes which voice produced the take.

    One take with a voice and one without, both generated, both recording
    the distinction. An absent take_voices row is not enough: that is also
    how a take that never considered a voice looks. The take itself must
    say which voice, or that there was none.
    """
    sid = _song(style_text="drums, 128 bpm warehouse", lyrics="[verse]\nmeow",
                mp3_path="/keep/me.mp3")
    vid = db.insert_voice(f"lead-{time.time_ns()}", "local",
                          source="own recording", consent="own")
    _gen_audio(sid, seed=42, voice_id=vid)
    _gen_audio(sid, seed=43)

    listed = db.list_takes(sid)
    assert len(listed) == 2, "expected one take with a voice and one without"
    with_voice, without = listed
    assert db.jset(with_voice, "params_json")["voice_id"] == vid
    assigned = db.list_take_voices(with_voice["id"])
    assert [row["voice_id"] for row in assigned] == [vid]
    params = db.jset(without, "params_json")
    assert "voice_id" in params, "a take generated without a voice must record that"
    assert params["voice_id"] is None
    assert db.list_take_voices(without["id"]) == []
