# TRD-7 · Anchor variations on the build_refs workflow

Status: written 2026-08-13. Owns the gap between what `build_refs.workflow()`
accepts and what the anchors UI can reach, and the prompts a wider set of views
needs. TRD-4 owns *who the character is* and how the positive prompt is built;
this document owns *how many different sheets of them you can ask for* and
whether they stay the same person.

Acceptance criteria are `T7-n` and each **can fail**. Every claim in §1 was read
off the code before it was written down.

---

## 1. The premise, corrected

**The anchors UI already renders through `build_refs.workflow()`.**
`make_anchor.py:36` is `from build_refs import workflow`, `pipeline.gen_anchor`
shells out to `make_anchor.py`, and `h_anchor` (`app.py:797`) calls
`gen_anchor`. There is no second graph to port and no second model: an anchor
sheet and a clip reference frame come out of the same eight nodes, the same
`qwen_image_edit_2511_fp8mixed` UNET, the same Lightning LoRA and the same
`qwen_2.5_vl_7b_fp8_scaled` text encoder.

So this is not an integration. It is **closing the gap between the parameters
`workflow()` takes and the ones the anchor path can express**. Every row below
was checked:

| `workflow()` parameter | reachable from the anchors UI | evidence |
|---|---|---|
| `scene["image_prompt"]` | **Per tier, not per view.** One textarea per tier; an edited prompt is sent for every view of that tier | `app.py:3182-3185`, and the trap is documented at `app.py:3160-3173` |
| `scene["negative_prompt"]` | yes, versioned, dropped below cfg 1.0 | `anchor_render_settings`, `build_refs.negative_applies` |
| `anchor` (image1, the identity lock) | **uploads only** — a *rendered sheet* cannot be fed back in | `app.py:3136` reads `assets kind='anchor_ref'`; `h_anchor` writes to the `anchors` table, which is never an asset |
| `base` (image2, the composition plate) | **no** — the 2nd picked reference silently becomes it | `make_anchor.py:337` passes `images[1]` as `base` |
| `latent_mode` | **no** — hardcoded `"empty"` | same call site |
| `w` / `h` | **no** — fixed 896×1216 | `make_anchor` declares `--width/--height`; `gen_anchor` never passes them |
| `seed` | yes, base seed, candidates spaced `+137` | `ANCHOR_RENDER_FLAGS["seed"]` |
| `shot` | always `""`, deliberately — a character sheet is self-contained | `make_anchor.py:338` |
| `guard` | yes, the tier's wording | `gen_anchor(..., "--guardrail", guard)` |
| `extra_refs` | **auto-named `"reference 3"`** | `make_anchor.py:339-340` — verified independently 2026-08-13: `f"reference {i + 3}"` |
| `settings.{steps,cfg,sampler,scheduler,denoise}` | yes | `ANCHOR_RENDER_FLAGS` |
| `settings.lora_strength` | **no** — `--lora-strength` exists, the map omits it | `pipeline.py:889-901` |
| `ref_method` | yes | `ANCHOR_RENDER_FLAGS["ref_method"]` |
| `SHIFT` (3.1), `CFGNorm` (1.0) | **no** — module constants | `build_refs.py:28`, node `"4"` |

Two of those rows are defects rather than absences, and they are the reason this
document exists rather than a checkbox list:

**(a) The third reference contradicts the composite instruction.** With three
references, `make_anchor` hands `images[2:]` to `extra_refs` as
`("reference 3", img, "")`, `assign_ref_slots` gives it slot 3, and
`cast_clause` writes *"The character in image 3 is reference 3."* into the same
prompt that already says *"All of the reference images show the SAME single
character."* The cast-clause mechanism exists to tell two anchors apart in a
duet frame; pointed at one character's three photographs it asserts a second
person. This is `T4-12` arriving at the anchor path, where the slot names are
wrong rather than missing.

**(b) The whole denoise control is dead.** `DENOISE_CHOICES` offers five values
whose labels all read *"on an anchor this returns noise"* (`app.py:2214-2221`),
and they are correct, because `latent_mode` is pinned to `"empty"`. A dropdown
where five of six options are documented as broken is the editor-promising-what-
the-renderer-does-not-do defect this codebase keeps finding, in its mildest
form.

