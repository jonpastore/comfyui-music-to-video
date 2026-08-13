1. CONTRADICTIONS BETWEEN the three documents.

- **Queue/scheduler ownership is inconsistent between TRD-2 and the other two.**  
  - `TRD-1 §11` says the general render queue / wait-state scheduler is owned by `docs/TRD-6`, and TRD-1 only enqueues one `render_set` job.  
  - `TRD-3 §9` likewise says the queue and scheduler are `docs/TRD-6`.  
  - But `TRD-2 T2-11` says “**TRD-2 owns this rule, not the scheduler**” and requires readiness semantics for chained clips now.  
  This is a real boundary contradiction: `T2-11` requires queue-state behaviour while `TRD-1 §11` and `TRD-3 §9` move that model out to TRD-6.

- **TRD-2 still claims “One scene is one clip” while later sections allow a scene to split into multiple clips.**  
  - `TRD-2 §3.4` says: “**One scene is one clip. A scene longer than the measured render ceiling splits**...”  
  - `TRD-2 T2-10` then explicitly requires a long scene to produce a **chain of clips**.  
  - `TRD-2 T2-48` also requires a 30 s scene to split into model-sized clips.  
  Internal contradiction in TRD-2, but it matters cross-document because `TRD-1 §3.2` says a set item is a “rendered song” driven by storyboard clip length, and `TRD-3 §2.3(1)` says expected clip duration comes from the workflow request. The surviving rule is “scene-driven planning may yield multiple clips per scene,” not “one scene is one clip.”

- **Clip fps ownership/expectation is inconsistent across TRD-2 and TRD-3.**  
  - `TRD-2 W1-5` / `T2-13d` says **one output fps per song** after normalisation of mixed-model clips.  
  - `TRD-3 §4.2` says clip QC checks `fps` against **the workflow’s request** per clip.  
  - `TRD-3 T3-2` says tier-1 checks read the submitted workflow’s own request, not constants.  
  This is not fully contradictory if the workflow request is already normalised before clip render, but neither document says whether the workflow’s requested fps for a clip is its native model fps or the song-normalised fps. **UNSURE** because the clash may resolve in TRD-6’s persisted workflow shape, which is referenced in `TRD-3 §9` but not provided here.

- **Model-availability semantics differ in strength between storyboarding and QC repair routing.**  
  - `TRD-2 T2-45` says a mixed-model song is refused before enqueue if any named model is unavailable on every reachable backend per `models.where()`, explicitly respecting `False` vs `None`.  
  - `TRD-3 T3-23` says repair routing asks `models.where()` / `models.fits()` / `models.resolve()` and refuses if pinned to a box under a bad name.  
  This is not a direct contradiction on its own, but `TRD-2 T2-45` treats `None` as a candidate state at planning time, while `TRD-3 T3-23` does not state the same three-valued handling for repair routing. **UNSURE** whether contradictory or just underspecified.

- **TRD-1 says export format addition is “a row, not a code change,” while TRD-3 depends on persisted workflow requests including expectations for QC.**  
  - `TRD-1 T1-24` says adding an export format is just a table row of ffmpeg parameter sets.  
  - `TRD-3 T3-2` requires QC expectations to be read from “the submitted workflow’s own request.”  
  If a new export row introduces a new container/codec combination with different ffprobe/reporting behaviour or omitted expectation fields, `T1-24`’s “no code change” is stronger than `T3-2`’s requirement that QC know what was requested. **UNSURE** because the workflow schema is not shown; this may be satisfiable if export rows are fully represented in persisted requests.

2. ACCEPTANCE CRITERIA THAT CANNOT FAIL - any T1-n/T2-n/T3-n still satisfiable with the feature deleted. Name the id and the mutation that leaves it green.

- **T1-16** — delete dynamic computation of `not_applied` and return a static proxy payload that always includes a generic list.  
  `TRD-1 T1-16` asserts adding an effect makes it appear in `not_applied`, so it is better than pure presence, but if preview itself is deleted and the endpoint always returns a static “proxy/not_applied” list broad enough to include the tested effect, the criterion can stay green without any actual preview-feature coupling.

- **T1-19** — delete one-button master application but still record a named/versioned chain on the render row.  
  `TRD-1 T1-19` checks recording/readability afterwards, not that the recorded chain affected output. Mutation: persist metadata only, perform no mastering DSP. Criterion remains green.

