# TRD-6 · Queue, artefact lifecycle and storage

Status: written 2026-08-13. **This document exists because two independent
reviews found the same hole: every other TRD depends on this machinery and each
one explicitly disowns it.** TRD-1 §11 says the scheduler "needs its own
specification", TRD-3 §9 says it "depends on the wait-state model" without
specifying it, and TRD-2 owns only the narrow chain-readiness rule. A dependency
that three documents disown is a dependency nobody is going to build.

Acceptance criteria are `T6-n` and each **can fail**.

---

## 1. The queue is a wait state, not a timing match

**Decided 2026-08-12 by Jon**, and recorded in the reconciliation: when a
resource frees, it takes the next queued item that matches it. His words: *"we
should not be trying to match timing, that's how race conditions happen."*

This replaced a fan-out floor derived from *predicted* render times — scheduling
by forecast, which is the failure being avoided. A pull model needs no
prediction and dissolves the straggler problem: if cerberus is 2.59× faster it
simply takes 2.59× more items, and the measured 291.6 s vs 378.2 s inversion
never arises because nothing was split by a forecast.

- `T6-1` Workers **pull**; the studio does not assign. A backend that is slow,
  off, or behind a VPN self-corrects by pulling less. Asserted with one backend
  stalled: the others drain the queue and the total does not wait on it.
- `T6-2` **"Ready" is expressed separately from "queued".** A chained clip is not
  enqueueable until its predecessor has landed, because it needs that frame
  (TRD-2 `T2-11`). A queue with one state hands scene chains out in the wrong
  order.
- `T6-3` Matching is on **capability, not identity**: an item requires a model,
  and `models.where()` answers which boxes hold it, under which spelling, and
  whether it fits. Its three-valued answer is respected — `False` is a refusal,
  `None` is a candidate.
- `T6-4` A job lost to a box that went away **requeues**; a workflow a box
  *refused* does not. Both arrive under the same "No backends match" headline,
  so the REASON line is the discriminator — already built in
  `pipeline._backend_vanished()` and asserted across the seam.

## 2. The lifecycle of an artefact

Named because TRD-1 `T1-26`, TRD-2 `T2-11` and TRD-3 `T3-6`/`T3-18`/`T3-21` all
lean on it and none defines it.

    planned -> queued -> ready -> running -> landed -> checked
                                     |          |        |
                                   failed    stamped   finding -> approved -> repaired

- `T6-5` Every transition is **recorded with its time**, so "why did this take
  four hours" is answerable from rows rather than from logs.
- `T6-6` A **re-render is a new candidate, never a replacement** — the rule
  TRD-1 `T1-26` and TRD-3 `T3-6` both state. One implementation of it, here.
- `T6-7` `landed` requires the file to exist. A row claiming an artefact that is
  not on disk is the state QC then measures nothing against.

## 3. Identity: what joins to what

Both reviews raised this and neither TRD answers it.

- `T6-8` `findings.path` joins `artefacts.path`, and **paths are canonical**:
  one absolute form, resolved, no two rows describing one file. A test inserts
  the same file by two spellings and asserts one row.
- `T6-9` **A file that disappears after its row exists is detected**, not
  reported as passing. QC over a missing artefact is a finding, not a skip.
- `T6-10` Deleting a set item deletes its automation rows (TRD-1 `T1-2`);
  deleting a song does **not** silently orphan its clips, refs and findings.
  Cascade policy is stated per table rather than inherited from whatever sqlite
  does by default.

## 4. Where the submitted request is kept

TRD-3 requires every check to compare against **what the workflow asked for**,
and until 2026-08-13 nothing stored it — the sharpest checks sat idle on clips.

- `T6-11` The submitted request is persisted **at submit time, from the built
  graph**, and retrievable for any artefact later. `artefacts.expect_json`,
  written by `pipeline._stamp_expect` from `build_song.expect_from_workflow`.
- `T6-12` A **repaired candidate links back to the expectation it was judged
  against**, or the re-check after a repair compares against a different
  question than the original finding did.
- `T6-13` Absent stays absent: an artefact with no recorded expectation makes QC
  **skip** those comparisons, never infer a baseline from the file itself. A
  check reading 81 frames off a file and then asserting the file has 81 frames
  is a check comparing a number against itself.

## 5. Concurrency on one SQLite database

The studio is single-user but multi-process: a web layer and a serialized job
worker share one file, and WAL is already on.

- `T6-14` A job handler's writes are **one transaction**, so a killed worker
  leaves no half-written job. Asserted by killing mid-handler and reading back.
- `T6-15` The `findings` upsert and the `artefacts` stamp are **idempotent**
  under a re-run — already true and asserted (`T3-5`), stated here because it is
  a concurrency property and not only a QC one.
- `T6-16` Nothing holds a write transaction across a subprocess call. A render is
  minutes long and the web layer must not block on it.

## 6. Migration and retention

- `T6-17` Every schema addition is an `ALTER` in `MIGRATIONS` and **existing
  rows keep working with the column NULL**, which is the compatibility rule
  every column added this week already follows (`expect_json`,
  `scene_seconds`, `resident_gib`).
- `T6-18` **Nothing is deleted by this document.** Garbage collection is
  deferred by name in the reconciliation because it needs a manifest of what was
  pushed where — and §4's expectation record plus §3's identity rules are most
  of that manifest. When GC is specified it extends these tables rather than
  inventing its own, and the shapes here must not make that harder.

## 7. Explicitly not building

- **No forecast-based scheduling.** §1, decided.
- **No second queue.** `jobs.py` is it; a "render queue" beside the job queue is
  two places for one item's state.
- **No distributed coordinator.** Four boxes on a tailnet, one SQLite file, one
  worker thread. The wait state is the whole design.

## 8. How every criterion above is to be verified

A measurement that cannot fail is not evidence; a refusal or a presence is half a
criterion. And the one this document is most exposed to: **every criterion here
describes machinery that does not exist yet**, so each must be read as
specifying a test that fails today. A criterion satisfied by the absence of the
thing it describes is the defect TRD-3 `T3-6` and `T3-18` are marked provisional
for, and this document must not repeat it at scale.
