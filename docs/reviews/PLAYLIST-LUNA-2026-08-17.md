# Luna review — modern consistent AV web UI

**Model:** `gpt-5.6-luna` (OpenAI; MCP `chatgpt5__gpt5_chat` called first — wrapper
returns `Unexpected response type` while the API succeeds; full text recovered
via the same key/model because `mcp_server.log` truncates `send_response` at
200 chars.)
**Date:** 2026-08-17
**Brief:** `docs/UIUX-DEFINITION-AND-STYLE-GUIDE.md` (playlist/album look, song,
storyboard, §5.5 long-running work), TRD-2 status/UI criteria, skim TRD-1 /
PRD-1-3 / DDD-1-3 for surfaces UIUX may under-specify. Loading/placeholder
states for set render, jobs, clips.
**Scope:** Opinion only. No studio code. No commit.

Tree-check notes below mark where Luna assumed absence of something the TRD
ledgers already call **built**. Those notes are the documenter's, not Luna's.

---

## Verdict

Yes: the current path is sound for a modern, consistent AV workstation,
especially because the pipeline is reflected in the song page rather than
split across unrelated tools. The strongest decisions are media-first
presentation, a single state vocabulary, song-length-owned clip planning,
in-place storyboard approval, and explicit cost before GPU actions. The album
look/cast fold, storyboard-on-song-page, lazy media loading, and sticky queue
shell are all appropriate for a one-operator production system.

It will still read as an internal tool where pages expose
implementation-shaped forms instead of production objects: jobs without
object-level context, sets without a clear timeline *feel* in the broader
system, and songs that feel like stacked configuration folds rather than an
active edit workspace. The missing **page-level job status** is the largest
consistency break because the shell can say "something is running" while the
current object says nothing. The other major risk is incomplete application of
the already-decided design system: tokens, focus treatment, canvas layout, and
universal plan panels.

No visual redesign or SPA rewrite is needed; the next work should make the
existing decisions pervasive and give each production object a clear status,
output, and next action.

---

## Numbered recommendations

| ID | Title | Default | Effort | Touches |
|----|-------|---------|--------|---------|
| R1 | Object-level production status panel | **Approve** | M | UIUX §5.5; queue-strip; finding-row; T6-A1–A4; TRD-3 |
| R2 | Universal `plan-panel` for GPU work | **Approve** | M | UIUX §4 / §5.5; TRD-2 §5; TRD-6 |
| R3 | Apply type / space / radius scales globally | **Approve** | M | UIUX §2.2 / §5.2 / §5.3; all named components |
| R4 | Song page as canvas-oriented workstation | **Approve** | L | UIUX §5.6 canvas; tier-board; media-tile; TRD-2 §5 |
| R5 | Finish Playlists → Albums rename | **Approve** | S | UIUX §5.1; TRD-2 §7; album look/cast |
| R6 | Set timeline / render surface polish | **Approve** (polish only) | L | TRD-1; UIUX timeline; plan-panel |
| R7 | Job-chip popover without permanent slab | **Approve** | M | UIUX §5.5; job-chip; jobs-modal; T2-11 chaining |
| R8 | Take-oriented audio strip on song page | **Approve** | M | UIUX §7b.1 media-tile; TRD-8; T8-1–3 |
| R9 | Pose coverage matrix per song | **Approve** | M | TRD-2 pose plan; UIUX pose strip; T2-28 readiness |
| R10 | Compact QC / failure-recovery surface | **Approve** | M | UIUX finding-row; TRD-3; page-level status |

### R1 — Object-level production status panel

- **Change:** Reusable page-level status block on Album, Song, Anchor, Set (and
  other object pages): active jobs, latest output, latest failure, next action
  for *this* object.
- **Why:** Shell `job-chip` answers "is anything running?" not "what is
  happening to this object?" Largest gap in the three-level long-running-work
  model (UIUX §5.5 already admits page level is missing).
- **Default:** Approve · **Effort:** M
- **Touches:** UIUX §5.5; queue-strip; finding-row; T6-A1–A4; TRD-3

### R2 — Make `plan-panel` the universal preflight for GPU work

- **Change:** `plan-panel` before every GPU spend: generate refs, reroll stills,
  generate clips, s2v hop, assemble, set render (not only anchors).
- **Why:** Operator sees work estimate, clip count, duration, model path, and
  prerequisites before enqueue. Blocked (not disabled) preserves the reason.
