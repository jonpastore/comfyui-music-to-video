# PRD · The studio's editing and quality surface (TRD 1-3)

Status: written 2026-08-13. **Rewritten 2026-08-17 for Jarvis #529
(D1–D10).** Covers `docs/TRD-1-TIMELINE-AND-MIXING.md`,
`docs/TRD-2-STORY-ARC-AND-STORYBOARDS.md`, `docs/TRD-3-QC-AND-REMEDIATION.md`.
The product loop is coverage → library → Accept-gated map → per-scene
stills + location plates → LTX → optional decoded s2v hop → LTX refine.
One chosen front sheet as image1 for every scene is the old world.
Design that satisfies it: `docs/DDD-1-3-EDITING-AND-QUALITY.md`.
Built-state lives in those TRD ledgers, not in this file.

**What this document adds, and what it deliberately does not.** The three TRDs
already hold ~133 acceptance criteria, and they are the contract — this does not
restate one of them. What no TRD has is the layer above: who is served, what
counts as the product working, **and what order the work happens in**. Each TRD
names what it does not own; none says what ships first. Sequencing is §6 and it
is the reason this document exists.

Rules inherited from `TRD-6 §0` (`T6-A1`…`T6-A7`) apply throughout and are cited,
never repeated. Prohibitions live in TRD-1 §12, TRD-2 §9 and TRD-3 §10.
`T6-A1`'s four named loops complete over JSON (`test_t6_a1_*`), including
the TRD-4/TRD-7 anchor loop (`test_t6_a1_anchor_loop_over_json`).
`T6-A2` compares HTML and JSON in one test per surface: queue panel
(`test_t6_a2_html_and_json_report_the_same_queue_numbers`), review
queue (`test_t6_a2_html_and_json_report_the_same_review_queue_numbers`),
set editor (`test_t6_a2_html_and_json_report_the_same_set_numbers`,
`T6-A2-set`), storyboard
(`test_t6_a2_html_and_json_report_the_same_storyboard_numbers`,
`T6-A2-storyboard` — same `storyboard_service.payload()` for scene_time /
song_length / clip_seconds / scene_count / mismatch), and album arc
(`test_t6_a2_html_and_json_report_the_same_arc_numbers`, `T6-A2-arc` —
same `arc_service.payload()` for song_count / act_count / premise /
has_proposal), and playlist cards
(`test_t6_a2_html_and_json_report_the_same_playlist_numbers`,
`T6-A2-playlists` — same `playlist_service.numbers()` for song_count /
total_secs; `arc` still only when defined, T2-37; Play column audio /
rating videos stay on the card in `#media-player`), and the library list
(`test_t6_a2_html_and_json_report_the_same_library_numbers`,
`T6-A2-library` — same `library_service.numbers()` for song_count on
HTML `GET /` / `GET /songs` and JSON `GET /api/songs`; `GET /songs` is
200 never 405; the list groups by album and the upload fold is
collapsed when songs exist), and the topbar nav
(`test_uiux_nav.py` / `test_uiux_nav_html_and_json_share_one_list`,
`T6-A2-nav` — same `nav_service.links()` for HTML `base.html` `<nav>`
and JSON `GET /api/nav`; probe monkeypatch mutation).
`T6-A4` is proven for the queue panel
(`test_t6_a4_queue_page_shows_stubbed_values_unmodified`), the jobs panel
elapsed label (`test_t6_a4_jobs_panel_shows_stubbed_elapsed_unmodified`,
`T6-A4-jobs`: `jobs_ctx` owns preformatted `elapsed`; the template does
not `|format`), the storyboard coverage meter
(`test_t6_a4_storyboard_page_shows_stubbed_fill_pct_unmodified`,
`T6-A4-storyboard`: `coverage.fill_pct` is service-owned; the template
does not recompute intent/rendered), and the song generate card replace-span
hint (`test_t8_9_splice_hint.py`, `T6-A4-splice-hint` / T8-9:
`splice_eaten_secs` = `2 * mixer.SPLICE_XFADE` from the route; no
`2 * 0.25` in the template). `T6-A5` is proven for set re-render,
refine, repair and anchor re-roll (`test_t6_a5_*`, `qc_service.listed` /
`select`). `T6-A3` is **built** as `sets_service.py` /
`storyboard_service.py` / `arc_service.py` / `playlist_service.py` /
`cleanup_service.py` / `media_service.py` (`test_t6_a3_*_imports_nothing_from_fastapi`
and the direct-call differentials). `T6-19` song-page cleanup UI is **built**
(`test_t6_19_cleanup_ui.py`): confirmed tiers show the dry-run plan card;
unconfirmed has no delete form. `T6-A7` is **built**
(`test_t6_a7_measurement_can_fail.py`): equal control/mutated is refused;
T6-A4's distinctive stub counts are the product differential.

---

## 1. Who this is for

**One operator, on a tailnet.** The studio has no authentication and the trust
boundary is the bind address and nothing else (`TRD-6 §0.1`). Every requirement
below is written for a single person producing a catalogue, not for a team and
not for a tenant.

The work is albums of music videos. The factory loop is: ceiling-tier
storyboard → coverage list of needed poses → classified library →
Accept-gated pose→scene map → per-scene refs (that keeper + location
plate, picked from a thumbnail slider on the scene row — click opens a lightbox with search, a gallery grid, and a save icon; selecting a result fetch-pins it in place, no reload) → LTX 2.5 first (clips strip + shimmer cards on Render clip; a landed take shows the picture, a play badge, and a trash to delete that take. Prompt boxes load the last selected (else last saved) version after refresh. A still marked stale is older than the last Save Scene — click the chip for what to do; still action icons line up across the strip) → optional decoded s2v hop on lip scenes →
assemble. Identity — one character, recognisably the same across an
album — is the text lock plus her photographs as image1. A stranger
plate as image1 is how this project has most often lost her.

## 2. The product, in one sentence

TRD 1-3 are the three surfaces where a **human decides**: the set timeline
decides what an audience hears, the arc and storyboards decide what the album is
about, and QC decides whether what came back is what was asked for.

Everything else in the studio is machinery that runs unattended. These three are
not, and they fail differently: machinery fails loudly, a decision surface fails
by *looking right*.

## 3. The product rule that outranks every other requirement

