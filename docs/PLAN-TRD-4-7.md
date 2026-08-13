# Plan · TRD 4-7

Status: written 2026-08-13, revised the same day after review
(`docs/reviews/PLAN-TRD-4-7-RECOMMENDATIONS-2026-08-13.md`).
Covers `docs/TRD-4-CHARACTER-ANCHORS.md` (18 criteria),
`docs/TRD-5-CLIP-RENDERING-AND-REFINE.md` (10),
`docs/TRD-6-QUEUE-LIFECYCLE-AND-STORAGE.md` (25 — 19 numbered plus
`T6-A1`…`T6-A6`), `docs/TRD-7-ANCHOR-VARIATIONS.md` (19). **72 criteria.**

**Those counts are counted, and the ones everyone was quoting are wrong.** The
draft of this plan said 73 from a table that has TRD-5 at 12 and TRD-6 at 24;
`grep -cE "^- .T<n>-"` says 10 and 25. Five of the seven documents' quoted counts
are wrong and the total is **192**, not ~197. Third time a number has been
carried between documents in this project instead of measured, which is what the
documents' own rule about two copies of a number is for.

**How this plan was produced, said plainly.** The in-process agent lane is dead
in this session — one trivial spawn, no report, not listed, the same as last
session's seven — so there was no consensus fan-out to run. The measured lane is
`llm -m grok` / `llm -m chatgpt` with the prompt on stdin, and the consensus
step is §7: this plan goes to both, and what survives verification against the
tree is folded in. Nothing here claims an agent ran that did not.

**Lane.** Session B holds every anchor source file (`make_anchor.py`,
`build_refs.py`, `studio/app.py`, `studio/prompts.py`, `studio/tiers.py`) and is
executing TRD-4 and TRD-7 right now. **This is a specification-level plan, not a
work order for those files.** Where it names an ordering, that is a
recommendation to whoever holds the file.

---

## 1. What is actually built

Read off the tree at `f9ca597`, per criterion, not off the summary tables.

| | criteria | built | evidence |
|---|---|---|---|
| TRD-4 | 18 | **6 criteria, from 5 changes** | `_NEGATION_ALLOWED = ()` (`make_anchor.py:210`) → `T4-10`; `tiers.check_tier_policy` → `T4-5` **and** `T4-6` (one change, two criteria — the draft said "5 built" and listed six ids); zero views refused → `T4-1`; positive part-list body → `T4-11`; slot naming via `name=None` → `T4-12` |
| TRD-5 | 10 | **1** | `ltx25_latent_upscaler` in `models.CATALOG` + the `installed()` spec-shape fix → `T5-8` |
| TRD-6 | 25 | **4, partially** | `artefacts.expect_json` + `pipeline._stamp_expect` → `T6-11`; `pipeline._backend_vanished` → `T6-4`; WAL + `MIGRATIONS` convention → `T6-17`; `findings` upsert idempotent → `T6-15`. **Phase F's "machinery that does not exist" is about `T6-1`…`T6-10`, the pull queue and the lifecycle; these four are conventions and stamps that happen to satisfy their criteria.** Both statements were in the draft and read as a contradiction |
| TRD-7 | 19 | **6** | `make_anchor.is_nude_view()` → `T7-2`; slot naming → `T7-10`; per-tier-AND-view prompt box (`415584d`) → `T7-19`; "use as reference" on an anchor tile (`d315c6f`) → `T7-6`; `latent_mode` unpinned and `base=None` (`d3f2f6a`) → `T7-8`, `T7-9` |

**17 of 72**, counting `T4-5` and `T4-6` separately as the documents do. Read at `d3f2f6a`.

**This table went stale three times while the plan was being written, which is
the risk the plan itself lists.** It was `12 of 73` when the draft was written.
Session B landed `415584d` (`T7-19`), `4032aba`, `d315c6f` (`T7-6`) and then
`d3f2f6a` (`T7-8`, `T7-9`) on top of `f9ca597` in that window — the last one
between this plan being committed and the sentence you are reading. **A ledger
is therefore stamped with the commit it was read at, not the date**, and one of
the four matters beyond the count:

> **`T4-10`/`T4-11` were only half true and this document said they were done.**
> `_NEGATION_ALLOWED` was emptied and `make_anchor.DEFAULT_BODY` rewritten
> positively — but `app.ALBUM_FIELDS["body"]`'s own default still read *"with no
> lighter or differently-toned patches anywhere"*, and **that is the one that
> renders**: `album_profile()` fills every field from its default, so a truthy
> value always reaches `anchor_from()` and always beats the constant. B measured
> it on a fresh album — `make_anchor.DEFAULT_BODY in the composed prompt: False`.
> Fixed in `4032aba`; the negation walker now covers the studio's own defaults.

The lesson is not "update the table". It is that **a criterion satisfied by one
constant while a second constant overrides it is the same defect class as a
check that cannot fail** — and it survived the document, the test suite and a
deploy. Any claim in the ledger above is worth re-reading before it is acted on.

## 2. The consolidation pass, done first because it changes what gets built

Stage 3 asks for duplication to be found and consolidated. Three real ones, each
quoted from both sides rather than asserted. The project has done this once
already — `cfe7979`, twelve criteria for four facts — and the same shape is back.

### 2.1 The legal-length rule is stated twice, near-verbatim

TRD-2 **F-2**: *"`EmptyLTXVLatentVideo.length` is `step: 8`,
`WanSoundImageToVideo.length` is `step: 4`, and every `8n+1` is also `4(2n)+1` —
so **frames ≡ 1 (mod 8) is legal for both**. One rule, no per-model fork.
Verified against cerberus `/object_info`; both accept `max: 16384`."*

TRD-5 **`T5-10`**: *"The legal-length rule is shared: `EmptyLTXVLatentVideo.length`
is `step: 8`, `WanSoundImageToVideo.length` is `step: 4`, and every `8n+1` is
also `4(2n)+1` — so **frames ≡ 1 (mod 8) serves both**, one rule and no per-model
fork. Verified against cerberus; both accept `max: 16384`."*

