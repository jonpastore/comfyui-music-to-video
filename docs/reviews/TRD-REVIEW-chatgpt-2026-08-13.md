## 1. CONTRADICTIONS BETWEEN the three documents

### 1.1 Duplicate ownership / duplicated specification across documents
- **Set-duration tolerance / check specified in both TRD-1 and TRD-3**:  
  - TRD-1 `T1-7` specifies rendered set duration must match `mixer.set_duration()` within `mixer.SET_DURATION_TOLERANCE`.  
  - TRD-3 `T3-11` specifies the same check on artefacts, same owner constant.  
  This is not a not-X conflict, but it is the **same fact/check specified in two places**. The docs themselves acknowledge shared ownership in TRD-1 §11 and TRD-3 §9.

- **Loudness measurement ownership / use specified in both TRD-1 and TRD-3**:  
  - TRD-1 `T1-25` says export writes integrated loudness and true peak, with measurement owned by `effects.py`.  
  - TRD-3 §4.3 and `T3-9`/audio tier also rely on the same `effects.py` loudness measurement.  
  Again, not a conflict, but **the same fact is specified in two documents**; both docs acknowledge this in TRD-1 §11 and TRD-3 §9.

### 1.2 Ownership boundary tension on chain readiness / scheduler
- **UNSURE**: TRD-2 `T2-11` says “TRD-2 owns this rule, not the scheduler,” while TRD-1 §11 and TRD-3 §9 both disown the general queue/scheduler. This may now be intentional and non-conflicting, but it still leaves a split where:
  - TRD-2 `T2-11` owns a readiness rule for chained clips,
  - TRD-1 §11 disowns the queue and wait-state scheduler,
  - TRD-3 §9 disowns the queue and scheduler.
  I do **not** count this as a contradiction because TRD-2 narrows ownership to the `depends_on` readiness rule, but it is close enough to merit **UNSURE** scrutiny.

## 2. ACCEPTANCE CRITERIA THAT CANNOT FAIL

### TRD-1
- **NOTHING FOUND**

### TRD-2
- **T2-5** — mutation: **delete “restore” capability, keep version creation and retrieval of old versions**.  
  Criterion text: “Editing an arc prompt creates a new version; the previous version is retrievable and restorable.”  
  As written, unless the test explicitly exercises restore, it can pass with restore deleted by only checking new-version creation and retrieval. No mutation-to-fail is named.  
  Section: TRD-2 §3.3, criterion `T2-5`.

- **T2-6** — mutation: **delete version deletion entirely or make delete a no-op**.  
  “Deleting a version does not renumber the others.” If deletion is removed/refused/no-op, there is no renumbering, so the criterion can stay green unless it first asserts that a delete actually occurred.  
  Section: TRD-2 §3.3, criterion `T2-6`.

- **T2-7** — mutation: **store dummy/static values for model and timestamp, independent of actual generation**.  
  “A version records which model produced it and when…” This can pass with non-functional provenance if the check only asserts fields exist. The criterion does not name a differential that proves the values are correct.  
  Section: TRD-2 §3.3, criterion `T2-7`.

- **T2-12** — mutation: **hardcode any parseable measurement record unrelated to the actual ceiling constant**.  
  The criterion requires that a record exists and parses. It does not require the stored measurement to match the ceiling value used by code, so the measurement/constant link can be broken and still pass.  
  Section: TRD-2 §3.4, criterion `T2-12`.

- **T2-18** — mutation: **return static/hardcoded limits/guardrails not actually used at generation time**.  
  The criterion only requires the limits and guardrails be present in the same API response. It does not prove they are the ones actually applied.  
  Section: TRD-2 §4.2, criterion `T2-18`.

- **T2-33** — mutation: **have the picker call `models.renderable(role)` but ignore its result or post-filter to a stale fixed list**.  
  The criterion says the picker reads `models.renderable(role)`, but unlike `T1-8`/`T2-41` style differentials, it does not specify a mutation/differential proving catalogue changes reach UI behavior.  
  Section: TRD-2 §6, criterion `T2-33`.

