# TRD-9 · The fleet and its operational layer

Status: written 2026-08-13. **Absorbs `docs/SWARM_PIPELINE_PLAN.md` *(absorbed and removed 2026-08-13; in git history)* (382 lines)
and `docs/UNRAID_BACKEND_PLAN.md` *(absorbed and removed 2026-08-13; in git history)* (387 lines)**, neither owned by any TRD, plus
`studio/gpu.py`, `studio/fleet_watch.py` and `studio/creds.py` — 811 lines that
no TRD cites.

Acceptance criteria are `T9-n` and each **can fail**. Rules every document
inherits are `TRD-6 §0` (`T6-A1`…`T6-A6`) — cited, never restated.

---

## 1. The problem: this is the most-built and least-specified thing here

Unlike every other TRD, this one covers machinery that **works and is in
production**. Four render backends, per-box model curation, filename
retargeting, a retry walk, input staging, backend alerting and a shared GPU.
Roughly 1,700 lines including both plans, all of it live, and **not one
acceptance criterion anywhere.**

That is the opposite failure from TRD-6, which specifies machinery that does not
exist. Here the machinery exists and nothing states what it promises — so a
change to it cannot be shown to have broken anything, and every fact about it
lives in `SESSIONS.md` notes and code comments.

**This document's job is to pin down what is already true**, so the answer to
"did that refactor change routing?" stops being "run it and see".

## 2. What exists — do not rebuild

| built | where |
|---|---|
| Backend seam: `RENDER_BACKEND` (`comfy` default), one branch point | `pipeline._submit_and_collect` |
| SwarmUI submission, fetch, prefix, attempt plan | `pipeline.submit_swarm`, `_swarm_fetch`, `_wf_prefix`, `_attempt_plan` |
| Per-box filename rewriting before a pinned attempt | `pipeline._retarget`, over `models.ALIASES` |
| Retry walk: one free draw, then each box in turn by `exactbackendid` | `pipeline._attempt_plan` |
| Distinguishing a box that vanished from a workflow a box refused | `pipeline._backend_vanished` (`T6-4` consumes it) |
| Input staging by rsync, `--chmod=F664` | `pipeline.install_input` |
| Per-backend availability, fit, and the spelling each box uses | `models.where()`, `fits()`, `resolve()`, `spellings()` |
| Which box is always on, separately from how fast it is | `models.BACKEND_STABILITY`, keyed by **host** |
| Backend state watching and alerting | `fleet_watch.py` |
| Credential storage and the alert transport | `creds.py` |
| Sharing one card with ollama | `gpu.py` |

## 3. Routing is curation, not scheduling

The decision this fleet is built on, and it was reached by measurement:
**model curation determines where a job *can* succeed; it does not determine
where SwarmUI *sends* it.** Pinned with `exactbackendid`, one box refused an
anchor with `Model in folder 'vae' … not found` and another on a missing LoRA,
both in about a second — and **a validation miss is not requeued by Swarm**;
only a websocket-connect failure is.

- `T9-1` A workflow naming a model under one box's spelling, pinned to a box
  using the other, is **rewritten before submission and renders**. Measured:
  refused as written, **9.7 s once retargeted**. Both directions in one test —
  as-written refuses, retargeted succeeds — or the criterion certifies a
  retargeter that rewrites everything into failure.
- `T9-2` **Retargeting is per loader.** A VAE name can never be resolved out of
  the UNET enum. Asserted by handing a workflow a name that exists in a
  different loader's list and confirming it is not substituted.
- `T9-3` **The free draw goes out byte-identical.** Not equal — *identical* — so
  ComfyUI's execution cache still hits. Asserted by object identity and by
  counting the `ListBackends` calls, because a rebuild of the same JSON reads as
  "untouched" while busting the cache. *This criterion was rewritten once
  already after a mutation audit found it could not fail for the reason it
  named.*
- `T9-4` `models.where()`'s answer is **three-valued and every consumer respects
  it** — `T6-A6` owns the rule; this asserts the fleet's own consumers do.
  Paired positive: a `None` box is still **offered** as a candidate.
