# PRD · Identity, variations, rendering and the queue (TRD 4-7)

Status: written 2026-08-13. Covers `docs/TRD-4-CHARACTER-ANCHORS.md` (18),
`docs/TRD-5-CLIP-RENDERING-AND-REFINE.md` (10),
`docs/TRD-6-QUEUE-LIFECYCLE-AND-STORAGE.md` (25),
`docs/TRD-7-ANCHOR-VARIATIONS.md` (19) — **72 criteria**, counted not quoted.
Sequencing: `docs/PLAN-TRD-4-7.md`. Design: `docs/DDD-4-7-IDENTITY-AND-RENDERING.md`.
Sibling: `docs/PRD-1-3-EDITING-AND-QUALITY.md`.

This does not restate a criterion. It says who is served, what counts as
working, and what the four documents are collectively **for** — which none of
them says, because each was written to close a specific hole.

---

## 1. What these four are, together

TRD 1-3 are the surfaces where a human **decides**. These four are the machinery
that has to be trustworthy for those decisions to mean anything:

- **TRD-4 — who the character is.** The prompt that defines identity.
- **TRD-7 — how many ways you can ask to see them, and whether it is still
  them.** Variations on the same sheet-builder.

`T6-A1`'s named loop for these two, over JSON: save operator base photographs,
generate candidates for a named view, pick one, use that sheet as the next
identity lock (`test_t6_a1_anchor_loop_over_json`).
- **TRD-5 — the graph that turns a request into a clip**, and the refine pass
  that currently does nothing.
- **TRD-6 — the queue, the lifecycle, and what joins to what.** The plumbing
  every other document depends on and each one disowned.

**The single thread running through all four is identity.** An album is one
character seen from many angles across thirty-one songs, and every defect this
project has recorded most expensively has been that character quietly becoming
someone else: the identity collapse, the human body with a cat's head at cfg 7.0,
the ordinary woman by the halfway point keeping only the harness, "the character
in image 3 is reference 3" asserting a second person into a prompt that says
there is one.

## 2. Who it is for

The same single operator on a tailnet as TRD 1-3, doing a different job. Here
they are not judging a result — they are **specifying a character precisely
enough that a diffusion model cannot drift**, then asking for that character
repeatedly and cheaply.

What they need from these four, in their own terms:

1. *"Give me this character from another angle, and have it still be her."*
2. *"Let me tune the words that make her her, and keep the version that worked."*
3. *"Don't let me save something the tier forbids, or ask for something that
   cannot render."*
4. *"Tell me what is running, where, and whether it is actually alive."*
5. *"Show me, on each candidate, how well it matches the base photographs
   and the prompt I asked for — then I pick. A repaired sheet is a new
   candidate with its own score. An `h_reroll` dest, an approved repair
   dest, and a standalone refine dest are scored the same way. Per-clip
   refs score against the chosen anchor as identity bases, not a standing
   plate or the broken source. If scoring could not run, name the xAI or
   local failure; do not shrug 'unknown'. Confidence is the worse of
   identity and pose, not an average that can read 95% on a human-faced
   two-tail sheet."*
   (`T3-31`, `T4-19`)
6. *"I have sixteen clothed pose photographs. I name each one, assign a
   tier or generate a tier version, and the identity pair stays the
   identity pair. Base cards look like candidate cards without render
   data."* (`T7-20`)

## 3. The product rules

Four, and each is a thing that was learned by paying for it.

**3.1 A diffusion model has no NOT.** Day 8's rule, and day 11 removed the last
exception to it. *"No smoke"* put smoke on every sheet for the life of the
project; *"no garments, no underwear, no straps"* put a leather harness on a nude
sheet. Every positive constant is walked by a test with no exemptions, and a new
prompt type that says "no" fails the suite — deliberately.

**3.2 Identity comes from the text, not from the reference image.** Measured with
a one-variable differential: same reference, same seed, same box; the species
named in the prompt gives a feline throughout, unnamed gives an ordinary human
woman by the halfway point. This is why `T3-28` forbids "swap the reference
image" as a remedy and why `T2-32`'s refusal message has to say so — a studio
that suggests the wrong fix teaches the operator the wrong lesson. The
storyboard side is `T2-31`: `write_storyboard` / `save_scene` refuse an
empty `character_reference` and name that identity comes from the text.
The QC side is `qc.check_identity_wrong`: the proposed remedy is edit the
text, then re-render, and a swap-the-reference wording is refused on
record, edit and approve.

