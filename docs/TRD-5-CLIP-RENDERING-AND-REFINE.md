# TRD-5 · Clip rendering and refine

Status: **rewritten 2026-08-17** for Jarvis **#529** (D6–D9). The 2026-08-13
text still owns T5-A refine, ceilings, and the latent forbid. This pass
requires LTX first on every scene and a decoded s2v hop on marked lip
scenes. Source of truth:
`docs/PROMPT-2026-08-15-PIPELINE-REQUIREMENTS.md`.

Acceptance criteria are `T5-n` and each **can fail**. Everything asserted about
the fleet below was queried live on 2026-08-13, not remembered.

---

## 1. `--refine` is a silent no-op on the default video model

`build_song.workflow()` returns for the LTX families before the refine block is
reached:

    build_song.py:550   if video_model in ("ltx", "ltx25"):
                            build = ltx25_workflow if video_model == "ltx25" else ltx_workflow
                            return build(...)
    build_song.py:619   if refine:      # unreachable for ltx and ltx25

`ltx25` is the catalogue default. So passing `--refine` on the model this studio
renders with does nothing **and says nothing** — the accepted-and-ignored shape
these documents exist to catch, sitting in the flag whose whole purpose is to
change the output.

**The existing refiner is WAN-only and correctly so.** It re-samples the s2v
latent with `wan22_i2v_low` at `REFINE_DENOISE = 0.25` / `REFINE_STEPS = 6`, and
that is valid *only* because s2v and i2v-low share `wan_2.1_vae`. LTX uses its
own video VAE. **Handing an LTX latent to WAN is meaningless — do not wire them
together.**

- `T5-1` `--refine` with `ltx` or `ltx25` either adds a second pass or **raises
  naming the reason**. It never returns a graph identical to the unrefined one.
  *Mutation: restore the early return → a test asserting the graph gains nodes
  goes red.*

## 2. Two variants. Ship A, measure before B

**Variant A — same-resolution second pass.** Re-denoise the sampled latent at
low sigma with the same guider. No upsampler, no extra VRAM, no resolution
change. The minimum thing that makes `--refine` mean something on LTX.

**Variant B — upsample, then re-denoise.** `LTXVLatentUpsampler` ×2 then the
second pass at the higher resolution. LTX's own documented two-stage, and the
only one that adds detail rather than redistributing it.

**DECIDED 2026-08-13 by Jon: A first, B after it is measured.**

Both share one shape, inserted **before `VAEDecode` (node 23)**:

1. take the **video** latent — node 22's output when `with_audio`, else 21.
   **Split the AV latent first**: a joint audio-video latent into a spatial
   upsampler is not a thing.
2. *(B only)* `LatentUpscaleModelLoader` → `LTXVLatentUpsampler(samples,
   upscale_model, vae)`.
3. truncated sigmas via `SplitSigmasDenoise(sigmas, denoise=<refine denoise>)`,
   taking `low_sigmas`, **reusing guider 17** so the conditioning is
   byte-identical between passes.
4. a second `SamplerCustomAdvanced` with a fresh `RandomNoise` seed, mirroring
   the WAN path's `2000 + i`.
5. `VAEDecode` the refined latent.

Every node this needs is installed on cerberus, verified against
`/object_info`: `LTXVLatentUpsampler`, `LTXVScheduler`, `SplitSigmas`,
`SplitSigmasDenoise`, `SamplerCustomAdvanced`, `LatentUpscaleModelLoader`.

- `T5-2` **The differential is on the OUTPUT, not the graph.** Same seed, same
  scene, refine on and off: the decoded frames differ measurably (mean absolute
  pixel difference > 0) and a sharpness metric moves in the right direction. A
  test that only asserts the nodes exist proves the code exists, not that
  anything reaches it. **Split after review:** MAD > 0 is the no-op guard
  (refine did *something*). Laplacian variance on the same pair is the named
  quality metric (right direction: sharper). Missing decoded frames raise
  `NOT MEASURED`; `skip` is not a reading. Graph-only is `T5-1`, not this.
- `T5-3` The refine pass runs at **denoise < 1.0**, mirroring the assertion the
  WAN path already carries: a refiner at denoise 1.0 is not a refiner.
- `T5-4` Refine changes no output-path semantics: still a new file, never an
  overwrite.

## 3. The measurement that decides whether B is possible at all

`models.py`'s `ltx25` notes record the base render peaking at **23.4 GB of 23.9
on cerberus — 95.8% of the card** at 832×480. An ×2 latent refine may simply not
fit. **Measure this first, not last**, with `pipeline.free_vram()` before the
render as the clip job already does.

- `T5-5` Peak VRAM for whichever variant ships is **measured on the box it ran
  on** and recorded in `models.py` beside the existing 23.4/23.9 figure. A number
  quoted rather than measured fails review.
