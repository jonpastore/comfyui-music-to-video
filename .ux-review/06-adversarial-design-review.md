Status: COMPLETE
Phase: 5 — Mandatory adversarial design review
Last Updated: 2026-08-19
Inputs Used: `.ux-review/03-ux-strategy.md`; `.ux-review/04-design-directions.md`; `.ux-review/05-prototype-review.md`; independent adversarial, security, and rendered-browser reviews
Open Questions: None blocking design approval
Blocking Findings: None for design approval; production security blockers remain carried forward
Next Recommended Phase: Decision package and explicit user design approval

# Mandatory adversarial design review

## Category status before mitigation

| Category | Result | Summary |
| --- | --- | --- |
| Security/trust UX | ISSUES | Cloud consent is strong; version, replay, policy scope, and release target contracts are incomplete. |
| UX | ISSUES | Hard blockers do not block approval; exhausted repair and set approval are ambiguous. |
| Accessibility | ISSUES | Timeline buttons and attention tabs are incomplete; dialog name and media semantics need correction. |
| Consistency | ISSUES | Four-attempt escalation conflicts with ordinary fifth-repair wording. |
| Simplicity | PASS | DAW semantics remain limited to Sets; technical detail is progressively disclosed. |
| Responsive/adaptive | PASS WITH CAVEAT | No root overflow at 1440/1280/768/390 after first iteration; mobile is monitoring/approval only. |
| Async/data integrity | ISSUES | Toast-only costly actions and incomplete version binding do not demonstrate safe mutation state. |
| Architecture/API | UNTESTED | Mock-only prototype; server contracts remain later implementation requirements. |

## Consolidated blocking findings

### AD-01

ID: AD-01
Category: Approval integrity / UX
Severity: High
Confidence: High
Observation: An enabled `Approve video` action succeeds while a hard identity blocker remains visible.
Evidence: Independent reviewer reproduced approval on `#review`; the timeline and finding pane simultaneously show the blocker.
Failure scenario: Operator approves a master that the declared QC contract says cannot advance.
Why it matters: Makes hard blockers decorative and breaks the primary human gate.
Recommended mitigation: Replace approval with blocker resolution until repair or explicit audited override; bind later approval to the reviewed master version.
Implementation impact: Review action state, finding disposition, version-bound server enforcement, audit.
Must fix before implementation? Yes
Disposition: MITIGATE — prototype change required before decision package.

### AD-02

ID: AD-02
Category: Stale approval / data integrity
Severity: High
Confidence: High
Observation: Only the scene-plan fixture visibly handles staleness, and its click handler could still approve; other consequential decisions lack artifact versions.
Evidence: Reviewers inspected plan/video/set/cloud/release actions and reproduced the stale label without a safe mutation contract.
Failure scenario: A decision authorizes a superseded plan, repair, master, set, or destination configuration.
Why it matters: Unattended progression makes stale approval an integrity failure.
Recommended mitigation: Show immutable version/current-as-of on all consequential decisions; stale state offers only compare/reload. Production later enforces compare-and-swap/409.
Implementation impact: Versioned mutation contracts and reconciliation.
Must fix before implementation? Yes
Disposition: MITIGATE — demonstrate consistently in prototype.

### AD-03

ID: AD-03
Category: Core interaction / accessibility
Severity: Medium
Confidence: High
Observation: Timeline markers and attention tabs look interactive but do not change finding/filter state; tabs lack expected keyboard behavior; media control is nested in `role=img`; dialogs lack a stable accessible name.
Evidence: Browser reviewer clicked the 02:22 marker and Ready tab, used Arrow keys, and inspected dialog semantics.
Failure scenario: Mouse/keyboard users cannot navigate the two primary decision maps and encounter false controls.
Why it matters: These interactions define the recommended direction.
Recommended mitigation: Implement finding selection/seek, functional labelled panels and roving tabs, correct media grouping, and `aria-labelledby` dialogs.
Implementation impact: Shared selection/tab/player/dialog primitives.
Must fix before implementation? Yes
Disposition: MITIGATE — prototype behavior required.

### AD-04

ID: AD-04
Category: Automation scope / costly mutation
Severity: High
Confidence: High
Observation: Four attempts are exhausted, yet the primary action is an ordinary repair and costly actions use transient toast success without durable pending/accepted state.
Evidence: Reviewer reproduced a fifth `Repair scene`; only scene-plan approval disabled itself.
Failure scenario: Retry limits silently extend or duplicate GPU/cloud work.
Why it matters: The attention model exists to stop invisible retry loops and make authority explicit.
Recommended mitigation: Use `Authorize exception repair` with attempt 5, changed scope, version, time/cost and effective policy; demonstrate pending/accepted request identity and duplicate prevention.
Implementation impact: Policy resolution, attempt ledger, idempotent async state.
Must fix before implementation? Yes
Disposition: MITIGATE — prototype one shared costly-mutation contract.

