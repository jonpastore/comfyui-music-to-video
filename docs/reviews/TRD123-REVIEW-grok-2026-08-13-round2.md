## 1. Contradictions between the three documents

- **TRD-1 §3.2 vs TRD-2 §3.4 (site count for the section floor).** TRD-1 still says the formula change is in TRD-2 “and the three sites §3.4 names.” TRD-2 §3.4 explicitly retracts that: “**‘Three places’ was the headline and TWO is the honest number**” (sites 1–2 live; site 3 never on the pinned path). The cross-doc dependency statement and the owning doc disagree.

- **TRD-2 W1-1 / `build_song` `LEN = 77` vs TRD-3 `T3-7` (and TRD-2 `T2-12a` / F-2).** TRD-2 states s2v clips are **77** frames at 16 fps (4.8125 s). `T3-7` requires the frame-count check to enforce **8n+1** on the finished clip, with no model exemption. 77 ≡ 5 (mod 8), so it is not 8n+1. F-2’s claim that a single `frames ≡ 1 (mod 8)` rule is “legal for both” only means 8n+1 ⊆ wan’s 4n+1; it does not make 77 legal under `T3-7`. Same tension with `T2-12a`, which forces requested lengths to 8n+1 before render.

- **TRD-3 §2.1 vs `T3-7` + current s2v lengths.** §2.1 says tier 1 in `qc.py` **already satisfies `T3-7`** (“8n+1 with the interpolated exemption”). A strict 8n+1 check cannot pass today’s 77-frame s2v outputs; either the claim of current satisfaction is false, or the implemented check is not what `T3-7` states.

- **TRD-1 `T1-20b` / default per-item `loudnorm` vs TRD-3 §6.2 loudness remedy.** `T1-20b`: master `loudnorm` appears only when something asks (gain curve / easy master); sets with only per-item `loudnorm` have **no** master stage. TRD-3 §6.2 still prescribes “re-run loudnorm **at the master**” for “audio loudness off target.” For the default no-curve set that remedy names a stage that does not exist.

## 2. Acceptance criteria that cannot fail

- **`T1-23`.** Mutation: never ship `duck` / `layer`. Refusal-everywhere stays green. The positive half correctly defers to `T1-21`/`T1-22` and marks the gap; until those exist the id is still satisfiable by absence.

- **`T2-14`.** Mutation: delete the arc wand (no handler / always 404). “Refuses to run with an empty theme prompt” remains true; there is **no** positive half in TRD-2’s pairing table (unlike `T2-5`/`T2-18`/…).

- **`T2-16`.** Mutation: never implement multi-song auto-write. “Never writes to more than one song at a time without confirmation” holds vacuously; no paired positive (e.g. confirmed multi-song apply actually writes N songs).

- **`T3-25`.** Mutation: keep “can an output be moved from this host” permanently false (or never implement repair move). Refusal stays green forever. Prose requires the check to be able to flip; that flip is **not** in the positive-half table (unlike `T3-14`/`T3-23`), so absence of lift still leaves the criterion green.

- **`T3-6` / `T3-18`.** Already marked **PROVISIONAL** while `approve()` raises; deleting repair leaves them green. Pairs correctly admit this; still cannot-fail until routing exists.

**Pairs (fair game): generally sound.** `T1-4`, `T1-24`, `T2-5`–`T2-7`, `T2-18`, `T2-33`–`T2-34`, `T2-36`–`T2-37`, `T3-1`, `T3-4`, `T3-14`, `T3-20`, `T3-22`–`T3-24`, `T3-27` positive halves actually exercise the feature. Residual hole is only the still-provisional / unlisted rows above, not a bad pairing formula.

**UNSURE:** `T1-29a` (trust boundary “stated”) — if verified only by doc/review, it never goes red under code mutation; no test shape is specified.

## 3. Specification gaps all three assume and none states

- **What “landed” / job success means for the next stage.** `T2-11` (predecessor must have landed), TRD-1 render completion, and TRD-3 QC-after-jobs all assume a reliable “output exists and is the one we asked for” signal. None of the three define it (path present vs `artefacts` row vs job status vs `collect()` finished). TRD-6 is named as owner; the three still share the assumption with no contract here.

- **Persistence of the submitted workflow / request metadata that tier-1 expectations are read from.** `T3-2` requires expectations from “the workflow the studio itself submitted.” TRD-1 (`render_set` / mixer graphs) and TRD-2 (`build_song.workflow`, clip plans) are the producers; neither requires durable request records. TRD-3 §9 hands this to TRD-6 but the producer TRDs never state an obligation to write them — a shared invisible dependency.

- **Path identity across render → collect → QC → repair → set ingest.** Findings join `artefacts(path)` (`TRD-3` schema); repairs must use a new path (`T3-6`); set export adds files (`T1-26`); clips/refs are path-addressed in TRD-2 flows. No document states normalisation, host-local vs returned path, or stability after `collect()` / rsync.

**NOTHING further** that is clearly assumed by all three and not already in the “already fixed” list (tailnet, shared loudness owner, duration tolerance, chain-readiness ownership, etc.).

## 4. Anything that is wrong

- **`T2-8a` wording vs TRD-2 §3.4 facts.** Criterion title/body: “**The three sites agree**.” Same section’s audit: only **two** sites had to move; site 3 “was never part of the defect.” The criterion asserts a false inventory.

- **`T3-7` as a universal 8n+1 law vs documented s2v frame counts.** Enforcing 8n+1 on all clips is incompatible with **77-frame** s2v outputs described in TRD-2 W1-1; see also §1. Calling that check already green in TRD-3 §2.1 is therefore wrong unless the implementation silently differs from the criterion (in which case the criterion text is wrong).

- **F-2 / `T2-12a` nearest-8n+1 at 77 frames.** 4.8125 s × 16 fps = 77; nearest 8n+1 values are **73** and **81** (tie, distance 4). No tie-break is defined, so “the” rounded length is underspecified and any claim that rounding preserves the old CHUNK duration is false.

- **Easy mode vs loudnorm cardinality (TRD-1 §5.0(c), `T1-9a`, `T1-18`, `T1-20a`–`c`).** `T1-20c` makes easy’s one-button master the master chain (includes `loudnorm`). `T1-9a`/`T1-20a` strip per-item `loudnorm` only when a **gain curve** is present. Default items still get per-item `loudnorm` (`DEFAULT_EFFECTS`). Easy on + no curves ⇒ **two** `loudnorm`s is allowed by the text; only the gain-curve case is forced to one. That conflicts with the master-stage rationale (“per-item levelling can be switched off without the set losing its level” / single set-level pass).

- **TRD-3 §6.2 loudness remedy “at the master” for all loudness-off findings.** Incorrect for sets/items that never engaged the master (`T1-20b`); see §1.

- **UNSURE (arithmetic presentation only):** `T3-24` “20.5 GB” vs “13.31 GiB + 6.3 GB” — mixed GiB/GB; 13.31 GiB + 6.3 GiB ≈ 19.6 GiB. Order-of-magnitude intent is clear; the headline figure is sloppy, not a separate behavioural bug.
