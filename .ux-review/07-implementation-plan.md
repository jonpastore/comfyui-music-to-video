Status: AWAITING IMPLEMENTATION AUTHORIZATION
Phase: 6 — Approved implementation planning
Last Updated: 2026-08-20
Inputs Used: `.ux-review/01-discovery.md` through `.ux-review/06-adversarial-design-review.md`; `.ux-review/decision-package.md`; approved direction recorded in the active Codex session (2026-08-20)
Open Questions: Select the concrete single-operator identity/session mechanism before Work Package 1a; decide the initial notification delivery provider before Work Package 8. Neither changes the approved UX direction.
Blocking Findings: SEC-01–05 are rollout blockers for autonomous, cloud, and release actions. Do not expose those actions until Work Packages 1a and 1b are complete.
Next Recommended Phase: Explicit implementation authorization, then bounded production work packages in order.

# Production Desk — implementation plan

## Approval and scope

The owner approved **Direction B — Production Desk** on 2026-08-20. This authorizes this plan only; it does **not** authorize production implementation.

The target is one neutral, professional FastAPI/Jinja/HTMX studio with:

1. Attention as the default human-decision surface.
2. A persistent video workspace: `Prepare → Plan scenes → Generate → Review → Release`.
3. Timeline-led video review with version-bound approval, repair, override, and evidence.
4. A separate DAW-inspired, non-destructive Set plan and editor.

Preserve server-rendered pages, HTMX/fetch partial updates, SQLite, SSE/polling, the existing dark visual foundation, the shared `.modal-close` ghost-X, and progressive enhancement. Do not create an SPA, phone-first editor, generic design-system rewrite, or general `studio/app.py` refactor. New behavior belongs in focused routers/services/templates rather than enlarging existing slabs.

Every landed package updates the affected TRD, PRD, DDD, and UI/UX documents and its TRD *Status against the tree* row with a test that can go red, as required by `AGENTS.md`.

## Delivery sequence

```text
Security/authority baseline
        ↓
Production + decision contracts
        ↓
Shared shell and async primitives
        ↓
Attention + Library
        ↓
Scene plan / progressive generation
        ↓
Video review / QC decisions
        ↓
Set plan/editor + release destinations
        ↓
Accessibility, responsive hardening, end-to-end review
```

Work Packages 2–6 may use mock or disabled cloud/release controls while their server contracts are built. Work Packages 6–7 must not activate costly/external behavior until Work Packages 1a–1b and Work Package 2's version/idempotency contracts are live.

## Work packages

