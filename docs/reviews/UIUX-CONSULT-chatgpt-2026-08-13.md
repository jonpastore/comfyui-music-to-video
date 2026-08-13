# 1. Critique: why this still reads as an internal tool

Ranked by impact.

## 1.1 The UI appears organized around implementation areas, not operator tasks
**Evidence**
- Top nav is a flat list of 8 areas: **Library, Anchors, Playlists, Sets, Tiers, Models, Jobs, Config**
- Template sizes suggest several large, operation-heavy pages: `playlists.html` 484 lines, `_anchor_form.html` 467, `song.html` 430, `set_edit.html` 296
- CSS sections are heavily page/domain-specific: `storyboard page`, `models page`, `publishing config`, `set timeline`, `queue panel`, `preflight`

**Why it reads internal**
A polished app usually makes the primary jobs feel primary. Here the information scent is backend/domain-structure scent: songs, anchors, tiers, models, jobs, config all surfaced equally. That is typical of tools that grew route-by-route.

For a single operator making long-running media jobs, the primary mental model is more like:
- find/select source media
- prepare inputs
- verify renderability / preflight
- start work
- monitor work
- review outputs
- assemble/publish sets

The current nav exposes the system’s nouns, not the workflow’s verbs.

## 1.2 The stylesheet structure signals local fixes rather than a reusable design system
**Evidence**
- `static/style.css` is **1247 lines**
- Section headings are mostly page-specific or scenario-specific:
  - `storyboard direction`
  - `a refs tier answers "can this actually render?" before the click`
  - `approve grid: repair, flags, keyboard focus`
  - `tiers: the nudity capability toggle`
  - `anchors: tier tabs, clothed/nude rows, thumbnails`
  - `set timeline`
  - `job status, and the vocabulary of work in flight`
  - `the queue panel, on every page that can start work`
- Most-used classes are mixed semantic and presentational utility-ish names:
  - `muted`, `hint`, `tag`, `card`, `field-row`, `secondary`, `warn-tag`, `btn-sm`, `linkish`, `danger`

**Why it reads internal**
This suggests styling was added as pages were built, rather than components being defined once and reused. Internal tools often accumulate “this box on this page” CSS. Mature applications tend to have:
- fewer page-specific sections
- clearer primitives
- variants of common components
- state rules applied consistently across components

## 1.3 Queue/status is architecturally important, but visually sounds bolted on
**Evidence**
- In `base.html`, every page has:
  - `#queue-panel` that **htmx-loads `/queue` on every page and then polls itself**
- CSS has dedicated sections:
  - `job status, and the vocabulary of work in flight`
  - `the queue panel, on every page that can start work`

**Why it reads internal**
If long-running work is first-class, status should feel integrated into the app shell and local page actions, not as a separate panel inserted above page content everywhere. “A panel that loads itself and polls” is operationally fine, but visually it risks reading as a dashboard widget attached after the fact.

## 1.4 The app likely over-explains locally instead of establishing stable visual conventions
**Evidence**
- Repeated concepts implied by headings:
  - warnings/preflight
  - capability/renderability
  - job state
  - repair/flags
  - expensive/destructive action context
- High usage of `muted`, `hint`, `warn`, `warn-tag`, `meta`, `label-text`

**Why it reads internal**
This often means every page carries its own mini-language and hand-built explanatory patterns. Mature products still explain dangerous actions, but they standardize:
- warning blocks
- cost summaries
- empty states
- section headers with actions
- status chips
- progress rows

The count pattern suggests many ad hoc text treatments rather than a few strong reusable ones.

## 1.5 Page complexity is likely too high in key screens
**Evidence**
- Largest templates:
  - `playlists.html` 484
  - `_anchor_form.html` 467
  - `song.html` 430
  - `set_edit.html` 296

**Why it reads internal**
Large Jinja templates usually correlate with:
- too many responsibilities on one page
- inconsistent local structures
- one-off markup for repeated concepts
- difficult visual hierarchy

I cannot claim specific markup problems without seeing the files, but template size alone is a strong smell.

**UNSURE** - would need to see those templates to identify exact hierarchy failures.

## 1.6 The current token set solves some fundamentals but not enough roles
**Evidence**
- Existing tokens cover:
  - background/panel
  - border/divider/strong border
  - text/muted
  - accent
  - danger
  - elevations
  - motion
