# Bringing song generation in-house — plan

> **PENDING APPROVAL.** Nothing here is built. This document specifies the four
> documents to be written once it is approved, and the phases they cover.

Songs arrive as mp3 uploads made in Suno. Whisper transcribes them, and
everything downstream — storyboard, refs, clips, render, sets, publish — is
local. **The audio generation step is the last external dependency, and closing
it is the point of this work.**

Everything below was checked against the box (cerberus, ComfyUI 0.31.0) rather
than recalled. Where something is unverified it says so.

---

## 1 · RALPLAN-DR

### Principles

1. **Generate what the studio already knows.** `songs.style_text` is the style
   prompt, `songs.lyrics` is the lyric sheet with `[Section N]` tags that
   `lyrics.to_sections()` already emits. The generator's two main inputs are
   columns that exist. Nothing new has to be authored to make the first track.
2. **A generated track is a CANDIDATE, not a song.** Anchors and refs both keep
   every candidate until one is picked. Audio is cheaper to generate than either,
   so the same shape applies with more force.
3. **One GPU, one worker.** `jobs.py` says "there is exactly one RTX 5090 behind
   this — do not add a second worker". A 30-second generation makes a second lane
   look free. It is not: the card holds 22.3 GB of ComfyUI between renders.
4. **The deterministic path wins whenever it can do the job.** ffmpeg trims ends
   exactly, for free, reversibly. The model is for what ffmpeg structurally
   cannot do — cutting from the middle, putting something else there, and
   separating a mix into stems.
5. **A feature level is not a permission level.** `tiers.py` g/pg13/r/xxx are
   CONTENT ratings. easy/enthusiast/advanced are DISCLOSURE levels. Neither ever
   gates the other, and they must not share a table, a column or a word.

### Decision drivers

1. **Vocal quality is the whole risk.** Style alignment is close (39.1 vs 46.8);
   lyric alignment is not (26.3 vs 34.2), and intelligibility is the axis a
   listener judges first. Every phase is ordered so the work survives a verdict
   of "the vocals are not there yet".
2. **VRAM is the hard ceiling.** The card is a **24463 MiB RTX 5090 Laptop**,
   currently holding **22265 MiB** of ComfyUI. `ACEStep15.memory_usage_factor` is
   4.7 and its text encoder is a Qwen3 2B/4B. LTX already peaks at 95% during its
   own text encoding with the standing rule that nothing else may be resident.
   The voice chain adds a separator and an SVC model to the same card.
3. **The existing operational split must not be broken.** ComfyUI's venv has
   torch; the studio venv deliberately does not (`requirements.txt` and
   `deploy.sh` both say so, in those words). Anything that puts a second torch on
   the box is paying a very large bill for whatever it buys. A ComfyUI *custom
   node* is free of this — it lands in the venv that already has torch.

### What is actually installed — verified on the box, not assumed

| Fact | Evidence |
|---|---|
| ComfyUI has **native ACE-Step 1.5** support | `comfy_extras/nodes_ace.py`, `comfy/ldm/ace/ace_step15.py`, `comfy/text_encoders/ace15.py`, `supported_models.ACEStep15` |
| The 1.5 **weights are not on the box** | `CheckpointLoaderSimple` enumerates `ace_step_v1_3.5b.safetensors` only — that is 1.0. The continuation's "ACE-Step downloaded" means v1. |
| The 1.5 checkpoint is **all-in-one** | `vae_key_prefix = ["vae."]`, `text_encoder_key_prefix = ["text_encoders."]`; the TE is detected as `qwen3_2b` or `qwen3_4b` |
| The whole enthusiast control surface is **already typed inputs** | `TextEncodeAceStepAudio1.5`: tags, lyrics, seed, **bpm**, **duration**, **timesignature**, **language** (51), **keyscale** (34), generate_audio_codes, cfg_scale, temperature, top_p, top_k, min_p |
| Audio utilities present | `VAEEncodeAudio`/`VAEDecodeAudio(Tiled)`, `AudioEqualizer3Band`, `AudioAdjustVolume`, `TrimAudioDuration`, `AudioConcat`, `AudioMerge`, `Split`/`JoinAudioChannels`, `EmptyAudio`, `SaveAudioMP3`/`Advanced` |
| **No Seed-VC, no RVC, no stem separation** | nothing matching `seedvc`/`rvc`/`demucs`/`separat`/`stem` in `/object_info`. `SeedVR2*` is **video restoration**, unrelated — do not mistake it for Seed-VC. `ElevenLabsAudioIsolation` is a paid partner API node, not local. |
| Disk | 1.4 TB free |

### The three findings that shape everything

Read `comfy/model_base.py:2289` (`ACEStep15.extra_conds`) before designing any
voice feature. Twenty lines, and they decide three questions:

- **Only ONE timbre reference is ever used.** `ReferenceTimbreAudio` appends to
  `reference_audio_timbre_latents`, but `extra_conds` takes `refer_audio[-1]`.
  Chaining reference nodes does nothing; the last one silently wins. Anyone
  designing duets from that node without reading this loses a day.
