# AV / music-video studio UI practices (operator workstation)

**Date:** 2026-08-17  
**Scope:** Meow P Studio — FastAPI + Jinja + htmx + sqlite, dark theme, GPU fleet jobs.  
**Audience:** Single operator on the tailnet judging media, not a consumer streaming product.  
**Not in scope:** React rewrite, public multi-tenant SaaS chrome, marketing polish.

Companion: [`docs/UIUX-DEFINITION-AND-STYLE-GUIDE.md`](../UIUX-DEFINITION-AND-STYLE-GUIDE.md) (tokens, principles, component inventory). This note does not replace that guide; it adds workstation-side loading, density, and iconography practices and eight stack-fit recommendations.

External references used (general UX, not product requirements):

- Nielsen Norman Group — skeleton screens and progress timing  
- IBM Carbon — loading pattern (skeleton vs spinner vs progress)  
- GitLab Pajamas — skeleton loader guidelines  
- Bill Chung / UX Collective — skeleton screen design  
- htmx docs — `hx-indicator`, progressive enhancement, fragment swap  

---

## 1. Loading / placeholder / skeleton while a set or clip job runs

### 1.1 Three different waits (do not collapse them)

| Wait class | Duration (typical) | Operator need | Pattern |
|---|---|---|---|
| **Fetch** (htmx swap, panel reload, song page fragment) | &lt; 2 s, often &lt; 500 ms | Prove the click registered; do not flash a full skeleton | Inline `hx-indicator` spinner, or none if swap is instant |
| **Short work** (save form, recompute meter, assign keeper) | 1–10 s | Same surface stays usable; local busy | Button/row spinner; disable only the control that is in flight |
| **Fleet job** (anchor sheet, stills, clip, set render) | minutes → hours | Know *what*, *where*, *cost*, *state*; keep judging other media | In-place media placeholder + global job chip + poll/SSE of status — **not** a full-page blocker |

NN/g and Carbon agree on the split: skeletons help for *layout that will fill soon*; progress (or at least named status) is required once wait exceeds ~10 s. A GPU render is not a page load. Treating it like Netflix “buffering” is wrong.

### 1.2 Skeleton: when and how

**Use skeleton / shimmer placeholders when:**

- The slot already exists in the layout (scene ref strip, still grid, clip tile, set timeline block).
- You know *count and aspect* of what is coming (e.g. “4 stills for this scene”).
- The operator may stay on the page and needs spatial stability (no jump when results land).

**Do not skeleton:**

- Toasts, overflow menus, dialog chrome, the topbar.
- Actions themselves (buttons get a spinner, not a fake button outline).
- Whole pages for jobs that outlive a single request (full-page `#page-loading` is for *navigation/upload* only, not clip renders).
- Content that arrives in &lt; ~1 s (flashing skeleton increases perceived jank).

**Shape rules for media workstations:**

1. **Match final geometry.** Portrait still skeleton ≈ 896×1216 aspect (or the studio’s current still tile); landscape clip tile ≈ 16:9. Wrong aspect trains the eye for the wrong thing.
2. **Caption is data, not decoration.** `rendering…` alone is weak; prefer `clip 3 · running · ethan` or at least kind + status from the job row.
3. **One shimmer language.** The existing `.still-pending` / `.still-skeleton` shimmer is the right primitive. Generalize it to clips and set blocks; do not invent a second animation curve per page.
4. **Honor `prefers-reduced-motion`.** Shimmer becomes a static dashed panel (motion tokens already exist: `--motion-standard`, `--motion-easing`).
5. **Swap, don’t pile.** When the job finishes, replace the placeholder in the same DOM slot (htmx outerHTML or targeted fragment). Leaving both “rendering…” and the finished still is a defect.
6. **aria-live sparingly.** Announce *state transitions* (queued → running → done/failed) on a status region, not every poll tick.

### 1.3 Job-shaped progress (fleet, not HTTP)

Consumer spinners imply “almost done.” Fleet jobs need the **studio state vocabulary** (from `jobs.py`): `queued` → `running` → (`cancelling`) → `done` | `failed` | `cancelled`. UI already treats this as first-class (job chip + jobs modal). Practices:

- **Local placeholder** = “this *slot* is owned by job N.”
- **Global chip** = “something is on the fleet” (always visible while work is in flight).
- **Jobs modal / queue fragment** = cancel, log, host, kind — operator controls, not entertainment chrome.
- **Backoff poll** when idle (already the direction); never hammer `/queue` while nothing runs.
- **Never block the rest of the page** for a multi-minute render. Operator workflow is multi-threaded: judge other scenes while one set encodes.

