"""T9-1, T9-2, T9-3, T9-4, T9-5, T9-6, T9-7, T9-8, T9-11, T9-13a, T9-14, T9-16, T9-17, and the RENDER_BACKEND seam.

The fleet machinery is live; these criteria were not independently asserted
outside pipeline.demo() (slow, and skipped by default). Offline only: the
live-fleet half of T9-1 (as-written refuses AND retargeted renders on a real
box) stays in demo(). Deleting the helper these call must go red.

conftest stubs pipeline for app tests. This file loads the real module under a
private name so it cannot hit SwarmUI and cannot inspect the stub.
"""
import inspect
import io
import json
import os
import tempfile
import urllib.error
import urllib.request
from contextlib import redirect_stderr

import creds
import db
import fleet_watch
import jobs
import models
import pytest
from conftest import _real_module

pipeline = _real_module("pipeline")
assert pipeline is not None, "real pipeline.py failed to import"

# Real enums, trimmed: models.demo() read these from /object_info on 2026-08-12.
# A VAE name lives in VAELoader on both boxes and never in UNETLoader -- that
# is T9-2's fixture, not an invention.
CERBERUS = {
    "CheckpointLoaderSimple": {"ace_step_v1_3.5b.safetensors"},
    "VAELoader": {"ae.safetensors", "qwen_image_vae.safetensors"},
    "UNETLoader": {"qwen_image_edit_2511_fp8mixed.safetensors",
                   "z_image_turbo_fp8mix.safetensors"},
}
PEACHES = {
    "CheckpointLoaderSimple": {"ace_step_v1_3.5b_fp16.safetensors"},
    "VAELoader": {"z_image_ae.safetensors", "flux2-vae.safetensors"},
    "UNETLoader": {"z_image_turbo_fp8mix.safetensors",
                   "flux-2-klein-4b-fp8.safetensors"},
}
BOXES = [
    {"id": "0", "address": "http://cerberus", "status": "running"},
    {"id": "2", "address": "http://peaches", "status": "running"},
]
POOLS = {"http://cerberus": CERBERUS, "http://peaches": PEACHES}

# Measured on this fleet 2026-08-12. Both families share the "No backends
# match" headline; the reason line is the discriminator (T9-6 / T6-4).
VANISHED = (
    "No backends match the settings of the request given! Backends refused "
    "for the following reason(s):\n- Specific backend ID# requested in "
    "advanced parameters did not match",
    "did not finish within 1800s",
)
REFUSED = (
    "No backends match the settings of the request given! Backends "
    "refused for the following reason(s):\n- The custom workflow "
    "contains an unsupported node type 'EmptyImage'.",
    "Model in folder 'vae' with filename "
    "'qwen_image_vae.safetensors' not found.",
)


def _ckpt(name):
    return json.dumps({
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": name}},
        "99": {"inputs": {"filename_prefix": "audio/demo"}},
    })


def _retarget_on_fleet():
    """Pin _retarget to the fixture boxes; restore even if a test raises."""
    was_sb, was_inst = pipeline.swarm_backends, pipeline.models.installed
    pipeline.swarm_backends = lambda: BOXES
    pipeline.models.installed = lambda object_info=None, url=None: POOLS.get(url)
    return was_sb, was_inst


def _restore_fleet(was_sb, was_inst):
    pipeline.swarm_backends, pipeline.models.installed = was_sb, was_inst


def test_t9_1_retarget_rewrites_both_directions_and_as_written_is_absent():
    """T9-1: as-written spelling is not on the pin; retargeted spelling is.

    Both directions in one test or a retargeter that always rewrites into one
    box's name certifies itself. Offline stand-in for the live 9.7s render:
    the target pool is the refusal/success oracle, not SwarmUI.
    """
    was = _retarget_on_fleet()
    try:
        fp16 = "ace_step_v1_3.5b_fp16.safetensors"
        bf16 = "ace_step_v1_3.5b.safetensors"
        # peaches spelling, pinned to cerberus
        assert fp16 not in CERBERUS["CheckpointLoaderSimple"]
        to_cerberus = json.loads(pipeline._retarget(_ckpt(fp16), "0"))
        sent = to_cerberus["1"]["inputs"]["ckpt_name"]
        assert sent == bf16, f"cerberus was handed a filename it does not hold: {sent}"
        assert sent in CERBERUS["CheckpointLoaderSimple"]
        # cerberus spelling, pinned to peaches
        assert bf16 not in PEACHES["CheckpointLoaderSimple"]
        to_peaches = json.loads(pipeline._retarget(_ckpt(bf16), "2"))
        sent = to_peaches["1"]["inputs"]["ckpt_name"]
        assert sent == fp16, f"peaches was handed a filename it does not hold: {sent}"
        assert sent in PEACHES["CheckpointLoaderSimple"]
    finally:
        _restore_fleet(*was)


def test_t9_2_retarget_is_per_loader_not_a_global_rename():
    """T9-2: a VAE name is never resolved out of the UNET enum.

    Positive half: the same name on the VAE loader IS substituted. A global
    string-replace would rewrite the UNET input too and stay green on the
    VAE assertion alone.
    """
    was = _retarget_on_fleet()
    try:
        wf = json.dumps({
            "1": {"class_type": "VAELoader",
                  "inputs": {"vae_name": "ae.safetensors"}},
            "2": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": "ae.safetensors"}},
        })
        # ae.safetensors exists as a VAE alias and is absent from peaches UNET.
        assert "ae.safetensors" not in PEACHES["UNETLoader"]
        assert "z_image_ae.safetensors" not in PEACHES["UNETLoader"]
        got = json.loads(pipeline._retarget(wf, "2"))
        assert got["1"]["inputs"]["vae_name"] == "z_image_ae.safetensors", \
            "a name that exists in the right loader was not substituted"
        assert got["2"]["inputs"]["unet_name"] == "ae.safetensors", \
            "a VAE name was resolved out of a different loader's list"
    finally:
        _restore_fleet(*was)