## 2. Variations: more views, and one place that decides what a view is

Today there are four views (`app.py:129`), and the only variation within a sheet
is the seed. `n` candidates at `seed + k*137` is real variation — composition
here is seed-dominated — but it cannot be *asked for*: there is no way to say
"the same character, three-quarter turn" or "seated" or "head and shoulders".

- `T7-1` The view set is **data, extended by adding an entry**, not by editing
  four places. Adding one view today means `app.py:ANCHOR_VIEWS`,
  `app.py:NUDE_VIEWS`, `make_anchor.DEFAULT_VIEWS` and `make_anchor.NUDE_VIEWS`
  — and the two `NUDE_VIEWS` are **hand-kept copies of one another**
  (`app.py:135`, `make_anchor.py:167`). *Mutation: add a view to one copy only →
  a test asserts the two agree, and goes red.*
- `T7-2` **Nudity gating is derived, not enumerated.** A view is nude because of
  what it is, not because somebody remembered to add it to a literal set. A new
  nude view that nobody added to `NUDE_VIEWS` today renders at `g` with the
  album's *wardrobe* wording and `anchor_plan` never skips it — a tier violation
  produced by an omission, which is exactly the failure `T4-6` guards on the save
  path and nothing guards here. *Mutation: add `three_quarter_nude` without
  touching any gate → still refused at `g`.*
- `T7-3` The new views ship with framing text and **each is a single positive
  sentence naming the camera relationship**, in the shape `DEFAULT_VIEWS`
  already uses. At minimum: `three_quarter` (body turned 45°, face to camera),
  `profile` (full side view), `seated`, `portrait` (head and shoulders), each
  with its nude parallel. No negation, per `T4-10`.
- `T7-4` A view's framing sentence is the **only** thing that differs between two
  sheets of one tier. Asserted by composing two views and diffing: identical but
  for the framing clause and, on a nude view, the wardrobe swap.
- `T7-5` `portrait` **overrides the head-to-toe clause** rather than sitting
  beside it. `BACKDROP` ends *"full body head to toe inside the frame"*, which
  argues with a head-and-shoulders framing; a prompt holding both is the
  bare-skin-versus-fur contradiction in a new place, and Day 4 measured what that
  costs.

## 3. Consistency: the anchor is the lock, and the UI cannot use it

The reason clips stay on-model is that `gen_refs` passes a **chosen anchor** as
image1 for every scene (`app.py:1015`). The anchors UI has no such path: it
conditions on uploaded photographs every time, so sheet 2 is a fresh
interpretation of the source images rather than a variation of the sheet you
approved. This is the single largest consistency lever available and it is
unwired.

- `T7-6` **A chosen anchor can be used as the identity reference for a new
  sheet.** The `anchors` gallery gets "use as reference"; the row's `path` goes
  through `pipeline.install_input` exactly as `gen_refs` does it. Not a re-upload
  — the same file, no copy.
- `T7-7` With an anchor as image1, a variation sheet **keeps the identity across
  views**, measured rather than asserted: render `front` and `three_quarter` from
  one anchor and compare against the same pair rendered from the raw photographs.
  The criterion is a differential on the rendered images, per TRD-3's rules; a
  string being present proves nothing here.
- `T7-8` **`latent_mode="image"` is reachable**, and it is what makes the denoise
  control honest: refine an existing sheet at 0.55 to vary the surface while
  holding the composition. When it is selected the denoise labels change, and
  when it is not they still say the value returns noise. One resolver decides
  both, so the label and the graph cannot disagree.
- `T7-9` **The composition plate is named.** `base` is image2 and sets the
  framing; today it is whichever reference happened to be picked second, with
  nothing in the UI saying so. Either the form has a plate slot or `make_anchor`
  stops assigning one — silently is the one option that is out. *Mutation: pick
  two references, confirm the second is not silently promoted to image2.*
- `T7-10` **Slot names are real.** `T4-12`'s naming applies here: image 1 is the
  identity reference, image 2 the wardrobe or plate reference, image 3 the third
  view of the same character. `"the character in image 3 is reference 3"` is
  refused by a test, because it asserts a second person into a prompt whose
  composite clause denies one.
