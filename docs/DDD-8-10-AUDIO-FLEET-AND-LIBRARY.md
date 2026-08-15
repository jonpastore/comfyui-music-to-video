# DDD · Design for TRD 8-10

Status: written 2026-08-13. Product: `docs/PRD-8-10-AUDIO-FLEET-AND-LIBRARY.md`.
Contracts: TRD-8, TRD-9, TRD-10. Siblings: `docs/DDD-1-3-EDITING-AND-QUALITY.md`,
`docs/DDD-4-7-IDENTITY-AND-RENDERING.md`.

Everything below was read off the tree at `c01c977`, deployed to production the
same day. Where a claim is a measurement, the command that produced it is named.

---

## 1. The shape of the work, which differs per document

| | what building it means |
|---|---|
| **TRD-8** | a take/voice schema wired under a stage that already generates |
| **TRD-9** | tests for behaviour that is correct and unspecified — almost no new code |
| **TRD-10** | one unbuilt feature (bulk edit) plus labelling rules over four live modules |

## 2. TRD-8 — the take model

### 2.1 What is missing, exactly

`AUDIO_BUILDOUT_PLAN.md` §4 specifies four tables. At `c01c977` all four were
absent. `takes`, `voices` and `take_voices` now exist in `db.py`; **`library`
does not** (TRD-8 §9 left it to TRD-10, and TRD-10 did not take it).

What shipped at `c01c977` wrote each generated candidate as an `assets` row under
`db.DATA/audio/<slug>/`. **Nothing is overwritten**, so `T6-A5` is not violated.
`h_audio` now also writes a `takes` row via `insert_take` (`T8-1`): tags, lyrics,
seed, duration and the parameters as sent sit on the take, so a later song edit
cannot rewrite the ask. `songs.mp3_path` is not a write target.

### 2.2 The design, and the one rule it turns on

    takes(id, song_id, path, seed, tags, lyrics, bpm, keyscale, timesig,
          language, duration, params_json, parent_id, origin, created)

**`tags` and `lyrics` are copied onto the take, not joined from the song.** That
is the whole point and it looks like denormalisation until the failure is stated:
the song row moves on, and a take that reads its prompt back off the song
describes an ask that never happened. `T8-1`'s differential is exactly this —
change the song's tags after generating, and the take must still report what it
was generated with.

`parent_id` and `origin` (`gen | cover | repaint | svc`) make a repaint's lineage
readable, which is what turns "is this any good" into "is this better than the
one it came from".

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
**per loader**, before a pinned attempt goes out. `_attempt_plan` walks one free
draw then each box in turn.

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
  comfy path. Any A/B uses different seeds (`T9-10`).
- **SwarmUI caches each backend's node list at connect time**, so a box that
  connected while its ComfyUI was booting refuses a node it plainly has
  (`T9-11`).
- **ComfyUI's `/history` does not record jobs that arrived through SwarmUI**
  (`T9-12`) — it streams over the websocket instead. `/history` at 0 is not
  evidence.
- **Nodes are never the discriminator; files are** (`T9-13`). Every node is on
  every box.

### 3.4 What TRD-9 adds rather than documents

Only three things are genuinely new work: `T9-9` (registering an empty backend is
refused or flagged — ethan joined with `models/` at 8 KB and would have been
handed real jobs), `T9-14` (a render refused because the *other tenant* holds the
card, naming the tenant), and `T9-17` (an alert transport whose failure degrades
to a recorded state change, never to silence).

`T9-17` is the one worth defending: **an alerting path whose failure mode is
quiet is worse than none**, because it is trusted.

## 4. TRD-10 — one feature and a set of rules

### 4.1 Bulk edit

Server-side, one route, one transaction (`T10-6`), every value checked against
`genres.json` before any write (`T10-5`). The two rules that destroy data if
inverted:

- **Blank means leave alone** (`T10-3`). Clearing needs its own control.
- **Toggle-all is scoped to the rows currently shown** (`T10-4`), because the
  header sort and filters are live and off-screen edits are invisible.

`T10-7`'s pre-write count must be the count that actually changes — a
confirmation that overstates teaches the operator to stop reading it.

### 4.2 The advice rules are a payload contract, not UI copy

`T10-11` marks model-authored strings **in the payload**, the same shape as
`T2-36`'s warnings-versus-notes. A client that cannot separate advice from
measurement will show the wrong one, and `DDD-4-7` §7a.2 already needs a
three-valued chip for the same reason.

`T10-14` is the sharpest and the least obvious: **a model is never asked a
question whose answer it cannot be visibly wrong about.** "Does this match?" is
refused as a *prompt shape*; "describe what differs" is not. The recorded
evidence is the 41.1-versus-64.7 inversion — a plausible number, confidently
backwards — and a VLM asked the same question would have agreed with it.

### 4.3 One guard, several callers

`screen_prompt_field` is the single screening implementation and `T10-17` keeps
it that way. `MAX_PROMPT_FIELD` replaced `MAX_CHARACTER_FIELD` because two bounds
for one idea sat 39 characters from refusing real saved content.

**Rule 0 applies here too**: assert through `screen_prompt_field`, not through
each caller, or a caller that stops calling it stays green.

## 5. Build order

    TRD-9 tests (no new behaviour)  ->  a routing change becomes provable
    takes/voices schema  ->  h_audio writes takes (T8-1, built)
                         ->  insert_voice refuses missing source/consent (T8-10, built)
                         ->  h_audio records which voice, or none (T8-11, built)
                         ->  the picked/unpicked distinction (T8-2)
    bulk edit (self-contained)      ->  T10-3..T10-7
    advice labelling  ->  T10-11..T10-15 over the four live modules

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