def test_t9_3_free_draw_is_object_identity_and_asks_nothing():
    """T9-3: the free draw goes out byte-identical, by identity not equality.

    A rebuild of the same JSON reads as untouched while busting ComfyUI's
    execution cache. The guard is worth the ASKING -- one ListBackends per
    workflow -- so a pin=None that still consults the fleet is a failure.
    Positive half: the same fixture IS rewritten when pinned.
    """
    asked = []
    was_call, was_sb = pipeline._swarm_call, pipeline.swarm_backends
    was_fleet = _retarget_on_fleet()
    try:
        pipeline._swarm_call = lambda path, payload, timeout=30: (
            asked.append(path) or {})
        pipeline.swarm_backends = lambda: asked.append("swarm_backends") or BOXES
        plain = "PLAIN TEXT, NOT EVEN JSON"
        assert pipeline._retarget(plain, None) is plain, \
            "the free draw came back re-serialised, so the cache key changed"
        assert not asked, \
            f"the free draw asked SwarmUI what each box holds: {asked}"

        # same fixture, pinned: must not be the original object, and must change
        fp16 = "ace_step_v1_3.5b_fp16.safetensors"
        src = _ckpt(fp16)
        pinned = pipeline._retarget(src, "0")
        assert pinned is not src, "a pinned attempt returned the original object"
        assert json.loads(pinned)["1"]["inputs"]["ckpt_name"] != fp16
    finally:
        pipeline._swarm_call, pipeline.swarm_backends = was_call, was_sb
        _restore_fleet(*was_fleet)


def test_t9_6_vanished_requeues_refused_does_not():
    """T9-6: the reason line, not the shared headline, is the discriminator.

    A vanished box requeues (jobs._TRANSIENT agrees with pipeline's exhausted
    walk). A refused workflow does not. Four strings SwarmUI actually produced.
    """
    for msg in VANISHED:
        assert pipeline._backend_vanished(msg), \
            f"a vanished box read as a refusal: {msg[:60]}"
    for msg in REFUSED:
        assert not pipeline._backend_vanished(msg), \
            f"a REFUSED workflow read as a vanished box: {msg[:60]}"

    gone = RuntimeError(
        "cannot reach SwarmUI backends for wf.json: every box that could run it "
        "is offline or went away mid-render (No backends match ...)")
    refused = RuntimeError(REFUSED[0])
    assert jobs._is_transient(gone), \
        "pipeline's offline-backend wording no longer matches jobs._TRANSIENT"
    assert not jobs._is_transient(refused), \
        "a workflow every box REFUSED is queued for retry"


def test_render_backend_seam_is_one_branch_and_both_paths_are_taken():
    """RENDER_BACKEND is one comparison, and both sides of it run.

    DDD-8-10 §3.1: _submit_and_collect is the only place that branches, which
    is why the swarm path could be added without touching the seven gen_*
    wrappers. A source check plus a behavioural one: deleting the comparison
    or hard-coding one side leaves a path un-taken.
    """
    src = inspect.getsource(pipeline)
    assert src.count('RENDER_BACKEND == "swarm"') == 1, \
        "the seam is no longer one comparison"
    for name in ("gen_anchor", "gen_refs", "gen_clips", "gen_audio",
                 "gen_postproc", "gen_artwork"):
        body = inspect.getsource(getattr(pipeline, name))
        assert "RENDER_BACKEND" not in body, \
            f"{name} now branches on the backend"

    taken = []
    was = (pipeline.RENDER_BACKEND, pipeline.submit_dir, pipeline.submit_swarm,
           pipeline.gpu.preflight, pipeline.gpu.ollama_holding,
           pipeline.submitted_prefixes, pipeline.collect, pipeline._stamp)
    try:
        pipeline.gpu.preflight = lambda progress=None: taken.append("preflight")
        pipeline.gpu.ollama_holding = lambda: False
        pipeline.submitted_prefixes = lambda d: set()
        pipeline.collect = lambda *a, **k: []
        pipeline._stamp = lambda *a, **k: None
        pipeline.submit_dir = lambda *a, **k: taken.append("comfy")
        pipeline.submit_swarm = lambda *a, **k: taken.append("swarm") or []
        with tempfile.TemporaryDirectory() as d:
            pipeline.RENDER_BACKEND = "comfy"
            pipeline._submit_and_collect(d, "x", "*.png", lambda m: None)
            pipeline.RENDER_BACKEND = "swarm"
            pipeline._submit_and_collect(d, "x", "*.png", lambda m: None)
        assert taken == ["preflight", "comfy", "swarm"], taken
    finally:
        (pipeline.RENDER_BACKEND, pipeline.submit_dir, pipeline.submit_swarm,
         pipeline.gpu.preflight, pipeline.gpu.ollama_holding,
         pipeline.submitted_prefixes, pipeline.collect, pipeline._stamp) = was


# T9-4 / T6-A6. Same measured enums as models.demo() (2026-08-12), plus a
# box that never answers. object_info shape, not the installed() sets above:
# catalog() is the producer of available True/False/None.
CERBERUS_INFO = {
    "UNETLoader": {"input": {"required": {"unet_name": [
        ["qwen_image_edit_2511_fp8mixed.safetensors",
         "z_image_turbo_fp8mix.safetensors"]]}}},
    "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [
        ["ace_step_v1_3.5b.safetensors"]]}}},
    "VAELoader": {"input": {"required": {"vae_name": [
        ["ae.safetensors", "qwen_image_vae.safetensors"]]}}},
}
PEACHES_INFO = {
    "UNETLoader": {"input": {"required": {"unet_name": [
        ["z_image_turbo_fp8mix.safetensors",
         "flux-2-klein-4b-fp8.safetensors"]]}}},
    "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [
        ["ace_step_v1_3.5b_fp16.safetensors"]]}}},
    "VAELoader": {"input": {"required": {"vae_name": [
        ["z_image_ae.safetensors", "flux2-vae.safetensors"]]}}},
}
T9_4_FLEET = [
    {"id": "0", "title": "cerberus", "status": "running",
     "address": "http://127.0.0.1:8188"},
    {"id": "2", "title": "peaches", "status": "running",
     "address": "http://100.95.184.29:8188"},
    {"id": "9", "title": "ghost", "status": "running",
     "address": "http://10.0.0.99:8188"},
]
# Answered, but UNETLoader publishes no enum. catalog() must leave available
# as None — not False. The existing ghost is unreachable (have is None);
# mutating `None if pool is None else bool(found)` to bool(found) stayed
# green on that fixture alone.
PARTIAL_INFO = {
    "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [
        ["ace_step_v1_3.5b.safetensors"]]}}},
}
T9_4_PARTIAL = {
    "id": "4", "title": "partial", "status": "running",
    "address": "http://10.0.0.4:8188",
}
T9_4_INFO = {
    "http://127.0.0.1:8188": CERBERUS_INFO,
    "http://100.95.184.29:8188": PEACHES_INFO,
    "http://10.0.0.4:8188": PARTIAL_INFO,
}
T9_4_STATS = {
    "http://127.0.0.1:8188": {"vram_gib": 23.42, "gpu": "RTX 5090 Laptop"},
    "http://100.95.184.29:8188": {"vram_gib": 10.58, "gpu": "RTX 2080 Ti"},
    "http://10.0.0.4:8188": {"vram_gib": 23.42, "gpu": "RTX 5090"},
}