**3.3 Two clauses that contradict each other do not average — the model picks.**
Day 4 measured it: the nude clause asserted bare skin beside "entire body covered
in jet-black fur", and a fixed-seed sweep watched the model resolve towards skin
*harder* as guidance rose. Every new view, every new prompt type and every
per-album override is a new chance to write a contradiction, which is why `T7-5`
(portrait vs "full body head to toe") is called out by name. The string omit is
not enough: the portrait crop is measured on the image (`subject_bottom`), and
head-to-toe must not win the ranking against a head-and-shoulders fixture.

**3.4 Accepted-and-ignored is the defect class.** `--refine` on the default video
model returns before the refine block and says nothing. Five of six denoise
values are labelled *"on an anchor this returns noise"* and are correct because
`latent_mode` is pinned. A dropdown documenting its own uselessness is the mild
form; a flag whose whole purpose is changing the output doing nothing silently is
the severe one.

## 4. What "working" means

| # | outcome | proven by |
|---|---|---|
| P1 | A sheet cannot be produced from a silent default — no tier, view, or wardrobe falls back to something nobody chose | `T4-1`…`T4-4` |
| P2 | Text that a tier forbids cannot be saved under it, and text it permits can | `T4-5`…`T4-9` |
| P3 | The composed positive prompt contains no negation, names the body parts, names the reference slots, and never says "bare skin" on a furred character | `T4-10`…`T4-14`, `T4-18` |
| P3a | Lighting lock is channel balance on the rendered sheet (olive/magenta FLAG, grey PASS), not the `BACKDROP` string. Job 257 `front_nude` seed 5151 PASSes 8.06; sibling seed 5288 still FLAGs 14.76 | `T4-13` |
| P4 | A new view is one table entry, and is tier-gated by what it *is* rather than by a list somebody remembered to update | `T7-1`/`T7-2` built (`make_anchor.VIEWS` + `is_nude_view`). `T7-3` (measured new-view renders) remains |
| P5 | An approved sheet can be the identity lock for the next sheet — the lever that keeps clips on-model, applied to anchors | `T7-6`…`T7-8` |
| P6 | The four things that shape every sheet — view framing, backdrop, composite, pose — are versioned, per-album prompts rather than code constants | `T7-13` built (`view:<key>` from the view table). `T7-14`/`T7-15`/`T7-19` built. Album `pose` row in `T7-16` remains |
| P7 | `--refine` either refines or refuses, and whether it helps is measured rather than assumed | `T5-1`…`T5-6` |
| P7a | A ×2 clip among 832×480 siblings assembles at 1664×960 with no silent letterbox; mixed aspect is refused | `T5-7` |
| P7b | Each clip ceiling is labeled measured or chosen; an over-long single-clip request is refused or split, not only annotated | `T5-9` |
| P7f | A long LTX scene is a chain whose successor graph uses `LTXVAddGuide` so the first frame is the predecessor's last | `T2-10` |
| P7c | Refine-on vs refine-off is judged on decoded frames (MAD > 0, sharpness up), not graph nodes. Missing measurement fails closed. GPU pair still NOT MEASURED | `T5-2` |
| P7d | If LTX variant B does not fit, that is a recorded finding on `ltx25` and `--refine` ships A; the upsampler is never dropped silently | `T5-6` |
| P7e | Peak VRAM of shipped refine variant A is measured on the box, or fail-closed `NOT MEASURED`. Copying the base 23.4/23.9 figure onto `refine_peak` is a quote, not a reading | `T5-5` |
| P8 | Work is pulled, not assigned; "ready" is not "queued"; every artefact's state transition is a row with a time. A re-render, refine, repair or anchor re-roll lists both candidates and either is selectable | `T6-1`…`T6-7`, `T6-A5` |
| P9 | Every artefact can be joined to what was asked of it, by one canonical path | `T6-8`…`T6-13a` |
| P10 | A killed worker leaves no half-written job; a long render does not hold the write lock | `T6-14`…`T6-16` |

**P5 is the highest-leverage unbuilt thing in the studio** — and it moved while
this was being written. `gen_refs` passes a chosen anchor as image1 for every
scene, which is *why clips stay on-model*; the anchors UI had no such path, so
sheet 2 was a fresh interpretation of the photographs rather than a variation of
the sheet that was approved. Session B shipped `T7-6` on 2026-08-13 (`d315c6f`).
`T7-7` — does it actually hold identity across views — now has the offline
ranking harness: `t7_7_identity_differential` on a rendered front /
three_quarter pair versus the same pair from the raw photographs. No
threshold. The GPU four-image set is still NOT MEASURED. The
photo-conditioned half is on disk (Catatonic jobs 244/248: a front /
three_quarter pair of the identity-collapsed human woman, not her;
Street Cats jobs 264/268: `front_nude_s1943749893` +
`three_quarter_nude_s1096561198`; 262 cancelled). Both used base
photographs, not a chosen anchor as image1. The use-as-ref half has
never been rendered. `t7_7_claim` refuses unpinned bytes.
The compose hook FLAGs a human-body nude compose, including the
live-studio "Human woman's body" clause, through `run_artefact`. That is
not the picture measurement.

