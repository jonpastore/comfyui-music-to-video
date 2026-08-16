#!/usr/bin/env python3
"""Apply a prompt to images, one output each. Driven by a config file or flags.

The storyboard scripts (build_refs.py, make_anchor.py) are the same model and
the same graph, but their unit of work is a scene or a character sheet. This
one's unit is a FILE: point it at images, give it a prompt, get edited images
back. Nothing else here is new -- the workflow comes from build_refs.workflow()
and the submission from studio/pipeline.py, so the guardrail, the reference
handling and the Comfy staging are the same ones every other path uses.

WHY A CONFIG FILE. A batch applies ONE prompt, but a set of images rarely wants
one: a pose directive has to name THAT image's pose, and it has to come first or
it is ignored mid-prompt. Measured on this fleet 2026-08-15: a shared prompt
saying "the same pose as image 1" held the pose in 1 render of 4, while naming
the pose in the leading clause held it in 4 of 4. That is a per-job value, and
the alternative to a config file is editing this script for every set of images
-- so `jobs` is a list, each entry overriding whatever it needs, and the shared
prose lives once in `defaults.prompt` with {placeholders} the jobs fill in.

Unlike its siblings this DOES render. They stop at writing workflow JSON
because the studio submits for them; a CLI batch has no studio, so --wf-only
is how you get the old contract back.

usage:
  batch_edit.py --config config.json            # a whole job set
  batch_edit.py --config config.json --only back.jpg --debug
  batch_edit.py --input ~/pics --prompt "..."   # one-off, no config
"""
import argparse, glob, json, os, random, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# The studio package is `studio/` in a checkout and `../app` on the deployed
# box (deploy.sh puts the scripts in ~/meowp-studio/scripts and the app beside
# them). Find it rather than assume, or this runs in the repo and not where the
# renders actually happen.
for _cand in (os.environ.get("STUDIO_APP"), os.path.join(HERE, "studio"),
              os.path.join(os.path.dirname(HERE), "app")):
    if _cand and os.path.isfile(os.path.join(_cand, "pipeline.py")):
        sys.path.insert(0, _cand)
        break
import build_refs  # noqa: E402
import guardrail   # noqa: E402

# Every value this script used to hardcode. A config's `defaults` block and the
# CLI flags both start from here, so there is one statement of what the default
# IS rather than one per entry point. Anything absent from a job falls back
# through defaults to this.
DEFAULTS = {
    "input": "",            # image file, or a directory of images
    "prompt": "",
    "refs": [],             # extra conditioning images, held constant
    "outdir": "",           # "" -> <input dir>/out
    "n": 1,
    "seed": None,           # None -> random base
    "tier": "",             # a studio tier name; resolved to its wording
    "guardrail": "",        # literal wording, if you are not using a tier
    "negative": "",
    "mode": "fast",
    "latent": "image",
    "width": 896,
    "height": 1216,
    "denoise": None,        # None -> whatever `mode` says
    "steps": None,
    "cfg": None,
    "sampler_name": None,
    "scheduler": None,
    "lora_strength": None,
    "ref_method": None,
    "backend": None,        # None -> RENDER_BACKEND from the environment
    "pin": None,            # swarm backend id to render on; None -> the normal walk
    # Below here: things that were literals in the code. Rarely worth changing,
    # but a config that cannot express them is a config you end up editing code
    # around.
    "exts": [".png", ".jpg", ".jpeg", ".webp"],
    "run_prefix": "batch_",  # ComfyUI output subdirectory, + outdir name + seed
    "pattern": "*.png",      # what SaveImage writes, and so what to collect
    "seed_stride": 137,      # between variants of one image
    "seed_span": 1000,       # between images, in strides -- keeps runs apart
}


