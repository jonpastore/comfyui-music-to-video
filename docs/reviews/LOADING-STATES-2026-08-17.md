# Loading states audit — render set & job UX

**Date:** 2026-08-17  
**Scope:** `/home/jon/projects/comfyui/studio` — POST render paths, sticky job chip,
htmx indicators, placeholders while a set or clips job is running.  
**Mode:** read-only. No code landed. Implementation deferred (see §3).

---

## 1. What exists today

### 1.1 POST `/playlists/{id}/render`

| Item | Fact |
|---|---|
| Route | `app.py` `render_playlist` ~8783 |
| Form | `_playlist_card.html` lines 112–130 — plain `method="post"`, **no** `hx-*` |
| Body | checkbox `include_videos`; optional tier checkboxes; button **Render set** |
| Work | enqueues `render_set` (audio one job; video one job per selected tier) |
| Response | `303` → `/playlists` (full navigation) |
| Guard | empty playlist / missing mp3 / missing tier video → HTTP 400 |
| In-flight UI | **none** on the card after enqueue: no disable, no busy span, no skeleton list of pending outputs |

Same job kind from the set editor:

| Item | Fact |
|---|---|
| Route | POST `/sets/{id}/render` → `sets_service.enqueue_render` |
| Form | `set_edit.html` ~414–416 — plain post; button disabled only if `not items` |
| Response | `303` → `/sets/{id}` |
| List page | `sets.html` shows finished assets or “Not rendered yet” — no “rendering…” card |

Handler label: `jobs.LABELS["render_set"]` = `"Render playlist set"`. Progress rides the job row / chip, not the set or playlist surface.

### 1.2 Sticky job chip (already the primary loading surface)

| Piece | Path | Behaviour |
|---|---|---|
| Shell | `base.html` topbar | stub `#job-chip` with `hx-get="/queue?chip=1" hx-trigger="load" hx-swap="outerHTML"` |
| Fragment | `_job_chip.html` | status class (`job-chip-running` / `failed` / `idle`), kind desc, `#id · status`, progress/error truncate, `N running · M waiting` |
| Poll | same fragment | `hx-trigger="every {{ queue_refresh_secs }}s"` **only when** active or waiting; `queue_refresh_secs = 0` when idle (no forever poll) |
| Sticky | `.topbar { position: sticky; top: 0; z-index: 40 }` | chip sits in the sticky header on every page |
| Modal | `#jobs-modal` + `_queue.html` | chip click loads `/queue` into modal; modal panel self-polls on the same interval rule |
| Server | `queue_ctx()` | global queue on purpose (one worker); includes recent finished (~300s) |
| Reroll bridge | `applyRerollChip` in `app.js` | when chip kind is `reroll`, paints/clears still placeholders on the song page |

**Verdict:** the job chip is already sticky and is the intended “something is running” affordance for long work, including `render_set` and `clips`. Tests pin this (`test_app.py` sticky chip suite ~5710+).

### 1.3 htmx indicators already in the tree

Pattern: `.htmx-indicator { display: none }` → `.htmx-indicator.htmx-request { display: inline }` plus often `hx-disabled-elt`.

| Surface | Indicator | Notes |
|---|---|---|
| Playlist card open | `.playlist-loading` + spinner | `playlists.html` `hx-get` card on `toggle once` |
| Album look fill | `#fill-busy-{id}` | “reading lyrics and cover…” |
| Propose cast | `#cast-busy-{id}` | “looking at the cover…” |
| Album field wand | `#wand-busy-{fid}` | “reading lyrics…” |
| Nav full page | `#page-loading` overlay | click on topbar links only; not job-related |
| Storyboard tier open | “Loading scenes…” text | no shimmer |
| Song page async forms | disable submitter + `#song-status` / `.save-note` | fetch, not htmx |

