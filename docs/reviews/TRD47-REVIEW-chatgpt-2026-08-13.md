1. ONE-SIDED CRITERIA

Criteria here that would stay green if the feature were deleted or never built, with the positive half that should also pass:

- TRD-4 `T4-1`
  - One-sided half present: refusal on zero views selected.
  - Why deletion stays green: if generation is removed or the path always refuses, this can still pass.
  - Positive half needed: with at least one valid view selected, generation proceeds and does not refuse for missing views.

- TRD-4 `T4-3`
  - One-sided half present: “No fallback … exists anywhere on the anchor path” asserted via refusal on empty selection.
  - Why deletion stays green: a deleted anchor path has no fallback.
  - Positive half needed: valid non-empty tier/view selections are accepted and produce jobs using exactly the selected values.

- TRD-4 `T4-4`
  - One-sided half present: refusal names which control is empty.
  - Why deletion stays green: a path that always refuses could still emit those messages.
  - Positive half needed: when both controls are populated, submission succeeds without those refusal messages.

- TRD-4 `T4-6`
  - One-sided half present: explicit sexual content or full nudity under `g` or `pg13` is refused.
  - Why deletion stays green: a save path that refuses everything satisfies this.
  - Positive half needed: same save path accepts text that complies with `g`/`pg13`, and `T4-7` covers the cross-tier case for the same text.

- TRD-4 `T4-9`
  - One-sided half present: tier wording gets the same treatment.
  - Why deletion stays green: if `/anchors/tier-wording` save is removed or always refused, unsafe text is still “blocked”.
  - Positive half needed: compliant tier wording saves successfully and is stored/retrieved on that path.

- TRD-4 `T4-14`
  - One-sided half present: nude view never says “bare skin” on a furred character.
  - Why deletion stays green: if nude views are deleted, criterion stays green.
  - Positive half needed: nude view still composes and renders with the intended nude positive wording for a furred character, with wardrobe wording dropped but the feature present.

- TRD-4 `T4-16`
  - One-sided half present: negative list unchanged and nothing from it moves into the positive text.
  - Why deletion stays green: if the negative prompt is deleted entirely, then nothing moved from it.
  - Positive half needed: the negative list is still actually present and applied in quality mode as intended.

- TRD-4 `T4-17`
  - One-sided half present: negative is dropped in fast mode.
  - Why deletion stays green: if the negative prompt is deleted in all modes, fast mode still “drops” it.
  - Positive half needed: in quality mode the negative prompt is present and used.

- TRD-5 `T5-1`
  - One-sided half present: `--refine` with `ltx` or `ltx25` either adds a second pass or raises naming the reason.
  - Why deletion stays green: always raising would satisfy the refusal half.
  - Positive half needed: at least one supported refine path actually succeeds and produces a non-identical refined graph/output.

- TRD-5 `T5-6`
  - One-sided half present: if B does not fit, that is recorded and A ships.
  - Why deletion stays green: B can simply never exist and be recorded as not fitting.
  - Positive half needed: A actually exists, is selectable/invoked by `--refine`, and changes output.

- TRD-6 `T6-3`
  - One-sided half present: `False` is a refusal, `None` is a candidate.
  - Why deletion stays green: if capability matching never schedules anything, all hard refusals remain respected.
  - Positive half needed: `None`-candidate jobs are still queueable/dispatchable to candidate boxes rather than treated as refusal.

- TRD-6 `T6-4`
  - One-sided half present: workflow a box refused does not requeue.
  - Why deletion stays green: if jobs never run or everything stays unscheduled, no refused workflow requeues.
  - Positive half needed: a job lost because a box vanished does requeue and later runs elsewhere.

- TRD-6 `T6-9`
  - One-sided half present: file that disappears after its row exists is detected, not reported as passing.
  - Why deletion stays green: if QC never runs on missing files, it may still avoid “passing”.
  - Positive half needed: existing files do proceed through QC normally rather than all being treated as missing findings.

- TRD-6 `T6-10`
  - One-sided half present: deleting a song does not silently orphan its clips, refs and findings.
  - Why deletion stays green: refusing song deletion entirely would avoid silent orphaning.
  - Positive half needed: song deletion has an explicit implemented policy that is exercised and leaves no silent orphans.

- TRD-6 `T6-13`
  - One-sided half present: with no recorded expectation, QC skips those comparisons and never infers a baseline from the file itself.
  - Why deletion stays green: if expectation recording is absent everywhere, all such checks skip.
  - Positive half needed: when expectation is recorded, those comparisons actually run against it and can fail.

- TRD-7 `T7-2`
  - One-sided half present: a new nude view omitted from gating is still refused at `g`.
  - Why deletion stays green: if new nude views are impossible to add or all views are refused, this stays green.
  - Positive half needed: the same nude view succeeds under an allowed tier such as `xxx`, with the correct nude composition.

- TRD-7 `T7-8`
  - One-sided half present: when `latent_mode="image"` is not selected the denoise labels still say the value returns noise.
  - Why deletion stays green: if `latent_mode="image"` is never implemented, the “not selected” half can still pass.
  - Positive half needed: when `latent_mode="image"` is selected, denoise becomes effective in the graph and labels change accordingly.

