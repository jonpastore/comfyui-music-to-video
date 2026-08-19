# TRD-4 · Character anchors and identity

Status: **rewritten 2026-08-17** for Jarvis **#529** (D1–D10). The 2026-08-13
text still owns who she is and T4-1…T4-20. This pass puts the classified
pose library in sqlite, keeps gap-from-board from binding, and retunes
T4-11 colour to the operator photographs. Source of truth:
`docs/PROMPT-2026-08-15-PIPELINE-REQUIREMENTS.md`.

Acceptance criteria are `T4-n` and each **can fail**. Every claim below was
checked against the code before it was written down; where the brief that
prompted this document was wrong, §1 says so rather than inheriting it.

---

## 1. What was reported, and what the code actually does

The brief listed three problems. **One and a half of them are real**, and the
correction matters because fixing what is already fixed is how a session is
spent producing nothing.

| reported | actual |
|---|---|
| "Selecting nothing for **Tiers** silently falls back to G" | **FALSE.** POST raises 400 *"select at least one tier"*. The form used to pre-tick G (or last-used); it no longer does (`T4-3`). |
| "Selecting nothing for **Views** silently falls back to front-clothed" | **FALSE.** POST raises 400 *"select at least one view"*. The form no longer pre-ticks front. |
| "Saving a prompt does not verify the text matches the tier's policy" | **TRUE.** `save_anchor_prompt` runs `tiers.check_text` (the minor screen) and `tiers.check_override` (the anti-jailbreak screen) and **nothing compares the text against the selected tier's own policy**. Explicit wording saves cleanly under G. |
| "Positive prompts still contain negation" | **TRUE, and it is a documented exception rather than an oversight.** `make_anchor._NEGATION_ALLOWED = ("DEFAULT_BODY",)` permits it, and `DEFAULT_BODY` ends *"with no lighter or differently-toned patches anywhere"*. |

**How XXX wording reached the G tier is therefore still unexplained**, and this
document does not invent a mechanism for it. What is proven is that nothing
stops it being *saved* there (§3). Whether it was also *rendered* there needs
the reproduction in `T4-13`.

## 1a. The boundary with TRD-7

`docs/TRD-7` was written the same day and the two must not drift into one
subject. **TRD-4 owns who the character is and how the positive prompt is
built; TRD-7 owns how many different sheets of them you can ask for and whether
they stay the same person.** Three criteria here have their anchor-path
realisation there, and neither document restates the other:

- `T4-12`'s slot naming → `T7-10`. Verified independently 2026-08-13:
  `make_anchor.py:339` names the third image `f"reference {i + 3}"`, and
  `cast_clause` then writes *"The character in image 3 is reference 3"* into a
  prompt whose composite clause says every reference is the same character. The
  mechanism exists to tell two anchors apart in a duet frame; pointed at one
  character's three photographs it **asserts a second person**.
- `T4-6`'s tier gating → `T7-2`. `NUDE_VIEWS` is two hand-kept copies
  (`app.py:135`, `make_anchor.py:167`), so a nude view added to one renders at
  `g` with the album's wardrobe wording — a tier violation produced by an
  omission, on the render path rather than the save path this document guards.
- `T4-13`'s lighting lock → `T7-14`, which makes `BACKDROP` a versioned prompt
  so the lock has somewhere to live per album.

## 2. No silent defaults

- `T4-1` Generating with **zero views selected** is refused, naming the control.
  Today it renders `front`. The tier half of this already passes and stays
  asserted, because a criterion that only covers the broken half stops covering
  the fixed one the moment somebody edits it.
- `T4-2` The tiers and views used are **exactly the checkboxes as they stand
  when the button is pressed** — asserted by a differential: submit two
  selections and confirm two different sets of jobs, rather than confirming the
  fields post.
- `T4-3` **No fallback to `G`, `pg13`, `r`, `xxx`, `front`, `back`, `clothed` or
  `nude` exists anywhere on the anchor path.** A test enumerates the routes and
  asserts each refuses an empty selection. *Mutation: restore any `or ["front"]`
  → red.*
- `T4-4` The refusal names which control is empty. "Select at least one tier"
  and "select at least one view" are different messages, because a form with two
  empty multi-selects and one generic error is a form you fix twice.

## 3. Tier policy is checked on every save

The screening that exists is real but answers a different question. `check_text`
asks *"does this mention a minor"*; `check_override` asks *"is this trying to
instruct the model about its own rules"*. **Neither asks "is this text allowed at
the tier it is being saved under".**

