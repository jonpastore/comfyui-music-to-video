# Missed asks — Anchors / Media (2026-08-18)

Recovered after the generate-form compact. This is the ledger. Status
is what is true on the tree **after** the commit that lands this file.
Do not treat Jarvis or a grind "landed" list as source of truth.

## Why the sticky tiers were wrong

The generate-form screenshot said: put **G / PG-13 / R / XXX as chips
in the sticky bar**, one at a time; remove the form's album select and
the form's tier checkboxes.

What shipped: the form checkboxes went away, and the sticky bar kept
listing **only tiers that already had storyboard coverage**. Catatonic
showed R and XXX. G and PG-13 never appeared, so it did not look like
the picker from the screenshot. Coverage chips ≠ the full tier list.

Fix: `sticky_tiers` walks `tiers.all_tiers()` and fills 0/0 when a board
does not exist. Click sets `page_tier` (`gap_tier=`). That chip is `.on`
even with no storyboard. Roster and Character catalog drop their inner
tier tabs and show only that tier. Album / song / tier chips use
htmx (`#anchors-root`). Tier chips are `<button>` — no `href`, so a
missed htmx bind cannot full-reload the page. When a chip is `.on`,
tagged keepers are that tier's **chosen** sheets (nude thumb on r/xxx),
not the album-wide classification dump. Keeper thumbs are eager:
`loading=lazy` inside `.keeper-rows { overflow:auto }` painted empty
boxes. Sidecar files under `scripts/anchor5` are inside `_media_roots()`
so `/media` is not 403.

## Done on this tree (verify on live after deploy)

- Nav-duplicate `h1` hidden; unique titles stay (song, New Image, …).
- Pose catalog keepers: 3-column cards, large thumbs, same realpath counted once.
- `#pose-preview` Apply this sheet → `POST /api/keepers/apply` (albums × tiers, same path, no byte copy).
- Generate: hidden album, hidden single sticky tier, missing catalog poses, actor identity thumbs, prose behind help.
- Media click-pin, Escape (`holdClosed`), arrows, overlay not intercepting.
- `grok.list_models` 8s timeout + 300s cache.
- Hole chips: **pose unset** + scene count, not `no pose named` + dump.
- Character catalog starts closed.
- Sidecar basenames resolve for keeper urls.
- Anchors in-page: failed-job Retry is `data-job-retry` + `api()` (no
  bare `/jobs/.../retry` form). Clear / pick / delete / upload-pose /
  keeper save / rename stay on the page via `api()` (or htmx on the
  playlist card). Roster badge names the sticky tier (**G needs N**).
  Pose catalog drops the album/tier echo already in `#anchor-scope`.
- Song-page QC chips (P0-4): `#fold-qc` expandable `.finding-chip`
  pills; high-traffic song POSTs are `.song-async` + `initSongPage`.

## Open — do these, do not recommend them

### P0 — product, next slice

1. **Shared keeper is the file, not a copy per album.**
   `classification_json` is still album-scoped. Tag-from-sheets copies
   metadata (and often a second path) into Catatonic. That is 100 sheets /
   43 poses. `anchors.chosen` is still `(album, tier, view, character)`.
   Apply-this-sheet writes more pointer rows; it does not yet make
   classification a shared library.
   **Plan:** classification images key by resolved path (or `anchors.id`).
   Albums and tiers are membership, not copies. `library(album)` = shared
   union album overrides. Tag-from-sheets inserts a pointer. Roster
   "have" uses the same have as pose-gap (a keeper covering the pose),
   not a required chosen row per tier. Promote to `scope_kind=shared`
   when the operator applies to >1 album (T4-25 already exists).

2. **Generate lists every actor the sheet can use.** **built**:
   `form_actor_rows` pads like the gallery — lead + album cast + people
   with a visible chosen sheet (`visible_anchor_sql` / shared by name).
   Catatonic with an empty `characters` table still lists Panther when a
   shared keeper exists (`test_generate_lists_shared_cast_when_album_characters_empty`).
   Thumbs fall back to any chosen sheet, not only `view=front`.

