# Prompt — update requirements for the full stills→clips loop

**This file is the source of truth for the docs session.** Do not implement
from Jarvis #528. That ticket is the earlier stills-only draft (classify →
gap → pose → reclassify → anatomy on the anchor form). The decided product
is this whole loop, including storyboard map, location plates, LTX, s2v
lip hop, and tier backfill.

Decided 2026-08-15 with the operator. D1–D10 are locked.

---

You are updating Meow P Studio requirements so the UI, sqlite fields, and
code describe one loop from storyboard poses through clips, for every
defined tier (g, pg13, r, xxx). Product: `comfyui-music-to-video`.

This is a documents change. Do not implement UI or deploy. Isolated
worktree if you also touch `studio/*.py`. Push and deploy are not gated
on ComfyUI / Swarm jobs (AGENTS.md).

Read first, in this order:

- `AGENTS.md` (pipeline, character, render facts, docs-drift rule)
- `docs/TRD-2-STORY-ARC-AND-STORYBOARDS.md`
- `docs/TRD-3-QC-AND-REMEDIATION.md`
- `docs/TRD-4-CHARACTER-ANCHORS.md`
- `docs/TRD-5-CLIP-RENDERING-AND-REFINE.md`
- `docs/TRD-7-ANCHOR-VARIATIONS.md` (ledger in §9 is stale)
- `docs/PRD-1-3-EDITING-AND-QUALITY.md`
- `docs/PRD-4-7-IDENTITY-AND-RENDERING.md`
- `docs/DDD-1-3-EDITING-AND-QUALITY.md`
- `docs/DDD-4-7-IDENTITY-AND-RENDERING.md`
- `docs/UIUX-DEFINITION-AND-STYLE-GUIDE.md` §7a and storyboard/clip surfaces
- `make_anchor.py`, `build_refs.py`, `build_song.py` (s2v `control_video`, `_refine_ltx`)
- `studio/pipeline.py` `gen_anchor` / `gen_refs` / `gen_clips`
- `CONTINUATION-2026-08-15-nude-anchors.md`
- `anchor5/image-classification.json`, `anchor5/pose-gaps.json`

Update TRD-2, TRD-3, TRD-4, TRD-5, TRD-7, both PRDs, both DDDs, and UIUX
in the same change. Add fail-able T-ids. Refresh stale ledgers. Do not
leave any of those describing the old one-shot “one front sheet → every
scene → one video_model” world.

Adult / explicit is in-scope. Do not moralize. Do not add a second graph
builder, ControlNet, IP-Adapter, or a WAN refine of an LTX latent.

## 0. Decisions (do not re-litigate)

**D1.** Storyboard is analyzed first for **needed poses**. That is a
coverage list, not a bind. Classification of stills stays a library.
Mapping comes later and requires Accept.

**D2.** Pose library is generated at the **ceiling** = highest tier the
operator ticked this run. Not always xxx. A run may be g-only, or start
at r. If the ceiling allows nudity (r, xxx), generate clothed **and**
nude coverage. If it does not (g, pg13), clothed only. No anatomy pass
on a g/pg13 ceiling.

**D3.** Backfill = every **lower** tier that was also ticked. Unticked
tiers get nothing. Do not auto-write all four. Machinery must still know
all four tiers (UI, columns, guardrails, nude skip).

Backfill means: that tier’s guardrail + the wardrobe it permits.
g/pg13 bind clothed keepers only and carry the mainstream lock.
r may keep nude; it does not inherit xxx graphic board text.
Never invent a **higher** tier than the ceiling (no nude from a g run).

**D4.** After coverage is green, the studio **drafts** a pose→scene map
from classified tags + scene text. Operator Accepts or rejects per scene
(same shape as the arc wand, T2-15). Generate scene refs only from
accepted bindings. Classify never writes the map.

**D5.** One backdrop **image** per unique location key, reused by every
scene (and every ticked tier) that names that location. Generate or
upload. Unset / “studio” keeps the grey-studio prompt and no plate.
This is not `make_anchor.BACKDROP` on a character sheet.

**D6.** Every scene renders LTX 2.5 first from the scene ref + location
plate (if any).

**D7.** Lip-sync is a second, **decoded** hop on marked scenes only:

