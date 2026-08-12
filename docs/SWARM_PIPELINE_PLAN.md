# Routing the studio through SwarmUI — plan

> **PENDING APPROVAL. Nothing here is built.** Written for another session to
> execute. Every claim about SwarmUI below was read from its source on
> `cerberus-ai:~/SwarmUI` (v0.9.8.2), not recalled; every claim about the studio
> is from this checkout. What is *not* verified is marked, and phase 0 exists to
> settle exactly those things before any of the rest is written.

SwarmUI is installed on cerberus and running headless on `0.0.0.0:7801`, with one
backend — `comfyui_api` pointed at the existing `comfyui.service` on `:8188`,
`AllowIdle: true`. Its core node packs are symlinked into
`~/ComfyUI/custom_nodes/` (59 nodes, 14 backend features). The studio does not
know it exists.

The point of doing this at all is **more than one GPU box**. On one box, talking
to ComfyUI directly is simpler and strictly better, and this plan should not be
started for its own sake. It is worth doing the moment a second backend is real.

---

## The one thing that makes this small

**Every piece of ComfyUI coupling in `pipeline.py` already sits behind five
functions**, and `pipeline.demo()` already monkeypatches four of them:

| Function | What it assumes |
|---|---|
| `_post` / `_get` (`:56`, `:71`) | one HTTP endpoint |
| `submit_dir` (`:135`) | `POST /prompt`, poll `/history/<id>` |
| `collect` (`:183`) | outputs are files under `COMFY_OUTPUT`, **a local path** |
| `install_input` (`:79`) | inputs are files copied into `COMFY_INPUT`, **a local path** |

The seven `gen_*` wrappers above them — `gen_anchor`, `gen_refs`, `reroll`,
`gen_clips`, `fix_ref`, `gen_artwork`, `stage_refs` — all have the identical
shape: run a CLI script into a temp dir, then `_submit_and_collect(wf_dir,
prefix_dir, pattern, progress)`. **None of them should change.** If this work
ends up editing `gen_refs`, it has gone wrong.

`demo()` at `:435` already replaces `_post`, `_get`, `COMFY_OUTPUT` and
`COMFY_INPUT` against a fake server. That is the seam, it is already load-bearing
for the tests, and this plan widens it rather than inventing one.

---

## What actually breaks with a second box

Not submission. Submission is a URL. These two are the work:

1. **`collect()` globs a local directory.** A render on box 2 lands on box 2's
   disk. `_submit_and_collect` diffs a before/after set of that directory, so on
   a remote backend it returns an empty list and the job silently produces
   nothing — no error, no files. This is the dangerous one: it looks like a
   generation failure rather than a plumbing failure.
2. **`install_input()` copies into a local directory.** `gen_clips` stages
   approved refs by name (`stage_refs`, `:334`) and copies the mp3 in, because
   `build_song.py` references them *by filename inside the workflow*. Box 2
   cannot see them.

There is a third, quieter one: `gen_clips` passes `--ref-motion` and
`--control-video` as **paths**, deliberately not installed into `COMFY_INPUT`
(see the comment at `:354`). Those are read straight off the local filesystem by
`LoadVideosFromFolder`. Nothing about Swarm fixes that; those two features are
single-box until someone shares a filesystem.

---

## Phase 0 — the spike · ~half a day · nothing else starts before it

Four unknowns, each of which changes the shape of everything below. Answer them
with curl against the running Swarm, and write the answers into this document.

1. **Does `comfyworkflowraw` accept our workflows unmodified?** The parameter
   exists (`ComfyUIBackendExtension.cs:188`, and `T2IAPI.AlwaysTopKeys` at `:87`)
   and takes raw workflow text. But `:233` handles keys beginning
   `comfyrawworkflowinput`, which means Swarm **injects its own parameters into
   the workflow** it is given. Our workflows are complete and want nothing
   injected. Establish whether a full API-format workflow round-trips byte-for-
   byte in behaviour, or whether Swarm requires named input nodes. **If it
   rewrites them, the whole approach changes** and the fallback is Swarm as a
   router only, with the studio still speaking ComfyUI's protocol to whichever
   address Swarm names.
