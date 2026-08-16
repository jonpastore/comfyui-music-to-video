# O00 — Same-pose undress (keeper)

**Status:** WIN. Do not redo.

## Purpose
Turn `looking-back.jpg` into a nude standing/3-4 sheet that is still her.
This is the identity parent, not an FDAU pose.

## Models
- UNET `qwen_image_edit_2511_fp8mixed.safetensors`
- CLIP `qwen_2.5_vl_7b_fp8_scaled` type `qwen_image`
- VAE `qwen_image_vae`
- Lightning **off** (grind). `index_timestep_zero`
- Encode the source photo, denoise **1.0**, CFG 2 / 50 / `dpmpp_2m`+`karras`
- Seed **843167749** (undresses). 4748 clothes the back. 5151 holds plate pose.

## How
image1 = `looking-back.jpg`. VAEEncode that photo. Positive: same pose,
completely nude, source-brown skin, feline muzzle. No empty latent.

## Community / measured
Measured here: pose (not prompt) exposes anatomy; encode+denoise 1.0
undresses. Empty latent invents a face.

## Variation
One seed at a time. Do not add Union on this hop (that is O1+).

## QC
Identity + wardrobe-off. Not the five FDAU pose checks. Keeper:
`anchor5/poses/keepers/lb_undress_s843167749.png` =
cerberus `input/identity_nude.png`.

## Results
See `results/` and `RESULTS.txt`.
