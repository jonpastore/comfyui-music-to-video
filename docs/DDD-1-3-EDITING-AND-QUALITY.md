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
| `studio/app.py` | 7589 | 138 routes, 25 of them `/api/*` JSON | T6-A1 named loops land on `/api/sets`, `/api/playlists/{id}/arc`, `/api/songs/{id}/storyboard/{tier}`, `/api/qc/*`; song page `video_model` select is `models.renderable("video")` (`T2-33`); `sets_service.py` / `storyboard_service.py` are still T6-A3 |
| `studio/mixer.py` | 2116 | set duration, `transition_times` (`T3-12` model), both filter graphs, overlap arithmetic, beatmatch, ramps, splice, `spliced_duration` / `SPLICE_DURATION_TOLERANCE` (`T3-10`), song-assembly geometry (`T5-7`) and fps (`T2-13d`) | TRD-1's engine. Built; one measured gap, §5.2. Song assemble honours largest same-aspect size and refuses mixed aspect — it does not letterbox. Mixed clip fps honours the highest and is asserted on the assembled file |
| `studio/effects.py` | 592 | effect validation, `filter_sweep`, `duration_delta`, `loudnorm_filter`, `measure_loudness`, `export_loudness`, `LOUDNORM_I` | built; owns loudness for `T1-25` and the loudness half of §4.3. `T3-9` silence is **not** here |
| `studio/automation.py` | 457 | TRD-1 §5 in full: lanes, RDP decimation, `MAX_POINTS = 64`, `FILTER_EXPR_MAX_BYTES = 8192` (`T1-10`), `fragment`, `item_audio`, `wants_master_loudnorm` | built |
| `studio/qc.py` | 642 | TRD-3 tier 1 in full; **T3-8** `expect_interpolated` (RIFE `(n-1)*m+1` + `make_postproc.out_fps`; duration/fps/frame_count, not latent exemption alone — `test_t3_8_interpolated.py`); T3-9 `measure_band_energy` (low/mid/high mean, not peak); **T3-10** `check_splice` vs `mixer.spliced_duration` / `bridge_seconds` (`test_t3_10_splice.py`); **T3-11** `check_set` / `run(kind="set")` duration vs `mixer.set_duration()` within `mixer.SET_DURATION_TOLERANCE` on the artefact (`test_t3_11_set_duration.py`); T3-12 `transition_lands` (pixels vs `mixer.transition_times`, half-frame, no remedy); T3-13 `score_zimage_sweep`; T3-15 histogram `identity_embed`; T3-16 `identity_verdict`; T3-17 `score_identity_artefact` (per artefact vs chosen anchor); T3-26 `measure_refiner_help` (fail-closed labelled set, not opportunistic); T3-28 `check_identity_wrong` / `identity_wrong_remedy`; T3-27 `CHECK_REMEDY_CLASS` / `actuator_for` | built |
| `studio/qc_service.py` | 308 | findings, queue, `by_host` (`T3-1`), remedy edit, dismiss, reopen; `artefact_hash` keeps a dismissal on the same bytes and reopens the same check when the file changes (`T3-22`); `approve()` enqueues dest ≠ source; `pair()` lists original and repair, both scored (`T3-21`); approve uses `remedy_class` (`T3-27`); the version that RUNS is `findings.remedy_prompt_id` looked up at execute (`T3-20`); `dispatch_repair` asks `where()`/`fits()`/`resolve()` then submits `fix_ref` / `gen_postproc`; real `fits()` routes the refiner by resident cost (`T3-24`); `can_move_output` gates remote repair (`T3-25`); `run_zimage_calibration` writes the T3-13 row; `set_threshold` writes a value only on a stored separated row (`T3-14`/`T3-16`); `build_identity_gate` never builds; T3-17 `score_identity_artefact` / `run_artefact` records the per-artefact score as a tier-2 measurement, no gate; T3-28 refuses a swap-the-reference identity-wrong remedy; `record_refiner_help` persists the T3-26 finding; `run_song` is tier 1 over a song's artefacts with no GPU and no backend (`T3-32`); `persist_still_qc` writes advisory `qc_json` on an `h_repair` dest still and a standalone refine dest (`T3-31`); named lander `h_reroll` writes `refs.qc_json` (`test_h_reroll_stores_qc_json`) | built |
| `studio/arc.py` | 327 | TRD-2 §3.1/§3.2 JSON-canonical arc; §3.3 `save_prompt`/`restore_prompt` (`T2-5`); §4.1 wand (`require_theme`, proposal files, `apply_summaries`) | built (`T2-5`/`T2-14`/`T2-15`/`T2-16`) |
| `studio/prompts.py` | 265 | TRD-2 §3.3 versioning; `restore(vid)` puts previous text back as a new version (`T2-5`); `delete` drops a row and does not renumber survivors (`T2-6`); `running(vid)` is the row a render RUNS (`T3-20`) | built |
| `studio/grok.py` | 1249 | storyboard generation, `validate`, the retry loop | built; §5.5 |
| `build_song.py` | 789 | `clip_plan`, `clip_seconds`, `n_clips_for`, `expect_from_workflow`, `clips_for_scene` | the one timing owner; `clip_seconds` honours `legal_frames`, §5.5; `main()` honours per-scene `video_model` (`T2-47`), per-model ceilings (`T2-48`), and per-scene `ref_motion` / `control_video` (`T2-46`) |
| `studio/db.py` | 559 | schema | `automation`, `findings` (`artefact_hash`, `remedy_class`), `artefacts`, `sets.mode_audience`, `calibrations` landed; `sets.out_fps` did not, §4 |
| `studio/vision.py` | 516 | VLM calls, local-first | **not** tier 2, §5.6 |