**Owner: TRD-5 `T5-10`.** It is a renderer fact about two nodes' declared steps.
TRD-2 F-2 cites it and keeps only what is TRD-2's — that `T2-12a` rounds *to*
that rule when planning. TRD-3 `T3-7`'s note stays as it is: it already draws the
distinction that matters (the rule for what to **ask for** is not the rule for
judging an **already-rendered** clip, where the model's own step governs), and
that distinction is the one thing here that is not duplication.

### 2.2 The per-model ceilings are stated twice, with the same measurements

TRD-2 **W1-1** and TRD-5 **§5** both carry: LTX 15 s as a *cost* ceiling with
505 frames / 30.004 s and 1009 / 59.949 s on a 24 GB card and the 3.0-vs-12.4 s
superlinearity; and s2v 4.8125 s *provisional*, `LEN = 77` a choice not a node
limit, coherence past ~5 s unmeasured.

**Owner: TRD-5 §5**, which already says so — *"TRD-2 `T2-12` owns the criterion
… the **values** are renderer facts and belong here"* — and then TRD-2 keeps a
full copy anyway. TRD-2 W1-1 becomes a citation. **Two copies of a measured
number are free to drift**, and this project's own rule is that the second copy
is the defect, not the risk.

### 2.3 "How every criterion is verified" is restated in all seven documents

TRD-4 §8, TRD-5 §7, TRD-6 §8, TRD-7 §6 — plus TRD-1 §13, TRD-2 §10 and TRD-3 §11
— each restate the same four rules: a measurement that cannot fail is not
evidence; then mutate and read what the mutation did; a refusal or a presence is
half a criterion; `grep -c "^def test_"` before and after and never replace a
slice to end of file.

**This is exactly the shape `cfe7979` consolidated for the API rules.** Proposal:
**TRD-6 §0 gains §0.4, `T6-A7`…`T6-A10`**, and the other six cite it, keeping
only what is theirs — TRD-2 §10.3's recorded-fixture rule and TRD-3 §11.1's
both-directions rule are genuinely document-specific and stay.

Counter-argument, recorded because it is not obviously wrong: these restatements
are load-bearing *rhetoric* — a document that ends by telling you how to falsify
it is read differently from one that cites a rule elsewhere. **Recommendation:
consolidate anyway**, because the four rules are already drifting (TRD-1 §13 has
five numbered rules, TRD-5 §7 compresses them to a paragraph, and only three of
the seven mention the `grep -c` count), and drift is the thing one owner fixes.

### 2.3a The missing tables — found by asking what the review asked

TRD-1, TRD-2 and TRD-3 each end with **"The positive half of each one-sided
criterion"**: a table pairing every criterion of the form *"X is refused"* or
*"the payload carries Y"* with the case that must ALSO pass, because the first
form stays green when the whole feature is deleted.

    TRD-1  has one      TRD-4  none
    TRD-2  has one      TRD-5  none
    TRD-3  has one      TRD-6  none
                        TRD-7  none

All four of 4-7 *state the rule* — TRD-7 §6 even names one instance, that `T7-2`
needs the `g` refusal **and** the `xxx` success — and none of them enumerates its
own one-sided criteria. **The audit that produced those three tables was never
run over these four documents.** On a quick read the candidates include `T4-3`,
`T4-16`, `T4-17` (prohibitions that a deleted feature satisfies), `T5-6`, `T5-9`,
`T7-2` (named, not tabled), and most of TRD-6, whose §8 already warns that
*"every criterion here describes machinery that does not exist yet"*.

This is work, not commentary: ~20 criteria across TRD-1/2/3 were found this way
and each needed a positive case written.

### 2.4 Checked and NOT duplication

Recorded so it is not re-litigated. `T4-12` ↔ `T7-10` (slot naming: TRD-4 owns
the prompt rule, TRD-7 owns the anchor-path realisation), `T4-6` ↔ `T7-2` (save
path vs render path — different code, same policy), `T4-13` ↔ `T7-14` (the lock's
wording vs where it lives), TRD-4 §7 ↔ TRD-7 §5 (the second already cites the
first). All four boundaries are stated in the documents and hold.

## 3. The dependency graph

    T6-13a (songs.duration, one authority)  ->  TRD-2 T2-12a  ->  the whole clip-length chain
    T6-A1..A6 (inherited rules)             ->  everything, from the first line of new code

    TRD-7 view table (T7-1,T7-3,T7-5)  ->  T7-13 view:<key> prompts  ->  T7-19 per-view override
                                       ->  T4-18 composition test (it composes per view)
    T7-6 anchor-as-image1  ->  T7-7 identity differential  ->  T7-8 latent_mode=image
                           ->  T7-9 plate named
    TRD-5 A (same-res refine)  ->  T5-5 VRAM measured  ->  B, or T5-6 records why not
    TRD-6 §1-§6 (pull queue, lifecycle)  ->  nothing in 4/5/7 blocks on it

**`T6-13a` is the smallest item with the largest reach and it is not in anyone's
plan.** One column, `songs.duration`, written once from ffprobe on upload,
everything else reading it. TRD-1 §3.2, TRD-2 §3.4 and TRD-3 §4.4 all derive
from "the song's length" and none says where it comes from; they disagree in the
third decimal, which is enough to move a clip count at a boundary. It should be
built before `T2-12a`, which is the PRD's own P0.

## 4. Phases

Each phase names its criteria, the files it touches, and **the differential that
proves it** — because a phase whose completion test is "the code exists" is a
phase that can be reported done while doing nothing.

### Phase 0 — the document surgery §2 proposes

Added after review: §2 proposed four consolidations and **no phase did them**, so
the proposal would have sat as commentary. Docs only, no source.

- §2.1 TRD-2 F-2 becomes a citation of `T5-10`; §2.2 TRD-2 W1-1 becomes a
  citation of TRD-5 §5.
- §2.3 the shared verification rules move to **TRD-6 §0.4** and the other six
  cite it.
- §2.3a each of TRD-4/5/6/7 gains its positive-half table.

*Proof: `grep` for the LTX ceiling's measurements and for `≡ 1 (mod 8)` returns
one document each. That check can fail, which is the point of writing it.*

### Phase A — the view set becomes data (TRD-7)

`T7-1`, `T7-3`, `T7-5`. **`T7-2` is a precondition, not a deliverable** — it
landed on day 12 and the draft listed it as work. Files: `make_anchor.py`,
`app.py`'s view constants.

Everything downstream multiplies by the number of views, so a view set that
still lives in four hand-kept places makes every later phase four edits. `T7-2`
is already derived; `T7-1` finishes the job.

*Proof, and the order inside it is the point: **(a) the new view is reachable and
composes a sheet** — assert that first, because (b) alone is satisfied by a view
that never renders at all; (b) it is then refused at `g` with no gate edited;
(c) a test asserting the two `NUDE_VIEWS` agree goes red if a copy is
reintroduced. One test, three assertions, in that order. Tightened after review
caught that (b) was a refusal standing on its own.*

`T7-5` is the one to not skip: `BACKDROP` ends *"full body head to toe inside the
frame"*, which argues with a head-and-shoulders `portrait`. A prompt holding both
is the bare-skin-versus-fur contradiction in a new place, and day 4 measured what
that costs — two of three seeds rendered a human body with a cat's head by
cfg 7.0.

### Phase B — the four new prompt types (TRD-7 §4)

`T7-13` `view:<key>`, `T7-14` `backdrop`, `T7-15` `composite`, `T7-16` `pose`,
plus `T7-17` (composed by the real composer and visible in the preview),
`T7-18` (screened, and walked by the negation test) and **`T7-4`** — a view's
framing sentence is the *only* thing that differs between two sheets of one
tier. `T7-4` belongs here rather than in Phase A because it is the check that
keeps four types × ten views honest, and Risk 2 named it without scheduling it.
`T7-19` already landed (`415584d`). Files: `prompts.py` (`PROMPT_TYPES`, today 9
entries), `make_anchor.prompt_for`, the preview route.

`prompts.py`'s own docstring states the extension rule — *"adding a type here is
all that is needed to give it history"* — so this is small if `T7-13` is
generated from the view table rather than written per view. **`T7-18` is the
gate**: `_NEGATION_ALLOWED` is empty and the negation test walks every positive
constant with no exemptions, so a new type that says "no" fails the suite. That
is deliberate — *"no smoke"* put smoke on every sheet for the life of the
project.

*Proof, rewritten after review found the draft's version satisfiable by absence:
**mutate each type's stored text independently and assert that exact segment
moves**, in the preview and in the string sent downstream. "The preview shows
all four" passes on static labels; "deleting a type changes the composed string"
passes on a fallback. And the completion bar for `T7-18` is **red-before-green
per type** — the negation walker is green today because the four types do not
exist, so using it as the gate for adding them is the plan committing, inside
its own gate, the defect the plan is about. That was grok's sharpest finding.*

### Phase C — the identity lock (TRD-7 §3)

`T7-6` anchor-as-image1, `T7-7` the identity differential, `T7-8`
`latent_mode="image"`, `T7-9` the named plate, `T7-11` `lora_strength`,
`T7-12` w/h.

**`T7-6` is the largest single consistency lever in the studio and it is
unwired.** `gen_refs` passes a chosen anchor as image1 for every scene, which is
why clips stay on-model; the anchors UI conditions on uploaded photographs every
time, so sheet 2 is a fresh interpretation rather than a variation of the sheet
that was approved.

`T7-8` and `T7-9` are both "the editor promises what the renderer does not do" in
its mildest form: five of six denoise values are labelled *"on an anchor this
returns noise"* and are correct because `latent_mode` is pinned to `"empty"`; and
the second picked reference is silently promoted to the composition plate. One
resolver decides the label and the graph, or they disagree again.

`T7-11` and `T7-12` are independent of the `T7-6`→`T7-9` chain and can ship in
any order within the phase.

*Proof, two parts, because review found the draft had one.*

*(a) **`T7-8`/`T7-9` need their own differential** and the draft gave them none,
in a phase whose own text says the labels and the graph already disagree. One
resolver decides both, asserted from **both ends**: with `latent_mode="image"`
selected the denoise labels change AND the graph carries the image latent; with
it unselected the labels still say the value returns noise AND the graph does
not. Mutating either end alone must go red.*

*(b) **`T7-7` is human-judged and says so.** Render `front` and `three_quarter`
from an anchor and from the raw photographs, put the four side by side, and
record the answer to one question: is the anchored pair the same character as
each other more than the photograph pair is? No threshold is invented for it —
review asked for one, and a fake number on a judgement call is worse than an
honest human step. This is the criterion where **looking at the image** is the
method: the identity collapse, the world that never rendered and the LoRA that
did nothing all passed every deterministic check this project had.*

### Phase D — TRD-4's remainder

`T4-2`, `T4-3`, `T4-4` (differentials and refusals on the no-fallback rule),
`T4-7`, `T4-8`, `T4-9` (the save path's positive direction and the stored-text
re-screen), `T4-13` (the lighting differential), `T4-14`, `T4-15`, `T4-16`,
`T4-17`, `T4-18` (the composition test, six independent assertions).

`T4-13` is the criterion that reproduces the reported defect and **must fail
against a current render** — it is a differential on the rendered image's channel
balance, not on the string being present. It is also the one item in this plan
that is blocked on a render Jon has not made yet, and it must not be marked done
from the prompt text alone.

`T4-18` composes a front-nude XXX sheet for real. TRD-4 §6 gives the shape and
says explicitly it is to be **regenerated from the code, not pasted from the
document** — a sample in a document is stale the moment the constants move.

Phase D cannot start before Phase A: `T4-18` composes a sheet **per view**, so
the view table has to be data first. That edge was in the graph and not in the
phase.

### Phase E — refine on LTX (TRD-5)

`T5-1` (never a silent no-op), `T5-2` (the output differential), `T5-3` (denoise
< 1.0) and `T5-4` (a new file, never an overwrite — `T6-A5`, cited not restated)
are the build list; the draft named only `T5-1` and then used `T5-2` as its
proof, which both reviewers caught. Then variant **A** — same-resolution second pass,
no upsampler, no extra VRAM — per Jon's decision of 2026-08-13. Then `T5-5`:
measure peak VRAM **on the box it ran on**, beside the existing 23.4 / 23.9 GB
figure. Then B, or `T5-6` records in the catalogue that B does not fit and A
ships.

`--refine` on `ltx25` — the catalogue default — currently returns before the
refine block is reached and says nothing. The accepted-and-ignored shape, sitting
in the flag whose entire purpose is to change the output.

**Do not wire the WAN refiner to LTX.** It works for s2v only because s2v and
`wan22_i2v_low` share `wan_2.1_vae`; LTX has its own video VAE, and handing an
LTX latent to WAN is meaningless.

*Proof, split after review: **mean absolute pixel difference > 0 is the no-op
guard, not the quality claim.** It passes on noise, on a metadata perturbation,
on anything non-semantic — it proves `--refine` did *something*, which is exactly
`T5-1`. The quality claim needs a named metric on a fixed fixture set, moving in
a stated direction. `T5-2`'s own wording in TRD-5 conflates the two and should
be split there when that document is next opened.*

### Phase F — TRD-6, and it is the biggest

**DECIDED 2026-08-13 by Jon: the queue is rewritten in full.** Asked whether to
take only `T6-13a` and leave a queue that currently works alone, he chose the
whole pull model. So this phase is in scope rather than deferred, the §6 risk
about it costing more than it returns is accepted knowingly, and the ordering
below stands with `T6-13a` still first because the clip-length chain waits on it.

25 criteria describing machinery that does not exist. TRD-6 §8 says the thing
that must shape how it is built: **every criterion here specifies a test that
fails today**, so each one must be written as a red test first or the document
will be satisfied at scale by the absence of what it describes — the defect
`T3-6` and `T3-18` are already marked provisional for.

Order within it: `T6-13a` first and early (§3); then identity (`T6-8`…`T6-10`,
canonical paths and cascade policy, which everything else joins on); then
lifecycle (`T6-5`…`T6-7`, and **`T6-12`**, a repaired candidate linking back to
the expectation it was judged against — in no bucket in the draft); then the
pull queue (`T6-1`…`T6-4`); then concurrency (`T6-14`…`T6-16`). `T6-11`,
`T6-15` and `T6-17` are already satisfied; `T6-18` deletes nothing by design.

**`T6-13a` does not have to wait for the rest of Phase F**, and should not:
it is one column with a cross-document consumer. TRD-1 §3.2, TRD-2 §3.4 and
TRD-3 §4.4 all read "the song's length" and none says from where. **The
TRD-1-3 side of that handoff is unowned** — `docs/DDD-1-3-EDITING-AND-QUALITY.md`
§5.5's chain starts at `T2-12a` and assumes a duration it does not name. Whoever
takes `T2-12a` takes `T6-13a` with it.

### The obligation this plan will not discharge for you

Phases D and F together are ~30 criteria for which no per-criterion differential
is written here, and both reviewers said so. That is deliberate: **writing thirty
differentials into a plan is writing the tests in the wrong file.** What the plan
owes instead is the rule, stated once and binding on every phase above:

> A criterion is done when a mutation to the code it describes turns a check
> red, **and somebody read what the mutation actually did**. Not when the code
> exists, not when a string is present, not when a refusal fires — a refusal is
> half a criterion and needs its positive case.

This is the same bar `T6-A7`…`T6-A10` will carry once Phase 0 lands, and Phase F
is the phase most exposed to it: 25 criteria describing machinery that does not
exist can all be "satisfied" at once by never building it.

## 5. What this plan does not do

- **It does not schedule B's work, and here is how that binds.** Phases A-D are
  B's claimed files (`make_anchor.py`, `build_refs.py`, `studio/app.py`'s anchor
  routes, `_anchor_form.html`, `static/app.js`, `test_app.py`). B is executing
  TRD-4 and TRD-7 now and has already shipped `T7-19`, `T7-6` and the
  `ALBUM_FIELDS["body"]` fix from inside those phases. **The contract:** this
  plan is read by whoever holds the file, the ordering is a recommendation, and
  `SESSIONS.md` is where a disagreement gets settled before an edit — not after.
  Review asked for this to be written down and it was missing.