- TRD-7 `T7-9`
  - One-sided half present: “the second is not silently promoted to image2”.
  - Why deletion stays green: if multiple references or `base` are removed, nothing is silently promoted.
  - Positive half needed: either an explicit plate slot exists and drives image2, or `make_anchor` truly stops assigning a base and rendering still works in that declared shape.

- TRD-7 `T7-10`
  - One-sided half present: `"the character in image 3 is reference 3"` is refused by a test.
  - Why deletion stays green: if third-reference support is deleted, the bad string never appears.
  - Positive half needed: three-reference prompts still compose successfully with image 3 described as the third view/reference of the same character, not a second person.

- TRD-7 `T7-18`
  - One-sided half present: every new type is screened and walked by the negation test.
  - Why deletion stays green: if the new prompt types are never added, there is nothing unscreened.
  - Positive half needed: those new types actually exist, are composed, previewed, and the screens/tests cover them.

2. CONTRADICTIONS

- TRD-4 restates inherited TRD-6 rules instead of citing them.
  - Restatements found:
    - `T4-4`: message/refusal shape, though not obviously one of `T6-A1..A6`; UNSURE whether you want this flagged as inherited.
    - `T4-7` says “Both directions or the criterion certifies a save path that refuses everything.”
    - `T4-18` says “each able to fail on its own.”
    - §8 restates both project-level rules verbatim: “A measurement that cannot fail is not evidence; a refusal or a presence is half a criterion…”
  - Strongest definite restatement against TRD-6 §0: `T4-15`/`T4-18` do not seem to cite `T6-A5` when “new candidate, never overwrite” is relevant elsewhere; this is weaker. Main definite issue is §8 restatement of inherited test-rule text.

- TRD-5 restates inherited TRD-6 rules instead of citing them.
  - `T5-4` restates `T6-A5`: “still a new file, never an overwrite.”
  - §7 restates inherited rules: “A measurement that cannot fail is not evidence … A refusal or a presence is half a criterion.”

- TRD-7 restates inherited TRD-6 rules instead of citing them.
  - §6 restates inherited rules: “A measurement that cannot fail is not evidence; a refusal is half a criterion…”
  - `T7-2` itself explicitly embeds the inherited “refusal needs positive case” rule rather than citing it.

- TRD-4 vs TRD-7 ownership seam is intentionally split, but there is an internal tension:
  - TRD-4 §1a says `T4-12`’s slot naming has its anchor-path realisation in `T7-10`, and “neither document restates the other”.
  - But TRD-4 `T4-12` itself specifies reference-slot naming in general, while TRD-7 `T7-10` specifies slot names on the anchor path.
  - This is not a contradiction, but there is overlap in owned requirement text. UNSURE whether you want this counted under contradictions or boundary defects.

- TRD-7 §4 says three things are “code constants with no history and no per-album override”, including view framing, and `T7-13`/`T7-14`/`T7-15` make them versioned prompts.
  - TRD-4 `T4-15` says an album profile still overrides `identity`, `wardrobe`, `body`, `nude_wardrobe` and `anatomy`; constants are defaults, not policy.
  - No direct contradiction, but if `backdrop` and `composite` become versioned prompt types and remain “untiered”, the document set does not clearly state whether they are also per-album. `T7-15` says “nobody can tune per album” today, implying they should be tuneable; `T7-13` only says versioned. This is a missing decision more than a contradiction.

- TRD-6 `T6-13` says no expectation means QC skip.
  - TRD-6 `T6-9` says a file disappearing after its row exists is a finding, not a skip.
  - Not a contradiction if one concerns missing expectation and the other missing artefact, but the decision boundary is close enough that an implementation could conflict. Measurement to settle: matrix of {file present/missing} × {expectation present/missing} with expected outcome per cell.

3. BOUNDARY DEFECTS

- TRD-4 `T4-6` and TRD-7 `T7-2` both claim tier/nudity gating on different seams of the same behavior.
  - TRD-4 owns save-path gating of prompt text against tier.
  - TRD-7 owns render-path derivation of whether a view is nude.
  - Boundary defect: the same user-visible failure “nude content under `g`” is split across save-time text policy and render-time view classification. A feature can pass one and fail the other, and each document can claim the other seam. This is already partly acknowledged in TRD-4 §1a.

- TRD-4 `T4-12` and TRD-7 `T7-10` both claim slot naming.
  - Work overlap: generic reference-slot naming vs anchor-path slot naming.
  - Risk: duplicate implementation or duplicate tests on the same prompt fragment.

- TRD-4 `T4-13` and TRD-7 `T7-14` both claim the lighting/backdrop lock.
  - TRD-4 owns “positive lighting lock”.
  - TRD-7 says `backdrop` becomes versioned prompt type and that `T4-13`’s lighting lock lands inside it.
  - Boundary defect: one document owns the behavior, the other owns the storage/versioning vehicle. If `backdrop` is not migrated, `T4-13` can be “implemented” in constants; if migrated without the lock, `T7-14` can pass while defect remains.