2. **Does the raw path work for video?** Every `gen_clips` workflow ends in a
   SaveVideo and yields `*.mp4`. Swarm's generate API is called
   `GenerateText2Image` and returns `images`. The backend advertises a `video`
   feature, so it is plausible — but `gen_clips` is the longest, most expensive
   job in the studio and it must not be the thing that discovers the limitation.
3. **How do inputs reach a backend?** No upload API is registered — the
   `RegisterAPICall` list in `WebAPI/T2IAPI.cs:29-38` has `ListImages`,
   `AddImageToHistory`, `DeleteImage`, and no upload. Yet `View/local/inputs/...`
   is a served path (`T2IAPI.cs:528`). Find the mechanism, or conclude there
   isn't one — which would mean inputs stay a shared-filesystem problem (rsync,
   NFS or a `COMFY_INPUT` per backend) rather than an API problem.
4. **What is `images[].image` in practice?** Documented at `T2IAPI.cs:72` as
   `"View/local/raw/2024-01-02/0304-....png"` — a path to GET from Swarm — but
   "in some cases can be a `data:...` encoded image". Both forms must be handled;
   confirm which one this setup actually returns for our workflows.

**Gate:** phase 1 does not start until 1 and 2 are answered with a real
generation through Swarm, logged. If either answer is "no", stop and re-plan —
do not work around it.

---

### Phase 0 RESULTS — run 2026-08-12, against the live Swarm

**There are two backends now**, which is the precondition this whole plan sets:

    [0] studio ComfyUI (existing service)   127.0.0.1:8188        running, AllowIdle=True
    [1] gamingpc RTX 5090 32GB              100.107.235.105:8188  running, AllowIdle=True

**1. Does `comfyworkflowraw` accept our workflows unmodified? YES.** A real
16-node `make_anchor.py` workflow — LoadImage, TextEncodeQwenImageEditPlus,
FluxKontextMultiReferenceLatentMethod, KSampler, SaveImage — was accepted as-is
and rendered in 17.8s. Nothing was rewritten. The approach is viable.

**4. What is `images[].image`? A PATH**, not a data URI:
`View/local/raw/2026-08-12/0120001--unknown.png`, and a plain GET returns it
(200, valid PNG, 896x1216). Only the path form has been observed here.

**The output lands in BOTH places, and this matters.** ComfyUI still wrote our
own filename into its own output directory (`swarmtest/front_s52862573_00001_.png`,
788836 bytes) while Swarm kept a separate copy under its own naming
(`0120001--unknown.png`, 930525 bytes — not byte-identical). So on a LOCAL
backend today's `collect()` keeps working untouched and the Swarm path is purely
additive. That is only true while the backend is local, which is the whole
problem phase 2 exists to solve — and it confirms the filename mapping there is
required rather than theoretical, because Swarm's name carries none of the
`clip_(\d+)` or seed information that seven wrappers parse out of basenames.

**3. How do inputs reach a backend? There is no upload API.** `UploadImage`
returns HTTP 400 (not registered), confirming the reading of `T2IAPI.cs`. Inputs
are a shared-filesystem problem, not an API one, exactly as feared.

**But that is not the blocker. THE SECOND BACKEND HAS NO MODELS.** Pinning the
same workflow to backend 1 with `exactbackendid` fails in 0.6s:

    backend 1: ComfyUI execution error: Model in folder 'vae' with filename
               'qwen_image_vae.safetensors' not found.
    backend 0: OK in 25.4s

Its VAE list is `['pixel_space']` — the built-in and nothing else — against
cerberus's full Qwen-Image-Edit / LTX-2.3 / ACE-Step set. It is a reachable,
registered, EMPTY ComfyUI.

**So the gate passes on the protocol and fails on the provisioning.** The API
works; there is nothing for it to route to. Phases 1–3 would build a router to a
box that fails every job in 0.6s, and every generation would keep landing on
backend 0 regardless. **The next step is not code.** It is putting the model set
and an input path on the second box — the checkpoints this studio uses, plus
whatever answers question 3 for inputs (rsync, NFS, or a per-backend
`COMFY_INPUT`).

**2. Does the raw path work for video? STILL UNANSWERED.** Deliberately not
attempted: it needs a `gen_clips` workflow, which needs a storyboard and approved
refs, and the answer only changes what phase 2 does on a backend that currently
cannot run anything. Answer it against backend 0 before starting phase 1.