Deliberately absent, verified by `grep -rn` over `studio/*.py` and the root
scripts: no *configurable* master chain (T1-19 records the fixed
`one-button-master` v1 on the render; §8a stays fixed-order, not a
control surface), no peaks store, no
tier-2 gate or UI. `calibrations` and `qc.score_zimage_sweep` landed for
`T3-13` (overlap/separation/per-file, `threshold` NULL). `T3-14`
`set_threshold` writes a number on a stored separated row and refuses
without one. `T3-15` is a colour histogram, not a spatial grid.
`T3-16` names overlap inconclusive and does not build a gate.
`T3-17` scores each artefact against the chosen anchor; it is not a
gate and not a UI.
`siglip2_naflex`
is still only a `models.py` catalogue entry; the default embedder is a
colour histogram so the report can run without a GPU. `insightface` is
absent.

## 2. The structural problem, and the pattern that already solves it

`app.py` is 7589 lines and 138 routes, of which **25 are `/api/*` JSON**.
`T6-A1`'s three named loops complete over those paths (set empty→rendered,
storyboard, review queue). `/queue` still answers JSON from the same
`queue_ctx()` as the fragment (`T6-A2`). The HTML handlers still decide;
`sets_service.py` and `storyboard_service.py` are still the T6-A3 move.
`render_set_route` is TRD-1 §10's named example: `_set_render_items` plus
`_enqueue_set_render` is now the shared entry the JSON loop calls.

`T6-A1`…`T6-A4` are the requirement. **`qc_service.py` is the pattern and it
already works**: `qc.py` is pure measurement that touches no database, so it runs
over a directory of old output (`T3-30`); `qc_service.py` persists and imports
nothing from FastAPI; the five routes are thin. Copy that shape, do not invent a
second one. `T6-A4` holds on `/queue`: `queue_ctx` emits the counts, the row
list and a formatted `elapsed`, and `_queue.html` interpolates them. A stub that
returns `12.7s` and counts that are not the list lengths is what the page
shows (`test_t6_a4_queue_page_shows_stubbed_values_unmodified`). `_jobs_panel.html`
still formats elapsed.

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
The first object is the queue panel: `GET /queue` HTML and
`Accept: application/json` share `queue_ctx()`
(`test_t6_a2_html_and_json_report_the_same_queue_numbers`). Set, storyboard
and review loops now complete over JSON (`test_t6_a1_*`); their T6-A2
number-agreement tests still sit with those surfaces.

## 3. API surface

Named per journey, because `T6-A1` requires a curl script to drive each one end
to end. Shapes only — the fields are the TRDs'.

**A · set timeline** — `GET/POST /api/sets`, `/api/sets/{id}` (model in full:
items, automation, predicted duration, rounding deltas), `/api/sets/{id}/items`,
`.../items/{iid}/automation/{lane}` (POST raw points, response is the **stored,
decimated** curve — the client re-reads what was kept, §5.3),
`GET/POST /api/songs/{id}/automation/{lane}` (T8-13: same `automation.save` /
`item_audio` path, one-item `song_editor` set, not a second curve model),
`/api/songs/{id}/peaks?z=` (`pairs` plus `reason` when empty, `T1-15`),
`/api/sets/{id}/peaks?z=`, `/api/sets/{id}/preview` (returns `is_proxy` and
`not_applied`), `/api/sets/{id}/preview/render?at=&secs=`
(`is_proxy: false`, the accurate span),
`/api/sets/{id}/render` (`T1-3`: same ffmpeg argv as `POST /sets/{id}/render`),
`/api/sets/{id}/renders` (every candidate, `T1-26`,
`T6-A5`) and `POST /api/sets/{id}/renders/pick` (either listed render is
selectable). `GET /api/qc/lineage?kind=&group=` and `POST /api/qc/lineage/select`
are the same pair for refine, repair and anchor re-roll — `qc_service.listed`
and `qc_service.select` decide; the route forwards.

