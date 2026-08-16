# TRD-10 · The library, lyrics, and the AI advice surfaces

Status: written 2026-08-13. **Absorbs `docs/LIBRARY_BULK_EDIT_PLAN.md` *(absorbed and removed 2026-08-13; in git history)* (229
lines)** — the last plan document no TRD owned — and claims `studio/lyrics.py`
(405), `studio/chat.py` (330), `studio/mixadvice.py` (247) and
`studio/vision.py` (516): **1,498 lines of shipped code that no TRD cited.**

Acceptance criteria are `T10-n` and each **can fail**. Rules every document
inherits are `TRD-6 §0` (`T6-A1`…`T6-A6`) — cited, never restated.

---

## 1. What these four have in common

They are the studio's **inputs and its opinions**: how a song gets catalogued,
how its words are obtained, and every place a model is asked to advise rather
than to render.

That second half is why they are one document. **Four modules ask a model for
words, and no document has ever said what those words are allowed to be.** The
only rule anywhere is a prohibition inside TRD-3 §10 — *"a VLM may write a
description attached to a finding; it may not be the verdict"* — which is a
constraint on a subsystem nothing specifies.

The risk is specific and this project has already paid it once: **asked "does
this match?", a model answers yes.** A studio that surfaces model opinions
without saying which are load-bearing will have one of them quietly become a
gate.

## 2. What exists — do not rebuild

| built | where |
|---|---|
| Lyric fetch and transcription, faster-whisper preferred, backend chosen **at call time not import time** | `lyrics.py` |
| The two real chat providers behind the arc and advice surfaces | `chat.py` |
| Relational mix advice over a set | `mixadvice.py` |
| Image questions: contact-sheet review, anchor description, cast proposal, edit-instruction parsing; local gateway first, xAI as fallback | `vision.py` |
| Genre vocabulary | `genres.json`, and `songs.genre/subgenre/genre2/subgenre2` |
| Per-song catalogue fields, sortable headers | the library page (`GET /` and `GET /songs`; JSON `GET /api/songs`) |
| Library `song_count` shared HTML/JSON | `library_service.numbers()` (`T6-A2-library`) |

**`lyrics.py` and `vision.py` both choose their backend per call, deliberately.**
`vision.py`'s docstring states the reason and it generalises to both: *"the local
gateway comes and goes as models are loaded on it, and a studio that started
before the model did must not be stuck on the paid path for the rest of its
life."*

- `T10-1` Backend selection is **per call**, and a studio started while the local
  gateway was down uses it once it is up, with no restart. Asserted by a
  differential — gateway absent then present, same call, two different providers
  — not by reading the code.
- `T10-2` A call that falls back to the paid path **says so in the record**, so
  cost is attributable after the fact rather than inferred from a bill.

## 3. Bulk editing the library

From `LIBRARY_BULK_EDIT_PLAN.md`, whose own sharpest requirements are kept
verbatim because they are the ones that destroy data when got wrong.

- `T10-3` **Blank means "leave alone", not "clear".** Someone setting only
  `genre2` on twelve songs must not have their `genre` wiped. Asserted on the
  stored rows before and after. **If clearing is wanted it needs its own explicit
  control**, never an empty select.
- `T10-4` **Toggle-all applies to the rows currently shown**, not to every song
  in the database. The header sort and any filter are already live, so a filtered
  view that selects off-screen rows edits things the operator cannot see.
  Asserted by filtering, toggling all, and counting what changed.
- `T10-5` Every submitted value is **validated server-side against
  `genres.json`** before any row is written, and one invalid value refuses the
  whole batch rather than writing a partial edit. A half-applied bulk edit is
  two states to reconcile by hand.
