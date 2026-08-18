# DDD · Design for TRD 1-3

Status: written 2026-08-13. **Rewritten 2026-08-17 for Jarvis #529
(D1–D10).** Product framing: `docs/PRD-1-3-EDITING-AND-QUALITY.md`.
Contract: `docs/TRD-1-TIMELINE-AND-MIXING.md`,
`docs/TRD-2-STORY-ARC-AND-STORYBOARDS.md`, `docs/TRD-3-QC-AND-REMEDIATION.md`.
The one-line pipeline (one front sheet → every scene → one
`video_model`) is retired. Design below is the loop.
Rules inherited from `TRD-6 §0` are cited, never restated. `T6-A7` (a
measurement that cannot fail is not evidence) is **built** as
`test_t6_a7_measurement_can_fail.py` — equal control/mutated refused; product
exemplar is the T6-A4 stub differential on `/queue`.

**Every "built" and "not built" below was read off the tree at `7de0aea` (refreshed 2026-08-15), then
reconciled to the TRD-1/2/3 ledgers at `d782d2e` on 2026-08-16, then
to the 2026-08-18 ledgers (`T2-51` partial; `T4-21`…`T4-24` / `T7-21`
built), then `T2-54` built (`test_t2_54_ceiling_backfill.py`).** The 2026-08-13 snapshot was `f9ca597`. TRD-3 §2.1 records what happens otherwise: a "do not rebuild"
table that omitted the QC implementation, which is the omission most likely to
cost a rewrite. Built-state is the TRD ledgers. Where a claim here is a measurement, the command that produced it
is named.

---

## 1. What exists today

| module | lines | owns | state against its TRD |
|---|---|---|---|
| `studio/app.py` | 7589 | 156+ routes, 38+ of them `/api/*` JSON | T6-A1 named loops land on `/api/sets`, `/api/playlists/{id}` (`T2-37` arc when defined; `T6-A2-playlists` via `playlist_service.numbers`), `/api/playlists/{id}/arc` (`T6-A2-arc` via `arc_service.payload`), `/api/songs` (`T6-A2-library` via `library_service.numbers`; HTML also on `GET /` / `GET /songs`), `/api/nav` (`T6-A2-nav` via `nav_service.links`; HTML topbar on every page), `/api/songs/{id}/storyboard/{tier}`, `/api/qc/*`, `/api/anchors`; song page `video_model` select is `models.renderable("video")` (`T2-33`); `sets_service.py` / `storyboard_service.py` / `arc_service.py` / `playlist_service.py` / `library_service.py` / `cleanup_service.py` / `media_service.py` / `nav_service.py` land T6-A3 (`test_t6_a3_*_imports_nothing_from_fastapi`) |
| `studio/arc_service.py` | — | TRD-6 T6-A2-arc meter: `payload(playlist_id)` → song_count / act_count / premise / has_proposal; no FastAPI | **built** (`test_t6_a2_html_and_json_report_the_same_arc_numbers`) |
| `studio/playlist_service.py` | — | TRD-6 T6-A2-playlists: `numbers(playlist_id)` → song_count / total_secs; no FastAPI | **built** (`test_t6_a2_html_and_json_report_the_same_playlist_numbers`) |
| `studio/library_service.py` | — | TRD-6 T6-A2-library: `numbers()` → song_count for HTML library and `GET /api/songs`; no FastAPI | **built** (`test_t6_a2_html_and_json_report_the_same_library_numbers`) |
| `studio/nav_service.py` | — | UIUX §8 / TRD-6 T6-A2-nav: `LINKS` / `links()` → topbar `{href,label}` list for `base.html` and `GET /api/nav`; no FastAPI | **built** (`test_uiux_nav_html_and_json_share_one_list`) |
| `studio/storyboard_backfill.py` | — | T2-54 ceiling + ticked-lower boards from the ceiling board; each ticked tier ≤ ceiling gets that tier's guardrail + wardrobe subset; no FastAPI | **built** (`test_t2_54_ceiling_backfill.py`) |
| `studio/mixer.py` | 2116 | set duration, `transition_times` (`T3-12` model), both filter graphs, overlap arithmetic, beatmatch, ramps, splice, `spliced_duration` / `SPLICE_DURATION_TOLERANCE` (`T3-10`), song-assembly geometry (`T5-7`) and fps (`T2-13d`), `EXPORT_FORMATS` (`T1-24`), `probe.sample_rate` for **T3-4.3-sr**, `probe["channels"]` (`T3-4.3-ch`) | TRD-1's engine. Built; one measured gap, §5.2. Song assemble honours largest same-aspect size and refuses mixed aspect — it does not letterbox. Mixed clip fps honours the highest and is asserted on the assembled file. Export encode args are a named row of `EXPORT_FORMATS`; `render_set(..., fmt=)` looks the row up and passes it to ffmpeg (`test_t1_24_export_format_row.py`). Probe always exposes sample rate and channel count (0 when no audio) for QC |
| `studio/effects.py` | 592 | effect validation, `filter_sweep`, `duration_delta`, `loudnorm_filter`, `measure_loudness`, `export_loudness`, `LOUDNORM_I` | built; owns loudness for `T1-25` and the loudness half of §4.3. `T3-9` silence is **not** here |
| `studio/automation.py` | 457 | TRD-1 §5 in full: lanes, RDP decimation, `MAX_POINTS = 64`, `FILTER_EXPR_MAX_BYTES = 8192` (`T1-10`), `fragment`, `item_audio`, `wants_master_loudnorm` | built |
| `studio/qc.py` | 642 | TRD-3 tier 1 in full; **T3-3** silent LTX clip does not emit `has_audio`; `kind=song` REJECTs `has_audio` when no audio stream (`test_t3_3_has_audio.py`); **T3-4.1-opens** `check_image` `opens` (missing/unreadable REJECT; real PNG not opens-rejected; no image size floor — `test_t3_4_1_opens.py`); **T3-4.1-alpha** `measure_alpha` / `check_image` `alpha` (max alpha vs `ALPHA_MIN`; fully transparent RGBA REJECT, RGB/opaque/partial PASS — `test_t3_4_1_alpha.py`); **T3-4.1-resolution** `check_image` `resolution` when `expect.width`+`height` are set (PIL WxH; exact match PASS / downscale REJECT; unit `px`, not `None` — `test_t3_4_1_resolution.py`); **T3-36** `expect.latent==image` inherits source WxH PASS (1024×1024 vs 896×1216 is not REJECT; empty/absent latent still exact-match REJECT — `test_t3_36_image_latent_size.py`); **T3-4.1-not_uniform** `measure_pixel_std` / `not_uniform` (max per-channel spatial RGB std vs `UNIFORM_STD_FLOOR`; solid red/gray/black REJECT, testsrc2 PASS — `test_t3_4_1_not_uniform.py`); **T3-4.1-not_blank** `measure_mean_level` / `not_blank` (mean RGB vs `LUMA_FLOOR`; solid black REJECT, testsrc2 PASS; distinct from not_uniform — `test_t3_4_1_not_blank.py`); **T3-4.3-loudness** `check_audio` `loudness` via `effects.measure_loudness` (`test_t3_4_3_loudness.py`); **T3-4.3-duration** `check_audio` `duration` vs `expect.duration` within `DURATION_TOL_S` (`test_t3_4_3_duration.py`); **T3-4.2-luma** `measure_luma` / `check_video` `luma` (black REJECT below `LUMA_FLOOR` — `test_t3_4_2_luma.py`); **T3-4.2-size_floor** `check_video` `size_floor` (under `MIN_VIDEO_BYTES` REJECT — `test_t3_4_2_size_floor.py`); **T3-4.2-opens** `check_video` `opens` (unreadable / no video stream / missing path REJECT after size floor — `test_t3_4_2_opens.py`); **T3-4.3-opens** `check_audio` `opens` (missing/unreadable/no audio stream REJECT; real take not opens-rejected — `test_t3_4_3_opens.py`); **T3-4.2-black_frames** `check_video` `black_frames` (partial Y < `LUMA_FLOOR` while mean PASSes FLAG — `test_t3_4_2_black_frames.py`); **T3-4.2-luma** `measure_luma` / `check_video` `luma` (mean YAVG vs `LUMA_FLOOR`; solid black REJECT, testsrc2 PASS — `test_t3_4_2_luma.py`); **T3-4.2-sat** `measure_channel_sat` / `channel_sat` (green dominance vs `CHANNEL_SAT_LIMIT`; solid green garbage FLAGs, testsrc2/gray/black PASS — `test_t3_4_2_sat.py`); **T3-4.2-resolution** `check_video` `resolution` when `expect.width`+`height` are set (`mixer.probe` WxH; exact match PASS / downscale REJECT; unit `px` — `test_t3_4_2_resolution.py`); **T3-4.2-fps** `check_video` `fps` when `expect.fps` is set (`mixer.probe` rate within `FPS_TOL`; match PASS / retimed FLAG; unit `fps` — `test_t3_4_2_fps.py`; RIFE out_fps is T3-8); **T3-4.2-duration** `check_video` `duration` when `expect.duration` is set (`mixer.probe` seconds within `DURATION_TOL_S`; match PASS / wrong length REJECT; unit `s` — `test_t3_4_2_duration.py`; song mp3 is T3-4.4-mp3, audio is T3-4.3-duration); **T3-4.2-frame_count** `check_video` `frame_count` when `expect.frames` is set (`qc._ffprobe_frames`; match PASS / 81-vs-505 REJECT; unit `frames` — `test_t3_4_2_frame_count.py`; not T3-7 latent_8n1); **T3-4.3-sr** `check_audio` `sample_rate` when `expect.sample_rate` is set (`mixer.probe` carries the Hz reading; exact match PASS / mismatch REJECT — `test_t3_4_3_sr.py`); **T3-4.3-true-peak** `check_audio` `true_peak` vs `effects.LOUDNORM_TP` + `TRUE_PEAK_TOLERANCE_DB` via `effects.measure_loudness` (under PASS / over FLAG / missing Peak FLAG — `test_t3_4_3_true_peak.py`); **T3-4.3-ch** `check_audio` `channels` vs `expect.channels` via `mixer.probe["channels"]` (stereo vs 2 PASS, mono vs 2 REJECT, unit `ch` — `test_t3_4_3_ch.py`); **T3-4.3-clip** `measure_clipped_samples` / `clipped_samples` (s16 rail count vs `CLIPPED_SAMPLES_LIMIT` 0; clean sine PASSes, hard-clipped FLAG — `test_t3_4_3_clip.py`); **T3-4.3-dc** `measure_dc_offset` / `dc_offset` (abs mean sample vs `DC_OFFSET_LIMIT` 0.02 FS; clean tone PASS, biased take FLAG — `test_t3_4_3_dc.py`); **T3-4.3-edge** `measure_edge_silence` / `edge_silence` (leading/trailing seconds vs `EDGE_SILENCE_LIMIT_S`; 0.5 s pad FLAGs, clean tone and 0.15 s pad PASS; not T3-9 — `test_t3_4_3_edge.py`); **T3-4.4-av** `measure_av_durations` / `av_sync` on assembled song (`want_audio`; kind=song defaults it): matching streams PASS within `DURATION_TOL_S`, video/audio gap over that FLAGs, clips without `want_audio` skip — `test_t3_4_4_av.py`; **T3-4.4-mp3** song `duration` vs `songs.duration` / source mp3 within `DURATION_TOL_S` on the assembled file (`test_t3_4_4_mp3.py`); **T3-4.4-gap** `check_join_black_gap` / `measure_join_black_gap` (black span on a planned song join REJECTS; hard cut PASSes; `joins` / `clip_durations`; re-assemble — `test_t3_4_4_gap.py`); **T3-4.4-nclips** `check_nclips` / `run(kind="song")` assembly count vs `len(build_song.clip_plan)` (`test_t3_4_4_nclips.py`); **T3-8** `expect_interpolated` (RIFE `(n-1)*m+1` + `make_postproc.out_fps`; duration/fps/frame_count, not latent exemption alone — `test_t3_8_interpolated.py`); T3-9 `measure_band_energy` (low/mid/high mean, not peak); **T3-10** `check_splice` vs `mixer.spliced_duration` / `bridge_seconds` (`test_t3_10_splice.py`); **T3-11** `check_set` / `run(kind="set")` duration vs `mixer.set_duration()` within `mixer.SET_DURATION_TOLERANCE` on the artefact (`test_t3_11_set_duration.py`); T3-12 `transition_lands` (pixels vs `mixer.transition_times`, half-frame, no remedy); T3-13 `score_zimage_sweep`; T3-15 histogram `identity_embed`; T3-16 `identity_verdict`; T3-17 `score_identity_artefact` (per artefact vs chosen anchor); T3-26 `measure_refiner_help` (fail-closed labelled set, not opportunistic); T3-28 `check_identity_wrong` / `identity_wrong_remedy`; T3-33.a `IMAGE_PROMPT_REWRITE_CHECKS` (image FLAG/REJECT is edit-text, not seed); T3-27 `CHECK_REMEDY_CLASS` / `actuator_for`; T3-35 pose/identity FAIL `remedy_class` via `qc_settings` | built |
| `studio/qc_settings.py` | — | T3-35 named settings remedies + expect-driven resolver (`latent` / `denoise` / `CFG` / `pose-match` / `plate-absent` / `body-colour`); `check_identity_wrong` puts the class on the finding; T3-33.a blank/uniform/alpha stay edit-text | **built** (`test_t3_35_settings_remedies.py`) |
| `studio/qc_service.py` | 308 | findings, queue, `by_host` (`T3-1`), remedy edit, dismiss, reopen; `artefact_hash` keeps a dismissal on the same bytes and reopens the same check when the file changes (`T3-22`); `approve()` enqueues dest ≠ source; `pair()` lists original and repair, both scored (`T3-21`); approve uses `remedy_class` (`T3-27`); the version that RUNS is `findings.remedy_prompt_id` looked up at execute (`T3-20`); `dispatch_repair` asks `where()`/`fits()`/`resolve()` then submits `fix_ref` / `gen_postproc`; real `fits()` routes the refiner by resident cost (`T3-24`); `can_move_output` gates remote repair (`T3-25`); `run_zimage_calibration` writes the T3-13 row; `set_threshold` writes a value only on a stored separated row (`T3-14`/`T3-16`); `build_identity_gate` never builds; T3-17 `score_identity_artefact` / `run_artefact` records the per-artefact score as a tier-2 measurement, no gate; T3-17-ui queue keeps identity_drift PASS and finding-row shows compliance/variation/n; T3-28 refuses a swap-the-reference identity-wrong remedy; T3-33.a image content FLAG/REJECT is edit-text (not seed); `record_refiner_help` persists the T3-26 finding; `run_song` is tier 1 over a song's artefacts with no GPU and no backend (`T3-32`); `persist_still_qc` writes advisory `qc_json` on an `h_repair` dest still and a standalone refine dest (`T3-31`); named lander `h_reroll` writes `refs.qc_json` (`test_h_reroll_stores_qc_json`) | built |
| `studio/arc.py` | 327 | TRD-2 §3.1/§3.2 JSON-canonical arc; §3.3 `save_prompt`/`restore_prompt` (`T2-5`); `generate` records an `arc` version (`T2-7`); §4.1 wand (`require_theme`, proposal files, `apply_summaries`) | built (`T2-5`/`T2-7`/`T2-14`/`T2-15`/`T2-16`) |
| `studio/prompts.py` | 265 | TRD-2 §3.3 versioning; `restore(vid)` puts previous text back as a new version (`T2-5`); `delete` drops a row and does not renumber survivors (`T2-6`); a version stores the asked `model` and `created` (`T2-7`); `running(vid)` is the row a render RUNS (`T3-20`) | built |
| `studio/grok.py` | 1249 | storyboard generation, `validate`, the retry loop | built; §5.5 |
| `build_song.py` | 789 | `clip_plan`, `clip_seconds`, `n_clips_for`, `expect_from_workflow`, `clips_for_scene`, `chain_clip_count`, `LTXVAddGuide` handoff (`T2-10`) | the one timing owner; `clip_seconds` honours `legal_frames`, §5.5; hop 0 is `ltx25` (`T5-11`); `T2-47` mixed native frames **built** (`test_t2_47_mixed_model.py`: LTX hop0 81@`LTX25_FPS` + s2v hop 77@16.0); `T2-48` ceilings compose **built** (`test_t2_48_ceilings_compose.py`: 30 s `needs_lip_sync` is LTX 15+15 plus per-part s2v windows); T5-12 D7 hop graph **built** (`test_t5_12_d7_hop.py`); T5-13 `skip_first_frames` **built** (`main()` hop emit + `test_t5_13_s2v_window.py`); T5-14 T5-A on LTX take **built** (`test_t5_14_refine_on_ltx_take.py`: hop `refine=False`, `control_video` = refined LTX prefix); per-scene `ref_motion` / `control_video` (`T2-46`). A scene over the 15 s LTX ceiling is `ceil(scene / ceiling)` clips; successor graph injects N's last frame at index 0 |
| `studio/db.py` | 559 | schema | `automation`, `findings` (`artefact_hash`, `remedy_class`), `artefacts`, `sets.mode_audience`, `calibrations` landed; `sets.out_fps` did not, §4 |
| `studio/vision.py` | 516 | VLM calls, local-first | **not** tier 2, §5.6 |
| `anchor5/poses/cleanrun/qc-pose-*.json` | — | Operator `T3-33.b` pose-then-anatomy eye gates (not a VLM). Anatomy is not composited on FAIL | process, this slice |

