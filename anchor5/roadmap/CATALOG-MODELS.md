# Catalog → models (ahead of those tests)

Source: `anchor5/reddit-pose-catalog.json` (111 topics, 9 families,
2026-08-15). A scene is

`configuration × pose × contact × act × finish × movement × camera [× overlay]`

**We do not need 111 models.** Almost every id is a **prompt + pose
lock + (later) clip**, on the stacks we already have. Anatomy is
three topic ids after pose QC. Movement is video, not 2511.

Research 2026-08-16: Civitai/HF/Reddit/WAN Rapid notes. Extra files
are listed under “download only if.” Do not pull them onto cerberus
mid-`p_*`.

## What each family actually is

| family | n | What it is | How we get it | Extra model? |
|---|---|---|---|---|
| **pose** | 31 | Her skeleton + camera | 2511 + InstantX Union/depth / AnyPose / Multiple-Angles. Parent = identity or a pose-PASS. | **No.** One 2511 graph per *family* (FDAU/doggy, cowgirl, missionary, standing look-back, prone, kneel). Variants are captions. |
| **camera** | 4 | Lens | Same still graph. `plowcam`/`rear` = low hips-to-cam (current grind). `side_3qtr` is looking-back already. `pov` = face+act, watch face-only. | Multiple-Angles LoRA already on disk. |
| **movement** | 7 | Beat inside a pose | **Clip.** `ltx25` (default) or `wan22_s2v`. Prompt the verb (`thrust`, `grind`, `look_back`, `crawl`). Still is the hold frame. | Not 2511. Optional WAN/LTX sex LoRA only if stock clip is static. |
| **contact** | 13 | What touches | Pose sheet first. Insertion readable = anatomy/inpaint on a PASS, or the partner is a later layer. | No new UNET. |
| **act** | 20 | Named topology (spit roast, DP, …) | Config count + a pose + contacts. 2511 can take image2/3 as *cast props* (`T4-12`) — not as her plate. | No. Multi-body later; she must stay complete. |
| **finish** | 12 | Fluid / aftermath | Inpaint or donor stitch on a pose-PASS sex sheet. Clip if it has to move (squirt jet, drip). | Donor path we already have (Z-Image labiaplasty). Not Pony as image1. |
| **configuration** | 18 | Who is in frame | `solo`/`pair` first. 3+ bodies only after she is locked. Extract her; extras are clutter. | No. |
| **anatomy** | 3 | Texture after pose QC | O10 → O11 SNOFS → O11b labiaplasty → donors retone’d. | Files **on disk**. |
| **overlay** | 3 | anthro / public / bondage | She is already anthro. Public/bondage = pose + prompt. | No character LoRA. |

## Pose families (31 → 6 graphs)

Do not train or download a LoRA per row. Get **one PASS** in the
family, then variants by caption / CN map.

| family | catalog ids | still method | motion after |
|---|---|---|---|
| **FDAU / doggy** | `all_fours`, `face_down_ass_up`, `doggy`, `bent_over_lookback`, `pronebone` | Current grind. Union/depth/AnyPose. Seed 129080599 kneels — skip. | `thrust`, `look_back`, `crawl` on ltx25 |
| **standing** | `standing_behind`, `standing_sex`, `wall_pin`, `furniture_edge` | looking-back / standing photos as image1; small pose hop | short thrust |
| **supine** | `missionary`, `mating_press`, `legs_over_head`, `butterfly`, `legs_spread` | New CN map from a supine hold-frame (depth, not photoreal encode) | hip roll / thrust |
| **ride** | `cowgirl`, `reverse_cowgirl`, `squat_ride`, `amazon`, `lotus` | Ride OpenPose/depth; she is the mover | `bounce` / `grind` |
| **side** | `spoon`, `side_scissor`, `t_square` | Side skeleton; 3/4 camera is allowed here | grind / side thrust |
| **fold / oral / sit** | `piledriver`, `full_nelson`, `wheelbarrow`, `lift_carry`, `kneel_oral`, `deepthroat`, `facesit`, `sixty_nine`, `hanging_breasts` | After the five above. Harder skeletons. | hold / bob / grind |

