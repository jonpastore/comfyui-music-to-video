# CRITIC PASS — `docs/AUDIO_BUILDOUT_PLAN.md` + architect-review.md

**VERDICT: ITERATE**

Not REJECT: the pre-mortem and test plan are genuinely adequate rather than merely long
(§6 below argues this on evidence). Not APPROVE: phase 2's central mechanism is misread,
the plan misquotes its own principle 3 in its own favour, and it cites two guards that do
not guard. The Architect is right about most of what it found and overreaches in three
places I verified against the box and the deployed database.

Everything below that I checked myself is marked **[verified]** with the line. Everything
I took from the brief as settled, or from either document on trust, is marked as such.
§9 is my own gap list.

---

## 1 · Principle–option consistency: does Option A follow from principle 3?

**Adjudication: the Architect wins the reading of the principle. The plan wins the
decision anyway — but not for the reason it gives, and it must stop quoting principle 3
as support.**

The file, verbatim [verified — `studio/requirements.txt:1-7`]:

```
# Studio app deps. Deliberately NOT installed into ComfyUI's venv -- ComfyUI runs
# on aiohttp and its own torch build, and nothing here should be able to disturb
# a working renderer. This list installs into a separate venv (see deploy.sh).
...
# needs no torch at all: the studio venv stays ~1GB instead of ~6GB, and there is
# no second CUDA/torch stack sitting next to ComfyUI's.
```

Both readings are textually present, and each document quoted the half that suited it:

- The **purpose** clause (lines 2-3) is "nothing here should be able to disturb a working
  renderer" — the protected asset is ComfyUI, and the protection is one-directional. The
  Architect is right about this and the plan's decision driver 3 does not say it.
- The **"no second CUDA/torch stack"** clause (line 7) is also there, which the Architect's
  §1 argument 2 elides. So the plan's "anything that puts a second torch on the box is
  paying a very large bill" is not invented — but note *what kind* of bill line 7 is about:
  it is a **size** argument, stated with a number (~1GB vs ~6GB), in a paragraph justifying
  faster-whisper over openai-whisper. Transplanted to this question it is worth very little:
  disk is 1.4 TB free, and the plan itself says so.

So on the literal text, Option A — three third-party dependency trees plus a hand-written
numerics patch into ComfyUI's own venv — is the option that touches the protected asset.
The plan's own cons list registers this only as "three things that can break
independently", which understates it: a bad third-party import in `custom_nodes/` breaks
**ComfyUI startup**, and that takes the video half of the studio — the currently working
half — down with it. That is a category of failure the plan never names anywhere.

**But the Architect's conclusion does not follow, and it knows why.** Its §7 item 6:

> Upstream ACE-Step's own repo. Not cloned, not on the box, no web lookup. The plan's
> Option B claims ... are **unverified by me**.

Its §1 argument 1 — "upstream's repo exposes edit/repaint as a supported entry point" — is
the load-bearing input to the whole boundary redraw, and it is the one thing it did not
check. The remaining steelman arguments (venv boundaries, serialization, failure-mode
asymmetry) establish that B is *tolerable*, not that B *delivers the feature*. If upstream's
repaint is itself a research script, B buys the same fork in a different venv **plus** a
second stack, and the trade flips back.

