Status: COMPLETE
Phase: 3 — Design directions
Last Updated: 2026-08-19
Inputs Used: `.ux-review/03-ux-strategy.md`; completed discovery/interview; current design-method references
Open Questions: Direction selection remains pending rendered comparison and adversarial review
Blocking Findings: None
Next Recommended Phase: Isolated representative prototypes

# Design directions

These directions share the same product rules, lifecycle, security constraints, and server-rendered architecture. They differ materially in hierarchy, density, and the relationship between overview and media.

## Direction A — Operations Control Room

### Composition

- Dense attention table as the dominant home surface.
- Persistent filters, compact lifecycle columns, fleet/job status, and keyboard-oriented batch triage.
- Selecting a row opens a right-side evidence inspector without leaving the list.
- Video review and scene work retain dense metadata around smaller media.

### Strengths

- Best for the present commissioning phase and cross-song throughput.
- Makes failures, stages, models, attempts, and infrastructure highly visible.
- Lowest conceptual distance from the current Library and operational UI.

### Risks

- Preserves the engineering-console bias the product is trying to outgrow.
- Media may remain too small for credible identity, motion, and continuity judgment.
- Encourages the operator to manage jobs rather than approve outcomes.

### Implementation implications

Most compatible with current tables/fragments, but would require strong responsive reprioritization and a unified inspector contract.

## Direction B — Production Desk (recommended)

### Composition

- Attention-led home uses compact grouped queues with a contextual preview/evidence pane.
- Production workspace uses a stage path and media-first center, with a calm decision column and collapsible technical evidence.
- Library remains dense and operational rather than becoming a card gallery.
- Set composition adopts a dedicated time-based arrangement canvas after set-plan approval.

### Strengths

- Balances current diagnostic needs with the desired autonomous future.
- Keeps the decision and its visual evidence together.
- Supports one coherent experience without explicit expert/basic modes.
- Lets each task use the right density: dense overview, spacious judgment, DAW-like arrangement.

### Risks

- Requires clearer contextual navigation and state contracts than Direction A.
- Poorly implemented progressive disclosure could hide diagnostics.
- Multiple page compositions demand disciplined shared primitives to remain coherent.

### Implementation implications

Preserves Jinja/HTMX fragments but requires a reusable workspace shell, evidence inspector, lifecycle/stage primitives, and normalized async feedback.

## Direction C — Review Theatre

### Composition

- Large video/image canvas dominates most surfaces.
- Timeline findings and approval controls float close to media.
- Cross-production overview is a visually rich gallery of hero frames and simple status summaries.
- Technical operations are separated into secondary views.

### Strengths

- Best visual-judgment environment and strongest perceived creative quality.
- Makes completed videos feel like the primary product rather than pipeline artifacts.
- Simplest normal review path once automation is reliable.

### Risks

- Weak fit for current pipeline instability and batch diagnosis.
- Gallery overview scales poorly to many songs and nuanced blockers.
- Can conceal the evidence required to understand repeated model failures.
- Highest risk of decorative empty space and generic media-app styling.

### Implementation implications

Largest departure from current throughput surfaces; requires more client coordination and may duplicate operational context.

## Recommendation

Prototype **Direction B — Production Desk** deeply. Prototype A and C at the attention/video-review level only, using identical mock production data, to verify that the recommendation is based on observable hierarchy and density rather than prose.

Direction B best matches the owner’s stated priorities: attention first, findings on the timeline, all expert evidence available, neutral professional presentation, simpler-than-ComfyUI scene work, no explicit modes, and a DAW-inspired set editor. It also preserves the current server-owned partial architecture better than a theatre-style client rewrite.

## What the prototypes must prove

1. Attention items can be scanned and acted on without exposing raw jobs as the primary object.
2. Direction B gives media enough space without losing expert evidence.
3. Scene-plan batch approval communicates pose, location, reference, preview, lip-sync classification, duration, and exception state.
4. Video findings are understandable on a timeline and connect to repair/override/attempt actions.
5. Set planning explains AI order/rationale before the time-based editor spends GPU resources.
6. Dense, empty, slow, partial, failed, and paid-authorization states remain coherent.
7. Laptop and tablet layouts preserve decision context; phone retains monitoring/approval without pretending to be a full editor.

## Independent Phase 3 challenge incorporated

The design reviewer independently recommended the same composition under the name “attention-first production workbench”: stable shell, media-centered decisions, concise action pane, progressively disclosed diagnostics, and DAW behavior limited to Sets. It challenged these risks:

- `Needs attention` must remain an overlay/filter, not become a false lifecycle column.
- A universal DAW metaphor would contradict the requirement to make scene generation simpler than ComfyUI.
- Broken/missing decision media must render as a degraded-state blocker, never a silent blank tile.
- Findings must lead with the timestamp, human-readable explanation, and proposed action; technical evidence follows.
- Direction B must not become a three-pane control room with every setting permanently visible.

The security reviewer added three design-approval constraints:

1. Automation controls show effective scope and precedence (`Global → production → scene`), attempt/time/budget bounds, and escalation behavior.
2. Approval binds visibly to an artifact/plan version and handles “updated since opened” rather than approving stale evidence.
3. Paid/cloud authorization names provider, data leaving self-hosting, purpose, scope, cost ceiling/unknown estimate, retry limit, and authorization duration.

Further production constraints—authentication/authorization, media-root isolation, XSS, CSRF/origin, idempotency, rate controls, protected credentials, and per-destination publishing—remain explicit rollout blockers but do not block an isolated mock prototype.
