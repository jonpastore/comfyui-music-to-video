# Roadmap — pose then anatomy (2026-08-16)

Companion to `docs/MEASURED-2026-08-16-POSE-ANATOMY.md`.
Gates: `T3-33.b`, `T4-20`. Judge the picture. Anatomy is illegal until pose PASS.

**Operator runbook (per-option workflow, synced sheets, catalog →
models):** `anchor5/roadmap/README.md`. QC: `anchor5/roadmap/QC.md`.
Catalog: `anchor5/roadmap/CATALOG-MODELS.md`.

**Grind complete 2026-08-16** (cerberus + gamingpc). Operator ledger:
`anchor5/roadmap/README.md` + `AUDIT.md`. No pose PASS. Anatomy
(O10–O11c) not run. Klein not fetched. O14 not started.

Closest: `o8blend_qc3_tight` (plowcam + her muzzle, tail up) and
`o6_union_pface_d85` (muzzle + tail aside + both arms, 3/4 squat).

**Short answers**

- Wins and fails **were** written (MEASURED table + `qc-pose-*.json` in
  deprecated). This file is the full ledger + a plan per research option.
- **13 inference options** (O1–O13) plus **O14 last-resort training**.
  Runnable 2511 options are **done**. **4** are improper or a different
  product. **O14 is written and parked** — do not start it.
- Both boxes were used: cerberus CropAndStitch / O8, gamingpc depth +
  O13 Lightning + O1 CN 1.0.

---

## Wins (keep)

| Win | Evidence | Why it matters |
|---|---|---|
| Same-pose undress from `looking-back.jpg` seed 749 | `anchor5/poses/keepers/lb_undress_s843167749.png` = cerberus `input/identity_nude.png` | Identity + source-brown nude. Parent for later hops. |
| Source skin lock | Every `anchor5/` hop after the UI-pair redo | Jet-black UI pair is the wrong person. |
| Rear camera can land | `lbpose_s749` | InstantX + empty latent *can* put hips to camera. |
| Muzzle can land | `qc3_s749` | looking-back as a ref keeps the cat face. |
| Both arms + tail origin can land | `qc2_s129080599`, `qc3_s129080599` | Arms and coccyx-tail are solvable. That seed kneels. |
| Pose QC / anatomy QC as two gates | `T3-33.b`, `T4-20`, qc json | Stops us poisoning a FAIL with anatomy. |
| Anatomy *samples* on disk | `anchor5/reddit-samples/named/` + archiver topics | Ready after a PASS. Never image2. |
| Research split Union vs Inpaint vs Edit | 18 threads + HF cards | Scribble + Edit 0.50 was the wrong tool. |

## Fails (do not promote)

| Sheet | Face | Arms | Skin | Hips-to-cam | Tail above anus | Why |
|---|---|---|---|---|---|---|
| `lbpose_s749` | FAIL peach patch | FAIL missing | PASS | closest | FAIL on cleft | Incomplete OpenPose (`1v1u8fd`). Empty latent. |
| `lbpose_s886` | FAIL | — | — | FAIL kneel | — | Wrong pose family. |
| `qc2_s749` | PASS | FAIL third hand | PASS | FAIL side | PASS | image1=looking-back (standing 3/4) stole camera. |
| `qc2_s129080599` | PASS | PASS | PASS | FAIL kneel | PASS | Seed kneels. Gold blotch. |
| `qc3_s749` | **best** | FAIL missing | PASS | FAIL 3/4 crouch | FAIL hip tail | image2=looking-back + CN 0.85 still lost rear cam. |
| `qc3_s129080599` | PASS-ish | PASS | PASS | FAIL kneel | PASS | Seed habit. Gold blotch. |
| `g1_s749` / `g1_s129080599` | FAIL | FAIL | PASS | rear kept | FAIL | Encoded a FAIL parent. Denoise 0.70 copies the defect. |
| scribble inpaint 0.50/0.75 | — | — | — | — | — | Outline remains. User: looks stupid. |
| inpaint denoise 1.0 | — | — | reseal / hot peach | — | — | Edit at 1.0 on a mask reseals the cleft. |

Sheets live in `deprecated/2026-08-16-pose-grind/` (local + cerberus).

---

## Improper — do not run again

Technical reasons, not taste.