**The editor must not promise what the renderer does not produce.**

Day 4's Traps section, found and fixed six times, and all three of these surfaces
are editors sitting over a renderer. The three named product problems are each
one instance of it:

| surface | the problem today | source |
|---|---|---|
| set timeline | forms remain; a server-rendered `.tl-axis` tracks `set_duration()`; `.tl-join` / `.tl-playhead` / `.tl-lanes` are HTML on that clock (POST `/join` writes secs; stored curves draw; easy omits lanes); waveform is still a PNG (`mixer.waveform_png`) | TRD-1 §1 |
| arc & storyboards | songs are storyboarded independently, so an album is twelve unrelated stories that share a character; `scene_seconds` could not lengthen a scene and nothing in the UI revealed it | TRD-2 §1 |
| QC | nothing checks output. The identity collapse, the world that never rendered and the LoRA that did nothing all passed every deterministic check and were found by opening the picture | TRD-3 §1 |

A second rule follows from the third row and applies to the whole of TRD-3:
**a number that has not been shown to separate known-good from known-bad gates
nothing.** A confident green tick on a render nobody looked at is worse than no
check at all — that is TRD-3 §1's measured 41.1-vs-64.7 inversion, where a
plausible metric ranked the wrong image first.

## 4. The three journeys

Stated as journeys because `T6-A1` requires each one to be drivable over JSON
with no HTML involved, and it names these three as the loops to prove it with.

**A · Build a set and render it.** Add songs, insert a title card as its own
item (`T1-27`/`T1-28`: `[song A][ MEOW P — 3s ][song B]`), drag the joins,
draw a level curve, hear a proxy, render a real 20-second preview of one join,
render the whole thing — and the length shown while editing is the length of
the file. A card is a beat in the running order, not a decoration on one.

**B · Give the album a story, cover the poses, then bind.** Write or
generate an arc; a proposal is not on disk until accepted (`T2-15`).
Generate each song's ceiling-tier storyboard as a scene *of that arc*.
**Analyze** writes a coverage list (`T2-50`) — it does not bind.
Review the classified library; expand missing poses at the ceiling
(`T4-24`). **Map** drafts keeper → scene; the operator Accepts per
scene (`T2-52`), same shape as the arc wand. Generate refs only from
accepted bindings, with that scene's keeper as image1 and the location
plate when the scene has one (`T2-56`, `T2-53`). `needs_lip_sync`
sits beside camera (`T2-55`). Playlist and song forms stay in-page
(htmx fragment swap; no full reload). No wizard.

**C · Find out what came back wrong.** After renders land, a queue of findings,
each carrying what was measured against what was asked for, an editable remedy
prompt, and an approve button. Nothing repairs itself. The approve-grid Fix
control is a dialog (Use this face / paint a spot / extend), not an inline
form that names image-1 slots. The approve grid is scene stills and scene prompts. Video chopping is
automatic; last-frame chain is T2-10/T2-11. A candidate can be deleted.
A thumb opens a full-size preview dialog.

## 5. What "working" means

Product outcomes, each with the TRD criterion that already proves it. These are
the eight things that must become true; they are not a new contract.

