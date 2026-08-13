## 1. ONE-SIDED CRITERIA

Criteria that stay green if the feature is deleted / never built, and the positive half each needs.

### TRD-4
| ID | Why one-sided | Positive half required |
|---|---|---|
| `T4-1` | Pure refusal (zero views) | At least one selected view produces a job/render for that view |
| `T4-3` | “No fallback… refuses empty” — absence of fallback paths | Non-empty tier+view selection is accepted and drives jobs (pair with `T4-2`) |
| `T4-4` | Refusal-message shape only | (same success path as `T4-1`; message criterion only applies when refusal is the correct outcome) |
| `T4-6` | Refusal of explicit under `g`/`pg13` | Already paired in prose by `T4-7` — **table must say so** |
| `T4-7` | Success-only if save path always accepts | Already paired by `T4-6`; keep both mandatory |
| `T4-9` | “Same treatment” as save guard — no success/fail pair stated | Explicit wording refused under `g`/`pg13` **and** accepted under `r`/`xxx` on `/anchors/tier-wording` |
| `T4-10` | Emptiness of an allowlist / walk of constants | Composed positive prompt for a real sheet contains the body-colour assertion (`T4-11`) and still renders; mutation alone does not prove runtime compose |
| `T4-11` | Payload-carries-Y (part list string) | Render differential: two-tone/lighter patches **decrease** vs current `DEFAULT_BODY` negation (image metric, not string present) |
| `T4-12` | Payload-carries-Y (slot names + composite) | Realisation is `T7-10`/`T7-7`: multi-ref sheet does **not** split identity; string presence is not enough |
| `T4-14` | “Drops wardrobe” + “never says bare skin” (absences) | Nude view at `xxx`/`r` still composes fur/anatomy positives and renders non-human-skin body (Day-4 failure mode inverted) |
| `T4-16` | “Unchanged” + “nothing moves into positive” (absences) | Quality-mode render still applies the negative list (behavior), and a known negative-only defect is held down |
| `T4-17` | “Still dropped in fast mode” — can pass if fast path/feature gone | Fast mode render succeeds without negative pass; quality mode still has negative (both modes exist and differ) |

**Not one-sided (already have a failing positive measurement path):** `T4-2`, `T4-5`, `T4-8`, `T4-13`, `T4-15`, `T4-18` (six assertions — still add explicit “compose succeeds for xxx front-nude” as the harness entry, or delete-the-composer goes green on “no negation”).

**UNSURE:** `T4-5` alone — “runs the same guardrail” can pass as a mock/no-op if save+render both disappear; needs “save of permitted text succeeds and is stored.”

### TRD-5
| ID | Why one-sided | Positive half required |
|---|---|---|
| `T5-1` | “Raises naming the reason” branch is a refusal form | Default `ltx25` + `--refine` either **changes decoded frames** (`T5-2`) or hard-fails before accept; accepted silent no-op is the defect — success path must be specified as ship target (A), not only raise |
| `T5-3` | Parameter constraint on a pass that may not exist | Refine pass executes with `0 < denoise < 1` **and** output differs (`T5-2`) |
| `T5-4` | “Never an overwrite” — green if refine never writes | Refine lands a **new** artefact path, both unrefined and refined reachable (cite `T6-A5`, don’t only restate) |
| `T5-6` | “Recorded as a finding… A ships” — process/absence | Catalogue notes contain measured unfit **and** shipped path still satisfies `T5-2` |
| `T5-8` | Availability enum shape — green if upscaler feature unused | End-to-end: when file present, refine B can load it; when absent, `False` blocks with named reason (`T6-A6` consumer) |
| `T5-9` | Labeling measured vs chosen — doc criterion | Ceilings enforced in planner/renderer (over-long rejected or split), not merely annotated |
| `T5-10` | Shared congruence rule as presence | Illegal lengths refused **and** legal length renders for both LTX and s2v |