| Method | Why it is wrong |
|---|---|
| Photoreal Reddit / plate as `image2` or VAE-encoded latent | Plate wins pose **and identity**. InstantX two-ref photoreal leaked a stranger. Banned in AGENTS.md / `T4-20`. |
| Empty latent + standing `looking-back` as image1, no rear CN | Image1 composition is 3/4 standing. Camera will not become plowcam. |
| InstantX Union on `1v1u8fd` OpenPose | Skeleton is missing the far arm. CN copies the amputation (`lbpose`, G1). |
| Encode a pose-FAIL parent (`lbpose`, G1) | Denoise 0.70 keeps peach face + missing arm. Parent must already pass the checks you are not changing. |
| Scribble + 2511 inpaint 0.50/0.75 | Edit treats the scribble as the drawing. Not anatomy. |
| 2511 inpaint denoise 1.0 on the cleft | Reseals / hot peach. Measured. |
| InstantX Union as an anatomy tool | Union is pose/depth/canny. It does not emit genitals. |
| Vanilla 2511 “just prompt the vulva” | Uncensored ≠ trained. Community + our sheets: crease only. |
| Lightning / Phr00t 4–8 step as the *identity* stack | Different sampler regime. Fights CFG 2 / 50 / LoRA off. Last resort only. |
| Pony / Illustrious as image1 | Draws holes. Wrong person. Identity lives in her photos. |
| Seed 129080599 when you need all-fours | Kneels twice (qc2, qc3). Do not spend another 8 min proving it. |
| Anatomy on a pose FAIL | `T3-33.b`. Poisons the next hop (G1). |
| Deploy mid-render / two writers on `studio/*.py` | Fleet rule. |
| Hand-gluing one OpenPose limb onto a bad map and calling it complete | We did this. InstantX still saw a hip-arm / weak plant. |

---

## 12 options

Runnable on cerberus 2511 unless marked **blocked** or **improper**.

### O1 — Empty latent + Union + `identity_nude` only (no face ref)

**Status:** run (`lbpose`). Rear cam closest. Face/arm FAIL.

**Plan:** Do not repeat with `1v1u8fd`. Only if we have a **complete** two-arm
pose/depth map. Then: empty 896×1216, image1=`identity_nude`, Union 0.85,
seed 749. Accept: hips-to-cam + both arms (face may fail → O8).

### O2 — Empty latent + Union + looking-back as image1

**Status:** run (`qc2`). Muzzle PASS. Camera FAIL.

**Plan:** Do not repeat. Standing image1 owns the camera. Improper for FDAU.

### O3 — Empty latent + Union + identity_nude image1 + looking-back image2

**Status:** run (`qc3`). Best muzzle. Camera still 3/4.

**Plan:** Repeat **only** with a complete pose/depth map and a CN sweep
(0.55 / 0.75 / 0.95) + seed 749 and 5151. That is a *settings* question,
not a new method.

### O4 — VAEEncode a FAIL pose parent

**Status:** run (G1). **Improper.** Copies the FAIL.

**Plan:** Never. Encode only a sheet that already PASSes the axes you
are not editing.

### O5 — VAEEncode a good-face parent (`qc3_s749`) + Union

**Status:** not run. Highest-value untested method.

**Plan:** Parent pixels already have the muzzle and (on 129080599) both
arms. CN pulls hips-to-cam. Denoise 0.55–0.80 so the face can stay.
Settings matrix below (`panel/o5_*`).

### O6 — Depth map instead of OpenPose

**Status:** not run. DWPose empty on the pike; `1v1u8fd` incomplete.

**Plan:** Depth from `farflungfreesquid_poster.jpg` or a wide two-arm
still. Union accepts depth. Never encode the photoreal still. One hop
at CN 0.85, image1=`identity_nude`, image2=looking-back, seed 749.

### O7 — DiffSynth Union LoRA (on disk)

**Status:** not run.

**Plan:** Same graph as O3 or O5 + `qwen_image_union_diffsynth_lora` 0.6.
Strengthens CN so we can keep image2 for the face without losing pose.

### O8 — Crop-and-stitch muzzle onto a rear body

**Status:** not run. Community #1 face fix.

**Plan:** Rear body = `lbpose_s749` (camera PASS, face FAIL). Mask the
head. Edit only that crop with image2=`looking-back.jpg`, denoise
0.35–0.50. Stitch. Unmasked pixels stay the original. Accept: same
hips/arms as parent + looking-back muzzle.