**Neither boundary is the right one on the evidence either document actually has.** The
Architect's own §0 finding supplies a third: ComfyUI already does masked latent denoising
generically (`samplers.py:634-642`, `utils.py:1315-1316`, blocked only by
`SetLatentNoiseMask`'s 4-D reshape — settled per the brief). That is Option A, zero
internals, ~10 lines. The defensible boundary today is:

> **A for what ComfyUI exposes, including `noise_mask` repaint. `chunk_masks` goes behind a
> measurement, not behind a venv — and the A/B question is reopened only if `noise_mask`
> seams audibly.**

That needs no B for phases 0-2 at all, and it converts the sharpest disagreement in the
pair into a one-afternoon experiment. Deciding a venv architecture on two unverified
premises (upstream's API surface; whether the seam is audible) when one afternoon settles
the second and a `git clone` settles the first is the actual error here, and both documents
make it.

---

## 2 · Was Option B steelmanned, or strawmanned then dismissed?

**Strawmanned — mildly, but on the con that carries the rejection.**

Ratio in the original plan: Option B gets **one** sentence of pros and **five lines** of
cons. The single pro is the same unverified upstream claim. That alone is a fairness
problem, but the decisive one is this con:

> "A second GPU consumer outside the single-worker policy that `jobs.py` calls 'the whole
> concurrency policy'."

**False for the shape B would actually take** [verified — `studio/pipeline.py:41-53`].
`_run_script` already runs external CLIs from inside a job handler with
`subprocess.run(..., check=True, timeout=SCRIPT_TIMEOUT)`, and every build script in the
repo goes through it. A CLI in a third venv invoked from a handler is serialized by exactly
the same single worker as a ComfyUI submit. The Architect is right; the plan's own
architecture already contains the counterexample. B is "outside the single-worker policy"
only if run by hand — which the plan then explicitly sanctions for LoRA training, conceding
the point in the next paragraph.

Remove that con and B's cons reduce to: a second torch install (a disk-and-maintenance
argument, weak given 1.4 TB free), two upgrade paths (real), and "the voice chain would
still need ComfyUI" (real, and the strongest of the three).

**Third option (external music API): fairly invalidated.** Two independent grounds, either
sufficient, and the right length for an option that fails on a stated project premise —
the whole document exists to remove this dependency. One nit: "none of them expose latent
timeline masking or per-section voice replacement either" is an unevidenced assertion about
three external products. It changes nothing (the local-first constraint already kills it),
so state it as belief rather than fact or delete it.

---

## 3 · Risk mitigation: does every pre-mortem have a detection that would detect it?

**PM2 — no. The Architect is right, and I endorse it without qualification.** A monkeypatch
never goes missing; the node registers whether or not the patched body still matches
upstream. `/object_info` cannot see the failure the plan itself calls "the dangerous shape".
The guard must be a runtime assertion on the patched function (source hash or signature),
checked at import and asserted in `check_integration.py`.

**PM4 — yes, sound.** "Phase 0 measures peak for ACE alone; phase 3 measures it again for
the full chain" would detect the failure. The Architect's §5 argues the plan fears the
wrong *term* (`memory_usage_factor` 4.7 × a 3000-frame latent ≈ 282 MB of activation, not a
headline) — I did **not** verify that arithmetic (§9). Note it changes no decision: the
mitigation is "measure it in phase 0" under either reading. Worth one corrected sentence in
driver 2, not the section the Architect gave it.

**PM1 and PM3 — the detections would work, but neither is specified well enough for anyone
but the author to run.** See §4.

**The gap that repeats is not PM2's.** PM2's is a blind instrument. What repeats across PM1,
PM3 and the phase-3 gate is a different hole: **three of four detections are "the user
listens", and not one of them says what material, what order, who administers it, or what
failure sounds like.** "Judged by the user" and "blind" are both asserted; a single listener
who prepared both stimuli cannot blind themselves without a script that randomises and
labels the files.

**Two failures have no pre-mortem at all**, and both are the shape this plan is otherwise
good at catching:

- **The monkeypatch stops applying** (as opposed to "the node breaks"). Different failure,
  different detection, currently unowned. This is PM2's real content once the Architect's
  extension lands.
- **A community node pack breaks ComfyUI startup.** Phase 3 installs two unvetted third-party
  packs (`ComfyUI_Seed-VC`, the `audio-separation-nodes-comfyui` family) into the renderer's
  venv. A bad import there does not degrade audio — it stops video rendering, the half that
  works today. Detection is cheap and must be stated: restart ComfyUI and confirm
  `/object_info` still answers *before* any audio work, and install the packs one at a time.

---

## 4 · Acceptance criteria: which are failable?

**Failable, keep as written:**

- Phase 0 gate — "peak VRAM and one generated track exist as numbers in the log". Someone
  else can run it and it can fail. This is the model for the rest.
- §8's trigger to begin infra — "the user has generated a full song locally, end to end, in
  a voice they chose, that they prefer to its Suno equivalent, and has cut a video to it."
  Excellent, and proof the plan can write these when it tries.
- Most of §5's integration tests (see §5 below).

**Not failable / underspecified:**

1. **§7 "Minimum path to 'sounds amazing'".** This is the plan's own headline success
   condition and it is not a criterion. Replace with the §8 trigger, which is already
   written three pages later and is exactly the same claim made testable.
2. **Phase 2 acceptance — "everything outside the mask is unchanged."** The first clause
   ("the giggling is gone") is a judgement, fine. The second clause is *measurable* and no
   measurement is given. It also cannot be bit-exact: decode → latent → decode → encode
   guarantees drift. Specify it: correlate or null-test the unmasked region against the
   source (`ffmpeg` can do the null test) and state a tolerance in dB. Without a number
   this criterion cannot fail, and it is the one criterion that distinguishes a working
   repaint from an unmasked regeneration — i.e. from the exact silent failure PM2 names.
3. **Phase 3 gate — "an A/B by ear of the same track unmodified, through cover mode, and
   through the SVC chain. If the chain loses, multi-voice waits."** Not runnable by anyone
   but its author. Missing: which track, which voice, which reference clip; the listening
   order and how it is blinded; **what "loses" means**; and a tie-break. The plan's own PM3
   names three distinct failure modes for this chain (Demucs artefacts in the stem,
   consonant smearing at low step counts, the converted vocal seated on an accompaniment it
   was not mixed against) — so score those three axes separately. A chain that wins on
   timbre and loses on consonants must not resolve to one thumb, and with one thumb it will.
   n=1 on one track is also too thin for a gate that decides whether a 4-6 day phase ships;
   name three tracks spanning the catalogue's range.

---

## 5 · Verification: does the test plan test the design or the code?

**Mostly the design, and it is the strongest section of the plan.** Evidence rather than
impression: the three tests it names as siblings all exist and are the right siblings
[verified] — `test_audio_edit_rejects_hostile_params` (`studio/test_app.py:295`),
`test_explicit_not_passed_to_grok_or_pipeline` (`:372`),
`test_storyboard_direction_is_screened_before_any_model_is_called` (`:1094`). Writing new
tests as siblings of existing ones is how they land in the house idiom instead of beside
it, and `test_generated_lyrics_are_screened_before_any_model_is_called` is the single most
valuable test in the list — a lyrics box genuinely is the largest new free-text surface.

### The Architect's two specific findings

**(a) The `audio_original` recording gap — CORRECT, verified in full.**

- `studio/app.py:2197-2201` records `audio_original` **inside the edit-submit route**,
  guarded by "record the true original exactly once, before mp3_path can ever move".
- `studio/app.py:2208-2215` `use_audio_edit` writes `mp3_path` with **no recording at all**.
- `studio/app.py:2219-2225` `revert_audio` raises `"no original recorded for this song"`
  when the asset is absent.
- The existing `test_audio_edit_use_and_revert` (`studio/test_app.py:306-325`) passes only
  because line 312 posts an edit first, which is what runs the recording.

A generate → use-take flow never passes `app.py:2199`. The plan's sentence — "'Use this
take' moves `songs.mp3_path` through the same `audio_original` asset the audio-edit path
already records, so revert keeps working and is not recorded twice" — describes a mechanism
that does not exist at the site the take flow would use, and
`test_using_a_take_records_the_original_once_and_revert_restores_it` would fail as designed.
The Architect's fix (extract to a shared helper) is right and is ~4 lines.

**(b) `take_voices` NULL/NULL — CORRECT, and it is the plan's own comment that creates it.**
`-- NULL/NULL = the whole track` plus
`test_voice_regions_do_not_overlap_and_cover_only_the_track` cannot both hold: a NULL region
overlaps every bounded one, so the test needs a special case for a sentinel the schema did
not need. I prefer a cheaper fix than the Architect's ("forbid mixing the two forms"):
**store `0` / `duration` and delete the sentinel.** `takes.duration` is a column on the same
take, so the value is always known at write time, and the test collapses to one interval
predicate with no branch. Deleting a special case beats adding a rule that forbids it.

### Where the test plan tests something that is not there

**The `check_integration.py` item is false.** The plan says "the existing `RENDERED_ROLES`
assertion keeps forcing `build_track.py` to exist." It does not, twice over [verified]:

- `studio/models.py:458-462` asserts only that a `cli` **string** is present, and then that
  `key in renderable(m["role"])` — but `renderable()` (`studio/models.py:324-331`) returns
  *exactly* the entries that have a `cli`. The second assertion is a tautology.
- Nothing anywhere checks that a script file exists, and nothing consumes
  `renderable("audio")` at all — the only call sites are `app.py:1024` (video) and
  `app.py:2570` (artwork).

Combined with the Architect's correct catch that `ace_step_v1` already carries
`"cli": "ace_step"`, phase 1's "**forced**, not chosen" framing is wrong on both legs. The
honest version is the Architect's: the catalogue advertises an audio model whose CLI does
not exist, and phase 1 makes that honest. The fix is one line in `check_integration.py`
asserting `build_track.py` is present in `SCRIPTS` — which also protects the plan's own best
catch, the `deploy.sh` rsync omission [verified — `studio/deploy.sh:24-26` lists
`build_refs.py build_song.py build_storyboard.py make_anchor.py reroll_refs.py
make_contact_sheet.py guardrail.py fix_ref.py`, and a new script would indeed be missing].

**The missing test that matters most.** Every proposed repaint test is about refusal,
routing or range (`refuses a range outside the track`, `refuses when the node is missing`,
`an end region uses ffmpeg not the model`). **Not one of them fails when the mask is
silently discarded** — which is the plan's own named dangerous shape and the Architect's
verified `ace_step15.py:1119-1120` finding. The test that fails in that case is the phase-2
acceptance criterion turned into an assertion: the masked region changed, the unmasked
region did not, to a stated tolerance. It belongs in **phase 0**, before the node is
written, not in phase 2 after.

**On dropping the `test_load.py` overlap test** — the Architect is probably right
(`studio/jobs.py:286` asserts `order == [("start",1),("end",1),("start",2),("end",2)]`,
which is a serialization proof), but I read that line in a grep, not in context, and did not
confirm the two jobs `jobs.demo()` orders are of *different kinds*. Read `jobs.demo()` in
full before deleting the test; if both jobs are the same kind, the plan's cross-kind claim
is not strictly covered and the test earns its place.

---

## 6 · Deliberate mode: is the pre-mortem/test plan adequate or merely long?

**Genuinely adequate.** Deliberate mode says reject a weak one, so here is the evidence
rather than the compliment:

- Every pre-mortem names a **mechanism**, not a worry. PM2 names two specific locals; PM3
  names four specific lossy stages; PM4 names the ceiling and the resident figure.
- PM1's mitigation **restructures the phasing** — "phase 2 works on uploaded mp3s, so it
  delivers the headline feature regardless of the verdict" — rather than adding a checkbox.
  A mitigation that changes the plan is a real one.
- PM4 produces a **prohibition** derived from the failure ("do not add an audio lane"), which
  is what a pre-mortem is for and what padded ones never contain.
- The test plan names 12 integration tests, at least 3 verified as correct siblings of
  existing tests, plus contract checks at the right seam. This is not length for its own sake.

Two structural holes, both listed in §3: the monkeypatch-stops-applying failure, and the
community-pack-breaks-ComfyUI-startup failure. Add those and the pre-mortem is complete.

---

## 7 · Adjudicating Architect vs Plan

### Architect right, plan must change

Extensions 1 and 2 and the phase-2 re-cost (settled per the brief); PM2's blind detection;
the `audio_original` gap; `take_voices` NULL/NULL; the `models.py` `cli` overstatement;
`free_vram()` needing to run **between** the three submits rather than once per job and not
being allowed to fail silently into an OOM [`studio/pipeline.py:86-110` — `free_vram` returns
`False` and continues by design, verified]; "no seam at all" → "no seam at the section
boundaries"; `takes.parent_id` being NULL for both a fresh generation and a repaint of an
upload; and principle 1's claim that `songs.lyrics` carries `[Section N]` tags — **0 of 31
deployed rows contain `[Section`** [verified against `cerberus:~/meowp-studio/data/studio.db`].

### Architect overreaches — three corrections

**(i) "Open question 2 asks about `[verse]`/`[chorus]`, which is not what is in the column."
FALSE as stated** [verified, same database]. The 31 rows carry **202 distinct bracket tags**.
The distribution is dominated by production directives, which is the Architect's real point
and it stands — `[pause]` ×96, `[build]` ×71, `[drop]` ×55, `[silence]` ×18, `[dry kick]` ×9 —
but `[verse]` appears **26 times across 13 of the 31 songs**, alongside `[intro]` ×11,
`[outro]` ×12, `[breakdown]` ×16, `[end]` ×13. Open question 2 is therefore **incomplete,
not misdirected**, and the rewrite the Architect demands would discard the half of it that
is about real data. The correct question covers both: what does 1.5 do with semantic section
tags *and* with production directives, since the column contains both, mixed, in the same
sheet.

**(ii) §7 item 12 — "SETS_MIXING_PLAN.md phase 2 ... is itself unbuilt ... there is none [no
implementation]." FALSE** [verified]. `studio/analyse.py` exists — 164 lines, committed and
unmodified, implementing `librosa.beat.beat_track`, chroma against Krumhansl–Schmuckler, RMS
energy, a downbeat-offset guess, and a `demo()` that checks the Camelot table and recovers
every rotation of both profiles. `studio/db.py:207-210` has already added `songs.key`,
`beat_grid_json`, `energy`, `downbeat_offset`.

