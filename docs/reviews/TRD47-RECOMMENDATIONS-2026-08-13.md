# What the two reviewers said about TRD 4-7, and what was done

Round 1, 2026-08-13. **The first external review these four documents have ever
had** — the four earlier reviews in this directory cover TRD-1/2/3 only, verified
by grepping them for any `T4-`/`T5-`/`T6-`/`T7-` id and finding none.

grok and chatgpt, independently, same brief, neither shown the other's answer.
Raw reviews beside this file. Lane: `llm -m grok` and `llm -m chatgpt`, prompt on
stdin, in parallel — the in-process agent lane is dead, so no agent reviewed
anything and none is claimed to have.

**Fabrication count: zero.** Every criterion id both models cited exists. The
brief asked for one thing above all — build the one-sided-criteria table these
four documents never had — and both delivered it, which is why this review
produced more work than any previous one.

---

## What landed, in the documents themselves

**All four now carry "The positive half of each one-sided criterion",** matching
TRD-1/2/3. That was the gap: the audit that produced those three tables was never
run over these four. **No criteria were added** — the tables pair existing ones.

| | one-sided, now paired | explicitly *not* one-sided |
|---|---|---|
| TRD-4 | 12 | `T4-2`, `T4-5`, `T4-8`, `T4-13`, `T4-15`, `T4-18` |
| TRD-5 | 7 | `T5-2`, `T5-5`, `T5-7` |
| TRD-6 | 14 | `T6-A2`, `T6-A3`, `T6-A4`, `T6-A6`, `T6-1`, `T6-3`, `T6-7`, `T6-8`, `T6-14`, `T6-15`, `T6-17` |
| TRD-7 | 12 | `T7-1`, `T7-4`, `T7-7` |

Listing what is *not* one-sided is what makes the tables trustworthy — grok did
this unprompted, and without it a table reads as a complete audit when it is a
sample.

## The findings that were more than a pairing

### 1. `image 2` has two roles across two documents — FOLDED into both

TRD-4 `T4-12` and §6: *"image 2 is the wardrobe reference"*. TRD-7 `T7-9`:
*"`base` is image2 and sets the framing"*. `T7-10` hedges *"the wardrobe **or**
plate reference"*.

One slot, two jobs, no rule for which wins — and the conflict is sharpest exactly
where it matters, because **a nude view drops the wardrobe wording**, so what
image2 carries there is undefined. **This blocks `T7-9`**, which is scheduled
work. Written into both documents as a decision to take before implementing.

### 2. Nobody owns wiring the chain guide frames — FOLDED into TRD-5

grok reported TRD-5 §6 as *refusing* to build frame handoff while TRD-2 `T2-10`
needs it. **That reading is wrong** — "No frame handoff from scratch" means *do
not reinvent it*, because `LTXVAddGuide` and friends are installed; TRD-2 W1-7
says the same from the other side.

**The misreading is the finding.** The sentence sits under *"Explicitly not
building"*, so a reviewer read it as a refusal and an implementer will too — and
underneath it, the real gap is genuine: **no document says who wires those nodes
into `build_song`.** TRD-2 owns the criterion, TRD-5 owns the graph, neither
claims the implementation. That is the shape of the hole TRD-6 was written to
fill. Recorded in TRD-5 with the note that the sentence belongs in §2.

### 3. The duet case — FOLDED, then CORRECTED, and the correction is the lesson

**As first written here, this finding was wrong about the guard and right about
the hole**, and it is left in with its correction rather than quietly fixed.

The claim was: *"nothing asserts a duet can still name two people"* now that
`T7-10` refuses *"the character in image 3 is reference 3"*. Session B checked
it against the code and answered within the hour. **A guard already existed** —
`build_refs._selfcheck`, shipped in the same commit as the `T7-10` fix and run by
`check_integration.py`, asserted that a named cast member composes to *"The
character in image 3 is Nyx: a rival DJ."*, and a test already took one cast
member end to end through `workflow()`.

