"""TDD for docs/TRD-3 T3-18 / T3-6 / T3-19: approve() is the human sign-off.

The route in app.api_qc_approve calls qc_service.approve and decides nothing
else (T6-A10). These tests call that same function -- not a helper it wraps,
and not the HTTP layer, which is just a 501-or-forward.
"""
import json
import os
import time

import db
import jobs
import models
import pipeline
import qc_service


def _new_path(tag):
    return os.path.join(db.DATA, f"qc_approve_{tag}_{time.time_ns()}.mp4")


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


def test_t3_18_qc_enqueues_nothing_until_approve():
    """Same broken artefact: QC writes findings and zero jobs; approve()
    on one of them enqueues exactly one repair."""
    path = _new_path("missing")
    before = {r["id"] for r in db.q("SELECT id FROM jobs")}

    found = qc_service.run_artefact(path, "clip")
    assert found and all(f["verdict"] != "pass" for f in found), found
    assert {r["id"] for r in db.q("SELECT id FROM jobs")} == before, \
        "QC enqueued a job on its own -- it must never auto-heal"

    row = db.one("SELECT * FROM findings WHERE path=? AND verdict != 'pass'", path)
    assert row, "a failing check did not reach the findings table"

    qc_service.approve(row["id"])

    fresh = [r for r in db.q("SELECT * FROM jobs") if r["id"] not in before]
    assert len(fresh) == 1, fresh
    assert len(_jobs_for(row["id"])) == 1
    assert qc_service.get(row["id"])["status"] == qc_service.APPROVED


def test_t3_6_repair_path_is_a_new_candidate():
    """A repair names a dest that is not the artefact it is repairing."""
    path = _new_path("overwrite")
    qc_service.run_artefact(path, "clip")
    row = db.one("SELECT * FROM findings WHERE path=?", path)
    qc_service.approve(row["id"])

    _, args = _jobs_for(row["id"])[-1]
    assert args["path"] == path
    assert args["repair_path"], args
    assert args["repair_path"] != path, \
        "a repair must write a new candidate, never overwrite"
    landed = qc_service.get(row["id"])["repair_path"]
    assert landed in (None, "") or landed != path


def test_t3_19_two_remedy_texts_are_two_jobs():
    """The edited remedy is what is queued -- two wordings, two jobs."""
    path = _new_path("remedy")
    qc_service.record([{
        "path": path, "kind": "clip", "tier": 1, "check": "duration",
        "verdict": "reject", "measured": "4.8", "expected": "30.0",
        "unit": "s", "detail": "short render", "remedy": "first wording",
    }])
    fid = db.one("SELECT id FROM findings WHERE path=?", path)["id"]

    qc_service.set_remedy(fid, "re-render clip at 505 frames")
    qc_service.approve(fid)
    qc_service.set_remedy(fid, "upscale the existing clip instead")
    qc_service.approve(fid)

    jobs_for = _jobs_for(fid)
    assert len(jobs_for) == 2, jobs_for
    remedies = [args["remedy"] for _, args in jobs_for]
    assert remedies == [
        "re-render clip at 505 frames",
        "upscale the existing clip instead",
    ], remedies


def _finding_with_file(tag, payload=b"broken-clip-bytes"):
    """A real artefact on disk plus one reject, so h_repair has something
    to write beside. approve() only names the dest; this is the half that
    has to produce it."""
    src = _new_path(tag)
    with open(src, "wb") as f:
        f.write(payload)
    qc_service.record([{
        "path": src, "kind": "clip", "tier": 1, "check": "duration",
        "verdict": "reject", "measured": "4.8", "expected": "30.0",
        "unit": "s", "detail": "short render", "remedy": "re-render",
    }])
    fid = db.one("SELECT id FROM findings WHERE path=?", src)["id"]
    qc_service.approve(fid)
    _, args = _jobs_for(fid)[-1]
    return fid, src, args