- `T9-5` A box that cannot hold a model resident is **sorted to the back, not
  dropped**. Streaming is slow, and slow is not "cannot". A hard exclusion is a
  different decision and would need its own flag.

## 4. What happens when a box goes away

- `T9-6` A job lost to a box that vanished **requeues**; a workflow a box
  **refused** does not. Both arrive under the same *"No backends match the
  settings of the request given"* headline, so **the reason line is the
  discriminator**. `T6-4` states the rule; this asserts it across the real seam.
- `T9-7` **A refused attempt can take a backend out from under the next
  attempt.** Measured: straight after a validation failure, a box answered *"No
  backends match"* for about a minute. So the walk can hit a box Swarm has just
  benched — which is why retargeting, which stops the refusal happening at all,
  is worth more than another retry. Asserted as a behaviour of the walk, not a
  timing test.
- `T9-8` A backend changing state **says something**, once per transition and not
  once per poll. `fleet_watch.py` is the implementation; the criterion is that a
  flapping box does not become a flapping alert.
- `T9-9` **A registered backend holding no models is a hazard, not a
  capability.** Measured: ethan joined with `models/` at 8 KB and SwarmUI's free
  draw would hand it real jobs it must refuse. Curation routes around it only
  *after* a refusal. Staging weights is a prerequisite for registering a backend,
  and the criterion is that registering an empty one is refused or flagged.

## 5. Traps that cost a wrong diagnosis, as criteria

Each of these was diagnosed wrongly once. They are criteria so the next person
does not pay again.

- `T9-10` **A cache hit is not a refusal.** Re-submitting a byte-identical
  workflow makes ComfyUI execute nothing and write no file; through Swarm that
  reads as *"No images were generated (all refused, or failed)"*, and on the
  comfy path as a job that succeeded with an empty result. **Any A/B of the two
  paths uses different seeds** or it measures the cache.
- `T9-11` **SwarmUI caches each backend's node and model list at connect time —
  AND THE SCOPE IS HALF THE CRITERION.** A backend that connected while its
  ComfyUI was still booting refused a render with *"the custom workflow contains
  an unsupported node type 'EmptyImage'"* — a node it plainly had. A node-missing
  refusal must be distinguishable from a stale list.

  **RESCOPED 2026-08-13, and the rescoping is worth more than the original.**
  This hazard is **inert on the studio's own path**. `_swarm_generate` submits
  `{"images": 1, "comfyworkflowraw": wf_text}` with `exactbackendid` on every
  pin, so the graph goes to the target box and **ComfyUI validates the filenames
  itself**; Swarm's cached per-backend list is never consulted. It is real for
  **Swarm's own model-based routing** and for anything that trusts Swarm's view
  of what a box holds. The studio-path half is checked by
  `test_t9_11_submit_stays_comfyworkflowraw_plus_exactbackendid`: drop the raw
  key or the pin and the cache becomes the discriminator again.

  **This was already measured on 2026-08-12** — *"harmless for our raw+pinned
  path, since ComfyUI validates filenames itself, but Swarm's own model-based
  routing would be stale until a re-init"* — and recorded **without its scope
  attached to this criterion**. The cost of that omission, paid the next day:
  two sessions independently concluded a production SwarmUI restart was required
  after staging models to a box, and neither could justify it, because a finding
  recorded without its scope reads as universal. **A criterion that names a
  hazard must name where it does NOT apply**, or it is a warning that spends
  other people's caution.
- `T9-12` **ComfyUI's `/history` does not record jobs that arrived through
  SwarmUI**, because Swarm advertises `comfy_saveimage_ws` and streams outputs
  back. `/history` staying at 0 is not evidence a box did not run. The authority
  is the container log.
- `T9-13` **Nodes are never the discriminator; files are.** Every node the studio
  uses is present on every box; what differs is which weights are there and under
  what name. A capability check that consults the node list answers the wrong
  question.