- **T1-20c** — delete reuse of the same chain and instead record easy mode as “this same chain” metadata while using no chain or a different implementation.  
  `TRD-1 T1-20c` only states identity by spec text; no differential in the criterion distinguishes shared implementation from parallel implementation or no-op plus recording.

- **T1-25** — delete the flagging behaviour and only write measured loudness/true peak into the asset row.  
  `TRD-1 T1-25` combines two requirements, but the measurable acceptance text given is naming the measurement in the asset row. Mutation: always write numbers, never flag out-of-tolerance renders. Criterion can still look satisfied unless the test explicitly forces an out-of-tolerance render and checks the flag, which the text does not say.

- **T1-26** — delete use of old renders anywhere in UI/API while still writing a new file beside the old one.  
  `TRD-1 T1-26` only checks coexistence of both files and asset rows. Mutation: history/listing/selection feature deleted; criterion remains green.

- **T2-15** — delete the “reject proposal” action entirely, provided proposals are never auto-saved.  
  `TRD-2 T2-15` says proposal is not saved until accepted; rejecting leaves previous arc untouched. Mutation: remove reject path and leave proposal ephemeral until accept. Criterion still green.

- **T2-16** — delete all multi-song apply capability.  
  `TRD-2 T2-16` says the wand never writes to more than one song at a time without confirmation. Mutation: remove any path that writes to multiple songs. Criterion stays green while the guarded feature is absent.

- **T2-17** — delete editing/consumption of the prompt but keep returning a default prompt string from the API.  
  `TRD-2 T2-17` only requires the prompt be returned, defaulted, and editable before generating. If the edit control exists but generation ignores edits, `T2-19` is meant to catch that; `T2-17` itself stays green with the meaningful half deleted.

- **T2-23** — delete the mismatch flagging and only report total scene time and song length numbers.  
  `TRD-2 T2-23` says API reports total scene time against song length, and flags mismatch beyond tolerance. Mutation: always return the numbers, never flag. The presence half stays green if tests don’t force an over-tolerance mismatch.

- **T2-26** — delete any consumer/use of anchor images while still returning them in the API.  
  `TRD-2 T2-26` is payload presence only.

- **T2-27** — delete any consumer/use of per-scene reference image while still returning it alongside scene data.  
  `TRD-2 T2-27` is payload presence only.

- **T2-29** — delete role-based downstream behaviour while still storing/returning a role on each named character.  
  `TRD-2 T2-29` checks presence/classification, not use. `T2-30` partly exercises use for warnings, but `T2-29` itself remains satisfiable.

- **T2-38** — delete the HTML loop entirely; keep JSON endpoints only.  
  `TRD-2 T2-38` requires JSON driveability with no HTML. Mutation: remove HTML client. Criterion remains green though part of the broader “same backend for both clients” product capability is gone.

- **T3-2** — delete some tier-1 checks entirely, as long as none of the remaining checks use hardcoded duration/frame/fps.  
  `TRD-3 T3-2` forbids hardcoded expectations in tier-1 checks; it does not require any particular tier-1 check to exist. Mutation: remove duration/frame/fps QC checks altogether. Criterion stays green.

- **T3-5** — delete failing checks entirely.  
  `TRD-3 T3-5` guards duplicate findings, but only with a fixture “known to FAIL at least one check.” Mutation: remove all checks except one deterministic failing check, or collapse check set drastically; duplicate protection still passes though most QC value is deleted.

- **T3-7** — delete the “report nearest legal value” half while keeping 8n+1 enforcement.  
  `TRD-3 T3-7` combines two requirements; a test could pass on enforcement alone if it doesn’t assert reported nearest legal value. Mutation: fail illegal counts without reporting nearest legal value.

- **T3-11** — delete all set-QC checks except duration-vs-prediction.  
  `TRD-3 T3-11` can remain green with most of set QC deleted, since it only exercises one check.

- **T3-12** — delete all transition-specific remediation/use, keep only measurement of landing times.  
  `TRD-3 T3-12` is measurement only; any feature acting on that result can be absent.

- **T3-13** — delete any UI/gating integration for tier 2, keep only a calibration report job.  
  `TRD-3 T3-13` requires score implementation and reporting over `zimage_sweep/`; the surrounding feature can be largely absent and this still passes.

