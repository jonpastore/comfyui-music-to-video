# TRD-8 · Audio generation and the song editor

Status: written 2026-08-13. **Absorbs `docs/AUDIO_BUILDOUT_PLAN.md` (785 lines),
which no TRD owned**, plus `make_audio.py` (180 lines) and `mixer`'s splice and
bridge path, neither of which any TRD cited. Also takes the song-level audio
editor that **TRD-1 §11 defers by name**.

Acceptance criteria are `T8-n` and each **can fail**. Rules every document
inherits are `TRD-6 §0` (`T6-A1`…`T6-A6`) — cited here, never restated.

---

## 1. The problem: the stage shipped without the plan's central idea

The audio stage went live on 2026-08-12 — a job kind, a route, a form,
`make_audio.py` writing ACE-Step workflows, and `mixer.splice_bridge` repairing a
span. **The plan that specified it was never implemented in the part that
matters**, and nothing noticed because no document owned it.

`AUDIO_BUILDOUT_PLAN.md` §4 defines four tables. **None of them exists** —
verified by `grep -c "CREATE TABLE IF NOT EXISTS <t>" studio/db.py`:

    takes        0        voices     0
    take_voices  0        library    0

Its central sentence is one this project believes everywhere else and arrived at
independently, before `T6-A5` was written:

> *"A TAKE is one generated candidate for a song, exactly as a `refs` row is one
> candidate frame. Generation is cheap and the good one is picked by ear, so a
> take is never written over `songs.mp3_path` — picking one is a separate act,
> and the take that was not picked survives to be compared against it."*

What shipped instead writes each take as an `assets` row under
`db.DATA/audio/<slug>/`. That is not wrong — nothing is overwritten — but it
loses the second half of the plan's reasoning: *"tags/lyrics/bpm/keyscale are
copied ONTO the take rather than read back off the song: the song row moves on,
and a take that cannot say what it was asked for can be neither regenerated nor
explained six months later."*

- `T8-1` **A take records what it was asked for**, not a pointer to a song row
  that has since moved: tags, lyrics, seed, duration and the parameters as sent.
  Asserted by changing the song's tags after generating and confirming the take
  still reports the tags it was generated with. A take that reads its prompt back
  off the song passes a presence check and fails this one.
- `T8-2` **A take is never written over `songs.mp3_path`.** Picking one is a
  separate act with its own record. `T6-A5` owns the rule; this is its audio
  realisation, and the positive half is that **both the picked and the unpicked
  take remain listed and playable**.