- `T9-13a` **A file is not a model, and `models.installed()` cannot tell the
  difference.** It reads the loader's **enum**, never the bytes — so a truncated
  weight file reports `available: True` and fails at load, hours later, looking
  like a model defect rather than a copy that never finished. Measured
  2026-08-13 while staging Qwen-Image-Edit to gamingpc: three model files sat at
  their **real filenames** at 19%, 46% and 76% of source size, every one of them
  enumerable and none of them loadable.

  Two detection rules, both free and neither requiring anyone to remember that a
  transfer happened:

  - **An epoch mtime on a model file means truncated.** `rsync` sets mtime only
    on completion, so an interrupted `--partial` leaves `Dec 31 1969`. This is
    the cheap check and it catches the common case.
  - **Size against source, or a checksum, before a box is trusted with the
    model.** The epoch rule misses an `--inplace` write, which carries a current
    mtime and mode `600` — so mtime alone is necessary and not sufficient.

  This is the `wan22_i2v_low` defect in a new place: a box reporting a capability
  it does not have. Staging is not complete when the file exists; it is complete
  when the bytes match.
- `T9-13c` **A model is not staged until its checksum passes, and SwarmUI must
  not be restarted before that.** Observed live 2026-08-13, mid-transfer:
  gamingpc's `UNETLoader` enum **already listed
  `qwen_image_edit_2511_fp8mixed.safetensors` at 26% of its bytes**, because
  rsync writes to the real filename. Anything reading `/object_info` in that
  window sees a model that exists and cannot load.

  **What is verified, and what is only believed** — the distinction matters
  because the second was nearly reported as the first. *Verified:* the queue was
  idle and nothing was enqueued, so no job could route anywhere. *Believed, and
  not provable from Swarm's side:* that Swarm's own cached list for that backend
  does not yet hold the partial. `SESSIONS.md` records that the node and model
  list comes from `object_info` via `LoadValueSet()`, **which runs only in
  `Init()`** — the idle monitor never refreshes it — so a continuously-connected
  backend should still be holding its old list. But `ListBackends` does not
  expose that list, so **it cannot be read back**, and a reconnect for any reason
  would have re-Init'd it silently.

  **So the safety here rests on the idle queue, not on the cache.** The cache is
  probably helping and must not be counted on, which is the same error as
  trusting a check nobody has watched go red. The ordering is therefore not a
  preference:

      transfer completes -> checksums pass -> BOTH queues idle -> restart SwarmUI -> render

  **Restarting mid-transfer publishes a truncated model to the router.** The same
  cache that refused a node a box plainly had is, in this window, the only thing
  standing between a partial file and a pinned render. Neither behaviour is
  designed; the sequence is what makes them safe.
- `T9-13b` **Staging a model stages its companions in the same act, and the
  criterion is that the STAGING PATH reads `CATALOG.companions` — not that one
  script happened to get the list right.** A box holding the UNET and VAE but
  not the text encoder reports the model available and fails at load, the same
  failure as `T9-13a` by a different route.

  **Built, check can fail.** `models.staging_files(key)` returns the primary
  weight plus every name in `CATALOG[key]["companions"]`. The gamingpc run of
  2026-08-13 staged UNET, text encoder, VAE and LoRA together and all four
  verified, but that was a hardcoded shell list; the next model must not depend
  on someone remembering companions. Mutation: hardcode only the primary, or
  keep a remembered companion after `CATALOG.companions` changes → red.

## 6. The shared card

`gpu.py` exists because *"ComfyUI and ollama share ONE 24 GB card on cerberus,
and neither knows the other"*.

- `T9-14` A render is not started when the card cannot hold it **because of the
  other tenant**, and the refusal says which tenant. The failure this prevents is
  an OOM attributed to the model.
- `T9-15` Free VRAM is **measured before the render**, as the clip job already
  does, and recorded with the result. TRD-5 `T5-5` consumes this for the refine
  measurement.

## 7. Credentials and alerting

- `T9-16` **No credential is stored in the repo**, and the store names where a
  key came from. `creds.py` owns it.
- `T9-17` An alert transport that is unreachable **degrades to a recorded state
  change**, never to silence. An alerting path whose failure mode is quiet is
  worse than none, because it is trusted.

