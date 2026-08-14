#!/usr/bin/env python3
"""QC as a service: run the checks, record what they found, answer the queue.

docs/TRD-3 7. This is the layer the web routes call and it imports NOTHING from
FastAPI, so every operation is reachable from a test, a shell, or a mobile
client written later against the same JSON. If a route handler decides
something, a mobile client cannot -- so nothing is decided in a route handler.

The split from qc.py is deliberate and is the one docs/TRD-3 T3-30 asks for:
qc.py is pure measurement and touches no database, so it can be run over a
directory of old output; this module is what persists an answer.

    python3 qc_service.py      # self-check against a temporary database
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db      # noqa: E402
import jobs    # noqa: E402
import qc      # noqa: E402
import prompts  # noqa: E402

OPEN, APPROVED, RUNNING, REPAIRED, DISMISSED = (
    "open", "approved", "running", "repaired", "dismissed")

MAX_REMEDY = 4000


def _txt(v):
    """measured/expected are stored as TEXT because a check may measure a
    number ("30.004") or a shape ("832x480"), and a REAL column would quietly
    turn the second into NULL."""
    return None if v is None else str(v)


def record(findings):
    """Persist findings. Returns the number of rows written.

    A finding that PASSES is recorded too. It is the evidence that the check
    ran and what it read, which is what makes a later regression traceable --
    "this clip passed the duration check at 30.004s on the 13th" is a fact worth
    having when the same clip fails at 29.1 next week.

    Re-running QC over an unchanged artefact UPDATES rather than inserting a
    second row (docs/TRD-3 T3-5): re-running after a repair is the normal case,
    and a queue that grows a duplicate every run is a queue nobody reads. The
    human's own columns -- status, why it was dismissed, the edited remedy
    prompt -- are NOT overwritten by a re-run, because a re-measurement is not a
    reason to forget that somebody already looked at it.
    """
    now = time.time()
    n = 0
    for f in findings:
        db.run("""INSERT INTO findings
                    (path, kind, tier, check_name, verdict, measured, expected,
                     unit, detail, remedy, status, created)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(path, check_name) DO UPDATE SET
                     verdict=excluded.verdict, measured=excluded.measured,
                     expected=excluded.expected, unit=excluded.unit,
                     detail=excluded.detail, created=excluded.created""",
               f["path"], f["kind"], f["tier"], f["check"], f["verdict"],
               _txt(f.get("measured")), _txt(f.get("expected")), f.get("unit"),
               f.get("detail"), f.get("remedy"), OPEN, now)
        n += 1
    return n


def run_artefact(path, kind, expect=None, items=None, record_pass=True):
    """Measure one artefact and record what was found. Returns the findings.

    NOTHING IS REPAIRED HERE and nothing is enqueued. docs/TRD-3 T3-18: QC never
    auto-heals, so running it over a directory of broken output must leave the
    job queue exactly as it was.
    """
    found = qc.run(path, kind, expect=expect, items=items)
    record(found if record_pass else [f for f in found if f["verdict"] != qc.PASS])
    return found


def queue(status=OPEN, kind=None, tier=None, include_pass=False):
    """The review queue IS the findings table filtered. docs/TRD-3 3.

    Defaults to what a human still has to look at: open, and not the passes.
    """
    sql = "SELECT * FROM findings WHERE 1=1"
    args = []
    if status:
        sql += " AND status=?"
        args.append(status)
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    if tier:
        sql += " AND tier=?"
        args.append(int(tier))
    if not include_pass:
        sql += " AND verdict != 'pass'"
    # rejects before flags, newest first: the order a person would want to work
    sql += " ORDER BY CASE verdict WHEN 'reject' THEN 0 ELSE 1 END, created DESC, id DESC"
    return db.q(sql, *args)


def get(fid):
    row = db.one("SELECT * FROM findings WHERE id=?", int(fid))
    if not row:
        raise ValueError(f"no finding {fid}")
    return row


def summary(path=None):
    """Counts by verdict, for one artefact or the whole table."""
    sql = "SELECT verdict, COUNT(*) AS n FROM findings"
    args = []
    if path:
        sql += " WHERE path=?"
        args.append(path)
    sql += " GROUP BY verdict"
    counts = {r["verdict"]: r["n"] for r in db.q(sql, *args)}
    return {v: counts.get(v, 0) for v in (qc.PASS, qc.FLAG, qc.REJECT)}


def set_remedy(fid, text, album=None):
    """Edit the remedy that approving this finding would run.

    The edited text is what would run -- docs/TRD-3 T3-19 -- so it is stored on
    the finding and returned, not merely accepted.

    When the album is known the text is ALSO saved as a version in prompts.py's
    table (docs/TRD-3 T3-20: same rules as every other prompt -- editing makes
    a version, deleting does not renumber, a version records its model and
    time). When it is not known, the text still saves and no version is
    written: prompts.save() is scoped to an album and inventing a scope to
    satisfy the letter of the rule would put every artefact's remedy in one
    bucket labelled with a lie.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("a remedy cannot be empty -- dismiss the finding instead")
    if len(text) > MAX_REMEDY:
        raise ValueError(f"remedy is {len(text)} characters, the limit is {MAX_REMEDY}")
    row = get(fid)
    vid = row["remedy_prompt_id"]
    if album:
        v = prompts.save(album, "qc_remedy", text,
                         label=f"{row['kind']} {row['check_name']}"[:prompts.MAX_LABEL])
        vid = v["id"]
    db.run("UPDATE findings SET remedy=?, remedy_prompt_id=? WHERE id=?", text, vid, int(fid))
    return get(fid)