- **A reference puts the model in COVER mode.** Supplying one sets
  `is_covers=True` and disables the audio-codes LLM (exactly what the
  `generate_audio_codes` tooltip says). The reference is padded with silence to
  the full track length, so whether a *short* reference works is a measurement,
  not a given.
- **The model supports masked repaint and multi-reference. ComfyUI exposes
  neither.** In `ace_step15.py`'s `forward`, `chunk_masks = torch.ones_like(x)`,
  `src_latents = x` and `refer_audio_order_mask = zeros` are hardcoded — and all
  three are `None`-defaulted locals the surrounding code is written to accept.
  `prepare_condition` concatenates `chunk_masks` onto `src_latents`: **that is
  the timeline mask.** Exposing it is what makes "remove the giggling from the
  intro, keep everything else" a thing you point at rather than a thing you beg
  a prompt for.

  **VERIFIED ON THE BOX, and it is worse than a custom node.** `forward` at
  `ace_step15.py:1114` does take `**kwargs`, but lines 1119–1120 assign
  `chunk_masks = None` and `src_latents = None` *unconditionally*, before the
  `if ... is None` defaults at 1131–1135. So a cond emitted under either name
  reaches `forward` and is **silently discarded** — which is precisely the
  dangerous shape pre-mortem 2 names, arrived at by the obvious implementation.
  The work is therefore a two-line monkeypatch of `forward`

      chunk_masks = kwargs.get("chunk_masks")
      src_latents = kwargs.get("src_latents")

  plus an `ACEStep15.extra_conds` extension to emit them (the shape `refer_audio`
  already uses at `model_base.py:2329`), plus the node. Still small — but it
  patches ComfyUI *internals* rather than adding a self-contained node, so
  pre-mortem 2's mitigations (refuse when absent, assert in
  `check_integration.py`) are **mandatory, not prudent**, and an upgrade that
  reorders those twenty lines breaks repaint silently rather than loudly.

### How a voice actually sings — the corrected chain

**ACE-Step supplies the melody, phrasing and timing. Seed-VC replaces the
timbre.** Speech-to-singing where a model invents the melody is research-only;
nothing here plans on it.

Seed-VC does **zero-shot** SVC from **1–30 s of reference speech** — no training,
and **the reference does not have to sing**. It carries f0-conditioning,
semitone shift, and BigVGAN for high-pitched vocals; 30–50 diffusion steps for
quality, 4–10 for speed. `ComfyUI_Seed-VC` exists as a node.

That closes the loop the user actually asked for: **a fish.audio cloned or
spoken voice becomes a Seed-VC reference directly.** fish.audio is still not a
singer, and nothing here pretends otherwise — but it is now a *voice supply* for
something that is.

There are therefore two voice paths, and they are for different jobs:

| | **Cover mode** (native, no new deps) | **Separate → SVC → remix** |
|---|---|---|
| Mechanism | `ReferenceTimbreAudio`, `is_covers=True` | Demucs stems → Seed-VC on the vocal → remix over the original accompaniment |
| Voices per track | exactly one | **as many as you like, per section** |
| Reference needed | probably a sung clip — unverified | 1–30 s of **speech** |
| Accompaniment | re-rendered by the model | **untouched — no seam at all** |
| New dependencies | none | `ComfyUI_Seed-VC` + a separator, both into ComfyUI's venv |

**Separate → SVC is the primary path**, and it is what makes duets, bands,
quartets and backing singers real: you separate once, convert vocal regions with
different voices, and lay them back over the *same* accompaniment. Section-wise
regeneration and stitching — my earlier proposal — is strictly worse, because it
re-renders the backing track at every seam. Cover mode stays as the cheap
single-voice option and as the fallback if the SVC chain degrades quality (see
pre-mortem 3).

Separation is a genuinely new dependency and is justified plainly: **no ffmpeg
filter performs source separation.** ffmpeg has 562 filters on this box and not
one of them can do it. It is also the enabler for the DJ plan's stems and for
surgical vocal-only edits, so it earns its place twice.

### Options for the core architecture

**Option A — ACE-Step 1.5 inside ComfyUI, plus custom/community nodes.**
`build_track.py` at the repo root writes API-format workflow JSON into an
`--outdir` and never renders (the shape every script here already has);
`pipeline.gen_track()` submits it; a `generate` job kind runs it. The repaint
node, Seed-VC and the separator are all ComfyUI nodes in the same graph.

- *Pros:* no new architecture. Reuses submit/collect/progress/cancel, the single
  worker, `free_vram()`, and the `models.py` catalogue — which already has an
  `audio` role waiting. One box, one queue, one VRAM policy. Every new model
  lands in the venv that already has torch.
- *Cons:* the repaint node depends on ComfyUI internals (`chunk_masks`,
  `src_latents`) that can move on an upgrade, and `ReferenceTimbreAudio` is
  marked `is_experimental=True`. Three community/custom nodes is three things
  that can break independently.

**Option B — ACE-Step's own repo in a third venv, driven as a CLI.**

- *Pros:* everything upstream supports on day one, including flow-edit and LoRA
  training, for which ComfyUI has no node at all. No dependence on comfy
  internals.