- **T3-15** — delete general identity metric deployment and special-case the recorded pair.  
  `TRD-3 T3-15` is one recorded-pair ordering check. Mutation: implement no general usable metric, only a narrow comparator or fixture-specific branch that gets this pair right. Criterion stays green.

- **T3-16** — delete any future gate-building capability.  
  `TRD-3 T3-16` says if distributions overlap, report so and do not build the gate. Mutation: never build any gate at all. Criterion stays green on overlapping distributions.

- **T3-19** — delete the actual repair execution path, but enqueue two different placeholder jobs carrying different edited texts.  
  `TRD-3 T3-19` checks that edited text is what runs via differential on submitted jobs. If the repair subsystem still does nothing real downstream, this criterion can remain green.

- **T3-21** — delete side-by-side review/scoring UI and merely create a new candidate path while leaving original in place.  
  `TRD-3 T3-21` can pass on file/path creation without the comparative review experience really existing, unless the test asserts visibility and scoring presentation concretely.

- **T3-29** — delete the HTML queue entirely; keep JSON review loop only.  
  As with `T2-38`, JSON-only still satisfies the criterion while part of the intended full system experience is removed.

3. SPECIFICATION GAPS all three assume and none states.

- **No document states the canonical persisted workflow/request schema that all three rely on.**  
  - `TRD-1 T1-3`, `T1-4`, `T1-24`, `T1-27` assume a stored model fully determines render/export.  
  - `TRD-2 T2-12`, `T2-12a`, `T2-41` assume planning outputs are canonical and consumed consistently.  
  - `TRD-3 T3-2`, `T3-11`, `§9` assume QC reads “the submitted workflow’s own request” / persisted workflow request.  
  None of the three specifies the shape, versioning, or retention of that persisted request/model.

- **No document states path/asset identity rules across generations, repairs, and re-renders.**  
  - `TRD-1 T1-26` requires new files beside old ones.  
  - `TRD-2 T2-13b` depends on stable clip identities through re-plan.  
  - `TRD-3 T3-5`, `T3-6`, `T3-21`, `§9` depend on artefact identity, change detection, and candidate lineage.  
  TRD-3 says this belongs largely to TRD-6 (`TRD-3 §9`), but the three TRDs all assume it.

- **No document states the single canonical song/clip/set identifier strategy across DB rows, files on disk, and API payloads.**  
  - `TRD-1 §4.1` introduces `automation.set_item_id`; `T1-2` worries about row reuse.  
  - `TRD-2 T2-13b` / `W1-3` rely on stable `clip_idx`; `T2-3` relies on song slug uniqueness in `arc["songs"]`.  
  - `TRD-3 findings.path` joins artefacts by `path` (`TRD-3 §3`).  
  None states how stable IDs and paths relate, or what happens on rename/move.

- **No document states transactionality/concurrency expectations for the one SQLite database.**  
  - `TRD-1 T1-1`, `T1-2`, `T1-27` involve edits, deletes, reorders, and render enqueues.  
  - `TRD-2 T2-5`, `T2-6`, `T2-11`, `T2-13b` involve versioning, readiness, and re-plan stability.  
  - `TRD-3 T3-5`, `T3-18`, `T3-22` involve deduplication, approvals, dismissals, and reruns.  
  All assume correctness under concurrent job workers/API actions; none specifies locking/isolation or acceptable race behaviour.

- **No document states retention/lifecycle policy for derived artefacts and their measurements.**  
  - `TRD-1 T1-26` keeps every re-render.  
  - `TRD-2 T2-13b` preserves approved refs across re-plan.  
  - `TRD-3 T3-21` keeps repaired candidates side by side and `T3-22` requires change detection over time.  
  The system clearly needs storage/lifecycle rules, but none of the three states them.

- **No document states time/tolerance policy beyond local criteria.**  
  - `TRD-1 T1-5`, `T1-6`, `T1-7` use per-frame and 0.05 s tolerances.  
  - `TRD-2 T2-8b`, `T2-23`, `T2-25` mention tolerances around song duration / scene tiling.  
  - `TRD-3 T3-11`, `T3-12` use duration and half-frame tolerances.  
  There is no shared rule for when tolerances are absolute vs frame-derived vs sample-derived.