- Explicit note in comments that boundary visibility had to be corrected

**Why it reads internal**
This is actually one of the stronger parts. But the token set still appears too small for a mature, consistent language across warnings, success, info, selected state, disabled state, overlays, and media framing. When those roles are missing, pages tend to improvise.

## 1.7 “Dark theme only” can become “all surfaces blur together” unless surface hierarchy is strict
**Evidence**
- Existing comments already mention past issues with near-invisible boundaries
- `--panel-raised` was added because dialogs previously sat on same flat `--panel` as page
- Domain is media-heavy; the UI should recede behind images and video

**Why it reads internal**
Dark internal tools often become a field of similar rectangles. Your own token commentary indicates that already happened once. A mature dark product needs very disciplined use of:
- page background vs app chrome vs panel
- rest vs hover vs selected
- media stage surfaces vs control surfaces
- dividers only where meaningful

## 1.8 Terminology may be accurate but not uniformly legible
**Evidence**
- Domain-specific terms in nav and CSS: Anchors, Tiers, Models, Sets, storyboard, cast, refs, approve grid
- Adult tier is explicit and must remain explicit

**Why it reads internal**
Internal tools often assume operator fluency everywhere. Mature applications still use domain terms, but they group and label them according to task context. “Tiers” and “Models” may be correct, but as top-level peers to Library and Jobs they may expose implementation detail over workflow relevance.

## 1.9 There are likely too many “special rows” and “button rows”
**Evidence**
- Dedicated section: `button rows: separate forms that belong together`
- Existing classes: `field-row`, `stack-form`, `list`, `meta`, `num`, `linkish`, `btn-sm`

**Why it reads internal**
When CSS names include layout patches for forms that “belong together,” it usually means the template structure is compensating for route/form boundaries. That’s common in server-rendered internal apps, but the visual result can feel improvised.

## 1.10 The app probably lacks a strong shell-level visual rhythm
**Evidence**
- `main` max-width 1200, margin auto, padding 1.5rem
- One stylesheet for the whole app
- Large range of page types inferred from section headings

**Why it reads internal**
A polished application usually has a very repeatable shell:
- app header
- page header
- primary content column or grid
- side status / inspector patterns where needed
- stable spacing rhythm

I cannot confirm shell inconsistency without seeing templates, but the current evidence suggests the shell is doing little beyond containing content.

**UNSURE** - would need to see `base.html` and a few representative pages.

---

# 2. Information architecture

## 2.1 Is the 8-item flat nav right?
**Short answer:** no, not as-is.

For an internal single-operator tool, 8 top-level items is not automatically too many. The problem is that they appear to mix:
- primary work objects
- support/reference data
- infrastructure/operations
- admin/config

That flattening makes the app feel like a file cabinet.

## 2.2 What I would group
I would group into four top-level buckets in the shell, even if implemented in plain Jinja/CSS with no JS framework:

### A. Work
Primary production entities.
- Library
- Anchors
- Sets

### B. Runs
Execution and review of long-running work.
- Jobs
- Queue/status entry point

### C. Assets / Setup
Support data that shapes production.
- Models
- Tiers
- Playlists only if they are production inputs rather than outputs

### D. System
- Config

Whether these become actual dropdowns, subnavs, or simply visual grouped sections in the top bar depends on space and current shell markup.

**Implementable in plain Jinja/CSS:** yes.

## 2.3 What I would rename
Based only on the names given:

- **Jobs** → **Runs** or **Render Jobs**
  - “Jobs” is generic and backend-flavoured.
  - “Runs” better expresses work in flight.
  - If the page is queue-centric, **Queue** may be clearer than Jobs.

- **Library** → likely keep
  - It is a normal term and likely clear.

- **Sets** → likely keep
  - Short, distinctive, domain-specific.

- **Playlists** → **DJ Sets** or **Mixes** if that is what they really are
  - You said DJ “sets” mix songs together, so I am not sure how “Playlists” differs from “Sets.”

**UNSURE** - would need to see the semantic difference between Playlists and Sets before recommending final naming.

- **Tiers** → **Content Tiers** if ambiguity exists
  - “Tiers” alone is vague in nav.

- **Anchors** → likely keep if this is the canonical operator term
  - It is domain-specific but short and likely meaningful to the sole operator.

