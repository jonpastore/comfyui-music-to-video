# PRD · Identity, variations, rendering and the queue (TRD 4-7)

Status: written 2026-08-13. **Rewritten 2026-08-17 for Jarvis #529
(D1–D10).** Covers `docs/TRD-4-CHARACTER-ANCHORS.md`,
`docs/TRD-5-CLIP-RENDERING-AND-REFINE.md`,
`docs/TRD-6-QUEUE-LIFECYCLE-AND-STORAGE.md`,
`docs/TRD-7-ANCHOR-VARIATIONS.md`. The four documents are the machinery
for the same loop as PRD-1-3: classified library → C1/C2 at the
ceiling → Accept-gated map → per-scene keeper + location plate → LTX
first → decoded s2v hop. Do not implement from Jarvis #528.
Sequencing: `docs/PLAN-TRD-4-7.md`. Design: `docs/DDD-4-7-IDENTITY-AND-RENDERING.md`.
Sibling: `docs/PRD-1-3-EDITING-AND-QUALITY.md`.
Built-state lives in those TRD ledgers, not in this file.

This does not restate a criterion. It says who is served, what counts as
working, and what the four documents are collectively **for** — which none of
them says, because each was written to close a specific hole.

---

## 1. What these four are, together

TRD 1-3 are the surfaces where a human **decides**. These four are the machinery
that has to be trustworthy for those decisions to mean anything:

- **TRD-4 — who the character is.** The prompt that defines identity.
- **TRD-7 — how many ways you can ask to see them, and whether it is still
  them.** Variations on the same sheet-builder.

`T6-A1`'s named loop for these two, over JSON: save operator base photographs,
generate candidates for a named view, pick one, use that sheet as the next
identity lock (`test_t6_a1_anchor_loop_over_json`).
- **TRD-5 — the graph that turns a request into a clip**, and the refine pass.
  `_refine_ltx` ships variant A (`T5-1`/`T5-3`/`T5-4` built as a graph). The
  GPU pair that proves it helps (`T5-2`) and the peak-VRAM reading (`T5-5`)
  are **NOT MEASURED**.
- **TRD-6 — the queue, the lifecycle, and what joins to what.** Ledger is
  **built** (`T6-1`…`T6-A10`). `T6-18` still deletes nothing; GC is
  **deferred** (Status row; §7 **No automatic GC**).

**The single thread running through all four is identity.** An album is one
character seen from many angles across thirty-one songs, and every defect this
project has recorded most expensively has been that character quietly becoming
someone else: the identity collapse, the human body with a cat's head at cfg 7.0,
the ordinary woman by the halfway point keeping only the harness, "the character
in image 3 is reference 3" asserting a second person into a prompt that says
there is one.

## 2. Who it is for

The same single operator on a tailnet as TRD 1-3, doing a different job. Here
they are not judging a result — they are **specifying a character precisely
enough that a diffusion model cannot drift**, then asking for that character
repeatedly and cheaply.

What they need from these four, in their own terms:

1. *"Give me this character from another angle, and have it still be her."*
2. *"Let me tune the words that make her her, and keep the version that worked."*
3. *"Don't let me save something the tier forbids, or ask for something that
   cannot render."*
4. *"Tell me what is running, where, and whether it is actually alive."*
5. *"Show me, on each candidate, how well it matches the base photographs
   and the prompt I asked for — then I pick. A repaired sheet is a new
   candidate with its own score. An `h_reroll` dest, an approved repair
   dest, and a standalone refine dest are scored the same way. Per-clip
   refs score against the chosen anchor as identity bases, not a standing
   plate or the broken source. If scoring could not run, name the xAI or
   local failure; do not shrug 'unknown'. Confidence is the worse of
   identity and pose, not an average that can read 95% on a human-faced
   two-tail sheet."*
   (`T3-31`, `T4-19`)
6. *"Do not draw anatomy on a sheet that failed pose QC. Empty latent
   plus a standing photo is how we grew a human face. Photoreal Reddit
   is never her plate."* (`T3-33.b`, `T4-20`)
7. *"I have sixteen clothed pose photographs. I name each one, assign a
   tier or generate a tier version, and the identity pair stays the
   identity pair. Base cards look like candidate cards without render
   data. If I upload a sheet to the wrong tier and delete it, the
   empty card goes with the file — the row is not left behind. A
   three-body plate lives on the Actors tab, not under Meow P; I tick
   who is in the sheet (or All) on generate, on the base card, and on
   Assign as sheet. Intertwined sex uses that multi-body plate as the
   lock, not three solo fronts. Kitty, Panther, and the other models
   live once: an upload is a shared anchors row any album can
   reference, not a copy under each album folder. Historical
   Street Cats actor plates promote into that shared library;
   Meow P's album-generated candidates stay on that album."*
   (`T7-20`, `T4-25`)