def _write_candidate(src, dest, args, progress):
    """Stand-in for the GPU actuator: a new file, not a silent copy."""
    with open(src, "rb") as f:
        payload = f.read()
    with open(dest, "wb") as f:
        f.write(payload + b"-repaired")
    return dest


def test_t3_6_h_repair_writes_a_new_candidate(monkeypatch):
    """T3-6 positive half: after h_repair runs, dest exists, dest != src,
    the original is still there, and finding.repair_path is the dest.

    Naming a dest on the job is not producing one. The actuator seam is
    what writes dest; this test supplies one so the contract is exercised
    without claiming GPU work landed."""
    monkeypatch.setattr(qc_service, "dispatch_repair", _write_candidate)
    fid, src, args = _finding_with_file("repair_src")
    dest = args["repair_path"]
    assert dest and dest != src
    assert not os.path.isfile(dest)

    qc_service.h_repair(args, lambda m: None)

    assert os.path.isfile(src), "repair deleted or overwrote the original"
    assert os.path.isfile(dest), (
        "h_repair wrote no new file -- GPU work is still missing")
    assert not os.path.samefile(src, dest)
    with open(src, "rb") as f:
        original = f.read()
    assert original == b"broken-clip-bytes", "repair mutated the source"
    row = qc_service.get(fid)
    assert row["repair_path"] == dest
    assert row["repair_path"] != src
    assert row["status"] == qc_service.REPAIRED
    landed = db.one("SELECT * FROM artefacts WHERE path=?", dest)
    assert landed and landed["status"] == "landed", landed


def test_t3_6_h_repair_refuses_overwrite():
    """T3-6: dest equal to src is refused before anything is written."""
    fid, src, args = _finding_with_file("overwrite_src")
    args = dict(args)
    args["repair_path"] = src
    try:
        qc_service.h_repair(args, lambda m: None)
    except ValueError as e:
        assert "overwrite" in str(e).lower() or "new candidate" in str(e).lower(), e
    else:
        raise AssertionError("h_repair accepted dest == src")
    assert os.path.isfile(src)
    assert qc_service.get(fid)["repair_path"] in (None, "")


def test_t3_h_repair_fails_when_no_file_written(monkeypatch):
    """A writer that produces nothing must not flip the finding to repaired.
    The old stub returned metadata and claimed success."""
    fid, src, args = _finding_with_file("no_write")
    dest = args["repair_path"]
    monkeypatch.setattr(qc_service, "produce_repair",
                        lambda *a, **k: dest)
    try:
        qc_service.h_repair(args, lambda m: None)
    except RuntimeError as e:
        assert "no new file" in str(e).lower() or "gpu" in str(e).lower(), e
    else:
        raise AssertionError("h_repair succeeded without writing dest")
    assert not os.path.isfile(dest)
    assert os.path.isfile(src)
    row = qc_service.get(fid)
    assert row["repair_path"] in (None, "")
    assert row["status"] != qc_service.REPAIRED


def test_t3_h_repair_refuses_a_silent_copy(monkeypatch):
    """Putting shutil.copy2 back in the seam must not mark the finding
    repaired. dest same-bytes-as-src is the broken artefact under a new name."""
    import shutil
    monkeypatch.setattr(qc_service, "dispatch_repair",
                        lambda src, dest, args, progress: shutil.copy2(src, dest))
    fid, src, args = _finding_with_file("silent_copy")
    dest = args["repair_path"]
    try:
        qc_service.h_repair(args, lambda m: None)
    except RuntimeError as e:
        assert "gpu" in str(e).lower() or "no new file" in str(e).lower(), e
    else:
        raise AssertionError("h_repair accepted a byte-copy of the source")
    assert os.path.isfile(src)
    assert not os.path.isfile(dest), "silent copy left a dest that looks repaired"
    row = qc_service.get(fid)
    assert row["repair_path"] in (None, "")
    assert row["status"] != qc_service.REPAIRED


