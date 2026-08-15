# TRD-1 · Timeline and mixing (the DAW)

Status: draft for review, written 2026-08-12. Inputs: `docs/SETS_MIXING_PLAN.md`
(what is built), `docs/RECONCILIATION_2026-08-12.md` (the day's measurements and
the decisions), `docs/EXTERNAL_REVIEW_2026-08-12.md` (outside opinion, verified).

Acceptance criteria are numbered `T1-n` and are written so that each one **can
fail**. A criterion that cannot fail is not a criterion. Where a number appears
it was measured on this fleet, and the source is named.

Blocked on nothing. The two things that blocked it — clip length and frame rate
— were measured 2026-08-12, and the two decisions this document needed are taken
in §3.

---

## 1. The problem

A set is a stack of forms. `templates/set_edit.html` renders one `<form>` per
item with in/out/gain/transition/secs/hold/beatmatch/effects_json, and the only
picture of the result is a number. There is no time axis, no waveform, no
automation, and nothing that shows an item's length against its neighbours.

What is wanted is a timeline: see the set, drag the joins, draw a level curve,
hear it, then render the same thing you were looking at.

Two constraints from outside review that shape everything below, both of which
this project has already paid for in other forms:

- **The timeline model lives on the server, not in the DOM.** The browser is a
  view. Export must be deterministic from the stored model with no dependency on
  a pixel position.
- **Preview is not the deliverable, and the user will trust the wrong one.**
  Browser playback is a proxy; ffmpeg is the truth. This is *the editor promising
  what the renderer does not produce* — day 4's Traps section, found and fixed
  six times — arriving somewhere new.

## 2. Not in scope, because it already exists

Do not rebuild any of this. It is built, tested, and its arithmetic is the part
that has been debugged.

| already built | where |
|---|---|
| `sets` / `set_items` rows with in/out trim, gain, transition, secs, hold, beatmatch, brand, `effects_json` | `db.py:124-141` plus the `ALTER TABLE`s |
| Predicted set length, walked exactly as the renderer walks it, through the same fit guard | `mixer.set_duration()` |
| The audio and video filter graphs, geometry/fps normalisation, crossfade overlap arithmetic | `mixer.mix_audio()`, `mixer.render_set()`, `_build_render_set_filter()` |
| Beat grid, downbeat offset, snap on both sides, tempo ramp, Camelot ordering | `analyse.py`, `mixer.snap_transition/plan_tempo_ramp/apply_tempo_ramp/suggest_running_order` |
| Effect validation with hard ranges, and the length an effect chain ADDS | `effects.py`, `effects.duration_delta()` |
| Per-item video look (grade, glitch) and beat-aligned cut offsets | `video_fx.py` |
| Waveform PNG | `mixer.waveform_png()` |
| Drag-to-reorder | `static/app.js`, generic over rows |

**The overlap arithmetic is shared between the audio-only and video paths on
purpose. Keep it that way** — `SETS_MIXING_PLAN.md` says so and it is the reason
`set_duration` can price both.

## 3. Decisions taken here

**3.1 The channel model is stereo pan, per item.** Decided 2026-08-12 by Jon.
"L/R split" is three different features and outside review was right that one has
to be picked before any UI is drawn. It is one number, one ffmpeg filter, one
automation lane.

**BUILT 2026-08-13, and NOT as a column.** Pan is a key in the existing
`effects_json`, validated by `effects.py` and applied in the one chain builder,
because that path is already plumbed end to end — route, form, renderer — and a
`set_items.pan` column would have created a second place for the same value
before anything needed one. That is the defect §5.0(b) records for gain, which
is already in two places. The column arrives with the timeline, or not at all.

    effects_json: {"pan": 0.6}          -- -1 hard left .. +1 hard right
    pan=stereo|c0=<l>*c0|c1=<r>*c1

**It is a BALANCE, not an equal-power pan law**, and the difference is the
centre. cos/sin puts 0.707 on both channels at centre, which is -3 dB on every
item nobody panned; attenuating only the opposite channel leaves centre at
unity, so a set with no panning renders exactly as it did before the feature
existed. At `pan: 0` no filter is emitted at all. Sources here are stereo
tracks, so balance is the right operation anyway.

Measured, not asserted: hard right leaves the right channel within 0.5 dB of
source and the left more than 40 dB below it, the mirror holds for hard left,
and centre is within 0.1 dB of source on both channels.

**A review challenged both halves of this and both challenges are wrong**,
recorded here so the argument is not had a third time. It said the filter
"discards cross-channel terms" and is therefore not a balance: cross-channel
terms are what ROTATES a stereo image, and balance by definition attenuates one
side without mixing — which is the stated intent and what the measurement shows.
It also said the -3 dB claim was "oversimplified to the point of being wrong".
Measured 2026-08-13 on a 440 Hz stereo tone: source -21.1 dB mean, balance at
centre -21.1 dB, equal-power at centre **-24.1 dB**. Exactly the 3 dB, on the
file, which is what the sentence claims.

Dual mono and mid/side are **not** built. The upgrade path is a `channel_mode`
column added later with `pan` as its default, so nothing stored today has to
move. Recorded so the next person does not re-derive the question.

