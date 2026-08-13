# TRD-10 · The library, lyrics, and the AI advice surfaces

Status: written 2026-08-13. **Absorbs `docs/LIBRARY_BULK_EDIT_PLAN.md` (229
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
| Per-song catalogue fields, sortable headers | the library page |

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

- `T10-18` **The lyric-to-storyboard cascade is screened at the boundary it
  crosses.** Found by review, and it is the sharpest thing either reviewer
  returned because both halves are correct on their own: a lyric mentioning a
  child **is accepted** (`T8-4`, `T10-16` — Jon makes songs for his nieces), and
  lyrics **feed TRD-2's section structure and scene generation** (`T10-10`). So
  text that the audio path rightly permits can arrive at the **image path**,
  which rightly refuses it, by a route neither document watches.

  The criterion: when lyrics are used to derive a storyboard, the derived
  **scene and image text is screened as image-path text**, and a refusal names
  the lyric line it came from rather than failing anonymously. **Both halves:**
  the song still generates, and the scene derivation refuses — accepting the
  lyric and refusing the scene is the correct outcome, not a contradiction.

  *Nothing here weakens `T8-4`.* The audio path's acceptance is unchanged; this
  is about what happens two stages later, on a different path, with a different
  policy that was always going to apply.

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
| `T10-3` blank leaves alone | passes if bulk edit writes nothing at all | a **non-blank** field **does** write, same request |
| `T10-4` toggle-all is scoped to shown rows | passes if toggle-all selects nothing | with no filter, toggle-all selects **every** row |
| `T10-5` invalid refuses the batch | passes if every batch is refused | a **valid** batch writes all of it |
| `T10-9` an edit survives a re-fetch | passes if re-fetch is impossible | an explicit **re-transcribe replaces** them |
| `T10-11` model output is marked | a field that is present and never read | a **measurement** in the same payload is marked distinctly, and a client can separate them |
| `T10-12` advice writes nothing directly | passes with the advice surface deleted | **accepting** a proposal writes, and records the model |
| `T10-13` vision output is never a verdict | passes if `classify_sheet` is never called | it **is** called and its text **is** attached to a finding |
| `T10-16` the image guardrail is off audio | passes if nothing is screened anywhere | the **image path still refuses** the same string |
