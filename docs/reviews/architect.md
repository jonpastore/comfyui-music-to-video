# ARCHITECT PASS — `docs/AUDIO_BUILDOUT_PLAN.md`

Read-only review. ComfyUI is **not** in this checkout; it lives on `cerberus-ai:~/ComfyUI`
(0.31.0). Every `comfy/*`, `comfy_extras/*` and `nodes.py` line reference below was read
over `ssh cerberus-ai`. Every `studio/*`, `docs/*`, `guardrail.py` reference is local.

The plan's verified-facts table cites `comfy_extras/nodes_ace.py` etc. as bare paths.
Anyone checking from this repo finds nothing there — the doc should say which box.

---

## 0 · Confirmations, and the extension to them

Your four verified facts hold. I am not re-litigating them; two extensions matter,
because they make phase 2 worse than "needs a monkeypatch of `forward`".

**Extension 1 — even with `forward` patched, the `src_latents` you pass never reaches
the model.** `ace_step15.py:1104-1110`:

```python
lm_hints = lm_hints[:, :src_latents.shape[1], :]
if is_covers is None or is_covers is True:
    src_latents = lm_hints
elif is_covers is False:
    src_latents = refer_audio_acoustic_hidden_states_packed
context_latents = torch.cat([src_latents, chunk_masks.to(src_latents.dtype)], dim=-1)
```

There is **no branch in which the incoming `src_latents` survives**. It is consumed for
its length only (`.shape[1]`, twice). So the plan's phase-2 sentence — "`VAEEncodeAudio`
over the existing track supplies `src_latents`, so **this works on an uploaded Suno mp3
too**" — describes something this code does not do. The only route for an existing track
into `context_latents` is as `refer_audio` with `is_covers=False`. `prepare_condition`
must be patched too, or the repaint has a mask and no source.

**Extension 2 — ComfyUI makes `is_covers=False` with a reference unreachable.**
`model_base.py:2312-2315` forces `is_covers=True` the moment a reference is supplied.
Repaint needs reference-present **and** `is_covers=False`. So `extra_conds` is the third
function that has to be forked.

**Real cost of phase 2 as specified:** `ACEStep15.extra_conds` (`model_base.py:2293-2330`)
+ `AceStepConditionGenerationModel.forward` (`ace_step15.py:1114-1155`) +
`prepare_condition` (`ace_step15.py:1077-1112`) ≈ **120 lines of upstream numerics
forked**, not "~100 lines exposing it". §7's "a custom node costs nothing extra against
it" is false for this node.