**Render set and Render clip forms use none of these.** They are classic form posts (song page intercepts via `initSongPage` and flashes “Queued job #…”, then relies on the chip / `watchJob`).

### 1.4 Placeholders when work is running

| Job kind | In-place placeholder? | Where feedback lives |
|---|---|---|
| `reroll` (stills) | **Yes** — `.still-pending` + `.still-skeleton` shimmer + “rendering…” | painted by `paintRerollPlaceholders`; chip can re-apply via `data-kind=reroll` |
| `refs` / anchor batch | List under “Rendering now” on Anchors | `anchors.html` + SSE batch, not skeleton tiles in the grid |
| `clips` | **No** skeleton in the scene strip | empty “No clips yet” stays empty; clip modal says “queueing… / queued job #”; chip shows “Render video clips” |
| `render_song` (assemble) | **No** | chip + song Recent jobs |
| `render_set` (playlist or set editor) | **No** | chip + `/queue` modal; playlist/set list unchanged until reload after done |
| Playlist “Render set” double-click | **No** client guard | full 303 reload; second click possible before navigation completes |

CSS for still skeletons is reusable (`.still-pending` / `@keyframes still-shimmer` in `style.css` ~1305). There is **no** `.clip-pending` / set-output skeleton.

### 1.5 Clips path (song) — brief

- Scene: `_scene_row.html` `POST /songs/{id}/clips` — plain form, “Render clip”, optional First clip only / refine / QC.
- Song-level: `song.html` “Render video” same endpoint, multipart for optional s2v files.
- With JS: `initSongPage` disables the button for the request, `refreshQueue()`, `watchJob` updates status line; **on done** for non-reroll it only `refreshSong()` (metadata), not a scene strip skeleton swap for clips.
- Chip exposes `data-clips` / `data-n` for **reroll** only in `applyRerollChip`; clips jobs do not drive strip placeholders.

---

## 2. Smallest htmx-friendly placeholders to add

Ordered by cost / value. Prefer reusing chip + existing CSS tokens over new systems.

### 2.1 Do not rebuild: job chip stays the long-poll truth

The chip is already sticky, global, and polls only while busy. Any local placeholder must **complement** it (so the operator knows *where* on the page the result will land), not replace it.

### 2.2 Playlist **Render set** (smallest product gap on that fold)

**Today:** submit → 303 → full `/playlists` reload; chip eventually shows “Render playlist set”; the Render set fold looks idle and the button is clickable again immediately after load.

**Minimal UI (template + thin server, not 10 lines in one partial alone):**

1. **During the POST (htmx-ify the form)** — same pattern as fill/cast:
   - `hx-post="/playlists/{{ id }}/render"` with either redirect follow or a small OOB swap that re-arms the chip via existing `refreshQueue()` on `htmx:afterRequest`.
   - `hx-disabled-elt="find button"`
   - `<span class="htmx-indicator muted" id="render-set-busy-{{ id }}">queueing set…</span>`
   - This only covers the request RTT, not the multi-minute ffmpeg job.

2. **While a `render_set` job is active for this playlist** (needs `queue_ctx` / job args in the card payload):
   - Disable **Render set** with title “set render already in the queue”.
   - Optional one-line under the form: `rendering set…` linking attention to the chip (not a fake media tile).
   - Optional: append a dashed list item in `.tier-links` — skeleton row “output pending” — only if the card is re-fetched or polled; otherwise it goes stale.

**Smallest honest slice:** (1) alone is htmx-local and matches fill/cast. (2) needs card context (`running_render_set: bool` or job id from `args_json.playlist_id`) — outside pure `_playlist_card.html` unless the card route already joins jobs (it does not today).

### 2.3 Set editor **Render this set**

Same as playlist: plain post, button only empty-disabled. Smallest add: post-disable + “queued — watch the job chip” note after enqueue (JS or htmx), and disable while any `render_set` with `set_id` is queued/running. Lives in `set_edit.html` / route context, not the two partials named below.

### 2.4 Clips (scene strip)

Mirror stills, not invent a third system:

- On successful clips enqueue (in `followJob` / clip modal path): append  
  `<figure class="clip-frame clip-pending">` with a re-used shimmer (rename/shared class with `.still-skeleton`) and caption `rendering clip…`, `data-job-id=…`.
- On chip poll done/failed for kind `clips`: clear pending figures and refresh scene row (same as reroll’s `refreshSceneEl`).
- Needs `app.js` + maybe chip `data-kind=clips` handling — **not** a 10-line template-only change.

### 2.5 Skeleton rows (sets list)

If a set has an active `render_set`, show a muted card or list row “rendering…” on `/sets` and on the set edit “Rendered” section. Requires listing jobs by `set_id` in those routes. Higher cost than chip + button disable.

### 2.6 Pattern inventory for implementers

| Pattern | Use for |
|---|---|
| `hx-disabled-elt` + `.htmx-indicator` | short request (queue accept) |
| Sticky `#job-chip` poll | long job status (already done) |
| `.still-pending` shimmer | in-place media that will appear in a strip |
| Anchors “Rendering now” list | multi-job batch on the page that queued it |
| `#page-loading` | full navigation only — **do not** reuse for jobs |

---

## 3. Implementation decision this pass

**No code change.**

Criteria from the task: implement only if the fix is **≤ ~10 lines** and **obviously correct** in **`_playlist_card.html` / `_job_chip.html` only**.

| Candidate | Lines | Verdict |
|---|---|---|
| Chip sticky / poll | already correct | leave alone |
| Disable Render set while job runs | needs job awareness on card | not template-only |
| htmx indicator on Render set form | ~5–8 lines in `_playlist_card.html` | only covers RTT; form still 303s without route/`hx-post` cooperation → incomplete / misleading alone |
| Clip skeletons | `app.js` + CSS | out of allowed files |
| Copy “busy” span with no htmx | dead UI | wrong |

A lone busy span next to a non-htmx form never toggles. Wiring `hx-post` without changing the 303 handler is a behaviour change that wants a test. Out of scope for this audit pass.

---

## 4. Recommended follow-up (when someone implements)

1. **Playlist Render set:** htmx post + indicator + disable button for the request; on afterRequest call `refreshQueue()` so the chip arms without full page reload if the route returns a fragment or 204.  
2. **Server:** expose “active render_set for this playlist/set” on card/edit context; disable Render while true.  
3. **Clips:** still-style pending tiles driven by chip kind `clips` (or `watchJob` done → scene refresh).  
4. Keep chip as global source of truth; do not start a second poller on the playlist card.

---

## 5. File map (absolute)

| Role | Path |
|---|---|
| Playlist render POST | `/home/jon/projects/comfyui/studio/app.py` (`render_playlist`) |
| Set render POST | `/home/jon/projects/comfyui/studio/app.py` (`render_set_route`), `/home/jon/projects/comfyui/studio/sets_service.py` (`enqueue_render`) |
| Job handler | `/home/jon/projects/comfyui/studio/app.py` (`h_render_set`) |
| Job labels | `/home/jon/projects/comfyui/studio/jobs.py` |
| Queue / chip API | `/home/jon/projects/comfyui/studio/app.py` (`queue_ctx`, `GET /queue`) |
| Playlist render form | `/home/jon/projects/comfyui/studio/templates/_playlist_card.html` |
| Playlist shell / card load | `/home/jon/projects/comfyui/studio/templates/playlists.html` |
| Job chip | `/home/jon/projects/comfyui/studio/templates/_job_chip.html` |
| Jobs modal list | `/home/jon/projects/comfyui/studio/templates/_queue.html` |
| Chip shell | `/home/jon/projects/comfyui/studio/templates/base.html` |
| Set render button | `/home/jon/projects/comfyui/studio/templates/set_edit.html` |
| Clips form | `/home/jon/projects/comfyui/studio/templates/_scene_row.html`, `song.html` |
| Still placeholders | `/home/jon/projects/comfyui/studio/static/app.js` (`paintRerollPlaceholders`, `applyRerollChip`) |
| Indicator / skeleton CSS | `/home/jon/projects/comfyui/studio/static/style.css` |

---

## 6. What this review did not do

- Did not run the live studio or enqueue a real `render_set` / `clips` job.
- Did not change templates, CSS, or routes.
- Did not audit every htmx surface outside playlist/set/clips (anchors batch, arc panel, etc.) beyond noting patterns.