## 7a. One operational postmortem — CLOSED, kept as history

**CLOSED 2026-08-13 by Jon: peaches-unraid onboarding is DONE and took a
different route.** The disk work below is finished and is not a live task. It is
kept because the *lesson* outlives the incident and `T9-18` is a criterion about
fleet operations generally, not about this box — but nothing here is outstanding
and nobody should re-plan against it.

### The incident, for the record

Carried here 2026-08-13 when `docs/UNRAID_BACKEND_PLAN.md` was removed after
being absorbed. It was the only part of that document with no equivalent in
these criteria, and it is the kind of thing a fleet document exists to hold.

**2026-08-12: growing the Docker vDisk took the Unraid box down for hours.** The
box went unreachable — no ssh, no ping — and came back with a stopped array and
a pending dual-parity check against 11.7 TB.

The evidence, from `/boot/logs/syslog-previous`: `umount /mnt/cache` returned
**exit status 32, "target is busy"**, Unraid retried every 5 s for ~45 s, and
then `rc.6` forced the shutdown through with SIGTERM. That is why the array came
back unclean and why a parity check was pending. **The lost ssh and ping were
`rc.6` tearing down `eth0`, not a crash and not a network fault** — the shutdown
was orderly, it was the *unmount* that would not complete.

- `T9-18` **A fleet operation that requires stopping a service names which
  service, and never more.** The lesson generalises past Unraid: the array did
  not need stopping to resize a Docker vDisk, and stopping it is what cost the
  hours. An operational runbook step that takes down more than the thing being
  changed is the same class as a migration that rewrites more rows than it
  meant to.

## 8. Explicitly not building

- **No forecast-based scheduling.** TRD-6 §1 decided the wait state; nothing here
  predicts render times to split work.
- **No second queue.** `jobs.py` is it, and TRD-6 owns it.
- **No distributed coordinator.** Four boxes on a tailnet and one SQLite file.
- **No SwarmUI on the Unraid box.** `UNRAID_BACKEND_PLAN.md` §4 says don't, and
  the measurement is in that document.
- **No hard exclusion of slow boxes.** `T9-5`, and it is a decision not an
  oversight.

## 9. How every criterion above is to be verified

`TRD-6 §0`'s rules, cited not restated. Two that bite hardest here:

- **Different seeds, always** (`T9-10`). Half the traps in §5 are measurement
  artefacts that look like defects.
- **Test against the live fleet, not a mock.** Every number in this document was
  measured on the real boxes, and the failures it names — a benched backend, a
  cached node list, a silent empty backend — are all things a mock cannot
  produce.

### The positive half of each one-sided criterion

**Extended 2026-08-13 after external review** — grok and chatgpt independently
found eight more, six overlapping. `docs/reviews/TRD8910-*`.