## 3. The product rules

Four, and each is a thing that was learned by paying for it.

**3.1 A diffusion model has no NOT.** Day 8's rule, and day 11 removed the last
exception to it. *"No smoke"* put smoke on every sheet for the life of the
project; *"no garments, no underwear, no straps"* put a leather harness on a nude
sheet. Every positive constant is walked by a test with no exemptions, and a new
prompt type that says "no" fails the suite — deliberately.

**3.2 Identity is the text plus her photographs as image1 (D10).** Text
names species/body. Image1 is her. A plate that is not her is refused.
Measured with two one-variable differentials: (a) same photos, same
seed, same box; species named gives a feline throughout, unnamed gives
an ordinary human woman by the halfway point; (b) perfect text, stranger
plate as image1 → the plate person. This is why `T3-28` forbids
"swap in a stranger plate" as a remedy and why `T2-32`'s message names
**both** halves — not "the text, not the photo". `T2-31` still refuses
an empty `character_reference`. `T2-56` requires the accepted keeper
for **that** scene as image1. `T3-33.a` still says image FLAG/REJECT
content findings are edit-text; `T3-35` **built**
(`test_t3_35_settings_remedies.py`) adds settings remedies.

**3.3 Two clauses that contradict each other do not average — the model picks.**
Day 4 measured it: the nude clause asserted bare skin beside "entire body covered
in jet-black fur", and a fixed-seed sweep watched the model resolve towards skin
*harder* as guidance rose. Every new view, every new prompt type and every
per-album override is a new chance to write a contradiction, which is why `T7-5`
(portrait vs "full body head to toe") is called out by name. The string omit is
not enough: the portrait crop is measured on the image (`subject_bottom`), and
head-to-toe must not win the ranking against a head-and-shoulders fixture.

**3.4 Accepted-and-ignored is the defect class.** `--refine` on the default video
model returns before the refine block and says nothing. Five of six denoise
values are labelled *"on an anchor this returns noise"* and are correct because
`latent_mode` is pinned. A dropdown documenting its own uselessness is the mild
form; a flag whose whole purpose is changing the output doing nothing silently is
the severe one.

**3.5 The still that holds her and the clip that moves her are different
UNETs.** Identity stills are Qwen-Image-Edit 2511 on the operator
photographs. Clips are `ltx25` or `wan22_s2v` on the approved still.
Pony, Krea, and Flux are other generators: they can donate an anatomy
crop or make a stranger; they are not a second identity picker.
`docs/DDD-4-7-IDENTITY-AND-RENDERING.md` §1a is the when-to-use map
that a later `models.py` `family`/`stage`/`when`/`not_for` change
copies. Do not offer those families as `role=reference` defaults.

## 4. What "working" means