- **No document states failure semantics for partial pipelines.**  
  - `TRD-1 T1-17` preview render vs full render; `T1-26` re-renders accumulate.  
  - `TRD-2 T2-10`, `T2-11`, `T2-47`, `T2-48` imply multi-clip/mixed-model jobs may partially succeed.  
  - `TRD-3 T3-5`, `T3-21`, `T3-22` depend on distinguishing unchanged artefacts from changed/failed ones.  
  None specifies when a song/set is considered failed, partial, resumable, or publishable.

- **No document states clock-source authority for song duration itself.**  
  - `TRD-1 §3.2` treats set items as rendered songs with variable item fps.  
  - `TRD-2 §3.4`, `T2-8`, `T2-13` derive scene/clip counts from song duration.  
  - `TRD-3 §4.4` says assembled song duration matches source mp3 within tolerance.  
  All assume a canonical song duration value, but none says whether it comes from ffprobe, metadata, decode length, or prior DB measurement.

4. Anything that is WRONG - a claim about behaviour, arithmetic or a filter that is simply incorrect.

- **Wrong ffmpeg pan filter expression for stereo balance.**  
  - `TRD-1 §3.1` gives: `pan=stereo|c0=<l>*c0|c1=<r>*c1`.  
  This does not implement a proper stereo balance operation on general stereo content; it independently scales each output channel from its corresponding input channel and discards any cross-channel terms. That is a simplistic channel gain, not a general “balance” operator. If the intent is “attenuate only the opposite channel,” the formula is incomplete/misleading as stated.

- **Wrong dB claim in the pan discussion.**  
  - `TRD-1 §3.1` says equal-power centre “puts 0.707 on both channels at centre, which is **-3 dB on every item nobody panned**.”  
  0.707 gain per channel is -3 dB **per channel**, but for a centred stereo signal reproduced on both channels the perceived/summed power framing is not simply “-3 dB on every item” in the blanket way stated. The statement is oversimplified to the point of being wrong.

- **Arithmetic error in RIFE drift.**  
  - `TRD-1 §4.3` says the “RIFE one-frame bug ... cost **2.5 s across eighty clips**.”  
  - `TRD-3 T3-8` repeats: “Eighty clips at one frame each is **2.5 s** of drift against the audio.”  
  At 32 fps, 80 missing frames is 80/32 = **2.5 s**; that part is right only if all clips are evaluated at 32 fps. But the same paragraph says 77 doubled to 153 frames gives 4.781 s from a 4.8125 s source, i.e. one-frame short at ~32 fps after compensation. This is internally dependent on the post-processed declared fps. **UNSURE** whether wrong, because the document’s own compensated-fps rule muddies which fps the “one frame each” drift should be measured at.

- **TRD-2’s own “three places” claim is false.**  
  - `TRD-2 §3.4` explicitly corrects itself: “**‘Three places’ was the headline and TWO is the honest number.**”  
  This is already self-identified as wrong in the spec text.

- **The line-count/file-count arithmetic around uncatalogued models was wrong in prior claims.**  
  - `TRD-2 T2-35` says earlier claims of 16 and 15 unaccounted files were wrong; measured live count was 14 before closure.  
  This is already identified in-document as prior arithmetic being false.

- **The claim that `T3-4` can require `measured/expected/unit` on “every finding” is over-broad and conflicts with non-scalar checks.**  
  - `TRD-3 §3` schema has scalar `measured REAL, expected REAL, unit TEXT`.  
  - `TRD-3 T3-4` says “Every finding records `measured`, `expected` and `unit`,” then narrows to named checks that must carry all three.  
  For checks like “opens,” “not uniform,” “not blank,” “alpha not fully transparent” in `TRD-3 §4.1`, a single scalar `measured/expected/unit` is not always a natural or correct representation. The blanket claim is wrong; the narrowed named-list is the only viable version.

- **UNSURE: `TRD-1 T1-9b` uses RMS-per-second slope to verify a -12 dB to 0 dB gain ramp, which is not a reliable direct proxy for gain on arbitrary program material.**  
  If source content changes over time, RMS slope per second can differ from the drawn automation even when the gain curve is correct. The criterion may be testable only on specially constructed source, but the spec text does not say that. This is likely wrong as written, but **UNSURE** without the intended fixture.

- **UNSURE: `TRD-1 T1-21` measures ducking “as RMS per second across the join,” which may miss short overlaps or under-resolve requested duck amounts.**  
  For short transitions, one-second windows are too coarse to prove “reduced by at least the requested amount during the overlap and restored after it.” Likely wrong measurement method, but **UNSURE** because overlap durations are not bounded here.