- **It does not start TRD-6's queue.** Nothing in 4/5/7 blocks on it, and it is
  the one phase that rewrites machinery that currently works.
- **It does not touch the negative prompt or fast/quality mode.** TRD-4 §5 owns
  them and nothing here moves them.
- **The criterion arithmetic, stated once because the draft contradicted
  itself.** §2.3 mints four ids — `T6-A7`…`T6-A10` — for rules that today exist
  as prose restated in seven documents. That is **+4 ids and −7 restatements**,
  and no behaviour is added: nothing is required that was not already required.
  §2.1 and §2.2 fold two duplicated statements into citations and remove no
  criteria at all. So: **72 for TRD 4-7 becomes 76**, and the count going up
  while duplication goes down is the honest description. The draft said "it adds
  no criteria" beside a section that added four, and both reviewers caught it.

## 6. Risks

1. **`T4-13` cannot be closed without a render**, and it is the criterion for the
   defect that prompted the whole prompt rewrite. Marking it done from the prompt
   text is the failure mode.
2. **Phase B multiplies with Phase A.** Four new prompt types × ten views is a
   lot of composed text, and `T7-4` (a view's framing sentence is the *only*
   difference between two sheets of one tier) is the check that keeps it honest.
3. **TRD-6 rewrites `jobs.py`, which works.** The pull queue is right and the
   current one is not broken. This is the phase most likely to cost more than it
   returns if it is started before 4/5/7 are done.
4. **Two documents still hold the same numbers** until §2 lands, and the numbers
   are measurements. That is the drift this project keeps paying for.

## 7. The consensus step

This plan goes to grok and chatgpt with the same brief shape that scored zero
fabrications twice: **UNSURE is an acceptable answer, NOTHING FOUND is an
acceptable answer, and no claim about the tree is accepted without being checked
against the tree.** What survives verification is folded in, and what does not is
recorded with its reason — `docs/reviews/` is where that lands.