def _t9_4_stub_fleet():
    """Pin catalog/where to the fixture boxes. Restore even if a test raises."""
    was_info, was_stats = models._object_info, models._system_stats
    models._object_info = lambda url=None: T9_4_INFO.get(url)
    models._system_stats = lambda url=None: T9_4_STATS.get(url)
    return was_info, was_stats


def _t9_4_restore_fleet(was_info, was_stats):
    models._object_info, models._system_stats = was_info, was_stats


def _available(backend_id, key):
    row = next(b for b in models.by_backend(T9_4_FLEET) if b["id"] == backend_id)
    return next(e["available"] for e in row["models"] if e["key"] == key)


def test_t9_4_where_is_three_valued_and_none_is_offered():
    """T9-4: available is True, False or None; False is dropped, None is not.

    One-sided trap (TRD-9 §9): a filter that treats every box as False stays
    green on "peaches lacks qwen". The paired positive is a None box still
    listed as a candidate. `if not entry["available"]` is the mutation that
    must go red — that is the T6-A6 bug.

    Same fleet, two keys, or a hard-coded "always drop peaches" certifies
    itself: peaches is False for qwen and True for ace_step_v1.
    """
    was = _t9_4_stub_fleet()
    try:
        assert _available("0", "qwen_image_edit_2511") is True
        assert _available("2", "qwen_image_edit_2511") is False
        assert _available("9", "qwen_image_edit_2511") is None
        assert _available("2", "ace_step_v1") is True

        qwen = models.where("qwen_image_edit_2511", T9_4_FLEET)
        qwen_ids = [r["id"] for r in qwen]
        assert "0" in qwen_ids, "a confirmed box was not offered"
        assert "2" not in qwen_ids, (
            "a box that answered and lacks the model was offered")
        assert "9" in qwen_ids, (
            "a None box was not offered — three-valued collapsed to False")
        assert qwen_ids[0] == "0", (
            "unconfirmed sorted before confirmed — None is a candidate, "
            "not the first pick")
        assert qwen_ids[-1] == "9"
        assert next(r for r in qwen if r["id"] == "0")["confirmed"] is True
        assert next(r for r in qwen if r["id"] == "9")["confirmed"] is False
        assert next(r for r in qwen if r["id"] == "9")["reachable"] is False

        ghost_only = models.where("qwen_image_edit_2511", [T9_4_FLEET[2]])
        assert len(ghost_only) == 1, (
            f"an unreachable box was reported as unable: {ghost_only}")
        assert ghost_only[0]["confirmed"] is False
        assert ghost_only[0]["id"] == "9"

        false_only = models.where("qwen_image_edit_2511", [T9_4_FLEET[1]])
        assert false_only == [], (
            f"a False-only fleet was offered as a candidate: {false_only}")

        ace = models.where("ace_step_v1", T9_4_FLEET)
        ace_ids = {r["id"] for r in ace}
        assert ace_ids == {"0", "2", "9"}, (
            f"peaches holds ace_step_v1 and must stay a candidate: {ace}")
        assert all(r["confirmed"] is True for r in ace if r["id"] in ("0", "2"))
        assert next(r for r in ace if r["id"] == "9")["confirmed"] is False

        assert models.where("qwen_image_edit_2511", None) == []
        assert models.where("qwen_image_edit_2511", []) == []
    finally:
        _t9_4_restore_fleet(*was)


def test_t9_4_answered_box_with_no_loader_enum_is_none_not_false():
    """T9-4: reachable + no enumerable loader is None, still a candidate.

    installed() answers None for that loader, not set(). catalog() must
    keep available is None. `bool(found)` after resolve(pool=None) is
    False and is the mutation that must go red — the unreachable ghost
    takes a different branch (have is None) and cannot see it.

    T9-5 is fits, not available: this box has VRAM enough for qwen so a
    collapse of unknown-enum into False is not a slow-box sort.
    """
    was = _t9_4_stub_fleet()
    try:
        fleet = [T9_4_PARTIAL]
        row = models.by_backend(fleet)[0]
        assert row["reachable"] is True, "an answering box was marked unreachable"
        avail = next(e["available"] for e in row["models"]
                     if e["key"] == "qwen_image_edit_2511")
        assert avail is None, (
            f"a missing UNET enum read as {avail!r}, not None — unknown "
            "collapsed to missing")
        ace_avail = next(e["available"] for e in row["models"]
                         if e["key"] == "ace_step_v1")
        assert ace_avail is True, (
            "the loader that DID enumerate was not confirmed")

        offered = models.where("qwen_image_edit_2511", fleet)
        assert len(offered) == 1, (
            f"an answered box with no UNET enum was refused: {offered}")
        assert offered[0]["id"] == "4"
        assert offered[0]["confirmed"] is False
        assert offered[0]["reachable"] is True

        mixed = models.where("qwen_image_edit_2511",
                             T9_4_FLEET + [T9_4_PARTIAL])
        mixed_ids = [r["id"] for r in mixed]
        assert mixed_ids == ["0", "4", "9"], mixed_ids
        assert "2" not in mixed_ids, "peaches False was offered beside the Nones"
    finally:
        _t9_4_restore_fleet(*was)


def _t9_4_isolate_jobs():
    was = (db.DATA, db.DB_PATH, jobs.LOGS, jobs._capability_where)
    data = tempfile.mkdtemp(prefix="t94_")
    db.DATA = data
    db.DB_PATH = os.path.join(data, "t.db")
    db._local.__dict__.clear()
    jobs.LOGS = os.path.join(data, "logs")
    if "t94" not in jobs._handlers:
        @jobs.handler("t94")
        def _t94(args, progress):
            return args
    return was


def _t9_4_restore_jobs(was):
    db.DATA, db.DB_PATH, jobs.LOGS, jobs._capability_where = was
    db._local.__dict__.clear()