- s2v `WanSoundImageToVideo`
- `ref_image` = the accepted scene still (her)
- `control_video` = the LTX take, loaded as IMAGE frames
  (`LoadVideosFromFolder` — not `LoadVideo`, not an LTX latent).
  Windowed to the s2v ceiling (~4.8125 s, T5-9 chosen).
- `audio` = that clip’s trim window

Deliverable for those scenes is the s2v clip. The LTX take stays listed
as predecessor (T6-A5).

**D8.** “LTX post” is T5 variant A (same-resolution re-denoise) on the
LTX take. It is not a third LTX job on s2v frames. It is not the WAN
i2v-low refiner. TRD-5’s latent forbid **stands**: LTX VAE ≠
`wan_2.1_vae`. The hop in D7 is pixels, which is why it is allowed.

**D9.** D7 is **NOT MEASURED** until a same-scene GPU pair exists
(LTX-only vs LTX+s2v-control). Criterion is a picture look: lips move,
she is still her, LTX blocking is still readable. If the pictures fail,
the fallback is today’s s2v-from-still (no `control_video`), recorded as
a finding, not a silent drop of the hop.

**D10.** Identity: text names species/body; image1 is her; a plate that
is not her is refused. Pose geometry exposes anatomy; prompt does not.
Body colour matches operator photographs (charcoal-brown / espresso),
not jet-black. Working still stack: Qwen 2511, CFG 2.0 / 50 /
`dpmpp_2m`+`karras` / LoRA off. Same-pose undress = image latent +
denoise 1.0 + pose text matches source. New pose = empty 896×1216 + her
keepers, never a stranger plate.

## 1. The loop (this is the product)

1. Ceiling-tier storyboard exists (generate or open).
   **Analyze:** extract required (pose, view, wardrobe, exposure) per
   scene. Write a coverage list. Do not attach files.
2. **Review** the album’s classified library (sqlite JSON document,
   shape of `anchor5/image-classification.json`: id, path, kind, view,
   pose, wardrobe, usable, notes, seed). `usable=skip` never enters a
   slot.
3. **Expand:** generate missing poses (job types C1 same-pose edit /
   C2 new-pose). QC each landing. Operator marks keeper / reject.
   Write the new rows back into the JSON document. Coverage updates.
   Do not map.
4. **Backfill** ticked lower tiers: their boards (wording + guardrail),
   their allowed wardrobe subset, their own later maps. Pose files are
   not regenerated.
5. **Map:** draft keeper → scene; operator Accepts. Persist the map
   per song per tier. T2-13b still holds: approved refs survive re-plan
   of the same board.
6. **Scene refs:** `gen_refs` uses the accepted keeper for **that**
   scene as image1 (plus her other views as extra refs if present), and
   the location plate when the scene has one. Stop using one chosen
   front sheet as image1 for every scene. T2-27 (per-scene refs) stays;
   the source of the still changes.
7. **Location plates:** one still per distinct location key, Qwen or
   upload, reused. Not a character sheet.
8. **Clips:** LTX 2.5 per scene (D6). Marked lip scenes then D7.
   LTX refine T5-A on LTX takes (D8). Song length still owns clip
   count. Per-model ceilings still compose (T2-48) — a 15 s LTX take
   becomes several s2v windows when the hop runs.
9. Assemble as today (one output fps, T2-13d). Mixed LTX@16.8312 and
   s2v@16.0 is already specified.

## 2. What each document must say

### TRD-2 (boards, map, per-scene model)

- Add: analyze-for-poses is a first-class output of a board (coverage
  list). It does not write refs.
- Add: pose→scene map, drafted, Accept required, per song per tier.
- Revise T2-42/43: a scene still may name `video_model`; **add**
  `needs_lip_sync` (or equivalent) as the directorial fact. Lip-sync
  no longer means “skip LTX.” It means “LTX first, then D7.”
  Unmarked scenes are LTX only.
- Keep T2-21/22 (tier wording), T2-31/32 (`character_reference` text
  lock), T2-27 (per-scene refs), T2-48 (ceilings compose).
- Add: location plate key on the scene; reuse by key.
- Add: ceiling + ticked-lower backfill of boards.

### TRD-3 (QC)

- New poses run the same still QC as anchors (T3-31 confidence,
  identity, hallucinations). Add prompt/settings remedies:
  latent / denoise / CFG / pose-match / plate-absent / body colour.