- **Models** → likely keep
  - Assuming model management is a real top-level concern.

- **Config** → **Settings**
  - “Config” reads technical/internal.
  - “Settings” reads more product-like.

## 2.4 What I would remove from top-level if possible
If one item can leave top-level, it is likely **Tiers** or **Models**, depending on frequency.

Reason:
- They sound like supporting configuration/reference entities.
- Top-level should bias toward frequent workflow areas.

**UNSURE** - would need actual usage frequency or route/page traffic patterns.

## 2.5 Proposed nav model
Independent recommendation before seeing your agreed order:

### Option A: grouped topbar, no dropdown dependency
Top bar visually grouped with separators/labels:
- **Work:** Library, Anchors, Sets, Playlists
- **Runs:** Queue, Jobs
- **Setup:** Tiers, Models
- **System:** Settings

This can be done with plain HTML and CSS if the current nav can be edited.

### Option B: reduce to 5 top-level items
- Library
- Anchors
- Sets
- Runs
- Settings

Then expose Tiers, Models, Playlists as local tabs/secondary nav where relevant.

This is cleaner, but only if those areas are not daily entry points.

---

# 3. Component inventory

Based only on class frequency, CSS headings, and the shell information.

## 3.1 Components the app clearly has

### Shell
- Top app bar / top navigation
- Main content container
- Global queue/status region

### Layout primitives
- Cards (`card`)
- Lists (`list`)
- Stacked forms (`stack-form`)
- Field rows (`field-row`)
- Section headers with actions
- Two-column comparison/info layouts
- Button rows

### Typography / metadata
- Muted text (`muted`)
- Hints (`hint`)
- Labels (`label-text`)
- Metadata rows (`meta`)
- Numeric values (`num`)
- Empty states (`empty`)
- Link-like inline controls (`linkish`)

### Buttons and actions
- Primary button
- Secondary button (`secondary`)
- Small button (`btn-sm`)
- Danger button (`danger`)
- Thumbnail danger button (`thumb-btn-danger`)
- Likely check/toggle controls (`check`)

### Status / feedback
- Tags (`tag`)
- Warning tags (`warn-tag`)
- Warning text/blocks (`warn`)
- Job status indicators
- Preflight summaries
- Error states
- Keyboard focus treatment in approve grid

### Forms
- Standard inputs
- Possibly grouped related forms
- Capability toggles
- Tabbed anchor tiers
- Destructive side-by-side actions

### Media-specific
- Thumbnails
- Thumbnail controls
- Approve/review grid
- Storyboard scene/coverage layouts
- Reference frame tiers
- Set timeline
- Cast/album look boxes
- Modal previews/editors

### Overlay
- Modals/dialogs

## 3.2 Which page-specific CSS sections should collapse into shared components

These headings sound like they should mostly become variants of shared components rather than page-specific styling.

### Collapse strongly into shared components

#### `622: button rows: separate forms that belong together`
Should become:
- `.action-row`
- button group spacing/alignment rules
- form section footer pattern

Delete page-specific special casing.

#### `661: section headers with their own actions`
Should become:
- reusable section header component
- title + meta + actions layout

#### `729: modals`
Keep as shared overlay component.

#### `856: sortable column headings`
Should become:
- reusable table/list header pattern
- sortable control styles

#### `1120: job status, and the vocabulary of work in flight`
Should become:
- status chip/badge system
- progress row component
- run state styles shared everywhere

#### `1207: preflight: what the form will do, before you press it`
Should become:
- reusable preflight/cost/impact callout
- likely one component with info/warn/danger variants

#### `1220: depth and motion`
Keep as shared foundation.

### Likely collapse into reusable content patterns

#### `693: album look / cast: two columns, self-explaining boxes`
This sounds like a generic two-panel comparison/info layout.

#### `610: models page`
Probably should reduce to shared:
- section header
- list/table
- card
- action row
- empty state

**UNSURE** - would need the page to know if any model-specific visual truly exists.

#### `844: publishing config`
Likely mostly standard forms, warning blocks, and section headers.

#### `1184: the queue panel, on every page that can start work`
Should not be a special “panel” component. It should become:
- shell run-status summary
- local run launcher/preflight blocks
- page-level active-jobs list only where relevant

### Keep somewhat domain-specific, but still built from shared primitives

