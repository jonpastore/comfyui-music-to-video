# What the two reviewers said about TRD 8-10, and what was done

Round 1, 2026-08-13, over the three documents written the same day to absorb five
orphaned plans and claim ~4,600 lines of uncited code. grok and chatgpt,
independently, same brief, neither shown the other's answer. Raw reviews beside
this file. Lane: `llm -m grok` and `llm -m chatgpt`, prompt on stdin, in parallel.

**Fabrication count: zero.** Every criterion id both cited exists.

The brief asked one thing above all: **find the one-sided criteria the
documents' own tables missed.** Each document already shipped with a
positive-half table; the question was what those tables did not cover. Both
models answered it, and **seven of their findings overlap exactly**, which is
the strongest signal available from two independent readers.

---

## Both reviewers, independently — all FOLDED

| criterion | the gap | positive half added |
|---|---|---|
| `T8-5` | bounds "and says which bound refused" passes if everything is refused with any label | just under each of `MAX_TAGS`/`MAX_LYRICS`/`MAX_AUDIO_SECS` **accepted**, just over refused **naming that bound** |
| `T8-9` | "the only place bridge arithmetic exists" is pure absence — true when the feature is deleted | a valid replace-span **succeeds through the route**, and changing `bridge_seconds` **moves the outcome** |
| `T9-5` | "sorted to the back, not dropped" passes if such a box is never considered | a plan with a fitting **and** a non-fitting box still includes the slow one **later in the order** |
| `T9-7` | states a hazard with no visible failure if the walk is deleted | after a refusal, **a subsequent attempt is made and the sequence is observable** |
| `T9-16` | "no credential in the repo" passes with no credential feature at all | a credential **from the store is usable** and its provenance recorded |
| `T10-6` | "one transaction" passes if the endpoint always refuses before writing | success **writes all**; induced mid-batch failure **writes none** |
| `T10-7` | the pre-write count passes if it is always zero | a non-zero predicted count writes **exactly that many** — the 12-vs-9 case by name |

## Found by one, verified, FOLDED

`T8-3` (all three origin paths, not one), `T8-6` (both edges, not one),
`T8-11` (a take with a voice **and** one without), `T8-13`/`T8-14`/`T8-15` (the
song editor's three, each vacuous if the editor is absent), `T9-10`…`T9-13`
(the four traps, each green if nobody looks), `T9-15` (a render **result**
carries its reading), `T10-1` (both modules, and *per call* not merely
*switching*), `T10-2`, `T10-14`, `T10-17`.

**Twenty-five positive halves added across three documents. No criteria added
by the pairing itself** — `T10-18` below is the only new criterion.

## The three structural findings

### 1. TRD-8 contradicted itself, and both reviewers caught it — FOLDED

The preamble says every `T8-n` **can fail**. `T8-12` — *no cloning path ships
without `T8-10`* — is **green by construction** while no cloning path exists.

**Marked PROVISIONAL rather than deleted**, in the shape TRD-3 already uses for
`T3-6` and `T3-18`: it cannot today distinguish "refuses to clone without
consent" from "cannot clone", and it now says so. grok argued for dropping it
until a cloning path is proposed; **rejected**, because the criterion's value is
that it is already written on the day someone proposes one, and a consent rule
invented under pressure is the one that gets weakened.

### 2. Two absorbed tables and a deferred menu had no owner — FOLDED as scope

grok found that TRD-8 §1 greps four missing tables, §2 designs two, and **two
were absorbed and then dropped**:

- **`take_voices`** — in scope, criterion deferred until `T8-10` holds, because
  per-region voice assignment is meaningless before consent is enforced.
- **`library`** — **explicitly out of scope**, and said so rather than absorbed.
  The plan's `library` table and TRD-10's subject are different things, and
  whether it adds anything beyond `songs` is unestablished. Absorbing a table
  nobody has justified would be inventing a requirement.
- **The media menu** — TRD-1 §11 defers *"the song-level audio editor **and the
  media menu**"*; TRD-8 claimed the deferral and covered only the editor. **It
  has no owner**, and that is now written down rather than lost twice.

### 3. `T10-18` — the lyric-to-storyboard cascade. NEW CRITERION

The sharpest finding of the review, and the only one that produced a new
criterion rather than a positive half. **Both halves are individually correct,
which is why nothing caught it:**

- A lyric mentioning a child **is accepted** on the audio path (`T8-4`,
  `T10-16`) — deliberately, measured, because Jon makes songs for his nieces and
  the image guardrail refused *"nursery rhyme for children"*.
- Lyrics **feed TRD-2's section structure and scene generation** (`T10-10`).

So text the audio path rightly permits can reach the **image path**, which
rightly refuses it, **by a route neither document watches.** The criterion
screens the derived scene and image text as image-path text and names the lyric
line it came from. Both halves: the song still generates **and** the scene
derivation refuses — accepting the lyric while refusing the scene is the correct
outcome, not a contradiction. Nothing about it weakens `T8-4`.

## Rejected

| finding | reason |
|---|---|
| grok: drop `T8-12` until a cloning path exists | §1. A consent rule written under pressure is the one that gets weakened |
| grok: `T9-7` mixes a criterion with a design note | true, and the design note is load-bearing — it is *why* retargeting beats another retry. Kept, with the positive half added |
| chatgpt: TRD-9 should gate deploys on live-fleet criteria | out of scope for the document; it is an operational decision and is in `PRD-8-10` §7 as Jon's |

## Still open, recorded not folded

- **The audio path's dependence on retargeting has no TRD-8 criterion.**
  `T9-1`/`T9-2` own retargeting, and TRD-9 fixtures need never submit an
  ACE-Step workflow — so a regression in audio filename spelling could stay
  green. Both documents are individually complete and the seam is not covered.
- **`T6-A1`/`T6-A2` are inherited by citation only** in all three documents. If
  the song editor, bulk edit and advice-accept surfaces are not pinned as
  JSON-reachable somewhere, they are unpinned. grok marked this UNSURE for want
  of TRD-6's body; it is correct that no `T8/9/10` criterion asserts it.
- **`chat.py`'s arc behaviour** — TRD-10 claims the module, TRD-2 owns the arc,
  and neither states which one pins the chat call itself.