**B · arc and storyboard** — `GET/POST /playlists/{id}/arc` (POST is
propose; empty theme is 400, `T2-14`), `POST .../arc/propose` (same
handler), `POST .../arc/accept`, `POST .../arc/reject` (proposal is not
saved until accepted; reject re-reads the previous file, `T2-15`),
`POST .../arc/apply` (`song_ids`, `confirm`; more than one song without
confirmation is 400, `T2-16`). Same routes, no parallel `/api/*` tree
(`wants_json`). `GET/POST /api/songs/{id}/storyboard/{tier}`,
`.../scene/{n}`, `.../meter`, `.../cast`. The generation prompt and
**the limits that apply to it** travel in the same response (`T2-18`).
**B · arc and storyboard** — `GET/POST /api/playlists/{id}/arc`,
`.../arc/propose` (proposal is not saved until accepted, `T2-15`),
`.../arc/reject` (previous file on disk is left untouched),
`GET/POST /api/songs/{id}/storyboard/{tier}`, `.../scene/{n}`,
`.../meter`, `.../cast`. The GET payload carries `anchors` — chosen album
sheets grouped per character (`character`, `character_id`, `images` with
`path`/`url`/`view`; protagonist first) so a client can draw the strip
(`T2-26`). Each scene object also carries its reference stills
(`refs` with `path`/`url` next to `image_prompt`, `T2-27`).
The generation prompt and **the limits that apply to it**
travel in the same response (`T2-18`).
`GET/POST /api/songs/{id}/storyboard/{tier}` (`T2-17` **built**: GET
returns `prompt` from `storyboard_generation_payload`, defaulted from the
tier; POST accepts an edited `prompt`; `T2-18` **built**: same body carries
`max_characters`, `pinned`, `pinned_added_at_use`, `pinned_editable`; one
character over the returned cap is 400 quoting that number),
`.../scene/{n}`, `.../meter`, `.../cast`.

**C · QC** — exists. `/api/qc/run`, `/api/qc/findings`, `/{fid}`,
`/{fid}/remedy`, `/{fid}/dismiss`, `/{fid}/approve`, `/{fid}/recheck`,
`/api/qc/by-host` (`T3-1`: groups by `host`, NULL host is the
`unattributed` bucket). `GET /qc` is the finding-row page (`T3-19`):
measured / expected / unit, editable remedy, approve. `POST
/qc/findings/{fid}/approve` stores the edited text then `approve()`.
Each finding carries `remedy_class` and
`actionable` (`T3-27`): approve uses the class, and a false `actionable`
is why the button is absent, not a button that does nothing. Dismiss needs a
reason and leaves the open queue; re-running QC on the same bytes keeps
it dismissed; rewriting the file reopens that `(path, check)` row
(`T3-22`). `POST /songs/{id}/qc` calls `qc_service.run_song` in-process
(`T3-32`): tier 1 over that song's artefacts does not enqueue behind
the GPU worker. `/api/qc/lineage` lists predecessor and successor for a
re-render / refine / repair / anchor re-roll; `/api/qc/lineage/select`
picks either (`T6-A5`).

**Q · queue** — `GET /queue` answers HTML or JSON from the same `queue_ctx()`
(`T6-A2`). The JSON body carries `running`, `waiting`, `recent`,
`refresh_secs` and the job ids/elapsed the fragment prints.

Every list response carries help text per control, with warnings marked
distinctly from notes (`T2-36`) — a client that cannot tell them apart hides the
wrong one, and day 8's rule is that the warnings do not move.

## 4. Schema deltas still required

Landed already: `automation`, `findings` (including `artefact_hash` for
`T3-22` and `remedy_class` for `T3-27`), `artefacts`, `storyboards.scene_seconds`,
`sets.mode_audience` (`easy|normal|advanced`, default `normal`; `T1-20`),
`calibrations` (`T3-13`; `T3-14` may write `threshold` only after a
separated row exists), the interstitial card
(`set_items.song_id` nullable, `card_path`, `card_secs`; `mixer.is_card` /
`set_duration` prices it; `POST /sets/{id}/cards`), and `lineage`
(`T6-A5`: predecessor/successor pair, either selectable). Switching audience writes
only that column. Easy is `mixer.master_engaged` reading `mode_audience ==
"easy"` on the item dict — the same application point as a gain curve
(`T1-18`, `T1-20c`, `T1-20d`).

Still needed, and no more than this:

    ALTER TABLE sets ADD COLUMN out_fps REAL;                        -- NULL = derive from items

Peaks are **not** a table. They are a binary min/max array written beside the
song by the existing `analyse` job and served decimated (§5.4).

