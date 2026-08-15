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
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db      # noqa: E402
import jobs    # noqa: E402
import models  # noqa: E402
import pipeline  # noqa: E402
import qc      # noqa: E402
import prompts  # noqa: E402

OPEN, APPROVED, RUNNING, REPAIRED, DISMISSED = (
    "open", "approved", "running", "repaired", "dismissed")

UNATTRIBUTED = "unattributed"
MAX_REMEDY = 4000


def _txt(v):
    """measured/expected are stored as TEXT because a check may measure a
    number ("30.004") or a shape ("832x480"), and a REAL column would quietly
    turn the second into NULL."""
    return None if v is None else str(v)


def _remedy_class_of(finding):
    """Named class the check declared, or the catalog default for its name."""
    d = finding if isinstance(finding, dict) else dict(finding)
    cls = d.get("remedy_class")
    if cls:
        return cls
    return qc.CHECK_REMEDY_CLASS.get(d.get("check") or d.get("check_name") or "")


def _as_finding_row(row):
    """sqlite row plus whether approve has something to run (T3-27)."""
    d = dict(row)
    cls = _remedy_class_of(d)
    d["remedy_class"] = cls
    d["actionable"] = qc.is_actionable(cls)
    return d


def artefact_hash(path):
    """sha256 of the file bytes. Empty string when the path is missing.

    Empty is a known-missing fingerprint, not NULL. NULL is reserved for
    rows that predate this column so the first re-run after migrate does
    not reopen every old dismissal (T3-22).
    """
    if not path or not os.path.isfile(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _same_artefact(old, new):
    """True when the dismissed baseline is this file, or there is none yet."""
    if old is None:
        return True
    return old == new


def _expect_from_artefacts(path):
    """T6-11 / T6-12: the question stored against this path, or {}."""
    row = db.one("SELECT expect_json FROM artefacts WHERE path=?", path)
    if not row or not row["expect_json"]:
        return {}
    try:
        return json.loads(row["expect_json"])
    except ValueError:
        return {}


def _identity_wrong_remedy(check, remedy):
    """T3-28: identity-wrong never proposes swapping the reference image."""
    if check != qc.IDENTITY_WRONG:
        return remedy
    return qc.identity_wrong_remedy(remedy)


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
    prompt -- are NOT overwritten by a re-run of the same bytes, because a
    re-measurement is not a reason to forget that somebody already looked at
    it. T3-22: a dismissed finding REOPENS when the artefact bytes change
    and the check still fails. Deleting that comparison keeps dismissed
    forever.
    """
    now = time.time()
    n = 0
    for f in findings:
        path = jobs.canonical_path(f["path"])
        remedy = _identity_wrong_remedy(f["check"], f.get("remedy"))
        digest = artefact_hash(path)
        cls = _remedy_class_of(f)
        existing = db.one(
            "SELECT status, artefact_hash FROM findings WHERE path=? AND check_name=?",
            path, f["check"])
        status = OPEN
        if existing:
            status = existing["status"] or OPEN
            if status == DISMISSED and not _same_artefact(
                    existing["artefact_hash"], digest) and f["verdict"] != qc.PASS:
                status = OPEN
        db.run("""INSERT INTO findings
                    (path, kind, tier, check_name, verdict, measured, expected,
                     unit, detail, remedy, remedy_class, status, created,
                     artefact_hash)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(path, check_name) DO UPDATE SET
                     verdict=excluded.verdict, measured=excluded.measured,
                     expected=excluded.expected, unit=excluded.unit,
                     detail=excluded.detail, created=excluded.created,
                     artefact_hash=excluded.artefact_hash,
                     remedy_class=excluded.remedy_class,
                     status=excluded.status,
                     resolved=CASE
                       WHEN excluded.status=? AND findings.status=?
                       THEN NULL ELSE findings.resolved END""",
               path, f["kind"], f["tier"], f["check"], f["verdict"],
               _txt(f.get("measured")), _txt(f.get("expected")), f.get("unit"),
               f.get("detail"), remedy, cls, status, now, digest,
               OPEN, DISMISSED)
        n += 1
    return n


def run_artefact(path, kind, expect=None, items=None, record_pass=True):
    """Measure one artefact and record what was found. Returns the findings.

    NOTHING IS REPAIRED HERE and nothing is enqueued. docs/TRD-3 T3-18: QC never
    auto-heals, so running it over a directory of broken output must leave the
    job queue exactly as it was.

    T6-8: the path is canonical so findings join artefacts. T6-9: a missing
    file is a finding (qc.run's opens check), not a skip. T6-12: when expect
    is omitted the artefacts row supplies the same question a repair was
    judged against.
    """
    path = jobs.canonical_path(path)
    if expect is None:
        expect = _expect_from_artefacts(path)
    found = qc.run(path, kind, expect=expect, items=items)
    for f in found:
        f["path"] = path
    record(found if record_pass else [f for f in found if f["verdict"] != qc.PASS])
    return found


def run_song(song_id, tier="", progress=None):
    """T3-32: tier 1 over one song's artefacts. No GPU, no backend.

    Completes in this call. It is not a jobs row and does not wait on
    the one worker thread. Assembled expect is songs.duration (T6-13a);
    clips read artefacts.expect_json; absent stays absent.
    """
    song = db.one("SELECT * FROM songs WHERE id=?", song_id)
    empty = {"artefacts": 0, "checks": 0,
             qc.PASS: 0, qc.FLAG: 0, qc.REJECT: 0}
    if not song:
        return empty
    report = progress or (lambda _m: None)
    found, seen = [], 0
    tier = tier or ""

    for r in db.q(
            "SELECT * FROM renders WHERE song_id=? AND tier=? ORDER BY id DESC",
            song["id"], tier)[:1]:
        report(f"qc: assembled render {os.path.basename(r['path'])}")
        expect = {"want_audio": True}
        if song["duration"]:
            expect["duration"] = song["duration"]
        found += run_artefact(r["path"], "song", expect)
        seen += 1

    for c in db.q("""SELECT * FROM clips WHERE song_id=? AND tier=?
                     AND path IS NOT NULL ORDER BY clip_idx""",
                  song["id"], tier):
        report(f"qc: clip {c['clip_idx']}")
        found += run_artefact(c["path"], "clip")
        seen += 1

    for ref in db.q(
            "SELECT * FROM refs WHERE song_id=? AND tier=? ORDER BY clip_idx",
            song["id"], tier):
        found += run_artefact(ref["path"], "image", {})
        seen += 1

    counts = {v: sum(1 for x in found if x["verdict"] == v)
              for v in (qc.PASS, qc.FLAG, qc.REJECT)}
    return {"artefacts": seen, "checks": len(found), **counts}


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
    return [_as_finding_row(r) for r in db.q(sql, *args)]


def get(fid):
    row = db.one("SELECT * FROM findings WHERE id=?", int(fid))
    if not row:
        raise ValueError(f"no finding {fid}")
    return _as_finding_row(row)


def summary(path=None):
    """Counts by verdict, for one artefact or the whole table."""
    sql = "SELECT verdict, COUNT(*) AS n FROM findings"
    args = []
    if path:
        sql += " WHERE path=?"
        args.append(jobs.canonical_path(path))
    sql += " GROUP BY verdict"
    counts = {r["verdict"]: r["n"] for r in db.q(sql, *args)}
    return {v: counts.get(v, 0) for v in (qc.PASS, qc.FLAG, qc.REJECT)}


def by_host():
    """Per-box quality report. Groups artefacts by host (T3-1).

    NULL host is an explicit unattributed bucket with a count. Group
    by host, never backend -- Swarm renumbers backend ids.
    """
    rows = db.q(
        """SELECT CASE
                    WHEN host IS NULL OR TRIM(host) = '' THEN ?
                    ELSE host
                  END AS host,
                  COUNT(*) AS n
             FROM artefacts
            GROUP BY 1
            ORDER BY CASE WHEN host = ? THEN 1 ELSE 0 END, host""",
        UNATTRIBUTED, UNATTRIBUTED)
    groups = [{"host": r["host"], "n": r["n"]} for r in rows]
    if not any(g["host"] == UNATTRIBUTED for g in groups):
        groups.append({"host": UNATTRIBUTED, "n": 0})
    return groups


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
    text = _identity_wrong_remedy(row["check_name"], text)
    vid = row["remedy_prompt_id"]
    # Once a version exists, further edits stay versioned: the album is
    # the stored row's scope, so we do not invent one. Editing creates
    # a version (T3-20); the edited text is what runs (T3-19).
    if not album and vid:
        existing = prompts.get(vid)
        if existing:
            album = existing["scope_value"]
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
    row = get(fid)
    digest = artefact_hash(row["path"])
    db.run("UPDATE findings SET status=?, dismissed_why=?, resolved=?, artefact_hash=? WHERE id=?",
           DISMISSED, why, time.time(), digest, int(fid))
    return get(fid)


def reopen(fid):
    db.run("UPDATE findings SET status=?, resolved=NULL WHERE id=?", OPEN, int(fid))
    return get(fid)


def _scored_listing(path, kind=None, expect=None):
    """One artefact plus its findings. Scores the path if nothing is recorded."""
    path = jobs.canonical_path(path)
    if not db.one("SELECT id FROM findings WHERE path=?", path):
        if kind and path and os.path.isfile(path):
            run_artefact(path, kind, expect=expect)
    artefact = db.one("SELECT * FROM artefacts WHERE path=?", path)
    findings = db.q(
        "SELECT * FROM findings WHERE path=? ORDER BY check_name, id", path)
    scored = []
    for f in findings:
        scored.append({
            "path": f["path"],
            "kind": f["kind"],
            "tier": f["tier"],
            "check": f["check_name"],
            "verdict": f["verdict"],
            "measured": f["measured"],
            "expected": f["expected"],
            "unit": f["unit"],
        })
    return {
        "path": path,
        "artefact": artefact,
        "findings": findings,
        "score": qc.summarise(scored),
    }


def pair(fid):
    """T3-21: original and repair listed side by side, both scored.

    dest != src is T3-6. This is the comparison: both reachable as
    artefacts, both with findings, so "did the repair help" is read
    off rows rather than asserted.
    """
    row = get(fid)
    src = jobs.canonical_path(row["path"])
    dest = (jobs.canonical_path(row["repair_path"])
            if row["repair_path"] else None)
    if not dest:
        raise ValueError(
            "no repair candidate yet — approve and let the repair land first")
    if dest == src:
        raise ValueError("a repair must write a new candidate, not overwrite")
    expect = _expect_from_artefacts(src) or _expect_from_artefacts(dest) or None
    original = _scored_listing(src, kind=row["kind"], expect=expect)
    repair = _scored_listing(dest, kind=row["kind"], expect=expect)
    if original["artefact"] is None:
        raise ValueError(f"original is not listed: {src}")
    if repair["artefact"] is None:
        raise ValueError(f"repair is not listed: {dest}")
    if not original["findings"]:
        raise ValueError(f"original is not scored: {src}")
    if not repair["findings"]:
        raise ValueError(f"repair is not scored: {dest}")
    return {"original": original, "repair": repair}


def _repair_dest(path):
    """A new candidate beside the original. Never the input path (T3-6)."""
    root, ext = os.path.splitext(path)
    dest = f"{root}.repair{ext}"
    return dest if dest != path else path + ".repair"


def _same_bytes(a, b, chunk=1024 * 1024):
    """True when both paths exist and hold the same bytes."""
    if not a or not b or not os.path.isfile(a) or not os.path.isfile(b):
        return False
    if os.path.samefile(a, b):
        return True
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            ca, cb = fa.read(chunk), fb.read(chunk)
            if ca != cb:
                return False
            if not ca:
                return True


def _repair_actuator_and_key(args):
    """Actuator from the finding's remedy class (T3-27). Text is not the class.

    Jobs that predate remedy_class fall back to kind + wording so T3-23's
    existing payloads still route.
    """
    args = args or {}
    cls = (args.get("remedy_class") or "").strip()
    if cls == qc.REMEDY_NONE:
        raise ValueError("this check has no remedy -- it cannot be approved")
    mapped = qc.actuator_for(cls, args.get("kind")) if cls else None
    if mapped:
        key = args.get("requires") or args.get("model") or mapped[1]
        return mapped[0], key
    kind = (args.get("kind") or "").lower()
    text = f"{args.get('remedy') or ''} {args.get('check_name') or ''}".lower()
    key = args.get("requires") or args.get("model")
    wants_fix = kind == "image" or any(
        w in text for w in ("face", "inpaint", "outpaint"))
    wants_post = any(w in text for w in (
        "upscale", "interpolat", "postproc", "soft"))
    if wants_fix and not wants_post:
        return "fix_ref", key or "qwen_image_edit_2511"
    if wants_post or kind in ("clip", "song"):
        return "gen_postproc", key or "ltx25_latent_upscaler"
    if kind == "image":
        return "fix_ref", key or "qwen_image_edit_2511"
    return "gen_postproc", key or "ltx25_latent_upscaler"


def can_move_output(host):
    """T3-25: can an output be moved from this host back for repair.

    Local and unattributed artefacts need no fetch. A remote host stays
    false until output return is proven — install_input only stages
    inputs. Tests force True to exercise the flip.
    """
    box = models.canonical_host(host) if host else None
    if not box or box == models.SELF_HOST:
        return True
    return False


def _repair_source_host(src, args):
    """Host that produced src: job payload, else the artefacts row."""
    host = (args or {}).get("host")
    if host:
        return models.canonical_host(host)
    path = jobs.canonical_path(src) if src else None
    if not path:
        return None
    row = db.one("SELECT host FROM artefacts WHERE path=?", path)
    return models.canonical_host(row["host"]) if row and row["host"] else None


def _pin_matches(box, pin):
    if pin is None or pin == "":
        return True
    pin = str(pin)
    addr = box.get("address") or ""
    host = models.canonical_host(addr)
    return pin in {str(box.get("id")), box.get("title") or "", addr, host or ""}


def _route_repair(args):
    """Ask where/fits/resolve before any submit (T3-23)."""
    actuator, key = _repair_actuator_and_key(args)
    backends = pipeline.swarm_backends()
    candidates = models.where(key, backends)
    pin = args.get("backend") if args else None
    if pin is None or pin == "":
        pin = (args or {}).get("host") or (args or {}).get("pin")
    if pin is not None and pin != "":
        candidates = [c for c in candidates if _pin_matches(c, pin)]
    spec = models.CATALOG.get(key) or {}
    filename = spec.get("file")
    chosen = None
    last_reason = None
    for box in candidates:
        fit = models.fits(key, box.get("vram_gib"))
        if fit is False:
            last_reason = (
                f"{key} does not fit {box.get('title') or box.get('id')} "
                f"({box.get('vram_gib')} GiB)")
            continue
        pool = {box["file_here"]} if box.get("file_here") else set()
        resolved = models.resolve(filename, pool) if filename else box.get("file_here")
        if filename and resolved is None:
            last_reason = (
                f"repair pinned to {pin or box.get('id')} under a name it "
                f"does not have: {filename}")
            if pin is not None and pin != "":
                continue
            if box.get("confirmed") is True:
                continue
        chosen = dict(box, file_here=resolved or box.get("file_here"), fits=fit)
        break
    if chosen is None:
        if pin is not None and pin != "":
            raise ValueError(
                last_reason or (
                    f"repair pinned to {pin} under a name it does not have: "
                    f"{filename or key}"))
        raise ValueError(last_reason or f"no box can run repair model {key}")
    return actuator, key, chosen


def _place_repair(src, dest, produced):
    """Put the actuator's file at dest. Never src, never a silent no-op."""
    path = produced
    if isinstance(produced, list):
        if not produced:
            path = None
        elif isinstance(produced[0], dict):
            path = produced[0].get("path")
        else:
            path = produced[0]
    if not path or not os.path.isfile(path):
        raise RuntimeError("repair actuator produced no file")
    if os.path.abspath(path) == os.path.abspath(src):
        raise RuntimeError("repair actuator returned the source")
    if os.path.abspath(path) != os.path.abspath(dest):
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "rb") as fh:
            data = fh.read()
        with open(dest, "wb") as fh:
            fh.write(data)
    return dest


def _running_remedy(args):
    """The wording a repair RUNS. T3-20: when a prompts row is named,
    that row is the source of truth — same id, looked up now, not the
    copied string on the job. A missing stored row is a refusal.
    Text-only jobs (T3-19, no album so no version) still run their
    edited text."""
    args = args or {}
    vid = args.get("remedy_prompt_id")
    if vid is None or vid == "":
        return (args.get("remedy") or ""), None
    row = prompts.running(vid)
    return row["text"], row["id"]


def _invoke_actuator(actuator, src, dest, args, progress):
    args = dict(args or {})
    remedy, vid = _running_remedy(args)
    args["remedy"] = remedy
    if vid is not None:
        args["remedy_prompt_id"] = vid
        prompts.mark_used([vid])
    if actuator == "fix_ref":
        made = pipeline.fix_ref(
            slug=args.get("slug") or "repair",
            tier=args.get("tier") or "r",
            clip_idx=int(args.get("clip_idx") or 0),
            mode=args.get("mode") or "inpaint",
            image_path=src,
            seed=int(args.get("seed") or 0),
            progress=progress,
            instruction=remedy,
            face_path=args.get("face_path"),
            mask_path=args.get("mask_path"),
            pad=tuple(args.get("pad") or (0, 0, 0, 0)),
            guard=args.get("guard") or "",
            body=args.get("body") or "",
        )
    else:
        made = pipeline.gen_postproc(
            [src],
            slug=args.get("slug") or "repair",
            multiplier=int(args.get("multiplier") or 2),
            upscale=args.get("upscale") or "",
            progress=progress,
        )
    return _place_repair(src, dest, made)


def dispatch_repair(src, dest, args, progress):
    """Route via where/fits/resolve, then submit fix_ref or gen_postproc.

    A pin under a name the box does not have, or a box that does not
    fit, is refused before submit (T3-23). dest is the actuator's file,
    never a copy of src. The refiner's resident cost, not the UNET's
    13.31, is what fits() answers (T3-24). Remote output is refused by
    name until can_move_output is true (T3-25)."""
    host = _repair_source_host(src, args)
    if not can_move_output(host):
        raise ValueError(
            f"repair of remote output refused: can_move_output({host!r}) "
            f"is false")
    actuator, key, box = _route_repair(args)
    args = dict(args or {})
    args["requires"] = key
    if box.get("file_here"):
        args["file_here"] = box["file_here"]
    if box.get("id") is not None and not args.get("backend"):
        args["backend"] = box["id"]
    return _invoke_actuator(actuator, src, dest, args, progress)


def produce_repair(src, dest, args, progress):
    """Write dest as a new candidate beside src. Never the input path.

    The contract is a new file at dest, produced by dispatch_repair. Tests
    replace that seam to prove a silent no-write cannot mark the finding
    repaired. The default routes and submits; it is not a copy."""
    if not dest or dest == src:
        raise ValueError("a repair must write a new candidate, not overwrite")
    if not src or not os.path.isfile(src):
        raise ValueError(f"cannot repair missing artefact: {src!r}")
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    dispatch_repair(src, dest, args, progress)
    return dest


@jobs.handler("repair")
def h_repair(args, progress):
    """Queued by approve(). Writes a new candidate at repair_path (T3-6).

    A dest equal to the source is refused so a writer cannot overwrite the
    evidence. Success requires dest on disk from dispatch_repair; a writer
    that produces nothing — including a silent copy of src — fails rather
    than flipping status. The original is landed beside dest (T3-21)
    so pair() can list both."""
    src = jobs.canonical_path(args.get("path")) if args.get("path") else args.get("path")
    dest = (jobs.canonical_path(args.get("repair_path"))
            if args.get("repair_path") else args.get("repair_path"))
    if not dest or dest == src:
        raise ValueError("a repair must write a new candidate, not overwrite")
    # T3-20: refuse a missing stored row before any write. A stubbed
    # writer must not run a copied string after the version is gone.
    _running_remedy(args)
    progress(f"repair finding {args.get('finding_id')}")
    produce_repair(src, dest, args, progress)
    if not os.path.isfile(dest) or dest == src:
        raise RuntimeError("repair wrote no new file — GPU work is still missing")
    if src and os.path.isfile(src) and os.path.samefile(src, dest):
        raise ValueError("a repair must write a new candidate, not overwrite")
    if src and os.path.isfile(src) and _same_bytes(src, dest):
        os.remove(dest)
        raise RuntimeError("repair wrote no new file — GPU work is still missing")
    expect = _expect_from_artefacts(src) or None
    fid = args.get("finding_id")
    with jobs.writes():
        jobs.land(dest, expect=expect)
        if src and os.path.isfile(src):
            jobs.land(src)
        if fid:
            db.run("UPDATE findings SET status=?, repair_path=?, resolved=? WHERE id=?",
                   REPAIRED, dest, time.time(), int(fid))
    remedy, vid = _running_remedy(args)
    return {"finding_id": fid, "repair_path": dest,
            "remedy": remedy, "remedy_prompt_id": vid}


def approve(fid):
    """Human sign-off: enqueue one repair job for this finding.

    QC never auto-heals (T3-18). This is the only call that enqueues a repair,
    and it is the function the /api/qc/findings/{id}/approve route calls
    (T6-A10). The job names a dest that is not the original path (T3-6) and
    carries the edited remedy (T3-19). When the remedy is a prompts row,
    the job carries that id and that is the wording that RUNS (T3-20).
    repair_path on the finding stays empty until h_repair writes that new file.
    """
    row = get(fid)
    if row["status"] == DISMISSED:
        raise ValueError("a dismissed finding cannot be approved -- reopen it first")
    cls = _remedy_class_of(row)
    if not qc.is_actionable(cls):
        raise ValueError("this check has no remedy -- it cannot be approved")
    remedy = (row["remedy"] or "").strip()
    if not remedy:
        raise ValueError("approving a finding needs a remedy -- edit one first")
    remedy = _identity_wrong_remedy(row["check_name"], remedy)
    vid = row["remedy_prompt_id"]
    if vid:
        stored = prompts.running(vid)
        remedy = stored["text"]
        vid = stored["id"]
        remedy = _identity_wrong_remedy(row["check_name"], remedy)
    src = jobs.canonical_path(row["path"])
    dest = jobs.canonical_path(_repair_dest(src))
    orig = db.one("SELECT expect_json FROM artefacts WHERE path=?", src)
    if orig and orig["expect_json"]:
        # T6-12: the repaired candidate is judged against the same question.
        # The dest file does not exist yet, so this is not land() (T6-7).
        db.run("""INSERT INTO artefacts (path, expect_json, created) VALUES (?,?,?)
                  ON CONFLICT(path) DO UPDATE SET
                    expect_json=excluded.expect_json""",
               dest, orig["expect_json"], time.time())
    _, key = _repair_actuator_and_key({
        "kind": row["kind"], "check_name": row["check_name"], "remedy": remedy,
        "remedy_class": cls,
    })
    payload = {
        "finding_id": int(fid),
        "path": src,
        "repair_path": dest,
        "remedy": remedy,
        "remedy_class": cls,
        "check_name": row["check_name"],
        "kind": row["kind"],
        "requires": key,
    }
    if vid:
        payload["remedy_prompt_id"] = vid
    jobs.enqueue("repair", payload)
    db.run("UPDATE findings SET status=? WHERE id=?", APPROVED, int(fid))
    return get(fid)


def identity_calibration_report(report):
    """T3-16 decision on a T3-13 measurement. Overlap says inconclusive
    and does not invent a threshold or a gate."""
    out = dict(report)
    if "overlap" not in out:
        raise RuntimeError("identity report needs an overlap")
    verdict = qc.identity_verdict(out["overlap"])
    out["verdict"] = verdict
    if verdict == qc.INCONCLUSIVE:
        if out.get("threshold") is not None:
            raise ValueError(
                "T3-16: overlapping distributions are inconclusive; "
                "they do not earn a threshold")
        out["threshold"] = None
        out["gate"] = False
    return out


def build_identity_gate(report):
    """T3-16: overlapping distributions do not earn a gate.

    Separated ranges are named, not gated — T3-14 is the setter.
    A threshold on an overlapping report is refused by name.
    """
    decided = identity_calibration_report(report)
    return {
        "built": False,
        "verdict": decided["verdict"],
        "threshold": None,
    }


def record_calibration(report):
    """Persist a T3-13 report. threshold stays NULL — storing one is the
    failure T3-13 exists to prevent. T3-14's setter is what writes a value."""
    if report.get("threshold") is not None:
        raise ValueError(
            "T3-13 stores no threshold; the report is overlap and separation")
    scores = report.get("scores")
    if not scores:
        raise RuntimeError("calibration report has no per-file scores")
    cid = db.run(
        """INSERT INTO calibrations
             (metric, dataset, n_good, n_bad, separation, overlap,
              scores_json, threshold, created)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        report.get("metric") or qc.IDENTITY_METRIC,
        report.get("dataset") or "zimage_sweep",
        int(report["n_good"]), int(report["n_bad"]),
        report["separation"], report["overlap"],
        json.dumps(scores), None, time.time())
    return db.one("SELECT * FROM calibrations WHERE id=?", cid)


def latest_calibration(dataset="zimage_sweep"):
    return db.one(
        "SELECT * FROM calibrations WHERE dataset=? ORDER BY id DESC", dataset)


def set_threshold(threshold, dataset="zimage_sweep"):
    """T3-14: a threshold cannot be configured without a stored calibration.

    Attempting to set one with no calibration row is refused, naming why.
    With a stored row the value is written on that row unless T3-16
    names the distributions inconclusive. This is not a gate and not a UI.
    """
    row = latest_calibration(dataset)
    if row is None:
        raise ValueError(
            f"cannot set a threshold: no stored T3-13 calibration "
            f"for {dataset}")
    if qc.identity_verdict(row["overlap"]) == qc.INCONCLUSIVE:
        raise ValueError(
            "T3-16: overlapping distributions are inconclusive; "
            "they do not earn a threshold")
    db.run("UPDATE calibrations SET threshold=? WHERE id=?",
           float(threshold), row["id"])
    return db.one("SELECT * FROM calibrations WHERE id=?", row["id"])


def run_zimage_calibration(root, score_fn=None, embed=None, reference=None):
    """Score the 18 stills and write the calibrations row (T3-13)."""
    return record_calibration(qc.score_zimage_sweep(
        root, reference=reference, embed=embed, score_fn=score_fn))


def record_refiner_help(pairs, score_fn=None, reference=None, embed=None):
    """T3-26: measure the labelled set and persist the finding.

    Does not flip models.CATALOG proven. Opportunistic is not a measurement.
    """
    report = qc.measure_refiner_help(
        pairs, score_fn=score_fn, reference=reference, embed=embed)
    found = qc.refiner_help_finding(report)
    record([found])
    return report, found


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
        # T3-22 positive: same check REAPPEARS when the bytes change.
        changed = os.path.join(d, "changed.bin")
        with open(changed, "wb") as fh:
            fh.write(b"v1")
        record([{
            "path": changed, "kind": "clip", "tier": 1, "check": "duration",
            "verdict": qc.REJECT, "measured": "1", "expected": "2",
            "unit": "s", "detail": "short", "remedy": "re-render",
        }])
        ch = db.one("SELECT * FROM findings WHERE path=?", changed)
        dismiss(ch["id"], "looked at v1")
        with open(changed, "wb") as fh:
            fh.write(b"v2")
        record([{
            "path": changed, "kind": "clip", "tier": 1, "check": "duration",
            "verdict": qc.REJECT, "measured": "1", "expected": "2",
            "unit": "s", "detail": "short", "remedy": "re-render",
        }])
        assert get(ch["id"])["status"] == OPEN, \
            "dismissed finding did not reappear after the artefact changed"
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
        # T3-20: the row that would RUN is that stored id, not a copy
        ran_text, ran_id = _running_remedy(
            {"remedy": "a stale copy", "remedy_prompt_id": v["remedy_prompt_id"]})
        assert ran_id == v["remedy_prompt_id"] and ran_text == "second wording"

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
        # T3-20: the id that RUNS is the stored prompts row, read back
        assert first["remedy_prompt_id"] == get(fid)["remedy_prompt_id"]
        assert prompts.running(first["remedy_prompt_id"])["id"] == first["remedy_prompt_id"]
        assert prompts.running(first["remedy_prompt_id"])["text"] == first["remedy"]
        landed = get(fid)["repair_path"]
        assert landed in (None, "") or landed != src
        # T3-6 positive: the handler writes dest; naming it on the job is not
        # producing it. dest != src and the original stays. This self-check
        # injects a writer so it does not need a fleet.
        def _demo_write(src, dest, args, progress):
            with open(src, "rb") as f:
                payload = f.read()
            with open(dest, "wb") as f:
                f.write(payload + b"-repaired")
            return dest
        orig_dispatch = dispatch_repair
        try:
            globals()["dispatch_repair"] = _demo_write
            h_repair(first, lambda m: None)
        finally:
            globals()["dispatch_repair"] = orig_dispatch
        assert os.path.isfile(src), "repair overwrote the original"
        assert os.path.isfile(first["repair_path"]), "h_repair wrote no new file"
        assert get(fid)["repair_path"] == first["repair_path"]
        assert get(fid)["status"] == REPAIRED
        set_remedy(fid, "second wording of the same repair")
        approve(fid)
        queued = db.q("SELECT * FROM jobs ORDER BY id")
        assert len(queued) == 2, queued
        second = json.loads(queued[1]["args_json"])
        assert first["remedy"] != second["remedy"], (first["remedy"], second["remedy"])

    print("qc_service.py OK")


if __name__ == "__main__":
    demo()
