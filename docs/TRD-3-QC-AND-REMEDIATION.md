# TRD-3 · Output QC and remediation

Status: draft for review, written 2026-08-12. Supersedes `docs/OUTPUT_QC_PLAN.md` *(absorbed and removed 2026-08-13; in git history)*,
which was written earlier the same day and **predates the scope**: it covers
images and clips only, and it hardcodes expected values that the clip-length
decision has since invalidated. Where this document contradicts that one, this
one is right and §2.3 says why.

Inputs: `docs/OUTPUT_QC_PLAN.md`, `docs/RECONCILIATION_2026-08-12.md`,
`docs/EXTERNAL_REVIEW_2026-08-12.md`, and the fleet measurements recorded in
`SESSIONS.md` for 2026-08-12.

Acceptance criteria are numbered `T3-n` and are written so that each one **can
fail**.

---

## 1. The problem, and the trap it walks into

Asked for: a stage that, after the jobs, analyses output for reference
compliance and for artifacts needing cleanup, and returns a final. Scope has
since grown to **images, audio, video clips, full song videos AND sets**, each
with a compliance percentage, a variation figure, and an explicit statement of
what it can and cannot fix — plus a review queue whose findings carry an
**editable remedy prompt** and an **approve** button.

**A QC stage built the obvious way is this project's signature defect wearing a
lab coat.** Ask a vision model "does this clip match the reference?" and it will
answer yes, confidently, nearly always — and now there is a green tick that means
nothing, attached to a render nobody looked at. Two measurements from 2026-08-12
say this is not hypothetical:

- **A plausible metric was confidently backwards.** A pixel-distance score
  ranked a WRONG image first: the render that had dragged a photoreal tabby look
  through from a pose plate scored 41.1 from the anchor, and the correct one
  scored 64.7 — because the metric measures **composition**, and the correct
  render changed pose on purpose.
- **The identity collapse, the world that never rendered, and the LoRA that did
  nothing were all found by opening the pictures.** All three passed every
  deterministic check that existed.

So: **tiers are never mixed, and each tier earns the next.** A number that has
not been shown to separate known-good from known-bad does not gate anything.

## 2. What exists, and what the predecessor plan got wrong

### 2.1 Already built — do not rebuild

| built | where |
|---|---|
| **Tier 0** — which box produced each artefact | `artefacts(path, backend, host, via, created)`, written by `pipeline._stamp` at the two places a render lands |
| Image repair actuators — face swap, inpaint, outpaint | `fix_ref.py`, on Qwen-Image-Edit 2511, wired as a job + route |
| Video post-processing — interpolate, upscale | `make_postproc.py` + `pipeline.gen_postproc`; writes a NEW file, never overwrites |
| Media probing | `mixer.probe()` (ffprobe: duration, fps) |
| Audio analysis | `analyse.py` (bpm, key, energy, beat grid) |
| Per-box capability and fit | `models.where()`, `models.fits()`, `models.resolve()` |
| Versioned prompts with usage counts and no renumbering after delete | `prompts.py` |
| **Tier 1 itself — every check in §4** | **`studio/qc.py`**: `check_video`, `check_audio`, `check_image`, `check_set`, `run`, `summarise` |
| **The findings table, the queue, and the remedy edit** | **`studio/qc_service.py`** + `db.findings`; `/api/qc/*` and the `qc` job kind in `app.py` |
| **T3-1** per-box report groups by `host`; NULL host is `unattributed` | **`qc_service.by_host`** + `GET /api/qc/by-host` |
| **T3-22** dismissed stays dismissed until the artefact changes | **`qc_service.record`** + `findings.artefact_hash`; same check reopens when the file bytes change |
| **T3-28** identity-wrong never proposes swapping the reference image | **`qc.check_identity_wrong`** / **`qc.identity_wrong_remedy`**; `record` / `set_remedy` / `approve` refuse the swap wording |