def test_t3_h_repair_gpu_work_is_still_missing():
    """A shutil.copy2 of the broken artefact is not a repair (T3-6 / T3-23).

    Two honest outcomes: dest exists and dest bytes != src (an actuator
    produced a candidate), or h_repair raises and dest is absent (GPU
    work is still missing). A silent clone that marks the finding
    repaired stays green with make_postproc / fix_ref deleted.
    """
    fid, src, args = _finding_with_file("gpu_gap")
    dest = args["repair_path"]
    try:
        qc_service.h_repair(args, lambda m: None)
    except (RuntimeError, ValueError) as e:
        msg = str(e).lower()
        assert (
            "gpu" in msg or "no new file" in msg
            or "no box" in msg or "cannot run" in msg
            or "does not have" in msg or "does not fit" in msg
        ), e
        assert not os.path.isfile(dest)
        row = qc_service.get(fid)
        assert row["repair_path"] in (None, "")
        assert row["status"] != qc_service.REPAIRED
        return
    assert os.path.isfile(src), "repair deleted or overwrote the original"
    assert os.path.isfile(dest), (
        "h_repair wrote no new file -- GPU work is still missing")
    with open(src, "rb") as f:
        original = f.read()
    with open(dest, "rb") as f:
        written = f.read()
    assert written != original, (
        "h_repair cloned the broken artefact -- GPU work is still missing")
    assert qc_service.get(fid)["repair_path"] == dest


_T323_FLEET = [{"id": "0", "title": "cerberus",
                "address": "http://127.0.0.1:8188"}]
_T323_FILE = models.CATALOG["qwen_image_edit_2511"]["file"]


def _t323_route(monkeypatch, *, where_rows, fit, resolved, fleet=_T323_FLEET):
    """Watch where/fits/resolve. Do not replace dispatch_repair."""
    asked = []

    def _where(key, backends):
        asked.append(("where", key, backends))
        return list(where_rows)

    def _fits(key, vram_gib):
        asked.append(("fits", key, vram_gib))
        return fit

    def _resolve(name, pool):
        asked.append(("resolve", name, pool))
        return resolved

    monkeypatch.setattr(models, "where", _where)
    monkeypatch.setattr(models, "fits", _fits)
    monkeypatch.setattr(models, "resolve", _resolve)
    monkeypatch.setattr(pipeline, "swarm_backends", lambda: fleet)
    return asked


def _t323_actuators(monkeypatch):
    """Record submit. Write dest only if dispatch_repair calls us."""
    submitted = []

    def _fix_ref(slug, tier, clip_idx, mode, image_path, seed, progress=None,
                 **kw):
        out = image_path + ".fixed"
        with open(image_path, "rb") as f:
            payload = f.read()
        with open(out, "wb") as f:
            f.write(payload + b"-fixed")
        submitted.append(("fix_ref", image_path, out))
        return [{"clip_idx": clip_idx, "path": out, "seed": seed}]

    def _gen_postproc(clip_paths, slug, multiplier=2, upscale="",
                      progress=None):
        src = clip_paths[0]
        out = src + ".post"
        with open(src, "rb") as f:
            payload = f.read()
        with open(out, "wb") as f:
            f.write(payload + b"-post")
        submitted.append(("gen_postproc", src, out))
        return [out]

    monkeypatch.setattr(pipeline, "fix_ref", _fix_ref)
    monkeypatch.setattr(pipeline, "gen_postproc", _gen_postproc)
    return submitted


