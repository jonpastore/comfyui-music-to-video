# UI/UX definition and style guide

Status: written 2026-08-13. Covers the whole studio front end, not one feature.
Consulted: chatgpt (see §7 for what was folded in and what was rejected).
Companion documents: `docs/PRD-1-3-EDITING-AND-QUALITY.md`,
`docs/DDD-1-3-EDITING-AND-QUALITY.md`.

**Every number below was counted from the tree at `f9ca597`.** The commands are
named so a claim can be re-run rather than believed, and two things that looked
like findings were counted and are not — they are in §2.4 under "already good",
because a style guide that lists a discipline the code already has as a defect
is a document nobody trusts twice.

---

## 1. What this interface is

A single operator, on a tailnet, judging media. Songs in, music videos out, with
character anchor sheets, storyboards, reference frames, clips, sets and a job
queue across a fleet of GPU boxes.

Three facts about the domain decide almost every rule below:

1. **The media is the content and the interface is the frame around it.** The
   operator's real work is looking at an image or a clip and deciding whether it
   is right. The identity collapse, the world that never rendered and the LoRA
   that did nothing were all found by opening the picture — never by a check.
2. **Actions cost GPU minutes to hours.** "What is about to happen, on which box,
   and what will it cost" is a first-class part of every control, not a
   confirmation dialog.
3. **The front end is disposable and the API is not.** `T6-A1`…`T6-A4` require
   every operation to be reachable over JSON so a different front end, including
   mobile, can be built against the same API. **No rule in this guide may depend
   on the server rendering HTML.** A template that computes anything is already a
   violation (`T6-A4`).

## 2. What is there today

### 2.1 The material

| | measured |
|---|---|
| `static/style.css` | 1247 lines |
| `static/app.js` | 1589 lines, hand-written, 55 `addEventListener` |
| `templates/` | 29 files, 3481 lines |
| routes | 138, of which **25** are `/api/*` JSON. `T6-A1` named loops complete: set empty→rendered, storyboard, review queue. `/queue` answers JSON with the same numbers the fragment prints (`T6-A2`) |

### 2.2 The root finding: tokens exist for colour, and for nothing else

`:root` carries nine colour tokens, two elevation tokens, a motion duration and
an easing curve — **and they carry their reasoning in the file**: `--border` at
1.39:1 against `--bg` was measured, found to fail WCAG 1.4.11's 3:1 for non-text
boundaries, and split into `--divider` (recede) and `--border-strong` (3.51:1).
That is a design system's worth of care applied to one axis.

Type, space and radius got none of it:

    font-size values     14 distinct    0.66 0.7 0.72 0.75 0.78 0.8 0.85 0.9 0.95 1 1.15 1.2 1.35 1.6 rem
    spacing values       18 distinct    0.1 0.15 0.2 0.25 0.3 0.35 0.4 0.45 0.5 0.6 0.75 0.9 1 1.2 1.25 1.5 2 rem, 4px
    border-radius        6 distinct     3px 4px 5px 6px 8px 999px (+ 50%)

0.72rem, 0.75rem and 0.78rem are three sizes doing one job. This is the single
highest-impact thing to fix, because it is the cause of §2.3 rather than a
sibling of it: with no scale to reach for, every new page invents its own values,
and once a page has its own values it needs its own section.

### 2.3 The front end is organised by PAGE, not by COMPONENT — in both files

`style.css`'s own section headings, in file order, include: *storyboard
direction*, *refs tier*, *storyboard page*, *cast*, *approve grid*, *models
page*, *tiers*, *anchor candidates*, *album look / cast*, *modals*, *anchors*,
*tier table*, *sets shelf*, *publishing config*. Roughly twenty page-scoped
blocks.

`app.js` is the same shape: `initAnchorPrompts`, `initAnchorPlan`,
`initAnchorBatch`, `initAnchors`, `initRunHistory`, `initJobForms`,
`initLibraryBulk`.

**And yet the component system already exists — it is just unnamed.** Counting
class use across all templates:

    90 muted   78 hint   53 tag   41 card   36 field-row   33 stack-form
    23 empty   19 secondary   18 warn-tag   16 check   15 num   15 meta
    14 warn    14 label-text   12 list   12 btn-sm   11 linkish   11 danger

Those are the components. `card`, `field-row`, `stack-form`, `tag`/`warn-tag`,
`hint`/`muted`, `empty`, `num`/`meta` cover the whole interface, and each of the
twenty page sections is mostly a local re-specification of one of them.

### 2.4 Already good — do not "polish" these away

Counted, because each of them looked like a defect until it was measured:

- **`!important` appears once** in 1247 lines.
- **10 inline `style=` attributes** in 3481 lines of template.
- **`prefers-reduced-motion` is honoured** in two places, and motion is already
  tokenised (`--motion-standard`, `--motion-easing`).
- **Native elements are used where they work**: `<dialog>` for the contact-sheet
  viewer (so Esc closes it, and the browser owns the backdrop), `<details>` for
  collapsible playlist cards.

### 2.5 The five real defects

Ranked by impact.

1. **No type/space/radius scale.** §2.2. Cause of §2.3.
2. **Keyboard focus is essentially unhandled: 2 `:focus-visible` rules in 1247
   lines.** In an application whose primary act is stepping through images and
   judging them — with a keyboard-navigated dialog already built — this is the
   accessibility basic that is not optional and not a polish item.
3. **The queue is bolted to the top of every page.** `base.html` htmx-loads
   `/queue` on load and it then polls itself, on nearly every page; `/jobs` has
   to switch it off with an empty block because two pollers on one page is one
   too many. Presence-on-every-page is right; a block of page content that
   pushes the work down is not (§5.5).
4. **The layout is a 1200px text document, and the content is media.** `main`
   is `max-width: 1200px` with 1.5rem padding, so a contact sheet, an anchor
   grid and a set timeline are all poured into a column sized for prose.
5. **The nav does not match the agreed order and carries an extra item.**
   `base.html` has *Library, Anchors, Playlists, Sets, Tiers, Models, Jobs,
   Config*. TRD-2 §7's agreed order is *Library → Playlists → Anchors → Sets →
   Jobs → Tiers → Config* — make-things first, then machinery — and does not
   include Models. One of the two is stale and §5.1 says which.

