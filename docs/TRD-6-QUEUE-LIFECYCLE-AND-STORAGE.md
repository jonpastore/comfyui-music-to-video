# TRD-6 · Queue, artefact lifecycle and storage

Status: written 2026-08-13. **This document exists because two independent
reviews found the same hole: every other TRD depends on this machinery and each
one explicitly disowns it.** TRD-1 §11 says the scheduler "needs its own
specification", TRD-3 §9 says it "depends on the wait-state model" without
specifying it, and TRD-2 owns only the narrow chain-readiness rule. A dependency
that three documents disown is a dependency nobody is going to build.

Acceptance criteria are `T6-n` and each **can fail**.

---

## 0. Rules every document inherits

**Consolidated here 2026-08-13.** These were restated in TRD-1, TRD-2 and TRD-3
in near-identical words — the API separation four times over as twelve criteria
for four facts, and "a re-render is a new candidate" five times across five
documents. One owner each; the others cite and add only what is theirs.

### 0.1 Backend / front-end separation — `T6-A1`…`T6-A4`

All business logic in the backend, the front end disconnected, so a replacement
front end including mobile can be built later against the same API.

- `T6-A1` **Every operation is reachable over JSON with no HTML involved.** A
  curl script drives the feature end to end. Each document names its own loop:
  TRD-1 a set from empty to rendered, TRD-2 the storyboard loop, TRD-3 the review
  queue.
- `T6-A2` **The HTML page and the JSON endpoint report the same numbers** for the
  same object, asserted by comparing them in one test. Two answers means two
  implementations.
- `T6-A3` **The service module imports nothing from FastAPI** and its functions
  are called directly by tests. If a test can only reach the logic through a
  request, the logic is in the wrong place. A route handler contains no
  arithmetic, no defaulting and no decision — if a route handler decides
  something, a mobile client cannot.
- `T6-A4` **No template computes anything.** Asserted by a differential, not a
  grep: stub the service to return known values and assert the page shows them
  unmodified. A template that rounds, sums or reformats a number is a second
  implementation of that number.

**The trust boundary is the tailnet binding and nothing else.** The studio has no
authentication; a full JSON control plane inherits exactly that and no more, so
a deployment that widens the bind widens everything.

### 0.2 A new candidate, never an overwrite — `T6-A5`

- `T6-A5` **Anything re-produced is written beside its predecessor, never over
  it.** Set re-renders, refine passes, repaired candidates, re-rolled anchors and
  reference frames. **Both survive and both are reachable** — listed and
  selectable, or "keeps history" means files accumulating that nothing can reach.

  Five documents each said this in their own words. The studio's whole design is
  candidates plus a human pick, and an overwrite destroys the evidence that
  anything was wrong along with the comparison that would show whether the
  repair helped.

### 0.3 Availability is three-valued — `T6-A6`

- `T6-A6` `models.where()` answers `True`, `False` or `None`, and **`False` is a
  refusal while `None` is a candidate.** Conflating them once made
  `where("wan22_i2v_low", …)` return empty for the box that actually held the
  refiner. Every consumer respects all three: storyboard planning, repair
  routing, and the queue's capability match.

### 0.4 How a criterion is verified — `T6-A7`…`T6-A10`

**Consolidated here 2026-08-13.** All ten documents restated these same rules in
their own words, and they had already drifted: TRD-1 §13 carried five numbered
rules, TRD-5 §7 compressed them to a paragraph, and only three of the ten
mentioned the `grep -c` count. That is the shape §0 exists to fix — the API
separation was four documents and twelve criteria for four facts before
`cfe7979`. One owner; the others cite and add only what is theirs.

- `T6-A7` **A measurement that cannot fail is not evidence.** Every criterion is
  a differential — one variable changed, an expected direction — or it names the
  mutation that must break it.
- `T6-A8` **Then mutate the code and read what the mutation actually did.** Not
  "the check went red": *what changed*. One session's mutation did not mutate
  anything and the check passed; another applied a truthy `str.replace` that
  short-circuited an `or`. A flag believed without reading it is a second
  unverified claim on top of the first.