`pan` stays an `effects_json` key and does **not** become a column — TRD-1 §3.1
decided that and the reason is §5.0(b)'s: a column would be a second place for
the value before anything needs one. Gain already had two places and cost a
silent -6 dB (mixer.py `_audio_chain`'s own docstring).

## 5. Subsystem designs

### 5.1 The clock, and one place that rounds

`T1-5` still needs the video cut on the nearest frame and the audio
crossfade at the exact second. `T1-6` is **built**: `mixer.frame_round(t, fps)
-> (t_rounded, delta)` is the one place that rounds (nearest, not
truncation); `mixer.rounding_report` walks the same joins as
`timeline_joins` and reports per-join delta plus `abs_delta_sum`.
`GET /api/sets/{id}` carries that object, so the half-frame-per-join
bound is checkable from the model without rendering. Truncation is the
mutation that must break it: the losses all share a sign and accumulate
at 0.0594 s per join at 16.8312 fps, which is the RIFE one-frame bug's
shape — it plays, it looks fine, it is the wrong length.

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

**Easy mode, 2026-08-14.** `sets.mode_audience` is the set-level fact.
`render_set_route` stamps it onto every item dict; `master_engaged` reads
`mode_audience == "easy"` at the same point a gain curve does, so easy
is that chain (`T1-20c`) and still one loudnorm (`T1-20d`). `app.audience_affordances`
is the affordance set `set_edit.html` consults — easy and advanced
differ as data, not as a stylesheet.

**`T1-19`, 2026-08-14.** `mixer.one_button_master()` is the named
versioned chain (`one-button-master` v1, I/TP/LRA). `_master_lines`
applies those params; `h_render_set` writes the same object to
`assets.meta_json.master_chain` only when `applied_master_chain` is
not None. The set editor shows name+version+params on the render
card. Changing I moves measured LUFS
(`studio/test_t1_19_master_chain.py`).

**`T1-25`, 2026-08-14.** `effects.export_loudness(path, I=, TP=)` is
the named record: measured LUFS / true peak, the target those were
compared to, and `flagged` when either sits outside
`LOUDNESS_TOLERANCE_LU` (2.0) or `TRUE_PEAK_TOLERANCE_DB` (0.5) of
that target. `mixer.export_loudness` supplies the master chain's I/TP
when the master ran, else the loudnorm defaults. `h_render_set`
writes it to `assets.meta_json.loudness`. The render card shows the
numbers and "off target" when flagged. The live `meter` component is
still not this.
(`studio/test_t1_25_export_loudness.py`).

**`T1-3`, 2026-08-14.** The stored model is the export. `POST /sets/{id}/render`
(UI) and `POST /api/sets/{id}/render` (JSON, no browser) both call
`_enqueue_set_render` → `_set_render_items`. `mixer.render_set_argv(items,
out)` is the ffmpeg command those items determine — the same list
`_run_ffmpeg` receives plus `ffmpeg -y -v error -stats`. T1-3 compares that
command, not file bytes (`creation_time`). Extra form fields on the UI POST
are not in the model and do not reach argv. Two encodes of the same items
agree on duration (`SET_DURATION_TOLERANCE`), frame count and integrated
loudness (`studio/test_t1_3_json_export_argv.py`).

**`T1-4`, 2026-08-14.** The filter graph is regenerated from the stored
model on every render. `mixer.render_set_graph(items)` is the
`-filter_complex` string `_render_set_args` just built — no module-level
cache. Mutating stored `set_items.gain_db` and re-reading via
`_set_render_items` changes that string (`volume=-6.000dB` →
`volume=-3.000dB`). A reused ffmpeg string would stay put
(`studio/test_t1_4_no_cached_graph.py`).

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
hand-kept copies, `CHUNK` with five clip-count readers (collapsed by `T2-13` to `n_clips_for`), `DEFAULT_BODY` losing to
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

### 5.3 Automation — built; what remains is the other lanes

`automation.py` owns the model, decimates on write with RDP plus a hard
`MAX_POINTS = 64`, and emits through `asendcmd`, which is the mechanism
`effects.filter_sweep` already uses — one emitter, one cap, and `sweep` becomes a
preset that writes points rather than a second automation system.

**`T1-1` is built (2026-08-14).** `t` is item-relative. Reordering a
set (`POST /sets/{id}/reorder`) or changing an item's `in_secs` /
`out_secs` / `secs` leaves every stored `(lane, t, value)` unchanged.
The check reads the rows before and after; it requires a non-empty
curve first, and asserts the reorder/trim itself landed. T1-2 / T6-10
only cover delete. (`studio/test_t1_1_reorder_keeps_automation.py`).

**`T1-9b` is built (2026-08-14).** `mixer.rms_per_second` / `mixer.rms_slope`
are the one RMS/s implementation. A stored `gain_db` ramp −12→0 dB over 6 s
on a constant 1 kHz sine, rendered through `mix_audio` (not `_audio_chain`),
has measured slope within `GAIN_CURVE_SLOPE_TOLERANCE` (0.5 dB/s) of drawn
2.0. The same fragment with `suppress_loudnorm` forced off misses that
bound — that is the 5.0(c) mutation. The fixture is a constant sine
because RMS slope on program material is not a proxy for gain.

**`T1-10` is built (2026-08-14).** A fully-populated lane (`MAX_POINTS`
zigzag over 1800 s so linear sampling hits `SWEEP_MAX_STEPS`) emits an
`asendcmd` string ≤ `FILTER_EXPR_MAX_BYTES` (8 KB) and `mix_audio`
writes a file from it. `fragment` refuses a longer string in Python
rather than handing ffmpeg a graph it will reject. Measured on
`gain_db` / `lowpass_hz` / `highpass_hz` in
`studio/test_t1_10_filter_expr.py`.

**`T1-11` is built (2026-08-14).** `POST /api/sets/{id}/items/{iid}/automation/{lane}`
writes one lane through `automation.save`. Two points at the same `t` are
400 and the body names that `t`. The module demo already refused; the
route is what the client posts to.

What is left is `T1-12` per remaining lane, as a differential (`pan` by L/R
energy ratio, the filter lanes by band energy). `gain_db` RMS/s is T1-9b.
This is the criterion that catches a lane wired into the UI and not into
the graph, which is how `_apply_beatmatch` was unreachable for a whole
session.

### 5.4 Peaks and preview

Peaks: computed on the **existing** `analyse` job, which already decodes the file
— do not decode it twice. Stored beside the song, served decimated at
`PEAKS_MAX_POINTS = 2048` per request. Decimation is a **min/max reduce, not a
resample** (`T1-14`): a waveform that under-reports a peak lies about where the
loud part is. The reduce is `mixer.peaks(samples, z)` (`T1-13`/`T1-14`).
`GET /api/songs/{id}/peaks` serves `{song_id, z, n, pairs, reason}`:
`reason` is `null` when there are pairs, and `no_audio` / `missing` /
`unreadable` when `pairs` is empty (`T1-15`). A flat line is silence;
empty without a reason is forbidden. Analyse storage and
`/api/sets/{id}/peaks?z=` are not wired yet.

The limit is stated in the design because it will otherwise be discovered by a
feature request: `analyse.py` loads mono at 22050 Hz, chosen because it matched
the measured tempo and halved load time. That is an envelope. A stereo waveform,
or anything claiming to show clipping, is a **second decode** and must be asked
for deliberately.

Preview: the browser plays source files with gain and position applied. **No
second DSP engine in Web Audio.** The proxy declaration is data —
`{"is_proxy": true, "not_applied": [...]}` — computed from the item's actual
effects by `mixer.preview_proxy` and served at `GET /api/sets/{id}/preview`,
so `T1-16`'s test (add an effect, see it appear in `not_applied`) fails
a static list. "Render preview" (`T1-17`) is `mixer.render_preview`: the
*same* `mix_audio`/`render_set` path as a full render, then a cut of
`PREVIEW_SPAN` (20 s) around the playhead, served at
`GET /api/sets/{id}/preview/render?at=&secs=` as `{is_proxy: false, ...}`.
It is the only preview that claims accuracy. `waveform_png` stays the
picture.

### 5.4a The time axis — built

`mixer.timeline_axis(duration_s)` turns `mixer.set_duration()` into ruler ticks.
`set_detail` passes that duration through — no second length arithmetic.
The HTML is a view: `.tl-axis` / `.tl-tick[data-t]`. A TestClient GET (no JS)
must carry the ticks, and a stub offset must move the last one
(`studio/test_t1_timeline.py`).

Joins, playhead and lanes sit on the same clock. `mixer.timeline_joins`
walks items with `_advance` so a fade's handle is the overlap start;
`POST /sets/{id}/items/{iid}/join` writes only `secs`. `mixer.timeline_playhead`
clamps `?at=` to `set_duration()`. `mixer.timeline_lanes` lifts item-relative
automation `t` onto the set axis; the HTML is `.tl-lane-pt[data-t][data-value]`.
Easy omits `.tl-lanes` (affordance, not CSS) and does not delete the rows.

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
2. The renderer takes a length. **Built (`T2-13a`).** `EmptyLTXVLatentVideo.length`
   and `TrimAudioDuration` follow `legal_frames(clip_seconds)`, not
   `LTX25_LEN`/`CHUNK`. Missing `length_seconds` stays 81 / `CHUNK`. `T5-9` is
   the ceiling **gate** on that request: over the labeled measured/chosen
   ceiling is refused or split, not annotated. It does not change the planner
   divisor — `clip_seconds(30)` and `n_clips_for(…, 30)` stay.
3. Then `T2-8`/`T2-9`. **`T2-8b` built.** `_compose` stamps `start`/`end`
   covering `[0, song.duration]`; `validate` refuses a gap or overlap
   (`test_t2_8b.py`). **`T2-8c` built.** `_compose` stamps `lyric_sections`
   as a partition of `parse_sections(audio_lyrics)`; `validate` refuses
   a missing field, an unnamed section, or a section named twice
   (`test_t2_8c.py`). `T2-13b` and `T2-13c` are not blocked on the
   renderer: `h_storyboard` upserts the storyboard row and does not touch
   `refs`, so re-planning leaves the approved `(clip_idx, seed)` set
   identical (`T2-13b`); `approve_context` enumerates `clip_count`, so a
   20-scene storyboard on a 41-clip song still lists every clip (`T2-13c`).
   **`T2-13e` built.** `clip_plan` with an `audio_path` sums
   `clip_seconds(length_seconds)` (CHUNK when missing) and refuses when
   that total misses the track by more than one clip. `main()` therefore
   writes no graphs. nclips-only callers are display and skip the gate.
   `assemble_song` keeps `-t audio_dur`; its comment no longer says
   clips are quantised so the video always overruns.
4. **`T2-47` built.** `main()` takes `scene.video_model` when present, else
   `--video-model`. One job with a scene marked `s2v` and one left `ltx25`
   writes WAN 77@16.0 and LTX 81@16.8312 (`test_t2_47_mixed_model.py`).
   Two names on a plan is not this check. **`T2-45` built.**
   `start_clips` asks `models.mixed_unavailable` (via `models.where()`)
   before `jobs.enqueue`: a mixed board that names a model `False` on
   every reachable backend is 400 and writes no job; `None` is a
   candidate (`test_t2_45_enqueue_unavailable.py`). **`T2-46` built.**
   A scene with `ref_motion` / `control_video` writes
   `LoadVideosFromFolder` on that clip only; `_attempt_plan` pins it
   to cerberus and the rest of the song still free-draws
   (`test_t2_46_driving_pins_cerberus.py`). **`T2-48` built.**
   `clips_for_scene` / `clips_for_scenes` split a scene on *that scene's*
   model ceiling: 30 s `s2v` → s2v-sized parts (`CHUNK`), 30 s `ltx25`
   → 15 s + 15 s, each chain tiles its scene from 0 (`T2-8b`).
   `grok._compose` stamps `clips` from the planned length;
   `validate` refuses a gap or overlap. `main()` expands an over-ceiling
   scene into that chain instead of handing 30 s to `workflow`.
   Mutation: ignore `video_model` → both scenes take 15 s.
   **`T2-42` / `T2-43` built.** `_scene_json` returns `video_model`
   beside `camera`; an unmarked scene stays empty and
   `clips_for_scene` / `main()` take `--video-model`.
   `EDITABLE_SCENE_FIELDS` includes `video_model`; the scene row
   shows it beside camera (`test_t2_42_scene_video_model.py`).
   **`T2-44` built.** `models.refuse_unknown_video_model` refuses a
   named model absent from `renderable("video")` at save.
   **`T2-46` built.** A scene requesting `ref_motion` or `control_video`
   pins that clip to cerberus; the rest of the song still free-draws.
   **`T2-13d` built:** `assemble_song` normalises those native rates to
   one output fps (highest) on the assembled file. Concat first-clip-wins
   is not that check.
   **`T2-13f` built.**
   `qc.clip_qc_expect` keeps that native fps as the clip's QC question;
   the song's output fps is assembly's (`T2-13d`) and is ignored here.
   Mixed s2v@16 / LTX@16.8312 each pass their own check
   (`test_t2_13f_native_fps.py`). Copying the song rate onto the clip
   flags the other model.

`W1-4` sits alongside and is a **prompt**, not code. `T2-14a` is **built**:
`grok._user_prompt` no longer names a fixed 4.8125 s quantum, does not say
nothing shorter or longer can be produced, and does not tell the model to
round `duration_guidance` to multiples of a constant. `_system_prompt` no
longer names 4.8125 s either. `T2-14b` is **built**: the TIMING clip-length
line is `clip_seconds(scene_seconds)`, so one song at two `scene_seconds`
produces two statements — a new constant 15.0 would keep the sentence shape
and fail this. `T2-14c` is **built**: the return value still states track
length and requires scene durations to sum to approximately it. Deleting
the TIMING block wholesale leaves `T2-14a` green and fails this. The
function is pure; assert on its return value, never by grepping the source.

`T2-8b` is **built**. `_compose` stamps each scene's `start`/`end` so they
tile `[0, duration]`; `validate` refuses a gap or overlap. Mutation: drop
the check → a gapped board is accepted.

`T2-8c` is **built**. `_compose` stamps each scene's `lyric_sections` so
the parsed lyric sections are a partition across scenes; `validate`
refuses a missing field, an unnamed section, or a section named twice.
Mutation: drop the check → an unnamed section is accepted.

`T2-20` is **built**. `_compose` stamps `album_arc` from `arc_ctx` beat and
continuity onto the generated board; no arc leaves the field off. Same
recorded model response both arms — two fixtures differing is not the
check. Mutation: drop `arc_ctx` from `_compose` → red.

`T2-21` is **built**. `_compose` at `xxx` strips *"fully clothed,
tasteful and non-graphic"* and *"no explicit gesture"* from each
scene's `image_prompt` and `video_motion_prompt` and stamps
*"Explicit adult content is permitted"* in their place. Same recorded
`rear-entrance_xxx.json` response; the existing direction test only
checked the guardrail sent to grok. Mutation: leave scene text
untouched → red. Mutation: strip and do not stamp → red.

`T2-22` is **built**. `_compose` stamps `guardrail` from
`tiers.compose_guardrail(tier)`, not the `guardrail` argument — a
passed-in dummy is discarded. `app.foreign_tier_in_storyboard` matches
another row's stored tone half (PINNED is shared, so composed text
would false-positive) and `save_scene` / `h_storyboard` refuse it.
A clean scene edit still writes. Mutation: drop the stamp → generation
arm red. Mutation: write without the check → save arm red.