| # | outcome | proven by |
|---|---|---|
| P1 | A sheet cannot be produced from a silent default — no tier, view, or wardrobe falls back to something nobody chose | `T4-1`…`T4-4` |
| P2 | Text that a tier forbids cannot be saved under it, and text it permits can | `T4-5`…`T4-9` |
| P3 | The composed positive prompt contains no negation, names the body parts, names the reference slots, and never says "bare skin" on a furred character | `T4-10`…`T4-14`, `T4-18`. `T4-11` **built** (compose, `test_t4_11_fresh_album_compose_is_charcoal_brown`); render differential **harness only; NOT MEASURED** (`test_t4_11_body_colour.py`, `T4_11_REAL_PAIR_MEASURED` False) |
| P3a | Lighting lock is channel balance on the rendered sheet (olive/magenta FLAG, grey PASS), not the `BACKDROP` string. Job 257 `front_nude` seed 5151 PASSes 8.06; sibling seed 5288 still FLAGs 14.76 | `T4-13` |
| P4 | A new view is one table entry, and is tier-gated by what it *is* rather than by a list somebody remembered to update | `T7-1`/`T7-2`/`T7-3` built (`make_anchor.VIEWS` + `is_nude_view` + form/compose via `test_t7_3_new_views.py`). GPU new-view sheets NOT MEASURED |
| P5 | An approved sheet can be the identity lock for the next sheet — the lever that keeps clips on-model, applied to anchors | `T7-6`/`T7-8` built. `T7-7` harness only; GPU pair **NOT MEASURED** |
| P6 | The four things that shape every sheet — view framing, backdrop, composite, pose — are versioned, per-album prompts rather than code constants | `T7-13` built (`view:<key>` from the view table). `T7-14`/`T7-15`/`T7-16`/`T7-19` built. `T7-16`: saved `pose` version reaches compose + preview (`test_pose_is_composed_previewed_and_screened`); `apply_pose` replaces the stance (`test_pose_replaces_the_view_stance_and_does_not_sit_beside_it`). Named uploads stay `T7-20` |
| P7 | `--refine` either refines or refuses, and whether it helps is measured rather than assumed | `T5-1`…`T5-6` |
| P7a | A ×2 clip among 832×480 siblings assembles at 1664×960 with no silent letterbox; mixed aspect is refused | `T5-7` |
| P7b | Each clip ceiling is labeled measured or chosen; an over-long single-clip request is refused or split, not only annotated | `T5-9` |
| P7f | A long LTX scene is a chain whose successor graph uses `LTXVAddGuide` so the first frame is the predecessor's last | `T2-10` |
| P7c | Refine-on vs refine-off is judged on decoded frames (MAD > 0, sharpness up), not graph nodes. Missing measurement fails closed. GPU pair still NOT MEASURED | `T5-2` |
| P7d | If LTX variant B does not fit, that is a recorded finding on `ltx25` and `--refine` ships A; the upsampler is never dropped silently | `T5-6` |
| P7e | Peak VRAM of shipped refine variant A is measured on the box, or fail-closed `NOT MEASURED`. Copying the base 23.4/23.9 figure onto `refine_peak` is a quote, not a reading | `T5-5` |
| P8 | Work is pulled, not assigned; "ready" is not "queued"; every artefact's state transition is a row with a time. A re-render, refine, repair or anchor re-roll lists both candidates and either is selectable | `T6-1`…`T6-7`, `T6-A5` |
| P9 | Every artefact can be joined to what was asked of it, by one canonical path | `T6-8`…`T6-13a` |
| P10 | A killed worker leaves no half-written job; a long render does not hold the write lock | `T6-14`…`T6-16` |
| P11 | Pose QC before anatomy. Empty latent is not the identity lock for a new pose. Photoreal is not image2. Anatomy only on a pose PASS. Training a 2511 LoRA is last resort (gamingpc), not the default path | `T3-33.b`, `T4-20` |
| P12 | Qwen-Image-Edit 2511 holds her stills. LTX/WAN animate an approved still. Pony/Krea/Flux are not a second identity stack. `models.py` may grow `family`/`when`/`not_for`; it does not grow a Pony default | DDD-4-7 §1a, `T4-20`, `T2-35` |
| P13 | The #529 loop: coverage → library → Accept-gated map → per-scene keeper + location plate → LTX first → optional decoded s2v hop. One front sheet is not image1 for every scene. D7 look NOT MEASURED | `T2-50`…`T2-56`, `T4-21`…`T4-24`, `T5-11`…`T5-15`, `T7-21`…`T7-23` |

**P5's path is built; the picture look is not.** `T7-6` shipped: with
use-as-ref ticked, `gen_anchor`'s images list is exactly that sheet.
`gen_refs` passes the accepted keeper for **that** scene as image1
(`T2-56` **built**, `test_t2_56_per_scene_keeper.py`). Empty map /
draft / rejected refuse refs and reroll (`T2-52` **built**); no auto-bind
fallback; `scene_bases` is saved `pose_sheet_id` only; `h_refs`/`h_reroll`
do not fill plates from `plan()` auto. Location plates (`T2-53` **built**,
`test_t2_53_location_plates.py`). Extra-view slots are later.
`T7-7` has the offline ranking harness. The GPU four-image set is still
**NOT MEASURED**. **0 chosen studio anchors** — the factory is still on
step 1.

