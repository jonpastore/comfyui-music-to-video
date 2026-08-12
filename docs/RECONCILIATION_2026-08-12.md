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

**Decision required before the sets/DAW TRD is written**, because clip length
determines what the timeline is made of. The options are: leave CHUNK alone and
treat 30s as an experiment; make CHUNK per-model catalogue data; or make it
per-song. No TRD in this program is safe to finalise while this is open.

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

## Decisions needed

1. **CHUNK.** Fixed at 4.8125s, per-model, or per-song? Nothing downstream is
   safe to specify until this is answered.
2. **Fan-out floor.** Encode "do not spread fewer than 3 clips across the fleet"
   as a scheduling rule, or leave routing as it is?
3. **gamingpc.** Leave on WSL2+Docker at 2.59x the cost, or move it to native
   Linux and roughly triple its contribution?