**3.2 Clip length is per song, from the storyboard, scenes driving clips.**
Decided 2026-08-12 by Jon; the formula change belongs to TRD-2 (`T2-8`
through `T2-9`, and the **two** live sites §3.4 names — this said three, which
§3.4 itself retracts). TRD-1
depends on it only through §4.3's clock: a set item is a *rendered song*, and
what clip length changes for this document is that **an item's video no longer
has a known constant fps**. 16.8312 is derived (`LTX_FPS = LTX_LEN / CHUNK`) and
LTX-2.5's own nodes default to 25. So the set has one output fps and every item
is normalised to it, which `_build_render_set_filter` already does.

**3.3 The set's stored timebase is seconds, floating point, and it is
canonical.** Media timebase is derived at render, never stored. See §4.3 for the
rounding rule and the case where audio and video disagree.

## 4. The timeline model

### 4.1 What is added to the schema

Three deltas, and nothing that duplicates a value already stored:

    -- pan is NOT here: it is an effects_json key, see 3.1
    ALTER TABLE sets      ADD COLUMN out_fps REAL           -- NULL = derive from items
    ALTER TABLE sets      ADD COLUMN mode_audience TEXT DEFAULT 'normal'   -- easy|normal|advanced

    -- One row per automation POINT. Not a blob: the decimator (§5) has to be
    -- able to delete points, and a JSON column would make that a read-modify-write
    -- of the whole curve on every mouse-up.
    CREATE TABLE IF NOT EXISTS automation (
      id INTEGER PRIMARY KEY,
      set_item_id INTEGER NOT NULL,
      lane TEXT NOT NULL,          -- 'gain_db' | 'pan' | 'lowpass_hz' | 'highpass_hz'
      t REAL NOT NULL,             -- seconds from the START OF THE ITEM, not of the set
      value REAL NOT NULL,
      curve TEXT DEFAULT 'linear'  -- linear | hold ; §5 allows no others
    );
    CREATE INDEX IF NOT EXISTS idx_automation ON automation(set_item_id, lane, t);

`t` is item-relative and that is deliberate: a set-relative time would be
invalidated by every reorder, trim and transition-length change, which is four
ways for the curve to end up describing a moment that no longer exists.

- `T1-1` Reordering a set, or changing any item's `in_secs`/`out_secs`/`secs`,
  leaves every automation row's `(lane, t, value)` unchanged. Asserted by
  reading the rows before and after, not by inspecting the reorder handler.
  **The item must carry at least one stored curve first**, and the test asserts
  the row count is non-zero before it compares: "unchanged" is otherwise
  satisfied by an empty table, and deleting the whole write path would pass.
- `T1-2` Deleting a set item deletes its automation rows. An orphan row that a
  later `set_item_id` reuse could pick up is a curve appearing on an item nobody
  drew one on. **Same non-vacuity rule**: rows must exist before the delete, or
  "no orphans" is true by construction.

### 4.2 The model is the export

- `T1-3` **An export produced through the JSON API alone, with no browser
  involved, generates the identical ffmpeg argv to one produced by pressing
  render in the UI for the same set**, and the two outputs agree on duration,
  frame count and integrated loudness. This is the criterion that fails if any
  value lives only in the DOM. *(Not byte-identity of the file: ffmpeg writes
  container metadata such as `creation_time`, so byte-comparing would fail for a
  reason that has nothing to do with where the model lives. Compare the command,
  which is what the model actually determines.)*
- `T1-4` The filter graph is **regenerated from the stored model on every
  render** and no graph string is ever cached and reused. Asserted by mutating a
  stored value and confirming the next render's graph changes. Nothing parses an
  ffmpeg string back into the model — outside review, all four models — and that
  prohibition is recorded in §12, where a rule nothing can render false belongs.

### 4.3 The clock, and what happens when audio and video disagree

Audio is sample-accurate at 48 kHz; video is frame-accurate at the set's output
fps. They do not land on the same instants and something has to give.

**The rule: seconds are canonical; audio is rendered at the exact stored second;
video rounds to the nearest whole frame at the set's output fps; the rounding is
reported, not hidden.** Nearest, not truncation, because truncation loses up to
a whole frame every time and the losses all have the same sign: at 16.8312 fps
that is 0.0594 s per join, accumulating in one direction, where nearest rounding
is bounded by 0.0297 s per join and the errors cancel. This is the same shape as
the RIFE one-frame bug that cost 2.5 s across eighty clips and failed in the
direction nobody looks (SESSIONS 16:45, session B).

- `T1-5` A transition placed at a time that is not a frame boundary renders with
  the video cut on the nearest frame and the audio crossfade at the exact
  second, and the API reports the rounding delta for that join. A delta of zero
  on a deliberately off-grid time is a failure, not a pass.
- `T1-6` The sum of |rounding delta| over a set is reported and is bounded by
  half a frame per join. A test builds a set whose joins are all off-grid and
  asserts the bound; removing the "nearest" rounding in favour of truncation
  fails it.

### 4.4 The predicted length is the rendered length

This project's oldest defect, made falsifiable. `mixer.set_duration()` already
walks the items exactly as the renderer walks them, through the same
`_check_transition_fits` guard, and already prices `effects.duration_delta()`'s
echo tail.

