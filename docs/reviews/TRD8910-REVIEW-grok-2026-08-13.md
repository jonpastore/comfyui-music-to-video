## 1. Criteria that cannot fail — positive halves the tables missed

### TRD-8
- **`T8-5`** — Refusal/bound form (“bounds… and says which bound refused”). Passes if the audio accept path is gone or everything is rejected with any label. Table omits it. Positive half needed: in-bound tags/lyrics/duration **accepted and enqueued/generated**, and the refusal payload names the specific bound when over.
- **`T8-9`** — “Only place bridge arithmetic exists.” Pure absence. Passes if splice/bridge is deleted. Positive half needed: an edge-span repair **goes through `mixer.bridge_seconds()` and returns the expected length** (same numbers already used in `T8-6`).
- **`T8-12`** — Table admits it is provisional and green while no cloning path exists. That is a cannot-fail criterion by construction; table note ≠ a failing positive half.

### TRD-9
- **`T9-16`** — “No credential is stored in the repo” is half a criterion (absence). Passes with no credential feature at all. Positive half needed: a key **stored only via the store**, usable by the alert path, **and the store names where it came from**.
- **`T9-5`** — “Sorted to the back, not dropped” is not in the table. If consumers treat “slow” as `False`, the criterion dies quietly. Positive half: a box that cannot hold resident weights is **still a candidate** and **can be selected after** resident boxes (order assertion, not merely “not excluded in code”).
- **`T9-7`** — Framed as acceptance of a hazard (“can take a backend out”). Not in the table; see also §4. As written it is unclear what failure looks like if the walk is deleted.

### TRD-10
- **`T10-14`** — “Does this match the reference?” **refused** as a prompt shape. Classic one-sided refusal; not in the table. Positive half needed: “describe what differs” (or equivalent) **is accepted** and returns non-verdict text on the same surface.
- **`T10-6`** — One transaction. Passes if bulk edit cannot run. Positive half (only crash/all-or-nothing is implied in prose): a **successful** batch commits **all** rows; a mid-batch failure commits **none** — both measured on stored rows.
- **`T10-17`** — “One shared guard… not a per-module copy.” Absence of copies cannot fail if modules stop screening. Positive half needed: over-long/disallowed free text through **each** of the four modules is refused **via `screen_prompt_field`**, and an in-bound string **passes** (shared entry point, as §8 already demands).
- **`T10-7`** — Not one-sided in intent, but has no table row; a confirmation UI that never runs stays green. Needs: displayed count **equals** rows actually changed on a partial-match batch (the 12-vs-9 case the text names).

`NOTHING FOUND` beyond the above for criteria that are already two-sided in-body (`T8-1`, `T8-6`, `T8-11`, `T9-1`’s paired refuse/render, etc.).

---

## 2. Contradictions

- **No direct contradiction** between TRD-8 / TRD-9 / TRD-10 on the guardrail split: `T8-4` owns audio-vs-image; `T10-16` cites it. Consistent.
- **No clear restatement** of full `T6-A1`…`T6-A6` text; realisations cite (`T8-2`→`T6-A5`, `T9-4`→`T6-A6`). OK.
- **Internal tension (TRD-8):** preamble says every `T8-n` **can fail**; **`T8-12`** is explicitly green until a cloning path exists. Document disagrees with itself.
- **Internal tension (TRD-9):** **`T9-7`** pins third-party benching behaviour as a walk criterion while §3 says retargeting matters *because* refusals bench boxes — criterion vs design note not separated.
- **Inherited-rule surface gap (not a wording contradiction):** none of the three adds a failable check that **song-editor / bulk-edit / advice accept/apply** operations are JSON-reachable and that HTML and JSON report the same numbers (`T6-A1` / `T6-A2`). They inherit by citation only. If inheritance is enforced elsewhere, fine; if not, these surfaces are unpinned. **UNSURE** without TRD-6 body.

`NOTHING FOUND` for “document A says X, document B says not-X” on a shared fact.

---

## 3. Boundary defects