- *Cons:* a **third torch install** beside ComfyUI's, on the box where the studio
  venv's torch-lessness is a stated design decision. A second GPU consumer
  outside the single-worker policy that `jobs.py` calls "the whole concurrency
  policy". Two upgrade paths, two VRAM disciplines — and the voice chain would
  still need ComfyUI, so it buys a second stack without removing the first.

**Take A, with B as a training-only escape hatch.** The single-worker policy and
the torch split are the two load-bearing operational decisions in this repo, and
B breaks both to buy a capability A gets for ~100 lines. LoRA *training* is the
one thing A genuinely cannot do; it is a rare, offline, batch operation that can
live in its own isolated venv and be run by hand. It does not need to be a job
kind, and making it one is how the third torch gets in through the back door.

**Invalidation of the third option** (an external music API — Suno's, Udio,
ElevenLabs Music): fails the local-first constraint outright, reinstates exactly
the dependency this work exists to remove, and none of them expose latent
timeline masking or per-section voice replacement either — so it does not even
buy the headline features.

---

## 2 · Pre-mortem

**1. The vocals are not good enough, and the project quietly goes back to Suno.**
The most likely failure by a distance. Lyric alignment is the weak axis and it is
the one that matters here. *Detection:* phase 1's gate is not "it generated" — it
is a blind A/B against an existing Suno track on the same lyrics, judged by the
user. *Mitigation:* phase 2 works on uploaded mp3s, so it delivers the headline
feature regardless of the verdict; and it is what turns a mostly-good take into a
usable one, which is the difference between a 1-in-20 hit rate and a workflow.

**2. The repaint node breaks on a ComfyUI upgrade and takes generation with it.**
`chunk_masks`/`src_latents` are internal locals; `ReferenceTimbreAudio` is
flagged experimental; ComfyUI on this box has already moved twice this month.
*Detection:* the node must surface as **missing** through the same
`/object_info` probe `models.py` already uses. A silent fall-through to unmasked
regeneration is the dangerous shape — it looks like "the repaint did nothing" and
costs a day. *Mitigation:* the repaint job refuses to run when its node is
absent, `check_integration.py` asserts it, and end-trims never route through the
model at all, so the common case has no dependency on it.

**3. The voice chain loses on every hop and sounds worse than ACE's own voice.**
Generate → separate → convert → remix is four lossy stages: Demucs leaves
artefacts in the vocal stem, Seed-VC at low step counts smears consonants, and
the remix has to sit the converted vocal back on an accompaniment it was not
mixed against. *Detection:* the phase-3 gate is an A/B of the same track through
cover mode, through the SVC chain, and unmodified — judged by ear, not by a
similarity metric. *Mitigation:* cover mode is kept as the single-voice path
precisely so multi-voice failing does not take single-voice with it; Seed-VC's
step count is exposed as an advanced control (4–10 fast, 30–50 quality) rather
than pinned; and BigVGAN is used for the high-pitched vocals this catalogue is
full of, which is the case the default vocoder handles worst.

**4. VRAM.** 24463 MiB total, 22265 MiB currently held, `memory_usage_factor`
4.7, a Qwen3 text encoder, and now a separator and an SVC model wanting the same
card. *Detection:* phase 0 measures peak for ACE alone; phase 3 measures it again
for the full chain. *Mitigation:* `free_vram()` before every audio job, as the
clip job already does; the chain runs as **separate submits**, not one graph, so
the three models are never co-resident; and the single worker already serialises
everything. **Do not add an audio lane** — a 30-second generation makes that look
free, and it is the one change that turns two working subsystems into an OOM
nobody can reproduce.

---

## 3 · Phasing

Ordered so each phase ships something usable alone, and so the earlier ones do
not depend on the later ones landing.

### Phase 0 — the spike (deliberately not shippable) · ~1 day

Download the ACE-Step 1.5 weights and **measure**, before anything is committed
to:

- Wall-clock and **peak VRAM** for a 120 s track against the 24463 MiB ceiling,
  with `free_vram()` called first. If a full song does not fit with nothing else
  resident, every phase below changes shape.
- Do `[verse]`/`[chorus]` tags do anything on 1.5? ACE **1.0**'s lyric tokeniser
  matches them explicitly (`structure_pattern = re.compile(r"\[.*?\]")` in
  `comfy/text_encoders/ace.py`); 1.5 feeds lyrics as free text into a Qwen3
  template (`# Lyric\n{}`), so the tags are prompt text there, not tokens. This
  decides whether `lyrics.to_sections()`'s output is a gift or a liability.
- Does `generate_audio_codes=False` plus a timbre reference sound like the
  reference — and does a **short** reference work, given it is silence-padded to
  the full length?
- Patch `chunk_masks` locally and confirm masked repaint does what the source
  says it does.

**Gate:** phase 1 does not start until peak VRAM and one generated track exist as
numbers in the log, in the style `models.py` already records LTX's ("MEASURED on
this box, not quoted").

### Phase 1 — a track, from the row that already exists · 2–3 days

- `build_track.py` at the repo root, same contract as `build_refs.py`: writes
  workflow JSON to `--outdir`, renders nothing. `pipeline.gen_track()` wraps it.
  A `generate` job kind runs it.