- **Default:** Approve · **Effort:** M
- **Touches:** UIUX §4 plan-panel; §5.5; TRD-2 §5 (refs/clips enqueue); TRD-6

### R3 — Apply type, spacing, and radius scales globally

- **Change:** Land the approved scales in one shared stylesheet; delete
  page-scoped values except documented media-canvas exceptions.
- **Why:** 14 font sizes / 18 spacings / 6 radii make album, song, and
  storyboard feel like separate apps (UIUX §2.2 root finding).
- **Default:** Approve · **Effort:** M
- **Touches:** UIUX §5.2 / §5.3; all §4 components

### R4 — Convert the song page into a canvas-oriented workstation

- **Change:** `main.canvas` for storyboard/media-heavy song states: persistent
  song context, dense scene rail, selected scene center, refs/stills/clips
  adjacent to scene details; metadata/forms stay document layout.
- **Why:** Keeps song-page architecture but stops "stack of forms." Operator
  should compare scene, pose plate, refs, still, and clip without long
  vertical traversal.
- **Default:** Approve · **Effort:** L
- **Touches:** UIUX §5.6; storyboard/tier-board; media-tile; TRD-2 §5

### R5 — Finish the Album terminology and card behavior

- **Change:** Visible "Playlists" → "Albums" in nav, headings, empty states,
  buttons, and UI labels. Route/API aliases only if needed.
- **Why:** Domain decision already made (UIUX §5.1). Inconsistent naming forces
  operator translation between product language and schema language.
- **Default:** Approve · **Effort:** S
- **Touches:** UIUX §5.1; TRD-2 §7; album look/cast fold

### R6 — Give Sets a real timeline and render surface

- **Change (as Luna wrote):** Set page with horizontal song/scene timeline,
  duration totals, gaps/overlaps, render coverage, set-level plan-panel.
- **Default:** Approve · **Effort:** L
- **Touches:** TRD-1 timeline; TRD-3 assembly; UIUX §5.6; media-tile; plan-panel

**Tree note:** UIUX already documents `.timeline` / `.tl-block` on
`set_edit.html` as built (peaks, joins, audiences, loudness). Treat R6 as
*canvas density + plan-panel + coverage*, not greenfield DAW work. Do not
rebuild the timeline model.

### R7 — Make the queue useful without opening the modal

- **Change:** Expand sticky `#job-chip` on hover/focus/click into a compact
  popover: current object, stage, state, dependency, next event. Keep
  `#jobs-modal` for the full queue.
- **Why:** Quick orientation without a permanent slab. Matters for chained
  clips that stay **queued** until predecessor **done** (T2-11; not a 7th
  state).
- **Default:** Approve · **Effort:** M
- **Touches:** UIUX §5.5; job-chip; jobs-modal; TRD-2 T2-11 / TRD-6

### R8 — Add a take-oriented audio surface

- **Change:** Song-page "audio candidates/takes" strip: waveform or duration
  meta, selected take, replacement action, "used by storyboard" relationship.
- **Why:** Pipeline starts at MP3; multiple candidates need a media-oriented
  pick that owns song length and timing.
- **Default:** Approve · **Effort:** M
- **Touches:** UIUX §7b.1 (take = media-tile with audio body); TRD-8 T8-1–3

**Tree note:** UIUX §7b.1 already names the component and pick act. R8 is
*surface density on the song page*, not a new pattern.

### R9 — Surface pose coverage as a matrix, not only a library

- **Change:** Pose coverage view: scene rows × required pose/identity/plate,
  cells for missing / reused / approved / blocked.
- **Why:** Pose library alone does not show whether *this song* is fully
  covered for refs.
- **Default:** Approve · **Effort:** M
- **Touches:** TRD-2 pose plan / T2-28; UIUX pose strip + plan blockers

**Tree note:** Collapsed per-tier pose plan and scene **Pose plate** row already
exist. R9 is a denser matrix readout, not inventing the binding model.

### R10 — Compact QC and failure-recovery surface

- **Change:** Approval/QC queue for failed, suspicious, missing-artifact, and
  awaiting-approval outputs; reroll / retry / replace / inspect / dismiss with
  preserved reason.
- **Why:** Done ≠ usable. Artifact-less or failed renders must stay actionable
  without rediscovery through the global jobs modal alone.
- **Default:** Approve · **Effort:** M
- **Touches:** UIUX finding-row; approve grid; page-level status; TRD-3