| # | outcome | proven by |
|---|---|---|
| P1 | The number on the screen is the number in the file — set length, to 0.05 s, with echo, hold, beatmatch, trim and an interstitial card all in play; each join lands where the model says, within half a frame, measured on the rendered file | `T1-7`, `T1-8`, `T1-27`, `T3-11` **built** (`qc.check_set` on the artefact; `test_t3_11_set_duration.py`), `T3-12` **built** (`test_t3_12_transition_lands.py`) |
| P2 | A drawn curve reaches the audio, and is not normalised away two stages later | `T1-9a`, `T1-9b` **built** (`mix_audio` RMS/s slope on a constant sine), `T1-10` **built** (full-lane `fragment` ≤ 8 KB and renders), `T1-12` **built** (`pan` by L/R energy, `lowpass_hz`/`highpass_hz` by band energy), `T1-20d` |
| P3 | Every surface is drivable with no browser, and the page and the JSON agree. A re-render, refine, repair or anchor re-roll leaves predecessor and successor both listed and selectable | `T6-A1`…`T6-A5`, `T1-3` **built** (JSON `POST /api/sets/{id}/render` and UI `POST /sets/{id}/render` emit the same `mixer.render_set_argv`; outputs agree on duration, frames, LUFS), `T1-4` **built** (mutate stored `gain_db`; next `mixer.render_set_graph` changes), `T2-41` |
| P4 | An album's songs are scenes of one story, demonstrably — arc content appears in the storyboard and is absent when the arc is; at xxx no scene prompt carries the mainstream lock and the tier's own wording does; the board's guardrail field is this tier's clause and save refuses another tier's wording | `T2-20`, `T2-21`, `T2-22` |
| P5 | Requested clip length is honoured end to end: `scene_seconds` in, a legal frame count out, the approve grid showing every **scene**, a re-plan leaving approved `(clip_idx, seed)` unchanged, the planner prompt not naming a fixed 4.8125 s quantum, its clip-length text derived from planning, TIMING still stating track length and sum-to-track, generated scenes tiling `[0, duration]` with no gap or overlap, and a larger `scene_seconds` never returning more scenes | `T2-8`, `T2-8b`, `T2-9`, `T2-12a`, `T2-13a`, `T2-13b`, `T2-13c`, `T2-14a`, `T2-14b`, `T2-14c` |
| P1 | The number on the screen is the number in the file — set length, to 0.05 s, with echo, hold, beatmatch, trim and an interstitial card all in play | `T1-7`, `T1-8`, `T1-27`, `T3-11` |
| P2 | A drawn curve reaches the audio, and is not normalised away two stages later | `T1-9a`, `T1-9b` **built** (`mix_audio` RMS/s slope on a constant sine), `T1-12` **built** (`pan` by L/R energy, filter lanes by band energy), `T1-20d` |
| P3 | Every surface is drivable with no browser, and the page and the JSON agree | `T6-A1`…`T6-A4`, `T1-3`, `T2-41` |
| P4 | An album's songs are scenes of one story, demonstrably — arc content appears in the storyboard and is absent when the arc is; the board's guardrail field is this tier's clause and save refuses another tier's wording | `T2-20`, `T2-21`, `T2-22` |
| P5 | Requested clip length is honoured end to end: `scene_seconds` in, a legal frame count out, the approve grid showing every **scene**, a re-plan leaving approved `(clip_idx, seed)` unchanged, a plan that misses the track by more than one clip refused before render, the planner prompt not naming a fixed 4.8125 s quantum, its clip-length text derived from planning, TIMING still stating track length and sum-to-track, and a larger `scene_seconds` never returning more scenes | `T2-8`, `T2-9`, `T2-12a`, `T2-13a`, `T2-13b`, `T2-13c`, `T2-13e`, `T2-14a`, `T2-14b`, `T2-14c` |
| P5a | Assembling a song with a 1664×960 clip among 832×480 siblings keeps the ×2 size and does not letterbox; mixed aspect is refused | `T5-7` |
| P5b | Every clip of one song is normalised to one output fps, asserted on the assembled file | `T2-13d` |
| P5c | A scene longer than the 15 s LTX ceiling becomes a clip chain; clip N+1 starts on clip N's last frame | `T2-10` |
| P6 | Every rendered artefact is measured against the workflow that asked for it, never against a constant. A mixed-model clip is judged at its native fps, not the song's output fps. An interpolated clip is judged at RIFE `(n-1)*m+1` frames and `make_postproc.out_fps`, not `n*m` / `fps*m`. A silent or near-silent take is rejected on measured low/mid/high band energy, not peak volume. A take with DC offset above `DC_OFFSET_LIMIT` is flagged. An assembled song's clip count is judged against `len(build_song.clip_plan)`, not `scene_count` | `T3-2`, `T3-4`, `T3-7`, `T3-8`, `T3-9`, `T3-4.3-dc`, `T3-4.4-nclips` **built** (`test_t3_4_4_nclips.py`), `T2-13f` |
| P7 | A finding arrives actionable — measured, expected, unit, a remedy class, and an editable prompt — and nothing runs without approval. A dismissed finding stays off the queue until the artefact itself changes. The remedy that RUNS is the stored prompts row. Approving produces a new candidate; original and repair are both listed and scored | `T3-18`, `T3-19` **built** (`GET /qc` finding-row + `test_t3_19_finding_row.py`: two HTML approvals submit two jobs), `T3-20`, `T3-21`, `T3-22`, `T3-27` |
| P8 | Identity is the text lock plus her photographs as image1. Empty `character_reference` is refused. A stranger plate as image1 is refused. Identity-wrong remedy is edit the text, not swap a stranger plate | `T2-31`, `T2-32`, `T2-56`, `T3-17`, `T3-28`, `T3-35` |
| P9 | A board produces a coverage list of needed poses; classify does not write the pose→scene map | `T2-50`, `T2-51` **built** |
| P10 | Scene refs generate only from an accepted map row; one chosen front is not image1 for every scene | `T2-52` **built**; `T2-56` **built** |
| P11 | One location plate per location key, reused; unset/studio has no plate | `T2-53` **built** (`test_t2_53_location_plates.py`) |
| P12 | Ceiling + ticked-lower backfill: r+pg13 writes both; r-only does not write pg13; g ceiling writes no nude | `T2-54` **built** (`test_t2_54_ceiling_backfill.py`); `T4-24` **built** |
| P13 | Every scene is LTX first. Marked lip scenes then the decoded s2v hop. D7 look harness only; NOT MEASURED until a GPU pair | `T2-55`, `T5-11`, `T5-12`, `T5-13`, `T3-37` |
| P8a | An image FLAG/REJECT content finding's remedy is the next prompt rewrite, not "re-render with a different seed". Identity-wrong already said "edit the text"; blank, uniform, transparent, lighting and portrait findings say the same | `T3-28`, `T3-33.a` |

**P8 is the one to defend hardest.** D10: text names species/body;
image1 is her photographs; a plate that is not her is refused. The
2026-08-12 differential still holds: same photos, same seed, species
named or not — named gives a feline throughout, unnamed gives an
ordinary human woman by the halfway point keeping only the harness.
The missing half is: photos omitted or a stranger plate as image1 →
also a stranger, even with perfect text. A remedy that proposes
swapping in a stranger plate teaches the operator a false lesson,
which is why `T3-28` forbids it by name. Using **her** photos as
image1 is required (`T2-56`). `T3-33.a` still says image FLAG/REJECT
content findings are edit-text; `T3-35` **built**
(`test_t3_35_settings_remedies.py`) adds settings remedies
(latent / denoise / CFG / pose-match / plate-absent / body-colour).
`T2-31` **built** still refuses an empty `character_reference`. `T2-32`
**built**: the shipped message names both halves — not "the text, not
the photo".

**P9 is partial.** `T2-50` **built** (`test_t2_50_coverage_list.py`):
analyze writes `(pose, view, wardrobe, exposure)` per scene and no
map/refs rows. `T4-21`/`T4-22` classification_json in sqlite **built**
(`test_t4_21_classification_json.py`). `T4-23` gap-vs-board **built**
(`test_t2_51_classify_cannot_write_map.py`): ceiling needs vs keepers,
holes only, no `scene_pose_map`. `T4-24` ceiling-tier pose generate
**built** (`test_t4_24_ceiling_generate.py`): holes → studio jobs at
the run ceiling; clothed+nude iff r/xxx; g/pg13 clothed only, no
anatomy. `T7-21` C1/C2 resolver **built** (`test_t7_21_c1_c2_resolver.py`).
`T3-34` **built** (`test_t3_34_pose_still_qc.py`): those C1/C2
`source=pose-gap` landings call `score_candidate` and store `qc_json`.
`T3-36` **built** (`test_t3_36_image_latent_size.py`): image-latent
sheets that inherit source WxH do not `resolution` REJECT.
`T2-51` **built** (`test_t2_51_classify_cannot_write_map.py`):
classify + gap write zero map rows; `POST .../pose-map` drafts
`status=draft`. `T2-52` **built** (`test_t2_52_map_accept.py`):
Accept/Reject per scene; `start_refs` refuses draft/rejected;
accepted writes a still. **P10 is built** (`T2-56` —
image1 is that scene's accepted keeper;
`test_t2_56_per_scene_keeper.py`). Location plates (`T2-53` **built**,
`test_t2_53_location_plates.py`). Extra-view slots are later. **P11 is built**. **P12 is built** (`T2-54` board backfill,
`test_t2_54_ceiling_backfill.py`; generate half `T4-24`; C1/C2
`T7-21`). **P13 is partial**: `T5-11` / `T2-55` / `T5-12` graph / `T5-13`
`skip_first_frames` **built** (`main()` hop emit + `test_t5_13_s2v_window.py`);
D7 look `T3-37` **harness only; NOT MEASURED**
(`qc.t3_37_*` + `test_t3_37_d7_look.py`; no GPU pair;
`T3_37_REAL_PAIR_MEASURED` False; warm-px and silent hop omit
refused). Anchors-on-model and this loop beat the timeline (`§6.0`).
Do not mark a row built until the named test can go red.

