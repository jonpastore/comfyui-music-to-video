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

**A scene is planned as one clip where it fits, and splits into a chain where it
does not.** "One scene is one clip" was the shorthand and it is not the rule:
`T2-10` and `T2-48` both require a long scene to become several clips, so the
shorthand contradicted two of this document's own criteria. The surviving
statement is *scene-driven planning may yield more than one clip per scene, and
never more than one scene per clip.* A split is stitched by using **the last
frame of clip N as the first frame of clip N+1**.

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

**FIXED 2026-08-13; this table is what was found, not what is there now.** Line
numbers are the ORIGINAL ones and have all moved — an audit found every citation
here stale, which is what a document written against a moving file does.

| # | where, as found | what it did | now |
|---|---|---|---|
| 1 | `grok.py:624` | `n_scenes = max(len(sections), ceil(duration / scene_seconds))` | gone; `grok.py:659` is `ceil(duration / scene_seconds)` |
| 2 | `grok.py:525` | `validate()` added *"only 7 scenes for 25 lyric sections"* | `grok.py:541-547`, now conditional on `expect_scenes is None` |
| 3 | `grok.py:368-371` | `_system_prompt` says *"at least {min_scenes} (one per lyric section)"* | `grok.py:368-373`, and only the `else` branch — it never applied when a count was pinned |

**"Three places" was the headline and TWO is the honest number.** Site 3 only
ever ran on the unpinned path, so it was never part of the defect; the
implementation commit says "two live places" and this document said three. Both
were written the same day and neither was reconciled with the other until an
audit put them side by side. Two sites had to move. The third is a different
code path that was always correct.

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

- `T2-8a` **Both live sites agree** — the formula and `validate()`. (This said
  "three sites"; §3.4 retracts that, and a criterion asserting a false inventory
  is one nobody can check.) A test generates at `scene_seconds=30` for a
  25-section song and asserts the result **validates**; leaving the rule at
  that rule in place (now `grok.py:541-547`) fails it, which is the whole point
  of naming it here.
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
  **TRD-2 owns this rule, not the scheduler.** TRD-1 §11 and TRD-3 §9 both
  disown the general wait-state queue, which would have left this criterion
  belonging to nobody. The narrow rule — *a clip whose `depends_on` clip has no
  landed output is not `ready`* — belongs here because TRD-2 is what creates the
  chains. The general scheduler stays deferred, and this criterion must not wait
  for it.
- `T2-12` The render ceiling is a **measured constant with its measurement
  recorded**, not a guess. 505 frames / 30.004 s and 1009 frames / 59.949 s both
  rendered on a 24 GB card; the upper limit is untested above that.
  **Checkable, not a review convention**: the ceiling is stored with the
  measurement that produced it — frames, seconds, card, date — and a test
  asserts the record exists, parses, **and that its frame count IS the ceiling
  the code uses**. The match is the half that matters: a record that merely
  exists and parses can describe a different number than the constant, and the
  two then drift while the check stays green. "Fails review" was the whole
  assertion until an independent pass pointed out that no check can go red on
  it, and a second pass caught that the first fix still let the record and the
  constant disagree.
- `T2-12a` **A scene length is rounded to a LEGAL frame count before it is
  rendered, and TRD-2 owns the rounding.** `T3-7` enforces LTX's 8n+1 latent rule
  on the finished clip, and §3.4 now derives clip length from `scene_seconds`
  and a measured ceiling — but nothing between the two required the REQUESTED
  frame count to be legal. Scene lengths are now arbitrary reals (195.792 / 7 =
  27.97 s), so this is a hole the scene-driven decision opened: whoever converts
  seconds to frames rounds to the nearest `8n+1` at the clip's fps and records
  the rounded length, so the storyboard's arithmetic and the renderer's agree.
  A requested length that is not 8n+1 fails here rather than at the sampler.
#### The song's length is the source of truth, not the scene count