- `T5-6` **If B does not fit, that is recorded as a finding in the `ltx25`
  catalogue notes and A ships.** Silently dropping the upsampler and calling the
  same-resolution pass a two-stage is the defect this whole document is about,
  committed while fixing it.
- `T5-7` If B ships, its ×2 output resolution reaches `CreateVideo` **and the
  assembled song's geometry normalisation still holds**: a clip at 1664×960
  among 832×480 siblings must not silently letterbox at assembly.

## 4. The upscaler is catalogued — and the brief's premise about it was wrong

**BUILT 2026-08-13.** `LatentUpscaleModelLoader` is in `LOADER_FIELD` and
`ltx25_latent_upscaler` is in `CATALOG`, so it is visible to `catalog()`,
`by_backend()` and `pipeline._retarget` rather than invisible the way
`clip_vision` was before 2026-08-12.

The brief said `model_name` "publishes the literal `COMBO`, not a list", so
availability must read **unknown**. **It does not.** It publishes

    ["COMBO", {"multiselect": false, "options": [
        "ltx-2-spatial-upscaler-x2-1.0.safetensors",
        "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"]}]

which is perfectly enumerable. It reads `available=True` on cerberus with the
real filename.

**Chasing that premise found a live defect**, since fixed: `models.installed()`
read `spec[0]` only, so every loader using the newer shape returned `None`
meaning "not enumerable" — **7 files visible on a box that has 37**. 433 fields
on cerberus use that shape, including `AudioEncoderLoader`, which is in
`LOADER_FIELD` and had been reading as unknown.

- `T5-8` Availability for the upscaler reads `True`/`False` from the enum, never
  `None`, on any box that answers `/object_info`. *Mutation: parse only
  `spec[0]` again → it reads unknown and this fails.*

## 5. Per-model ceilings live here, not in the storyboard

TRD-2 `T2-12` owns the criterion that a ceiling is a measured constant with its
measurement beside it. The **values** are renderer facts and belong here.

- **LTX: 15 s**, a **cost** ceiling and not a capability one. 505 frames /
  30.004 s and 1009 / 59.949 s both render on a 24 GB card; cost is superlinear,
  3.0 s of compute per finished second at 15 s against 12.4 s at 30 s.
- **s2v: 4.8125 s, provisional and labelled so.** `LEN = 77` is a **choice**,
  not a node limit — the node accepts `min: 1` and the comment claims only a
  floor. Whether WAN S2V stays coherent past its ~5 s training segment is
  **unmeasured**.

- `T5-9` Each ceiling states whether it was measured or chosen. **A ceiling
  presented as measured when it was chosen fails**, which is the whole of
  `T2-12` applied to the two numbers that exist.
- `T5-10` The legal-length rule is shared: `EmptyLTXVLatentVideo.length` is
  `step: 8`, `WanSoundImageToVideo.length` is `step: 4`, and every `8n+1` is
  also `4(2n)+1` — so **frames ≡ 1 (mod 8) serves both**, one rule and no
  per-model fork. Verified against cerberus; both accept `max: 16384`.

## 5a. LTX first, then the decoded s2v hop (D6, D7, D8)

Every scene renders LTX 2.5 first from the scene ref + location plate
(if any). Lip-sync is a second, **decoded** hop on marked scenes only.
The latent forbid in §1 **stands**: LTX VAE ≠ `wan_2.1_vae`. The hop
is pixels, which is why it is allowed.

- `T5-11` **Every scene's first clip graph is `ltx25`.** `needs_lip_sync`
  does not skip LTX. Unmarked scenes are LTX only. *Mutation:
  `video_model=s2v` or `needs_lip_sync=true` as the first hop → red.*
  (`test_t5_11_ltx_always_first.py`)
- `T5-12` **D7 hop graph.** On `needs_lip_sync` scenes, after the LTX
  take lands:
  - `ref_image` = the accepted scene still (her)
  - `control_video` = the LTX take, loaded as IMAGE frames
    (`LoadVideosFromFolder` — not `LoadVideo`, not an LTX latent)
  - windowed to the s2v ceiling (~4.8125 s, `T5-9` chosen)
  - `audio` = that clip's trim window
  - deliverable is the s2v clip
  - the LTX take stays listed as predecessor (`T6-A5`)
  *Mutation: `control_video` is an LTX latent or `LoadVideo` → red.
  Mutation: hop overwrites the LTX file → red. Mutation: `ref_image`
  is the album front, not the scene still → red.*
  (`test_t5_12_d7_hop.py`)
- `T5-13` **`skip_first_frames` / trim so each s2v window reads the
  matching slice of the LTX take, not always frame 0.** Window 2 of a
  15 s LTX take does not start at frame 0. *Mutation: every window
  loads the LTX file from index 0 → red.* (`test_t5_13_s2v_window.py`)