- `models.py` gains `ace_step_15` with `cli: "ace15"`. This is **forced**, not
  chosen: `RENDERED_ROLES` includes `audio` and `models.demo()` asserts every
  model in such a role carries a `cli` value — "a model catalogued but not wired
  is unfinished work". The existing `ace_step_v1` entry is either wired the same
  way or removed; it cannot stay as it is.
- Inputs come from the song row: `style_text` → `tags`, `lyrics` → `lyrics`, plus
  bpm / keyscale / timesignature / language / duration / seed.
- Output is a **take**, never a song. "Use this take" moves `songs.mp3_path`
  through the same `audio_original` asset the audio-edit path already records, so
  revert keeps working and is not recorded twice.
- **`deploy.sh` must gain `build_track.py` in its rsync list**, or generation
  fails on the box with a missing script — the exact failure the storyboard
  exemplar check exists to prevent.

Ships: you can make a song on your own hardware. Nothing else in the studio moves.

### Phase 2 — the intro problem · 2–4 days · highest risk, highest value

This is the acceptance test for the whole design, not a footnote.

- A custom node (`studio/comfy_nodes/ace_repaint.py`, installed into ComfyUI's
  `custom_nodes/`) exposing `chunk_masks` and `src_latents` on the 1.5 sampler
  path. ~100 lines.
- UI: select a range on the waveform, then "regenerate this region" or "take what
  is here out". `VAEEncodeAudio` over the existing track supplies `src_latents`,
  so **this works on an uploaded Suno mp3 too**, not only on locally generated
  takes.
- A range touching either end falls through to the existing deterministic ffmpeg
  trim — cheaper, exact, no re-synthesis. `models.py` already states the
  boundary: "the deterministic editor can only trim the ENDS; cutting from the
  middle needs this". Phase 2 is the other half of that sentence.
- **Acceptance:** the giggling in the first four seconds of a real track is gone,
  and everything outside the mask is unchanged.

Because it works on uploads, phase 2 pays for itself even if phase 1's vocals are
judged not good enough. Do not gate it behind that verdict.

### Phase 3 — voices · 4–6 days

- **Stem separation.** One community node (Demucs-based; the
  `audio-separation-nodes-comfyui` family gives vocals/drums/bass/other plus
  recombine, tempo-match and slice) into ComfyUI's venv. Justified because **no
  ffmpeg filter does source separation**, and it is needed three times over: SVC,
  vocal-only surgical edits, and the DJ plan's stems.
- **Seed-VC** (`ComfyUI_Seed-VC`) as the voice engine. Zero-shot, 1–30 s of
  reference **speech**, no training. Exposed controls: f0-condition, semitone
  shift, BigVGAN for high vocals, diffusion steps (4–10 fast / 30–50 quality).
- **fish.audio**: a config section holding the key (read from a file under
  `~/.config/`, never the repo — the precedent is `XAI_API_KEY` and
  `LITELLM_KEY`), voices addable by `reference_id`, generation through
  `POST /v1/tts`, which is the entire public surface. Its output is used two
  ways: **spoken word** (intros, outros, skits, ad-libs) and — the part the user
  actually wanted — **as a Seed-VC reference**, which is how a fish.audio voice
  ends up singing. There is no documented SVC endpoint on fish.audio;
  `Voice.type` contains `"svc"` and nothing invokes it, and `[singing]` is TTS
  affect, not melody-following. The doc says this where the user can read it.
- **Multiple voices** — duets, bands, quartets, backing singers — are
  **separate → SVC per region → remix over the original accompaniment**. The
  backing track is never regenerated, so there is no seam. Regions come from the
  section boundaries the lyrics already carry.
- **Cover mode** (`ReferenceTimbreAudio`) ships alongside as the cheap
  single-voice path and the fallback.
- **Training-data ethics, stated in the shipped doc and enforced by the schema:**
  the reference, SVC and LoRA paths are for the user's **own catalogue, own
  voice, and licensed or consented material**. `voices.consent` and
  `library.licence` are not optional fields.

**Gate:** an A/B by ear of the same track unmodified, through cover mode, and
through the SVC chain. If the chain loses, multi-voice waits and single-voice
ships.

### Phase 4 — the training library · 3–5 days for the useful half

Upload mp3s, classify them, let them influence style and output.

- Classification reuses the **`analyse` job that `SETS_MIXING_PLAN.md` phase 2
  already specifies** (librosa: `beat_track` for BPM, chroma against
  Krumhansl–Schmuckler for key, RMS for energy). **Do not build a second
  analyser.** Tags are proposed by a local model through the litellm gateway
  `vision.py` already talks to.
- Influence, cheapest first:
  1. **Retrieval.** Nearest neighbours in the library by BPM/key/energy/tags
     become the `tags` string and the bpm/key defaults for a new track. **No
     training at all**, works from the first upload, and ships in this phase.
  2. **LoRA.** 8–20 songs, 30–120 s each, WAV/FLAC 44.1 kHz+ (**not mp3**),
     consistent style; ~2.5 h for 23 songs on an H200, so materially longer here.
     Offline, out-of-band, Option B's escape hatch. LoRA scale blends 0–100% at
     inference.