- `T6-A9` **A refusal or a presence is half a criterion.** *"X is refused"* and
  *"the payload carries Y"* both stay green when the whole feature is deleted,
  because a feature that does not exist refuses everything and a field nobody
  reads is still present. Every such criterion is paired with a positive case,
  or marked **provisional** and says what it cannot yet distinguish.
- `T6-A10` **Assert through the shared entry point, never through the function
  it wraps.** Earned on `T1-20d`, 2026-08-13: correct, thorough checks aimed one
  level too low stayed green through a call site deliberately set to the wrong
  value, because they exercised the wrapped function directly. **Two correct
  call sites is not a property a per-function check can see.** Wherever a design
  collapses a decision to one application point — `mixer.item_chains`,
  `mixer.set_duration`, `build_song.clip_plan`, `effects.measure_loudness`,
  `models.canonical_host`, `jobs.canonical_path`, `screen_prompt_field` — the
  criterion goes *through* it, not around it.

Two rules stay with their documents because they are genuinely local: TRD-2
§10.3's recorded-fixture rule for criteria that need a language model, and
TRD-3 §11.1's both-directions rule for a check that must reject a broken
artefact *and* pass a correct one.

And the one no automated rule replaces, which every document may keep saying
because saying it is the point: **when an image looks wrong, look at it.** The
identity collapse, the world that never rendered and the LoRA that did nothing
all passed every deterministic check this project had.

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

- `T6-13a` **One authority for a song's duration.** TRD-1 §3.2, TRD-2 §3.4 and
  TRD-3 §4.4 all derive from "the song's length" and none says where it comes
  from — ffprobe, file metadata, decode length, or a prior `songs.duration`
  measurement. They disagree in the third decimal, which is enough to move a clip
  count at the boundary. `songs.duration` is the authority, written once from
  ffprobe on upload; everything else reads it and nothing re-probes.

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

### The positive half of each one-sided criterion

Added 2026-08-13 from the first external review of this document (grok and
chatgpt, independently — `docs/reviews/TRD47-*-2026-08-13.md`). This document is
the one most exposed to the rule, because **all 25 criteria describe machinery
that does not exist**, so every one of them can go green at once by never
building it.

| criterion | why it is one-sided | its positive half |
|---|---|---|
| `T6-A1` every operation reachable over JSON | vacuously true for an empty API surface | each document's **named loop actually completes** end to end over curl: a set from empty to rendered, the storyboard loop, the review queue. **TRD-4 and TRD-7 never name their loop** — that is a gap, not an exemption |
| `T6-A5` a new candidate, never an overwrite | "never overwrote" is true when nothing was produced | for each of set re-render, refine, repair, anchor re-roll: **predecessor and successor both listed and selectable** |
| `T6-2` "ready" is separate from "queued" | refusing every early enqueue satisfies it | once the predecessor has **landed**, the successor becomes `ready` and is pulled |
| `T6-4` vanished requeues, refused does not | nothing running satisfies both halves | a vanished backend's item **runs elsewhere**; a refused workflow **stays failed with its REASON** and does not requeue forever |
| `T6-5` every transition recorded with its time | green when there are no transitions | one happy-path job produces the **ordered chain with non-null times** |
| `T6-6` a re-render is a new candidate | duplicates `T6-A5` in this same document | one test, and this criterion should **cite `T6-A5`** rather than restate it — the rule §0 exists to enforce, broken inside §0's own document |
| `T6-9` a disappeared file is detected | green if QC never runs on anything | a **present** file runs QC for real and can pass; deleted-after-row produces a finding, not a skip |
| `T6-10` deleting a song does not orphan | refusing all deletion satisfies it | the delete policy is **stated and exercised** — an intended delete removes its automation rows, and no orphan survives |
| `T6-11` the request is persisted at submit | a payload that is stored and never read | QC's comparison **uses `expect_json` and fails when the artefact disagrees with it** |
| `T6-12` a repair links to its expectation | a column that is set and never consulted | the re-check after a repair **judges against the same expectation and can change the outcome** |
| `T6-13` absent expectation means skip | "skip" is the absence half | with an expectation present the comparisons **run**; with it absent they skip **and no baseline is inferred from the file** |
| `T6-13a` `songs.duration` is the authority | naming an authority with no consumers | TRD-1, TRD-2 and TRD-3's length derivations **all read it and nothing re-probes**, asserted to the third decimal across those paths |
| `T6-16` no write transaction across a subprocess | an absence | a concurrent web read **succeeds during a long render** |
| `T6-18` nothing is deleted by this document | always green, by construction | lifecycle artefacts **remain reachable after a re-render**, and GC being out of scope is named — so "nothing was deleted" cannot be read as "storage works" |