def test_t3_23_pinned_name_the_box_does_not_have_is_refused_before_submit(
        monkeypatch):
    """T3-23: a pin under a name the box does not have is refused BEFORE
    submit. Default dispatch_repair — not a monkeypatched writer. The
    unwired 'GPU work is still missing' raise is not this refusal."""
    asked = _t323_route(
        monkeypatch,
        where_rows=[{"id": "0", "title": "cerberus",
                     "address": "http://127.0.0.1:8188",
                     "fits": True, "file_here": None, "vram_gib": 23.42,
                     "confirmed": True}],
        fit=True,
        resolved=None)
    submitted = _t323_actuators(monkeypatch)
    fid, src, args = _finding_with_file("t323_pin")
    args = dict(args)
    args["kind"] = "image"
    args["backend"] = "0"
    args["requires"] = "qwen_image_edit_2511"
    dest = args["repair_path"]
    try:
        qc_service.h_repair(args, lambda m: None)
    except Exception as e:
        msg = str(e).lower()
        assert "gpu work is still missing" not in msg, e
        assert any(w in msg for w in (
            "does not have", "cannot run", "no box", "unfittable",
            "does not fit", "pinned")), e
    else:
        raise AssertionError(
            "repair pinned to a box under a name it does not have was submitted")
    assert submitted == [], "actuator ran before routing refused"
    assert any(c[0] == "where" for c in asked), "routing never asked where()"
    assert any(c[0] == "fits" for c in asked), "routing never asked fits()"
    assert any(c[0] == "resolve" for c in asked), "routing never asked resolve()"
    assert not os.path.isfile(dest)
    row = qc_service.get(fid)
    assert row["repair_path"] in (None, "")
    assert row["status"] != qc_service.REPAIRED


def test_t3_23_dispatch_repair_refuses_when_fits_says_unfittable(monkeypatch):
    """T3-23: where()/fits() saying the box cannot run it is a named
    refusal, not 'GPU work is still missing'."""
    asked = _t323_route(
        monkeypatch,
        where_rows=[{"id": "2", "title": "peaches",
                     "address": "http://100.95.184.29:8188",
                     "fits": False, "file_here": _T323_FILE,
                     "vram_gib": 10.58, "confirmed": True}],
        fit=False,
        resolved=_T323_FILE)
    submitted = _t323_actuators(monkeypatch)
    fid, src, args = _finding_with_file("t323_fit")
    args = dict(args)
    args["kind"] = "image"
    args["backend"] = "2"
    args["requires"] = "qwen_image_edit_2511"
    dest = args["repair_path"]
    try:
        qc_service.h_repair(args, lambda m: None)
    except Exception as e:
        msg = str(e).lower()
        assert "gpu work is still missing" not in msg, e
        assert any(w in msg for w in (
            "fit", "cannot run", "no box", "unfittable")), e
    else:
        raise AssertionError("unfittable repair was submitted")
    assert submitted == [], "actuator ran after fits() said no"
    assert any(c[0] == "where" for c in asked)
    assert any(c[0] == "fits" for c in asked)
    assert not os.path.isfile(dest)
    assert qc_service.get(fid)["status"] != qc_service.REPAIRED


def test_t3_23_correctly_named_model_on_a_box_that_holds_it_is_submitted(
        monkeypatch):
    """T3-23 positive: default dispatch_repair asks where/fits/resolve,
    then submits the actuator. dest is NEW bytes, never a copy of src."""
    asked = _t323_route(
        monkeypatch,
        where_rows=[{"id": "0", "title": "cerberus",
                     "address": "http://127.0.0.1:8188",
                     "fits": True, "file_here": _T323_FILE,
                     "vram_gib": 23.42, "confirmed": True}],
        fit=True,
        resolved=_T323_FILE)
    submitted = _t323_actuators(monkeypatch)
    fid, src, args = _finding_with_file("t323_ok")
    args = dict(args)
    args["kind"] = "image"
    args["backend"] = "0"
    args["requires"] = "qwen_image_edit_2511"
    dest = args["repair_path"]

    qc_service.h_repair(args, lambda m: None)

    assert any(c[0] == "where" for c in asked), "routing never asked where()"
    assert any(c[0] == "fits" for c in asked), "routing never asked fits()"
    assert any(c[0] == "resolve" for c in asked), "routing never asked resolve()"
    assert submitted and submitted[0][0] == "fix_ref", submitted
    assert os.path.isfile(src)
    assert os.path.isfile(dest), "actuator submitted but dest was not written"
    with open(src, "rb") as f:
        original = f.read()
    with open(dest, "rb") as f:
        written = f.read()
    assert written != original, "dest is a byte-copy of the broken artefact"
    row = qc_service.get(fid)
    assert row["repair_path"] == dest
    assert row["status"] == qc_service.REPAIRED