- `T7-11` `lora_strength` is settable, with the `sampler_settings` interlock
  intact: cfg > 1.0 still forces it to 0 unless it was passed explicitly
  (`build_refs.sampler_settings`, `_selfcheck`). The escape hatch that module
  deliberately kept is currently unreachable from the studio.
- `T7-12` Width and height are settable, defaulting to today's 896×1216. A
  `portrait` view at 3:4 and a full-body sheet at 3:4 are not the same crop, and
  a fixed size is what makes `portrait` render a distant figure.

## 4. Prompts to add

`prompts.py` versions nine types (`PROMPT_TYPES`) and its own docstring states
the extension rule: *"Adding a type here is all that is needed to give it
history."* Three things that materially shape every sheet are **code constants
with no history and no per-album override**, and the view framing is explicitly
excluded from the profile at `app.py:4781` — *"framing is make_anchor's, and
species-neutral"*, which stops being true the moment a view is `seated`.

- `T7-13` **Per-view framing is a versioned prompt.** One type per view, keyed
  `view:<key>` and generated from the view table so `T7-1` still holds — not a
  new `view` column on `prompt_versions`, and not a fixed literal per view.
  Untiered: how a camera is placed is not a function of the rating.
- `T7-14` **`backdrop`** becomes a type. `make_anchor.BACKDROP` is five clauses
  of studio, lighting, framing and focus welded together and shared by every
  sheet this studio has ever rendered; `T4-13`'s lighting lock lands inside it
  and `T7-5` has to override half of it. Untiered.
- `T7-15` **`composite`** becomes a type. It is the clause that decides whether
  three references are one character or three, it is load-bearing for `T7-10`,
  and it is currently a constant nobody can tune per album.
- `T7-16` **`pose`** is a new, optional, per-sheet type: what the character is
  *doing* in this sheet, as distinct from where the camera is (`view`) and what
  they look like (`identity`/`body`). It is the variation knob the form does not
  have — today the only way to ask for a different pose is to overwrite the whole
  composed prompt, which discards the per-view framing and the nude swap
  (`app.py:3160-3173`). Untiered; it describes an action, not a rating.
- `T7-17` Every new type is composed by `make_anchor.prompt_for` and appears in
  `anchor_prompt_preview` — the preview runs the real composer, and a type the
  preview cannot show is a type the operator is editing blind.
- `T7-18` Every new type is screened by `screen_prompt_field` and walked by
  `test_no_positive_prompt_constant_tries_to_negate`. A new positive constant
  that says "no" is the defect this project has shipped twice: *"no smoke"* put
  smoke on every sheet for the life of the project, and *"no garments, no
  underwear, no straps"* put a leather harness on a nude sheet.
- `T7-19` The **per-view prompt override** the form lacks: an edited prompt
  currently applies to every view of its tier. With four views that is a
  documented trap; with ten it is the default outcome. Either the textarea is per
  tier *and* view, or the edit box holds only the clauses that are not per-view.

## 5. Explicitly not building

- No new graph, no second workflow builder, no ControlNet, no IP-Adapter. §1: the
  anchor path already runs `build_refs.workflow()`, and `T4` §7 already refused
  the identity add-ons for the same reason — a multi-image edit model conditions
  natively.
- No `shift` or `CFGNorm` control. They are in §1's table for completeness; both
  are packaged operating points from ComfyUI's own 2511 template, neither has a
  measured reason to move, and an unmeasured knob on a form is an invitation to
  spend a render finding out.
- No change to the negative prompt or to fast/quality mode. TRD-4 §5 owns those
  and nothing here moves them.
- No new storage for variations. A variation is an `anchors` row like any other,
  scoped by album, tier, view and character exactly as today.

## 6. How every criterion is verified

Same rules as TRD-1..4. A measurement that cannot fail is not evidence; a
refusal is half a criterion and needs its positive case (`T7-2` needs the `g`
refusal *and* the `xxx` success); and where a criterion is about what an image
looks like — `T7-7`, and `T7-5`'s framing contradiction — **look at the image**.
The identity collapse, the world that never rendered and the LoRA that did
nothing all passed every deterministic check this project had.

