## 1. Contradictions between the three documents

**C1. “One shared touch point” prose vs criteria (TRD-1 §11, TRD-3 §9 vs T1-7 / T3-11 / T3-12)**  
TRD-1 §11: “The one place they touch is §9’s loudness, and it is measured once.”  
TRD-3 §9: “The one shared measurement is loudness, taken once (TRD-1 `T1-25`).”  
But T1-7 and T3-11 both bind set duration to `mixer.set_duration()` / `mixer.SET_DURATION_TOLERANCE`, and T3-12 checks transition placement against the TRD-1 timeline model (“within half a frame”). The ownership sections deny shared surface that the criteria already define.

**C2. TRD-1 §11 disowns “any check on the rendered output” (→ TRD-3) while TRD-1 criteria perform output checks**  
TRD-1 §11: “Any check on the rendered output. TRD-3. TRD-1 renders; TRD-3 measures.”  
Yet T1-3 (duration, frame count, integrated loudness of exports), T1-9b (RMS slope), T1-12 (per-lane output differentials), T1-17 (preview vs full-render loudness/duration), T1-18 (integrated loudness under easy), T1-21 (RMS across a duck), and T1-25 (flag export outside loudness tolerance on the asset row) are all post-render measurements owned by TRD-1. TRD-3 §9 agrees TRD-1 owns the set render and that loudness is shared via T1-25, but does not reconcile the broader “TRD-1 does not measure output” rule with those criteria.

**C3. T3 remedy table vs T1 gain-curve / loudnorm rule (TRD-3 §6.2 table vs T1-9a / T1-9b)**  
TRD-3 §6.2: finding “audio loudness off target” → remedy “re-run loudnorm”.  
T1-9a / T1-9b: an item with a `gain_db` curve must render with per-item `loudnorm` off (master only), or the drawn curve is flattened.  
Unqualified “re-run loudnorm” as a set/item remedy reintroduces the failure T1-9a/b exist to prevent. No cross-reference or exception for curved items / master-stage levelling.

NOTHING FOUND beyond the above (same-fact-two-places issues already on your fixed list were not re-reported).

---

## 2. Acceptance criteria that cannot fail

**T1-1** — Mutation: never persist automation rows (automation write path deleted / unused). Before/after reorder both `[]` → `(lane, t, value)` “unchanged.” Criterion stays green without proving item-relative `t` survives reorder.

**T1-2** — Mutation: same as above (no automation rows created). Delete item → no orphans by construction. Stays green without proving cascade/delete behaviour.

**T1-20** — Mutation: delete audience/`mode_audience` behaviour (switches become no-ops). easy → advanced → easy leaves DB unchanged → green. Does not require modes to exist as real affordance sets (T1-18 is the half that can fail; T1-20 alone cannot).

**T1-23** — Mutation: never implement `duck` / `layer` rendering; keep current refuse-everywhere behaviour. Criterion stays green indefinitely; it does not require the joins to ship (only that they not be silently accepted).

**T2-12** — Mutation: any ceiling value left as a bare constant. Criterion says a raise without a new measurement “fails review” — a human process gate, not a falsifiable suite check. Nothing in §10 makes this red in CI.

**T3-5** — Mutation: delete all tier checks so QC emits zero findings. Two runs → still “one finding per check” (0 = 0). Vacuous green.

**T3-18** — Mutation: delete repair enqueue entirely. QC over broken artefacts → zero jobs → green without any approval/repair feature existing.

**T3-25** — Mutation: never implement output return from remote boxes; always refuse remote repair. Stays green forever; does not force the precondition to be closed.

UNSURE (not counted above): **T2-41** — states a single `clip_plan()` implementation but, unlike T1-8 / T2-40, gives no differential/mutation; a second timer could survive if tests only call `clip_plan`.

---

## 3. Gaps all three assume and none specifies

**G1. General wait-state / render queue scheduler**  
TRD-1 §11 disowns it (“needs its own specification”). TRD-3 §9 disowns it but “depends on the wait-state model decided 2026-08-12.” TRD-2 T2-11 owns only the narrow chain `depends_on`/ready rule and says the general scheduler “stays deferred.” All three assume ordered, multi-kind enqueue (clips, refs, audio, `render_set`, TRD-3 repairs) with ready ≠ queued; no document specifies that scheduler.

**G2. How a set item binds to TRD-2’s variable-length clip/song video**  
TRD-1 §3.2: set item is a “rendered song”; video fps no longer constant; `out_fps` + normalise. TRD-2: scenes drive clips, chains, non-CHUNK lengths (T2-8…T2-13). TRD-3: song/set checks against workflow / `clip_plan` / `set_duration`. None specifies the handoff: which artefact path a `set_item` points at after chained clips + assemble, how item duration is derived when storyboard tiling ≠ mp3 length, or what happens when `out_fps` is NULL and sources disagree.

**G3. Legal frame counts (8n+1) under scene-driven lengths**  
T3-7 enforces 8n+1 on clips. TRD-2 chooses `n_scenes` / split chains from `scene_seconds` and a measured ceiling (T2-8, T2-10, T2-12) with no requirement that requested frames be 8n+1. TRD-1 normalises fps at set render (T1-5, T1-6) but does not own clip request shaping. Assumed: someone emits legal latent lengths; unspecified who rounds/pads and when.

**G4. Master-bus / set-level processing graph after per-item chains**  
T1-9a moves levelling to “the master” when a gain curve exists; T1-18/T1-19 easy “one-button master”; T1-25/T3 loudness on exports/sets. No document specifies the master stage (order, single loudnorm, true peak, interaction with per-item pan/filters, where it sits vs set transitions/`duck`). TRD-3 remedies say “re-run loudnorm” without a defined master target.

**G5. `artefacts` / asset identity shared by render and QC**  
TRD-3 findings join `artefacts(path)`; Tier 0 stamp is “already built.” TRD-1 T1-26: set re-render → new file + new asset row. TRD-2 chains produce multiple clip files plus assembled song. None specifies the unified asset/manifest schema (ids, kind, workflow request snapshot T3-2 needs, link set_item → song video → clip paths) that all three write or read.

**G6. Single-user / authz / tailnet trust boundary**  
Context is one user on a tailnet; all three require full JSON driveability (T1-27, T2-38, T3-29) with no HTML. None specifies authentication, CSRF, or that the JSON API is tailnet-only vs world-reachable. Assumed safe multi-endpoint control plane; unspecified.

NOTHING FOUND for additional cross-cutting gaps at the same confidence level without inventing requirements.
