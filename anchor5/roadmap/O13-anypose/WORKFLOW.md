# O13 — AnyPose (ControlNet-free pose copy)

**Status:** done / closed. Photoreal, map 50-step, and Lightning
4-step all FAIL (standing lean, human-structured face).

## Purpose
Copy pose/FOV of image 2, keep style of image 1, no OpenPose.

## Models
- `2511-AnyPose-base-000006250` + `2511-AnyPose-helper-00006000`
- Strength **0.7 / 0.7** (author)
- Author: **Lightning 4-step**. We try **50-step grind first**;
  Lightning A/B only if 50-step fails (do not mix).

## Community prompt (HF lilylilith/AnyPose)
> Make the person in image 1 do the exact same pose of the person
> in image 2. Changing the style and background of image 1 is
> undesirable. Pixel-accurate arms/head/legs. Match FOV and angle.
> If background leaks from image 2: “Remove the background of
> image 2, and replace it with the background of image 1.”

We add: do **not** copy the person or skin from image 2.

## Risk
image2 is still encoded. Photoreal guide = O9 leak. Fail → drop.

## Variation
image1 = identity_nude vs qc3. image2 = farflung *poster* (pose
guide). Empty vs encoded latent. 50-step vs Lightning 4 / cfg 1.

## QC
§A. If the person is the Reddit woman, FAIL identity — stop O13.

## Results
| tag | verdict |
|---|---|
| `o13_anypose` | Photoreal image2 = identity leak (O9). Closed. |
| `o13_map` | pose_map_botharms + 50-step: standing lean, human face. |
| `o13_lt_map` | Lightning 4 / CFG 1 / euler+simple: same standing lean. |
| `o13_lt_fdau` | fdau map + Lightning: same. |

AnyPose + a skeleton does not produce plowcam. **Do not repeat.**
