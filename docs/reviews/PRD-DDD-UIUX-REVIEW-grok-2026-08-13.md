# Review findings

## 1. Does the PRD/DDD layer earn its existence?

**PRD-1-3 — earns it.** Sequencing (§6), product-level “who decides,” and Jon’s 2026-08-13 re-order (timeline last; full queue rewrite) are not things acceptance criteria carry. The “what this adds” claim is coherent.

**DDD-1-3 — earns it.** Built ledger at a named commit, service-split pattern from `qc_service.py`, master-stage measurement/mutation history (§5.2), schema deltas, subsystem designs, and verification rule 0 are design content TRDs would not hold as the contract.

**PRD-4-7 — earns it, thinner.** Product rules 3.1–3.4 and the identity thread are real framing. Priorities mostly defer to `PLAN-TRD-4-7.md`; without that plan in this set, much of the “order” value sits outside this layer.

**DDD-4-7 — earns it.** One-graph framing, view-table collapse, identity-lock design, refine variants A/B with VRAM gate, TRD-6 “red test first,” and dual-copy inventory are design, not restated criteria.

**PRD-8-10 — earns it.** Backward origin (reconciliation / unowned shipped code), TRD-9-as-tests-for-production, and P9 (model words never a gate) are reasons to exist that criteria alone do not supply.

**DDD-8-10 — earns it for TRD-8/10; borderline for TRD-9.** Take schema and denormalised tags/lyrics, bulk-edit rules, advice payload contract are design. TRD-9 sections are largely operational description of existing behaviour plus “write tests”; still justified as the place that pins seams (`_submit_and_collect`, retarget/retry), but closest of the six to “spec that is a tour of the code.”

**Cross-cutting:** All six assert they do not restate criteria and point at TRDs/PLAN for the contract. That split is credible for 1-3 and 8-10; 4-7 PRD leans on an external plan more than it carries sequencing itself.

---

## 2. Contradictions

**Timeline priority (PRD-1-3 internal + pair).**  
PRD-1-3 §6.0: Jon put set timeline last; “§6's P1 below was written with the timeline first and is superseded.” Immediately under that, heading **“P1 — the timeline…”** still sequences clock/peaks/proxy/master/audiences as the P1 work block, while Jon’s list puts anchors, QC repair, and `scene_seconds` ahead. DDD-1-3 §6 still has `sets_service → clock/peaks/preview → master → audiences` on the main graph without restating “timeline last.” **Supersession is declared but not applied consistently in headings or DDD order.**

**Queue priority (PRD-1-3 vs PRD-4-7).**  
PRD-1-3 §6.0: full pull-based queue in scope; Phase F no longer deferred; `PLAN-TRD-4-7.md` §4 updated.  
PRD-4-7 §5: queue last except `T6-13a`; §8 open whether TRD-6 is built this cycle.  
Same calendar day, opposite product posture on TRD-6 beyond `T6-13a`.

**Refine / denoise UI honesty (DDD-4-7 vs UI/UX 7a.3).**  
DDD-4-7 §4: `T7-8`/`T7-9` shipped (`d3f2f6a`); `latent_mode` no longer pinned; `base=None` default.  
UI/UX §7a.3 still presents five of six `DENOISE_CHOICES` labelled noise **because `latent_mode` is pinned** as a live defect. Stale relative to DDD-4-7’s own ledger (or DDD over-claims; tree not in review).

**Nav order (UI/UX vs its own citation).**  
UI/UX §2.5: TRD-2 §7 order *Library → Playlists → Anchors → Sets → Jobs → Tiers → Config*.  
§5.1 prescribed bar: *Library · Albums · Anchors · Sets · Jobs · Tiers · Config* and “TRD-2 §7's order stands” while renaming Playlists→Albums. Rename may be intentional; claiming the TRD order “stands” after a label change is a soft inconsistency. **UNSURE** whether TRD-2 §7 uses Playlists or Albums (TRD not in set).

**Commit baselines across DDDs.**  
DDD-1-3 and DDD-4-7: tree at `f9ca597` (+ session B commits in 4-7).  
DDD-8-10: `c01c977`.  
Not a logical contradiction, but “what exists” is not one freeze; cross-DDD built claims are not comparable without a merge rule.

**PRD-1-3 criterion count vs coverage line.**  
Status/covers TRD 1-3; §8 says **192** criteria across seven TRDs, these three hold **120** (32/58/30). PRD-4-7 claims **72**, PRD-8-10 **49**. 120+72+49 = 241 ≠ 192. Document explains older wrong totals but does not reconcile 192 with 72+49 or with “seven TRDs.” **Internal arithmetic contradiction** unless “seven”/scope means something not stated.

**P8 “identity from text” ownership.**  
PRD-1-3 P8 cites `T2-31`, `T2-32`, `T3-17`, `T3-28`. PRD-4-7 §3.2 is the same rule as core identity machinery. Not a direct conflict, but two PRDs both treat it as crown-jewel product rule without a single owner doc—drift risk, not a hard contradiction.