- The library therefore records what qualifies as *training* input versus what is
  merely *reference* — an mp3 is fine for the second and not the first, and the
  UI says which it is rather than discovering it at train time.

### Phase 5 — generation-time engineering · 1–2 days

All ffmpeg, all already on the box; the filter table in `SETS_MIXING_PLAN.md`
phase 4 is the specification and this phase does not reproduce it.

- Per-take: `loudnorm` **on by default** (the DJ plan already calls level
  matching the unglamorous one that matters most), 3-band EQ, gain, fades.
- Per-stem once separation exists: the same chain applied to vocals or drums
  alone, which is the first genuinely "audio-engineering" control in the studio.
- `AudioEqualizer3Band` and `AudioAdjustVolume` exist as ComfyUI nodes too. Use
  ffmpeg: it is in the studio venv, it is how `mixer.py` already works, and
  keeping engineering off the GPU means it does not queue behind a render.

### The amendment to `docs/SETS_MIXING_PLAN.md`

Not a rewrite — an added section and two corrections. **Generation-time
engineering and set-level engineering are different things and must not grow one
shared control surface:**

| | Generation-time (per song) | Set-level (per mix) |
|---|---|---|
| Scope | one track | one item's place in one set |
| Persistence | produces a new take; the previous survives | `set_items.effects_json`, non-destructive |
| Owner | this plan | `SETS_MIXING_PLAN.md` phases 1 and 4 |

Two corrections once generation lands:

1. **`songs.bpm` and key are now known, not detected**, for anything the studio
   generated — they were *inputs*. That plan's phase 2 says "`songs.bpm` has been
   in the schema since the beginning and nothing has ever written to it";
   generation is what finally writes it, exactly, and the `analyse` job becomes
   the fallback for uploaded material rather than the only source. The editable
   downbeat offset it insists on stays — a known BPM is not a known bar one.
2. **A set can commission a track.** "This mix needs a 128 BPM bridge in 8A" is
   now actionable. That capability did not exist when that plan was written and is
   the strongest reason the two plans belong to each other. Separation also hands
   phase 4 real stems for bass-swap transitions instead of EQ approximations.

---

## 4 · Schema

`db.MIGRATIONS` entries in `db.py`'s conventions — comments explain why the model
is shaped the way it is, not what the statement does.

```python
# A TAKE is one generated candidate for a song, exactly as a `refs` row is one
# candidate frame. Generation is cheap and the good one is picked by ear, so a
# take is never written over songs.mp3_path -- picking one is a separate act, and
# the take that was not picked survives to be compared against it.
#
# tags/lyrics/bpm/keyscale are copied ONTO the take rather than read back off the
# song: the song row moves on, and a take that cannot say what it was asked for
# can be neither regenerated nor explained six months later.
CREATE TABLE takes (
  id INTEGER PRIMARY KEY, song_id INTEGER NOT NULL,
  path TEXT NOT NULL, seed INTEGER,
  tags TEXT, lyrics TEXT,
  bpm REAL, keyscale TEXT, timesig TEXT, language TEXT,
  duration REAL, params_json TEXT,   -- the advanced knobs, as sent
  parent_id INTEGER,                 -- the take this was derived FROM: a repaint's
                                     -- source, or the take a voice pass converted.
                                     -- NULL for a fresh generation.
  origin TEXT,                       -- gen | cover | repaint | svc
  created REAL);

-- WHICH voice sings WHERE. Not a column on takes: a track can have four singers
-- and the whole point of the SVC path is that they are per-REGION, over one
-- untouched accompaniment. A take with no rows here is sung by whatever voice
-- generated it, which is every take until phase 3.
CREATE TABLE take_voices (
  id INTEGER PRIMARY KEY, take_id INTEGER NOT NULL, voice_id INTEGER NOT NULL,
  start_secs REAL, end_secs REAL,    -- NULL/NULL = the whole track
  params_json TEXT);                 -- f0/semitone/steps, per region: a low
                                     -- harmony and a lead are not converted alike

-- A VOICE is a timbre reference, not a model. What makes one usable is a short
-- clip of SPEECH -- Seed-VC is zero-shot and the reference need not sing. Where
-- that clip came from is the part that must not be lost, which is why source and
-- consent are columns rather than a note nobody fills in. kind decides which of
-- path/reference_id is meaningful: a local clip and a hosted fish.audio id are
-- not the same object and must not share a column.
CREATE TABLE voices (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL,                -- 'local' (a clip) | 'fish' (a hosted id)
  path TEXT, reference_id TEXT,
  source TEXT, consent TEXT,
  note TEXT, created REAL);

-- The TRAINING LIBRARY. A row here is reference material, NOT a song: songs are
-- what this studio publishes, these are what it learns from, and one table for
-- both puts unreleasable material on the Library page. licence has exactly two
-- honest values because the LoRA path may draw only on the owner's own catalogue
-- or on licensed work, and a nullable field is how that gets skipped.
CREATE TABLE library (
  id INTEGER PRIMARY KEY, path TEXT NOT NULL, title TEXT,
  bpm REAL, keyscale TEXT, energy REAL,   -- from the SAME analyse job
  tags TEXT,                              -- SETS_MIXING_PLAN phase 2 specifies
  licence TEXT NOT NULL,                  -- 'own' | 'licensed'
  trainable INTEGER DEFAULT 0,            -- WAV/FLAC 44.1kHz+, 30-120s. An mp3
  created REAL);                          -- is reference-only, never training.
```