#### `440: storyboard direction: the rules, stated above the box they govern`
Keep the content, but style as standard rule/help block.

#### `460: a refs tier answers "can this actually render?" before the click`
This is a domain-specific idea, but visually it should probably be a standard capability/status card.

#### `477: storyboard page: anchors, coverage, scenes`
Likely domain-specific layout, but should consume shared:
- section headers
- tags
- cards
- media grid
- warning blocks

#### `550: cast`
Potentially a shared roster/list pattern if repeated.

#### `561: approve grid: repair, flags, keyboard focus`
Grid may be domain-specific. Focus rules should be global, flags should use shared tags.

#### `645: tiers: the nudity capability toggle`
Domain-specific content; toggle styling should be shared.

#### `656: anchor candidates: pick and delete side by side`
Should become a generic item-card with action cluster.

#### `777: anchors: tier tabs, clothed/nude rows, thumbnails`
Tabs/rows/thumb styles should be shared; only the content model is specific.

#### `829: sets shelf`
Potentially a generic shelf/grid component.

#### `934: set timeline`
Likely genuinely domain-specific, but should use shared:
- markers
- status chips
- cards
- list row spacing

## 3.3 Shared component set I would formalize
Implementable in CSS + Jinja:

- App shell
- Page header
- Section header
- Card
- Inset/subpanel
- List row
- Form row
- Action row
- Button variants
- Tag/chip variants
- Warning/info/error callout
- Empty state
- Media tile
- Status row
- Progress bar
- Modal
- Tabs
- Split layout / two-column info boxes
- Table/sortable header pattern

---

# 4. Style-guide proposal

All recommendations use plain CSS and Jinja. No dependency, no build step.

## 4.1 Principles
1. **Media first**: UI should frame images/video, not compete with them.
2. **Status always visible**: work state is part of the shell and local action areas.
3. **Warnings stay inline**: no hidden help affordances for footguns.
4. **Fewer surface types**: use clear hierarchy, not many almost-identical boxes.
5. **Delete decorative variation**: rely on spacing, border strength, and typography.

---

## 4.2 Tokens: keep, rename, drop, add

## Keep as-is
These are useful and already thought through:
```css
--bg
--panel
--divider
--border-strong
--text
--muted
--accent
--accent-fg
--danger
--elevation-1
--elevation-2
--motion-standard
--motion-easing
```

## Rename
```css
--border -> DROP or repurpose
```
Reason: you already documented that `--border` was doing the wrong job and is equal to `--divider`. Keeping both invites misuse.

### Proposal
- **Delete `--border`**
- Keep:
  - `--divider` for subtle row separators
  - `--border-strong` for actual boundaries

## Keep but constrain usage
```css
--panel-raised
```
Use only for overlays, active inspector-type surfaces, or selected “live” status containers. Do not spread it widely across normal cards.

## Add colour-role tokens
```css
:root {
  --panel-2: #20242c;
  --panel-3: #262b35;

  --text-soft: #b6bdc9;
  --text-faint: #969ead;

  --accent-muted: color-mix(in srgb, var(--accent) 20%, var(--panel) 80%);
  --accent-line: color-mix(in srgb, var(--accent) 45%, var(--panel) 55%);

  --danger-muted: color-mix(in srgb, var(--danger) 16%, var(--panel) 84%);
  --danger-line: color-mix(in srgb, var(--danger) 40%, var(--panel) 60%);

  --success: #7dcfff;
  --success-muted: color-mix(in srgb, var(--success) 16%, var(--panel) 84%);
  --success-line: color-mix(in srgb, var(--success) 40%, var(--panel) 60%);

  --warning: #e0af68;
  --warning-muted: color-mix(in srgb, var(--warning) 16%, var(--panel) 84%);
  --warning-line: color-mix(in srgb, var(--warning) 40%, var(--panel) 60%);

  --overlay: rgba(8, 10, 14, 0.66);

  --focus-ring: #9ab8ff;
  --focus-ring-shadow: 0 0 0 3px rgba(122,162,247,.28);

  --disabled-opacity: .48;
}
```

Notes:
- I used values compatible with the existing palette and dark theme.
- `--success` is needed for healthy/running/complete states.
- `--warning` is needed for expensive or risky but not destructive actions.
- Muted/line variants avoid inventing many one-off colors.

