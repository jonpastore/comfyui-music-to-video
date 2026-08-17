# QA Test Report: Playlist interface (Playwright)

**Date:** 2026-08-17  
**Target:** http://100.103.148.120:8000 (live Meow P Studio, no auth)  
**Tooling:** Playwright sync API, `chromium.launch(channel="chrome", headless=True)`  
**Playlist under test:** Street Cats (`#playlist-2`, 12 songs, ~116 sheets)  
**Screenshots:** `/tmp/meowp-pw/`  
**Destructive actions:** none (no render enqueue, no anchor generate, no playlist/sheet delete)

---

## Failures first

| # | Failure | Severity |
|---|---------|----------|
| **F1** | **Save album look while Anchors is open leaves Anchors stuck on “Loading sheets…”** | **Real product bug** |
| F2 | First-pass Anchors tab automation after save saw empty body (symptom of F1, not a separate UI gap) | Follow-on |
| F3 | Song row `<a>` click from open card timed out on visibility once; direct `/songs/3` load is fine | Test/harness noise, not a product defect |

### F1 detail (the one that matters)

`playlist_hx` posts to `closest .playlist-body` with `innerHTML` swap.  
`app.js` chrome restore (`htmx:beforeSwap` / `htmx:afterSwap`) re-opens previously open folds by setting `details.open = true` **without** firing a `toggle` event.

Anchors fold is:

```html
hx-get="/playlists/{id}/anchors" hx-trigger="toggle once"
```

So after Save album look:

1. Body is replaced with placeholder `<p class="muted">Loading sheets…</p>`.
2. Chrome restore reopens `#fold-anchors-2`.
3. `toggle once` never runs → body stays **Loading sheets…** with zero tiles/tabs.
4. Operator can recover by collapsing then re-expanding Anchors (close/reopen fires `toggle` once).

**Evidence:**

- Immediately after save with Anchors open: body text `Loading sheets…`, tier tabs = 0  
  → `/tmp/meowp-pw/303-anchors-stuck-after-save.png`, `/tmp/meowp-pw/203-anchors-post-save-final.png`
- After user close/reopen: content loads (pose-need + R/XXX tabs)  
  → `/tmp/meowp-pw/304-anchors-after-reopen.png`
- Save with Anchors closed, then first open: loads fine  
  → `/tmp/meowp-pw/302-anchors-first-open-after-save.png`
- Profile POST itself is fine (200, full card HTML with `Loading sheets…` placeholder and `hx-trigger="toggle once"`).

**Root cause (code, not fixed in this QA pass):**  
`/home/jon/projects/comfyui/studio/static/app.js` ~797–806 restores open folds; does not re-trigger htmx load for `hx-trigger="toggle once"` folds.  
Macro: `playlist_hx` in `studio/templates/_macros.html` always swaps whole `.playlist-body`.

---

## Environment

| Item | Value |
|------|--------|
| Session | Playwright Chrome channel (no tmux service under test) |
| Service | Live studio `:8000` |
| Browser | `p.chromium.launch(channel="chrome", headless=True)` |
| Cards on /playlists | Catatonic, **Street Cats**, Test |

---

## Test cases

### TC1: Open /playlists — collapsed cards

- **Command:** `goto /playlists`
- **Expected:** Cards present, none open
- **Actual:** 3 cards (Catatonic, Street Cats, Test); `open=0`
- **Status:** **PASS**
- **Screenshot:** `/tmp/meowp-pw/01-playlists-collapsed.png`

### TC2: Expand Street Cats

- **Command:** open `#playlist-2` (htmx `GET /playlists/2/card`)
- **Expected:** Card expands; Songs fold present
- **Actual:** `name=Street Cats songs=12 has_songs_h2=True open=True`
- **Status:** **PASS**
- **Screenshot:** `/tmp/meowp-pw/02-card-expanded.png`

### TC3: Expand every fold

| Fold | Status | Screenshot | Notes |
|------|--------|------------|-------|
| Songs | **PASS** | `03-fold-songs.png` | 12 songs, ~1:00:19; table + transitions |
| Story arc | **PASS** | `04-fold-story-arc.png` | Premise text present |
| Render set | **PASS** | `05-fold-render-set.png` | Audio mix available; partial XXX video notice |
| Album look | **PASS** | `06-fold-album-look.png` | Meow P · Panther · Tiger |
| Anchors | **PASS** (fresh open) | `07-fold-anchors.png` | Pose-need + sheets load on first expand |

### TC4: Album look cast tabs + assertions

- **Command:** click Meow P, Panther, Tiger, World, Add
- **Expected / Actual:**

| Check | Status | Actual |
|-------|--------|--------|
| All five cast tabs clickable | **PASS** | Meow P / Panther / Tiger / World / Add all `active=True` |
| World shows premise/world fields, not character wardrobe | **PASS** | `data-look="world"` visible; premise + world/backdrop/style fields; wardrobe panel not active |
| Identity (not Lead) is the look subtab | **PASS** | Identity look-tabs=3; Lead look-tabs=0 (Lead is cast/role checkbox only) |
| NO “Loading sheets…” under Album look | **PASS** | `found_in_look=False` |
| NO Cover fold | **PASS** | `cover_fold=0 cover_h2=0` (cover is header slot + lightbox only) |

- **Screenshots:**  
  `08-cast-meow-p.png` … `12-cast-add.png`,  
  `13-album-look-world.png`, `14-album-look-identity.png`

### TC5: Save album look — no full reload

