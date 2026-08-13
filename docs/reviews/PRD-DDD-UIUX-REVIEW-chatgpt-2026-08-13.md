1. PRD/DDD layer existence

## docs/PRD-1-3-EDITING-AND-QUALITY.md
- EARNS EXISTENCE: YES.
- Finding: it adds a cross-TRD sequencing layer in §6 and explicitly re-orders work based on “What Jon decided, 2026-08-13”, which is not the same thing as criterion restatement.
- Finding: it adds product-level outcomes P1–P8 that aggregate multiple cited criteria into cross-document definitions of “working”, rather than merely repeating single TRD points.
- Finding: it also adds operator/context framing and the “editor must not promise what the renderer does not produce” rule, which is broader than any one cited TRD excerpt.
- Limitation finding: large parts of §5 are still mostly index/traceability back down to TRD ids rather than independent product decisions.

## docs/DDD-1-3-EDITING-AND-QUALITY.md
- EARNS EXISTENCE: YES.
- Finding: it adds implementation structure absent from a requirements layer: current module ownership, service split pattern, proposed API surface, schema deltas, and subsystem designs.
- Finding: it contains tree-read built/unbuilt assertions and specific architectural decisions such as “Peaks are not a table” and the `sets_service.py` / `storyboard_service.py` split, which are design content rather than TRD restatement.
- Finding: §5.2 records a design-correction history around the master-stage fix that is design reasoning, not requirement restatement.
- Limitation finding: some sections lean into test philosophy and mutation methodology rather than design, so part of the document is process guidance rather than DDD content.

## docs/PRD-4-7-IDENTITY-AND-RENDERING.md
- EARNS EXISTENCE: YES, but with slack.
- Finding: it adds a collective purpose across TRD-4/5/6/7 (“the single thread running through all four is identity”) that the underlying TRDs may not carry as a group.
- Finding: it adds product priorities in §5 and scope decisions in §6, including “The queue last” except `T6-13a`, which is sequencing and scoping above criterion level.
- Limitation finding: much of §4 is close to a curated restatement of criteria as P1–P9 with direct proof links; this is useful traceability but not strongly distinct from the TRD layer.
- Finding: despite that slack, the document should still exist because it makes an explicit product call about whether TRD-6 gets built this cycle and presents a smaller shippable scope.

## docs/DDD-4-7-IDENTITY-AND-RENDERING.md
- EARNS EXISTENCE: YES.
- Finding: it adds concrete design choices the TRDs would not ordinarily carry: one graph/no second builder, one view table/two projections, four prompt types, refine Variant A vs B, and queue design shape.
- Finding: it maps duplicated ownership across named modules and identifies consolidation points such as `DEFAULT_VIEWS` / `ANCHOR_VIEWS`.
- Finding: it records built-state movement across specific commits and uses that to justify design constraints; that is implementation/design detail, not requirement restatement.

## docs/PRD-8-10-AUDIO-FLEET-AND-LIBRARY.md
- EARNS EXISTENCE: YES.
- Finding: it adds a rationale absent from forward-written TRDs: these three were written “backward” from a reconciliation of shipped code and plans, especially TRD-9 as specification of already-working production machinery.
- Finding: it adds cross-document prioritisation in §4 and product ownership of P9, which it says has “no owner anywhere else.”
- Finding: it distinguishes built-vs-unspecified risk for TRD-9 in a way a TRD normally would not.
- Limitation finding: like the other PRDs, the P1–P9 table is partly a traceability restatement.

## docs/DDD-8-10-AUDIO-FLEET-AND-LIBRARY.md
- EARNS EXISTENCE: YES.
- Finding: it adds explicit schema design for `takes` and `voices`, live-fleet seam design, and bulk-edit/advice implementation structure.
- Finding: it identifies what is genuinely new versus “tests for behaviour that is correct and unspecified,” which is design/planning content not carried by TRDs.
- Finding: it states design rules such as “assert through `screen_prompt_field`, not through each caller,” which are implementation/test-shape constraints above raw requirements.

2. Contradictions

