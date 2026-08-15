# DDD · Design for TRD 4-7

Status: written 2026-08-13. Product: `docs/PRD-4-7-IDENTITY-AND-RENDERING.md`.
Sequencing and review record: `docs/PLAN-TRD-4-7.md`,
`docs/reviews/PLAN-TRD-4-7-RECOMMENDATIONS-2026-08-13.md`. Sibling:
`docs/DDD-1-3-EDITING-AND-QUALITY.md`.

**Read off the tree at `f9ca597` plus session B's `415584d` / `4032aba` /
`d315c6f`.** The built state in here moved three times during the writing of the
plan, so every claim names what it was read from.

---

## 1. The anchor path, as it actually is

There is **one graph**, and TRD-7 §1 corrected the brief that said otherwise:
`make_anchor.py` does `from build_refs import workflow`, `pipeline.gen_anchor`
shells out to `make_anchor.py`, and `h_anchor` calls `gen_anchor`. An anchor
sheet and a clip reference frame come out of the same eight nodes, the same
`qwen_image_edit_2511_fp8mixed` UNET, the same Lightning LoRA and the same
`qwen_2.5_vl_7b_fp8_scaled` text encoder.

**So nothing here is an integration.** It is closing the gap between the
parameters `build_refs.workflow()` already takes and the ones the anchor path can
express. That framing is the whole design: no new builder, no second model, no
ControlNet.

