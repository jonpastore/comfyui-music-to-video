## 1. CONTRADICTIONS

- **Built count vs ids (TRD-4):** Section 1 says **5** built but lists six criterion ids as evidence: `T4-10`, `T4-5`, `T4-6`, `T4-1`, `T4-11`, `T4-12`.

- **TRD-6 existence claim:** Section 1 says TRD-6 is **4, partially** built (`T6-11`, `T6-4`, `T6-17`, `T6-15`). Phase F says *“24 criteria describing machinery that does not exist.”* Those cannot both be right without a sharper split of which machinery exists.

- **Phase E scope vs proof:** Phase E’s build list is `T5-1`, variant A, `T5-5`, B or `T5-6`. Its proof is **`T5-2`**, which is not named as a phase deliverable. Either `T5-2` is in the phase or it is not the phase proof.

- **§5 vs §2 on criterion count:** §5 says *“the 73 stay 73 minus what §2 folds”* and also *“It adds no criteria.”* §2.3 **adds** `T6-A7`…`T6-A10` while folding restatements out of other docs. Net count and “adds no criteria” need one rule.

- **UNSURE (external):** Whether quoted TRD-2 F-2 / TRD-5 `T5-10` / W1-1 text actually match the docs as claimed — not verifiable from this plan alone.

## 2. ORDERING DEFECTS

- **`T7-19`:** Dependency graph requires `T7-13` → `T7-19`. No phase includes `T7-19`.

- **`T7-4`:** Named in Risk 2 as the honesty check for Phase B × views; not in Phase A/B/C or any other phase. If it gates B, it must precede or ship inside B.

- **`T4-18`:** Graph ties it to the TRD-7 view table (Phase A). Phase order A→…→D is fine only if D may not start until A’s view table is done; that dependency is not stated inside Phase D.

- **`T6-A1..A6` → everything:** Graph says these bind *“from the first line of new code,”* but no pre-A phase lands or verifies them. If they are not already in-tree and binding, Phases A–E are unordered relative to their dependency.

- **`T6-13a`:** Correctly called out as before `T2-12a` / clip-length chain; it only appears inside Phase F (last). If any A–E work assumes song length authority, F is too late; if not, the “largest reach” claim should not block 4/5/7. **Measurement that settles it:** do Phases A–E code paths read `songs.duration` (or equivalent) at all?

- **Phase C internal:** Graph orders `T7-6` → `T7-7` → `T7-8` → `T7-9`. `T7-11` and `T7-12` are in the phase with no dependency edges.

## 3. CRITERIA THAT CANNOT FAIL

- **Phase C — `T7-8`, `T7-9`:** Phase text admits labels and graph already disagree (`latent_mode` pinned `"empty"`; second ref promoted silently). Phase proof only specifies `T7-7` (render + look). **No differential is stated that fails if labels change and the graph does not** (or the reverse). High risk of green-by-string-presence — the failure mode the phase itself describes.

- **Phase B — `T7-13`…`T7-16` existence:** Proof is preview shows four types + deleting a type changes the composed string. That does not fail if types are stubs, wrong, or not the real composer path; nor does it require each of backdrop/composite/pose/`view:<key>` to affect output distinctly. **`T7-18` as gate:** negation walking positives stays green if the four types are never added — absence satisfies the suite until types land; completion must require red-before-green per type, not only “negation still passes.”

- **Phase A — (a) “it renders”:** No stated signal that distinguishes a real new view from a fallback to an existing view or empty success. (c) copy-reintroduction going red is strong; (a)/(b) need the same mutate-and-read strength.

- **Phase D — non-`T4-13` items:** Only `T4-13` and `T4-18` get strong anti-absence language. `T4-2`…`T4-4`, `T4-7`…`T4-9`, `T4-14`…`T4-17` have no phase-level differentials named — same recurring hole the plan attributes to TRD-6.

- **Phase F:** Intent (“red test first”) is right; **no per-criterion differential is named.** At 24 criteria, that is the exact “satisfied by absence” pattern called out via `T3-6` / `T3-18`.

- **Section 1 “built” evidence (process risk):** Several build claims are presence/convention shaped (`WAL + MIGRATIONS convention` → `T6-17`; catalogue entry → `T5-8`; empty `_NEGATION_ALLOWED` → `T4-10`). Not necessarily wrong, but the same shape the plan warns against — treat as **UNSURE** until each has a mutate-and-read proof in the tree.

