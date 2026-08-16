# QC — pose then anatomy, then donor, then clip

Gates: `T3-33.b`, `T4-20`. Judge the **picture**. A VLM badge is not a
stamp. Anatomy on a pose FAIL is illegal.

This process is compatible with the studio tiles (UIUX §7a.6). Donor
t2i and clips need extra stamps the studio tile does not have yet —
use this file, not a second identity stack.

## A. Identity still (2511 grind / studio sheet)

Stamp **pose** first. All five must PASS or name the fail.

| # | check | PASS | FAIL (examples we have) |
|---|---|---|---|
| 1 | Cat muzzle | Black feline face, cat nose, whisker pads, yellow slit eyes. No peach human patch. | `lbpose` peach face. `p_idn` human-structured face. |
| 2 | Both arms | Shoulder to wrist, two plants or a complete hang. | `lbpose` / `p_*` far arm hidden. `qc2` third hand. |
| 3 | Source skin | Dark brown from `looking-back.jpg` + `standing.jpg`. Not jet-black UI pair. Not pale plate. | Charcoal invent. Hot peach reseal. |
| 4 | Asked camera | For FDAU / doggy look-back: hips to camera, low rear. | `qc3` / `p_*` 3/4 crouch. `p_idn` standing. Seed 129080599 kneels. |
| 5 | Tail origin | Coccyx **above** the anus, tail aside or up. | Tail across the cleft. Hip-exit tail. |

Write one line: `pose PASS` or `pose FAIL: <checks>`.

If pose FAIL: stop. Do not O10 / SNOFS / labiaplasty / stitch donors.

If pose PASS: stamp **anatomy**.

| # | check | PASS |
|---|---|---|
| 6 | Vulva visible | Human-shaped, not a crease, not missing. |
| 7 | Anus visible | Below the tail origin, not sealed. |
| 8 | Pigment | Lighter than surrounding fur/skin; a/b from looking-back + standing. Not charcoal, not pale photoreal. |
| 9 | Lighting | Cleft is lit. Shadow that hides both holes is a fail. |

## B. Donor still (Z-Image / Pony / Reddit crop)

These are **not her**. Different QC. Never use as `image2`.

| # | check | PASS |
|---|---|---|
| D1 | Geometry | Human-shaped vulva and/or anus, asked camera (usually rear). |
| D2 | No child-read | Adult. Hard exclude if not. |
| D3 | Usable crop | Cleft fills enough of the frame to retone and stitch. |
| D4 | Not a person-plate | No face we would copy. If a face is in frame, crop it off before retone. |
| D5 | After retone | Lab **L** from donor, **a/b** from looking-back + standing. Then it may sit next to a pose-PASS body. |

`donors-zimage-labiaplasty/results/rear_s101`…`s404`: D1 PASS (holes
drawn), D5 not done (pale plate flesh). Hold as geometry.

## C. Clip (ltx25 / wan22_s2v)

Only from a **chosen** still that already passed A (and B if nude
exposing).

| # | check |
|---|---|
| C1 | First frame is still her (species named in `character_reference` — LTX forgets otherwise). |
| C2 | Asked movement happens (`thrust`, `grind`, `look_back`, …). |
| C3 | She does not become a human woman mid-clip. |
| C4 | Length is the song’s clip, 8n+1 legal frames. |

No Pony/Krea LoRA on the video UNET. WAN NSFW LoRAs only if C2 fails
on stock `ltx25` / `s2v`.

## Variation rule

One variable per hop: seed **or** CN strength **or** parent **or**
LoRA **or** sampler family. A matrix is a **queue**, not three boxes
on the same graph. If two settings produce the same picture
(`p_base` ≈ `p_cn90` ≈ `p_ds`), the variable did nothing — say so
and change the **method**, not the CFG.

## Search on fail

When a hop fails a named check, search that failure (missing arm,
identity leak, reseal, Lightning garbage) before the next hop. Record
the thread in that option’s WORKFLOW. Do not “try Pony” because a
2511 sheet was 3/4.
