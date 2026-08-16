# O12a — Phr00t Rapid-AIO NSFW v23

**Status:** file on disk (27 GiB). Jobs queued on cerberus
(`o12a_s5151`, `o12a_qc3`, `o12a_idn`).

## Purpose
Same Qwen-Edit *family*, different **sampler**. Fair try if 50-step
cannot rotate.

## Models
- Checkpoint `Qwen-Rapid-AIO-NSFW-v23.safetensors` (Load Checkpoint)
- **Do not** add Lightning LoRA. **Do not** use CFG 2 / 50 / dpmpp_2m
- **8 steps, `euler_ancestral`, `beta`, CFG 1.0**

## Community
Author comments: extra Lightning LoRAs make garbage. v19 consistency /
v23 prompt. NSFW baked in.

## Variation
Parents: qc3 / identity_nude. Seeds 749 / 5151. Encode vs empty as
a later A/B, one at a time.

## QC
Same five pose checks. If PASS, O10 on this stack (Inpaint CN works
on the family).

## Results
(empty until cerberus drains)
