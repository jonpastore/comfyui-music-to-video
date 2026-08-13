# Reconciliation — every plan against the code, before any TRD is written

The input to the TRD program. Nine areas were named for specification; this
document says what each one actually is today, names every place a plan document
and the code disagree, and proposes where the TRD boundaries fall.

Everything here was checked against the code or measured on the fleet on
2026-08-12. Where a percentage appears it is weighted by remaining work, not by
section count.

---

## THE FORK — a 30-second clip contradicts the pipeline's core constant

This is the finding that outranks everything else in this document, and it did
not exist yesterday.

Measured today: **both 5090s rendered a 505-frame, 30.004s clip** — cerberus in
145.8s, gamingpc in 378.2s. Verified with ffprobe, files kept in `clipmax/`.

The pipeline cannot express that. `build_song.py:24`:

    CHUNK = LEN / FPS        # 4.8125s

`CHUNK` is imported by `build_storyboard.py`, `build_refs.py` and
`reroll_refs.py`. Clip count is `math.ceil(audio_duration / CHUNK)` in two
places. The code says so itself at `build_song.py:220`: *"Changing CHUNK per
model would change the clip count, and every ..."*.

**What that means concretely.** A three-minute song:

| clip length | clips | reference frames to approve | seams |
|---|---|---|---|
| 4.8125s (today) | 38 | 38 | 37 |
| 30s (measured possible) | 6 | 6 | 5 |

This is not a tuning knob. It changes how many scenes a storyboard describes,
how many reference frames a human approves, how many joins can drift, how the
contact sheets are laid out, and how long a failed clip costs to redo. It also
changes the QC surface — six long clips fail differently from thirty-eight short
ones.

**It is also not free.** A 30s clip is 6.2x the render of a 4.8s one, so a failed
clip costs 6.2x to redo, and identity drift *within* a clip is not something the
reference-frame mechanism can correct — today drift is bounded by re-anchoring
every 4.8 seconds.

**DECIDED 2026-08-12 by Jon: clip length is PER SONG, defined by the storyboard,
and scenes are the unit.** A scene becomes one clip. A scene longer than the
render ceiling is split, and the split is stitched by using **the last frame of
clip N as the first frame of clip N+1**.

The cost of the change is near zero and the reason is worth recording: nothing
downstream is solidified. No anchor has been chosen, no reference image approved.
The clip-merging design existed to stitch 7-8 short clips into one 30-second
scene "and hope they align" — the measurement removes the need for that entirely.
Greenfield, so the constant moves.

**Three consequences that follow, and they are not all free:**

1. **Scene-internal clips SERIALISE.** Chaining last-frame-to-first-frame means
   clip N+1 cannot start until clip N has finished — it needs the frame. Clips
   *within* a scene are a chain; different scenes stay parallel. The queue model
   (below) handles this correctly as long as a chained clip is not enqueued until
   its predecessor lands.
2. **Drift is now scene-scoped rather than clip-scoped.** At 4.8s every clip was
   re-anchored to an approved reference. With chaining, only the first clip of a
   scene is anchored and each subsequent clip starts from a *generated* frame, so
   error compounds along the chain. This is not an argument against the change —
   it is the specific thing QC tier 2 has to watch, and the reason a compliance
   score per clip matters more now than it did.
3. **A failed clip costs 6.2x more to redo.** Retry policy should reflect that a
   30s clip is not a cheap thing to re-roll.

---

## The nine areas

### 1. Swarm pipeline — ~95%, and now live

Phases 0-4 all landed 2026-08-12. `RENDER_BACKEND=swarm` is deployed and serving.
Inputs stage to both remote boxes by rsync; outputs are renamed back to what the
seven `gen_*` wrappers parse; retry walks `exactbackendid` over running backends.

**Contradiction found — doc vs code.** `SWARM_PIPELINE_PLAN.md` phase 3 says
`edit_audio` "moves `mp3_path` and is not" idempotent, and therefore excludes it
from retry. `app.py` writes a fresh timestamped file every run and never touches
`song["mp3_path"]`. The plan's stated reason for an exclusion list is false, and
no exclusion list was built. **Fix the plan.**

**New measurement that changes routing policy.** gamingpc is 2.59x slower than
cerberus warm-vs-warm (378.2s vs 145.8s for the same 505-frame workflow). Cause
confirmed: it runs **WSL2 + Docker** (`6.18.33.2-microsoft-standard-WSL2`,
`systemd-detect-virt` = `wsl`), so the GPU is reached through `/dev/dxg`
paravirtualisation rather than the kernel driver. Cerberus is native Linux.

