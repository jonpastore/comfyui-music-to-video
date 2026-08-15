# PRD · The studio's editing and quality surface (TRD 1-3)

Status: written 2026-08-13. Covers `docs/TRD-1-TIMELINE-AND-MIXING.md`,
`docs/TRD-2-STORY-ARC-AND-STORYBOARDS.md`, `docs/TRD-3-QC-AND-REMEDIATION.md`.
Design that satisfies it: `docs/DDD-1-3-EDITING-AND-QUALITY.md`.

**What this document adds, and what it deliberately does not.** The three TRDs
already hold ~133 acceptance criteria, and they are the contract — this does not
restate one of them. What no TRD has is the layer above: who is served, what
counts as the product working, **and what order the work happens in**. Each TRD
names what it does not own; none says what ships first. Sequencing is §6 and it
is the reason this document exists.

Rules inherited from `TRD-6 §0` (`T6-A1`…`T6-A6`) apply throughout and are cited,
never repeated. Prohibitions live in TRD-1 §12, TRD-2 §9 and TRD-3 §10.
`T6-A1`'s three named loops complete over JSON (`test_t6_a1_*`).
`T6-A2` compares the HTML queue panel and JSON `/queue` in one test
(`test_t6_a2_html_and_json_report_the_same_queue_numbers`); set, storyboard
and review still write their own T6-A2 as those loops move.
`T6-A4` is proven for the queue panel (`test_t6_a4_*`); `T6-A5` is proven
for set re-render, refine, repair and anchor re-roll (`test_t6_a5_*`,
`qc_service.listed` / `select`). `T6-A3` remains the rest of P3.

---

## 1. Who this is for

**One operator, on a tailnet.** The studio has no authentication and the trust
boundary is the bind address and nothing else (`TRD-6 §0.1`). Every requirement
below is written for a single person producing a catalogue, not for a team and
not for a tenant.

The work is albums of music videos: a song becomes a storyboard, the storyboard
becomes reference frames and clips, the clips assemble into a song video, and
songs assemble into sets. Identity — one character, recognisably the same across
an album — is the thing the whole pipeline is trying to hold onto, and it is what
this project has most often lost.

## 2. The product, in one sentence

TRD 1-3 are the three surfaces where a **human decides**: the set timeline
decides what an audience hears, the arc and storyboards decide what the album is
about, and QC decides whether what came back is what was asked for.

Everything else in the studio is machinery that runs unattended. These three are
not, and they fail differently: machinery fails loudly, a decision surface fails
by *looking right*.

## 3. The product rule that outranks every other requirement

**The editor must not promise what the renderer does not produce.**

Day 4's Traps section, found and fixed six times, and all three of these surfaces
are editors sitting over a renderer. The three named product problems are each
one instance of it:

| surface | the problem today | source |
|---|---|---|
| set timeline | forms remain; a server-rendered `.tl-axis` tracks `set_duration()`; waveform is still a PNG (`mixer.waveform_png`); automation lanes and draggable joins are not in the UI | TRD-1 §1 |
| arc & storyboards | songs are storyboarded independently, so an album is twelve unrelated stories that share a character; `scene_seconds` could not lengthen a scene and nothing in the UI revealed it | TRD-2 §1 |
| QC | nothing checks output. The identity collapse, the world that never rendered and the LoRA that did nothing all passed every deterministic check and were found by opening the picture | TRD-3 §1 |

A second rule follows from the third row and applies to the whole of TRD-3:
**a number that has not been shown to separate known-good from known-bad gates
nothing.** A confident green tick on a render nobody looked at is worse than no
check at all — that is TRD-3 §1's measured 41.1-vs-64.7 inversion, where a
plausible metric ranked the wrong image first.

## 4. The three journeys

Stated as journeys because `T6-A1` requires each one to be drivable over JSON
with no HTML involved, and it names these three as the loops to prove it with.

**A · Build a set and render it.** Add songs, insert a title card as its own
item (`T1-27`/`T1-28`: `[song A][ MEOW P — 3s ][song B]`), drag the joins,
draw a level curve, hear a proxy, render a real 20-second preview of one join,
render the whole thing — and the length shown while editing is the length of
the file. A card is a beat in the running order, not a decoration on one.