- **T2-34** — mutation: **show all models as unavailable**.  
  “A model that is catalogued but unavailable on every reachable backend is shown as unavailable rather than offered.” This can pass if the system marks everything unavailable, including actually available models, unless there is a paired positive case.  
  Section: TRD-2 §6, criterion `T2-34`.

- **T2-36** — mutation: **return help text payload but never use it anywhere**.  
  The criterion requires help text to be carried in the API response and warnings marked, but the feature can be effectively deleted from clients and still pass.  
  Section: TRD-2 §7, criterion `T2-36`.

- **T2-37** — mutation: **include album arc in playlist payload but never show/consume it**.  
  The criterion only asserts payload presence. The row/show behavior described in prose can be deleted and this still passes.  
  Section: TRD-2 §7, criterion `T2-37`.

### TRD-3
- **T3-1** — mutation: **delete all grouping/reporting except a synthetic “unattributed” bucket count**.  
  The criterion only states that per-box report groups by `host` and NULL-host artefacts appear in an “unattributed” bucket. A crippled report with almost no useful grouping could still pass if it preserves those surface conditions.  
  Section: TRD-3 §2.1, criterion `T3-1`.

- **T3-4** — mutation: **populate `measured`, `expected`, `unit` with nonsense/default values for any quantitative check**.  
  The criterion requires those fields be recorded, not that they be correct. The explanatory sentence says why they matter, but the acceptance test as written can pass with bogus contents.  
  Section: TRD-3 §3, criterion `T3-4`.

- **T3-6** — mutation: **disable repair generation entirely so `repair_path` is always NULL/non-equal**.  
  “A finding's `repair_path` is never equal to its `path`.” If repairs are deleted, this remains trivially true unless the test first asserts a repair was produced.  
  Section: TRD-3 §3, criterion `T3-6`.

- **T3-14** — mutation: **delete threshold configuration UI/API entirely**.  
  “Attempting to set one with no calibration row is refused…” If no threshold can ever be configured because the feature is absent, the refusal still satisfies the criterion.  
  Section: TRD-3 §5, criterion `T3-14`.

- **T3-20** — mutation: **store remedy prompt in `prompts.py` version table but delete any use of it in actual repair execution**.  
  The criterion checks versioning/storage rules, not that the stored version is the one actually used when repair runs.  
  Section: TRD-3 §6, criterion `T3-20`.

- **T3-22** — mutation: **never re-run dismissed findings for changed artefacts because artefact-change detection is deleted**.  
  The criterion says a dismissed finding does not reappear unless the artefact changed. If change detection is absent and dismissed findings never reappear at all, the first half passes and the second half may never be exercised unless explicitly tested.  
  Section: TRD-3 §6, criterion `T3-22`.

- **T3-23** — mutation: **perform preflight validation via `models.where()` / `models.fits()` / `models.resolve()` but delete actual repair submission**.  
  The criterion only checks refusal before submission when names/boxes do not match. The repair feature could be deleted and this still pass on refusal paths.  
  Section: TRD-3 §6.1, criterion `T3-23`.

- **T3-24** — mutation: **hardcode refusal/placement logic using the 20.5 GB number in one check, but never use that arithmetic in actual scheduling/execution**.  
  The criterion says the arithmetic must use that number, but as written here there is no stated differential tying the number to a real box-selection decision.  
  Section: TRD-3 §6.1, criterion `T3-24`.

- **T3-27** — mutation: **delete all repair buttons/actions, leave only displayed remedy-class labels**.  
  “Every check names its remedy class, and a check with no remedy says so…” The actionable remediation feature can be deleted while this taxonomy/display criterion still passes.  
  Section: TRD-3 §6.2, criterion `T3-27`.

## 3. GAPS all three assume and none specifies

- **Canonical identifiers and referential integrity for cross-document links are assumed but not specified.**  
  All three documents rely on stable linkage across artefacts/jobs/models/findings/renders/storyboards/sets, but none specifies FK policy, cascade policy, or stable IDs beyond local table sketches. Examples:
  - TRD-1 §4.1 introduces `automation.set_item_id` with no FK/cascade specified in schema text, while `T1-2` assumes item deletion removes rows.
  - TRD-3 §3 uses `findings.path` joining `artefacts(path)` by convention, but no uniqueness/canonical path rules are specified.
  - TRD-2 relies on song slugs and arc/song membership (`T2-3`, §3.2) without specifying canonical album/song identity rules.