- `T4-5` Saving a prompt runs **the same guardrail the render runs**, against
  the selected tier. Not a second implementation: whatever
  `tiers.compose_guardrail(tier, album)` says the tier permits is what the save
  is checked against, so the two cannot disagree.
- `T4-6` **Explicit sexual content or full nudity saved under `g` or `pg13` is
  refused**, with a message naming the tier and the clause it violates. This is
  the criterion the reported defect asks for and it fails today.
- `T4-7` The same text saved under `r` or `xxx` **succeeds**, when those tiers
  are the ones selected. Both directions or the criterion certifies a save path
  that refuses everything.
- `T4-8` The check is on the **stored** text, not the submitted text: read the
  row back and re-screen it. A guard that runs before a transform and not after
  it is a guard on something else.
- `T4-9` Tier wording (`/anchors/tier-wording`) gets the same treatment. It is
  the other free-text path to the same render.

## 4. Positive prompt construction

**Zero negation in any positive text, and the documented exception goes.**
`_NEGATION_ALLOWED = ("DEFAULT_BODY",)` is reasoned — that a denied *property*
of a subject already in frame cannot summon an object the way "no alley" summons
an alley — and the reasoning is defensible. **The measured output disagrees**:
lighter fur patches and two-tone limbs are exactly what the clause denies, at
cfg 4.5 / 28 steps / dpmpp_2m where the negative prompt is live. A reasoned
exception losing to an observation is the observation winning.

- `T4-10` `_NEGATION_ALLOWED` is **empty**, and
  `test_no_positive_prompt_constant_tries_to_negate` walks every constant in
  `POSITIVE_CONSTANTS` with no exemptions. *Mutation: re-add `DEFAULT_BODY` →
  red.*
- `T4-11` **Body colouring is a pure positive assertion naming the parts,
  matching the operator photographs.** Charcoal-brown / espresso — the
  colour of `anchor5/` / the UI pair — not jet-black. "Her entire body
  from shoulders to feet is covered in the same sleek charcoal-brown
  fur as her face, uniform in shade and texture on shoulders, upper
  arms, forearms, hands, torso, hips, thighs, calves and feet." The
  part list is the load-bearing
  half: "identical head to toe" is a summary a model can satisfy by
  averaging, and a list is not. A compose that still says jet-black
  or defers colour to the face fails this (D10).
- `T4-12` **Reference images are named by slot** — "the character in image 1 is
  the identity reference", "image 2 is the wardrobe reference" — while the
  existing composite instruction that every reference shows *the same single
  adult character* stays. Naming slots without it is how three references become
  three people.
- `T4-13` **A positive lighting lock**: "even neutral studio lighting". Green and
  magenta casts are the reported symptom and `BACKDROP` already says "evenly
  lit"; the lock states the colour temperature rather than only the evenness.
  Asserted by a differential on the rendered image's channel balance, not by the
  string being present — this is the criterion that reproduces the reported
  defect and must fail against a current render.
- `T4-14` A nude view **drops the wardrobe wording completely** (already true)
  and **never says "bare skin" on a furred character**. Day 4 measured what that
  contradiction costs: the nude clause asserted bare skin beside "entire body
  covered in jet-black fur", and a fixed-seed sweep watched the model resolve it
  towards skin harder as guidance rose — two of three seeds rendered a human
  body with a cat's head by cfg 7.0.
- `T4-15` An album profile still overrides `identity`, `wardrobe`, `body`,
  `nude_wardrobe` and `anatomy`. The constants are defaults, not policy.

## 5. The negative prompt does not move

- `T4-16` The negative list is unchanged and **nothing from it moves into the
  positive text**. It is already targeted for quality mode, and the whole reason
  the positive prompt has no negation is that absences live here.
- `T4-17` The negative is still dropped in fast mode, and the form still says so.
  ComfyUI skips the negative pass at cfg 1.0, so an absence has nowhere to live
  there at all — which is a further reason quality mode is the default.

## 6. What a front-nude XXX sheet composes to

Required by the brief as a check on the wording. This is the **shape**, to be
regenerated from the code once §4 lands rather than pasted from it — a sample
in a document is stale the moment the constants move.

    <composite: every reference image shows the same single adult character>
    The character in image 1 is the identity reference; the character in
    image 2 is the wardrobe reference.
    <identity, from the album profile>
    <nude_wardrobe, from the album profile — no wardrobe clause at all>
    Her entire body from shoulders to feet is covered in the same sleek
    charcoal-brown fur as her face, uniform in shade and texture on
    shoulders, upper arms, forearms, hands, torso, hips, thighs, calves
    and feet, every part the same single tone.
    <anatomy, from the album profile>
    Even neutral studio lighting.
    <BACKDROP: flat neutral mid-grey, evenly lit, empty, contact shadow>
    <FRONT VIEW framing>
    <tiers.compose_guardrail("xxx"), with PINNED welded on last>