**B · Give the album a story and storyboard against it.** Write or generate an
arc, accept it, generate each song's storyboard as a scene *of that arc*, edit a
scene, read a time meter that agrees with the song, and see which leads still
have no anchor.

**C · Find out what came back wrong.** After renders land, a queue of findings,
each carrying what was measured against what was asked for, an editable remedy
prompt, and an approve button. Nothing repairs itself.

## 5. What "working" means

Product outcomes, each with the TRD criterion that already proves it. These are
the eight things that must become true; they are not a new contract.

| # | outcome | proven by |
|---|---|---|
| P1 | The number on the screen is the number in the file — set length, to 0.05 s, with echo, hold, beatmatch, trim and an interstitial card all in play | `T1-7`, `T1-8`, `T1-27`, `T3-11` |
| P2 | A drawn curve reaches the audio, and is not normalised away two stages later | `T1-9a`, `T1-9b` **built** (`mix_audio` RMS/s slope on a constant sine), `T1-12`, `T1-20d` |
| P3 | Every surface is drivable with no browser, and the page and the JSON agree. A re-render, refine, repair or anchor re-roll leaves predecessor and successor both listed and selectable | `T6-A1`…`T6-A5`, `T1-3`, `T2-41` |
| P4 | An album's songs are scenes of one story, demonstrably — arc content appears in the storyboard and is absent when the arc is; at xxx no scene prompt carries the mainstream lock and the tier's own wording does; the board's guardrail field is this tier's clause and save refuses another tier's wording | `T2-20`, `T2-21`, `T2-22` |
| P5 | Requested clip length is honoured end to end: `scene_seconds` in, a legal frame count out, the approve grid showing every clip, a re-plan leaving approved `(clip_idx, seed)` unchanged, the planner prompt not naming a fixed 4.8125 s quantum, its clip-length text derived from planning, TIMING still stating track length and sum-to-track, and generated scenes tiling `[0, duration]` with no gap or overlap | `T2-8`, `T2-8b`, `T2-12a`, `T2-13a`, `T2-13b`, `T2-13c`, `T2-14a`, `T2-14b`, `T2-14c` |
| P5a | Assembling a song with a 1664×960 clip among 832×480 siblings keeps the ×2 size and does not letterbox; mixed aspect is refused | `T5-7` |
| P5b | Every clip of one song is normalised to one output fps, asserted on the assembled file | `T2-13d` |
| P6 | Every rendered artefact is measured against the workflow that asked for it, never against a constant. A mixed-model clip is judged at its native fps, not the song's output fps | `T3-2`, `T3-4`, `T3-7`, `T2-13f` |
| P7 | A finding arrives actionable — measured, expected, unit, a remedy class, and an editable prompt — and nothing runs without approval. A dismissed finding stays off the queue until the artefact itself changes. The remedy that RUNS is the stored prompts row. Approving produces a new candidate; original and repair are both listed and scored | `T3-18`, `T3-19`, `T3-20`, `T3-21`, `T3-22`, `T3-27` |
| P8 | Identity failures are attributed to the text, never to the reference image | `T2-31`, `T2-32`, `T3-17`, `T3-28` |

**P8 is the one to defend hardest.** It is measured, not theoretical: same
reference, same seed, same box, species named in the prompt or not — named gives
a feline throughout, unnamed gives an ordinary human woman by the halfway point
keeping only the harness. A remedy that proposes swapping the reference image
teaches the operator a false lesson, which is why `T3-28` forbids it by name.
`qc.check_identity_wrong` (via `qc.run`) proposes "edit the text, then
re-render"; `record` / `set_remedy` / `approve` refuse a swap-the-reference
wording. `T3-17` scores that artefact against the chosen anchor
regardless of cause — it does not require an empty `character_reference`.
The picture still has to be looked at — this is the score and the remedy,
not a gate. The storyboard-side pair is `T2-31` / `T2-32`: saving an empty
`character_reference` is refused, and the message says identity comes
from the text, not the reference image.

## 6. Sequencing — the part the TRDs do not have

