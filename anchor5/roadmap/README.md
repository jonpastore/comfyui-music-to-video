# Pose / anatomy runbook

Operator follow-along for the 2026-08-16 grind. Specs stay in
`docs/TRD-*`, `docs/PRD-*`, `docs/DDD-4-7-IDENTITY-AND-RENDERING.md`
§1a. This folder is the **how to run each test**, with sheets synced
here so you can judge them.

`*.png` is gitignored (`*.png` at repo root). The pictures live on
**disk** under this folder; `git status` will not list them. Each
option has `WORKFLOW.md` + `results/` + `RESULTS.txt` (file list).

**Full dump** (every hop from this grind, not split by option):
`_inbox/cerberus-cleanrun/`, `_inbox/gamingpc-gp/`,
`_inbox/gamingpc-donor/`. Parents and maps: `_refs/`.

Empty `results/` means that option **has not been run** (O6, O10,
O11, O14, …), not that the sync missed it. Older FAIL hops that we
moved off the grind live in `deprecated/2026-08-16-pose-grind/`,
not here.

## How to follow

1. Read `QC.md`. Pose PASS is required before any anatomy hop.
2. Training (later): `TRAIN.md` — identity / pose-family / anatomy /
   motion. Not one LoRA for the catalog. Do not start yet.
3. Open the next **runnable** option (status table below). One
   variable per hop.
3. Follow that folder’s WORKFLOW: models, graph, community settings,
   variation matrix, accept/fail.
4. Drop outputs in that folder’s `results/`. Fill `RESULTS.txt`.
5. Judge by eye with the QC stamps. Metrics that disagree with the
   picture lose.
6. Catalog work (doggy, cowgirl, thrust, …) is `CATALOG-MODELS.md`.
   Do not invent a model per topic id.

Cerberus `:8188` is the live 2511 grind. gamingpc
`100.107.235.105:8188` is parallel (donors, O13, empty+Union). Do not
duplicate `p_*` on both boxes. Do not restart Comfy mid-queue.

## Status

| folder | status | next |
|---|---|---|
| `O00-samepose-undress` | **win** — keeper | Identity parent. Do not redo. |
| `O01-empty-union-identity` | **done** — both-arms 0.85 and CN 1.0: muzzle PASS, extra limbs/tails | Map is incomplete. Do not repeat. |
| `O02-empty-union-lookingback` | **done** — muzzle PASS, camera FAIL | **Do not repeat.** |
| `O03-empty-union-two-ref` | **done** — best muzzle, 3/4 camera | Settings only (done as O05). |
| `O04-encode-fail-parent` | **improper** | Never. |
| `O05-encode-qc3-union` | **done** — encodes keep 3/4 | Stop CN-on-qc3. |
| `O06-depth-map` | **done** — real Depth-Anything (not RGB). `o6_union_pface_d85` = best new identity (muzzle + tail aside + both arms). Camera not plowcam. Farflung depth = extras. RGB-as-depth = horror (closed). Encode-parent 0.50 kept parent. | Closest muzzle+tail-aside parent. Not pose PASS. |
| `O07-diffsynth-union` | **done** (`p_ds`) — no rotation | Do not repeat. |
| `O08-crop-stitch-muzzle` | **done**. Crop-edit works: `o8crop_qc3_d100_crop` is her muzzle. `o8blend_qc3_tight` = closest plowcam+muzzle (tail still up). Full-sheet Edit/CN closed. Crop-as-image2 0.70–0.75 keeps human face. Tail crop-edit invents a second body. | Use the qc3 crop as muzzle donor. Do not remask the full sheet. |
| `O09-photoreal-image2` | **improper** | Never as person-plate. |
| `O10-inpaint-cn-anatomy` | **blocked** — no pose PASS after full grind | After PASS. |
| `O11-snofs-qwen` | **blocked** — no pose PASS | After PASS. |
| `O11b-labiaplasty-2511` | **blocked** — no pose PASS | After PASS. |
| `O11c-all-inclusive` | **blocked** — no pose PASS | After O11/O11b. |
| `O12a-phr00t-rapid-aio` | **done** — no rotate; glow + kneel | Do not repeat on identity_nude. |
| `O12b-klein-9b` | **ran** 4B and 9B. 9B undress of looking-back is cleaner (boots gone, muzzle held). Still not a pose tool. | Prefer O00 2511 for undress. |
| `O12c-pony-donor` | **done** via Z-Image (no Pony ckpt). Copies in `results/`. | Retone a/b. Never image2. |
| `O13-anypose` | **done / closed** | Photoreal leak. Map 50-step = standing human face. Lightning 4-step same fail. |
| `O14-train-last-resort` | written, **not started** | After a pose PASS strategy, not instead of one. |
| `donors-zimage-labiaplasty` | **done** — holes drawn, pale flesh | Retone a/b. Never image2. Never on FAIL. |

## Two samplers, one 2511 file

| lane | settings | where |
|---|---|---|
| Studio stills | Lightning 4-step, CFG 1 | `make_anchor.py` |
| Grind | CFG 2 / 50 / `dpmpp_2m`+`karras`, Lightning **off** | this folder |

Mixing them is the O12 mistake. Phr00t uses 8 / `euler_ancestral` /
`beta` / CFG 1.

## Boxes

| box | for |
|---|---|
| cerberus `100.103.148.120:8188` | `p_*`, O12a. Do not occupy with training. |
| gamingpc docker `~/comfy-backend` | Donors, O13, O1 empty+both-arms, #535 copy. |