## 6. Sequencing — the part the TRDs do not have

Each TRD disowns what it does not cover; none of them orders the work. This is
that order. Every edge below is a real dependency taken from the documents, not
a preference.

### 6.0 What Jon decided, 2026-08-13

Asked which capability he wanted next, in his own terms rather than by criterion
id, and the answer re-orders everything below:

1. **Anchors that stay on-model** and the **#529 loop** (coverage →
   library → Accept-gated map → per-scene refs + location plates → LTX
   → optional s2v hop). This beats the timeline. 0 chosen studio
   anchors live — the factory is still on step 1.
2. **Know when a sheet or clip is wrong** — QC's repair path plus
   pose-before-anatomy (`T3-33.b`) and the D7 look (`T3-37`,
   harness only; NOT MEASURED). Image FLAG/REJECT is a prompt
   rewrite (`T3-33.a`); settings remedies are `T3-35` **built**
   (`test_t3_35_settings_remedies.py`).
3. **Clips at the length you asked for** — song length still owns clip
   count. LTX first (`T5-11`); s2v is a hop, not a skip.

**The set timeline went last and is now built** including peaks-from-data
and the on-demand loudness meter. §6's P1 below was written with the
timeline first and is superseded by this list.

**The queue is rewritten in full**, not reduced to its one blocking column. Asked
whether to take just `T6-13a` and leave working machinery alone, Jon chose the
full pull-based queue. So TRD-6 §1-§6 is in scope, `T6-13a` still goes first
inside it because the clip-length chain waits on it, and the plan's Phase F is no
longer the phase to defer — `docs/PLAN-TRD-4-7.md` §4 is updated to match.

### Already built and deployed (do not rebuild)

**`T2-11` built** — a chained clip (T2-48 over-ceiling scene split) is not
ready until its predecessor has landed: `start_clips` → `enqueue_clips`
wires `depends_on` per clip; T6-2 `_claim` skips the successor until the
predecessor is done (`test_t2_11_clip_chain_depends.py`). Under-ceiling
songs still enqueue one batch `clips` job.