The consequence is counterintuitive and should be encoded: **two clips on
cerberus alone (291.6s) beat two clips spread across the fleet (378.2s)**,
because the wall clock is set by the straggler. Fan-out wins from three clips up,
and is worth +38% throughput across a whole song.

**`models.py` now carries a false comment**: `BACKEND_STABILITY` says the fastest
card here is somebody's desktop. True of the silicon, false of delivered
throughput. **Fix with the measured numbers.**

### 2. Unraid / peaches — ~85%

§3 was rewritten today from architectural reasoning to measurement: **fp8 runs on
Turing** (Z-Image rendered a real 1024x576 image in 8.6s warm), and the real
constraint is the 10.58 GiB card, not the dtype. Two of three open questions
answered. `models.fits()` enforces the size check in code rather than prose.

**Remaining:** §6's "move audio generation here permanently" is effectively true
by filename curation but was never declared done. Garbage collection does not
exist anywhere (see area 9).

### 3. Sets & mixing — ~85% built, and the largest new specification

Phases 1-2 full, 3 nearly, 4 except `duck`, 5 except `layer`. Both gaps are
per-transition effects filed as per-item ones; both need the join graph changed,
not another filter fragment.

The new work — the DAW-like timeline — is specified in TRD #1. Outside review
converged on: the timeline model lives on the server and not in the DOM;
automation drawn at 60 Hz mouse events must be decimated or the filter graph
becomes pathological; "L/R split" is three different features (dual mono, stereo
pan, mid/side) and must be chosen before any UI exists; and **preview is not the
deliverable**, which is this codebase's oldest defect arriving somewhere new.

**Modes, resolved by Jon.** Not three UIs — three *audiences*. Easy is "solve it
for me" and therefore needs real automation (auto-level, auto-fade, one-button
master), not merely hidden lanes. Normal exposes customisation with enough
context to learn from. Advanced assumes audio-engineering knowledge. One data
model, one editor, three affordance sets — and easy mode is a **feature set**,
not a CSS class.

### 4. Album arc & storyboards — ~80%, and the most-changed requirement

§1 fade-to-black, §2 branding overlay, §4 the arc generator and §5 credentials
are built. **§3 the interstitial card is 0%** and appears only in two comments
explaining what precedes it.

What Jon has now asked for goes well beyond the existing plan: story arc as the
*setting and through-line* for the album, like a musical or an opera, with each
song's storyboard derived from it as a scene rather than written independently.
Full CRUD and version history on both, a wand that reads the lyrics and proposes
the arc from a themed prompt, and machine-readable output.

**Format decision (recommended, not asked):** JSON is canonical, Markdown is
rendered from it — the shape `build_storyboard.to_md` already uses, so there is
one generator and the two cannot drift. Never hand-edit the MD.

**Reuse, do not rebuild:** `prompts.py` is already a versioned table with usage
counts and numbers that are not reused after delete. Outside review was explicit:
do not build a custom git for this — no commit trees, no merge engine.

### 5. Library bulk edit — done

Correcting an earlier status of mine that said 75%. All four sections are built:
selection and the genre bar, async save, **async analyse** (`static/app.js:1519`
polls `/songs/analysis` and patches bpm/key/energy per row, reporting "3 of 31"
because there is one worker and one GPU), and the suggest route that returns its
evidence. I scored it low because I grepped the template and not the JavaScript.

### 6. Audio buildout — ~10%, and the plan is about a different model

`AUDIO_BUILDOUT_PLAN.md` is a 785-line plan for **ACE-Step 1.5** — full songs,
the intro problem, voices, a training library. Peaches publishes the 1.5 *nodes*
(`TextEncodeAceStepAudio1.5`, `EmptyAceStep1.5LatentAudio`) but only the **v1**
checkpoint is installed anywhere, so **Phase 0's spike has never been run**.

What shipped today is ACE-Step **v1** generation with a job, a route, a form and
stored takes. That is a precursor, not this plan. **Risk:** the catalogue now
marks ACE-Step `proven: stable`, which is true of v1 generation and could be
misread as this plan being underway. It is not.

Jon has since asked for a **media menu with a song-level audio editor** (distinct
from the set-level mixer) and post-render video editing that retains clips as
scenes. Neither is in the existing plan. That is a TRD, and it should be written
after the sets/DAW TRD because they share the timeline model.