def test_t3_23_clip_finding_submits_make_postproc(monkeypatch):
    """T3-23: clip/postproc findings choose gen_postproc, not fix_ref."""
    _t323_route(
        monkeypatch,
        where_rows=[{"id": "0", "title": "cerberus",
                     "address": "http://127.0.0.1:8188",
                     "fits": True, "file_here": _T323_FILE,
                     "vram_gib": 23.42, "confirmed": True}],
        fit=True,
        resolved=_T323_FILE)
    submitted = _t323_actuators(monkeypatch)
    fid, src, args = _finding_with_file("t323_clip")
    args = dict(args)
    args["kind"] = "clip"
    args["check_name"] = "resolution"
    args["remedy"] = "upscale pass"
    args["backend"] = "0"
    dest = args["repair_path"]

    qc_service.h_repair(args, lambda m: None)

    assert submitted and submitted[0][0] == "gen_postproc", submitted
    assert os.path.isfile(dest)
    with open(src, "rb") as f, open(dest, "rb") as g:
        assert f.read() != g.read()
    assert qc_service.get(fid)["status"] == qc_service.REPAIRED


_T325_REMOTE = "100.95.184.29"


def _t325_remote_finding(tag):
    """Peaches output, repair routed to a box that can run it.

    Host lives on the artefacts row — the production path. args.host is
    left unset so a check that only reads the job payload stays green.
    """
    fid, src, args = _finding_with_file(tag)
    jobs.land(src, host=_T325_REMOTE, backend="2", via="swarm")
    args = dict(args)
    args["kind"] = "image"
    args["backend"] = "0"
    args["requires"] = "qwen_image_edit_2511"
    args.pop("host", None)
    return fid, src, args


def test_t3_25_can_move_output_is_callable():
    """T3-25: the precondition is a callable, not a sentence."""
    assert callable(qc_service.can_move_output)
    assert qc_service.can_move_output(_T325_REMOTE) is False
    assert qc_service.can_move_output(models.SELF_HOST) is True
    assert qc_service.can_move_output(None) is True


def test_t3_25_remote_repair_refused_by_name_until_check_is_true(monkeypatch):
    """T3-25: remote output is refused by name until can_move_output.

    Default dispatch_repair. Routing is wired so a missing move check
    would SUBMIT — the refusal must quote can_move_output, not
    'GPU work is still missing' and not a T3-23 pin/fit miss.
    """
    assert callable(qc_service.can_move_output)
    _t323_route(
        monkeypatch,
        where_rows=[{"id": "0", "title": "cerberus",
                     "address": "http://127.0.0.1:8188",
                     "fits": True, "file_here": _T323_FILE,
                     "vram_gib": 23.42, "confirmed": True}],
        fit=True,
        resolved=_T323_FILE)
    submitted = _t323_actuators(monkeypatch)
    fid, src, args = _t325_remote_finding("t325_refuse")
    dest = args["repair_path"]
    try:
        qc_service.h_repair(args, lambda m: None)
    except Exception as e:
        msg = str(e)
        assert "gpu work is still missing" not in msg.lower(), e
        assert "can_move_output" in msg, e
        assert _T325_REMOTE in msg, e
    else:
        raise AssertionError(
            "remote repair was submitted while can_move_output is false")
    assert submitted == [], "actuator ran before can_move_output refused"
    assert not os.path.isfile(dest)
    row = qc_service.get(fid)
    assert row["repair_path"] in (None, "")
    assert row["status"] != qc_service.REPAIRED