**§4 and §6 below read as unbuilt work and are not.** An audit found this table
listing seven items, none of them the QC implementation, in a section whose
stated purpose is "do not rebuild" — the omission most likely to cost a rewrite.
Already satisfied by `qc.py` today: `T3-2` (expectations read from the submitted
workflow, no hardcoded duration anywhere), `T3-4`'s measured/expected/unit on
every check that has them, `T3-7` (8n+1 with the interpolated exemption), `T3-11`
(imports `mixer.SET_DURATION_TOLERANCE` rather than restating it), `T3-27`
(a remedy on every finding), and `T3-3` both ways. Tier 2's calibration
order is built: `T3-13` writes the calibrations row, `T3-14` is a setter
(with a stored row a threshold can be set; without one it is refused,
naming why), `T3-15` ranks the recorded pose pair, and `T3-16` names
overlap inconclusive and builds no gate. There is still no tier-2 UI.
`T3-23` is wired: `dispatch_repair` asks `models.where()` /
`models.fits()` / `models.resolve()`, refuses an unfittable or mis-named pin
before submit, and invokes `pipeline.gen_postproc` or `pipeline.fix_ref` so dest
is the actuator's file. `T3-24` uses the refiner's resident cost (~19.6 GiB),
not the UNET's 13.31: a 15.92 GiB card is skipped, a 24 GiB box that holds the
correct name is SUBMITTED, and peaches cannot take the pair. `T3-25` is a
callable: `can_move_output(host)` — remote repair is refused by that name until
the check is true, and forcing it true SUBMITS. `approve()` enqueues a dest ≠
source; `h_repair` writes that dest only when `dispatch_repair` produces it, and
refuses a silent copy of the broken file.

**Tier 0's two properties that QC must respect**, both from the code that writes
it: group by `host`, never by `backend` (Swarm renumbers ids when a backend is
added); and **either may be NULL** — SwarmUI does not report which box served an
unpinned render, and the stamp records nothing rather than guessing.

- `T3-1` A per-box quality report groups by `host`, and artefacts whose `host`
  is NULL appear in an explicit "unattributed" bucket with a count. Silently
  dropping them would make the fleet look cleaner the more free draws it did.

### 2.2 The calibration set exists and cost nothing

`zimage_sweep/` is 18 renders: the same prompt at six step counts across three
seeds. On seeds …380 and …517 the model draws a woman with bare human legs and a
cat's head at **every** step count; …654 holds fur head to toe. **Twelve known-bad
images and six known-good ones, same prompt, same anchor, same day.**

### 2.3 Three things `OUTPUT_QC_PLAN.md` states that are now false

Corrected here rather than left to be discovered by whoever implements it.

1. **The expected duration and frame count are not constants.** The plan's tier-1
   table says `4.8125s ± tolerance` and `81 @ 16.8312`. Clip length is per song
   from the storyboard now (TRD-2, decided 2026-08-12), so a check against those
   numbers fails every correct 30-second clip. **The expected value is read from
   the workflow the studio itself submitted**, which is the only version of this
   check that is a real differential.
2. **"Audio and video stream durations agree" cannot be a clip check.** Measured
   and confirmed not-a-bug on 2026-08-12: **LTX-2.5 clips are silent by design.**
   The audio is loaded, trimmed and concatenated into the latent so it conditions
   motion, then `LTXVSeparateAVLatent`'s audio output is discarded and
   `CreateVideo` receives only images; `mixer.assemble_song` lays the real mp3
   over at assembly. A clip with no audio stream is correct. This check belongs
   to the **assembled song**, and applied to clips it would fire on every one.
3. **Tier 3's cross-box blocker may already be closed.** The plan says repair on
   a remote box's output is blocked because there is no upload API. Input staging
   by rsync landed the same day (`pipeline.install_input`, `--chmod=F664`). This
   is stated as a **precondition to re-verify**, not as a solved problem —
   `install_input` was written to stage inputs, and the plan's blocker is about
   moving an *output* back the other way.

- `T3-2` No tier-1 check compares against a hardcoded duration, frame count or
  fps. Each reads the submitted workflow's own request. A test renders the same
  storyboard at two clip lengths and asserts both pass; a check pinned to 4.8125
  fails the second one.
- `T3-3` A clip with no audio stream passes. A test asserts an LTX-2.5 clip is
  not flagged for its missing audio, and that the **assembled song** with a
  missing or short audio stream is.

## 3. The finding is the queue

One table. A "review queue" that is a second store of the same rows is two
places for a finding to exist in different states.

    CREATE TABLE IF NOT EXISTS findings (
      id INTEGER PRIMARY KEY,
      path TEXT NOT NULL,              -- joins artefacts(path); the file examined
      kind TEXT NOT NULL,              -- image|audio|clip|song|set
      tier INTEGER NOT NULL,           -- 1 | 2
      check_name TEXT NOT NULL,
      verdict TEXT NOT NULL,           -- pass | flag | reject
      measured REAL, expected REAL, unit TEXT,
      detail TEXT,                     -- human sentence, names the consequence
      remedy_prompt_id INTEGER,        -- prompt_versions row; editable, versioned
      remedy_action TEXT,              -- what approving it RUNS
      status TEXT DEFAULT 'open',      -- open|approved|running|repaired|dismissed
      repair_path TEXT,                -- the NEW candidate; never the input path
      created REAL, resolved REAL
    );
    CREATE INDEX IF NOT EXISTS idx_findings ON findings(status, kind, tier);

