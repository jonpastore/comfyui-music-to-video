# Train LoRAs for Meow P and the catalog

**Do not start this while O1–O13 inference is unfinished.** This is
the how-to. O14 in the option folders is the anatomy *job* only.
Design split: `docs/DDD-4-7-IDENTITY-AND-RENDERING.md` §1a.1.

Identity is her **operator photographs** (`anchor5/looking-back.jpg`,
`standing.jpg`, keepers). A LoRA does not replace `image1`. Train
only what inference cannot do, and only from **her** PASS sheets.

## What to train (four adapters, not one)

The catalog is `configuration × pose × contact × act × finish ×
movement × camera`. That is four training problems.

| adapter | UNET | learns | catalog ids it covers | when |
|---|---|---|---|---|
| **A. Identity** (optional) | Qwen-Image-Edit-2511 | this face/body is `meowp` | all stills | Only if image1 drifts across views |
| **B. Pose-edit** (one per *family*) | 2511 | standing-her → that skeleton + camera | the 31 pose ids, collapsed to 6 families | After you have 8–20 **her** PASSes in that family |
| **C. Anatomy-edit** (O14) | 2511 | draw human-shaped vulva/anus, her pigment, tail above anus | `rear_anatomy`, `vulva_closeup`, `anus_closeup` + finishes that need holes | After SNOFS + labiaplasty v4 fail on a PASS |
| **D. Motion** | **LTX-2.5 or WAN 2.2** | `thrust` / `grind` / `bounce` / `look_back` / `crawl` | the 7 movement ids | After the still exists. Never 2511 |

Do **not** train: configuration (mfm, gangbang), contact (anal vs
vaginal), act (spit_roast), finish (creampie_flow), overlay. Those
are prompt + inpaint + clip on top of A–D.

Do **not** train 111 files. Do **not** dump Reddit bodies in as her.
Do **not** train on pose-FAIL sheets (`p_*` 3/4, `p_idn` standing,
`lbpose` missing arm).

## Box and tool

