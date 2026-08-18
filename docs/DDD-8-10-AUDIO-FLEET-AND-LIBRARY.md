# DDD · Design for TRD 8-10

Status: written 2026-08-13. **Refreshed 2026-08-16 against the TRD-8/9/10
ledgers at `d782d2e`.** Product: `docs/PRD-8-10-AUDIO-FLEET-AND-LIBRARY.md`.
Contracts: TRD-8, TRD-9, TRD-10. Siblings: `docs/DDD-1-3-EDITING-AND-QUALITY.md`,
`docs/DDD-4-7-IDENTITY-AND-RENDERING.md`.

The original read-off was `c01c977`. Built-state is the TRD ledgers, not this
stamp. Where a claim is a measurement, the command that produced it is named.

---

## 1. The shape of the work, which differs per document

| | what building it means | ledger |
|---|---|---|
| **TRD-8** | a take/voice schema wired under a stage that already generates | **built**; `T8-12` provisional (no cloning path) |
| **TRD-9** | tests for behaviour that is correct and live | **built**; `T9-1`/`T9-2`/`T9-15` have red tests. gamingpc image box **CAPABLE, NOT PROVEN** |
| **TRD-10** | bulk edit plus labelling rules over four live modules | **built** (`T10-1`…`T10-26`). The plan's `library` table is still out of scope |

## 2. TRD-8 — the take model

### 2.1 What shipped, and what is still missing

`AUDIO_BUILDOUT_PLAN.md` §4 specified four tables. `takes`, `voices` and
`take_voices` exist in `db.py` and are the `T8-1`…`T8-11` store. **`library`
does not** (TRD-8 §9 left it to TRD-10, and TRD-10 did not take it). That is
the only named schema leftover; it is not a TRD-10 criterion.

What shipped at `c01c977` wrote each generated candidate as an `assets` row under
`db.DATA/audio/<slug>/`. **Nothing is overwritten**, so `T6-A5` is not violated.
`h_audio` now also writes a `takes` row via `insert_take` (`T8-1`): tags, lyrics,
seed, duration and the parameters as sent sit on the take, so a later song edit
cannot rewrite the ask. `songs.mp3_path` is not a write target. Pick is
`POST /songs/{id}/takes/{id}/pick` via `pick_take` (`T8-2`): it records
`takes.picked` and leaves the unpicked take listed and playable. Use on an
`audio_gen` asset is refused so that column cannot become the pick. The song
Media card (T8-16 bag) exposes that same pick form on unpicked takes and a
`picked` tag when already picked (`test_t8_2_media_card_pick.py`). **`T8-2a`**
is built: `insert_take` copies `songs.style_text` onto `takes.tags` when tags
are omitted (`test_t8_2a_song_style_text_is_copied_onto_the_take`).

### 2.2 The design, and the one rule it turns on

    takes(id, song_id, path, seed, tags, lyrics, bpm, keyscale, timesig,
          language, duration, params_json, parent_id, origin, created)

**`tags` and `lyrics` are copied onto the take, not joined from the song.** That
is the whole point and it looks like denormalisation until the failure is stated:
the song row moves on, and a take that reads its prompt back off the song
describes an ask that never happened. `T8-1`'s differential is exactly this —
change the song's tags after generating, and the take must still report what it
was generated with.

`parent_id` and `origin` (`generated | resynthesised | bridged` — the three
paths `h_audio` actually runs; `T8-3`) make a take's lineage readable: which
route produced it, and for a rework whether it is better than the one it came
from.

**Migration:** `T6-17`'s rule — every addition is an `ALTER`/`CREATE` and
existing rows keep working. The open question is whether existing audio `assets`
rows are backfilled into `takes` with NULL asks, or left alone; PRD §7 has it as
Jon's call. **Backfilling with NULLs is the honest option**: it says "this take
cannot tell you", where inventing an ask would be a fabricated record.

### 2.3 The repair path is built and its arithmetic has one owner

`mixer.bridge_seconds()` owns the sizing and `mixer.splice_bridge()` performs it;
the route asks rather than computing. `T8-9` states that, and it is the rule the
edge-span bug broke the first time — the route sized every bridge as
gap + 2×xfade when an edge span has only **one** seam, so a 20 s track spliced at
0.1 s came back **20.193 s** with audio missing.