`exactbackendid` (a dropdown T2I parameter) is how a specific backend is
targeted. That is what made this testable, and it is what phase 2's acceptance
criterion should use to prove both paths.

---

## Phase 1 — a backend seam, no behaviour change · 1–2 days

Introduce the abstraction with exactly one implementation: the current one.

- A `RENDER_BACKEND` env var (`comfy` | `swarm`), defaulting to **`comfy`**.
- `submit_dir`, `collect` and `install_input` gain a Swarm sibling each. The
  existing bodies move untouched into the `comfy` branch. Nothing about
  behaviour changes when the var is unset, which is how this ships without a
  flag day.
- `pipeline.demo()` grows a second pass over the Swarm implementations against a
  fake Swarm, in the shape it already uses for the fake ComfyUI at `:438`.

Ships: nothing visible. This is the phase that makes the next one small, and it
is the one to be strict about — if the seam is right, phase 2 is mechanical.

## Phase 2 — the Swarm implementation · 2–3 days

- `submit_swarm(wf_dir)` — for each workflow JSON, `POST /API/GenerateText2Image`
  with `{session_id, images: 1, comfyworkflowraw: <the JSON as text>}`. Sessions
  come from `POST /API/GetNewSession`; cache one and re-request on expiry rather
  than per submit.
- **`collect()` inverts.** Today it discovers files by globbing and the caller
  diffs before/after. Against Swarm the response *names* its outputs, so the
  returned `images[]` is authoritative: GET each `View/...` path (or decode the
  `data:` form) and write it into a local scratch dir under **the same filename
  the current code produces**, because `_clip_records` parses `clip_(\d+)` out of
  basenames at `:242` and the seven wrappers all depend on that.
  `_submit_and_collect`'s before/after diff becomes unnecessary on this path —
  but leave it in place for the comfy path, where it is load-bearing (SaveImage
  bumps a counter suffix and old candidates would otherwise be re-collected).
- `install_input()` per phase 0's answer. If there is no upload API, the honest
  implementation is a per-backend rsync into that box's `COMFY_INPUT`, and it
  belongs here rather than being pretended away.

**Acceptance:** one `gen_anchor` and one `gen_refs --limit 2` produce identical
results under `RENDER_BACKEND=comfy` and `RENDER_BACKEND=swarm`, same filenames,
same DB rows.

## Phase 3 — retry, which is the actual reason to do this · 1 day

Verified in SwarmUI's source, and it is narrower than it sounds:

- `ComfyUIAPIAbstractBackend.cs:295-303` throws `PleaseRedirectException` when
  the websocket **fails to connect** — but only `if (CanIdle)`, and
  `ComfyUIAPIBackend.cs:32` is `CanIdle => Settings.AllowIdle`. That is now true
  on backend 0. `T2IEngine.cs:355-358` handles it with `claim.Extend(gens: 1)`
  and re-runs the task on another backend. **That is a real requeue.**
- `:575-582` — a failure **after** the socket is up sets the backend IDLE and
  rethrows. No redirect, ever. **A drop mid-generation is not requeued by
  SwarmUI.**
- `ComfyUISelfStartBackend.cs:65` hardcodes `CanIdle => false`. Self-start
  backends never redirect at all.

So: lose the VPN between clips and the next clip routes elsewhere; lose it during
a 90-second clip and that clip is gone. A song is 40–80 clips. **`jobs.py` has no
retry of any kind** — the only exception handling is three bare `except Exception`
blocks (`:142`, `:174`, `:204`).

The fix belongs in the studio, not in Swarm, because the studio is the only layer
that knows a clip is one of eighty and that re-running it is safe:

- Retry a **failed clip within a job**, bounded (2 attempts), logging each. Not a
  retry of the whole job: re-running `gen_clips` from scratch after clip 60 fails
  is an hour of GPU to recover ninety seconds of work.
- Only for idempotent kinds. `clips`, `refs`, `reroll`, `anchor` are safe — they
  write new candidate files and pick later. `edit_audio` moves `mp3_path` and is
  not.
- The retry must be visible in the job log. A silent retry that halves throughput
  is worse than a failure, because nobody goes looking.

