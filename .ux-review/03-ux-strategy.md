Status: COMPLETE
Phase: 3 — UX architecture
Last Updated: 2026-08-19
Inputs Used: `.ux-review/01-discovery.md`; `.ux-review/02-product-interview.md`; current UI/UX product-review references
Open Questions: Initial automation/QC defaults remain configurable product policy
Blocking Findings: None for isolated prototyping; known security P0s remain production blockers
Next Recommended Phase: Design directions and isolated prototype

# Meow P Studio UX strategy

## Executive assessment

The studio should evolve from a collection of pipeline surfaces into one production system organized around decisions and finished media. It must retain expert evidence while making the normal path independent of ComfyUI concepts. The redesign should not mimic a generic SaaS dashboard or a DAW everywhere. It should use three task-appropriate compositions within one coherent shell:

1. **Attention and throughput:** scan, prioritize, and resume work across productions.
2. **Scene/video production:** approve a visual plan, let QC advance work, and review exceptions in context.
3. **Set composition:** arrange approved videos on a time-based editorial canvas.

## Goals

- Make the next required human decision unmistakable.
- Let successful self-hosted work advance without supervision.
- Preserve complete evidence and expert intervention without making it the default reading order.
- Make images/video large enough for credible judgment.
- Keep long-running progress, cancellation, partial completion, retry, and recovery trustworthy.
- Preserve standalone videos while enabling non-destructive set-specific edits.
- Establish consistent language and state across Library, Song, scenes, jobs, QC, sets, and releases.

## Non-goals

- Rebuilding the application as a client-side SPA.
- Hiding diagnostic capability needed while the pipeline is still being commissioned.
- Adopting DAW chrome for pose, storyboard, or reference generation.
- Designing for phone-first production.
- Treating Tailnet containment as authorization or solving production security in a mock prototype.

## Product concepts and state

### Primary concepts

- **Production:** an individual music-video effort or a mixed-set effort.
- **Song:** source media and preparation context for an individual video.
- **Scene plan:** storyboard plus pose, location, reference, preview, and approval state.
- **Attempt:** immutable evidence for one generation/repair try.
- **Finding:** AI or operator observation tied to a scene/timestamp, severity, confidence, and disposition.
- **Decision:** approval, override, repair instruction, cloud authorization, or release action requiring the operator.
- **Output:** approved video, exported master, or per-destination release.

### Lifecycle

`Preparing → Needs approval → Rendering → Validating/repairing → Ready for review → Approved → Exported → Released`

`Needs attention` is a cross-cutting flag, never a competing lifecycle stage. Release is destination-specific and may be partially successful.

## Information architecture

### Global navigation

1. **Attention** — default landing surface; decisions, exhausted repairs, missing inputs, infrastructure failures, and paid approvals.
2. **Library** — all songs/videos, grouping, filtering, batch intake and preparation.
3. **Characters & Poses** — reusable operator bases, classified pose coverage, anchors, keepers, and missing-pose work.
4. **Sets** — set plans, arrangement, rendering, review, and release.
5. **Operations** — Jobs, Fleet, Models, and technical diagnostics. Contextual errors deep-link here without making it the normal workflow.

Settings and Help remain utility navigation. The persistent job indicator becomes fleet/work progress context, not the primary representation of production state.

### Individual-video workspace

Use a persistent stage path rather than a single long disclosure page:

`Prepare → Plan scenes → Generate → Review → Release`

- **Prepare:** audio analysis, lyrics/style, media, edit audio, character selection.
- **Plan scenes:** storyboard, pose/location mapping, references, and motion previews as one approval package.
- **Generate:** progressive references/clips, stage-level progress, local cancellation, and exception repair.
- **Review:** assembled video with timeline findings and attempt comparison.
- **Release:** export validation and destination status.

The workspace keeps the current song context visible and preserves the last active stage. A problem link opens the exact scene/timestamp and evidence, not a generic jobs page.

### Set workspace

Set plan and set editor are distinct steps. The plan explains AI ordering, narrative/musical rationale, proposed transitions, timing, and regenerations. After approval, the editor uses tracks/time, clips, boundaries, transition regions, and automation appropriate to a DAW-inspired arrangement—not ComfyUI nodes.

## Core workflow simplification

### Attention

- Group by production and human decision, not by raw job.
- Separate `Action required`, `Ready to review`, and `System blocked`; successful routine work stays out.
- Every item exposes consequence, recommended next action, and age. Technical evidence is one level deeper.
- Bulk actions exist only where the same decision is safe; paid authorization and destructive actions remain explicit.

### Scene-plan approval

- Present storyboard intent, pose/location, reference image, and motion preview together per scene.
- Support batch approval with clear exceptions; a scene can be held without losing approved peers.
- Show lip-sync classification before expensive rendering and make the WAN hop explainable.
- Treat duration as invariant across LTX/WAN; surface any duration mismatch as a hard blocker.

### Progressive generation