- `T5-14` **T5-A refine stays on the LTX take.** It is not a third LTX
  job on s2v frames. It is not the WAN i2v-low refiner. *Mutation:
  `--refine` attaches to the s2v successor → red. Mutation: a third
  LTX graph is submitted on s2v pixels as "correction" → red.*
  (`test_t5_14_refine_on_ltx_take.py`)
- `T5-15` **No LTX latent into WAN.** A graph that wires an LTX VAE
  latent into a WAN node is refused. Stands as the explicit
  not-building half of §1. *Mutation: hand off node 21/22 samples to
  `wan22_i2v_low` → red.* (`test_t5_15_no_latent_handoff.py`)

D7's picture look is `T3-37` and is **NOT MEASURED** until a pinned
same-scene GPU pair exists. Fallback: s2v-from-still (no
`control_video`), recorded as a finding, not a silent drop.

## 6. Explicitly not building

- **No WAN refiner on LTX output.** §1 / `T5-15`.
- **No LTX latent into WAN.** `T5-15`.
- **No third LTX "correction" pass on s2v frames.** `T5-14`.
- **No frame handoff from scratch** for chained clips: `LTXVAddGuide` is
  installed and `build_song.attach_ltxv_guide` wires it. Do not invent a
  second mechanism. TRD-2 `T2-10` owns the criterion; this graph is how.
- **No third variant.** A and B are the shapes LTX documents; a bespoke one is a
  new failure surface for no measured gain.

## 7. How every criterion above is to be verified

A measurement that cannot fail is not evidence — use a differential on the
output, then mutate the code and watch it fail, and read what the mutation
actually did. A refusal or a presence is half a criterion. And the baselines
before and after: the suite, `check_integration.py`, `mixer.py`, and
`grep -c "^def test_"` — a deleted test does not fail.

### The positive half of each one-sided criterion

Added 2026-08-13 from the first external review of this document (grok and
chatgpt, independently — `docs/reviews/TRD47-*-2026-08-13.md`).

| criterion | why it is one-sided | its positive half |
|---|---|---|
| `T5-1` refine adds a pass **or raises** | *always* raising satisfies the whole criterion, forever, on the catalogue default | a supported refine path **succeeds and produces a non-identical output** (`T5-2`). The raise branch is the fallback, not the deliverable — see the note below |
| `T5-3` refine runs at denoise < 1.0 | a parameter constraint on a pass that may not exist | the pass **executes** and its output differs (`T5-2`) |
| `T5-4` still a new file, never an overwrite | green if refine never writes anything | the refined artefact **lands at a new path with both reachable** — and this criterion should **cite `T6-A5`, not restate it**, which is the one place this document breaks TRD-6 §0's rule |
| `T5-6` if B does not fit, record it and ship A | B never existing satisfies "recorded as not fitting" | **A exists, is invoked by `--refine`, and changes the output** |
| `T5-8` availability reads `True`/`False`, never `None` | green while the upscaler is never used | end to end: file present → B can load it; file absent → `False` blocks with a named reason, as a `T6-A6` consumer |
| `T5-9` a ceiling states measured or chosen | a documentation property, checkable by reading | the ceiling is **enforced**: an over-long request is refused or split, not merely annotated |
| `T5-10` frames ≡ 1 (mod 8) serves both | a statement about two nodes' declared steps | an illegal length is **refused** and a legal one **renders**, on both LTX and s2v |

**Not one-sided:** `T5-2`, `T5-5`, `T5-7`.

**The `T5-1` note, because it is a product decision hiding in a criterion.**
As written, "adds a second pass **or** raises naming the reason" is satisfiable
forever by raising — on `ltx25`, which is the catalogue default. That is better
than today's silent no-op and it is not the outcome the document wants. Whether
the shipped behaviour on the default model is *raise*, *variant A*, or *hide the
flag* is unstated, and `T5-6` only covers the case where B does not fit.

### One ownership gap this document creates by accident

§6 says **"No frame handoff from scratch"** — meaning *do not reinvent it*,
because `LTXVAddGuide`, `LTXVAddGuideMulti` and `LTXVAddGuidesFromBatch` are
installed and TRD-2 `T2-10` needs exactly that. TRD-2 W1-7 says the same thing
from the other side.

**A reviewer read that sentence as a refusal to build it**, because it sits in a
section headed *"Explicitly not building"* — and an implementer will read it the
same way. **Closed 2026-08-15:** `build_song.attach_ltxv_guide` wires
`LTXVAddGuide` at frame 0 for a chain successor. TRD-2 still owns `T2-10`;
this document owns the node. The sentence stays "do not reinvent", not
"do not build".


---

## Status against the tree, 2026-08-17

#529 clip-graph rows. T5-1…T5-10 stay in the 2026-08-13 ledger below.