## Phase 4 — the Jobs page tells the truth about both queues · half a day

`comfy_queue()` (`:113`) exists and its docstring is careful about what it does
and does not know ("attribution is deliberately not attempted"). It gains a
sibling, not a replacement — with two backends there are two answers and
collapsing them into one number re-creates exactly the confusion that function
was written to end.

- `swarm_backends()` → per backend: id, status, title. `POST /API/ListBackends`.
- Show them beside the existing ComfyUI count. A backend in `IDLE` because the
  VPN dropped is the single most useful thing this page could say, and today
  nothing in the studio can say it.

**This phase is independently useful and depends on nothing else here.** If the
second box slips, do this one anyway.

---

## Tests

Matching the house style — `demo()` self-checks, `TestClient` routes in
`test_app.py`, one-place stubs in `conftest.py`, seams in `check_integration.py`.

- **`pipeline.demo()`** — the Swarm submit/collect pair against a fake Swarm, the
  way `:438` already fakes ComfyUI. Assert the filenames written match what the
  comfy path produces, because `_clip_records` parses them.
- **`conftest.py`** — a `swarm` stub recording its calls, in the style of
  `refs_calls` / `anchor_calls`. No test may reach the network.
- **`test_app.py`**
  - `test_render_backend_defaults_to_comfy_when_unset` — the flag-day guard.
  - `test_swarm_and_comfy_collect_the_same_filenames`
  - `test_a_failed_clip_is_retried_once_and_logged`
  - `test_edit_audio_is_never_retried` — the non-idempotent kind, tested rather
    than trusted.
  - `test_jobs_page_reports_both_queues_separately`
- **`check_integration.py`** — `pipeline.submit_swarm` accepts what the job
  handlers pass (the existing `sig()` helper), and the Swarm path refuses to run
  when `RENDER_BACKEND=swarm` but no backend answers. **Failing loudly on an
  unreachable Swarm matters more than usual here**, because the failure mode this
  plan is most likely to ship is an empty result set that looks like a bad render.

---

## What to read, and what to take from each

| Source | Take |
|---|---|
| `studio/pipeline.py:435` `demo()` | The existing fake-ComfyUI harness. The Swarm one is its twin; do not invent a second style of test double. |
| `studio/pipeline.py:168` `_submit_and_collect` | Why the before/after diff exists (SaveImage bumps a counter). Keep it on the comfy path; it is not needed on the Swarm one. |
| `~/SwarmUI/src/WebAPI/T2IAPI.cs:60-170` | `GenerateText2Image` / `...WS` — the request shape and the documented response, including the `data:` caveat at `:72`. |
| `~/SwarmUI/src/BuiltinExtensions/ComfyUIBackend/ComfyUIBackendExtension.cs:87,188,201,233` | How `comfyworkflowraw` is handled, and the `comfyrawworkflowinput` injection that phase 0 question 1 is about. |
| `~/SwarmUI/src/Text2Image/T2IEngine.cs:345-372` | The generation error path, and the only place a requeue happens. |
| `studio/jobs.py` | The single-worker contract. Retry is added *inside* a handler; adding a second worker is not an option this plan opens. |
| `docs/SETS_MIXING_PLAN.md` | The house style for a plan document, and the reminder that phases must each ship something alone. |

---

## Adding a second backend (prerequisite, not part of this work)

None of the phases above are worth starting until a second box exists. Making
one is three steps, and it is not this plan's work — it is recorded here so the
plan is self-contained.