- `T1-7` For a set containing at least one echoing item, one `black` transition
  with a hold, one beatmatched join and one trimmed item, the value the UI shows
  and the `ffprobe` duration of the rendered file agree to within
  **`mixer.SET_DURATION_TOLERANCE` (0.05 s)**. The four features are named
  because each one has broken this prediction before. The tolerance is **one
  named constant**, imported by TRD-3 `T3-11` rather than restated: the draft had
  the literal 0.05 in two documents, and two copies of a number are free to
  drift into a check that passes while its twin fails.
- `T1-8` **The displayed length is the return value of `mixer.set_duration()`
  and no other arithmetic exists.** Verified by a differential rather than by
  grepping for the call: change `set_duration`'s result by a known offset in a
  stub and confirm the UI number moves by exactly that offset. A test that greps
  source proves the code exists, not that anything reaches it (day 4).

## 5. Automation curves

Outside review, points 3 and 6: drawing at 60 Hz produces thousands of keyframes
and a pathological filter graph, and the peaks must be decimated per zoom level.

### 5.0 Three things the code already does that this section must not duplicate

Found by reading `effects.py` and `mixer.py` during the consensus pass, and each
one would have been a second implementation of something that exists.

**(a) `effects.filter_sweep` IS automation, and it is already built.**
`effects.py:79` emits a time-varying highpass/lowpass as an `asendcmd`
staircase, capped at `SWEEP_MAX_STEPS = 200` steps of `SWEEP_STEP_S = 0.1`. A
`lowpass_hz`/`highpass_hz` automation lane capped at 64 points would be the same
feature with a different cap. **So: automation is the model, `asendcmd` is the
one emitter, and `sweep` becomes a preset that writes automation points.** One
cap, and the lanes are `gain_db`, `pan`, `lowpass_hz`, `highpass_hz` with the
last two rendering through the mechanism `filter_sweep` already uses.

**(b) Gain is in two places before this document adds a third.**
`mixer._audio_chain:652` applies `set_items.gain_db` first and then
`effects.parse_effects`'s own `gain_db` stage, which its docstring says is
"inert unless a set item's JSON explicitly asks for one". The rule, stated so
nothing silently loses: **the column is the static offset, automation is a curve
relative to it, and `effects_json.gain_db` is an alias of the column rather than
a second input.**

**(c) THE SERIOUS ONE — `loudnorm` runs LAST and would flatten every curve
drawn.** `effects.parse_effects` appends `loudnorm_filter()` at the end of the
chain, `DEFAULT_EFFECTS` has `loudnorm: True` for every item, and single-pass
`loudnorm` is a *dynamic* normaliser. Drawing a level curve and then normalising
it away is this project's oldest defect — the editor promising what the renderer
does not produce — designed in from the start, on the one feature whose entire
purpose is drawing levels.

**The rule: an item carrying a `gain_db` automation curve renders with per-item
`loudnorm` OFF, and levelling moves to the master.** The alternative — applying
automation after loudnorm — keeps per-item levelling but puts an unnormalised
stage last, which defeats the level-matching that `SETS_MIXING_PLAN.md` calls
the unglamorous one that matters most.

- `T1-9a` An item with a gain curve renders with no `loudnorm` fragment in its
  own chain, and the master stage carries one instead. Asserted on the generated
  filter graph, both halves.
- `T1-9b` **A drawn gain curve survives to the output.** Render an item with a
  curve from -12 dB to 0 dB, measure RMS per second, and assert the measured
  slope matches the drawn one within tolerance. With per-item loudnorm left on,
  this fails — which is the whole reason it is written down.

### 5.1 Interpolation and decimation

**Interpolation is linear between points, `hold` is a step, and no other curve
type exists.** Not because curves are undesirable but because ffmpeg's
`volume`/`pan` expressions have to be able to express what is drawn, and every
shape that is drawable but not expressible is another way for the editor to
promise what the renderer will not produce.

**Decimation happens on the server, on write.** The client may post whatever the
mouse produced; the stored curve is the decimated one, and the client re-reads
what was stored. Rule: Ramer–Douglas–Peucker with a per-lane epsilon
(`gain_db` 0.25 dB, `pan` 0.02, filter frequencies 2% of the value), then a hard
cap of 64 points per lane per item — **built as `automation.MAX_POINTS`**, not
the `AUTOMATION_MAX_POINTS` this document named — taking the highest-
error points first.

- `T1-9c` Posting 3000 points from a 60 Hz drag stores at most 64, and the stored
  curve's value at 100 sampled times is within the lane's epsilon of the raw
  curve at the same times. Both halves are needed: the cap alone would pass with
  a curve that keeps the first 64 points and throws the shape away.
- `T1-10` The generated filter expression for a fully-populated lane is under
  8 KB and renders. A cap that produces a string ffmpeg refuses is not a cap.
- `T1-11` A curve with two points at the same `t` is refused at the API, naming
  the time. Two values at one instant have no defined render.
- `T1-12` **An automation lane that is drawn but does not change the render is a
  failure.** Per lane, a differential: render the item with the curve and with
  it flat, and assert the measured output differs — `gain_db` by RMS per second,
  `pan` by the L/R energy ratio, the filter lanes by band energy. This is the
  criterion that catches a lane wired into the UI and not into the graph, which
  is exactly how `_apply_beatmatch` was unreachable for a whole session.

