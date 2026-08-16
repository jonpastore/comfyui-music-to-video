# O05 — Encode qc3 (good muzzle) + Union

**Status:** run. Highest-value method; **settings did not rotate**.

## Purpose
Keep qc3's muzzle; let CN pull hips-to-cam.

## Models
- 2511 grind. Encode `qc3_s749.png`. Denoise **0.75**.
- Union on `pose_map_fdau_wide.png` or `pose_map_botharms.png`.
- image2 = looking-back.jpg.

## Community
Encode + drop denoise is the usual “keep the face” fix (r/comfyui
Qwen face threads; CropAndStitch is O8). CN 0.8–1.0 for InstantX.
Our 0.55–0.90 on this parent produced the **same 3/4 crouch**.

## Variation (cerberus `p_*`)

| id | result |
|---|---|
| `p_base` CN off | 3/4. Muzzle PASS. Hips FAIL. |
| `p_cn55` 0.55 | Same picture. Variable did nothing. |
| `p_cn90` 0.90 | Same. Map/parent, not strength. |
| `p_both` both-arms 0.80 | Same. |
| `p_ds` → O07 | Same. |
| `p_idn` identity_nude parent | **Standing.** Parent pose won. Face more human. Tail covers. |
| `p_face` | still queued (O8-lite). |
| `p_s5151` | still queued. |

## QC
All judged `p_*` except pending: pose FAIL camera (or standing).
Do not O10.

## Next
Change **method** (empty+complete map O1, depth O6, AnyPose O13,
Phr00t O12a), not another CN strength on this parent.