def test_t3_25_forced_true_remote_repair_is_submitted(monkeypatch):
    """T3-25 positive: force can_move_output true, remote repair SUBMITS.

    The flip is the criterion. A permanently-false check keeps the
    refusal green forever.
    """
    asked = []

    def _yes(host):
        asked.append(host)
        return True

    monkeypatch.setattr(qc_service, "can_move_output", _yes)
    _t323_route(
        monkeypatch,
        where_rows=[{"id": "0", "title": "cerberus",
                     "address": "http://127.0.0.1:8188",
                     "fits": True, "file_here": _T323_FILE,
                     "vram_gib": 23.42, "confirmed": True}],
        fit=True,
        resolved=_T323_FILE)
    submitted = _t323_actuators(monkeypatch)
    fid, src, args = _t325_remote_finding("t325_ok")
    dest = args["repair_path"]

    qc_service.h_repair(args, lambda m: None)

    assert asked, "dispatch_repair never called can_move_output"
    assert any(h == _T325_REMOTE or (
        h and _T325_REMOTE in str(h)) for h in asked), asked
    assert submitted and submitted[0][0] == "fix_ref", submitted
    assert os.path.isfile(src)
    assert os.path.isfile(dest), "forced-true remote repair did not SUBMIT"
    with open(src, "rb") as f:
        original = f.read()
    with open(dest, "rb") as f:
        written = f.read()
    assert written != original, "dest is a byte-copy of the broken artefact"
    row = qc_service.get(fid)
    assert row["repair_path"] == dest
    assert row["status"] == qc_service.REPAIRED


_T324_REFINER = "wan22_i2v_low"
_T324_PAIR = "wan22_i2v"
_T324_REFINER_FILE = models.CATALOG[_T324_REFINER]["file"]
_T324_PAIR_FILE = models.CATALOG[_T324_PAIR]["file"]

_T324_ETHAN = {
    "id": "3", "title": "ethan",
    "address": "http://ethan:8188",
    "fits": None, "file_here": _T324_REFINER_FILE,
    "vram_gib": 15.92, "confirmed": True,
}
_T324_PEACHES = {
    "id": "2", "title": "peaches",
    "address": "http://100.95.184.29:8188",
    "fits": None, "file_here": _T324_REFINER_FILE,
    "vram_gib": 10.58, "confirmed": True,
}
_T324_CERBERUS = {
    "id": "0", "title": "cerberus",
    "address": "http://127.0.0.1:8188",
    "fits": None, "file_here": _T324_REFINER_FILE,
    "vram_gib": 23.42, "confirmed": True,
}


def _t324_where_only(monkeypatch, where_rows):
    """Stub where() only. Real fits() is the T3-24 arithmetic."""
    asked = []

    def _where(key, backends):
        asked.append(("where", key, backends))
        return [dict(r) for r in where_rows]

    monkeypatch.setattr(models, "where", _where)
    monkeypatch.setattr(pipeline, "swarm_backends", lambda: [])
    return asked


def _t324_watch_fits(monkeypatch):
    """Record real fits() answers. Do not replace the arithmetic."""
    real = models.fits
    calls = []

    def _fits(key, vram_gib):
        result = real(key, vram_gib)
        calls.append((key, vram_gib, result))
        return result

    monkeypatch.setattr(models, "fits", _fits)
    return calls


def _t324_watch_invoke(monkeypatch):
    chosen = []
    orig = qc_service._invoke_actuator

    def _wrap(actuator, src, dest, args, progress):
        chosen.append({
            "actuator": actuator,
            "backend": args.get("backend"),
            "requires": args.get("requires"),
            "file_here": args.get("file_here"),
        })
        return orig(actuator, src, dest, args, progress)

    monkeypatch.setattr(qc_service, "_invoke_actuator", _wrap)
    return chosen