**Decided 2026-08-13 by Jon**, after an audit found this document deciding
against an invariant the code has defended since it was written and never citing
it. `app.clip_count` derives the count from the AUDIO LENGTH and its docstring
records what the alternative cost: *"using scene_count here hid clips 20..40 from
the approve grid and let clip generation start with two thirds of its references
missing"*, because `clip_plan` spreads a 20-scene storyboard across all 41 clips
of a 3:16 track.

**Both survive.** Duration is the dividend; `scene_seconds` is the divisor; the
count is `ceil(duration / scene_seconds)` and is therefore always ours. One
scene is one clip **because grok is asked for exactly that many and `validate()`
refuses any other number** — never because anything counts what came back. The
distinction is the whole reconciliation: the old bug was trusting the MODEL's
scene count, and nothing here does.

- `T2-13` **`CHUNK` has exactly one reader.** `build_song.clip_seconds()` and
  `n_clips_for()` are it; `build_storyboard`, `build_refs`, `reroll_refs`,
  `grok.py` **and `app.py`** each carried their own copy of
  `ceil(duration / CHUNK)`. Five, not the three this criterion first named and
  not the four the audit found. A test asserts no module outside `build_song`
  computes a clip count.
- `T2-13a` **The divisor is not honoured until the RENDERER honours it**, and
  `clip_seconds()` returns `CHUNK` whatever it is passed until then. The
  renderer builds every clip at `LTX25_LEN` frames, and the storyboard form
  defaults `scene_seconds` to 4.0 — so switching the divisor first re-times
  every storyboard to 4.0s clips while 4.8125s ones keep being rendered. That is
  the approve grid expecting a count that never gets produced, which is the
  original bug from the other direction, and a test caught it within a minute.
  Unblocked by `T2-12a` (round to a legal 8n+1 frame count), not before.

### 3.5 Variable clip length — what satisfying §3.4 touches (W1)

§3.4 took the decisions and owns their criteria (`T2-8`…`T2-13`). This section is
what implementing them touches, so the blast radius is written down rather than
discovered. **Seven modules read `CHUNK`** — `build_song`, `build_refs`,
`reroll_refs`, `build_storyboard`, `grok`, `app`, `mixer` — and the three tests
at `test_app.py:1348, 2515, 2582-2583` pin the current invariant **on purpose**:
they are the guard that stopped clip allocation moving when LTX arrived. Replace
each with the invariant that succeeds it; do not delete them.

**F-1 A clip becomes a record, not an index.** `clip_plan()` returns
`(idx, scene_number, start_s, duration_s, model, frames, fps)` per clip and no
caller derives time as `idx * CHUNK` again. `app.py`'s copy is already gone
(§3.4); `build_song.py:328, 364, 410` remain.

**F-2 One legal-length rule serves both models — owned by TRD-5 `T5-10`, cited
here.** The rule about the two nodes' declared steps is a renderer fact and
lived in this section and in `T5-10` in near-identical words; **consolidated
2026-08-13** for the same reason as W1-1 above.

What is TRD-2's: **`T2-12a` rounds a planned scene length TO that rule** before
anything is submitted, so the storyboard's arithmetic and the renderer's agree
and an illegal request fails in planning rather than at the sampler.

**F-3 `refs` keying does not move.** `UNIQUE(song_id, tier, clip_idx, seed)`
stays and `clip_idx` stays an ordinal. What changes is the *length* of clip 17,
never which scene it belongs to.

- `T2-13b` **Every approved reference frame survives a re-plan.** Read `refs`
  before and after re-planning the same storyboard and assert the set of
  approved `(clip_idx, seed)` is identical. This is the criterion that stops the
  work quietly invalidating a human's approvals.

**W1-1 Per-model ceilings — `T2-12` owns the criterion, TRD-5 §5 owns the
values, and this cites them.**