## 5. Priorities

Full ordering and dependencies are `docs/PLAN-TRD-4-7.md` §3-§4. The product-level
statement of it:

1. **Make a view cheap** (P4). `T7-1`/`T7-2` landed: one `VIEWS` table, nudity
   derived. Everything downstream still multiplies by the number of views;
   `T7-3` (those views as measured renders) is what is left.
2. **Make the words editable and versioned** (P6). The operator's real loop is
   tune-render-compare. `view:<key>` (`T7-13`), `backdrop` and `composite` are
   versioned; the leftover is the album `pose` row (`T7-16`).
3. **Prove identity holds** (P5's `T7-7`). One measurement, and it is a
   human-judged one.
4. **Finish TRD-4's remainder** (P1-P3), most of which is differentials for
   behaviour that already exists.
5. **Make `--refine` honest** (P7).
6. **The queue — CORRECTED.** An earlier draft of this line said "last, except
   `T6-13a`". **Jon decided 2026-08-13 to build TRD-6 IN FULL**: the pull model,
   the lifecycle and the identity rules are all in scope, and `T6-13a` still goes
   first *inside* it because the clip-length chain waits on that one column.
   `PRD-1-3` §6.0 carried this decision and this file did not — **two documents
   disagreeing about scope on the same day**, found by the first external review
   of this layer.

## 6. Scope

**In:** the four documents' 72 criteria, plus the four consolidation items in
`PLAN-TRD-4-7` §2 that give a duplicated rule one owner.

**Out, with the owner named:** the timeline, the arc, QC's tiers and repair
(TRD 1-3). The negative prompt and fast/quality mode (TRD-4 §5 owns them and
nothing here moves them). Garbage collection (`T6-18` deletes nothing by design).

**Not building**, cited not restated: no IP-Adapter / InstantID / ReActor
(TRD-4 §7, TRD-7 §5 — a multi-image edit model conditions natively); no second
graph or workflow builder (TRD-7 §1 — the anchor path already runs
`build_refs.workflow()`); no WAN refiner on LTX output (TRD-5 §1 — they do not
share a VAE); no forecast scheduling, no second queue, no distributed
coordinator (TRD-6 §7).

## 7. Risks

1. **The specification drifts from the code faster than it can be written.**
   Demonstrated rather than feared: the plan's built-ledger was stale within the
   hour, three commits landed mid-review, and `T4-10`/`T4-11` were documented as
   done while `ALBUM_FIELDS["body"]`'s default still carried the negation that
   actually rendered. **Any built-state claim is worth re-reading before acting
   on it.**
2. **A criterion satisfied by absence.** TRD-6's 25 criteria describe machinery
   that does not exist and can all go green at once by never building it — its
   own §8 says so. TRD-4/5/6/7 have no one-sided-criteria tables, while TRD-1/2/3
   each do.
3. **Prompt surface area grows faster than the checks on it.** Four new types ×
   ten views is a lot of composed text, and every combination is a chance at
   §3.3's contradiction. `T7-4` is the check that keeps it honest: two views of
   one tier compose to the same remainder but for the framing clause (and the
   nude wardrobe swap). The compose-diff is `studio/test_t7_4_framing.py`.
4. **Two sessions in one tree.** B holds every anchor source file. The plan is a
   recommendation to whoever holds the file, and `SESSIONS.md` settles a
   disagreement *before* an edit.

## 8. Open, and needing Jon

- **`T4-13` is measured on a current GPU sheet.** Job 257 Street Cats xxx
  `front_nude` seed 5151 PASSes backdrop olive 8.06 (limit 12). Sibling seed
  5288 on the same prompt still FLAGs 14.76 — the lock is seed-dependent, not
  closed for every candidate. `BACKDROP` is still not the proof.
  `T4_13_REAL_SHEET_MEASURED` is True only for sha256 `ac56dc72…238f1b`.
- **`chosen` is 0 on every anchor.** Same blocker. No prompts are invented for it.
- ~~Whether TRD-6 gets built at all this cycle.~~ **DECIDED: in full.** Struck
  rather than deleted, because the argument against it is still true — 25
  criteria rewriting machinery that currently works — and it was heard and
  overruled. Worth having in front of whoever finds it expensive later.