### 7. Output QC — 0% built, plan exists, and the policy just changed

`OUTPUT_QC_PLAN.md` was written today: tier 0 records which backend produced an
artefact, tier 1 is deterministic checks, tier 2 is compliance as a calibrated
number, tier 3 is repair. Tier 0 has since been built by session B.

**Policy resolved by Jon, and it is not a conflict.** Outside review said "never
auto-heal". Jon asked for a review queue with the finding's own comments and a
button to approve the fix, where those comments are an editable prompt. Those are
the same rule — the human signs off — and Jon's version is strictly better,
because a finding that carries its own proposed remedy is actionable where a bare
PASS/FAIL is not. **The remedy prompt should be versioned in the same `prompts`
table as everything else.**

Scope has grown since the plan was written: images, audio, video clips, full
videos **and sets**, each with compliance percentage, variation, and an explicit
statement of what it can and cannot fix.

### 8. Publishing — policy 100%, upload 0%, no plan document

`publish.py` says it plainly: *"a CATALOGUE and a GATE. It does not upload
anything yet."* `refusal()` fails closed and nine services are catalogued. There
is a `/publish` page.

**This is the largest body of remaining work with no plan behind it.** Jon has
asked for: researched APIs for all nine, a tier-to-service compatibility matrix
in the tiers UI, and per-service icons on the playlist linking to what was
published. Outside review: use official SDKs, never hand-roll chunked upload,
never scrape to bypass limits, and do not build a social CMS.

### 9. Garbage collection — 0%, no plan, and it is now load-bearing

Does not exist. Nothing prunes anything, on any box.

Not urgent by disk pressure — cerberus is at 64% with 1.1 GB of ComfyUI output,
peaches has 8.7 TB free — but it became load-bearing the moment inputs started
being staged to remote boxes: the studio now pushes files to machines it does not
own the lifecycle of, and one of those (ethan) is offline more than it is online.

**Storage decision (researched):** `/mnt/user/media/meowp-studio/` on peaches —
a folder in the existing `media` share, which is already `shareUseCache="no"` so
writes land on the 8.7 TB array rather than filling the SSD pool. No new share
needed. The hard rule from the Unraid docs: never move files between
`/mnt/user/share` and `/mnt/diskN/share`; address `/mnt/user/...` only.

**The design this needs is a manifest, not a cron job**: a table of what was
pushed, where, when, and what job it belonged to, so a node that was offline gets
swept when it returns. "Wayne's ComfyUI garbage collection tool" on cerberus
turns out to be **ComfyUI-Manager**, which is a node installer, not a collector.

---

## Contradictions to fix, in one list

| # | where | what |
|---|---|---|
| 1 | `SWARM_PIPELINE_PLAN.md` phase 3 | claims `edit_audio` moves `mp3_path`; it writes a fresh timestamped file and never touches it |
| 2 | `models.py` `BACKEND_STABILITY` | comment says the desktop is the fastest card; measured 2.59x slower than the laptop |
| 3 | `AUDIO_BUILDOUT_PLAN.md` | is about ACE-Step **1.5**, whose weights are not installed; what shipped is v1 |
| 4 | plan docs generally | none record what is finished, which is why area 5 was scored 75% when it was done |
| 5 | `build_song.CHUNK` vs the 30s measurement | the fork at the top of this document |

Items 1-3 are one-line fixes and should land before the TRDs, so no TRD is
written against a false statement.

---

## Proposed TRD boundaries

Three now, in this order, each with acceptance criteria:

- **TRD-1 · Timeline & mixing.** The set editor's timeline model, waveform and
  playback, automation curves, channel model, and the ffmpeg round-trip. Owns the
  easy/normal/advanced affordance question. Blocked on the CHUNK decision.
- **TRD-2 · Story arc & storyboards.** Arc as setting and through-line, per-song
  scenes derived from it, versioned prompts reusing `prompts.py`, wand flows,
  JSON-canonical output. Owns the playlist UI restructure and the menu order.
- **TRD-3 · QC & remediation.** Tiers 1-3 across images, audio, clips, videos and
  sets; the review queue with an editable remedy prompt; what it can and cannot
  fix, stated per check.