What does **not** exist is the wiring: there is no `analyse` job kind
[`studio/jobs.py:56-64` lists transcribe / anchor / storyboard / refs / reroll / clips /
render_song / render_set / edit_audio] and no route. So the plan's "reuse the analyse job,
do not build a second analyser" is *more* correct than either document knew — but phase 4
depends on a prerequisite that is half-built and **unowned by either plan**. The Architect
graded phase 4 "Sound" without noticing this. It is the second most consequential of its 14
gaps.

**(iii) §5's VRAM section** is probably right and is over-weighted. It changes prose, not
decisions; the phase-0 gate is unchanged under either reading, as the Architect itself
concludes.

### Which of the Architect's 14 gaps most undermines its recommendations

**Item 6 — upstream ACE-Step's repo, never checked.** Its §3 synthesis is the review's
headline recommendation, and §1 argument 1 states the dependency explicitly: B is worth a
second stack because upstream "exposes edit/repaint as a supported entry point". Nobody has
looked. A `git clone` and a grep costs ten minutes, no GPU and no weights, and it is the
single input that decides A versus B. Runner-up: **item 9** — whether a `custom_nodes/`
module can monkeypatch `comfy.ldm.ace.ace_step15` before a model loads at all. If it cannot,
phase 2b under A is not expensive, it is impossible, and the architecture question settles
itself. Third: item 12, above.