**DDD-1-3 “master fix” vs PRD-1-3 “already built.”**  
PRD-1-3 already-built lists automation curve model; DDD §5.2 says mixed-set `T1-20d` gap **FIXED** same day by session B. Consistent if read as “automation existed, master engagement bug fixed later”; PRD ledger does not mention the fix or residual risk.

---

## 3. Claims that cannot be checked (from these documents alone)

- Any **pass/fail of a cited TRD criterion** (`T1-*` … `T10-*`, `T6-A*`) — TRDs absent; ids are opaque here. **UNSURE** on correctness of every “proven by” cell.
- **Line counts** (e.g. `app.py` 6331, `mixer.py` 2116, style 1247, templates 3481) and **grep counts** — commands named in places, results not reproducible from the text alone.
- **Commit hashes** (`f9ca597`, `d315c6f`, `415584d`, `c01c977`, etc.) and “read off the tree” / “both sessions independently” — not falsifiable without the repo.
- **Numerical production measurements**: loudnorm path table; 0.0594 s/join; 23.4/23.9 GB; 291.6 vs 378.2 s; 41.1 vs 64.7; fleet GiB table; `grep -c` zeros for `takes`/`voices`; class histograms; font-size/spacing inventories.
- **“FIXED … session B”** and mutation narratives (assertions stayed green / went red) — historical claims about code and tests not in the document set.
- **`PLAN-TRD-4-7.md` §3–§4**, **`SESSIONS.md`**, **`RECONCILIATION-CODE-VS-SPEC-2026-08-13.md`**, **`AUDIO_BUILDOUT_PLAN.md`** — asserted contents not present.
- UI/UX §7: consultation **zero fabrications**, **UNSURE eleven times**, 7.4 KB / 36 KB — process claims, not checkable here.
- DDD-4-7: every node for refine **installed on cerberus, verified against `/object_info`**.
- PRD-8-10: **3,147 lines of shipped code and 1,992 lines of plan documents, none of it owned** — not evidenced inside the seven files.

---

## 4. Sequencing defects

1. **Jon order vs numbered P0–P3 (PRD-1-3).** Desired next: anchors on-model → QC repair path → clip length; timeline last. Written sequence: P0 = `T2-12a` + service split; P1 = timeline; P2 = arc; P3 = QC tier 2/repair. Clip length is P0 (aligned with third priority) but anchors/identity live in PRD-4-7, and QC repair is P3 after a full timeline P1 that §6.0 said is superseded. **Stated dependency order cannot hold as the product order §6.0 just mandated.**

2. **`T6-13a` vs clip-length chain.** PRD-1-3: full queue in scope; `T6-13a` first inside it because clip-length waits on it. DDD-4-7 §6: `T6-13a` first; consumer side unowned; **whoever takes `T2-12a` takes `T6-13a` with it**. DDD-1-3 §5.5 / §6 chain starts at `T2-12a` and does **not** place `T6-13a` on the arrow graph. **Dependency asserted in 4-7 DDD, missing from 1-3 DDD build graph** — dual ownership / skip risk.

3. **Service split vs feature work (PRD-1-3 §6 P0).** “Doing this after the features means writing them twice” vs Jon moving timeline last and pushing other features first — if features proceed in non-timeline areas without split, the PRD’s own “write twice” warning applies; order does not resolve which features may precede `sets_service` / `storyboard_service`.

4. **PRD-4-7 priorities vs PRD-1-3 queue.** 4-7: queue last (except `T6-13a`). 1-3: TRD-6 §1–§6 in scope and plan phase undeffered. **Cannot both be the schedule.**

5. **PRD-8-10 / DDD-8-10: “Nothing here blocks TRD 1-7”** while TRD-9 is “everything renders through it” and first for proof of routing. Not a hard blocker contradiction, but **operational priority (fleet tests first) vs “no block” understates coupling** if deploy gates depend on live fleet (PRD-8-10 §7 open).

6. **Tier 2 before repair vs Jon “know when wrong / repair path”.** P3 orders calibration (`T3-13`…) before repair routing that stops `approve()` raising. Jon item 2 is repair path; measuring half “already built.” **Repair after full tier-2 calibration may contradict “wanted next”** unless repair is only tier-1 actuators — not spelled out.

7. **DDD-4-7 refine:** measurement whether B fits **runs first**; good. Depends on cerberus headroom claim — sequencing OK inside doc; **UNSURE** vs fleet doc ownership of where that measurement is scheduled.

---

## 5. UI/UX guide — §7a and §7b

### 7a (TRD 4-7 surfaces)

