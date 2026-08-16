# PRD · Audio, the fleet, and the library (TRD 8-10)

Status: written 2026-08-13. Covers `docs/TRD-8-AUDIO-GENERATION-AND-THE-SONG-EDITOR.md`
(15), `docs/TRD-9-THE-FLEET-AND-ITS-OPERATIONAL-LAYER.md` (17),
`docs/TRD-10-LIBRARY-LYRICS-AND-THE-ADVICE-SURFACES.md` (17) — **49 criteria.**
Design: `docs/DDD-8-10-AUDIO-FLEET-AND-LIBRARY.md`. Siblings:
`docs/PRD-1-3-EDITING-AND-QUALITY.md`, `docs/PRD-4-7-IDENTITY-AND-RENDERING.md`.

---

## 1. Why these three exist, and why they are different from TRD 1-7

TRD 1-7 were written **forward**: a feature was wanted, so it was specified.
These three were written **backward**, from a reconciliation
(`docs/RECONCILIATION-CODE-VS-SPEC-2026-08-13.md`) that asked a question nobody
had asked: *what does this studio do that no document describes?*

The answer was **3,147 lines of shipped code and 1,992 lines of plan documents,
none of it owned.** These three close that, and the distinction shapes
everything below:

| | TRD-8 audio | TRD-9 fleet | TRD-10 library |
|---|---|---|---|
| built? | **partly, and the central idea is missing** | **yes, entirely, in production** | partly |
| the risk | a feature that shipped without its model | machinery that promises nothing in writing | model opinions with no rules |

**TRD-9 is the unusual one and worth stating plainly: it specifies software that
already works.** Four backends, retargeting, the retry walk, input staging,
alerting and a shared GPU — roughly 1,700 lines, live in production, zero
acceptance criteria. That is the opposite of TRD-6, which specifies machinery
that does not exist. Its value is not new behaviour; it is that **a change to
routing can be shown to have broken something**, which today it cannot.

## 2. Who it is for

The same operator, in the two modes the other documents do not cover:

- **Making the music, not just the video.** TRD-8. Songs are generated,
  regenerated and repaired by ear, and the take that was not picked is evidence.
- **Keeping four heterogeneous boxes useful.** TRD-9. A 5090 laptop, a 5090
  desktop, a 2080 Ti in an Unraid container and a 5080 in WSL2, on a tailnet,
  with different weights under different filenames.
- **Getting songs into the studio and words onto them.** TRD-10.

## 3. What "working" means

| # | outcome | proven by |
|---|---|---|
| P1 | A take says what it was asked for, months later, without reading it back off a song row that has moved | `T8-1`, `T8-3` |
| P2 | Picking a take is a separate act, and the take you did not pick survives to be compared | `T8-2`, and `T6-A5` owns the rule |
| P3 | A span can be replaced without deleting audio or lengthening the song | `T8-6`…`T8-9` |
| P4 | A voice reference cannot exist without a recorded source and consent | `T8-10`…`T8-12` |
| P5 | A workflow naming a model reaches the box that holds it, under the name that box uses | `T9-1`…`T9-3` (built: `test_t9_1_*` both directions; `test_t9_2_*` per-loader; T9-3 free-draw identity) |
| P6 | A box that went away is told apart from a workflow a box refused | `T9-6`, `T9-7` |
| P6a | A fleet op that needs a stop names which service, and never more | `T9-18` (built: `fleet_watch.name_stop`; vDisk lesson — docker only, not the array) |
| P6b | An unreachable alert transport degrades to a recorded state change, never silence | `T9-17` (built: `fleet_watch` `_alert` record + check) |
| P7 | Four measurement traps that each cost a wrong diagnosis are checks, not folklore | `T9-10`…`T9-13` (`T9-10` built: cache-hit empty ≠ refusal, A/B needs distinct seeds; `T9-11` built: raw+pin; `T9-12` built: `/history` is not Swarm authority, container log is; `T9-13a`/`T9-13b` built: byte completeness; staging path reads `CATALOG.companions`) |
| P8 | A bulk edit changes exactly what was shown and asked for, or nothing | `T10-3`…`T10-7` (built) |
| P9 | A model's words are a proposal, never a verdict and never a gate | `T10-11`…`T10-15` |
| P10 | A song for a child, and a G-tier video for it, is a first-class thing this studio can make | `T10-18` (built). `T10-18a` (built: `r` may mention in lyrics/narrative only). `T10-18b` (built: xxx refuses minor refs everywhere including lyrics). `T10-19` (built: escalation re-screens whole work, names blocker). `T10-19a` (built: named-field list at the prompt boundary). `T10-20` (built: no override reaches escalation). `T10-21` (built: clear does not silently unlock; explicit unlock on empty re-screen; prior renders keep attribution). `T10-22` (built: locked accepts, explicit refuses, one string). `T10-23` closes the asset side channel (built). `T10-24` screens the final composed string after merge/PINNED weld (built). `T10-25` (built: unset tier is `xxx`). `T10-26` (built: non-nude sexualisation of a depicted minor refused at every tier) |