`T2-31` / `T2-32` are **built**. `grok.write_storyboard` refuses an
empty, whitespace, or missing `character_reference` before creating
files. `save_scene` and `_apply_scene_fields` return 400 with
`grok.EMPTY_CHARACTER_REFERENCE`: identity comes from the text, not
the reference image; an empty lock renders a stranger in every clip.
A filled lock still writes. Mutation: dump without the check → writer
arm red. Mutation: write the scene without the check → save arm red.
`T2-23` is **built**. `GET /api/songs/{id}/storyboard/{tier}/meter`
reports `scene_time` (sum of scene `duration_guidance`), `song_length`
(the song duration), `tolerance` (`SCENE_TIME_TOLERANCE`, 0.15 of song
length) and `mismatch` when the absolute delta exceeds that.
In-tolerance is not flagged. Mutation: always report the numbers and
never set `mismatch` → the miss arm fails. The live `meter` component
is not this.

`T2-24` is **built**. The same meter reports `clip_seconds` from
`build_song.clip_seconds(scene_seconds)`, not `CHUNK`. Same song at
15 s and 30 s yields two lengths. Mutation: hardcode 4.8125 → both
arms equal. Mutation: return raw `scene_seconds` → 15.0 is not the
legal 8n+1 length. The live `meter` component is not this.