def dismiss(fid, why):
    """Record that a human looked and decided it was not a problem.

    A reason is REQUIRED. docs/TRD-3 T3-22 -- a dismissal with no reason is
    indistinguishable from a finding nobody read, and the next person cannot
    tell whether to trust it.
    """
    why = (why or "").strip()
    if not why:
        raise ValueError("dismissing a finding needs a reason")
    db.run("UPDATE findings SET status=?, dismissed_why=?, resolved=? WHERE id=?",
           DISMISSED, why, time.time(), int(fid))
    return get(fid)


def reopen(fid):
    db.run("UPDATE findings SET status=?, resolved=NULL WHERE id=?", OPEN, int(fid))
    return get(fid)


def _repair_dest(path):
    """A new candidate beside the original. Never the input path (T3-6)."""
    root, ext = os.path.splitext(path)
    dest = f"{root}.repair{ext}"
    return dest if dest != path else path + ".repair"


@jobs.handler("repair")
def h_repair(args, progress):
    """Queued by approve(). No GPU work yet: the job carries the finding and
    the edited remedy so a later actuator can run them. A dest equal to the
    source is refused so a future writer cannot overwrite the evidence."""
    src, dest = args.get("path"), args.get("repair_path")
    if not dest or dest == src:
        raise ValueError("a repair must write a new candidate, not overwrite")
    progress(f"repair finding {args.get('finding_id')}")
    return {"finding_id": args.get("finding_id"), "repair_path": dest,
            "remedy": args.get("remedy")}


def approve(fid):
    """Human sign-off: enqueue one repair job for this finding.

    QC never auto-heals (T3-18). This is the only call that enqueues a repair,
    and it is the function the /api/qc/findings/{id}/approve route calls
    (T6-A10). The job names a dest that is not the original path (T3-6) and
    carries the edited remedy (T3-19). repair_path on the finding stays empty
    until a later actuator actually writes that new file.
    """
    row = get(fid)
    if row["status"] == DISMISSED:
        raise ValueError("a dismissed finding cannot be approved -- reopen it first")
    remedy = (row["remedy"] or "").strip()
    if not remedy:
        raise ValueError("approving a finding needs a remedy -- edit one first")
    dest = _repair_dest(row["path"])
    jobs.enqueue("repair", {
        "finding_id": int(fid),
        "path": row["path"],
        "repair_path": dest,
        "remedy": remedy,
        "check_name": row["check_name"],
        "kind": row["kind"],
    })
    db.run("UPDATE findings SET status=? WHERE id=?", APPROVED, int(fid))
    return get(fid)