**Not one-sided:** `T6-A2`, `T6-A3`, `T6-A4`, `T6-A6`, `T6-1`, `T6-3`, `T6-7`,
`T6-8`, `T6-14`, `T6-15`, `T6-17` — each already carries a kill, a differential
or an idempotency check that can fail.


---

## Status against the tree, 2026-08-13

Written by session A, in the shape session B set in TRD-4/TRD-7: a **ledger**,
not folded into the criteria above — *a criterion edited to describe what was
built is no longer a criterion, it is a changelog with a prefix.*

**"built" means a check can go red, not that the code exists.** `T4-10` read as
done all day while `app.ALBUM_FIELDS["body"]` quietly beat it, so a ledger that
repeats that is worse than none. Production is `c01c977`+; `origin/main` is
current.

| criterion | state | commit | what was measured |
|---|---|---|---|
| `T6-11` the request is persisted at submit | **built** | earlier | `artefacts.expect_json`, written by `pipeline._stamp_expect` from the built graph |
| `T6-4` vanished vs refused | **built** | earlier | `pipeline._backend_vanished()`; both arrive under one headline so the REASON line is the discriminator |
| `T6-15` the findings upsert is idempotent | **built** | earlier | |
| `T6-17` migrations keep old rows working | **convention, held** | earlier | every column added this week works NULL |
| `T6-A7`…`T6-A10` verification rules | **new today** | today | consolidated here from all ten documents, which had already drifted. `T6-A10` is session B's: assert through the shared entry point |
| `T6-8` canonical identity | **built** | this change | HOST: `models.canonical_host()`. PATH: `jobs.canonical_path()` at write time (`jobs.land`, `qc_service.record` / `run_artefact`). Symlink vs dotted path lands as one artefacts row; findings join that path. `studio/test_trd6_queue.py` |
| `T6-13` absent expectation means skip | **built** | this change | `qc.run` with `{}` emits no duration/frame_count; `_stamp_expect` with no sidecar writes no `expect_json`. Present expect still compares. `studio/test_trd6_queue.py` |
| **`T6-13a` one duration authority** | **built** | this change | `app.clip_count`, `grok.generate_storyboard` and `h_qc` all read `songs.duration`; a re-ffprobe on those paths fails `test_t6_13a_songs_duration_is_the_authority_and_nothing_reprobes`. Asserted at 195.792 |
| `T6-2`/`T6-3`/`T6-5`/`T6-7`/`T6-9`/`T6-10`/`T6-12` | **built** | `test_trd6_queue.py` | claim/land/transitions/cascade/repair copies `expect_json`. **T6-1** is still one studio thread plus Swarm assign — do not add a second pull queue |
| `T6-6`/`T6-14` | **partial** | — | repair dest is a new path; handler writes are not one transaction |
| `T6-16` no write lock across a long handler | **built** | this change | `test_t6_16_web_query_succeeds_during_long_handler`: concurrent `jobs.recent`/`queue_ctx` and BEGIN IMMEDIATE succeed while a fake handler is blocked. `_run_one` commits before the handler. |