- `T3-33.b` / `T4-20`: pose QC (cat muzzle, both arms, source skin, asked
  camera, tail origin above the anus) **before** anatomy QC. Empty
  latent invents a face. InstantX Union is pose only. Vanilla 2511
  undraws genitals — SNOFS / Inpainting CN / crop-stitch after PASS.
  Anatomy samples (r/rearpussy, r/GodPussyv2, r/GodAsshole, …) retone
  to her source photos. Never anatomy on a pose FAIL. Never photoreal
  as image2. Operator grind:
  `docs/MEASURED-2026-08-16-POSE-ANATOMY.md`.
- QC must not fail image-latent sheets for inheriting source size.
- D7 pair is a new image/video look: lips + identity + blocking.
  NOT MEASURED until a real pair is pinned. Do not rank on warm px.
- T3-28 stays: identity-wrong remedy is edit the text, not swap a
  stranger plate in.

### TRD-4 / TRD-7 (library and generate)

- Classification JSON lives in the DB (album + character scoped,
  versioned). Sidecar files are not the store.
- Stages A–E from the 2026-08-15 stills loop stay (classify, gap
  against **this** board, C1/C2, reclassify, anatomy last on exposing
  geometry). Gap reads the board; it does not bind.
- T4-11 colour matches operator photographs.
- T7-8/T7-16 coupling: C1 vs C2 decides latent, denoise labels, and
  whether pose text must match the source.
- T7-9 stands: no silent plate. Location plates are a different
  object, attached at scene-ref time, never as her identity lock.
- Use-as-ref only from keepers with `usable≠skip`.

### TRD-5 (clip graphs)

- Keep: no WAN refine of an LTX latent; T5-A is LTX post; T5-9/10
  ceilings; T5-2 still a picture differential.
- Add the D7 hop as a new criterion: decoded LTX frames →
  `control_video`, scene still → `ref_image`, audio window, s2v
  ceiling split, predecessor LTX file retained.
- Add: `skip_first_frames` / trim so each s2v window reads the
  matching slice of the LTX take, not always frame 0.
- Explicitly not building: LTX latent into WAN; a third LTX job on
  s2v frames as “correction.”

### PRD-1-3 and PRD-4-7

- One product narrative: coverage → library → map → scene stills +
  location plates → LTX → optional s2v hop → LTX refine.
- Rewrite PRD-4-7 §3.2 (identity is text + her image1, not “text
  not the photo”).
- Priorities: anchors-on-model and this loop beat the timeline.

### DDD-1-3 and DDD-4-7

- Replace the one-line pipeline with the loop above.
- One resolver for C1/C2 (latent + denoise labels + pose hint).
- One resolver for clip hops (LTX always; s2v if `needs_lip_sync`;
  T5-A if refine). Labels cannot promise a hop the graph omits.
- JSON document schema named; versioned; queryable by
  view / pose / wardrobe / usable.
- Location plates table or assets kind, keyed by location string.

### UIUX

- No wizard. No storyboard on the generate-anchors form.
- Anchors page: library chips, coverage vs the open song’s ceiling
  board, C1/C2 job type, QC remedy line, keeper/reject.
- Storyboard page: coverage meter, draft map + Accept, location
  plate per unique key, `needs_lip_sync` beside camera (not instead
  of it), ceiling/backfill of ticked tiers visible.
- Refs page: generate from accepted map; show which keeper and
  which location plate each scene used.
- Clips page: LTX predecessor + s2v successor both listed when the
  hop ran; refine sibling on the LTX take.
- Every control the backend cannot honour is marked, never inert
  (UIUX 7a.3). D7 unmeasured until the GPU pair exists — say so on
  the control.

## 3. Data (minimum; do not over-schema)

- `classification_json` (album, `character_id` NULL=protagonist,
  versioned document, same fields as `image-classification.json`)
- `pose_coverage` (song, tier, derived from board vs library)
- `scene_pose_map` (song, tier, scene_number → keeper id/path,
  status `draft|accepted|rejected`)
- `location_plates` (album or song, location key → asset path)
- `scenes.needs_lip_sync` (or `video_model` kept plus this flag)
- clips retain predecessor/successor (T6-A5) for LTX take, s2v hop,
  LTX refine

