# What the two reviewers recommended, and what was done with each

Round 2, 2026-08-13. grok and chatgpt reviewed TRD 1-3 as they stood after the
audit fixes. Raw reviews are beside this file. **Every criterion id and every
quotation was checked against the files before anything was acted on. Both
scored zero fabrications.**

Legend: **FOLDED** = changed. **REJECTED** = not changed, reason given.
**DEFERRED** = agreed, owned elsewhere.

---

## The one that was a live bug, not a documentation defect

| # | finding | status |
|---|---|---|
| 1 | **`T3-7` enforced 8n+1 on every clip, and WAN's 77 frames is not 8n+1** — so QC flagged every correctly-rendered s2v clip. 8n+1 is LTX's latent rule (`EmptyLTXVLatentVideo` step 8); WAN declares step 4 and 77 = 4x19+1. | **FOLDED, in code.** `expect_from_workflow` records `frame_step` off the graph; `qc.py` uses the model's own rule. Asserted both ways on one 77-frame file: passes at step 4, flags at step 8 naming 81. |

## Contradictions between documents

| # | finding | status |
|---|---|---|
| 2 | TRD-2 says **"one scene is one clip"** while `T2-10` and `T2-48` both require a long scene to split into a chain | **FOLDED.** The shorthand contradicted two of its own criteria. Surviving rule stated: planning may yield more than one clip per scene, never more than one scene per clip. |
| 3 | TRD-1 §3.2 still cited **"the three sites §3.4 names"** after §3.4 retracted that to two | **FOLDED.** |
| 4 | `T2-8a` asserted **"the three sites agree"** — a false inventory | **FOLDED.** Reads "both live sites". |
| 5 | TRD-3 §6.2's remedy **"re-run loudnorm at the master"** names a stage a set without curves does not have | **FOLDED.** Now "at the master when the set has one, per item otherwise". |
| 6 | **Easy mode allowed TWO loudnorms** — master engaged by easy, per-item stripped only for a gain curve | **FOLDED** as `T1-20d`: exactly one, always. Two normalisers in series is the second working against the first. |
| 7 | Clip fps: **native vs song-normalised** never stated | **FOLDED** as `T2-13f`. A clip's expectation is its NATIVE fps; comparing against the song's would flag every correct clip of the other model. |

## Criteria that could still not fail

| # | criterion | status |
|---|---|---|
| 8 | `T1-19`, `T1-20c` — could record metadata over a no-op | **FOLDED.** Both now require a measured output move. |
| 9 | `T1-25` — could write numbers and never flag | **FOLDED.** Both halves asserted. |
| 10 | `T1-26` — files could accumulate that nothing can reach | **FOLDED.** Older render must be listed and selectable. |
| 11 | `T2-14`, `T2-15`, `T2-16`, `T2-17` — all satisfiable by deleting the guarded feature | **FOLDED.** Each gained its positive half. |
| 12 | `T3-25` — precondition could stay false forever | **FOLDED.** The flip must be exercised. |
| 13 | `T1-23`, `T3-6`, `T3-18` still vacuous | **REJECTED as unfixable by wording.** All three are satisfied by the absence of the feature they guard, and only `duck`/`layer` and `approve()` doing something fixes that. Marked provisional, which is the honest state. |
| 14 | `T1-29a` (trust boundary) can never go red — UNSURE | **ACCEPTED as a limitation.** It is a statement of where authz lives, not a testable behaviour. |

## Wrong claims — both rejected, with a measurement

| # | finding | status |
|---|---|---|
| 15 | chatgpt: the pan filter **"discards cross-channel terms"** and so is not a balance | **REJECTED.** Cross-channel terms rotate a stereo image; balance attenuates one side without mixing, which is the stated intent and what the measurement shows. |
| 16 | chatgpt: the **-3 dB claim is "oversimplified to the point of being wrong"** | **REJECTED, measured.** 440 Hz stereo tone: source -21.1 dB, balance at centre -21.1, equal-power at centre **-24.1**. Exactly the 3 dB, on the file. Recorded in TRD-1 §3.1 so the argument is not had a third time. |

## Smaller corrections

| # | finding | status |
|---|---|---|
| 17 | `T3-24`'s "20.5 GB" mixes GiB and GB (13.31 GiB + 6.3 GiB + 0.24 GiB is ~19.6 GiB) | **FOLDED.** Units corrected; the conclusion never changed — it does not fit a 15.92 GiB card either way. |
| 18 | 77 is equidistant from 73 and 81, so a planner rounding to 8n+1 needs a tie-break | **FOLDED** into `T3-7`'s note: the code rounds half-to-even and lands on 81. |
| 19 | No document names the **authority for a song's duration** | **DEFERRED to TRD-6** `T6-13a`: `songs.duration`, written once from ffprobe on upload. |
| 20 | Gaps: persisted workflow schema, path identity, lifecycle, SQLite concurrency, retention | **DEFERRED to TRD-6**, which exists because both reviewers found the queue owned by nobody. |
