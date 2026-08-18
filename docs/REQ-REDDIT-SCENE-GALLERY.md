# Requirement: Reddit scene gallery as the pose vocabulary

Draft for tomorrow’s refinement. Adult 18+ only.

The operator catalog is the scene list, not a pile of photoreal people
to copy. Source of truth:

- `anchor5/reddit-pose-catalog.json` — 111 topic ids, aliases, 9 families
- `anchor5/reddit-samples/<topic>/` — hold-frames and clips per topic
- `anchor5/reddit-pose-catalog.md` — human index

A scene is composed:

`configuration × pose × contact × act × finish × movement × camera [× overlay]`

Example: `mfm` + `doggy` + `anal` + `spit_roast` + `creampie_flow` + `thrust` + `rear`.

## What future product must do

1. **Mint a sheet for any catalog topic** the board asks for, not only the
   four shipped views. The 2026-08-18 Street Cats xxx boards already
   need cowgirl+Panther, kneeling look-back, and supine+Panther
   (`docs/street-cats-xxx-pose-need.md`).
2. **Treat gallery stills as geometry**, not identity. Extract pose /
   camera / contact. Do not use a Reddit face as `image1`. Photoreal
   Reddit as `image2` leaked a stranger (O09). Tonight we re-test that
   path on six curated stills (jobs 304–309) so we have new pictures,
   not a memory.
3. **Curate hold-frames.** Largest-file auto-pick is useless: Snapchat
   ads, nipple closeups, contact sheets. A still is usable only if it
   shows the asked skeleton (two+ bodies for configs, hips-to-camera
   for FDAU, etc.) and the face reads adult.
4. **Hard excludes stay:** teen / school / youthful-uniform packaging,
   any under-18 read, incest, personals, casting-as-act.
5. **Ref slots:** `MAX_ANCHOR_REFS=3`. Identity is `image1`. A pose
   plate is `image2`. A second identity (Kitty, Tiger) is `image3`.
   An ensemble plate **is** the multi-body lock — do not also send
   three solo fronts.
6. **Compose must not say “single adult character”** on an ensemble
   topic. Tonight’s enqueue still did: `front_nude` + pose=lesbian 69
   composed a *single-character* front sheet. That is a product bug
   for tomorrow: ensemble topics need a multi-body compose, or the
   plate cannot win.
7. **Kitty** (Street Cats id=3, cover crop figure 5) is the second
   female lead for `lesbian` / `ffm` / `fff`. Do not mint those
   without her identity sheet passing QC.md A (pale/white, not Meow P).
8. **Street Cats xxx generate** is still blocked by T10-19 on Rear
   Entrance scene 1 age-lock wording. Workarounds enqueue on Catatonic
   with the same identity files until that screen is fixed.
9. **QC.md A** (pose then anatomy) before any donor/O10. Skin must
   match `standing-nude.jpg` / `looking-back.jpg` brown, not jet UI
   pair. Extra limbs = fail.

## Gallery topics we have samples for

`airtight` `anal` `anus_closeup` `cowgirl` `creampie_cleanup`
`creampie_flow` `cunnilingus` `doggy` `double_anal` `double_cowgirl`
`double_penetration` `double_vaginal` `face_down_ass_up` `facesit`
`ffm` `fmf` `fucklicking` `gangbang` `lesbian` `mfm` `missionary`
`mmf` `orgy` `rear_anatomy` `reverse_cowgirl` `scissoring`
`spit_roast` `squirt` `vulva_closeup`

## Hops started 2026-08-18 (Catatonic xxx)

`image1` = standing-nude keeper. `image2` = curated still. n=1.
Empty latent, CFG 2.0 / 50. Jobs sit behind Kitty 303.

| Job | Topic | Still |
|---|---|---|
| 304 | lesbian 69 | `LesbianAsianGirls/1tuon5l.jpg` |
| 305 | ffm | `FFM/1vp44se.jpeg` |
| 306 | spit_roast | `SpitRoastedGW/1vlwlkj.jpeg` |
| 307 | face_down_ass_up | `AssUpFaceDown/1vb0fcy.jpg` |
| 308 | doggy | `NSFW_Plowcam/1vo7ndt.jpeg` |
| 309 | supine legs-up | `Pussy_From_Behind/1vqj6ys.jpg` |

Rejected as plates (ads, selfie, no skeleton): Snap watermarks,
breast-only, elf cosplay selfie, missionary selfie, strap-on solo
mislabeled mmf, porn contact-sheet.

Judge 304–309 when they land. If the plate wins pose and she stays
her, the gallery is a viable mage.space replacement for those
topics. If she becomes the photoreal woman, O09 still holds and
tomorrow’s work is depth/DWPose (O06), not pixels.