Tiers remain g / pg13 / r / xxx. Nude views derived (T7-2). A nude
map row on g/pg13 is refused.

## 4. Non-goals

- Do not auto-map during classify.
- Do not regenerate the pose library once per tier.
- Do not invent xxx from a g ceiling.
- Do not put Reddit / photoreal / stranger plates in any slot.
- Do not wire LTX latent to WAN.
- Do not add a third LTX “correction” pass on s2v output.
- Do not put the storyboard on the anchor generate form.
- Do not file 244 criteria. Add this slice’s fail-able ids.
- Do not move song-length ownership of clip count.

## 5. Done when

- All listed docs describe the same loop and the same D1–D10.
- TRD-5 still forbids latent handoff and newly requires the decoded hop.
- TRD-2 map is Accept-gated; classify cannot write it.
- Ceiling + ticked-lower backfill is a criterion with both directions
  (r+pg13 writes both; r-only does not write pg13; g ceiling writes
  no nude).
- UIUX can be built without a wizard.
- A reader who never saw the chat can implement the screens and the
  two graphs from the docs alone.
- Every new criterion has a positive half and can go red.
- D7’s picture look is marked NOT MEASURED until a pinned GPU pair.

## 6. Tree vs this loop (2026-08-16)

Reconciled after `trd-closeout-30` was stopped. Code/ledger closeout
wrote the **old** one-shot world to a high built-rate. This file is
now the product. Do not mark the loop **built** until the criteria
below exist and can go red.

**Shipped (keep):** still QC (T3-31 advisory, T3-28 / T3-33.a edit-text),
T2-27 per-scene refs, T2-28 refuse refs without a chosen sheet, T2-48
ceilings, T5 no WAN-of-LTX-latent, T5-A refine, T6-A5 dest≠src, T7-20
named poses, T10 minor policy rows that landed, nude-loop CLI as a
sidecar (not the studio loop).

**Not this product yet (the leftover):**

| #529 piece | Tree |
|---|---|
| D1 coverage list from the board (no bind) | not a first-class studio output |
| D2 ceiling-tier pose generate (clothed+nude iff r/xxx) | **built** `T4-24` (`test_t4_24_ceiling_generate.py`). `POST /api/songs/{id}/pose-generate` / `pose_generate.generate` from pose-gap holes at the run ceiling. Sidecar `batch_edit` is not the path |
| D3 ticked-lower backfill, never invent a higher tier | not a criterion |
| D4 draft map + Accept (classify cannot write it) | **built** `T2-51`/`T2-52` (`test_t2_51_classify_cannot_write_map.py`, `test_t2_52_map_accept.py`). `scene_pose_map` status draft\|accepted\|rejected; `start_refs` refuses draft/rejected |
| D5 location plate per location key | **built** `T2-53`/`T7-22` (`test_t2_53_location_plates.py`). Store only; no page display |
| D6 LTX always first | **built** `T5-11` (`test_t5_11_ltx_always_first.py`); lip fact is `T2-55` **built** |
| D7 decoded s2v hop (`control_video` = LTX frames) | graph **built** `T5-12`; look **NOT MEASURED** (`T3-37`); no GPU pair |
| D8 T5-A stays on the LTX take, not on s2v | specified; confirm graph labels |
| D9 D7 look (lips + her + blocking) | no pinned pair |
| D10 identity = text + her image1; charcoal-brown | measured on stills; 0 chosen studio anchors |
| sqlite `classification_json` | **built** `T4-21`/`T4-22` (`test_t4_21_classification_json.py`). Sidecar seeds import only |
| Docs TRD-2/3/4/5/7 + PRDs + DDDs + UIUX describe this loop | **rewritten 2026-08-17** — T2-50…T2-56, T3-34…T3-37, T4-21…T4-24, T5-11…T5-15, T7-21…T7-23. `T2-50`…`T2-56`, `T3-34`, `T4-21`…`T4-24`, `T5-11`, `T5-12` (graph), `T5-13`, `T5-15` (`test_t5_15_no_latent_handoff.py`), `T7-21`…`T7-23` **built**. Leftover is T5-14 (refine-not-on-s2v still partial), D7 look `T3-37` |

**Product:** 0 chosen anchors live. Factory is still on step 1.