Each TRD disowns what it does not cover; none of them orders the work. This is
that order. Every edge below is a real dependency taken from the documents, not
a preference.

### 6.0 What Jon decided, 2026-08-13

Asked which capability he wanted next, in his own terms rather than by criterion
id, and the answer re-orders everything below:

1. **Anchors that stay on-model** — identity and variations. Session B's work,
   already in flight.
2. **Know when a render is wrong** — QC's repair path. The measuring half is
   built; `approve()` enqueues a dest ≠ source. GPU actuators
   (`make_postproc` / `fix_ref`) are not wired — `h_repair` refuses a silent
   copy rather than marking the finding repaired.
3. **Clips at the length you asked for** — `scene_seconds` finally meaning
   something.

**The set timeline goes last.** It is the biggest gap between what exists and
what a person would expect, and it is not what is wanted next. §6's P1 below was
written with the timeline first and is superseded by this list.

**The queue is rewritten in full**, not reduced to its one blocking column. Asked
whether to take just `T6-13a` and leave working machinery alone, Jon chose the
full pull-based queue. So TRD-6 §1-§6 is in scope, `T6-13a` still goes first
inside it because the clip-length chain waits on it, and the plan's Phase F is no
longer the phase to defer — `docs/PLAN-TRD-4-7.md` §4 is updated to match.

### Already built and deployed (do not rebuild)

`studio/qc.py` (TRD-3 tier 1 in full), `studio/qc_service.py` + `db.findings` +
`/api/qc/*` including `GET /api/qc/by-host` (`T3-1`) and dismiss/reopen on
artefact change (`T3-22`), `qc_service.run_song` (`T3-32`: tier 1 over a song
completes without a GPU, a backend, or the one worker thread), `studio/automation.py` + `db.automation` (TRD-1 §5's curve model,
decimation and filter emission; `T1-1` **built** — reorder or trim
leaves stored `(lane, t, value)` unchanged, asserted on non-empty
rows; `T1-9b` **built** — a stored −12→0 dB
ramp's RMS/s slope survives `mix_audio` within
`mixer.GAIN_CURVE_SLOPE_TOLERANCE`), `studio/arc.py` + the arc routes (TRD-2 §3.1's
JSON-canonical arc), `db.artefacts` (tier 0), `prompts.py` (TRD-2 §3.3's
versioning, reused by `T3-20`). TRD-3 §2.1 is explicit that §4 and §6 "read as
unbuilt work and are not" — the ledger with line counts is DDD §1.

### P0 — unblock, then separate

1. **`T2-12a` — round a scene length to a legal frame count.** Landed for the
   divisor: `clip_seconds(scene_seconds)` is `legal_frames / LTX_FPS`, and
   `n_clips_for` is `ceil(duration / that)`, so song length owns clip count.
   `None` stays `CHUNK` — a storyboard written before the column does not
   re-time. The renderer honours that length (`T2-13a`): latent frames and
   audio trim follow the legal count, not `LTX25_LEN`/`CHUNK`. `T2-13c`
   is **built**: the approve grid enumerates `clip_count` (duration /
   legal `scene_seconds`), so a 20-scene storyboard on a 41-clip song
   still lists every clip.
2. **The service split**, TRD-1 and TRD-2 (`T6-A3`). `qc_service.py` already
   demonstrates it and is the pattern to copy. Doing this after the features
   means writing them twice.

### P1 — SUPERSEDED BY §6.0, kept for its dependency edges

**Read §6.0 first: Jon put the timeline LAST.** This block was written with the
timeline first and its ORDER no longer holds; its *edges* still do, which is why
it is not deleted — the master stage really is a prerequisite for automation
being usable, and audiences really do need the master. Follow §6.0's capability
order and take the dependencies from here.

3. Clock and rounding (`T1-5`, `T1-6`); peaks and the waveform data model
   (`T1-13`/`T1-14` **built** as `mixer.peaks`; `T1-15` empty-reason **built**
   as `{pairs, reason}` on `peaks_from_path` / `GET /api/songs/{id}/peaks`);
   the proxy-preview contract (`T1-16` **built** as `mixer.preview_proxy` /
   `GET /api/sets/{id}/preview` `{is_proxy, not_applied}`; `T1-17` **built**
   as `mixer.render_preview` / `GET /api/sets/{id}/preview/render?at=&secs=`
   `{is_proxy: false}` — the only preview that claims accuracy.
   `waveform_png` stays the picture).