## Add radius tokens
```css
:root {
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-pill: 999px;
}
```

## Add spacing scale
Use a 4px base for density.

```css
:root {
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
  --space-12: 48px;
}
```

## Add size tokens
```css
:root {
  --control-h-sm: 28px;
  --control-h-md: 36px;
  --control-h-lg: 44px;
}
```

---

## 4.3 Type scale
Dense internal app, dark theme, image-heavy. Keep it restrained.

```css
:root {
  --text-xs: 12px;
  --text-sm: 13px;
  --text-md: 14px;
  --text-lg: 16px;
  --text-xl: 20px;
  --text-2xl: 24px;

  --lh-tight: 1.2;
  --lh-base: 1.4;
  --lh-relaxed: 1.55;
}
```

### Usage
- App/nav/body default: `14px / 1.4`
- Form labels, meta, tags, table headers: `12–13px`
- Section titles: `16px`
- Page titles: `20px`
- Only major views use `24px`

### Recommendation
Delete gratuitous font-size variation. Mature internal apps often improve by using fewer sizes, not more.

---

## 4.4 Density
Target: **compact but breathable**.

### Rules
- Default control height: `36px`
- Dense controls allowed at `28px` only for thumbnail/tool rows
- Card padding: `16px`
- Tight list-row padding: `10px 12px`
- Page section gap: `24px`
- Field gap in forms: `12px`
- Label-to-control gap: `6px`

This should fit the “lots of operational data” need without collapsing readability.

---

## 4.5 Surface system
Use only 4 main surface roles:

### 1. Page background
```css
background: var(--bg);
```

### 2. Standard panel/card
```css
background: var(--panel);
border: 1px solid var(--border-strong);
border-radius: var(--radius-md);
```

### 3. Nested inset/subpanel
```css
background: var(--panel-2);
border: 1px solid var(--divider);
border-radius: var(--radius-sm);
```

### 4. Raised/overlay panel
```css
background: var(--panel-raised);
box-shadow: var(--elevation-2);
border: 1px solid var(--border-strong);
border-radius: var(--radius-lg);
```

### Delete
- Any “card” variant that differs only slightly in background without meaning
- Borders using `--divider` where actual boundaries are intended
- Extra shadows on ordinary content cards

---

## 4.6 Button system
Keep simple.

### Primary
```css
background: var(--accent);
color: var(--accent-fg);
border: 1px solid transparent;
height: var(--control-h-md);
padding: 0 14px;
border-radius: var(--radius-sm);
font-size: var(--text-md);
font-weight: 600;
```

### Secondary
```css
background: transparent;
color: var(--text);
border: 1px solid var(--border-strong);
```

### Danger
```css
background: var(--danger-muted);
color: var(--text);
border: 1px solid var(--danger-line);
```

### Tertiary / link-like action
For current `linkish`, prefer a real text-button style:
```css
background: transparent;
color: var(--accent);
border: 0;
padding: 0;
height: auto;
```

### Small
```css
height: var(--control-h-sm);
padding: 0 10px;
font-size: var(--text-sm);
```

### What to delete
- Any button variant distinguished only by tiny size/color differences with no semantic meaning
- `linkish` as a vague catch-all if it is being used for multiple unrelated affordances; replace with either text action or actual link styling

**UNSURE** - would need to see current selectors to say exactly what to replace.

---

## 4.7 State styles

### Hover
Use light, not flashy changes.
```css
transition:
  background-color var(--motion-standard) var(--motion-easing),
  border-color var(--motion-standard) var(--motion-easing),
  color var(--motion-standard) var(--motion-easing),
  box-shadow var(--motion-standard) var(--motion-easing);
```

- Primary: slightly darker via opacity/filter or mixed background
- Secondary: border shifts to `--accent-line`
- Card/list row hover: only on interactive rows; use subtle background lift to `--panel-2`

### Active/pressed
```css
transform: translateY(1px);
```
Only for buttons, very lightly.

### Focus-visible
Global rule:
```css
outline: none;
box-shadow: var(--focus-ring-shadow);
border-color: var(--focus-ring);
```

This is especially important given explicit mention of keyboard focus in `approve grid`.

### Disabled
```css
opacity: var(--disabled-opacity);
cursor: not-allowed;
pointer-events: none;
```
Also remove shadows.