Three breakpoints exist (`860px`, `900px`, `46rem`) in two units, which is not a
responsive strategy; §5.6.

## 3. Principles

Six, and they are the tie-breakers when two rules below disagree.

1. **The media is the content.** Chrome recedes. Anything that is not the
   picture gives up space to the picture.
2. **Say the cost before the click.** Every control that spends GPU time names
   what it will do and where. This is a design requirement because the studio's
   own history is jobs that ran for an hour and produced nothing.
3. **A warning stays on the page.** Day 8's standing rule. Help goes behind a
   `?`; a footgun does not. The API marks which strings are warnings and which
   are notes (`T2-36`) precisely so a client cannot hide the wrong one.
4. **One state vocabulary, one visual language.** The six states `jobs.py`
   writes, plus "candidate awaiting a human", are what this studio actually has.
   A chip, a row border, a button and a QC verdict all speak them the same way
   (§5.5).
5. **Never promise what the renderer will not produce.** The interface rule
   version of the project's oldest defect: a preview says it is a proxy
   (`T1-16`: `GET /api/sets/{id}/preview` returns `{is_proxy, not_applied}` so
   the warning is data, not a sentence in one template), a 20 s ffmpeg
   render preview is the one that claims accuracy (`T1-17`:
   `GET /api/sets/{id}/preview/render?at=&secs=` returns `{is_proxy: false}`
   and is not the waveform picture), an estimated length says it is
   estimated, and a control that cannot act is absent or
   disabled-with-a-reason, never present and inert. Pressing Render
   and `POST /api/sets/{id}/render` produce the same ffmpeg argv
   (`T1-3`); a value that lives only in the form is not in the export.
6. **Nothing in the presentation may be load-bearing.** If deleting the
   stylesheet loses information, the information was in the wrong place.

## 4. Component inventory

The system that already exists, named, plus what the roadmap adds. Every page
section in §2.3 collapses into one of these or is deleted. Two of the four
components the roadmap seemed to need turned out to exist already — which is the
reason this section was written by reading the stylesheet rather than the TRDs.

**Primitives** — `card`, `stack-form`, `field-row`, `button-row`, `tag`
(+`warn-tag`), `hint`, `muted`, `meta`, `num`, `empty`, `check`, `label-text`,
`linkish`, `list`.

**Composites** — `media-tile` (image/clip + its controls + its verdict, one
component behind `_clip_tile.html`, the anchor grid, the approve grid and the
refs grid, which are four re-specifications of it today); `section-head` (title
+ its own actions); `modal` (on `<dialog>`); `queue-strip` (§5.5);
`field-with-wand` (label + AI action + hint + control, the album-profile shape);
`finding-row` (`_finding_row.html` on `GET /qc` and the song QC card:
measured / expected / unit / editable remedy / approve, `T3-19`).

**`plan-panel` is the most under-used component in the studio.** `.plan-panel` /
`.plan-line` / `.plan-blocker` / `.plan-note` plus `button.blocked` already
exist — *"what the form will do, before you press it"* — and they are used by
**one template, `_anchor_form.html`**. Its comment states the principle the
whole application needs: *"the Generate button is MARKED, never disabled — a
control that cannot apply still has to say why, and the reason is in the panel
above it."* Principle 2 is this component. Every control that spends GPU time
gets one (§5.5).