Deferred to the next round, with a reason: **publishing** (research first, since
nine APIs decide the shape), **garbage collection** (needs the manifest schema,
which TRD-3's artefact model largely defines), **audio buildout / media menu**
(shares the timeline model with TRD-1 and should not be specified before it).

## Decisions — all three answered 2026-08-12

**1. Clip length is per song, from the storyboard. Scenes are the unit.** Split a
scene that exceeds the ceiling and stitch by last-frame-to-first-frame. See the
fork section above for the three consequences.

**2. Scheduling is a WAIT STATE, not a timing match.** When a resource frees, it
takes the next queued item that matches it. Jon's words: *"we should not be
trying to match timing, that's how race conditions happen."*

This replaces the fan-out floor this document originally proposed, and it is a
better answer. A floor of three was a heuristic derived from *predicted* render
times — scheduling by prediction, which is precisely the failure being named. A
pull model needs no prediction and dissolves the straggler problem on its own:
if cerberus is 2.59x faster it simply takes 2.59x more items, and the 291.6s vs
378.2s inversion never arises because nothing was ever split by a forecast.

Design notes that follow:
- Workers pull; the studio does not assign. A backend that is slow, off, or
  behind a VPN self-corrects by pulling less.
- **A chained clip is not enqueueable until its predecessor lands**, because it
  needs that last frame. The queue must express "ready" separately from "queued",
  or scene chains will be handed out in the wrong order.
- Match on capability, not on identity: an item requires a model, and
  `models.where()` already answers which boxes hold it with which spelling and
  whether it fits in that card.

**3. gamingpc stays on WSL2 + Docker.** Not a choice — it is somebody's Windows
desktop. It contributes at 2.59x the cost of cerberus and that is worth having.
Recorded so nobody re-derives the 2.59x as a bug and goes looking for a fix that
does not exist.

## The decision needs one more turn of the screw — `scene_seconds` cannot lengthen a scene

Found 2026-08-12 while generating the xxx storyboard for Rear Entrance at 15s and
30s scenes. `grok.generate_storyboard`:

    n_scenes = max(len(sections), math.ceil(song["duration"] / scene_seconds))

Rear Entrance has **25 lyric sections**, so:

| requested | ceil(195.792 / s) | sections | actual scenes | avg scene |
|---|---|---|---|---|
| 15s | 14 | 25 | **25** | 7.83s |
| 30s | 7 | 25 | **25** | 7.83s |

The `max()` floors it: once the lyric sections outnumber the requested count,
asking for longer scenes has no effect at all. Both runs produce the same 25
scenes, and grok's own `duration_guidance` came back "4-6 sec" / "7-10 sec" /
"9-11 sec" -- it wrote to the song's natural pacing.

**So "clip length is defined by the storyboard" resolves to 7.83s, not 30s.**

The storyboard's own strategy block explains why, and it is a deliberate design
rather than an accident:

    "coverage_model": "coverage-based; scenes are shot opportunities, not final clips"

Scenes and clips are already decoupled. `build_storyboard.py:213` computes
`nclips = ceil(dur / CHUNK)` and `allocate()` maps scenes onto clips. At
CHUNK=4.8125 that is 41 clips for 25 scenes -- a clip is a slice of a scene,
which is what "shot opportunity" means. At CHUNK=30 it inverts: **7 clips for 25
scenes, so each clip must swallow ~3.6 scenes**, and a clip sends exactly one
`video_motion_prompt`.

Two coherent answers, and this is a decision, not a bug:

1. **Scenes drive clips.** Change the formula so `scene_seconds` wins and grok is
   asked for 7 long scenes. The storyboard becomes the timeline. Cost: coarser
   shot description, and grok is writing against the lyrics' section structure
   rather than with it.
2. **Clips span scenes.** Keep 25 coverage scenes and merge each clip's scenes
   into one motion prompt. Keeps grok reading the song naturally; needs a merge
   step that does not exist, and a merged prompt is a new failure surface.

**Recommended: (1).** A 30s clip is one continuous camera move, and describing it
with four stitched shot descriptions is how a prompt comes to fight itself --
the same class of defect as the contradictory nude clause, arriving through
composition rather than through wording.

## Still open

The **render ceiling above 30s has not been found.** The ladder that produced the
30s result descended from 505 frames and 505 succeeded on the first attempt, so
the true maximum is untested. Now that scene length drives storyboarding, clip
count, reference approval and the timeline, the ceiling is a load-bearing number
rather than a curiosity. An upward ladder (561 / 673 / 841 / 1009 frames =
33s / 40s / 50s / 60s) is running.