```python
# Musical facts about the track. WRITTEN AT GENERATION TIME when the studio made
# it -- these were inputs, not measurements -- and by the analyse job when it did
# not. songs.bpm has been in the schema since the beginning and nothing has ever
# written to it; between this and SETS_MIXING_PLAN's analyse job, something
# finally does.
"ALTER TABLE songs ADD COLUMN keyscale TEXT",
"ALTER TABLE songs ADD COLUMN timesig TEXT",
"ALTER TABLE songs ADD COLUMN language TEXT",
# WHERE the audio came from. Not a judgement -- it is what tells you what can be
# done to a track. A local take carries its seed and parameters and can be
# regenerated; an upload can only be repainted, because there is nothing to
# regenerate FROM. Every song here today is 'suno'.
"ALTER TABLE songs ADD COLUMN audio_origin TEXT",   -- suno | local | upload
```

The disclosure level is a `settings` row (`ui.level`), **not** a column on any
table that touches content — a studio-wide preference exactly as the per-role
model choices are, and for the same reason: a per-song copy goes stale and,
worse, invites gating content by it.

---

## 5 · Test plan

Matching what exists: module `demo()` self-checks, `TestClient` route tests in
`test_app.py`, one-place stubs in `conftest.py`, seam contracts in
`check_integration.py`, concurrency in `test_load.py`.

**Unit — `build_track.py` `demo()`** (no GPU, no network). The workflow JSON it
writes carries node names and links `submit_dir()` will accept;
bpm/duration/keyscale/timesignature/language land on
`TextEncodeAceStepAudio1.5`; `EmptyAceStep1.5LatentAudio.seconds` matches the
requested duration; supplying a timbre reference adds both `VAEEncodeAudio` and
`ReferenceTimbreAudio`, and omitting one adds neither; a repaint job emits a mask
whose non-zero span matches the requested seconds at 25 latent frames per second.

**Unit — `studio/pipeline.py` `demo()`.** `gen_track()`, `gen_repaint()` and
`gen_voice()` through the existing fake-ComfyUI `_post`/`_get` stubs, the same
shape as the current `gen_refs` test. `gen_voice()` submits **three** graphs, not
one — separation, conversion, remix — because they must not be co-resident.

**Unit — `studio/conftest.py`.** `pipeline.gen_track` / `gen_repaint` /
`gen_voice` stubs recording their arguments in the style of `refs_calls` and
`anchor_calls`; a `vision.draft_lyrics` stub in the style of
`read_edit_instruction`'s; a `fish` stub so no test reaches the network.

**Integration — `studio/test_app.py`**, named in the house style:

- `test_generate_creates_a_take_and_never_overwrites_the_song`
- `test_using_a_take_records_the_original_once_and_revert_restores_it` — the
  `audio_original` asset already exists for the edit path and must not be
  double-recorded by a second writer.
- `test_generation_params_are_clamped_like_the_audio_edit_ones` — parametrized
  hostile values mirroring `test_audio_edit_rejects_hostile_params`: bpm 10–300,
  duration 1–1000, cfg 0–100, temperature 0–2, semitone shift, SVC steps,
  nan/inf everywhere.
- `test_lyrics_and_style_text_reach_the_generator_and_explicit_does_not` — the
  sibling of `test_explicit_not_passed_to_grok_or_pipeline`. `songs.explicit`
  describes the lyrics and must never steer generation.
- `test_generated_lyrics_are_screened_before_any_model_is_called` — the sibling
  of `test_storyboard_direction_is_screened_before_any_model_is_called`. **A
  lyrics box is the largest new free-text surface in the app**; every other one
  goes through `check_text` + `check_override` and this one is no different.
- `test_repaint_refuses_a_range_outside_the_track_and_when_the_node_is_missing`
- `test_repaint_of_an_end_region_uses_ffmpeg_not_the_model` — the cheap path must
  actually be taken, not merely be available.
- `test_voice_regions_do_not_overlap_and_cover_only_the_track`
- `test_a_voice_requires_a_consent_basis`
- `test_a_fish_voice_stores_a_reference_id_and_a_local_one_stores_a_path` — the
  `kind` discriminator, tested rather than trusted.
- `test_library_refuses_mp3_as_training_input_but_accepts_it_as_reference`
- `test_feature_level_hides_controls_but_never_changes_what_a_content_tier_permits`

**End-to-end — `studio/test_load.py`.** A generate job, a voice job and a clips
job never overlap — the single-worker invariant extended to the new kinds; two
generate requests queue rather than both reaching the card; and a full
upload → generate → repaint → voice → use-take → render chain runs through the
real job queue against the stubs, which is the only place the take/song/asset
bookkeeping is exercised end to end.