**The timeline exists and is not yet the DAW.** `.timeline` / `.tl-block`
are built and used by `set_edit.html`, and the good part is already right:
blocks are flex-sized by how long each item actually **plays after trim**, so
the picture matches the render rather than being decorative, and the handover
marker sits on the trailing edge where the overlap really happens. A title
card is a block like any other (`T1-27`/`T1-28`): it is labelled MEOW P, sized
by `card_secs`, and it is a `set_items` row, not a comment on the strip.
The **time axis** is server-rendered: `mixer.timeline_axis(set_duration())`
emits `.tl-tick[data-t]` seconds in the HTML (T1-8's stub-offset shape).
A rendered set is QC'd against that same number (`T3-11`): `qc.check_set`
PASSes when `ffprobe` duration sits within `mixer.SET_DURATION_TOLERANCE`,
REJECTs when it does not. Measurement, not a new widget — the finding is
the existing QC row (`measured` / `expected` / `s`).
Joins, playhead and lanes are the same view: `.tl-join[data-t]` (drag POSTs
`secs` only), `.tl-playhead` (`?at=`), `.tl-lane-pt` (stored curve, set-relative
`t`). Easy omits the lane strip. Waveform is still a PNG. Forms remain.
A stored `gain_db` ramp does reach the rendered file (`T1-9b`, RMS/s
slope on `mix_audio`); a fully-populated lane's filter text stays under
8 KB and still renders (`T1-10`).
Dragging the running order or a trim (`in_secs`/`out_secs`/`secs`)
must leave every stored point's `(lane, t, value)` put (`T1-1`):
`t` is from the start of the item, not the set, so the curve does
not slide when the block moves.
Two points posted at the same `t` are refused by name (`T1-11`), so a
lane editor can show the instant rather than a generic save failure.

**Three audiences, one editor.** `set_edit.html` now carries a
`mode_audience` select (`easy|normal|advanced`). These are affordance
sets, not densities: easy *omits* gain, effects JSON and automation
controls from the HTML (hidden inputs keep stored values so a later
Save cannot wipe them) and names the one-button master
(`one-button-master` v1); advanced *adds*
the mastering-chain numbers and unrounded steps. Switching the select
writes only `sets.mode_audience`. A CSS class that hid the same fields
would fail `T1-18` — easy changes the mix. After an easy render the
card shows the named chain that ran (`T1-19`), not a hidden set of
values. After any render the same card names measured integrated
loudness and true peak (`T1-25`); an off-target file is marked
"off target" rather than silently shipped. That is the asset row,
not the live `meter`.

The waveform is the part that must change rather than grow: today it is
`mixer.waveform_png()` set as a `background-image` on the block. `mixer.peaks`
now returns the decimated min/max pairs (`T1-13`/`T1-14`);
`GET /api/songs/{id}/peaks` adds `reason` when there is nothing to draw
(`T1-15`: `no_audio` / `missing` / `unreadable`, never a flat line). The UI
still draws the picture. The swap onto those numbers remains — the regions
have to be draggable, and a picture cannot be. Same component, different
source; the CSS comment about text-shadow over the waveform (dimming it
would hide the quiet passages, which are exactly what you look at it to
find) stays true either way. An empty envelope must surface `reason`, not
a silent strip.

**Genuinely not built** — the live `meter` component (live
loudness-against-target as you mix — the export asset already
names measured I/TP and the off-target flag, `T1-25`).
`GET /api/songs/{id}/storyboard/{tier}/meter` reports `scene_time`
against `song_length` and `mismatch` beyond `SCENE_TIME_TOLERANCE`
(`T2-23`). It reports this song's `clip_seconds` from
`build_song.clip_seconds(scene_seconds)` (`T2-24`): the same song at
two `scene_seconds` yields two clip lengths. **`T2-25` built**:
`POST /songs/{id}/clips` refuses a scene-time miss (400, no job)
and still queues an in-tolerance board.

`finding-row` **built** (`GET /qc`, `_finding_row.html`,
`test_t3_19_finding_row.py`): measured / expected / unit / editable
remedy / approve — the QC queue's atom, `T3-4`, `T3-19`, `T3-20`,
`T3-27`; dismiss stays off this row until the file bytes change,
`T3-22`. A set finding
two `scene_seconds` yields two clip lengths.
`GET /api/songs/{id}/storyboard/{tier}` returns `anchors` grouped per
character (`character`, `images[].path` / `url` / `view`) so a client
that is not the HTML page can still put the strip at the top (`T2-26`).
Chosen sheets only; protagonist first. Each scene on that same GET
carries its reference stills (`refs[].path` / `url`) next to the
editable description (`T2-27`); the HTML scene row already showed them. `finding-row` (measured / expected / unit /
remedy / approve — the QC queue's atom, `T3-4`, `T3-19`, `T3-20`, `T3-27`; dismiss
stays off this row until the file bytes change, `T3-22`). A set finding
`transition_lands` (`T3-12`) is measurement only — `actionable` is false,
same as `duration_matches_prediction`. The
JSON already carries `remedy_class` and `actionable` (`GET /api/qc/findings`,
`T3-27`): a false `actionable` is why the button must not exist. The
per-box QC report is JSON only (`GET /api/qc/by-host`, `T3-1`): groups by
`host`, NULL host is an explicit `unattributed` bucket. No page; do not
pre-empt `finding-row` with one. An identity-wrong finding's remedy is
"edit the text, then re-render" (`T3-28`); the queue must not offer
"swap the reference image". A silence finding (`T3-9`) shows low / mid /
high band energy, not a peak; a take that only clicked is empty. A
spliced-track finding (`T3-10`) shows measured vs predicted seconds
from `mixer.bridge_seconds`, not a restated gap + 2×xfade.

## 5. The style guide

### 5.1 Navigation

    Library · Albums · Anchors · Sets · Jobs · Tiers · Config

TRD-2 §7's order stands: make-things first, machinery second. **Models joins
Config** as a section within it rather than a top-level peer — it is a
capability inspector, consulted when something will not render, not a place work
begins. `base.html` is the stale one.

**Playlists is renamed Albums, and this is the one rename worth doing.** The
outside consultation asked what the difference between "Playlists" and "Sets"
was and marked itself UNSURE, which is the right question: there isn't one that
the word explains. The domain calls them albums everywhere it speaks for itself
— `arc.py`'s docstring opens *"The album's STORY"* and then says *"an album is a
playlist, so the arc attaches to the playlist record"*; the arc, the album
profile, the cast and the anchors are all album-scoped. `playlists` is the
table's name and the nav is showing the schema to the operator. The table does
not have to move for the label to be right.

Depth stays at one level. Seven items is inside the range a flat bar carries.
The consultation proposed grouping them into four buckets (Work / Runs / Setup /
System); **rejected** — TRD-2 §7 already decided the order after the same
argument, and grouping adds a click to every navigation in exchange for tidiness
in a bar the operator has already memorised.

### 5.2 Type scale

Six steps, geometric-ish, replacing fourteen ad-hoc values.

    --text-xs:   0.75rem    /* tags, table meta, timestamps */
    --text-sm:   0.875rem   /* hints, secondary labels, dense tables */
    --text-base: 1rem       /* body; the default */
    --text-lg:   1.125rem   /* card titles, section heads */
    --text-xl:   1.375rem   /* page h2 */
    --text-2xl:  1.75rem    /* page h1 */

Line height: 1.5 body, 1.25 headings. One family (the existing system-ui stack)
plus `ui-monospace` for one job only — **numbers that are compared down a
column**: durations, frame counts, measured-vs-expected in a finding, file sizes.
Tabular figures there (`font-variant-numeric: tabular-nums`), because a column of
durations that does not align is a column nobody scans. Storyboard and
approve-grid clip duration is `build_song.clip_seconds(scene_seconds)` — the
legal 8n+1 length at the clip fps, not a page-local 4.8125. Clip count is
`build_song.n_clips_for` (`T2-13`), never a page-local `ceil(duration / CHUNK)`.
A row whose `scene_seconds` is NULL (generated before the column) still reads
as `CHUNK`. The renderer emits that same legal length (`T2-13a`): latent
frames and the audio-trim window follow `clip_seconds`, not a hardcoded
`LTX25_LEN`/`CHUNK`; a NULL `length_seconds` still renders 81 frames of
`CHUNK`. A mixed-model job keeps each clip's **native** frames and fps
(`T2-47`): s2v is 77@16.0, ltx25 is 81@16.8312; the editor must not
show one fps as if both renderers produced it. Starting that job is
refused before enqueue when any named model is unavailable on every
reachable backend (`T2-45`); a box that could not be asked (`None`)
is still a candidate, not a refusal. Per-scene model and
per-model ceilings compose (`T2-48`): a 30 s scene marked `s2v` splits
into s2v-sized clips, a 30 s scene on `ltx25` into 15 s ones, and each
chain tiles that scene. QC compares each clip to that native rate, not the song's output fps (`T2-13f`): using the song rate flags every correct clip of the other model. A single-clip request
over the model's ceiling (`T5-9`) is a
named refusal (measured vs chosen), not a quiet annotation; split is
`split_to_ceiling` / `clips_for_scene`. Re-generating a storyboard keeps every approved reference
(`T2-13b`); the approve grid still shows the same `(clip_idx, seed)` picks.
The grid lists every duration-owned clip even when the storyboard has
fewer scenes (`T2-13c`); a 20-scene board on a 41-clip song still
renders tiles 0..40.
A plan whose clip durations miss the track by more than one clip is
refused before render (`T2-13e`); the storyboard page still allocates
from `nclips` alone. Assembly still clamps to the track — an overrun
is a signal, not the expected leftover of 4.8125 s quantisation.
The storyboard planner prompt does not tell the model clips are a fixed
4.8125 s (`T2-14a`). Its clip-length line is `clip_seconds(scene_seconds)`,
so two plannings produce two TIMING statements (`T2-14b`). TIMING still
states track length and requires scene durations to sum to it (`T2-14c`).
Generated scenes tile the song (`T2-8b`): starts ascend, each end is the
next start, first is 0, last is duration ± 0.05 s; a gap or overlap is
refused at `validate`.
Editing the album's arc prompt creates a new version; restore puts the
previous wording back as the current text (`T2-5`). The album arc page
requires a **theme** before the wand runs (`T2-14`).
What comes back is a **proposal** (`--muted` plus a `model` tag, §7b.5),
not a saved story: Accept writes the committed pair, Reject leaves the
previous file on disk (`T2-15`). Applying per-song summaries to more
than one song is a confirmation checkbox, not a default (`T2-16`).
The album arc wand proposes; Accept and Reject are separate controls
(`T2-15`). Propose does not replace the stored file. Reject leaves the
previous arc on disk. Accept is the write. A proposal that was never
Accepted is still a proposal.
A generated storyboard carries a distinctive string from the album arc
when one exists, and does not when the arc is absent (`T2-20`).
At `xxx`, no scene `image_prompt` or `video_motion_prompt` carries the
mainstream lock (*fully clothed / no explicit gesture*); the tier's
own permission wording is in the scene text (`T2-21`).
The board's declared `guardrail` is this tier's `compose_guardrail`
clause; saving a board that carries another tier's wording is refused
(`T2-22`). Saving a board whose `character_reference` is empty is
refused; the message says identity comes from the text, not the
reference image (`T2-31`, `T2-32`).
The storyboard meter API reports total scene time against song length
and flags a miss beyond a stated tolerance (`T2-23`); it reports this
song's `clip_seconds`, not a constant (`T2-24`). A miss is refused
before clips enqueue (`T2-25`). The live `meter` component is not this.
The song page **Video model** select is `models.renderable("video")`
with each option's purpose in the hint (`T2-33`). Adding a catalogue
entry with a `cli` appears there with no template change.
A scene may name its own `video_model` beside `camera` (`T2-42`,
`T2-43`). The field is editable on the scene row
(`EDITABLE_SCENE_FIELDS`) and returned on
`GET /api/songs/{id}/storyboard/{tier}`; absent means the job
picker applies.
The generation prompt itself is API data (`T2-17`):
`GET /api/songs/{id}/storyboard/{tier}` returns the same defaulted-from-tier
string the direction box prefills; the HTML is not the only place that
string lives.
song's `clip_seconds`, not a constant (`T2-24`). The live `meter`
component is not this.
Every named scene figure carries `lead` / `extra` / `background`
(`T2-29`). `GET .../cast` returns `role` on each figure; the scene
row shows it. The unanchored-lead warning (`T2-30`) is not this.

### 5.3 Space and radius

    --space-1: 0.25rem   --space-2: 0.5rem   --space-3: 0.75rem
    --space-4: 1rem      --space-5: 1.5rem   --space-6: 2rem

    --radius-sm: 4px     /* tags, inputs, small buttons */
    --radius-md: 6px     /* cards, buttons, thumbnails — the default */
    --radius-lg: 10px    /* dialogs, raised panels */
    --radius-pill: 999px /* status pills only */

Six spacing steps against eighteen values, and the existing values map cleanly:
0.75rem and 0.5rem are already the two most-used by a wide margin (31 uses each),
so this is mostly ratification. **0.1/0.15/0.2/0.3/0.35/0.45rem all round to
`--space-1` or `--space-2`** — a difference nobody can see is a difference not
worth a token.

### 5.4 Colour roles

Keep all nine existing tokens and their names; the reasoning in the file is
better than most design systems'.

**First, name the palette, because it already is one.** `--accent: #7aa2f7` and
`--danger: #f7768e` are Tokyo Night's blue and red exactly. That is worth
writing down for one reason: every colour added from here comes **out of that
palette** rather than being invented, and two people picking a green
independently will otherwise pick two greens. The consultation proposed
`#7dcfff` for success, which is Tokyo Night's *cyan* — same family, wrong role.

    --ok:      #9ece6a    /* Tokyo Night green: done, passed, available */
    --warn:    #e0af68    /* Tokyo Night yellow: flagged, degraded, unmeasured */
    --running: #7aa2f7    /* = --accent; work in flight */
    --idle:    #8b93a1    /* = --muted; queued, not started */
    --ok-fg / --warn-fg   /* text on a filled state chip */

`--danger` already exists and stays failure/destructive. **Five states, five
colours, one meaning each, everywhere** — a tag, a row border, a job pill and a
QC verdict all draw from this and never from a local value.

Four more tokens for things every page improvises today:

    --focus-ring:  #9ab8ff
    --focus-shadow: 0 0 0 3px rgba(122,162,247,.28)
    --overlay:     rgba(8,10,14,.66)     /* dialog backdrop */
    --disabled-opacity: .48

**One extra surface, not three.** The consultation proposed `--panel-2` and
`--panel-3`; the measured complaint is that dialogs floated on the same flat
`--panel` as the page, and `--panel-raised` already fixed exactly that. Add
`--panel-2` for a subpanel nested inside a card and stop there — a dark
interface with four surface levels is a field of rectangles again, which is the
problem the ladder was meant to solve.

Colour is never the only carrier: every state chip carries a word, because the
tier system already proves the operator reads labels and because a colour-blind
reading of "flagged" versus "done" must not depend on hue.

### 5.5 Long-running work

The problem: renders take minutes to hours, so the operator needs to know work is
alive without a polling block pushing the page down.

**Status exists at three levels, and today only one of them is built.** This
frame came from the consultation and it is the most useful thing it returned:

| level | question it answers | today |
|---|---|---|
| shell | is anything happening at all? | the `#queue-panel` slab, on nearly every page |
| page | what is happening **to this song / anchor / set**? | nothing |
| action | what will *this button* start, where, and at what cost? | `plan-panel`, on one form |

**Shell.** The queue becomes a strip in the topbar, not a panel in `main`. One
line, always the same place: `3 running · 12 queued · 1 failed · cerberus`, the
whole strip a link to `/jobs`, expanding to the current panel's content so
nothing is lost. `/jobs` stops needing its empty-block exception — one poller
per page becomes structural instead of a per-page opt-out. **Polling backs off
when nothing is queued or running**: an idle studio should not be talking to
itself.

**Page.** Every page that can start work carries a small block for *its own*
work: active jobs for this object, the latest output, the latest failure. This
is what makes a page feel alive without the operator mentally joining a row in a
global panel to the thing they are looking at.

**Action.** `plan-panel` everywhere, per §4.

The six job states are the ones `jobs.py` already writes — **queued, running,
cancelling, cancelled, done, failed** — and one vocabulary serves buttons, rows,
chips and summaries. The consultation suggested deleting synonyms; checked, and
there are none: `error` is a *column* on the jobs row, not a seventh state.

Rules that apply at every level:

- **Progress is per-job and per-stage**, and a job that cannot report progress
  says *"no progress signal"* rather than showing a bar that does not move. A
  bar that does not move is the interface promising what the renderer is not
  producing.
- **Liveness, not just state.** A running row shows elapsed, last progress
  update, and goes **stale** past a threshold. "It says running" and "it is
  running" have been different things in this studio more than once — a job that
  succeeded and produced nothing is its signature failure — and only the second
  is worth showing.
- **Failure is sticky.** A failed job stays in the strip until acknowledged. It
  is the one state that must not scroll away, because a failure nobody saw is a
  render nobody re-queued.
- **Which box, always.** Every running job names its host. The fleet is
  heterogeneous — a 5090, a 5080, a 2080 Ti — and the same job on a different box
  is a different wait.
- **Milestones where the pipeline has them.** Storyboard → refs → clips →
  approve → assemble is the real shape of the work, and a chip row showing which
  step a song is on answers "where is this album" without opening five pages.
  Assemble does not silently letterbox: a ×2 clip among 832×480 siblings
  keeps 1664×960; mixed aspect is a named refusal (`T5-7`), not black bars.
  Mixed-model clips keep native fps until assembly; the assembled song
  is one output fps (`T2-13d`), not the first clip's rate.

### 5.6 Density, layout and breakpoints

Two layout modes, chosen per page rather than globally:

- **Document** — `max-width: 1200px`, centred. Forms, config, tiers, prose.
- **Canvas** — full width minus a gutter. Anything whose content is media or a
  time axis: anchor grids, approve grids, contact sheets, storyboards, the set
  timeline. This is the fix for §2.5(4), and it is a one-class change
  (`main.canvas`), not a rewrite.

Breakpoints: **two, both in rem**, replacing three in two units.

    --bp-sm: 40rem   /* below: one column, controls stack, tables scroll */
    --bp-md: 64rem   /* below: two columns collapse to one */

Mobile is a real target because a JSON API exists to serve one (`T6-A1`). What
must work small: reading state, approving and dismissing, looking at a picture.
What need not: drawing an automation curve.

### 5.7 States

    :focus-visible  2px solid var(--accent), 2px offset, on EVERY interactive
                    element — the §2.5(2) fix, and it is one rule, not fifty
    :hover          --panel-raised, or a 4% lift on filled controls
    [disabled]      60% opacity, cursor not-allowed, AND a title naming why
    [aria-busy]     the existing .htmx-request treatment, promoted to a token
    error           --danger border + a message that says what to do next

Disabled without a reason is banned. "Approve" greyed out with no explanation is
the same defect as a button that does nothing — the operator cannot tell refusal
from breakage. `T3-18` now distinguishes those: QC enqueues nothing, approve
enqueues one repair. `T3-27` names the other: a finding with `actionable`
false has no remedy, and approve refuses by that name. `T3-32`: running
tier 1 over a song is not a jobs row and does not wait on the GPU
worker — `POST /songs/{id}/qc` measures and returns. `T3-20`: the wording
that runs is the stored `prompts` row — same id on the finding and the job
after approval, not a stale copy in the form. `T3-23` names a routing
refusal (unfittable, or pinned under a name the box does not have) instead
of looking like a successful copy. `T3-25` names `can_move_output` when a
remote output cannot be moved back.
`T3-24` names the refiner as too big for a 15.92 GiB card (and for peaches)
and routes it to a 24 GiB box that holds the file. `T3-26` names a refine
pass that did not improve the tier-2 score on a labelled set as **not
helping** — the opportunistic catalogue tag is not that sentence. A
dismissed finding does not sit in the open queue until the file itself
changes (`T3-22`). A repaired finding lists the original and the new
candidate side by side, both scored (`T3-21` / `qc_service.pair`) —
dest ≠ src without those scores cannot answer whether the repair helped.

### 5.8 Motion

Keep `--motion-standard: 200ms` and `--motion-easing`. Two additions: 120ms for
state changes on small elements, 320ms for a dialog or drawer. Nothing animates
position on a list the operator is reading. `prefers-reduced-motion` already
turns it off and must keep doing so.

### 5.9 Copy

- Buttons say the verb and the object: *Render set*, not *Submit*.
- Costly actions say the cost: *Render set (~40 min on cerberus)*.
- Empty states say what to do next, never just *No items*.
- Errors name the consequence, not the exception. `qc.py`'s findings already do
  this — `detail` is "a human sentence, names the consequence" — and the rest of
  the interface adopts it.
- Never a claim the system cannot back. *Estimated*, *proxy*, *unmeasured* and
  *unproven* are all words this studio has earned the right to use precisely.

## 6. What to delete

- **The ~20 page-scoped CSS sections**, folded into §4's components. Expect the
  stylesheet to shrink; a page-specific rule that survives must say why in a
  comment, which is the existing file's own convention.
- **The per-page `init*` functions in `app.js`** where they are one behaviour
  wearing four names. The anchor page alone has `initAnchorPrompts`,
  `initAnchorPlan`, `initAnchorBatch` and `initAnchors`.
- **`--divider`**, which is the same value as `--border` (`#2c313c`). Two names
  for one colour is a drift waiting to happen; keep `--border` for the receding
  hairline and `--border-strong` for a boundary, which is the distinction the
  comment actually describes. (The consultation reached this independently and
  argued for dropping `--border` instead. Either is defensible; `--border` has
  more call sites, so dropping `--divider` is the smaller diff.)
- **The third and fourth of every triplet**: 0.72/0.75/0.78rem, 3px/4px/5px
  radii.
- **The `#queue-panel` slab**, replaced by the shell strip (§5.5) — not the
  information, the slab.
- **Nothing in §2.4.**

## 7. The outside consultation

**chatgpt, via `llm -m chatgpt` with the prompt on stdin** — the in-process agent
lane is dead (one trivial spawn, no report, not listed), so this is the measured
lane and it is named rather than implied. Brief: the measurements in §2, the
verbatim `:root` block, the stylesheet's own section headings, the class
histogram, `base.html`'s shell, and the domain facts in §1. 7.4 KB in, 36 KB
back.

**Zero fabrications**, and the brief is why: it demanded *"do not invent file
contents, class names, selectors or line numbers you were not given"*, accepted
`UNSURE — would need to see X` and `NOTHING FOUND` as answers, and required
every recommendation to be implementable with no dependency and no build step.
It used UNSURE eleven times, including on the one question that turned out to
matter most (§5.1). Every heading and class it cited was checked back against
`style.css`; all were real and all were in the brief.

**Folded in, after verification**

| what | why it survived |
|---|---|
| status at three levels — shell, page, action (§5.5) | the best thing it returned. The studio has level 1 and a one-page version of level 3, and no level 2 at all |
| promote `plan-panel` to a universal action companion (§4, §5.5) | it inferred the component from a CSS heading; the component turned out to already exist, used by exactly one template |
| liveness cues and the stale threshold (§5.5) | lands directly on this project's signature failure — a job that says running and is not, or succeeds and produces nothing |
| milestone chips for the pipeline (§5.5) | storyboard → refs → clips → approve is the real shape of the work |
| the question "how does Playlists differ from Sets?" (§5.1) | it marked itself UNSURE; resolving it produced the one rename worth doing |
| `--focus-ring`, `--overlay`, `--disabled-opacity` (§5.4) | four things every page improvises |
| delete the duplicate border token (§6) | independently reached the same conclusion I did, from the same evidence |
| back polling off when nothing is running (§5.5) | free, and an idle studio should not talk to itself |

**Rejected, with the reason**

- **Grouping the nav into four buckets.** TRD-2 §7 decided the flat order after
  the same argument. §5.1.
- **`--success: #7dcfff`.** Tokyo Night's cyan, in the success slot. The palette
  has a green. §5.4.
- **A three-step surface ladder (`--panel-2`, `--panel-3`).** One step, because
  `--panel-raised` already solved the measured complaint. §5.4.
- **Radius 6/10/14.** The tree's actual usage is 21×6px and 8×4px; a scale that
  moves every existing corner to make room for a level nobody uses is churn.
- **Renaming Jobs → Runs and Config → Settings.** Reasonable in the abstract,
  and both words are load-bearing elsewhere in the codebase (`jobs` table, `jobs.py`,
  `settings` table). A rename that stops at the label is a second vocabulary.
- **"Delete synonyms in the job state vocabulary."** Checked: there are none.
  `error` is a column, not a state. Recorded because a recommendation that was
  looked for and not found is worth as much as one that was.
- Everything it marked UNSURE about template internals. It was right to; those
  files were not in the brief and nothing was folded in from a guess about them.

## 7a. The surfaces TRD 4-7 adds

Added 2026-08-13 as stage 3's UI/UX pass. Not a second style guide — the system
in §4 and §5 applies unchanged. This is only what these four documents ask of it.

### 7a.1 The anchor form is the hardest screen in the studio and is about to get harder

`_anchor_form.html` is the second-largest template. TRD-7 `T7-3` shipped the
view table (cameras × clothed/nude, including on-all-fours) and `T7-19` made
the prompt box **per tier AND view**.

**Views are a matrix, not two lists.** One row per camera (front, back,
three-quarter, profile, seated, portrait, on all fours), two columns
(clothed | nude), a check-all on each column and one for all views. A radio
plus a disabled “override” checkbox was a status light pretending to be a
control (2026-08-14). Nothing is pre-ticked: G used to be the opening rating
because it is first alphabetically, and front used to stand in for an empty
view list (`T4-3`). Each ticked cell has its own prompt row so an edit on
front cannot land on back (`T7-19`). Two views of one rating share identity,
body and wardrobe; only the framing sentence differs, plus the nude swap on
a nude cell (`T7-4`). Clipboard paste and drop add base
photographs; they do not invent bases.

**Rendered sheets and the prompt editor share one shape.** Tier tabs, then a
clothed / nude sub-tab, then one row per camera position. A wand on each
prompt drafts that view; a second wand drafts every selected view in that
clothed or nude family. Drafts land in the boxes and are not saved until
the operator keeps them. Neither surface mentions a storyboard.

**The form reads in the order the work happens.** Who → rating → matrix →
base photographs → the wording that will be sent → negative → plan + Generate
(sticky, cost named first) → sampler knobs. The knobs used to sit above the
prompts, so the operator scrolled through CFG before they could see what the
sheet would say. A wizard is still banned: every footgun stays on the page.

**Do not "simplify" the footguns out while doing it.** The reason `T7-19` exists
is that one box per tier was sent verbatim to every view, so an edit typed at the
front sheet overrode the back view's framing and the nude wardrobe swap. Whatever
replaces the form has to make that visible, which a matrix does and a wizard does
not.

### 7a.2 Three-valued availability needs a three-valued chip

`T6-A6` is explicit: `models.where()` answers `True`, `False` or `None`, and
**`False` is a refusal while `None` is a candidate**. Conflating them once made
the box that actually held the refiner look like it did not.

A two-state available/unavailable chip cannot express that, so the state
vocabulary in §5.4 gains one member for capability specifically:

    available    --ok      this box holds it, under this filename
    unavailable  --danger  asked, and it does not have it — a refusal
    unknown      --muted   could not be asked; still a candidate, and says so

The middle and the right one must never look the same. "Nobody could ask the
sleeping gaming PC" and "peaches does not have this model" are different
sentences and the operator acts differently on each.

### 7a.3 A control the backend cannot honour is marked, never inert

The studio has two live instances of the same defect and both are UI-visible:

- **`--refine` on `ltx25`** attaches variant A (same-resolution second pass)
  (`T5-1`). Variant B does not fit on cerberus — recorded on the `ltx25`
  notes (`T5-6`); the upsampler is not silently dropped. Peak VRAM of
  shipped A is `T5-5`: `models.refine_peak` sits beside the 23.4/23.9
  base figure. A quoted copy of 23.4 is not a reading; missing samples
  raise. The refine peak is **NOT MEASURED**. Whether A changed the
  picture is `T5-2`: decoded-frame MAD and Laplacian variance, same seed,
  on vs off. A graph growing is not that reading. Missing frames raise;
  a skip is not a reading. The real GPU pair is **NOT MEASURED**.
  `T3-26` is the labelled-set half: a refine that does not raise the
  tier-2 score is reported as not helping; missing scores raise, they do
  not inherit `opportunistic`.
- **Five of six `DENOISE_CHOICES`** *were* labelled *"on an anchor this returns
  noise"*, correctly, because `latent_mode` was pinned to `"empty"`. **`T7-8`
  shipped 2026-08-13 (`d3f2f6a`) and unpinned it** — corrected after review
  caught this section still presenting a fixed defect as live. What follows is
  now a rule to **hold**, not a defect to fix.

The second is the honest version of the first — it at least tells you. The rule
that generalises both, and `plan-panel`'s own comment already states it:

> **The button is MARKED, never disabled — a control that cannot apply still has
> to say why, and the reason is in the panel above it.**

So: a control whose backend cannot honour it is **absent, or present and marked
with the reason**. Never present and silently inert. When `T7-8` lands, one
resolver decides the denoise labels *and* the graph, so the label cannot go on
saying "returns noise" after the mode makes it false.

### 7a.4 Versioned prompt fields are one component, not four more

`prompts.py` versions 9 types today and TRD-7 adds 4 (`view:<key>`, `backdrop`,
`composite`, `pose`). If each arrives with its own markup the stylesheet gains
four more page-scoped sections, which is §2.3 happening again in real time.

One `versioned-field`: label, the wand, the hint, the control, a version picker,
and the usage count — which counts **renders, not loads**, because a wording you
looked at and rejected is not a wording you used. Deleting a version leaves a
gap; remaining numbers do not compact (`T2-6`). `T7-13`'s `view:<key>` types
are generated from the view table, so the UI iterates types rather than listing
them; a type added to `PROMPT_TYPES` appears with no template change. That is the
same rule `T2-33` sets for the model picker.

### 7a.5 "Use as reference" is a tile state, not a new page

`T7-6` shipped: an anchor can now be the identity lock for the next sheet. The
`T7-7` picture look is still human-judged; the compose hook FLAGs a
human-body nude wording (including the live-studio body clause) so a dirty
prompt does not reach the tile as a clean candidate. The front /
three_quarter ranking harness exists offline; the GPU pair is not measured.
`T4-13` is a `channel_balance` FLAG on the sheet's pixels (olive/magenta vs
grey wall), not a `BACKDROP` string; the real GPU sheet is **NOT MEASURED**. In
`media-tile` terms that is one more action on the tile and one more state on it —
*this sheet is the identity reference for the sheet you are composing*. It earns
emphasis because it is the studio's largest consistency lever, and it does not
earn a screen.

