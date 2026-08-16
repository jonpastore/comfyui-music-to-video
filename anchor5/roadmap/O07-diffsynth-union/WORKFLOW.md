# O07 — DiffSynth Union LoRA

**Status:** run (`p_ds`). No camera change vs `p_base`.

## Purpose
Strengthen InstantX so image2 can keep the face without losing pose.

## Models
- Same as O05 + `qwen_image_union_diffsynth_lora.safetensors` **0.6**

## Community
DiffSynth Union LoRA is the official strengthener for Qwen InstantX.

## Variation
0.4 / 0.6 / 0.8 — only after the parent/map actually differs from
`p_ds`. Repeating 0.6 on qc3+0.75 is wasted.

## QC
`p_ds`: muzzle PASS, 3/4 FAIL (same as O05).

## Results
`p_ds_00001_.png`