**Contracts — `studio/check_integration.py`.** `pipeline.gen_track` accepts every
parameter `app.h_generate` passes (via the existing `sig()` helper); every ACE
node name `build_track.py` writes appears in the catalogue's companions; the
repaint and voice jobs refuse when their nodes are absent; and the existing
`RENDERED_ROLES` assertion keeps forcing `build_track.py` to exist.

**Observability.** Every take records seed, wall-clock, which path ran (fresh /
cover / repaint / svc / ffmpeg-trim) and the parameters as sent — `h_edit_audio`
already stores `prompt`/`note`/`model` in `meta_json` for exactly this reason
("an edit you cannot explain six months later is an edit you cannot reproduce").
Same rule, same place, no new mechanism. Peak VRAM goes in the job log where
LTX's numbers went. The voice job reports **per stage** (separate / convert /
remix), because a chain that reports only at the end tells you nothing about
which of four hops lost the quality.

---

## 6 · The competitive advantage, argued

**What this can do that Suno structurally cannot:**

1. **Point at a region of the timeline.** "Remove the giggling in the first four
   seconds" is a mask over latent frames and a regenerate. Suno's surface is a
   prompt; there is nowhere to point and no way to say "keep the rest". This is
   not a feature Suno declined to build — it is unavailable through a prompt-only
   interface, which is precisely why the user's prompts cannot get it.
2. **Any number of named voices, on one untouched accompaniment.** Suno's
   advanced settings offer male/female. Separate → SVC → remix puts a different
   voice on each section — duet, band, quartet, backing stack — with the backing
   track never re-rendered. And the voices are *yours*: a fish.audio clone or
   30 seconds of someone speaking becomes a singer.
3. **Commission a track at a BPM and in a key.** bpm, keyscale, timesignature and
   duration are typed inputs, not hints buried in a style string.
   `SETS_MIXING_PLAN.md` phase 3 beat-matches by *detecting* tempo and stretching
   toward it; generating locally means the set can **ask for** the tempo and a
   Camelot-adjacent key and get them. A DJ set built out of tracks written to fit
   each other is a category no prompt-driven service can offer.
4. **The song and the video stop being strangers.** `lyrics.py`'s own docstring
   admits Whisper on sung vocals over dense production gives a mediocre
   transcript with drifting timestamps — and the storyboard is built on it.
   Generate the song and the lyrics, section boundaries and tempo are *known
   exactly*; scene boundaries can be the real `[chorus]`. This compounds, and
   nobody who owns only one half of the pipeline can have it.
5. **Zero marginal cost per retry, and no content policy but `guardrail.py`.**

**What Suno will still do better, and should be said out loud:**

- **Lyric intelligibility.** 26.3 against 34.2, on the axis a listener judges
  first. Expect words to be mushier.
- **English vocal accent artifacts** are a known ACE-Step weakness, and SVC does
  not fix pronunciation — it changes *who* is singing, not *what* they said.
- **Mix polish out of the box**, and a much higher one-shot hit rate.
- **Nothing to install, nothing to maintain.** Suno does not break on an upgrade.

The mitigation is the studio's existing shape, not a wish: generate several, pick
by ear, repair rather than re-roll. That is exactly how anchors and refs already
work, and it is why takes are candidates in phase 1 and repaint is phase 2 rather
than phase 5.

---

## 7 · Where it runs, what it costs

| Piece | Where | Why |
|---|---|---|
| ACE-Step 1.5 sampling, `VAEEncodeAudio`/`Decode`, the repaint node, Demucs, Seed-VC | **ComfyUI venv** on cerberus | it is the venv with torch; that is the whole rule, and a custom node costs nothing extra against it |
| `build_track.py`, job handlers, ffmpeg engineering, librosa analysis, sqlite | **studio venv**, same box | no torch here, deliberately, and nothing in this list needs it |
| fish.audio | **external**, `POST /v1/tts` | key from `~/.config/`, never the repo |
| Lyric drafting for the easy tier | **local litellm gateway** | already wired through `vision.ask_text`; free |
| LoRA training | **isolated venv, run by hand** | the one thing Option A cannot do, and the one thing that must not become a job kind |

| Phase | Effort | Cost | Note |
|---|---|---|---|
| 0 spike | ~1 day | £0, ~10–20 GB download | gates everything |
| 1 generate | 2–3 days | £0 | `build_track.py` ≈ 200 lines, `build_refs.py`'s shape |
| 2 repaint | 2–4 days | £0 | node ≈ 100 lines; waveform range-select is most of the rest |
| 3 voices | 4–6 days | fish.audio free tier | two node installs + weights; three-stage job; the A/B gate |
| 4 library | 3–5 days | £0 | retrieval half only; LoRA is open-ended and out of scope |
| 5 engineering | 1–2 days | £0 | ffmpeg only; the DJ plan already specifies the filters |

**Minimum path to "sounds amazing": phases 0, 1, 2, 3** — roughly 9–14 days.
That is generation, surgical editing, and named multiple voices, which is every
headline the user asked for. Phase 4's retrieval half is a bonus; LoRA training
is not on the path and should not be allowed onto it. **No infra work starts
before that path is walked.**

