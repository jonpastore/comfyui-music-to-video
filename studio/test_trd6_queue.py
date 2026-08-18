"""TRD-6 queue criteria.

T6-2: ready is not queued. A chain handed out in enqueue order is the
race this exists to catch. Asserted through jobs._claim — the one place
that decides what runs — not through a helper that wraps it (T6-A10).
"""
import inspect
import json
import math
import os
import re
import sqlite3
import tempfile
import threading
import time

from PIL import Image

import db
import jobs
import qc
import qc_service
from conftest import _real_module


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


def test_t6_2_failed_predecessor_fails_successor():
    """A failed pred must not leave Auto QC queued forever (job 332)."""
    _isolate()
    pred = jobs.enqueue("t6", {"who": "pred"})
    succ = jobs.enqueue("t6", {"who": "qc"}, depends_on=pred)
    assert jobs._claim()["id"] == pred
    db.run("UPDATE jobs SET status='failed', finished=?, error=? WHERE id=?",
           1.0, "clip plan miss", pred)
    assert jobs._claim() is None
    got = jobs.get(succ)
    assert got["status"] == "failed", got["status"]
    assert "predecessor failed" in (got["error"] or "")


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


def _png(path, size=(64, 64), split=True):
    """A sheet that image QC can pass: not blank, not uniform."""
    im = Image.new("RGB", size, (180, 40, 40))
    if split:
        for x in range(size[0] // 2):
            for y in range(size[1]):
                im.putpixel((x, y), (40, 180, 40))
    im.save(path)
    return path


def _spellings(data, name="sheet.png"):
    """Two strings for one file: symlink vs dotted path. abspath keeps both."""
    real_dir = os.path.join(data, "real")
    os.makedirs(real_dir, exist_ok=True)
    path = os.path.join(real_dir, name)
    link_dir = os.path.join(data, "via")
    if not os.path.lexists(link_dir):
        os.symlink(real_dir, link_dir)
    a = os.path.join(link_dir, name)
    b = os.path.join(real_dir, ".", name)
    assert a != b
    assert os.path.abspath(a) != os.path.abspath(b)
    return path, a, b


def test_t6_8_two_spellings_one_artefact_row():
    """T6-8: inserting the same file by two spellings yields one artefacts
    row, stored as one absolute resolved path."""
    data = _isolate()
    path, a, b = _spellings(data)
    with open(path, "wb") as f:
        f.write(b"png")
    jobs.land(a)
    jobs.land(b)
    rows = db.q("SELECT path FROM artefacts")
    assert len(rows) == 1, rows
    stored = rows[0]["path"]
    assert stored == os.path.realpath(path)
    assert os.path.isabs(stored)
    assert stored != a and stored != b


def test_t6_8_findings_path_joins_artefacts_path():
    """T6-8: findings.path joins artefacts.path after QC via the other
    spelling. Two keys for one file is the defect this exists to catch."""
    data = _isolate()
    path, a, b = _spellings(data)
    _png(path)
    jobs.land(a)
    found = qc_service.run_artefact(b, "image")
    assert found
    canon = os.path.realpath(path)
    assert all(f["path"] == canon for f in found), found
    joined = db.q(
        "SELECT f.id FROM findings f JOIN artefacts a ON a.path = f.path")
    assert joined, "findings.path did not join artefacts.path"
    assert db.one("SELECT COUNT(*) AS n FROM artefacts")["n"] == 1


def test_t6_9_present_file_qc_can_pass():
    """T6-9 positive half: a present file runs QC for real and can pass.
    Green if QC never runs otherwise."""
    data = _isolate()
    path = os.path.join(data, "ok.png")
    _png(path)
    jobs.land(path)
    found = qc_service.run_artefact(path, "image")
    assert found, "QC produced no findings for a present file"
    assert all(f["verdict"] == qc.PASS for f in found), found


def test_t6_9_deleted_after_row_is_a_finding():
    """T6-9: a file that disappears after its artefacts row exists is a
    finding, not a skip or a pass. QC via the other spelling still joins."""
    data = _isolate()
    path, a, b = _spellings(data, "gone.png")
    _png(path)
    jobs.land(a)
    assert db.one("SELECT * FROM artefacts") is not None
    os.remove(path)
    found = qc_service.run_artefact(b, "image")
    assert found, "QC skipped a missing artefact"
    assert any(f["verdict"] != qc.PASS for f in found), found
    joined = db.q("""SELECT f.id FROM findings f
                     JOIN artefacts a ON a.path = f.path
                     WHERE f.verdict != 'pass'""")
    assert joined, "the missing-artefact finding did not join its artefacts row"


def test_t6_12_repair_links_original_expect():
    """T6-12: approve() copies the original artefacts.expect_json onto the
    repaired candidate, and a re-check without an explicit expect judges
    that same question and can change the outcome."""
    data = _isolate()
    path = os.path.join(data, "orig.png")
    _png(path, size=(10, 10))
    want = {"width": 100, "height": 100}
    landed = jobs.land(path, expect=want)
    found = qc_service.run_artefact(landed, "image")
    row = next(f for f in found if f["check"] == "resolution")
    assert row["verdict"] != qc.PASS, row
    fid = db.one(
        "SELECT id FROM findings WHERE path=? AND check_name='resolution'",
        landed)["id"]
    qc_service.approve(fid)

    repairs = db.q("SELECT * FROM artefacts WHERE path != ?", landed)
    assert len(repairs) == 1, repairs
    dest = repairs[0]["path"]
    assert dest != landed
    assert json.loads(repairs[0]["expect_json"]) == want

    _png(dest, size=(100, 100))
    again = qc_service.run_artefact(dest, "image")
    res = [f for f in again if f["check"] == "resolution"]
    assert res, "re-check did not consult the linked expectation"
    assert res[0]["verdict"] == qc.PASS, res[0]
    assert str(res[0]["expected"]) == "100x100"


def test_t6_7_stamp_lands_only_when_the_file_exists(tmp_path):
    """pipeline._stamp goes through jobs.land: missing file is not a row."""
    _isolate()
    pipe = _real_module("pipeline")
    missing = str(tmp_path / "gone.mp4")
    there = str(tmp_path / "here.mp4")
    open(there, "wb").write(b"x")
    db.run("INSERT INTO artefacts (path, expect_json, created) VALUES (?,?,?)",
           jobs.canonical_path(there), '{"frames": 81}', time.time())
    pipe._stamp([missing, there], "0", "cerberus", "swarm")
    assert db.one("SELECT * FROM artefacts WHERE path=?",
                  jobs.canonical_path(missing)) is None, (
        "_stamp wrote a landed row for a file that is not on disk")
    row = db.one("SELECT * FROM artefacts WHERE path=?", jobs.canonical_path(there))
    assert row["status"] == "landed"
    assert row["host"] == "cerberus"
    assert row["expect_json"] == '{"frames": 81}', (
        "re-stamp wiped expect_json")

_T6_13_INFO = {
    "duration": 4.8125, "width": 832, "height": 480, "fps": 16.8312,
    "has_audio": False, "has_video": True,
}


def _silence_qc_pixels(monkeypatch):
    """Keep T6-13 on duration/frames. luma/frozen would shell out."""
    monkeypatch.setattr(qc.mixer, "probe", lambda p: dict(_T6_13_INFO))
    monkeypatch.setattr(qc, "_ffprobe_frames", lambda p: 81)
    monkeypatch.setattr(qc, "_readings", lambda *a, **k: [40.0] * 8)
    monkeypatch.setattr(qc, "_stderr_events", lambda *a, **k: [])


def test_t6_13_absent_expect_skips_duration_and_frame_count(monkeypatch):
    """No recorded expectation: duration/frame comparisons do not run,
    and expected is never filled from the file itself."""
    data = _isolate()
    path = os.path.join(data, "orphan.mp4")
    with open(path, "wb") as f:
        f.write(b"\x00" * 3000)
    _silence_qc_pixels(monkeypatch)

    found = qc.run(path, "clip", {})
    compared = [x for x in found if x["check"] in ("duration", "frame_count")]
    assert compared == [], compared
    for x in compared:
        assert x.get("expected") != x.get("measured"), x


def test_t6_13_present_expect_runs_duration_and_frame_count(monkeypatch):
    """Positive half: with an expectation the comparisons run and can fail."""
    data = _isolate()
    path = os.path.join(data, "asked.mp4")
    with open(path, "wb") as f:
        f.write(b"\x00" * 3000)
    _silence_qc_pixels(monkeypatch)

    found = qc.run(path, "clip", {"duration": 30.0, "frames": 505})
    by_check = {x["check"]: x for x in found}
    assert "duration" in by_check and "frame_count" in by_check, by_check
    assert by_check["duration"]["verdict"] == qc.REJECT
    assert by_check["frame_count"]["verdict"] == qc.REJECT
    assert by_check["frame_count"]["measured"] == 81
    assert by_check["frame_count"]["expected"] == 505
    assert by_check["duration"]["expected"] == 30.0

    match = qc.run(path, "clip", {"duration": 4.8125, "frames": 81})
    ok = {x["check"]: x for x in match}
    assert ok["duration"]["verdict"] == qc.PASS
    assert ok["frame_count"]["verdict"] == qc.PASS


def test_t6_13_stamp_expect_does_not_invent_a_baseline_from_the_file():
    """Absent sidecar stays absent. Reading the clip to fill expect_json
    would be the self-comparison T6-13 exists to stop."""
    data = _isolate()
    path = os.path.join(data, "unstamped.mp4")
    with open(path, "wb") as f:
        f.write(b"\x00" * 3000)
    stamp = _real_module("pipeline")._stamp_expect
    stamp([{"clip_idx": 0, "path": path}], {})
    row = db.one("SELECT * FROM artefacts WHERE path=?", path)
    assert row is None or not row["expect_json"], row

    stamp(
        [{"clip_idx": 0, "path": path}],
        {0: {"frames": 81, "duration": 4.8125}})
    stamped = db.one("SELECT expect_json FROM artefacts WHERE path=?", path)
    assert stamped and stamped["expect_json"]
    assert json.loads(stamped["expect_json"])["frames"] == 81


# ----------------------------------------------------------------- T6-13a --

# The hole §3.4 opened: third-decimal drift moves a clip count at the boundary.
_T6_13A_DURATION = 195.792


def _assert_no_reprobe(src, name):
    lowered = src.lower()
    for needle in ("ffprobe", "estimate_duration", "mixer.probe", "probe("):
        assert needle not in lowered, (
            f"{name} re-probes the song ({needle!r}); songs.duration is the "
            f"authority once the column is set:\n{src}")


def test_t6_13a_songs_duration_is_the_authority_and_nothing_reprobes():
    """TRD-1 §3.2, TRD-2 §3.4 and TRD-3 §4.4 all read songs.duration.
    A later ffprobe on those paths fails this test."""
    import app as appmod
    import build_song
    import qc_service

    data = _isolate()
    mp3 = os.path.join(data, "track.mp3")
    render = os.path.join(data, "assembled.mp4")
    with open(mp3, "wb") as f:
        f.write(b"ID3")
    with open(render, "wb") as f:
        f.write(b"\x00" * 3000)
    sid = db.upsert_song("t6-13a", title="Authority",
                         duration=_T6_13A_DURATION, mp3_path=mp3)
    db.run("INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
           sid, "r", render, time.time())
    song = db.one("SELECT * FROM songs WHERE id=?", sid)

    # TRD-1 §3.2 / TRD-2 §3.4: clip count dividend is the column.
    n = appmod.clip_count(song)
    assert n == build_song.n_clips_for(_T6_13A_DURATION)
    assert n == math.ceil(round(_T6_13A_DURATION, 3) / build_song.CHUNK)

    captured = []

    def _capture(path, kind, expect=None, items=None, record_pass=True):
        captured.append((kind, dict(expect or {})))
        return []

    orig = qc_service.run_artefact
    qc_service.run_artefact = _capture
    try:
        appmod.h_qc({"song_id": sid, "tier": "r"}, lambda m: None)
    finally:
        qc_service.run_artefact = orig

    song_expects = [e for kind, e in captured if kind == "song"]
    assert song_expects, captured
    assert song_expects[0]["duration"] == _T6_13A_DURATION
    assert round(song_expects[0]["duration"], 3) == 195.792

    grok = _real_module("grok")
    _assert_no_reprobe(inspect.getsource(appmod.clip_count), "app.clip_count")
    _assert_no_reprobe(inspect.getsource(appmod.h_qc), "app.h_qc")
    _assert_no_reprobe(inspect.getsource(qc_service.run_song),
                       "qc_service.run_song")
    _assert_no_reprobe(inspect.getsource(build_song.n_clips_for),
                       "build_song.n_clips_for")
    _assert_no_reprobe(inspect.getsource(grok.generate_storyboard),
                       "grok.generate_storyboard")
    assert 'song["duration"]' in inspect.getsource(grok.generate_storyboard)
    assert 'song["duration"]' in inspect.getsource(appmod.clip_count)
    assert 'song["duration"]' in inspect.getsource(qc_service.run_song)


# ----------------------------------------------------------------- T6-16 --

def test_t6_16_web_query_succeeds_during_long_handler():
    """T6-16: nothing holds a write transaction across a long handler.
    A concurrent web read (the queue the pages poll) succeeds while a
    fake render is in flight. A write lock held across that window
    would make BEGIN IMMEDIATE on another connection time out."""
    import app as appmod

    _isolate()
    inside = threading.Event()
    release = threading.Event()

    @jobs.handler("t6_long")
    def _long(args, progress):
        inside.set()
        if not release.wait(5):
            raise AssertionError("release never came")
        return {"ok": True}

    jid = jobs.enqueue("t6_long", {"who": "render"})
    row = jobs._claim()
    assert row["id"] == jid

    err = []

    def _work():
        try:
            jobs._run_one(row)
        except Exception as e:
            err.append(e)

    worker = threading.Thread(target=_work, daemon=True)
    worker.start()
    assert inside.wait(2), "handler never started"

    t0 = time.monotonic()
    listed = jobs.recent()
    active = jobs.active()
    ctx = appmod.queue_ctx()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5, (
        f"web-visible query blocked {elapsed:.2f}s during a long handler")
    assert any(r["id"] == jid for r in listed), listed
    assert active is not None and active["id"] == jid
    assert any(e["job"]["id"] == jid for e in ctx["queue_active"]), ctx

    other = sqlite3.connect(db.DB_PATH, timeout=0.3)
    try:
        other.execute("BEGIN IMMEDIATE")
        other.execute("COMMIT")
    except sqlite3.OperationalError as e:
        raise AssertionError(
            f"write lock held across the long handler: {e}") from e
    finally:
        other.close()

    release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert not err, err
    assert jobs.get(jid)["status"] == "done"


# ----------------------------------------------------------------- T6-14 --

def _repair_args(data, name="broken.png"):
    """A finding plus an approved repair job. dest artefacts come only from land()."""
    src = os.path.join(data, name)
    _png(src)
    qc_service.record([{
        "path": src, "kind": "image", "tier": 1, "check": "resolution",
        "verdict": "reject", "measured": "64x64", "expected": "100x100",
        "unit": "px", "detail": "small", "remedy": "re-render",
    }])
    fid = db.one(
        "SELECT id FROM findings WHERE path=?", jobs.canonical_path(src))["id"]
    qc_service.approve(fid)
    args = json.loads(
        db.one("SELECT args_json FROM jobs WHERE kind='repair' ORDER BY id DESC")[
            "args_json"])
    return fid, src, args


def _write_repaired(src, dest, args, progress):
    with open(src, "rb") as f:
        payload = f.read()
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(payload + b"-repaired")
    return dest


def test_t6_14_successful_handler_writes_land_and_findings():
    """Positive half: a finished handler lands the dest and stamps the finding.
    The kill-rollback half stays green if nothing is ever written."""
    data = _isolate()
    fid, src, args = _repair_args(data)
    dest = jobs.canonical_path(args["repair_path"])
    orig = qc_service.dispatch_repair
    try:
        qc_service.dispatch_repair = _write_repaired
        qc_service.h_repair(args, lambda m: None)
    finally:
        qc_service.dispatch_repair = orig

    landed = db.one("SELECT * FROM artefacts WHERE path=?", dest)
    assert landed is not None and landed["status"] == "landed", landed
    row = qc_service.get(fid)
    assert row["status"] == qc_service.REPAIRED
    assert row["repair_path"] == dest
    assert os.path.isfile(src)


def test_t6_14_kill_mid_handler_leaves_no_half_write():
    """T6-14: land + findings update are one transaction. Kill after land
    and neither write is visible. A committed land with an unstamped
    finding is the half-write this exists to catch."""
    data = _isolate()
    fid, src, args = _repair_args(data)
    dest = jobs.canonical_path(args["repair_path"])
    real_land = jobs.land

    def _land_then_die(*a, **k):
        real_land(*a, **k)
        raise RuntimeError("killed mid-handler")

    orig = qc_service.dispatch_repair
    jobs.land = _land_then_die
    try:
        qc_service.dispatch_repair = _write_repaired
        qc_service.h_repair(args, lambda m: None)
    except RuntimeError as e:
        assert "killed mid-handler" in str(e)
    else:
        raise AssertionError("handler was not killed after land")
    finally:
        jobs.land = real_land
        qc_service.dispatch_repair = orig

    landed = db.one("SELECT * FROM artefacts WHERE path=?", dest)
    assert landed is None or landed["status"] != "landed", (
        f"kill after land left a landed artefacts row: {landed}")
    row = qc_service.get(fid)
    assert row["status"] != qc_service.REPAIRED, row["status"]
    assert row["repair_path"] in (None, ""), row["repair_path"]


# ----------------------------------------------------------------- T6-A2 --

_T6_A2_NOW = 1_700_000_100.0
_T6_A2_RUNNING_ELAPSED = 58
_T6_A2_RECENT_ELAPSED = 15


def test_t6_a2_html_and_json_report_the_same_queue_numbers(monkeypatch):
    """T6-A2: HTML /queue and JSON /queue report the same numbers for the
    same jobs. Distinctive 1/2/58/15/5 so two empty answers cannot pass."""
    import app as appmod
    from fastapi.testclient import TestClient

    _isolate()
    monkeypatch.setattr(appmod.time, "time", lambda: _T6_A2_NOW)
    monkeypatch.setattr(jobs, "start", lambda: None)
    jobs._capability_where = lambda key, backends: []

    running = jobs.enqueue("t6", {"who": "running"})
    wait_a = jobs.enqueue("t6", {"who": "wait-a", "requires": "wan22_s2v"})
    wait_b = jobs.enqueue("t6", {"who": "wait-b", "requires": "wan22_s2v"})
    claimed = jobs._claim()
    assert claimed["id"] == running
    db.run("UPDATE jobs SET started=? WHERE id=?",
           _T6_A2_NOW - _T6_A2_RUNNING_ELAPSED, running)

    done = jobs.enqueue("t6", {"who": "done"})
    db.run("UPDATE jobs SET status='done', started=?, finished=? WHERE id=?",
           _T6_A2_NOW - 20, _T6_A2_NOW - 5, done)

    with TestClient(appmod.app) as client:
        html = client.get("/queue")
        js = client.get("/queue", headers={"Accept": "application/json"})

    assert html.status_code == 200, html.text
    page = html.text
    ctype = (js.headers.get("content-type") or "").split(";")[0].strip()
    assert js.status_code == 200, js.text
    assert ctype == "application/json", (
        f"/queue Accept:json returned {ctype or 'no content-type'}, not JSON: "
        f"{js.text[:200]}")
    assert "<html" not in js.text.lower(), js.text[:200]
    body = js.json()

    html_running = int(re.search(r"(\d+) running", page).group(1))
    html_waiting = int(re.search(r"(\d+) waiting", page).group(1))
    html_refresh = int(re.search(r"refreshing every (\d+)s", page).group(1))
    html_elapsed = [int(n) for n in re.findall(r'class="num">(\d+)s', page)]
    html_ids = [int(n) for n in re.findall(r"/jobs/(\d+)/log", page)]

    json_ids = [e["id"] for e in
                body["active"] + body["waiting_jobs"] + body["recent_jobs"]]
    json_elapsed = [round(e["elapsed"]) for e in
                    body["active"] + body["recent_jobs"]
                    if e.get("elapsed") is not None]

    assert html_running == body["running"] == 1, (html_running, body)
    assert html_waiting == body["waiting"] == 2, (html_waiting, body)
    assert html_refresh == body["refresh_secs"] == 5, (html_refresh, body)
    assert body["recent"] == 1, body
    assert html_elapsed == json_elapsed == [
        _T6_A2_RUNNING_ELAPSED, _T6_A2_RECENT_ELAPSED], (html_elapsed, json_elapsed)
    assert html_ids == json_ids == [running, wait_a, wait_b, done], (
        html_ids, json_ids)


def test_t6_a2_html_and_json_report_the_same_review_queue_numbers():
    """T6-A2 / review: GET /qc HTML and GET /api/qc/findings report the same
    open-queue numbers. Distinctive 4.8/30.0 and 896/1024 so two empty
    answers cannot pass. Pass rows stay out of the default queue."""
    import app as appmod
    from fastapi.testclient import TestClient

    _isolate()
    qc_service.record([
        {"path": "/tmp/t6a2-a.mp4", "kind": "clip", "tier": 1,
         "check": "duration", "verdict": "reject", "measured": "4.8",
         "expected": "30.0", "unit": "s", "detail": "short render",
         "remedy": "re-render"},
        {"path": "/tmp/t6a2-b.png", "kind": "image", "tier": 1,
         "check": "resolution", "verdict": "flag", "measured": "896",
         "expected": "1024", "unit": "px", "detail": "narrow",
         "remedy": "re-render pinned"},
        {"path": "/tmp/t6a2-c.png", "kind": "image", "tier": 1,
         "check": "blank", "verdict": "pass", "measured": "0",
         "expected": "0", "unit": "", "detail": "ok", "remedy": ""},
    ])

    with TestClient(appmod.app) as client:
        html = client.get("/qc")
        js = client.get("/api/qc/findings")

    assert html.status_code == 200, html.text
    page = html.text
    ctype = (js.headers.get("content-type") or "").split(";")[0].strip()
    assert js.status_code == 200, js.text
    assert ctype == "application/json", (
        f"/api/qc/findings returned {ctype or 'no content-type'}, not JSON: "
        f"{js.text[:200]}")
    assert "<html" not in js.text.lower(), js.text[:200]
    body = js.json()
    rows = body["findings"]
    assert len(rows) == 2, rows

    html_ids = [int(n) for n in re.findall(r'data-finding="(\d+)"', page)]
    html_measured = re.findall(r'data-measured="([^"]*)"', page)
    html_expected = re.findall(r'data-expected="([^"]*)"', page)
    html_units = re.findall(r'data-unit="([^"]*)"', page)
    html_checks = re.findall(r'data-check="([^"]*)"', page)

    json_ids = [int(f["id"]) for f in rows]
    json_measured = [str(f["measured"]) for f in rows]
    json_expected = [str(f["expected"]) for f in rows]
    json_units = [str(f["unit"] or "") for f in rows]
    json_checks = [f.get("check_name") or f.get("check") for f in rows]

    assert html_ids == json_ids, (html_ids, json_ids)
    assert html_measured == json_measured == ["4.8", "896"], (
        html_measured, json_measured)
    assert html_expected == json_expected == ["30.0", "1024"], (
        html_expected, json_expected)
    assert html_units == json_units == ["s", "px"], (html_units, json_units)
    assert html_checks == json_checks == ["duration", "resolution"], (
        html_checks, json_checks)
    assert "No open findings" not in page
    assert "4.8" in page and "30.0" in page and "896" in page and "1024" in page
    assert "data-finding=" in page
    # pass-row must not leak into the default review queue on either surface
    assert "blank" not in html_checks and "blank" not in json_checks


_T6_A2_SET_COUNT = 3
_T6_A2_SET_TOTAL = 137.0  # distinctive; not 0, not the stub item sum


def test_t6_a2_html_and_json_report_the_same_set_numbers(patch_stub):
    """T6-A2-set: HTML /sets/{id} and JSON /api/sets/{id} report the same
    numbers for one fixture. Distinctive 3 items / 137s so two empty answers
    cannot pass. Same set_detail()."""
    import app as appmod
    from fastapi.testclient import TestClient
    from test_app import _upload_song

    patch_stub("mixer", set_duration=lambda items, key="video": _T6_A2_SET_TOTAL)

    with TestClient(appmod.app) as client:
        songs = [_upload_song(client, f"T6-A2 Set {i}")
                 for i in range(_T6_A2_SET_COUNT)]
        created = client.post("/api/sets",
                              json={"name": "T6-A2 Set Fixture", "mode": "audio"})
        assert created.status_code == 200, created.text
        set_id = created.json()["set"]["id"]
        for song in songs:
            r = client.post(f"/api/sets/{set_id}/items",
                            json={"song_id": song["id"],
                                  "transition": "cut", "secs": 0})
            assert r.status_code == 200, r.text

        html = client.get(f"/sets/{set_id}")
        js = client.get(f"/api/sets/{set_id}")

    assert html.status_code == 200, html.text
    page = html.text
    assert js.status_code == 200, js.text
    ctype = (js.headers.get("content-type") or "").split(";")[0].strip()
    assert ctype == "application/json", (
        f"/api/sets/{{id}} returned {ctype or 'no content-type'}, not JSON: "
        f"{js.text[:200]}")
    assert "<html" not in js.text.lower(), js.text[:200]
    body = js.json()

    html_count = int(re.search(r"(\d+) items?", page).group(1))
    html_hms = re.search(
        r"running length <strong>([^<]+)</strong>", page).group(1).strip()
    html_dur = float(re.search(r'data-duration="([^"]+)"', page).group(1))
    html_ids = [int(n) for n in re.findall(r'id="item-(\d+)"', page)]

    json_ids = [it["id"] for it in body["items"]]

    assert html_count == body["count"] == _T6_A2_SET_COUNT, (
        html_count, body.get("count"), body)
    assert html_dur == body["total_secs"] == _T6_A2_SET_TOTAL, (
        html_dur, body.get("total_secs"), body)
    assert html_hms == appmod.hms(_T6_A2_SET_TOTAL), (
        html_hms, appmod.hms(_T6_A2_SET_TOTAL))
    assert html_ids == json_ids, (html_ids, json_ids)
    assert len(html_ids) == _T6_A2_SET_COUNT, html_ids


# ----------------------------------------------------------------- T6-A4 --

_T6_A4_ELAPSED = "12.7s"
_T6_A4_N_RUNNING = 3
_T6_A4_N_WAITING = 7
_T6_A4_REFRESH = 4
_T6_A4_DESC = "STUB-DESC-77"


def test_t6_a4_queue_page_shows_stubbed_values_unmodified(monkeypatch):
    """T6-A4: stub the service; the page shows those values unmodified.

    Counts are not the list lengths; elapsed is not an integer second.
    A template that rounds, sums or reformats is a second implementation.
    """
    import app as appmod
    from fastapi.testclient import TestClient

    row = {
        "job": {"id": 77, "status": "running", "progress": "sheet 3/9",
                "error": None},
        "desc": _T6_A4_DESC,
        "elapsed": _T6_A4_ELAPSED,
    }
    stub = {
        "queue_active": [row],
        "queue_waiting": [{
            "job": {"id": 78, "status": "queued", "progress": "", "error": None},
            "desc": "STUB-WAIT-78",
            "elapsed": None,
        }],
        "queue_recent": [],
        "queue_rows": [row],
        "queue_n_running": _T6_A4_N_RUNNING,
        "queue_n_waiting": _T6_A4_N_WAITING,
        "queue_refresh_secs": _T6_A4_REFRESH,
    }
    monkeypatch.setattr(appmod, "queue_ctx", lambda: stub)
    with TestClient(appmod.app) as client:
        html = client.get("/queue").text
    assert _T6_A4_ELAPSED in html, html
    assert _T6_A4_DESC in html, html
    assert f"{_T6_A4_N_RUNNING} running" in html, html
    assert f"{_T6_A4_N_WAITING} waiting" in html, html
    assert f"every {_T6_A4_REFRESH}s" in html, html
    assert "1 running" not in html
    assert "13s" not in html


# ----------------------------------------------------------------- T6-A1 --

def _wait_job(jid, timeout=10):
    deadline = time.time() + timeout
    row = None
    while time.time() < deadline:
        row = jobs.get(jid)
        if row and row["status"] in ("done", "failed", "cancelled"):
            return row
        time.sleep(0.05)
    raise TimeoutError(f"job {jid} did not finish: {row}")


def _json(client, method, path, **kw):
    """One HTTP hop with Accept: application/json. HTML is a failure."""
    headers = dict(kw.pop("headers", None) or {})
    headers["Accept"] = "application/json"
    r = getattr(client, method)(path, headers=headers, **kw)
    ctype = (r.headers.get("content-type") or "").split(";")[0].strip()
    assert r.status_code < 400, f"{method.upper()} {path} -> {r.status_code}: {r.text[:400]}"
    assert ctype == "application/json", (
        f"{method.upper()} {path} returned {ctype or 'no content-type'}, not JSON: "
        f"{r.text[:200]}")
    assert "<html" not in r.text.lower(), (
        f"{method.upper()} {path} involved HTML: {r.text[:200]}")
    return r.json()


def test_t6_a1_set_empty_to_rendered_over_json():
    """T6-A1 / TRD-1: a set from empty to rendered over JSON, no HTML.

    An empty /api/sets 200 would stay green. The loop has to mint a set,
    add a song, render, and list a candidate whose file exists.
    """
    import app as appmod
    from fastapi.testclient import TestClient

    stamp = f"t6a1-set-{time.time_ns()}"
    mp3 = os.path.join(tempfile.mkdtemp(prefix="t6a1_"), "loop.mp3")
    with open(mp3, "wb") as f:
        f.write(b"ID3")
    sid = db.upsert_song(stamp, title="Loop Track", mp3_path=mp3, duration=12.3)

    with TestClient(appmod.app) as client:
        created = _json(client, "post", "/api/sets",
                        json={"name": stamp, "mode": "audio"})
        set_id = created.get("set", created).get("id")
        assert set_id, created
        assert created.get("set", created).get("mode") == "audio"
        assert created.get("items", []) == [] or created.get("count") == 0

        listed = _json(client, "get", "/api/sets")
        assert any((s.get("set") or s).get("id") == set_id for s in listed["sets"]), listed

        added = _json(client, "post", f"/api/sets/{set_id}/items",
                      json={"song_id": sid, "transition": "cut", "secs": 0})
        items = added.get("items") or []
        assert any(it.get("song_id") == sid for it in items), added

        rendered = _json(client, "post", f"/api/sets/{set_id}/render")
        jid = rendered.get("job_id") or (rendered.get("job") or {}).get("id")
        assert jid, rendered
        row = _wait_job(jid)
        assert row["status"] == "done", row

        detail = _json(client, "get", f"/api/sets/{set_id}")
        listed_r = _json(client, "get", f"/api/sets/{set_id}/renders")
        renders = listed_r.get("renders") or detail.get("renders") or []
        assert renders, (listed_r, detail)
        path = renders[0].get("path") or (renders[0].get("asset") or {}).get("path")
        assert path and os.path.isfile(path), renders
        assert any((r.get("set_id") == set_id) or
                   ((r.get("asset") or {}).get("id") is not None)
                   for r in renders), renders


def test_t6_a1_storyboard_loop_over_json(monkeypatch):
    """T6-A1 / TRD-2: read arc, propose, accept, generate, edit a scene,
    read the meter, list unanchored leads -- all JSON.
    """
    import app as appmod
    import tiers
    from fastapi.testclient import TestClient

    tiers.ensure_builtins()
    stamp = f"t6a1-sb-{time.time_ns()}"
    album = f"T6-A1 Album {stamp}"
    mp3 = os.path.join(tempfile.mkdtemp(prefix="t6a1_"), "sb.mp3")
    with open(mp3, "wb") as f:
        f.write(b"ID3")
    sid = db.upsert_song(stamp, title="Arc Track", album=album,
                         mp3_path=mp3, duration=12.3, lyrics="she leaves")
    pid = db.run(
        "INSERT INTO playlists (name, kind, created) VALUES (?,?,?)",
        album, "playlist", time.time())
    db.run("INSERT INTO playlist_items (playlist_id, song_id, position) VALUES (?,?,?)",
           pid, sid, 0)

    def _fake_generate(album, songs, direction="", backend=None, model=None,
                       progress=None, transitions=None):
        song_id = songs[0]["id"]
        return ({
            "premise": "A cat walks the city at night and does not come back.",
            "acts": [{"name": "Night", "songs": [song_id], "turn": "she leaves"}],
            "songs": [{
                "song_id": song_id, "position": 1,
                "role": "the door", "beat": "she leaves",
                "opens": "a shut door", "closes": "headlights",
            }],
            "continuity": ["the collar is brass"],
            "album": album, "direction": direction,
        }, "stub/model")

    def _fake_sb(*_a, **_k):
        return {
            "character_reference": "a sleek black feline DJ",
            "scenes": [{
            "scene_number": 1,
            "name": "the door",
            "image_prompt": "she stands at the door",
            "video_motion_prompt": "she walks out",
            "story": "the door closing",
            "characters": ["Unknown Lead"],
            "duration_guidance": "5 sec",
            "negative_prompt": "",
            "camera": "wide",
        }]}

    monkeypatch.setattr(appmod.arc, "generate", _fake_generate)
    monkeypatch.setattr(appmod.grok, "generate_storyboard", _fake_sb)

    with TestClient(appmod.app) as client:
        before = _json(client, "get", f"/api/playlists/{pid}/arc")
        assert not (before.get("arc") or before.get("premise")), before

        proposed = _json(client, "post", f"/api/playlists/{pid}/arc/propose",
                         json={"direction": "keep her walking the city"})
        proposal = proposed.get("proposal") or proposed.get("arc")
        assert proposal and proposal.get("premise"), proposed
        still = _json(client, "get", f"/api/playlists/{pid}/arc")
        assert not (still.get("arc") or still.get("premise")), still

        accepted = _json(client, "post", f"/api/playlists/{pid}/arc",
                         json=proposal)
        assert (accepted.get("arc") or accepted).get("premise"), accepted
        stored = _json(client, "get", f"/api/playlists/{pid}/arc")
        assert "does not come back" in (
            (stored.get("arc") or stored).get("premise") or ""), stored

        started = _json(client, "post", f"/api/songs/{sid}/storyboard/pg13",
                        json={"scene_seconds": 4.0, "direction": "night walk"})
        jid = started.get("job_id") or (started.get("job") or {}).get("id")
        assert jid, started
        row = _wait_job(jid)
        assert row["status"] == "done", row

        board = _json(client, "get", f"/api/songs/{sid}/storyboard/pg13")
        scenes = board.get("scenes") or []
        assert scenes, board
        num = scenes[0].get("num") or scenes[0].get("scene_number")
        assert num, scenes[0]

        edited = _json(client, "post",
                       f"/api/songs/{sid}/storyboard/pg13/scene/{num}",
                       json={"image_prompt": "she looks back at the door"})
        scene = edited.get("scene") or edited
        prompt = scene.get("image_prompt") or ""
        if not prompt:
            again = _json(client, "get", f"/api/songs/{sid}/storyboard/pg13")
            prompt = (again["scenes"][0].get("image_prompt") or "")
        assert "looks back" in prompt, (edited, prompt)

        meter = _json(client, "get", f"/api/songs/{sid}/storyboard/pg13/meter")
        assert meter.get("nclips") or meter.get("duration") is not None, meter
        assert "rendered" in meter or "intent" in meter, meter

        cast = _json(client, "get", f"/api/songs/{sid}/storyboard/pg13/cast")
        names = cast.get("unanchored") or []
        assert "Unknown Lead" in names, cast


def test_t6_a1_review_queue_over_json():
    """T6-A1 / TRD-3: run, list, edit remedy, approve, re-check over JSON.

    Inserting a finding and only listing it is the empty-surface trap.
    """
    import app as appmod
    from fastapi.testclient import TestClient

    path = os.path.join(tempfile.mkdtemp(prefix="t6a1_"), "review.png")
    _png(path, size=(10, 10))
    jobs.land(path, expect={"width": 100, "height": 100})

    with TestClient(appmod.app) as client:
        ran = _json(client, "post", "/api/qc/run",
                    json={"path": path, "kind": "image"})
        found = ran.get("findings") or []
        assert found, ran
        assert any(f.get("check") == "resolution" or f.get("check_name") == "resolution"
                   for f in found), found

        listed = _json(client, "get", "/api/qc/findings")
        rows = [f for f in listed["findings"] if f.get("path") == jobs.canonical_path(path)
                or f.get("path") == path]
        assert rows, listed
        fid = rows[0]["id"]

        remedy = _json(client, "post", f"/api/qc/findings/{fid}/remedy",
                       data={"text": "regenerate at 100x100"})
        assert remedy.get("remedy") == "regenerate at 100x100", remedy
        assert _json(client, "get", f"/api/qc/findings/{fid}")["remedy"] == (
            "regenerate at 100x100")

        approved = _json(client, "post", f"/api/qc/findings/{fid}/approve")
        assert approved.get("status") == "approved", approved

        _png(path, size=(100, 100))
        rechecked = _json(client, "post", f"/api/qc/findings/{fid}/recheck")
        again = rechecked.get("findings") or []
        res = [f for f in again if (
            f.get("check") == "resolution" or f.get("check_name") == "resolution")]
        assert res, rechecked
        assert res[0].get("verdict") == "pass", res[0]


def test_t6_a1_anchor_loop_over_json(monkeypatch):
    """T6-A1 / TRD-4+TRD-7: save bases, generate a named view, pick, use-as-ref.

    TRD-4 and TRD-7 had no named curl loop. An empty /api/anchors 200 would
    stay green. The loop has to land a candidate file and make the pick
    the next identity lock.
    """
    import app as appmod
    import pipeline
    import tiers
    from fastapi.testclient import TestClient

    tiers.ensure_builtins()
    stamp = f"t6a1-anchor-{time.time_ns()}"
    album = f"T6-A1 Anchors {stamp}"
    db.run("INSERT INTO playlists (name, kind, created) VALUES (?,?,?)",
           album, "playlist", time.time())
    work = tempfile.mkdtemp(prefix="t6a1_anchor_")
    base = os.path.join(work, "base.png")
    _png(base)

    count = {"i": 0}

    def _gen(images, view="front", n=4, progress=None, **kw):
        out = []
        for _ in range(int(n or 1)):
            p = os.path.join(work, f"cand_{view}_{count['i']}.png")
            count["i"] += 1
            _png(p)
            out.append(p)
        return out

    monkeypatch.setattr(pipeline, "gen_anchor", _gen)
    monkeypatch.setattr(appmod, "refine_generated_still",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip")))

    with TestClient(appmod.app) as client:
        saved = _json(client, "post", "/api/anchors/refs",
                      json={"album": album, "path": base})
        ref_id = saved.get("id") or (saved.get("ref") or {}).get("id")
        assert ref_id, saved
        assert saved.get("path") == base or (saved.get("ref") or {}).get("path") == base

        refs = _json(client, "get", f"/api/anchors/refs?album={album}")
        rows = refs.get("refs") or refs.get("images") or []
        assert any(r.get("id") == ref_id for r in rows), refs

        started = _json(client, "post", "/api/anchors", json={
            "album": album, "tier": ["r"], "view": ["front"], "n": 2,
            "ref_id": [ref_id],
        })
        jobs_out = started.get("jobs") or []
        assert started.get("queued") == 1 or len(jobs_out) == 1, started
        assert started.get("views") == ["front"] or started.get("view") == "front", started
        jid = jobs_out[0].get("id") or jobs_out[0].get("job_id") or started.get("job_id")
        assert jid, started
        row = _wait_job(jid)
        assert row["status"] == "done", row

        listed = _json(client, "get", f"/api/anchors?album={album}")
        cands = []
        for g in listed.get("groups") or []:
            cands.extend(g.get("candidates") or [])
        if not cands:
            cands = listed.get("candidates") or listed.get("anchors") or []
        assert len(cands) >= 2, listed
        for c in cands:
            path = c.get("path")
            assert path and os.path.isfile(path), c
        pick_id = cands[-1]["id"]
        assert pick_id, cands[-1]

        picked = _json(client, "post", f"/api/anchors/{pick_id}/pick")
        assert picked.get("chosen") == pick_id, picked
        group = picked.get("group") or []
        if group:
            assert sum(1 for p in group if p.get("chosen")) == 1, picked

        borrowed = _json(client, "post", f"/api/anchors/{pick_id}/use-as-ref")
        lock_path = borrowed.get("path") or (borrowed.get("ref") or {}).get("path")
        assert lock_path and os.path.isfile(lock_path), borrowed
        picked_path = cands[-1]["path"]
        assert os.path.samefile(lock_path, picked_path), (lock_path, picked_path)

        again = _json(client, "get", f"/api/anchors/refs?album={album}")
        again_rows = again.get("refs") or again.get("images") or []
        assert any(os.path.samefile(r["path"], picked_path)
                   for r in again_rows if r.get("path")), again


# ----------------------------------------------------------------- T6-A5 --

def _t6_a5_assert_pair(kind, group, pred, succ):
    """Shared entry point: qc_service.listed / select (T6-A10). Both files
    stay; either pick keeps the other listed."""
    pred = jobs.canonical_path(pred)
    succ = jobs.canonical_path(succ)
    assert pred != succ
    assert os.path.isfile(pred) and os.path.isfile(succ), (
        f"{kind}: a write that overwrote the predecessor is not T6-A5")

    listed = qc_service.listed(kind, group)
    paths = [c["path"] for c in listed]
    assert pred in paths and succ in paths, (
        f"{kind}: listed {paths}, expected predecessor {pred} and successor {succ}")
    assert all(c.get("selectable") for c in listed), listed
    assert len({c["path"] for c in listed}) >= 2, listed

    picked_pred = qc_service.select(kind, group, pred)
    assert [c["path"] for c in picked_pred if c["selected"]] == [pred], picked_pred
    assert succ in [c["path"] for c in picked_pred], picked_pred

    picked_succ = qc_service.select(kind, group, succ)
    assert [c["path"] for c in picked_succ if c["selected"]] == [succ], picked_succ
    assert pred in [c["path"] for c in picked_succ], (
        f"{kind}: selecting the successor dropped the predecessor")
    assert os.path.isfile(pred) and os.path.isfile(succ)


def test_t6_a5_set_rerender_predecessor_and_successor_listed_and_selectable(monkeypatch):
    """T6-A5 / set re-render: two h_render_set calls leave both files listed
    and either selectable. A timestamp collision that overwrites stays red."""
    import app as appmod

    data = _isolate()

    def _mix(items, out, progress=None):
        parent = os.path.dirname(out)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out, "wb") as f:
            f.write(b"ID3-mix")

    monkeypatch.setattr(appmod.mixer, "mix_audio", _mix)
    monkeypatch.setattr(appmod.mixer, "export_loudness",
                        lambda *a, **k: {"i": -14.0, "tp": -1.0, "ok": True})

    mp3 = os.path.join(data, "t6a5.mp3")
    with open(mp3, "wb") as f:
        f.write(b"ID3")
    sid = db.upsert_song("t6a5-set", title="Set Pair", mp3_path=mp3, duration=12.3)
    set_id = db.run(
        "INSERT INTO sets (name, created, updated, mode) VALUES (?,?,?,?)",
        "t6a5", time.time(), time.time(), "audio")
    db.run("INSERT INTO set_items (set_id, song_id, position, transition, secs) "
           "VALUES (?,?,?,?,?)", set_id, sid, 0, "cut", 0.0)
    items = [{"audio": mp3, "transition": "cut", "secs": 0}]
    first = appmod.h_render_set(
        {"set_id": set_id, "mode": "audio", "items": items}, lambda m: None)
    second = appmod.h_render_set(
        {"set_id": set_id, "mode": "audio", "items": items}, lambda m: None)
    assert first["path"] != second["path"], first
    group = qc_service.lineage_group("set_rerender", set_id=set_id)
    _t6_a5_assert_pair("set_rerender", group, first["path"], second["path"])


def test_t6_a5_refine_predecessor_and_successor_listed_and_selectable():
    """T6-A5 / refine: refine_generated_still writes beside src; both selectable."""
    import app as appmod

    data = _isolate()
    src = os.path.join(data, "still.png")
    _png(src)
    orig = qc_service.dispatch_repair
    try:
        qc_service.dispatch_repair = _write_repaired
        dest = appmod.refine_generated_still(src, lambda m: None)
    finally:
        qc_service.dispatch_repair = orig
    assert dest != src
    group = qc_service.lineage_group("refine", src)
    _t6_a5_assert_pair("refine", group, src, dest)


def test_t6_a5_repair_predecessor_and_successor_listed_and_selectable():
    """T6-A5 / repair: h_repair dest is a new candidate; original stays selectable."""
    data = _isolate()
    fid, src, args = _repair_args(data, "t6a5-repair.png")
    dest = jobs.canonical_path(args["repair_path"])
    orig = qc_service.dispatch_repair
    try:
        qc_service.dispatch_repair = _write_repaired
        qc_service.h_repair(args, lambda m: None)
    finally:
        qc_service.dispatch_repair = orig
    group = qc_service.lineage_group("repair", src, finding_id=fid)
    _t6_a5_assert_pair("repair", group, src, dest)


def test_t6_a5_anchor_reroll_predecessor_and_successor_listed_and_selectable():
    """T6-A5 / anchor re-roll: a second generate adds a new anchors row;
    the previous sheet stays listed and selectable."""
    import app as appmod
    import pipeline

    data = _isolate()
    count = {"i": 0}

    def _gen(images, view="front", n=4, progress=None, **kw):
        p = os.path.join(data, f"anchor_{count['i']}.png")
        count["i"] += 1
        _png(p)
        return [p]

    orig = pipeline.gen_anchor
    pipeline.gen_anchor = _gen
    try:
        args = {
            "scope_kind": "album", "scope_value": "T6A5 Album",
            "tier": "r", "view": "front", "n": 1,
            "images": [os.path.join(data, "base.png")],
            "refine": False,
        }
        _png(args["images"][0])
        first = appmod.h_anchor(args, lambda m: None)
        second = appmod.h_anchor(args, lambda m: None)
    finally:
        pipeline.gen_anchor = orig

    rows = db.q(
        "SELECT path FROM anchors WHERE scope_value=? ORDER BY id", "T6A5 Album")
    assert len(rows) >= 2, rows
    pred, succ = rows[0]["path"], rows[-1]["path"]
    group = qc_service.lineage_group(
        "anchor_reroll", pred,
        scope_kind="album", scope_value="T6A5 Album",
        tier="r", view="front", character_id=None)
    _t6_a5_assert_pair("anchor_reroll", group, pred, succ)
    assert first["n"] == 1 and second["n"] == 1