Deliberately absent, verified by `grep -rn` over `studio/*.py` and the root
scripts: no *configurable* master chain (T1-19 records the fixed
`one-button-master` v1 on the render; §8a stays fixed-order, not a
control surface), no peaks store, no
tier-2 gate. `calibrations` and `qc.score_zimage_sweep` landed for
`T3-13` (overlap/separation/per-file, `threshold` NULL). `T3-14`
`set_threshold` writes a number on a stored separated row and refuses
without one. `T3-15` is a colour histogram, not a spatial grid.
`T3-16` names overlap inconclusive and does not build a gate.
`T3-17` scores each artefact against the chosen anchor; it is not a
gate. `T3-17-ui` shows compliance / variation / n on the `/qc`
finding-row (still not a threshold control).
`siglip2_naflex`
is still only a `models.py` catalogue entry; the default embedder is a
colour histogram so the report can run without a GPU. `insightface` is
absent.

## 2. The structural problem, and the pattern that already solves it

`app.py` is 7589 lines and 138 routes, of which **25 are `/api/*` JSON**.
`T6-A1`'s four named loops complete over those paths (set empty→rendered,
storyboard, review queue, anchors). `/queue` still answers JSON from the same
`queue_ctx()` as the fragment (`T6-A2`). The HTML handlers still decide;
`sets_service.py`, `storyboard_service.py`, `arc_service.py`,
`playlist_service.py`, `cleanup_service.py`, and `media_service.py` land the
T6-A3 move (`test_t6_a3_*_imports_nothing_from_fastapi`).
`render_set_route` is TRD-1 §10's named example: `_set_render_items` plus
`_enqueue_set_render` is now the shared entry the JSON loop calls.

`T6-A1`…`T6-A4` are the requirement. **`qc_service.py` is the pattern and it
already works**: `qc.py` is pure measurement that touches no database, so it runs
over a directory of old output (`T3-30`); `qc_service.py` persists and imports
nothing from FastAPI; the five routes are thin. Copy that shape, do not invent a
second one. `T6-A4` holds on `/queue`: `queue_ctx` emits the counts, the row
list and a formatted `elapsed`, and `_queue.html` interpolates them. A stub that
returns `12.7s` and counts that are not the list lengths is what the page
shows (`test_t6_a4_queue_page_shows_stubbed_values_unmodified`). **`T6-A4-jobs`
built**: `jobs_ctx` owns preformatted `elapsed` (`12s` / stub `12.7s`);
`_jobs_panel.html` interpolates `e.elapsed` only (no `|format`). Stub
differential: `test_t6_a4_jobs_panel_shows_stubbed_elapsed_unmodified`.
**`T6-A4-storyboard` built**: `storyboard_service.coverage`
owns `fill_pct`; `storyboard.html` interpolates `coverage.fill_pct` only (no
intent/rendered division in the template). Stub differential:
`test_t6_a4_storyboard_page_shows_stubbed_fill_pct_unmodified`.

