# Measured — pose QC then anatomy (2026-08-16)

Judge the pictures. This file is the operator grind plan, not a studio
graph. `make_anchor.py` stays one Qwen-Edit graph. Do not add ControlNet
to the product builder.

Full win/fail ledger, 12 options, do-not list, and the settings matrix:
`docs/ROADMAP-2026-08-16-POSE-ANATOMY.md`.

Adult / explicit is in-scope.

## Locked (do not re-argue)

- Identity = `anchor5/` operator photos (`looking-back.jpg`, `standing.jpg`).
  Not the jet-black UI pair.
- Pose, not prompt, exposes anatomy. A standing figure cannot show it.
- Photoreal Reddit is never `image2` / never a person-plate.
- `T3-33.b`: pose QC **before** anatomy QC. Eye, not a VLM gate.
- Working 2511 still: CFG 2.0 / 50 / `dpmpp_2m`+`karras`, LoRA off,
  `index_timestep_zero`. Lightning LoRA stays off.
- One variable per test.

## Pose QC (must all PASS)

1. Feline muzzle matching `looking-back.jpg` (no human skin patch).
2. Both arms complete, both hands planted when the pose asks for it.
3. Source-brown skin from `looking-back.jpg` + `standing.jpg`.
4. Asked camera (FDAU / hips-to-camera look-back).
5. Tail originates at the coccyx **above** the anus, not on the cleft.

Anatomy QC (only after pose PASS): human-shaped vulva/anus; pigment from
those two photos; cleft lit; no panties; no photoreal identity leak.

## What we measured on disk

| Sheet | Verdict | Why |
|---|---|---|
| `lbpose_s749` | FAIL | Rear camera closest. Human face patch. Missing arm (pose map missing it). |
| `qc2_s749` | FAIL | Muzzle PASS. Third hand. Side crawl. |
| `qc2_s129080599` | FAIL | Muzzle+arms+tail PASS. Kneel, 3/4, gold blotch. |
| `qc3_s749` | FAIL | Best muzzle. Far arm gone. 3/4 crouch. |
| `qc3_s129080599` | FAIL | Arms PASS. Kneel again. Gold blotch. Seed 129080599 kneels. |
| `g1_s749` | FAIL | Encoded `lbpose` at denoise 0.70. Kept rear camera **and** the human face patch / missing arm. |
| `g1_s129080599` | FAIL | Same parent defects. Encoding a FAIL sheet at 0.70 does not replace the face. |
| `o8crop_qc3_d100_crop` | muzzle donor | Crop-edit of `p_face` with qc3 as the only ref. Her black cat head. |
| `o8blend_qc3_tight` | FAIL | Closest plowcam + her muzzle. Tail still up the cheek. |
| `o6_union_pface_d85` | FAIL | Real Depth-Anything of `p_face` + Union. Muzzle + tail aside + both arms. Camera is 3/4 squat, glow on cleft. Best new identity, not plowcam. |
| `o13_lt_map` / `o13_lt_fdau` | FAIL | AnyPose + Lightning 4-step: same standing lean / human face as 50-step. |

Empty latent + looking-back as image1 keeps the muzzle and steals the
rear camera. Empty latent + identity_nude as image1 keeps the rear
camera and loses the muzzle. Seed 129080599 kneels.

## What Reddit / Civitai / HF said (2026-08-16)