- `T3-4` Every finding records `measured`, `expected` and `unit`. **The
  qualifier "for any check that has them" is gone**: it was self-exempting, and
  returning `None` from every check made every check one that "does not have
  them" while the criterion stayed green. The checks that MUST carry all three
  are named — duration, frame_count, fps, luma, silence, loudness, true_peak,
  resolution, duration_matches_prediction — and a `None` in any of them for
  those checks fails. A finding that says only "failed" cannot be argued with, and
  cannot be re-checked after a repair.
- `T3-5` Running QC twice over an unchanged artefact produces one finding per
  check, not two. Re-running is the normal case after a repair. **The fixture is
  an artefact known to FAIL at least one check**, asserted before the second run:
  with a clean fixture, or with every check deleted, "no duplicates" is 0 = 0 and
  the criterion is vacuously green.
- `T3-6` A finding's `repair_path` is never equal to its `path`, **asserted
  only after a repair has actually produced one**. `approve()` now names a dest
  ≠ source and `h_repair` writes that dest when `dispatch_repair` produces it —
  a silent `shutil.copy2` of the broken artefact is refused, because a copy
  marks the finding repaired while dest is still the same bytes. GPU actuator
  dispatch (`T3-23`) is wired: routing asks `where()`/`fits()`/`resolve()` and
  dest is the actuator's file. **A repair
  produces a new candidate and never overwrites** — the studio's whole design is
  candidates plus a human pick, and an overwrite destroys the evidence that
  anything was wrong along with the comparison that would show whether the
  repair helped.

## 4. Tier 1 — deterministic checks

ffprobe, PIL and numpy. No model, no opinion. Every check compares the output
against **what the workflow asked for**, which the studio knows because it wrote
the workflow.

**Tier 1 is the only tier allowed to auto-reject**, and only on checks where no
judgement exists: unreadable, zero-length, wrong duration, all-black. A rejection
writes a row naming the check and **keeps the file**.

### 4.1 Images (anchors, refs, candidates)

opens; resolution as requested; not uniform; not blank; not a single flat colour;
alpha not fully transparent.

- `T3-31` **Each generated anchor candidate is scored by a vision model against
  the operator's base images and the prompt that produced it.** The score is
  stored on the candidate row (`anchors.qc_json`) and shown on the tile. It is
  **advisory**: it never picks, deletes, or rejects. A vision failure stores
  `confidence: null` plus the xAI or local error that caused it. The tile
  names that backend failure (`qc_tag`); it must not collapse it to
  "vision unknown". Still not a fail — the candidate stays pickable. §7
  still forbids a VLM PASS/FAIL as a gate. Mutation: deleting the scorer
  leaves candidates
  with no `qc_json` and the tile has nothing to show.

### 4.2 Clips

| check | expected from | catches |
|---|---|---|
| opens, over a floor size | — | the 38 KB toy that looked like an 827 KB clip |
| duration | the workflow's own frame count ÷ fps | truncated render, 2.3-vs-2.5 graph mismatch |
| frame count | the workflow's request, and 8n+1 | LTX's latent rule violated silently |
| fps | the workflow's request | a box that quietly re-timed |
| resolution | the workflow's request | a box that quietly downscaled |
| mean luma per frame | above a floor | black frames from a dead sampler |
| consecutive-frame difference | above a floor | a frozen segment |
| channel saturation | in range | NaN / green garbage frames |

- `T3-7` The frame-count check enforces **the MODEL'S OWN latent step** and
  reports the nearest legal value when it fails. **Not a universal 8n+1**, and
  this criterion said 8n+1 until a review caught what that meant:
  `EmptyLTXVLatentVideo` declares `step: 8` so LTX wants 8n+1, but
  `WanSoundImageToVideo` declares `step: 4` and WAN's own `LEN = 77` is
  4×19+1 — **not** 8n+1. The check flagged every correctly-rendered s2v clip.
  The step comes from the submitted graph (`build_song.expect_from_workflow`
  records `frame_step`), defaulting to 8, which is the default renderer's rule.
  FIXED in code 2026-08-13; asserted both ways on one 77-frame file.
  *TRD-2 F-2's shared `≡ 1 (mod 8)` rule is about what to ASK FOR when planning
  a new length — every 8n+1 is also 4n+1, so one request satisfies both — and it
  is not a claim about what already-rendered clips must be. 77 is equidistant
  from 73 and 81, so a planner rounding to it must state its tie-break; the code
  rounds half-to-even and lands on 81.*
