1. CONTRADICTIONS

- Section 2.3 says “How every criterion is verified” is restated in all seven documents and proposes consolidating that into **TRD-6 §0** as **`T6-A7`…`T6-A10`**. Section 5 then says **“It adds no criteria.”** Those are in tension: creating `T6-A7`…`T6-A10` is adding criteria unless those ids already exist. I am UNSURE whether `T6-A7`…`T6-A10` already exist in TRD-6; if they do not, this is a direct contradiction.

- Section 2.3 also says consolidation removes duplicates while Section 5 says **“the 73 stay 73 minus what §2 folds.”** If the shared verification rules are converted into TRD-6-owned criteria and six other documents cite them, the total criterion count changes in a way the plan does not state cleanly. UNSURE, because this depends on whether those rules are currently counted as criteria or prose in the source documents.

2. ORDERING DEFECTS

- Phase B includes `T7-17` and says the files include **the preview route**, while the dependency graph says **“TRD-7 view table (T7-1,T7-3,T7-5) -> T7-13 view:<key> prompts -> T7-19 per-view override.”** I do not see `T7-19` scheduled in any phase. If `T7-17` preview is supposed to show the composed prompt surface for the new prompt system, omitting `T7-19` leaves a named downstream dependency unscheduled.

- Phase D includes `T4-18`, and the dependency graph says `T7-13 view:<key> prompts -> T4-18 composition test`. That dependency is named, but `T4-18` also appears to depend on Phase B’s `T7-15` `composite` and `T7-17` “composed by the real composer and visible in the preview.” The plan does not name those dependencies explicitly at `T4-18`. Measurement to settle it: identify whether `T4-18` exercises the same composition path as `T7-15`/`T7-17`; if yes, they should be explicit prerequisites.

- Phase E says do `T5-1`, then variant A, then `T5-5`, then B or `T5-6`. I do not see `T5-2`, `T5-3`, or `T5-4` named in the phase body even though the proof paragraph says **“`T5-2` is a differential…”** If those criteria exist in TRD-5, the phase ordering is incomplete because the acceptance proof relies on a criterion not scheduled.

- Phase F orders **identity (`T6-8`…`T6-10`) before lifecycle (`T6-5`…`T6-7`) before pull queue (`T6-1`…`T6-4`)**. That may be right, but the plan’s own dependency statement says **“TRD-6 §1-§6 (pull queue, lifecycle) -> nothing in 4/5/7 blocks on it.”** I cannot tell from the plan whether canonical paths and cascade policy can be implemented before queue records/jobs that refer to them. UNSURE; the missing dependency naming is between `T6-8`…`T6-10` and the queue/lifecycle storage they likely attach to.

3. CRITERIA THAT CANNOT FAIL

- Phase A proof: **“add `three_quarter_nude` to the table only, and (a) it renders, (b) it is refused at `g` with no gate edited…”** Part (b) can stay green if the feature never renders or the new view is ignored, as long as the gate still refuses unknown or nude cases generically. The proof needs an assertion that the new view is actually reachable in the positive path before the refusal path is checked.

- Phase B proof: **“`T7-17`'s preview shows all four; deleting a type from `prompt_for` changes the composed string.”** The first half is weak: a preview can “show all four” from static labels or stale data even if the renderer/composer ignores them. The second half is stronger, but it still risks passing if the composed string changes due to fallback text rather than the actual new type path. Measurement to settle it: mutate each type’s source text independently and assert the exact affected segment appears/disappears in preview and in the composed prompt sent downstream.

- Phase C proof: **“`T7-7` renders ... and compares the images. Per TRD-3's rules, and look at them...”** This one is directionally good, but as written it lacks a threshold or pass/fail definition. Without a quantitative bound or blinded manual rubric, it risks becoming non-falsifiable. Measurement to settle it: define a metric or review protocol that distinguishes “anchor used” from “raw photos used.”

- Phase D note on `T4-13`: good warning, but the surrounding phase still includes other prompt criteria whose proof appears to rely heavily on prompt text and stored text. I would flag `T4-14` through `T4-17` as UNSURE because no differential is stated here; if their proof is only string presence, they may stay green when rendering behavior regresses.

- Phase E proof for `T5-2`: **“same seed, same scene, refine on and off, mean absolute pixel difference > 0 and a sharpness metric moving the right way.”** `mean absolute pixel difference > 0` can pass from trivial noise, metadata-induced variation, or any non-semantic perturbation. It proves “not a no-op,” not “refine worked.” The sharpness metric clause helps, but “moving the right way” is undefined. Alternative: require both nonzero differential and an agreed image-quality metric improvement on a fixed fixture set.

4. THE CONSOLIDATION PROPOSAL IN SECTION 2

I think folding the shared “how this is verified” rules into one owner is **right**, with one caveat.

Why right:
- The plan itself cites drift: different counts, paragraph vs numbered rules, only some documents mention the `grep -c` rule.
- These are meta-verification rules, not domain behavior. One owner is the normal way to stop procedural drift.
- It reduces the recurring failure mode the plan names: tests that pass by absence.

Caveat:
- Putting them in **TRD-6** seems weak unless TRD-6 is already the project’s home for cross-cutting test/verification doctrine. From the plan text alone, TRD-6 is “QUEUE-LIFECYCLE-AND-STORAGE,” which does not sound like the natural owner for project-wide verification policy. Alternative: put the shared verification rules in a project-wide document or the earliest TRD that already owns inherited rules. Measurement to settle it: choose the location that minimizes future cross-document citations and matches existing ownership patterns in the tree.

5. WHAT IS MISSING

- `T7-19` is named in the dependency graph but not assigned to any phase.

- The plan says **“the other six cite it”** for consolidation of verification rules, but there is no phase covering the actual edits to those six documents.

- If §2.1 and §2.2 are to be acted on, there is no phase for the document surgery to replace duplicate text with citations in TRD-2/TRD-5, only the proposal.

- Section 3 says **`T6-13a` is not in anyone's plan** and should be built before `T2-12a`, but this plan covers TRD 4-7 only. That leaves a cross-document dependency unresolved: no phase here covers the needed change to TRD-2 planning logic that consumes `songs.duration`.

- Phase F says “every criterion here specifies a test that fails today, so each one must be written as a red test first,” but there is no explicit phase/task for authoring those red tests before implementation. If that sequencing matters, it is missing as work.

6. ANYTHING YOU WOULD CUT

- I would cut the proposal to mint or move shared verification rules into **TRD-6** specifically, unless the tree already treats TRD-6 as the home for inherited/meta rules. Keep the consolidation idea, change the owner to a genuinely cross-cutting location if one exists. Measurement: whichever location yields the fewest unnatural citations and future edits.

- I would cut or tighten the Phase A proof as written. “Refused at `g` with no gate edited” is not enough by itself; it invites a green check from absence. Replace it with a two-step proof that first demonstrates the new view is actually produced in the positive path.

- I would cut the `mean absolute pixel difference > 0` part of Phase E as a primary success check. Keep it only as a no-op guard, not as proof of correct refine behavior.
