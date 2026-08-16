# O08 — Crop-and-stitch muzzle onto a rear body

**Status:** done. Crop-edit of the face works. Tail crop-edit does
not. Full-sheet inpaint closed.

## Purpose
Keep hips/arms of a camera-PASS body; replace only the head.

## Models
- 2511 grind, denoise **0.35–0.50** on the head crop
- image2 = `looking-back.jpg`
- ComfyUI-Inpaint-CropAndStitch (cloned on cerberus; **needs Comfy
  restart** — do not restart mid-queue)

## Community
r/comfyui face consistency; civitai 2511 Segment Inpaint; GitHub
Qwen-Image#88. Unmasked pixels stay the parent.

## Variation
Denoise 0.35 / 0.45 / 0.50. `p_face` on cerberus is O8-lite
(encode lbpose, denoise 0.45, CN off).

## QC
Same hips/arms as parent + looking-back muzzle. If parent is pose
FAIL (`lbpose` missing arm), O8 cannot grow the arm.

## Closed (do not repeat)
- Full-sheet `InpaintModelConditioning` on `p_face` at 0.38–0.70
  (`o8_head_*`, `o8raw_*`). Face unchanged. Tail still over the cheek.
- InstantX Inpaint CN on the head at 0.85 and 1.0 (`o8cn_d85`,
  `o8cn_d100`). Same human face; d100 speckled the tail-adjacent
  background. Mask fired; model rebuilt the face from context.

## Judged 2026-08-16
| tag | verdict |
|---|---|
| `o8crop_qc3_d100_crop` | **WIN muzzle donor** — her black cat head, nude, gold hoops. |
| `o8crop_qc3_d100` uncrop | Hard oval on `p_face`. Tail still on cheek. |
| `o8blend_qc3_tight` | Closest plowcam + her muzzle. Tail still up. Not a keeper. |
| `o8crop_lb_d100` | Face changed but makeup-cat + harness leak. |
| `o8crop_lb_d75` / `o8crop_qc3_d70` | Crop as image2 at 0.70–0.75 **keeps the human face**. Closed. |
| `o8crop_tail_qc3_d100` | Denoise 1.0 on the tail crop invented a kneeling second body. Closed. |
| tail Edit 0.55 / Inpaint CN 1.0 | Tail did not move. Closed. |

## Results
See `RESULTS.txt`. No pose PASS. Do not anatomy on these.