- `T3-8` **An interpolated clip is one frame short and must not be flagged for
  it.** RIFE returns `(n-1)*m+1` frames, not `n*m`, so 77 doubled is 153; at the
  obvious 32 fps that is 4.781 s where the source was 4.8125 s. Measured
  2026-08-12, and `make_postproc.out_fps` already writes `fps*((n-1)*m+1)/n` to
  compensate. The check reads the post-processed file's own declared fps.
  Eighty clips at one frame each is **2.5 s of drift against the audio**, and it
  fails in the direction nobody looks: the clip plays, looks smoother, and is
  silently the wrong length.

### 4.3 Audio (generated takes, bridges, edits)

New — the predecessor plan has no audio tier at all, and the audio stage shipped
2026-08-12.

opens; duration against what was requested; sample rate and channel count as
requested; integrated loudness and true peak; clipped-sample count; leading and
trailing silence; DC offset; band energy present across low/mid/high.

**The loudness measurement is `effects.py`'s and this tier calls it** — TRD-1
`T1-25` names the same owner. The draft had each document pointing at the other,
which is how a measurement said to be taken once ends up taken twice.

- `T3-9` A silent or near-silent take is rejected. Measured band energies, not
  `aspectralstats` — that filter emits nothing without a metadata printer, and a
  check built on it returned 0.0 for both sides of a comparison and passed on no
  data, behind an `if` that made it a no-op (2026-08-12).
- `T3-10` A spliced track's duration is checked against `mixer.bridge_seconds()`'
  own arithmetic. A span within a crossfade of either edge once deleted audio and
  **lengthened** the song — 20 s spliced at 0.1 s came back 20.193 s — and that
  is the case this check exists for.

### 4.4 Assembled song videos

Everything in 4.2, plus: audio and video stream durations agree; the assembled
duration matches the source mp3 within tolerance; the clip count matches
`clip_plan`; no black gap at a join.

### 4.5 Sets

- `T3-11` **The rendered set's duration equals `mixer.set_duration()`'s
  prediction within `mixer.SET_DURATION_TOLERANCE`** — imported, not restated,
  so it cannot drift away from TRD-1 `T1-7`'s copy of the same number. This is the project's oldest defect — the editor
  promising what the renderer does not produce — turned into a check that runs on
  every set. TRD-1 `T1-7` asserts it at build time; this asserts it on the
  artefact, which is the one that catches a divergence introduced later.
- `T3-12` Each transition lands where the model says it does, within half a
  frame, measured from the rendered file rather than from the plan.

## 5. Tier 2 — compliance as a number, and it gates nothing until it is calibrated

Not "ask a VLM". An embedding distance between the chosen anchor and N sampled
frames of the artefact. A number can be calibrated, plotted, and wrong in a way
you can see.

**The metric must measure identity, not composition.** The 41.1-vs-64.7 result
above is the recorded case of getting this exactly backwards, and it is why
pixel distance is refused by name. `siglip2_naflex` is installed on peaches and
is the right shape; a face embedding (`insightface`) is the alternative.

Reported per artefact: a **compliance percentage** (calibrated, not raw
distance), a **variation** figure (the spread across the sampled frames — the
number that catches drift *within* a long clip, which matters far more now that
chained clips start from a generated frame rather than an approved reference),
and the sample count the two were computed from.

**Order, and it is not negotiable:**

- `T3-13` The score is implemented and run over `zimage_sweep/`'s 12 known-bad
  and 6 known-good images, and the two distributions are **reported** — overlap,
  separation, and the score of every individual file. No threshold, no gate, no
  UI until that report exists.
- `T3-14` **A threshold cannot be configured without a stored calibration.**
  Attempting to set one with no calibration row is refused, naming why. This is
  the criterion that stops "ship a threshold that splits noise".
- `T3-15` The metric does **not** rank a deliberate pose change as an identity
  failure. Asserted against the recorded pair: the correct anchored render must
  score better than the pose-plate render that dragged a photoreal look through,
  which is the ordering pixel distance got wrong.
- `T3-16` If the distributions overlap, the report says so and the gate is not
  built. A tier that reports "inconclusive" is a success; one that reports a
  threshold anyway is the failure this document exists to prevent.
- `T3-17` **Identity drift is scored per artefact, whatever caused it.** The
  draft scoped this to an empty `character_reference` — but TRD-2 `T2-31` refuses
  that at save, so no new storyboard can have one and the criterion would test an
  unreachable state. The failure that remains reachable is the measured one: a
  **non-empty** reference with text that does not name the species renders an
  ordinary human by the halfway point. So this scores the artefact against the
  anchor and does not care which cause produced the gap. Tier 1 cannot see any of
  it; tier 2 is the only tier that can.