**Pre-mortem 2's detection does not cover the failure it names.** The plan requires the
node to "surface as **missing** through the same `/object_info` probe". A monkeypatch
never goes missing — the node still registers while the patched method's body moves
underneath it. The shape the plan itself calls dangerous ("a silent fall-through to
unmasked regeneration… looks like 'the repaint did nothing' and costs a day") *is* the
monkeypatch failure mode, and `/object_info` is blind to it. The guard must be a runtime
assertion on the patched function (signature or source hash), not node presence.

**The cheap path the plan never considers.** ComfyUI already does masked latent denoising
generically, with zero ACE internals:

- `samplers.py:634-642` — `x = x * denoise_mask + scale_latent_inpaint(...) * latent_mask`,
  then `out = out * denoise_mask + self.latent_image * latent_mask`. Outside the mask the
  latent is pinned to the encoded original. That is "regenerate this region, keep the rest".
- `sampler_helpers.py:18-19` → `utils.reshape_mask` (`utils.py:1312-1331`) already has a
  `dims == 1` branch (`mode="linear"`) — exactly what a `[B, 64, T]` audio latent needs.
- One blocker: `SetLatentNoiseMask` (`nodes.py:1559-1562`) hard-reshapes to 4-D
  `(-1, 1, H, W)`, which `interpolate(mode="linear")` rejects. **A ~10-line node writing
  `latent["noise_mask"]` as `[1, 1, T]` fixes it.**
- Encoding the source works: `sd.py:661` sets `audio_sample_rate = 48000` for this VAE,
  matching `EmptyAceStep1.5LatentAudio`'s `round(seconds * 48000 / 1920)` = 25 frames/s
  (the plan's "25 latent frames per second" is **correct**).

The difference is real — `chunk_masks` tells the *model* which region is being repainted
so it can bridge musically; `noise_mask` only blends latents and will seam. But you
cannot know whether the seam is audible until you hear it, and the cheap version is an
afternoon. **NOT MEASURED — no ACE 1.5 weights on the box. This is a source-reading
claim about the code path, not a demonstration that it sounds acceptable.**

---

## 1 · Steelman antithesis to Option A

Option A = everything as ComfyUI custom/community nodes; ACE-Step's own repo relegated
to a hand-run LoRA escape hatch. Argued as well as it can be argued:

**1. The comparison arithmetic is wrong, and it is the whole argument.** The plan rejects
B because "B breaks both [load-bearing decisions] to buy a capability A gets for ~100
lines." The number is a three-function fork of upstream numerics with a silent failure
mode. Upstream's repo exposes edit/repaint as a supported entry point. B buys the phase-2
headline as an API contract instead of a patch against internals the plan itself says
"have already moved twice this month". Change the input to the trade and the trade flips.

**2. The torch-split principle protects the studio venv — and A is the option that
violates it.** `studio/requirements.txt:1-8` gives the reason in its own words: the studio
venv stays torch-less so "nothing here should be able to disturb a working renderer." The
protected asset is **the renderer**. Option A pip-installs `ComfyUI_Seed-VC`, a Demucs
separator, and a hand-written numerics monkeypatch **into ComfyUI's own venv** — three
third-party dependency trees plus a fork, in the exact environment the principle exists to
keep pristine. Option B's torch lands in a directory nothing else imports. Read literally,
B is the conservative option and A is the invasive one. The plan reads the principle as
"only one torch on the box", which is not what the file says.

**3. The single-worker policy is a studio invariant, not GPU arbitration.** `jobs.py:1-9`
is one worker thread; anything a handler shells out to is serialized by construction.
`pipeline._run_script` (`studio/pipeline.py:41`) **already runs external CLIs from inside a
handler** — that is the existing shape of every build script in this repo. A CLI in a third
venv invoked from a job handler is exactly as serialized as a ComfyUI submit. B adds a
second GPU consumer only if run by hand — which the plan already sanctions for LoRA
training, conceding the point it used to reject B.

**4. B collapses the phase-3 stack.** Separation and SVC become pip installs in one
isolated venv: no `custom_nodes/` entries, no `/object_info` probing for third-party
nodes, no third-party import able to break a render at ComfyUI startup.

**5. The failure modes differ in kind, and A's cons list omits the larger one.** A's
failure is a monkeypatch that stops matching upstream and silently emits unmasked audio
into a workflow that reports success. B's is a subprocess exiting non-zero. One costs a
day of misdiagnosis; the other costs a log line.

**6. Version drift.** Under A, phase 4's LoRA training lives in a venv whose ACE version
can silently diverge from the inference one, and nothing detects it. Under B they are one
install, and training/inference cannot disagree.

**7. Disk cost is trivial** — 1.4 TB free on cerberus, torch ≈ 6 GB, one-time.

---

## 2 · Tradeoffs the plan states as settled but are not

### (i) "Phase 2 pays for itself even if phase 1's vocals are judged not good enough."

Stated twice — in §3 and again as pre-mortem 1's mitigation, so it carries the plan's
answer to its own most-likely failure.

Repaint **re-synthesises** the masked region in ACE 1.5's own voice. If the phase-1
verdict is "the vocals are not there yet", repainting a vocal region of a Suno track
splices the rejected voice next to the accepted one *inside one song* — worse than either
alone. And `model_base.py:2314-2315` sharpens it: supplying a reference forces
`is_covers=True` **and** `pass_audio_codes = False`, so repaint-on-an-upload runs with the
audio-codes LLM **disabled** — the configuration whose own tooltip (`nodes_ace.py`,
`generate_audio_codes`) says it exists to "increase the quality of the generated audio".

Phase 2's independence holds for **non-vocal** masks and collapses for anything sung. The
chosen acceptance test — "the giggling in the first four seconds" — is precisely the case
that hides this. Add a sung-region criterion, or state the limit honestly.

### (ii) "Separate → SVC → remix … accompaniment untouched — no seam at all."

The accompaniment is not untouched: it is Demucs' *residual* after the vocal was pulled
out, and it carries the hole the vocal left. Bleed, phase smear and vocal-band artefacts
remain. Pre-mortem 3 knows this ("Demucs leaves artefacts in both halves"); the §1
comparison table contradicts it. The true and still-valuable claim is *no seam at the
section boundaries*.

### (iii) Principle 1's "nothing new has to be authored to make the first track."

True for `style_text` — 31/31 deployed rows populated. False for lyrics; see §4.

---

## 3 · Synthesis

Option B still loses for **generation**, for the reason the plan gets right: plain
text-to-music needs no fork at all. `TextEncodeAceStepAudio1.5` (`comfy_extras/nodes_ace.py`)
already exposes tags, lyrics, seed, bpm, duration, timesignature, language (51), keyscale
(34), `generate_audio_codes`, cfg/temperature/top_p/top_k/min_p as typed inputs, and the
whole submit/collect/progress/cancel/`free_vram` apparatus exists. Paying for a second
stack to get what the first gives free is wrong.

But "A for everything, B for training only" is the wrong boundary. The defensible one:

> **A for what ComfyUI already exposes. B for anything that must reach inside the model.**

That puts phase 1 and the `noise_mask` cut of phase 2 in A with zero forks; puts
`chunk_masks` repaint, SVC and LoRA training in B; and keeps ComfyUI's venv free of three
community packs plus a numerics patch. It is a *smaller* B than the plan's, because the
studio never drives B for the common case — and it satisfies the plan's own stated
principle (`requirements.txt:1-8`) better than the plan's own answer does.

Five changes before approval:

1. Rewrite finding 3 and re-cost phase 2 as a three-function fork, not a node.
2. Insert **phase 2a: `noise_mask`** (~10 lines, no internals). Ship it first. Phase 0's
   `chunk_masks` spike then measures a *delta* against something that already works —
   a far better spike than a yes/no on a patch.
3. Fix pre-mortem 2's detection: assert on the patched function, not `/object_info`.
4. Qualify phase 2's independence (non-vocal masks only; vocal repaint runs with
   audio-codes off).
5. Correct principle 1's claim about `songs.lyrics`, and rewrite open question 2 around
   what is actually in that column.

---

## 4 · Principle violations

### P2 — "a generated track is a CANDIDATE, not a song." Violated, twice.

- `takes` has no `chosen`/`approved` column. `anchors.chosen` (`studio/db.py:29`) and
  `refs.approved` (`studio/db.py:48`) both have one. Pickedness is implied by
  `songs.mp3_path` string equality, which breaks the instant an audio edit moves
  `mp3_path` — then no take is picked and nothing records which one was.
- The plan says "Use this take moves `songs.mp3_path` through the same `audio_original`
  asset the audio-edit path already records, so revert keeps working and is not recorded
  twice." **It does not.** `audio_original` is recorded in the *edit-submit* route
  (`studio/app.py:2199-2201`); `use_audio_edit` (`studio/app.py:2208-2216`) writes
  `mp3_path` with no recording at all, relying on having been preceded by an edit. A
  generate → use-take flow never passes that site, so `revert_audio`
  (`studio/app.py:2219-2226`) raises "no original recorded for this song". The mechanism
  must be **extracted to a shared helper**, not reused as-is. The test the plan wants
  (`test_using_a_take_records_the_original_once_and_revert_restores_it`) is the right
  test; the claim it will pass as designed is wrong.

### P1 — "generate what the studio already knows." Mostly right; one factual error that changes phase 1.

Deployed db (`cerberus:~/meowp-studio/data/studio.db`): **31 songs, 31 with `style_text`,
31 with lyrics.** The principle holds. But the plan says `songs.lyrics` is "the lyric sheet
with `[Section N]` tags that `lyrics.to_sections()` already emits" — **0 of 31 rows
contain `[Section`**. What they contain is Suno arrangement sheets:

```
[32-Bar DJ Intro - NO VOCALS]
[Dry kick]
[Closed hats]
[Metallic rim hits]
[Filtered warehouse ...]
```

ACE **1.0** had `structure_pattern = re.compile(r"\[.*?\]")`. **1.5 has no such pattern** —
`comfy/text_encoders/ace15.py:216-217` drops lyrics verbatim into `"# Lyric\n{}"` inside a
Qwen3 chat template. Phase 1 as written pipes twenty lines of percussion cues into a field
the model reads as words to sing.

Open question 2 asks about `[verse]`/`[chorus]`, which is **not what is in the column**.
Rewrite it: *what does 1.5 do with the arrangement directives present in all 31 rows, and
does phase 1 need a strip step* — noting `build_storyboard.parse_sections` reads those
tags, so stripping must happen only on the way to the generator.

(`lyrics.to_sections`, `studio/lyrics.py:174-179`, emits `[Intro]`/`[Section N]` from
silence gaps — also not semantic labels, which weakens competitive-advantage claim §6.4's
"scene boundaries can be the real `[chorus]`".)

### P3 — "one GPU, one worker." Honoured; one gap and one wasted test.

- Phase 3's three-submit chain is one *job*, but the plan says `free_vram()` "before every
  audio job". It needs to be **between** the submits, and `free_vram` is best-effort by
  design (`studio/pipeline.py:86-110`) — a failed `/free` must not silently proceed into
  an OOM.
- Proposed `test_load.py` "a generate job, a voice job and a clips job never overlap" tests
  `jobs.py`'s single worker, already proven by `jobs.demo()`'s ordering assertion
  (`studio/jobs.py:286`). Drop it; keep the end-to-end chain test, which is the one that
  exercises take/song/asset bookkeeping.

### P4 — "the deterministic path wins whenever it can do the job." Honoured.

End-touching ranges → ffmpeg; phase 5 on ffmpeg rather than `AudioEqualizer3Band`, with
the right reason (studio venv, off the GPU queue, matches how `mixer.py` already works).
No violation.

### P5 — "a feature level is not a permission level." Honoured, well.

`ui.level` as a `settings` row with no column on any content table is correct, and the
stated reason (per-song copies go stale and invite gating) matches how per-role model
choices already work. Content tiers stay ratings: `studio/tiers.py:26-40` (MPA wording),
`guardrail.py:178` `check_text`, `studio/tiers.py:185` `check_override`. Nothing to fix.

### Repo invariant — "candidates never overwrite the picked artefact." Partially violated.

Covered under P2 above. Additionally: phase 2's repaint of an **upload** has no
candidate/pick shape at all — it produces a take whose source is a `songs.mp3_path` that
moves.

### `models.py` — the plan overstates the forcing.

It claims the `ace_step_v1` entry "cannot stay as it is" because `RENDERED_ROLES` demands
a `cli`. It already has one — `"cli": "ace_step"` (`studio/models.py:219`) — so the
assertion the plan leans on already passes. The true, narrower statement: the catalogue
advertises an audio model whose CLI does not exist ("nodes are present, but no workflow is
written yet", `studio/models.py:226`), and phase 1 is what makes that honest.

### Schema, beyond P2

- `takes.parent_id` is ambiguous exactly where its comment claims it is not. `NULL` is
  documented as "a fresh generation" — but a repaint of an **upload** (phase 2's headline)
  is also `parent_id NULL` with `origin='repaint'`. Add `source_path`, or delete the
  comment and let `origin` carry it.
- `library` with no FK to `songs` (open q5) is right, for a better reason than given:
  `songs.mp3_path` **moves** (edits, takes), so an FK would make the training set follow
  the song's edit history — wrong for reproducibility. Say that.
- `take_voices` NULL/NULL = "whole track" makes
  `test_voice_regions_do_not_overlap_and_cover_only_the_track` incoherent — a NULL region
  overlaps every bounded one. Either forbid mixing the two forms per take, or store
  `0`/`duration`.
- Take retention (open q4): correctly deferred. `anchors` already has a delete-unpicked
  action to copy when the first song reaches thirty takes.

---

## 5 · VRAM — the plan is afraid of the wrong number

`memory_usage_factor = 4.7` (`comfy/supported_models.py:2179`) enters at
`comfy/model_base.py:427-428`:

```python
area = sum(input_shape[0] * math.prod(input_shape[2:]))
return area * dtype_size * 0.01 * self.memory_usage_factor * (1024*1024)
```

A 120 s track's latent is `[1, 64, 3000]` → `area = 3000` → `3000 × 2 × 0.01 × 4.7`
≈ **282 MB** of activation budget. For scale, 4.7 is mid-table in that file — 6.5, 7, 8.7,
10.0 and 11.6 all appear (`:1940, :627, :2032, :2278, :1873`) — and it multiplies an audio
latent four orders of magnitude smaller in area than a video one.

Decision driver 2 and pre-mortem 4 both elevate 4.7 into a headline risk. It is not one.

The real cost is **weights**: the all-in-one checkpoint (DiT + Qwen3 2B/4B TE + VAE —
`comfy/supported_models.py:2183-2201`), a static number readable off the file the moment
it is downloaded. The "22265 MiB currently held" figure is a transient, not a floor; the
card was at 13.3–13.5 GB at probe time, and `free_vram()` clears it.

**Verdict: phase 3 is not shown to be unbuildable on this card, and the plan's own
arithmetic does not show it either.** Three separate submits + `free_vram()` between them
is a sound mitigation for co-residency; the binding constraint is the largest single stage
(ACE 1.5 weights + Qwen3 TE), which is one download away from being known rather than
argued. Restate driver 2 as "weights, measured after download", delete the 4.7 alarm, keep
the phase-0 gate — it is the right gate, aimed at the wrong term.

---

## 6 · Per-phase verdict

| Phase | Verdict | Why |
|---|---|---|
| **0 — spike** | **Sound, needs one addition** | Right instinct, right gate ("numbers in the log"). Add: (a) what 1.5 does with the arrangement directives actually in all 31 lyric rows, not `[verse]`/`[chorus]`; (b) measure the free `noise_mask` repaint *before* patching `chunk_masks`, so the fork is measured as a delta. Item 4 ("patch `chunk_masks` locally") now requires patching `forward` **and** `prepare_condition` **and** `extra_conds` — scope it honestly. |
| **1 — a track from the existing row** | **Sound, three revisions** | No forks needed; native nodes cover it. Fix: the `audio_original` recording gap (`app.py:2199` vs `:2208-2216`) — extract to a shared helper; add a `chosen` flag to `takes`; add the lyric-strip step. Correct the `models.py` `cli` claim. `deploy.sh` rsync addition is correctly caught and real. |
| **2 — the intro problem** | **Needs revision — not buildable at the stated cost** | Central mechanism misread. Not *unbuildable*, but it is a ≈120-line fork of three upstream functions with a silent failure mode, not "~100 lines". Split into **2a `noise_mask`** (~10 lines, ship first) and **2b `chunk_masks` fork** (gate on 2a's seams; if built, build it under Option B rather than as a ComfyUI monkeypatch). Independence-from-phase-1 holds only for non-vocal masks. |
| **3 — voices** | **Sound in shape, revise two claims** | Not blocked by VRAM on the evidence available. Revise "no seam at all" → "no seam at the section boundaries"; call `free_vram()` **between** submits, not once per job. `refer_audio[-1]` and cover-mode findings are correct and load-bearing — keep them verbatim. The A/B-by-ear gate is right. |
| **4 — training library** | **Sound** | Reusing `SETS_MIXING_PLAN` phase 2's `analyse` job instead of building a second analyser is exactly right. Retrieval-before-LoRA ordering is right. `library.licence NOT NULL` with two honest values is right. Keeping LoRA off the critical path is right. |
| **5 — engineering** | **Sound** | ffmpeg in the studio venv, no duplication of the DJ plan's filter table, `loudnorm` on by default matching `docs/SETS_MIXING_PLAN.md:126-127`. Nothing to change. |
| **SETS amendment** | **Sound** | The generation-time vs set-level split is a genuine distinction, and "a set can commission a track" is the strongest argument in the document for why these two plans belong to each other. `songs.bpm` finally getting a writer, with the editable downbeat offset retained (`docs/SETS_MIXING_PLAN.md:84-87`), is correctly reasoned. |

**Overall:** unusually well-grounded — it argues from this repo's actual decisions rather
than around them, and its pre-mortem is honest. The one place it did not read closely
enough is the one place carrying a whole phase. Approve 0, 1, 3, 4, 5 with the listed
revisions; send phase 2 back.

---

## 7 · WHAT I DID NOT CHECK

Everything in this section is a gap, not a finding. Treat any plan claim listed here as
still unverified.

**Ran nothing. Measured nothing.** ACE-Step 1.5 weights are absent from the box
(`~/ComfyUI/models/checkpoints/` holds `ace_step_v1_3.5b.safetensors`, 7.7 GB, plus LTX
files). No generation, no repaint, no sampling was executed. Every claim above is
source-reading and arithmetic.

Specifically NOT verified:

1. **That the `noise_mask` path actually works end to end for ACE 1.5 audio latents.**
   I traced `samplers.py:634-642` → `sampler_helpers.py:18-19` → `utils.py:1312-1331`
   and the `dims == 1` branch is there, but I did not run a sampler over a
   `[1, 64, T]` latent with a mask. The `SetLatentNoiseMask` 4-D reshape incompatibility
   is read from source, not observed as an exception.
2. **Whether the `noise_mask` repaint sounds acceptable.** Entirely unheard. The claim
   that it will seam more than `chunk_masks` is theory.
3. **Peak VRAM for ACE 1.5, and for the voice chain.** The 282 MB activation figure is
   arithmetic from `model_base.py:427-428`; the *weights* figure is unknown because the
   checkpoint is not downloaded. Phase 3 buildability is "not shown to be blocked", which
   is weaker than "shown to be fine".
4. **What ACE 1.5 does with `[Dry kick]` / `[32-Bar DJ Intro - NO VOCALS]`.** I confirmed
   the template is free text (`text_encoders/ace15.py:216-217`) and that 1.5 has no
   `structure_pattern`, and I confirmed the directives are in all 31 rows. I did not
   confirm the model sings them. That is a phase-0 measurement.
5. **Whether a short timbre reference works in cover mode.** Confirmed only that it is
   silence-padded (`model_base.py:2325-2327`). Nothing about how it sounds.
6. **Upstream ACE-Step's own repo.** Not cloned, not on the box, no web lookup. The plan's
   Option B claims — "everything upstream supports on day one, including flow-edit and
   LoRA training" — are **unverified by me**. My steelman for B argues from structural
   grounds (venv boundaries, serialization, failure modes) that hold regardless, but if
   upstream does not in fact expose repaint as a supported API, argument 1 of the steelman
   weakens considerably. Check this before acting on it.
7. **`ComfyUI_Seed-VC` and the `audio-separation-nodes-comfyui` family.** Not installed,
   not inspected, not benchmarked. Zero-shot quality, the 1–30 s reference claim, f0
   conditioning, BigVGAN, the 4–10 / 30–50 step ranges — all taken from the plan on trust.
   Demucs quality on this catalogue's dense electronic production (the plan's own open
   question 3) is untouched.
8. **fish.audio.** No API call, no key, no docs read. `POST /v1/tts` being "the entire
   public surface" and the absence of an SVC endpoint are the plan's claims, unchecked.
9. **Whether patching `forward` from a `custom_nodes/` module actually works in ComfyUI
   0.31.0.** I established that it is *required*; I did not confirm the import ordering
   lets a custom node monkeypatch `comfy.ldm.ace.ace_step15` before a model is loaded.
10. **`build_track.py` sizing, and the workflow JSON shape.** I read `build_refs.py`'s
    contract only via `pipeline.py` call sites and greps, not the file end to end. The
    "≈200 lines, `build_refs.py`'s shape" estimate is unaudited.
11. **`studio/test_load.py`.** Not opened. I confirmed the three cited sibling tests exist
    in `studio/test_app.py` (`:295`, `:372`, `:1094`) but did not read the load suite.
12. **librosa / the `analyse` job.** Phase 4 leans on `SETS_MIXING_PLAN.md` phase 2, which
    is itself unbuilt. I checked the plan text, not any implementation, because there is
    none.
13. **`mixer.py` internals.** Function list only (`grep -n "def "`). The remix step's
    ffmpeg arithmetic is unexamined.
14. **The local vs deployed db divergence.** `cerberus:~/meowp-studio/app/data/studio.db`
    has 0 songs and a pre-migration `songs` table (no `style_text`); the live one is
    `cerberus:~/meowp-studio/data/studio.db` with 31. I did not chase why two exist or
    which one the service opens. Probably harmless, possibly not.