`studio/qc.py` (TRD-3 tier 1 in full; **`T3-4.1-opens` built** —
image `opens` via PIL: missing/unreadable REJECTs, real PNG is not an
opens reject, no image size floor (`test_t3_4_1_opens.py`);
**`T3-4.1-resolution` built** —
image `resolution` via PIL size when `expect.width`+`height` are set:
matching WxH PASSes, downscaled REJECTs with unit `px` (not `None`),
no expect emits nothing, `test_t3_4_1_resolution.py`;
**`T3-36` built** — `check_image` `resolution` PASSes inherited
source WxH when `expect.latent==image` (1024×1024 vs 896×1216 is not
REJECT); empty/absent latent still exact-match REJECTs
(`test_t3_36_image_latent_size.py`);
**`T3-4.1-alpha` built** — image
`alpha` / `measure_alpha`: fully transparent RGBA REJECTs, RGB and
opaque/partial alpha PASS, unit `levels`, `test_t3_4_1_alpha.py`;
**`T3-4.1-not_uniform` built** —
image `not_uniform` / `measure_pixel_std` REJECTs solid flat colour
(max per-channel spatial std ≤ `UNIFORM_STD_FLOOR`), PASSes testsrc2,
`test_t3_4_1_not_uniform.py`; **`T3-4.1-not_blank` built** —
image `not_blank` / `measure_mean_level` REJECTs solid black below
`LUMA_FLOOR`, PASSes testsrc2, distinct from `not_uniform` (solid bright
red PASSes not_blank), `test_t3_4_1_not_blank.py`; **`T3-4.2-luma` built** — clip
`luma` / `measure_luma` REJECTs solid black below `LUMA_FLOOR`, PASSes
testsrc2, `test_t3_4_2_luma.py`; **`T3-4.2-sat` built** — clip
`channel_sat` / `measure_channel_sat` FLAGs solid green garbage (NaN
encode mode) above `CHANNEL_SAT_LIMIT`, PASSes testsrc2/gray/black,
`test_t3_4_2_sat.py`; **`T3-4.2-black_frames` built** — partial black while mean PASSes FLAGs `black_frames`, `test_t3_4_2_black_frames.py`; **`T3-4.2-size_floor` built** — clip under `MIN_VIDEO_BYTES` REJECTs, `test_t3_4_2_size_floor.py`; **`T3-4.2-opens` built** — unreadable / no-video-stream REJECTs `opens` (post size floor; demo never hit), `test_t3_4_2_opens.py`; **`T3-4.2-luma` built** — mean luma below `LUMA_FLOOR` REJECTs, `test_t3_4_2_luma.py`; **`T3-4.3-opens` built** — audio `opens`: missing/unreadable/no-audio-stream REJECTs, real take not opens-rejected, `test_t3_4_3_opens.py`; **`T3-4.3-duration` built** — audio duration as requested within `DURATION_TOL_S`, `test_t3_4_3_duration.py`; **`T3-4.3-loudness` built** — `check_audio` FLAG/PASS via `effects.measure_loudness`, `test_t3_4_3_loudness.py`; **`T3-4.2-resolution` built** — clip `resolution`
vs workflow width/height via `mixer.probe`: matching WxH PASSes,
downscaled REJECTs with unit `px`, no expect emits nothing,
`test_t3_4_2_resolution.py`; **`T3-4.2-fps` built** — clip `fps` vs
workflow request via `mixer.probe` within `FPS_TOL`: matching PASSes,
retimed FLAGs with unit `fps`, no expect emits nothing,
`test_t3_4_2_fps.py` (RIFE out_fps is `T3-8`); **`T3-4.2-duration` built** — clip
`duration` vs workflow frames÷fps via `mixer.probe` within `DURATION_TOL_S`:
matching PASSes, wrong length REJECTs with unit `s`, no expect emits nothing,
`test_t3_4_2_duration.py` (was demo-only; song mp3 is `T3-4.4-mp3`, audio is
`T3-4.3-duration`); **`T3-4.2-frame_count` built** — clip
`frame_count` vs workflow request via `qc._ffprobe_frames`: matching PASSes,
81-vs-505 REJECTs with unit `frames`, no expect emits nothing; not `T3-7`
`latent_8n1`, `test_t3_4_2_frame_count.py` (was demo-only); **`T3-4.3-sr` built** — `check_audio` sample
rate as requested via `mixer.probe`: matching Hz PASSes, mismatch
REJECTs, no expect emits nothing, `test_t3_4_3_sr.py`; **`T3-4.3-true-peak` built** — `check_audio` true peak vs `effects.LOUDNORM_TP` (+`TRUE_PEAK_TOLERANCE_DB`) via `effects.measure_loudness`: under PASSes, over FLAGs, missing Peak FLAGs, `test_t3_4_3_true_peak.py`; **`T3-4.3-ch` built** — `mixer.probe` exposes
`channels`; `check_audio` `channels` when `expect.channels` is set
(stereo vs 2 PASS, mono vs 2 REJECT, unit `ch`), `test_t3_4_3_ch.py`;
**`T3-4.3-clip` built** — audio
`clipped_samples` / `measure_clipped_samples` counts s16 rails; clean
sine PASSes 0, hard-clipped takes FLAG, `test_t3_4_3_clip.py`;
**`T3-4.3-dc` built** — audio `dc_offset` /
`measure_dc_offset` FLAGs abs mean sample above `DC_OFFSET_LIMIT`
(0.02 FS), PASSes a clean tone, `test_t3_4_3_dc.py`;
**`T3-4.3-edge` built** — `edge_silence` /
`measure_edge_silence` FLAGs leading or trailing null pad above
`EDGE_SILENCE_LIMIT_S` (0.25 s), PASSes a clean tone and a 0.15 s pad,
distinct from T3-9 whole-file band energy, `test_t3_4_3_edge.py`;
**`T3-3` built** — silent LTX clip does not emit `has_audio`;
assembled song with no audio stream REJECTs `has_audio` (re-assemble);
`test_t3_3_has_audio.py` (was demo-only / clip-skip half of av only);
**`T3-4.4-av` built** — assembled-song
`av_sync` / `measure_av_durations`: matching A/V streams PASS within
`DURATION_TOL_S`, a 1s gap FLAGs, clips without `want_audio` skip,
`test_t3_4_4_av.py`; **`T3-8` built** — `expect_interpolated`
owns RIFE `(n-1)*m+1` + `make_postproc.out_fps`; duration/fps/frame_count
PASS on a compensated clip, latent exemption alone is not enough;
`test_t3_8_interpolated.py`; **`T3-9` built** — silence is
`measure_band_energy` low/mid/high mean, not peak `volumedetect`;
`test_t3_9_silence.py`; **`T3-10` built** — spliced-track duration vs
`mixer.spliced_duration` / `bridge_seconds` within
`mixer.SPLICE_DURATION_TOLERANCE`, `test_t3_10_splice.py`; **`T3-11` built** — `check_set` / `qc.run(kind="set")` compares the artefact to `mixer.set_duration()` within `mixer.SET_DURATION_TOLERANCE`, `test_t3_11_set_duration.py`; **`T3-4.4-mp3` built** — assembled song duration vs `songs.duration` / source mp3 within `DURATION_TOL_S`; mismatch REJECTs on the media (`test_t3_4_4_mp3.py`); **`T3-4.4-gap` built** — no black gap at an assembled song join (`qc.check_join_black_gap` / `test_t3_4_4_gap.py`: hard cut PASSes, black insert on a planned join REJECTS)), `studio/qc_service.py` + `db.findings` +`/api/qc/*` including `GET /api/qc/by-host` (`T3-1`) and dismiss/reopen on
artefact change (`T3-22`), `GET /qc` finding-row (`T3-19`: measured /
expected / unit, editable remedy, approve; `test_t3_19_finding_row.py`),
`qc_service.run_song` (`T3-32`: tier 1 over a song
completes without a GPU, a backend, or the one worker thread), `studio/automation.py` + `db.automation` (TRD-1 §5's curve model,
decimation and filter emission; `T1-1` **built** — reorder or trim
leaves stored `(lane, t, value)` unchanged, asserted on non-empty
rows; `T1-9b` **built** — a stored −12→0 dB
ramp's RMS/s slope survives `mix_audio` within
`mixer.GAIN_CURVE_SLOPE_TOLERANCE`; `T1-10` **built** — a `MAX_POINTS`
lane's `fragment` is ≤ `FILTER_EXPR_MAX_BYTES` (8 KB) and `mix_audio`
accepts it; `T1-11` **built** — POST of two
points at the same `t` is 400 and names that `t`; `T1-12` **built** — drawn `pan` / `lowpass_hz` /
`highpass_hz` change the `mix_audio` file), `studio/arc.py` + the arc routes (TRD-2 §3.1's
JSON-canonical arc), `db.artefacts` (tier 0), `prompts.py` (TRD-2 §3.3's
versioning, reused by `T3-20`; **`T2-5` built** — edit is a new `arc`
version and restore puts the previous text back). TRD-3 §2.1 is explicit that §4 and §6 "read as
unbuilt work and are not" — the ledger with line counts is DDD §1.

### P0 — unblock, then separate