### Loading
No new JS framework needed.

For htmx-driven actions:
- Add a shared loading class/pattern using existing request classes or template-set classes.
- Visual treatment:
  - dim the action region
  - show inline text “Starting…”, “Refreshing…”, etc.
  - do not rely on spinner only

```css
opacity: .72;
```

**UNSURE** - would need to see current htmx attribute usage to specify exact selectors.

### Error
Inline errors should be block-level and persistent until next valid submission.
```css
background: var(--danger-muted);
border: 1px solid var(--danger-line);
color: var(--text);
padding: 12px;
border-radius: var(--radius-sm);
```

### Success/healthy
Needed especially for jobs:
```css
background: var(--success-muted);
border: 1px solid var(--success-line);
```

---

## 4.8 Tags / chips
You already have `tag` and `warn-tag`. Formalize them.

### Base tag
```css
display: inline-flex;
align-items: center;
gap: 6px;
min-height: 22px;
padding: 0 8px;
border-radius: var(--radius-pill);
font-size: var(--text-xs);
line-height: 1;
border: 1px solid var(--divider);
background: var(--panel-2);
color: var(--text-soft);
```

### Variants
- neutral
- accent/info
- success
- warning
- danger

Delete one-off ad hoc status text colors where tags can do the job.

---

## 4.9 Forms
### Standard field block
- label
- optional hint
- control
- optional persistent warning/preflight note
- optional inline error

### Rules
- Labels always above controls for consistency
- `field-row` used only for multi-column related fields
- Hints use `--text-soft`, not full muted grey if too low contrast
- Dangerous consequences shown below or adjacent to submit action in a standard preflight block

### Delete
- Horizontal micro-layouts that save 8px but reduce scannability
- “belong together” rows that are only compensating for separate forms

---

## 4.10 Cards, lists, and rows
### Card
Default outer grouping.

### Inset block
For secondary detail inside cards.

### List row
For jobs, queue items, media metadata rows, etc.

```css
padding: 10px 12px;
border-top: 1px solid var(--divider);
```

First row should not need a special visual hack; use container border and internal separators.

### Delete
- Multiple card-like patterns with nearly identical treatment
- Excess nested boxes

---

## 4.11 Modal style
You already added depth/motion for this. Good direction.

### Rules
- Backdrop uses `--overlay`
- Modal surface uses `--panel-raised`
- Widths constrained by content type, not full-screen by default
- Header/footer sticky only if content is long

### Motion
- fade + slight lift
- 200ms is appropriate
- no bounce, no scale theatrics

---

# 5. The long-running-work problem

## 5.1 Core critique
A polling queue panel at the top of every page is mechanically understandable, but it makes the app feel like pages plus a status widget. Since long-running work is central, status should exist at three levels:

1. **global shell level** — is anything active?
2. **page level** — what work from this object/view is active?
3. **action level** — what will this button start and how expensive is it?

## 5.2 Proposed model

## A. Replace “queue panel bolted to top of every page” with a shell status bar
In the app shell, near the top bar or directly under it, keep a compact persistent **run strip**.

Contents:
- active count
- queued count
- failed count if nonzero
- current fleet signal, if available
- one-line current activity summary

Example structure idea, not selector claim:
- “3 running · 7 queued · 1 failed”
- “Latest: Render clip for Song X on GPU-02”

This can still be htmx-polled. The difference is presentation:
- always present
- one-line unless expanded
- part of shell chrome, not page content

**Implementable with Jinja + htmx + CSS:** yes.

## B. Make the full jobs view the “control tower”
The dedicated Jobs/Runs page becomes the full detailed list:
- grouped by Running / Queued / Blocked / Failed / Complete recent
- each row shows:
  - job type
  - target object
  - state
  - age / elapsed
  - machine if relevant
  - last update / heartbeat if available
  - cancel/retry where applicable

This is where the polling can be heavier.

## C. Add local “active work for this thing” blocks on relevant pages
On pages that can launch work—songs, anchors, sets, playlists if applicable—show a small local run status block near actions:
- active jobs for this item
- latest completed output
- latest failure
- current preflight summary

This makes the page feel alive without requiring the operator to mentally connect to a separate top panel.

## D. Standardize state vocabulary everywhere
Use one state set across buttons, rows, tags, and summaries:

- Idle
- Queued
- Starting
- Running
- Waiting / Blocked
- Succeeded
- Failed
- Cancelled

Delete synonyms if they exist.

**UNSURE** - would need current job state vocabulary to identify exact terms to remove.

## E. Make “is this actually running?” explicit
You said this is first-class.

So each active job row should expose liveness cues:
- queued age
- running elapsed
- last heartbeat / last progress update
- worker/machine name if available
- stale indicator if no update beyond threshold

Without inventing backend fields, I can only say the UI should show these if available.

**UNSURE** - would need to see the `/queue` payload/HTML and backend job data.

## F. Progress presentation
Use 3 levels:

### 1. Indeterminate
For known active work with no measurable percentage.
- animated bar or striped fill is possible in CSS only
- label with elapsed time matters more than fake percent

### 2. Determinate
If real percent exists, show bar + number.

### 3. Milestone progress
For workflows like storyboard → refs → render clips → approve
- show completed/current/blocked step chips
- this can be template-rendered from state

## G. Launch actions should always have preflight attached
Before starting expensive work, the action area should show:
- what artifact(s) will be produced
- which tier/model/settings matter
- estimated scope if available
- whether existing outputs will be replaced
- warning if prerequisites are missing

You already have a `preflight` CSS section. Promote this to a universal action companion component.

## H. Polling behavior should be context-sensitive
No new dependency needed.

Recommended:
- shell run strip polls at a moderate interval only when there are active/queued jobs
- local page run blocks poll only when relevant jobs exist
- idle pages should not show a full queue slab

**UNSURE** - whether current app.js/htmx setup already supports conditional polling.

---

# 6. What to delete

Specific, based only on what you provided.

## 6.1 Delete `--border`
Reason:
- It duplicates `--divider`
- Your own comments explain it failed as a boundary token
- Keeping it invites regression

## 6.2 Delete page-specific styling where a shared component can replace it
Highest-confidence candidates from headings:

- `button rows: separate forms that belong together`
- `section headers with their own actions`
- `sortable column headings`
- `preflight: what the form will do, before you press it`
- at least part of `job status, and the vocabulary of work in flight`
- at least part of `the queue panel, on every page that can start work`

These should be absorbed into shared components.

## 6.3 Delete the idea of a full queue panel as default content on every page
Keep global status, but remove the heavy panel from the main flow on every page.

Reason:
- It competes with page content
- It makes status feel bolted on
- It repeats operational detail where a compact shell-level summary would do

## 6.4 Delete duplicate visual treatments for warnings/hints/meta text
Likely candidates from class list:
- `muted`
- `hint`
- `warn`
- `warn-tag`
- `meta`
- `label-text`

Not delete the concepts, but delete uncontrolled variation between them.
Target:
- one body secondary text style
- one hint style
- one warning block
- one warning tag
- one metadata row style
- one label style

**UNSURE** - would need actual CSS rules to specify exact consolidation.

## 6.5 Delete one-off “small action” patterns unless they map to a standard
Likely:
- `btn-sm`
- `linkish`
- `thumb-btn-danger`

Keep only if each corresponds to a clear reusable variant:
- compact button
- text action
- icon/thumb destructive action

Otherwise remove ad hoc variants.

## 6.6 Delete excess nested panels around media
This is a recommendation, not a verified current fact.

Because the operator is judging images/video constantly, the UI should reduce chrome around media:
- fewer double borders
- fewer nested cards
- less padding around thumbnails/previews where it does not add meaning

**UNSURE** - would need page screenshots or template/CSS markup to confirm current nesting.

## 6.7 Delete top-level nav items that are support structures if they are not primary daily destinations
Likely candidate:
- `Tiers`
Possibly:
- `Models`

Do this only if they can move into secondary navigation or local tabs.

## 6.8 Delete accidental terminology duplication
Potential candidate:
- `Playlists` vs `Sets`

If both are truly distinct, keep both. If not, unify naming.

**UNSURE** - would need definitions/page purposes.

## 6.9 Delete unnecessary motion outside overlays and status transitions
You already identified only a few M3 ideas worth taking. Stay disciplined:
- keep motion for dialogs and status updates
- remove ornamental motion elsewhere