## 6. Waveform, peaks and playback

### 6.1 Peaks are precomputed and decimated, and they are not the render

`mixer.waveform_png()` renders a PNG and that stays for the static case. The
timeline needs numbers, not a picture, because the regions have to be draggable.

- Peaks are computed once per song, on the existing `analyse` job (`analyse.py`
  already decodes the file — do not decode it twice), stored beside the song as
  a binary min/max array at a base resolution, and served decimated.
- **That decode is mono at 22050 Hz** (`librosa.load(mp3_path, mono=True)`,
  default sr, chosen because it matched the measured tempo and halved load
  time). Adequate for an envelope; it is **not** adequate for a stereo waveform
  or for anything claiming to show clipping. A per-channel waveform is a second
  decode and has to be asked for deliberately, not assumed to be free.
- `T1-13` A request for zoom level *z* returns at most `PEAKS_MAX_POINTS` (2048)
  pairs regardless of song length, **and at least one pair for a song that has
  audio**. Bounded above only, `return []` passes — and it takes `T1-14` with
  it, because "the decimated envelope equals the full-resolution min/max" is
  vacuously true over zero buckets. Both halves or neither. A 60-minute set must
  not decode in the browser (outside review, point 6).
- `T1-14` The decimated envelope's per-bucket min/max equals the full-resolution
  min/max over the same span, exactly — decimation is a max/min reduce, not a
  resample. A waveform that under-reports a peak is a waveform that lies about
  where the loud part is.
- `T1-15` Peaks for a song with no audio return an explicit empty result with a
  reason, not a flat line. A flat line is indistinguishable from silence.

### 6.2 Playback is a proxy and says so

- `T1-16` **The preview endpoint's own response says it is a proxy and lists
  what it does not apply** — `{"is_proxy": true, "not_applied": [...]}` — so the
  warning is data every client carries rather than a sentence typed into one
  template that a mobile client will not have. Asserted by adding an effect to
  an item and confirming it appears in `not_applied`; a static list fails that.
  **No second DSP engine in Web Audio** (outside review): the browser plays the
  source files with gain and position applied; it does not attempt to mirror the
  ffmpeg effect chain.
- `T1-17` A "render preview" action produces a real ffmpeg render of a bounded
  span (default 20 s around the playhead) through the same code path as the full
  render, and is the only preview that claims to be accurate. Asserted by
  rendering the same span twice — once via preview, once by rendering the whole
  set and cutting that span — and comparing measured loudness and duration.

## 7. Three audiences, one data model

Decided 2026-08-12 by Jon, against two of four external models: easy / normal /
advanced are **audiences, not densities**. One data model, one editor, three
affordance sets. **Easy is a feature set, not a CSS class** — "solve it for me"
requires real automation that the other modes expose as individual controls.

| audience | what it is |
|---|---|
| easy | auto-level, auto-fade, one-button master. No lanes drawn by hand. |
| normal | every control the model has, with context, defaults visible |
| advanced | the same plus the mastering chain, and the numbers unrounded |

- `T1-18` **Easy mode changes the output, measurably.** Same set, same items,
  easy on and off, nothing else touched: the rendered integrated loudness under
  easy lands within 1.0 LU of `effects.LOUDNORM_I` (-16 LUFS), and the same set
  with easy off and its per-item defaults cleared does not. A criterion that
  cannot separate the two modes would confirm easy is a stylesheet.
- `T1-19` One-button master is a named, versioned chain, not a hidden set of
  values: what it applied is recorded on the render and is readable afterwards —
  **and the recorded chain is the one that ran**, asserted by changing a
  parameter and measuring the output move. Recording metadata while performing no
  mastering satisfies "readable afterwards".
  A user who cannot see what the button did cannot learn from it, which is
  normal mode's stated purpose.
- `T1-20` Switching audience never changes stored values. Round-trip
  easy → advanced → easy and assert every `set_items` column and every
  automation row is unchanged — **after asserting the switch DID something**:
  `mode_audience` must read back as what was set, or deleting audience switching
  entirely leaves every column trivially unchanged and this passes.
  **Paired with an assertion that the audiences differ at all** — that the affordance set returned for easy is not the one
  returned for advanced. Alone this criterion passes when the mode switch is a
  no-op, which is the "easy is a CSS class" outcome §7 exists to refuse.

## 8. The join graph: `duck` and `layer`

The two known gaps, and `SETS_MIXING_PLAN.md` is explicit about why neither is
another filter fragment: both are per-TRANSITION effects that were filed as
per-ITEM ones.

- `duck` — `sidechaincompress` needs a second input. At the join both streams
  exist, but `running_a` is the ACCUMULATED chain and is not time-aligned with
  `nxt_a` before the `acrossfade`. Needs `adelay` + `asplit`.
- `layer` — `xfade` has no blend modes, so a screen/overlay/difference blend
  across the overlap means trimming the overlap from both streams, blending, and
  splicing back.

**Build `layer` first**: video has no time-alignment problem because `xfade`
already positions both streams. That ordering is `SETS_MIXING_PLAN.md`'s and it
is right.

