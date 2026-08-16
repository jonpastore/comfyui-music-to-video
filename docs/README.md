# The document set — what owns what, and where to trust it

Written 2026-08-13. **Refreshed 2026-08-16 against the TRD ledgers at
`d782d2e`.** This is the map, and it exists because the first external
review of the PRD/DDD layer found there was none. Eleven documents grouped in
threes, each internally coherent, and nothing saying which owns which, which
label is canonical, or where a reader should trust a built-state claim. Four of
that review's "what is missing" findings are one missing document, and this is it.

---

## 1. Ownership matrix

| TRD | subject | product | design | UI/UX |
|---|---|---|---|---|
| **TRD-1** Timeline & mixing | the set editor, automation, the master | `PRD-1-3` | `DDD-1-3` | guide §1-6 |
| **TRD-2** Story arc & storyboards | album through-line, clip length | `PRD-1-3` | `DDD-1-3` | guide §1-6 |
| **TRD-3** QC & remediation | measuring output, the findings queue | `PRD-1-3` | `DDD-1-3` | guide §1-6 |
| **TRD-4** Character anchors | who the character is | `PRD-4-7` | `DDD-4-7` | guide §7a |
| **TRD-5** Clip rendering & refine | the graph, `--refine` | `PRD-4-7` | `DDD-4-7` | guide §7a |
| **TRD-6** Queue, lifecycle, storage | **§0 holds what every document inherits** | `PRD-4-7` | `DDD-4-7` | guide §7a |
| **TRD-7** Anchor variations | how many sheets, still the same person | `PRD-4-7` | `DDD-4-7` | guide §7a |
| **TRD-8** Audio & the song editor | takes, voices, splice repair | `PRD-8-10` | `DDD-8-10` | guide §7b |
| **TRD-9** The fleet | routing, staging, alerting, the shared card | `PRD-8-10` | `DDD-8-10` | guide §7b |
| **TRD-10** Library, lyrics, advice | catalogue, transcription, model opinions | `PRD-8-10` | `DDD-8-10` | guide §7b |

**When two documents disagree, `TRD-6 §0` wins.** It holds the inherited rules —
`T6-A1`…`T6-A6` (API separation, a new candidate never an overwrite,
three-valued availability) and `T6-A7`…`T6-A10` (how a criterion is verified).
Everything else cites them and must not restate them.

**Beyond that the order is: TRD > DDD > PRD > guide.** The TRD is the contract;
a PRD describing something the TRD does not require is aspiration, and a design
contradicting its TRD is a bug in the design.

## 2. Where to trust a built-state claim

**Answer: the ledger at the end of each TRD, and nowhere else.**

Every TRD ends with *"Status against the tree"* — a table naming each criterion
as built, partial, not built, **NOT MEASURED**, or blocked, with the commit and
what was measured. **"Built" means a check can go red, not that the code
exists.** That distinction is the whole point: `T4-10` read as done for a day
while `app.ALBUM_FIELDS["body"]` quietly beat the constant it asserted.

Do **not** trust a PRD or DDD that disagrees with its TRD ledger. Those
files were refreshed 2026-08-16 to match the ledgers at `d782d2e`; if they
drift again, the ledger wins. Also do not trust `docs/STATUS-2026-08-13.md`
(a snapshot, dated) or a summary in `SESSIONS.md` (a log, not a state).

**Built-state claims in this project have drifted within the hour, repeatedly.**
Three commits landed mid-review on 2026-08-13 and made a ledger stale before it
was committed. A ledger is stamped with the commit it was read at for that
reason. Re-read before acting.

## 3. Glossary — the labels that are contested

Named because several documents rely on distinctions the interface blurs, and
one label is wrong on screen today.

| term | what it is | note |
|---|---|---|
| **Album** | a body of songs sharing a look, a cast and an arc | the domain's word |
| **Playlist** | the *table* an album is stored in (`playlists`) | **the nav says "Playlists" and shows the schema to the operator.** Guide §5.1 renames it Albums |
| **Set** | a DJ mix — several songs joined with transitions | TRD-1. Not an album |
| **Anchor** | a character reference *sheet*, per album/tier/view | `anchors` table; `chosen=1` is the one clips use |
| **Ref** | a per-clip reference *frame* | `refs` table, keyed by `clip_idx`. **Not** an anchor |
| **Candidate** | any generated option awaiting a human pick | anchors, refs and repairs are all candidates (`T6-A5`) |
| **Take** | one generated candidate *for a song's audio* | TRD-8. `h_audio` lands each candidate as a `takes` row via `insert_take` (`T8-1`); never over `songs.mp3_path` |
| **View** | the camera relationship of a sheet — front, back, nude parallels | TRD-7 |
| **Tier** | the content rating: `g`, `pg13`, `r`, `xxx` | `xxx` is the operator's own label, never an MPAA rating |
| **Backend** | one GPU box registered with SwarmUI | ids **renumber**; group by `host`, and one box has one canonical host (`models.canonical_host`) |

## 4. One dependency graph, studio-wide

Local orderings live in each PRD. This is the only place they are drawn together,
and it is what the review found missing.

    T6-13a  (one column: songs.duration is the authority)
       |
       v
    T2-12a  (one rule: round seconds to a legal 8n+1 frame count)
       |
       +--> the renderer takes a length --> clip_seconds honours it (T2-13a)
       |         |
       |         +--> T2-13c approve grid, T2-8/T2-9 scene counts
       |         +--> T2-48 per-scene models, T5-* refine at real lengths
       |
       v
    everything about variable clip length

    TRD-7 view table (T7-1/T7-3/T7-5)  --> T7-13/T7-16 prompt types --> T4-18
       (must land STRUCTURALLY FIRST, its own commit, four existing views
        asserted byte-identical -- `pose` beside "standing upright, arms
        relaxed at their sides" is a shipped prompt contradiction)

    qc_service.py pattern --> sets/storyboard/arc/playlist/cleanup/media_service (T6-A3, built)
    approve() enqueues dest ≠ src (T3-6 / T3-18, built) --> T3-19…T3-27 / T3-33.a
    calibration row --> tier 2 threshold --> tier 2 UI  (never the other order)

**`T6-13a` and `T2-12a` are the two smallest items with the largest reach in the
whole set.** One column and one rounding rule.

**Capability order, decided by Jon 2026-08-13:** anchors on-model → know when a
render is wrong → clips at the length you asked. **The set timeline goes last**,
and TRD-6's queue is built **in full**.

## 5. Reviews

Every TRD has been reviewed by grok and chatgpt independently, as has the TRD 4-7
plan, the minor policy, and this PRD/DDD/guide layer. Records are in
`docs/reviews/`, each naming what was folded and what was rejected **with the
reason**. Five consecutive rounds scored **zero fabrications**, which is a
property of the brief and not of the models: it demands `UNSURE`, accepts
`NOTHING FOUND`, forbids inventing ids or quotations, and every returned claim is
checked against the tree before it reaches a document.

## 6. What no document in this set can tell you

**Whether the pictures hold.** Most TRD checks are still on strings, graphs
and schemas. `T4-13` is now **measured** on job 257 (seed 5151 PASSes 8.06;
sibling 5288 still FLAGs 14.76). `T7-7` (identity held across views) still
needs a pinned GPU four-image set — harness only, **NOT MEASURED**. 0 chosen
studio anchors.