### AD-05

ID: AD-05
Category: Set approval / non-destructive editorial integrity
Severity: High
Confidence: High
Observation: The set claims five videos/four derivatives but shows three/two and lacks source versions, changed ranges, estimate, plan version, and stale branch.
Evidence: Browser reviewer compared visible arrangement DOM with summary and rationale.
Failure scenario: Operator approves broader regeneration or different masters than the plan they believe they reviewed.
Why it matters: Set approval gates hours of GPU work and must preserve standalone masters.
Recommended mitigation: Enumerate complete ordered sources/versions, every trim/overlap/replacement/regeneration range, derivatives, duration, estimate, plan version, and stale/replan behavior.
Implementation impact: Versioned set-plan/derivative graph and approval contract.
Must fix before implementation? Yes
Disposition: MITIGATE — prototype full plan evidence.

### ADSEC-01

ID: ADSEC-01
Category: Automation policy scope
Severity: Medium
Confidence: High
Observation: Precedence is named but effective values, inherited/overridden source, blast radius, and escalation are not legible.
Evidence: Prototype shows only `Global → production → scene` and retry count.
Failure scenario: A local-looking override widens unattended work across a production or Library.
Why it matters: Automation configuration grants operational authority.
Recommended mitigation: Effective-policy evidence names each active value/source, affected units, attempt/time/cost bounds, and escalation.
Implementation impact: Policy resolution API/audit later; interaction contract now.
Must fix before implementation? Yes
Disposition: MITIGATE.

### ADSEC-02

ID: ADSEC-02
Category: Release integrity
Severity: Medium
Confidence: High
Observation: Destination states exist, but Vimeo/archive omit target account/scope; release count says `3 Released` despite only one success.
Evidence: Rendered Release section and reauthorization dialog.
Failure scenario: Retry publishes the wrong artifact to the wrong account or visibility.
Why it matters: External publication is difficult to unwind and destinations fail independently.
Recommended mitigation: Show account/target, artifact version, visibility/schedule or delivery scope, external ID, and retry safety per destination; count `1 of 3 released`.
Implementation impact: Destination schema, credential binding, idempotent publish/callback validation later.
Must fix before implementation? Yes
Disposition: MITIGATE.

## Nonblocking findings carried into later planning

### AD-06

ID: AD-06
Category: Production security
Severity: Critical
Confidence: High
Observation: Current app has no identity/authorization, exposes the database through media, has stored XSS, lacks CSRF/origin defense, and lacks replay/rate controls.
Evidence: `.ux-review/01-discovery.md`, SEC-01–05.
Failure scenario: Tailnet-reachable hostile client reads data or triggers/duplicates costly and release actions.
Why it matters: UI confirmation cannot secure automation or publication.
Recommended mitigation: Resolve server P0s before affected production rollout; reconcile UI only from authoritative responses.
Implementation impact: Backend identity/session, authorization, media isolation, safe rendering, mutation protocol, deployment.
Must fix before implementation? Yes for affected production work; no for isolated design approval.
Disposition: MITIGATE in later production plan; never infer approval from this decision package.

### AD-07

ID: AD-07
Category: Auditability and local learning
Severity: Medium
Confidence: High
Observation: Override copy claims auditable local evidence without showing actor class, time, version/attempt, policy, rationale, supersession, or learning status.
Evidence: Override dialog and evidence panel.
Failure scenario: Future recommendations learn from ambiguous or superseded exceptions.
Why it matters: Owner approved local QC learning, which needs provenance.
Recommended mitigation: Demonstrate a concise System/Operator event and require protected append-oriented audit semantics later.
Implementation impact: Event history and controlled learning-signal pipeline.
Must fix before implementation? No
Disposition: MITIGATE in prototype if inexpensive; require in planning.

### AD-08

ID: AD-08
Category: Untrusted text / XSS
Severity: Medium
Confidence: High
Observation: Mock static strings use `innerHTML`; production contains a confirmed stored-XSS pattern.
Evidence: `prototype.js` static fixture rendering and discovery SEC-03.
Failure scenario: Dynamic AI/operator/provider text becomes executable markup.
Why it matters: New evidence/release surfaces multiply untrusted strings.
Recommended mitigation: Prototype remains mock-only; production renders strings as escaped text or through a constrained sanitization schema.
Implementation impact: Safe shared rendering patterns and SEC-03 remediation.
Must fix before implementation? No for mock; yes before production integration.
Disposition: MITIGATE in later plan.

### AD-09

ID: AD-09
Category: Notification privacy
Severity: Low
Confidence: Medium
Observation: Email is promised without a minimal-content contract.
Evidence: Empty Attention copy and owner notification requirements.
Failure scenario: Mature thumbnails, prompts, raw errors, costs, or approval tokens leak through email.
Why it matters: Email is outside the controlled Tailnet UI.
Recommended mitigation: Email only production identifier/status and an authenticated in-app link; no media, prompts, findings, raw errors, cost, or one-click approval.
Implementation impact: Authenticated deep links, recipient controls, delivery security.
Must fix before implementation? No
Disposition: MITIGATE in decision package and later plan.