**Not one-sided:** `T5-2`, `T5-5`, `T5-7` (conditional but has geometry positive).

### TRD-6
| ID | Why one-sided | Positive half required |
|---|---|---|
| `T6-A1` | “Reachable over JSON” can be vacuously true for empty API surface | Named loops actually complete: set empty→rendered; storyboard loop; review queue (document says each TRD names its loop — those positives must exist as tests) |
| `T6-A5` | “Never overwrite” half; “both reachable” is the positive — keep mandatory | Re-render/refine/repair/anchor re-roll: predecessor **and** successor listed and selectable |
| `T6-2` | “Not enqueueable until…” is refusal of early enqueue | After predecessor `landed`, successor becomes `ready` and is pulled |
| `T6-4` | Split refusal/requeue — need both sides explicit in one pair | Vanished backend → item runs elsewhere; refused workflow → stays failed with REASON, does not infinite requeue |
| `T6-5` | “Every transition recorded” — green if no transitions | A full happy-path job produces the ordered timestamp chain with non-null times |
| `T6-6` | Duplicate of `T6-A5` in refusal/absence form | Same positive as `T6-A5` (one test, cite one id) |
| `T6-9` | Missing file → finding (failure path) | Present file → QC runs for-real and can pass; delete-after-row → finding not skip |
| `T6-10` | Delete cascade / “does not silently orphan” | Song delete behavior **stated and measured** (block vs cascade vs reparent) — both “orphans refused” and “intended deletes remove automation rows” |
| `T6-11` | Payload stored at submit | QC comparison uses `expect_json` and fails when artefact disagrees with stored expect |
| `T6-12` | Link presence | Re-check after repair judges against **same** expect and can change finding outcome |
| `T6-13` | “Skip when absent” — skip is half a criterion | With expect present, comparisons **run**; with expect absent, skip **and** no self-baseline from file |
| `T6-13a` | “Authority is X” without consumers | TRD-1/2/3 length derivations read `songs.duration` only; third-decimal agreement test across those paths |
| `T6-16` | “Nothing holds write tx across subprocess” — absence | Concurrent web read/API succeeds during long render |
| `T6-18` | “Nothing is deleted by this document” — always green | Retention policy test: lifecycle artefacts remain reachable after re-render; GC explicitly out of scope **named** so absence of deletes is not a pass for “storage works” |

**Not one-sided (have kill/differential/idempotent teeth):** `T6-A2`, `T6-A3`, `T6-A4`, `T6-A6`, `T6-1`, `T6-3`, `T6-7`, `T6-8`, `T6-14`, `T6-15`, `T6-17`.

### TRD-7
| ID | Why one-sided | Positive half required |
|---|---|---|
| `T7-2` | Refusal at `g` for nude-by-omission | §6 already says it: nude view **succeeds** under `xxx` (and wardrobe swap applies). **Promote to criterion id**, not only verification prose |
| `T7-3` | New sentences exist (presence) | Each new view composes and renders; framing clause appears once (`T7-4`) |
| `T7-5` | Override / absence of conflict string | `portrait` render is head/shoulders crop (image), not full-body + competing clause |
| `T7-6` | Feature presence (“use as reference”) | `T7-7` is the positive — bind them in the missing table |
| `T7-8` | `latent_mode=image` reachable + label text | Denoise 0.55 refine on existing sheet changes surface, holds composition (image differential); labels match graph |
| `T7-9` | “Not silent” refusal of silent promote | Plate slot works **or** single-ref sheet succeeds with no image2 plate; two-ref case has named roles |
| `T7-10` | Refuses `"reference 3"` string | Slot names identity/wardrobe-or-plate/third-view **present**; three-photo one-character sheet keeps one identity (`T7-7`) |
| `T7-11` | Settable presence | Explicit lora_strength reaches graph; cfg>1 interlock still forced unless explicit (both directions) |
| `T7-12` | Settable presence | Non-default w/h appear in workflow **and** output dimensions match |
| `T7-13`–`T7-16` | Types exist / versioned (presence) | Each type editable per album, composed into real prompt, visible in preview (`T7-17`), screened (`T7-18`) |
| `T7-18` | Screen + no-negation walk (absence of “no …”) | New types accept clean positive text and refuse negation/jailbreak the way other positives do |
| `T7-19` | Either/or presence of UI shape | Edit one view’s override does **not** change another view’s compose (differential) |