- `T4-18` A test composes this for real and asserts: no negation anywhere, the
  body part list present, both reference slots named, no wardrobe clause, no
  "bare skin", and `tiers.PINNED` last. Six assertions, each able to fail on its
  own.
- `T4-19` **Base images are the operator's photographs.** Generate produces
  *candidates*. A pick marks the candidate that later reference generation
  uses. The Anchors UI must not grow new base images unless the operator
  uploaded them or clicked "Use as reference" on a sheet they already
  accepted. Each candidate tile shows the `T3-31` vision confidence against
  those bases and the prompt, or the named xAI/local scoring failure —
  not "vision unknown". A `fix_anchor` lands a new scored candidate; it
  does not overwrite and does not leave `qc_json` NULL. An approved
  `h_repair` dest still and a standalone refine dest also store
  `qc_json`. Mutation: a
  generate that writes extra `anchor_ref` rows fails this.
- `T4-20` **Exposing nudes are two gates, not one render.** Pose QC
  (`T3-33.b`) is judged on the picture before any anatomy pass. A new
  pose is not an empty latent plus a contradictory source (that invents
  a human face). InstantX Union is pose/depth only and does not emit
  genitals. Vanilla Qwen-Image-Edit 2511 is uncensored and still
  undraws vulva/anus; anatomy is a later inpaint/composite on a pose
  PASS, pigment from the operator photographs, never a photoreal plate
  as image2. A trained 2511 edit LoRA is last resort (roadmap O14 on
  gamingpc) after SNOFS Qwen v1.3 + Inpaint CN fail; it is not this
  criterion and it does not land in `make_anchor.py`. Measured
  2026-08-16: `docs/MEASURED-2026-08-16-POSE-ANATOMY.md`.
  Mutation: compositing anatomy onto a pose-FAIL sheet fails this.

## 6a. The classified library (D1, D2, D10)

Stages A–E from the 2026-08-15 stills loop stay: classify, gap against
**this** board, C1/C2, reclassify, anatomy last on exposing geometry.
Gap reads the board; it does not bind (`T2-51`).

- `T4-21` **`classification_json` lives in the DB**, album +
  `character_id` (NULL = protagonist), versioned document. Same fields
  as `anchor5/image-classification.json`: id, path, kind, view, pose,
  wardrobe, usable, notes, seed. Queryable by view / pose / wardrobe /
  usable. *Mutation: the only store is a sidecar file → red.*
  (`test_t4_21_classification_json.py`)
- `T4-22` **Sidecar files are not the store.** Reading
  `anchor5/image-classification.json` as the album library fails this
  once a DB document exists. Sidecars may seed an import; they are not
  the runtime source. Live empty DB on `/anchors` may call
  `ensure_sidecar_seed` → `import_sidecar` once (default
  `_DEFAULT_SIDECAR` = `~/meowp-studio/anchor5/image-classification.json`
  on the render box); `library()` still never opens a file. Live seed
  depends on `deploy.sh` shipping tracked `studio/seed/image-classification.json`
  to that path — without the ship, empty stays empty.
  (`test_t4_21_classification_json.py`)
- `T4-23` **Gap reads the open song's ceiling board and writes
  coverage holes only.** It does not write `scene_pose_map`. *Mutation:
  gap upserts a map row → red.* (`test_t2_51_classify_cannot_write_map.py`)
- `T4-24` **Ceiling-tier pose generate.** Library sheets are generated
  at the highest ticked tier this run. If the ceiling allows nudity
  (r, xxx), generate clothed **and** nude coverage. If it does not
  (g, pg13), clothed only. No anatomy pass on a g/pg13 ceiling. Never
  invent a higher tier than the ceiling. *Mutation: g-only run emits a
  nude view or an anatomy job → red. Mutation: r ceiling emits clothed
  only and calls coverage green → red.* (`test_t4_24_ceiling_generate.py`)