### Is "A for what ComfyUI exposes, B for anything reaching inside the model" better than the plan's boundary?

**Better diagnosis, unearned boundary.** It is right that the plan's boundary was drawn by
a cost estimate that turned out to be wrong by an order of magnitude, and right that
redrawing follows. But it replaces one under-evidenced line with another: B is only the
better home for `chunk_masks` if upstream actually has it, which is item 6. Draw the
boundary at **capability, then measurement** — A for everything ComfyUI exposes including
`noise_mask`; `chunk_masks` blocked behind (a) does `noise_mask` seam audibly, and (b) does
upstream expose repaint. Both are answerable this week, and neither document needs to guess.

---

## 8 · What NEITHER document has established

### The finding neither made: `songs.key` and `songs.keyscale` are two different key columns

[verified] `studio/db.py:207` already adds `songs.key`, commented "key is Camelot notation
(`8A`)", and `studio/analyse.py:95` returns exactly that. The plan's §4 adds
`ALTER TABLE songs ADD COLUMN keyscale TEXT` for ACE's input, and on the box
`comfy_extras/nodes_ace.py:46` builds that enum as
`f"{root} {quality}"` over 17 root spellings × {major, minor} = **34 options** — "Ab minor",
"C major". So the schema ends up with two key columns in two notations and **nothing converts
between them**. Consequences the plan states as settled and are not:

- **SETS amendment correction 1** — "`songs.bpm` and key are now known, not detected, for
  anything the studio generated" — is **false for key**. Generation writes `keyscale`;
  nothing writes `key`; so `SETS_MIXING_PLAN` phase 3's harmonic matching still has to run
  the (unbuilt) analyse job on a track the studio generated itself, which is precisely the
  thing the correction claims is no longer necessary.
- **Competitive advantage §6.3** — "the set can ask for the tempo and a **Camelot-adjacent
  key** and get them" — needs the *reverse* map, which is one-to-many: the enum offers both
  spellings of every enharmonic (C#/Db, D#/Eb, F#/Gb, G#/Ab, A#/Bb), so 34 options collapse
  onto 24 Camelot codes and a spelling has to be chosen going the other way.

The fix is cheap and half-written already: `analyse._CAMELOT` is keyed by
`(pitch_class, mode)` [verified — `studio/analyse.py:29-34`], so a root-name → pitch-class
dict plus the existing table derives `songs.key` from `keyscale` at generation time in about
five lines, in the module that already owns the notation. Do that instead of adding a second
key column that nothing reconciles.

### Also unestablished by both

- **Whether upstream ACE-Step exposes repaint** (Architect item 6). Decides the architecture.
- **Whether a `custom_nodes/` module can monkeypatch `ace_step15` before model load**
  (Architect item 9). Decides whether phase 2b is possible under A.
- **Who owns the `analyse` job kind.** `analyse.py` exists, the job does not, and neither
  plan claims it. Phase 4 assumes it.
- **Everything about Seed-VC, the separator packs, and fish.audio.** Both documents take the
  plan's numbers on trust (1–30 s reference, zero-shot quality, 4–10 / 30–50 steps, BigVGAN,
  `POST /v1/tts` as the whole public surface). Nothing has been installed, called or heard.