def test_t9_4_claim_consumer_treats_none_as_candidate_and_false_as_refusal():
    """T9-4: a where() consumer must respect all three values.

    T6-3 stubs where(), so collapsing None inside where() stayed green
    there. This wires the real function onto the T9-4 fleet: a False-only
    match leaves the job queued; a None-only match is pulled. T6-A10:
    asserted through _claim, not a helper that wraps it.

    Does not change the production matcher (T6-1 / no second scheduler).
    """
    was_fleet = _t9_4_stub_fleet()
    try:
        was_jobs = _t9_4_isolate_jobs()
        try:
            jobs._capability_where = (
                lambda key, backends: models.where(key, [T9_4_FLEET[1]]))
            refused = jobs.enqueue("t94", {"requires": "qwen_image_edit_2511"})
            later = jobs.enqueue("t94", {"who": "later"})
            pulled = jobs._claim()
            assert pulled is not None and pulled["id"] == later, (
                f"_claim took {pulled['id'] if pulled else None}; a False-only "
                "where() result must refuse the requires job")
            assert jobs.get(refused)["status"] == "queued"
        finally:
            _t9_4_restore_jobs(was_jobs)

        was_jobs = _t9_4_isolate_jobs()
        try:
            jobs._capability_where = (
                lambda key, backends: models.where(key, [T9_4_FLEET[2]]))
            ghost = jobs.enqueue("t94", {"requires": "qwen_image_edit_2511"})
            pulled = jobs._claim()
            assert pulled is not None and pulled["id"] == ghost, (
                "an unconfirmed None candidate was treated as a refusal")
        finally:
            _t9_4_restore_jobs(was_jobs)

        was_jobs = _t9_4_isolate_jobs()
        try:
            jobs._capability_where = (
                lambda key, backends: models.where(key, [T9_4_PARTIAL]))
            partial = jobs.enqueue("t94", {"requires": "qwen_image_edit_2511"})
            pulled = jobs._claim()
            assert pulled is not None and pulled["id"] == partial, (
                "a reachable box with no loader enum was treated as a refusal")
        finally:
            _t9_4_restore_jobs(was_jobs)
    finally:
        _t9_4_restore_fleet(*was_fleet)


# T9-5. Two answering boxes that both HOLD the file. The 10.58 GiB card
# cannot keep wan22_s2v resident (15.27 GiB, measured 1.44x). Same stability
# class, slow box has the lower id — dropping `fits is False` from the sort
# key puts the slow box first and the order assertion goes red.
# T9-4 peaches lacks qwen (available False); that fixture cannot see this.
T9_5_SLOW = {
    "id": "0", "title": "tiny", "status": "running",
    "address": "http://10.0.0.10:8188",
}
T9_5_FITS = {
    "id": "2", "title": "wide", "status": "running",
    "address": "http://10.0.0.12:8188",
}
T9_5_FLEET = [T9_5_SLOW, T9_5_FITS]
T9_5_HOLDING = {
    "UNETLoader": {"input": {"required": {"unet_name": [
        ["wan2.2_s2v_14B_fp8_scaled.safetensors"]]}}},
    "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [
        ["ace_step_v1_3.5b.safetensors"]]}}},
}
T9_5_INFO = {
    "http://10.0.0.10:8188": T9_5_HOLDING,
    "http://10.0.0.12:8188": T9_5_HOLDING,
}
T9_5_STATS = {
    "http://10.0.0.10:8188": {"vram_gib": 10.58, "gpu": "RTX 2080 Ti"},
    "http://10.0.0.12:8188": {"vram_gib": 23.42, "gpu": "RTX 5090"},
}


def test_t9_5_nonresident_box_stays_in_the_plan_later():
    """T9-5: a box that cannot hold the model resident is later, not out.

    Positive half (TRD-9 §9): a plan with a fitting AND a non-fitting box
    still includes the slow one, later in the order. Dropping fits=False
    rows, or sorting only by id/stability, must go red. Same fleet, a
    model both cards hold resident, or a "small cards last" sort stays
    green on s2v alone.
    """
    was_info, was_stats = models._object_info, models._system_stats
    models._object_info = lambda url=None: T9_5_INFO.get(url)
    models._system_stats = lambda url=None: T9_5_STATS.get(url)
    try:
        assert models.fits("wan22_s2v", 10.58) is False
        assert models.fits("wan22_s2v", 23.42) is True
        assert models.fits("ace_step_v1", 10.58) is True
        assert models.fits("ace_step_v1", 23.42) is True

        plan = models.where("wan22_s2v", T9_5_FLEET)
        ids = [r["id"] for r in plan]
        assert "0" in ids, (
            f"the 10.58 GiB box that holds s2v was dropped: {plan}")
        assert "2" in ids, (
            f"the fitting box was not in the plan: {plan}")
        assert ids.index("2") < ids.index("0"), (
            f"the non-resident box was not later in the plan: {ids}")
        assert next(r for r in plan if r["id"] == "0")["fits"] is False
        assert next(r for r in plan if r["id"] == "2")["fits"] is True

        ace = models.where("ace_step_v1", T9_5_FLEET)
        ace_ids = [r["id"] for r in ace]
        assert ace_ids == ["0", "2"], ace_ids
        assert all(r["fits"] is True for r in ace)
    finally:
        models._object_info, models._system_stats = was_info, was_stats


# Measured 2026-08-12 (SESSIONS.md): after a validation refuse, Swarm can
# answer "No backends match" on the next pin for about a minute — the box is
# benched, not gone. Same headline as T9-6 vanished; the walk must still step.
BENCHED_AFTER_REFUSE = (
    "No backends match the settings of the request given! Backends refused "
    "for the following reason(s):\n- Specific backend ID# requested in "
    "advanced parameters did not match"
)
VALIDATION_REFUSE = (
    "Model in folder 'vae' with filename "
    "'qwen_image_vae.safetensors' not found."
)


