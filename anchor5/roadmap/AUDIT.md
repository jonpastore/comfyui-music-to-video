# Folder audit — 2026-08-16 grind complete

Every **runnable** option has been run. Empty `results/` now means
**illegal / parked / gated**, not "forgot to sync".

| folder | pngs | verdict |
|---|---|---|
| O00 | 2 | **win** keeper undress |
| O01 | 4 | lbpose + both-arms 0.85 + CN 1.0. Extra limbs. Closed. |
| O02 | 2 | muzzle PASS, camera FAIL. Do not repeat. |
| O03 | 2 | qc3 best muzzle, 3/4 |
| O04 | 2 | G1 improper |
| O05 | 9 | encode qc3 keeps 3/4 |
| O06 | 8+ | RGB-as-depth horror (closed). Real depth: `o6_union_pface_d85` best new identity, camera FAIL. Farflung depth extras. |
| O07 | 1 | p_ds no rotation |
| O08 | 20+ | crop-edit works (`o8crop_qc3_d100_crop`). Blend closest plowcam+muzzle. Tail crop invents a body. |
| O09 | 0 | improper |
| O10 / 11 / b / c | 0 | **blocked** — no pose PASS |
| O12a | 3 | Phr00t kneel/glow |
| O12b | 0 | Klein not fetched (18 GiB, undress not pose) |
| O12c | 0 | use donors |
| O13 | 5 | photoreal leak + map 50-step + Lightning 4-step all FAIL |
| O14 | 0 | do not train |
| donors | 4 | holes, pale |

## Closest sheets (none are pose PASS)

1. `O08/.../o8blend_qc3_tight.png` — plowcam body + her muzzle, tail up over cheek.
2. `O06/.../o6_union_pface_d85_00001_.png` — her muzzle + tail aside + both arms, 3/4 squat, glow, cuff.
3. `p_face` — plowcam body, human face.

## Back Alley Pussy XXX

Still do **not** mint the 16 stills. No pose-PASS all-fours.

## Do not run again

Full-sheet face inpaint, RGB-as-depth, farflung depth, AnyPose (any
image2), encode-qc3, Phr00t on identity_nude, tail crop at denoise 1.0,
crop-as-image2 at 0.70–0.75, O1 both-arms CN sweep.