Service modules, same shape:

    sets_service.py        TRD-1   sets, items, automation, peaks, preview, render, export
    storyboard_service.py  TRD-2   arc flows, storyboard generation, scene edit, time meter, casting; thin T2-54 `backfill` wrapper
    storyboard_backfill.py TRD-2   T2-54 ceiling + ticked-lower boards from the ceiling board; no FastAPI
    arc_service.py         TRD-2/6 album arc meter (song_count / act_count / premise)
    playlist_service.py    TRD-6   playlist card numbers (song_count / total_secs)
    #media-player          UIUX    Play column audio/tier cells stay on the
                                   playlist (`js-media-play`); no FastAPI
    cleanup_service.py     TRD-6   T6-19 operator-confirmed clip cleanup
                                   (song page card interpolates plan_clip_cleanup)
    media_service.py       TRD-8   song media bag (takes / edits / original / renders)
    app.py POST/GET        TRD-6   operator Delete of one assembled output
      /songs/{id}/renders/{id}/delete
                                   (row gone even if mp4 missing; unlink only
                                   when no sibling shares the path)
    approve.html #ref-fix  TRD-3   Fix is a dialog; empty instruction uses
                                   fix_ref.INSTRUCTION; tiles stay even
    approve.html                   one tile per scene; no part/clip tiles
    build_song.apply_chain_guide   T2-10 last frame → LTXVAddGuide on successor
    enqueue_clips                  only scene-head stills required
    build_refs --heads             one still per scene
    remap_legacy_refs              clip_plan 0..n → scene heads (live BAP)
    POST /songs/{id}/refs/{id}/delete
                                   one still candidate; file unlinked only
                                   when no sibling shares the path
    approve_context        TRD-2   one tile per scene (clip_chain_plan heads);
                                   seed above scene name; origin tag
                                   only for gen/reroll/refine/face/inpaint/outpaint

`arc.py` and `automation.py` are already FastAPI-free and become their
dependencies rather than being folded in. The boundary rule that decides what
moves: **a route handler contains no arithmetic, no defaulting and no decision**
(`T6-A3`). `app.storyboard_scenes` computing `idx * CHUNK` inline is the defect
this prevents, and `T2-41` records that it was real and is now fixed.

Migration is per-loop, not per-file. Move one journey (PRD §4) at a time, and
`T6-A2` is the check that the move was faithful: the HTML page and the JSON
endpoint report the same numbers, asserted by comparing them in one test.
The first object is the queue panel: `GET /queue` HTML and
`Accept: application/json` share `queue_ctx()`
(`test_t6_a2_html_and_json_report_the_same_queue_numbers`). Review queue
T6-A2 is `test_t6_a2_html_and_json_report_the_same_review_queue_numbers`
(`/qc` HTML vs `/api/qc/findings`, same `qc_service.queue()`). Set HTML
`/sets/{id}` and JSON `/api/sets/{id}` share `set_detail()`
(`test_t6_a2_html_and_json_report_the_same_set_numbers`, `T6-A2-set`).
Storyboard HTML `/songs/{id}/storyboard/{tier}` and JSON
`GET /api/songs/{id}/storyboard/{tier}` share `storyboard_service.payload()`
(`test_t6_a2_html_and_json_report_the_same_storyboard_numbers`,
`T6-A2-storyboard`: scene_time, song_length, clip_seconds, scene_count,
mismatch; scene_count is service-owned so a template `len(scene_rows)`
recompute fails the stub arm). Album arc HTML `/playlists/{id}/arc` and
JSON `GET /api/playlists/{id}/arc` share `arc_service.payload()`
(`test_t6_a2_html_and_json_report_the_same_arc_numbers`, `T6-A2-arc`:
song_count, act_count, premise, has_proposal; song_count is service-owned
so a template `arc.songs | length` recompute fails the stub arm). Playlist
HTML `/playlists` card and JSON `GET /api/playlists/{id}` share
`playlist_service.numbers()` (`test_t6_a2_html_and_json_report_the_same_playlist_numbers`,
`T6-A2-playlists`: song_count, total_secs; song_count is service-owned so a
template `len` recompute fails the stub arm; `arc` still only when defined,
T2-37). The list page is summaries only; album look, cast, the
embedded arc writer (`_arc_panel.html`, same `arc_service.payload()`
as `/playlists/{id}/arc`) and the
anchor gallery land from `GET /playlists/{id}/card` when the operator
opens the card (`test_playlists_page_is_summaries_until_the_card_loads`).
Look-field wands and **Draft from lyrics + cover** call
`vision.draft_look_field` with every track's lyrics plus the cover.
Album look and cast are one fold: character tabs, same look form for
the album lead and each named supporting character. `characters.figure_role`
(`lead` default, or `extra`) is what `offered_cast` reads; story `role`
is a label. Library HTML `GET /` / `GET /songs` (`#library` `data-song-count`)
and JSON `GET /api/songs` share `library_service.numbers()`
(`test_t6_a2_html_and_json_report_the_same_library_numbers`, `T6-A2-library`:
song_count is service-owned so a template `len` recompute fails the stub
arm; `GET /songs` is 200 never 405). Topbar HTML (`base.html` iterates
`nav_links()`) and JSON `GET /api/nav` share `nav_service.links()`
(`test_uiux_nav_html_and_json_share_one_list`, `T6-A2-nav`: probe
monkeypatched into `LINKS` appears in both; hardcoding the old eight
`<a>` tags in the template drops the probe). Set, storyboard, review and
anchor loops complete over JSON (`test_t6_a1_*`).

## 3. API surface

Named per journey, because `T6-A1` requires a curl script to drive each one end
to end. Shapes only — the fields are the TRDs'.

**A · set timeline** — `GET/POST /api/sets`, `/api/sets/{id}` (model in full:
items, automation, predicted duration, rounding deltas; HTML `/sets/{id}` and
JSON share `set_detail()`, `T6-A2-set`), `/api/sets/{id}/items`,
`.../items/{iid}/automation/{lane}` (POST raw points, response is the **stored,
decimated** curve — the client re-reads what was kept, §5.3),
`GET/POST /api/songs/{id}/automation/{lane}` (T8-13: same `automation.save` /
`item_audio` path, one-item `song_editor` set, not a second curve model),
`GET /api/songs/{id}/editor/duration` and `POST /api/songs/{id}/editor/render`
(T8-14: `mixer.set_duration` then `mixer.mix_audio`; predicted equals
rendered within `mixer.SET_DURATION_TOLERANCE`),
`/api/songs/{id}/peaks?z=` (`pairs` plus `reason` when empty, `T1-15`),
`/api/sets/{id}/peaks?z=`, `/api/sets/{id}/preview` (returns `is_proxy` and
`not_applied`), `/api/sets/{id}/preview/render?at=&secs=`
(`is_proxy: false`, the accurate span),
`/api/sets/{id}/render` (`T1-3`: same ffmpeg argv as `POST /sets/{id}/render`),
`/api/sets/{id}/renders` (every candidate, `T1-26`,
`T6-A5`) and `POST /api/sets/{id}/renders/pick` (either listed render is
selectable). `GET /api/qc/lineage?kind=&group=` and `POST /api/qc/lineage/select`
are the same pair for refine, repair and anchor re-roll — `qc_service.listed`
and `qc_service.select` decide; the route forwards.

**B · arc and storyboard** — `GET /api/playlists/{id}` is the playlist
card payload: identity fields, `song_count` / `total_secs` from
`playlist_service.numbers()` (`T6-A2-playlists`; same numbers as the
HTML `/playlists` card), plus `arc` only when one is defined
(`T2-37`; omitted when none so always-present cannot pass).
`GET/POST /playlists/{id}/arc` (POST is
propose; empty theme is 400, `T2-14`), `POST .../arc/propose` (same
handler), `POST .../arc/accept`, `POST .../arc/reject` (proposal is not
saved until accepted; reject re-reads the previous file, `T2-15`),
`POST .../arc/apply` (`song_ids`, `confirm`; more than one song without
confirmation is 400; with confirm writes exactly those songs under
`applied/`, `T2-16` / `test_t2_16_multi_song_apply.py`). The committed
arc is editable (`POST .../arc/save`) and versioned (`versions/N.json`,
`POST .../arc/restore`). Playlist POSTs answer the card fragment on
`HX-Request` so Save Tiger does not reload `/playlists`. Same routes, no
parallel `/api/*` tree (`wants_json`). Song-page POSTs
(`/songs/{id}/storyboard`, lyrics, analyse, refs, clips, render, audio,
qc, …) answer JSON to `Accept: application/json` and 303 otherwise;
`GET /api/songs/{id}` is the page state. `GET/POST /api/songs/{id}/storyboard/{tier}`,
`.../scene/{n}`, `.../meter`, `.../cast`. The generation prompt and
**the limits that apply to it** travel in the same response (`T2-18`).
`GET/POST /api/songs/{id}/storyboard/{tier}` (`T2-17` **built**: GET
returns `prompt` from `storyboard_generation_payload`, defaulted from the
tier; POST accepts an edited `prompt`; `T2-18` **built**: same body carries
`max_characters`, `pinned`, `pinned_added_at_use`, `pinned_editable`; one
character over the returned cap is 400 quoting that number; `T2-19` **built**:
the edited prompt is what `generate_storyboard` is handed — two different
directions produce two different boards and two different model messages),
`.../scene/{n}`, `.../meter`, `.../cast`.

**C · QC** — exists. `/api/qc/run`, `/api/qc/findings`, `/{fid}`,
`/{fid}/remedy`, `/{fid}/dismiss`, `/{fid}/approve`, `/{fid}/recheck`,
`/api/qc/by-host` (`T3-1`: groups by `host`, NULL host is the
`unattributed` bucket). `GET /qc` is the finding-row page (`T3-19`):
measured / expected / unit, editable remedy, approve. `POST
/qc/findings/{fid}/approve` stores the edited text then `approve()`.
Each finding carries `remedy_class` and
`actionable` (`T3-27`): approve uses the class, and a false `actionable`
is why the button is absent, not a button that does nothing. Dismiss needs a
reason and leaves the open queue; re-running QC on the same bytes keeps
it dismissed; rewriting the file reopens that `(path, check)` row
(`T3-22`). `POST /songs/{id}/qc` calls `qc_service.run_song` in-process
(`T3-32`): tier 1 over that song's artefacts does not enqueue behind
the GPU worker. `/api/qc/lineage` lists predecessor and successor for a
re-render / refine / repair / anchor re-roll; `/api/qc/lineage/select`
picks either (`T6-A5`).

**D · anchors** — `GET/POST /api/anchors`, `/api/anchors/refs`,
`POST /api/anchors/{id}/pick`, `POST /api/anchors/{id}/use-as-ref`.
`T6-A1` / TRD-4+TRD-7: save base photographs, generate a named view, pick,
use the pick as the next identity lock (`test_t6_a1_anchor_loop_over_json`).
HTML `POST /anchors` and `POST /anchors/{id}/pick` share `_enqueue_anchor_jobs`
/ `_pick_anchor`.

**Q · queue** — `GET /queue` answers HTML or JSON from the same `queue_ctx()`
(`T6-A2`). The JSON body carries `running`, `waiting`, `recent`,
`refresh_secs` and the job ids/elapsed the fragment prints.

