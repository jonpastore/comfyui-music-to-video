# What the two reviewers said about the TRD 4-7 plan, and what was done

Round 1, 2026-08-13, over `docs/PLAN-TRD-4-7.md`. grok and chatgpt, independently,
same brief, neither shown the other's answer. Raw reviews are beside this file.

**Lane: `llm -m grok` and `llm -m chatgpt`, prompt on stdin, run in parallel.**
The in-process agent lane is dead in this session — one trivial spawn, no report,
not listed — so no agent reviewed anything and none is claimed to have.

**Fabrication count: zero confirmed, one near-miss that the brief caught.** grok
named `T5-11` and `T5-12` while explicitly writing *"only ids appearing in the
plan text are safe to name"* in the same sentence. Those ids do not exist —
TRD-5 declares `T5-1`…`T5-10`. The hedge held, and it is recorded because the
hedge is the reason the review is usable.

Legend: **FOLDED** = the plan changed. **REJECTED** = it did not, reason given.

---

## The finding that outranks the rest: the criterion counts are wrong

Not raised by either reviewer directly, but found by chasing grok's *"TRD-4 says
5 built and lists six ids"*. Counting declaration sites in the files:

| | quoted everywhere | actually declared |
|---|---|---|
| TRD-1 | 36 | **32** |
| TRD-2 | 61 | **58** |
| TRD-3 | 36 | **30** |
| TRD-4 | 18 | 18 |
| TRD-5 | 12 | **10** |
| TRD-6 | 24 | **25** (19 numbered + `T6-A1`…`T6-A6`) |
| TRD-7 | 19 | 19 |
| **total** | **~197** | **192** |

Five of seven are wrong, and the numbers had been copied into the day-12
continuation, this plan and `docs/PRD-1-3-EDITING-AND-QUALITY.md` before anyone
counted. TRD 4-7 is **72** criteria, not 73. It is a small error with a large
shape: it is the third time in this project that a number was carried between
documents instead of measured, and the documents' own rule about two copies of a
number drifting applies to their own front matter.

Corrected in the plan and the PRD. `grep -cE "^- .T<n>-"` is the count, and it
can be re-run.

## Both reviewers, independently

These carry the most weight — two models, no shared context, same finding.

| # | finding | status |
|---|---|---|
| 1 | **§2.3 mints `T6-A7`…`T6-A10` while §5 says "it adds no criteria".** A direct self-contradiction. | **FOLDED.** §5 now says consolidation moves rules to one owner and mints four ids for what were seven prose restatements, and states the net. |
| 2 | **`T5-2` is Phase E's stated proof and is not a Phase E deliverable.** | **FOLDED.** Phase E now names `T5-1`…`T5-4` as its build list. |
| 3 | **`T7-19` is in the dependency graph and in no phase.** | **FOLDED**, and overtaken: session B shipped it as `415584d` while the plan was being reviewed. Now in §1's built ledger. |
| 4 | **Consolidating the verification rules is right; TRD-6 is the wrong owner.** grok: *"putting canon in the doc most likely to be rewritten maximizes churn"*; chatgpt marked itself UNSURE for want of the fact. | **REJECTED, with the fact neither had.** TRD-6 **§0 is titled "Rules every document inherits"** and already owns `T6-A1`…`T6-A6`, which TRD-1 §10, TRD-2 §8 and TRD-3 §7 already cite instead of restating — the mechanism works today. The objection is really about the document's *name*; §0 is a preamble no phase touches, and moving canon to a new file to fix a title is churn for churn. Recorded because both reviewers reached it and the reason they were wrong is a fact, not a preference. |

## Ordering and coverage gaps — all folded