### 7a.6a Candidate tiles carry a vision confidence

`T3-31` / `T4-19`. Each generated still — anchors, refs, rerolls,
`fix_ref` results, `fix_anchor` siblings, artwork generate and its
refine sibling, an `h_repair` dest still, and a standalone refine dest —
stores `qc_json`. The artwork generate is a scored
`assets` row even when a refined cover is what the playlist card shows.
Anchor tiles in `_anchor_group.html` show `confidence` (0–100) against
the **base photographs and the prompt**, or the named xAI/local failure
when scoring failed (`vision: xAI …` / `vision: local …`). Never
"vision unknown". Not a gate. The operator still picks. A refine pass
or a `fix_anchor` writes a sibling file; it does not overwrite.
Predecessor and successor are both listed and selectable (`T6-A5`:
`qc_service.listed` / `select`; set re-render, repair and anchor re-roll
use the same pair). Old rows with no `qc_json` stay blank, same as a
missing render tag.

### 7a.6 What the queue owes these four

§5.5's three levels, applied: an anchor batch is *n* candidates at
`seed + k*137`, and the page-level block is what says how many of them have
landed. **Which box, always** matters more here than anywhere — cerberus,
peaches and ethan render the same sheet at very different speeds, and `T6-4`'s
distinction between a box that went away and a workflow a box *refused* is the
one the operator has to see, because only the first is worth waiting for.
A repair never shows a landed dest beside a finding that is still only
approved (`T6-14`): land and the findings stamp commit together, so a killed
worker cannot paint half a job.