**Not one-sided:** `T7-1` (mutation cross-copy), `T7-4` (compose diff), `T7-7` (image differential).

---

## 2. CONTRADICTIONS

1. **Image2 role: wardrobe vs plate**  
   - `T4-12` / `T4-18`: image 2 = **wardrobe** reference.  
   - `T7-9` / `T7-10`: image 2 = **composition plate** (`base`), “wardrobe or plate”.  
   Same slot cannot be both wardrobe lock and composition plate without a rule for which wins when both matter (nude swap drops wardrobe; plate may still be needed).

2. **`T5-4` restates `T6-A5`** (“new file, never overwrite”) instead of citing it. Violates TRD-6 §0 “cite, never restate.”

3. **Chained guide frames**  
   - TRD-5 §6: **not building** `LTXVAddGuide*` handoff.  
   - Same bullet: TRD-2 `T2-10` **needs exactly that**.  
   Internal “we know it’s needed / we refuse to own it” contradiction across the set (see boundaries).

4. **`T6-6` vs `T6-A5`**  
   Same rule twice in one document (“re-render is a new candidate” and §0.2). Not opposite, but breaks “one owner… others cite” for readers of TRD-1/3 who were told the consolidation removed this duplication.

5. **TRD-4 §1a vs `T4-12` wording**  
   §1a says `T4-12`’s slot naming → `T7-10`, and that the bad name **asserts a second person**. `T4-12` body still specifies the good naming as if owned here. Ownership is clear in §1a, criteria section still reads like dual ownership.

6. **UNSURE — `T4-7` tier set**  
   `T4-6` refuses `g`/`pg13`; `T4-7` succeeds under `r`/`xxx` only. If policy allows partial explicit at `r` and full at `xxx`, “same text” may be wrong for one of them. Settle by `tiers.compose_guardrail` matrix — not stated here.

No contradiction found with quoted `T6-A1`–`A4` restated as full API blocks in TRD-4/5/7 bodies (they largely don’t restate those four). **Exception:** overwrite rule via `T5-4`.

---

## 3. BOUNDARY DEFECTS

### Disowned (TRD-6-class hole)
1. **Clip-to-clip frame handoff / guide injection**  
   TRD-5 §6 explicitly will not build `LTXVAddGuide` / `LTXVAddGuideMulti` / `LTXVAddGuidesFromBatch`, while stating TRD-2 `T2-10` needs them. TRD-4/6/7 do not claim it. **No owner for chain continuity implementation.**

2. **UNSURE — Anchor artefact lifecycle under queue**  
   `T6-A5` lists “re-rolled anchors”; TRD-4/7 never cite `T6-A5`/`T6-6` for anchor writes, and TRD-7 §5 says “no new storage” but not “new candidate beside predecessor.” Easy to implement anchor re-roll as overwrite while queue doc assumes beside.

### Dual-claimed / blurry
3. **Slot naming on anchor path:** `T4-12` and `T7-10` (mitigated by §1a pointer; still two acceptance ids for one behavior).  
4. **Nude tier violation:** save `T4-6` vs render `T7-2` (intentional split; OK if table cross-cites).  
5. **Lighting lock home:** `T4-13` metric vs `T7-14` versioned `backdrop` (OK if `T4-13` measures, `T7-14` stores).  
6. **Negation ban:** `T4-10` and `T7-18` both bind `test_no_positive_prompt_constant_tries_to_negate`.

### Nothing found
- No second disowned dependency as clean as pre-TRD-6 scheduler **other than** guide-frame handoff above.

---