| # | finding | status |
|---|---|---|
| 5 | grok: **`T7-4`** (a view's framing sentence is the only difference between two sheets of one tier) is named in Risk 2 as the honesty check and appears in no phase. | **FOLDED** into Phase B, where it gates the fan-out it is the check for. |
| 6 | grok: **`T6-12`** is in no phase bucket. | **FOLDED** into Phase F. |
| 7 | Both: **§2's consolidation has no phase, no files and no proof** — it would have stayed a proposal. | **FOLDED** as Phase 0, with a `grep` that can fail as its proof. |
| 8 | chatgpt: **`T6-13a` has no owner on the TRD-1-3 side**, though §3 says it should precede `T2-12a`. | **FOLDED** as an explicit cross-document handoff. |
| 9 | grok: **`T7-11`/`T7-12` sit in Phase C with no dependency edges.** | **FOLDED** — they are independent of `T7-6`→`T7-9` and now say so. |
| 10 | grok: **the cross-session contract with B is missing** — the plan says "not a work order" for files B is actively editing and never says how that binds. | **FOLDED** into §5. |
| 11 | grok: **`T4-18`'s dependency on the Phase A view table is in the graph and not inside Phase D.** | **FOLDED.** |

## Criteria that cannot fail — the reviewers' best work

| # | finding | status |
|---|---|---|
| 12 | Both: **Phase A's proof "(b) refused at `g` with no gate edited" stands on its own** and is satisfied by a view that never renders. | **FOLDED.** One test, three assertions, reachability asserted **first**. |
| 13 | grok: **`T7-18` as a gate stays green while the four types do not exist** — absence satisfies the negation walker. Completion must require red-before-green *per type*. | **FOLDED**, and it is the sharpest thing either review returned: it is the plan committing, in its own gate, the defect the plan is about. |
| 14 | Both: **Phase B's "the preview shows all four" is satisfiable by static labels or a fallback string.** | **FOLDED.** Each type's source text is mutated independently and the exact segment must move, in the preview *and* in what is sent downstream. |
| 15 | grok: **`T7-8`/`T7-9` have no differential at all**, in a phase whose own text says the labels and the graph already disagree. | **FOLDED.** One resolver, asserted from both ends. |
| 16 | Both: **Phase D's non-`T4-13` items and all of Phase F carry no per-criterion differential.** | **FOLDED** as an explicit obligation rather than per-criterion text — writing 30 differentials into a plan is writing the tests in the wrong file. |
| 17 | grok: **§1's own "built" evidence is presence-shaped** — a catalogue entry for `T5-8`, `WAL + MIGRATIONS` for `T6-17`, an empty tuple for `T4-10` — *"the same shape the plan warns against; treat as UNSURE"*. | **FOLDED, and independently confirmed within the hour.** B measured that `T4-10`/`T4-11` were half-true: `_NEGATION_ALLOWED = ()` was real, and `app.ALBUM_FIELDS["body"]`'s default still carried the negation and is the one that renders. grok's UNSURE was right, about the exact criterion it could not see. |
| 18 | chatgpt: **`T5-2`'s "mean absolute pixel difference > 0" proves not-a-no-op, not that refine worked**, and "a sharpness metric moving the right way" is undefined. | **FOLDED into Phase E as a split**: MAD > 0 is the no-op guard, a stated metric on a fixed fixture set is the quality claim. This is a criticism of TRD-5 `T5-2`'s wording, not only of the plan, and it belongs in TRD-5 when that document is next opened. |
| 19 | chatgpt: **`T7-7` has no threshold or pass/fail definition**, so "compare the images" risks being non-falsifiable. | **FOLDED, but not as a threshold.** `T7-7` is human-judged on purpose — TRD-7 §6 says *look at the image* — so the plan now states the protocol (which pair, which question, recorded answer) instead of inventing a number. A fake threshold on a judgement call is worse than an honest human step. |

## Rejected, beyond #4

| # | finding | status |
|---|---|---|
| 20 | grok: **cut `T7-2` from Phase A**, since the same bullet says it landed. | **FOLDED not rejected** — it is a precondition now, not a deliverable. Listed here because it is the one place the two reviewers disagreed in emphasis and grok was simply right. |
| 21 | grok: **"look at them" as the sole proof for Phase C.** | **PARTIALLY REJECTED.** The render differential stays and is not cut; human inspection stays too, because the identity collapse, the world that never rendered and the LoRA that did nothing were *all* found by opening the picture and *all* passed every deterministic check. Reliance on unaudited eyeballing for "done" is what #19 fixes. |
| 22 | chatgpt: **cut the TRD-6 ownership proposal.** | **REJECTED**, same reason as #4. |

## Not raised by either, found while verifying them

- **TRD-4, TRD-5, TRD-6 and TRD-7 have no "positive half of each one-sided
  criterion" table**, while TRD-1, TRD-2 and TRD-3 each have one. The audit that
  produced those three was never run over these four. Plan §2.3a, Phase 0.
- **The plan's own ledger went stale during the review.** Three commits landed
  from session B between writing and folding. §1 says so rather than being
  quietly corrected, because "the document drifted from the code within the hour"
  is the finding.