4. The master stage (`T1-20a`…`T1-20d`). It is a prerequisite for automation
   being *usable*, not an enhancement: without it, per-item `loudnorm` flattens
   every curve `automation.py` can already store and render.
5. Audiences (`T1-18`…`T1-20`). **Built**: `sets.mode_audience`
   persists; switching easy→advanced→easy does not rewrite `set_items` or
   automation; easy and advanced return different affordance sets; easy
   engages the existing master (`mixer.master_engaged`) so a set with
   per-item defaults cleared lands within 1.0 LU of `effects.LOUDNORM_I`
   and the same set with easy off does not. **`T1-19` built** — easy's
   one-button master is the named chain `one-button-master` v1, recorded
   on the render (`assets.meta_json.master_chain`); changing I moves
   measured loudness. **`T1-25` built** — an export names measured
   integrated loudness and true peak on `assets.meta_json.loudness`;
   a render outside `effects.LOUDNESS_TOLERANCE_LU` /
   `TRUE_PEAK_TOLERANCE_DB` of its own target is flagged.

### P2 — the arc through to the storyboard

6. `T2-8b`/`T2-8c` tiling and section coverage, then the wand flows (§4.1–4.3),
   the time meter (§5.1), casting (§5.3). **`T2-8b` built**: `_compose`
   stamps scene `start`/`end` so they tile `[0, duration]`; `validate`
   refuses a gap or overlap (`test_t2_8b.py`). **`T2-20` built**: a distinctive
   arc string appears in the generated board and is absent when the arc is.
   **`T2-21` built**: at `xxx`, no scene `image_prompt` or
   `video_motion_prompt` carries the mainstream lock, and the tier's
   own permission wording is in the scene text (`rear-entrance_xxx.json`).
   **`T2-22` built**: the generated board's `guardrail` field is
   `compose_guardrail(tier)` verbatim, and save refuses another tier's
   wording. **`T2-23` built**: `GET .../meter` reports total scene time
   against song length and flags a miss beyond `SCENE_TIME_TOLERANCE`.
   **`T2-24` built**: the same meter reports this song's `clip_seconds`
   from `build_song.clip_seconds(scene_seconds)`; 15 s and 30 s on one
   song yield two lengths. Remaining: `T2-8c`, §4 wands (`T2-14`…`T2-19`),
   `T2-25`, and casting.
7. Per-scene model choice, W2 (`T2-42`…`T2-48`) — last, because `T2-45` needs
   `models.where()`'s three-valued answer respected at enqueue and `T2-48` needs
   per-model ceilings, which is P0 item 1 again. The renderer half of those
   ceilings is `T5-9`: labeled measured vs chosen, and an over-long single
   clip is refused or split. The planner divisor is unchanged.
   **`T2-47` built**: one clips job with a scene marked `s2v` and one left
   `ltx25` writes each model's own frames/fps
   (`test_t2_47_mixed_model.py`). **`T2-48` built**: a 30 s `s2v` scene
   splits on the s2v ceiling and a 30 s `ltx25` scene into 15 s clips,
   each tiling its scene (`test_t2_48_ceilings_compose.py`).
   `T2-42`…`T2-46` remain.
   **`T2-13f` built**: QC judges each of those clips at its native fps, not the song's (`test_t2_13f_native_fps.py`); comparing against the song rate flags the other model.

### P3 — QC tier 2 and repair

8. Tier 2, **calibration first and in this order**: `T3-13` scores the 18
   images of `zimage_sweep/` and stores overlap, separation and every file
   on a `calibrations` row with no threshold. `T3-14` can set a threshold
   on that row and refuses without one, naming why. `T3-15` ranks the
   recorded pose pair (histogram, not pixel distance). `T3-16` names
   overlap inconclusive and does not build a gate; that is a successful
   outcome. `T3-17` is **built**: identity drift is scored per artefact
   against the chosen anchor, whatever caused it — a non-empty reference
   plus text that does not name the species still scores. Tier 1 cannot
   see the score. There is still no tier-2 UI.