**Tree note:** `GET /qc` + `_finding_row.html` + T3-19 are built. R10 is
*object-page sticky failures + tighter song linkage*, not a second QC product.

### Explicitly not recommended (already rejected in UIUX §7)

- Nav bucket grouping (Work / Runs / Setup / System)
- Renaming Jobs → Runs or Config → Settings
- SPA rewrite / second product surfaces for the same pipeline

---

## Gaps: TRD criteria not fully surfaced in UIUX

The UIUX guide is strong on component vocabulary and density. Luna flags these
operator-facing surfaces as under-specified relative to TRD/PRD/DDD.

### TRD-1 / song and timing

- Audio source / take selection ownership of song length; replacement impact on
  lyrics, board timing, clips.
- Timeline visibility beyond the storyboard meter: scene order, cumulative
  time, gaps/overlaps, mismatch location.
- Set-level sequencing readiness (order, transitions, total duration, render
  readiness) as a *system* story, not only set_edit.
- Assembly state: clips complete vs assembled deliverable available.
- Cleanup / normalization status if in the domain model.

### TRD-2 / visual planning and references

- Pose coverage matrix (library ≠ song readiness).
- Reference provenance per scene (identity front, pose plate, look, wardrobe,
  supporting cast).
- Anchor readiness visible *before* Generate refs (missing front, unanchored
  lead, invalid plate, guardrail) — HTML plan-panel exists; system-wide
  pattern incomplete.
- Wardrobe/rating constraint applied to a given scene/ref.
- Still→clip parent relationship for reroll/approve/replace.
- Adult-content rating indicators local to media/action, not as exceptional
  errors.

### TRD-3 / jobs, fleet, outputs

- Dependency copy: "waiting for predecessor X" on chained clips.
- GPU cost / capacity consistently on plan-panel and job rows.
- Cancelling vs cancelled semantics and downstream invalidation.
- `done` with no artefact as a distinct finding (not a success tile).
- Stale-running as warning on `running`, not a 7th state.
- Retry/reroll lineage (which output is current).
- Small fleet/worker diagnostic (availability, assignment, model errors) —
  not a separate product.
- Output cleanup as reviewable action tied to retention / current artefact.

### DDD/PRD adjacency

- Consistent object↔job and artefact relationships across Album / Song / Set /
  Anchor / export.
- Approval ownership / lock for board and output review.
- Idempotency / duplicate enqueue prevention UX.
- JSON parity for every new status, plan, QC, timeline view (T6-A1–A4).
- Empty-state next actions: album without songs, song without lyrics,
  unanchored song, set without songs, job without artefact (UIUX §5.9).

**Also thin in UIUX vs built TRD-2 ledger:** live `meter` component vs API
meter (T2-23/24/25); multi-lead cast control vs free-text Role (operator
complaint surface on live playlist cards — separate playlist-card Luna pass
at 15:21 same day, truncated in MCP log); identity-front vs pose-sheet
language consistency.

---

## Loading-state recommendations

Key rule: distinguish *not loaded*, *queued*, *running*, *stale*, *complete*,
and *failed*. Do not use generic shimmer for all of them.

### Initial page load

- Structural skeletons matching final layout (album cards; song scene rail +
  media rows + plan region; jobs rows with state/object/stage/actions).
- Shell and heading visible immediately.
- `#page-loading` for nav-level activity, not the only object-request signal.
- Album card expansion: keep "Loading album…"; add skeleton regions for look /
  cast / anchors.

### Enqueue

- After plan confirmation: compact acknowledgement (`Queued`, object/stage,
  estimate if known, link to job) — not media shimmer before a job exists.
- Update job-chip, page-level status, and affected media via htmx/poll.

### Queued / waiting for predecessor

- Media-tile or finding-row: `Queued — waiting for clip 03`, predecessor
  state, "starts after predecessor."
- Muted non-pulsing frame — not active GPU shimmer.

### Running without progress signal

- Static or very slow indeterminate treatment — never a fake progress bar.
- Stage + start time: `Generating refs · started 14:32`.
- Known plan data (scene count, clip length, model, estimate).
- Cancel where supported; page-level status mirrors it.

### Stale running

- Canonical state stays `running`; attach warning:
  `Running — no update received for 8 min` + last heartbeat.
- Actions: inspect, cancel, retry after fail, refresh.

### Done with no artefact