## Initial challenge table

| Assumption | Challenge | Result before mitigation |
| --- | --- | --- |
| Hard blockers prevent approval | Approve while identity blocker visible | FAIL |
| Approval binds to current evidence | Switch to stale plan; inspect other approvals | FAIL |
| Four retries escalate | Trigger repair after limit | FAIL |
| Timeline is actionable | Click 02:22 warning | FAIL |
| Attention tabs are accessible | Click/Arrow across tabs | FAIL |
| Set approval covers full plan | Compare summary to rendered sources/derivatives | FAIL |
| Paid consent is informed | Inspect provider/egress/scope/cap/expiry/retries | PASS; version missing |
| Missing media blocks judgment | Select degraded fixture | PASS |
| Narrow monitoring preserves access | Render 390px and measure root overflow | PASS |
| Server authorization/replay resistance | Direct API challenge | UNTESTED; discovery reports ISSUES |

## Post-mitigation verification

| Finding | Disposition | Verification result |
| --- | --- | --- |
| AD-01 hard-blocker approval | MITIGATE | PASS — approval is disabled and visibly muted; queued repair remains blocked; only audited override unlocks master v18. |
| AD-02 stale/version binding | MITIGATE | PASS — plan stale state only compares/reloads v13; video, set, cloud, and release actions show immutable versions/currentness. |
| AD-03 tabs/timeline/dialog/media semantics | MITIGATE | PASS — finding selection, playhead label, roving keyboard tabs, labelled panels, accessible dialog title, Escape/focus restore, and media grouping verified. |
| AD-04 retry boundary / duplicate action | MITIGATE | PASS — bounded attempt 5 shows scope/time/cost/version; `UX-204` durable queued state disables duplicates and keeps approval blocked. |
| AD-05 / AD-05R set-plan integrity | MITIGATE | PASS — `Approve set plan v6` presents the complete five-master change manifest, ranges/actions/derivatives, 41m/$0 estimate, immutable standalone guarantee, stale branch, and durable duplicate-safe `SET-006` state. |
| ADSEC-01 / ADSEC-01R cloud binding | MITIGATE | PASS — Scene 07, plan v12, source attempt 3, current time, and target output bind the egress/cost consent. |
| ADSEC-02 / ADSEC-02R costly-action replay | MITIGATE | PASS — cloud confirmation becomes durable `CLD-071 · provider pending`, disables duplicates, and persists after close. |
| ADSEC-03 automation scope | MITIGATE | PASS — effective source scope, Scene 04 blast radius, attempt/time/cost bounds, and escalation are visible. |
| ADSEC-04 release integrity | MITIGATE | PASS — `1 of 3 released`; every destination names target/account, master version, visibility/delivery scope, and recovery context. |
| AD-07 audit/local learning | MITIGATE | PASS for representative override/exception events; protected append-oriented server history remains a production requirement. |
| AD-08 untrusted text | MITIGATE LATER | Mock remains static/isolated. Safe escaped production rendering and SEC-03 remediation are mandatory before integration. |
| AD-09 notification privacy | MITIGATE LATER | Decision package requires minimal email content and authenticated in-app review links. |

Independent deterministic recheck passed JavaScript syntax, no external/API calls, blocker/override/repair state, marker/tab keyboard behavior, dialog naming/focus, stale/reset behavior, full set manifest, cloud binding/state, release evidence, and 390px no-root-overflow. Browser console/network showed no errors or external requests.

## Final category status

| Category | Result after mitigation |
| --- | --- |
| Security/trust UX | PASS for design contract; current production SEC-01–05 remain rollout blockers |
| UX | PASS |
| Accessibility | PASS for prototype semantics/interactions tested; real screen reader/media remain untested |
| Consistency | PASS |
| Simplicity | PASS |
| Responsive/adaptive | PASS within desktop/laptop primary and phone-monitoring scope |
| Async/data integrity | PASS for representative versioned, duplicate-safe mock contracts; backend enforcement untested |
| Architecture/API | UNTESTED by design; requirements carried to post-approval planning |

## Final challenge table

| Assumption | Result after mitigation |
| --- | --- |
| Hard blockers prevent approval | PASS |
| Approval binds to current evidence | PASS in prototype; server enforcement later |
| Four retries escalate | PASS |
| Timeline is actionable | PASS |
| Attention tabs are accessible state controls | PASS |
| Set approval covers the full versioned change manifest | PASS |
| Paid consent is informed and duplicate-safe | PASS |
| Missing media blocks judgment | PASS |
| Narrow monitoring preserves access | PASS |
| Server authorization/replay resistance exists today | FAIL in current production; blocks affected rollout, not design approval |