- `T4-25` **One anchors table, any album can reference.** Operator
  pose uploads (`/anchors/upload-pose`, Assign as sheet) write
  `scope_kind='shared'`, one file under `uploads/anchors/shared/`.
  `chosen_anchor` / pose-plan / the album gallery / the song-page
  chosen summary (`visible_anchor_sql`) union album-scoped rows with
  the shared library. A second album does not copy the file or
  insert a second row. An album-specific chosen sheet still wins
  over a shared one for the same view. Historical Street Cats
  Kitty/Panther/Tiger/ensemble operator plates promote to
  `scope_kind='shared'` via `scripts/import_shared_poses.py
  --promote` when any of: basename in `SKIP_SUBSTR`, a `SHEETS`
  basename, character name Kitty/Panther/Tiger, `render_json.actors`,
  or `render_json.shared_pending` with character_id/actors. Meow P
  `character_id IS NULL` with empty actors stays album-scoped.
  *Mutation: upload-pose writes `scope_kind='album'` and a second
  album cannot resolve the sheet → red. Mutation: assigning the
  same upload copies the bytes into `uploads/anchors/album/<other>/`
  → red. Mutation: a Kitty/SHEETS album row stays album-scoped after
  `--promote` → red.* (`test_shared_anchors.py`)

Use-as-ref / map / image1 only from keepers with `usable≠skip`
(`T7-23`). `usable=skip` never enters a slot.

## 7. Explicitly not building

- No second guardrail for saving. `T4-5` is explicit that the save path calls the
  render path's own composer.
- No IP-Adapter, InstantID or ReActor. `fix_ref.py` does face swap, inpaint and
  outpaint on the model that rendered the frame; a multi-image edit model does
  not need them.
- No new negative prompt. §5.
- No second identity UNET in the studio picker. Pony / Illustrious /
  Krea 2 / Flux t2i are not `role=reference` defaults. When-to-use is
  DDD-4-7 §1a. A Pony anatomy **donor crop** after pose PASS is O12c,
  not a new criterion.

## 8. How every criterion above is to be verified

Same rules as TRD-1..3. A measurement that cannot fail is not evidence; a
refusal or a presence is half a criterion and needs its positive case; and
**when an image looks wrong, look at it** — the identity collapse, the world
that never rendered and the LoRA that did nothing all passed every deterministic
check this project had.

**INHERITED from TRD-6 §0.1** (`T6-A1`…`T6-A4`). Not restated.
`T6-A1`'s named loop here, shared with TRD-7: save operator base photographs,
generate candidates for a named tier+view, pick one, use that sheet as the next
identity lock — over JSON, no HTML. `test_t6_a1_anchor_loop_over_json`.
Named pose sheets (`pose_<asset_id>`, `pose_<asset_id>_nude`) are the
pose library. They do **not** satisfy `chosen_anchor(..., view="front")`.
Generate refs still needs one chosen **identity front** per album+tier;
the song page and storyboard plan-panel say so when the library is full
and that row is missing. The song page **Reference images** card lists
every chosen sheet for that tier in a `.pose-strip` (label via
`viewname`, character name when the sheet is not the protagonist) and
says *N pose sheets · identity front ready* — not a single thumb that
reads *anchor ready*. Generate refs then binds each scene to one of
those sheets (`pose_plan`) and uses it as image2. Clips still consume
approved scene refs, not the strip; the clips form prints approved/scene
counts per tier so a full library is not mistaken for a ready clip pass.
`test_song_page_lists_the_pose_library_not_just_identity_front`,
`test_pose_plan.py`.

### The positive half of each one-sided criterion

Added 2026-08-13. TRD-1, TRD-2 and TRD-3 each carry one of these and TRD-4
through TRD-7 did not, because the audit that produced those three was never run
over these four. Built from the first external review of this document (grok and
chatgpt, independently — `docs/reviews/TRD47-*-2026-08-13.md`), every id checked
against the criteria above.