**Claimed by two (overlap / dual ownership risk)**  
- **`pipeline._retarget` / `models.ALIASES`:** TRD-8 §2 lists ACE-Step per-box filename retarget as “built”; TRD-9 owns failable retarget criteria (`T9-1`, `T9-2`). Behaviour specified once (TRD-9) but audio path depends on it without a TRD-8 criterion that audio workflows retarget — regression on audio spelling can stay green under TRD-9 fixtures that never submit ACE-Step.  
- **Child-string guardrail:** `T8-4` and `T10-16` both require the image-path refusal half. Intentional chain; duplicate live tests likely.

**Named / absorbed then disowned**  
- **`library` table** — TRD-8 §1 greps it as a missing `AUDIO_BUILDOUT_PLAN` table and absorbs that plan; **no `T8-*` for it**. TRD-10 “library” is bulk genre fields on songs / library **page**, not that table. Plan table has no owner.  
- **`take_voices` table** — same grep list in TRD-8 §1; **no criterion**. `T8-11` only requires a take “records which voice,” not the junction table the absorbed plan specified.  
- **Media menu** — TRD-8 claims what TRD-1 §11 deferred “by name” including **“the song-level audio editor and the media menu”**; criteria `T8-13`…`T8-15` cover automation/duration/preview only. Media menu disowned in criteria.  
- **`chat.py`** — TRD-10 claims the module and “arc and advice surfaces”; failable rules are generic advice (`T10-11`, `T10-12`) plus vision/mixadvice specifics. Arc chat behaviour vs TRD-2 is unspecified here — **UNSURE** what TRD-2 already pins.

**Storage / lifecycle seam (TRD-6-class risk)**  
- TRD-8 moves audio from “`assets` under `db.DATA/audio/<slug>/`” to take rows that snapshot prompt fields and support pick-as-separate-act. **Lifecycle/storage of takes, pick records, and non-overwrite** sits on TRD-6’s storage/queue territory; TRD-8 does not cite a TRD-6 storage criterion for the pick act or take listing — only `T6-A5` for non-overwrite. Same pattern that produced TRD-6.

**Cascade neither document pins**  
- Lyrics with child mentions **accepted** (`T8-4` / `T10-16`) and lyrics **feed TRD-2 section structure** (`T10-10`). No criterion on whether storyboard/scene derivation from those lyrics re-introduces refused image-path text or silently strips it.

---

## 4. Decisions that look wrong  
*(name → alternative → measurement that settles)*

1. **`T8-12` as a standing criterion while cloning does not exist**  
   Alternative: drop until a cloning path is proposed; keep `T8-10`/`T8-11` only.  
   Measurement: criterion suite goes red if cloning is added without consent — today it cannot go red; count of forced-red paths = 0.

2. **`T9-7` as acceptance of Swarm benching after validation failure**  
   Alternative: trap/note only; criterion = walk **still finishes** on another box (or requeues per `T9-6`) after a validation refuse, without requiring the bench duration.  
   Measurement: after a deliberate validation refuse on box A, attempt N+1 on A within the “~minute” window vs skip-to-B; job terminal state and backend id of the successful attempt.

3. **`T9-9` “refused or flagged”** for empty backends  
   Alternative: **refuse register** only, or flag **and** exclude from free draw until stocked.  
   Measurement: register backend with empty `models/`; count free-draw submissions to it and refuse rate (doc already claims free draw hands it jobs).

4. **Take model = new tables (`takes` / `voices` / …) rather than `assets` + mandatory snapshot fields**  
   Alternative: keep `assets` layout; require snapshot columns/JSON on the asset row; pick = pointer update + history row.  
   Measurement: can `T8-1`/`T8-2`/`T8-3`/`T8-11` be asserted on current `assets` rows without `CREATE TABLE takes`? If yes, tables are not the requirement.

5. **`T10-14` ban on yes/no “match?” prompt shapes as a global enforceable rule**  
   Alternative: ban model output as gate/verdict only (`T10-11`–`T10-13`); allow match questions if answer is non-binding and labeled.  
   Measurement: inventory every prompt string in `vision.py` / `chat.py` / `mixadvice.py`; how many are closed yes/no; whether any remaining path can write a stored decision without a human act.

6. **Soft preference “local gateway first” without a criterion for tie-break when both work** (`T10-1` only proves switch after outage)**  
   Alternative: explicit order criterion when both up (local wins / sticky / etc.).  
   Measurement: both up; N identical calls; provider distribution in the records `T10-2` requires.