### 1.4 Progressive loading for media grids

Carbon’s progressive model fits this stack without React:

1. Shell + text meta (scene index, duration, tags) first — server-rendered in Jinja.
2. Skeleton tiles for missing thumbs.
3. Images with `loading="lazy"` (and post-htmx re-init — `app.js` already notes native lazy is not enough after panel swap).
4. Heavier assets (video, full lightbox) on demand only.

Placeholders for *not yet generated* work are different from *image not yet downloaded*. Label them differently: “not rendered” vs “loading preview.”

### 1.5 Failure is a first-class loading outcome

A done skeleton that never fills is worse than an empty state. Practices:

- On `failed` / `cancelled`, replace skeleton with a stable failure tile: status chip + link to job log + retry if allowed.
- Do not leave shimmer running after the job terminal state.
- Keep the plan-panel / cost wording; the operator may re-queue with different inputs.

---

## 2. Shared design tokens and CSS class reuse

### 2.1 What this codebase already got right

`:root` in `studio/static/style.css` already has a *reasoned* colour system:

- `--bg`, `--panel`, `--text`, `--muted`, `--accent`, `--accent-fg`, `--danger`
- Split borders: `--divider` (recede) vs `--border-strong` (WCAG-ish boundary)
- Depth/motion: `--elevation-1/2`, `--panel-raised`, `--motion-standard`, `--motion-easing`

Colour tokens carry measured contrast rationale. That is the model for everything else.

### 2.2 The known gap (from the style guide — still true)

Type, space, and radius were **not** tokenized: many ad-hoc `rem` sizes and six radii. Result: page-scoped CSS sections that re-specify `card` / `field-row` / `tag` instead of reusing them.

### 2.3 Workstation token set (minimal, enough)

Add only what stops page-local invention. Do not import a full M3 type scale.

| Axis | Suggested tokens | Rule |
|---|---|---|
| Type | `--fs-xs` `--fs-sm` `--fs-md` `--fs-lg` (4 steps) | Body stays 15px; tables and meta use sm/xs only |
| Space | `--sp-1`…`--sp-6` (e.g. 0.25 / 0.5 / 0.75 / 1 / 1.5 / 2 rem) | No new 0.72rem one-offs |
| Radius | `--r-sm` `--r-md` `--r-pill` | Tiles/cards use md; chips use pill |
| Status | map job + QC states to existing chips, not new hex | One vocabulary (§5.5 of the style guide) |
| Media | `--tile-still-w`, `--tile-clip-aspect` | Skeletons and finished tiles share geometry |

### 2.4 Reuse hierarchy (component over page)

**Primitives already used widely:** `card`, `stack-form`, `field-row`, `tag` / `warn-tag`, `hint`, `muted`, `meta`, `num`, `empty`, `icon-btn`, `modal-close`, `plan-panel`.

**Composites to treat as single components (one partial + one CSS block):**

- `media-tile` — image/clip + verdict + actions (anchors, approve grid, refs, stills)
- `job-chip` / queue row — status vocabulary
- `section-head` — title + actions
- `finding-row` — QC atom
- `still-pending` — loading media slot

**Rule for new CSS:** if the selector is a page name (`#storyboard…`, `.models-…`) and the visual is a card or tag, stop and use the primitive. Page sections stay for layout only.

### 2.5 htmx and tokens

Fragment responses must ship the **same classes** as full pages. Tokens live in the global stylesheet; partials never inline a second palette. `hx-swap` targets are components (`#scene-12`, `.media-strip`), not “the whole main with a unique class.”

---

## 3. Consistent iconography

### 3.1 What is already decided

- Shared SVG glyphs via `_macros.html` (`_glyph`, `glyph_close`, `glyph_save`, `glyph_delete`, `glyph_edit`).
- **Every** `<dialog>` dismiss control is `modal_close()` — ghost X, class `.modal-close`. Not accent circle, not the word “Close” mixed with ×.
- Confirm actions stay labeled words: Cancel / Delete.
- Icon buttons: `.icon-btn` + `title` + `aria-label`; danger uses `.danger-icon`.

### 3.2 Workstation rules

1. **One stroke system.** Current lucide-like 24 viewBox, stroke 2, round caps — keep it. Do not mix filled Material icons on one page and outline on another.
2. **Macros only for chrome actions.** Close, save, delete, edit, help (`?`), cancel job, open log — go through `_macros.html` or one icon partial. No inline path soup in page templates.
3. **Text labels for irreversible / GPU-cost actions.** Icon-only is fine for dense toolbars (delete cover, open log) when tooltip + aria exist; **Generate / Render / Assemble** stay words (or icon + label via `save_icon`-style).
4. **Status is colour + word, not a unique pictogram per state.** Queued/running/done/failed use the same chip language; optional small spinner only for `running`.
5. **Help vs warning.** `?` opens help dialogs; footguns stay inline (style guide principle 3). Do not hide cost or “this will fail” behind an icon.
6. **No emoji as UI icons.** Adult content is in-scope; the chrome stays neutral so the media carries the charge.