## 7b. The surfaces TRD 8-10 adds

Added 2026-08-13. Same system as §4 and §5; only what these three ask of it.

### 7b.1 A take is a candidate, and the studio already has that component

TRD-8's take is *"one generated candidate for a song, exactly as a `refs` row is
one candidate frame"* — so it is **`media-tile` with an audio body**, not a new
pattern. Same states, same pick act (`POST /songs/{id}/takes/{id}/pick`), same
rule that the unpicked one stays reachable (`T6-A5`, `T8-2` — `qc_service.listed`
/ `select` is the pick act for a re-produced pair). Pick does not
write `songs.mp3_path`; Use on a generated take is refused. The tile reads the
`takes` row (`T8-1`: tags, lyrics, seed, duration, params as sent), not the
live song row.

What differs is that **you cannot judge audio from a thumbnail.** A tile that
shows a waveform and a duration is showing metadata; the operator has to press
play. So the take tile's primary action is **playback**, and comparison is the
layout's job: takes for one song sit in a row that can be played in turn without
leaving the page, because *"picked by ear"* is the actual workflow and a
navigation between two takes destroys the comparison. The tile also reads
`params_json.voice_id` (`T8-11`): which voice produced the take, or that none
did. A take that cannot say is a take that cannot be compared on that axis.