## 6. Tier 3 — remediation, through a human

**QC never auto-heals.** Resolved 2026-08-12 and it is not a conflict with
outside review: a finding goes to a review queue **carrying its own comments and
a proposed remedy, that remedy is an EDITABLE PROMPT, and a button approves
reprocessing.** That IS the human sign-off, and it is strictly better than a bare
PASS/FAIL because the finding arrives actionable.

- `T3-18` Nothing runs a repair without an explicit approval. Asserted by
  running QC over a set of deliberately broken artefacts and confirming zero
  jobs were enqueued — **and by the same fixture, once approved, enqueuing
  exactly one**. That second half exists: `approve()` enqueues one `repair` job
  and does not write dest itself. `dispatch_repair` now routes via
  `where()`/`fits()`/`resolve()` and submits `fix_ref` / `gen_postproc`
  (`T3-23`). `T3-24` asks real `fits()` so the refiner's resident cost, not
  the UNET's 13.31, picks the box. `T3-25` consults `can_move_output` before
  submit.
- `T3-19` The remedy prompt is **editable before approval**, and the edited text
  is what runs. A differential: approve the same finding twice with two different
  remedy texts and confirm two different jobs were submitted — not by checking
  that the form posts.
- `T3-20` The remedy prompt is a row in `prompts.py`'s versioned table, with the
  same rules as every other prompt: editing creates a version, deleting does not
  renumber, and a version records which model produced it and when.
- `T3-21` Approving a finding produces a new candidate and leaves the original
  in place, with both visible side by side and both scored, so the question
  "did the repair help" is answerable rather than asserted.
- `T3-22` Dismissing a finding records who dismissed it and why, and a dismissed
  finding does not reappear on the next run unless the artefact changed.

### 6.1 Routing a repair

The actuators exist; what has never been measured is whether they help.

- `T3-23` Repair routing asks `models.where()` and `models.fits()` for the box
  that can run the repair model, and names the filename **that** box uses via
  `models.resolve()`. A repair pinned to a box under a name it does not have is
  refused before it is submitted, not after.
- `T3-24` **The refiner costs ~19.6 GiB resident and the arithmetic must use
  that, not the UNET's 13.31.** (The figure has been written 20.5 GB in several
  places by adding GiB to GB: 13.31 GiB + 6.3 GiB + 0.24 GiB ≈ 19.6 GiB ≈ 21.0
  GB. The units were mixed, the conclusion was not — it does not fit a 15.92 GiB
  card either way, and `models.resident_gib` now carries one number.) `wan22_i2v_low` is 13.31 GiB of UNET plus a 6.3 GB `umt5` text
  encoder that the catalogue did not know about until 2026-08-12. It does not fit
  on peaches (10.58 GiB) and the pair does not fit resident on cerberus either.
  So "clean up peaches output" means *peaches renders, cerberus refines*, and the
  artefact crosses boxes.
- `T3-25` Repair of a remote box's output is refused with a clear reason until
  the artefact can demonstrably be moved back. Stated as a precondition, because
  the plan's blocker was about moving an output and what shipped stages an input.
  **The precondition is a callable check, not a sentence**: something answers
  "can an output be moved from this host", the refusal quotes it, and when it
  starts answering yes the refusal stops. **The flip is the criterion's positive
  half and must be exercised**: with the check forced true, a remote repair is
  SUBMITTED. Leaving it permanently false keeps the refusal green forever, which
  is the same shape as `T3-6` and `T3-18`. A criterion that only ever refuses is
  green forever and never notices the day the blocker lifts.
- `T3-26` **Whether the refiner helps is tier 3's first measurement, not its
  assumption.** It is catalogued `proven: opportunistic` precisely because
  nothing has measured it. A refine pass that does not improve the tier-2 score
  on a labelled set is reported as not helping, and the finding says so.

### 6.2 What each check can and cannot fix

Asked for explicitly. Every check declares its remedy class, and the queue shows
it, because a finding whose remedy is "regenerate the whole clip" is a different
decision from one whose remedy is "re-run the upscale".