**Consolidated 2026-08-13.** This section carried the LTX and s2v numbers in
full — the 505/1009-frame renders, the 3.0-vs-12.4 s superlinearity, `LEN = 77`
being a choice rather than a node limit — and so does TRD-5 §5, near-verbatim.
TRD-5 §5 already said it owned them (*"the **values** are renderer facts and
belong here"*) and this document kept a copy anyway. **Two copies of a measured
number are free to drift**, and this project's own rule is that the second copy
is the defect rather than the risk — the same finding as twelve criteria for
four facts in `cfe7979`.

What is TRD-2's and stays here: **planning must ASK for a length that respects
whatever ceiling TRD-5 records**, and `T2-12a` rounds that request to a legal
frame count. The numbers themselves are read from TRD-5 §5, never restated.

**W1-2 The audio trim window follows the clip.** `TrimAudioDuration` at
`build_song.py:364` takes `start_index = i * CHUNK, duration = CHUNK`; both
become the clip record's own `start_s` and `duration_s`. This is what makes a
48-second scene condition on its own 48 seconds of music.

**W1-3 The approve grid must not regress**, and this change walks straight back
through the ground that bug was found on. Under W1 the count comes from
enumerating clip records — neither audio length nor scene count.

- `T2-13c` **A song whose storyboard has fewer scenes than clips still shows
  every clip in the approve grid.** The explicit regression test for
  *"using scene_count hid clips 20..40 and let clip generation start with two
  thirds of its references missing"*.

**W1-4 grok's prompt states the quantum and must stop.** `grok._user_prompt()`
(`grok.py:401-431`) tells the model the renderer *"emits fixed clips of exactly
4.8125 s… Nothing shorter or longer can be produced"* and to round every
`duration_guidance` to multiples of it. **This is a prompt, not code**: leaving
it changes nothing that runs and everything that comes back — the same shape as
the section floor, where the formula was fixed and `validate()` quietly
regenerated the old answer. The function is pure; call it directly.

- `T2-14a` For a song planned with variable clip lengths the composed prompt
  contains **no fixed clip quantum**: not the `CHUNK` value in any formatting,
  not *"Nothing shorter or longer can be produced"*, and no instruction to round
  `duration_guidance` to multiples of a constant.
  *Mutation: restore any one of the three sentences → red.*
- `T2-14b` The clip-length text is **derived, not replaced by a new constant**.
  Compose for two songs whose planning differs — different per-model ceilings, or
  one song at two `scene_seconds` — and assert the TIMING blocks differ in their
  clip-length statement. *Mutation: swap 4.8125 for 15.0 and keep the sentence
  shape → `T2-14a` passes and this fails, which is why it is separate.*
- `T2-14c` **What the block is FOR survives.** The prompt still states the track
  length and still requires the scene durations to sum to approximately it —
  `_user_prompt`'s own docstring records why: *"without the duration it invents
  scene times that do not add up to the track"*. *Mutation: delete the TIMING
  block wholesale → `T2-14a` passes and this fails.*

All three assert on the **return value** of `_user_prompt`, which is the string
actually sent. Grepping the source proves the text exists, not that anything
composes it.

**W1-5 One output fps per song.** s2v renders at 16.0 and LTX at 16.8312; today
they are made to agree deliberately (`LTX_FPS = LTX_LEN / CHUNK`), and under W1
and W2 they need not. `mixer.assemble_song`'s fast path is a concat demuxer
whose comment already names *"encoder-parameter drift between clips"* as a
hazard, and mixed fps is a new instance of it.

- `T2-13d` Every clip of one song is normalised to one output fps, asserted on
  the **fps of the assembled file**, not of the plan.
- `T2-13f` **A clip's QC expectation is its NATIVE fps, not the song's.** The two
  differ the moment a song mixes models — s2v renders 16.0 and LTX 16.8312 — and
  normalisation happens at assembly, after the clip exists. TRD-3 `T3-2` compares
  a clip against the workflow that produced it, so the expectation is what that
  workflow asked for; comparing against the song's output fps would flag every
  correctly-rendered clip of the other model. Asserted on a mixed-model song:
  each clip passes its own fps check and the assembled file carries one fps.

**W1-6 Assembly's stated assumption stops being true.** `mixer.assemble_song`
says *"clips are quantised to 4.8125s so the video always overruns"*. The
function is already length-agnostic and clamps with `-t audio_dur`: **keep the
clamp, correct the comment.** Under variable lengths the clips should sum to
approximately the song, so an overrun becomes a signal rather than the norm.

- `T2-13e` A plan whose clip durations miss the track length by more than one
  clip is refused **before render**, not absorbed by the clamp.

**W1-7 Chained clips have a node already.** `LTXVAddGuide`, `LTXVAddGuideMulti`
and `LTXVAddGuidesFromBatch` are installed on cerberus and inject a guide frame
at a given index. `T2-10` requires clip N+1's first frame to be clip N's last —
**do not build frame handoff from scratch.**

## 6a. Per-scene model choice (W2)

**Owned by no document until now.** `build_song.workflow()` already branches on
`video_model` per call; it receives one value for the whole song, and that is
the whole limitation.

- `T2-42` A scene may carry a `video_model`; absent, the render's
  `--video-model` applies.
- `T2-43` It lives in the **storyboard, beside `camera`**. "This shot needs lip
  sync" is a directorial fact about the scene, not a render setting. Editable
  through `EDITABLE_SCENE_FIELDS` and readable over JSON like every other scene
  field.
- `T2-44` A scene naming a model absent from `models.renderable("video")` is
  **refused at save**, naming the scene number and the bad value — not at render
  time and not silently defaulted.
- `T2-45` A mixed-model song is refused **before enqueue** if any named model is
  unavailable on every reachable backend per `models.where()`, respecting its
  three-valued answer: `False` is a refusal, `None` is a candidate. Failing at
  clip 31 of 42 is the outcome this exists to prevent.
- `T2-46` A scene requesting `ref_motion` or `control_video` **pins to
  cerberus**: both load through `LoadVideosFromFolder`, a kjnodes node present on
  cerberus and **absent on gamingpc** (verified against both `/object_info`). The
  rest of the song must still route freely.
- `T2-47` **The differential that proves two renderers ran**: one storyboard,
  two scenes, one marked `s2v` and one left `ltx25`, rendered in a single job —
  and the two output clips carry the models' own frame counts and fps. Asserting
  the plan holds two model names proves the field posts, not that two renderers
  ran.
- `T2-48` Per-scene model and per-model ceilings compose: a 30 s scene marked
  `s2v` splits into s2v-sized clips, a 30 s scene on `ltx25` into 15 s ones, and
  each tiles its own scene exactly (`T2-8b`).

## 4. Generation flows

### 4.1 The arc wand

A wand on the album reads the songs' lyrics and proposes an arc. It opens a
prompt for **what theme or ideas to capture** before it runs — the arc is a
creative decision, and a wand that fires without asking produces a generic one.

Returns two things: the proposed arc, and **a per-song summary of what that
song's storyboard should be**. The second is the point — it is what makes the
storyboards scenes of one story instead of twelve stories.

- `T2-14` The wand refuses to run with an empty theme prompt — **and runs with a
  non-empty one**, producing an arc. Refusal alone is satisfied by deleting the
  wand.
- `T2-15` The proposal is not saved until accepted. Rejecting leaves the previous
  arc untouched, verified by re-reading from disk — **and accepting DOES save
  it**. Leaving proposals ephemeral with no reject path satisfies the first
  half.
- `T2-16` **The wand never writes to more than one song at a time without
  confirmation.** Outside review: "do not auto-apply an LLM rewrite across every
  song in an album."

### 4.2 The storyboard generation prompt becomes visible and editable

Today the form takes tier, model, `scene_seconds` and `direction`; the prompt
template is neither visible nor editable, and the limits that apply to it are
not shown.

- `T2-17` The generation prompt is returned by the API, defaulted from the tier,
  and editable before generating. The half that matters — that an edit REACHES
  the model — is `T2-19`, and the two are read together: `T2-17` alone is
  satisfied by an API returning a string nothing consumes.
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

- `T2-20` **A distinctive string from the arc appears in the generated
  storyboard, and does NOT appear when the arc is absent.** "Differs" was the
  whole assertion and it cannot fail: two generations from a language model
  always differ, so passing `arc_ctx=None` unconditionally leaves this green
  with the arc reaching nothing — the identical defect `T2-21`'s own
  parenthetical diagnoses four criteria later, and recorded fixtures do not save
  it because two fixtures also differ. This takes `T2-21`'s shape instead:
  assert specific arc content is present, and absent when the arc is.

  The tiers are the MPAA ladder plus an explicit **xxx** tier, and `T2-21` and
  `T2-22` already assert tier content that way — a permission clause that must
  appear and a mainstream clause that must not. The arc gets the same treatment
  rather than a different one.

### 4.4 The tier reaches the model

Found 2026-08-12: all 25 scenes of `rear-entrance_xxx.json` carry *"fully
clothed, tasteful and non-graphic, no explicit gesture"* — the **mainstream**
clause — while `tiers.compose_guardrail("xxx")` says *"Explicit adult content is
permitted..."* and even the `r` tier says *"nudity, including graphic nudity, is
in scope"*. The tier never reached grok, so the storyboard is a PG-13 body filed
as xxx. Same defect class as a file whose job is to be true saying something
false.

- `T2-21` **At `xxx`, the mainstream clause must NOT appear in any scene.** No
  scene's `video_motion_prompt` or `image_prompt` contains *"fully clothed,
  tasteful and non-graphic"* or *"no explicit gesture"*, and the tier's own
  wording does appear. This **fails today** against `rear-entrance_xxx.json`,
  where all 25 scenes carry the mainstream clause, which is the point of writing
  it down. *(The draft said "a storyboard generated at two tiers differs" — two
  generations from a language model always differ, so that criterion passed with
  the tier wired to nothing.)*
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
  explicitly listed in `models.IGNORED` with a reason.** BUILT 2026-08-13.
  Measured live rather than quoted: cerberus enumerates **36 files across the
  seven loaders in `LOADER_FIELD`, of which 14 were unaccounted for** — not the
  sixteen this criterion first claimed and not the fifteen an audit counted, and
  the discrepancy is itself the point of doing the diff instead of citing it.
  gamingpc enumerates 6, with 1 unaccounted (`pixel_space`).
  Both are now zero.

  The parenthetical here used to say *"`ae.safetensors` is a companion under an
  alias"*. **That was false** — it is an `ALIASES` key and no catalogue entry
  named it, because there was no Z-Image entry at all. There is now, with the
  measurement that earned it: the only image model the 2080 Ti can run, 8.6s
  warm at 1024x576.

  `IGNORED` is a decision list, not a dumping ground: every entry carries a
  reason, nothing is both catalogued and ignored, and `models.demo()` asserts
  both. The camera-control LoRAs are in it with the differential that retired
  them; the nvfp4 LTX build is in it because it is the same model at another
  quantisation and a second entry would put two LTX-2.5s in the picker.

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

- `T2-36` Help text is **carried in the API response for each control**, so any
  client can put it behind a `?` and none has to hardcode it. **The warnings
  that must not move stay where they are** — day 8's standing rule — and the
  payload marks which strings are warnings, because a client that cannot tell a
  warning from a help note will hide the wrong one.
- `T2-37` The playlist payload carries the album's arc when one is defined, so a
  row can show it. Asserted on the payload, not on the rendered row.

## 8. Backend / front-end separation

**INHERITED from TRD-6 §0.1** (`T6-A1`…`T6-A4`). Not restated. TRD-2's own loop
is the one `T6-A1` names for this document: read the arc, propose one, accept it,
generate a storyboard, edit a scene, read the time meter, list unanchored leads.


**A requirement, not a nicety.** All business logic in the backend; the front end
disconnected, so a replacement front end — including mobile — can be built later
against the same API. Everything in §4, §5 and §7 above is therefore specified as
data first and presentation second.

The service module here covers arc generation, storyboard generation, scene
editing, casting and the time meter.

- `T2-41` Scene timing has exactly one implementation, `build_song.clip_plan()`.
  **This was FALSE when written and is true as of 2026-08-13.**
  `app.storyboard_scenes` computed every scene's `start`, `end` and `length` as
  `idx * CHUNK` inline — a second implementation, in the function that feeds the
  storyboard page, and the very site `T2-24` is about. Asserted by a
  differential, never by grepping for a call: a grep proves the code exists and
  not that anything reaches it.
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
3. **A criterion that needs a language model runs against a RECORDED response.**
   `T2-8`, `T2-19`, `T2-20`, `T2-21` and `T2-22` all involve a generation call.
   Live calls in the default suite would make 226 tests slow, non-deterministic
   and dependent on a paid API being reachable — and a non-deterministic test
   gets deleted the first week it goes yellow. Fixtures are recorded from real
   responses and checked in; **one deliberately live test exists and is kept out
   of the default run**, because a fixture that no longer resembles what the
   model returns is a check measuring its own history. Unspecified, whoever
   writes the first of these picks differently from whoever writes the second.
4. **When an image looks wrong, look at it.** The identity collapse, the world
   that never rendered and the LoRA that did nothing were all found by opening
   the pictures, and all three passed every deterministic check.
5. Baseline before and after: `cd studio && python3 -m pytest -q .` (the count is
   deliberately NOT written down here -- it was copied into three documents and
   all three went stale; green before and after is the requirement), `python3 check_integration.py`, and `grep -c "^def test_"`
   — a slice-to-end-of-file replacement once deleted four tests silently, and a
   deleted test does not fail.

6. **A REFUSAL or a PRESENCE is half a criterion.** Found by a second
   independent reviewer, and it is systematic rather than incidental: a
   criterion of the form "X is refused" or "the payload carries Y" stays green
   when the whole feature is DELETED, because a feature that does not exist
   refuses everything and a field nobody reads is still present. Every such
   criterion is paired with a positive case that exercises the feature, or it is
   marked **provisional** and says what it cannot yet distinguish.

   One-sided in this document today, listed so nobody has to re-derive it:
   `T2-5` (restore is named but never exercised), `T2-6` (a no-op delete renumbers nothing), `T2-7` (provenance fields can hold anything), `T2-18` and `T2-33`/`T2-34` (a picker that marks EVERYTHING unavailable passes; it needs the paired positive), `T2-36`/`T2-37` (payload presence with no consumer). `T2-12a`'s stored measurement must also be asserted to MATCH the ceiling the code uses, or the record and the constant drift apart.

### The positive half of each one-sided criterion

| criterion | its positive half |
|---|---|
| `T2-5` restore | actually RESTORE a version and assert the arc text returns to it. "Retrievable and restorable" was never exercised |
| `T2-6` delete does not renumber | assert a delete HAPPENED first (row count drops by one), or a no-op delete renumbers nothing and passes |
| `T2-7` provenance recorded | assert the recorded model equals the model that was ASKED for, and the timestamp lies between the call's start and end. Fields that merely exist can hold anything |
| `T2-18` limits in the response | assert the returned limit is the one ENFORCED: submit text one character over it and confirm the refusal quotes the same number |
| `T2-33` picker reads `renderable()` | add a model to the catalogue and assert it APPEARS without a UI change; a picker that calls the function and discards it passes otherwise |
| `T2-34` unavailable shown as unavailable | paired positive: an AVAILABLE model is offered. Marking everything unavailable satisfies the negative half alone |
| `T2-36` help text carried | assert a control with no help text is absent from the payload rather than present-and-empty, and that warnings are marked distinctly from notes |
| `T2-16` multi-song apply | with confirmation it writes to exactly the songs confirmed, asserted by count |
| `T2-37` arc in the playlist payload | assert a playlist WITHOUT an arc omits the field, so "always present" cannot pass for it |


---

## Status against the tree, 2026-08-13

Written by session A, in the shape session B set in TRD-4/TRD-7: a **ledger**,
not folded into the criteria above — *a criterion edited to describe what was
built is no longer a criterion, it is a changelog with a prefix.*

**"built" means a check can go red, not that the code exists.** `T4-10` read as
done all day while `app.ALBUM_FIELDS["body"]` quietly beat it, so a ledger that
repeats that is worse than none. Production is `c01c977`+; `origin/main` is
current.

| criterion | state | commit | what was measured |
|---|---|---|---|
| `T2-1`…`T2-4` the arc | **built** | earlier | `studio/arc.py`, JSON canonical, `to_md`, screened both directions |
| `T2-8a` the section floor is gone | **built** | `881d7cf` | both live sites moved together; the `validate()` site was the one that would have regenerated 25 scenes and made the formula fix look inert |
| `T2-35` every enumerated file catalogued | **built** | earlier | measured live: cerberus enumerates 36 files across seven loaders, 14 were unaccounted, now zero |
| `T2-41` scene timing has one implementation | **built** | earlier | `app.storyboard_scenes` no longer computes `idx * CHUNK` inline |
| **`T2-12a` legal frame count** | **built (divisor)** | `clip_seconds` | `legal_frames` rounds to 8n+1; `clip_seconds(scene_seconds)` returns that length so `n_clips_for` is `ceil(duration / legal)`. `None` stays `CHUNK` — old storyboards do not re-time |
| **`T2-13` `CHUNK` has one clip-count reader** | **built** | `n_clips_for` | `grok._user_prompt` and `build_storyboard` no longer compute `ceil(dur / CHUNK)`. A test asserts no module outside `build_song` does |
| **`T2-13b` approved refs survive re-plan** | **built** | `h_storyboard` | re-planning the same storyboard leaves the approved `(clip_idx, seed)` set identical. Mutation: wipe or remap refs in `h_storyboard` → red |
| **`T2-13a` renderer honours `clip_seconds`** | **built** | `test_clip_length.py` | `EmptyLTXVLatentVideo.length` and `TrimAudioDuration` follow the legal 8n+1 count, not `LTX25_LEN`/`CHUNK`. 8.0 s (under the T5-9 15 s ceiling) is 137 frames; `start_index` is `i * legal`. Missing `length_seconds` stays 81 / `CHUNK`. Mutation: restore the constants → red |
| **`T2-13c` approve grid lists every clip** | **built** | `approve_context` | 20-scene storyboard on a 41-clip song still renders `data-clip` 0..40 and `data-nclips="41"`. Mutation: range over `scene_count` → clip 20 missing |
| **`T2-14a` no fixed clip quantum in the planner prompt** | **built** | `_user_prompt` | return value has no `CHUNK` formatting, no "Nothing shorter or longer can be produced", no `duration_guidance`-to-multiples instruction. Mutation: restore any one → red. `_system_prompt` no longer names 4.8125 s either |
| **`T2-14b` clip-length text derived from planning** | **built** | `_user_prompt` | TIMING clip-length line is `clip_seconds(scene_seconds)`, not a new constant. Same song at 15 s and 30 s yields two statements. Mutation: swap 4.8125 for 15.0 and keep the sentence shape → `T2-14a` passes and this fails |
| **`T2-14c` TIMING purpose** | **built** | `_user_prompt` | TIMING still states track length and sum-to-track. Mutation: delete the TIMING block wholesale → `T2-14a` passes and this fails |
| **`T2-20` distinctive arc string in the generated board** | **built** | `album_arc` | same recorded response with and without `arc_ctx`; beat/continuity token present only when the arc is. Mutation: drop `arc_ctx` from `_compose` → red. Mutation: always stamp the token → the absent-arc arm fails |
| **`T2-22` own clause on the board; foreign wording refused at save** | **built** | `guardrail` | `_compose` stamps `guardrail` as `tiers.compose_guardrail(tier)` (not the passed argument). `save_scene` / `h_storyboard` refuse when another tier's stored wording appears. Mutation: drop the stamp → generation arm red. Mutation: copy the argument → red when the argument is not the clause. Mutation: write without the check → save arm red |
| §4 remaining wands (`T2-14`…`T2-19`), §5 meter, §5.3 casting | **not built** | — | |
| `T2-42`…`T2-46`, `T2-48` per-scene model (W2) | **not built** | — | |
| `T2-47` mixed-model native frames/fps | **built** | `test_t2_47_mixed_model.py` | one `build_song.main` job, scene 1 marked `s2v` and scene 2 left `ltx25`: clip_000 is WAN 77@16.0, clip_001 is LTX 81@16.8312. Mutation: `main()` ignores `scene.video_model` → both graphs match `--video-model` |