1. **The new box needs Swarm's core node packs**, or it runs degraded exactly as
   cerberus did before they were installed. Symlink both from a SwarmUI checkout
   into that box's `custom_nodes/` and restart its ComfyUI:

       ln -sfn <swarm>/src/BuiltinExtensions/ComfyUIBackend/ExtraNodes/SwarmComfyCommon \
               ~/ComfyUI/custom_nodes/SwarmComfyCommon
       ln -sfn <swarm>/src/BuiltinExtensions/ComfyUIBackend/ExtraNodes/SwarmComfyExtra \
               ~/ComfyUI/custom_nodes/SwarmComfyExtra

   A clean ComfyUI does NOT install what those packs import. They need `cv2`,
   `imageio_ffmpeg` and `OpenGL_accelerate`, and declare `dill`, `rembg`,
   `ultralytics`; without them the backend registers and runs **degraded**, and
   cerberus only works because other custom node packs happened to drag opencv
   in. Install `opencv-python-headless imageio-ffmpeg PyOpenGL-accelerate dill
   rembg ultralytics` alongside them.

   Verify by PARSING the JSON — cerberus reports 59 node types, gamingpc 60, and
   the backend's feature count goes 10 → 14 once they load:

       curl -s <box>:8188/object_info | python3 -c "
       import sys,json; d=json.load(sys.stdin)
       print(len([k for k in d if k.startswith('Swarm')]))"

   **Not `grep -c '\"Swarm'`.** Recent ComfyUI returns `/object_info` as a single
   line, so `grep -c` counts lines and reports `1` for a perfectly healthy
   backend. That produced a wrong diagnosis on gamingpc.
   **Note the symlinks point into the SwarmUI checkout**, so a `git pull` there
   changes the nodes under a renderer without a ComfyUI restart being involved.
   Copies decouple them at the cost of manual sync.

2. **Unlock settings first, or the next step answers `{"error":"Settings are
   locked."}`.** The unit runs SwarmUI with `--lock_settings`, because the
   instance has no authentication and every visitor on the tailnet is therefore
   the `local` admin — without it, anyone opening the page can add backends and
   start model downloads onto the box, which is exactly what the first-run
   wizard did once already. So adding a backend is a deliberate three-step dance:

       # 1. drop --lock_settings from ExecStart
       ssh cerberus-ai 'systemctl --user edit --full swarmui.service'   # or sed it
       ssh cerberus-ai 'systemctl --user daemon-reload && systemctl --user restart swarmui'
       # 2. register the backend (below)
       # 3. put the flag back, daemon-reload, restart

   Note that while locked SwarmUI does **not persist settings changes at all**
   (`Program.cs:694` returns early from `SaveSettingsFile`), so a backend added
   without unlocking would also not survive a restart even if it were accepted.

3. **Register it**, two API calls against `:7801` (`session_id` from
   `POST /API/GetNewSession`):

       POST /API/AddNewBackend  {"type_id": "comfyui_api"}          -> returns id
       POST /API/EditBackend    {"backend_id": <id>, "title": "...",
                                 "settings": {"Address": "http://<box>:8188",
                                              "AllowIdle": true, "OverQueue": 1}}

   `EditBackend` reads its values from a nested `settings` object; a flat body
   answers `{"error":"Missing settings."}`.

4. **`AllowIdle` must be true.** It is not cosmetic — `ComfyUIAPIBackend.cs:32`
   is `CanIdle => Settings.AllowIdle`, and phase 3 explains that this is the flag
   deciding whether a connect failure requeues onto another backend or hard-fails.
   It defaults to false.

## Open questions

1. **Does the studio keep speaking ComfyUI at all?** If phase 0 finds that
   `comfyworkflowraw` rewrites our workflows, the better answer may be to use
   Swarm purely as a **router** — ask it which backend is free, then speak
   ComfyUI's own protocol to that address. That keeps `submit_dir` exactly as it
   is and makes this a much smaller change. Do not decide before phase 0.
2. **Where do inputs live with two boxes?** An API upload, a shared mount, or
   rsync-on-submit. This is a real infrastructure decision and it should be made
   once, deliberately, rather than falling out of whatever phase 2 finds easiest.
3. **`--ref-motion` and `--control-video` stay single-box.** They read local
   paths by design. Either they are box-1-only features, or the shared-filesystem
   answer to question 2 covers them too.
4. **Does `free_vram()` still mean anything?** It POSTs to one ComfyUI
   (`pipeline.py:98`). With two backends, freeing the wrong card is worse than
   not freeing at all — it is a no-op that reads as a mitigation. Either it takes
   a backend, or Swarm's own model management replaces it.
5. **What happens when Swarm and the studio both submit?** The studio serialises
   its own jobs through one worker because the card fits one render. Swarm has
   its own queue and its own idea of how many jobs a backend takes
   (`OverQueue: 1`). Two schedulers over one GPU is the same class of problem
   `comfy_queue()` was written to expose, and it is now ours rather than a
   stranger's on the tailnet.