`T2-25` is **built**. `POST /songs/{id}/clips` calls
`refuse_if_scene_time_mismatch` after the existing duration/refs
gates: a miss is 400 and writes no clips job; an in-tolerance board
still enqueues. An unreadable board file is skipped so the older gates
still fire. Mutation: flag only on GET `/meter` → the miss arm fails.

`T2-33` is **built**. `GET /songs/{id}` builds the video-model select
from `models.renderable("video")` (labels/purpose from `catalog()`).
Adding a `CATALOG` entry with a `cli` makes that cli, label and
purpose appear with no template change
(`test_t2_33_picker_renderable.py`). Mutation: call `renderable()` and
discard it, or post-filter to a stale list → the probe is absent.
`T2-34` (unavailable shown as unavailable, with an available model
still offered) is not this.

`T2-26` is **built**. `GET /api/songs/{id}/storyboard/{tier}` includes
`anchors`: one group per character with `character`, `character_id` and
`images` (`id`, `view`, `path`, `url` via `media_url`). Protagonist
(`character_id` NULL, name `"protagonist"`) first, then cast by name.
`album_chosen_anchors` is the one query; the HTML page and the JSON
share it. Chosen sheets only. Mutation: omit the key → red. Mutation:
flat images with no character grouping → red. Mutation: drop a cast
member's chosen sheet → red.