def test_t9_7_refusal_benches_next_pin_and_walk_still_continues():
    """T9-7: a refuse can take a backend out from under the next walk step.

    Positive half (TRD-9 §9): after a refusal, a subsequent attempt is still
    made and the sequence is observable. Not a timing test. Mutations that
    must go red: stop the walk on the benched "No backends match" headline
    mid-walk; delete the walk so only the free draw runs; silent retries with
    no progress line per pin.
    """
    was = (
        pipeline.RENDER_BACKEND, pipeline.COMFY_OUTPUT, pipeline._swarm_call,
        pipeline._stamp, pipeline.gpu.ollama_holding, pipeline.gpu.preflight,
        pipeline.gpu.release_ollama, urllib.request.urlopen,
    )
    said = []
    tries = []
    payloads = []

    class _Blob:
        def __init__(self, b):
            self.b = b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.b

    def fleet_call(path, payload, timeout=30):
        if path.endswith("ListBackends"):
            return {
                str(i): {"status": "running", "title": f"box{i}",
                         "address": f"http://10.0.0.{i}:8188"}
                for i in range(3)
            }
        if path.endswith("GenerateText2Image"):
            tries.append(path)
            payloads.append(dict(payload))
            n = len(tries)
            if n == 1:
                # free draw: validation refuse — Swarm may bench that box
                return {"error": VALIDATION_REFUSE}
            if n == 2:
                # next pin hits the benched backend (same headline as vanished)
                return {"error": BENCHED_AFTER_REFUSE}
            # later pin still runs and succeeds
            return {"images": ["View/local/raw/2026-08-12/0120001--unknown.png"]}
        return {}

    with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as d:
        pipeline.RENDER_BACKEND = "swarm"
        pipeline.COMFY_OUTPUT = out
        pipeline._swarm_call = fleet_call
        pipeline._stamp = lambda *a, **k: None
        pipeline.gpu.ollama_holding = lambda: False
        pipeline.gpu.preflight = lambda progress=None: None
        pipeline.gpu.release_ollama = lambda progress=None: None
        urllib.request.urlopen = lambda url, timeout=None: _Blob(b"PNGDATA")
        try:
            json.dump(
                {"1": {"inputs": {"filename_prefix": "anchor_v2/front_s42"}}},
                open(os.path.join(d, "wf.json"), "w"),
            )
            got = pipeline._submit_and_collect(
                d, "anchor_v2", "*.png", said.append)
        finally:
            (pipeline.RENDER_BACKEND, pipeline.COMFY_OUTPUT, pipeline._swarm_call,
             pipeline._stamp, pipeline.gpu.ollama_holding, pipeline.gpu.preflight,
             pipeline.gpu.release_ollama, urllib.request.urlopen) = was

    assert len(tries) == 3, (
        f"walk did not continue after refuse + benched next pin: {tries}")
    pins = [p.get("exactbackendid") for p in payloads]
    assert pins[0] is None, f"free draw was not first: {pins}"
    assert pins[1] == "0", f"first pin after free draw was not backend 0: {pins}"
    assert pins[2] == "1", (
        f"walk stopped before the pin after the benched backend: {pins}")
    assert any("refused by SwarmUI" in m and "not found" in m for m in said), (
        f"validation refuse not observable: {said}")
    assert any(
        "refused by backend 0" in m and "No backends match" in m for m in said
    ), f"benched next pin not observable: {said}"
    assert any("refused by" in m for m in said if "backend 0" in m), said
    assert [os.path.basename(p) for p in got] == ["front_s42_00001_.png"], got
    # Mid-walk benched headline must not reclassify the whole walk as vanished
    # before later pins run — T9-6 still owns exhaust-only requeue.
    assert not any("offline or went away" in m for m in said), said


# T9-8. fleet_watch already edges on up/down; without a count assertion a
# poll-spam notify still looks green. Exercise once() with a flapping box:
# first reading silent, one alert per real transition, zero on re-polls.


def test_t9_8_state_change_alerts_once_per_transition_not_per_poll():
    """T9-8: a backend state change says something once per transition.

    Positive half (TRD-9 §9): a flapping box produces one alert per
    transition, asserted by count. A box that stays down across many polls
    fires once on the edge; recovery is a second edge; same-state re-polls
    fire nothing. First reading is never an alert (restart must not spam).
    Wired through once() so a transitions()-only fix that never notifies
    still goes red.
    """
    up = {"h": {"label": "box", "up": True, "detail": "ok",
                "running": 0, "pending": 0}}
    down = {"h": {"label": "box", "up": False, "detail": "URLError",
                  "running": None, "pending": None}}

    assert fleet_watch.transitions({}, up) == [], (
        "a first reading alerted — every watcher restart would spam")
    assert fleet_watch.transitions(up, up) == []
    assert fleet_watch.transitions(down, down) == []

    # stay down for many polls: one edge only
    fired, state = 0, up
    for _ in range(20):
        fired += len(fleet_watch.transitions(state, down))
        state = down
    assert fired == 1, (
        f"a box down for 20 scans alerted {fired} times — once-per-poll flood")
    assert len(fleet_watch.transitions(state, up)) == 1, (
        "the recovery after a long outage was missed")

    # flap: each edge is one, asserted by count
    seq = [up, down, up, down, up]
    edges = sum(len(fleet_watch.transitions(seq[i - 1], seq[i]))
                for i in range(1, len(seq)))
    assert edges == 4, f"flapping edges counted {edges}, want 4"

    # once() path: notify is what "says something". Mock scan + notify.
    # Sequence: first up (seed), down, down, down, up, up → 2 alerts.
    alerts = []
    readings = [up, down, down, down, up, up]
    idx = {"i": 0}
    was_scan, was_notify = fleet_watch.scan, fleet_watch.notify
    try:
        def fake_scan(fleet=None):
            r = readings[min(idx["i"], len(readings) - 1)]
            idx["i"] += 1
            return r

        fleet_watch.scan = fake_scan
        fleet_watch.notify = (
            lambda lines, webhook=None: alerts.append(list(lines)) or True)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            for _ in readings:
                fleet_watch.once(
                    state_path=path, webhook="http://example/hook", quiet=True)
        assert len(alerts) == 2, (
            f"once() alerted {len(alerts)} times on a 2-edge flap "
            f"(seed + down×3 + up×2); want 2 — one per transition")
        assert any("OFFLINE" in line for line in alerts[0])
        assert any("ONLINE" in line for line in alerts[1])
    finally:
        fleet_watch.scan, fleet_watch.notify = was_scan, was_notify


# Swarm keys that would consult the connect-time node/model list for routing.
# Studio submit must not use these as the graph discriminator (T9-11).
_SWARM_MODEL_ROUTE_KEYS = ("model", "models", "modelname", "loras")