### 7b.2 The consent field is a gate, and gates look different from fields

`T8-10` refuses a voice with no recorded source and consent. **A refusal that
looks like a validation error teaches the operator to route around it.** This one
is a precondition, not a typo: the form states what is required before the
control accepts anything, in the `plan-panel` shape (§4) — *what this will do,
before you press it* — rather than as red text after a failed submit. The
server still refuses if the form is bypassed: `insert_voice` names `source`
or `consent` in the error. There is no voice-cloning control on any page.

### 7b.3 The fleet page is the one screen where "unknown" must not read as "no"

TRD-9's whole subject is four heterogeneous boxes, and §7a.2's three-valued chip
was written for exactly this page: `available` / `unavailable` / **`unknown`**.
`T6-A6` makes it a correctness requirement rather than a nicety — `False` is a
refusal and `None` is a candidate — and the fleet page is where the operator
reads it.

Two additions specific to TRD-9:

- **A backend row says when it was last asked**, because `by_backend()` reads one
  box at a time and a sleeping gaming PC answers slowly or not at all. A stale
  reading presented as current is the same defect as a progress bar that does not
  move.
- **An empty registered backend is marked as a hazard, not as healthy** (`T9-9`).
  It is "running" by every measure Swarm reports and it will refuse real work.
  Green here would be the interface agreeing with the wrong signal.

