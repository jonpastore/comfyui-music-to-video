# TRD-9 · The fleet and its operational layer

Status: written 2026-08-13. **Absorbs `docs/SWARM_PIPELINE_PLAN.md` (382 lines)
and `docs/UNRAID_BACKEND_PLAN.md` (387 lines)**, neither owned by any TRD, plus
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
  This hazard is **inert on the studio's own path**. `pipeline.py:487-489`
  submits `{"images": 1, "comfyworkflowraw": wf_text}` with `exactbackendid`, so
  the graph goes to the target box and **ComfyUI validates the filenames
  itself**; Swarm's cached per-backend list is never consulted. It is real for
  **Swarm's own model-based routing** and for anything that trusts Swarm's view
  of what a box holds.

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

  **Satisfied in practice 2026-08-13 and NOT closed.** The gamingpc run staged
  UNET, text encoder, VAE and LoRA together and all four verified — but
  `~/stage_gamingpc.sh` **hardcodes its file list**. The next model staged by
  the next person gets whatever they remember. The gap is the path, not the
  outcome, and an outcome that happened to be right is exactly the evidence that
  hides it. A box
  holding the UNET and VAE but not the text encoder reports the model available
  and fails at load — the same failure as `T9-13a` by a different route.
  `models.CATALOG`'s `companions` already names them; the criterion is that the
  staging path reads that list rather than a human remembering it.

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
| `T9-11` a stale node list is distinguishable | passes if neither case ever occurs | **one real unsupported-node case and one stale-list case produce distinguishable records** |
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

## Status against the tree, 2026-08-13

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
| **`T9-13a` a file is not a model** | **OBSERVED LIVE, unfixed** | today | gamingpc's `UNETLoader` enum listed the Qwen UNET **at 26% of its bytes**. Three files sat truncated at real filenames at 19%, 46% and 76%. `models.installed()` reads the enum, never the bytes |
| `T9-13c` staging sequence | **written today, untested** | today | transfer → checksums → queues idle → restart → render. **The safety rests on the idle queue, not on Swarm's cache**, which cannot be read back |
| `T9-11` scope | **rescoped today** | today | inert on `comfyworkflowraw`+`exactbackendid`; real for Swarm's own routing. Retires a hazard two sessions were ready to spend a production restart on |
| `T9-13a` the 26% enum | **INCIDENT CLOSED, rule kept** | today | all six staged files sha256-verified both ends, zero MISMATCH in the run. The file that was 26% written reads `OK`. The rule stands; the window is shut |
| `T9-13b` companions | **satisfied in practice, NOT closed** | today | the run staged all four together and they verify — but `~/stage_gamingpc.sh` **hardcodes the list**. The criterion is that the path reads `CATALOG.companions`, and it does not |
| **gamingpc as a second image box** | **CAPABLE, NOT PROVEN** | today | all six files enumerated under the loader that will load them — `UNETLoader`, `CLIPLoader`, `VAELoader`, `LoraLoaderModelOnly` — and 31.84 GiB total / 30.01 free against a 19.12 GiB UNET plus an 8.7 GiB encoder. **Fits on paper and has never been run.** Written this way so the next session inherits a fact and not a claim |
| `T9-4`, `T9-5`, `T9-7`…`T9-12`, `T9-14`…`T9-17` | **behaviour exists, no checks** | — | including the four measurement traps, each of which cost a wrong diagnosis once |