- `T1-21` A `duck` join renders with the outgoing item's level reduced by at
  least the requested amount during the overlap and restored after it, measured
  as RMS per second across the join. Requesting a duck and getting no level
  change is today's behaviour dressed up.
- `T1-22` A `layer` join renders with both items' frames present during the
  overlap, asserted by a pixel-difference against each source separately — the
  blend must differ from both, not just from one.
- `T1-23` Both remain refused with a message naming the reason at **every**
  entry point until they render, as they are today. An effect accepted and
  silently ignored is the defect this whole document is about.

## 8a. The master stage

Named here because §5.0(c) sends levelling to "the master" and §7's easy mode
promises a "one-button master", and **no section said what the master IS**. An
independent review found it: two features route work to a stage this document
never specified.

The master is **one chain applied to the assembled set, after every item and
every join**, in a fixed order: sum → (optional) master EQ → limiter → single
`loudnorm` → export. Fixed, not configurable, because the whole point is that
per-item levelling can be switched off without the set losing its level.

- `T1-20a` There is exactly ONE `loudnorm` in a rendered set's filter graph when
  any item carries a gain curve: none on that item, one at the master. Asserted
  on the generated graph by counting, both halves.
- `T1-20b` A set whose items all keep per-item loudnorm renders with NO master
  loudnorm, so today's behaviour is unchanged for every set that does not draw a
  curve. The master appears because something asked for it, not by default.
- `T1-20c` Easy mode's one-button master is this same chain with recorded
  parameters (`T1-19`), not a second implementation of it. **Asserted by a
  differential**: render one set through easy and one through the master directly
  and compare measured loudness and true peak. Identity claimed in prose is
  satisfied by a parallel implementation, or by recording metadata over a no-op.
- `T1-20d` **EXACTLY ONE `loudnorm` in the graph, always.** Easy mode engages the
  master while per-item `loudnorm` is stripped only for an item carrying a gain
  curve — so easy-on with no curves puts one on every item AND one at the master.
  Two normalisers in series is not twice the levelling, it is the second working
  against the first. Engaging the master strips per-item `loudnorm` from every
  item, not only curved ones. *Found by review; the text permitted the double.*

## 8b. The interstitial card

**Folded in 2026-08-13 from `docs/ALBUM_ARC_AND_STAGING_PLAN.md` *(absorbed and removed 2026-08-13; in git history)* §3, which no
TRD owned.** Its two siblings in that plan are already built — fade-to-black is
a transition kind in `mixer.py`, and the branding overlay has its `brand_path`
columns and its renderer — and only this one is unbuilt and unclaimed. It is a
timeline feature, so it is TRD-1's.

A title or branding card as **its own timeline item, with its own duration**:

    [song A][ MEOW P — 3s ][song B]

The plan's reasoning is right and is kept: this is *"a beat in the running
order, not a decoration on one"*, and **it changes set length**, so it goes
through `set_duration()` and both render paths as a first-class item — a
`set_items` row whose `song_id` is NULL, carrying an image path and a duration.

That nullable `song_id` is the only schema wrinkle, and the plan argues for it
correctly: **the alternative is a parallel list of "things between songs" that
every length calculation has to learn about separately** — which is a second
place that computes set length, forbidden by §12.

- `T1-27` A set containing a card renders it, and **`mixer.set_duration()`
  prices it**: the predicted length includes the card's duration and matches the
  rendered file within `SET_DURATION_TOLERANCE`. A card that renders but is not
  priced is the oldest defect in this document arriving through a new item type.
- `T1-28` A card is a `set_items` row with `song_id` NULL, and **every path that
  walks items tolerates it** — reorder, trim, transition, automation lanes, and
  the export. Asserted by putting a card first, last, and between two beatmatched
  songs; the join arithmetic must not assume a neighbouring song exists.

## 9. Export

- `T1-24` **Adding an export format is a row, not a code change.** The format
  list is a table of ffmpeg parameter sets; asserted by adding a test-only row
  and rendering through it with no other edit. Codec parameters are passed to
  ffmpeg and there is no custom encoder or muxer (outside review) — that
  prohibition lives in §12.
- `T1-25` An export names its measured integrated loudness and true peak in the
  asset row. `effects.loudnorm_filter()` targets -16 LUFS / -1.5 dBTP; a render
  that lands outside a stated tolerance of its own target is flagged rather than
  silently shipped. **Both halves are asserted**: an in-tolerance render records
  its numbers and is NOT flagged, and a deliberately out-of-tolerance one IS.
  Writing numbers and never flagging satisfies the first half alone.
  **The measurement lives in `effects.py`, beside `LOUDNORM_I` and
  `loudnorm_filter()` that already own those numbers, and TRD-3 §4.3 calls it.**
  Naming the owner matters: the draft had TRD-1 pointing at TRD-3 and TRD-3
  pointing back, which is how a thing said to be measured once ends up measured
  twice by two people who each read the other document.
- `T1-26` Re-rendering a set writes a NEW file beside the old one and never
  replaces it, exactly as anchors and refs behave. Asserted by rendering twice
  and finding both files and both asset rows — **and by both being REACHABLE**:
  the older render is listed and selectable, or "keeps history" means files
  accumulating on disk that nothing can reach.