3. **Identity bag is operator photographs of her, not a stranger plate.**
   The white cat on Base images is an `anchor_ref` with
   `role=identity` and no pose name. Filter is not enough — it still
   sits in the bag. Identity lock = chosen `front` for that actor, or
   an `anchor_ref` the operator marked identity **and** that matches
   the actor (character_id / actors stamp). Untagged random uploads
   are not image1. Offer delete on the wrong one.

4. **Song-page QC chips.** **built**
   Song `#fold-qc` lists expandable `.finding-chip` pills (check /
   verdict / class); open body has measured + remedy + Approve
   (`secondary btn-sm`). Full `finding-row` cards stay on `/qc`.
   High-traffic song actions (lyrics / style / refs / clips / render /
   QC / reroll / still approve) are `.song-async` under `#song-page`;
   `initSongPage` posts `Accept: application/json` (no full reload).
   Tests: `test_song_page_high_traffic_forms_are_song_async`,
   `test_scene_reroll_and_approve_are_song_async`,
   `test_song_page_qc_findings_are_expandable_chips_not_cards`.

### P1 — asked, deferred with a speech

5. **Generate seed range (random / min / max / equal / fib).**
   Clip reroll already has this (`reroll_refs.seed_plan`). Generate
   is one base seed +137. Either grow `make_anchor` to take a seed
   plan for `n` candidates, or enqueue `n` jobs from the plan.
   Do not leave a second seed UI that does not drive the renderer.

6. **New Image model dropdown.** **built**
   Wired: Qwen, Flux 2 Dev, Flux 2 Klein 4B, Z-Image Turbo, Krea 2 Turbo
   OSS (`make_t2i.py`). Mage Mango/Guava are not local files.
   Civitai `base` follows the model (Qwen / Flux.2 D / Klein 4B /
   ZImageTurbo / Krea 2). Style LoRA select is family-filtered with
   Anatomy / Popular groups (`seed/lora_pack.json`).
   `test_make_t2i.py`, `test_media_create.py`.

7. **`/media` landing.**
   Keep the two-card chooser. Recent Images stays on New Image.

8. **G 0/100 vs "100 Missing".** **built**
   Roster warn-tag with sticky `gap_tier` reads **G needs N** (tier
   named), not a bare `N missing`. Evidence:
   `test_roster_badge_says_g_needs_n_when_gap_tier_g`,
   `test_anchors_retry_and_roster_badge_are_in_page`.

### P2 — inspect leftovers, not dropped

9. Failed-jobs banner — keep collapsed. Not a defect.
10. Orphan chosen rows with missing files (`pose_14` / `pose_15`) —
    omitted from picker; do not delete without operator say.
11. T7-7 MEASURED / xxx plates — GPU + eye. Hold.

## Hard-stuff implementation order

1. Sticky bar = all builtin tiers (this commit). Generate already
   reads `gap_tier`.
2. Identity bag = her photographs, not a stranger plate (P0-3). Actor list on Generate is built (P0-2).
3. Shared classification pointers + roster have = keeper covering
   the pose across tiers (P0-1). Tests: apply one path to Catatonic
   + Street Cats + R + XXX → one file, N pointer rows, both albums'
   pose-gap close. Mutation: copy the bytes → red.
4. Seed plan on Generate (P1-5) only after (3), unless asked sooner.

## Tests that can go red

- `test_uiux_generate_catalog.py` — all four sticky chips; no form
  album select; apply one file two albums two tiers; **G needs N**;
  failed Retry not a bare `/jobs/.../retry` form.
- `test_uiux_page_chrome.py` — hidden nav h1; Retry + roster badge
  + clear-anchor / pose-keeper `api()` wiring.
- `test_uiux_classification_chips.py` — keeper cards, pose unset.

Mutation for P0-1 (not built yet): `classification.library("Catatonic")`
returning a second copy of a Street Cats path as a new file.
