# Plate-pose path (draft for tomorrow)

Replace mage.space stills with studio Qwen-Image-Edit 2511 sheets.
Adult / explicit is in scope. Judge the picture. A VLM badge is not a stamp
(`anchor5/roadmap/QC.md`).

## Did the T7-7 four use Reddit?

No. Jobs 292/293 conditioned on one image: the operator standing-nude
keeper (`anchor5/standing-nude.jpg` = Street Cats #181 = Catatonic #154).
Empty latent, CFG 2.0 / 50, 896×1216. No Reddit still, no ensemble plate.

## Is this ask achievable?

**Yes, as an experiment, with these measured limits:**

| Want | How | Limit |
|---|---|---|
| Her, asked pose | `image1` = identity keeper, `image2` = **drawn** pose plate | Pose comes from the plate, not the prompt |
| Graphic anatomy | Plate must already expose it. Standing legs-together will not | QC.md A6–A9 only after pose PASS |
| Multi-actor (MMF) | Ensemble plate **is** the lock (`cowgirl-dp`, split-roast) | `MAX_ANCHOR_REFS=3`. Do not also send three solo fronts |
| Lesbian / FFM | Need a second female identity (Kitty) + a two-body plate | Three identity fronts without a plate is a weak assist |
| Reddit catalog | Vocabulary + hold-frame geometry. Extract depth/pose, **discard pixels** | Photoreal Reddit as `image2` is O09 **improper** (stranger leak). Operator asked to re-test curated stills: jobs 304–309, see `docs/REQ-REDDIT-SCENE-GALLERY.md` |

This will not cancel mage.space on the first 20 hops. It tells us whether
drawn plates + the T7-7 identity lock hold pose and species. If they do,
mage is only needed for plates we do not have yet (lesbian two-body, new
cameras).

Street Cats `POST /api/anchors` at xxx is still blocked by T10-19 on Rear
Entrance scene 1 age-lock wording. Iterations enqueue on **Catatonic**
with the same identity files.

## QC of the T7-7 four

Gates from `anchor5/roadmap/QC.md` A. Identity still. Compared to
`standing-nude.jpg` (dark-brown source skin) and the UI pair.

| Sheet | Pose 1 muzzle | 2 arms | 3 skin | 4 camera | 5 tail | Anatomy | Call |
|---|---|---|---|---|---|---|---|
| **225** front chosen | PASS | PASS | **FAIL** jet-black, not keeper brown | PASS front stand | PASS aside | Vulva lighter, visible | Species/identity hold. Tone drift to UI-pair charcoal. Best front. |
| **226** front | PASS | PASS | **FAIL** jet | PASS | PASS | Crotch too dark | Same person, worse anatomy |
| **227** 3qtr | PASS | **FAIL** extra pair of legs | closer to keeper brown | PASS 3qtr | PASS | Visible | Unpicked. Limb-count fail. |
| **228** 3qtr chosen | PASS | PASS | **FAIL** jet | PASS 3qtr | PASS | Hidden | Clean figure, same charcoal drift |

`pose FAIL: source skin` on 225/226/228. 227 `pose FAIL: extra legs`.
Do not send these to donor/O10. Identity across 225+228 is her. That is
the promise. Next hops must pull **tone** from `standing-nude.jpg` /
`looking-back.jpg` (image2 or refine), not only the jet UI pair.

## Kitty

Second female lead, Street Cats character **id=3**, `figure_role=lead`.
Cropped from the album cover, figure 5 (platinum-white, magenta eyes,
`BAD KITTY CLUB` behind her). Crop:
`anchor5/kitty/kitty_cover_crop.png`

Jobs **302** `front_nude` + **303** `three_quarter_nude` queued on
Catatonic from that crop (same stack as T7-7). Use those sheets as
Kitty `image1` only after they pass QC.md A.

## How to run a hop (one variable)

1. `image1` = chosen identity (225 or standing-nude, or Kitty front).
2. `image2` = one **drawn** plate from `anchor5/` (already on live
   `~/meowp-studio/data/uploads/anchors/album/Catatonic/plate-exp/`).
3. Optional `image3` = second identity (Kitty or Tiger), never a third
   plate.
4. Empty latent, CFG 2.0, 50 steps, 896×1216, LoRA off, short negative.
5. `n=1`. Change seed **or** plate **or** identity, not two at once.
6. Stamp pose A1–A5. On FAIL stop. On PASS stamp anatomy A6–A9.
7. Do not load Reddit / named photoreal as `image2` (O09). Catalog is
   for picking which drawn plate to make next.

## 20-iteration queue

Workflow `meowp-plate-20`. Drawn plates first; two labeled photoreal
trials only to reconfirm O09. Results append below when hops land.

| # | Variable | image1 | image2 | image3 | Why |
|---|---|---|---|---|---|
| 1 | plate | standing-nude | cowgirl-nude | — | solo graphic |
| 2 | plate | standing-nude | all-fours-looking-back-exposed | — | rear expose |
| 3 | plate | standing-nude | rear-all-fours | — | FDAU family |
| 4 | plate | standing-nude | seated-legs-spread | — | seated |
| 5 | plate | standing-nude | wide-stance-spreading | — | stand spread |
| 6 | plate | standing-nude | looking-back | — | tone+pose from clothed source |
| 7 | identity | 225 | cowgirl-nude | — | generated keeper vs upload |
| 8 | ensemble | standing-nude | cowgirl-dp-panther-tiger | — | MMF plate lock |
| 9 | ensemble | standing-nude | all-fours-split-roasted | — | MMF spit |
| 10 | ensemble | standing-nude | reverse-cowgirl + tiger oral | — | MMF |
| 11 | MF | standing-nude | cowgirl-panther | — | one male on plate |
| 12 | MF | standing-nude | panther-blowjob | — | oral |
| 13 | Kitty | Kitty crop | — | — | already 302 (control) |
| 14 | lesbian | 225 | Kitty front | — | two IDs, no plate (weak assist) |
| 15 | lesbian | 225 | Kitty front | seated-legs-spread | 3-slot, solo plate |
| 16 | FFM | 225 | Kitty front | tiger-standing-erect | 3 IDs, no plate |
| 17 | tone | 225 | standing-nude | latent=image denoise 0.65 | pull brown back |
| 18 | seed | standing-nude | cowgirl-nude | seed+1 | same as #1 |
| 19 | O09 trial | 225 | one lesbian still | — | expect stranger; do not keep |
| 20 | O09 trial | 225 | one mmf still | — | expect stranger; do not keep |

## Results

### Kitty jobs 302 / 303 (QC.md A vs `kitty_cover_crop.png`)

Jobs **302** `front_nude` (ids 229/230) and **303** `three_quarter_nude`
(ids 231/232) done. Copied to `anchor5/kitty/`. QC by eye (`read_file` on
png + face/crotch crops). Cover reference: platinum-white fur, **magenta**
eyes (hue ~332°). Kitty must stay pale/ivory — Meow P black = FAIL. Extra
limbs = FAIL. VLM badge not used as stamp.

| Sheet | Pose 1 muzzle/eyes | 2 arms | 3 skin (Kitty pale) | 4 camera | 5 tail | Extra limbs | Anatomy | Call |
|---|---|---|---|---|---|---|---|---|
| **229** front `s409029363` | Cat muzzle PASS; eyes **FAIL** yellow/gold not magenta | PASS | PASS pale silver/ivory | PASS front | PASS aside | PASS | Vulva pink slit visible; anus not a front read | `pose FAIL: eyes`. Fur holds Kitty. Best front of the four. |
| **230** front `s409029500` | Yellow eyes; Meow P face read | PASS | **FAIL** charcoal/black | PASS front | PASS | PASS | Crotch dark, weak | `pose FAIL: source skin` (became Meow P black) |
| **231** 3qtr `s673144867` | Cat muzzle PASS; eyes **FAIL** amber/yellow not magenta | PASS | PASS cream/ivory | PASS 3qtr | PASS coccyx | PASS | Vulva pink, visible between thighs | `pose FAIL: eyes`. Fur holds Kitty. Best 3qtr of the four. |
| **232** 3qtr `s673145004` | Yellow eyes; Meow P face read | PASS | **FAIL** charcoal/black | PASS 3qtr | PASS | PASS | Pink genital patch on dark body | `pose FAIL: source skin` (became Meow P black) |

None PASS as Kitty `image1`. Pale keepers **229** + **231** hold ivory fur and
limb count but lose magenta eyes to Meow P yellow. **230** + **232** are
identity leaks (black fur + yellow eyes). Do not O10 / donor these. Next hop
must pull **eye color** (and keep pale fur) from `kitty_cover_crop.png`.

Paths:
- `anchor5/kitty/front_nude_s409029363_00001_.png` (229, job 302)
- `anchor5/kitty/front_nude_s409029500_00001_.png` (230, job 302)
- `anchor5/kitty/three_quarter_nude_s673144867_00001_.png` (231, job 303)
- `anchor5/kitty/three_quarter_nude_s673145004_00001_.png` (232, job 303)

Live sources: `cerberus-ai:/home/jon/ComfyUI/output/anchor_v2/` same basenames.