**R · review queue** — `GET /qc` HTML and `GET /api/qc/findings` both read
`qc_service.queue()` (`T6-A2`). The page interpolates finding-row measured /
expected / unit; the JSON list carries the same ids and numbers
(`test_t6_a2_html_and_json_report_the_same_review_queue_numbers`).

Every list response carries help text per control, with warnings marked
distinctly from notes (`T2-36`) — a client that cannot tell them apart hides the
wrong one, and day 8's rule is that the warnings do not move.

## 4. Schema deltas still required

Landed already: `automation`, `findings` (including `artefact_hash` for
`T3-22` and `remedy_class` for `T3-27`), `artefacts`, `storyboards.scene_seconds`,
`sets.mode_audience` (`easy|normal|advanced`, default `normal`; `T1-20`),
`calibrations` (`T3-13`; `T3-14` may write `threshold` only after a
separated row exists), the interstitial card
(`set_items.song_id` nullable, `card_path`, `card_secs`; `mixer.is_card` /
`set_duration` prices it; `POST /sets/{id}/cards`), `lineage`
(`T6-A5`: predecessor/successor pair, either selectable), and
`pose_coverage` (`T2-50`: song, tier, scene_number, pose, view, wardrobe,
exposure — board needs only; analyze writes this table and nothing else),
`GET /api/songs/{id}/pose-gap` (`T4-23` **built**: ceiling board vs
`classification_json` keepers; holes only; no table; no `scene_pose_map`),
`POST /api/songs/{id}/pose-generate` (`T4-24` **built**: ceiling-tier
library sheets from those holes; clothed+nude iff r/xxx; g/pg13 clothed
only, no anatomy; studio `anchor` jobs, not `batch_edit`; C1/C2
graphs `T7-21` **built**, `test_t7_21_c1_c2_resolver.py`; landings
scored `T3-34` **built**, `test_t3_34_pose_still_qc.py`; settings
remedies `T3-35` **built**, `test_t3_35_settings_remedies.py`;
image-latent size `T3-36` **built**, `test_t3_36_image_latent_size.py`;
D7 look `T3-37` **harness only; NOT MEASURED**
(`qc.t3_37_*` + `test_t3_37_d7_look.py`; no GPU pair;
warm-px / silent hop omit refused)),
and `classification_json` (`T4-21`/`T4-22`: album, character_id
NULL=protagonist, versioned document, same fields as
image-classification.json; sidecars seed import only),
and `scene_pose_map` (`T2-51`/`T2-52` **built**: song, tier,
scene_number → keeper id/path, status `draft|accepted|rejected`;
`prev_*` holds the last accepted bind so reject leaves it),
and `storyboard_backfill.backfill` (`T2-54` **built**: ceiling board
→ only ticked tiers ≤ ceiling; each board gets that tier's
`compose_guardrail` + allowed wardrobe; nude clamps to clothed on
g/pg13; no new table, no route).
Switching audience writes only that column. Easy is `mixer.master_engaged`
reading `mode_audience == "easy"` on the item dict — the same application
point as a gain curve (`T1-18`, `T1-20c`, `T1-20d`).

Still needed, and no more than this:

    ALTER TABLE sets ADD COLUMN out_fps REAL;                        -- NULL = derive from items

    -- #529 loop leftover. Minimum; do not over-schema.
    -- location_plates (T2-53 **built**): album or song, location key → asset path
    -- scenes.needs_lip_sync (T2-55 **built**, storyboard JSON bool beside camera)
    -- clips retain predecessor/successor (T6-A5) for LTX take,
    --   s2v hop, LTX refine

One resolver for clip hops: LTX always; s2v if `needs_lip_sync`
(`T2-55` **built**, `test_t2_55_needs_lip_sync.py`); T5-A if refine,
on the LTX take only (`T5-14` **built**,
`test_t5_14_refine_on_ltx_take.py`).
Labels cannot promise a hop the graph omits. Classify never
writes `scene_pose_map`. A nude map row on g/pg13 is refused.

Peaks are **not** a table. They are a binary min/max array written beside the
song by the existing `analyse` job and served decimated (§5.4).