| criterion | why it is one-sided | its positive half |
|---|---|---|
| `T9-5` slow boxes sort to the back, not out | passes if such a box is never considered at all | a plan containing **both** a fitting and a non-fitting box **still includes the slow one, later in the order** — an ordering assertion, not "not excluded in code" |
| `T9-7` a refusal can bench the next attempt | states a hazard with no visible failure if the walk is deleted | after a refusal, **a subsequent attempt is still made and the sequence is observable** |
| `T9-10` a cache hit is not a refusal | passes if the A/B is never run | with **different seeds** the same path produces a real output where the byte-identical resubmission does not |
| `T9-11` studio submit stays raw+pinned (cache inert on our path) | passes if Swarm is never the router because nothing submits | **every GenerateText2Image carries `comfyworkflowraw`; every pin carries `exactbackendid`; a `model=`-only payload is not the studio path** |
| `T9-12` `/history` is not the authority | passes if nobody checks | a Swarm-routed job leaves `/history` unchanged **while the container log shows it executed** |
| `T9-13` files discriminate, not nodes | passes if capability checks stop running | **two boxes with identical nodes and different weights are told apart** by file presence |
| `T9-15` VRAM measured before the render | passes with preflight logging and no successful render | a **render result carries** its pre-render reading |
| `T9-16` no credential in the repo | absence — passes with no credential feature at all | a credential **loaded from the store is usable by the alert path**, and its provenance is recorded |
| `T9-1` retargeting rewrites names | passes if it rewrites everything, including into failure | **as-written refuses AND retargeted renders**, same workflow, one test |
| `T9-2` per-loader resolution | an absence — no cross-loader substitution | a name that **does** exist in the right loader **is** substituted |
| `T9-3` the free draw is untouched | passes trivially when nothing is submitted | a pinned attempt **is** modified, same fixture |
| `T9-4` three-valued availability | passes if everything reads `False` | a `None` box **is offered** as a candidate |
| `T9-6` refused does not requeue | passes when nothing runs at all | a **vanished** box's job **does** requeue and lands elsewhere |
| `T9-8` a state change alerts | passes if nothing ever changes state | a flapping box produces **one** alert per transition, asserted by count |
| `T9-9` an empty backend is refused | passes if no backend can be registered | a **stocked** backend registers and renders |
| `T9-14` a render is refused on shared-card pressure | passes if renders never start | with the card free, the same render **starts** |
| `T9-17` an unreachable transport degrades | passes if alerting is deleted | with the transport reachable, the alert **arrives** |


---

## Status against the tree, 2026-08-15

Written by session A, in the shape session B set in TRD-4/TRD-7: a **ledger**,
not folded into the criteria above — *a criterion edited to describe what was
built is no longer a criterion, it is a changelog with a prefix.*

**"built" means a check can go red, not that the code exists.** `T4-10` read as
done all day while `app.ALBUM_FIELDS["body"]` quietly beat it, so a ledger that
repeats that is worse than none. Production is `c01c977`+; `origin/main` is
current.

**This document is the inverse of the others: the machinery is built and in
production, and almost none of it has a check.** That is the point of writing it.