The song page generate card's "Replace a span" hint shows the two-crossfade
eaten seconds as `splice_eaten_secs` = `2 * mixer.SPLICE_XFADE` from the route
(`T8-9` / `T6-A4-splice-hint`). The template interpolates that number; it does
not restate `2 * 0.25`. Stubbing `SPLICE_XFADE` moves the page
(`test_t8_9_splice_hint.py`).

**This is rule 0 of `DDD-1-3` §7 in another place**: one decision, one
application point, and the criterion asserts through the owner.

### 2.4 Voices

    voices(id, name, kind, path, reference_id, source, consent, note, created)

`kind` is `local` (a clip) or `fish` (a hosted id). **`source` and `consent` are
NOT NULL in the schema, and `insert_voice` is the gate** — empty or whitespace
is not a recorded state, and the `ValueError` names which of `source` /
`consent` is missing (`T8-10`). A row that stores both is readable via
`get_voice` and assignable on `take_voices`. `take_voices` carries per-region
parameters so a voice can apply to a span rather than a whole track.
`h_audio` records `params_json.voice_id` on every take (`T8-11`): the voice id
when one was asked, `None` when not, so the absence is a recorded answer
rather than a missing field. A take generated with a voice also lands the
whole-track assignment on `take_voices`.

Nothing here ships a cloning path for a real named person. That is `T8-12`,
still **provisional** — green today by absence, even though `T8-10` now holds.

### 2.5 The song editor inherits TRD-1's model

`T8-13` is the important one: the same `automation` rows, the same
`automation.MAX_POINTS`, RDP decimation, linear and hold only. **A second curve
model for one track is the drift TRD-1 §5.0 exists to prevent** — and §5.0's own
list of three near-duplications is the evidence that it happens by default, not
by carelessness.

**Built 2026-08-14.** The song editor is a one-item set (`sets.mode =
song_editor`) so `t` stays item-relative and the rows stay in `automation`.
`automation.editor_item(song_id)` mints that item on write, not on read.
`GET/POST /api/songs/{id}/automation/{lane}` is the surface; POST calls
`automation.save` and the response carries `item_audio` so a write is
consumed by the shared path, not stored and forgotten. The editor set is
filtered off the sets shelf — it is the song's timeline, not a second
document. **`T8-14` is built** — `_song_editor_mix_items` feeds
`mixer.set_duration` then `mixer.mix_audio` (`GET .../editor/duration`,
`POST .../editor/render`); prediction is emitted before the mix and the
probed file lands within `mixer.SET_DURATION_TOLERANCE`. **`T8-15` is
built** — `GET /api/songs/{id}/preview` returns `mixer.preview_proxy`
over the editor item's `effects_json` (`is_proxy`, `not_applied`); same
rule as T1-16 on the set surface.

### 2.6 The media menu is one bag, one service

**`T8-16` is built.** TRD-1 §11 deferred the media menu with the song editor;
this document owns it. `media_service.list_bag(song_id)` is the only assembly
point: takes (`db.list_takes`), `assets` rows of kind `audio_edit` and
`audio_original`, and `renders` rows. It returns one list plus counts and, when
empty, a non-empty `reason`. No FastAPI import (`T6-A3`).
`GET /api/songs/{id}/media` and the song-page Media card both call it, so
HTML and JSON report the same numbers and `kind:id` keys (`T6-A2`). The bag
list is T8-16; pick on take rows is T8-2 (form when not picked, tag when
picked). Use of edits stays on the edit card.

The topbar **Media** item is a submenu (`nav_service` children; `initNavDrop`
pins on click and holds 2s after leave). `GET /media`
is the chooser. New Song is `/media?new=song` (`POST /media/songs` → song
row + `audio` job with `as_new_song`). New Image is `/media?new=image`
(`POST /media/images` → `t2i` job on `T2I_WIRED` Qwen; album look
retrieved into the prompt; optional `style_lora`; lands `assets.kind=t2i`).
Parked Flux 2 / Z-Image are listed disabled. Civitai search/download is
the same `/models/civitai` as the Models page. Recent images multi-select
delete is `POST /media/images/delete`. It does not replace T8-16.