- **A single source of expected workflow metadata for QC is assumed but not specified.**  
  TRD-3 repeatedly requires checks to compare outputs to “what the workflow asked for” (`T3-2`, §4), while TRD-1 and TRD-2 define parts of those expectations (set timing, clip plan, frame legality). None of the three specifies:
  - where the submitted workflow/request is persisted,
  - how QC retrieves it later for a given artefact,
  - how a repaired/re-rendered candidate links back to the exact expectation set used for judgment.

- **Lifecycle/state model for renders/jobs/artefacts is assumed but not specified.**  
  All three rely on enqueueing, landed outputs, readiness, rerenders as new candidates, approval, repair, listing renders/findings:
  - TRD-1 `T1-26`, `T1-27`
  - TRD-2 `T2-11`
  - TRD-3 `T3-6`, `T3-18`, `T3-21`, `T3-29`
  But none specifies the canonical state machine for jobs/artefacts/candidates or how transitions are recorded. Each document leans on that machinery.

- **Concurrency/serialization rules for the single SQLite database are assumed but not specified.**  
  All three require JSON-driven operations, queueing, reruns, findings deduplication, prompt versioning, and render/job updates. None specifies transaction boundaries, locking expectations, or how race conditions are prevented in SQLite on this single-user-but-multi-process/job system.

- **File/path canonicalization and storage layout are assumed but not specified.**  
  All three use files as durable truth:
  - TRD-2 writes `<album>_arc.json` / `.md` (`T2-1`)
  - TRD-1 writes new render files (`T1-26`)
  - TRD-3 keys findings by `path` and compares candidates/repairs (`T3-6`, `T3-21`)
  None specifies canonical path rules, rename/move behavior, uniqueness constraints, or what happens if a file disappears after DB rows exist.

- **Schema migration/backfill strategy is assumed but not specified.**  
  All three add behavior on top of existing data:
  - TRD-1 adds `sets.out_fps`, `sets.mode_audience`, `automation`
  - TRD-2 changes clip-count semantics and expects existing generators/validators/prompts to agree
  - TRD-3 adds `findings`
  None specifies migration ordering, backfill of existing rows/files, or compatibility behavior for pre-existing assets/storyboards/sets.

- **Retention/cleanup policy for accumulating candidates and findings is assumed but not specified.**  
  All three require “write a NEW file, never overwrite” behavior:
  - TRD-1 `T1-26`
  - TRD-3 §2.1, `T3-6`, `T3-21`
  TRD-3 §9 explicitly disowns garbage collection, and neither TRD-1 nor TRD-2 picks it up. The system therefore assumes unbounded accumulation with no specified retention/cleanup owner.

- **Error taxonomy and API error shape are assumed but not specified.**  
  All three require “refused with a message naming the reason/consequence” in many places:
  - TRD-1 `T1-11`, `T1-23`
  - TRD-2 `T2-28`, `T2-31`, `T2-32`
  - TRD-3 `T3-14`, `T3-25`
  None specifies a common JSON error schema, status codes, or machine-readable error types, despite all three requiring full JSON driveability.

- **Time/fps conventions across the system are assumed but not fully unified.**  
  TRD-1 makes seconds canonical for sets (§3.3, §4.3).  
  TRD-2 owns scene-to-frame rounding to legal `8n+1` (`T2-12a`).  
  TRD-3 checks clip duration/frame count/fps against workflow request (§4.2, `T3-7`, `T3-8`).  
  None of the three specifies one cross-system contract for:
  - which fps is authoritative at each stage,
  - where rounded frame counts are stored,
  - how repaired/post-processed derivatives preserve or declare those expectations.

- **Authorship/audit identity is assumed beyond the “single user on a tailnet” statement, but not specified in data terms.**  
  TRD-3 `T3-22` requires recording who dismissed a finding and why. None of the three specifies user identity representation, even for a single-user deployment, or how “who” is obtained in an auth-less tailnet model.
