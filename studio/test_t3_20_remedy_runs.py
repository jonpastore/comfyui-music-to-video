"""T3-20: the approved remedy that RUNS is the stored prompts row.

docs/TRD-3 §6 / §11. Storage rules (editing versions, delete does not
renumber) are already in prompts.demo(). That is the one-sided half:
a table that is never read stays green. The positive half is the
version that RUNS — same id, read back after approval. Mutating the
job's copied text, or deleting the row, must not silently run a copy.
"""
import json
import os
import time

import db
import jobs
import models
import pipeline
import prompts
import qc_service


STORED = "re-render clip 3 at 505 frames, same seed, same anchor"
MUTATED = "MUTATED COPY THAT MUST NOT RUN"


_T323_FILE = models.CATALOG["qwen_image_edit_2511"]["file"]
_FLEET = [{"id": "0", "title": "cerberus",
           "address": "http://127.0.0.1:8188"}]


def _new_path(tag):
    return os.path.join(db.DATA, f"qc_t320_{tag}_{time.time_ns()}.png")


def _jobs_for(fid):
    out = []
    for row in db.q("SELECT * FROM jobs ORDER BY id"):
        try:
            args = json.loads(row["args_json"] or "{}")
        except ValueError:
            continue
        if args.get("finding_id") == fid:
            out.append((row, args))
    return out


def _finding(tag, remedy=STORED, album="Street Cats T3-20"):
    src = _new_path(tag)
    with open(src, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"broken-still")
    qc_service.record([{
        "path": src, "kind": "image", "tier": 1, "check": "identity",
        "verdict": "reject", "measured": "0", "expected": "1",
        "unit": "match", "detail": "not her", "remedy": remedy,
    }])
    fid = db.one("SELECT id FROM findings WHERE path=?", src)["id"]
    row = qc_service.set_remedy(fid, remedy, album=album)
    return fid, src, row


def _route_ok(monkeypatch):
    monkeypatch.setattr(
        models, "where",
        lambda key, backends: [{"id": "0", "title": "cerberus",
                                "address": "http://127.0.0.1:8188",
                                "fits": True, "file_here": _T323_FILE,
                                "vram_gib": 23.42, "confirmed": True}])
    monkeypatch.setattr(models, "fits", lambda key, vram_gib: True)
    monkeypatch.setattr(models, "resolve", lambda name, pool: _T323_FILE)
    monkeypatch.setattr(pipeline, "swarm_backends", lambda: _FLEET)


def _capture_fix_ref(monkeypatch):
    seen = []

    def _fix_ref(slug, tier, clip_idx, mode, image_path, seed, progress=None,
                 **kw):
        out = image_path + ".fixed"
        with open(image_path, "rb") as f:
            payload = f.read()
        with open(out, "wb") as f:
            f.write(payload + b"-fixed")
        seen.append({"instruction": kw.get("instruction"), "image_path": image_path,
                     "out": out, "kw": kw})
        return [{"clip_idx": clip_idx, "path": out, "seed": seed}]

    monkeypatch.setattr(pipeline, "fix_ref", _fix_ref)
    return seen


def test_t3_20_approve_reads_back_the_same_stored_id():
    """After approval the job carries the stored prompts id, and
    reading that id back is the same row that was saved."""
    fid, src, saved = _finding("approve_id")
    vid = saved["remedy_prompt_id"]
    assert vid, "set_remedy(album=) must store a prompts row"
    stored = prompts.get(vid)
    assert stored and stored["text"] == STORED
    assert stored["prompt_type"] == "qc_remedy"

    qc_service.approve(fid)

    finding = qc_service.get(fid)
    assert finding["remedy_prompt_id"] == vid
    _, args = _jobs_for(fid)[-1]
    assert args.get("remedy_prompt_id") == vid, (
        "approve queued a copy of the text without the stored id — "
        "storage rules alone do not prove use")
    back = prompts.get(args["remedy_prompt_id"])
    assert back["id"] == vid
    assert back["text"] == STORED
    assert args["remedy"] == STORED
    assert args["path"] == src


def test_t3_20_running_remedy_is_the_stored_row_not_the_job_copy(
        monkeypatch):
    """Positive half: mutate the job's copied text after approval.
    The actuator must still receive the stored row. A repair that
    stores a version and then runs args['remedy'] stays green here
    unless this lookup happens at RUN time."""
    _route_ok(monkeypatch)
    seen = _capture_fix_ref(monkeypatch)
    fid, src, saved = _finding("runs_stored")
    vid = saved["remedy_prompt_id"]
    qc_service.approve(fid)
    _, args = _jobs_for(fid)[-1]
    assert args["remedy_prompt_id"] == vid

    args = dict(args)
    args["remedy"] = MUTATED
    args["kind"] = "image"
    args["backend"] = "0"
    args["requires"] = "qwen_image_edit_2511"
    db.run("UPDATE findings SET remedy=? WHERE id=?", MUTATED, fid)

    before = prompts.get(vid)["usage_count"] or 0
    qc_service.h_repair(args, lambda m: None)

    assert seen, "actuator never ran — cannot prove which wording ran"
    assert seen[0]["instruction"] == STORED, (
        f"actuator ran the job copy, not the stored row: "
        f"{seen[0]['instruction']!r}")
    assert seen[0]["instruction"] != MUTATED
    used = prompts.get(vid)
    assert used["id"] == vid
    assert used["text"] == STORED
    assert (used["usage_count"] or 0) == before + 1, (
        "stored version was not marked used — the row was not what ran")
    row = qc_service.get(fid)
    assert row["remedy_prompt_id"] == vid
    assert row["status"] == qc_service.REPAIRED
    dest = args["repair_path"]
    assert dest != src and os.path.isfile(dest)
    assert os.path.isfile(src)


def test_t3_20_deleted_stored_row_is_refused_not_the_copy(monkeypatch):
    """If the stored version is gone, repair must refuse — falling
    back to the job's copied text is the mutation T3-20 exists to
    catch."""
    _route_ok(monkeypatch)
    seen = _capture_fix_ref(monkeypatch)
    fid, src, saved = _finding("deleted_row")
    vid = saved["remedy_prompt_id"]
    qc_service.approve(fid)
    _, args = _jobs_for(fid)[-1]
    prompts.delete(vid)
    assert prompts.get(vid) is None

    args = dict(args)
    args["kind"] = "image"
    args["backend"] = "0"
    dest = args["repair_path"]
    try:
        qc_service.h_repair(args, lambda m: None)
    except ValueError as e:
        msg = str(e).lower()
        assert str(vid) in str(e) or "prompt" in msg or "version" in msg, e
    else:
        raise AssertionError(
            "h_repair ran after the stored prompts row was deleted")
    assert seen == [], "actuator ran a copy after the stored row was gone"
    assert not os.path.isfile(dest)
    assert qc_service.get(fid)["status"] != qc_service.REPAIRED
