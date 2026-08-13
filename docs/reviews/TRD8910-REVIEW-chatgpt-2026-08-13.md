## 1. CRITERIA THAT CANNOT FAIL that the documents' own positive-half tables MISSED

### TRD-8
- `T8-3` looks one-sided in practice. “A take records which path produced it” can stay green if no take row is recorded at all for one or more paths, or if only one path remains reachable. Missing positive half: demonstrate **generated**, **resynthesised**, and **bridged** each produce a take that is listed with its path.

- `T8-5` is half a criterion as written. “The audio path still bounds what it accepts and says which bound refused” can pass if the path refuses all requests, or if only refusal text exists without a success path near the boundary. Missing positive half: values just under each of `MAX_TAGS`, `MAX_LYRICS`, and `MAX_AUDIO_SECS` are accepted, and values just over are refused naming the bound.

- `T8-6` is mostly stated as a regression on one failure case. It can miss the “cannot fail” shape on the “within a crossfade of either edge” wording if only one edge is tested. Missing positive half: both start-edge and end-edge spans splice successfully, preserving length.

- `T8-9` is one-sided. “`mixer.bridge_seconds()` is the only place bridge arithmetic exists” can stay green if the route no longer computes anything because the feature is deleted or hard-refused. Missing positive half: a valid replace-span request succeeds through the route while route-level arithmetic changes in `mixer.bridge_seconds()` are observed at the outcome.

- `T8-11` is partly one-sided. The “without one records that too” half can pass if voice references are never accepted anywhere. Missing positive half: one take with a voice reference and one without are both generated and both record the distinction.

- `T8-13` is one-sided. “The editor reads and writes the same automation model” can pass if the editor is absent or read-only. Missing positive half: an edit written in the song-level editor is then consumed by the shared automation path with the same limits and modes.

- `T8-14` is one-sided. “Predicted length is the rendered length” can pass vacuously if nothing renders or no prediction is emitted. Missing positive half: a rendered edit returns a prediction before render and the completed render matches it within `mixer.SET_DURATION_TOLERANCE`.

- `T8-15` is one-sided. “Preview says it is a proxy and lists what it does not apply” can pass if preview is removed. Missing positive half: a preview endpoint returns proxy data plus a non-empty list of omitted effects/operations.

### TRD-9
- `T9-5` is one-sided. “Sorted to the back, not dropped” can pass if no such backend is ever considered. Missing positive half: a render attempt plan containing both fitting and non-fitting resident-capacity backends still includes the slow-streaming one later in order.

- `T9-7` is one-sided. It asserts a walk behaviour but not a constructive counterpart. Missing positive half: after one refused attempt, a subsequent attempt is still made according to the walk, and the sequence is observable.

- `T9-10` is one-sided. “A cache hit is not a refusal” can pass if A/B tests are never run or if empty outputs are treated uniformly. Missing positive half: with different seeds, the same path produces a real output where the byte-identical resubmission does not.

- `T9-11` is one-sided. “A node-missing refusal must be distinguishable from a stale node list” can pass if neither case occurs or all node failures are merged. Missing positive half: one real unsupported-node case and one stale-node-list case produce distinguishable records.

- `T9-12` is one-sided. “`/history` staying at 0 is not evidence a box did not run” can pass if nobody checks authority. Missing positive half: a SwarmUI-routed job leaves `/history` unchanged while the container log shows execution for the same job.

- `T9-13` is one-sided. “Nodes are never the discriminator; files are” can pass if capability checks stop running. Missing positive half: two boxes with the same nodes but different weights/names are distinguished correctly by file/model presence.

- `T9-15` is one-sided. “Free VRAM is measured before the render, and recorded with the result” can pass if only preflight logging exists and no successful render occurs. Missing positive half: a render result contains the recorded pre-render VRAM measurement.

- `T9-16` is one-sided. “No credential is stored in the repo, and the store names where a key came from” can pass if credentials are unsupported. Missing positive half: a credential loaded from the external store is usable and its provenance is recorded.

### TRD-10
- `T10-1` positive half is incomplete for the stated requirement. It checks provider switching, but not “at call time not import time” across both modules named in §2. Missing positive half: repeated calls within one long-lived process switch provider after gateway state changes for both `lyrics.py` and `vision.py`.

- `T10-2` is one-sided. “Falls back to the paid path says so in the record” can pass if the paid path is never used or no record is stored. Missing positive half: one local call and one fallback call both record provider, with the fallback specifically marked.

- `T10-6` is one-sided. “One transaction” can pass if the endpoint always refuses before writing. Missing positive half: a successful multi-row bulk edit writes all target rows in one request, while an induced failure writes none.

- `T10-7` is one-sided. “The count of what will change is shown before the write, and it is the count that actually changes” can pass if the preflight count is always zero or writes are disabled. Missing positive half: a batch with a non-zero predicted change count writes exactly that many changed rows.