## 10. Backend / front-end separation

**INHERITED from TRD-6 §0.1** (`T6-A1`…`T6-A4`) — the four rules were restated
here, in TRD-2 and in TRD-3 in near-identical words, twelve criteria for four
facts. They are not repeated; what follows is only what is specific to the
timeline, which is the feature most exposed to them.


**This is a requirement, not a nicety**, and TRD-1 is the document most exposed
to it: the timeline is the most presentation-shaped feature in the studio, and
it is the one that must survive a mobile client being written against the same
API.

The studio today is FastAPI + Jinja2 + htmx with logic and presentation
interleaved. `app.py:5875`'s `render_set_route` is the concrete example (this said 5711,
which is `add_set_item` — an audit caught it; the description was right and the
line number was not): it reads the
items, joins the songs, decides which path (audio vs video), builds every item
dict, and enqueues — all inside the route handler, all unreachable from any
client that is not this HTML page.

The service module for this document is `sets_service.py` or its equivalent.
`T6-A1`'s named loop here: a set from empty to rendered over JSON alone.

## 11. What TRD-1 does not own

Named explicitly so the cross-TRD review has boundaries to check rather than
guess at:

- **The render queue and the wait-state scheduler — now `docs/TRD-6`.** It was
  disowned here, disowned by TRD-3 §9, and only narrowly owned by TRD-2 `T2-11`,
  which two independent reviews both flagged: a dependency three documents
  disown is one nobody builds. Decided 2026-08-12: when a
  resource frees it takes the next queued item that matches it; no timing match,
  no forecast fan-out; "ready" is expressed separately from "queued" so a chained
  clip is not handed out before the frame it needs exists. That model is
  cross-cutting — clips, refs, audio, and TRD-3's repairs all enqueue — and it
  needs its own specification. TRD-1 enqueues one `render_set` job and depends on
  nothing else in it.
- **The song-level audio editor and the media menu.** Deferred; they share this
  timeline model, which is why they come after this document and not with it.
- **Clip length, storyboards, scenes.** TRD-2.
- **Ongoing QC of stored artefacts.** TRD-3. **Not** "any check on the rendered
  output", which is what this line said until an independent review pointed out
  that seven of TRD-1's own criteria measure rendered output — `T1-3`, `T1-9b`,
  `T1-12`, `T1-17`, `T1-18`, `T1-21` and `T1-25` — and that the rule as written
  forbade the very differentials that make them able to fail.

  The real split: **TRD-1 measures its own render to prove the feature works;
  TRD-3 measures artefacts to find out when one has stopped working.** A drawn
  gain curve reaching the audio (`T1-9b`) is an acceptance test for automation.
  A clip being the length its workflow asked for is QC. Both are measurements of
  a rendered file and they are not the same job.

  **They share three things, not one**, and the "one place they touch"
  claim here was wrong: §9's loudness (`effects.measure_loudness`, TRD-3 §4.3
  calls it), the set-duration tolerance (`mixer.SET_DURATION_TOLERANCE`,
  `T1-7` and `T3-11`), and the handover times (`mixer.transition_times`,
  TRD-3 `T3-12` — QC measures the rendered file against that model, within
  half a frame). Each is one implementation with two callers.

## 12. Explicitly not building

From outside review, where two or more agreed independently, plus this project's
own history:

- No second DSP engine in Web Audio mirroring ffmpeg effects for preview.
- Never parse ffmpeg back into JSON — one way only, model → graph.
- No custom encoders or muxers.
- No `ffmpeg-python`: 11k stars, **last push 2024-08-04**, and it solves a
  problem `mixer.py` already solved. Read it, do not adopt it.
- No collaborative or multiplayer timeline.
- No `gl-transitions` — it needs a custom ffmpeg build and `xfade` already ships
  more than 50.
- No second place that computes set length. `mixer.set_duration()` is the one.

## 13. How every criterion above is to be verified

The rules this project arrived at by being wrong, applied to this document:

1. **A measurement that cannot fail is not evidence.** Every criterion above is
   a differential — one variable changed, an expected direction — or it names
   the mutation that must break it.
2. **Then mutate the code and watch the check fail.** Three of one session's own
   checks measured nothing on 2026-08-12 and only mutation found them: an
   `aspectralstats` reading that returned 0.0 behind an `if`, a 999-second span
   caught by the wrong bound, and a `demo()` branch never reached.
3. **Never replace a slice that runs to the end of a file**, and check
   `grep -c "^def test_"` before and after. A deleted test does not fail.
4. Baseline before and after: `cd studio && python3 -m pytest -q .` (the count is
   deliberately NOT written down here -- it was copied into three documents and
   all three went stale; green before and after is the requirement), `python3 check_integration.py`, `python3 mixer.py`.