**P9 is the one that has no owner anywhere else.** Four modules ask a model for
words — `vision.py`, `chat.py`, `mixadvice.py`, `lyrics.py` — and the only rule
in the entire document set is a prohibition buried in TRD-3 §10. The failure is
specific and already recorded: a plausible metric ranked the wrong image first,
41.1 against 64.7, and *a VLM asked the same question would have agreed with
it*. `T10-11` now marks those words in the payload (`authored=model`,
measurements `authored=measurement` plus a unit) so a client can separate them;
`T10-12` retains a proposal and writes the stored mix only on accept, recording
the model; `T10-13` attaches `classify_sheet` text to a finding and never
uses it as a pass/fail; `T10-14` refuses "does this match?" as a prompt
shape and accepts "describe what differs" with non-verdict text;
`T10-15` marks mixadvice as relational (`relative_to` / running `order` —
quote without neighbours is a different set); `T10-16` keeps the image
guardrail off audio and still refuses the same child string on the explicit
image/video path (`T10-18` is the g/pg13 exception).

**P4 is a requirement, not a feature.** `insert_voice` is the store gate:
a voice cannot be written without a recorded source and a recorded consent
state, and the refusal names which is missing (`T8-10`). A voice that has
both is stored and usable. A voice-cloning path for a real named person is
still not shipped (`T8-12`, provisional by absence).

## 4. Priorities

1. **TRD-9 first, and it is mostly writing tests for what exists.** It is the
   cheapest of the three — the behaviour is there and correct; what is missing is
   the ability to prove a change did not break it. Everything else in the
   project renders through it.
2. **TRD-8's take model.** New generations land as `takes` rows (`T8-1`); pick
   (`T8-2`) is built — picking records `takes.picked` and does not write
   `songs.mp3_path`; Use on a generated take is refused. **`T8-3` is built** —
   generated, resynthesised and bridged each land a take listed with its
   origin and path. Takes generated before `T8-1` still cannot say what they
   were asked for. `T8-10` is the voice-store gate (built); `T8-11` is built —
   `h_audio` writes which voice produced the take,
   or that none did. **`T8-13` is built** — the song editor reads and writes
   `automation` through `automation.save` / `item_audio` (`GET/POST
   /api/songs/{id}/automation/{lane}`). **`T8-14` is built** — predicted
   length equals rendered length within `mixer.SET_DURATION_TOLERANCE`
   (`GET/POST /api/songs/{id}/editor/duration` and `.../editor/render`).
   **`T8-15` is built** — `GET /api/songs/{id}/preview` is a proxy and lists
   `not_applied` from the editor item's effects (T1-16 on this surface).
3. **TRD-10's bulk edit.** `T10-3`…`T10-7` are built: blank leaves alone, toggle-all is the shown set, invalid refuses the batch, one transaction, pre-write count equals rows changed.
3a. **TRD-10's lyrics provenance.** `T10-8` is built: a transcription stores
   which backend produced it and that it is a transcription; supplied text
   is stored as supplied with no backend, and the two remain distinguishable.
   **`T10-9` is built** — a saved lyric edit survives a re-fetch;
   `POST /songs/{id}/retranscribe` is the explicit replace path and says it
   will replace. **`T10-10` is built** — empty lyrics and fetch-failed are
   two stored statuses (`lyrics_status`), not a bare empty string;
   `lyrics.section_state` is what T2-8c's section coverage reads
   (`studio/test_t10_10_empty_lyrics.py`).