def load_config(path):
    """-> (jobs, env). Each job is a fully merged dict, ready to render.

    `env` is applied to os.environ BEFORE studio/pipeline.py is imported,
    because that module reads COMFY_URL / RENDER_BACKEND / SWARM_* at import
    time into module globals. Setting them afterwards would look like it worked
    and change nothing.
    """
    cfg = json.load(open(path))
    # Paths are relative to the CONFIG, not to the shell's cwd. A config names
    # the images beside it, and it is run from the repo in a checkout and from
    # ~/meowp-studio/scripts on the render box -- resolving against cwd means
    # the same file is correct in one and silently empty in the other.
    root = os.path.dirname(os.path.abspath(path))
    def _at(p):
        return p if not p or os.path.isabs(p) else os.path.normpath(os.path.join(root, p))

    defaults = {**DEFAULTS, **(cfg.get("defaults") or {})}
    jobs = []
    for job in cfg.get("jobs") or []:
        merged = {**defaults, **job}
        merged["input"] = _at(merged["input"])
        merged["outdir"] = _at(merged["outdir"])
        refs = merged["refs"]
        merged["refs"] = [_at(r) for r in
                          (refs if isinstance(refs, list)
                           else [x.strip() for x in refs.split(",") if x.strip()])]
        # The shared prose lives once in defaults.prompt; a job fills its
        # {placeholders} from its OWN keys. A missing one is an error rather
        # than a silently empty clause -- that clause is usually the pose
        # directive, and losing it is exactly the failure this file documents.
        if "{" in merged["prompt"]:
            try:
                merged["prompt"] = merged["prompt"].format(**merged)
            except KeyError as e:
                sys.exit(f"{path}: job {job.get('input','?')} has no value for {e} "
                         f"used by defaults.prompt")
        jobs.append(merged)
    if not jobs:
        sys.exit(f"{path}: no jobs")
    return jobs, cfg.get("env") or {}


def images_in(path, exts):
    if os.path.isfile(path):
        return [path]
    return [p for p in sorted(glob.glob(os.path.join(path, "*")))
            if p.lower().endswith(tuple(exts)) and os.path.isfile(p)]


def build(src_name, prompt, seed, job, settings, save_prefix, refs=()):
    """One source image -> one workflow. The image is image1 (identity), the
    same slot the anchor occupies in build_refs -- for an edit that IS the
    subject. latent=image encodes it too, so the output inherits its size.

    refs: up to two MORE conditioning images (a style, an outfit, a second
    character). Three total is the model's ceiling, not ours -- see
    build_refs.MAX_REF_IMAGES; anything past it is dropped there, loudly.
    name=None so they are not asserted into the prompt as separate people."""
    scene = {"image_prompt": prompt, "negative_prompt": job["negative"].strip()}
    wf = build_refs.workflow(scene, src_name, None, job["latent"],
                             job["width"], job["height"], seed, "", job["guardrail"],
                             extra_refs=[(None, r, "") for r in refs],
                             settings=settings, ref_method=job["ref_method"])
    wf["18"] = {"class_type": "SaveImage",
                "inputs": {"images": ["17", 0], "filename_prefix": save_prefix}}
    return wf


def resolve_guardrail(job):
    """A tier NAME is the useful thing to put in a config; the wording is what
    the prompt needs. Resolved here so a config never carries a stale copy of
    wording the studio owns -- and an unknown tier stops the run rather than
    rendering an adult prompt with no tier wording at all."""
    if not job["tier"]:
        return job["guardrail"]
    try:
        import tiers
    except ImportError:
        sys.exit(f"tier {job['tier']!r} asked for, but the studio package is not "
                 f"importable here -- set STUDIO_APP, or use \"guardrail\" instead")
    try:
        # tier_text, not BUILTIN: the tiers TABLE is the studio-wide definition,
        # so a tier someone added or re-worded in the UI resolves here too. The
        # pinned clause is welded on later by build_refs.workflow either way.
        return tiers.tier_text(job["tier"])
    except Exception as e:                            # noqa: BLE001 -- no db in a checkout
        wording = (tiers.BUILTIN.get(job["tier"]) or (None,))[0]
        if not wording:
            sys.exit(f"unknown tier {job['tier']!r} ({e}); "
                     f"built-ins: {', '.join(tiers.BUILTIN)}")
        return wording