### The positive half of each one-sided criterion

Added 2026-08-13 from the first external review of this document (grok and
chatgpt, independently — `docs/reviews/TRD47-*-2026-08-13.md`).

| criterion | why it is one-sided | its positive half |
|---|---|---|
| `T7-2` a nude view is refused at `g` by derivation | if no nude view can be added, or every view is refused, this stays green | the same view **succeeds at `xxx`** with the wardrobe swap applied. §6 already said this in prose; **it is a criterion now, not a verification note** |
| `T7-3` new views ship with framing text | a string existing in a table | each new view **composes and renders**, its framing clause appearing exactly once (`T7-4`) |
| `T7-5` `portrait` overrides head-to-toe | the absence of a conflicting string | the `portrait` render **is a head-and-shoulders crop**, measured on the image, not full-body with a losing clause |
| `T7-6` an anchor can be the identity reference | the presence of a feature | **`T7-7` is its half** — bind them, because "the button exists" is not "identity held" |
| `T7-8` `latent_mode="image"` is reachable | the "not selected" branch passes while image mode is never implemented | with it selected, **denoise 0.55 changes the surface and holds the composition** (image differential), and the labels match the graph |
| `T7-9` the plate is named | "nothing is silently promoted" is satisfied by removing multi-reference support | either a plate slot **drives image2**, or `make_anchor` assigns no base **and a sheet still renders in that declared shape** |
| `T7-10` slot names are real | refusing one bad string | a three-photograph one-character sheet **keeps one identity** (`T7-7`), and — see below — a duet can still name two people |
| `T7-11` `lora_strength` is settable | the presence of a parameter | an explicit value **reaches the graph**, and cfg > 1.0 still forces 0 when it was not passed. Both directions |
| `T7-12` width and height are settable | the presence of parameters | a non-default size **appears in the workflow and in the output's dimensions** |
| `T7-13`…`T7-16` four new prompt types | types existing and being versioned | each is **editable per album, composed into the real prompt, visible in the preview** (`T7-17`) and screened (`T7-18`) |
| `T7-18` new types are screened and walked | nothing unscreened exists while the types do not | the types **exist and are composed**, and the walker covers them — **red-before-green per type**, because the walker is green today precisely because they are absent |
| `T7-19` the prompt box is per tier and view | either shape satisfies "either/or" | editing one view's override **does not change another view's composed prompt** (differential) |

**Not one-sided:** `T7-1` (the cross-copy mutation), `T7-4` (a compose diff),
`T7-7` (an image differential).

### Two things this review found — both resolved the same day

- **`image 2`'s two roles were a documents conflict, not a shipped one, and
  TRD-4 is the document that moves.** `T7-9` says `base` is image2 and sets the
  framing; `T7-10` hedged *"the wardrobe **or** plate reference"*; TRD-4 `T4-12`
  says flatly *"image 2 is the wardrobe reference"*. Measured on the shipped
  composer: **the anchor path never says "wardrobe reference" anywhere**, so
  `T4-12`'s wording was never implemented here and nothing contradicted itself
  in a render.

  Resolved in favour of what the code already does. On the anchor path the
  references are an unordered **set of photographs of one character**, and the
  honest wording — true on clothed and nude sheets alike — is *"Image 2 is
  another photograph of the same character."* Naming it "the wardrobe reference"
  would re-impose the face-then-outfit ordering that was deliberately removed,
  and would declare a role that a nude sheet's own dropped wardrobe wording then
  contradicts. **Slot naming belongs to the cast path, where the slots really do
  hold different people.** `T7-10` drops the "or plate" hedge; `T7-9` is resolved
  by `d3f2f6a`'s `base=None`.

- **The duet case was already guarded, and the guard was thinner than it
  looked.** `build_refs._selfcheck` asserted a named cast member composing to
  *"The character in image 3 is Nyx: a rival DJ."* before this review ran. The
  real hole: **every check used exactly ONE cast member**, so no slot collision
  and no name/file swap was reachable. Closed by `7836d6f` with two, asserted as
  `{"image2": "nyx.png", "image3": "ghost.png"}` — because asserting that both
  names merely appear would pass with both wired to one image, which is the
  blend the mechanism exists to prevent.