def demo():
    """Self-check against a temporary database, so it never touches real rows."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        # Same redirection prompts.demo() uses: db resolves DB_PATH at import,
        # so pointing it afterwards means moving the module's own attributes and
        # dropping the cached per-thread connection.
        db.DATA = d
        db.DB_PATH = os.path.join(d, "t.db")
        db._local.__dict__.clear()
        db.conn()  # build the schema in the temp database

        def mkclip(name, frames=81, size="320x240", rate=16.8312, src="testsrc2"):
            p = os.path.join(d, name)
            import subprocess
            subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
                            "-i", f"{src}=size={size}:rate={rate}",
                            "-frames:v", str(frames), "-pix_fmt", "yuv420p", p],
                           check=True, capture_output=True)
            return p

        good = mkclip("good.mp4")
        want = {"frames": 81, "fps": 16.8312, "width": 320, "height": 240,
                "duration": 81 / 16.8312}

        # --- a passing artefact records its evidence, and the queue stays empty.
        f = run_artefact(good, "clip", want)
        assert qc.worst(f) == qc.PASS, f
        assert summary(good)[qc.PASS] > 0, "a passing check recorded nothing"
        assert not queue(), "a clean artefact put something in the review queue"

        # --- a broken one: same file, an expectation it does not meet, which is
        # the differential -- one variable changed, and it is the EXPECTATION,
        # so nothing about the file explains the difference.
        run_artefact(good, "clip", {"frames": 505, "duration": 505 / 16.8312})
        rows = queue()
        assert rows, "a failing check did not reach the queue"
        checks = {r["check_name"] for r in rows}
        assert {"duration", "frame_count"} <= checks, checks
        row = [r for r in rows if r["check_name"] == "frame_count"][0]
        assert row["measured"] == "81" and row["expected"] == "505", dict(row)

        # --- T3-5: re-running does not grow a second row for the same check
        before = len(db.q("SELECT id FROM findings"))
        run_artefact(good, "clip", {"frames": 505, "duration": 505 / 16.8312})
        assert len(db.q("SELECT id FROM findings")) == before, \
            "re-running QC duplicated findings instead of updating them"

        # --- and a re-measurement does not forget that a human already looked.
        # record()'s docstring claims status/dismissed_why/remedy survive a
        # re-run; nothing asserted it until this line, and "the docstring says
        # so" is how a claim goes stale. Adding status=excluded.status to the
        # upsert fails here.
        dur = [r for r in queue() if r["check_name"] == "duration"][0]
        dismiss(dur["id"], "expected 505 was a typo in the re-check")
        set_remedy(dur["id"], "leave it alone")
        run_artefact(good, "clip", {"frames": 505, "duration": 505 / 16.8312})
        again = get(dur["id"])
        assert again["status"] == DISMISSED, "a re-run reopened a dismissed finding"
        assert again["remedy"] == "leave it alone", "a re-run overwrote an edited remedy"
        assert again["verdict"] == qc.REJECT, "the re-measurement itself was not stored"
        reopen(dur["id"])

        # --- T3-18: running QC enqueues nothing. Ever. Approving one finding
        # is the sign-off that enqueues exactly one repair.
        assert not db.q("SELECT id FROM jobs"), "QC enqueued a job on its own"

        # --- T3-19: the edited remedy is what is stored, and it comes back
        fid = row["id"]
        edited = "re-render clip 3 at 505 frames, same seed, same anchor"
        assert set_remedy(fid, edited)["remedy"] == edited
        assert get(fid)["remedy"] == edited, "the edit did not survive a re-read"
        try:
            set_remedy(fid, "   ")
        except ValueError as e:
            assert "empty" in str(e), e
        else:
            raise AssertionError("an empty remedy was accepted")

        # and with an album it is ALSO versioned, twice = two versions
        set_remedy(fid, "first wording", album="Street Cats")
        v = set_remedy(fid, "second wording", album="Street Cats")
        hist = prompts.versions("Street Cats", "qc_remedy")
        assert len(hist) == 2, [dict(h) for h in hist]
        assert get(fid)["remedy_prompt_id"] == v["remedy_prompt_id"]

        # --- T3-22: a dismissal needs a reason, and a dismissed finding leaves
        # the open queue
        try:
            dismiss(fid, "")
        except ValueError as e:
            assert "reason" in str(e), e
        else:
            raise AssertionError("a finding was dismissed with no reason")
        dismiss(fid, "the storyboard changed; 81 frames is correct now")
        assert fid not in [r["id"] for r in queue()], "a dismissed finding is still open"
        assert get(fid)["dismissed_why"]
        assert reopen(fid)["status"] == OPEN

        # --- T3-18 / T3-6 / T3-19: approve enqueues one job, dest != src,
        # and a second wording is a second job.
        src = get(fid)["path"]
        approve(fid)
        assert get(fid)["status"] == APPROVED, get(fid)["status"]
        queued = db.q("SELECT * FROM jobs")
        assert len(queued) == 1, queued
        first = json.loads(queued[0]["args_json"])
        assert first["finding_id"] == fid and first["remedy"]
        assert first["repair_path"] and first["repair_path"] != src
        landed = get(fid)["repair_path"]
        assert landed in (None, "") or landed != src
        set_remedy(fid, "second wording of the same repair")
        approve(fid)
        queued = db.q("SELECT * FROM jobs ORDER BY id")
        assert len(queued) == 2, queued
        second = json.loads(queued[1]["args_json"])
        assert first["remedy"] != second["remedy"], (first["remedy"], second["remedy"])

    print("qc_service.py OK")


if __name__ == "__main__":
    demo()