def render(job, pipeline, debug=False, wf_only=False):
    """One job: every image it names, n variants each, submitted as one set."""
    srcs = images_in(job["input"], job["exts"])
    if not srcs:
        print(f"no images in {job['input']}", file=sys.stderr)
        return []
    outdir = job["outdir"] or os.path.join(
        job["input"] if os.path.isdir(job["input"]) else os.path.dirname(job["input"]) or ".",
        "out")
    os.makedirs(outdir, exist_ok=True)

    over = {k: job[k] for k in ("denoise", "steps", "cfg", "sampler_name",
                                "scheduler", "lora_strength") if job[k] is not None}
    settings = build_refs.sampler_settings(job["mode"], **over)
    # Random base unless pinned: an identical workflow is a CACHE HIT in ComfyUI,
    # which returns the cached node output, never re-runs SaveImage, and still
    # reports success -- the job looks done and no file appears (make_anchor.py
    # carries the same note). The seed is in the filename for the same reason.
    base = job["seed"] if job["seed"] is not None else random.randrange(1, 2**31 - 1)
    run = job["run_prefix"] + os.path.basename(os.path.abspath(outdir)) + f"_{base}"

    refs = list(job["refs"])
    if len(refs) > build_refs.MAX_REF_IMAGES - 1:
        # Dropped HERE rather than by assign_ref_slots, because a silent drop is
        # the failure where you supply four and are told nothing.
        print(f"{len(refs)} extra refs given; the source occupies image1 so only the "
              f"first {build_refs.MAX_REF_IMAGES - 1} are used", file=sys.stderr)
        refs = refs[:build_refs.MAX_REF_IMAGES - 1]
    ref_names = [os.path.basename(r) if wf_only else pipeline.install_input(r) for r in refs]

    # Workflows are written to a directory and submitted as a SET, which is what
    # every other caller does -- _submit_and_collect is the only place that knows
    # whether this fleet renders through ComfyUI or SwarmUI, and it also does the
    # VRAM preflight, the stamping of which box produced each file, and the
    # cleanup of what a stopped run managed to write. Submitting per-image here
    # would be a fourth private copy of all of that, and a wrong one on swarm:
    # a render on another box never touches this filesystem, so there would be
    # nothing to collect.
    wf_dir = outdir if wf_only else tempfile.mkdtemp(prefix="batch_edit_")
    for i, src in enumerate(srcs):
        stem = os.path.splitext(os.path.basename(src))[0]
        name = os.path.basename(src) if wf_only else pipeline.install_input(src)
        for k in range(job["n"]):
            seed = base + (i * job["seed_span"] + k) * job["seed_stride"]
            tag = f"{stem}_s{seed}"
            wf = build(name, job["prompt"].strip(), seed, job, settings,
                       f"{run}/{tag}", ref_names)
            if debug:
                # Read off the built workflow, not re-derived -- a second copy of
                # the assembly would be free to disagree with what is submitted.
                enc = wf["11"]["inputs"]
                print(f"--- {tag}")
                for slot in sorted(k2 for k2 in enc if k2.startswith("image")):
                    print(f"  {slot}: {wf[wf[enc[slot][0]]['inputs']['image'][0]]['inputs']['image']}")
                print(f"  positive: {enc['prompt']}")
                print(f"  negative: {wf['12']['inputs']['prompt'] or '(none -- inert at cfg 1.0)'}")
                print(f"  settings: {settings}, latent={job['latent']}")
            json.dump(wf, open(os.path.join(wf_dir, f"{tag}.json"), "w"))

    count = len(srcs) * job["n"]
    if wf_only:
        print(f"{count} workflows -> {outdir}")
        return []
    print(f"submitting {count} via {pipeline.RENDER_BACKEND}", flush=True)
    try:
        got = pipeline._submit_and_collect(wf_dir, run, job["pattern"], print)
    finally:
        shutil.rmtree(wf_dir, ignore_errors=True)
    for p in got:
        shutil.copy2(p, os.path.join(outdir, os.path.basename(p)))
    print(f"{len(got)} images -> {outdir}")
    return got