## 6.10 Delete decorative border reliance where spacing can do the job
Given the prior contrast issue, there is a risk of too many “fixed” borders after introducing `--border-strong`.
Use:
- spacing for grouping
- dividers for rows
- strong borders only for real interactive boundaries

Do not turn every panel into a heavily outlined box.

---

# 7. Condensed style-guide proposal

If you want the shortest implementable version:

## Foundation
```css
:root {
  color-scheme: dark;

  --bg: #14161a;
  --panel: #1c1f26;
  --panel-2: #20242c;
  --panel-3: #262b35;
  --divider: #2c313c;
  --border-strong: #636d87;

  --text: #e6e8eb;
  --text-soft: #b6bdc9;
  --text-faint: #969ead;
  --muted: #8b93a1;

  --accent: #7aa2f7;
  --accent-fg: #0d1117;
  --accent-muted: color-mix(in srgb, var(--accent) 20%, var(--panel) 80%);
  --accent-line: color-mix(in srgb, var(--accent) 45%, var(--panel) 55%);

  --danger: #f7768e;
  --danger-muted: color-mix(in srgb, var(--danger) 16%, var(--panel) 84%);
  --danger-line: color-mix(in srgb, var(--danger) 40%, var(--panel) 60%);

  --warning: #e0af68;
  --warning-muted: color-mix(in srgb, var(--warning) 16%, var(--panel) 84%);
  --warning-line: color-mix(in srgb, var(--warning) 40%, var(--panel) 60%);

  --success: #7dcfff;
  --success-muted: color-mix(in srgb, var(--success) 16%, var(--panel) 84%);
  --success-line: color-mix(in srgb, var(--success) 40%, var(--panel) 60%);

  --overlay: rgba(8,10,14,.66);
  --panel-raised: color-mix(in srgb, var(--panel) 92%, var(--accent) 8%);

  --elevation-1: 0 1px 2px rgba(0,0,0,.3), 0 1px 3px 1px rgba(0,0,0,.15);
  --elevation-2: 0 2px 6px rgba(0,0,0,.35), 0 4px 12px 2px rgba(0,0,0,.2);

  --motion-standard: 200ms;
  --motion-easing: cubic-bezier(0.2, 0, 0, 1);

  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-pill: 999px;

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;

  --text-xs: 12px;
  --text-sm: 13px;
  --text-md: 14px;
  --text-lg: 16px;
  --text-xl: 20px;
  --text-2xl: 24px;

  --control-h-sm: 28px;
  --control-h-md: 36px;
  --control-h-lg: 44px;

  --focus-ring: #9ab8ff;
  --focus-ring-shadow: 0 0 0 3px rgba(122,162,247,.28);
  --disabled-opacity: .48;
}
```

## Core patterns
- page bg: `--bg`
- card: `--panel` + `1px solid --border-strong` + `10px radius`
- inset: `--panel-2` + `1px solid --divider`
- row separator: `--divider`
- page gaps: `24px`
- card padding: `16px`
- base text: `14px/1.4`
- labels/meta: `12–13px`
- focus-visible: border + ring
- warnings inline, never hidden behind help icon
- queue/status moved into shell strip + local page blocks

---

# 8. Highest-value next steps

## 1. Refactor the shell first
- replace full top-of-page queue panel with compact shell run strip
- create a page header pattern
- group nav items visually

## 2. Formalize 8 shared components
- card
- section header
- action row
- form field block
- tag
- callout
- status row
- modal

## 3. Consolidate CSS by deleting page-specific sections
Start with:
- button rows
- section headers
- sortable column headings
- preflight
- job status

## 4. Standardize state vocabulary
One language for queued/running/failed/etc.

## 5. Reduce top-level nav exposure of support areas
Move at least one of Tiers/Models out of top-level if feasible.

---

# 9. What I cannot verify from the provided material

- Exact duplicate selectors or classes to merge: **UNSURE - would need `static/style.css`**
- Exact markup patterns to componentize: **UNSURE - would need representative templates (`base.html`, `song.html`, `playlists.html`, `_anchor_form.html`, `set_edit.html`)**
- Whether `Playlists` and `Sets` are distinct enough to keep separate: **UNSURE - would need page purpose or route summaries**
- Current job-state labels and queue fields: **UNSURE - would need `/queue` fragment and related templates**
- Whether `app.js` already handles conditional polling/loading states adequately: **UNSURE - would need `static/app.js`**