- **Which database the running service opens.** I confirmed
  `cerberus:~/meowp-studio/data/studio.db` has 31 songs with `style_text` and
  `~/meowp-studio/app/data/studio.db` has 0 and no `style_text`, matching the Architect's
  item 14 — and additionally that **neither has the `key` column yet**, so `db.py`'s
  migrations 207-210 are committed but not deployed. Which one the service opens is still
  unknown, and phase 4 writes to it.

### The single measurement that would most reduce uncertainty

**Download the ACE-Step 1.5 weights and generate two tracks from one real deployed row: once
with `songs.lyrics` exactly as it sits, once with bracket tags stripped.**

It settles four things at once — peak VRAM against the 24463 MiB ceiling (driver 2, PM4,
phase-3 buildability), wall-clock, whether the 202 arrangement directives get *sung* (phase
1's scope, principle 1, open question 2, and the strip step the Architect demands), and it
produces the first artefact for PM1's A/B. More importantly it is the **prerequisite for
every other measurement either document wants**: the `noise_mask` afternoon, the `chunk_masks`
spike, the short-reference cover-mode question and the phase-3 gate are all blocked on
weights that are not on the box. Nothing else can go first.

**The single free thing that should happen before it:** clone upstream ACE-Step and grep for
its repaint/edit entry point. Ten minutes, no GPU, no weights — and it decides the A/B
question that this whole review pair is arguing about on two guesses.

---

## 9 · Required changes, ordered

Ordered by whether they change the architecture, then by cost.

1. **Clone upstream ACE-Step and confirm (or refute) that it exposes repaint/edit as a
   supported entry point.** Record the answer in the plan. Until it is answered, delete
   Option B's sole stated pro and the Architect's steelman argument 1 — both currently assert
   it. This gates items 2 and 3.
2. **Rewrite the third finding in §1 and re-cost phase 2** as a fork of three upstream
   functions (`extra_conds`, `forward`, `prepare_condition`) with a silent failure mode, not
   "a two-line monkeypatch plus a node". Delete "~100 lines" from §7's cost table and from
   §1's "a capability A gets for ~100 lines", which is the sentence the whole A/B decision
   rests on.
3. **Insert phase 2a — `noise_mask` repaint** (`latent["noise_mask"]` written as `[1,1,T]`,
   ~10 lines, no ComfyUI internals), ship it first, and make phase 0 measure the `chunk_masks`
   fork as a **delta against it** rather than as a yes/no. Gate 2b on 2a seaming audibly.
4. **Correct decision driver 3** to quote `requirements.txt` accurately: the stated purpose is
   protecting the renderer, and Option A's three community packs plus a numerics patch land
   inside the renderer's venv. State that as a real cost of A, with the mitigation (install
   one pack at a time; confirm ComfyUI restarts and `/object_info` still answers before any
   audio work), rather than citing the principle as support for A.
