"""TRD-6 queue criteria.

T6-2: ready is not queued. A chain handed out in enqueue order is the
race this exists to catch. Asserted through jobs._claim — the one place
that decides what runs — not through a helper that wraps it (T6-A10).
"""
import os
import tempfile
import time

import db
import jobs


def _isolate():
    data = tempfile.mkdtemp(prefix="t6q_")
    db.DATA = data
    db.DB_PATH = os.path.join(data, "t.db")
    db._local.__dict__.clear()
    jobs.LOGS = os.path.join(data, "logs")
    jobs._capability_where = None
    if "t6" not in jobs._handlers:
        @jobs.handler("t6")
        def _t6(args, progress):
            return args
    return data


def test_t6_2_claim_skips_a_job_whose_predecessor_has_not_landed():
    """Queued is not ready. An independent job behind a blocked chain item
    is pulled first — one state would hand the chain out in the wrong order."""
    _isolate()

    pred = jobs.enqueue("t6", {"who": "pred"})
    blocked = jobs.enqueue("t6", {"who": "chain"}, depends_on=pred)
    later = jobs.enqueue("t6", {"who": "later"})
    assert jobs.get(blocked)["status"] == "queued"
    assert jobs.get(later)["status"] == "queued"

    first = jobs._claim()
    assert first is not None and first["id"] == pred, (
        f"_claim handed out job {first['id'] if first else None} while the "
        f"predecessor was still queued; ready is not distinct from queued")

    second = jobs._claim()
    assert second is not None and second["id"] == later, (
        f"_claim took {second['id'] if second else None}, not the independent "
        f"job behind the blocked chain item {blocked}")

    assert jobs._claim() is None, (
        "the successor was pulled before its predecessor landed")
    assert jobs.get(blocked)["status"] == "queued"


def test_t6_2_successor_is_pulled_once_predecessor_has_landed():
    """Positive half: after the predecessor is done, the successor becomes
    ready and _claim takes it. Refusing every early enqueue would stay green
    without this."""
    _isolate()

    pred = jobs.enqueue("t6", {"who": "pred"})
    succ = jobs.enqueue("t6", {"who": "succ"}, depends_on=pred)
    claimed = jobs._claim()
    assert claimed["id"] == pred
    db.run("UPDATE jobs SET status='done', finished=? WHERE id=?", 1.0, pred)

    pulled = jobs._claim()
    assert pulled is not None and pulled["id"] == succ, (
        f"predecessor landed but successor {succ} was not pulled "
        f"(got {pulled['id'] if pulled else None})")


def test_t6_7_land_requires_the_file():
    """A row claiming a landed artefact that is not on disk is refused.
    QC would otherwise measure nothing against it."""
    data = _isolate()
    missing = os.path.join(data, "gone.png")
    try:
        jobs.land(missing)
    except ValueError as e:
        assert "gone.png" in str(e)
    else:
        raise AssertionError("land() accepted a missing file")
    assert db.one("SELECT * FROM artefacts WHERE path=?", missing) is None, (
        "a missing file still wrote a landed artefacts row")


def test_t6_7_present_file_lands():
    """Positive half: a file that exists becomes a landed artefacts row."""
    data = _isolate()
    path = os.path.join(data, "sheet.png")
    with open(path, "wb") as f:
        f.write(b"png")
    assert jobs.land(path) == path
    row = db.one("SELECT * FROM artefacts WHERE path=?", path)
    assert row is not None, "land() did not write an artefacts row"
    assert row["status"] == "landed"
    assert os.path.isfile(path)


def test_t6_3_claim_skips_a_job_no_box_can_run():
    """Capability, not identity. where() empty is a refusal — the job
    stays queued and an independent job behind it is pulled."""
    _isolate()

    def _nowhere(key, backends):
        assert key == "wan22_s2v"
        return []

    jobs._capability_where = _nowhere
    blocked = jobs.enqueue("t6", {"who": "need-s2v", "requires": "wan22_s2v"})
    later = jobs.enqueue("t6", {"who": "later"})
    pulled = jobs._claim()
    assert pulled is not None and pulled["id"] == later, (
        f"_claim took {pulled['id'] if pulled else None}, not the job "
        f"that needs no model; capability match is not wired")
    assert jobs.get(blocked)["status"] == "queued"
    assert jobs._claim() is None