| criterion | state | commit | what was measured |
|---|---|---|---|
| `T5-11` LTX always first | **not built** | — | Intended: `test_t5_11_ltx_always_first.py`. Tree: T2-42/43 still let `video_model=s2v` skip LTX |
| `T5-12` decoded s2v hop (`control_video` = LTX frames) | **not built**; **NOT MEASURED** | — | Intended: `test_t5_12_d7_hop.py`. No hop graph. No GPU pair (`T3-37`) |
| `T5-13` `skip_first_frames` matches the LTX slice | **not built** | — | Intended: `test_t5_13_s2v_window.py` |
| `T5-14` T5-A refine on the LTX take, not on s2v | **partial** | `test_clip_length.py` | `_refine_ltx` attaches A on an LTX graph. No s2v successor exists, so "not on s2v" is untested. Labels must not promise a hop the graph omits |
| `T5-15` no LTX latent into WAN | **built** (forbid) | `test_clip_length.py` | Early-return LTX path never reaches the WAN refine block. Keep: do not wire them. Intended positive: a graph that tries the handoff is refused (`test_t5_15_no_latent_handoff.py` **not built**) |
| `T5-1`/`T5-3`/`T5-4` refine on LTX | **built** (graph) | `test_clip_length.py` | `_refine_ltx` attaches a second pass; silent no-op is gone |
| `T5-2` output MAD + sharpness | **built** (decoded pair); GPU pair **NOT MEASURED** | `test_t5_2_refine_mad.py` | Same as 2026-08-13 row |

---

## Status against the tree, 2026-08-13 (pre-#529; kept)

Written by session A, in the shape session B set in TRD-4/TRD-7: a **ledger**,
not folded into the criteria above — *a criterion edited to describe what was
built is no longer a criterion, it is a changelog with a prefix.*

**"built" means a check can go red, not that the code exists.** `T4-10` read as
done all day while `app.ALBUM_FIELDS["body"]` quietly beat it, so a ledger that
repeats that is worse than none. Production is `c01c977`+; `origin/main` is
current.

| criterion | state | commit | what was measured |
|---|---|---|---|
| `T5-8` upscaler availability is `True`/`False`, never `None` | **built** | earlier | `ltx25_latent_upscaler` catalogued, and `models.installed()` taught ComfyUI's newer enum shape — it had been seeing **7 files on a box with 37** |
| `T5-1`/`T5-3`/`T5-4` refine on LTX | **built (graph)** | `test_clip_length.py` | `_refine_ltx` attaches a second pass; silent no-op is gone |
| `T5-2` output MAD + sharpness | **built (decoded pair); GPU pair NOT MEASURED** | `qc.py` + `test_t5_2_refine_mad.py` | `accept_t5_2_gpu_pair` / `check_refine_differential` measure MAD + Laplacian on decoded frames. Identical frames MAD == 0 (FLAG). Missing frames raise. `source=gpu` flips `T5_2_REAL_CLIP_MEASURED` only with populated frames. Default flag stays False — no Comfy same-seed pair has been accepted. Graph-only is T5-1 |
| `T5-5` peak VRAM of the shipped variant | **harness only; peak NOT MEASURED** | this change | `pipeline.sample_vram` / `peak_from_samples` / `t5_5_claim`; `models.refine_peak` sits beside the 23.4/23.9 base figure. Empty samples raise. `origin=measured` with `same_as_base` or no `n_samples` is a quoted 23.4 and goes red (`test_t5_5_refine_peak_vram.py`). Submit records a pre-render reading on `LAST_RENDER_VRAM` (T9-15). A's peak has not been read off the box — live jobs held the card. Mutation: quote 23.4 as measured → red |
| `T5-6` if B does not fit, record it and ship A | **built** | `test_t5_6_refine_variant_b.py` | B does not fit: 23.4/23.9 leaves 0.5 GB; x2 latent + 0.3 GiB upscaler exceeds it. Finding is in `CATALOG['ltx25']['notes']`. `--refine` ships A (`_refine_ltx`, no `LTXVLatentUpsampler`). Mutation: delete the finding while A still ships → red |
| `T5-7` geometry at assembly | **built (assembly)** | `test_t5_7_assembly_geometry.py` | same-aspect mixed sizes honour the largest (1664×960 among 832×480); mixed aspect is refused by name. Variant B is not shipped — `T5-6` recorded that it does not fit; ×2 reaching `CreateVideo` stays unbuilt |
| `T5-9`/`T5-10` ceilings and the legal-length rule | **built** | `test_clip_length.py` | each ceiling is labeled `measured` (LTX 15 s cost) or `chosen` (s2v `LEN=77`). `honour_ceiling` / `workflow` refuse an over-long single clip; `split_to_ceiling` is the split path. Planner `legal_frames` / `clip_seconds(30)` / `n_clips_for` unchanged |