| criterion | why it is one-sided | its positive half |
|---|---|---|
| `T4-1` zero views refused | a path that refuses everything passes | at least one selected view **produces a job for that view** |
| `T4-3` no fallback anywhere | a deleted anchor path has no fallback | a non-empty tier+view selection is **accepted and drives jobs using exactly those values** (pairs with `T4-2`) |
| `T4-4` the refusal names the control | a path that always refuses can still emit both messages | with both controls populated, submission **succeeds and emits neither** |
| `T4-6` explicit refused at `g`/`pg13` | a save path that refuses everything passes | **`T4-7` is its half** — the pairing was prose and is now mandatory in both directions |
| `T4-7` the same text succeeds at `r`/`xxx` | passes if the save path accepts everything | **`T4-6` is its half.** Both, always, or each certifies the other's absence |
| `T4-9` tier wording, same treatment | passes if `/anchors/tier-wording` is removed or always refuses | explicit wording **refused at `g`/`pg13` AND accepted at `r`/`xxx`** on that route specifically |
| `T4-10` `_NEGATION_ALLOWED` is empty | an empty allowlist is still empty when the composer is deleted | the composed prompt for a real sheet **carries `T4-11`'s assertion at render time**. Confirmed necessary the same day: `4032aba` found `_NEGATION_ALLOWED = ()` true while `app.ALBUM_FIELDS["body"]`'s default still carried the negation and was the one that actually rendered |
| `T4-11` body colouring names the parts | a string present in a constant | **a render differential**: patchy or two-tone fur measurably decreases against the previous negating wording. An image metric, not a string check |
| `T4-12` reference slots are named | a payload carrying names | realised by `T7-10`/`T7-7`: a multi-reference sheet **does not split identity**, measured on the image |
| `T4-14` nude drops wardrobe, never says "bare skin" | both halves are absences; deleting nude views satisfies both | a nude view at `r`/`xxx` **still composes and renders**, fur and anatomy positives present, body not human skin |
| `T4-16` the negative list is unchanged | deleting the negative prompt entirely satisfies "nothing moved out of it" | quality mode **still applies the negative list**, asserted on the submitted graph |
| `T4-17` the negative is dropped in fast mode | deleting it in all modes satisfies "dropped in fast" | **both modes exist and differ**: fast renders without the negative pass, quality with it |

**Not one-sided**, listed so the table is not read as covering everything:
`T4-2`, `T4-5`, `T4-8`, `T4-13`, `T4-15` and `T4-18` already carry a differential
or a named mutation. One caveat worth keeping, raised as UNSURE: `T4-5`'s *"runs
the same guardrail the render runs"* would pass if save and render both
disappeared, so it needs **a save of permitted text succeeding and being
stored**.

### Two things the review found, both since resolved — and both were overstated

Recorded with their corrections, because the corrections are the useful part.

**1. `T4-12`'s slot naming should be scoped to the CAST path, and this document
is the one that moves.**

The review reported a contradiction: `T4-12` and §6 say *"image 2 is the wardrobe
reference"* while TRD-7 `T7-9` says *"`base` is image2 and sets the framing"*.
**It is a conflict between two documents and not in the code** — measured on the
shipped composer, `grep "wardrobe reference"` across `make_anchor.py`,
`build_refs.py` and `app.py` returns **nothing**. `T4-12`'s prescribed wording
was never implemented on the anchor path, so the contradiction never shipped.

**It should not be implemented, and the reasoning is stronger than the criterion
it replaces.** (a) The anchor path's references are an unordered **set of
photographs of one character** — that is `make_anchor`'s documented model of its
input and the entire reason the COMPOSITE clause exists. Naming one of them "the
wardrobe reference" re-imposes the face-then-outfit ordering that was removed
because it made a single photograph carrying both unusable. (b) **A nude view
drops the wardrobe wording**, so the prompt would declare a role for image2 that
the same prompt then contradicts — the bare-skin-versus-fur failure in a new
place, and day 4 measured what that costs.

What the anchor path says instead, and what is true on clothed and nude sheets
alike: *"Image 2 is another photograph of the same character."*

**So slot naming belongs where the slots genuinely hold different people — the
cast path.** `T4-12` and §6 want rewording to that scope, and `T7-9` is resolved
by `d3f2f6a`'s `base=None` rather than by leaving both branches open.

**2. The duet case was guarded, and the guard was thinner than it looked.**

The review reported that nothing asserts a duet can still name two people now
that `T7-10` refuses *"the character in image 3 is reference 3"*. **That was
wrong about the guard and right about the hole.** `build_refs._selfcheck`
already asserted that a named cast member composes to *"The character in image 3
is Nyx: a rival DJ."*, and a test already took one cast member end to end
through `workflow()`.

The real defect was narrower: **every existing check used exactly ONE cast
member**, and with one name and one file there is no slot collision and no
name/file swap available to get wrong. Closed by `7836d6f` with two — each named
by the slot its own file is wired to, asserted as
`{"image2": "nyx.png", "image3": "ghost.png"}`, because asserting only that both
names appear would pass with both wired to one image, which is the blend the
mechanism exists to prevent.

The mutation that proves it is the one worth keeping: make the same-character
form swallow the cast path and the prompt becomes *"Image 2 is another
photograph of the same character. Image 3 is another photograph of the same
character."* — the capability loss stated in full.

---

## 9. Status against the tree, 2026-08-18

#529 library rows. T4-1…T4-20 stay in the 2026-08-15 ledger below.

