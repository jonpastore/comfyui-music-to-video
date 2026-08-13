# TRD-2 · Story arc and storyboards

Status: draft for review. Inputs: `docs/STORYBOARD_UI_RECONCILIATION.md` (what
already exists), `docs/RECONCILIATION_2026-08-12.md` (the day's measurements),
`docs/EXTERNAL_REVIEW_2026-08-12.md` (outside opinion, verified).

Acceptance criteria are numbered `AC-n` and are written so that each one can
fail. A criterion that cannot fail is not a criterion.

---

## 1. The problem

Storyboards are written per song, independently. An album has no through-line,
so twelve songs produce twelve unrelated visual stories that happen to share a
character. What is wanted is the opposite: **an album-level arc that acts as
setting and through-line — a musical or an opera — with each song's storyboard
being that song's scene within it.**

Two supporting problems, both measured today rather than assumed:

- **`scene_seconds` cannot lengthen a scene.** `n_scenes = max(len(sections),
  ceil(duration / scene_seconds))`. A 25-section song returns 25 scenes whether
  15s or 30s is requested. Nothing in the UI reveals this.
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

- `AC-1` Writing an arc produces both `<album>_arc.json` and `<album>_arc.md`,
  and the `.md` is byte-identical to `to_md(json.load(the .json))`. A test
  regenerates it and compares.
- `AC-2` Editing the `.md` on disk and re-rendering overwrites the edit without
  warning. This is asserted, not merely documented, so nobody builds a flow that
  depends on hand-edited Markdown surviving.

### 3.2 Arc content

The arc is the album's setting and through-line, not a summary. Required keys:
`setting`, `through_line`, `acts` (ordered, each with `name` and `intent`), and
`songs` — a per-song entry naming which act it sits in and **what that song's
scene contributes to the story**.

- `AC-3` Every song on the album appears exactly once in `arc["songs"]`.
  Generating an arc for an album with a song missing fails loudly rather than
  producing a partial arc.
- `AC-4` `arc["songs"][slug]["contributes"]` is non-empty for every song. An arc
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

- `AC-5` Editing an arc prompt creates a new version; the previous version is
  retrievable and restorable.
- `AC-6` Deleting a version does not renumber the others.
- `AC-7` A version records which model produced it and when, so a regression can
  be traced to a model change.

## 4. Generation flows

### 4.1 The arc wand

A wand on the album reads the songs' lyrics and proposes an arc. It opens a
modal asking **what theme or ideas to capture** before it runs — the arc is a
creative decision, and a wand that fires without asking produces a generic one.

Returns two things: the proposed arc, and **a per-song summary of what that
song's storyboard should be**. The second is the point — it is what makes the
storyboards scenes of one story instead of twelve stories.

- `AC-8` The wand refuses to run with an empty theme prompt.
- `AC-9` The proposal is not saved until accepted. Rejecting leaves the previous
  arc untouched, verified by re-reading from disk.
- `AC-10` **The wand never writes to more than one song at a time without
  confirmation.** Outside review: "do not auto-apply an LLM rewrite across every
  song in an album."

### 4.2 The storyboard generation prompt becomes visible and editable

Today the form takes tier, model, `scene_seconds` and `direction`; the prompt
template is neither visible nor editable, and the limits that apply to it are
not shown.

- `AC-11` The generation prompt is shown in a textarea, defaulted from the tier,
  and editable before generating.
- `AC-12` The limits and guardrails that apply are displayed **above** the
  textarea: the tier's pinned clause, the character/word bounds, and the fact
  that `tiers.PINNED` is added at use time and cannot be edited out.
- `AC-13` Editing the prompt and generating uses the edited text. Asserted by a
  differential — generate with two different prompts, confirm two different
  storyboards — not by checking that the field posts.

### 4.3 The song storyboard wand

Each song's storyboard gets the same treatment: a versioned, editable
description used as the prompt, and a wand that asks AI to review and improve
it. The arc is passed as context so the scene knows the story it belongs to.

- `AC-14` A storyboard generated with an arc present differs from one generated
  without it, for the same song and prompt. If it does not, the arc is not
  reaching the model and the feature is decorative.

## 5. The storyboard page

### 5.1 The time meter

- `AC-15` The page shows total scene time against song length, and flags a
  mismatch beyond a stated tolerance.
- `AC-16` **The meter reads the real per-song clip length, not a constant.**
  Clip length is per song now; a meter hardcoding 4.8125s would be wrong on
  every song that is not 4.8125s-based.
- `AC-17` Generating a 25-section song with `scene_seconds=30` shows the
  mismatch — 25 scenes at ~7.8s against a 30s request. This is the specific case
  that went unnoticed and is now a test.

### 5.2 Anchors and cast

- `AC-18` Anchor images for the album appear at the top of the storyboard page,
  per character.
- `AC-19` Each scene lists its reference image beside an editable scene
  description.
- `AC-20` A scene naming a character with no chosen anchor is flagged before
  rendering. (Already built; regression test only.)

### 5.3 Casting: who needs an anchor

Generation classifies each named figure as **lead**, **extra** or **background**.
Only leads need anchors.

- `AC-21` Every named character in a scene carries a role classification.
- `AC-22` The unanchored warning fires only for leads. An extra without an anchor
  is not a problem and must not be reported as one — a warning that cries wolf
  is a warning nobody reads.

### 5.4 Identity cannot be left empty

- `AC-23` Saving a storyboard with an empty `character_reference` is refused,
  with a message naming the consequence. Measured 2026-08-12: without it, every
  clip renders an ordinary human and every deterministic check passes.

## 6. Model selection

Every place a model is chosen shows what the candidates are FOR, from
`models.CATALOG`, rather than a bare list.

- `AC-24` The storyboard page's model picker reads `models.renderable(role)`, so
  a model added to the catalogue appears without a UI change.
- `AC-25` A model that is catalogued but unavailable on every reachable backend
  is shown as unavailable rather than offered. `models.where()` answers this, and
  since 2026-08-12 it distinguishes "no box has it" from "no box could be asked".

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

- `AC-26` Descriptive prose moves into help modals behind a `?` icon per
  control. **The warnings that must not move stay where they are** — day 8's
  standing rule.
- `AC-27` Playlist rows show the album's arc when one is defined, and a trash
  icon for delete.

## 8. Explicitly not building

From outside review, all four models agreeing: no custom git for versioning, no
visual node-graph prompt editor, no auto-apply across an album, no collaborative
editing. From this project's own history: no second place that computes scene
timing — `clip_plan` is the one, and the page calls it.