| | |
|---|---|
| Box | **gamingpc** 5090 (~32 GB). Stop Docker Comfy first (`docker stop comfyui`). Same GPU. |
| Not | cerberus (live grind + studio). Never train mid-render. |
| Stills trainer | [Ostris AI Toolkit](https://github.com/ostris/ai-toolkit) → model id `Qwen-Image-Edit-2511` (HF repo, not a local `.safetensors`) |
| Motion trainer | diffusion-pipe / musubi / Ostris video job on **ltx25 or wan22**, after we have approved clips |
| Dataset root | `~/meowp-lora/` on gamingpc, **not** `ComfyUI/input/` |

2511 on 32 GB is Ostris “Tier A”: qfloat8, low-VRAM, layer offload,
batch 1, grad accum 4, 768 buckets first. ~10 s/it → 2000 steps ≈ 6 h.

## A — Identity LoRA (`meowp`)

**Usually skip.** `image1` already is her. Train this only if later
views drift (human face, wrong skin) even with her photos loaded.

**Targets:** `anchor5/` operator jpgs + `O00` keeper nudes that are
clearly her. No Reddit. No Z-Image donors. No FAIL hops.

**Layout** (edit LoRA, 1 control):

```
~/meowp-lora/identity/
  targets/     the photo or keeper
  control_1/   same file (identity edit: keep her)
  captions/    "meowp, the black anthro cat-woman from the operator photos, keep this body unchanged"
```

Rank **8–16**, 800–1500 steps. Regularization is the same photos
with “keep this body unchanged.” If samples invent a new cat, stop.

**Use:** strength 0.4–0.6 on 2511 *in addition to* image1, never
instead of it. QC §A check 1 and 3.

## B — Pose-edit LoRA (the catalog stills)

Chicken-and-egg: you cannot train `doggy` until inference has
produced **her** in doggy and those sheets **pose-PASS** (`QC.md` §A).
CN / AnyPose / empty+Union first. Then train.

### Six files, not 31

| LoRA filename | catalog pose ids | control | caption stem |
|---|---|---|---|
| `meowp_pose_fdau.safetensors` | `all_fours`, `face_down_ass_up`, `doggy`, `bent_over_lookback`, `pronebone` | standing nude / `identity_nude` | `meowp, {id} {variant}` e.g. `doggy look_back` |
| `meowp_pose_standing.safetensors` | `standing_behind`, `standing_sex`, `wall_pin`, `furniture_edge` | front/standing photo | `meowp, standing_behind` |
| `meowp_pose_supine.safetensors` | `missionary`, `mating_press`, `legs_over_head`, `butterfly`, `legs_spread` | standing or a PASS sibling | `meowp, missionary legs_up` |
| `meowp_pose_ride.safetensors` | `cowgirl`, `reverse_cowgirl`, `squat_ride`, `amazon`, `lotus` | standing | `meowp, reverse_cowgirl look_back` |
| `meowp_pose_side.safetensors` | `spoon`, `side_scissor`, `t_square` | standing | `meowp, spoon` |
| `meowp_pose_fold.safetensors` | `piledriver`, `full_nelson`, `wheelbarrow`, `lift_carry`, `kneel_oral`, `deepthroat`, `facesit`, `sixty_nine`, `hanging_breasts` | last | `meowp, kneel_oral` |

Variants (`elbows_down`, `hands_down`) are **captions**, not files.
`camera` ids (`plowcam`, `rear`) go in the same caption:
`meowp, face_down_ass_up plowcam`.

### Dataset for one family (FDAU example)

Need **8–20** her-PASS sheets in that family (different seeds /
small variant), not 400 Reddit stills.

```
~/meowp-lora/pose_fdau/
  targets/     her pose-PASS FDAU/doggy/look-back sheets
  control_1/   the same stem, but standing her (identity_nude or looking-back)
  captions/    "change pose to face_down_ass_up plowcam, keep meowp identity, both arms planted, tail from the tailbone above the anus"
```

Pair by filename. If control and target are not the same person,
you are training O9.

### Trainer (same for A/B/C)

| knob | value |
|---|---|
| model | `Qwen-Image-Edit-2511` |
| LoRA rank | **16** (8 for identity) |
| quant | qfloat8 + low-VRAM + layer offload |
| opt | AdamW8Bit, batch 1, grad accum 4 |
| steps | 1500–2500, sample every 250 |
| res | 768 first; 1024 if it fits |
| 2511 | `zero_cond_t` / `index_timestep_zero` |
| lr | ~1e-4 |
| cache | text embeddings + latents |

**Use:** image1 = standing her, LoRA 0.6–0.8, caption = catalog id.
Still run QC §A. If the LoRA draws a stranger, the dataset leaked —
delete the adapter.

**Abort samples:** photoreal woman → leaked identity. Holes but new
face → rank/steps too high. Nothing happens → captions were
descriptions, or target == control.

## C — Anatomy-edit LoRA (O14)

Last resort after SNOFS Qwen v1.3 + labiaplasty v4 + Inpaint CN on a
**pose PASS**. Hard gates stay in
`docs/ROADMAP-2026-08-16-POSE-ANATOMY.md` §O14.

```
~/meowp-lora/anatomy/
  targets/     PASS body + correctly drawn cleft (retone’d composite)
  control_1/   the same PASS body, cleft still sealed
  control_2/   optional retone’d donor crop (Z-Image donors after Lab a/b)
  captions/    "draw a human-shaped vulva and anus in the cleft, lighter than the surrounding fur, pigment matching the body, tail origin above the anus. Preserve identity, pose, lighting."
```

How to make an honest target: her PASS pixels + donor/Reddit crop
with Lab **L** from the crop and **a,b** from `looking-back.jpg` +
`standing.jpg`, stitched. Z-Image donors in
`donors-zimage-labiaplasty/results/` are geometry only until retone.
Scribble and hot peach are not targets. 20–40 pairs.

Regularization: unmasked identity photos, caption “keep this body
unchanged.”

**Use:** 0.4 / 0.55 / 0.7 on a pose-PASS sheet. QC §A anatomy 6–9.

## D — Motion LoRA (catalog `movement`)

2511 has no time axis. `thrust`, `grind`, `bounce`, `look_back`,
`crawl`, `insertion`, `swap` are **clips**.

| | |
|---|---|
| Base | `ltx25` first (studio default). `wan22_s2v` if you need wav2vec mouth/beat |
| Targets | Approved clips of **her** in that pose doing that verb |
| Caption | catalog movement id + pose id: `meowp doggy thrust`, `meowp face_down_ass_up look_back` |
| WAN rule | low-noise 2.2 or Wan 2.1 LoRAs only. No high-noise 2.2. No 2511 file on a video UNET |
| LTX rule | do not reuse LTX-2 19B camera LoRAs (measured dead on 2.5) |

Train D only if stock `ltx25` on a pose-PASS still cannot do the
verb. One adapter per verb family (`thrust`/`grind`/`bounce` can
share if captions distinguish).

## Order

```
inference PASSes in a pose family   (this grind)
        │
        ├─ optional A if image1 drifts
        │
        ▼
B pose-edit from those PASSes       (repeat per family)
        │
        ▼
C anatomy only if SNOFS+labia fail
        │
        ▼
clip on ltx25
        │
        ▼
D motion LoRA only if the clip is static
```

FDAU first (current catalog priority). Then standing, ride,
supine. Fold/oral last (DWPose fails those).

## After a run

1. Copy `*.safetensors` to cerberus `~/ComfyUI/models/loras/`.
2. Test one strength. Judge the picture (`QC.md`).
3. Name the file after the table above so `models.py` can later
   grow `family` / `stage` / `when` (`DDD` §1a).
4. Do not make it a studio `role=reference` default.

## Not a training job

| catalog | do this instead |
|---|---|
| `anal` / `vaginal` | contact on a pose PASS + C |
| `spit_roast` / `mfm` | pair/solo first; extras as image2/3 cast |
| `creampie_flow` / `squirt` | C or donor stitch; clip if it must move |
| `plowcam` | caption on B, or Multiple-Angles LoRA |
| `anthro` | she already is |

## Checklist before `git clone ostris/ai-toolkit`

- [ ] At least one pose-PASS sheet exists (for B or C)
- [ ] Dataset is her, filename-paired, captions are catalog ids
- [ ] No Reddit full-body as `targets/`
- [ ] gamingpc Comfy **stopped**
- [ ] One adapter, one family, one job
- [ ] Sample every 250 and abort on leak