def test_t9_11_submit_stays_comfyworkflowraw_plus_exactbackendid():
    """T9-11: studio submit stays raw+pinned; Swarm's cache is not the discriminator.

    Rescoped 2026-08-13: the connect-time node/model list hazard is inert on
    our path because every GenerateText2Image carries comfyworkflowraw and
    every pin carries exactbackendid — ComfyUI on the target validates
    filenames itself. Swarm's own model-based routing would consult the stale
    list; that path is not ours.

    Positive half: free draw and a pin both ship the inert shape in one walk.
    Mutations that must go red:
      - drop comfyworkflowraw (route by Swarm model name alone)
      - drop exactbackendid on a pin (let Swarm pick by its cached list)
      - put model=/models= on the payload without raw workflow as the graph
    """
    was = (
        pipeline.RENDER_BACKEND, pipeline.COMFY_OUTPUT, pipeline._swarm_call,
        pipeline._stamp, pipeline.gpu.ollama_holding, pipeline.gpu.preflight,
        pipeline.gpu.release_ollama, urllib.request.urlopen,
    )
    payloads = []

    class _Blob:
        def __init__(self, b):
            self.b = b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.b

    def fleet_call(path, payload, timeout=30):
        if path.endswith("ListBackends"):
            return {
                "0": {"status": "running", "title": "box0",
                      "address": "http://10.0.0.0:8188"},
                "1": {"status": "running", "title": "box1",
                      "address": "http://10.0.0.1:8188"},
            }
        if path.endswith("GenerateText2Image"):
            payloads.append(dict(payload))
            # free draw refuses so the walk pins and we see both shapes
            if len(payloads) == 1:
                return {"error": VALIDATION_REFUSE}
            return {"images": ["View/local/raw/2026-08-12/0120001--unknown.png"]}
        return {}

    with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as d:
        pipeline.RENDER_BACKEND = "swarm"
        pipeline.COMFY_OUTPUT = out
        pipeline._swarm_call = fleet_call
        pipeline._stamp = lambda *a, **k: None
        pipeline.gpu.ollama_holding = lambda: False
        pipeline.gpu.preflight = lambda progress=None: None
        pipeline.gpu.release_ollama = lambda progress=None: None
        urllib.request.urlopen = lambda url, timeout=None: _Blob(b"PNGDATA")
        try:
            json.dump(
                {"1": {"inputs": {"filename_prefix": "anchor_v2/front_s42"}}},
                open(os.path.join(d, "wf.json"), "w"),
            )
            got = pipeline._submit_and_collect(
                d, "anchor_v2", "*.png", lambda m: None)
        finally:
            (pipeline.RENDER_BACKEND, pipeline.COMFY_OUTPUT, pipeline._swarm_call,
             pipeline._stamp, pipeline.gpu.ollama_holding, pipeline.gpu.preflight,
             pipeline.gpu.release_ollama, urllib.request.urlopen) = was

    assert len(payloads) >= 2, f"need free draw + pin to lock both shapes: {payloads}"
    free, pin = payloads[0], payloads[1]

    # Free draw: raw workflow is the graph; no exact pin (Swarm may load-balance).
    assert "comfyworkflowraw" in free and free["comfyworkflowraw"], free
    assert free.get("exactbackendid") is None, free
    # Pin: raw workflow still the graph; exactbackendid names the box.
    assert "comfyworkflowraw" in pin and pin["comfyworkflowraw"], pin
    assert pin.get("exactbackendid") == "0", pin

    for p in payloads:
        assert "comfyworkflowraw" in p and p["comfyworkflowraw"], (
            f"GenerateText2Image without comfyworkflowraw consults Swarm's "
            f"connect-time list: {p}")
        # Model-route keys alone would make Swarm the discriminator.
        if any(p.get(k) for k in _SWARM_MODEL_ROUTE_KEYS):
            assert p.get("comfyworkflowraw"), (
                f"model-route keys without raw workflow: {p}")
        # images count is fine; the graph must still be raw.
        assert "images" in p, p

    # Unit-level: _swarm_generate itself builds the inert shape (not only the
    # walk). Dropping the key here while the walk still passes would be a
    # different door into the same defect.
    unit = []
    was_call = pipeline._swarm_call
    pipeline._swarm_call = (
        lambda path, payload, timeout=30: unit.append(dict(payload))
        or {"images": ["View/x.png"]})
    try:
        pipeline._swarm_generate('{"1":{}}', None, None, None)
        pipeline._swarm_generate('{"1":{}}', None, None, "2")
    finally:
        pipeline._swarm_call = was_call
    assert unit[0] == {"images": 1, "comfyworkflowraw": '{"1":{}}'}, unit[0]
    assert unit[1] == {
        "images": 1,
        "comfyworkflowraw": '{"1":{}}',
        "exactbackendid": "2",
    }, unit[1]
    assert [os.path.basename(p) for p in got] == ["front_s42_00001_.png"], got


def test_t9_13a_truncated_or_enum_only_weight_is_not_available():
    """T9-13a: a file is not a model; enum membership is not availability.

    Measured 2026-08-13: gamingpc's UNETLoader listed the Qwen UNET at 26% of
    its bytes. models.installed() reads the loader enum, never the bytes, so a
    truncated weight reported available and failed at load.

    Two free detection rules (TRD-9):
      - epoch mtime → truncated (rsync --partial sets mtime only on completion)
      - size short of expected_bytes → truncated (--inplace carries a live mtime)

    Enum-only (path=None) is not available either: that is the defect shape.
    Positive half: a complete file with non-epoch mtime and full size IS
    available — or a predicate that always returns False stays green on the
    refusal arms alone.
    """
    assert callable(getattr(models, "weight_available", None)), (
        "models.weight_available is the byte check; enum-only is the defect")

    # Enum-only: no path, no bytes. The loader enum listed the name; that is
    # not a model.
    assert models.weight_available(None) is False, (
        "enum-only evidence read as available")
    assert models.weight_available(None, expected_bytes=1000) is False, (
        "enum-only with an expected size still is not a model")
    assert models.weight_available("") is False
    assert models.weight_available("/no/such/weight.safetensors",
                                   expected_bytes=1000) is False

    with tempfile.TemporaryDirectory() as d:
        full = os.path.join(d, "qwen_image_edit_2511_fp8mixed.safetensors")
        with open(full, "wb") as f:
            f.write(b"\0" * 1000)
        os.utime(full, (1_700_000_000, 1_700_000_000))
        assert models.weight_available(full, expected_bytes=1000) is True, (
            "a complete weight with live mtime and full size must be available")
        assert models.weight_available(full) is True, (
            "complete weight without expected_bytes still passes epoch check")

        # 26% of source size — the live gamingpc shape. Live mtime (so epoch
        # alone cannot catch it); size against source is the gate.
        short = os.path.join(d, "short.safetensors")
        with open(short, "wb") as f:
            f.write(b"\0" * 260)
        os.utime(short, (1_700_000_000, 1_700_000_000))
        assert models.weight_available(short, expected_bytes=1000) is False, (
            "a 26%-sized weight with live mtime reported available")

        # rsync --partial interrupted: real size, epoch mtime.
        epoch = os.path.join(d, "epoch.safetensors")
        with open(epoch, "wb") as f:
            f.write(b"\0" * 1000)
        os.utime(epoch, (0, 0))
        assert models.weight_available(epoch, expected_bytes=1000) is False, (
            "epoch-mtime weight reported available")
        assert models.weight_available(epoch) is False, (
            "epoch mtime alone must mean truncated")


