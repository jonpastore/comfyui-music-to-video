# DDD · Design for TRD 1-3

Status: written 2026-08-13. Product framing and sequencing:
`docs/PRD-1-3-EDITING-AND-QUALITY.md`. Contract: `docs/TRD-1-TIMELINE-AND-MIXING.md`,
`docs/TRD-2-STORY-ARC-AND-STORYBOARDS.md`, `docs/TRD-3-QC-AND-REMEDIATION.md`.
Rules inherited from `TRD-6 §0` are cited, never restated.

**Every "built" and "not built" below was read off the tree at `f9ca597`, not
off a document.** TRD-3 §2.1 records what happens otherwise: a "do not rebuild"
table that omitted the QC implementation, which is the omission most likely to
cost a rewrite. Where a claim here is a measurement, the command that produced it
is named.

---

## 1. What exists today

| module | lines | owns | state against its TRD |
|---|---|---|---|
| `studio/app.py` | 6331 | 113 routes, and most of the logic behind them | the structural problem, §2 |
| `studio/mixer.py` | 2116 | set duration, both filter graphs, overlap arithmetic, beatmatch, ramps, splice | TRD-1's engine. Built; one measured gap, §5.2 |
| `studio/effects.py` | 592 | effect validation, `filter_sweep`, `duration_delta`, `loudnorm_filter`, `measure_loudness`, `LOUDNORM_I` | built; owns loudness for `T1-25` **and** `T3-9`/§4.3 |
| `studio/automation.py` | 457 | TRD-1 §5 in full: lanes, RDP decimation, `MAX_POINTS = 64`, `fragment`, `item_audio`, `wants_master_loudnorm` | built |
| `studio/qc.py` | 642 | TRD-3 tier 1 in full: `check_video`, `check_audio`, `check_image`, `check_set`, `run`, `summarise` | built |
| `studio/qc_service.py` | 308 | findings, queue, remedy edit, dismiss, reopen; `approve()` enqueues dest ≠ source; `dispatch_repair` asks `where()`/`fits()`/`resolve()` then submits `fix_ref` / `gen_postproc` | built except `T3-24` / `T3-25` |
| `studio/arc.py` | 327 | TRD-2 §3.1/§3.2: JSON-canonical arc, `to_md`, `validate`, `for_song`, screened both directions | built |
| `studio/prompts.py` | 265 | TRD-2 §3.3 versioning, reused by `T3-20` | built |
| `studio/grok.py` | 1249 | storyboard generation, `validate`, the retry loop | built; §5.5 |
| `build_song.py` | 789 | `clip_plan`, `clip_seconds`, `n_clips_for`, `expect_from_workflow` | the one timing owner; `clip_seconds` honours `legal_frames`, §5.5 |
| `studio/db.py` | 559 | schema | `automation`, `findings`, `artefacts` landed; two `sets` columns did not, §4 |
| `studio/vision.py` | 516 | VLM calls, local-first | **not** tier 2, §5.6 |

Deliberately absent, verified by `grep -rn` over `studio/*.py` and the root
scripts: no master-chain configuration, no peaks store, no calibration table, no
embedding metric (`siglip2_naflex` appears only as a `models.py` catalogue
entry), no `insightface`.

## 2. The structural problem, and the pattern that already solves it

`app.py` is 6331 lines and 113 routes, of which **five return JSON** —
`/api/qc/findings*`. Everything else is a route handler that reads rows, decides,
formats and returns HTML. `render_set_route` is TRD-1 §10's named example: it
reads the items, joins the songs, chooses the audio-or-video path, builds every
item dict and enqueues, all inside the handler and all unreachable from a client
that is not this page.

`T6-A1`…`T6-A4` are the requirement. **`qc_service.py` is the pattern and it
already works**: `qc.py` is pure measurement that touches no database, so it runs
over a directory of old output (`T3-30`); `qc_service.py` persists and imports
nothing from FastAPI; the five routes are thin. Copy that shape, do not invent a
second one.

Two new modules, same shape:

    sets_service.py        TRD-1   sets, items, automation, peaks, preview, render, export
    storyboard_service.py  TRD-2   arc flows, storyboard generation, scene edit, time meter, casting

`arc.py` and `automation.py` are already FastAPI-free and become their
dependencies rather than being folded in. The boundary rule that decides what
moves: **a route handler contains no arithmetic, no defaulting and no decision**
(`T6-A3`). `app.storyboard_scenes` computing `idx * CHUNK` inline is the defect
this prevents, and `T2-41` records that it was real and is now fixed.

