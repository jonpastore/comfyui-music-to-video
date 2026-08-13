# TRD-4 · Character anchors and identity

Status: written 2026-08-13. Owned by no previous document: TRD-2 owns the
storyboard that *names* a character and TRD-3 owns *measuring* whether a render
kept them, and nothing owned the sheet that defines who they are.

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
| "Selecting nothing for **Tiers** silently falls back to G" | **FALSE.** `app.py:3056` already raises 400 *"select at least one tier"*, and `save_anchor_prompt` refuses with *"an album and a tier are needed"*. There is no G fallback on either path. |
| "Selecting nothing for **Views** silently falls back to front-clothed" | **TRUE.** `app.py:3054` is `sorted(...) or ["front"]`, and `anchor_form_ctx`'s signature defaults `selected_views=("front",)`. |
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
- `T4-11` **Body colouring is a pure positive assertion naming the parts.**
  "Her entire body from shoulders to feet is covered in the same sleek jet-black
  fur as her face, uniform in shade and texture on shoulders, arms, torso, hips,
  thighs and calves." The part list is the load-bearing half: "identical head to
  toe" is a summary a model can satisfy by averaging, and a list is not.
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
    jet-black fur as her face, uniform in shade and texture on shoulders,
    arms, torso, hips, thighs and calves.
    <anatomy, from the album profile>
    Even neutral studio lighting.
    <BACKDROP: flat neutral mid-grey, evenly lit, empty, contact shadow>
    <FRONT VIEW framing>
    <tiers.compose_guardrail("xxx"), with PINNED welded on last>

- `T4-18` A test composes this for real and asserts: no negation anywhere, the
  body part list present, both reference slots named, no wardrobe clause, no
  "bare skin", and `tiers.PINNED` last. Six assertions, each able to fail on its
  own.

## 7. Explicitly not building

- No second guardrail for saving. `T4-5` is explicit that the save path calls the
  render path's own composer.
- No IP-Adapter, InstantID or ReActor. `fix_ref.py` does face swap, inpaint and
  outpaint on the model that rendered the frame; a multi-image edit model does
  not need them.
- No new negative prompt. §5.

## 8. How every criterion above is to be verified

Same rules as TRD-1..3. A measurement that cannot fail is not evidence; a
refusal or a presence is half a criterion and needs its positive case; and
**when an image looks wrong, look at it** — the identity collapse, the world
that never rendered and the LoRA that did nothing all passed every deterministic
check this project had.