4. **TRD-10's advice rules.** `T10-2` (paid fallback marked in the record),
   `T10-11` (payload mark), `T10-12` (accept writes, records the model),
   `T10-13` (`classify_sheet` text on a finding, never a pass/fail),
   `T10-14` (match-question shape refused; describe-what-differs returns
   non-verdict text), and `T10-15` (mixadvice relational / neighbours named)
   are built. **`T10-16` is built** — the image guardrail stays off the audio
   path and the same child string is still refused on the explicit image/video
   path (`studio/test_t10_16_image_guardrail.py`; `T10-18` is the g/pg13
   exception). `T10-1` is built (per-call backend).
5. **TRD-10's minor policy.** `T10-18` is built: `g`/`pg13` may reference and
   depict. `T10-18a` is built: at `r`, lyrics/narrative may mention a minor;
   that mention never reaches a render prompt, and the work still generates
   and renders. `T10-18b` is built: at `xxx` a minor reference is refused
   everywhere including lyrics; a clean `xxx` work still generates and
   renders (`studio/test_t10_18b_xxx_no_minor.py`). `T10-18c` is built.
   **`T10-19` is built** — escalation re-screens the whole work at the
   destination tier and names the blocking reference
   (`studio/test_t10_19_escalation_rescreen.py`). `T10-19a` is built: at `r`
   the allowance is the named list `R_ALLOWANCE_FIELDS` (`lyrics`,
   `narrative`) at the prompt boundary. `T10-20` is built: no override
   channel reaches the escalation re-screen. **`T10-21` is built** — clearing
   a reference does not silently unlock; `POST /songs/{id}/unlock-minor` is
   the explicit act on an empty re-screen, and prior renders keep
   `minor_lock_attribution`. `T10-22` is built: one paired test keeps locked
   g/pg13 accept and explicit refuse on the same child string. `T10-23` is
   built: a child-locked artefact cannot be selected as ref/anchor/plate/init
   by an `r`/`xxx` work (`studio/test_t10_23_artefact_tier.py`). `T10-24` is
   built: the send path screens the final composed string after every merge
   and after `PINNED` is welded. `T10-25` is built: unset tier is `xxx` on
   every write path (`policy_tier` / `screen_prompt_field`;
   `studio/test_t10_25_unset_is_xxx.py`). `T10-26` is built.

## 5. Scope

**In:** the 49 criteria, and the five plan documents they absorb.

**Out, with the owner named:** the render queue (TRD-6), QC (TRD-3), the set
timeline (TRD-1) — TRD-8 §6 inherits its model rather than inventing one.

**Not building**, cited not restated: no second screening implementation, no
model as a gate, no custom transcription model, no clearing-by-blank
(TRD-10 §7); no forecast scheduling, no second queue, no distributed
coordinator, no SwarmUI on the Unraid box (TRD-9 §8); no second automation
model, no second loudness implementation, no image guardrail on the audio path
(TRD-8 §7).

## 6. Risks

1. **TRD-9 documents what is, and what is may be wrong.** Writing criteria for
   working code risks blessing a defect as a requirement. Each criterion states
   the measurement that produced it, so a future disagreement is with a number
   rather than with a sentence.
2. **The audio path has no equivalent of "look at the picture".** The video half
   learned that a render which passes every check can still be wrong, and that
   opening it is the only remedy. **TRD-8 §8 says listen to it**, and there is no
   habit behind that yet.
3. **P9 is a rule about restraint**, and restraint decays. The pressure to let a
   model's confident answer become a gate grows with every hour a human spends
   judging renders by hand.
4. **Most `T9-*` cannot be tested against a mock.** A benched backend is only
   the live fleet. Hermetic exceptions: the studio-path half of `T9-11`
   (submit shape `comfyworkflowraw` + `exactbackendid`) and `T9-9` (empty
   backend refused / stocked accepted via stubbed `/object_info` —
   `test_t9_9_empty_backend_refused_stocked_registers_and_renders`).

## 7. Open, and needing Jon

- **Whether the take model is retrofitted or applied going forward.** Takes
  generated before `T8-1` cannot say what they were asked for, and the answer
  determines whether the migration backfills from `assets` rows or starts clean.
- **Voice cloning at all.** `T8-10`…`T8-12` specify how it would be done safely;
  nothing says it is wanted. The plan's `voices` table implies it.
- **Whether TRD-9's criteria gate a deploy.** Writing them is cheap; running the
  live-fleet ones before every deploy is not, and the fleet is not always fully
  awake.
