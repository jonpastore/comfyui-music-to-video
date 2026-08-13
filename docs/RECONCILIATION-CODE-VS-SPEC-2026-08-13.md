# Reconciliation · what the code does that no document describes

Status: written 2026-08-13. Answers four questions Jon asked: what did we lose
to the `/clear`, what is built that no TRD covers, what do the older plan
documents still hold, and what is actually in the seven TRDs.

Everything here is counted or grepped. The commands are in-line so a number can
be re-run rather than believed.

---

## 1. Nothing was lost. TRD-8 and TRD-9 never existed

Searched all **19 session transcripts** in
`~/.claude/projects/-home-jon-projects-comfyui/*.jsonl`:

    TRD-1  992 mentions        TRD-5  165
    TRD-2 1004                 TRD-6  335
    TRD-3  871                 TRD-7  359
    TRD-4  428                 TRD-8   12   <- all in THIS session
                               TRD-9   12   <- all in THIS session

Every one of those 24 hits is from the question I asked an hour ago, and
**zero other sessions mention either id**. The set was TRD 1-7 from the day it
was created; TRD-6 and TRD-7 were the last two written, both on 2026-08-13,
because two reviews found holes that needed owners.

So there is nothing to recover. **But the instinct behind the question is
right** — §2 and §3 are the two real gaps, and they are bigger than two missing
documents.

## 2. Code with no specification — 3,147 lines

Method: for each module, `grep -l` its name across `docs/TRD-*.md`.

| module | lines | what it does | TRD |
|---|---|---|---|
| `studio/vision.py` | 516 | VLM calls, local gateway first, xAI fallback. Contact-sheet review, anchor description, cast proposal, edit-instruction parsing | none |
| `studio/lyrics.py` | 405 | Lyric fetch and transcription, faster-whisper first | none |
| `studio/publish.py` | 399 | *"a CATALOGUE and a GATE. It does not upload anything yet"* + `publish_targets` | none |
| `studio/chat.py` | 330 | The two real providers behind the arc/advice surfaces | none |
| `studio/creds.py` | 309 | Credential storage, and the Slack alerting path | none |
| `studio/beatmatch.py` | 259 | rubberband fragments, Camelot-wheel ordering | none¹ |
| `studio/gpu.py` | 252 | *"ComfyUI and ollama share ONE 24 GB card and neither knows the other"* | none |
| `studio/fleet_watch.py` | 250 | Watches every backend, says something when one changes state | none |
| `studio/mixadvice.py` | 247 | *"Mixing decisions are RELATIONAL"* — AI advice over a set | none |
| `make_audio.py` | 180 | ACE-Step workflow writer. Same contract as `make_anchor` / `build_song` | none |

¹ `beatmatch.py`'s *capability* is covered — TRD-1 §2 lists beat grid, snap,
tempo ramp and Camelot ordering under "already built, do not rebuild". The
module name is simply never cited. **The other nine are genuinely unowned.**

**The three that matter most, and why:**

- **`vision.py`.** TRD-3 §10 forbids a VLM from being a *verdict* — "asked
  'does this match?', a model answers yes" — and permits it to write a
  *description*. That is a constraint on a subsystem no document specifies. It
  is the only place in the studio where a model's opinion enters, and the rules
  for it live in one prohibition inside another document.
- **`publish.py`.** 399 lines and a table, and its own docstring says it uploads
  nothing yet. Where a finished song or set *goes* is the last step of the whole
  pipeline and nothing describes it.
- **`gpu.py` + `fleet_watch.py` + `creds.py`.** The fleet's operational layer.
  `models.py` says what a box *can* run; nothing says what happens when a box
  goes away, who is told, or how the card is shared with ollama.

## 3. Plan documents no TRD ever absorbed — 1,992 lines

Method: `grep -l` each filename across `docs/TRD-*.md`.

| plan | lines | state | TRD |
|---|---|---|---|
| `AUDIO_BUILDOUT_PLAN.md` | **785** | partly built — an `audio` job kind and route exist; **the `takes` table its §4 specifies does not** | none |
| `UNRAID_BACKEND_PLAN.md` | 387 | built — peaches and ethan are backends; §8 is a postmortem | none |
| `SWARM_PIPELINE_PLAN.md` | 382 | built — phases 0-4 shipped, `RENDER_BACKEND=swarm` in production | none |
| `LIBRARY_BULK_EDIT_PLAN.md` | 229 | unbuilt | none |
| `ALBUM_ARC_AND_STAGING_PLAN.md` | 209 | partly built — §4's arc is `arc.py`, §5's credentials are `creds.py`; **§1 fade-to-black, §2 branding overlay and §3 interstitial card**: fade and branding are in `mixer.py`, the card is not | none |
| `EXTERNAL_REVIEW_2026-08-12.md` | 127 | input to TRD-1/2/3 | 1,2,3 |
| `OUTPUT_QC_PLAN.md` | 130 | **superseded** by TRD-3, which says so | 3 |
| `RECONCILIATION_2026-08-12.md` | 355 | input to TRD-1/2/3 | 1,2,3 |
| `SETS_MIXING_PLAN.md` | 205 | input to TRD-1 | 1 |
| `STORYBOARD_UI_RECONCILIATION.md` | 101 | input to TRD-2 | 2 |

