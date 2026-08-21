# Feature and capability parity — UX prototype

Status: ACTIVE — prototype parity review
Updated: 2026-08-21
Evidence: current rendered local FastAPI pages (`/`, `/anchors`) and the current
tree's routes/templates, plus `docs/reviews/UIUX-DISCOVERY-2026-08-19.md`.

This is a presentation map, not authorization or an implementation contract.
The mock uses synthetic data and has no API, persistence, or render connection.
`P0-1-MIGRATION-RECONCILIATION` is a deferred implementation dependency: its
legacy/shared convergence details do not alter the operator's intended keeper
experience represented here.

| Current capability / route | User value and data | Prototype disposition | Target location / treatment | Evidence or boundary |
| --- | --- | --- | --- | --- |
| Global top navigation | Cross-workspace wayfinding | REDESIGN | Attention, Library, Characters & Poses, Sets, Operations, Settings | Preserves destinations while grouping raw operations. |
| Library `/` | Dense cross-song intake, grouping, bulk metadata, per-tier status | PRESERVE | Library as operational-throughput table | Never silently converted to a gallery. |
| Media `/media` | Song/image intake and media bag | RELOCATE | Library intake and Production **Prepare** | Upload remains a first-class action. |
| Song preparation `/songs/{id}` | Analysis, lyrics, style, takes, edit audio | REDESIGN | Production workspace **Prepare** stage | All sections remain mapped; reduced disclosure friction. |
| Anchors `/anchors` | Character bases, pose coverage, generation and reference upload | REDESIGN | Characters & Poses workspace | Keeps generation and upload; shows coverage before controls. |
| Classified pose library | Pose/name/tier/usable state and image identity | PRESERVE | Characters & Poses catalog and scene-plan picker | `usable=skip` remains unavailable for references. |
| Shared keeper library / album-tier memberships | Canonical file identity plus contextual album/tier membership | REDESIGN | Plain-language asset chips: Shared, tiered, reconciled, or needs review | Synthetic state only; raw migration internals are intentionally not surfaced. |
| Legacy-only keeper | Compatibility-read asset during transition | PRESERVE | A subtle **legacy source** label only when decision-relevant | Does not become a second editable truth in the mock. |
| Keeper conflict / verification-needed | Operator decision requiring safe resolution | REDESIGN | Attention item with artifact context and explicit hold | No raw database errors or automatic resolution. |
| Playlists `/playlists` | Album arc, song grouping and cast/character context | CONSOLIDATE | Library context and Set planning | Album arc remains visible from production context. |
| Sets `/sets` and set editor | Plan, arrangement, transitions, automation, output | REDESIGN | Dedicated Set plan then DAW-like arrangement | DAW metaphor intentionally limited to time-based editing. |
| Tiers `/tiers` | Policy, scene/asset eligibility, mature-content rules | RELOCATE | Contextual tier state plus Settings policy | Tier is never inferred from lyric explicitness. |
| Storyboard routes | Tiered board, scene details, drafts and locked versions | REDESIGN | Production **Plan scenes** with version badge | Holds, stale versions and batch approval stay explicit. |
| Pose map / scene plan | Pose, location, keeper, preview, duration, lip-sync routing | REDESIGN | One scene-plan approval package | Preserves per-scene exceptions and batch decisions. |
| Reference generation | Per-scene reference, image1 keeper, location plate | PRESERVE | Production **Generate** stage | Location plate is contextual, never identity lock. |
| LTX-first clips and optional s2v hop | Clip progress, model/stage, duration validation | REDESIGN | Stage status with technical evidence disclosure | Underlying pipeline rule stays unchanged. |
| Progressive job results | In-place still/clip arrival, cancellation/retry | PRESERVE | Generate stage and contextual progress | Mock demonstrates local state only; real SSE/poll contract is later work. |
| QC `/qc` and findings | Timestamped visual diagnosis, remedy, attempt history | REDESIGN | Media-led **Review** timeline and finding inspector | Technical/creative/tier findings remain distinct. |
| Approve, override, repair, compare attempt | Human gate over a versioned artifact | PRESERVE | Review decision panel | Hard blocker, stale version, bounded repair and audit are explicit. |
| Jobs `/jobs` and fleet/model state | Diagnostics, queue, cancellation, host/model availability | RELOCATE | Operations plus contextual deep links | Jobs are not the normal production object. |
| Models `/models` | Model inventory and availability | RELOCATE | Operations | Power-user administration retained. |
| Config `/config` | Studio and automation settings | RELOCATE | Settings / Operations | Frontend visibility is not authorization. |
| Paid/cloud authorization | Egress, provider, scope, cost and expiry consent | REDESIGN | Attention decision/dialog with version binding | No cloud call occurs from mock. |
| Release destinations | Exported master, target account, visibility, per-destination state | REDESIGN | Production **Release** stage | Partial success remains legible. |
| Empty, loading, error, missing-media states | Recoverability and accurate system feedback | PRESERVE | Fixture-controlled empty, running, degraded, stale and partial states | No blank media is presented as approvable. |
| Help, dialogs, destructive actions | Discoverability and safe dismissal/confirmation | PRESERVE | Shared ghost-X dismissal; labelled confirmation actions | Matches repository modal-close contract. |

## Parity conclusion

All meaningful current destinations and core operator capabilities have a
disposition. No `PROPOSE_DEPRECATION`, `MISSING`, or material `UNKNOWN` remains
in this prototype package. Production contracts still required after a direction
is selected include authenticated authorization, authoritative mutation/version
checks, SSE/poll reconciliation, real accessibility announcement coverage, and
the separately tracked P0-1 migration reconciliation.