`pan` stays an `effects_json` key and does **not** become a column — TRD-1 §3.1
decided that and the reason is §5.0(b)'s: a column would be a second place for
the value before anything needs one. Gain already had two places and cost a
silent -6 dB (mixer.py `_audio_chain`'s own docstring).

## 5. Subsystem designs

### 5.1 The clock, and one place that rounds

**`T1-5` is built.** `mixer.frame_round(t, fps) -> (t_rounded, delta)` is
the one place that rounds (nearest, not truncation). `_build_render_set_filter`
uses `t_rounded` for xfade/layer/black video offsets; audio `acrossfade` /
`afade` / `_duck_join` stay on the stored second. Brand marks stay on the
audio clock. A 2.02 s item with a 0.5 s fade at 30 fps puts xfade at
1.533 s (46/30), not exact 1.520 and not truncated 1.500
(`studio/test_t1_5_off_grid_join.py`).

`T1-6` is **built**: `mixer.rounding_report` walks the same joins as
`timeline_joins` and reports per-join delta plus `abs_delta_sum`.
`GET /api/sets/{id}` carries that object, so the half-frame-per-join
bound is checkable from the model without rendering. Truncation is the
mutation that must break it: the losses all share a sign and accumulate
at 0.0594 s per join at 16.8312 fps, which is the RIFE one-frame bug's
shape — it plays, it looks fine, it is the wrong length.

### 5.2 The master stage — built, with one measured gap

`mixer._master_lines` (mixer.py:652) exists and implements TRD-1 §8a: one
`loudnorm` after every item and every join, engaged only when some item
suppressed its own, so a set that draws no curve renders exactly as it did before
automation existed (`T1-20b`). `_audio_chain` takes the item's own `loudnorm` off
when `automation.item_audio()` says `suppress_loudnorm` (mixer.py:725).

**`T1-20d` is not satisfied for a MIXED set, and it is measured, not suspected.**
`_master_lines` engages when *any* item suppresses, while `_audio_chain`
suppresses only for the items that carry a curve — so an uncurved item in a set
that has one keeps its own `loudnorm` **and** passes through the master. Counting
`loudnorm` per signal path, calling the real `_audio_chain` and `_master_lines`:

    both curved          per-item=[0, 0]  master=1   worst path = 1
    neither curved       per-item=[1, 1]  master=0   worst path = 1
    one curved, one not  per-item=[0, 1]  master=1   worst path = 2   <-- two in series

Two normalisers in series is the second working against the first, which is
exactly the sentence `T1-20d` was added to enforce. Mutated in memory so that
engaging the master strips per-item `loudnorm` from every item, the mixed case
drops to 1 and the other two rows do not move — so the measurement responds to
that rule and to nothing else. **Reproduced independently by session B at HEAD,
same three rows.**

**Easy mode, 2026-08-14.** `sets.mode_audience` is the set-level fact.
`render_set_route` stamps it onto every item dict; `master_engaged` reads
`mode_audience == "easy"` at the same point a gain curve does, so easy
is that chain (`T1-20c`) and still one loudnorm (`T1-20d`). `app.audience_affordances`
is the affordance set `set_edit.html` consults — easy and advanced
differ as data, not as a stylesheet.

**`T1-19`, 2026-08-14.** `mixer.one_button_master()` is the named
versioned chain (`one-button-master` v1, I/TP/LRA). `_master_lines`
applies those params; `h_render_set` writes the same object to
`assets.meta_json.master_chain` only when `applied_master_chain` is
not None. The set editor shows name+version+params on the render
card. Changing I moves measured LUFS
(`studio/test_t1_19_master_chain.py`).

**`T1-25`, 2026-08-14.** `effects.export_loudness(path, I=, TP=)` is
the named record: measured LUFS / true peak, the target those were
compared to, and `flagged` when either sits outside
`LOUDNESS_TOLERANCE_LU` (2.0) or `TRUE_PEAK_TOLERANCE_DB` (0.5) of
that target. `mixer.export_loudness` supplies the master chain's I/TP
when the master ran, else the loudnorm defaults. `h_render_set`
writes it to `assets.meta_json.loudness`. The render card shows the
numbers and "off target" when flagged. The live `meter` component is
still not this.
(`studio/test_t1_25_export_loudness.py`).

**`T1-3`, 2026-08-14.** The stored model is the export. `POST /sets/{id}/render`
(UI) and `POST /api/sets/{id}/render` (JSON, no browser) both call
`_enqueue_set_render` → `_set_render_items`. `mixer.render_set_argv(items,
out)` is the ffmpeg command those items determine — the same list
`_run_ffmpeg` receives plus `ffmpeg -y -v error -stats`. T1-3 compares that
command, not file bytes (`creation_time`). Extra form fields on the UI POST
are not in the model and do not reach argv. Two encodes of the same items
agree on duration (`SET_DURATION_TOLERANCE`), frame count and integrated
loudness (`studio/test_t1_3_json_export_argv.py`).

**`T1-24`, 2026-08-14.** `mixer.EXPORT_FORMATS` is the table of ffmpeg
parameter sets. The shipped `mp4` row is the argv `_render_set_args`
already emitted. `export_format_args(fmt)` looks the row up; a missing
name is refused. `render_set` / `render_set_argv` take `fmt=` and pass
the row through to `_run_ffmpeg`. A test-only row is inserted and
rendered; the file is that codec and that metadata
(`studio/test_t1_24_export_format_row.py`). No custom encoder or muxer.

**`T1-4`, 2026-08-14.** The filter graph is regenerated from the stored
model on every render. `mixer.render_set_graph(items)` is the
`-filter_complex` string `_render_set_args` just built — no module-level
cache. Mutating stored `set_items.gain_db` and re-reading via
`_set_render_items` changes that string (`volume=-6.000dB` →
`volume=-3.000dB`). A reused ffmpeg string would stay put
(`studio/test_t1_4_no_cached_graph.py`).

**FIXED 2026-08-13 by session B, on Jon's decision, and the estimate this
document gave was wrong twice on the way — which is the part worth keeping.**

*First estimate: "one line at `mixer.py:664`."* Wrong. `_audio_chain(gain_db,
effects_json, auto=None)` receives **one item's** automation and cannot see the
others, so it cannot know the master will engage. Widening the `any(...)` at 664
would have added a master `loudnorm` on top of the per-item ones still there,
taking `neither curved` from 1 in series to **2** — worse than the bug, on the
path that was correct.

*Second estimate: "three points — the engagement test, the two call sites, and
the signature."* Right about the count, **wrong about the shape**, and a mutation
is what proved it. B wired the flag through both call sites as agreed, then
mutated the **video** call site to `master=False`: **every assertion stayed
green.** The checks exercised `_audio_chain` directly, so they never touched the
wiring. **Two correct call sites is not a property a per-function check can
see.**

*What actually shipped: one point.* `master_engaged(items)` is the single
set-level reading, and `item_chains(items)` builds every item's chain with that
decision applied. Both render paths call `item_chains`, and `grep` shows
**exactly one production `_audio_chain` call**, inside it. The criterion asserts
through `item_chains`, so the wiring is on the measured path — re-running the
same mutation now fails, naming the defect: *"one curved, one not: 2 loudnorms
in series on one signal path. A set is levelled ONCE."*

Measured independently through the real functions after the change:

    both curved          per-item=[0, 0]  master=1   worst signal path = 1
    neither curved       per-item=[1, 1]  master=0   worst signal path = 1
    one curved, one not  per-item=[0, 0]  master=1   worst signal path = 1   <-- was 2

**The generalisation, which outlives this bug — and it is two rules, not one.**

The defect lived in the *disagreement between two functions that each looked
correct alone*, and the first fix reproduced that exact shape: one decision with
two places to apply it. So the **design** rule is that any design computing a
decision in one place and applying it in two should be read against this. That
shape is already this codebase's most common defect — `NUDE_VIEWS` as two
hand-kept copies, `CHUNK` with five clip-count readers (collapsed by `T2-13` to `n_clips_for`), `DEFAULT_BODY` losing to
`ALBUM_FIELDS["body"]`, gain arriving from a column and a JSON key.

But a design smell is not what catches it, and session B's sharper version is
the one to build on: **the rule that actually catches it is a
test-construction rule — assert through the shared entry point, never through
the function it wraps.** B's checks were correct and thorough and pointed one
level too low, which is exactly why they stayed green through a deliberately
broken call site. **A design with one decision and two applications is a smell;
a check that bypasses the collapse point is what makes the smell
undetectable.** The second rule would have caught this on the first attempt and
the first would not.

**Two honest limits, recorded rather than implied away.** A caller
re-introducing a direct `_audio_chain` call and bypassing `item_chains` is
prevented **structurally, not by a test** — it is a visible code change rather
than a silent flag flip, but it is not guarded. And the selfcheck comment
claiming *"exactly ONE loudnorm in the graph"* **was already false when it was
written**: it counted the master line only, while a plain item still carried its
own. A true measurement of the wrong thing, sitting in the file the whole time.

### 5.3 Automation — built, including the other lanes

`automation.py` owns the model, decimates on write with RDP plus a hard
`MAX_POINTS = 64`, and emits through `asendcmd`, which is the mechanism
`effects.filter_sweep` already uses — one emitter, one cap, and `sweep` becomes a
preset that writes points rather than a second automation system. `pan` cannot
use that emitter: ffmpeg's `pan` filter takes no runtime command, so the lane
is one `aeval` applying the same balance law as `effects.pan`
(`L=min(1,1-p)`, `R=min(1,1+p)`), comma-chained, no join-graph split.

**`T1-1` is built (2026-08-14).** `t` is item-relative. Reordering a
set (`POST /sets/{id}/reorder`) or changing an item's `in_secs` /
`out_secs` / `secs` leaves every stored `(lane, t, value)` unchanged.
The check reads the rows before and after; it requires a non-empty
curve first, and asserts the reorder/trim itself landed. T1-2 / T6-10
only cover delete. (`studio/test_t1_1_reorder_keeps_automation.py`).

**`T1-9b` is built (2026-08-14).** `mixer.rms_per_second` / `mixer.rms_slope`
are the one RMS/s implementation. A stored `gain_db` ramp −12→0 dB over 6 s
on a constant 1 kHz sine, rendered through `mix_audio` (not `_audio_chain`),
has measured slope within `GAIN_CURVE_SLOPE_TOLERANCE` (0.5 dB/s) of drawn
2.0. The same fragment with `suppress_loudnorm` forced off misses that
bound — that is the 5.0(c) mutation. The fixture is a constant sine
because RMS slope on program material is not a proxy for gain.

**`T1-10` is built (2026-08-14).** A fully-populated lane (`MAX_POINTS`
zigzag over 1800 s so linear sampling hits `SWEEP_MAX_STEPS`) emits an
`asendcmd` string ≤ `FILTER_EXPR_MAX_BYTES` (8 KB) and `mix_audio`
writes a file from it. `fragment` refuses a longer string in Python
rather than handing ffmpeg a graph it will reject. Measured on
`gain_db` / `lowpass_hz` / `highpass_hz` in
`studio/test_t1_10_filter_expr.py`.

**`T1-11` is built (2026-08-14).** `POST /api/sets/{id}/items/{iid}/automation/{lane}`
writes one lane through `automation.save`. Two points at the same `t` are
400 and the body names that `t`. The module demo already refused; the
route is what the client posts to.

**`T1-12` is built (2026-08-14).** Per remaining lane, `mix_audio` of the
drawn curve vs flat: `pan` 0→+1 moves `lr_energy_ratio` by at least
`LR_ENERGY_DELTA` (0.08); `lowpass_hz` 400 Hz / `highpass_hz` 4 kHz drop
the attenuated band by at least `BAND_ENERGY_RATIO` (4). `gain_db` RMS/s
stays T1-9b. This is the criterion that catches a lane wired into the UI
and not into the graph, which is how `_apply_beatmatch` was unreachable
for a whole session.

### 5.4 Peaks and preview

Peaks: computed on the **existing** `analyse` job, which already decodes the file
— do not decode it twice. Stored beside the song, served decimated at
`PEAKS_MAX_POINTS = 2048` per request. Decimation is a **min/max reduce, not a
resample** (`T1-14`): a waveform that under-reports a peak lies about where the
loud part is. The reduce is `mixer.peaks(samples, z)` (`T1-13`/`T1-14`).
`GET /api/songs/{id}/peaks` serves `{song_id, z, n, pairs, reason}`:
`reason` is `null` when there are pairs, and `no_audio` / `missing` /
`unreadable` when `pairs` is empty (`T1-15`). A flat line is silence;
empty without a reason is forbidden. Song peaks are served. The set
timeline still paints `waveform_png`, not those pairs — that swap is
the leftover, not the API. `/api/sets/{id}/peaks?z=` is not a TRD-1
criterion.

The limit is stated in the design because it will otherwise be discovered by a
feature request: `analyse.py` loads mono at 22050 Hz, chosen because it matched
the measured tempo and halved load time. That is an envelope. A stereo waveform,
or anything claiming to show clipping, is a **second decode** and must be asked
for deliberately.

Preview: the browser plays source files with gain and position applied. **No
second DSP engine in Web Audio.** The proxy declaration is data —
`{"is_proxy": true, "not_applied": [...]}` — computed from the item's actual
effects by `mixer.preview_proxy` and served at `GET /api/sets/{id}/preview`,
so `T1-16`'s test (add an effect, see it appear in `not_applied`) fails
a static list. "Render preview" (`T1-17`) is `mixer.render_preview`: the
*same* `mix_audio`/`render_set` path as a full render, then a cut of
`PREVIEW_SPAN` (20 s) around the playhead, served at
`GET /api/sets/{id}/preview/render?at=&secs=` as `{is_proxy: false, ...}`.
It is the only preview that claims accuracy. `waveform_png` stays the
picture.

### 5.4a The time axis — built

`mixer.timeline_axis(duration_s)` turns `mixer.set_duration()` into ruler ticks.
`set_detail` passes that duration through — no second length arithmetic.
The HTML is a view: `.tl-axis` / `.tl-tick[data-t]`. A TestClient GET (no JS)
must carry the ticks, and a stub offset must move the last one
(`studio/test_t1_timeline.py`).

Joins, playhead and lanes sit on the same clock. `mixer.timeline_joins`
walks items with `_advance` so a fade's handle is the overlap start;
`POST /sets/{id}/items/{iid}/join` writes only `secs`. `mixer.timeline_playhead`
clamps `?at=` to `set_duration()`. `mixer.timeline_lanes` lifts item-relative
automation `t` onto the set axis; the HTML is `.tl-lane-pt[data-t][data-value]`.
Easy omits `.tl-lanes` (affordance, not CSS) and does not delete the rows.

### 5.5 Clip length: one blocked chain, and the order it unblocks in

`build_song.clip_seconds(scene_seconds)` **returns the legal 8n+1 length** at
`LTX_FPS`. `None` is a storyboard written before the column existed and still
returns `CHUNK`, so nothing already on disk changes length. `n_clips_for` is
`ceil(duration / clip_seconds(...))` — duration is the dividend, the legal
length is the divisor, the count is ours. `clip_plan` (the allocator
`build_refs` / `reroll_refs` / `build_song.main` share) defaults that count
through `n_clips_for(track, scene length_seconds)` — not
`ceil(track / CHUNK)` (**refs-length**, `test_refs_length.py`). Each
ref graph also writes `clip_NNN.expect.json` via `build_refs.ref_expect`
with `clip_seconds` / `legal_frames` (CHUNK only when
`length_seconds` is missing); `pipeline.gen_refs` stamps those expects
and submit skips `.expect.json` (**refs-length per-clip**,
`test_t2_refs_clip_seconds.py`).

1. `T2-12a`: seconds → nearest **legal** frame count at the clip's fps. F-2's
   rule is that `frames ≡ 1 (mod 8)` serves both models, since every `8n+1` is
   also `4(2n)+1`; the tie-break is half-to-even (77 is equidistant from 73 and
   81, and the code lands on 81). **Built.** `clip_seconds` honours it.
2. The renderer takes a length. **Built (`T2-13a`).** `EmptyLTXVLatentVideo.length`
   and `TrimAudioDuration` follow `legal_frames(clip_seconds)`, not
   `LTX25_LEN`/`CHUNK`. Missing `length_seconds` stays 81 / `CHUNK`. `T5-9` is
   the ceiling **gate** on that request: over the labeled measured/chosen
   ceiling is refused or split, not annotated. It does not change the planner
   divisor — `clip_seconds(30)` and `n_clips_for(…, 30)` stay.
3. Then `T2-8`/`T2-9`. **`T2-8b` built.** `_compose` stamps `start`/`end`
   covering `[0, song.duration]`; `validate` refuses a gap or overlap
   (`test_t2_8b.py`). **`T2-8c` built.** `_compose` stamps `lyric_sections`
   as a partition of `parse_sections(audio_lyrics)`; `validate` refuses
   a missing field, an unnamed section, or a section named twice
   (`test_t2_8c.py`). **`T2-9` built.** larger `scene_seconds` never returns
   more scenes for the same song (`test_t2_9_monotonic.py`). `T2-13b` and
   `T2-13c` are not blocked on the
   renderer: `h_storyboard` upserts the storyboard row and does not touch
   `refs`, so re-planning leaves the approved `(clip_idx, seed)` set
   identical (`T2-13b`); `approve_context` enumerates `clip_count`, so a
   20-scene storyboard lists 20 scene tiles, not 41 clip parts (`T2-13c`).
   **`T2-13e` built.** `clip_plan` with an `audio_path` sums
   `clip_seconds(length_seconds)` (CHUNK when missing) and refuses when
   that total misses the track by more than one clip. `main()` therefore
   writes no graphs. nclips-only callers are display and skip the gate.
   Scene-scoped `build_song --only` and studio `POST /clips` with
   `scene=` / `clip_idx=` skip the full-track / scene-time refuse (seam
   with `T2-25`); bare full-song POST still 400s.
   `assemble_song` keeps `-t audio_dur`; its comment no longer says
   clips are quantised so the video always overruns. **Meter honesty:**
   `storyboard.html` Coverage hint on mismatch says regenerate or edit
   `duration_guidance` to fill the track, or scene-scoped Render clip;
   bare full-song refuses. `coverage.ok` (intent≈rendered) must not
   read as "Pacing matches the track", and the off path must not claim
   stretch/compress when full-song refuses
   (`test_t2_13e_meter_copy.py`, 77s/237s fixture).
4. **`T2-47` built.** Hop 0 is LTX even when a scene is marked `s2v`
   (`T5-11` **built**, `test_t5_11_ltx_always_first.py`). One
   `build_song.main()` job with `needs_lip_sync` writes LTX hop0
   `.expect.json` 81@`LTX25_FPS` and s2v hop `.expect.json` 77@16.0;
   they differ (`test_t2_47_mixed_model.py`). Two names on a plan is
   not this check. **`T2-45` built.**
   `start_clips` asks `models.mixed_unavailable` (via `models.where()`)
   before `jobs.enqueue`: a mixed board that names a model `False` on
   every reachable backend is 400 and writes no job; `None` is a
   candidate (`test_t2_45_enqueue_unavailable.py`). **`T2-46` built.**
   A scene with `ref_motion` / `control_video` writes
   `LoadVideosFromFolder` on that clip only; `_attempt_plan` pins it
   to cerberus and the rest of the song still free-draws
   (`test_t2_46_driving_pins_cerberus.py`). **`T2-48` built.**
   Hop 0 splits on the LTX ceiling: 30 s marked `s2v` or `ltx25` →
   15 s + 15 s, each chain tiles its scene from 0 (`T2-8b`). A 30 s
   `needs_lip_sync` scene is those LTX parts plus per-part s2v windows
   (`clip_chain_plan` / `split_to_ceiling(s2v)`;
   `test_t2_48_ceilings_compose.py`). T5-12 hop graph **built**
   (`test_t5_12_d7_hop.py`).
   `grok._compose` stamps `clips` from the planned length; `validate`
   refuses a gap or overlap. `main()` expands an over-ceiling scene
   into that chain instead of handing 30 s to `workflow`. Mutation:
   treat `video_model=s2v` as hop 0 → 7 × CHUNK.
   **`T2-11` built.** `clip_chain_plan` sets `depends_on` on same-scene
   successors. `app.enqueue_clips` (called from `start_clips`) enqueues
   one job per chain clip with `jobs.enqueue(..., depends_on=pred)`;
   under-ceiling songs stay one batch job. `_claim` (T6-2) will not
   pull a successor until the predecessor is `done`
   (`test_t2_11_clip_chain_depends.py`).
   **`T2-42` / `T2-43` built.** `_scene_json` returns `video_model`
   beside `camera`; an unmarked scene stays empty and
   `clips_for_scene` / `main()` take `--video-model`.
   `EDITABLE_SCENE_FIELDS` includes `video_model`; the scene row
   shows it beside camera (`test_t2_42_scene_video_model.py`).
   Pose is a textarea. Pose-plate bind is a horizontal thumbnail
   slider (radio `sheet_id`, not a `<select>`), a floppy `.icon-btn`,
   and a `.save-note` (saved / pinned / error). Status is Pinned /
   Suggested / Missing sheet / No plate with a help icon, not
   “saved bind”.
   Scene field labels are Init Cap. Hint text is the textarea
   placeholder. Story / Image / Negative / Video Motion have Suggest
   and `field_versions`. Failed clip cards dismiss via
   `dismissed_clip_jobs`. Picking a scene prompt version writes
   `field_current` and the live field (`apply_field_version`). Song
   lyrics/style/direction/lock and album look boxes remember the last
   selected `prompt_versions` id (`prompt_current`). Video Motion Prompt sits above Clips.
   `_compose` fills a blank `video_motion_prompt` from motion + camera.
   A still is **stale** when `scene.edited` is after every candidate
   `created` (`storyboard_service.scenes`). The chip opens `#tip-modal`
   (reroll / generate from current text). `#tip-modal` Close sits after
   `.lightbox-spacer` (right of the title). Still QC is `button.qc-tag`
   with a transparent fill so the sentence stays readable accent text,
   not a primary well (`test_qc_tag_button_is_not_a_primary`). Still
   check/wrench/trash sit on `.still-icons { margin-top: auto }` so
   wrapping QC text does not offset the row.
   Scene-scoped `build_song --only` and studio Render clip (`scene=` /
   `clip_idx=`) skip T2-13e / T2-25. Scene preview is plate / stills / clips. Reroll plants
   `.ref-frame.clip-tile` shimmer cards (same 190px / 3:4 frame as a
   finished still). Render clip plants the same cards in
   `.media-strip.scene-clips` (`paintClipPlaceholders`) and calls
   `refreshQueue()` so an idle chip starts polling. `#clip-preview`
   walks the clicked `.scene-clips` strip (`thumbs(fromEl)`), not every
   `data-video` on the page. A leftover
   shimmer is cleared when that clip job is done/failed/cancelled
   (`sweepPendingClipCards` reads `/jobs/{id}`; the chip kind may be
   QC). The strip is
   also filled from `jobs` (`clip_pending` / `clip_failed`) so the
   chip going QC does not blank the row. A landed take is a
   reserved 3:4 `.still-thumb`, `<img class="clip-poster">` from the
   approved still, `<video src>` with `preload=metadata`, and a play
   badge. Click the well or the caption opens `#clip-preview`. A
   trash deletes the take (`storyboard_service.delete_clip`). Not
   `lazy-src` (`test_song_page_async.py`). Reroll note,
   seed range, Fix, and Delete live on the still. `GET /songs/{id}/approve/{tier}`
   303s to the song page. `POST /clips` accepts `scene` + `head_only`.
   `auto_qc` enqueues `qc` on that job. Dialogs share `modal_close()`.
   Stills and clips show `qc_tag`: confidence, identity, pose, notes.
   `SCORE_SYSTEM` does not treat wardrobe as an identity miss.
   `score_landed_clip` writes `clips.qc_json` from the first frame.
   **`T2-44` built.** `models.refuse_unknown_video_model` refuses a
   named model absent from `renderable("video")` at save.
   **`T2-46` built.** A scene requesting `ref_motion` or `control_video`
   pins that clip to cerberus; the rest of the song still free-draws.
   **`T2-13d` built:** `assemble_song` normalises those native rates to
   one output fps (highest) on the assembled file. Concat first-clip-wins
   is not that check.
   **`T2-13f` built.**
   `qc.clip_qc_expect` keeps that native fps as the clip's QC question;
   the song's output fps is assembly's (`T2-13d`) and is ignored here.
   Mixed s2v@16 / LTX@16.8312 each pass their own check
   (`test_t2_13f_native_fps.py`). Copying the song rate onto the clip
   flags the other model.

`W1-4` sits alongside and is a **prompt**, not code. `T2-14a` is **built**:
`grok._user_prompt` no longer names a fixed 4.8125 s quantum, does not say
nothing shorter or longer can be produced, and does not tell the model to
round `duration_guidance` to multiples of a constant. `_system_prompt` no
longer names 4.8125 s either. Unpinned generate (`scene_seconds` empty)
does not name `n_clips_for(duration)` either — that is 50 clips on
237.67 s at `CHUNK`. `T2-14b` is **built**: the TIMING clip-length
line is `clip_seconds(scene_seconds)`, so one song at two `scene_seconds`
produces two statements — a new constant 15.0 would keep the sentence shape
and fail this. `T2-14c` is **built**: the return value still states track
length and requires scene durations to sum to approximately it. Deleting
the TIMING block wholesale leaves `T2-14a` green and fails this. The
function is pure; assert on its return value, never by grepping the source.

`T2-8b` is **built**. `_compose` stamps each scene's `start`/`end` so they
tile `[0, duration]`; `validate` refuses a gap or overlap. Mutation: drop
the check → a gapped board is accepted.

`T2-8c` is **built**. `_compose` stamps each scene's `lyric_sections` so
the parsed lyric sections are a partition across scenes; `validate`
refuses a missing field, an unnamed section, or a section named twice.
Mutation: drop the check → an unnamed section is accepted.

`T2-20` is **built**. `_compose` stamps `album_arc` from `arc_ctx` beat and
continuity onto the generated board; no arc leaves the field off. Same
recorded model response both arms — two fixtures differing is not the
check. Mutation: drop `arc_ctx` from `_compose` → red.

`T2-21` is **built**. `_compose` at `xxx` strips *"fully clothed,
tasteful and non-graphic"* and *"no explicit gesture"* from each
scene's `image_prompt` and `video_motion_prompt` and stamps
*"Explicit adult content is permitted"* in their place. Same recorded
`rear-entrance_xxx.json` response; the existing direction test only
checked the guardrail sent to grok. Mutation: leave scene text
untouched → red. Mutation: strip and do not stamp → red.

`T2-22` is **built**. `_compose` stamps `guardrail` from
`tiers.compose_guardrail(tier)`, not the `guardrail` argument — a
passed-in dummy is discarded. `app.foreign_tier_in_storyboard` matches
another row's stored tone half (PINNED is shared, so composed text
would false-positive) and `save_scene` / `h_storyboard` refuse it.
A clean scene edit still writes. Mutation: drop the stamp → generation
arm red. Mutation: write without the check → save arm red.

