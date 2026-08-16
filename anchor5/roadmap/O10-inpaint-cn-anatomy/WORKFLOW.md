# O10 — InstantX Inpainting CN + crop/stitch cleft

**Status:** blocked. Full roadmap grind finished 2026-08-16 with
**no pose PASS**. File on disk (4.0 GiB). Do not run on `p_face` or
`o6_union_pface_*`.

## Purpose
Draw / replace the cleft after pose PASS. Union cannot emit genitals.

## Models
- `Qwen-Image-InstantX-ControlNet-Inpainting.safetensors`
- Optional Easy-Inpaint LoRA `QwenImageEditInpaint_v1` + black mask
  (`Inpaint the black areas.`)
- CropAndStitch so unmasked pixels stay

## How
Mask the cleft (enlarge small masks — SAM/segment tutorials).
Whole-image descriptive prompt. Not scribble. Not denoise 1.0 Edit
(reseals / hot peach).

## Community
r/comfyui InstantX Inpainting native; 2511 segment inpaint;
identity-sensitive inpaint tutorial: CFG 1 / Euler / ~8 as an A/B
**after** a PASS, not instead of grind 2/50.

## Variation
Inpaint CN vs Easy-Inpaint black-mask. Denoise/strength sweep only
on a PASS body.

## QC
§A must already be PASS. Then §A anatomy 6–9.

## Results
(empty)