- `T10-8` is one-sided. “A transcription records which backend produced it and that it is a transcription rather than supplied text” can pass if only one lyric source exists. Missing positive half: one supplied-text case and one transcription case are both stored and remain distinguishable.

- `T10-10` is one-sided. “An empty result is explicit rather than an empty string” can pass if lyric fetch is disabled entirely. Missing positive half: one song with genuinely no lyrics and one failed fetch are stored as two different explicit states.

- `T10-14` is one-sided. “A model is never asked a question whose answer it cannot be wrong about visibly” can pass if prompts are not sent at all. Missing positive half: an allowed prompt shape such as “describe what differs” is accepted and reaches the model.

- `T10-15` is one-sided. “Advice is relational and says what it is relative to” can pass if no advice is shown. Missing positive half: a set-level advice response includes neighbour/context references that change when the surrounding set changes.

- `T10-17` is one-sided. “Free text ... is bounded and screened by the one shared guard” can pass if all text entry is refused upstream or one module is dead. Missing positive half: representative free-text entries through each of the four modules pass through the same bound/screen decision path and succeed for valid input.

---

## 2. CONTRADICTIONS

### Against inherited-rule handling
- NOTHING FOUND on direct restatement of `T6-A1`…`T6-A6`. The repeated “cited, never restated” language appears compliant from the text given.

### Between these three
- `TRD-9` cites `T6-4` and `TRD-10` cites `T6-14`. The context only states inherited rules in `TRD-6 §0` as `T6-A1`…`T6-A6`. This is not necessarily wrong because TRD-6 may have later criteria outside §0, but with the provided context it is **UNSURE** and worth checking. If those ids do not exist, the alternative is to cite the actual existing criterion id or the owning TRD/section without inventing one. Measurement: verify whether `T6-4` and `T6-14` exist in `TRD-6`.

- `TRD-8 §6` says the editor “reads and writes the same automation model as the set timeline,” but `T8-15` says preview lists what it does not apply. This is not a contradiction by itself, but it creates an **UNSURE** ambiguity: if preview omits operations that affect duration, it may conflict with `T8-14` “predicted length is the rendered length.” Alternative: constrain `T8-14` to final render, or require preview omissions never affect length. Measurement: compare predicted length from preview-inclusive flow to final rendered length for edits using omitted operations.

---

## 3. BOUNDARY DEFECTS

- Guardrail ownership is split across `TRD-8` and `TRD-10`, but the boundary is not fully owned. `TRD-8 T8-4` covers child mentions accepted on audio and refused on image/video. `TRD-10 T10-16` says the image guardrail applies to every surface that reaches an image or video render, and not to audio. Missing owner boundary: advice surfaces in `vision.py` that ask image questions but may not directly render. Are they guarded because they “reach an image,” or only when they “reach an image or video render”? The wording leaves a seam. Measurement: enumerate `vision.py` entry points and test whether each free-text path is screened by the shared guard and/or image guardrail.

- Audio generation vs queue/lifecycle ownership: `TRD-8 T8-7` requires route refusal before GPU runs and job-level backstop if the track changes length between enqueue and run. `TRD-6` is said to own queue/lifecycle/storage, but from this text no criterion clearly owns the cross-document state transition “source media changed after enqueue.” This looks like a classic disowned dependency seam. Measurement: enqueue a span replace, mutate track length before worker execution, verify which document’s criterion catches and records the refusal.

- Backend selection per call is claimed by `TRD-10` for `lyrics.py` and `vision.py`, while `TRD-9` owns fleet/backend availability and alerting. The boundary “who decides local gateway availability at call time” is not explicitly owned. If gateway state caching exists below the call site, `T10-1` could fail for reasons in TRD-9 with no criterion there. Measurement: force gateway down/up without process restart and observe whether the provider choice changes because of fresh fleet state rather than stale cached state.

- `TRD-8 T8-2` says picking one take is a separate act with its own record, but no cited owner is named for the song-level selection/promotion record. Since TRD-6 owns lifecycle/storage generally and TRD-8 owns audio generation/editor, the exact owner of “pick a take” appears split. Measurement: verify whether there is a persisted record for the pick action distinct from take creation, and identify which criterion asserts it.

- `TRD-10 T10-12` says accepting advice writes and records that it came from a model. `TRD-6` owns JSON reachability and lifecycle/storage; `TRD-10` owns advice surfaces. The boundary “accepting a proposal as a stored change” may also overlap with TRD-1 or TRD-2 depending on what surface is being advised. From these texts, ownership of proposal-acceptance persistence is not fully pinned. Measurement: for each advice surface, verify there is a separate accept action and a persisted provenance record.

---

## 4. DECISIONS THAT LOOK WRONG, with the measurement that would settle it

- `TRD-8 T8-12` being an acceptance criterion looks wrong. The document itself marks its positive half “provisional” until a cloning path exists. Alternative: move it to explicit non-scope / precondition rather than acceptance until there is a real path to test. Measurement: determine whether any reachable voice-cloning path for a real named person exists today. If none exists, this criterion is not yet measuring shipped behaviour.