**`AUDIO_BUILDOUT_PLAN.md` is the largest unowned specification in the repo.**
785 lines with a pre-mortem, a phasing section and a schema, and its core idea is
one this project believes everywhere else: *"a TAKE is one generated candidate
for a song, exactly as a `refs` row is one candidate frame… a take is never
written over `songs.mp3_path` — picking one is a separate act, and the take that
was not picked survives to be compared against it."* That is `T6-A5` — a new
candidate, never an overwrite — stated independently before `T6-A5` existed.

The audio stage shipped on 2026-08-12 **without** that model: `gen_audio` writes
assets, and there is no `takes` table.

## 4. What the seven TRDs actually contain

The summary asked for. Criteria counted with `grep -cE "^- .T<n>-"`.

### TRD-1 · Timeline and mixing — 32 criteria, 564 lines
1 the problem · 2 not in scope (already built) · 3 decisions taken (stereo pan;
clip length per song; seconds canonical) · 4 the timeline model (schema, model =
export, the clock) · 5 automation curves (incl. the loudnorm-flattens-curves
rule) · 6 waveform, peaks, playback · 7 three audiences · 8 `duck` and `layer` ·
**8a the master stage** · 9 export · 10 backend/front-end · 11 what it does not
own · 12 explicitly not building · 13 verification

### TRD-2 · Story arc and storyboards — 58 criteria, 683 lines
1 the problem · 2 not in scope · 3 data model (arc JSON canonical; versioning;
**§3.4 clip length — the biggest decision in the set**; §3.5 variable clip
length W1) · **6a per-scene model choice W2** · 4 generation flows (arc wand,
storyboard prompt, tier reaches the model) · 5 the storyboard page (time meter,
anchors, casting, identity) · 6 model selection · 7 navigation · 8
backend/front-end · 9 not building · 10 verification

### TRD-3 · QC and remediation — 30 criteria, 483 lines
1 the problem and its trap · 2 what exists / what the old plan got wrong ·
3 the finding IS the queue · 4 tier 1 deterministic checks · 5 tier 2 compliance,
gated on calibration · 6 tier 3 remediation through a human · 7 backend/front-end
· 8 where it runs · 9 not owned · 10 not building · 11 verification

### TRD-4 · Character anchors — 18 criteria, 181 lines
1 what was reported vs what the code does · **1a the boundary with TRD-7** ·
2 no silent defaults · 3 tier policy on every save · 4 positive prompt
construction · 5 the negative does not move · 6 what a front-nude XXX sheet
composes to · 7 not building · 8 verification

### TRD-5 · Clip rendering and refine — 10 criteria, 159 lines
1 `--refine` is a silent no-op on the default model · 2 two variants, ship A ·
3 the VRAM measurement that decides B · 4 the upscaler is catalogued · 5
per-model ceilings · 6 not building · 7 verification

### TRD-6 · Queue, lifecycle and storage — 25 criteria, 188 lines
**0 rules every document inherits (`T6-A1`…`T6-A6`)** · 1 the queue is a wait
state · 2 the lifecycle of an artefact · 3 identity: what joins to what · 4 where
the submitted request is kept · 5 SQLite concurrency · 6 migration and retention
· 7 not building · 8 verification

### TRD-7 · Anchor variations — 19 criteria, 201 lines
1 the premise, corrected · 2 more views, one place deciding what a view is ·
3 consistency: the anchor is the lock · 4 prompts to add · 5 not building ·
6 verification

**Totals: 192 criteria** (32/58/30/18/10/25/19). The `~197` quoted in the day-12
continuation and elsewhere is wrong for five of the seven — see
`docs/reviews/PLAN-TRD-4-7-RECOMMENDATIONS-2026-08-13.md`.

## 5. So what is missing, in one list

Ordered by how much shipped code sits behind it with nothing describing it.

| # | subject | evidence | proposed |
|---|---|---|---|
| 1 | **Audio generation and the song editor** | `AUDIO_BUILDOUT_PLAN.md` 785 lines unowned, `make_audio.py` 180 lines uncited, the `takes` model unbuilt, and TRD-1 §11 defers "the song-level audio editor" by name | **TRD-8** |
| 2 | **The fleet's operational layer** | `gpu.py` + `fleet_watch.py` + `creds.py` + `UNRAID_BACKEND_PLAN.md` + `SWARM_PIPELINE_PLAN.md` = 1,700 lines, all built, none specified. `models.py` says what a box *can* run; nothing says what happens when one goes away | **TRD-9** |
| 3 | **Publish and distribution** | `publish.py` 399 lines, uploads nothing yet, last step of the pipeline | TRD-10 |
| 4 | **Library, lyrics and the AI advice surfaces** | `lyrics.py` + `chat.py` + `mixadvice.py` + `vision.py` = 1,498 lines. TRD-3 §10 constrains the VLM without any document specifying it | TRD-11 |
| 5 | **Storage, retention, garbage collection** | deferred **by name** in both TRD-3 §9 and TRD-6 §6 — the same everyone-disowns-it signal that produced TRD-6 | TRD-12, or a section in TRD-6 |

**Recommendation for TRD-8 and TRD-9: rows 1 and 2.** Row 1 because it is the
largest orphaned specification and the shipped code diverges from it in a way
that matters (no `takes`). Row 2 because it is the only area where a failure is
*operational* — a box vanishing mid-render — and the studio already has the
alerting built with nothing saying what it promises.

Rows 3-5 are real and can wait; row 5 is arguably a TRD-6 section rather than its
own document, since §6 already says "nothing is deleted by this document".