- **7a.1 Matrix vs form** — Strong, specific, tied to `T7-3` / `T7-19` and footgun (per-tier box applied to every view). Actionable. Risk not addressed: how nude parallels, tier policy, and wand/preview (`T7-17` in DDD) map onto cells; density on “canvas” layout unspecified.
- **7a.2 Three-valued chip** — Aligns with DDD-8-10 §4.2 reference to three-valued chip and PRD/DDD `T6-A6`. Adds `--muted` for unknown vs §5.4 job colours; **possible overload of `--muted` for idle jobs and unknown capability** — collision not resolved.
- **7a.3 Marked not inert** — Consistent with principles §3.5 and `plan-panel`. **Contradicts DDD-4-7 on `latent_mode` pinned** (stale). Still correct as enduring rule for `--refine` on `ltx25` if that remains true in DDD-4-7 §5.
- **7a.4 `versioned-field`** — Fits §2.3 anti-pattern; matches DDD-4-7 one-composer rule. “Usage counts **renders, not loads**” is a product rule with **no cited criterion** in-section (may live in TRD — **UNSURE**).
- **7a.5 Reference as tile state** — Consistent with DDD-4-7 §4 / `media-tile`; appropriately minimal.
- **7a.6 Queue** — Applies §5.5; `seed + k*137` is a concrete batch detail **not defined elsewhere in these seven docs** — unexplained magic for a style guide reader.
- **Gap in 7a:** No UI for refine variant A/B or VRAM refusal copy; no portrait/`w`/`h` distant-figure warning surface (DDD-4-7 §4).

### 7b (TRD 8-10 surfaces)

- **7b.1 Take as `media-tile` + audio** — Coherent with DDD-8-10 and `T6-A5`; playback-primary and row comparison are the right differentiator. Missing: how proxy/waveform peaks rules from TRD-1/UI §4 interact with take tiles; loudness/`T1-25` meter reuse.
- **7b.2 Consent as gate / plan-panel** — Aligns with PRD P4 and DDD voices NOT NULL-able intent; sharp teaching point (refusal ≠ validation). Good.
- **7b.3 Fleet / unknown** — Correct cross-link to 7a.2; stale-read and empty-backend hazard (`T9-9`) match DDD-8-10. **“Fleet page”** assumed; not in §5.1 nav (Models→Config only) — **where this page lives in IA is unspecified**.
- **7b.4 Bulk edit** — Directly implements PRD/DDD `T10-3/4/7` as UI failure modes; strongest subsection in 7b.
- **7b.5 Model-authored text** — Payload + presentation; ties to P9 and 41.1/64.7. Rule “model text `--muted` + marker; measurements `--text` + unit” may **fight 7a.2** (unknown also `--muted`) and **QC finding density** (remedy is model-ish and must stay actionable — hierarchy under-specified).
- **Cross 7a/7b:** Both bolted on after chatgpt §7; no pass reconciling new components (`versioned-field`, matrix, take tile, fleet row) with §6 delete list or §8 verification checks (no check that three-valued chips exist, or that blank bulk fields do not clear).

---

## 6. What is missing

- **The ten TRDs, `PLAN-TRD-4-7.md`, reconciliation and audio buildout plans** — layer repeatedly defers; reader cannot verify contracts, one-sided tables, or plan phase claims.
- **Single sequencing authority** after Jon’s re-order — one ordered backlog across PRD-1-3, PRD-4-7, PRD-8-10 (anchors vs `T2-12a` vs `T6-13a` vs TRD-9 tests vs timeline).
- **Resolved decision records** for opens: take backfill vs clean; voice cloning wanted; TRD-6 this cycle; TRD-9 deploy gating; live-model fixture policy (PRD-1-3 §8).
- **Who implements `T6-13a` and where duration authority lives** in DDD-1-3’s graph (named gap in DDD-4-7, not closed).
- **Cross-pair identity/QC remedy ownership** — P8 / `T3-28` vs TRD-4/7 prompt work; one narrative for “wrong remedy.”
- **UI IA for fleet / models / albums** — rename Albums, Models under Config, fleet “page,” vs API route names still `playlists` in DDD-1-3 §3.
- **UI verification extensions** for §7a/7b (matrix, three-valued availability, take playback row, bulk blank semantics, model-text marker).
- **Shared “built ledger” freeze** (one commit / date) across all DDDs and UI/UX counts.
- **Criterion-count reconciliation** (192 vs 120+72+49; “seven TRDs” vs ten TRDs in the programme).
- **Whether PRD-4-7 still claims `T7-7` unmeasured** while Session B shipped adjacent items — measurement protocol status beyond “human-judged.”
- **Mobile/canvas specifics for new matrices and take comparison** — principles say mobile matters; 7a.1/7b.1 do not specify small-screen behaviour.
- **NOTHING FOUND** on: security/auth beyond “tailnet/bind” (out of stated scope); i18n; performance budgets beyond GPU cost copy.

---

### Highest-signal plain findings

1. PRD/DDD layer **should exist** for all six; none is pure heading-swap, though **PRD-4-7** and **TRD-9 slices of DDD-8-10** are the weakest “must be separate docs.”  
2. **Hard schedule contradiction:** full TRD-6 now (PRD-1-3) vs queue last / maybe not this cycle (PRD-4-7).  
3. **Hard internal sequencing failure:** Jon’s priority list vs PRD-1-3 P1 = timeline still in the file and DDD-1-3 build graph.  
4. **UI §7a.3 stale vs DDD-4-7** on denoise/`latent_mode`.  
5. **Uncheckable:** nearly all “built/fixed/measured at commit” claims without the repo and TRDs.