### 7b.4 Bulk edit is the highest-risk form in the studio

`T10-3`…`T10-7` are built. `T10-3` and `T10-4` are data-destruction rules, and
both are *interface* failures before they are code failures:

- **Blank must not read as "clear".** The empty option is *(leave alone)*, and
  a blank field is not written. Clearing needs its own explicit control.
- **Toggle-all must show its scope.** The header checkbox title is
  *"Select all N shown"*, because the header sort and filters are live and the
  operator cannot see what is off-screen.
- **The pre-write count is part of the control, not a toast.** `#bulk-count`
  shows `would_change` from a `preview` POST, and that number is the write's
  `changed` — the 12-vs-9 case. A confirmation that overstates once is a
  confirmation nobody reads again.

### 7b.5 Model-authored text has to be visually distinct, everywhere

`T10-11` marks it in the payload; this is what the payload is for. **One
treatment, used for every model-authored string** — the arc proposal, the mix
advice, the contact-sheet description, the QC remedy — and never the same
treatment as a measurement.

The client reads `authored`. `model` is advice; `measurement` is a reading and
must carry `unit`; `operator` is typed text. The set editor's mix `why` is
`--muted` plus a `model` tag; a measurement is never given that tag.

`T10-12`: Suggest and Accept are separate controls. Suggest retains a proposal
and writes no mix values. Accept writes the mix and names the model that
proposed it. A filled-in form that was never Accepted is still a proposal.