`lift_carry` / `wheelbarrow` / `piledriver` are last: feet-off-floor
and stacked folds fail DWPose the way the pike did.

## Movement (7) — video, not stills

| id | still already is | clip |
|---|---|---|
| `look_back` | head rotated on the pose sheet | ltx25: hold the look; small head turn if the still is static |
| `thrust` | doggy / standing_behind / missionary PASS | ltx25 / s2v prompt. If static: **then** a WAN low-noise thrust LoRA |
| `grind` | cowgirl / spoon / lotus | same |
| `bounce` | cowgirl / squat_ride | same; peak height vs peak seat is the hold |
| `insertion` | one frame of entry | clip first second, or a still inpaint |
| `crawl` | all_fours mid-step | clip; four points visible |
| `swap` | same pose, new partner | later; config + two clips |

Community (WAN Rapid AIO / r/comfyui NSFW video):

- WAN LoRAs must be **Wan 2.1 or Wan 2.2 low-noise**. High-noise 2.2
  LoRAs fight Rapid/Lightning merges.
- Phr00t WAN Rapid NSFW exists (different file from the **image**
  Rapid-AIO v23 we already have). Do not load an image LoRA on WAN.
- LTX-2.5: camera LoRAs from LTX-2 19B were **measured not to work**
  (TRD-2). Motion is prompt + `character_reference`. Do not restage
  those camera LoRAs.
- Uncensored WAN often wants a **NSFW umt5** text encoder. We have
  stock umt5. Only swap if C3 (species) holds and C2 (sex motion)
  is the fail.

**Download only if** stock `ltx25` on a pose-PASS still cannot
thrust/grind: one WAN 2.2 **low-noise** sex-motion LoRA (thrust) on
gamingpc, not cerberus.

## Anatomy / finish — already covered

| catalog | method | on disk |
|---|---|---|
| `rear_anatomy` | O10 Inpaint CN or Easy-Inpaint; O11 SNOFS; O11b `adjust her pussy and anus` | yes |
| `vulva_closeup` / `anus_closeup` | Donor crop (Z-Image labiaplasty v3 **ran**) + Lab retone | yes |
| `creampie*` / `squirt*` / `gape` | Same inpaint/donor on a sex-pose PASS; clip if it must jet/drip | donor path yes |
| Reddit named refs | `farflungfreesquid`, `gr8eOKMH4M` (trim), `nBo9BtPloK` | `reddit-samples/named/` — **never image2** |

Z-Image donors (`donors-zimage-labiaplasty`): geometry PASS, pigment
FAIL until retone. That is O12c without downloading Pony.

## Configuration / act — later

`solo` and `pair` are enough for the album’s first exposing sheets.
`mfm` / `spit_roast` / `dp` need a second/third body as **cast**
(image2/3, named by slot). Do not train a gangbang LoRA. Do not use
a photoreal orgy still as image2 (O9).

## Do not download for the catalog

| temptation | why not |
|---|---|
| One Pony/IL checkpoint “for the catalog” | Wrong UNET. Donors already work on Z-Image. |
| One LoRA per topic id | 111 adapters. Families + captions. |
| LTX-2 19B camera LoRAs | Measured dead on 2.5. |
| WAN high-noise sex LoRAs | Community: they fight the 2.2 / Rapid stack. |
| Qwen 2512 pussy LoRAs | t2i 2512, not Edit 2511. |
| SNOFS Krea / Klein defaults | Wrong backbone. |
| Klein 9B until 12a fails | O12b. |

## Order vs the catalog

1. FDAU / `bent_over_lookback` still, pose PASS (this grind).
2. Anatomy on that PASS (`rear_anatomy`).
3. Clip that still with `look_back` / `thrust` on `ltx25`.
4. Next pose family (cowgirl or missionary), same 2511 graph, new map.
5. Finishes and multi-body last.

That is how the catalog gets done without a new model per row.