| finding | can fix | cannot fix |
|---|---|---|
| wrong duration / frame count | re-render with corrected request | — |
| black or frozen frames | re-render (different seed) | nothing repairs a dead sampler in place |
| resolution downscaled | re-render pinned to a box that honours it | — |
| soft or low-detail clip | upscale pass (`make_postproc`) | it will not add identity |
| identity drift **within** a chained clip | re-render the chain from the last good frame | a per-frame fix; the drift is generative |
| identity wrong from the first frame | edit the **text**, then re-render | swapping the reference image will not fix it — measured |
| audio loudness off target | re-run loudnorm — **at the master when the set has one, per item otherwise** | it must NOT re-run per-item loudnorm on an item carrying a `gain_db` automation curve — that is the flattening `T1-9a` exists to prevent, and this row said plain "re-run loudnorm" until a review caught it |
| set duration ≠ prediction | a bug in the model→graph path | never "fixed" by re-rendering |

- `T3-27` Every check names its remedy class, and a check with no remedy says so
  rather than offering a button that does nothing.
- `T3-28` **"Identity is wrong" never proposes swapping the reference image as
  its remedy.** Measured 2026-08-12 with a one-variable differential: the species
  named in the prompt or not, same reference, same seed, same box. Named — feline
  throughout. Not named — an ordinary human woman by the halfway point, keeping
  only the harness. Identity comes from the text. A remedy prompt that says
  otherwise is the studio teaching a false lesson to the person reading it.

## 7. Backend / front-end separation

**INHERITED from TRD-6 §0.1** (`T6-A1`…`T6-A4`). Not restated. QC's own loop is
run, list, edit remedy, approve, re-check — and `T3-30` stays because it is
stronger than `T6-A3`: a check must be callable with a path and an expectation
and NO database at all, so it can be run over a directory of old output.


Same rule as TRD-1, and QC is the easier case because a finding is data.

`qc.py` is pure measurement and touches no database; `qc_service.py` is the
service module. That split is stronger than `T6-A3` asks for and is kept.

- `T3-30` A check function is callable from a test with a path and an expectation
  and returns a finding, with no request, no database and no app import. A check
  that needs the web layer to run cannot be run over a directory of old output.
## 8. Where it runs

QC **measurement** runs wherever the studio runs, on the file `collect()` already
brought back. It is not blocked by anything, and it does not need a GPU for
tier 1.

- `T3-32` Tier 1 over a full song's artefacts completes without a GPU and
  without contacting any backend. The measurement stage must not queue behind
  renders on the one worker thread, or QC becomes a reason not to run QC.

## 9. What TRD-3 does not own

- **The queue and scheduler — `docs/TRD-6`**, which exists because this section
  and TRD-1 §11 both disowned it. TRD-3 enqueues repair jobs and depends on the
  wait-state model decided 2026-08-12; TRD-6 specifies it, along with the
  artefact lifecycle, path identity and the persisted workflow request that
  `T3-2` compares against.
- **Garbage collection.** Deferred by name in the reconciliation because it needs
  the manifest schema that this document's artefact model largely defines. TRD-3
  must therefore not make the `findings`/`artefacts` shape harder to extend into
  a manifest of what was pushed where.
- **The storyboard and the arc.** TRD-2. QC checks the output; TRD-2 decides
  what was asked for.
- **The set timeline and its render.** TRD-1. **Two** things are shared, not
  one: loudness (`effects.measure_loudness`, TRD-1 `T1-25`) and the set-duration
  tolerance (`mixer.SET_DURATION_TOLERANCE`, `T1-7` and `T3-11`). Each is one
  implementation with two callers.
  And the boundary is not "TRD-1 never measures output" — it measures its own
  render to prove a feature works, which is what `T1-9b` and `T1-12` are for.
  TRD-3 measures artefacts to find out when something has stopped working.

## 10. Explicitly not building

- **No auto-heal.** No regeneration without human sign-off.
- **No CV model trained from scratch.** Pretrained extractors only, and not until
  cheap gates exist and there are labelled failures.
- **No VLM PASS/FAIL as a gate.** A model asked "does this match?" answers yes.
  A VLM may write a *description* attached to a finding; it may not be the
  verdict.
- **No threshold before calibration.** §5, and it is the whole shape of tier 2.
- **No second loudness implementation.** TRD-1 §9 owns it.
- **No overwrite, ever.** Repairs are candidates.

## 11. How every criterion above is to be verified

1. **A measurement that cannot fail is not evidence.** Every check gets a
   deliberately broken artefact that it must reject and a correct one it must
   pass — both directions, or the check is untested in the direction that
   matters.
2. **Then mutate the check and watch it fail.** Twelve mutations were run against
   one session's own checks on 2026-08-12 and two did not fail; one of those two
   was hiding a real defect in the code it claimed to cover.