- **Command:** click **Save album look** (htmx POST `/playlists/2/profile`)
- **Expected:** URL stays `/playlists`, card stays open (not full document reload)
- **Actual:**  
  `url_before=…/playlists url_after=…/playlists path_ok=True card_open True→True framenavigated=False`
- **Status:** **PASS** for the stated criterion (no full reload)
- **Screenshot:** `/tmp/meowp-pw/15-save-album-look.png`
- **Related defect:** See **F1** — body swap + chrome restore breaks open Anchors fold content (not a full-page reload, but operator-visible breakage).

### TC6: Anchors fold — tabs, Keeper, Fix modal

Re-run after clean expand (not post-save stuck state):

| Check | Status | Actual |
|-------|--------|--------|
| Character tabs All / names | **PASS** | All, Meow P (109), Panther (1), Tiger (2) |
| R / XXX tier tabs | **PASS** | R (43), XXX (69) — counts vary slightly across runs |
| Clothed / Nude family tabs | **PASS** | e.g. Clothed (19), Nude (50) on XXX |
| Pose-need Keeper + Save | **PASS** | 122× `select[name=sheet_id]` + Save buttons |
| Tile Edit → Fix modal | **PASS** | Preview `naturalWidth=1152`; Close is rightmost in `.modal-bar`; help tips on Use this face / Repair a spot / Extend the frame |
| Close Fix without submit | **PASS** | `modal.open=False`; no repair POST |

- **Screenshots:**  
  `101-anchors-reload.png`, `102–105-anchors-*.png`,  
  `201-fix-modal-final.png`, `202-fix-closed-final.png`  
- **First-pass FAIL** (`16–19-anchors-*.png`) was F1 contamination after Save, not missing tabs.

### TC7: Header cover lightbox

- **Command:** click cover on open Street Cats card
- **Expected:** lightbox with replace pencil + delete + Close on the right
- **Actual:** replace forms present, delete present, Close rightmost on `.lightbox-bar`; closes cleanly
- **Status:** **PASS**
- **Screenshots:** `20-cover-lightbox.png`, `21-cover-closed.png`

### TC8: /anchors?scope_value=Street%20Cats

- **Command:** `goto /anchors?scope_value=Street%20Cats`
- **Expected:** Anchors page for that album
- **Actual:** Loads; copy about album pose library / keepers
- **Status:** **PASS**
- **Screenshot:** `22-anchors-page.png`

### TC9: Song page from playlist

- **Command:** open song from playlist table (Back Alley Pussy → `/songs/3`); expand Storyboard; do not enqueue GPU
- **Expected:** Song page usable; storyboard fold openable; no generate/render submitted
- **Actual:** Page loads (`h1=Back Alley Pussy EXPLICIT`); Storyboard fold shows R 28 / XXX 16 scenes; Generate control visible but **not** clicked
- **Status:** **PASS** (direct navigation / expand). Row-link click once failed Playwright visibility (overlay); product link is valid.
- **Screenshots:** `204-song3.png`, `205-song3-storyboard.png`

---

## Summary

| Metric | Count |
|--------|-------|
| Primary checklist steps (1–9) | 9 |
| Primary **PASS** | **8** (step 5 pass on reload criterion; Anchors content regression filed under F1) |
| Product **FAIL** | **1** (F1: Anchors stuck after Save when fold was open) |
| Harness noise | song-link click timeout once |

### What broke

1. **Anchors “Loading sheets…” stuck after Save album look** when the Anchors fold was open. Chrome restore sets `open=true` without re-firing htmx `toggle once`. Collapse + expand recovers.  
   Fix direction (for implementers, not done here): after restoring open state on `#fold-anchors-*`, call `htmx.trigger(d, 'toggle')` or replace `toggle once` with a load that also runs when the fold is programmatically opened / after swap if `open`.

### What did not break

- Collapsed cards, expand, all five folds  
- Album look cast tabs (Meow P / Panther / Tiger / World / Add)  
- World = premise/world fields; Identity subtab; no Loading under look; no Cover fold  
- Save keeps `/playlists` + open card (no full reload)  
- Anchors tabs / Keeper / Fix modal (on a healthy load)  
- Cover lightbox (replace + delete + Close right)  
- Anchors page scope + song storyboard read-only visit  

### Cleanup

- No studio mutations beyond **Save album look** (profile POST; wording already on disk)  
- No GPU jobs enqueued  
- No playlists/sheets deleted  
- Screenshots left under `/tmp/meowp-pw/` for inspection  

---

## Screenshot index

| File | What |
|------|------|
| `01-playlists-collapsed.png` | /playlists closed cards |
| `02-card-expanded.png` | Street Cats open |
| `03-fold-songs.png` … `07-fold-anchors.png` | Each fold |
| `08–12-cast-*.png` | Album look cast tabs |
| `13-album-look-world.png` | World fields |
| `14-album-look-identity.png` | Identity subtab |
| `15-save-album-look.png` | After Save album look |
| `20-cover-lightbox.png` | Cover lightbox |
| `22-anchors-page.png` | /anchors?scope_value=Street Cats |
| `101–105-anchors-*.png` | Healthy Anchors tabs / Keeper |
| `201-fix-modal-final.png` | Fix modal preview + Close right + help |
| `203 / 303-anchors-*-save*.png` | **Stuck Loading after save** |
| `304-anchors-after-reopen.png` | Recovery via close/reopen |
| `204–205-song*.png` | Song + storyboard |