Migration is per-loop, not per-file. Move one journey (PRD §4) at a time, and
`T6-A2` is the check that the move was faithful: the HTML page and the JSON
endpoint report the same numbers, asserted by comparing them in one test.

## 3. API surface

Named per journey, because `T6-A1` requires a curl script to drive each one end
to end. Shapes only — the fields are the TRDs'.

**A · set timeline** — `GET/POST /api/sets`, `/api/sets/{id}` (model in full:
items, automation, predicted duration, rounding deltas), `/api/sets/{id}/items`,
`.../items/{iid}/automation/{lane}` (POST raw points, response is the **stored,
decimated** curve — the client re-reads what was kept, §5.3),
`/api/sets/{id}/peaks?z=`, `/api/sets/{id}/preview` (returns `is_proxy` and
`not_applied`), `/api/sets/{id}/preview/render?at=&secs=`,
`/api/sets/{id}/render`, `/api/sets/{id}/renders` (every candidate, `T1-26`,
`T6-A5`).

**B · arc and storyboard** — `GET/POST /api/playlists/{id}/arc`,
`.../arc/propose` (proposal is not saved until accepted, `T2-15`),
`GET/POST /api/songs/{id}/storyboard/{tier}`, `.../scene/{n}`,
`.../meter`, `.../cast`. The generation prompt and **the limits that apply to it**
travel in the same response (`T2-18`).

**C · QC** — exists. `/api/qc/findings`, `/{fid}`, `/{fid}/remedy`,
`/{fid}/dismiss`, `/{fid}/approve`.

Every list response carries help text per control, with warnings marked
distinctly from notes (`T2-36`) — a client that cannot tell them apart hides the
wrong one, and day 8's rule is that the warnings do not move.

## 4. Schema deltas still required

Landed already: `automation`, `findings`, `artefacts`, and `storyboards.scene_seconds`.

Still needed, and no more than this:

    ALTER TABLE sets ADD COLUMN out_fps REAL;                        -- NULL = derive from items
    ALTER TABLE sets ADD COLUMN mode_audience TEXT DEFAULT 'normal'; -- easy|normal|advanced

    -- Tier 2 cannot store a threshold without the calibration that earned it (T3-14).
    CREATE TABLE IF NOT EXISTS calibrations (
      id INTEGER PRIMARY KEY,
      metric TEXT NOT NULL,          -- which extractor and version
      dataset TEXT NOT NULL,         -- e.g. zimage_sweep
      n_good INTEGER, n_bad INTEGER,
      separation REAL, overlap REAL, -- the report T3-13 requires
      scores_json TEXT NOT NULL,     -- every individual file's score; the report is data
      threshold REAL,                -- NULL when the distributions overlap (T3-16)
      created REAL
    );

Peaks are **not** a table. They are a binary min/max array written beside the
song by the existing `analyse` job and served decimated (§5.4).

