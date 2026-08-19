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

Fix in the same change as this doc: `sticky_tiers` walks `tiers.all_tiers()`
and fills 0/0 when a board does not exist. Click still sets `gap_tier`
and drives Generate.

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

2. **Generate lists every actor the sheet can use.**
   Catatonic's `characters` table is empty, so the form showed Meow P
   only. Street Cats people (Tiger, Panther, Kitty) live as shared
   sheets / other-album rows. Pad `form_actor_rows` the same way
   `_pad_gallery_cast` pads gallery tabs: lead + album cast + people
   with a visible chosen front (`visible_anchor_sql`). Thumb stays
   that person's identity front.

3. **Identity bag is operator photographs of her, not a stranger plate.**
   The white cat on Base images is an `anchor_ref` with
   `role=identity` and no pose name. Filter is not enough — it still
   sits in the bag. Identity lock = chosen `front` for that actor, or
   an `anchor_ref` the operator marked identity **and** that matches
   the actor (character_id / actors stamp). Untagged random uploads
   are not image1. Offer delete on the wrong one.

4. **Song-page QC chips.**
   Playwright only hit `/qc` (small pills). The huge blue boxes were
   on a song with clip findings. Exercise a song that has findings.

### P1 — asked, deferred with a speech

5. **Generate seed range (random / min / max / equal / fib).**
   Clip reroll already has this (`reroll_refs.seed_plan`). Generate
   is one base seed +137. Either grow `make_anchor` to take a seed
   plan for `n` candidates, or enqueue `n` jobs from the plan.
   Do not leave a second seed UI that does not drive the renderer.

6. **New Image model dropdown.**
   Hide unwired rows (Flux 2, Z-Image, Krea). A disabled "on disk ·
   no studio graph" is a fake picker. Wiring Flux 2 is its own graph
   slice.

7. **`/media` landing.**
   Keep the two-card chooser. Recent Images stays on New Image.

8. **G 0/100 vs "100 Missing".**
   Same count, two sentences. Roster tag should read **G needs 100**
   so it names the tier.

### P2 — inspect leftovers, not dropped

9. Failed-jobs banner — keep collapsed. Not a defect.
10. Orphan chosen rows with missing files (`pose_14` / `pose_15`) —
    omitted from picker; do not delete without operator say.
11. T7-7 MEASURED / xxx plates — GPU + eye. Hold.

## Hard-stuff implementation order

1. Sticky bar = all builtin tiers (this commit). Generate already
   reads `gap_tier`.
2. Actor list + identity-front thumbs on Generate (P0-2, P0-3).
3. Shared classification pointers + roster have = keeper covering
   the pose across tiers (P0-1). Tests: apply one path to Catatonic
   + Street Cats + R + XXX → one file, N pointer rows, both albums'
   pose-gap close. Mutation: copy the bytes → red.
4. Seed plan on Generate (P1-5) only after (3), unless asked sooner.

## Tests that can go red

- `test_uiux_generate_catalog.py` — all four sticky chips; no form
  album select; apply one file two albums two tiers.
- `test_uiux_page_chrome.py` — hidden nav h1.
- `test_uiux_classification_chips.py` — keeper cards, pose unset.

Mutation for P0-1 (not built yet): `classification.library("Catatonic")`
returning a second copy of a Street Cats path as a new file.