`T2-27` is **built**. `_scene_json` includes `refs` next to
`image_prompt` / `story` / `video_motion_prompt`: per-clip `idx`,
`path`/`url` of the latest candidate, plus `candidates[]` (`id`,
`path`, `url`, `seed`, `approved`). `storyboard_scenes` is the one
mapping; HTML `_scene_row.html` and the JSON share it. Scene A does
not carry scene B's still. Another tier stays out. Mutation: omit
`refs` on the scene → red. Mutation: top-level refs only → red.
Mutation: copy another scene's still onto this scene → red.

`T2-29` is **built**. A named scene figure is `{name, role}` with
`role` in `lead` / `extra` / `background`. `_compose` keeps classified
figures (it used to drop dicts). `write_storyboard` / `validate` /
scene save refuse a named figure with no role or a free-text role.
`GET /api/songs/{id}/storyboard/{tier}/cast` returns `role` on each
figure. A bare name is a legacy lead. Mutation: coerce to strings →
compose arm red. Mutation: dump without the check → writer arm red.
Mutation: return names without role → API arm red. `T2-30` is not this.

`T2-44` is **built**. `models.refuse_unknown_video_model` walks the
board's scenes and raises when a named `video_model` is absent from
`models.renderable("video")` as a key *or* a cli value, quoting the
scene number and the bad value. `save_scene` and `_apply_scene_fields`
return 400 and do not write. Absent or whitespace is not a name
(`T2-42`). A real cli (`s2v`) still saves. Mutation: write without
the check → save arm red. Mutation: rewrite to `default_cli` → the
file changes and the named-value assertion fails.

### 5.6 Tier 2 is a calibration, not a metric

`vision.py` is a VLM caller and is **not** the tier-2 path. TRD-3 §10 forbids a
VLM verdict by name — asked "does this match?", a model answers yes — though it
may write a *description* attached to a finding. `app.score_generated_still`
stores that advisory `qc_json` on every landed still (anchors, refs including
`h_reroll`, artwork generate and its refine sibling, and the sibling
`h_fix_anchor` writes).
`qc_service.persist_still_qc` scores an `h_repair` dest still and a standalone
`refine_generated_still` dest onto `artefacts.qc_json` (and updates a dest
candidate row if one already exists). `h_artwork` inserts one scored `assets`
row per landed cover; it does not drop the generate when refine succeeds.
`refine_generated_still` writes a sibling via `qc_service.produce_repair` and
then scores it; it never overwrites the generate. `h_fix_anchor` is the
operator-started repair; it scores the new file and does not overwrite or
auto-heal. QC never auto-heals (`T3-18`).

Design, in the order `T3-13`…`T3-17` fix:

1. Extractor over `zimage_sweep/`'s **12 known-bad and 6 known-good** images
   (same prompt, same anchor, same day; on two seeds the model draws bare human
   legs with a cat's head at every step count, on the third it holds fur head to
   toe). **Built** as `qc.score_zimage_sweep` / `qc.identity_score`. Default
   embedder is a colour histogram (not pixel MSE, not a spatial grid).
   `siglip2_naflex` is still the intended production extractor and is not
   wired; `insightface` is the alternative.
2. Write a `calibrations` row: both distributions, the overlap, the separation,
   and **every individual file's score**. **Built** (`qc_service.run_zimage_calibration`);
   `threshold` is refused at write. That report is the T3-13 deliverable.
3. `T3-14` can set a threshold on a stored calibration and refuses without
   one, naming why. `T3-16` names overlap inconclusive and does not build
   a gate — that is a success, and the failure mode it avoids is shipping
   a threshold that splits noise. No UI.
4. `T3-15` is the regression guard: the metric must not rank a deliberate pose
   change as an identity failure. **Built** against the recorded pair that
   pixel distance got backwards — 41.1 for the wrong render, 64.7 for the right
   one.
5. `T3-17` scores **each artefact** against the chosen anchor, whatever
   caused the gap. **Built** as `qc.score_identity_artefact` (pure) and
   `qc_service.score_identity_artefact` / `run_artefact` (recorded, tier 2).
   The reachable case is a non-empty reference plus text that does not
   name the species. `qc.run` (tier 1) cannot see the score. No threshold,
   no gate, no UI.