5. **A REFUSAL or a PRESENCE is half a criterion.** Found by a second
   independent reviewer, and it is systematic rather than incidental: a
   criterion of the form "X is refused" or "the payload carries Y" stays green
   when the whole feature is DELETED, because a feature that does not exist
   refuses everything and a field nobody reads is still present. Every such
   criterion is paired with a positive case that exercises the feature, or it is
   marked **provisional** and says what it cannot yet distinguish.

   One-sided in this document today, listed so nobody has to re-derive it:
   `T1-4` and `T1-24` (prohibitions restated as differentials, but the differential proves the mechanism, not that anything uses it) and `T1-23`, which stays green for as long as `duck` and `layer` are never built.

### The positive half of each one-sided criterion

Naming them was not pairing them. Each row is the case that must ALSO pass, so
the criterion stops being satisfied by the feature's absence.

| criterion | its positive half |
|---|---|
| `T1-4` no cached graph | mutate a stored value and assert the regenerated graph CHANGES — proves regeneration happens, not merely that no cache exists |
| `T1-23` `duck`/`layer` refused everywhere | when either ships, the same fixture must RENDER and be measured (`T1-21`, `T1-22`). Until then this certifies only that nothing is silently accepted, and says so |
| `T1-24` a format is a row | add a test-only row and RENDER through it; asserting the table is a table proves nothing reaches ffmpeg |


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
| `T1-1` reorder/trim keep automation | **built** | this slice | stored `(lane, t, value)` read before and after `POST /sets/{id}/reorder` and `POST /sets/{id}/items/{item_id}` (`in_secs`/`out_secs`/`secs`). Rows exist before the compare; the reorder/trim itself lands. Empty table is not the check. `studio/test_t1_1_reorder_keeps_automation.py` |
| `T1-3` JSON export argv = UI render argv | **built** | this slice | `studio/test_t1_3_json_export_argv.py`: JSON `POST /api/sets/{id}/render` and UI `POST /sets/{id}/render` of the same stored set produce identical `mixer.render_set_argv`. Extra form fields on the UI POST are ignored. Two encodes agree on duration (`SET_DURATION_TOLERANCE`), frame count and integrated loudness (≤1.0 LU). Compare the command, not file bytes. |
| `T1-4` no cached graph | **built** | this slice | `studio/test_t1_4_no_cached_graph.py`: stored `gain_db` −6 → −3; next `mixer.render_set_graph` from `_set_render_items` CHANGES (`volume=-6.000dB` gone, `volume=-3.000dB` present). A reused ffmpeg string stays put. |
| `T1-9a`/`T1-9c` automation curves | **built** | earlier | `automation.py`: lanes, RDP decimation, `MAX_POINTS = 64`, `asendcmd` emission through the mechanism `effects.filter_sweep` already used |
| `T1-9b` a drawn curve survives to output | **built** | this slice | `studio/test_t1_9b_gain_curve.py`: 6 s 1 kHz sine (constant amplitude — RMS is not a proxy on program material), stored `gain_db` ramp −12→0 dB, `mix_audio` RMS/s slope vs drawn 2.0 dB/s within `mixer.GAIN_CURVE_SLOPE_TOLERANCE` (0.5). Per-item loudnorm left on measures ~1.06 dB/s and misses the same bound. Asserted through `mix_audio`, not `_audio_chain`. |
| `T1-10` full-lane filter expression under 8 KB and renders | **built** | this slice | `studio/test_t1_10_filter_expr.py`: `MAX_POINTS` zigzag over 1800 s on `gain_db` / `lowpass_hz` / `highpass_hz`; `fragment` ≤ `FILTER_EXPR_MAX_BYTES` (8192); `mix_audio` writes a file. A longer string or a refused graph fails. |
| `T1-11` two points at the same `t` refused | **built** | this slice | `studio/test_t1_11_same_t.py`: POST `/api/sets/{id}/items/{iid}/automation/{lane}` with two `gain_db` points at `t=2.25` is 400 and the body names `t=2.25`. Nothing is stored. `automation.save` already refused; the route now surfaces it. |
| `T1-12` a drawn lane changes the render | **built** | this slice | `studio/test_t1_12_lane_changes_render.py`: same item through `mix_audio` with the curve and with it flat. `pan` 0→+1 on a 1 kHz sine: `lr_energy_ratio` L/(L+R) drops by ≥ `LR_ENERGY_DELTA` (0.08). `lowpass_hz` 400 Hz / `highpass_hz` 4 kHz on a 200+8000 Hz tone: attenuated-band `band_energy` ratio ≥ `BAND_ENERGY_RATIO` (4). `gain_db` stays T1-9b. |
| `T1-20a`/`T1-20b` master stage | **built** | earlier | `mixer._master_lines`, engaged when an item suppressed its own loudnorm or the set is easy |
| `T1-20d` exactly one loudnorm per path | **built** | `2f8e559` | mixed set measured `per-item=[0,0] master=1` → worst path **1**, was **2**. Reproduced independently by both sessions. Fix is `master_engaged` + `item_chains`, one application point |
| `T1-6` sum of \|rounding delta\| bounded by half a frame per join | **built** | this slice | `studio/test_t1_6_rounding_bound.py`: off-grid set at 16.8312 fps, `mixer.rounding_report` `abs_delta_sum` ≤ `n * 0.5/fps`; each join delta ≠ 0; truncation of the same times exceeds the bound. `GET /api/sets/{id}` carries `rounding.joins[].delta` and `rounding.abs_delta_sum`. No render. |
| `T1-7` predicted length = rendered (echo+black+beatmatch+trim) | **built** | this tree | `studio/test_t1_7_set_duration.py`: mix_audio gap 0.032 s, render_set gap 0.027 s, both ≤ `mixer.SET_DURATION_TOLERANCE` (0.05). Each named feature moves the prediction. Arithmetic and the constant were not changed. Artefact-side twin is TRD-3 `T3-11` (`test_t3_11_set_duration.py`). |
| `T1-8` displayed length is `set_duration()` | **built** | this slice | `studio/test_t1_8_displayed_length.py`: stub 125s → UI `2:05`; stub +17s → UI `2:22`. Displayed HMS is `hms(set_duration())`; extra +1s arithmetic turns the check red. |
| `T1-27`/`T1-28` interstitial card | **built** | this slice | `mixer.is_card` + `card_secs` priced by `set_duration`; inserting a 3s card adds 3s, omitting it does not. `set_items.song_id` NULL. mix_audio/render_set match prediction within `SET_DURATION_TOLERANCE`. Card first/last/between beatmatched songs. HTTP POST `/sets/{id}/cards` writes the row — a comment in `set_edit.html` cannot. |
| `T1-13`/`T1-14` peaks as data | **built** | this slice | `mixer.peaks(samples, z)` returns ≤2048 min/max pairs, ≥1 when audio exists; per-bucket min/max equals the full-resolution span. `studio/test_timeline.py` |
| `T1-15` empty reason | **built** | this slice | `mixer.peaks_from_path` / `GET /api/songs/{id}/peaks` return `{pairs: [], reason}` (`no_audio` / `missing` / `unreadable`) when there is nothing to draw. A zero-length envelope with no reason fails. Silence stays a flat line. `studio/test_timeline.py` |
| `T1-16` proxy preview | **built** | this slice | `GET /api/sets/{id}/preview` returns `{is_proxy: true, not_applied}` from `mixer.preview_proxy`. Adding `echo_out` lists it; unused keys stay off; gain/pan are applied so they are not listed. A static catalogue fails. `studio/test_t1_16_preview.py` |
| `T1-17` render preview | **built** | this slice | `mixer.render_preview` cuts a bounded span (default `PREVIEW_SPAN` 20 s around the playhead) from the same `mix_audio`/`render_set` path as the full render. `GET /api/sets/{id}/preview/render?at=&secs=` returns `{is_proxy: false, start, end, secs, duration, path}`. Same span via preview vs full-then-cut agrees on loudness (≤1.0 LU) and duration (`SET_DURATION_TOLERANCE`). `mixer.waveform_png()` stays the picture. `studio/test_t1_17_render_preview.py` |
| `T1-18` easy changes output | **built** | this slice | same items, defaults cleared: easy mix lands within 1.0 LU of `effects.LOUDNORM_I`; easy-off does not. Graph half: easy engages `master_engaged` / `_master_lines`, one loudnorm. `studio/test_t1_18_audience.py` |
| `T1-19` recorded one-button chain | **built** | this slice | `mixer.one_button_master` is `one-button-master` v1; `_master_lines` applies its I/TP/LRA; `h_render_set` writes it to `assets.meta_json` only when the master ran. Changing I from -16 to -23 moves measured LUFS. `studio/test_t1_19_master_chain.py` |
| `T1-25` export names I/TP | **built** | this slice | `effects.export_loudness` measures via `measure_loudness` and flags outside `LOUDNESS_TOLERANCE_LU` / `TRUE_PEAK_TOLERANCE_DB` of its own target. `mixer.export_loudness` picks the master chain's I/TP when it ran. `h_render_set` writes `assets.meta_json.loudness`. In-tolerance is not flagged; a hot no-loudnorm mix is. `studio/test_t1_25_export_loudness.py` |
| `T1-24` a format is a row | **built** | this slice | `mixer.EXPORT_FORMATS` is the encode argv; `render_set(..., fmt=)` looks up the row. A test-only row (`mpeg4` + `libmp3lame` + `comment=t1-24-row`) is inserted and rendered; `_run_ffmpeg` received those tokens and the file is mpeg4/mp3 with that comment. Asserting the table exists is not the check. `studio/test_t1_24_export_format_row.py` |
| `T1-20` switch does not mutate | **built** | this slice | `sets.mode_audience` persists; easy→advanced→easy leaves `set_items` and `automation` unchanged; `audience_affordances("easy") != audience_affordances("advanced")`; easy HTML omits gain/effects controls |
| `T1-21`…`T1-23` `duck`/`layer` | **built (ledger was stale)** | mixer joins | `_duck_join` / `_layer_join` render. `T1-23` "refused" is no longer the tree |
| the timeline itself | **built** | this slice | `studio/test_t1_timeline.py`: axis last `.tl-tick[data-t]` tracks stubbed `set_duration()` (125 → 142). `.tl-join[data-t]` is overlap start (`_advance`); POST `/join` secs 2→4 moves it 2s and does not wipe gain. `.tl-playhead` tracks `?at=` and clamps to duration. `.tl-lane-pt` is the stored curve on the set axis; easy omits `.tl-lanes` and leaves the rows. TestClient, no JS. Forms remain. |