This is the interface half of `T10-14`. If advice and measurement look alike, the
operator will eventually treat a confident sentence as a reading, which is how
`41.1 vs 64.7` would have become a gate. The style-guide rule: **model text
carries the `--muted` role and an explicit marker; measurements carry
`--text` and a unit.** A number without a unit is a claim, not a measurement.

`T3-13` is not a screen. Overlap and separation live on the `calibrations`
row. `T3-14` can write a threshold on a stored separated row (service,
not a tile); `T3-16` still builds no gate. `T3-17` scores each artefact
against the chosen anchor (compliance, variation, n) as a tier-2
measurement — it is not a badge and not a tile. There is no threshold
control. Putting that number on a tile now would be the inversion this
paragraph exists to stop.

## 8. How this document is verified

A style guide is falsifiable or it is decoration.

- **The scales are the only values.** A check greps the stylesheet for
  `font-size`, spacing and `border-radius` literals outside `:root` and fails on
  a value that is not a token. This is the check that keeps §2.2 from happening
  again, and it can fail, which is why it is worth writing.
- **Focus is everywhere.** A check walks the rendered pages for interactive
  elements and asserts each resolves a `:focus-visible` style. Deleting the rule
  must turn it red.
- **The nav matches the agreed order**, asserted against one list that both
  `base.html` and the API read. `T6-A2`'s first object is the queue panel:
  `/queue` HTML and JSON report the same numbers
  (`test_t6_a2_html_and_json_report_the_same_queue_numbers`). Nav is still
  this guide's own list check.
- **No template computes.** `T6-A4`, asserted by a differential: stub the service
  to return known values and assert the page shows them unmodified.
  `test_t6_a4_queue_page_shows_stubbed_values_unmodified` is that check for
  `/queue`. `_jobs_panel.html` still formats elapsed.
- **The measurements in §2 are re-runnable.** Each is a one-line count, and a
  number here that no longer reproduces is a document that has gone stale — which
  is what happened to every line-number citation in TRD-2 §3.4 within a day.