| module | owns |
|---|---|
| `make_anchor.py` | the view table, the positive constants, `is_nude_view`, `prompt_for`, the call into `workflow()` |
| `build_refs.py` | the graph: `workflow()`, `sampler_settings`, `assign_ref_slots`, `cast_clause`, `negative_applies` |
| `studio/app.py` | the anchor routes, `ANCHOR_VIEWS` labels, `ANCHOR_RENDER_FLAGS`, `DENOISE_CHOICES`, the preview |
| `studio/prompts.py` | `PROMPT_TYPES` — 9 today, 4 more in `T7-13`…`T7-16` |
| `studio/tiers.py` | `compose_guardrail`, `check_text`, `check_override`, `check_tier_policy` |
| `build_song.py` | TRD-5's territory: `workflow()`, the LTX branches, `clip_plan`, `expect_from_workflow` |
| `studio/jobs.py`, `pipeline.py`, `db.py` | TRD-6's territory |
| `studio/vision.py` | `score_candidate(path, bases, prompt)` — advisory identity+prompt match; a failure stores the xAI/local error and the backend that actually failed (not `available()`'s hope); `h_anchor` and `h_fix_anchor` write `anchors.qc_json`; `h_artwork` writes `assets.qc_json` on the generate and on a refine sibling; `qc_tag` shows the named failure, never "vision unknown" (`T3-31`, `T4-19`) |

**The pipeline, and it is not a loop of adding bases:** operator base
photographs (`assets` kind `anchor_ref`) → generate *candidates*
(`anchors` rows) → pick `chosen=1` → that sheet feeds storyboard
*reference frames* → clips. A pose plate is not a base image unless the
operator put it there.

## 2. The view table — one table, two projections

`T7-2` is done in both files: `make_anchor.NUDE_VIEWS` and `app.NUDE_VIEWS` are
both now `tuple/frozenset(v for v in … if is_nude_view(v))`, so nudity is derived
from what a view *is*. **`T7-1` is not done**, and the reason is visible in the
two tables that remain:

    make_anchor.DEFAULT_VIEWS   {key: framing sentence}
    app.ANCHOR_VIEWS            {key: human label}

Same keys, two files, two hand-kept dicts. Adding `three_quarter` today means
editing both — one for the sentence the model reads, one for the words the
operator reads. That is the same shape `NUDE_VIEWS` had before it was derived.

**Design: one table in `make_anchor.py`, two accessors.**

    VIEWS = {
      "front":       {"label": "front, clothed", "framing": "FRONT VIEW …"},
      "three_quarter": {"label": "three-quarter, clothed",
                        "framing": "THREE-QUARTER VIEW … body turned 45° … "},
      …
    }

`app.py` reads `make_anchor.VIEWS` for its labels; nothing keys a second dict on
view names. Nudity stays **derived** (`is_nude_view`) rather than becoming a
third field, because a field is a thing somebody can forget to set and a
derivation is not — that is exactly the argument `is_nude_view`'s own docstring
makes and it should not be walked back for the label.

`T7-3`'s new views — `three_quarter`, `profile`, `seated`, `portrait`,
`on_all_fours`, each with a nude parallel — are then entries, and `T7-5`'s
problem is local to one of them:
`BACKDROP` ends *"full body head to toe inside the frame"*, which argues with a
head-and-shoulders `portrait`. **A view must be able to override a backdrop
clause, not only add to it** — which is why `T7-5` and `T7-14` (backdrop becomes
a versioned prompt) belong in the same phase.

**`T7-4` is the compose-diff on that table.** Two views of one clothing family
that share a backdrop omit must compose to the same remainder once each
framing sentence is stripped; a nude pair of that family uses the wardrobe
swap instead of the album outfit. The check is `studio/test_t7_4_framing.py`,
through `prompt_for` and `default_anchor_prompt`. A view-only extra clause
makes the remainders diverge. Portrait/seated omit is `T7-5`, not this.

## 3. The four new prompt types

`prompts.py` carries 9 types today and its docstring states the extension rule —
*"adding a type here is all that is needed to give it history"*. Four more:

| type | tiered | why it is a prompt and not a constant |
|---|---|---|
| `view:<key>` | no | how a camera is placed is not a function of the rating. **Generated from `VIEWS`, not written per view**, or `T7-1` is undone the moment a view is added |
| `backdrop` | no | five clauses of studio, lighting, framing and focus welded together, shared by every sheet ever rendered here; `T4-13`'s lighting lock lands inside it and `T7-5` overrides half of it |
| `composite` | no | the clause deciding whether three references are one character or three. Load-bearing for `T7-10` and untunable today |
| `pose` | no | what the character is *doing*, as distinct from where the camera is and what they look like. The variation knob the form lacks |

Two constraints that make this smaller than it looks:

- **`T7-17`: composed by `make_anchor.prompt_for` and visible in
  `anchor_prompt_preview`.** The preview runs the real composer; a type the
  preview cannot show is a type the operator edits blind. `prompt_for(view,
  anchor, n_refs)` already assembles `[views[view], wardrobe, body, identity]` —
  the new types slot into that list, they do not get a second composer.
- **`T7-18`: screened by `screen_prompt_field` and walked by
  `test_no_positive_prompt_constant_tries_to_negate`.** `_NEGATION_ALLOWED` is
  `()` and the walker has no exemptions, so a new type that says "no" fails the
  suite — and since `4032aba` the walker also covers `app.ALBUM_FIELDS`'
  defaults, which is where the last negation was actually hiding.

**The completion bar, from review: red-before-green per type.** The negation
walker is green today *because the four types do not exist*. Using it as the gate
for adding them would be a check satisfied by absence, in the gate for the work
whose whole point is not doing that.

## 4. The identity lock

Identity comes from the text, not from the reference image. Saving a
storyboard whose `character_reference` is empty is refused
(`T2-31` / `T2-32` / `grok.EMPTY_CHARACTER_REFERENCE`). When a sheet or
clip is wrong from the first frame, the QC remedy is edit the text, then
re-render (`T3-28` / `qc.check_identity_wrong`). Swapping the reference
image is refused — measured 2026-08-12: same reference, same seed, same
box; species named or not is the one variable.

`T7-6` shipped (`d315c6f`): "use as reference" on an anchor tile, the row points
at the sheet's own file with no copy, deleting the ref keeps the file, deleting
the anchor cascades to its borrowed refs. That is the same mechanism `gen_refs`
uses for clips — `pipeline.install_input` on the chosen anchor's path — which is
why clips stay on-model.

What that unblocks, and the order:

**`T7-8` and `T7-9` shipped while this section was being written** — session B's
`d3f2f6a`, *"the sampler can start from a reference, and no photograph is
promoted to a plate behind your back"*. `latent_mode` is no longer pinned and
`base=None` is now the default, so the second picked reference is not silently
promoted to the composition plate. **This is the third time in one session that
a built-state claim went stale between being verified and being written down**,
which is why every ledger here names the commit it was read at rather than a
date.

The design points survive their implementation and are why they were worth
stating:

- **One resolver decides the denoise label and the graph.** The differential
  asserts from both ends: with image mode selected the labels change *and* the
  graph carries the image latent; with it unselected the labels still warn *and*
  the graph does not. Mutating either end alone must go red. This is the
  editor-promises-what-the-renderer-does-not defect in its mildest form — five
  of six `DENOISE_CHOICES` were labelled *"on an anchor this returns noise"* and
  were correct, a dropdown documenting its own uselessness.
- **The plate is named or it does not exist. Silently is the option that was
  out**, and `base=None` is the version of that answer which removes the
  question rather than answering it — the smaller change, and the right one.

**`T7-11`, `T7-12` — `lora_strength` and `w`/`h`.** Independent of the chain
above. `build_refs.sampler_settings` already keeps an escape hatch (cfg > 1.0
forces lora_strength to 0 *unless passed explicitly*) and the studio cannot reach
it because `pipeline`'s flag map omits it. `w`/`h` default to today's 896×1216 —
and a fixed size is what makes a `portrait` view render a distant figure.

**`T7-7` is the measurement, and it is human-judged on purpose.** Render `front`
and `three_quarter` from an anchor and from the raw photographs; four images side
by side; one recorded answer. No threshold is invented — review asked for one and
a fake number on a judgement call is worse than an honest human step. The
offline ranking (`t7_7_identity_differential`) is that comparison: which pair
holds identity, with no cutoff. `T7_7_REAL_PAIR_MEASURED` stays False until a
GPU four-image set is recorded. The compose hook (`b081030`) FLAGs a compose
that asserts a human body — live-studio "Human woman's body" included — through
`run_artefact`. That does not replace the picture look.

## 5. Refine on LTX

`build_song.workflow()` returns for the LTX families before the refine block is
reached, so `--refine` on `ltx25` — the catalogue default — does nothing and says
nothing.

**Do not wire the WAN refiner to LTX.** It re-samples the s2v latent with
`wan22_i2v_low` and that is valid *only* because s2v and i2v-low share
`wan_2.1_vae`. LTX has its own video VAE.

Variant **A** (Jon's decision, 2026-08-13): a same-resolution second pass,
inserted **before `VAEDecode` (node 23)**:

1. take the **video** latent — node 22's output when `with_audio`, else 21.
   **Split the AV latent first**: a joint audio-video latent into a spatial
   upsampler is not a thing.
2. truncated sigmas via `SplitSigmasDenoise(sigmas, denoise=<refine denoise>)`,
   `low_sigmas`, **reusing guider 17** so the conditioning is byte-identical
   between passes.
3. a second `SamplerCustomAdvanced` with a fresh `RandomNoise` seed, mirroring
   the WAN path's `2000 + i`.
4. `VAEDecode` the refined latent.

Variant **B** adds `LatentUpscaleModelLoader` → `LTXVLatentUpsampler` at step 2.
Every node either needs is installed on cerberus, verified against `/object_info`.

**Assembly geometry (`T5-7`), ready before B ships.** `mixer.assembly_geometry`
picks the largest same-aspect size among the clips, and `assemble_song` scales
to that size with an exact `scale=W:H` — no `force_original_aspect_ratio=decrease`
and no `pad`. A 1664×960 B clip among 832×480 siblings therefore keeps its
pixels; the siblings are scaled up, not letterboxed. Mixed aspect is a named
`ValueError`. `_normalize_filter`'s decrease+pad path stays on `render_set`
(playlist songs of different geometry), not on song assembly.

**The measurement that decides whether B is possible runs first, not last.** The
base render already peaks at 23.4 GB of 23.9 on cerberus — 95.8% of the card — at
832×480. **`T5-6` recorded the finding on the `ltx25` notes: variant B does not
fit.** 0.5 GB of headroom cannot hold a 4× spatial latent plus the 0.3 GiB
upscaler on the same graph. `--refine` ships variant A. Silently dropping the
upsampler and calling A a two-stage is the defect this document is about.

**Proof, split after review:** mean absolute pixel difference > 0 is the
**no-op guard** (`T5-1`), not the quality claim. It passes on noise and on any
non-semantic perturbation. The quality claim needs a named metric on a fixed
fixture set moving in a stated direction. `T5-2`'s wording in TRD-5 now names
both: MAD > 0 is the no-op guard; Laplacian variance on the same pair is the
quality metric. `qc.t5_2_refine_differential` measures decoded frames (arrays
or video paths). Missing frames raise `NOT MEASURED`; `skip` is not a reading.
`T5_2_REAL_CLIP_MEASURED` stays False until a same-seed GPU pair is decoded.
A graph-only assert is `T5-1`, not `T5-2`.

**Ceilings (`T5-9`).** `build_song.CLIP_CEILINGS` (mirrored on the video
`CATALOG` rows) labels LTX 15 s as a **measured** cost ceiling and s2v
4.8125 s as **chosen**. `workflow()` calls `honour_ceiling` on the scene's
requested length: over the ceiling raises, naming the origin. `split_to_ceiling`
is the split answer. `clip_seconds` / `legal_frames` stay the planner half and
still accept a 30 s divisor so song length owns clip count.

## 6. Queue, lifecycle and identity (TRD-6)

25 criteria, and TRD-6 §8 states the design constraint better than a design
section can: **every criterion here describes machinery that does not exist, so
each must be written as a red test first** or the document is satisfied at scale
by never building it.

**What is already true**, and should not be rebuilt: `artefacts.expect_json`
written at submit time by `pipeline._stamp_expect` from
`build_song.expect_from_workflow` (`T6-11`); `pipeline._backend_vanished`
distinguishing a box that went away from a workflow a box refused, which arrive
under the same "No backends match" headline (`T6-4`); WAL on, and the
`MIGRATIONS` convention that every added column works NULL on existing rows
(`T6-17`); the `findings` upsert idempotent under re-run (`T6-15`);
`jobs.canonical_path` at write time so `findings.path` joins `artefacts.path`
and two spellings of one file are one row (`T6-8`); a job handler's land +
findings writes are one transaction (`T6-14`, `jobs.writes()`), and `_run_one`
still drops the write lock before a long handler (`T6-16`).

**The shape of what is not:**

- **`T6-13a` first, and it does not wait for the rest.** `songs.duration`, written
  once from ffprobe on upload, is the authority. TRD-1 §3.2 (`app.clip_count`),
  TRD-2 §3.4 (`grok.generate_storyboard`) and TRD-3 §4.4 (`qc_service.run_song`
  assembled expect; `h_qc` forwards) all read that column; a re-ffprobe on those
  paths fails
  `test_t6_13a_songs_duration_is_the_authority_and_nothing_reprobes`.
  `DDD-1-3` §6's chain now starts at `T6-13a`.
- **Identity before lifecycle before queue.** `T6-8`'s path is the join key
  later rows attach to. Cascade policy is stated **per table**, not inherited
  from whatever sqlite does.
- **`T6-2` is the criterion that makes chains safe**: "ready" expressed
  separately from "queued", because a chained clip needs its predecessor's last
  frame to exist (TRD-2 `T2-11`).
- **`T6-1`'s pull model is a rewrite of machinery that works.** A backend that is
  slow, off, or behind a VPN self-corrects by pulling less, and the measured
  291.6 s vs 378.2 s inversion never arises because nothing is split by a
  forecast. It is right, and it is the phase most likely to cost more than it
  returns if it starts before TRD-4/5/7 are done.

## 7. Where the studio still owns two copies of one fact

Design-level, because each is a place a future change can silently disagree with
itself. Two are folded by `PLAN-TRD-4-7` §2; these are the ones that remain in
code rather than in documents.

- **`DEFAULT_VIEWS` / `ANCHOR_VIEWS`** — §2. The last hand-kept view pair.
- **`ALBUM_FIELDS` defaults vs `make_anchor`'s constants** — `4032aba` fixed the
  `body` case *and the general shape remains*: `album_profile()` fills every
  field from its default, so a truthy default always beats the constant. The
  negation walker now covers both; nothing yet asserts they *agree* except for
  `body`.
- **`DENOISE_CHOICES`' labels vs `latent_mode`** — §4, `T7-8`. One resolver, or
  the label and the graph drift the moment either moves.

## 8. How this design is verified

The rule, stated once and binding on everything above, because writing thirty
per-criterion differentials into a design document is writing the tests in the
wrong file:

> A criterion is done when a mutation to the code it describes turns a check
> red, **and somebody read what the mutation actually did**. Not when the code
> exists, not when a string is present, not when a refusal fires.

Plus the two this subject is most exposed to:

- **A refusal or a presence is half a criterion.** TRD-4/5/6/7 carry no
  one-sided-criteria table while TRD-1/2/3 each do; `PLAN-TRD-4-7` Phase 0 adds
  them. `T4-3`, `T4-16`, `T4-17`, `T7-2` and most of TRD-6 are the candidates.
- **When an image looks wrong, look at it.** `T4-13`, `T7-5` and `T7-7` are all
  criteria about what a picture looks like. The identity collapse, the world that
  never rendered and the LoRA that did nothing all passed every deterministic
  check this project had. `T4-13` now has a pixel harness:
  `qc.LIGHTING_LOCK` / `check_channel_balance` FLAGs olive and magenta fixtures
  and PASSes a grey wall; whole-image mean is not the metric (a black figure on
  an olive wall still FLAGs). The `BACKDROP` string is not the proof.
  `T4_13_REAL_SHEET_MEASURED` stays False until a rendered sheet is pointed at.