| Work package | Repository | Affected areas | Dependencies | Recommended executor | Acceptance criteria | Validation |
| --- | --- | --- | --- | --- | --- | --- |
| 1a. Operator access, media isolation, and safe text | `comfyui-music-to-video` | New focused auth/security module and tests; `studio/app.py` registration only; `studio/db.py`; `studio/static/app.js`; media route | None | Backend-focused worker plus security review | Operator identity and server authorization gate protected access; media serves only allowlisted artifacts, never SQLite/data roots; Library grouping text is inert | Focused pytest security suite; route tests for unauthenticated/unauthorized, media DB request, and XSS payload; independent security recheck |
| 1b. Mutation integrity and costly-work controls | `comfyui-music-to-video` | Focused request-protection/idempotency module; mutation-route registration; `studio/jobs.py`; `studio/db.py`; client transport helper; tests | 1a | Backend-focused worker plus security review | Browser mutations have origin/CSRF defense; costly mutation endpoints require idempotency and enforce a bounded replay/rate/size policy; model acquisition validates allowed source, size, and hash | Route tests for forged origin, duplicate/cross-tab mutation, rate/size rejection, and disallowed model acquisition; independent security recheck |
| 2. Production, decision, and audit contracts | `comfyui-music-to-video` | Add focused `production_service`, `decision_service`, and route modules; `studio/db.py`; migration/backfill path; `studio/jobs.py`; `studio/qc_service.py`; tests | 1b | Backend-focused worker | Immutable versions identify scene plans, attempts, masters, set plans, and release requests; decisions bind version/currentness, actor, policy source, scope, estimate, expiry, rationale, and outcome; stale mutations return conflict data rather than applying; four automatic attempts escalate | Unit/integration tests for version conflict, idempotency, four-attempt boundary, audited override, cancellation/smallest safe unit, migration/backfill; database backup and rollback rehearsal |
| 3. Shared Production Desk shell and async primitives | `comfyui-music-to-video` | `studio/nav_service.py`; `studio/templates/base.html`, `_macros.html`; new shared partials; `studio/static/style.css`, `app.js`; focused UI tests | 2 | Frontend worker | Navigation is Attention, Library, Characters & Poses, Sets, Operations; status language is consistent; stage paths/tabs, notices, buttons, evidence rows, dialogs, skeleton/progress/error states use shared primitives; normal mutations prevent native navigation/reload and reconcile authoritative partial/JSON state in place | Existing UI tests adapted; new browser smoke for keyboard tabs/dialog focus/Escape, reduced motion, pending/error/success states; visual checks at 1440, 1280, 768, 390 |
| 4. Attention and Library throughput | `comfyui-music-to-video` | New attention router/service/templates; `studio/templates/_song_row.html`, `_jobs_panel.html`; Library routes/fragments; `studio/jobs.py`; `app.js`, `style.css`; tests | 2–3 | Frontend worker with backend support | Attention is the default route and separates Action required, Ready to review, and System blocked; each item has consequence, age, recommended action, and contextual deep link; successful routine work stays out; Library remains dense and supports safe batch actions only for equivalent decisions | Route/fragment tests for empty, long, partial, failed, paid, missing-media, and stale items; browser tests for keyboard triage and in-place updates; desktop/laptop/tablet rendering evidence |
| 5. Scene-plan approval and progressive generation | `comfyui-music-to-video` | Focused production/scene routes; `studio/storyboard_service.py`, `studio/pose_plan.py`, `studio/pipeline.py`, `studio/jobs.py`; `studio/templates/_storyboard_panel.html`, `_scene_row.html`, `_clip_tile.html`; `app.js`, `style.css`; tests | 2–4 | Backend and frontend workers in separate, non-overlapping file scopes | A scene-plan bundle presents storyboard, pose/location, reference, preview, duration, lip-sync route, and held exceptions; batch approval preserves held scenes; LTX is first, WAN is preclassified only for lip-sync scenes; timestamp sampling preserves duration between LTX 25fps and WAN 16fps; results stream/paint incrementally and permit smallest-safe cancellation | Existing pipeline/QC tests plus new plan-approval, frame-timestamp, partial-result, cancellation, and stale-SSE reconciliation tests; browser review for dense, error, and missing-evidence states |
| 6. Video review, QC, repair, and approval | `comfyui-music-to-video` | Focused review/QC routes/service; `studio/qc_service.py`, `studio/jobs.py`; review/video templates and fragments; `app.js`, `style.css`; tests | 2–5 | Frontend worker with QC/backend support | Review is media/timeline first; selecting a finding seeks the correct timestamp and evidence; hard blockers disable approval; operator can repair, revise storyboard, compare attempts, or record a reasoned audited override; local QC passes auto-advance under configured policy; costly/cloud consent discloses provider, exact egress, purpose, version, scope, cap, expiry, and no-retry rule | Route tests for hard blocker, missing media, stale master, exhausted repair, approved override, cloud consent, duplicate/replay, and rejected authorization; keyboard/player/dialog browser test and screen-reader spot check |
| 7. Set plan/editor and release destinations | `comfyui-music-to-video` | `studio/sets_service.py`, `studio/playlist_service.py`, focused set/release routes; `studio/templates/_set_editor.html`, `_playlist_card.html`; `studio/static/app.js`, `style.css`; destination/adaptor modules and tests | 1b–3, 6 | Backend and frontend workers in separate file scopes | AI can propose order with reasons; approval shows a complete immutable set manifest covering every source master, range, transition, derivative, estimate, and stale/replan rule; set edits create derivatives only, never mutate standalone masters; release distinguishes Approved, Exported, and each destination's result/account/scope/recovery; external provider actions are idempotent and opt-in | Unit tests for plan manifest, immutable source master, stale set, transition derivative, partial destination release and retry; browser tests for horizontal arrangement controls at tablet/phone monitoring sizes; provider sandbox/contract tests before activation |
| 8. Notifications, accessibility, responsive hardening, and release readiness | `comfyui-music-to-video` | Notification adapter/config; shared templates/styles/scripts; browser tests; docs/ledgers | 3–7 | Frontend worker, test runner, security/adversarial reviewers | Email contains only production identifier/status plus authenticated in-app link—never media, prompts, findings, raw errors, cost, or approval controls; live updates announce meaningful scoped changes; all dialogs use `.modal-close`, restore focus, and have accessible names; phone remains monitoring/approval, not a timeline editor; visual/interaction semantics are consistent across routes | Full `studio` pytest suite; browser regression suite at 1440×900, 1280×800, 768×1024, 390×844; keyboard/reduced-motion/zoom checks; final adversarial, security, and rendered review |

