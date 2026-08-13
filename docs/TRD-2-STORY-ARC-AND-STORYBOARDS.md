# TRD-2 · Story arc and storyboards

Status: **reviewed 2026-08-12** (draft written earlier the same day). Inputs:
`docs/STORYBOARD_UI_RECONCILIATION.md` (what already exists),
`docs/RECONCILIATION_2026-08-12.md` (the day's measurements),
`docs/EXTERNAL_REVIEW_2026-08-12.md` (outside opinion, verified).

Acceptance criteria are numbered `T2-n` and are written so that each one **can
fail**. A criterion that cannot fail is not a criterion.

**What the review changed**, so the diff is not hunted for:

- Criteria renumbered `AC-n` → `T2-n`, so TRD-1/2/3 can be reviewed together
  without three sets of `AC-1`.
- **§3.4 is new**: the `scene_seconds` decision is taken, and the criterion that
  depended on the old behaviour (was `AC-17`) could no longer fail once the
  behaviour changed. Replaced with one that can.
- **The most important thing the review found: the section floor is in THREE
  places, and only one of them is the formula everyone has been quoting.**
  `grok.validate()` rejects a storyboard with fewer scenes than lyric sections
  and feeds that rejection to the retry loop, so fixing the formula alone would
  regenerate 25 scenes and look like the fix had done nothing. §3.4.
- **§8 is new**: backend/front-end separation. The draft specified textareas,
  modals and a menu order — presentation a mobile client can never use.
- One criterion was doing no work and is now a differential (was `AC-16`).
- The uncatalogued-model gap is now a criterion rather than a note in another
  document.

---

## 1. The problem

Storyboards are written per song, independently. An album has no through-line,
so twelve songs produce twelve unrelated visual stories that happen to share a
character. What is wanted is the opposite: **an album-level arc that acts as
setting and through-line — a musical or an opera — with each song's storyboard
being that song's scene within it.**

Two supporting problems, both measured rather than assumed:

- **`scene_seconds` cannot lengthen a scene.** `n_scenes = max(len(sections),
  ceil(duration / scene_seconds))`. A 25-section song returns 25 scenes whether
  15s or 30s is requested. Nothing in the UI reveals this. **Decided in §3.4.**
- **The reference image does not carry identity — the text does.** A storyboard
  whose `character_reference` is empty renders a stranger in every clip and
  passes every deterministic check while doing it.

## 2. What is NOT in scope, because it already exists

Per-scene timing from `clip_plan`, editable scene prompts
(`EDITABLE_SCENE_FIELDS`), the cast with per-character fields and per-character
anchors (`anchors.character_id`), the unanchored-character warning, and face
swap / inpaint / outpaint (`fix_ref.py`). See the reconciliation. **Do not
rebuild any of it.**

## 3. Data model

### 3.1 The arc is JSON; the Markdown is rendered from it

**Decision.** JSON is canonical. Markdown is generated, never hand-edited — the
shape `build_storyboard.to_md` already uses for storyboards, so there is one
generator and the two cannot drift.

- `T2-1` Writing an arc produces both `<album>_arc.json` and `<album>_arc.md`,
  and the `.md` is byte-identical to `to_md(json.load(the .json))`. A test
  regenerates it and compares.
- `T2-2` Editing the `.md` on disk and re-rendering overwrites the edit without
  warning. This is asserted, not merely documented, so nobody builds a flow that
  depends on hand-edited Markdown surviving.

### 3.2 Arc content

The arc is the album's setting and through-line, not a summary. Required keys:
`setting`, `through_line`, `acts` (ordered, each with `name` and `intent`), and
`songs` — a per-song entry naming which act it sits in and **what that song's
scene contributes to the story**.

- `T2-3` Every song on the album appears exactly once in `arc["songs"]`.
  Generating an arc for an album with a song missing fails loudly rather than
  producing a partial arc.
- `T2-4` `arc["songs"][slug]["contributes"]` is non-empty for every song. An arc
  that does not say what a song is FOR is the thing this feature exists to
  prevent.

### 3.3 Versioning reuses `prompts.py`

`prompts.py` is already a versioned table with usage counts that count renders
rather than loads, and numbers that are not reused after delete. The arc's
generation prompt, each song's storyboard prompt, and (per TRD-3) each QC remedy
prompt are rows in it.

**Do not build a custom git.** Outside review was explicit and unanimous: no
commit trees, no merge engine, no branches. A linear version history with
restore is the whole requirement.

- `T2-5` Editing an arc prompt creates a new version; the previous version is
  retrievable and restorable.
- `T2-6` Deleting a version does not renumber the others.
- `T2-7` A version records which model produced it and when, so a regression can
  be traced to a model change.

### 3.4 Clip length: scenes drive clips — DECIDED 2026-08-12 by Jon

The formula floors scene count at the number of lyric sections:

    n_scenes = max(len(sections), math.ceil(song["duration"] / scene_seconds))

Rear Entrance has 25 lyric sections, so 15s and 30s both returned the identical
25 scenes at 7.83s average, and grok's own `duration_guidance` came back
"4-6 sec" / "7-10 sec" / "9-11 sec". **"Clip length defined by the storyboard"
therefore resolved to 7.83s**, which is not what the decision meant.

**Decided: `scene_seconds` wins. The floor goes.**

    n_scenes = math.ceil(song["duration"] / scene_seconds)

One scene is one clip. A scene longer than the measured render ceiling splits,
and the split is stitched by using **the last frame of clip N as the first frame
of clip N+1**.

The rejected alternative, recorded so it is not re-argued: keep 25 coverage
scenes and merge each clip's several scenes into one motion prompt. A 30s clip is
one continuous camera move, and describing it with four stitched shot
descriptions is how a prompt comes to fight itself — the same class of defect as
the contradictory nude clause, arriving through composition instead of wording.

The cost is accepted and stated: grok writes **against** the lyric section
structure rather than with it, and shot description is coarser.

#### The floor is in three places, not one

Found during this review, by reading `grok.py` rather than the reconciliation's
quotation of it. Changing the formula alone does **not** implement the decision:

| # | where | what it does |
|---|---|---|
| 1 | `grok.py:624` | `n_scenes = max(len(sections), ceil(duration / scene_seconds))` — the formula everyone has been quoting |
| 2 | `grok.py:525` | `validate()` adds a problem: *"only 7 scenes for 25 lyric sections (need >= 1 per section)"* |
| 3 | `grok.py:368-371` | `_system_prompt` instructs the model *"at least {min_scenes} (one per lyric section)"* when the count is not pinned |

(2) is the one that bites. `problems` feeds the **retry loop**, which sends the
failure text back to the model as "fix every problem and resend" — so a 7-scene
storyboard would be rejected and regenerated at 25 scenes, and the formula fix
would look like it had silently done nothing. All three move together or the
decision is not implemented.

The coverage guarantee those rules provided is real and must be replaced rather
than deleted: it is what stopped a section of the song going unrepresented.

**Replacement invariant: the scenes tile the song.** Every second is covered by
exactly one scene, scenes are contiguous and non-overlapping, and each scene
names the lyric sections it spans — so a scene covering four sections is
answerable for all four, which is what a one-per-section rule was approximating.

- `T2-8a` The three sites agree. A test generates at `scene_seconds=30` for a
  25-section song and asserts the result **validates**; leaving the rule at
  `grok.py:525` in place fails it, which is the whole point of naming it here.
- `T2-8b` The scenes tile the song: start times ascend, each scene's end equals
  the next scene's start, the first starts at 0 and the last ends at the song
  duration ± tolerance. An overlap or a gap fails.
- `T2-8c` Every scene names the lyric sections it spans, and every section is
  named by exactly one scene. This is the coverage guarantee that the deleted
  rule was providing, asserted directly instead of through a count.

- `T2-8` A 195.792 s song generated with `scene_seconds=30` returns **7** scenes
  averaging ~28 s, not 25 at 7.83 s. The measured before-and-after case; the old
  `max()` behaviour fails it.
- `T2-9` `scene_seconds` is monotonic: for the same song, a larger
  `scene_seconds` never returns more scenes. The old formula violates this for
  every song with more sections than the requested count.
- `T2-10` A scene longer than the render ceiling produces a chain of clips whose
  count is `ceil(scene_seconds / ceiling)`, and **clip N+1's first frame is
  clip N's last frame**, asserted by extracting both frames and comparing them —
  not by asserting the chain was planned.
- `T2-11` A chained clip is not enqueueable until its predecessor has landed,
  because it needs that frame. The queue expresses "ready" separately from
  "queued"; a chain handed out in the wrong order is the race this criterion
  exists to catch.
- `T2-12` The render ceiling is a **measured constant with its measurement
  recorded**, not a guess. 505 frames / 30.004 s and 1009 frames / 59.949 s both
  rendered on a 24 GB card; the upper limit is untested above that. A ceiling
  raised without a new measurement beside it fails review.
- `T2-13` `CHUNK` is no longer imported as a clip-length constant by
  `build_storyboard`, `build_refs` or `reroll_refs`. Clip count comes from the
  storyboard. A test asserts two songs with different scene lengths produce
  different clip counts from the same duration.

## 4. Generation flows

### 4.1 The arc wand

A wand on the album reads the songs' lyrics and proposes an arc. It opens a
prompt for **what theme or ideas to capture** before it runs — the arc is a
creative decision, and a wand that fires without asking produces a generic one.

Returns two things: the proposed arc, and **a per-song summary of what that
song's storyboard should be**. The second is the point — it is what makes the
storyboards scenes of one story instead of twelve stories.

- `T2-14` The wand refuses to run with an empty theme prompt.
- `T2-15` The proposal is not saved until accepted. Rejecting leaves the previous
  arc untouched, verified by re-reading from disk.
- `T2-16` **The wand never writes to more than one song at a time without
  confirmation.** Outside review: "do not auto-apply an LLM rewrite across every
  song in an album."

### 4.2 The storyboard generation prompt becomes visible and editable

Today the form takes tier, model, `scene_seconds` and `direction`; the prompt
template is neither visible nor editable, and the limits that apply to it are
not shown.

- `T2-17` The generation prompt is returned by the API, defaulted from the tier,
  and editable before generating.
- `T2-18` The limits and guardrails that apply are **part of the same API
  response** as the prompt: the tier's pinned clause, the character/word bounds,
  and the fact that `tiers.PINNED` is added at use time and cannot be edited out.
  Any client can then show them; a client that has to hardcode them will get them
  wrong the first time a tier changes.
- `T2-19` Editing the prompt and generating uses the edited text. Asserted by a
  differential — generate with two different prompts, confirm two different
  storyboards — not by checking that the field posts.

### 4.3 The song storyboard wand

Each song's storyboard gets the same treatment: a versioned, editable
description used as the prompt, and a wand that asks AI to review and improve
it. The arc is passed as context so the scene knows the story it belongs to.

- `T2-20` A storyboard generated with an arc present differs from one generated
  without it, for the same song and prompt. If it does not, the arc is not
  reaching the model and the feature is decorative.

### 4.4 The tier reaches the model

Found 2026-08-12: all 25 scenes of `rear-entrance_xxx.json` carry *"fully
clothed, tasteful and non-graphic, no explicit gesture"* — the **mainstream**
clause — while `tiers.compose_guardrail("xxx")` says *"Explicit adult content is
permitted..."* and even the `r` tier says *"nudity, including graphic nudity, is
in scope"*. The tier never reached grok, so the storyboard is a PG-13 body filed
as xxx. Same defect class as a file whose job is to be true saying something
false.

- `T2-21` A storyboard generated at two different tiers differs in its wardrobe
  and gesture language, asserted by a differential across tiers rather than by
  checking the tier was passed as an argument.
- `T2-22` The tier's own clause appears in the generated storyboard's guardrail
  field, verbatim from `tiers.compose_guardrail(tier)`. A storyboard carrying
  another tier's wording is refused at save.

## 5. The storyboard page

### 5.1 The time meter

- `T2-23` The API reports total scene time against song length, and flags a
  mismatch beyond a stated tolerance.
- `T2-24` **The meter reads the real per-song clip length, not a constant.**
  Asserted by a differential: the same song at two different `scene_seconds`
  reports two different clip lengths. A meter hardcoding 4.8125 s passes a
  presence check and fails this one.
- `T2-25` A song whose scenes do not sum to its duration is flagged **before**
  any render is queued. This is the check that would have surfaced the
  `scene_seconds` defect on its first generation instead of on its hundredth.

### 5.2 Anchors and cast

- `T2-26` The storyboard API returns the album's anchor images per character, so
  any client can show them at the top of the page.
- `T2-27` Each scene carries its reference image alongside its editable scene
  description.
- `T2-28` A scene naming a character with no chosen anchor is flagged before
  rendering. (Already built; regression test only.)

### 5.3 Casting: who needs an anchor

Generation classifies each named figure as **lead**, **extra** or **background**.
Only leads need anchors.

- `T2-29` Every named character in a scene carries a role classification.
- `T2-30` The unanchored warning fires only for leads. An extra without an anchor
  is not a problem and must not be reported as one — a warning that cries wolf
  is a warning nobody reads.

### 5.4 Identity cannot be left empty

- `T2-31` Saving a storyboard with an empty `character_reference` is refused,
  with a message naming the consequence. Measured 2026-08-12: without it, every
  clip renders an ordinary human and every deterministic check passes.
- `T2-32` The refusal message says that identity comes from the **text**, not
  from the reference image. A message that suggests attaching a reference would
  teach the wrong lesson — the one-variable differential (species named in the
  prompt or not, same reference, same seed, same box) is what established this,
  and TRD-3 `T3-28` refuses the same wrong remedy on the QC side.

## 6. Model selection

Every place a model is chosen shows what the candidates are FOR, from
`models.CATALOG`, rather than a bare list.

- `T2-33` The model picker reads `models.renderable(role)`, so a model added to
  the catalogue appears without a UI change.
- `T2-34` A model that is catalogued but unavailable on every reachable backend
  is shown as unavailable rather than offered. `models.where()` answers this, and
  since 2026-08-12 it distinguishes "no box has it" from "no box could be asked"
  — `available is False` is a refusal, `available is None` is a candidate.
- `T2-35` **Every file the installed loaders enumerate is either catalogued or
  explicitly listed as ignored.** Sixteen installed models are absent from
  `models.CATALOG` today, found by diffing each loader enum against the
  catalogue's files, companions and aliases. A test does that diff; a model that
  is neither catalogued nor named as deliberately ignored fails it. Some
  omissions are correct (`ae.safetensors` is a companion under an alias,
  `pixel_space` is built in) — which is exactly why the exception has to be
  written down rather than inferred from absence.

**MEASURED AND CLOSED 2026-08-12: the camera-control LoRAs do not work on
LTX-2.5.** They load without error and they change the output, and they do not
produce the camera motion they are named for.

The differential, with a NEUTRAL prompt so the LoRA is the only possible source
of camera movement — per-second horizontal frame shift, dolly-left LoRA at
strength 1.0, same seed:

    LoRA OFF   0, 0, 0, -3, -4, -4, -3, -1     a locked camera
    LoRA ON   -1, 0, 3, 9, -9, -37, 30, -1     erratic, no direction

The ON run is LESS coherent than the control. This is the failure this test was
shaped to catch: the inner dimensions match at 4096 so it applies, but 2.5 is
int8-quantised and a LoRA half-applied over quantised weights looks exactly like
one that did not help.

A first attempt was worthless and is recorded so it is not repeated: its prompt
said "the camera dollies smoothly to the left", so BOTH arms dollied and the
LoRA would have been credited for the text's work.

So the `camera` field stays prose, and the 19B base model stays uninstalled --
the LoRAs were the only argument for it. Retest only if a non-quantised 2.5
build is ever used; n=1 LoRA at one strength is not a proof about all of them,
but the burden was on the LoRA and it did not clear it.

## 7. Navigation

Menu order, agreed: **Library → Playlists → Anchors → Sets → Jobs → Tiers →
Config.** Make-things first, then the machinery. Sets moves in from the side; it
is the last creative step before publish and is currently orphaned.

- `T2-36` Descriptive prose moves into help modals behind a `?` icon per
  control. **The warnings that must not move stay where they are** — day 8's
  standing rule.
- `T2-37` Playlist rows show the album's arc when one is defined, and a trash
  icon for delete.

## 8. Backend / front-end separation

**A requirement, not a nicety.** All business logic in the backend; the front end
disconnected, so a replacement front end — including mobile — can be built later
against the same API. Everything in §4, §5 and §7 above is therefore specified as
data first and presentation second.

1. Arc generation, storyboard generation, scene editing, casting and the time
   meter live in a service module that imports nothing from FastAPI.
2. Every one of them is a JSON endpoint. The Jinja page is **one client**.
3. A route handler contains no arithmetic, no defaulting and no prompt
   composition. If a route handler decides something, a mobile client cannot.

- `T2-38` The whole storyboard loop is driveable over JSON with no HTML: read
  the arc, propose one, accept it, generate a storyboard, edit a scene, read the
  time meter, list the unanchored leads.
- `T2-39` The HTML page and the JSON endpoint report the same scene count, the
  same clip length and the same warnings for the same storyboard. Two answers
  means two implementations.
- `T2-40` **No template computes anything.** Asserted by a differential: stub the
  service to return known values and assert the page shows those values
  unmodified. A template that sums scene seconds is a second implementation of
  the time meter, and it is the one that will disagree.
- `T2-41` Scene timing has exactly one implementation, `build_song.clip_plan()`.
  Its own docstring says deriving it a second time is the drift it exists to
  prevent: re-rolling clip 17 would silently regenerate a different scene than
  the one that was rejected.

## 9. Explicitly not building

From outside review, all four models agreeing: no custom git for versioning, no
visual node-graph prompt editor, no auto-apply across an album, no collaborative
editing. From this project's own history: no second place that computes scene
timing — `clip_plan` is the one, and every client calls it.

## 10. How every criterion above is to be verified

1. **A measurement that cannot fail is not evidence.** Every criterion above is
   a differential or names the mutation that must break it. Two in the original
   draft were not, and are fixed above.
2. **Then mutate the code and watch the check fail.**
3. **When an image looks wrong, look at it.** The identity collapse, the world
   that never rendered and the LoRA that did nothing were all found by opening
   the pictures, and all three passed every deterministic check.
4. Baseline before and after: `cd studio && python3 -m pytest -q .` (225 at the
   time of writing), `python3 check_integration.py`, and `grep -c "^def test_"`
   — a slice-to-end-of-file replacement once deleted four tests silently, and a
   deleted test does not fail.