def test_t6_3_unconfirmed_box_is_a_candidate():
    """None is a candidate, not a refusal. where() listing an unconfirmed
    box must still make the job ready — dropping None as False was the
    models.where() bug T6-A6 exists to stop."""
    _isolate()

    def _ghost(key, backends):
        return [{"id": "9", "confirmed": False, "reachable": False}]

    jobs._capability_where = _ghost
    jid = jobs.enqueue("t6", {"requires": "qwen_image_edit_2511",
                              "backend": "peaches"})
    pulled = jobs._claim()
    assert pulled is not None and pulled["id"] == jid, (
        "an unconfirmed candidate was treated as a refusal")


def test_t6_5_happy_path_records_ordered_transitions():
    """One happy-path job produces queued -> running -> done, each with
    a non-null time. Green when there are no transitions otherwise."""
    _isolate()
    jid = jobs.enqueue("t6", {"who": "happy"})
    row = jobs._claim()
    assert row["id"] == jid
    jobs._run_one(row)
    chain = [(r["status"], r["at"]) for r in jobs.transitions(jid)]
    assert [s for s, _ in chain] == ["queued", "running", "done"], chain
    assert all(at is not None for _, at in chain), chain
    assert chain[0][1] <= chain[1][1] <= chain[2][1], chain


def test_t6_10_delete_set_item_removes_its_automation():
    """T1-2 / T6-10: intended item delete removes automation rows.
    Refusing all deletion would stay green without this."""
    _isolate()
    sid = db.upsert_song("t6-cascade", title="Cascade")
    set_id = db.run(
        "INSERT INTO sets (name, created, updated) VALUES (?,?,?)",
        "s", time.time(), time.time())
    item = db.run(
        "INSERT INTO set_items (set_id, song_id, position) VALUES (?,?,?)",
        set_id, sid, 0)
    other = db.run(
        "INSERT INTO set_items (set_id, song_id, position) VALUES (?,?,?)",
        set_id, sid, 1)
    db.run("INSERT INTO automation (set_item_id, lane, t, value) VALUES (?,?,?,?)",
           item, "gain_db", 0.0, -3.0)
    db.run("INSERT INTO automation (set_item_id, lane, t, value) VALUES (?,?,?,?)",
           other, "gain_db", 0.0, 0.0)

    db.delete_set_item(item)
    assert db.one("SELECT id FROM set_items WHERE id=?", item) is None
    assert db.q("SELECT * FROM automation WHERE set_item_id=?", item) == []
    assert db.one("SELECT id FROM set_items WHERE id=?", other) is not None
    assert db.one("SELECT * FROM automation WHERE set_item_id=?", other) is not None


def test_t6_10_delete_song_does_not_orphan_clips_refs_findings():
    """Positive half of 'does not silently orphan': an intended song
    delete removes clips, refs, findings and the item's automation."""
    _isolate()
    sid = db.upsert_song("t6-song", title="Orphan Check")
    clip = "/tmp/t6-clip.mp4"
    ref = "/tmp/t6-ref.png"
    db.run("INSERT INTO clips (song_id, tier, clip_idx, path, status) VALUES (?,?,?,?,?)",
           sid, "r", 0, clip, "done")
    db.run("INSERT INTO refs (song_id, tier, clip_idx, path, seed) VALUES (?,?,?,?,?)",
           sid, "r", 0, ref, 1)
    db.run("""INSERT INTO findings
                (path, kind, tier, check_name, verdict, status, created)
              VALUES (?,?,?,?,?,?,?)""",
           clip, "clip", 1, "duration", "flag", "open", time.time())
    set_id = db.run(
        "INSERT INTO sets (name, created, updated) VALUES (?,?,?)",
        "s", time.time(), time.time())
    item = db.run(
        "INSERT INTO set_items (set_id, song_id, position) VALUES (?,?,?)",
        set_id, sid, 0)
    db.run("INSERT INTO automation (set_item_id, lane, t, value) VALUES (?,?,?,?)",
           item, "gain_db", 0.0, -1.0)

    db.delete_song_rows(sid)
    assert db.one("SELECT id FROM songs WHERE id=?", sid) is None
    assert db.q("SELECT * FROM clips WHERE song_id=?", sid) == []
    assert db.q("SELECT * FROM refs WHERE song_id=?", sid) == []
    assert db.q("SELECT * FROM findings WHERE path=?", clip) == []
    assert db.q("SELECT * FROM set_items WHERE song_id=?", sid) == []
    assert db.q("SELECT * FROM automation WHERE set_item_id=?", item) == []
