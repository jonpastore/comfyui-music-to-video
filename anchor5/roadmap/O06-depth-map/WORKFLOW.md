# O06 — Depth instead of OpenPose

**Status:** done. Real Depth-Anything-V2 maps, not RGB photos.

## Purpose
Rear/all-fours volume. InstantX Union accepts depth.

## Models
- InstantX Union
- DiffSynth depth patch `qwen_image_depth_diffsynth_controlnet.safetensors`
- Depth from Depth-Anything-V2-Small (`depth_pface.png`,
  `depth_farflung.png` in `_refs/`). Generated on gamingpc, not a
  Comfy preprocessor (none installed).

## Closed methods
- Feeding `pose_guide_farflung.jpg` **RGB** as the DiffSynth depth
  image (`o6_depth75/85/90`): two-headed body-horror.
- Farflung **depth** + Union 0.85 (`o6_union_ff_d85`): extra tails /
  extra volume. Do not use the plate's depth.

## What ran
| tag | method | verdict |
|---|---|---|
| `o6_union_pface_d85` | Union + `depth_pface` + empty + identity + looking-back | **Best new identity.** Muzzle PASS, tail aside, both arms. Camera is a 3/4 squat, not plowcam. Glow blob on cleft. Cuff leak. **pose FAIL: camera + lighting.** |
| `o6_union_pface_d95` | same, CN 0.95 | Same picture. Strength did nothing. |
| `o6_ds_pface_d85` | DiffSynth depth patch + `depth_pface` | Same family, worse hair/tail. |
| `o6_enc_d50` | encode `o6_union_pface_d85` + depth, denoise 0.50 | Parent wins. No plowcam. |
| `o6_enc_d70` | denoise 0.70 | Same as parent. Depth did not pull plowcam. Closed. |

## QC
`o6_union_pface_d85`: pose FAIL: camera (not hips-to-cam plowcam),
glow on cleft, cuff. Do not anatomy.

## Do not repeat
RGB-as-depth. Farflung depth. Union 0.95 after 0.85 already judged.