9. Repair routing (`T3-23`) is built: `dispatch_repair` asks `where()` /
   `fits()` / `resolve()`, refuses a mis-named pin before submit, and
   dest is the `fix_ref` / `gen_postproc` file. `T3-24` is built: the
   refiner's resident cost (~19.6 GiB), not the UNET's 13.31, routes it
   off a 15.92 GiB card onto a 24 GiB one; peaches cannot take the pair.
   `T3-25` is built: `can_move_output` refuses remote repair by name
   until the check is true; forcing it true SUBMITS. `T3-26` is built:
   whether the refiner helps is a fail-closed labelled-set measurement
   (`qc.measure_refiner_help`), not the catalogue's `opportunistic` tag;
   a pass that does not improve the tier-2 score is a finding that says
   not helping. `T3-20` is built:
   the approved remedy that RUNS is the stored `prompts` row, same id,
   read back after approval — a copied string on the job is not what
   the actuator receives. `T3-27` is built: every check names a remedy
   class, `approve()` uses that class (not the edited wording), and a
   check with no remedy refuses rather than offering a button.
10. Every generated still is vision-scored into `qc_json` (`T3-31`),
    including a `fix_anchor` sibling and the artwork generate (not only
    the refined cover). A refine pass writes a new candidate beside the
    generate; it is not a silent overwrite and not a VLM gate.
    `fix_anchor` itself is the operator-approved repair (`T3-18`); it
    does not auto-heal.

### Deferred to another document, on purpose

The queue and the wait-state scheduler (**TRD-6**, and it exists because TRD-1
§11 and TRD-3 §9 both disowned it); garbage collection; the song-level audio
editor; `duck` and `layer` until `T1-21`/`T1-22` can be measured.

## 7. Risks

Each is a thing this project has already done once, not a hypothetical.

1. **A check that cannot fail.** ~20 criteria across the three documents were
   one-sided — "X is refused", "the payload carries Y" — and stay green when the
   whole feature is deleted. Each TRD now carries a table pairing them with a
   positive half; those tables are requirements, not commentary.
2. **A second implementation of a number.** Twelve criteria for four facts;
   `CHUNK` once had five clip-count readers (`T2-13` collapsed them to `n_clips_for`); scene timing computed twice; gain in two places
   before automation would have made three. Every new value gets one owner and
   the others cite it.
3. **A metric that is confidently backwards.** §3, and it is why tier 2 is
   calibration-gated rather than threshold-first.
4. **Preview trusted over the render.** `T1-16` makes the proxy warning part of
   the API response rather than a sentence in one template, because a mobile
   client will not carry a sentence.
5. **Documents drifting from the code.** Every line-number citation in TRD-2 §3.4
   went stale within a day. Cite behaviour and function names; cite line numbers
   only alongside the behaviour that identifies them.

## 8. Open, and needing Jon

- **Scope.** **192** criteria across seven TRDs, of which these three hold
  **120** — 32 / 58 / 30. (Counted 2026-08-13 with `grep -cE "^- .T<n>-"`. The
  figures quoted everywhere until then — ~197 total, 36 / 61 / 36 — were wrong
  for five of the seven documents, and had been carried between documents rather
  than measured. The correction changes no decision; it is recorded because a
  number copied instead of counted is the defect these documents are about.)
  This is the whole remaining project. If a smaller shippable scope is wanted,
  §6's P0 and P1 are the smallest cut that produces something usable — the
  timeline is the one surface that still lacks joins, lanes and a playhead
  (the ruler now tracks `set_duration()`; the rest is still forms and a number).
- **`duck` and `layer`.** Refused everywhere today and honestly so (`T1-23`).
  They stay refused until measured, and that is a decision to schedule, not a
  bug to fix.
- **Live-model tests.** TRD-2 §10.3 requires fixtures in the default suite and
  one deliberately live test kept out of it. Nobody has decided how the live one
  is run or how often the fixtures are re-recorded, and a fixture that no longer
  resembles what the model returns is a check measuring its own history.