- Each scene advances independently and paints new still/clip evidence in place.
- Cancellation targets the smallest safe unit.
- QC auto-advances passes and locally retries hard failures within configured limits.
- Attempt four escalates with history rather than looping invisibly.

### Video review

- Media and timeline are primary. Findings are timestamped and severity-coded without obscuring playback.
- The primary decision layer shows the failed moment, diagnosis, and proposed action.
- Supporting evidence includes confidence, model/stage, attempt history, time estimate, prompt/settings, and audit history.
- Approve, override, repair, revise storyboard, and compare attempts remain within the review context.

### Set and release

- AI proposes order and reasons; operator edits and approves the whole plan before GPU work.
- Set edits are non-destructive derivatives of standalone videos.
- Release tracks `Approved`, `Exported`, and destination-specific `Released/Failed` separately.

## Async interaction contract

Every mutation has local pending, success, validation error, authorization error, timeout/network error, server error, cancellation, and partial-success behavior as applicable. Disable unsafe duplicate submission, preserve recoverable input, reconcile authoritative server state, and never require a document reload. Long jobs return immediate acknowledgement and stream/poll progress. Stale/out-of-order scene results must not overwrite newer attempts.

## Visual-system strategy

- Keep the restrained dark foundation; use neutral charcoal surfaces and one cool primary action accent.
- Reserve semantic colors for attention severity, success, warning, destructive action, and selection. Never rely on color alone.
- Use a compact 4/8-based spacing scale, modest 4–8px radii, thin borders, and elevation only for overlays.
- Establish typography roles for page title, section title, body, metadata, label, and timecode/technical values. Use tabular numerals for time and progress.
- Standardize buttons, fields, notices, tabs/stage paths, status indicators, progress, evidence rows, media frames, timeline markers, dialogs, drawers/inspectors, and empty/loading/error states.
- Keep the shared ghost-X `modal_close()` contract for dismissals; destructive confirmation actions remain labeled.

## Accessibility and responsive strategy

- Desktop 1440 and laptop 1280 are primary; tablet must retain review/action access. Phone may offer monitoring/approval but is not a production-layout target.
- Tables re-prioritize or transform; they do not simply clip. The set timeline may intentionally pan horizontally with persistent controls.
- Native semantics first; stage/tab controls expose selection; disclosure summaries receive focus styles.
- Dynamic job/QC changes use scoped live announcements. Dialogs restore focus. Findings include text/icon labels beyond color.
- Keyboard flow covers attention triage, playback, findings, approval, scene navigation, and dialogs. Reduced motion disables shimmer/spinners where practical.

## Security and trust strategy

- The prototype must not imply that hidden controls are authorization.
- Paid/cloud approvals show provider, data leaving the host, scope, estimated/max cost, and authorization duration.
- Automation configuration and operator overrides are server-authoritative and audited.
- Release actions show destination, account identity, scope, progress, and partial failure.
- Before multi-operator/cloud exposure, production must add real authentication/authorization and resolve database exposure, stored XSS, CSRF/origin, replay/idempotency, and rate/abuse controls.

## Priorities

| Priority | Problem | Impact | Recommendation |
| --- | --- | --- | --- |
| P0 | Decisions and failures are distributed across songs, QC, jobs, and fleet | Lost attention and unsafe resumption | Attention-first global entry with contextual deep links |
| P0 | Media/QC evidence is fragmented or broken | Bad approvals and wasted renders | Media-led review with timestamped findings and reliable artifact access |
| P0 | Reload/bespoke async behavior breaks state trust | Duplicate work and lost context | One async interaction/error contract with localized reconciliation |
| P0 | Current security defects undermine future automation/release | Data exposure and hostile costly work | Treat SEC-01–05 as production prerequisites, not UI polish |
| P1 | Song page mixes stages into a long disclosure stack | Weak progress model and high cognitive load | Persistent five-stage production workspace |
| P1 | Scene approval evidence lives in separate concepts | Expensive bad renders | One batch scene-plan approval package |
| P1 | Technical controls dominate learning and production alike | ComfyUI complexity leaks into product | Decision-first presentation with evidence disclosure |
| P1 | Set editing lacks a clear editorial mental model | Weak final-release composition | DAW-inspired, non-destructive set arrangement |
| P2 | Tokens/components/states are only partially formalized | Drift and maintenance cost | Extend the existing semantic layer; do not create a parallel system |
| P2 | Accessibility gaps affect frequent controls and dynamic state | Keyboard/screen-reader friction | Fix focus, tab semantics, announcements, reduced motion |
| P3 | Narrow-screen Library/Anchors clipping | Monitoring friction | Intentional reprioritization; no phone-first rewrite |

## Roadmap before production planning

1. Compare three design directions on the same attention/review problem.
2. Prototype the recommended shell, attention queue, scene-plan approval, video review, and set plan/editor with mock data.
3. Render desktop/laptop/tablet/mobile monitoring states plus dense/empty/error/partial states.
4. Run independent adversarial UX, accessibility, security, and async review.
5. Mitigate blocking prototype findings and present the decision package for explicit design approval.
