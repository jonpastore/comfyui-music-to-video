# O12b — Flux.2 Klein

**Status:** ran 4B and 9B distilled on gamingpc. 9B gate is open
(jon-ewm accepted the FLUX non-commercial license).

## What we ran
Official Comfy 4-step edit: `flux-2-klein-4b-fp8.safetensors` +
`qwen_3_4b_fp8_mixed` (CLIP type `flux2`) + `flux2-vae`. Euler,
Flux2Scheduler 4, CFG 1, ReferenceLatent of the source.

| tag | parent | verdict |
|---|---|---|
| `o12b_klein_lb` | `looking-back.jpg` | Partial undress. Muzzle and pose held. Boots, gloves, choker left. Not a photoreal stranger. Weaker than O00 2511 undress. |
| `o12b_klein_idn` | `identity_nude.png` | Face drifts human. Nude standing. Drop as identity parent. |
| `o12b_k9_lb` | `looking-back.jpg` | **Better undress than 4B.** Boots gone. Muzzle and standing look-back held. Tiny gloves left. |
| `o12b_k9_idn` | `identity_nude.png` | Muzzle held (unlike 4B). Nude standing. Slimmer. Not plowcam. |

9B stack: `flux-2-klein-9b-fp8` + `qwen_3_8b_fp8mixed` +
`full_encoder_small_decoder`. Same 4-step euler / CFG 1 graph.

## QC
Did not become a random photoreal woman on looking-back. Did start
to humanize the already-nude keeper. **Not a pose tool.** Do not
use as image1 going forward.

## Results
`results/o12b_klein_lb_00001_.png`, `results/o12b_klein_idn_00001_.png`