## 3. TRD-9 — testing what already works

### 3.1 The seam is already right

`pipeline._submit_and_collect` is the **only** place that branches on
`RENDER_BACKEND`, which is why the swarm path could be added without touching the
seven `gen_*` wrappers. Production runs `RENDER_BACKEND=swarm`, confirmed on the
box; the fleet answers with four backends:

    [0] cerberus   RTX 5090 Laptop  23.42 GiB   running
    [1] gamingpc   RTX 5090         31.84 GiB   running
    [2] peaches-unraid RTX 2080 Ti  10.58 GiB   running
    [3] ethan      RTX 5080 16GB    idle (opportunistic)

### 3.2 Retargeting is the design, and the retry is the fallback

`_retarget` rewrites loader filenames to the spellings a box publishes,
**per loader**, before a pinned attempt goes out. `T9-1` asserts both
alias directions (peaches fp16 ↔ cerberus bf16); `T9-2` asserts a VAE
name is never resolved out of the UNET enum (`test_trd9_fleet.py`).
`_attempt_plan` walks one free
draw then each box in turn, except a graph that loads `ref_motion` /
`control_video` (`LoadVideosFromFolder`) pins to cerberus (`T2-46`) — kjnodes
is absent on gamingpc.

**The free draw must go out byte-identical** (`T9-3`) so ComfyUI's execution
cache still hits — and that criterion was already rewritten once after a mutation
audit found it could not fail for the reason it named. It now asserts **object
identity** and counts `ListBackends` calls, because a rebuild of the same JSON
reads as "untouched" while busting the cache.

`T9-7` is why retargeting matters more than another retry: **a refused attempt
can bench a backend for the next one** — measured, about a minute of *"No
backends match"* after a validation failure.

### 3.3 The four traps become checks

Each cost a wrong diagnosis once. As criteria they cost nothing again:

- **A cache hit reads as a refusal** through Swarm and as an empty success on the
  comfy path. Any A/B uses different seeds (`T9-10`). Built:
  `pipeline.empty_render_kind` classifies byte-identical empty as `cache_hit`
  (model/node misses stay `refusal`); `ab_paths_use_distinct_seeds` refuses
  same-seed A/B. Checked by
  `test_t9_10_cache_hit_is_not_a_refusal_and_ab_uses_different_seeds`.
- **SwarmUI caches each backend's node list at connect time** (`T9-11`). On the
  studio path this is **inert**: submit stays `comfyworkflowraw` +
  `exactbackendid`, so ComfyUI validates filenames itself and Swarm's list is
  never the discriminator. Real only for Swarm's own model-based routing.
  Checked by `test_t9_11_submit_stays_comfyworkflowraw_plus_exactbackendid`.
- **ComfyUI's `/history` does not record jobs that arrived through SwarmUI**
  (`T9-12`) — it streams over the websocket instead. `/history` at 0 is not
  evidence. Checked by `test_t9_12_history_is_not_authority_for_swarm_jobs`:
  empty history before and after with a container log that shows execution is
  `ran`; the log is authority, not `/history`.
- **Nodes are never the discriminator; files are** (`T9-13`). Every node is on
  every box. **Staging a model stages its companions from `CATALOG.companions`
  in the same act** (`T9-13b`, built: `models.staging_files`); a hardcoded shell
  file list is not the path. A truncated weight at a real filename is not a
  model (`T9-13a`: `weight_available`). Staging order is fixed (`T9-13c`):
  transfer → checksums → both queues idle → restart SwarmUI → render.
  `models.staging_allows` refuses restart until checksums pass and queues are
  idle — the safety is the idle queue, not Swarm's connect-time cache (which
  cannot be read back).

### 3.4 What TRD-9 adds rather than documents