| criterion | state | commit | evidence |
|---|---|---|---|
| `T4-21` / `T4-22` `classification_json` in DB | **built** | `test_t4_21_classification_json.py`, `test_uiux_classification_chips.py` | sqlite `classification_json` (album + `character_id` NULL=protagonist, versioned). Query by view/pose/wardrobe/usable. Sidecar seeds `import_sidecar` only; `library()` never reads a file. Live empty auto-seed **built**: `ensure_sidecar_seed` from `_anchors_classification_ctx` imports `_DEFAULT_SIDECAR` once when images are empty (Street Cats `/anchors`); missing sidecar stays empty; second call adds no version; a random sidecar path alone still does not paint. Live path is `~/meowp-studio/anchor5/image-classification.json` (parent of `app/`); `deploy.sh` ships tracked `studio/seed/image-classification.json` there (`test_t4_22_deploy_ships_default_sidecar_to_meowp_studio_anchor5`) — omit the ship and live empty stays empty. `/anchors` has no visible page `h1` (nav current is the name; `page_title` is visually-hidden; help sits on the right of `#anchor-scope`, `test_uiux_page_chrome.py`). Sticky `#anchor-scope` album + **every builtin tier** as `<button>` chips (0/0 if no board; htmx `#anchors-root`, no `href`). A selected chip's tagged keepers are that tier's chosen sheets (`test_page_tier_keepers_are_chosen_sheets_and_chips_are_buttons`). Nested roster/gallery tier tabs stay off while a chip is on; Generate lists pose-unset song holes plus unbound coverage (`test_pg13_missing_poses_include_unset_holes_and_actor_thumbs`). Character catalog fold starts closed (no album/tier in the summary). Missed-ask ledger: `docs/MISSED-ASKS.md`. Pose catalog is a `<details>`. Tagged keepers are one row per pose (`classification.group_rows`: thumb + name + clothed/nude counts; `pose_71` slugs off the label); click reuses `#pose-preview` (arrows step). Chip urls go through `resolve_image_path` so sidecar basenames paint. Hole chips say **pose unset** + a scene count, not `no pose named` or a scene dump (`test_unspecified_hole_says_pose_unset_not_scene_dump`, `test_keeper_chips_group_and_resolve_basename`). Song-to-check is inside it. **Tag from these sheets** copies chosen Character catalog keepers (no generate). Keeper chips preview. Hole chips open a picker (clothed/nude + **Generate anchors** fills `#anchor-form` and `requestSubmit`s it). `GET /api/albums/{album}/sheets` skips missing files and returns `actors` (`test_sheets_api_skips_missing_files_and_names_actors`). Mutation: sidecar-only store → red. Mutation: omit chips / skip painted as keeper → red. Mutation: song select before album select → red. Mutation: deploy omits `$DEST/anchor5/image-classification.json` → red |
| `T4-23` gap reads the board, does not bind | **built** | `test_t2_51_classify_cannot_write_map.py`, `test_uiux_classification_chips.py` | `GET /api/songs/{id}/pose-gap` reads the open song's ceiling board vs `classification_json` keepers (`usable≠skip`) and emits holes only. Classify/gap write zero `scene_pose_map` / `pose_coverage` / refs rows. `/anchors` shows those holes; import closes them without GPU. Mutation: gap upserts a map row → red. Mutation: skip keeper or sidecar-only library closes a hole → red |
| `T4-24` ceiling-tier pose generate (clothed+nude iff r/xxx) | **built** | `test_t4_24_ceiling_generate.py` | `POST /api/songs/{id}/pose-generate` / `pose_generate.generate` plans sheets from pose-gap holes at the highest ticked tier. r/xxx: clothed **and** nude. g/pg13: clothed only, no anatomy job, no nude view. Never invents a higher tier. Studio `anchor` jobs (`source=pose-gap`), not sidecar `batch_edit`. Enqueued `images` are `existing_images` only — sidecar basenames like `tense.jpg` resolve under `scripts/anchor5/` or drop (`test_t4_24_generate_does_not_enqueue_missing_sidecar_names`). `h_anchor` resolves again so Retry of job 343 does not FileNotFound. Mutation: g-only emits nude or anatomy → red. Mutation: r emits clothed only and calls coverage green → red. Mutation: enqueue `tense.jpg` when the file is gone → red |
| `T4-11` / D10 colour (charcoal-brown, not jet-black) | **built** (compose); render differential **harness only; NOT MEASURED** | `test_trd4_unverified.py`, `test_t4_11_body_colour.py` | Compose: `test_t4_11_fresh_album_compose_is_charcoal_brown` — fresh album through `album_profile` contains charcoal-brown and the nine-part list, not jet-black. Mutation: `DEFAULT_BODY` / `ALBUM_FIELDS["body"]` default says jet-black, defers colour to the face, or omits charcoal-brown → red. Differential harness: `qc.t4_11_*` + `test_t4_11_body_colour.py` — missing/unpinned charcoal-vs-negating pair raises NOT MEASURED; synthetic uniform vs two-tone proves region-luma variance can fail; `T4_11_REAL_PAIR_MEASURED` is False. Do not flip without a pinned GPU pair. |
| `T4-20` pose QC before anatomy | **process** | 2026-08-16 | `docs/MEASURED-2026-08-16-POSE-ANATOMY.md`. Studio graph unchanged |
| `T4-25` shared pose library, any album references one row | **built** | `test_shared_anchors.py` | upload-pose / assign write `scope_kind=shared` under `uploads/anchors/shared/`. Two albums resolve the same `anchors.id` and the same path. Album-specific chosen still wins. Song-page chosen summary uses `visible_anchor_sql` so shared Kitty/actor keepers appear. `--promote` flips SKIP_SUBSTR / SHEETS basename / Kitty|Panther|Tiger character / actors-stamped / `shared_pending` album plates to shared; Meow P NULL+empty actors stay album (`test_promote_skip_substr_plates_shared_across_albums`, `test_promote_kitty_sheets_or_character_without_shared_pending`). Mutation: kitty album row remains album after promote → red |