- Not a success media tile. finding-row: `Done, but no output was found`,
  job id/stage/time, inspect / recheck / retry / dismiss.
- Page-level status retains as latest failure until resolved.

### Failed sticky

- Remain on object page after job leaves active queue.
- `warn-tag` with stage + concise reason.
- Smallest recovery: retry, regenerate plan, logs, replace input, dismiss.
- Do not blank into empty media after navigation.

### Done with artefact

- Real lazy thumbnail/player; until then fixed neutral skeleton.
- `Done` metadata outside image so tile is not "unfinished" solely for image lag.
- Clips: duration + approval independent of thumbnail.

### Set render

- Timeline-shaped skeleton while set definition loads.
- After enqueue: per-song/segment readiness slots.
- One set-level plan-panel (duration, estimate, missing artefacts, warnings).
- During render: completed solid, queued muted, active indeterminate — do not
  shimmer the entire timeline.

### Clips strip

| Situation | Treatment |
|-----------|-----------|
| No clips, prerequisites OK | Empty + next action + plan-panel |
| No clips, missing refs/stills | Blocked + exact prerequisite finding |
| Queued | Stable muted tiles; no active shimmer |
| Running | One active indeterminate tile + stage/time |
| Completed | Lazy thumbs + approval |
| Mixed | Per-tile state; no single strip-wide loading message |

### Refs stills

- Reroll: existing N shimmer placeholders OK (explicit replacement).
- Keep scene identity/position so grid does not jump.
- Initial generate: stable empty tiles labelled by scene until job is
  queued/running — not generic shimmer.
- Approve never looks available on a placeholder.

### Assemble

- Before: plan-panel (coverage, missing approvals, duration, cost).
- Queued: `Queued for assembly`.
- Running: `Assembling` + start time + source count (no fake %).
- Done with file: output media-tile + open/download.
- Done without file / failed: sticky finding-row on song/set + jobs view.

### Skeleton vs shimmer vs empty

| Pattern | Use when |
|---------|----------|
| Skeleton | Initial structure / data fetch; fixed geometry |
| Shimmer | Explicit media replacement (reroll) or known tile fetch |
| Empty + next action | No work requested or prerequisites absent |
| Queued placeholder | Stable, non-pulsing; dependency text |
| Running placeholder | Restrained indeterminate; stage/time |
| Failed placeholder | Persistent finding + recovery |

---

## Confidence

**89%** (Luna).

Implementable with shared CSS, Jinja, htmx partials, polling/refresh, and JSON
for new status/plan/QC data. Main uncertainty is not UI feasibility but exact
field names and which audio/set/fleet/cleanup concepts already exist (several
already do — see tree notes on R6/R8/R9/R10). Screenshots would refine density
and canvas breakpoints; not required for the priority fixes.

---

## Sources

- [docs/UIUX-DEFINITION-AND-STYLE-GUIDE.md](../UIUX-DEFINITION-AND-STYLE-GUIDE.md) — §2 defects, §4 components, §5.1 nav/Albums, §5.5 long-running work, song/storyboard/playlist behaviors, §7 consultation fold/reject
- [docs/TRD-2-STORY-ARC-AND-STORYBOARDS.md](../TRD-2-STORY-ARC-AND-STORYBOARDS.md) — §5 storyboard page, §7 nav, status ledger (T2-23–T2-37, T2-28, pose plan, playlist look)
- [docs/TRD-1-TIMELINE-AND-MIXING.md](../TRD-1-TIMELINE-AND-MIXING.md) — set timeline / export criteria
- [docs/PRD-1-3-EDITING-AND-QUALITY.md](../PRD-1-3-EDITING-AND-QUALITY.md) — journeys A–C; P1–P7
- [docs/DDD-1-3-EDITING-AND-QUALITY.md](../DDD-1-3-EDITING-AND-QUALITY.md) — service/API surfaces; playlist card load pattern
- Prior consult: [docs/reviews/UIUX-CONSULT-chatgpt-2026-08-13.md](UIUX-CONSULT-chatgpt-2026-08-13.md)

## Recommended next step

Ship **R1 (page-level status) + R2 (plan-panel on refs/clips/assemble) + R5
(Albums rename)** first — S/M work that closes the largest consistency gaps
without touching canvas layout. Then R3 tokens and R4 song canvas. Treat R6/R8/R9/R10 as polish on built machinery, not new products.