def test_t9_13b_staging_path_reads_catalog_companions():
    """T9-13b: staging a model stages its companions from CATALOG, not a list.

    A box with the UNET and VAE but no text encoder reports available and
    fails at load — same failure as T9-13a by another route. The gap is the
    path: ~/stage_gamingpc.sh hardcoding four files is not this criterion.

    Mutation: empty CATALOG.companions while the primary still stages → red
    if the path still returns the remembered companions.
    Mutation: staging_files returns only the primary → red on the companion
    membership half.
    One variable: the path reads CATALOG.companions.
    """
    key = "qwen_image_edit_2511"
    primary = models.CATALOG[key]["file"]
    companions = list(models.CATALOG[key]["companions"])
    assert companions, "fixture needs real companions so a primary-only path fails"
    assert callable(getattr(models, "staging_files", None)), (
        "models.staging_files is the staging path; a shell list is not T9-13b")

    got = models.staging_files(key)
    assert primary in got, f"primary weight missing from stage set: {got}"
    for name in companions:
        assert name in got, (
            f"companion {name!r} was not staged with {key}; path is not "
            f"reading CATALOG.companions: {got}")
    assert got[0] == primary, "primary weight must lead the stage set"

    was = models.CATALOG[key]["companions"]
    try:
        models.CATALOG[key]["companions"] = {
            "only_for_t9_13b.safetensors": "CLIPLoader",
        }
        live = models.staging_files(key)
        assert "only_for_t9_13b.safetensors" in live, (
            "staging path ignored a live CATALOG.companions change")
        assert companions[0] not in live, (
            "staging path still carries a remembered companion after "
            "CATALOG.companions changed — hardcoded list, not a catalog read")
        assert primary in live
    finally:
        models.CATALOG[key]["companions"] = was


# T9-16. Defaults keep secrets outside the tree; the encrypted store feeds
# fleet_watch.notify; status() names provenance without rendering the value.
# Absence alone is one-sided (TRD-9 §9) — a studio with no credential feature
# would pass "nothing in the repo". The positive half is the alert path.
_REPO_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))


def _t9_16_outside_repo(path):
    if not path:
        return True
    real = os.path.realpath(os.path.expanduser(path))
    return not (real == _REPO_ROOT or real.startswith(_REPO_ROOT + os.sep))


def test_t9_16_store_credential_usable_by_alert_with_provenance():
    """T9-16: no credential in the repo; store names source; alert path uses it.

    One-sided trap (TRD-9 §9): absence alone passes with no credential feature.
    Positive half: a credential loaded from the store is usable by the alert
    path, and its provenance is recorded.
    """
    # Defaults must not land under the git tree — a .env next to studio/ is one
    # `git add -A` from the remote.
    assert _t9_16_outside_repo(creds.KEY_PATH), (
        f"cred key defaults inside the repo: {creds.KEY_PATH}")
    assert _t9_16_outside_repo(creds.ENV_FILE), (
        f"ENV_FILE defaults inside the repo: {creds.ENV_FILE}")
    for name, p in creds.PROVIDERS.items():
        assert _t9_16_outside_repo(p.get("file")), (
            f"provider {name} file defaults inside the repo: {p.get('file')}")

    secret = "https://hooks.example.test/services/T9-16-STORE-ONLY"
    was_db = (db.DATA, db.DB_PATH, creds.KEY_PATH, creds.ENV_FILE)
    was_files = {n: dict(p) for n, p in creds.PROVIDERS.items()}
    was_env = {p["env"]: os.environ.pop(p["env"], None)
               for p in creds.PROVIDERS.values()}
    data = tempfile.mkdtemp(prefix="t916_")
    db.DATA = data
    db.DB_PATH = os.path.join(data, "t.db")
    db._local.__dict__.clear()
    creds.KEY_PATH = os.path.join(tempfile.mkdtemp(prefix="t916key_"), "cred.key")
    creds.ENV_FILE = os.path.join(data, "no-such.env")
    for p in creds.PROVIDERS.values():
        p["file"] = ""
    posted = []

    class _Ok:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"ok"

    def _urlopen(req, timeout=None):
        posted.append(getattr(req, "full_url", None) or req.get_full_url())
        return _Ok()

    was_urlopen = urllib.request.urlopen
    try:
        try:
            creds.put("slack_webhook", secret)
        except creds.Unavailable:
            pytest.skip("cryptography not installed; storing is refused by design")

        assert creds.get("slack_webhook") == secret, (
            "store did not round-trip the alert credential")
        with open(db.DB_PATH, "rb") as f:
            assert secret.encode() not in f.read(), (
                "the secret is recoverable from the sqlite file")

        st = {s["name"]: s for s in creds.status()}["slack_webhook"]
        assert st["set"] is True and st["stored"] is True, st
        assert "stored" in st["source"].lower() and "encrypt" in st["source"].lower(), (
            f"provenance not named: {st['source']!r}")
        assert secret not in st["source"] and secret not in str(st), (
            "status rendered the credential value")

        # Positive half: fleet_watch.notify(webhook=None) reads the store.
        urllib.request.urlopen = _urlopen
        assert fleet_watch.notify(["T9-16 store alert"], webhook=None) is True
        assert posted == [secret], (
            f"alert path did not use the store-loaded webhook: {posted}")
    finally:
        urllib.request.urlopen = was_urlopen
        db.DATA, db.DB_PATH, creds.KEY_PATH, creds.ENV_FILE = was_db
        db._local.__dict__.clear()
        for n, p in was_files.items():
            creds.PROVIDERS[n].update(p)
        for env, val in was_env.items():
            if val is None:
                os.environ.pop(env, None)
            else:
                os.environ[env] = val