**The real defect was narrower and did need closing: every existing check used
exactly ONE cast member.** With one name and one file there is no slot collision
and no name/file swap available to get wrong. `7836d6f` adds two, each named by
the slot its own file is wired to, asserted as
`{"image2": "nyx.png", "image3": "ghost.png"}` — asserting only that both names
appear would pass with both wired to one image, which is precisely the blend the
mechanism exists to prevent.

**Why the correction matters more than the finding.** "Nothing asserts X" is
itself a claim that can only be made by looking, and this one was made from the
documents rather than from the tree. It is the same class as the criteria this
review exists to find: an assertion about an absence, unfalsified. The reviewers
were reading documents and could not have caught it; the session holding the
files could, and did.

### 3a. `image 2`'s two roles — CORRECTED: a documents conflict, not a shipped one

Also verified against the tree rather than the documents. `grep "wardrobe
reference"` across `make_anchor.py`, `build_refs.py` and `app.py` returns
**nothing** — `T4-12`'s prescribed wording was never implemented on the anchor
path, so the contradiction with `T7-9` never reached a render.

**Resolved by moving TRD-4, not the code.** On the anchor path the references
are an unordered set of photographs of one character; the honest wording is
*"Image 2 is another photograph of the same character"*, which is true on
clothed and nude sheets alike. Naming it "the wardrobe reference" would
re-impose the face-then-outfit ordering that was deliberately removed, and would
declare a role that a nude sheet's own dropped wardrobe wording then
contradicts. Slot naming belongs to the cast path. `T7-9` is resolved by
`d3f2f6a`'s `base=None`.

### 4. `T5-1` lets the default model raise forever — FOLDED into TRD-5

"adds a second pass **or** raises naming the reason" is satisfiable indefinitely
by raising, on `ltx25`, which is the catalogue default. Better than today's
silent no-op, and not what the document wants. Whether the shipped behaviour is
*raise*, *variant A* or *hide the flag* is unstated; `T5-6` only covers the case
where B does not fit.

### 5. Cite-not-restate breaches — FOLDED as notes

`T5-4` restates `T6-A5` (*"still a new file, never an overwrite"*). `T6-6`
restates `T6-A5` **inside TRD-6 itself** — §0's rule broken in §0's own document.
Both flagged in place rather than rewritten, since the plan's Phase 0 owns that
surgery.

Both models independently returned **NOTHING FOUND** for restatements of
`T6-A1`…`T6-A4` in TRD-4/5/7 — the consolidation held there. A recommendation
looked for and not found is worth as much as one that was.

## Rejected

| finding | reason |
|---|---|
| grok: TRD-5 §6 *refuses* to build guide handoff | misreading — "from scratch" means do not reinvent. The ownership gap underneath it was folded instead |
| chatgpt: measure refine variant B before shipping A | Jon decided A-then-B on 2026-08-13, on the argument that A costs no extra VRAM and the base render already peaks at 95.8% of the card. `T5-5` is the measurement that reopens it |
| chatgpt: `songs.duration` should be decode length, not ffprobe | plausible, and it re-opens a decision `T6-13a` closed. Recorded as the settling measurement rather than a change: compare ffprobe, decode length and boundary clip counts on songs near the frame threshold |
| chatgpt: `T4-4` is an inherited-rule restatement | self-marked UNSURE, and it is not — the refusal-names-the-control rule is TRD-4's own |

## Still open, not folded

Both reviewers raised these and none is a document edit:

- **TRD-4 and TRD-7 never name their `T6-A1` curl loop**, while TRD-1/2/3 each do.
- **Anchor re-rolls never cite `T6-A5`**, so "a variation is an `anchors` row like
  any other" could be implemented as an overwrite.
- **`T7-2`'s derivation rule is unstated.** "Nudity is derived, not enumerated" —
  if the derivation is a `_nude` suffix match, it recreates the omission failure
  it fixed. The settling test: a view with nude semantics and a non-matching key.
- **OOM mid-refine** — `failed` or requeue, and how it interacts with `T6-4`.