def _selfcheck():
    job = {**DEFAULTS, "negative": "", "latent": "image", "guardrail": ""}
    wf = build("src.png", "a cat", 7, job, build_refs.sampler_settings("fast"), "run/src_s7")
    assert wf["7"]["inputs"]["image"] == "src.png", "source not attached as image1"
    assert wf["15"]["class_type"] == "VAEEncode", "latent=image must encode the source"
    assert guardrail.PINNED.strip() in wf["11"]["inputs"]["prompt"], "guardrail not applied"
    assert wf["18"]["inputs"]["filename_prefix"] == "run/src_s7"
    # three total: source + two extras, in slots 1/2/3
    enc = build("src.png", "a cat", 7, job, build_refs.sampler_settings("fast"),
                "p", ["b.png", "c.png"])["11"]["inputs"]
    assert [k for k in enc if k.startswith("image")] == ["image1", "image2", "image3"], enc

    # a config's jobs inherit defaults and fill the shared prompt's placeholders
    import tempfile as _t
    p = os.path.join(_t.mkdtemp(), "c.json")
    json.dump({"defaults": {"prompt": "{pose} then the shared part.", "n": 3},
               "jobs": [{"input": "a.png", "pose": "Seated,"},
                        {"input": "b.png", "pose": "Standing,", "n": 1}]}, open(p, "w"))
    jobs, env = load_config(p)
    assert jobs[0]["prompt"] == "Seated, then the shared part.", jobs[0]["prompt"]
    assert jobs[0]["n"] == 3 and jobs[1]["n"] == 1, "job must override defaults"
    assert jobs[1]["latent"] == "image", "unset keys must fall back to DEFAULTS"
    # paths resolve against the CONFIG's directory, not the cwd
    assert jobs[0]["input"] == os.path.join(os.path.dirname(p), "a.png"), jobs[0]["input"]
    assert jobs[0]["refs"] == [], "a config with no refs must still give a list"
    print("selfcheck ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="job set as JSON; see config.json.example. "
                                     "Supersedes the per-job flags below")
    ap.add_argument("--only", default="", help="with --config: run just the jobs whose "
                                               "input contains this substring")
    ap.add_argument("--input", help="image file, or directory of images")
    ap.add_argument("--prompt", default=DEFAULTS["prompt"])
    ap.add_argument("--outdir", help="default: <input dir>/out")
    ap.add_argument("--refs", default="", help="comma-separated extra reference images "
                    "held constant across the batch (style/outfit/second character). "
                    f"The source is image1, so at most {build_refs.MAX_REF_IMAGES - 1}")
    ap.add_argument("--n", type=int, default=DEFAULTS["n"], help="variants per image")
    ap.add_argument("--seed", type=int, default=DEFAULTS["seed"], help="base seed; random if unset")
    ap.add_argument("--tier", default=DEFAULTS["tier"], help="studio tier name, e.g. r")
    ap.add_argument("--guardrail", default=DEFAULTS["guardrail"],
                    help="literal tier wording; PINNED is added regardless")
    ap.add_argument("--negative", default=DEFAULTS["negative"],
                    help="inert at cfg 1.0 -- needs --mode quality")
    ap.add_argument("--mode", choices=("fast", "quality"), default=DEFAULTS["mode"])
    ap.add_argument("--latent", choices=("image", "empty"), default=DEFAULTS["latent"],
                    help="image: edit in place, output inherits source size. "
                         "empty: --width/--height instead")
    ap.add_argument("--width", type=int, default=DEFAULTS["width"])
    ap.add_argument("--height", type=int, default=DEFAULTS["height"])
    ap.add_argument("--denoise", type=float, default=DEFAULTS["denoise"])
    ap.add_argument("--steps", type=int, default=DEFAULTS["steps"])
    ap.add_argument("--cfg", type=float, default=DEFAULTS["cfg"])
    ap.add_argument("--sampler", dest="sampler_name", default=DEFAULTS["sampler_name"],
                    choices=list(build_refs.SAMPLERS))
    ap.add_argument("--scheduler", default=DEFAULTS["scheduler"], choices=list(build_refs.SCHEDULERS))
    ap.add_argument("--lora-strength", dest="lora_strength", type=float,
                    default=DEFAULTS["lora_strength"])
    ap.add_argument("--ref-method", dest="ref_method", default=DEFAULTS["ref_method"],
                    choices=list(build_refs.REF_METHODS))
    ap.add_argument("--backend", choices=("comfy", "swarm"), default=DEFAULTS["backend"],
                    help="comfy: render on COMFY_URL alone. swarm: SwarmUI picks a "
                         "backend across the fleet. Default: RENDER_BACKEND from the "
                         "environment, as the studio sets it")
    ap.add_argument("--pin", default=DEFAULTS["pin"],
                    help="swarm backend id to render on, skipping the fallback walk. "
                         "Run one process per backend to use more than one box at once")
    ap.add_argument("--wf-only", action="store_true", help="write workflow JSON, render nothing")
    ap.add_argument("--debug", action="store_true", help="print the FINAL assembled positive "
                    "prompt (yours + the anti-duplicate clause + tier + PINNED) and the "
                    "reference slots, as the model receives them")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()
    if args.selfcheck:
        return _selfcheck()

    if args.config:
        jobs, env = load_config(args.config)
        if args.only:
            jobs = [j for j in jobs if args.only in str(j["input"])]
            if not jobs:
                sys.exit(f"--only {args.only!r} matched no job in {args.config}")
    else:
        if not args.input or not args.prompt.strip():
            ap.error("--input and --prompt are required (or use --config)")
        one = {**DEFAULTS, **{k: v for k, v in vars(args).items() if k in DEFAULTS}}
        # --refs is one comma-separated string; a config gives a list. Normalise
        # here so everything downstream -- including the existence check below --
        # sees a list and never iterates a string one character at a time.
        one["refs"] = [r.strip() for r in args.refs.split(",") if r.strip()]
        jobs, env = [one], {}

    # BEFORE importing pipeline: it reads these at import time into module
    # globals, so a later assignment would be ignored. os.environ wins over the
    # config, so a shell export can still override a checked-in file.
    for k, v in env.items():
        os.environ.setdefault(k, str(v))

    pipeline = None
    if not args.wf_only:
        import pipeline  # noqa: F811  -- imports db/gpu; skipped in --wf-only
        backend = next((j["backend"] for j in jobs if j["backend"]), None)
        if backend:
            pipeline.RENDER_BACKEND = backend
        # --pin is a RUN-level flag, like --debug and --only: it says which box
        # this process drives, which is a property of the process and not of the
        # job set. It therefore wins over the config rather than being ignored
        # by it, the way the per-job flags are.
        pin = args.pin if args.pin is not None else \
            next((j["pin"] for j in jobs if j["pin"] is not None), None)
        if pin is not None:
            # ONE backend, chosen here, instead of pipeline._attempt_plan's walk.
            #
            # Why this exists: the walk offers SwarmUI's free draw only when
            # every registered backend is running, and pins running backends in
            # id order otherwise. With one box registered-but-idle the free draw
            # is skipped and every workflow lands on backend 0 -- measured, all
            # 32 renders of the v3 set stamped backend 0 while a second 5090 sat
            # idle. Pinning lets N processes each drive a different box, which
            # is the only way to get more than one render in flight: submission
            # waits for each workflow to finish.
            #
            # The cost is the fallback: a pinned plan has one entry, so a
            # backend that refuses fails the job instead of moving on. Only pin
            # boxes you have checked hold the model.
            # *_a: _attempt_plan takes the workflow on the DEPLOYED pipeline
            # (_attempt_plan(wf)) and nothing in the checkout. A signature-bound
            # replacement swallowed that argument as its own first parameter, so
            # the plan yielded the workflow dict as the backend id and SwarmUI
            # answered "Invalid value for param Exact Backend ID". Accept and
            # ignore whatever it is called with.
            pipeline._attempt_plan = lambda *_a, **_k: iter([str(pin)])
            print(f"pinned to swarm backend {pin}", flush=True)
        if pipeline.RENDER_BACKEND == "swarm" and not pipeline.SWARM_INPUT_DIRS:
            # SwarmUI has no upload API, so a reference image reaching another
            # box is a filesystem problem (deploy.sh's SWARM_INPUT_DIRS). Unset,
            # the refs exist on THIS box only -- and Swarm picks the backend, so
            # the render lands wherever it likes and LoadImage fails there.
            print("SWARM_INPUT_DIRS is unset: reference images are staged to this box "
                  "only, so a job routed to another backend will fail to load them. "
                  "Set it in the config's env block (see studio/deploy.sh).",
                  file=sys.stderr)

    # Up front, for the WHOLE set. A missing file used to surface as one line on
    # stderr per job while the run carried on -- so a mistyped directory spent
    # the GPU on nothing and still looked like it had worked.
    missing = sorted({p for j in jobs for p in [j["input"], *j["refs"]]
                      if p and not os.path.exists(p)})
    if missing:
        sys.exit("these inputs do not exist:\n  " + "\n  ".join(missing) +
                 (f"\n(paths in a config are relative to {os.path.dirname(os.path.abspath(args.config))})"
                  if args.config else ""))

    made, failed = 0, []
    for i, job in enumerate(jobs, 1):
        job["guardrail"] = resolve_guardrail(job)
        print(f"=== [{i}/{len(jobs)}] {job['input']}", flush=True)
        try:
            # One job must not take the rest of the set down with it: these run
            # for tens of minutes and a refusal on job 3 should not throw away
            # jobs 4-8, which are still renderable.
            made += len(render(job, pipeline, args.debug, args.wf_only))
        except Exception as e:                        # noqa: BLE001 -- see above
            print(f"FAILED {job['input']}: {e}", file=sys.stderr)
            failed.append(job["input"])
    if failed:
        print(f"{len(failed)} of {len(jobs)} jobs failed: {', '.join(map(str, failed))}",
              file=sys.stderr)
    if not args.wf_only:
        print(f"{made} images from {len(jobs)} job(s)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
