# TRD-5 · Clip rendering and refine

Status: written 2026-08-13. Owned by no previous document. TRD-2 owns what a
storyboard asks for and TRD-3 owns measuring what came back; the graph that
turns one into the other was specified nowhere.

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
  anything reaches it.
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

## 6. Explicitly not building

- **No WAN refiner on LTX output.** §1.
- **No frame handoff from scratch** for chained clips: `LTXVAddGuide`,
  `LTXVAddGuideMulti` and `LTXVAddGuidesFromBatch` are installed on cerberus and
  inject a guide frame at an index. TRD-2 `T2-10` needs exactly that.
- **No third variant.** A and B are the shapes LTX documents; a bespoke one is a
  new failure surface for no measured gain.

## 7. How every criterion above is to be verified

A measurement that cannot fail is not evidence — use a differential on the
output, then mutate the code and watch it fail, and read what the mutation
actually did. A refusal or a presence is half a criterion. And the baselines
before and after: the suite, `check_integration.py`, `mixer.py`, and
`grep -c "^def test_"` — a deleted test does not fail.