7. **Pinning live-fleet-only verification (TRD-9 §9) as the way “every criterion” is verified**  
   Alternative: split: hermetic tests for pure functions (`_retarget`, three-valued consumers); fleet tests for `T9-6`/`T9-7`/`T9-11`.  
   Measurement: how many `T9-*` can fail on a dark CI with no boxes; if answer is ~0, the suite cannot gate merges.

---

## 5. What is missing  
*(implied behaviour, no criterion)*

**TRD-8**  
- **Pick act:** `T8-2` says picking is separate and both takes stay playable; nothing requires that pick **sets** `songs.mp3_path` (or equivalent), **records which take** was picked, and is itself a listed/auditable act.  
- **Regenerate from take snapshot:** `T8-1` motivates regenerate/explain from the take; no criterion that “regenerate this take” uses **take** fields, not current song row.  
- **All three path labels** on real outputs: generated / resynthesised / bridged (`T8-3` names them; no requirement each path is produced and labeled in one suite).  
- **Voice consent vocabulary / revocation** after `T8-10` store.  
- **Song editor write path:** reads/writes same automation model (`T8-13`) but no criterion that an editor gesture **persists points** and round-trips under `automation.MAX_POINTS` / RDP.  
- Absorbed plan tables **`library`** and **`take_voices`** (see boundaries).

**TRD-9**  
- **Exhausted walk:** every box vanished or refused → job terminal state, operator-visible reason, no silent drop.  
- **`BACKEND_STABILITY`** (in “what exists”) — no criterion that stability affects routing differently from speed/`fits`.  
- **`install_input` failure** (rsync/chmod) — refuse vs retry vs wrong-box render.  
- **`RENDER_BACKEND` / comfy default branch** — presence in §2, no failable parity or switch criterion.  
- **In-flight jobs** across `fleet_watch` state transitions (alert ≠ job policy).

**TRD-10**  
- **Published lyric fetch** vs transcription (module claims both; criteria skew transcription `T10-8`/`T10-9`).  
- **`vision.py` call sites** beyond `classify_sheet`: contact-sheet review, anchor description, cast proposal, edit-instruction parsing — only generic proposal rules + `T10-13`.  
- **Accept path for mixadvice** detail: retained proposal **content** equality to what was shown; reject leaves store unchanged.  
- **Lyrics → TRD-2 storyboard** with audio-only-allowed strings (child mentions): strip, refuse scene gen, or pass through — unspecified.  
- **Bulk edit:** concurrency with single-song edit; non-genre fields explicitly out of scope (§7) but no criterion that those fields are **rejected** if submitted.

**Cross-cutting**  
- JSON/HTML parity and service-layer import rules on **new** surfaces (editor, bulk edit, take pick, advice accept) — inherited, not evidenced here.

---

## 6. What I would cut

- **`T8-12`** until a real voice-cloning path is in scope (keep `T8-10`/`T8-11`).  
- **`T9-7` as a criterion**; keep as §5 trap text. Replace with a walk **progress/completion** criterion if needed.  
- **`T9-12` / `T9-10` (and arguably `T9-11`)** from product acceptance tables — they are **measurement hygiene / operator diagnosis** rules. Keep as mandatory test-method notes, not “studio promises.”  
- **TRD-8’s claim to own `AUDIO_BUILDOUT_PLAN`’s `library` table** without criteria — either cut the claim or add criteria; as written it is inventory theatre.  
- **Duplicate image-refusal half** living as full criteria in both `T8-4` and `T10-16` — one owner (`T8-4`), one cite (`T10-16`) without a second full positive-half suite (or single shared test id).  
- **Provisional/green-forever rows** in any “positive half” table (`T8-12`) — they train the suite to ignore cannot-fail shape.

---

**Note:** Claims above refer only to ids, paths, and quotations present in the three TRD texts you pasted. Behaviour of unshipped TRD-1…7 bodies was not verified; cites to `T6-14`, `T1-7`, `T1-16`, `T2-8c`, `T2-36`, `T3-11`, `T5-5`, `T6-4` are taken as named by these docs only.