## API, async, and data-integrity decisions

- Keep the existing dual-mode progressive-enhancement convention only for genuine document navigation. New and converted mutations return authoritative JSON or an HTML fragment and update the current page; they do not return a `303` merely to refresh state.
- Long jobs acknowledge immediately with an immutable job/decision/attempt version, then stream or poll server-authoritative progress. A late event cannot overwrite a newer attempt/version.
- Consequential mutations carry an idempotency key and expected version. The server returns either accepted state, the prior accepted result, or a structured stale/conflict response suitable for compare/reload.
- The server alone evaluates policy, operator authority, paid/cloud allowance, retry count, cost cap, and release eligibility. Client controls present those results; they do not enforce them.
- Continue SQLite with additive schema/backfill migrations and explicit rollback/backup steps. Do not delete or reinterpret historical attempts or approved masters during the redesign.
- Retain the serialized worker model. UI progress is per production/scene/decision; it must not imply concurrent renderer capacity that the fleet cannot supply.

## Security prerequisites and rollout boundaries

Work Packages 1a–1b must resolve the discovery findings before any production cloud, release, or autonomous repair capability is enabled:

| Finding | Required implementation boundary |
| --- | --- |
| SEC-01 | Real authenticated operator identity and server-side authorization for every read/write privilege that needs protection. The exact identity/session mechanism is an implementation decision to settle before coding. |
| SEC-02 | Replace broad media-root traversal with an artifact allowlist/lookup. Database, logs, secrets, and arbitrary filesystem paths can never be media. |
| SEC-03 | Render operator/AI/provider text using text nodes or an explicitly constrained sanitizer—never `innerHTML` interpolation. |
| SEC-04 | Enforce origin/CSRF protection for browser mutations and validate request content server-side. |
| SEC-05 | Apply idempotency, authorization, rate/size controls, model source/hash/allowlist rules, and auditable accepted/pending/failed states to costly work. |

Do not turn these into superficial UI prompts. Failure states must remain recoverable and comprehensible, but security is enforced by the server.

## Documentation, release, and rollback

- This is one repository; there is no cross-repository version skew. Within the studio, schema/API additions are additive and old templates/routes remain supported until their replacements pass browser and route tests.
- Land one work package per clean worktree. Do not overlap writers in `studio/app.py`, `studio/static/app.js`, `studio/static/style.css`, or a template without an explicit file claim.
- For each landed package, update the relevant TRD/PRD/DDD/UIUX documents and ledger status in the same commit. Do not mark a requirement built without the corresponding red-capable test.
- Deploy only from a clean detached worktree when the render queue is idle. A deploy/restart is independent of in-flight fleet jobs; never restart the studio mid-render.
- Feature-gate unfinished Attention, cloud, release, and set capabilities. Roll back UI exposure/configuration first; preserve immutable attempts, decisions, masters, and audit events for diagnosis. Never “undo” an external release by silently rewriting local status.
- Observe action latency, accepted/duplicate/stale decisions, retry escalation, queue/fleet failure, artifact recovery, per-destination release outcome, and notification delivery with non-sensitive telemetry/logs.

## Final validation plan

1. Run the full `cd studio && python3 -m pytest -q .` suite after each package and targeted tests before it.
2. Add deterministic tests for every version-bound decision, retry/cost boundary, partial result, duplicate, stale response, and server authorization branch.
3. Exercise real rendered routes—not only source—at desktop, laptop, tablet, and 390px monitoring sizes with empty, dense, long, missing-media, malformed, slow, offline, authorization, concurrent, and partial-release states.
4. Verify keyboard stage/tabs/timeline/dialog flow, focus restoration, accessible names/live announcements, contrast, 200% zoom, and reduced motion.
5. Before declaring the implementation ready, perform a fresh independent adversarial design, security, rendered-browser, and deterministic-test review against the live implemented studio; `READY` is prohibited while a critical security, data-integrity, core-workflow, or accessibility finding remains.