### O9 — Factory Case 4 (character + HD pose *photo* as image2)

**Status:** **improper** as a person-plate. Depth/DW extracted from that
photo is O6, and is allowed.

**Plan:** Do not load farflung / nBo9BtPloK as image2.

### O10 — InstantX Inpainting CN + crop/stitch cleft

**Status:** **blocked** on pose PASS. Inpaint CN is on disk.

**Plan:** After PASS: mask cleft, descriptive
whole-image prompt, stitch. Not Union. Not scribble.

### O11 — SNOFS LoRA on vanilla 2511

**Status:** **blocked** on pose PASS (or a dedicated anatomy-capability
A/B on a PASS body). File is on cerberus
`~/ComfyUI/models/loras/Qwen_Snofs_1_3.safetensors` (585.4 MiB,
version **2474488**, verified 2026-08-16). Do not restart Comfy mid-panel
to pick it up — Refresh the LoRA list after the queue drains.

**Plan:** Low strength (0.4–0.7) on O10. If still undrawn, then O12.

### O13 — AnyPose LoRAs (ControlNet-free pose copy) **added**

**Status:** missed in the first pass. HF
[lilylilith/AnyPose](https://huggingface.co/lilylilith/AnyPose).
Two files: `2511-AnyPose-base-000006250` + helper, strength 0.7 each.
Prompt: copy pose/FOV of image 2, keep style of image 1.
Author used Lightning 4-step; we can try on the 50-step stack first
(do not bake Lightning unless 50-step fails).

**Risk:** image 2 is still a photoreal still in the encoder. Prompt must
forbid copying the person/skin. If identity leaks, this is O9 in a
costume. Fail → drop.

**Plan:** image1=`identity_nude` or `qc3_s749`, image2=farflung
*poster* as pose guide only, AnyPose 0.7/0.7, seed 749, empty or
encoded latent. No Union. Grey-studio keep prompt.

### O12 — three products (only 12a is a fair try on her photos)

**Why I said “wrong stack”:** O12 was a leftover bucket. It is not one
method. Mixing *their* weights with *our* CFG 2 / 50 / `dpmpp_2m` is
the actual mistake.

| id | What | Why it is a different stack | Try? |
|---|---|---|---|
| **O12a** | Phr00t Rapid-AIO **NSFW v23** | Same Qwen-Edit family. Lightning + NSFW LoRAs **baked in**. Author: 4–8 steps, `euler_ancestral` / `beta`, CFG ~1. Comments: extra Lightning LoRAs make garbage. | **Yes.** Same photos. Change the whole sampler regime, one variable. |
| **O12b** | Klein 9B | Different model. Good at undress, bad at pose-from-prompt. | Later if 12a pose fails. |
| **O12c** | Pony / Illustrious | Draws holes. Identity becomes a Pony person. | **No** as image1. Anatomy donor only after a pose PASS, never her plate. |

**O12a plan (this is “try that stack”):**

- Checkpoint: `Qwen-Rapid-AIO-NSFW-v23.safetensors` (Load Checkpoint).
- Do **not** add Lightning LoRA. Do **not** use 50 steps / CFG 2 /
  `dpmpp_2m`.
- 8 steps, `euler_ancestral`, `beta`, CFG 1.0.
- image1 = `identity_nude` or `qc3_s749`, image2 = `looking-back.jpg`.
- Seeds 749 and 5151. Encode parent (no empty latent) unless 12a-empty
  is the A/B.
- Accept: same five pose checks. If muzzle+pose PASS, then O10 on this
  stack (Inpaint CN is on disk).

### O14 — Last resort: train a 2511 edit LoRA on gamingpc

**Status:** written 2026-08-16. **Do not start.** Inference O1–O13 is
not exhausted. This is the similar process to “fork / finetune with
Reddit data,” and it is the *wrong* next action.

Factory split (identity / pose-family / anatomy / motion) is DDD-4-7
§1a.1. How-to: `anchor5/roadmap/TRAIN.md`. O14 is the **anatomy**
row only. Pose LoRAs need her PASS sheets first. Motion LoRAs are
LTX/WAN, not 2511.

**Why last resort.** Identity already lives in `anchor5/` as `image1`.
What 2511 lacks is *drawing* anatomy, not knowing who she is. A pose
LoRA is chicken-and-egg (you need her already in the pose as a target).
A full 20B fork is overkill. Training costs a day of dataset work plus
hours of 5090 time, and a bad dataset permanently poisons the adapter.

**Why gamingpc, not cerberus.** Cerberus is the live grind + studio
worker. Do not occupy it with a multi-hour trainer (never deploy /
never train mid-render). gamingpc has the other 5090 (~32 GiB,
TRD-9). Ostris rates 24–32 GB as “Tier A: possible with low-VRAM.”
Jarvis #535 (stack parity) is the same box — copy the *final* cerberus
inference stack first, then stop Comfy on that GPU before training.

**What we would train (one job, one LoRA).** An *edit* LoRA on
**Qwen-Image-Edit-2511** via [Ostris AI Toolkit](https://github.com/ostris/ai-toolkit).
It learns: given her sheet + an instruction, draw a human-shaped vulva
and anus in the cleft with pigment from `looking-back.jpg` +
`standing.jpg`. Trigger / caption is an instruction, not a tag dump.

**What we would not train.**

| Temptation | Why not |
|---|---|
| Photoreal Reddit full bodies as Meow P | The adapter becomes the stranger. Same leak as O9. |
| Pose LoRA first | Targets must already be her in the asked pose. We do not have those. |
| Identity LoRA | `image1` already is her. Extra identity rank fights the photos. |
| Full 20B finetune | Days, not hours. Same dataset problem, bigger blast radius. |
| Pony / IL as the train base | Draws holes, wrong person. |
| Train on a pose-FAIL parent | Same as G1. The LoRA copies the FAIL. |
| Train on cerberus mid-panel | Occupies the only grind GPU. |

**Hard gates before anyone installs the trainer.** All of these, in
order. Skip one and O14 is still not allowed.

1. `p_*` panel judged by eye (O5 / O7 / O8-lite).
2. O6 depth tried (complete two-arm map, never a photoreal encode).
3. O13 AnyPose tried; drop on identity leak.
4. Official SNOFS **Qwen v1.3** (`Qwen_Snofs_1_3.safetensors`,
   modelVersion **2474488**) tried at 0.4–0.7 on a pose PASS (O11).
   Not Krea 2 v1.3D. Not the `?tag=action` browse grid.
5. O10 InstantX Inpainting CN + crop/stitch tried on a pose PASS.
6. O12a Phr00t Rapid-AIO NSFW v23 tried on *its* sampler (8 /
   `euler_ancestral` / `beta` / CFG 1).
7. Still undrawn or wrong pigment after those.
8. At least one **pose PASS** parent exists (`T3-33.b`). Anatomy
   targets are illegal until then.
9. Dataset of *retone’d composites* is ready — not a folder of raw
   Reddit stills.

**Dataset (this is the real work).** Edit-LoRA triplets, filename-paired.

```
targets/     after: her body + correctly drawn cleft
control_1/   before: the same pose-PASS sheet, cleft still sealed
control_2/   optional donor crop (retone’d, never as her face)
captions/    instruction, same stem
```

How to make an honest `targets/` without already having the capability:
her PASS body + Reddit anatomy crop with Lab **L** from the crop and
**a,b** from `looking-back.jpg` + `standing.jpg`, stitched. Prefer
`nBo9BtPloK` / farflung poster; trim `gr8eOKMH4M`. The LoRA learns to
do that composite from the instruction.

If we cannot make an honest target, we cannot train. Scribble, hot
peach, and raw photoreal people are not targets.

- 20–40 well-paired crops beat 400 raw stills.
- Regularization: a few unmasked identity photos whose caption is
  “keep this body unchanged” so the adapter does not always punch holes.
- Never put her face in the same crop as a photoreal vulva.

Caption shape (instruction, not a description):

> draw a human-shaped vulva and anus in the cleft, lighter than the
> surrounding fur, pigment matching the body, tail origin above the
> anus. Preserve identity, pose, lighting, and the rest of the sheet.

**Trainer settings (gamingpc, 5090 ~32 GB).**

| knob | value | why |
|---|---|---|
| model | `Qwen-Image-Edit-2511` (HF repo id) | Toolkit does not take a local `.safetensors` path |
| target | LoRA, rank **16** (not 64) | 32 GB + one job. Rank 64 overfits 20–40 pairs |
| quant | qfloat8 + low-VRAM + layer offload | Tier A |
| opt | AdamW8Bit, batch 1, grad accum 4 | VRAM |
| steps | 1500–2500, sample every 250 | Stop early if samples leak |
| res | 768 buckets first; 1024 if it fits | Resolution is the VRAM lever |
| 2511 switch | `zero_cond_t` / `index_timestep_zero` | Same as inference |
| cache | text embeddings + latents | Faster second epoch |
| lr | ~1e-4 | Default edit-LoRA; do not “tune” until samples exist |

Stop ComfyUI on gamingpc first (same GPU). Clone
`ostris/ai-toolkit` to `~/ai-toolkit`. Dataset stays on disk, not in
`ComfyUI/input/`. Wall time: recent 2511 is ~10 s/it
([ostris#683](https://github.com/ostris/ai-toolkit/issues/683)) →
2000 steps ≈ 6 h plus samples. OOM → drop to 768, one control stream.

**After a run.** Copy the adapter to cerberus
`~/ComfyUI/models/loras/`. Test on a pose PASS at strength 0.4 / 0.55 /
0.7. One variable. Judge the picture. Then, and only then, talk
#535 stack copy of this file onto the live graph.

**Abort the run.**

| sample looks like | stop reason |
|---|---|
| photoreal stranger / pale plate flesh | dataset leaked identity |
| holes appear, her face changes | rank / steps too high |
| nothing happens | captions were descriptions, or target == control |
| peach reseal / scribble | we trained on junk targets |

**Not a studio feature.** O14 does not land in `make_anchor.py`. Same
rule as the InstantX grind (`T4-20`).

---

## Settings matrix (this grind)

One method family, corners — not one cheap hop.

Family: **O5** (encode `qc3_s749`) ± Union ± DiffSynth.
Prefix `cleanrun/p_`. Seed **749** unless noted. CFG 2 / 50 / dpmpp_2m+karras.

| id | parent | latent | CN | LoRA | denoise | seed | Asks |
|---|---|---|---|---|---|---|---|
| `p_base` | qc3 | encode | off | off | 0.75 | 749 | Can prompt alone rotate 3/4 → hips-to-cam? |
| `p_cn55` | qc3 | encode | Union wide 0.55 | off | 0.75 | 749 | Weak CN |
| `p_cn90` | qc3 | encode | Union wide 0.90 | off | 0.75 | 749 | Strong CN (may amputate if map incomplete) |
| `p_both` | qc3 | encode | Union both-arms 0.80 | off | 0.75 | 749 | Completed skeleton |
| `p_ds` | qc3 | encode | Union wide 0.80 | DiffSynth 0.6 | 0.75 | 749 | LoRA vs `p_cn90` |
| `p_idn` | identity_nude | encode | Union wide 0.80 | off | 0.75 | 749 | Standing-nude parent vs qc3 |
| `p_s5151` | qc3 | encode | Union wide 0.80 | off | 0.75 | 5151 | New seed, not the kneel seed |
| `p_face` | lbpose | encode | off | off | 0.45 | 749 | O8-lite: keep rear body, pull muzzle (low denoise) |

QC each on the five pose checks. Do not run O10 on any FAIL.

If the wide map amputates at CN 0.90 and both-arms does not, the map
was the defect (method), not “we needed more steps.”

---

## Sources (this research)

Threads fetched 2026-08-16 via old.reddit JSON + Firefox cookies
(`/tmp/meowp-research/*.json`):

| id | sub | title | url |
|---|---|---|---|
| 1pa2wuc | comfyui | Is there a reddit community focused on NSFW generations? | https://www.reddit.com/r/comfyui/comments/1pa2wuc/ |
| 1m89fiv | comfyui | AI NSFW community | https://www.reddit.com/r/comfyui/comments/1m89fiv/ |
| 1n44lq5 | comfyui | How much control do you really have over poses? (NSFW) | https://www.reddit.com/r/comfyui/comments/1n44lq5/ |
| 1qxy10f | comfyui | How do the nsfw image2image workflows actually work? | https://www.reddit.com/r/comfyui/comments/1qxy10f/ |
| 1nehe68 | comfyui | InstantX Inpainting ControlNet natively supported | https://www.reddit.com/r/comfyui/comments/1nehe68/ |
| 1nsp67m | comfyui | Editing using masks with Qwen-Image-Edit-2509 | https://www.reddit.com/r/comfyui/comments/1nsp67m/ |
| 1px2iok | comfyui | Qwen 2511 Edit Segment Inpaint workflow | https://www.reddit.com/r/comfyui/comments/1px2iok/ |
| 1o5gz5k | comfyui | Face consistency with Qwen Image Edit | https://www.reddit.com/r/comfyui/comments/1o5gz5k/ |
| 1mvkavf | comfyui | Stop Qwen Image editor from changing the face | https://www.reddit.com/r/comfyui/comments/1mvkavf/ |
| 1q38hj2 | comfyui | Showcase AIO Uncensored Qwen | https://www.reddit.com/r/comfyui/comments/1q38hj2/ |
| 1pzv43f | comfyui | Best workflows for NSFW in ComfyUI? | https://www.reddit.com/r/comfyui/comments/1pzv43f/ |
| 1l1bkfy | comfyui | Best model for NSFW images | https://www.reddit.com/r/comfyui/comments/1l1bkfy/ |
| 1ida93m | comfyui | NSFW workflows and checkpoints | https://www.reddit.com/r/comfyui/comments/1ida93m/ |
| 1pvco6n | StableDiffusion | 2511 can do NSFW by itself | https://www.reddit.com/r/StableDiffusion/comments/1pvco6n/ |
| 1n1wldy | StableDiffusion | Qwen Edit + InstantX Union + PuLID | https://www.reddit.com/r/StableDiffusion/comments/1n1wldy/ |
| 1uaewi3 | unstable_diffusion | SCAIL 2 undress + r/DegenDiffusion | https://www.reddit.com/r/unstable_diffusion/comments/1uaewi3/ |
| 1vee8t7 | unstable_diffusion | Can I ask local Comfy questions here? | https://www.reddit.com/r/unstable_diffusion/comments/1vee8t7/ |
| 1v1hu9l | sdnsfw | Longer NSFW video + consistent characters | https://www.reddit.com/r/sdnsfw/comments/1v1hu9l/ |

Model cards / workflows:

- InstantX Inpainting: https://huggingface.co/InstantX/Qwen-Image-ControlNet-Inpainting
- Comfy-Org InstantX CNs: https://huggingface.co/Comfy-Org/Qwen-Image-InstantX-ControlNets
- Phr00t Rapid-AIO: https://huggingface.co/Phr00t/Qwen-Image-Edit-Rapid-AIO
- SNOFS model page (not the tag grid): https://civitai.red/models/1972981
  — Qwen v1.3 = `?modelVersionId=2474488` → `Qwen_Snofs_1_3.safetensors`.
  Default download is Krea 2 v1.3D (**wrong** for 2511).
  Browse `models?tag=action` has **no version dropdown**.
  HF license copy: https://huggingface.co/Ashen3/SNOFS
- Ostris AI Toolkit (O14 only): https://github.com/ostris/ai-toolkit
  2511 guide: https://www.runcomfy.com/trainer/ai-toolkit/qwen-image-edit-2511-lora-training
- Factory 2511: https://civitai.com/models/2264596
- Segment inpaint: https://civitai.com/models/2257259
- CropAndStitch: https://github.com/lquesada/ComfyUI-Inpaint-CropAndStitch
- Qwen Edit face issue: https://github.com/QwenLM/Qwen-Image/issues/88
- Edit+inpaint feature request: https://github.com/comfyanonymous/ComfyUI/issues/9575
- NSFW edit LoRA (HF fallback): https://huggingface.co/ScottzillaSystems/qwen-image-edit-plus-nsfw-lora

Communities named, not scraped: r/DegenDiffusion, Unstable Diffusion / Furry Diffusion / The Bulge Discords.

Perplexity (Hermes `f1fb81b5-be3f-495b-9270-0cb4965fd10d`, 2026-08-16)
addendum — extra vs our 12:

- InstantX Union recommended CN scale **0.8–1.0**; separate depth-only vs
  pose-only before combining. Depth-anything for volume/camera; DWPose
  for limbs. Rear/all-fours: **depth first**.
- Official 2511 templates + paintbrush “replace the red area with image 2”
  as a non-scribble regional edit.
- SAM3 / segment-inpaint: only the mask is processed; enlarge the mask
  or small masks fail.
- Identity-sensitive inpaint: **CFG 1 / Euler / ~8 steps** (tutorial),
  not our 2/50 — A/B only after a pose PASS.
- Bypass unused image loaders; they still condition.
- Split: pose lock, then a second local-reference anatomy pass.
- AnyPose (O13) from our own follow-up, not Perplexity.

We already had Union vs Inpaint, SNOFS, Phr00t, crop-stitch. Perplexity
did **not** contradict those. It adds region-first edit settings and
depth-first for FDAU.

## Civitai catalog (2026-08-16)

Civitai is full of mature files. Almost all of them are the **wrong
base**. `base=Qwen` on a card is not enough — that bucket mixes
Qwen-Image t2i, Qwen 2512 t2i, Edit 2509, Edit 2511, and Krea/Klein
siblings. The tag browse (`models?tag=action`) has no version picker.

Rule: one LoRA, official **2511 Edit** version only, after a pose PASS.
Do not stack three NSFW adapters. Do not load Pony / IL / Flux / Krea /
2512 t2i onto `qwen_image_edit_2511_fp8mixed`.

### Load on 2511 Edit (anatomy, after pose PASS)

| file | version | size | trigger | when |
|---|---|---|---|---|
| `Qwen_Snofs_1_3.safetensors` | **2474488** | 585 MiB | sex / pose words (v1.0 list) | O11. On disk. |
| `m99_labiaplasty_pussy_4_qwen-image-edit-2511.safetensors` | **2637922** (v4.0 of [112299](https://civitai.com/models/112299)) | 282 MiB | `adjust her pussy and anus` | **O11b.** Closest to our cleft job. Default download on that page is Krea 2 v8a — wrong. |
| `Qwen_Image_Edit_2511_All_included_v2.safetensors` | **3160956** ([2700552](https://civitai.com/models/2700552)) | 810 MiB | (none listed) | O11c. Author: inpaint/outpaint + pose change. After SNOFS/labiaplasty, not instead of pose CN. |
| `QwenImageEditInpaint_v1.safetensors` | **2182543** ([1928341](https://civitai.com/models/1928341)) | 141 MiB | `Inpaint the black areas.` | O10-alt. Black-mask inpaint. Not scribble-Edit. |

### Load on 2511 Edit (pose helpers, not anatomy)

| file | version | size | trigger | when |
|---|---|---|---|---|
| `Qwen-Image-Edit-2511-Multiple-Angles.safetensors` | **2588352** ([2300308](https://civitai.com/models/2300308)) | ~282 MiB | camera/angle prompts | Camera rotate after a good-face parent. Not a genital tool. |
| `Qwen-Edit-2511-versatile-poses.safetensors` | **2735157** ([2182923](https://civitai.com/models/2182923)) | 225 MiB | `Change your posture` | Prompted pose change. Weaker than InstantX/AnyPose for FDAU. 2509 version is a different file. |

### On disk, do not use for this grind

| file | why |
|---|---|
| `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` | Wrong sampler stack (O12). |
| `Qwen-Image-Edit-Unblur-Upscale_15.safetensors` | SexGod wants this stacked. Photoreal finish. Skip until a PASS and only if SNOFS+labiaplasty fail. |
| `qwen-edit-skin.safetensors` | Skin/detail, not anatomy. |
| `qwen-image-edit-plus-nsfw-lora.safetensors` | 0-byte failed HF stand-in. Ignore. |
| AnyPose pair | O13. Pose copy. Identity-leak risk if image2 is photoreal. |

### Do not download / do not load

| card | why |
|---|---|
| SNOFS **Krea 2 v1.3D** / Klein 9b | Default button. Wrong backbone. |
| Labiaplasty Krea / Klein / ZImage / SDXL | Same page as v4. Default is Krea. |
| SexGod Female Nudes 2511 v2 ([2339965](https://civitai.com/models/2339965), 2.2 GiB) | Real 2511 Edit LoRA, but photoreal nude style + mandatory unblur. Will fight `anchor5/` pigment. Park until SNOFS+labiaplasty fail on a PASS. |
| SEXGOD Couples 2511 | Two-person. Not her. |
| Unchained XXX ([2163063](https://civitai.com/models/2163063)) | **2509** Edit. CFG 4. Wrong family. |
| Qwen_Nsfw_Body ([2020014](https://civitai.com/models/2020014)) | Qwen **t2i** body sliders (`hourglass_figure`, `hairy_pussy`). Not Edit 2511. |
| Qwen **2512** Pussy & Anus / Pussy Realistic ([2289084](https://civitai.com/models/2289084), [2299174](https://civitai.com/models/2299174)) | Trained on **Qwen-Image 2512 t2i**. 2289084 even says trained on Pony stills. Will not map onto Edit 2511. |
| QWEN P0ssy ([1872818](https://civitai.com/models/1872818)) | t2i. |
| Copy Pose ([2380153](https://civitai.com/models/2380153)) | 2509 only. We have AnyPose for 2511. |
| Pose Transfer side-by-side ([1959609](https://civitai.com/models/1959609)) | Left-half pose / right-half person. Photoreal left half = O9 leak. |
| Anime2Real / Reality Transform / Anything to Real | Turns her into a photoreal woman. |
| UnderBoner 2511 | Wrong anatomy. |
| Pony / Illustrious / Flux / SDXL NSFW LoRAs | Draw holes. Wrong person. |

### Why Pony / Flux / Krea are not a second identity stack

They are not “bad NSFW.” They are **different UNETs**. A Pony LoRA will
not bind onto `qwen_image_edit_2511_fp8mixed`. A Krea SNOFS file is
trained on Krea 2, not 2511. Loading the wrong file is a silent no-op
or a shape error — not a better vulva.

| family | what it is | what it does well | what it does to *her* |
|---|---|---|---|
| **Pony / Illustrious** | SDXL-line t2i. Prompt + tags. | Draws human-shaped genitals on demand. | Does not edit `looking-back.jpg`. The output is a Pony catgirl. Identity lock is gone. |
| **Flux.1 Kontext / Flux.2** | Separate DiT. Already on cerberus. | Photoreal edit / gen. | Measured this grind: Kontext resealed / leaked a stranger. Deprecated with the junk hops. |
| **Flux.2 Klein 9B** | Small Flux edit (O12b). | Undress. | Weak at pose-from-prompt. SNOFS has a Klein file; still not 2511. |
| **Krea 2** | New t2i. SNOFS/labiaplasty **default** button. | Photoreal NSFW the authors like *now*. | No operator-photo lock. Not in the studio graph. Not on disk. |

**If every 2511 Edit test fails**, the parked fallbacks are still
**inside the Qwen-Edit family first**: O12a Phr00t Rapid-AIO NSFW v23
(already on disk, its sampler, not ours). Then O12b Klein. Then Pony
as an **anatomy donor crop** composited onto a pose-PASS sheet (O12c)
— never as `image1`, never as a plate. A full Pony/Krea *character*
rebase is a different product: new identity lock, new prompts, new
QC. That is not a weekend A/B.

**Animation does not need them.** Clips are `ltx25` (default) or
`wan22_s2v`. Both take the **approved still** as the first frame /
guide (`T5-*`). LTX and WAN have their own LoRAs (camera, detailer).
A Pony or Krea adapter will not load on those video UNETs. NSFW
*video* LoRAs, if we ever want them, are LTX-2 / WAN 2.2 files, and
only after the still is pose+anatomy PASS.

Do not download a Pony/Krea base onto cerberus mid-grind. If a
fallback box is ever staged, it is **gamingpc**, idle, after #535
copies the *working* 2511 stack.

When-to-use (Qwen vs LTX/WAN vs parked Pony/Krea/Flux) and the later
`models.py` `family` / `stage` / `when` / `not_for` contract:
`docs/DDD-4-7-IDENTITY-AND-RENDERING.md` §1a.

API dump: `/tmp/meowp-research/civitai-qwen-search.json` +
`civitai-qwen-details.json`. Token in `cavitai.env` (`*.env` gitignored).

## After a PASS

O10 (Inpaint CN or Easy-Inpaint LoRA) → O11 SNOFS Qwen v1.3 → **O11b
labiaplasty v4 2511** (`adjust her pussy and anus`) → optional O11c
all-inclusive v2. Retone a/b from looking-back + standing.
Then copy the *working* stack to gamingpc (#535).

**O14 training** stays last resort. It is not #535. It does not start
because a browse page was missing a version dropdown.