def test_t9_14_render_refused_when_other_tenant_holds_card_and_starts_when_free():
    """T9-14: shared-card pressure from ollama refuses the render, naming the tenant.

    Positive half (TRD-9 §9): with the card free, the same render starts.
    Measured failure: ollama pins ~22 GB; unload can clear /api/ps while free
    VRAM stays low — the refusal must still name ollama, not only free GB.
    Asserted through _submit_and_collect so submit is not started on refuse.
    Mutations that must go red: always refuse; refuse without naming ollama;
    start submit on the pressure path.
    """
    GB = pipeline.gpu.GB
    card = {"free": 8.0, "models": [], "returns": 0.0, "pending": 0}
    submitted = []

    def _g(url, timeout=5):
        if url.endswith("/system_stats"):
            return {"devices": [{"vram_free": int(card["free"] * GB),
                                 "vram_total": int(24 * GB)}]}
        if card["pending"] > 0:
            card["pending"] -= 1
            if card["pending"] == 0:
                card["models"] = []
                card["free"] += card["returns"]
        return {"models": list(card["models"])}

    def _p(url, payload, timeout=30):
        card["pending"] = 3
        return b""

    was = (
        pipeline.RENDER_BACKEND, pipeline.submit_dir, pipeline.submit_swarm,
        pipeline.submitted_prefixes, pipeline.collect, pipeline._stamp,
        pipeline.gpu._get, pipeline.gpu._post,
    )
    pipeline.gpu._get, pipeline.gpu._post = _g, _p
    pipeline.RENDER_BACKEND = "comfy"
    pipeline.submitted_prefixes = lambda d: set()
    pipeline.collect = lambda *a, **k: []
    pipeline._stamp = lambda *a, **k: None
    pipeline.submit_swarm = lambda *a, **k: []
    pipeline.submit_dir = lambda *a, **k: submitted.append("comfy")

    try:
        with tempfile.TemporaryDirectory() as d:
            # pressure: ollama held 21.9 GB; unload clears /api/ps; free stays 0.25
            card.update(
                free=0.25, returns=0.0, pending=0,
                models=[{"model": "qwen3.6:27b",
                         "size_vram": int(21.9 * GB),
                         "expires_at": "2026-08-12T21:40:00Z"}],
            )
            submitted.clear()
            try:
                pipeline._submit_and_collect(d, "x", "*.png", lambda m: None)
                raise AssertionError(
                    "render started while the other tenant held the card")
            except RuntimeError as e:
                msg = str(e)
                assert "ollama" in msg.lower(), (
                    f"refusal did not name the other tenant: {msg}")
                assert "0.2" in msg or "0.25" in msg or "free" in msg.lower(), msg
            assert submitted == [], (
                f"submit ran on shared-card pressure: {submitted}")

            # positive half: same path, card free → render starts
            card.update(free=8.0, returns=0.0, pending=0, models=[])
            submitted.clear()
            pipeline._submit_and_collect(d, "x", "*.png", lambda m: None)
            assert submitted == ["comfy"], (
                f"free card did not start the render: {submitted}")
    finally:
        (pipeline.RENDER_BACKEND, pipeline.submit_dir, pipeline.submit_swarm,
         pipeline.submitted_prefixes, pipeline.collect, pipeline._stamp,
         pipeline.gpu._get, pipeline.gpu._post) = was
# T9-17. once() already catches a dead webhook so watching continues; without
# a check, deleting the degrade path (or only alerting when notify succeeds)
# stays green. Unreachable must leave a durable state change and must not be
# quiet; reachable must deliver the alert lines.


def test_t9_17_unreachable_transport_records_state_change_reachable_arrives():
    """T9-17: unreachable alert transport degrades to a recorded state change.

    Never silence: the transition is written to the state file and the failure
    is observable. Positive half (TRD-9 §9): with the transport reachable the
    alert arrives. Mutations that must go red: save state only after a successful
    notify; swallow the transition with no record; delete the notify path so a
    reachable transport never delivers.
    """
    up = {"h": {"label": "box", "up": True, "detail": "ok",
                "running": 0, "pending": 0}}
    down = {"h": {"label": "box", "up": False, "detail": "URLError",
                  "running": None, "pending": None}}

    was_scan, was_notify = fleet_watch.scan, fleet_watch.notify
    try:
        # --- unreachable transport: notify raises, state change still recorded
        readings = [up, down]
        idx = {"i": 0}

        def fake_scan(fleet=None):
            r = readings[min(idx["i"], len(readings) - 1)]
            idx["i"] += 1
            return r

        def dead_notify(lines, webhook=None):
            raise urllib.error.URLError("timed out")

        fleet_watch.scan = fake_scan
        fleet_watch.notify = dead_notify
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            err = io.StringIO()
            with redirect_stderr(err):
                # seed (first reading is never an alert)
                fleet_watch.once(
                    state_path=path, webhook="http://example/hook", quiet=True)
                now, changed = fleet_watch.once(
                    state_path=path, webhook="http://example/hook", quiet=True)
            assert changed and changed[0][2] is False, (
                f"down edge missing after unreachable transport: {changed}")
            saved = fleet_watch.load_state(path)
            assert saved.get("h", {}).get("up") is False, (
                f"unreachable transport silenced the state change: {saved}")
            # durable undelivered record — stderr alone is not a recorded state
            alert = saved.get(fleet_watch.ALERT_KEY)
            assert isinstance(alert, dict) and alert.get("delivered") is False, (
                f"unreachable transport left no undelivered record: {saved}")
            assert alert.get("lines"), (
                f"undelivered record dropped the alert lines: {alert}")
            assert any("OFFLINE" in line for line in alert["lines"])
            assert "alert FAILED" in err.getvalue(), (
                f"unreachable transport was quiet on stderr: {err.getvalue()!r}")

        # --- reachable transport: the alert arrives
        alerts = []
        readings = [up, down]
        idx["i"] = 0
        fleet_watch.notify = (
            lambda lines, webhook=None: alerts.append(list(lines)) or True)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            fleet_watch.once(
                state_path=path, webhook="http://example/hook", quiet=True)
            fleet_watch.once(
                state_path=path, webhook="http://example/hook", quiet=True)
            saved = fleet_watch.load_state(path)
            assert len(alerts) == 1, (
                f"reachable transport delivered {len(alerts)} alerts, want 1")
            assert any("OFFLINE" in line for line in alerts[0]), alerts[0]
            alert = saved.get(fleet_watch.ALERT_KEY)
            assert isinstance(alert, dict) and alert.get("delivered") is True, (
                f"successful delivery was not recorded: {saved}")
    finally:
        fleet_watch.scan, fleet_watch.notify = was_scan, was_notify