`pan` stays an `effects_json` key and does **not** become a column — TRD-1 §3.1
decided that and the reason is §5.0(b)'s: a column would be a second place for
the value before anything needs one. Gain already had two places and cost a
silent -6 dB (mixer.py `_audio_chain`'s own docstring).

## 5. Subsystem designs

### 5.1 The clock, and one place that rounds

`T1-5`/`T1-6` need nearest-frame rounding on video, exact seconds on audio, and
the delta **reported**. One function in `mixer.py` beside `set_duration`:

    frame_round(t, fps) -> (t_rounded, delta)

Every join asks it; nothing else rounds. `GET /api/sets/{id}` carries the
per-join delta and the summed |delta|, so `T1-6`'s bound is checkable from the
model without rendering. Truncation is the mutation that must break it: the
losses all share a sign and accumulate at 0.0594 s per join at 16.8312 fps, which
is the RIFE one-frame bug's shape — it plays, it looks fine, it is the wrong
length.

### 5.2 The master stage — built, with one measured gap

`mixer._master_lines` (mixer.py:652) exists and implements TRD-1 §8a: one
`loudnorm` after every item and every join, engaged only when some item
suppressed its own, so a set that draws no curve renders exactly as it did before
automation existed (`T1-20b`). `_audio_chain` takes the item's own `loudnorm` off
when `automation.item_audio()` says `suppress_loudnorm` (mixer.py:725).

**`T1-20d` is not satisfied for a MIXED set, and it is measured, not suspected.**
`_master_lines` engages when *any* item suppresses, while `_audio_chain`
suppresses only for the items that carry a curve — so an uncurved item in a set
that has one keeps its own `loudnorm` **and** passes through the master. Counting
`loudnorm` per signal path, calling the real `_audio_chain` and `_master_lines`:

    both curved          per-item=[0, 0]  master=1   worst path = 1
    neither curved       per-item=[1, 1]  master=0   worst path = 1
    one curved, one not  per-item=[0, 1]  master=1   worst path = 2   <-- two in series

Two normalisers in series is the second working against the first, which is
exactly the sentence `T1-20d` was added to enforce. Mutated in memory so that
engaging the master strips per-item `loudnorm` from every item, the mixed case
drops to 1 and the other two rows do not move — so the measurement responds to
that rule and to nothing else. **Reproduced independently by session B at HEAD,
same three rows.**

**FIXED 2026-08-13 by session B, on Jon's decision, and the estimate this
document gave was wrong twice on the way — which is the part worth keeping.**

*First estimate: "one line at `mixer.py:664`."* Wrong. `_audio_chain(gain_db,
effects_json, auto=None)` receives **one item's** automation and cannot see the
others, so it cannot know the master will engage. Widening the `any(...)` at 664
would have added a master `loudnorm` on top of the per-item ones still there,
taking `neither curved` from 1 in series to **2** — worse than the bug, on the
path that was correct.

*Second estimate: "three points — the engagement test, the two call sites, and
the signature."* Right about the count, **wrong about the shape**, and a mutation
is what proved it. B wired the flag through both call sites as agreed, then
mutated the **video** call site to `master=False`: **every assertion stayed
green.** The checks exercised `_audio_chain` directly, so they never touched the
wiring. **Two correct call sites is not a property a per-function check can
see.**

*What actually shipped: one point.* `master_engaged(items)` is the single
set-level reading, and `item_chains(items)` builds every item's chain with that
decision applied. Both render paths call `item_chains`, and `grep` shows
**exactly one production `_audio_chain` call**, inside it. The criterion asserts
through `item_chains`, so the wiring is on the measured path — re-running the
same mutation now fails, naming the defect: *"one curved, one not: 2 loudnorms
in series on one signal path. A set is levelled ONCE."*

Measured independently through the real functions after the change:

    both curved          per-item=[0, 0]  master=1   worst signal path = 1
    neither curved       per-item=[1, 1]  master=0   worst signal path = 1
    one curved, one not  per-item=[0, 0]  master=1   worst signal path = 1   <-- was 2

**The generalisation, which outlives this bug — and it is two rules, not one.**

The defect lived in the *disagreement between two functions that each looked
correct alone*, and the first fix reproduced that exact shape: one decision with
two places to apply it. So the **design** rule is that any design computing a
decision in one place and applying it in two should be read against this. That
shape is already this codebase's most common defect — `NUDE_VIEWS` as two
hand-kept copies, `CHUNK` with five readers, `DEFAULT_BODY` losing to
`ALBUM_FIELDS["body"]`, gain arriving from a column and a JSON key.

But a design smell is not what catches it, and session B's sharper version is
the one to build on: **the rule that actually catches it is a
test-construction rule — assert through the shared entry point, never through
the function it wraps.** B's checks were correct and thorough and pointed one
level too low, which is exactly why they stayed green through a deliberately
broken call site. **A design with one decision and two applications is a smell;
a check that bypasses the collapse point is what makes the smell
undetectable.** The second rule would have caught this on the first attempt and
the first would not.

**Two honest limits, recorded rather than implied away.** A caller
re-introducing a direct `_audio_chain` call and bypassing `item_chains` is
prevented **structurally, not by a test** — it is a visible code change rather
than a silent flag flip, but it is not guarded. And the selfcheck comment
claiming *"exactly ONE loudnorm in the graph"* **was already false when it was
written**: it counted the master line only, while a plain item still carried its
own. A true measurement of the wrong thing, sitting in the file the whole time.

### 5.3 Automation — built; what remains is reach

`automation.py` owns the model, decimates on write with RDP plus a hard
`MAX_POINTS = 64`, and emits through `asendcmd`, which is the mechanism
`effects.filter_sweep` already uses — one emitter, one cap, and `sweep` becomes a
preset that writes points rather than a second automation system.

What is left is the criteria that prove the lanes **reach the render**: `T1-12`
per lane, as a differential (`gain_db` by RMS/s, `pan` by L/R energy ratio, the
filter lanes by band energy). This is the criterion that catches a lane wired
into the UI and not into the graph, which is how `_apply_beatmatch` was
unreachable for a whole session.

### 5.4 Peaks and preview

Peaks: computed on the **existing** `analyse` job, which already decodes the file
— do not decode it twice. Stored beside the song, served decimated at
`PEAKS_MAX_POINTS = 2048` per request. Decimation is a **min/max reduce, not a
resample** (`T1-14`): a waveform that under-reports a peak lies about where the
loud part is. The reduce is `mixer.peaks(samples, z)` (`T1-13`/`T1-14`);
analyse storage and `/api/sets/{id}/peaks?z=` are not wired yet.

The limit is stated in the design because it will otherwise be discovered by a
feature request: `analyse.py` loads mono at 22050 Hz, chosen because it matched
the measured tempo and halved load time. That is an envelope. A stereo waveform,
or anything claiming to show clipping, is a **second decode** and must be asked
for deliberately.

Preview: the browser plays source files with gain and position applied. **No
second DSP engine in Web Audio.** The proxy declaration is data —
`{"is_proxy": true, "not_applied": [...]}` — computed from the item's actual
effects, so `T1-16`'s test (add an effect, see it appear in `not_applied`) fails
a static list. "Render preview" goes through the *same* code path as a full
render, bounded to a span, and is the only preview that claims accuracy.

### 5.5 Clip length: one blocked chain, and the order it unblocks in

`build_song.clip_seconds(scene_seconds)` **returns the legal 8n+1 length** at
`LTX_FPS`. `None` is a storyboard written before the column existed and still
returns `CHUNK`, so nothing already on disk changes length. `n_clips_for` is
`ceil(duration / clip_seconds(...))` — duration is the dividend, the legal
length is the divisor, the count is ours.

1. `T2-12a`: seconds → nearest **legal** frame count at the clip's fps. F-2's
   rule is that `frames ≡ 1 (mod 8)` serves both models, since every `8n+1` is
   also `4(2n)+1`; the tie-break is half-to-even (77 is equidistant from 73 and
   81, and the code lands on 81). **Built.** `clip_seconds` honours it.
2. The renderer takes a length. **Not this slice** — graphs still emit
   `LTX25_LEN`.
3. Only then `T2-13a`, `T2-13c` (the approve grid must still show every clip),
   `T2-8`/`T2-9`.

`W1-4` sits alongside and is a **prompt**, not code: `grok._user_prompt` still
tells the model the renderer emits fixed 4.8125 s clips and to round every
`duration_guidance` to multiples of it. Leaving it changes nothing that runs and
everything that comes back — the same shape as the section floor, where the
formula was fixed and `validate()` quietly regenerated the old answer. The
function is pure; assert on its return value (`T2-14a`…`T2-14c`), never by
grepping the source.

### 5.6 Tier 2 is a calibration, not a metric

`vision.py` is a VLM caller and is **not** the tier-2 path. TRD-3 §10 forbids a
VLM verdict by name — asked "does this match?", a model answers yes — though it
may write a *description* attached to a finding.

Design, in the order `T3-13`…`T3-16` fix:

1. Extractor over `zimage_sweep/`'s **12 known-bad and 6 known-good** images
   (same prompt, same anchor, same day; on two seeds the model draws bare human
   legs with a cat's head at every step count, on the third it holds fur head to
   toe). `siglip2_naflex` is installed on peaches and is the right shape;
   `insightface` is the alternative.
2. Write a `calibrations` row: both distributions, the overlap, the separation,
   and **every individual file's score**. That report is the deliverable.
3. No threshold, no gate, no UI until the row exists. If the distributions
   overlap, the report says so and the gate is not built — `T3-16` calls that a
   success, and the failure mode it avoids is shipping a threshold that splits
   noise.
4. `T3-15` is the regression guard: the metric must not rank a deliberate pose
   change as an identity failure. It is asserted against the recorded pair that
   pixel distance got backwards — 41.1 for the wrong render, 64.7 for the right
   one.

Reported per artefact: a calibrated compliance percentage, a **variation** figure
across the sampled frames, and the sample count both came from. Variation is the
one that matters more now than it did: chained clips start from a generated
frame, not an approved reference, so drift *within* a long clip is the reachable
failure.

### 5.7 What has to exist before a repair is a repair

`qc_service.approve()` enqueues one `repair` job with dest ≠ source. It does
not write dest and it does not run a GPU. `dispatch_repair` now turns that job
into a real candidate (`T3-23`):

1. **Remedy → action mapping.** Image findings submit `pipeline.fix_ref`;
   clip / upscale findings submit `pipeline.gen_postproc`. A silent
   `shutil.copy2` of src is still refused.
2. **Routing that asks first.** `models.where()` and `models.fits()` choose the
   box, `models.resolve()` names the file *that box* uses, and a pin under a
   name the box does not have is refused before submit. `T6-A6`'s three values
   stay: `False` refuses, `None` is a candidate. The refiner is ~19.6 GiB
   resident (`T3-24`) and fits neither peaches (10.58 GiB) nor a 15.92 GiB card,
   so "clean up peaches output" means peaches renders and cerberus refines, and
   the artefact crosses boxes.
3. **A callable cross-box precondition** (`T3-25`), not a sentence: something
   answers "can an output be moved back from this host", the refusal quotes it,
   and when it answers yes the refusal stops. Its positive half must be
   exercised with the check forced true, or the refusal is green forever and
   never notices the day the blocker lifts.

Every repair writes a **new candidate beside the original** (`T6-A5`), both
scored, so "did the repair help" is answerable rather than asserted.

## 6. Build order

The PRD's §6 in dependency form. An arrow is a hard edge taken from the
documents, not a preference.

    T6-13a (songs.duration)  ->  T2-12a (legal frame count + clip_seconds honours it)
                                 ->  renderer takes a length
                                 ->  T2-13a, T2-13c, T2-8, T2-9
                                 ->  W2 per-scene models (T2-48)

    qc_service pattern  ->  sets_service     ->  clock/rounding, peaks, preview
                                             ->  master fix (5.2)  ->  audiences (T1-18..T1-20)
                        ->  storyboard_service ->  arc flows, meter, casting

    zimage_sweep scored  ->  calibrations row  ->  threshold (only if separated)  ->  tier 2 UI
    T3-23 routing (where/fits/resolve + actuator)  ->  T3-24 refiner box pick
                                                   ->  T3-25 remote-output move

`duck` and `layer` are off this graph on purpose: refused everywhere and honestly
so (`T1-23`), and `layer` goes first when they are scheduled because `xfade`
already positions both streams, where `duck`'s `sidechaincompress` needs
`adelay` + `asplit` to time-align an accumulated chain.

## 7. How this design is verified

The rules the project arrived at by being wrong, as they apply to building from
this document. The first was earned on 2026-08-13 and is the newest:

0. **Assert through the shared entry point, never through the function it
   wraps.** A check aimed at the wrapped function is blind to whether its
   callers are wired correctly, so it stays green through a broken call site —
   measured on `T1-20d`, where every assertion survived a call site deliberately
   set to the wrong value. Wherever this design collapses a decision to one
   application point — `item_chains`, `mixer.set_duration`,
   `build_song.clip_plan`, `effects.measure_loudness` — the criterion goes
   **through** the collapse point, not around it. §5.2 has the mutation.
1. **Differential, or name the mutation.** Every criterion in the three TRDs
   already does one or the other.
2. **Then mutate and read what the mutation actually did.** Twelve mutations
   against one session's own checks found two that could not fail, and one of
   those was hiding a real defect. Another mutation did not mutate anything and
   the check passed — which is how a check that proves nothing survives an audit.
   §5.2 above is written the way it is for that reason: the mutation moved one
   row and left the other two alone.
3. **A refusal or a presence is half a criterion.** Each TRD carries a table of
   its one-sided criteria paired with the positive case that must also pass.
   Those tables are the work, not commentary.
4. **`grep -c "^def test_"` before and after, and never replace a slice that
   runs to the end of a file.** A deleted test does not fail. Baseline is green
   before and after — the count is deliberately not written into this document,
   because it was copied into three and all three went stale.

Plus the one that no automated check replaces: **when an image looks wrong, look
at it.** The identity collapse, the world that never rendered and the LoRA that
did nothing all passed every deterministic check this project had. QC does not
replace opening the picture; it decides which pictures to open.

## 8. Design risks

- **The service split stalls half-done**, leaving two ways to reach the same
  logic. `T6-A2` is the guard and it must be written per loop as the loop moves,
  not at the end.
- **Peaks get used as a quality signal.** They are a 22050 Hz mono envelope.
  Anything about clipping needs the second decode, stated in §5.4 so it is a
  decision rather than a discovery.
- **Tier 2 ships a threshold anyway** because a number exists and looks
  authoritative. §5.6's order is the whole defence, and `T3-14` refuses the
  configuration rather than trusting discipline.
- **`T2-12a` is treated as small.** It is one rounding rule, and four criteria,
  the approve grid, the time meter and the reference count all sit behind it.