3. **When an image looks wrong, look at it.** Every finding in this document that
   a deterministic check would have missed was found by opening the picture, and
   a QC stage does not replace that — it decides which pictures to open.
4. Baseline before and after: `cd studio && python3 -m pytest -q .` (the count is
   deliberately NOT written down here -- it was copied into three documents and
   all three went stale; green before and after is the requirement), `python3 check_integration.py`, and `grep -c "^def test_"`.

5. **A REFUSAL or a PRESENCE is half a criterion.** Found by a second
   independent reviewer, and it is systematic rather than incidental: a
   criterion of the form "X is refused" or "the payload carries Y" stays green
   when the whole feature is DELETED, because a feature that does not exist
   refuses everything and a field nobody reads is still present. Every such
   criterion is paired with a positive case that exercises the feature, or it is
   marked **provisional** and says what it cannot yet distinguish.

   One-sided in this document today, listed so nobody has to re-derive it:
   `T3-4` (fields present but never checked for sense) and `T3-27`. `T3-1` now has the two-host count half. `T3-6` / `T3-14` / `T3-18` / `T3-20` / `T3-23` / `T3-24` / `T3-25` have their positive halves: dest ≠ source, WITH a stored calibration a threshold CAN be set, the stored prompts id is what RUNS, a correctly-named model on a box that holds it is SUBMITTED, the refiner is routed off a 15.92 GiB card onto a 24 GiB one, and a remote repair with `can_move_output` forced true is SUBMITTED. `T3-22` has both halves: dismissed stays dismissed on the same bytes, and the same check REAPPEARS when the artefact changes.

### The positive half of each one-sided criterion