| criterion | state | commit | what was measured |
|---|---|---|---|
| the whole of §2 — the seam, retargeting, the retry walk, staging, alerting | **built and live** | earlier | `RENDER_BACKEND=swarm` in production; four backends; every artefact stamped `via=swarm` |
| `T9-1`/`T9-2` retargeting | **built, unchecked** | earlier | proven once on the live fleet: refused as written, **rendered in 9.7 s once retargeted**. No criterion asserts it today |
| `T9-3` the free draw is byte-identical | **built, and its check was rewritten once** | earlier | a mutation audit found the original could not fail for the reason it named; it now asserts identity and counts `ListBackends` calls |
| `T9-6` vanished requeues, refused does not | **built** | earlier | `pipeline._backend_vanished` |
| **`T9-13a` a file is not a model** | **built, check can fail** | this tree | `models.weight_available(path, expected_bytes=…)`: enum-only (`path=None`) is False; epoch mtime is False; size short of expected is False; complete file with live mtime and full size is True. `studio/test_trd9_fleet.py::test_t9_13a_truncated_or_enum_only_weight_is_not_available`. Mutation: treat enum presence or a 26% file as available → red |
| `T9-13c` staging sequence | **written today, untested** | today | transfer → checksums → queues idle → restart → render. **The safety rests on the idle queue, not on Swarm's cache**, which cannot be read back |
| **`T9-11` submit stays `comfyworkflowraw`+`exactbackendid`** | **built, check can fail** | this tree | `studio/test_trd9_fleet.py::test_t9_11_submit_stays_comfyworkflowraw_plus_exactbackendid`: free draw + pin both carry raw workflow; pin carries `exactbackendid`; unit shape of `_swarm_generate` is exact. Mutation: replace raw with `model=` → red. Hazard remains real for Swarm's own routing only |
| `T9-13a` the 26% enum | **INCIDENT CLOSED, rule kept** | today | all six staged files sha256-verified both ends, zero MISMATCH in the run. The file that was 26% written reads `OK`. The rule stands; the window is shut |
| `T9-13b` companions | **built, check can fail** | this tree | `models.staging_files(key)` returns primary + `CATALOG.companions`. `studio/test_trd9_fleet.py::test_t9_13b_staging_path_reads_catalog_companions`: qwen ships UNET+three companions; live monkeypatch of companions drops the old list and stages the new name. Mutation: hardcode only the primary or keep a remembered companion after CATALOG changes → red |
| **gamingpc as a second image box** | **CAPABLE, NOT PROVEN** | today | all six files enumerated under the loader that will load them — `UNETLoader`, `CLIPLoader`, `VAELoader`, `LoraLoaderModelOnly` — and 31.84 GiB total / 30.01 free against a 19.12 GiB UNET plus an 8.7 GiB encoder. **Fits on paper and has never been run.** Written this way so the next session inherits a fact and not a claim |
| **peaches-unraid onboarding** | **DONE — closed by Jon 2026-08-13** | — | took a different route from the one planned. Backend [2], running, `/system_stats` answers 200, 10.58 GiB visible. **No disk task is outstanding**; §7a is history, not work |
| **`T9-18` fleet ops name their service** | **built, check can fail** | this tree | `fleet_watch.name_stop(op, services)`: resize_docker_vdisk names docker only; empty/unnamed refuse; array or docker+array refuse (vDisk blast-radius class); unknown op refuses. `studio/test_trd9_fleet.py::test_t9_18_fleet_ops_name_their_service_and_never_more`. Mutation: accept unnamed or over-scope stop → red |
| `T9-5` slow boxes sort to the back, not out | **built, check can fail** | this tree | `studio/test_trd9_fleet.py::test_t9_5_nonresident_box_stays_in_the_plan_later`: a fitting 23.42 GiB box and a 10.58 GiB box that holds `wan22_s2v` both stay in `where()`, slow later. Same fleet, `ace_step_v1` (both fit) stays ordered by id — not a card-size sort |
| `T9-7` a refuse can bench the next walk step | **built, check can fail** | this tree | `studio/test_trd9_fleet.py::test_t9_7_refusal_benches_next_pin_and_walk_still_continues`: free-draw validation refuse, then pin 0 answers the benched "No backends match" headline, pin 1 still runs and succeeds; progress names both misses. Not a timing test |
| `T9-8` a state change alerts once per transition | **built, check can fail** | this tree | `studio/test_trd9_fleet.py::test_t9_8_state_change_alerts_once_per_transition_not_per_poll`: flapping box → one alert per edge by count; 20 down-polls → 1; once() notify path seed+down×3+up×2 → 2 alerts |
| `T9-4` three-valued `where()` | **built, check can fail** | `test_trd9_fleet.py` | `test_t9_4_where_is_three_valued_and_none_is_offered`. Same fact as T6-A6 |
| `T9-16` no credential in the repo; store names source | **built, check can fail** | this tree | `studio/test_trd9_fleet.py::test_t9_16_store_credential_usable_by_alert_with_provenance`: defaults sit outside the tree; store-loaded `slack_webhook` is what `fleet_watch.notify` posts to; `status()` names encrypted-store provenance without rendering the value |
| `T9-14` render refused when other tenant holds card | **built, check can fail** | this tree | `studio/test_trd9_fleet.py::test_t9_14_render_refused_when_other_tenant_holds_card_and_starts_when_free`: ollama held 21.9 GB, free stays 0.25 after unload clears `/api/ps` → `_submit_and_collect` raises naming tenant ollama, `submit_dir` not started; free card same path starts. Mutation: strip tenant from refuse → red |
| `T9-17` unreachable alert transport degrades | **built, check can fail** | this tree | `studio/test_trd9_fleet.py::test_t9_17_unreachable_transport_records_state_change_reachable_arrives`: dead notify → host `up` flipped on disk + `_alert.delivered is False` with lines + stderr `alert FAILED`; reachable notify → alert lines arrive + `_alert.delivered is True` |
| `T9-9`, `T9-10`, `T9-12`, `T9-13c`, `T9-15` | **behaviour exists, no red checks on HEAD** | — | worktrees exist; closeout grind is landing these. `T9-11` / `T9-13a` / `T9-13b` already have checks |