- **Phase E — `T5-2`:** Pixel MAD > 0 + sharpness direction is a strong pattern — **if** it is mandatory and wired to on/off refine. Good model for other phases.

## 4. CONSOLIDATION PROPOSAL (§2.3)

**Consolidate the four verification rules — yes. Owner `TRD-6 §0.4` / `T6-A7`…`T6-A10` — no.**

**Why fold:** The plan already records drift (TRD-1 §13 five rules vs TRD-5 §7 paragraph; `grep -c` only in some). That is the same defect class as §2.1/§2.2 and as `cfe7979`. Rhetoric that must be copy-pasted to stay true is how the copies diverge; citations plus document-local extras (`TRD-2 §10.3`, `TRD-3 §11.1`) preserve falsifiability without seven peers.

**Why not TRD-6:** These rules are process/meta for every TRD, not queue/lifecycle/storage behavior. TRD-6 is also the largest unbuilt surface and the phase the plan is most reluctant to start — a poor home for the stable “how we prove anything” canon. Putting canon in the doc most likely to be rewritten maximizes churn.

**Alternative:** One owner outside TRD-6 (e.g. TRD-1’s verification section, or a single shared rules section those TRDs already peer with). TRD-6 cites it like everyone else. **Measurement that settles owner:** after six months, count divergent edits to verification wording under TRD-6 ownership vs TRD-1/shared ownership; also count mistaken “TRD-6 blocked ⇒ can’t interpret pass/fail elsewhere.”

§2.1 and §2.2 (single owner for legal-length and ceilings) are right: **measured numbers and node step rules must not live in two places.**

§2.4 non-duplication list: no objection from plan text alone; **UNSURE** without the TRD boundary paragraphs.

## 5. WHAT IS MISSING

- **`T7-4` and `T7-19`:** implied by TRD-7 / graph / risks; no phase work or proof.

- **Most of TRD-5’s 12:** Phase E touches `T5-1`, A, `T5-5`, `T5-6`/(B), proof-mentions `T5-2`; `T5-8` marked built. No phase for the rest (e.g. whatever maps to `T5-3`, `T5-4`, `T5-7`, `T5-9`, `T5-10` as implementation vs citation, `T5-11`, `T5-12` — **only ids appearing in the plan text are safe to name; gap is “TRD-5 not covered by E + §1”).**

- **TRD-6 ids beyond the ordered buckets:** Phase F orders `T6-13a`, `T6-8`…`T6-10`, `T6-5`…`T6-7`, `T6-1`…`T6-4`, `T6-14`…`T6-16` plus built `T6-11`/`T6-17`/`T6-15`. Remaining TRD-6 criteria (document says 24) are not named in any phase.

- **Consolidation as work:** §2 is “done first” but has no phase, files list, or proof (e.g. other TRDs cite one owner; duplicate numbered rules gone; drift check).

- **§2.1 / §2.2 citation edits** in TRD-2 (F-2, W1-1) — ownership change with no phase.

- **Proof obligations for Phase D leftovers and Phase C `T7-8`/`T7-9`/`T7-11`/`T7-12`** — criteria named, differentials not.

- **Cross-session contract:** Lane B already executes TRD-4/7 on the named files while this plan is “not a work order.” Missing: how Phase A–D recommendations bind or avoid collision with in-flight B work.

- **UNSURE:** Anything in the four TRDs not cited by id in this plan (cannot inventory without the docs).

## 6. ANYTHING YOU WOULD CUT

- **Listing `T7-2` as Phase A work** when the same bullet says it already landed — keep as precondition, not deliverable.

- **“Look at them” as the sole stated proof for `T7-7`/Phase C** — keep human inspection as extra; do not cut the render differential, cut reliance on unaudited eyeballing for done.

- **Starting full TRD-6 rewrite before 4/5/7** — already deprioritized; I would cut it harder: ship `T6-13a` (+ proof) alone if length authority is truly cross-cutting; leave pull-queue rewrite out of this plan’s critical path entirely.

- **Duplicate measured ceilings / legal-length paragraphs** once owners land — cut second copies, not the measurements.

- **Nothing else cut from A–E scope** on plan text alone; under-coverage is the larger problem.