### 3.3 Density without mystery

Operator tools (Resolve, Avid, DAW browsers) use dense icon strips **after** the operator knows the map. For this studio:

- Primary path: labeled buttons.
- Secondary / repeated row actions: icon-btn with identical glyph + title across Library, Playlists, Queue, Anchors.
- If two pages use different trash glyphs for delete, that is a bug.

---

## 4. Density vs scanability for tables of media

### 4.1 Operator goal

Scan many assets quickly, select, judge, act. Not “lean back and browse.” Density serves throughput; scanability prevents mis-clicks on the wrong seed or scene.

### 4.2 Prefer hybrid: dense meta + large enough media

| Surface | Density | Scan aids |
|---|---|---|
| Library / songs list | High (table or compact rows) | Title, duration, status chips, one poster thumb |
| Anchor / still / ref grids | Medium — tiles large enough to judge identity and pose | Fixed tile size, consistent aspect, verdict corner, keyboard focus |
| Storyboard scenes | Medium rows | Scene index, time range, status, strip of refs |
| Jobs queue | High table | Kind, host, status, age, cancel/log icons |
| Set timeline | Spatial, not tabular | Block width = play duration; playhead; not a spreadsheet of frames |

### 4.3 Concrete scan rules

1. **Thumb size floor for judgment.** Identity/pose QC thumbs must be large enough to see face and anatomy exposure. Postage stamps are for *navigation*, not *accept/reject*. If the task is “is this her?”, enlarge the tile or open lightbox — do not shrink to fit more columns.
2. **Align columns.** Status, duration, and actions in fixed columns beat free-form wrapping cards when comparing many songs/jobs.
3. **Zebra / divider only at `--divider` strength.** Strong borders on every cell create noise; use row hover + selected state.
4. **One primary action per row visible; rest in icon cluster or details.** Avoid three equal accent buttons.
5. **Sticky header + sticky job chip.** Context stays while scrolling long queues (topbar already sticky).
6. **Filter before infinite scroll.** Operator knows the song; search/filter beats endless consumer feed.
7. **Selected / focused state must be obvious.** Keyboard stepping through approve grids is core work; `:focus-visible` is not optional (style guide defect #2).
8. **Empty vs pending vs failed.** Three different empty-state classes; same geometry so the grid does not reflow.

### 4.4 Tables of media vs pure tables

Jobs and config: true tables.  
Stills and anchors: CSS grid of `media-tile`.  
Do not force stills into a data table to look “enterprise,” and do not force the job queue into a Pinterest masonry to look “modern.”

---

## 5. What NOT to copy from consumer video sites

| Consumer pattern | Why it fails here |
|---|---|
| Autoplay next / endless recommendation rail | No “discovery”; work is task-driven |
| Large hero / marketing whitespace | Media is content; chrome recedes — but not into 40% empty marketing padding |
| “Continue watching” and engagement metrics | Irrelevant; cost is GPU minutes, not watch time |
| Soft, playful empty states with illustrations | Prefer factual empty + next action (“No refs — generate stills”) |
| Hidden advanced settings behind delight | Cost, host, seed, tier, cancel must stay scannable |
| Optimistic UI that pretends the render finished | Only mark done when job status is terminal |
| Full-screen watch player as default chrome | Lightbox/player is a tool; default is stills + queue + forms |
| Spoiler-blur / safe-for-work gates as product core | Adult content is in-scope; do not build consumer “blur until click” as the main metaphor (access control is tailnet/auth, not thumbnail theater) |
| Skeleton on every navigation for brand feel | Flashy chrome wastes operator time under 1 s loads |
| Infinite masonry of thumbnails without metadata | Unusable for comparing seeds, tiers, hosts |
| Social share, likes, comments | Not a studio surface |
| Onboarding carousels | Single operator; document in help `?` and plan-panels |

Copy **craft** from consumer apps (lazy images, responsive video element, accessible dialogs). Do not copy **product goals** (retention, binge, virality).

Closer analogues: Resolve Media Pool, Avid bin, DAW browser, Frame.io review (for comments on takes), SwarmUI/Comfy job lists — dense, stateful, reversible actions, expensive computes.

---

## 6. Eight concrete recommendations (this stack)

Each fits **Jinja partials + htmx + existing CSS/JS**. No React, no SPA rewrite.

### R1 — One `media-pending` partial for all in-flight slots

Extract `.still-pending` / `.still-skeleton` into a shared partial, e.g. `_media_pending.html`, parameterized by `aspect` (`still` | `clip` | `wide`), `job_id`, and short label.

- Server can render N placeholders when enqueue succeeds (redirect or htmx fragment).
- `app.js` already injects still skeletons on reroll; point both paths at the same markup.
- On job terminal state, fragment swap replaces `#job-slot-{{ id }}` only.

### R2 — Standardize htmx busy affordances

| Case | Mechanism |
|---|---|
| Fragment fetch | `hx-indicator` → shared `.spinner` (playlists already do this) |
| Form submit that enqueues | Disable submit, show plan-panel result, inject pending tiles |
| Multi-minute job | No full-page overlay; update job chip via existing `/queue` poll |
| True navigation/upload | Keep `#page-loading` only for that class |

Add a tiny CSS rule set: `.htmx-request .hide-when-busy` / `.show-when-busy` if not already universal, so every panel does not invent its own.

### R3 — Tokenize type / space / radius in `:root` (four type steps, six spaces, three radii)

Mechanical CSS pass: replace the most common one-off sizes with tokens. Do not redesign colours. This is the highest-leverage fix named in the style guide and unblocks class reuse without a framework.

### R4 — Glyph inventory complete in `_macros.html`

Add any missing chrome glyphs used today as inline SVG (log, cancel, expand, chevron, warning triangle if needed) as macros beside `glyph_delete`. Ban new path blobs in page templates. Keep `modal_close()` as the only dialog dismiss.

### R5 — `media-tile` as the only media grid atom

One partial + BEM-ish modifiers: `--still`, `--clip`, `--anchor`, states `--pending`, `--failed`, `--chosen`. Storyboard refs, approve grid, set shelf thumbs, and library posters all call it. Reduces four CSS sections to one.

### R6 — Status chip component bound to job/QC vocabulary

Single partial: `status_chip(state)` → classes for `queued|running|cancelling|done|failed|cancelled` plus QC pass/reject. Use in job chip, queue rows, scene rows, set render card. Colour once in CSS; never re-hex per page.

### R7 — Keyboard-first focus ring on media grids

Add a global `:focus-visible` for tiles and icon-buttons (2px `var(--accent)` offset). Storyboard/approve flows should move focus after htmx swap to the next pending item or the new candidate — small `app.js` helper, not a framework.

### R8 — Job-linked placeholders instead of page-level “loading…”

When enqueue returns `job_id`, every UI affordance that cares stores `data-job-id` on the placeholder (already done for still reroll). Extend to clip rows and set render blocks:

1. POST enqueue → 200 with job id (JSON or HX-Trigger).
2. Client or response OOB swap inserts pending tile(s).
3. Queue poll or `HX-Trigger: jobCompleted` refreshes only subscribed slots.
4. Failure path swaps pending → failed tile with log link.

This keeps multi-job concurrency honest on one song page (refs + clips + anchors without mutual full reload).

---

## 7. Fit check against existing principles

| Style guide principle | Practice here |
|---|---|
| Media is the content | Skeletons match media geometry; chrome stays thin |
| Say the cost before the click | plan-panel + no fake “instant” completion |
| Warning stays on the page | Fail tiles and inline footguns, not toast-only |
| One state vocabulary | R6 status chips = jobs.py states |
| Never promise what the renderer won’t produce | No optimistic final stills |
| Presentation not load-bearing | Status text in HTML, not only colour |

---

## 8. Explicit non-goals

- React / Vue / SPA migration for “modern” loading libraries.
- Consumer recommendation algorithms or watch-party features.
- Pixel-perfect clone of Resolve/Premiere (web is a review + queue surface; heavy NLE stays off-box).
- Expanding CSS to a full design-system site; tokens + partials are enough for one operator app.
- Editing `studio/*.py` for this research note alone.

---

## 9. Suggested implementation order (when someone lands work)

1. R3 tokens (CSS-only, low risk).  
2. R4 glyphs + audit `modal_close` (already mostly true).  
3. R1 + R8 pending partial wired to stills (path of least resistance — code exists).  
4. R6 status chips on queue + job chip.  
5. R5 media-tile consolidation (larger touch surface; do with tests on HTML/JSON parity).  
6. R2 htmx indicator pass across panels.  
7. R7 focus-visible + post-swap focus.  

No commit from this document. Measure with eyes on real sheets and with the existing pytest UI contracts (`T6-A2*`, queue polling, storyboard fragments).