5. **Delete the false con from Option B** — "a second GPU consumer outside the single-worker
   policy". `pipeline._run_script` already serializes external CLIs inside the one worker.
   Replace it with B's true cost: two upgrade paths, and the voice chain still needing
   ComfyUI regardless.
6. **Fix PM2's detection**: assert on the patched function (source hash or signature) at
   import and in `check_integration.py`. `/object_info` node presence stays as a second,
   weaker check, not the primary one.
7. **Add two pre-mortem entries**: (a) the monkeypatch silently stops applying — distinct
   from "the node breaks", detection per item 6; (b) a community node pack breaks ComfyUI
   startup and takes video rendering with it — detection per item 4.
8. **Derive `songs.key` (Camelot) from `keyscale` at generation time**, in `analyse.py` beside
   the existing `_CAMELOT` table (~5 lines), instead of leaving two unreconciled key columns.
   Then SETS amendment correction 1 becomes true as written; until then it is false for key.
9. **Extract the `audio_original` recording** from `app.py:2197-2201` into a shared helper
   called by both `use_audio_edit` and the new use-take route. Without it,
   `test_using_a_take_records_the_original_once_and_revert_restores_it` fails as designed and
   `revert_audio` raises on every generate → use-take flow.
10. **Add `takes.chosen`**, matching `anchors.chosen` (`db.py:29`) and `refs.approved`
    (`db.py:48`). Implying pickedness by `songs.mp3_path` string equality breaks the moment an
    audio edit moves `mp3_path`.
11. **Replace `take_voices`' NULL/NULL sentinel with `0`/`duration`.** `takes.duration` is on
    the same row, so the value is always available, and
    `test_voice_regions_do_not_overlap_and_cover_only_the_track` becomes one interval predicate
    with no special case.
12. **Correct the two guards the plan cites that do not guard.** `RENDERED_ROLES` does not
    force `build_track.py` to exist and `ace_step_v1` already carries a `cli`
    (`models.py:219`, `:458-462`, `renderable()` at `:324-331`). Replace phase 1's "forced,
    not chosen" framing with the Architect's narrower true statement, and add the one line to
    `check_integration.py` that actually asserts `build_track.py` is present — which is also
    what protects the `deploy.sh` rsync catch.
13. **Add the mask-actually-applied test to phase 0**, not phase 2: the masked region changed,
    the unmasked region did not, to a stated dB tolerance (decode/encode drift makes
    bit-exactness impossible). This is the only proposed test that fails when the mask is
    silently discarded, which is the plan's own named dangerous shape.
14. **Specify the phase-3 gate so someone else can run it**: named tracks (three, spanning the
    catalogue), a named reference clip, a randomised presentation order produced by a script,
    and three scored axes — intelligibility, timbre match, artefacts — rather than one verdict.
    Same treatment for PM1's "blind" A/B: say who blinds it and how.
15. **Give phase 2's acceptance criterion a measurement**: a null-test or correlation of the
    unmasked region against the source, with a tolerance. Add the Architect's qualification
    that phase-2 independence from phase 1's verdict holds for **non-vocal** masks only, since
    a reference forces `is_covers=True` with `pass_audio_codes=False` (settled per the brief).