- `T10-6` A bulk edit is **one transaction** (`T6-14`'s rule, this surface).
  Twelve songs edited and a crash halfway leaves twelve unedited, not six.
- `T10-7` The count of what will change is shown **before** the write, and it is
  the count that actually changes. A confirmation that says "12 songs" and edits
  9 has taught the operator to stop reading it.

## 4. Lyrics

- `T10-8` A transcription records **which backend produced it** and that it is a
  transcription rather than supplied text. The two are not the same evidence —
  TRD-2's storyboard generation reads lyrics, and a hallucinated line becomes a
  scene.
- `T10-9` Transcribed lyrics are **editable and the edit survives a re-fetch**,
  or a re-fetch silently discards human correction. Paired positive: an explicit
  re-transcribe **does** replace them, and says it will.
- `T10-10` Lyrics feed TRD-2's section structure, and **an empty result is
  explicit** rather than an empty string. A song with no lyrics and a song whose
  fetch failed are different states, and `T2-8c`'s section coverage cannot tell
  them apart otherwise.

## 5. The advice surfaces, and what they may claim

The rule this document exists to state, generalising TRD-3 §10 from QC to
everywhere:

> **A model's words are a proposal, never a verdict and never a gate.** Any
> surface that shows model output labels it as such, and no stored decision is
> made by one without a human act in between.

- `T10-11` Every model-authored string reaching the interface is **marked as
  model-authored in the payload**, not by a sentence typed into one template
  (`T2-36`'s shape — a client that cannot tell advice from measurement will show
  the wrong one).
- `T10-12` **No advice surface writes a stored value directly.** `mixadvice`
  proposes a running order; accepting it is a separate act, and the proposal is
  retained so "what did it suggest and what did I do" is answerable. Paired
  positive: accepting one **does** write, and records that it came from a model.
- `T10-13` `vision.classify_sheet`'s output is **attached to a finding or a
  candidate, never a pass/fail**. TRD-3 §10 owns the prohibition; this asserts it
  at the other call sites, because the same function is reachable outside QC.
- `T10-14` **A model is never asked a question whose answer it cannot be wrong
  about visibly.** "Does this match the reference?" is refused as a prompt shape;
  "describe what differs" is not. The recorded failure is the pixel metric that
  ranked the wrong image first at 41.1 against 64.7 — a plausible number,
  confidently backwards, and a VLM asked the same question would have agreed
  with it.
- `T10-15` `mixadvice`'s advice is **relational and says what it is relative
  to** — *"what happens at item 3 depends on what item 2 did"* is the module's
  own framing, so advice quoted without its neighbours is advice about a
  different set.

## 6. The guardrail boundary

- `T10-16` The **image** guardrail applies to every surface that reaches an image
  or video render, and **not** to the audio path (`T8-4` owns that split and this
  cites it). A lyric mentioning a child is accepted; a scene description
  mentioning one is not.
- `T10-17` Free text entering any of these four modules is bounded and screened
  by the **one** shared guard, `screen_prompt_field` — not a per-module copy.
  `MAX_PROMPT_FIELD` replaced `MAX_CHARACTER_FIELD` for exactly this reason: two
  bounds for one idea sat 39 characters from refusing real saved content.

### 6a. Minors: separate the depiction from the mention

**The rule this studio has today is over-broad, and its own justification says
why that was thought acceptable.** `guardrail.check_text` refuses **any** minor
reference, and its docstring argues: *"this is a character generator for
adult-themed music videos, so there is no legitimate reason for a tier
definition, style note or generated scene to reference children… and costs
nothing anyone actually needs."*

**That last clause is false and was falsified by the operator, 2026-08-13:** he
intends to write a song for a seven-year-old niece and make a video for it. A
rule justified by costing nothing now costs a thing somebody wants, so the
justification has to be rebuilt rather than reasserted.

**What must be impossible is a depiction, not a word.** The thing this project
must never produce is sexual or nude content involving a minor — CSAM or
anything approaching it. That is absolute, it is not a tier setting, and no
override reaches it. **Refusing the word "niece" does not prevent it**, and the
guardrail's own comment admits the real gap: a childlike figure described
without any blocked term *"needs a classifier"* and is not caught today. So the
blunt rule pays a real cost and does not buy the protection it is named for.

**A correction to that, before the design, because it was overstated.** The
blunt input filter is **not** merely a keyword screen that buys nothing. The
guardrail's own comment records why: *"the image pipeline runs at cfg 1.0, where
ComfyUI skips the negative pass entirely — a 'no children' negative prompt is
literally inert on this stack. Positive-text steering plus refusing the input
are therefore the only controls that actually do anything here."* **The input
refusal is one of exactly two working controls on the render path.** The gap
around unworded childlike depiction is real, and it does not make the filter
ornamental. Any loosening has to be justified against that, not against the
weaker claim.

**And the decisive technical fact, which this project has already measured.**
`PINNED` is welded onto every render prompt and asserts *"Every character is an
adult woman or man of at least 21 years, with fully adult face, body and
proportions."* **A prompt that carries `PINNED` and also references a child is a
self-contradicting prompt** — and day 4 measured what this stack does with
those: the nude clause asserted bare skin beside "entire body covered in
jet-black fur", and a fixed-seed sweep watched the model resolve the
contradiction *harder* as guidance rose, two of three seeds rendering a human
body with a cat's head by cfg 7.0. **A contradiction between "everyone is 21+"
and a child reference is the one contradiction that must never be handed to a
sampler.**

That is what fixes the tier line: the question is not "may a child be
mentioned" but **"may a child reference enter text that reaches a render
prompt"** — and at `r` and `xxx` the answer is no, whatever the tier permits
elsewhere.

**The design: a minor reference and explicit capability can never coexist, and
they are kept apart structurally rather than by screening prose.**

#### The legal ground, researched 2026-08-13 rather than assumed

Recorded because the tier names imply a legal framework and two of the
assumptions in them are wrong. **This is general information, not legal advice.**

- **The statutory floor for real performers is 18, not 21.**
  [18 U.S.C. § 2257](https://www.law.cornell.edu/uscode/text/18/2257) requires a
  producer of sexually explicit depictions of **actual human beings** to verify
  each performer's age by **examining an identification document** and to
  maintain those records. First-offence violations carry up to five years.
- **§ 2257 does not reach synthetic content**, because it governs depictions of
  actual human beings. No performer, no ID, no records. **That is not a
  permission**, it is the removal of the mechanism that does the protecting.
- **[18 U.S.C. § 1466A](https://uscode.house.gov/view.xhtml?req=granuleid%3AUSC-prelim-title18-section1466A)
  is the statute that reaches this studio.** It covers *drawings, cartoons,
  animations, sculptures, paintings and computer-generated images*, and
  **does not require that an actual minor be involved.** Congress added it in
  the PROTECT Act of 2003 to close the gap a 2002 Supreme Court decision opened.
  Synthetic CSAM is criminal with no real child anywhere in the process.
- **The rating names are looser than they look.** R is *"Restricted — Under 17
  Requires Accompanying Parent or Adult Guardian"*. **X was retired in 1990** and
  replaced by NC-17, *"No One 17 and Under Admitted"* — reworded in 1996 from
  "No Children Under 17", which effectively raised the floor to 18. **`xxx` was
  never an MPAA rating**; it is self-applied by the adult industry. The MPA
  system is **voluntary and has no legal standing**. So this studio's ladder is
  MPAA-*shaped*, with a top tier that is the operator's own label.

**Therefore `PINNED`'s "at least 21 years" stays, and the reason is now stated
rather than arbitrary.** It is **not** a legal minimum — 18 would be lawful. It
is a **margin against the model's output distribution**, and it is the only
defence this studio has:

> § 2257 protects by checking an ID, and **a synthetic performer has no ID**, so
> that mechanism has no analogue here. § 1466A turns on whether a depiction
> **appears** to be a minor. The only control left is that the output does not
> look like one — and a prompt asking for 18 puts the distribution **on** the
> boundary where one asking for 21+ pushes it away.

Same reasoning as `T4-11`'s body-part list: steering a distribution, not making
a declaration. The number is tunable **upward** with a reason; **18 is the floor
below which it may never go**, and lowering it to 18 would trade the margin for
nothing anyone needs.

- `T10-18c` **`PINNED`'s minimum age is never below 18, and the current value and
  its reason are recorded together.** A change to it is a change to the studio's
  only working steering control on this axis, and must be made with a rendered
  differential rather than a preference — `T4-11`'s shape.

**Decided 2026-08-13 by Jon, per tier:**

| tier | a minor may be… | and never… |
|---|---|---|
| `g`, `pg13` | referenced **and depicted** | — there is no nudity or explicit path to reach |
| `r` | **mentioned in lyrics and narrative text only** | depicted, cast, anchored, or present in **any text that reaches a render prompt** |
| `xxx` | **never mentioned, anywhere, at all** | — absolute, no exception, no override |

- `T10-18` **At `g` and `pg13`, a minor may be referenced and depicted**, because
  explicit content is structurally impossible there: `allow_nudity` false, no
  nude view reachable, no explicit wording in the album profile. **A song for a
  child, and a video for it, is a first-class thing this studio can make.**
- `T10-18a` **At `r`, a minor may be mentioned in lyrics and narrative text and
  must never reach a render prompt.** An `r` work may say a child exists in its
  story; it may not render one, cast one, anchor one, or carry the reference into
  any `image_prompt`, `video_motion_prompt`, scene text, character field or album
  profile field. **The boundary is the prompt, not the tier**, for the reason
  above: `PINNED` asserts every character is 21+, and a prompt asserting both is
  the contradiction this stack resolves badly.
- `T10-18b` **At `xxx`, a minor reference is refused everywhere in the work** —
  lyrics included, with no locked-context exception. Jon's words, and they are
  the right line: *anything with xxx should never mention children ever.* The
  `r` allowance does not extend upward, and a work escalated to `xxx` is checked
  in full at the moment of escalation (`T10-19`), not only at save.
- `T10-19` **Escalation is re-checked in full, at the moment of escalation.**
  Moving a work to a higher tier, enabling nudity, or adding a nude view
  re-screens **everything the work already contains** against the destination
  tier's rule, and refuses **naming the reference that blocks it** — a `g` work
  mentioning a child cannot become `xxx` at all, and cannot become `r` while the
  reference sits in any field that reaches a render prompt. This is the criterion
  that prevents the actual harm: **not the mention, but the escalation path**
  from a child-referencing work to an explicit one.
- `T10-19a` **The `r` allowance is enforced at the prompt boundary, and it is a
  positive check, not a filter.** Every string that reaches a render — composed
  positive prompt, scene fields, character fields, album profile — is screened
  at `r` exactly as it is at `xxx`. **Only lyrics and narrative fields carry the
  allowance**, and the set of fields that carry it is a named list, not "whatever
  is not a prompt". A field added later is outside the allowance until somebody
  adds it deliberately.
- `T10-20` **No override mechanism reaches `T10-19`.** Not `tier_overrides`, not
  the album profile, not tier wording, not a per-view prompt override, not an
  operator confirmation. A refusal that a determined operator can click through
  is a refusal that will be clicked through. **There is no supported path to an
  explicit render of a work that references a minor, and no code path that
  produces one.**
- `T10-21` **Removing the reference does not silently unlock.** Unlocking is an
  explicit act on an empty result, and **prior renders keep their attribution** —
  so a work cannot be laundered from child-safe to explicit by an edit.
- `T10-22` **The explicit path's refusal stays absolute and unchanged.** On any
  album, song or scene that is not locked non-explicit, a minor reference is
  refused exactly as today. Both halves in one test: **the locked path accepts,
  the explicit path refuses** — and the second is what `T8-4` and `T10-16`
  already assert.

#### What adversarial review found, and the one finding that is mine

Reviewed 2026-08-13 by grok and chatgpt, briefed to find the way it fails rather
than to approve it (`docs/reviews/MINOR-POLICY-REVIEW-*`). It found six bypass
paths. **Three are closed below. One is the acknowledged classifier gap. And one
is a hole this policy CREATED, which I did not see when I wrote it.**

- `T10-23` **The asset side channel is closed, and it is the serious one.**
  The policy binds *text* — fields, prompts, escalation. **It does not bind
  binary artefacts, and `T10-18` permits DEPICTING a minor at `g`/`pg13`.** So
  the click-path is: render the niece's video at `g` (now allowed), export a
  frame, and attach it in an `r`/`xxx` album as an anchor, an identity
  reference, an init image or a character pack. **Every text rule holds and a
  child's likeness reaches an explicit render.** The permission I added is what
  opened it.

  So: **an image rendered under a child-permitting lock is itself locked.** It
  carries that provenance, it cannot be selected as a reference, anchor, plate
  or init image by a work at `r` or `xxx`, and the refusal names the source. An
  artefact's tier travels with the artefact, not with the project it is pasted
  into.

- `T10-24` **Screening happens on the FINAL composed string, after every merge
  and after `PINNED` is welded on** — not on the field as typed. A check that
  runs pre-composition is a check on something else: scene generation, cast
  extraction, title and slug derivation, per-view overrides and template merges
  all assemble text after the field was screened, which is how *"mother and
  daughter"* typed into a narrative field arrives in a cast list and then in a
  prompt. `T10-19a`'s named-field allowance decides what may be *entered*; this
  decides what may be *sent*, and both run.

- `T10-25` **There is no tier-less draft.** A work with no tier set is treated
  as `xxx` for this rule — the most restrictive, not the least. Review found
  that content can be written before a lock exists and escalated before any save
  hook fires; failing closed on an unset tier removes the window rather than
  timing it.

- `T10-26` **Non-nude sexualisation of a depicted minor is refused at every
  tier.** `g`/`pg13` permit depiction because "no nudity path exists" — and
  review correctly found that nudity is not the only way to sexualise. Suggestive
  framing, lingerie-adjacent costume and fetish camera language applied to a
  depicted minor fall between `pg13`'s permission and `r`'s mention-only rule and
  are covered by neither. **This is the "anything close to it" line, and it is
  absolute.**

**What is NOT closed, stated rather than buried: the unworded depiction.** A
figure described as petite, doll-like, undeveloped or school-adjacent, with no
age word anywhere, passes every lexical screen in this document — and then
contradicts `PINNED`, which is the contradiction this stack resolves badly. The
guardrail's own comment already admits it *"needs a classifier"*. **No criterion
here closes it, and none pretends to.** It is the strongest argument for the
21-year margin in `T10-18c`, and the reason `T10-23` binds artefacts rather than
trusting the text screen to be complete.

**What this changes about risk, stated plainly rather than buried.** It makes the
studio *more* capable — a child may now be referenced somewhere, where before
nothing could — and that is a larger surface, not a smaller one. What makes it
safe is that the surface is a **dead end**: the locked context has no route to
nudity, to an explicit tier, or to an override, and `T10-19`/`T10-20`/`T10-21`
are the three walls. The previous rule had a smaller surface and a real gap
(the unworded childlike depiction it cannot catch); this one has a larger
surface and no route out of it. **The escalation interlock is the safety
property; the keyword screen never was.**

*This supersedes the cascade criterion first written here.* The original said
lyrics feeding scene generation must be re-screened as image-path text — correct
in mechanism, wrong in policy, because it would have refused the niece's video
at the second stage having accepted her song at the first. The cascade is still
real and is handled by the lock: a song written under `T10-18` derives scenes
that are locked with it.

## 7. Explicitly not building

- **No second screening implementation.** §6.
- **No model as a gate.** §5, and TRD-3 §10 owns the QC half.
- **No custom transcription model.** `lyrics.py` chooses between existing ones.
- **No clearing by blank.** `T10-3`, and it is a decision, not an omission.
- **No bulk edit of anything but the genre fields** until this document's
  criteria hold for those; the plan's scope is deliberate.

## 8. How every criterion above is to be verified

`TRD-6 §0`'s rules, cited not restated, plus **assert through the shared entry
point, never through the function it wraps** — earned on `T1-20d` 2026-08-13 and
directly relevant here, because `screen_prompt_field` (`T10-17`) and the
per-call backend choice (`T10-1`) are both single decisions applied from several
places.

### The positive half of each one-sided criterion

**Extended 2026-08-13 after external review** — grok and chatgpt independently.
`docs/reviews/TRD8910-*`.

| criterion | why it is one-sided | its positive half |
|---|---|---|
| `T10-1` backend chosen per call | checks switching, not "per call rather than per import" | **repeated calls in one long-lived process** switch after the gateway state changes — for `lyrics.py` **and** `vision.py`, both named in §2 |
| `T10-2` a fallback says so in the record | passes if the paid path is never taken, or nothing is recorded | **one local call and one fallback call**, both recording provider, the fallback marked |
| `T10-6` a bulk edit is one transaction | passes if the endpoint always refuses before writing | a successful multi-row edit **writes all** target rows; an induced mid-batch failure **writes none** |
| `T10-7` the pre-write count is the real count | passes if the count is always zero or writes are disabled | a batch with a **non-zero** predicted count writes **exactly that many** — the 12-vs-9 case by name |
| `T10-14` "does this match?" is refused as a prompt shape | classic one-sided refusal | **"describe what differs" is accepted** and returns non-verdict text on the same surface |
| `T10-17` one shared guard, no per-module copy | absence of copies is true when modules stop screening | disallowed text through **each of the four modules** is refused **via `screen_prompt_field`**, and an in-bound string passes |
| `T10-18` `g`/`pg13` may reference and depict | passes if nothing can ever be locked, i.e. the feature is absent | **a song referencing a child generates, and its G-tier video renders** — the niece case, end to end |
| `T10-18a` `r` mentions but never renders | passes if `r` refuses everything, or if nothing at `r` ever renders | an `r` work **with the mention in lyrics generates its song AND renders its video**, with the reference absent from every prompt string |
| `T10-18b` `xxx` never mentions | passes if `xxx` is unreachable | a **clean** `xxx` work still generates and renders normally |
| `T10-19a` the allowance is a named field list | absence of leakage is true when no field carries the allowance | a lyric field **does** carry it and a scene field **does not**, asserted per field |
| `T10-19` the lock cannot be lifted | passes if escalation is impossible for every work | a work **with no reference escalates normally** to `r`/`xxx` |
| `T10-20` no override reaches it | absence of a bypass is true when there are no overrides at all | overrides **still work** for everything else — asserted on a non-locked album |
| `T10-21` removing a reference does not silently unlock | passes if unlocking never happens | an **explicit** unlock on a cleaned work **does** succeed, and prior renders keep their attribution |
| `T10-22` the explicit path still refuses | this is the half that already exists | paired with `T10-18`: **locked accepts, explicit refuses**, one test |
| `T10-3` blank leaves alone | passes if bulk edit writes nothing at all | a **non-blank** field **does** write, same request |
| `T10-4` toggle-all is scoped to shown rows | passes if toggle-all selects nothing | with no filter, toggle-all selects **every** row |
| `T10-5` invalid refuses the batch | passes if every batch is refused | a **valid** batch writes all of it |
| `T10-9` an edit survives a re-fetch | passes if re-fetch is impossible | an explicit **re-transcribe replaces** them |
| `T10-11` model output is marked | a field that is present and never read | a **measurement** in the same payload is marked distinctly, and a client can separate them |
| `T10-12` advice writes nothing directly | passes with the advice surface deleted | **accepting** a proposal writes, and records the model |
| `T10-13` vision output is never a verdict | passes if `classify_sheet` is never called | it **is** called and its text **is** attached to a finding |
| `T10-15` mixadvice is relational | passes if no advice is shown | a set-level response **includes neighbour/context** that **changes when the surrounding set changes**; quote without neighbours is a different set |
| `T10-16` the image guardrail is off audio | passes if nothing is screened anywhere | the **explicit** image path still refuses the same string; `T10-18` is the g/pg13 exception |
| `T10-26` non-nude sexualisation of a depicted minor refused everywhere | passes if every minor reference is refused (feature absent) or if sexualisation alone is banned | **clean** child depiction at `g`/`pg13` still accepts; the **same** lingerie/suggestive/fetish wording on an adult still accepts at `r`/`xxx` |


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
| the four modules | **built, before this document** | earlier | `lyrics.py` 405, `chat.py` 330, `mixadvice.py` 247, `vision.py` 516 — 1,498 lines that no TRD cited until now |
| `T6-A2-library` HTML and JSON share library `song_count` | **built** | this change | `studio/test_t6_a2_library_numbers.py`: HTML `GET /` / `GET /songs` (`#library` `data-song-count`) and JSON `GET /api/songs` report the same `song_count` from `library_service.numbers()`; fixture 3 songs; stub arm forces `song_count=99` so a template `len` recompute goes red; `GET /songs` is 200 never 405 |
| `T10-1` backend chosen per call | **built** | this change | `studio/test_t10_1_per_call_backend.py`: gateway absent then present, same process — `vision.classify_sheet` records `xai` then `local` and the paid/local path is actually taken; `lyrics._pick_backend` / `available` switch `openai-whisper` → `faster-whisper` when the preferred package appears; `available()` re-probes after the first answer |
| `T10-2` a fallback says so in the record | **built** | this change | `studio/test_t10_2_fallback_record.py`: one local `classify_sheet` records `provider=local` / `fallback=false`; one local-then-xAI call records `provider=xai` / `fallback=true`; `score_candidate` success-after-fallback does not keep `available()`'s hope |
| `T10-3` blank leaves alone | **built** | this change | twelve songs, blank `genre`, set `genre2`; stored primary unchanged, secondary written. Same request writes the non-blank field (`studio/test_trd10.py`) |
| `T10-4` toggle-all is the shown set | **built** | this change | `shown()` filters `offsetParent`; pick-all walks `shown()`. Twelve shown change, three hidden do not. Unfiltered `/` lists every row |
| `T10-5` invalid refuses the batch | **built** | this change | twelve songs + valid `genre` + `genre2=NotAGenre` writes none; a valid batch writes all twelve |
| `T10-6` a bulk edit is one transaction | **built** | `c85037f` | POST `/songs/genres` writes all twelve; a BEFORE UPDATE trigger on the seventh song writes none (`studio/test_trd10.py`) |
| `T10-11` model output is marked | **built** | `ec74fb2` | `studio/test_t10_11_advice_marked.py`: `advice.separate` on mixadvice / vision / lyrics / chat payloads; `POST /sets/{id}/suggest` JSON. A measurement in the same payload carries `authored=measurement` and a unit |
| `T10-12` advice writes nothing directly | **built** | this change | `studio/test_t10_12_advice_writes.py`: `advice.retain` does not apply; `advice.accept` writes and records the model; `mixadvice.propose` leaves `set_items` unchanged; `POST /sets/{id}/suggest` retains a `proposal_id`; `POST /sets/{id}/proposals/{pid}/accept` writes the mix |
| `T10-13` vision output is never a verdict | **built** | this change | `studio/test_t10_13_classify_sheet_finding.py`: `classify_sheet` is called and its reason text is on a finding; flagged and empty both record `verdict=pass`; `h_classify` attaches the called text |
| `T10-14` "does this match?" refused; "describe what differs" accepted | **built** | this change | `studio/test_t10_14_prompt_shape.py`: `prompt_shape` refuses match questions naming the accepted shape; `describe_what_differs` returns non-verdict text; `classify_sheet` asks `DESCRIBE_DIFFERS` |
| `T10-15` mixadvice advice is relational | **built** | this change | `studio/test_t10_15_relational.py`: each item names `relative_to` (from/into neighbours); reordering the set rewrites those references; `quote_without_neighbours` drops `order`/`relative_to` and `about_set` is a different set |
| `T10-16` image path refuses the child string audio accepts | **built** | this change | `studio/test_t10_16_image_guardrail.py`: same string `"nursery rhyme for children"` accepted on `POST /songs/{id}/audio/generate` and `make_audio.workflow`; refused on the **explicit** path (`xxx` direction, scene fields) and `screen_prompt_field`. `T10-18` is the g/pg13 exception |
| `T10-7` pre-write count is the real count | **built** | this change | `preview=true` on POST `/songs/genres` returns `would_change=9` for the 12-vs-9 case and writes nothing; the write's `changed` is 9 (`studio/test_trd10.py`) |
| `T10-8` transcription records backend and source | **built** | this change | `studio/test_t10_8_transcript_record.py`: `transcribe()` returns `backend`; `h_transcribe` stores `lyrics_source=transcription` + `lyrics_backend`; POST `/songs/{id}/lyrics` stores `lyrics_source=supplied` with null backend; both remain distinguishable on the row; `store_lyrics` refuses a transcription without a backend |
| `T10-9` an edit survives a re-fetch | **built** | this change | `studio/test_t10_9_edit_survives_refetch.py`: save lyrics → `lyrics_edited=1`; re-fetch `h_transcribe` without force keeps the edit (`kept_edit`); POST `/songs/{id}/retranscribe` enqueues `force=True`, replaces the text, and the song page carries `REPLACE_WARNING` |
| `T10-10` empty vs fetch-failed are distinct states | **built** | this change | `studio/test_t10_10_empty_lyrics.py`: `store_lyrics` lands `lyrics_status=empty` and `lyrics_status=fetch_failed` on two rows with blank text; `lyrics.section_state` returns different values for T2-8c; empty transcription stores `empty`; failed transcription stores `fetch_failed` and the job still fails; `result_status` classifies failed/blank/present |
| `T10-11` model output is marked | **built** | this change | `studio/test_t10_11_advice_marked.py`: `advice.separate` on mixadvice / vision / lyrics / chat payloads; `POST /sets/{id}/suggest` JSON. A measurement in the same payload carries `authored=measurement` and a unit |
| `T10-17` one shared guard | **built** | earlier | `screen_prompt_field`; `MAX_PROMPT_FIELD` replaced `MAX_CHARACTER_FIELD` |
| **`T10-18`…`T10-26` the minor policy** | **built** | this change | `T10-18`, `T10-18a`, `T10-18b`, `T10-18c`, `T10-19`, `T10-19a`, `T10-20`, `T10-21`, `T10-22`, `T10-23`, `T10-24`, `T10-25`, `T10-26` are built |
| `T10-18` `g`/`pg13` may reference and depict | **built** | this change | `studio/test_t10_18_minor_g_pg13.py`: niece lyrics generate; G/pg13 scene saves; `build_song.workflow` and `build_refs.workflow` compose the child into the prompt; `r`/`xxx`/unset still refuse. Mutation: drop `tier=` or the g/pg13 skip and it goes red |
| `T10-22` locked accepts, explicit refuses (same string) | **built** | this change | `studio/test_t10_22_locked_accepts_explicit_refuses.py`: one child string accepted at g/pg13 on `check_text` and scene save; the same string refused at r/xxx/unset on `check_text`, xxx scene fields, and xxx direction. Mutation: drop the g/pg13 skip and the accept half goes red; drop the refuse and explicit save lands the child |
| `T10-18a` `r` mentions but never renders | **built** | this change | `studio/test_t10_18_minor_g_pg13.py`: `check_text` accepts lyrics/narrative at `r` via `field_kind`; render fields and `build_prompt` still refuse; an `r` work with niece lyrics generates audio and composes adult video/still prompts with no child in scene text; child scene save still 400. Mutation: drop `allows_minor_mention` or `MENTION_FIELD_KINDS` and the allowance half goes red |
| `T10-18b` `xxx` never mentions, lyrics included | **built** | this change | `studio/test_t10_18b_xxx_no_minor.py`: at `xxx`, `lyrics.screen` / `check_text` refuse; POST `/songs/{id}/lyrics`, audio generate, scene fields refuse a child string; existing child lyrics block an xxx storyboard enqueue; clean xxx lyrics save, audio generate, scene save, and `build_song`/`build_refs` still run. Mutation: drop the xxx lyrics screen and the refuse half goes red; refuse every xxx path and the clean half goes red |
| `T10-18c` `PINNED` ≥ 18 | **built** | this change | `PINNED_AGE_FLOOR = 18` in `guardrail.py`; the test extracts the number from `PINNED` and asserts it is never below the floor. The clause still says 21 |
| `T10-19a` the allowance is a named field list | **built** | this change | `studio/tiers.py` `R_ALLOWANCE_FIELDS` + `field_kind_for`; `studio/test_t10_18_minor_g_pg13.py`: lyric field does carry it and scene/character/prompt fields do not, asserted per field; unknown/missing field fails closed; `xxx` refuses even listed fields; `build_prompt` never gets the allowance. Mutation: drop `R_ALLOWANCE_FIELDS` or grant a prompt-boundary field and it goes red |
| `T10-19` escalation re-screens at destination, names blocker | **built** | this change | `studio/test_t10_19_escalation_rescreen.py`: `guardrail.screen_escalation` names the field; g work with prompt-child cannot enqueue `r`/`xxx`; lyrics-only child cannot become `xxx` but can become `r`; clean work escalates; enabling nudity on `g` re-screens and refuses. Mutation: drop the re-screen in `storyboard_service.enqueue` / `set_allow_nudity` and it goes red |
| `T10-20` no override reaches `T10-19` | **built** | this change | `studio/test_t10_20_no_override_reaches_escalation.py`: `guardrail.check_escalation` re-screens at dest tier; `confirm`/`force`/`tier_overrides`/`profile`/`wording`/`view_override` never lift a child-ref refusal; clean work escalates; `set_override` still applies on a non-locked album. Mutation: honour any override kwarg and it goes red |
| `T10-21` removing a reference does not silently unlock | **built** | this change | `studio/test_t10_21_no_silent_unlock.py`: g-tier niece scene sets `songs.minor_locked`; clearing the prompt leaves the lock; `POST /songs/{id}/unlock-minor` refuses while a reference remains and succeeds on a cleaned work; prior asset `minor_lock_attribution` survives unlock. Mutation: auto-clear the lock on edit, or rewrite asset meta on unlock → red |
| `T10-23` artefact tier travels; no g/pg13 child as r/xxx ref/anchor/plate/init | **built** | this change | `studio/test_t10_23_artefact_tier.py`: `check_artefact_use` refuses g/pg13 artefact into r/xxx/unset and names source; allows g↔pg13 and r/xxx non-child; `content_tier` stamp on meta; use-as-ref stamps; assign as r sheet 400s; `_collect_anchor_ref_paths(work_tiers=['r'])` refuses. Mutation: drop the check or the stamp and it goes red |
| `T10-24` screen final composed string after merge and PINNED weld | **built** | this change | `studio/test_t10_24_composed_screen.py`: fragments that pass field-as-typed form a blocked phrase when joined; `build_prompt` / `build_refs.workflow` / `build_song.workflow` refuse. xxx tier wording peels before screen (no self-trip). Mutation: check only a fragment before merge and the send path goes red |
| `T10-26` non-nude sexualisation of a depicted minor refused at every tier | **built** | this change | `studio/test_t10_26_no_sexualised_minor.py`: minor+lingerie/suggestive/fetish co-occurrence refused at g/pg13/r/xxx/unset and on scene save; clean child still accepted at g/pg13; adult sexualisation still accepted at r/xxx; r lyrics mention allowance does not open the hole. Mutation: drop the co-occurrence check before the g/pg13 skip and the g/pg13 refuse arm goes red |
| `T10-25` no tier-less draft | **built** | this change | `studio/test_t10_25_unset_is_xxx.py`: `policy_tier(None/""/" ")` is `xxx`; unset refuses on `check_text` / `build_prompt` / `screen_prompt_field`; form guard with `tier=g` accepts the same string. Mutation: map unset to `g` or drop `tier=` from `screen_prompt_field` → red |