Reported per artefact: a calibrated compliance percentage, a **variation** figure
across the sampled frames, and the sample count both came from. Variation is the
one that matters more now than it did: chained clips start from a generated
frame, not an approved reference, so drift *within* a long clip is the reachable
failure. `score_identity_artefact` is that report.

### 5.7 What has to exist before a repair is a repair

`qc_service.approve()` enqueues one `repair` job with dest ≠ source. It does
not write dest and it does not run a GPU. `dispatch_repair` now turns that job
into a real candidate (`T3-23`):

1. **Remedy → action mapping.** The check's `remedy_class` (`T3-27`) picks
   the actuator: image / `edit-text` submit `pipeline.fix_ref`; clip /
   `upscale` submit `pipeline.gen_postproc`. A class of `none` is a
   named refusal, not a button. A silent `shutil.copy2` of src is still
   refused.
2. **Routing that asks first.** `models.where()` and `models.fits()` choose the
   box, `models.resolve()` names the file *that box* uses, and a pin under a
   name the box does not have is refused before submit. `T6-A6`'s three values
   stay: `False` refuses, `None` is a candidate. The refiner is ~19.6 GiB
   resident (`T3-24`): real `fits()` routes it off a 15.92 GiB card onto a
   24 GiB one that holds the correct name, and peaches cannot take the pair,
   so "clean up peaches output" means peaches renders and cerberus refines,
   and the artefact crosses boxes.
3. **A callable cross-box precondition** (`T3-25`), not a sentence:
   `can_move_output(host)` answers "can an output be moved back from this
   host", the refusal quotes that name, and when it answers yes the refusal
   stops. The flip is exercised: with the check forced true, a remote repair
   is SUBMITTED.
4. **The wording that RUNS is the stored prompts row** (`T3-20`).
   `approve()` puts `remedy_prompt_id` on the job; `_invoke_actuator`
   looks that id up via `prompts.running` and sends that text. A copied
   string on the job, or a deleted row, is not what runs. Same id is
   readable on the finding, the job, and `prompt_versions` after
   approval.
5. **Whether the refiner helps is measured, not assumed** (`T3-26`):
   `qc.measure_refiner_help` scores a labelled plain/refined set and
   fail-closes on empty / missing files / missing scores. A pass that
   does not improve the tier-2 score is a finding that says not helping.
   Catalogue `proven: opportunistic` is not the answer.

Every repair writes a **new candidate beside the original** (`T6-A5`).
`h_repair` lands dest and the original; `qc_service.listed` / `select`
list both and either is selectable. `qc_service.pair(fid)` lists both
as landed artefacts with findings and a `qc.summarise` verdict (`T3-21`),
so "did the repair help" is answerable rather than asserted.

## 6. Build order

The PRD's §6 in dependency form. An arrow is a hard edge taken from the
documents, not a preference.

    T6-13a (songs.duration)  ->  T2-12a (legal frame count + clip_seconds honours it)
                                 ->  T2-13a (renderer honours that length)
                                 ->  T2-13c (built), T2-8b (built), T2-8c (built), T2-8, T2-9
                                 ->  T2-13c (built), T2-13e (built), T2-8, T2-9
                                 ->  W2 T2-47 mixed-model native fps (built)
                                 ->  W2 T2-45 mixed unavailable refused at enqueue (built)
                                 ->  W2 T2-46 driving scene pins to cerberus (built)
                                 ->  W2 T2-48 per-scene ceilings compose (built)
                                 ->  T2-13d assembly one output fps (built)
                                 ->  T2-13f clip QC uses native fps (built)

    qc_service pattern  ->  sets_service     ->  clock/rounding, peaks, preview
                                             ->  master fix (5.2)  ->  audiences (T1-18..T1-20)
                        ->  storyboard_service ->  arc flows, meter, casting

    T3-8 RIFE expect_interpolated (built; out_fps + (n-1)*m+1)
    T3-9 band-energy silence (built)  ->  §4.3 audio tier (loudness stays effects.py)
    T3-10 splice duration vs mixer.spliced_duration (built; SPLICE_DURATION_TOLERANCE)
    zimage_sweep scored  ->  calibrations row  ->  threshold (only if separated)  ->  tier 2 UI
    (T3-13..T3-16 landed the first three; T3-17 scores per artefact; the UI stays off)
    T3-11 set artefact vs mixer.set_duration() (built; SET_DURATION_TOLERANCE)
    T3-23 routing (where/fits/resolve + actuator)  ->  T3-24 refiner box pick
                                                   ->  T3-25 remote-output move
                                                   ->  T3-26 labelled-set "does it help"

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
  not at the end. The queue panel is written; set, storyboard and review are not.
- **Peaks get used as a quality signal.** They are a 22050 Hz mono envelope.
  Anything about clipping needs the second decode, stated in §5.4 so it is a
  decision rather than a discovery.
- **Tier 2 ships a threshold anyway** because a number exists and looks
  authoritative. §5.6's order is the whole defence, and `T3-14` refuses the
  configuration rather than trusting discipline.
- **`T2-12a` is treated as small.** It is one rounding rule, and four criteria,
  the approve grid, the time meter and the reference count all sit behind it.