def test_t3_24_refiner_routed_off_15_92_to_24_and_submitted(monkeypatch):
    """T3-24: resident cost, not UNET 13.31, decides the box.

    ethan (15.92) is first and has the correctly-named file. If fits()
    still read weights_gib the 15.92 card would win. peaches is in the
    fleet and cannot hold the refiner. The 24 GiB box is SUBMITTED.
    Default dispatch_repair — real fits(), not a stubbed True/False.
    """
    spec = models.CATALOG[_T324_REFINER]
    resident = spec.get("resident_gib", spec["weights_gib"])
    assert resident > spec["weights_gib"], (
        "T3-24 is gone if resident_gib collapses back to the UNET's 13.31")
    assert resident >= 19.6, resident
    assert models.fits(_T324_REFINER, 15.92) is False
    assert models.fits(_T324_REFINER, 13.31) is False
    assert models.fits(_T324_REFINER, 10.58) is False
    assert models.fits(_T324_REFINER, 23.42) is True

    asked = _t324_where_only(
        monkeypatch, [_T324_ETHAN, _T324_PEACHES, _T324_CERBERUS])
    fit_calls = _t324_watch_fits(monkeypatch)
    submitted = _t323_actuators(monkeypatch)
    chosen = _t324_watch_invoke(monkeypatch)
    fid, src, args = _finding_with_file("t324_route")
    args = dict(args)
    args["kind"] = "clip"
    args["check_name"] = "soft"
    args["remedy"] = "refine pass"
    args["requires"] = _T324_REFINER
    args.pop("backend", None)
    args.pop("host", None)
    dest = args["repair_path"]

    qc_service.h_repair(args, lambda m: None)

    assert any(c[0] == "where" and c[1] == _T324_REFINER for c in asked), asked
    assert (_T324_REFINER, 15.92, False) in fit_calls, fit_calls
    assert (_T324_REFINER, 10.58, False) in fit_calls, fit_calls
    assert (_T324_REFINER, 23.42, True) in fit_calls, fit_calls
    assert chosen and chosen[0]["backend"] == "0", chosen
    assert chosen[0]["requires"] == _T324_REFINER
    assert chosen[0]["file_here"] == _T324_REFINER_FILE
    assert submitted, "correctly-named refiner on a 24 GiB box was not SUBMITTED"
    assert os.path.isfile(src)
    assert os.path.isfile(dest), "actuator submitted but dest was not written"
    with open(src, "rb") as f:
        original = f.read()
    with open(dest, "rb") as f:
        written = f.read()
    assert written != original, "dest is a byte-copy of the broken artefact"
    row = qc_service.get(fid)
    assert row["repair_path"] == dest
    assert row["status"] == qc_service.REPAIRED


def test_t3_24_peaches_cannot_take_the_pair(monkeypatch):
    """T3-24: the i2v pair is 13.31x2; peaches (10.58) cannot hold it.

    Default dispatch_repair. Real fits(). Refusal names the fit, not
    'GPU work is still missing'. Actuator must not run.
    """
    pair = models.CATALOG[_T324_PAIR]
    cost = pair.get("resident_gib", pair["weights_gib"])
    assert cost > 10.58, cost
    assert models.fits(_T324_PAIR, 10.58) is False
    assert models.fits(_T324_PAIR, 23.42) is False, (
        "the pair does not fit resident on a 24 GiB card either")

    peaches = dict(_T324_PEACHES, file_here=_T324_PAIR_FILE)
    asked = _t324_where_only(monkeypatch, [peaches])
    fit_calls = _t324_watch_fits(monkeypatch)
    submitted = _t323_actuators(monkeypatch)
    fid, src, args = _finding_with_file("t324_peach")
    args = dict(args)
    args["kind"] = "clip"
    args["requires"] = _T324_PAIR
    args["backend"] = "2"
    dest = args["repair_path"]

    try:
        qc_service.h_repair(args, lambda m: None)
    except Exception as e:
        msg = str(e).lower()
        assert "gpu work is still missing" not in msg, e
        assert any(w in msg for w in (
            "fit", "cannot run", "no box", "unfittable")), e
    else:
        raise AssertionError("peaches took the i2v pair")

    assert any(c[0] == "where" and c[1] == _T324_PAIR for c in asked), asked
    assert (_T324_PAIR, 10.58, False) in fit_calls, fit_calls
    assert submitted == [], "actuator ran after peaches could not hold the pair"
    assert not os.path.isfile(dest)
    row = qc_service.get(fid)
    assert row["repair_path"] in (None, "")
    assert row["status"] != qc_service.REPAIRED