## Between PRD-1-3 and DDD-1-3
- Contradiction: PRD-1-3 §6.0 says “The set timeline goes last” and that §6’s earlier P1 “timeline first” is superseded. DDD-1-3 §6 still presents the build-order graph with `qc_service pattern -> sets_service -> clock/rounding, peaks, preview -> master fix -> audiences` before `storyboard_service -> arc flows, meter, casting`, which reads as timeline/service work preceding storyboard-service work.
- Contradiction: PRD-1-3 “Deferred to another document, on purpose” says “The queue and the wait-state scheduler (TRD-6 …)” are deferred, while §6.0 also says “The queue is rewritten in full” and “TRD-6 §1-§6 is in scope.” That is an internal contradiction in the PRD, and DDD-1-3 follows the in-scope reading by depending on `qc_service pattern` and inherited `T6-A*` rules.
- Contradiction/UNSURE: PRD-1-3 “Already built and deployed” includes `studio/automation.py` as “TRD-1 §5's curve model, decimation and filter emission,” while DDD-1-3 §5.3 says “What is left is the criteria that prove the lanes reach the render.” This may be a built-vs-proven distinction rather than a contradiction, but the PRD wording is stronger and can be read as feature completeness.

## Between PRD-4-7 and DDD-4-7
- Contradiction: PRD-4-7 §5 says “Make a view cheap (P4)” first, then “Make the words editable and versioned (P6),” then “Prove identity holds (P5's `T7-7`).” DDD-4-7 §4 places shipped identity-lock work and surrounding design before unresolved view-table consolidation, and §2 says `T7-1` is not done. This is not a logical contradiction in content, but the DDD emphasis/order does not align cleanly with the PRD’s stated priority order.
- Contradiction/UNSURE: PRD-4-7 §6 says “Out … the render queue (TRD-6)” while the PRD title and opening scope are “TRD 4-7” including TRD-6, and §4 includes P8/P9 for pull-based work and canonical path. The document both includes TRD-6 outcomes and says the render queue is out. DDD-4-7 §6 likewise discusses TRD-6 design in detail while also stressing it is machinery that does not exist and may not be built first.

## Between PRD-8-10 and DDD-8-10
- NOTHING FOUND.

## Between pairs
- Contradiction: PRD-1-3 §6.0 says “The queue is rewritten in full” and that “TRD-6 §1-§6 is in scope,” while PRD-4-7 §5 says “The queue last” and PRD-4-7 §8 raises “Whether TRD-6 gets built at all this cycle.” The two PRDs assign materially different cycle/scope status to TRD-6.
- Contradiction: PRD-1-3 says “The set timeline goes last” because Jon reordered priorities around anchors, QC repair path, and clip length. Yet PRD-1-3 §8 also says “§6's P0 and P1 are the smallest cut that produces something usable — the timeline is the one surface where the current experience is ‘a stack of forms and a number’.” That makes the timeline both deprioritised and the smallest usable cut.
- Contradiction/UNSURE: PRD-8-10 §5 says “Out … the render queue (TRD-6), QC (TRD-3), the set timeline (TRD-1),” while DDD-8-10 repeatedly inherits rule 0 and `TRD-6 §0` and relies on shared queue/fleet concepts. This may be separation of ownership rather than contradiction.

3. Claims that cannot be checked from the document itself

## PRD-1-3
- Uncheckable claim: “Day 4's Traps section, found and fixed six times.”
- Uncheckable claim: “the answer re-orders everything below.”
- Uncheckable claim: “The measuring half is built; nothing repairs anything, because `approve()` raises.”
- Uncheckable claim: “already in flight.”
- Uncheckable claim: “The queue is rewritten in full.”
- Uncheckable claim: “~20 criteria across the three documents were one-sided.”
- Uncheckable claim: the count method in §8 (`grep -cE "^- .T<n>-"`) is named but not reproducible from the document alone because the target files are not present.

## PRD-4-7
- Uncheckable claim: “every defect this project has recorded most expensively has been that character quietly becoming someone else.”
- Uncheckable claim: “Day 8's rule, and day 11 removed the last exception to it.”
- Uncheckable claim: “Day 4 measured it.”
- Uncheckable claim: “Session B shipped `T7-6` on 2026-08-13 (`d315c6f`).”
- Uncheckable claim: “the behaviour is there and correct.”
- Uncheckable claim: “three commits landed mid-review.”
- Uncheckable claim: “B holds every anchor source file.”

## PRD-8-10
- Uncheckable claim: “3,147 lines of shipped code and 1,992 lines of plan documents, none of it owned.”
- Uncheckable claim: “TRD-9 is … yes, entirely, in production.”
- Uncheckable claim: “roughly 1,700 lines, live in production, zero acceptance criteria.”
- Uncheckable claim: “the behaviour is there and correct.”
- Uncheckable claim: “A 5090 laptop, a 5090 desktop, a 2080 Ti in an Unraid container and a 5080 in WSL2.”
- Uncheckable claim: “running the live-fleet ones before every deploy is not.”

## DDD-1-3
- Uncheckable claim: “Every ‘built’ and ‘not built’ below was read off the tree at `f9ca597`.”
- Uncheckable claim: line counts and route counts in §1/§2, because the code tree is not present.
- Uncheckable claim: “Deliberately absent, verified by `grep -rn`...”
- Uncheckable claim: “Reproduced independently by session B at HEAD, same three rows.”
- Uncheckable claim: “FIXED 2026-08-13 by session B.”
- Uncheckable claim: “Measured independently through the real functions after the change.”
- Uncheckable claim: “the argument is already threaded through every caller.”
- Uncheckable claim: “`siglip2_naflex` is installed on peaches.”
- Uncheckable claim: “The refiner is ~19.6 GiB resident and fits neither peaches ... nor a 15.92 GiB card.”

## DDD-4-7
- Uncheckable claim: “Read off the tree at `f9ca597` plus session B's `415584d` / `4032aba` / `d315c6f`.”
- Uncheckable claim: “There is one graph.”
- Uncheckable claim: ownership table assertions.
- Uncheckable claim: “`T7-2` is done in both files.”
- Uncheckable claim: “`T7-8` and `T7-9` shipped while this section was being written.”
- Uncheckable claim: “Every node either needs is installed on cerberus, verified against `/object_info`.”
- Uncheckable claim: “The base render already peaks at 23.4 GB of 23.9 on cerberus.”
- Uncheckable claim: “Production runs `RENDER_BACKEND=swarm`, confirmed on the box” is in DDD-8-10, not here; NOTHING ELSE.

## DDD-8-10
- Uncheckable claim: “Everything below was read off the tree at `c01c977`, deployed to production the same day.”
- Uncheckable claim: “all four have zero references of any kind” from `grep`.
- Uncheckable claim: “Production runs `RENDER_BACKEND=swarm`, confirmed on the box.”
- Uncheckable claim: the four-backend listing and statuses.
- Uncheckable claim: “that criterion was already rewritten once after a mutation audit found it could not fail.”
- Uncheckable claim: “This one worth defending” judgments around `T9-17`.

## UI/UX guide
- Uncheckable claim: “Every number below was counted from the tree at `f9ca597`.”
- Uncheckable claim: all counts in §2 unless the tree is provided.
- Uncheckable claim: “the consultation ... 7.4 KB in, 36 KB back.”
- Uncheckable claim: “Zero fabrications.”
- Uncheckable claim: “all were real and all were in the brief.”
- Uncheckable claim: “The consultation proposed ...” wherever the cited external exchange is not present.

4. Sequencing defects

- Sequencing defect: PRD-1-3 §6.0 says Jon’s decision supersedes the old ordering and puts “Anchors that stay on-model” first, then QC repair path, then clip length, with “The set timeline goes last.” But the same document’s later sequencing still contains full P1/P2/P3 blocks in old order and only partly annotates supersession. This leaves two incompatible orders in one document.
- Sequencing defect: PRD-1-3 says “The queue is rewritten in full” and also says “The queue and the wait-state scheduler ... Deferred to another document, on purpose.” A dependency cannot be both in-scope now and deferred.
- Sequencing defect: PRD-1-3 P0 item 2 says “The service split, TRD-1 and TRD-2 (`T6-A3`). ... Doing this after the features means writing them twice.” But §6.0 says queue rewrite/TRD-6 is in scope and clip-length chain waits on `T6-13a`, while P2/P3 still describe feature work not clearly gated on that split. The actual order is ambiguous in a way that matters.
- Sequencing defect: PRD-4-7 says “The queue last ... except `T6-13a`,” while PRD-1-3 says the queue rewrite is in scope now and no longer deferred. The cross-document dependency ordering for TRD-6 is inconsistent.
- Sequencing defect: DDD-1-3 §6 puts `qc_service pattern -> sets_service` and `storyboard_service` as a dependency path, but PRD-1-3 §6.0 elevates anchor/identity and QC repair path ahead of timeline work. The DDD build graph is not updated to the PRD’s superseding order.
- Sequencing defect/UNSURE: PRD-1-3 says “Nothing in P5 can start until this lands” about `T2-12a`, but DDD-1-3 §5.5 says “The argument is already threaded through every caller and the value is already recorded on the `storyboards` row.” If caller threading and storage are already present, some P5-adjacent UI work might be possible before `T2-12a`; the blanket sequencing claim may be overstated.
- Sequencing defect: PRD-8-10 prioritises TRD-9 first because “Everything else in the project renders through it,” but PRD-1-3 and PRD-4-7 both discuss active work and blockers in TRD-6/queue/fleet areas without depending on TRD-9 first. The “everything else” dependency is too strong as written.

5. UI/UX guide, especially 7a and 7b

## Section 7a
- Finding: §7a.1 introduces a “matrix” interaction for `_anchor_form.html` without specifying how the operator edits, compares, or audits inherited/default prompt values versus overridden values across cells. Since `T7-19` exists because one box per tier was wrongly reused across views, omission of default/override visibility is a material gap inside the proposed UI itself.
- Finding: §7a.1 says “Editing a cell opens the prompt for that cell” but does not say where version history, usage count, tier policy, or screening/refusal feedback appear for that cell. Section 7a.4 later says one `versioned-field` includes those elements, but the matrix design and the `versioned-field` design are not joined operationally.
- Finding: §7a.2 adds a new capability-specific three-valued chip vocabulary that overlaps with §5.4’s “Five states, five colours, one meaning each, everywhere.” This is a local extension to the state language after §5.4 had already claimed one meaning each everywhere.
- Finding: §7a.2 says capability specifically gains “one member,” but it introduces three labels (`available`, `unavailable`, `unknown`) and maps them onto existing roles in a way that is not reconciled with the six job states plus “candidate awaiting a human” from §3 principle 4.
- Finding: §7a.3 says a control whose backend cannot honour it is “absent, or present and marked with the reason.” That permits two different treatments for the same defect class, reducing consistency at the exact point the section argues consistency matters.
- Finding: §7a.3 cites “When `T7-8` lands” although DDD-4-7 says “`T7-8` and `T7-9` shipped while this section was being written.” The guide’s wording is stale against the paired DDD.
- Finding: §7a.4 says a type added to `PROMPT_TYPES` appears with no template change, but §7a.1’s matrix is view × tier based and §7a.4’s `versioned-field` is type based. The guide does not explain how generated `view:<key>` prompt types coexist with the tier/view matrix without duplicating UI surfaces.
- Finding: §7a.4 says usage count counts renders not loads, but no document here supplies where that count comes from or whether it exists. This is a UI promise without supplied backing.
- Finding: §7a.6 says page-level status should report how many anchor batch candidates have landed, but does not define candidate identity on the page when batches are `seed + k*137`; a reader is left UNSURE how partial completion is mapped back to visible rows/tiles.

## Section 7b
- Finding: §7b.1 says the take tile is “`media-tile` with an audio body,” but the same guide’s component inventory defines `media-tile` around image/clip + controls + verdict and says waveform-as-data needs different treatment in TRD-1. The document does not specify the audio-body variant enough to know whether this is real reuse or only a naming analogy.
- Finding: §7b.1 says comparison requires takes “sit in a row that can be played in turn without leaving the page,” but gives no control/state rules for concurrent playback, stop/solo behavior, or how “picked/unpicked” state is shown while auditioning.
- Finding: §7b.2 says the consent precondition should be shown in `plan-panel` shape before submit rather than as red text after failed submit. It does not say whether submit is still server-refused if the precondition is unmet. As written, it risks moving a hard gate into advisory-only presentation.
- Finding: §7b.3 says the fleet page is where `available` / `unavailable` / `unknown` is read, then adds “last asked” and stale-read logic, but does not state how stale interacts with unknown/unavailable. A stale “available” and an “unknown” are different states and the section does not disambiguate them.
- Finding: §7b.3 says an empty registered backend is “marked as a hazard, not as healthy” (`T9-9`), but no general visual language for “hazard” is defined elsewhere in the guide. It is not one of the five colour roles in §5.4 or the states in §5.7.
- Finding: §7b.4 says bulk-edit pre-write count is “part of the control, not a toast,” but does not state when it recalculates relative to live filters/sorts or whether it updates before or after selection changes. Given the section’s own emphasis on scope visibility, this omission matters.
- Finding: §7b.5 says one treatment is used for every model-authored string, listing “the arc proposal, the mix advice, the contact-sheet description, the QC remedy.” The same sentence then contrasts it with measurement, but QC remedy is also described elsewhere as actionable text tied to a remedy class and approval flow. The guide does not resolve whether a QC remedy is advice-like, action-like, or both.
- Finding: §7b.5 states “model text carries the `--muted` role,” which may clash with §2.3’s existing high-frequency use of `muted` as a generic component class, risking model-authored text becoming visually similar to ordinary secondary copy rather than distinctly caution-marked.
- Finding: §7b.5 says “A number without a unit is a claim, not a measurement,” but the guide does not define how non-numeric but measured statuses are presented, leaving the distinction between advice and measured verdict under-specified.

## UI/UX guide outside 7a/7b
- Finding: §5.1 navigation lists “Library · Albums · Anchors · Sets · Jobs · Tiers · Config,” but earlier §2.5 says current nav order from TRD-2 §7 is “Library → Playlists → Anchors → Sets → Jobs → Tiers → Config,” while the defect statement there had “Playlists” before “Anchors.” The guide changes both label and order while treating only the label as the main issue.
- Finding: §5.5 says “Status exists at three levels, and today only one of them is built,” then immediately says the studio has shell and a one-page version of action. The “only one built” statement is overstated against its own text.
- Finding: §8 says “The nav matches the agreed order, asserted against one list that both `base.html` and the API read (`T6-A2`: the page and the JSON report the same thing).” No document here supplies such an API list for nav; this is an unsupplied implementation dependency.

6. What is missing and no document supplies

- Missing: a canonical mapping of the six document pairs to the ten TRDs beyond grouped coverage. The PRDs group ranges, but no document here gives a complete studio-wide ownership matrix showing which product/design doc owns each TRD and which cross-cutting rules override conflicts.
- Missing: a resolved, single source of truth for TRD-6 scope and timing. Across PRD-1-3 and PRD-4-7, TRD-6 is alternately in scope, out of scope, last, partially first, and maybe not built this cycle.
- Missing: explicit definitions for “Jon,” “session B,” and the authority of those decisions/commits in document governance. They are repeatedly used as decision sources, but no document here says how that status is tracked or superseded.
- Missing: a stable built-state ledger location. Multiple docs say built-state claims drifted within hours, yet no document here defines one authoritative place readers should trust next.
- Missing: for UI/UX §7a matrix editing, the inheritance/override model for prompt values across tier, view, and prompt type. The guide proposes a matrix and generated types, but no document supplies the interaction contract.
- Missing: for UI/UX capability states, a unified state model spanning job states, capability availability (`True`/`False`/`None`), candidate/approval state, stale/liveness state, and hazard state. The guide adds local vocabularies but no document consolidates them.
- Missing: a document-supplied contract for how page-level status blocks identify “this song / anchor / set” jobs against artefacts and queue rows. The guide asks for it; the DDDs discuss artefacts and canonical paths; no provided document closes the UI-facing join.
- Missing: an explicit rule for how model-authored text is stored, labelled, and rendered across all named modules. PRD-8-10 says P9 has no owner elsewhere; UI/UX adds visual treatment; DDD-8-10 calls it a payload contract. No single provided document supplies the end-to-end contract.
- Missing: a concrete mobile scope. The UI guide says mobile is a real target and names what must work small, but no document supplies interaction or API constraints specific to approve/dismiss/look-at-picture on small screens.
- Missing: acceptance/verification ownership for the style guide itself. §8 names checks, but no PRD/DDD pair covers who builds or runs them, and no sibling design document owns front-end architecture as a system.
- Missing: a glossary for domain terms whose user-facing labels are contested: “Playlists,” “Albums,” “Sets,” “Anchors,” “Refs,” “Candidates,” “Takes.” Several docs rely on these distinctions; the UI guide explicitly says one label is wrong; no document supplies a canonical vocabulary.
- Missing: a single dependency graph across all three PRD/DDD pairs. Each pair has local sequencing, but the contradictions around TRD-6, timeline, fleet, and anchor work show the absence of one studio-wide ordered plan.