---

## 9. Status against the tree, 2026-08-15 (pre-#529; kept)

A ledger, not an edit to the criteria above: a criterion rewritten to describe
what was built stops being a criterion. Commits are on `main`; `667debc` is
deployed and live on cerberus.

| criterion | state | commit | evidence |
|---|---|---|---|
| `T4-1`..`T4-4` no silent defaults | **built** | prior session | zero views and zero tiers are each refused, each naming its own control |
| `T4-5`..`T4-7` tier policy on save | **built** | prior session | `tiers.check_tier_policy`: explicit wording refused at `g`/`pg13`, accepted at `r`/`xxx`. Both directions |
| `T4-8` screen the STORED text | **built** | `test_trd4_unverified.py` | `test_t4_8_tier_policy_is_re_screened_on_the_stored_row`: policy runs on the stored row, not only the submitted box |
| `T4-9` tier wording gets the same | **built** | `test_trd4_unverified.py` | `test_t4_9_tier_wording_route_gets_the_same_tier_policy`: `/anchors/tier-wording` is the same `check_tier_policy` |
| `T4-10` `_NEGATION_ALLOWED` empty | **built** | prior session + `4032aba` | the walker now covers the studio's `ANCHOR_PROFILE_FIELDS` defaults as well as `make_anchor`'s constants — see below, that widening is what caught the live defect |
| `T4-11` body clause names the parts | **built, and it did not reach a render until `4032aba`** | `4032aba` | see §9.1 |
| `T4-12` references named by slot | **built** | `7836d6f` | the refusal half (a third photograph stops asserting a second person) predates this; the POSITIVE half is the commit — two cast members reach the graph as `image2`→`nyx.png`, `image3`→`ghost.png`, each named by the slot its own file is on. **Rescoped to the CAST path**: the anchor path deliberately does NOT name a slot "the wardrobe reference" — see §9.2 |
| `T4-13` positive lighting lock | **measured on job 257 GPU sheet** | `e214f35` | Job 257 Street Cats xxx `front_nude` seed 5151 (`front_nude_s5151_00001_.png`, sha256 `ac56dc72…238f1b`, 896×1216). Backdrop olive mag **8.06 PASS** (R=144.6 G=143.5 B=126.3, limit 12). Sibling seed 5288 on the same prompt still **FLAGs 14.76** — the criterion can fail on a current render. `BACKDROP` string is not the proof. `T4_13_REAL_SHEET_MEASURED` is True only for those bytes |
| `T4-14` nude view drops wardrobe, never says "bare skin" | **built** | prior session | measured on the composed prompt: wardrobe clause present on `front`, absent on `front_nude` |
| `T4-15` profile still overrides the five fields | **built, and now two more** | `d5526cb` | `backdrop` and `composite` joined `identity`/`wardrobe`/`body`/`nude_wardrobe`/`anatomy` as album-owned, versioned, screened text |
| `T4-16`/`T4-17` the negative does not move | **holds** | — | nothing moved out of the negative; the fast-mode drop is still stated on the form |
| `T4-18` compose a front-nude XXX sheet and assert six things | **built** | `a5527b1` | six independent tests on the real composer (`test_t4_18_*` in `studio/test_trd4_unverified.py`): no negation, body parts, both slots named, no wardrobe, no "bare skin", `tiers.PINNED` last. Deleting PINNED or adding a negation each fails only its own test |
| `T4-19` tile shows confidence or named xAI/local failure | **built** | `80575de` | `test_anchor_qc.py`: `qc_tag` and the candidate tile name the backend; generate still does not write extra `anchor_ref` rows |
| `T4-20` pose QC before anatomy; no empty-latent identity lock; no photoreal image2 | **process** | 2026-08-16 | Operator grind `docs/MEASURED-2026-08-16-POSE-ANATOMY.md`. Studio graph unchanged. O14 train is last resort, not this criterion. |