`T3-6` and `T3-18` have the enqueue + dest≠source halves. `T3-23` has both
halves: a pin under a name the box does not have is refused before submit, and
a correctly-named model on a box that holds it is SUBMITTED (dest is the
actuator's file, not a copy of the input). `T3-24` has both halves: peaches
cannot take the pair, and a correctly-named refiner on a box that holds it
is SUBMITTED to the 24 GiB card, not the 15.92 GiB one. `T3-25` has both
halves: remote repair is refused by the name `can_move_output` until the
check is true, and forcing the check true SUBMITS.

| criterion | its positive half |
|---|---|
| `T3-1` group by host, NULL bucketed | assert a report over artefacts from TWO hosts shows two groups with the right counts. A crippled report that only ever emits "unattributed" passes otherwise |
| `T3-4` measured/expected/unit recorded | the named checks must carry all three AND the values must be the ones measured — assert `measured` equals an independently computed reading, not merely that it is non-null |
| `T3-14` no threshold without calibration | paired positive: WITH a calibration row a threshold CAN be set. Deleting threshold configuration entirely satisfies the refusal |
| `T3-20` remedy versioned in `prompts` | assert the version that RUNS is the one stored — the same id, read back after approval. Storage rules alone do not prove use |
| `T3-22` dismissed stays dismissed | paired positive: a dismissed finding REAPPEARS when the artefact changes. Deleting change detection satisfies the first half forever |
| `T3-23` repair routing asks `where()`/`fits()` | paired positive: a correctly-named model on a box that holds it is SUBMITTED. Refusal-only passes with repair deleted |
| `T3-24` the 20.5 GB arithmetic | assert it decides a real box selection: the refiner must be routed away from a 15.92 GiB card and to a 24 GiB one |
| `T3-25` remote output move | paired positive: with `can_move_output` forced true, a remote repair is SUBMITTED. Refusal-only stays green forever |
| `T3-27` every check names a remedy class | assert the class is ACTIONABLE where one exists — the approve path uses it — and that a check with no remedy says so rather than offering a button |


---

## Status against the tree, 2026-08-13

Written by session A, in the shape session B set in TRD-4/TRD-7: a **ledger**,
not folded into the criteria above — *a criterion edited to describe what was
built is no longer a criterion, it is a changelog with a prefix.*

**"built" means a check can go red, not that the code exists.** `T4-10` read as
done all day while `app.ALBUM_FIELDS["body"]` quietly beat it, so a ledger that
repeats that is worse than none. Production is `c01c977`+; `origin/main` is
current.

| criterion | state | commit | what was measured |
|---|---|---|---|
| **tier 1, §4 entire** | **built** | earlier | `studio/qc.py` — `check_video`, `check_audio`, `check_image`, `check_set`, `run`, `summarise`. Every threshold measured, every `_readings()` raises rather than returning 0.0 |
| `T3-2` no hardcoded expectation | **built** | earlier | expectations read from the submitted workflow via `build_song.expect_from_workflow` |
| `T3-7` the model's own latent step | **built** | `d4a39c2` | asserted both ways on one 77-frame file: passes at step 4, flags at step 8 naming 81 |
| `T3-4` measured/expected/unit | **built** | earlier | on every check that has them |
| `T3-5` re-running does not duplicate | **built** | earlier | `UNIQUE(path, check_name)`; the mutation audit found the upsert alone was not the guard |
| `T3-1` group by host | **built** | `test_t3_1_by_host.py` | report over artefacts from two hosts has two groups with the planted counts; NULL host is an explicit unattributed bucket. Host is still canonical (`e20346f`) |
| `T3-13` score the 18 stills | **built** | `test_t3_13_identity.py` | `qc.score_zimage_sweep` reports overlap, separation and every file over 12-bad/6-good; `qc_service.run_zimage_calibration` stores the row with `threshold` NULL. A stored threshold is refused. No gate, no UI |
| `T3-14` no threshold without calibration | **built** | `test_t3_14_threshold.py` | `set_threshold` is refused with no calibration row, naming T3-13; WITH a stored row the value is written on that row. A non-T3-13 dataset does not unlock it. Not a UI |
| `T3-15` pose change is not identity failure | **built** | `test_t3_15_identity.py` | `identity_embed` is a colour histogram; `identity_score` ranks the anchored sheet above the pose-plate look. Pixel distance still inverts that pair |
| `T3-16` overlap is inconclusive, no gate | **built** | `test_t3_16_overlap_inconclusive.py` | `identity_verdict` names overlap inconclusive; `build_identity_gate` returns built False / threshold NULL; a threshold on that report (or via `set_threshold`) is refused. Separated ranges are not called inconclusive. No UI |
| **tier 3, §6 entire** | **partial** | `test_qc_approve.py` | `approve()` enqueues one repair and a dest ≠ source (`T3-6`/`T3-18`). `T3-20`, `T3-22`, `T3-23`, `T3-24` and `T3-25` are their own rows. Remaining in §6: T3-19, T3-21, T3-26, T3-27 |
| `T3-23` repair routing | **built** | `160547d` | default `dispatch_repair` asks `where()`/`fits()`/`resolve()`, refuses a pin under a name the box does not have before submit (`test_t3_23_pinned_name_the_box_does_not_have_is_refused_before_submit`), and a correctly-named model on a box that holds it is SUBMITTED (`test_t3_23_correctly_named_model_on_a_box_that_holds_it_is_submitted`). dest is the actuator's file (`fix_ref` / `gen_postproc`), not a copy of src |
| `T3-24` refiner resident cost | **built** | `a4b7ef9` | real `fits()` (not a stub) routes `wan22_i2v_low` off a 15.92 GiB card onto a 24 GiB one that holds the correct name (`test_t3_24_refiner_routed_off_15_92_to_24_and_submitted`); peaches cannot take the i2v pair (`test_t3_24_peaches_cannot_take_the_pair`) |
| `T3-25` remote output move | **built** | pending | `can_move_output` is callable; remote repair is refused by that name (`test_t3_25_remote_repair_refused_by_name_until_check_is_true`); forcing the check true SUBMITS (`test_t3_25_forced_true_remote_repair_is_submitted`) |
| `T3-31` vision score on generated stills | **built** | this slice | `score_generated_still` runs on anchors, refs, rerolls, `fix_ref` and artwork. `qc_json` is stored. A refine sibling is a new file (`test_h_anchor_refine_writes_sibling_not_overwrite`). Still advisory — not a gate |
| `T3-22` dismissed stays dismissed | **built** | this slice | same bytes stay dismissed (`test_t3_22_dismissed_stays_dismissed_until_artefact_changes`); rewriting the file reopens the same `(path, check)` row. `findings.artefact_hash` is the change detector |
| `T3-20` remedy versioned in `prompts` | **built** | `test_t3_20_remedy_runs.py` | the version that RUNS is the stored `prompt_versions` row — same id, read back after approval (`test_t3_20_approve_reads_back_the_same_stored_id`). Mutating the job's copied text still sends the stored wording (`test_t3_20_running_remedy_is_the_stored_row_not_the_job_copy`). A deleted row is refused, not replaced by the copy |
| `T3-28` identity-wrong never swaps the reference | **built** | `test_t3_28_identity_wrong_remedy.py` | `qc.check_identity_wrong` (also via `qc.run`) proposes "edit the text, then re-render"; `qc.proposes_reference_swap` is the detector. `record` / `set_remedy` / `approve` refuse a swap-the-reference wording and name that identity comes from the text. A legal text-edit remedy is stored. |