- `TRD-8 T8-4` uses one specific content example to split audio from image/video policy. The decision may be right, but the criterion shape may be too narrow if the actual boundary is “depiction-related image guardrail does not apply to music text.” Alternative: measure a small class of minor-related but non-depictive lyric/tag phrases, not one phrase. Measurement: acceptance/refusal matrix across audio, image, and video for several minor-related prompts differing in depictive content.

- `TRD-9 T9-3` says the free draw goes out “byte-identical” and is asserted by “object identity.” Object identity looks wrong as a measurement for byte-identical output across submission boundaries. Alternative: compare canonical serialized bytes/hashes of the submitted workflow, plus backend-call counts. Measurement: serialize the workflow before and after free draw and compare bytes or digest, while separately verifying no `ListBackends` calls.

- `TRD-9 T9-9` says “staging weights is a prerequisite for registering a backend, and the criterion is that registering an empty one is refused or flagged.” “Refused or flagged” looks too loose; those are different operational decisions. Alternative: choose one behaviour. Measurement: attempt to register an empty backend and observe whether it is rejected before becoming schedulable, versus merely alerted after it can already receive jobs.

- `TRD-9 T9-12` says the authority is the container log. That may be the practical authority, but it looks brittle as a decision if logs rotate or are incomplete. Alternative: persist a studio-side execution record keyed to job/backend independent of container logs. Measurement: for SwarmUI-routed jobs, compare reliability of container-log attribution versus any existing studio-side job record across restarts/log rotation.

- `TRD-10 T10-14` says “Does this match the reference?” is refused as a prompt shape. That may be right, but banning a shape rather than requiring a measurable decomposition may be too coarse. Alternative: permit only prompts that require enumerated differences or evidence-bearing structured output. Measurement: compare error rates on ranking/match tasks between yes/no prompts and structured difference prompts against a known-answer set.

---

## 5. WHAT IS MISSING

### TRD-8
- No criterion covers the separate act of **picking** a take beyond saying it has “its own record.” The behaviour is implied by `T8-2`; no acceptance criterion here names success, persistence, listing, or playback after pick.

- No criterion covers whether take metadata copied “onto the take” in `T8-1` is also returned consistently on both HTML and JSON surfaces under inherited `T6-A1`/`T6-A2`. Implied, not covered here.

- No criterion covers failure handling for generated audio files copied into `db.DATA/audio/<slug>/` if file copy/storage fails after generation. Implied by “takes copied into the studio's data dir,” uncovered here.

- No criterion covers the editor’s **media menu** even though the defer quote names “the song-level audio editor and the media menu.”

### TRD-9
- No criterion covers the declared “one branch point” `RENDER_BACKEND` seam itself: selecting `comfy` default versus another backend and preserving equivalent outcomes/contracts is implied by §2, not covered.

- No criterion covers `pipeline.install_input` cleanup/lifecycle after rsync staging. Input staging exists, but persistence/removal/error recovery behaviour is not covered.

- No criterion covers `creds.py` rotation/update semantics, only non-repo storage and provenance.

- No criterion covers interaction between `fleet_watch.py` state and routing decisions beyond alerts. A box changing state implies candidate set changes; no criterion here covers routing response to that state.

### TRD-10
- No criterion covers the **library page sortable headers** named in §2.

- No criterion covers `genres.json` vocabulary evolution effects on existing stored songs: what happens if a formerly valid value disappears is implied by server-side validation scope, but not covered.

- No criterion covers edit-instruction parsing in `vision.py` despite listing it as built.

- No criterion covers chat-provider output labelling/provenance beyond fallback cost attribution and model-authored marking. For example, provider/model identity for non-fallback successful calls is implied but not covered.

- No criterion covers what record shape distinguishes “proposal retained” from “accepted result” across advice surfaces, although `T10-12` implies both must be answerable later.

---

## 6. ANYTHING YOU WOULD CUT

- `TRD-8 §8` “listen to it.” As written here, it is direction, not a falsifiable criterion, and risks unverifiable review language.

- `TRD-9 §5` items that are pure diagnostic cautions may not all belong as acceptance criteria unless each is tied to an observable persisted distinction. The weakest from text alone are `T9-12` and possibly `T9-13`; both read more like operator notes unless there is a concrete product behaviour under test.

- `TRD-8 T8-12` until a real cloning path exists. The document already admits the positive half is provisional.

- `TRD-9 T9-7` if it remains “asserted as a behaviour of the walk, not a timing test” without a sharper observable. In current wording it is vulnerable to being true of many implementations and hard to falsify.

- `TRD-10 T10-14` in its current prompt-shape form, unless rewritten into a measurable allowed/disallowed prompt contract. The decision may be sound; the criterion text is policy-shaped more than test-shaped.