16. **Rewrite open question 2 to cover what is actually in the column**: both semantic section
    tags (`[verse]` ×26 across 13 of 31 rows) and production directives (`[pause]` ×96,
    `[build]` ×71, `[drop]` ×55) — 202 distinct tags in total — and note that
    `build_storyboard.parse_sections` (`build_storyboard.py:49-63`) reads every one of them as
    a scene boundary, so any strip step must happen **on the way to the generator only** and
    must never touch the column.
17. **Say that `studio/analyse.py` already exists** and that what is missing is the `analyse`
    job kind and route, then name who builds it. Phase 4 currently depends on an unowned
    prerequisite. Change "already specifies" to "is already written; the job kind is not".
18. **Replace §7's "minimum path to 'sounds amazing'"** with §8's trigger wording, which is the
    same claim already made falsifiable.
19. **Drop the `test_load.py` cross-kind overlap test only after reading `jobs.demo()` in
    full** — `jobs.py:286` proves serialization of two jobs, but I did not confirm they are of
    different kinds.
20. **State the box** in §1's verified-facts table. Every `comfy_extras/*` and `comfy/*` path
    is on `cerberus-ai:~/ComfyUI`, not in this checkout, and a bare path reads as a repo path.

---

## 10 · WHAT I DID NOT CHECK

**I ran no model, generated no audio, and executed no test.** No pytest, no `jobs.demo()`,
`models.demo()`, `analyse.demo()`, or `check_integration.py`. My claim that
`test_audio_edit_use_and_revert` passes only because it posts an edit first is read from
source, not observed.

**I read almost no ComfyUI source myself.** My only first-hand ComfyUI read is
`comfy_extras/nodes_ace.py:46` and `:58-59` (the `keyscale` enum and the tokenize call), via
`ssh cerberus-ai`. Everything else about ComfyUI I took from the brief as settled or from the
Architect on trust. Specifically **not** verified by me: `ace_step15.py:1104-1110` and
`1114-1155` and `1119-1120`; `prepare_condition` at `1077-1112`; `model_base.py:2289-2330`,
`:427-428` and the 282 MB arithmetic; `samplers.py:634-642`; `sampler_helpers.py:18-19`;
`utils.py:1312-1331`; `nodes.py:1559-1562`; `sd.py:661`; `supported_models.py:2179` and
`:2183-2201`; `text_encoders/ace15.py:216-217`; the absence of `structure_pattern` in 1.5;
the 25 latent frames/second arithmetic; and the claim that the 1.5 weights are absent.

**I did not read `build_refs.py`, `build_song.py`, `make_anchor.py`, `mixer.py`, `vision.py`,
`grok.py`, `tiers.py`, `guardrail.py` or `publish.py`.** The plan's "≈200 lines,
`build_refs.py`'s shape" estimate is as unaudited by me as it was by the Architect. My only
read of `build_storyboard.py` is `parse_sections` at `:49-63`.

**I read `test_load.py` and `conftest.py` only by grepping symbol names**, not in full, which
is why item 19 above is a hedge rather than an endorsement. I read `jobs.py` by grep, not in
context — including line 286, which several of my conclusions lean on.

**Nothing about Seed-VC, the separator packs, Demucs quality, fish.audio, or upstream
ACE-Step.** Not installed, not called, not cloned, no web lookup, no docs read. Every claim
about them in either document remains exactly as unverified after my pass as before it.

**Database caveat.** I queried both `cerberus:~/meowp-studio/data/studio.db` (31 songs) and
`~/meowp-studio/app/data/studio.db` (0 songs, no `style_text`) directly via python's sqlite3.
The tag counts, the 13/31 `[verse|chorus]` figure and the 0/31 `[Section` figure are real
query output. I did **not** determine which database the running service opens, so all of it
describes the file at that path, not necessarily production.

**I did not verify the effort or cost estimates** in §7, or that the Architect's line
references to `studio/*` files I did not open (`test_app.py:1094`, `pipeline.py:86-110` beyond
the function body I read) are exactly as cited.