---

## 8 · The documents

**1. `docs/AUDIO_GENERATION_PLAN.md`** — phases 0–5 in full, with the
verified-facts table, the three `model_base.py` findings, the two voice paths,
the pre-mortem and the test plan.

**2. `docs/FEATURE_TIERS.md`** — easy / enthusiast / advanced across audio *and*
video, each control named against the code that already implements it.

**Keep 1 and 2 separate.** The audio plan is a build plan with phases and gates
that gets *finished*; the tiers doc is a standing contract, spanning both halves
of the studio, read by whoever adds the next control. Merged, the contract ends
up buried in phase notes and rots — exactly what happened to the album profile
before it left `make_anchor.py` for the database. And the tiers doc has to cover
video, which has no business inside an audio buildout plan.

Its content is mostly *assignment*, not invention — the video controls all exist:

| Level | Audio | Video (all existing controls) |
|---|---|---|
| **easy** | prompt → drafted lyrics, genre/subgenre from `genres.json`, duration, one button | pick a tier, "make the video"; storyboard/refs/clips/render defaulted, model from `models.default_for()` |
| **enthusiast** | the node's own inputs — tags, structured lyrics, bpm, keyscale, timesignature, language, duration, seed — plus voice per section and take comparison | storyboard direction textarea, scene edits, video-model choice, refs `limit`, approve grid, reroll with a note |
| **advanced** | cfg_scale, temperature, top_p, top_k, min_p, generate_audio_codes, cover mode and reference strength, masked repaint, SVC f0/semitone/steps/BigVGAN, per-stem EQ and loudnorm, LoRA scale | `ref_motion`, `control_video`, the refiner pass, per-frame repair (face / inpaint / outpaint), seeds, fades, per-item set effects |

The doc's first line is the invariant: **a feature level never changes what a
content tier permits, and a content tier never changes which controls are shown.**

**3. `docs/INFRA_REQUIREMENTS.md`** — requirements only, explicitly deferred,
nothing built. GCP shape (including the honest option that inference stays on
cerberus and only the web tier moves); Terraform modules; Ansible playbooks — for
which **`deploy.sh` is already the specification**, since it does venv, systemd
unit, rsync and smoke test in order; user management; subscription.

It must state plainly that the app has **no authentication of any kind** today,
binds `0.0.0.0` (as `deploy.sh` already reports honestly), sits beside an
unauthenticated ComfyUI, and keeps keys in `~/.config/morpheus/`. That is a fine
posture on a home tailnet and is not one anywhere else. Multi-tenancy is the
expensive line item — every table is single-tenant and `settings` is global — and
it should be **named, not costed**.

**Trigger to begin it:** the user has generated a full song locally, end to end,
in a voice they chose, that they prefer to its Suno equivalent, and has cut a
video to it. Written down so the deferral has an end condition rather than being
indefinite.

**4. The `SETS_MIXING_PLAN.md` amendment** — the section in phase 5 above,
appended. Not a rewrite, and no filter table duplicated.

---

## 9 · Open questions, and what must be spiked before commitment

**Must be measured before anything is committed to (phase 0 and the phase 3
gate):**

1. **Peak VRAM for ACE 1.5 alone, and for the voice chain.** 24463 MiB, 22265
   already held, `memory_usage_factor` 4.7. This can invalidate the phasing.
2. **Do `[verse]`/`[chorus]` tags do anything on 1.5?** Tokenised in 1.0, free
   text in 1.5's Qwen3 template. Decides whether `lyrics.to_sections()` is a gift
   or a liability.
3. **Does a short timbre reference work in cover mode**, given it is
   silence-padded to full track length?
4. **Does `chunk_masks` do what the source says?** Patch it locally and listen
   before writing the node.
5. **Does the SVC chain beat cover mode by ear** on this catalogue's high-pitched
   vocals, with BigVGAN and 30–50 steps? If not, multi-voice waits.

**Open questions:**

1. **Is `refer_audio[-1]` deliberate or an oversight?** The architecture packs and
   unpacks multiple timbre embeddings (`unpack_timbre_embeddings`), so the
   capacity is there. Now less urgent — SVC gives multi-voice without it — but it
   would make cover mode multi-voice too.
2. **What does `duration` do when the lyrics do not fit** — pad, rush, or
   truncate? The storyboard's coverage meter exists because pacing mismatches are
   invisible until you watch them; the same failure exists here and wants the same
   kind of meter.
3. **Which separator.** Demucs quality on dense electronic production with
   heavily processed vocals is the case that matters here and is the case
   separators handle worst. Measure on a real track from this catalogue before
   picking.
4. **Take retention.** Anchors and refs keep every candidate. A 3-minute 48 kHz
   take is tens of megabytes, generation is cheap enough to make dozens, and a
   voice pass multiplies them. Either a delete-unpicked action like the anchors
   one, or a cap — decide after seeing how many a real song needs, not before.
5. **Does the library ever link to `songs`?** Starting assumption is no: different
   objects, and the separation is the point. Revisit only if the user wants their
   own released tracks in the training set — likely, and the reason to keep
   `library.path` free-standing rather than a foreign key.