1. **`T2-12a` — round a scene length to a legal frame count.** Landed for the
   divisor: `clip_seconds(scene_seconds)` is `legal_frames / LTX_FPS`, and
   `n_clips_for` is `ceil(duration / that)`, so song length owns clip count.
   `None` stays `CHUNK` — a storyboard written before the column does not
   re-time. The renderer honours that length (`T2-13a`): latent frames and
   audio trim follow the legal count, not `LTX25_LEN`/`CHUNK`. `T2-13c`
   is **built**: the approve grid lists every scene (`clip_chain_plan`
   heads). A 20-scene storyboard on a 195 s song is 20 tiles, not 41
   4.8 s slices. `T2-13e` is **built**: `clip_plan` refuses
   before render when planned clip durations miss the track by more
   than one clip; assemble still clamps to the track and no longer
   treats a 4.8125 s overrun as the norm. **refs-length built**:
   `clip_plan`'s audio-only default is `n_clips_for(track,
   length_seconds)`, not `ceil(track / CHUNK)`, so `build_refs` /
   `reroll_refs` emit one still per scene (`--heads`), not a CHUNK-era count.
   **Per-clip expect built**: each ref graph writes
   `clip_NNN.expect.json` with `clip_seconds` / `legal_frames` for that
   scene (not CHUNK); `pipeline.gen_refs` stamps it
   (`test_t2_refs_clip_seconds.py`).
2. **The service split**, TRD-1 and TRD-2 (`T6-A3`) — **built** as
   `sets_service.py` / `storyboard_service.py` / `arc_service.py` /
   `playlist_service.py` / `cleanup_service.py` / `media_service.py` (same
   shape as `qc_service.py`; `test_t6_a3_*_imports_nothing_from_fastapi`).

### P1 — SUPERSEDED BY §6.0, kept for its dependency edges

**Read §6.0 first: Jon put the timeline LAST.** This block was written with the
timeline first and its ORDER no longer holds; its *edges* still do, which is why
it is not deleted — the master stage really is a prerequisite for automation
being usable, and audiences really do need the master. Follow §6.0's capability
order and take the dependencies from here.

3. Clock and rounding (`T1-5` **built** as video xfade/layer/black offset via `mixer.frame_round`, audio on the stored second, `studio/test_t1_5_off_grid_join.py`; `T1-6` **built** as `mixer.rounding_report` / `GET /api/sets/{id}` `rounding.abs_delta_sum` ≤ half a frame per join); peaks and the waveform data model
   (`T1-13`/`T1-14` **built** as `mixer.peaks`; `T1-15` empty-reason **built**
   as `{pairs, reason}` on `peaks_from_path` / `GET /api/songs/{id}/peaks`);
   the proxy-preview contract (`T1-16` **built** as `mixer.preview_proxy` /
   `GET /api/sets/{id}/preview` `{is_proxy, not_applied}`; `T1-17` **built**
   as `mixer.render_preview` / `GET /api/sets/{id}/preview/render?at=&secs=`
   `{is_proxy: false}` — the only preview that claims accuracy.
   `waveform_png` stays the picture).
4. The master stage (`T1-20a`…`T1-20d`). It is a prerequisite for automation
   being *usable*, not an enhancement: without it, per-item `loudnorm` flattens
   every curve `automation.py` can already store and render.
5. Audiences (`T1-18`…`T1-20`). **Built**: `sets.mode_audience`
   persists; switching easy→advanced→easy does not rewrite `set_items` or
   automation; easy and advanced return different affordance sets; easy
   engages the existing master (`mixer.master_engaged`) so a set with
   per-item defaults cleared lands within 1.0 LU of `effects.LOUDNORM_I`
   and the same set with easy off does not. **`T1-19` built** — easy's
   one-button master is the named chain `one-button-master` v1, recorded
   on the render (`assets.meta_json.master_chain`); changing I moves
   measured loudness. **`T1-25` built** — an export names measured
   integrated loudness and true peak on `assets.meta_json.loudness`;
   a render outside `effects.LOUDNESS_TOLERANCE_LU` /
   `TRUE_PEAK_TOLERANCE_DB` of its own target is flagged.
   **`T1-3` built** — JSON `POST /api/sets/{id}/render` and UI
   `POST /sets/{id}/render` emit the same `mixer.render_set_argv` for
   the stored set; extra form fields on the UI POST are ignored; the
   two encodes agree on duration, frame count and integrated loudness.
   **`T1-24` built** — an export format is a row of
   `mixer.EXPORT_FORMATS`; a test-only row is rendered through ffmpeg
   (`studio/test_t1_24_export_format_row.py`). The table is not
   display-only.
   **`T1-4` built** — mutate stored `gain_db` and the next
   `mixer.render_set_graph` from `_set_render_items` changes; a cached
   ffmpeg string would stay put.

### P2 — the arc through to the storyboard

6. `T2-8b`/`T2-8c` tiling and section coverage, then the wand flows (§4.1–4.3),
   the time meter (§5.1), casting (§5.3). **`T2-8b` built**: `_compose`
   stamps scene `start`/`end` so they tile `[0, duration]`; `validate`
   refuses a gap or overlap (`test_t2_8b.py`). **`T2-5` built**: editing the
   album's arc prompt creates a new version; restore puts the previous text
   back (`test_t2_5_arc_prompt_restore.py`). **`T2-6` built**: delete drops
   the row and does not renumber survivors
   (`test_t2_6_delete_does_not_renumber.py`). **`T2-7` built**: a generated
   arc version records the model that was asked and a timestamp between the
   call's start and end (`test_t2_7_provenance.py`). **`T2-14`/`T2-15`/`T2-16` built**:
   the arc wand refuses an empty theme and runs with a non-empty one; reject
   leaves the previous committed file; accept saves; applying more than one
   song needs confirmation and then writes exactly those songs
   (`test_t2_14_arc_wand.py`, `test_t2_16_multi_song_apply.py`).
   **`T2-20` built**: a distinctive
   arc string appears in the generated board and is absent when the arc is.
   **`T2-21` built**: at `xxx`, no scene `image_prompt` or
   `video_motion_prompt` carries the mainstream lock, and the tier's
   own permission wording is in the scene text (`rear-entrance_xxx.json`).
   **`T2-22` built**: the generated board's `guardrail` field is
   `compose_guardrail(tier)` verbatim, and save refuses another tier's
   wording. **`T2-23` built**: `GET .../meter` reports total scene time
   against song length and flags a miss beyond `SCENE_TIME_TOLERANCE`.
   **`T2-24` built**: the same meter reports this song's `clip_seconds`
   from `build_song.clip_seconds(scene_seconds)`; 15 s and 30 s on one
   song yield two lengths. **`T2-33` built**: a model added to the
   catalogue appears in the song page video-model picker with no template
   change (`test_t2_33_picker_renderable.py`); a picker that calls
   `renderable()` and discards it fails that. **`T2-8c` built**: every
   scene names the lyric sections it spans; unnamed or double-named
   fails validate (`test_t2_8c.py`). **`T2-25` built**: a scene-time
   miss is 400 before clips enqueue; in-tolerance still queues
   (`test_t2_25_scene_time_enqueue.py`). **`T2-34` built**: the
   clip-pass picker marks a model `where()` says False on every
   reachable backend as unavailable and still offers a confirmed one
   (`test_t2_34_unavailable_shown.py`). **`T2-17` built**:
   `GET /api/songs/{id}/storyboard/{tier}` returns the generation prompt
   defaulted from the tier (`storyboard_generation_payload`); POST accepts
   an edit. The song-page Generate control is the same enqueue over
   `Accept: application/json` (no full-page submit); `GET /api/songs/{id}`
   is the card refresh. **`T2-18` built**: the same response carries the enforced
   `max_characters` and PINNED flags; one character over that cap is 400
   quoting it (`test_t2_18_storyboard_limits.py`). **`T2-19` built**: two
   different edited prompts against the same recorded response yield two
   different storyboards (`test_t2_19_edited_prompt_generates.py`).
   song yield two lengths. **`T2-26` built**: `GET .../storyboard/{tier}`
   returns the album's chosen anchor images grouped per character
   (`anchors[].character` / `images[]` with `path` and `url`), so a
   client can show the strip without the HTML page.
   **`T2-27` built**: each `scenes[]` object on
   `GET .../storyboard/{tier}` carries `refs` (`path` / `url` per clip)
   next to the editable description. Another scene's still is not this.
   **`T2-29` built**: every named scene figure
   carries `lead` / `extra` / `background`; `GET .../cast` returns
   `role`; save/write refuses an unclassified or free-text role.
   **`T2-30` built**: unanchored warning lists only leads
   (`test_t2_30_unanchored_leads_only.py`); extras/background without
   an anchor are silent.
   **`T2-49` built**: storyboard generate is offered every album
   character (Tiger, Panther, …) even when that character has no chosen
   front yet. Those names are the only leads besides the protagonist.
   Extras and background may be invented and do not need poses or
   anchors (`test_t2_49_album_leads.py`). The generate form lists them
   and whether this tier has an identity front.
   **Cast slots built**: named leads with chosen sheets occupy leftover
   ref slots (image3 when a pose plate holds image2); extras/background
   never take those slots even with a sheet
   (`test_cast_slots_only_leads_with_chosen_sheets_take_image2_and_image3`).
   **`T2-51`/`T2-52` built**: draft map + Accept per scene
   (`test_t2_51_classify_cannot_write_map.py`,
   `test_t2_52_map_accept.py`). `start_refs` refuses draft/rejected.
   **`T2-56` built**: accepted keeper for that scene is image1
   (`test_t2_56_per_scene_keeper.py`); keepers are not also stuffed
   into pose_bases/image2. Location plates (`T2-53` **built**,
   `test_t2_53_location_plates.py`).
   The row's Pinned / Suggested UI can stay as the Accept
   surface. Scene stills and clips sit in a labeled preview table;
   reroll N stills, pick one, then render the first LTX clip before
   the rest of the scene. Wardrobe in the prompt is allowed. QC
   reports **confidence** and an **identity assessment** of physical
   attributes (face, fur, body, anatomy) — not clothes.
   **`T2-28` built**: storyboard Generate refs is marked (`button.blocked`)
   not disabled, the plan panel names the unanchored lead, and
   `POST /songs/{id}/refs` 400s before enqueue
   (`test_t2_28_html.py`, `test_t2_28_refs_unanchored_leads.py`);
   extras/background do not block. Named pose sheets are not the identity
   front: the song page says *N pose sheets · missing identity front*
   instead of *no anchor* when the library is full and `view=front` is not
   chosen.
   **refs-identity built**: per-clip refs condition on the chosen
   sheet as image1 (identity), not a standing 4748 plate; each ref is
   scored against that chosen path (`test_t2_refs_identity.py`).
7. Per-scene model choice, W2 (`T2-42`…`T2-48`) — last, because `T2-45` needs
   `models.where()`'s three-valued answer respected at enqueue and `T2-48` needs
   per-model ceilings, which is P0 item 1 again. The renderer half of those
   ceilings is `T5-9`: labeled measured vs chosen, and an over-long single
   clip is refused or split. The planner divisor is unchanged.
   **`T2-47` built**: hop 0 is LTX even when a scene is marked `s2v`
   (`T5-11` **built**, `test_t5_11_ltx_always_first.py`). One
   `build_song.main()` job with `needs_lip_sync` writes LTX hop0
   `.expect.json` 81@`LTX25_FPS` and s2v hop `.expect.json` 77@16.0;
   they differ (`test_t2_47_mixed_model.py`). Two names on a plan is
   not this check.
   **`T2-48` built**: hop 0 splits a 30 s scene on the LTX ceiling
   even when marked `s2v`; a 30 s `needs_lip_sync` scene is LTX 15+15
   plus per-part s2v windows (`clip_chain_plan` / `split_to_ceiling(s2v)`;
   `test_t2_48_ceilings_compose.py`). T5-12 hop graph **built**
   (`test_t5_12_d7_hop.py`).
   **`T2-45` built**: a mixed-model song is refused before enqueue when
   any named model is `False` on every reachable backend
   (`test_t2_45_enqueue_unavailable.py`); `None` stays a candidate.
   **`T2-42` / `T2-43` built**: a scene may carry `video_model`;
   absent, the job `--video-model` applies. It lives beside `camera`
   on the storyboard, is editable through `EDITABLE_SCENE_FIELDS`,
   and is readable over JSON (`test_t2_42_scene_video_model.py`).
   **`T2-44` built**: a scene naming a model absent from
   `models.renderable("video")` is refused at save, naming the scene
   and the value (`test_t2_44_unknown_model.py`); not defaulted, not
   deferred to render.
   **`T2-46` built**: a scene requesting `ref_motion` or `control_video`
   pins that clip to cerberus (`LoadVideosFromFolder` / kjnodes); the
   rest of the song still free-draws (`test_t2_46_driving_pins_cerberus.py`).
   **`T2-13f` built**: QC judges each of those clips at its native fps, not the song's (`test_t2_13f_native_fps.py`); comparing against the song rate flags the other model.

### P3 — QC tier 2 and repair

8. Tier 2, **calibration first and in this order**: `T3-13` scores the 18
   images of `zimage_sweep/` and stores overlap, separation and every file
   on a `calibrations` row with no threshold. `T3-14` can set a threshold
   on that row and refuses without one, naming why. `T3-15` ranks the
   recorded pose pair (histogram, not pixel distance). `T3-16` names
   overlap inconclusive and does not build a gate; that is a successful
   outcome. `T3-17` is **built**: identity drift is scored per artefact
   against the chosen anchor, whatever caused it — a non-empty reference
   plus text that does not name the species still scores. Tier 1 cannot
   see the score. `T3-17-ui` is **built**: compliance, variation and n
   are visible on the QC finding-row surface (still no gate, no
   threshold control).
9. Repair routing (`T3-23`) is built: `dispatch_repair` asks `where()` /
   `fits()` / `resolve()`, refuses a mis-named pin before submit, and
   dest is the `fix_ref` / `gen_postproc` file. `T3-24` is built: the
   refiner's resident cost (~19.6 GiB), not the UNET's 13.31, routes it
   off a 15.92 GiB card onto a 24 GiB one; peaches cannot take the pair.
   `T3-25` is built: `can_move_output` refuses remote repair by name
   until the check is true; forcing it true SUBMITS. `T3-26` is built:
   whether the refiner helps is a fail-closed labelled-set measurement
   (`qc.measure_refiner_help`), not the catalogue's `opportunistic` tag;
   a pass that does not improve the tier-2 score is a finding that says
   not helping. `T3-20` is built:
   the approved remedy that RUNS is the stored `prompts` row, same id,
   read back after approval — a copied string on the job is not what
   the actuator receives. `T3-27` is built: every check names a remedy
   class, `approve()` uses that class (not the edited wording), and a
   check with no remedy refuses rather than offering a button.
   `T3-33.a` is built: image content FLAG/REJECT remedies are `edit-text`
   (the next prompt rewrite); "re-render with a different seed" is
   refused by the check, not offered as the default. `T3-35` **built**
   (`test_t3_35_settings_remedies.py`): pose/identity FAIL names
   `latent` / `denoise` / `CFG` / `pose-match` / `plate-absent` /
   `body-colour`; plate-as-image1 FAIL is not only `edit-text`.
10. Pose QC then anatomy QC (`T3-33.b`): the operator judges the
    picture. Anatomy is not drawn, inpainted, or composited onto a
    pose FAIL (missing arm, human face patch, wrong camera, tail
    covering the hole). Anatomy QC is a second eye pass on a pose
    PASS only.
11. Every generated still is vision-scored into `qc_json` (`T3-31`),
    including a `fix_anchor` sibling, an `h_reroll` dest, the artwork
    generate (not only the refined cover), an `h_repair` dest still,
    a standalone `refine_generated_still` dest, and pose-gap C1/C2
    `h_anchor` landings (`T3-34` **built**,
    `test_t3_34_pose_still_qc.py` — enqueue prompt is the decided
    pose clause; skip `score_candidate` on C2 → red). Per-clip refs
    (`h_refs`, `h_reroll`, `h_fix_ref`) are scored against the album's
    **chosen anchor** as `score_candidate` bases — not a job plate or
    the broken source. Storing any `qc_json` is not enough. A refine or
    repair pass writes a new candidate beside the generate; it is
    not a silent overwrite and not a VLM gate. QC never auto-heals
    (`T3-18`); dest exists after approve, except the explicit refine
    sibling.

### Deferred to another document, on purpose

The queue and the wait-state scheduler (**TRD-6**, and it exists because TRD-1
§11 and TRD-3 §9 both disowned it); garbage collection; the song-level audio
editor; `duck` and `layer` until `T1-21`/`T1-22` can be measured.

## 7. Risks

Each is a thing this project has already done once, not a hypothetical.

1. **A check that cannot fail.** ~20 criteria across the three documents were
   one-sided — "X is refused", "the payload carries Y" — and stay green when the
   whole feature is deleted. Each TRD now carries a table pairing them with a
   positive half; those tables are requirements, not commentary.
2. **A second implementation of a number.** Twelve criteria for four facts;
   `CHUNK` once had five clip-count readers (`T2-13` collapsed them to `n_clips_for`); scene timing computed twice; gain in two places
   before automation would have made three. Every new value gets one owner and
   the others cite it.
3. **A metric that is confidently backwards.** §3, and it is why tier 2 is
   calibration-gated rather than threshold-first.
4. **Preview trusted over the render.** `T1-16` makes the proxy warning part of
   the API response rather than a sentence in one template, because a mobile
   client will not carry a sentence.
5. **Documents drifting from the code.** Every line-number citation in TRD-2 §3.4
   went stale within a day. Cite behaviour and function names; cite line numbers
   only alongside the behaviour that identifies them.

## 8. Open, and needing Jon

- **Scope.** **192** criteria across seven TRDs, of which these three hold
  **120** — 32 / 58 / 30. (Counted 2026-08-13 with `grep -cE "^- .T<n>-"`. The
  figures quoted everywhere until then — ~197 total, 36 / 61 / 36 — were wrong
  for five of the seven documents, and had been carried between documents rather
  than measured. The correction changes no decision; it is recorded because a
  number copied instead of counted is the defect these documents are about.)
  This is the whole remaining project. If a smaller shippable scope is wanted,
  §6's P0 and P1 are the smallest cut that produces something usable — the
  timeline axis, joins, lanes and playhead are server HTML on
  `set_duration()` (`test_t1_timeline.py`). Remaining DAW work is
  drawing a curve that is not already a stored row, and peaks as a
  draggable envelope rather than a PNG. Forms remain.
- **`duck` and `layer`.** Refused everywhere today and honestly so (`T1-23`).
  They stay refused until measured, and that is a decision to schedule, not a
  bug to fix.
- **Live-model tests.** TRD-2 §10.3 requires fixtures in the default suite and
  one deliberately live test kept out of it. Nobody has decided how the live one
  is run or how often the fixtures are re-recorded, and a fixture that no longer
  resembles what the model returns is a check measuring its own history.