## 4. DECISIONS THAT LOOK WRONG

1. **Ship refine variant A first (same-res re-denoise)**  
   Risk: `T5-2` requires sharpness to move “right” — A may redistribute noise without detail gain → perpetual `T5-2` red or a weakened metric.  
   **Settle:** freeze seed/scene; compare A on/off with the stated MAPE + sharpness; if sharpness ≤ baseline, skip A as product default and only ship raise-or-B.

2. **TRD-5 refuses to build guide handoff while T2-10 needs it**  
   Risk: storyboard chains remain impossible; TRD-2 stays blocked.  
   **Settle:** one chained two-clip render with/without guide node — identity/continuity metric from TRD-2/3; if red without handoff, this “not building” cannot stand.

3. **`T7-2` “nudity gating is derived, not enumerated” without derivation rule**  
   Risk: substring/`_nude` suffix heuristics re-create omission failures.  
   **Settle:** add view with nude semantics but non-matching key; must refuse at `g` and accept at `xxx`.

4. **s2v ceiling `4.8125 s` as chosen `LEN = 77`, coherence “unmeasured”**  
   Risk: planner treats choice as safe max.  
   **Settle:** coherence/QA sweep at 5 s / 10 s / 15 s; promote to measured or cap by evidence (`T5-9`).

5. **`T4-10` delete negation exception solely from string policy**  
   Decision may be right, but string ban ≠ fix if model still two-tones.  
   **Settle:** `T4-11` image metric (channel/region variance on body) vs baseline seeds in §4.

6. **`T6-18` defer all GC with no retention bound**  
   Risk: disk fill is an ops failure with no criterion.  
   **Settle:** not “build GC now”, but a measured budget/alarm criterion — or explicit ops owner outside TRDs.

---

## 5. WHAT IS MISSING

1. **The refusal/positive pairing tables** themselves (TRD-1/2/3 pattern) for all `T4-*`/`T5-*`/`T6-*`/`T7-*`.  
2. **Formal criterion for `T7-2` success under allowing tiers** (only in §6 verification text).  
3. **Owner + criteria for LTX chain guide / frame handoff** (T2-10 realisation).  
4. **Cite-not-restate fixes:** `T5-4` → cite `T6-A5`; `T6-6` merge or cite `T6-A5` only.  
5. **Image2 single semantics** (wardrobe vs `base` plate vs both with explicit slot map) covering nude sheets.  
6. **`--refine` product behavior on catalogue default when B does not fit** — raise vs A vs hide flag; `T5-1` allows raise forever on default model.  
7. **Anchor path × `T6-A5`:** re-roll/variation writes new `anchors` row, both selectable.  
8. **`T6-13a` consumer criteria** in this set: force TRD-4/5/7 don’t re-probe duration (clips are TRD-5; assembly geometry `T5-7` should read `songs.duration` if duration-derived).  
9. **Failure path:** refine/VAE OOM mid-job → `failed` vs requeue (`T6-4` interaction) — not specified.  
10. **Duet / multi-character:** `T4-12` mentions cast_clause for duets; TRD-7 only fixes single-character three-photo case — no criterion that duet still **can** name two people when intended.  
11. **`T4-15` content:** override keys exist, but no criterion that album-profile values are what the renderer receives after save screening.  
12. **JSON end-to-end loop ids for anchors/variations** under `T6-A1` (TRD-4/7 never name their curl loop).  
13. **UNSURE — interaction `T7-8` image latent refine vs `T6-A5`:** refined sheet new row or overwrite in-place — unspecified.

---

### Restatements of TRD-6 §0 (flag)
- **`T5-4`:** restates `T6-A5` (new file / no overwrite).  
- **`T6-6`:** restates `T6-A5` inside the same doc.  
- TRD-4 / TRD-7: **NOTHING FOUND** as full restatements of `T6-A1`–`A4` or `T6-A6` (anchors should **cite** `T6-A5` for re-rolls and do not).