**P13 (the loop) is partial.** `T2-50` coverage list **is**
(`test_t2_50_coverage_list.py`). `T4-21`/`T4-22` classification_json
in sqlite **is** (`test_t4_21_classification_json.py`): album +
character, versioned, queryable; sidecars seed import only. Live empty
auto-seed **built** (`ensure_sidecar_seed` from
`_anchors_classification_ctx`; default repo
`anchor5/image-classification.json`; `library()` never reads a file).
`/anchors` paints keeper chips and import/save seed an empty library
(`test_uiux_classification_chips.py`). `T4-23`
gap **is**; the Pose catalog on `/anchors` is album-first then song-to-check, collapsed unless empty or holed, and import closes holes
without GPU. `T2-51` draft map (classify cannot write it) **is**
(`test_t2_51_classify_cannot_write_map.py`). `T2-52` Accept-gated
map **is** (`test_t2_52_map_accept.py`): Accept/Reject per scene;
`start_refs` and `start_reroll` refuse empty map, draft, or rejected;
`pose_plan.freeze_auto_binds` is deleted (`test_freeze_auto_binds_is_gone`);
`scene_bases` is saved binds only; landers do not auto-fill plates
(`test_pose_plan.py`).
`T4-24` ceiling-tier pose generate
**is** (`test_t4_24_ceiling_generate.py`): pose-gap holes → studio
jobs at the run ceiling; clothed+nude iff r/xxx. `T7-21` C1/C2
resolver **is** (`test_t7_21_c1_c2_resolver.py`): same-pose encode
vs empty 896×1216 + her keepers. `T3-34` C1/C2 landing QC **is**
(`test_t3_34_pose_still_qc.py`): pose-gap `h_anchor` landings call
`score_candidate` and store `qc_json`. Location plates (`T2-53`/`T7-22` **built**,
`test_t2_53_location_plates.py`). `T7-23` use-as-ref / map / image1 only
from `usable≠skip` **is** (`test_t7_23_usable_skip.py`). `T2-54` ceiling + ticked-lower board backfill **is**
(`test_t2_54_ceiling_backfill.py`). LTX-first (`T5-11` **built**,
`test_t5_11_ltx_always_first.py`). `needs_lip_sync` field (`T2-55`
**built**, `test_t2_55_needs_lip_sync.py`); D7 hop graph (`T5-12`
**built**, `test_t5_12_d7_hop.py`). T5-A refine on the LTX take, not
the s2v hop (`T5-14` **built**, `test_t5_14_refine_on_ltx_take.py`).
No LTX latent into WAN (`T5-15`
**built**, `test_t5_15_no_latent_handoff.py`). D7 look is `T3-37` NOT MEASURED.
`T2-56` per-scene
image1 **is** (`test_t2_56_per_scene_keeper.py`).

## 5. Priorities

Full ordering and dependencies are `docs/PLAN-TRD-4-7.md` §3-§4. The product-level
statement of it:

1. **Anchors on-model and the #529 loop.** Coverage → classified
   library → C1/C2 at the ceiling → Accept-gated map → per-scene
   keeper + location plate → LTX first → optional decoded s2v hop.
   This beats the timeline. 0 chosen studio anchors live.
2. **Make a view cheap** (P4). `T7-1`/`T7-2`/`T7-3` landed. GPU
   new-view sheets remain NOT MEASURED.