Sources: 18 threads (r/comfyui, r/StableDiffusion, r/unstable_diffusion,
r/sdnsfw), [Factory 2511](https://civitai.com/models/2264596),
[Phr00t Rapid-AIO](https://huggingface.co/Phr00t/Qwen-Image-Edit-Rapid-AIO),
[InstantX Inpainting CN](https://huggingface.co/InstantX/Qwen-Image-ControlNet-Inpainting).

- No Comfy NSFW *workshop* on Reddit. Dumps: r/unstable_diffusion,
  r/sdnsfw, r/AIpornhub. Tech: r/comfyui (SFW images), **r/DegenDiffusion**
  (~5.6k, process-first). Discords: Unstable Diffusion, Furry Diffusion,
  The Bulge.
- Pose is ControlNet, not prompt. VAE-encoding a photoreal pose plate
  leaks the person. Depth leaks less than that.
- Empty latent is why Qwen Edit invents a new face. Encode the identity
  / keeper still and drop denoise, or crop-and-stitch the face.
- Turn CN down → more her, less pose. DiffSynth Union LoRA (on cerberus
  as `qwen_image_union_diffsynth_lora.safetensors`) strengthens CN.
- Factory Case 4: image1 = character, image2 = HD pose photo, CN = DW
  **or Depth**.
- Vanilla 2511 does nudity poorly. It is uncensored, not trained. Needs
  **SNOFS** LoRA or Phr00t Rapid-AIO NSFW (v19 consistency / v23 prompt).
  Phr00t bakes Lightning (4–8 step) — a different stack.
- InstantX **Union** = pose/depth/canny. InstantX **Inpainting** = mask
  replace (not on cerberus). Edit knows what is under the region;
  Inpainting CN does not. Scribble + Edit 0.50/0.75 is why we got a drawing.
- Keep unmasked pixels with crop → edit → stitch
  ([2511 Segment Inpaint](https://civitai.com/models/2257259),
  ComfyUI-Inpaint-CropAndStitch).

Named anatomy refs (never image2): `anchor5/reddit-samples/named/`
farflungfreesquid, `gr8eOKMH4M` (trim panties), `nBo9BtPloK`.

Archiver topics: `rear_anatomy` (r/rearpussy), `vulva_closeup`
(r/GodPussyv2), `anus_closeup` (r/GodAsshole).
`python3 ~/.config/meowp/reddit_sample_pass.py --topics anatomy`

## Grind (one variable each)

Cerberus Comfy `:8188`. Prefix `cleanrun/gN_`. QC before the next hop.

| id | Variable | Graph | Accept |
|---|---|---|---|
| **G1** | No empty latent | `VAEEncode(lbpose_s749)` denoise 0.70. image1=that body, image2=`looking-back.jpg`. CN off. Seeds 749 + 129080599. | Rear camera stays. Muzzle becomes looking-back. Both arms. |
| **G2** | Depth not OpenPose | Empty latent (control is the variable). image1=`identity_nude`, image2=`looking-back`. InstantX Union on a **depth** map from a two-arm wide still. CN 0.85. Seed 749 only. | Both arms from depth. Hips-to-camera. |
| **G3** | DiffSynth Union LoRA | Winner of G1/G2 + `qwen_image_union_diffsynth_lora` at 0.6. | Pose holds harder without a new face. |
| **G4** | Anatomy (blocked) | InstantX Inpainting CN + crop/stitch on the cleft. Optional SNOFS low. Descriptive whole-image prompt. | Only if a G-sheet is pose PASS. |

Interim `p_*` (encode `qc3_s749`, denoise 0.75, seed 749) judged
2026-08-16 by eye. `p_base`, `p_cn55`, `p_cn90`, `p_both`, `p_ds`
are **nearly the same 3/4 crouch**. Muzzle PASS. Hips-to-cam FAIL.
Far arm hidden. Encode-at-0.75 kept the parent; Union 0.55–0.90,
both-arms map, and DiffSynth 0.6 did **not** rotate to plowcam.
`p_idn` (identity_nude parent) stayed **standing**; face more human;
tail covers. Parent pose wins at 0.75. Do not run O10 on these.
`p_s5151` same 3/4 as `p_base` (seed did nothing).
`p_face` (encode `lbpose`, denoise 0.45): **best rear camera so far**
(plowcam, feet toward lens). Muzzle FAIL (human face, glow eye). Tail
up across the face. Not pose PASS — O8 parent, not an anatomy parent.

O12a Phr00t: `o12a_qc3` same 3/4 + hot-glow cleft. `o12a_idn` /
`o12a_s5151` kneel, two-tail, pale feet, glow. Sampler did not
rotate; it added glow. Do not more Phr00t on identity_nude.

gamingpc O13 AnyPose + farflung image2: **identity leak** (human
face, sealed cleft, warped foot). Drop photoreal image2. O13 only
if the guide is a skeleton/mannequin, not a person.
`angles_qc3`: same 3/4. Multiple-Angles at denoise 0.70 did nothing.

Both queues idle 2026-08-16 ~02:05.

Sheets synced to `anchor5/roadmap/O05-encode-qc3-union/results/` and
`O07-diffsynth-union/results/`.

gamingpc 2026-08-16 (idle 5090, docker `~/comfy-backend`, :8188). Z-Image
Turbo + labiaplasty v3 donor t2i (`donor/rear_s101`…`s404`): **draws
human-shaped vulva from behind**. Pale photoreal plate flesh — retone
Lab a/b from looking-back+standing before any stitch. **Never image2.
Never onto a pose FAIL.** 2511 grind LoRAs copied; InstantX CNs in
flight. O1 empty+both-arms landed (`anchor5/roadmap/O01-empty-union-identity/results/o1_empty_botharms_00001_.png`):
muzzle PASS, camera closer than `p_*`, **FAIL** extra limb + two tails
+ sealed cleft. O13 AnyPose + Multiple-Angles still in the gamingpc
queue. Not a duplicate of cerberus `p_*`.

Cerberus now: Union CN yes. DiffSynth LoRA yes. InstantX Inpainting CN
on disk. 2511-Edit LoRAs on disk (SNOFS Qwen v1.3, labiaplasty v4,
all-inclusive v2, Easy Inpaint, Multiple-Angles, versatile poses).
Catalog: `docs/ROADMAP-2026-08-16-POSE-ANATOMY.md` §Civitai. Depth
preprocessor not installed — G2 downloads a depth map or waits.

Skip seed 129080599 after G1 if it kneels again.

## Anatomy stills (after PASS)

Retone Lab L from the Reddit crop, a/b from `looking-back.jpg`+`standing.jpg`.
Prefer `nBo9BtPloK` (no panties) or farflung poster. Trim `gr8eOKMH4M`.

## Not this grind

- Pony / Illustrious as identity.
- Phr00t AIO (Lightning baked) unless G4 SNOFS fails.
- Photoreal as image2.
- Deploy.
- Scribble inpaint.
- **Training a 2511 LoRA.** Last resort only, on **gamingpc**, after
  O1–O13 fail. Plan: `docs/ROADMAP-2026-08-16-POSE-ANATOMY.md` §O14.
  Do not occupy cerberus. Do not train Reddit bodies as her.

## Where the failed hops went

Moved, not deleted:

- local: `deprecated/2026-08-16-pose-grind/` (`MANIFEST.md`)
- cerberus: `~/ComfyUI/deprecated/2026-08-16-pose-grind/`

Keeper still: `anchor5/poses/keepers/lb_undress_s843167749.png` and
cerberus `input/identity_nude.png`.
