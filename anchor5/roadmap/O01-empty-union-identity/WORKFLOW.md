# O01 — Empty latent + Union + identity_nude

**Status:** done. both-arms map at 0.85 and 1.0 both FAIL extras.

## Purpose
New pose (FDAU / hips-to-cam) while keeping her body from the nude keeper.

## Models
- 2511 grind sampler (CFG 2 / 50 / dpmpp_2m+karras, Lightning off)
- InstantX Union `Qwen-Image-InstantX-ControlNet-Union.safetensors`
- Empty latent **896×1216**
- image1 = `identity_nude.png` (O00 keeper)
- Optional image2 = `looking-back.jpg` for muzzle (that mix is O3)

## How
1. Complete pose or depth map (both arms). Incomplete OpenPose copies
   amputation.
2. ControlNetApplyAdvanced strength **0.80–1.0** (community InstantX:
   0.8–1.0; Perplexity same). We measured 0.55–0.90 on an *encoded*
   parent did nothing — empty latent is the point of O1.
3. `index_timestep_zero`. Seed 749. Skip 129080599 (kneels).

## Community
- InstantX Union = pose/depth/canny only. No genitals.
- Depth-first for rear/all-fours (Perplexity). That is O6.

## Variation
CN 0.80 / 0.90 / 1.0. Map: both-arms vs depth (O6). Seed 749 vs 5151.

## QC
`QC.md` §A. Accept: hips-to-cam + both arms (face may fail → O8).

## Results
`lbpose_s843167749` — rear closest, peach face, missing arm (bad map).

`o1_empty_botharms` (CN 0.85) and `o1_cn100` (CN 1.0): same FAIL
family. Muzzle PASS. Extra plant, two tails, origin not coccyx.
Raising Union strength does not complete the skeleton. **Do not
repeat.** Depth (O6) is the map replacement.