3. **Prove identity holds** (P5's `T7-7` + D10 colour). Harness built.
   GPU four-image set **NOT MEASURED**. Body clause is charcoal-brown
   (`T4-11` **built** (compose), `test_t4_11_fresh_album_compose_is_charcoal_brown`;
   render differential **harness only; NOT MEASURED**, `test_t4_11_body_colour.py`).
4. **C1/C2 resolver** (`T7-21` **built**,
   `test_t7_21_c1_c2_resolver.py`). Location plates (`T7-22` **built**,
   `test_t2_53_location_plates.py`). Use-as-ref / map / image1 refuse
   `usable=skip` (`T7-23` **built**, `test_t7_23_usable_skip.py`).
   `T7-8` image-latent is the form control; the loop uses T7-21.
5. **`--refine` is honest as a graph** (P7 / `T5-1`). T5-A stays on
   the LTX take (`T5-14` **built**, `test_t5_14_refine_on_ltx_take.py`);
   hop successors force `refine=False`. D7 hop graph
   (`T5-12`) is **built** (`test_t5_12_d7_hop.py`); look is
   NOT MEASURED (`T3-37`). No LTX latent into WAN (`T5-15` **built**,
   `test_t5_15_no_latent_handoff.py`). Variant B does not fit (`T5-6`).
6. **The queue is built in full** (P8–P10). Ledger: `T6-1`…`T6-A10`.
   `T6-18` still deletes nothing.

## 6. Scope

**In:** the four documents' 72 criteria, plus the four consolidation items in
`PLAN-TRD-4-7` §2 that give a duplicated rule one owner.

**Out, with the owner named:** the timeline, the arc, QC's tiers and repair
(TRD 1-3). The negative prompt and fast/quality mode (TRD-4 §5 owns them and
nothing here moves them). Lifecycle writes still delete nothing (`T6-18`).
Operator-confirmed clip cleanup is `T6-19` (local `os.remove`; remote only
via a known `SWARM_INPUT_DIRS` twin with a shell-quoted ssh path, else skip).
The song page shows a dry-run cleanup card after Confirm clean; real delete
still needs `dry_run=0` and `confirm=DELETE` (no auto-delete). Assembled
outputs themselves are cards (thumbnail, preview modal, operator Delete
of that file — row gone even if the mp4 is missing; file unlinked only
when no sibling row shares the path; GET is a confirm page). Reference
images list the whole chosen pose library per tier, not a single
identity-front thumb. Generate refs checkboxes enqueue a rating (tick
XXX only for XXX). Generate refs binds each
storyboard scene to a chosen pose sheet (auto-match on `pose` / story,
operator override on the scene row: strip + `#pose-gallery` search / gallery / fetch save-on-select, no reload) and uses that sheet as image2.
Identity front stays image1. The anchors page shows the album pose
roster (have/missing across every song board) and **Use as this pose**
is the keeper; the full-size lightbox classifies the open sheet onto
that roster. The album lead’s gallery tab is a renameable name
(default **Lead**), not the word protagonist. **Generate…** lists the actors Mage needs a reference
image for (the sheet’s person, plus the album lead on a partnered
stance such as cowgirl, kneeling look-back, or supine) above the grey-studio sheet prompt.
Album-coverage / scene-row keeper dropdown use that same actor pool,
so a Panther-lead partnered scene can take a Meow P / ensemble keeper
without generating a new sheet. Refs enqueue does not auto-bind an
empty map. Uploading a sheet stays on that roster tier — it does
not refresh onto G because G has more rows. "Use as reference" is
not on the tile.

**Not building**, cited not restated: no IP-Adapter / InstantID / ReActor
(TRD-4 §7, TRD-7 §5 — a multi-image edit model conditions natively); no second
graph or workflow builder (TRD-7 §1 — the anchor path already runs
`build_refs.workflow()`); no WAN refiner on LTX output (TRD-5 §1 — they do not
share a VAE); no forecast scheduling, no second queue, no distributed
coordinator (TRD-6 §7).

## 7. Risks

1. **The specification drifts from the code faster than it can be written.**
   Demonstrated rather than feared: the plan's built-ledger was stale within the
   hour, three commits landed mid-review, and `T4-10`/`T4-11` were documented as
   done while `ALBUM_FIELDS["body"]`'s default still carried the negation that
   actually rendered. **Any built-state claim is worth re-reading before acting
   on it.**
2. **A criterion satisfied by absence.** TRD-6 §8 warned that 25 unbuilt
   criteria can all go green by never building them. That warning is spent:
   the ledger marks them **built** with tests that can go red. The remaining
   one-sided risk is `T6-18` (GC **deferred**, §7 **No automatic GC**) and the GPU **NOT MEASURED** rows
   in TRD-4 (`T4-11` colour), TRD-5, and TRD-7.
3. **Prompt surface area grows faster than the checks on it.** Four new types ×
   ten views is a lot of composed text, and every combination is a chance at
   §3.3's contradiction. `T7-4` is the check that keeps it honest: two views of
   one tier compose to the same remainder but for the framing clause (and the
   nude wardrobe swap). The compose-diff is `studio/test_t7_4_framing.py`.
4. **Two sessions in one tree.** B holds every anchor source file. The plan is a
   recommendation to whoever holds the file, and `SESSIONS.md` settles a
   disagreement *before* an edit.

## 8. Open, and needing Jon

- **`T4-13` is measured on a current GPU sheet.** Job 257 Street Cats xxx
  `front_nude` seed 5151 PASSes backdrop olive 8.06 (limit 12). Sibling seed
  5288 on the same prompt still FLAGs 14.76 — the lock is seed-dependent, not
  closed for every candidate. `BACKDROP` is still not the proof.
  `T4_13_REAL_SHEET_MEASURED` is True only for sha256 `ac56dc72…238f1b`.
- **`chosen` is 0 on every anchor.** Same blocker. No prompts are invented for it.
- ~~Whether TRD-6 gets built at all this cycle.~~ **DECIDED: in full.** Struck
  rather than deleted, because the argument against it is still true — 25
  criteria rewriting machinery that currently works — and it was heard and
  overruled. Worth having in front of whoever finds it expensive later.