- Possible disowned behavior: anchor prompt preview after new types/logic.
  - TRD-7 `T7-17` says new types appear in `anchor_prompt_preview`.
  - TRD-4 owns how positive prompt is built.
  - No criterion here clearly owns preview parity for existing TRD-4 components such as `T4-13` lighting lock or `T4-14` nude wording beyond the new types. UNSURE, but this looks like a seam where preview could drift from composer and each document only partially covers it.

- Possible disowned behavior: persistence/history semantics for new prompt types.
  - TRD-7 adds `view:<key>`, `backdrop`, `composite`, `pose`.
  - TRD-6 owns storage/lifecycle generally, but none of these four documents clearly owns migration/storage semantics for those prompt history rows beyond “becomes a type”.
  - Measurement to settle: after adding/editing each new type, is prior version reachable and is the currently composed prompt reproducible from stored versions? If no document covers that, this is a gap.

4. DECISIONS THAT LOOK WRONG

- TRD-5 decision: “Ship A, measure before B.”
  - Alternative: measure B first before deciding A is the shipping path, because B is described as “the only one that adds detail rather than redistributing it.”
  - Measurement that would settle it: same seeds/scenes, compare A vs B on sharpness/detail metrics and human review, alongside peak VRAM and runtime on cerberus.

- TRD-6 decision: `songs.duration` as sole authority written once from ffprobe on upload.
  - Alternative: define authority as decoded duration if downstream clip counts depend on actual sample length rather than container metadata.
  - Measurement that would settle it: compare ffprobe-derived duration, decode length, and the actual boundary clip-count outcomes on songs near the frame-count threshold; choose the source with the fewest off-by-one clip-count errors.

- TRD-7 decision in `T7-9`: “Either the form has a plate slot or `make_anchor` stops assigning one.”
  - Alternative: keep implicit promotion only if the UI explicitly labels and confirms which picked reference will be used as plate.
  - Measurement that would settle it: user-error rate / mismatch rate between intended and actual composition when selecting multiple references under the three options {silent implicit, explicit labelled implicit, dedicated plate slot}.

- TRD-7 decision to make `portrait` override the head-to-toe clause (`T7-5`).
  - Alternative: split `BACKDROP` into orthogonal clauses so portrait does not need to override a mixed constant.
  - Measurement that would settle it: prompt diffability and render consistency across portrait/full-body views, plus number of contradictory prompt combinations still possible after the change.

- TRD-4 decision in `T4-11`: body colouring must be “a pure positive assertion naming the parts.”
  - Alternative: allow either part list or another wording proven to reduce two-tone artefacts.
  - Measurement that would settle it: fixed-seed render comparison of candidate phrasings on the reported colouring defect rate.

5. WHAT IS MISSING

- TRD-4/7 imply a composed prompt path and preview path must stay identical, but no criterion clearly covers parity for the full existing prompt, only `T7-17` for new types.
  - Missing behavior: preview must equal the real composed prompt used for render, not a near-copy.

- TRD-4 `T4-5` says save uses the same guardrail the render runs, but no criterion covers what happens if the render-time guardrail changes after a prompt was saved.
  - Missing behavior: whether previously saved text is revalidated at render time and how mismatch is handled.

- TRD-5 `T5-2` requires refine-on/off outputs differ and sharpness improve, but no criterion covers preserving scene semantics/content.
  - Missing behavior: refine should not materially change prompt adherence, timing, or conditioning identity while improving detail.

- TRD-5 `T5-7` covers geometry normalization if B ships, but if A ships there is no criterion for assembly compatibility beyond “new file, never overwrite.”
  - Missing behavior: refined clips from A still integrate into assembly with expected duration/fps/audio sync.

- TRD-6 lifecycle diagram includes `approved -> repaired`, but no criterion here covers who/what creates the repaired candidate row or links approval/finding/repair causally beyond `T6-12`.
  - Missing behavior: complete relational chain from finding to approved repair candidate to re-check result.

- TRD-6 `T6-5` records every transition with time, but no criterion covers monotonicity or legal transition order.
  - Missing behavior: impossible transitions like `planned -> running` or timestamp regressions.

- TRD-6 `T6-18` defers garbage collection, but no criterion covers how unreachable-but-retained artefacts remain reachable under `T6-A5`.
  - Missing behavior: history listing/selectability for predecessor artefacts over time.

- TRD-7 `T7-6` says chosen anchor used as identity reference with “same file, no copy,” but no criterion covers what happens if that anchor file is later moved/deleted.
  - Missing behavior: stability of anchor-as-reference rows against file lifecycle.

- TRD-7 `T7-11` makes `lora_strength` settable, but no criterion covers how the UI communicates the cfg interlock that forces it to 0 unless explicitly passed.
  - Missing behavior: operator-visible truthfulness of controls, analogous to the denoise-control defect called out in §1.

- TRD-7 `T7-19` requires per-view prompt override or narrowing the edit box, but no criterion covers migration of existing per-tier edited prompts.
  - Missing behavior: what existing saved edits mean after the UI/data model change.

If you want, I can reformat item 1 into a strict two-column “criterion / missing positive half” table only.
