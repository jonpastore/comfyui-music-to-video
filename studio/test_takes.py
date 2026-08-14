"""T8-1, T8-2, T8-3, T8-2a: a take records the ask, not a pointer at a moving song.

insert_take / pick live here. The audio job's land path is asserted in
test_t8_1_gen_audio_lands_as_take_and_keeps_the_ask -- a take that only
exists as an assets row cannot say what it was asked for after the song
moves.
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