- `T8-2a` **`songs.style_text` is the ask that produced the audio, and it is
  owned here.** Found 2026-08-13 by sweeping every user request across all 19
  session transcripts against the document set: it was **asked for explicitly**
  — *"we should add a style field for the songs in addition to lyrics. I
  generate the style with chatgpt. I want to save them"* — it is **built**
  (`ALTER TABLE songs ADD COLUMN style_text`, and `app.py:944` calls it *"the
  prompt the AUDIO was generated from — drums, BPM"*), and **no TRD, PRD or DDD
  named it.** It appears only in three of the orphaned plan documents, so the
  fold that gave those plans owners missed the one field they had in common.

  It is TRD-8's because it is `T8-1` for songs that predate takes: **the record
  of what was asked for, kept beside the artefact.** The criterion is that it
  survives the take model rather than being superseded by it — a take generated
  from a song carries the song's `style_text` forward into its own `tags`, so
  the provenance is not lost when the song row moves on.

  *(`playlists.style_text` is a different thing under the same name — the
  album's overarching look, consumed by the anchor path. It is TRD-4's and is
  not this criterion.)*
- `T8-3` A take records **which path produced it** — generated, resynthesised or
  bridged. Already true of the shipped stage and asserted here as a regression
  test, because `models.py` is explicit that what ACE-Step returns is new audio
  and never a shortened original.

## 2. What already exists — do not rebuild

| built | where |
|---|---|
| ACE-Step workflow writing, same contract as `make_anchor` / `build_song` | `make_audio.py` |
| The `audio` job kind, the route, the form, takes copied into the studio's data dir | `app.py` (`@jobs.handler("audio")`) |
| Span replacement: ffmpeg cuts, ACE-Step writes the bridge, seams crossfaded | `mixer.splice_bridge`, and `mixer.bridge_seconds` owns the arithmetic |
| Form bounds | `MAX_TAGS = 600`, `MAX_LYRICS = 10000`, `MAX_AUDIO_SECS = 240.0` |
| Per-box filename divergence and routing to the box that can load it | `models.ALIASES` — cerberus holds `ace_step_v1_3.5b.safetensors`, peaches holds `..._fp16`; `pipeline._retarget` rewrites per box |
| Loudness and band-energy measurement | `effects.measure_loudness`, and TRD-3 §4.3's audio checks |

**The bounds are form sanity, not model limits, and must keep saying so.**
`TextEncodeAceStepAudio` publishes `lyrics` as a plain multiline STRING with no
declared maximum, so there was no number to read off the box and none was
invented. A document that later presents 10000 as ACE-Step's limit is wrong.

## 3. Screening on the audio path is deliberately different

**The image guardrail is off the audio path and must stay off.** Measured: the
tags *"nursery rhyme for children"* came back `ContentRefused: … child, nursery`.
`guardrail.check_text`'s own docstring justifies refusing any mention of a minor
by *"there is no legitimate reason for a tier definition, style note or generated
scene to reference children"* — **a claim about depiction, which does not carry
to music.** Jon makes songs for his nieces.

- `T8-4` A lyric or tag mentioning a child is **accepted** on the audio path and
  **still refused** on the image and video paths. Both halves in one test, or the
  criterion is satisfied by screening everything or nothing.
- `T8-5` The audio path still bounds what it accepts (`§2`'s three constants) and
  says which bound refused. A length bound is the screening that belongs here.

## 4. Repair: the span, and the case that deleted audio

- `T8-6` A span **within a crossfade of either edge** is spliced without losing
  audio and without lengthening the song. The recorded failure: a 20 s track
  spliced at 0.1 s came back **20.193 s** with the first 0.1 s gone, because
  `splice_bridge` kept a piece only `if head > xfade` and the route sized every
  bridge as gap + 2×xfade when an edge span has only **one** seam. Fixed in
  `871d820`; asserted here so it cannot regress. Edge span 0–5 s returns 20.036 s
  against an original 20.036 s.
- `T8-7` The route **refuses a span outside the track** before the GPU runs.
  Replacing 11 s–100 s of a 12.3 s song generated 89 seconds of music and threw
  it away. The job keeps its own check as the backstop for a track that changes
  length between enqueue and run — **both, because they guard different moments.**
- `T8-8` "Replace a span" and "re-synthesise the whole track" cannot both be
  asked for in one request. The form offers them as alternatives and nothing
  enforced it.
- `T8-9` **`mixer.bridge_seconds()` is the only place bridge arithmetic exists.**
  The route asks it rather than computing; a second implementation is how the
  edge case came back the first time.

## 5. Voices, and the part that is not a technical question

`AUDIO_BUILDOUT_PLAN.md` §4 specifies a `voices` table with `source` and
**`consent`** columns. That column is the requirement, not a field.

- `T8-10` A voice reference **cannot be stored without a recorded source and a
  recorded consent state**, and the refusal names which is missing. A nullable
  consent column that nothing enforces is a record that will be filled in with
  silence.
- `T8-11` A take generated with a voice reference **records which voice**, so
  the question "what is this built from" is answerable from rows. Paired
  positive: a take generated without one records that too, rather than leaving
  the field ambiguous.
- `T8-12` Nothing in this document ships a voice-cloning path for a **real named
  person** without `T8-10` satisfied first. Stated as a criterion because it is
  the one requirement here that a later reader might treat as an aspiration.

## 6. The song-level audio editor

**TRD-1 §11 defers this by name** — *"the song-level audio editor and the media
menu. Deferred; they share this timeline model, which is why they come after this
document and not with it."* It is claimed here, and it inherits TRD-1's model
rather than inventing a second one.

- `T8-13` The editor reads and writes **the same automation model** as the set
  timeline (`automation` rows, `automation.MAX_POINTS`, RDP decimation, linear
  and hold only). A second curve model for one track is the drift TRD-1 §5.0
  exists to prevent.
- `T8-14` The predicted length is the rendered length, to
  `mixer.SET_DURATION_TOLERANCE` — imported, never restated (TRD-1 `T1-7`,
  TRD-3 `T3-11`).
- `T8-15` **Preview says it is a proxy** and lists what it does not apply, as
  data in the response (`T1-16`'s rule, this document's surface).

## 7. Explicitly not building

- **No second automation model.** §6, and TRD-1 owns it.
- **No second loudness implementation.** `effects.py` owns it; TRD-1 §9 and
  TRD-3 §4.3 both call it.
- **No re-implementation of the splice arithmetic.** `mixer.bridge_seconds`.
- **No image guardrail on the audio path.** §3, decided and measured.
- **No claim that ACE-Step shortens an original.** It returns new audio;
  `models.py`'s entry was corrected once already for saying otherwise.

## 8. How every criterion above is to be verified

`TRD-6 §0`'s rules, cited not restated, plus the one this document is most
exposed to: **listen to it.** The video half of this project learned that an
image that looks wrong has to be opened; the audio half has the same failure
mode and no equivalent habit yet. A take that measures correct loudness and band
energy can still be unusable.

### The positive half of each one-sided criterion

**Extended 2026-08-13 after external review** — grok and chatgpt independently
found eight more one-sided criteria than the first table carried, with seven
overlapping. `docs/reviews/TRD8910-*`.

| criterion | why it is one-sided | its positive half |
|---|---|---|
| `T8-2` a take is never overwritten | true when nothing generates | **both takes listed and playable** after a second generation |
| `T8-3` a take records which path produced it | passes if only one path is reachable, or if no take is recorded for some | **generated, resynthesised and bridged each produce a take listed with its path** — all three, or the criterion covers one |
| `T8-4` the audio path accepts a child mention | passes if nothing is screened anywhere | the **image path still refuses it**, same test |
| `T8-5` the path bounds what it accepts and names the bound | passes if it refuses everything with any label | values **just under** each of `MAX_TAGS`, `MAX_LYRICS`, `MAX_AUDIO_SECS` are **accepted**; just over are refused **naming that bound** |
| `T8-6` an edge span does not delete or lengthen | one edge tested is not "either edge" | **both the start edge and the end edge** splice and preserve length |
| `T8-7` an out-of-range span is refused | passes with the whole splice path deleted | an **in-range span splices and returns the expected length** |
| `T8-8` both operations at once refused | passes if neither can be requested | **each alone succeeds** |
| `T8-9` `bridge_seconds` is the only arithmetic | pure absence — true when the feature is deleted | a valid replace-span **succeeds through the route**, and a change to `bridge_seconds` **moves the outcome** |
| `T8-10` no voice without consent recorded | passes if voices cannot be stored at all | a voice **with** source and consent **is** stored and usable |
| `T8-11` a take records which voice | the "records that too" half passes if voices are never accepted | **one take with a voice and one without**, both generated, both recording the distinction |
| `T8-13` the editor uses the shared automation model | passes if the editor is absent or read-only | an edit **written in the song editor is consumed by the shared path**, same limits and modes |
| `T8-14` predicted length is rendered length | vacuous if nothing renders or nothing is predicted | a real render **emits a prediction first** and lands within `SET_DURATION_TOLERANCE` |
| `T8-15` preview declares itself a proxy | passes if preview is removed | the endpoint returns proxy data **and a non-empty `not_applied` list** |

**`T8-12` is PROVISIONAL and the preamble's "each can fail" does not hold for
it.** Both reviewers caught the document contradicting itself: it says every
`T8-n` can fail, and `T8-12` — *no cloning path ships without `T8-10`* — is
green by construction while no cloning path exists. **Marked provisional rather
than deleted**, in the shape TRD-3 uses for `T3-6` and `T3-18`: it cannot today
distinguish "refuses to clone without consent" from "cannot clone", and it says
so. It becomes failable the day a cloning path is proposed, which is the day it
matters.

## 9. Two tables the absorbed plan specified and this document did not claim

Found by review, and named rather than quietly dropped.
`AUDIO_BUILDOUT_PLAN.md` §4 defines four tables; §1 greps all four as absent and
§2 designs two of them.

- **`take_voices`** — the junction carrying per-region voice parameters, so a
  voice applies to a span rather than a whole track. `T8-11` only requires a take
  to record *which* voice, which the junction is not. **In scope, and its
  criterion is deferred until `T8-10` holds**, because a per-region voice
  assignment is meaningless before consent is enforced.
- **`library`** — **explicitly out of scope here.** The plan's `library` table
  and TRD-10's subject are different things: TRD-10 owns the song catalogue and
  its bulk editing, which is the library the operator uses. Whether the plan's
  table adds anything beyond `songs` is unestablished, and absorbing a table
  nobody has justified would be inventing a requirement. **If it is wanted it is
  TRD-10's**, and this line exists so it is not lost a second time.

**The media menu is also disowned.** TRD-1 §11 defers *"the song-level audio
editor **and the media menu**"*, this document claims that deferral, and §6's
criteria cover only the editor. The media menu has **no owner** — recorded here
rather than silently absorbed.


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
| the audio stage itself | **built, before this document** | 2026-08-12 | `make_audio.py`, the `audio` job kind, a route, a form; takes copied into the data dir |
| `T8-6`…`T8-9` the splice repair path | **built** | `871d820` | the edge-span defect: a 20 s track spliced at 0.1 s came back 20.193 s with audio missing. After: 20.036 s against 20.036 s. `mixer.bridge_seconds` owns the arithmetic |
| `T8-4` the audio path accepts a child mention | **built** | `1cac5bb` | the image guardrail is off the audio path, measured — "nursery rhyme for children" had been refused |
| **`T8-1`…`T8-3` the take model** | **NOT BUILT, and it is the headline** | — | `takes`, `voices`, `take_voices`, `library` — **all four have zero references in `db.py`**, verified independently by both sessions. Takes are `assets` rows, so **a take cannot say what it was asked for** |
| `T8-10`…`T8-12` voices and consent | **not built** | — | `T8-12` is **provisional**: green by construction while no cloning path exists |
| `T8-13`…`T8-15` the song editor | **not built** | — | deferred by TRD-1 §11 and claimed here |
