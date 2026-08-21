Status: ACTIVE
Phase: Rendered direction comparison and user design decision
Last Updated: 2026-08-21
Inputs Used: `.ux-review/01-discovery.md` through `.ux-review/06-adversarial-design-review.md`, `.ux-review/08-current-rendered-evidence.md`, and `.ux-review/09-adversarial-prototype-review.md`; current local rendered baseline; isolated prototype; `feature-capability-parity.md`
Open Questions: Which of the three directions the operator wants to carry into an approved implementation plan
Blocking Findings: None for UX design approval; production security and P0-1 migration reconciliation remain separate implementation workstreams
Next Recommended Phase: User selects or combines a direction after fresh rendered evidence

# Meow P Studio design decision package

## Current decision status

The prior exploration recommended **Direction B — Production Desk**. The current
user priority reopens the visual decision until the fresh three-direction package
is reviewed. It is a recommendation, **not an implementation authorization**.

## Recommendation

Use one neutral, professional studio organized around three task-appropriate compositions:

1. **Attention workbench:** default entry for human decisions, exhausted repair, missing evidence, system blockage, and paid authorization.
2. **Media-led production workspace:** `Prepare → Plan scenes → Generate → Review → Release`, with expert evidence progressively disclosed and no ComfyUI node-graph UX.
3. **DAW-inspired Set workspace:** AI-proposed order/rationale, complete versioned plan approval, then non-destructive tracks/time/transition/automation editing.

The Library remains a dense throughput surface; Characters & Poses remain reusable production assets; raw Jobs/Fleet/Models move under Operations while contextual failures deep-link there.

## Alternatives considered

### Operations Control Room

Best for current model commissioning and dense batch triage, but keeps media too secondary and encourages managing jobs instead of approving outcomes. Its lifecycle filters remain useful inside Library/Operations.

### Review Theatre

Best pure playback experience, but weak for current pipeline instability, cross-song attention, and diagnostic evidence. Its media emphasis is retained inside Video Review rather than becoming the entire product shell.

## Why Production Desk wins

- Matches the owner’s priority order: attention → ready review → recent work → Library.
- Supports autonomous QC progression while making exceptions safe and explainable.
- Gives images/video credible judgment space without hiding model/stage/attempt evidence.
- Avoids separate basic/expert modes; technical detail stays contextual.
- Applies the DAW metaphor only where time-based arrangement is genuinely useful.
- Preserves the FastAPI/Jinja/HTMX partial architecture rather than requiring an SPA rewrite.

## Approved-design contract if selected

- `Needs attention` is a cross-cutting decision flag, not a lifecycle stage.
- Hard blockers prevent approval unless explicitly overridden with an auditable reason.
- All consequential approvals bind to immutable plan/artifact versions and handle stale conflicts.
- Automatic retries stop at four; further work is a bounded, explicit exception with scope/time/cost evidence.
- Costly and external actions have durable pending/accepted/failed state and duplicate protection—not toast-only success.
- Paid/cloud consent identifies provider, exact egress, purpose, artifact version, scope, cap, expiry, and retry policy.
- Scene-plan approval combines storyboard, pose/location, reference, preview, duration, lip-sync routing, and held exceptions.
- Video review starts with findings on the timeline and supports repair, audited override, storyboard revision, and attempt comparison.
- Set plans preserve standalone masters and enumerate every source version and derived change before GPU work.
- Release tracks Approved, Exported, and each destination independently.
- Normal mutations are asynchronous and update in place; no reload as state management.
- Email notifications are minimal: production identifier/status plus an authenticated in-app link, with no media, prompt, finding, raw error, cost, or one-click approval.

## Prototype and evidence

- Prototype: `.ux-review/prototype/index.html`
- Run instructions: `.ux-review/prototype/README.md`
- Rendered evidence: `.ux-review/08-current-rendered-evidence.md`
- Adversarial dispositions: `.ux-review/09-adversarial-prototype-review.md`
- Direction comparison: `output/playwright/ux-review/directions-1440-final.png`
- Keeper/review state: `output/playwright/ux-review/keeper-review-1280-final.png`

The isolated prototype contains mock data only, calls no production API, and does not modify live state.

## Known boundaries carried forward

- Real media playback, SSE/poll reconciliation, persistent state, screen-reader announcements, and server conflict handling remain unimplemented.
- Current production security findings SEC-01–05 must be addressed before affected autonomous/cloud/release work ships: authentication/authorization, database media exposure, stored XSS, CSRF/origin protection, and idempotency/rate/abuse controls.
- Approval of this package does not approve a framework rewrite, phone-first editor, or generic design-system project.

## Approval choices

1. **Approve Production Desk** — next phase creates actionable implementation plans only; implementation still requires a separate authorization.
2. **Request prototype changes** — describe what should change; the isolated prototype will iterate and be re-reviewed as needed.
3. **Choose another direction** — select Operations Control Room or Review Theatre and identify the tradeoff you prefer.