`T2-31` is **built**; `T2-32` is **built**. `grok.write_storyboard`
refuses an empty, whitespace, or missing `character_reference` before
creating files. `save_scene` and `_apply_scene_fields` return 400 with
`grok.EMPTY_CHARACTER_REFERENCE`. The message names both D10 halves:
the text lock (species/body) plus her photographs as image1. A stranger
plate is refused. An empty lock still renders a stranger in every clip.
A filled lock still writes. Mutation: dump without the check → writer
arm red. Mutation: restore "identity comes from the text, not the
reference image" → T2-32 red.
`T2-23` is **built**. `GET /api/songs/{id}/storyboard/{tier}/meter`
reports `scene_time` (sum of scene `duration_guidance`), `song_length`
(the song duration), `tolerance` (`SCENE_TIME_TOLERANCE`, 0.15 of song
length) and `mismatch` when the absolute delta exceeds that.
In-tolerance is not flagged. Mutation: always report the numbers and
never set `mismatch` → the miss arm fails. The live `meter` component
is not this.

`T2-24` is **built**. The same meter reports `clip_seconds` from
`build_song.clip_seconds(scene_seconds)`, not `CHUNK`. Same song at
15 s and 30 s yields two lengths. Mutation: hardcode 4.8125 → both
arms equal. Mutation: return raw `scene_seconds` → 15.0 is not the
legal 8n+1 length. The live `meter` component is not this.