### 9.1 `T4-11` was true in the constant and false in every render

`_NEGATION_ALLOWED` was emptied and `make_anchor.DEFAULT_BODY` rewritten as a
positive nine-part assertion. **The constant is not what renders.**
`album_profile()` fills every `ALBUM_FIELDS` entry from its default,
`anchor_profile_fields` copies anything truthy into the profile, and
`anchor_from` prefers a profile value over the constant — so for every album in
the database the studio's own default won, and that default still read
*"...identical head to toe, matching the face, with no lighter or
differently-toned patches anywhere"*. The exact sentence the exception was
deleted for.

Measured on a fresh album, composing through the real composer:

    before  front: NEGATION -> "...matching the face, with no lighter or differentl"
            make_anchor.DEFAULT_BODY in the composed prompt: False
            ALBUM_FIELDS body default in it: True
    after   front and front_nude: negations NONE, nine-part clause present: True

Verified again on the LIVE box after deploy: zero negations in the composed
prompt, nine-part clause present.

The guard that would have caught it is now in place — the negation walker covers
the studio's defaults, and asserts `body`, `backdrop` and `composite` are the
SAME STRING as their `make_anchor` constants. Two copies that each pass the same
screen still drift into two different sheets.

Compose is **built**. The one-sided half — a render differential that patchy
or two-tone fur measurably decreases — is **harness only; NOT MEASURED**.
`qc.t4_11_*` / `test_t4_11_body_colour.py` fail closed on a missing pair;
synthetic two-tone vs uniform proves the metric can fail.
`T4_11_REAL_PAIR_MEASURED` stays False until a charcoal-vs-negating GPU
pair is pinned. Peer to `T5-2` / `T3-37` / `T7-7`.

### 9.2 `T4-12` and `T7-9` disagreed about image 2, and this document moved

`T4-12` and §6 said *"image 2 is the wardrobe reference"*; `docs/TRD-7` `T7-9`
said `base` is image2 and sets the framing. The code implemented neither on the
anchor path, so nothing shipped broken — but the resolution matters and it is
that **slot naming belongs to the CAST path only**.

Two reasons. The references are an unordered SET of photographs of one character
— that is `make_anchor`'s documented model of its input and the reason
`COMPOSITE` exists; naming one "the wardrobe reference" re-imposes the
face-then-outfit ordering that was deleted for making a single photograph
carrying both unusable. And **a nude view drops the wardrobe wording entirely**
(`T4-14`), so the prompt would declare a role for image2 that the same prompt
then contradicts — the bare-skin-versus-fur failure in a new place.

The anchor path's wording is *"Image 2 is another photograph of the same
character"*, which is true on clothed and nude sheets alike.

### 9.3 What is still unmeasured, and it is the same thing every time

`T4-13`'s channel-balance harness FLAGs olive/magenta fixtures and PASSes a
grey wall (`qc.LIGHTING_LOCK`). A current GPU sheet is now **MEASURED**: job
257 `front_nude` seed 5151 PASSes 8.06; sibling seed 5288 still FLAGs 14.76.
`T7-7` now has a painted-pair ranking harness (`t7_7_identity_differential`);
the GPU four-image set has not been recorded. Photo-conditioned halves
(Catatonic jobs 244/248; Street Cats jobs 264/268) are on disk from base
photographs; the use-as-ref half has not been rendered. No live
four-image claim. Every other check in this session was on strings,
graphs and schemas.

Jobs 230/231/232 on the production box all finished more than four hours before
the 11:11:38 restart, so **no sheet on that box was rendered by this code**. The
first render after that restart is the first real evidence any of it works.