`T9-9` is built with a check: `models.by_backend` sets `empty` /
`hazard="empty"` on a reachable box holding none of the catalogue, and
`accept_backend` raises; a stocked box is accepted and remains a `where()`
render candidate
(`test_t9_9_empty_backend_refused_stocked_registers_and_renders`). Also built:
`T9-14`
(built: a render refused because the *other tenant* holds the card, naming the
tenant — `gpu.preflight` keeps who held at start so unload clearing `/api/ps`
cannot strip the name; check in `test_trd9_fleet.py`), and `T9-17` (built: `fleet_watch.once` writes
`_alert` on the state file with `delivered` True/False and the alert lines;
host up/down still advances so T9-8's once-per-edge holds).

`T9-17` is the one worth defending: **an alerting path whose failure mode is
quiet is worse than none**, because it is trusted.

`T9-18` is the operational-scope gate, not a new scheduler: a fleet op that
needs a stop names the unit via `fleet_watch.name_stop(op, services)` and
refuses a broader blast radius (the 2026-08-12 vDisk lesson — docker only, not
the array). It does not execute stops; it is the check a runbook step must
pass.

## 4. TRD-10 — one feature and a set of rules

### 4.0 Library list (`T6-A2-library`)

The catalogue page is `GET /` and `GET /songs` (same HTML handler). JSON is
`GET /api/songs`. Both report `song_count` from `library_service.numbers()`
(no FastAPI import, `T6-A3`). `#library` carries `data-song-count`; a template
that recomputes from `len(songs)` fails the stub arm
(`test_t6_a2_html_and_json_report_the_same_library_numbers`). `POST /songs`
upload is unchanged. `GET /songs` is 200, never 405.

### 4.1 Bulk edit

Server-side, one route, one transaction (`T10-6`, built: twelve-row success
writes all, a BEFORE UPDATE trigger on the seventh writes none). Every value
is checked against `genres.json` before any write (`T10-5`, built: valid genre
plus invalid `genre2` writes none). The two rules that destroy data if inverted:

- **Blank means leave alone** (`T10-3`, built: twelve songs, blank `genre`, set
  `genre2`; stored primary unchanged). Clearing needs its own control.
- **Toggle-all is scoped to the rows currently shown** (`T10-4`, built:
  `shown()` is `offsetParent`; twelve shown change, three hidden do not).

`T10-7` is built: `preview=true` on the same POST returns `would_change`, the
write's `changed` matches it, and `#bulk-count` is that number — the 12-vs-9
case. A confirmation that overstates teaches the operator to stop reading it.

### 4.2 Provider records (T10-2)

`T10-2` is a call-result contract on the vision path: `ask` / `ask_images`
return who answered (`provider` / `backend`) and whether the paid path was a
fallback (`fallback=true` when local was preferred and xAI served).
`classify_sheet` and `score_candidate` put that on the record so cost is
attributable after the fact, not inferred from a bill. A success-after-fallback
must not keep `available()`'s hope.

### 4.2a Lyrics provenance (T10-8)

A transcription and supplied text are not the same evidence — storyboard
generation reads lyrics, and a hallucinated line becomes a scene.
`lyrics.transcribe` returns which whisper package produced the text
(`backend`). `db.store_lyrics` is the write gate: a transcription requires
a backend and lands `songs.lyrics_source=transcription` plus
`songs.lyrics_backend`; supplied text lands `lyrics_source=supplied` and
clears `lyrics_backend`. Both paths are the job handler and
`POST /songs/{id}/lyrics`. A free-text source would let the criterion pass
for a row that recorded something else — `LYRICS_SOURCES` is the closed set.

### 4.2a′ Lyrics edits survive a re-fetch (`T10-9`)

`songs.lyrics_edited` is set when the operator saves lyrics (`store_lyrics`
with `source=supplied`). A re-fetch is the ordinary `transcribe` job without
`force` — the same path upload enqueues — and `lyrics.may_replace_lyrics`
refuses to overwrite when that flag is set. `h_transcribe` returns
`kept_edit` and leaves the stored text alone.

The only replace path is explicit: `POST /songs/{id}/retranscribe` enqueues
`transcribe` with `force=True`, clears `lyrics_edited` via a fresh
transcription `store_lyrics`, and writes the new draft. The song page shows
`lyrics.REPLACE_WARNING` ("Re-transcribe replaces the current lyrics,
including any edits") next to the control so the act says what it will do
before it runs.

### 4.2a2 Empty vs fetch-failed (T10-10)

An empty result is a stored status, not a bare empty string. A song with
no lyrics (`lyrics_status=empty`) and a song whose fetch failed
(`lyrics_status=fetch_failed`) are different rows even when `lyrics` is
blank — T2-8c's section coverage cannot tell them apart otherwise.
`lyrics.result_status` classifies failed / blank / present;
`lyrics.section_state` is the shared read over a song row.
`db.store_lyrics` takes `status` (`LYRICS_STATUSES`: `ok` | `empty` |
`fetch_failed`); `fetch_failed` is never inferred from blank text.
`h_transcribe` writes `empty` on a silent transcription and
`fetch_failed` on exception (job still fails). A free-text status would
let the criterion pass for a row that recorded something else.

### 4.2b The advice rules are a payload contract, not UI copy

`T10-11` marks model-authored strings **in the payload**, the same shape as
`T2-36`'s warnings-versus-notes. A client that cannot separate advice from
measurement will show the wrong one, and `DDD-4-7` §7a.2 already needs a
three-valued chip for the same reason.

The record is `{text, authored}` with `authored` one of `model` / `measurement`
/ `operator`. A measurement also carries `unit`; `advice.mark` refuses a
measurement without one. `advice.separate` is the client entry point. Each of
the four modules exposes `interface_payload`: mixadvice marks `why` against
measured `bpm`/`energy` and the operator's direction; vision marks `reason`
against a counted `cells`; lyrics marks transcribed `text` against segment
duration; chat marks every returned string and leaves `data` intact.
`POST /sets/{id}/suggest` with `Accept: application/json` is the live route.

`T10-12` is a write rule, not a label. `advice.retain` stores the proposal
(`advice_proposals`) and does not touch the target. `advice.accept` is the
human act: it calls the surface's apply function, writes the stored value,
and keeps the model on the row so "what did it suggest and what did I do"
is still answerable. mixadvice's apply writes `set_items`. The live accept
route is `POST /sets/{id}/proposals/{pid}/accept`.

`T10-13` is the persist rule for `vision.classify_sheet`. The live classify
job calls it and `qc_service.attach_sheet_review` writes the reason text on
a `sheet_review` finding. The finding's verdict is always `pass` — flagged
versus empty is not a gate (TRD-3 §10). A check that never calls
`classify_sheet` stays green; the proof is the call plus the attached text.

`T10-14` is the sharpest and the least obvious: **a model is never asked a
question whose answer it cannot be visibly wrong about.** "Does this match?" is
refused as a *prompt shape*; "describe what differs" is not. The recorded
evidence is the 41.1-versus-64.7 inversion — a plausible number, confidently
backwards — and a VLM asked the same question would have agreed with it.
**Built:** `vision.prompt_shape` refuses match questions and names the accepted
shape; `classify_sheet` asks `DESCRIBE_DIFFERS`; `describe_what_differs` is the
same surface and returns non-verdict text from `review_text`.

`T10-15` is the mixadvice half of the payload contract. Mixing is relational
("what happens at item 3 depends on what item 2 did"), so
`mixadvice.interface_payload` puts `relative_to` (from/into neighbours) on
each item and the running `order` on the payload. Reordering the set rewrites
those references. `quote_without_neighbours` drops them; `about_set` then
names a different set — advice quoted without its neighbours is not advice
about the set it came from.

`T10-16` is the image-path half of the audio/image guardrail split (`T8-4`
owns the decision; this cites it). Free text that reaches an image or video
render still runs `check_text` / `screen_prompt_field`; the audio generate
route and `make_audio` do not. The measurement is one string on both sides:
`"nursery rhyme for children"` is accepted as tags/lyrics and refused on the
**explicit** path (`xxx` direction, scene fields). `T10-18` is the g/pg13
exception.

### 4.3 One guard, several callers

`screen_prompt_field` is the single screening implementation and `T10-17` keeps
it that way. `MAX_PROMPT_FIELD` replaced `MAX_CHARACTER_FIELD` because two bounds
for one idea sat 39 characters from refusing real saved content.

**Rule 0 applies here too**: assert through `screen_prompt_field`, not through
each caller, or a caller that stops calling it stays green.

### 4.4 Minor policy (`T10-18`, `T10-20`, `T10-21`, `T10-23`, `T10-25`)

`guardrail.check_text(text, where, tier=..., field_kind=...)` is the single
screen. `policy_tier(tier)` resolves the lock: unset / blank is `xxx`
(`T10-25`). `LOCKED_DEPICT_TIERS = {g, pg13}` skips the refusal for
depiction; anything else is screened as `xxx`. `build_prompt`,
`build_song.workflow`, `build_refs.workflow`, scene save, storyboard
direction, and `screen_prompt_field` (draft / character / album form prose)
pass the tier. The storyboard JSON already carries it as `version`.
`PINNED` stays welded; `PINNED_AGE_FLOOR = 18` is the documented floor
(`T10-18c`).

`T10-18a`: at `r`, `allows_minor_mention(tier, field_kind=...)` is true only
for `MENTION_FIELD_KINDS = {lyrics, narrative}`. Render-reaching calls omit
`field_kind` (or pass a non-mention kind) and still refuse. `build_prompt`
is always a render path and never takes the mention allowance.

`T10-19a`: the form-field inventory lives in `studio/tiers.py` as
`R_ALLOWANCE_FIELDS = {lyrics, narrative}` — a positive named list at the
prompt boundary, not "whatever is not a prompt". `field_kind_for(field)`
maps only those names onto `MENTION_FIELD_KINDS`; unknown or missing field
returns `None` so `r` screens like `xxx`. A field added later is outside
until deliberately listed.

**`T10-19` escalation interlock.** `guardrail.screen_escalation(fields, dest)`
re-screens every `(field, text)` pair at the destination tier and raises
`ContentRefused` naming the field that blocks. At `r`, the T10-18a
`MENTION_FIELD_KINDS` allowance applies; at `xxx` every field is screened.
`tiers.collect_work_fields` / `screen_work_for_tier` walk the song's lyrics,
storyboards, cast and album profile. Call sites: `storyboard_service.enqueue`
(higher / non-locked tier), `tiers.set_allow_nudity` when enabling, and
`app._enqueue_anchor_jobs` when a nude view or non-locked tier is in the plan.
Scene `image_prompt` must stay adult-only at the destination: a baked PINNED
enumeration ("No minors, no children…") is a T10-19 self-trip at `xxx`.
Street Cats Rear Entrance uses the checked-in `rear_entrance_explicit.json`
adult wording; live pg13/r boards no longer carry that clause.

`guardrail.check_escalation(fields, dest_tier, **overrides)` is the same
re-screen with override kwargs accepted and discarded (`T10-20`: `confirm`,
`force`, `tier_overrides`, `profile`, `wording`, `view_override`, … — see
`ESCALATION_OVERRIDE_CHANNELS`). No channel lifts a `ContentRefused`.
Per-album `set_override` still applies tone wording on a clean (non-locked)
album.

**`T10-21` work lock.** Accepting a minor reference under g/pg13 sets
`songs.minor_locked` via `note_minor_reference` on scene save. Editing the
field to remove the wording does **not** clear the flag. `unlock_minor` /
`POST /songs/{id}/unlock-minor` re-screens every stored work field
(`work_text_fields`); it succeeds only when `references_minor` is empty, and
never rewrites asset meta. Renders made while locked stamp sticky
`meta_json.minor_lock_attribution` via `attributed_meta_for_song` /
`stamp_minor_lock_attribution`.

`T10-24`: the **send** screen runs on the final composed string after every
merge and after `PINNED` is welded — not on the field as typed.
`build_prompt` composes (user text + tier wording + `PINNED`), peels the
welded guard (longest clause first so xxx tier wording cannot self-trip),
then `check_text` on the remainder. Field entry screens remain; both run.

`T10-26`: before either allowance, `check_text` refuses when a minor hit
co-occurs with a `SEXUALISATION_TERMS` hit (lingerie-adjacent costume,
suggestive framing, fetish camera language, and explicit anatomy/act
wording). The co-occurrence is absolute — g/pg13 depiction and r
lyrics/narrative mention do not open it. Clean child text at g/pg13 and
adult sexualisation at r/xxx still pass.

`T10-23` binds **binary artefacts**, not text. A sheet rendered under a
child-permitting lock stamps `content_tier` on the asset meta
(`guardrail.stamp_content_tier` / `content_tier_of`). Selection into an
`r`/`xxx` (or unset) work as reference, anchor, plate or init runs
`guardrail.check_artefact_use` and refuses naming the source. Wired on
`_use_anchor_as_ref` (stamp), `_collect_anchor_ref_paths(work_tiers=…)`
and `assign_anchor_ref_as_sheet`. Operator-uploaded photos without a
render stamp are not child-locked.

**`T10-18b` (built):** at `xxx`, a minor reference is refused everywhere in
the work, lyrics included. `guardrail.refuses_minor_everywhere` /
`NO_MINOR_MENTION_TIERS` name the tier; `lyrics.screen(text, tier=...)` is
the lyrics/tags entry. Callers: POST `/songs/{id}/lyrics` and audio generate
when the song already has an `xxx` storyboard; storyboard `enqueue` at `xxx`
re-screens stored lyrics; transcription into an `xxx` work screens before
store. Bare audio without an `xxx` board stays off the image guardrail
(`T10-16` / `T8-4`). A clean `xxx` work still generates and renders
(`studio/test_t10_18b_xxx_no_minor.py`).

**`T10-22` (built):** the explicit path's refusal is absolute and unchanged.
Paired with `T10-18` in one test on the same string: `LOCKED_DEPICT_TIERS`
(`g`/`pg13`) accept a minor reference on `check_text` and scene save; any
tier that is not locked non-explicit (`r`/`xxx`/unset/custom) refuses that
same string on `check_text`, and the `xxx` storyboard direction and scene
fields refuse it on the HTTP surface
(`studio/test_t10_22_locked_accepts_explicit_refuses.py`). No new API —
`allows_minor_depiction` / `check_text` already own the split.

## 5. Build order

    TRD-9 tests (no new behaviour)  ->  a routing change becomes provable
    takes/voices schema  ->  h_audio writes takes (T8-1, built)
                         ->  insert_voice refuses missing source/consent (T8-10, built)
                         ->  h_audio records which voice, or none (T8-11, built)
                         ->  pick is its own record, not Use / mp3_path (T8-2, built)
                         ->  generated/resynthesised/bridged each list a take (T8-3, built)
                         ->  song editor writes the shared automation model (T8-13, built)
                         ->  song editor predicted length = rendered length (T8-14, built)
                         ->  song editor preview is a proxy with not_applied (T8-15, built)
                         ->  media bag one list, HTML=JSON (T8-16, built)
    bulk edit (T10-6 built)         ->  T10-3, T10-4, T10-5, T10-7
    advice labelling  ->  T10-11..T10-15 over the four live modules
                         ->  the picked/unpicked distinction (T8-2)
    bulk edit (T10-3…T10-7 built)
    vision provider record (T10-2 built)
    lyrics provenance (T10-8 built) ->  T10-10 empty vs fetch-failed (built)
                                    ->  T10-9 (edit survives re-fetch, built)
    advice labelling (T10-11..T10-15 built) over the four live modules
    image/audio guard split (T10-16 built; cites T8-4)

Nothing here blocks TRD 1-7. TRD-9 is first because it is cheapest and because
everything else in the project renders through the machinery it pins down.

## 6. How this design is verified

`TRD-6 §0`, plus **rule 0 from `DDD-1-3` §7 — assert through the shared entry
point, never through the function it wraps.** It applies three times in this
document alone: `mixer.bridge_seconds` (§2.3), `screen_prompt_field` (§4.3), and
the per-call backend choice in `lyrics.py`/`vision.py` (`T10-1`).

And the one this subject adds: **listen to it.** The video half of the project
learned that a render passing every check can still be wrong and that opening it
is the only remedy. Audio has the same failure mode and no habit behind it yet —
a take can measure correct loudness, correct band energy and correct duration
and still be unusable.