`T2-25` is **built**. Bare `POST /songs/{id}/clips` calls
`refuse_if_scene_time_mismatch` after the existing duration/refs
gates: a miss is 400 and writes no clips job; an in-tolerance board
still enqueues. Scene-scoped `scene=` / `clip_idx=` (Render clip)
skips that refuse, matching `build_song --only` / `T2-13e`
(`test_t2_25_scene_scoped_skips_mismatch_refuse`). An unreadable board
file is skipped so the older gates still fire. Mutation: flag only on
GET `/meter` → the miss arm fails. Mutation: scene-scoped still refuse
→ seam arm fails. Live `storyboard.html` Coverage hint on that miss
matches the refuse: fill the track via regenerate/`duration_guidance`,
or scene-scoped Render clip — not pacing-matches / stretch copy
(`test_t2_13e_meter_copy.py`).

`T2-33` is **built**. `GET /songs/{id}` builds the video-model select
from `models.renderable("video")` (labels/purpose from `catalog()`).
Adding a `CATALOG` entry with a `cli` makes that cli, label and
purpose appear with no template change
(`test_t2_33_picker_renderable.py`). Mutation: call `renderable()` and
discard it, or post-filter to a stale list → the probe is absent.

`T2-34` is **built**. The song page's clip-pass picker sets each
wired model's `available` from `models.available_on_fleet` (True if
`where()` has a confirmed box, False if every reachable backend
answered and lacks it, None if no box could be asked).
`song.html` disables `available is false` and still offers True /
None. Mutation: copy `catalog()['available']` → a model this box
does not mark False is offered. Mutation: disable every option →
the confirmed arm fails (`test_t2_34_unavailable_shown.py`).

`T2-26` is **built**. `GET /api/songs/{id}/storyboard/{tier}` includes
`anchors`: one group per character with `character`, `character_id` and
`images` (`id`, `view`, `path`, `url` via `media_url`). Protagonist
(`character_id` NULL, name `"protagonist"`) first, then cast by name.
`album_chosen_anchors` is the one query; the HTML page and the JSON
share it. Chosen sheets only. Mutation: omit the key → red. Mutation:
flat images with no character grouping → red. Mutation: drop a cast
member's chosen sheet → red.

`T2-27` is **built**. `_scene_json` includes `refs` next to
`image_prompt` / `story` / `video_motion_prompt`: per-clip `idx`,
`path`/`url` of the latest candidate, plus `candidates[]` (`id`,
`path`, `url`, `seed`, `approved`). `storyboard_scenes` is the one
mapping; HTML `_scene_row.html` and the JSON share it. Scene A does
not carry scene B's still. Another tier stays out. Mutation: omit
`refs` on the scene → red. Mutation: top-level refs only → red.
Mutation: copy another scene's still onto this scene → red.

`T2-29` is **built**. A named scene figure is `{name, role}` with
`role` in `lead` / `extra` / `background`. `_compose` keeps classified
figures (it used to drop dicts). `write_storyboard` / `validate` /
scene save refuse a named figure with no role or a free-text role.
`GET /api/songs/{id}/storyboard/{tier}/cast` returns `role` on each
figure. A bare name is a legacy lead. Mutation: coerce to strings →
compose arm red. Mutation: dump without the check → writer arm red.
Mutation: return names without role → API arm red. `T2-30` is not this.

`T2-28` is **built**. `refs_plan_blockers(song, tier, rows)` lists the
missing album protagonist **identity front** (`chosen_anchor` view
`front`) and each unanchored lead (extras / background never). Named
pose sheets do not satisfy that gate; `identity_front_blocker` names
the pose-sheet count so the operator is not told to create an anchor
they already have. The song-page storyboard panel (and the storyboard
page plan-panel) paints those as
`.plan-blocker` and marks Generate refs with `button.blocked` (never
`disabled`). `start_refs` / `POST /songs/{id}/refs` raises 400 with
the same reason and writes no refs job. Mutation: disable the
button → HTML arm red. Mutation: enqueue without the check → post arm
red (`test_t2_28_html.py`, `test_t2_28_refs_unanchored_leads.py`,
`test_identity_front_blocker_names_pose_library_when_front_is_missing`).

**refs-identity `T2-56` is built.** `start_refs`/`h_refs` pass
`accepted_bases` as `anchors` (image1 per scene). They do not also
stuff those keepers into `pose_bases` (image2). Empty / draft /
rejected map → 400 on **refs** (`start_refs`). Scene-row **Reroll**
needs a pinned plate on that scene (`scene_bases`) and enqueues those
paths as `pose_bases`; empty map + pin is allowed. No pin → 400
"pin a pose plate". `pose_plan.freeze_auto_binds` deleted; `scene_bases`
is saved `pose_sheet_id` only; `h_refs`/`h_reroll` take job
`pose_bases` or `{}` (no auto fallback;
`test_freeze_auto_binds_is_gone`, `test_t2_52_map_accept.py`,
`test_start_refs_freezes_pose_bases`,
`test_start_reroll_pinned_plate_skips_empty_map`).
Standing 4748 plate is refused (keep, `test_t2_refs_identity.py`).
Location plates (`T2-53` **built**, `test_t2_53_location_plates.py`).
Extra-view slots are later.
`test_t2_56_per_scene_keeper.py`. `scene_pose_map` is the Accept-gated
map (`T2-51`/`T2-52` **built**). The scene-row bind is a pose
textarea, then current thumb + Save plate, then a taller `pose-picks`
strip. `#pose-gallery` (search, Gallery grid, save icon) `fetch`es
`.../scene/{n}/pose-sheet` on select and paints the current thumb
from the JSON. Not a `<select>`, not a full-page submit.

**`T2-54` is built.** `storyboard_backfill.backfill(song_id, run_tiers)`
takes the existing ceiling-tier board (highest ticked) and writes only
ticked tiers at or below that ceiling. Each written board carries
`tiers.compose_guardrail(tier)` and that tier's wardrobe subset; g/pg13
clamp nude→clothed and strip `_nude` views. r+pg13 writes both;
r-only writes no pg13; g writes a clothed g board and no r/xxx.
`storyboard_service.backfill` is the thin wrapper. No `app.py` / `db.py`
route this slice. Mutation: r-only writes pg13 → red. Mutation: g
writes a nude view or r/xxx board → red
(`test_t2_54_ceiling_backfill.py`).

`T2-30` is **built**. `unanchored_leads(rows)` returns names of figures
with `role == "lead"` and no chosen anchor. Storyboard HTML banner,
`_storyboard_payload` / `GET .../cast` / storyboard JSON share that
list. Scene-row chips put `warn-tag` and "no anchor" only on unanchored
leads; extras and background stay neutral. A bare name is a legacy
lead. Mutation: list every unanchored name → extra arm red.
Mutation: never list → lead arm red. Mutation: fix API only → HTML
arm red (`test_t2_30_unanchored_leads_only.py`).

`T2-49` is **built**. `h_storyboard` offers `offered_cast(album)` — every
`characters` row — not `cast_anchors`. A missing front is a T2-28 refs
block, not a writer silence. `_cast_block` tells the model those names
are the only leads besides the protagonist, and that extras/background
may always be invented. `generate_storyboard` runs `apply_offered_cast`
so an invented lead is stored as an extra. The generate form, generation
payload, storyboard page and `GET .../cast` list `album_leads` with
`has_front` / `used`. Mutation: `cast_anchors` filter → offer arm red
(`test_t2_49_album_leads.py`).

**Cast slots** are **built**. `build_refs.scene_cast` returns only leads
(and bare names as legacy leads) that have a chosen sheet; those occupy
image2/image3. Extras and background never take those slots even when a
sheet exists. A scene of only non-leads leaves image2/3 empty.
`test_app.py::test_cast_slots_only_leads_with_chosen_sheets_take_image2_and_image3`.

`T2-44` is **built**. `models.refuse_unknown_video_model` walks the
board's scenes and raises when a named `video_model` is absent from
`models.renderable("video")` as a key *or* a cli value, quoting the
scene number and the bad value. `save_scene` and `_apply_scene_fields`
return 400 and do not write. Absent or whitespace is not a name
(`T2-42`). A real cli (`s2v`) still saves. Mutation: write without
the check → save arm red. Mutation: rewrite to `default_cli` → the
file changes and the named-value assertion fails.

### 5.6 Tier 2 is a calibration, not a metric

`vision.py` is a VLM caller and is **not** the tier-2 path. TRD-3 §10 forbids a
VLM verdict by name — asked "does this match?", a model answers yes — though it
may write a *description* attached to a finding. `app.score_generated_still`
stores that advisory `qc_json` on every landed still (anchors, refs including
`h_reroll`, artwork generate and its refine sibling, the sibling
`h_fix_anchor` writes, and pose-gap C1/C2 `h_anchor` landings —
`T3-34` **built**, `test_t3_34_pose_still_qc.py`). Landed refs resolve identity bases through
`app.ref_score_bases` → the album's chosen anchor path
(`test_h_refs_scores_vs_chosen_anchor` and the reroll/fix_ref twins); a job
plate or the broken source is not enough.
`qc_service.persist_still_qc` scores an `h_repair` dest still and a standalone
`refine_generated_still` dest onto `artefacts.qc_json` (and updates a dest
candidate row if one already exists). `h_artwork` inserts one scored `assets`
row per landed cover; it does not drop the generate when refine succeeds.
`refine_generated_still` writes a sibling via `qc_service.produce_repair` and
then scores it; it never overwrites the generate. `h_fix_anchor` is the
operator-started repair; it scores the new file and does not overwrite or
auto-heal. QC never auto-heals (`T3-18`).

Design, in the order `T3-13`…`T3-17` fix:

1. Extractor over `zimage_sweep/`'s **12 known-bad and 6 known-good** images
   (same prompt, same anchor, same day; on two seeds the model draws bare human
   legs with a cat's head at every step count, on the third it holds fur head to
   toe). **Built** as `qc.score_zimage_sweep` / `qc.identity_score`. Default
   embedder is a colour histogram (not pixel MSE, not a spatial grid).
   `siglip2_naflex` is still the intended production extractor and is not
   wired; `insightface` is the alternative.
2. Write a `calibrations` row: both distributions, the overlap, the separation,
   and **every individual file's score**. **Built** (`qc_service.run_zimage_calibration`);
   `threshold` is refused at write. That report is the T3-13 deliverable.
3. `T3-14` can set a threshold on a stored calibration and refuses without
   one, naming why. `T3-16` names overlap inconclusive and does not build
   a gate — that is a success, and the failure mode it avoids is shipping
   a threshold that splits noise. No UI.
4. `T3-15` is the regression guard: the metric must not rank a deliberate pose
   change as an identity failure. **Built** against the recorded pair that
   pixel distance got backwards — 41.1 for the wrong render, 64.7 for the right
   one.
5. `T3-17` scores **each artefact** against the chosen anchor, whatever
   caused the gap. **Built** as `qc.score_identity_artefact` (pure) and
   `qc_service.score_identity_artefact` / `run_artefact` (recorded, tier 2).
   The reachable case is a non-empty reference plus text that does not
   name the species. `qc.run` (tier 1) cannot see the score. No threshold,
   no gate. `T3-17-ui` is **built**: `GET /qc` shows compliance, variation
   and n on the finding-row (queue keeps the PASS so the scores are not
   hidden; still not a gate).

Reported per artefact: a calibrated compliance percentage, a **variation** figure
across the sampled frames, and the sample count both came from. Variation is the
one that matters more now than it did: chained clips start from a generated
frame, not an approved reference, so drift *within* a long clip is the reachable
failure. `score_identity_artefact` is that report.

### 5.7 What has to exist before a repair is a repair

`qc_service.approve()` enqueues one `repair` job with dest ≠ source. It does
not write dest and it does not run a GPU. `dispatch_repair` now turns that job
into a real candidate (`T3-23`):

1. **Remedy → action mapping.** The check's `remedy_class` (`T3-27`) picks
   the actuator: image / `edit-text` submit `pipeline.fix_ref`; clip /
   `upscale` submit `pipeline.gen_postproc`. A class of `none` is a
   named refusal, not a button. A silent `shutil.copy2` of src is still
   refused.
2. **Routing that asks first.** `models.where()` and `models.fits()` choose the
   box, `models.resolve()` names the file *that box* uses, and a pin under a
   name the box does not have is refused before submit. `T6-A6`'s three values
   stay: `False` refuses, `None` is a candidate. The refiner is ~19.6 GiB
   resident (`T3-24`): real `fits()` routes it off a 15.92 GiB card onto a
   24 GiB one that holds the correct name, and peaches cannot take the pair,
   so "clean up peaches output" means peaches renders and cerberus refines,
   and the artefact crosses boxes.
3. **A callable cross-box precondition** (`T3-25`), not a sentence:
   `can_move_output(host)` answers "can an output be moved back from this
   host", the refusal quotes that name, and when it answers yes the refusal
   stops. The flip is exercised: with the check forced true, a remote repair
   is SUBMITTED.
4. **The wording that RUNS is the stored prompts row** (`T3-20`).
   `approve()` puts `remedy_prompt_id` on the job; `_invoke_actuator`
   looks that id up via `prompts.running` and sends that text. A copied
   string on the job, or a deleted row, is not what runs. Same id is
   readable on the finding, the job, and `prompt_versions` after
   approval.
5. **Whether the refiner helps is measured, not assumed** (`T3-26`):
   `qc.measure_refiner_help` scores a labelled plain/refined set and
   fail-closes on empty / missing files / missing scores. A pass that
   does not improve the tier-2 score is a finding that says not helping.
   Catalogue `proven: opportunistic` is not the answer.

Every repair writes a **new candidate beside the original** (`T6-A5`).
`h_repair` lands dest and the original; `qc_service.listed` / `select`
list both and either is selectable. `qc_service.pair(fid)` lists both
as landed artefacts with findings and a `qc.summarise` verdict (`T3-21`),
so "did the repair help" is answerable rather than asserted.

## 6. Build order

The PRD's §6 in dependency form. An arrow is a hard edge taken from the
documents, not a preference.

    T6-13a (songs.duration)  ->  T2-12a (legal frame count + clip_seconds honours it)
                                 ->  T2-13a (renderer honours that length)
                                 ->  T2-13c (built), T2-8b (built), T2-8c (built), T2-8, T2-9 (built)
                                 ->  T2-13c (built), T2-13e (built), T2-8, T2-9 (built)
                                 ->  W2 T2-47 mixed-model native fps (built)
                                 ->  W2 T2-45 mixed unavailable refused at enqueue (built)
                                 ->  W2 T2-46 driving scene pins to cerberus (built)
                                 ->  W2 T2-48 per-scene ceilings compose (built)
                                 ->  T2-13d assembly one output fps (built)
                                 ->  T2-13f clip QC uses native fps (built)

    qc_service pattern  ->  sets_service     ->  clock/rounding, peaks, preview
                                             ->  master fix (5.2)  ->  audiences (T1-18..T1-20)
                        ->  storyboard_service ->  arc flows, meter, casting

    T3-8 RIFE expect_interpolated (built; out_fps + (n-1)*m+1)
    T3-4.1-opens image opens missing/unreadable REJECT (built; PIL; no size floor)
    T3-4.1-alpha image alpha not fully transparent (built; measure_alpha)
    T3-4.1-resolution image resolution as requested (built; PIL unit px)
    T3-36 image-latent inherits source WxH PASS (built; empty/absent still exact-match)
    T3-37 D7 look LTX vs hop (harness only; NOT MEASURED; warm_px refused)
    T3-4.2-black_frames partial black FLAG while mean PASSes (built)
    T3-4.2-size_floor clip under MIN_VIDEO_BYTES REJECT (built)
    T3-4.2-opens unreadable / no-video-stream REJECT (built)
    T3-4.2-frame_count clip frame count as requested (built; ffprobe)
    T3-4.2-luma named mean-luma check (built; measure_luma)
    T3-4.3-opens audio opens missing/unreadable/no-stream REJECT (built)
    T3-4.3-duration audio duration as requested (built)
    T3-4.3-loudness integrated loudness FLAG/PASS (built; effects.measure_loudness)
    T3-4.1-not_uniform image flat colour REJECT (built; measure_pixel_std)
    T3-4.1-not_blank image mean level above LUMA_FLOOR (built; measure_mean_level)
    T3-4.3-sr sample rate as requested (built; mixer.probe + check_audio)
    T3-4.3-ch channel count as requested (built; mixer.probe channels)
    T3-4.3-true-peak true peak vs LOUDNORM_TP (built; effects.measure_loudness)
    T3-9 band-energy silence (built)  ->  §4.3 audio tier (loudness stays effects.py)
    T3-4.3-edge leading/trailing silence (built; EDGE_SILENCE_LIMIT_S; not T3-9)
    T3-10 splice duration vs mixer.spliced_duration (built; SPLICE_DURATION_TOLERANCE)
    zimage_sweep scored  ->  calibrations row  ->  threshold (only if separated)  ->  gate UI later
    (T3-13..T3-16 landed the first three; T3-17 scores per artefact; T3-17-ui shows scores on /qc)
    T3-11 set artefact vs mixer.set_duration() (built; SET_DURATION_TOLERANCE)
    T3-23 routing (where/fits/resolve + actuator)  ->  T3-24 refiner box pick
                                                   ->  T3-25 remote-output move
                                                   ->  T3-26 labelled-set "does it help"

`duck` and `layer` are off this graph on purpose: refused everywhere and honestly
so (`T1-23`), and `layer` goes first when they are scheduled because `xfade`
already positions both streams, where `duck`'s `sidechaincompress` needs
`adelay` + `asplit` to time-align an accumulated chain.

## 7. How this design is verified

The rules the project arrived at by being wrong, as they apply to building from
this document. The first was earned on 2026-08-13 and is the newest:

0. **Assert through the shared entry point, never through the function it
   wraps.** A check aimed at the wrapped function is blind to whether its
   callers are wired correctly, so it stays green through a broken call site —
   measured on `T1-20d`, where every assertion survived a call site deliberately
   set to the wrong value. Wherever this design collapses a decision to one
   application point — `item_chains`, `mixer.set_duration`,
   `build_song.clip_plan`, `effects.measure_loudness` — the criterion goes
   **through** the collapse point, not around it. §5.2 has the mutation.
1. **Differential, or name the mutation.** Every criterion in the three TRDs
   already does one or the other.
2. **Then mutate and read what the mutation actually did.** Twelve mutations
   against one session's own checks found two that could not fail, and one of
   those was hiding a real defect. Another mutation did not mutate anything and
   the check passed — which is how a check that proves nothing survives an audit.
   §5.2 above is written the way it is for that reason: the mutation moved one
   row and left the other two alone.
3. **A refusal or a presence is half a criterion.** Each TRD carries a table of
   its one-sided criteria paired with the positive case that must also pass.
   Those tables are the work, not commentary.
4. **`grep -c "^def test_"` before and after, and never replace a slice that
   runs to the end of a file.** A deleted test does not fail. Baseline is green
   before and after — the count is deliberately not written into this document,
   because it was copied into three and all three went stale.

Plus the one that no automated check replaces: **when an image looks wrong, look
at it.** The identity collapse, the world that never rendered and the LoRA that
did nothing all passed every deterministic check this project had. QC does not
replace opening the picture; it decides which pictures to open.

## 8. Design risks

- **The service split regresses**, leaving two ways to reach the same
  logic. `T6-A2` is the guard and it must be written per loop as the loop moves,
  not at the end. Queue panel and review queue are written; set and storyboard
  land `T6-A3` with arc/playlist/cleanup/media (`test_t6_a3_*_imports_nothing_from_fastapi`).
- **Peaks get used as a quality signal.** They are a 22050 Hz mono envelope.
  Anything about clipping needs the second decode, stated in §5.4 so it is a
  decision rather than a discovery.
- **Tier 2 ships a threshold anyway** because a number exists and looks
  authoritative. §5.6's order is the whole defence, and `T3-14` refuses the
  configuration rather than trusting discipline.
- **`T2-12a` is treated as small.** It is one rounding rule, and four criteria,
  the approve grid, the time meter and the reference count all sit behind it.
