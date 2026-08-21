Status: COMPLETE
Phase: 4 — Isolated prototype construction and rendered review
Last Updated: 2026-08-20
Inputs Used: `.ux-review/03-ux-strategy.md`; `.ux-review/04-design-directions.md`
Open Questions: Capability/data preservation mapping is incomplete; real media/playback and server behavior remain implementation-time validation
Blocking Findings: No prototype interaction blocker; incomplete feature-capability parity blocks returning to the design-approval gate
Next Recommended Phase: Complete feature/capability preservation review and feature/data parity validation

# Prototype review — Meow P Studio directions

## Goal and scope

Compare three materially different compositions using the same production data, then deeply exercise the recommended Production Desk across Attention, Scene Plan, Video Review, Set composition, and Release. Prototype files are isolated under `.ux-review/prototype/`, use mock data only, and do not connect to production APIs.

## Screenshot evidence

| Viewport / state | Screenshot | Notes |
| --- | --- | --- |
| 1440×900 · three directions | `output/playwright/ux-review/.playwright-cli/page-2026-08-20T02-32-09-310Z.png` | Production Desk visibly balances the Control Room’s density and Review Theatre’s media emphasis. |
| 1440×900 · attention | `output/playwright/ux-review/.playwright-cli/page-2026-08-20T02-32-31-614Z.png` | Decision list and evidence/action inspector scan as one task. |
| 1280×800 · video review | `output/playwright/ux-review/.playwright-cli/page-2026-08-20T02-33-00-987Z.png` | Media/timeline remain primary; repair evidence fits without crowding playback. |
| 1280×800 · compare dialog | `output/playwright/ux-review/.playwright-cli/page-2026-08-20T02-33-30-478Z.png` | Shared ghost-X, labeled Cancel/selection action, and background focus. |
| 1280×800 · set timeline | `output/playwright/ux-review/.playwright-cli/page-2026-08-20T02-33-58-953Z.png` | DAW influence is constrained to arrangement, connective material, and automation. |
| 390×844 · video review | `output/playwright/ux-review/.playwright-cli/page-2026-08-20T02-44-10-162Z.png` | Monitoring/approval remains usable; media and finding stack vertically. |
| 768×1024 · video review | `output/playwright/ux-review/.playwright-cli/page-2026-08-20T02-44-52-827Z.png` | Full review action set and timeline remain visible. |
| 1280×800 · missing media | `output/playwright/ux-review/.playwright-cli/page-2026-08-20T02-45-33-812Z.png` | Missing evidence is an explicit hard blocker with recovery/escalation. |
| 1280×800 · stale plan | `output/playwright/ux-review/.playwright-cli/page-2026-08-20T02-46-00-152Z.png` | Approval binds to version; stale plan requires reload to version 13. |
| 1280×800 · cloud authorization | `output/playwright/ux-review/.playwright-cli/page-2026-08-20T02-49-32-230Z.png` | Provider, purpose, egress, scope, maximum cost, expiry, and retry limit are explicit. |
| 1280×800 · mitigated review | `output/playwright/ux-review/.playwright-cli/page-2026-08-20T03-16-41-363Z.png` | Hard blocker visibly disables approval; bounded exception repair and audited override are the available decisions. |

## Headless validation refresh — 2026-08-20

The isolated prototype was served locally on `127.0.0.1:8013` and rendered with Playwright Chromium launched from `.ux-review/playwright-headless.json` (`headless: true`). No graphical desktop, X11, Wayland, headed browser, production API, or production dependency was used.

| Viewport / flow | Evidence | Result |
| --- | --- | --- |
| 1440×900 · directions | `.ux-review/.playwright-cli/page-2026-08-20T11-38-17-642Z.png` | Screenshot captured; no root horizontal overflow; dialog has stable label. |
| 1280×800 · Review timeline | `.ux-review/.playwright-cli/page-2026-08-20T11-38-42-850Z.png` | Screenshot captured; marker selection changes time, finding, and playhead; hard-blocker approval remains disabled. |
| 768×1024 · Attention keyboard tabs | `.ux-review/.playwright-cli/page-2026-08-20T11-39-31-205Z.png` | Screenshot captured; ArrowRight selects `Ready to review`, updates the linked tabpanel, and retains tab focus. |
| 390×844 · Set monitoring | `.ux-review/.playwright-cli/page-2026-08-20T11-39-51-459Z.png` | Screenshot captured; root has no horizontal overflow; navigation and arrangement intentionally pan internally. |

The paid-cloud fixture was also exercised: its dialog identifies immutable Scene 07 / plan v12 / source attempt 3 binding, egress, cost cap, scope, expiry, and no-retry policy; it has an accessible name, initially focuses its ghost-X close button, and Escape returns focus to `Review authorization`. Browser console reported zero warnings/errors and no non-static network requests.

## Strengths

- Direction B reads as a genuine hybrid rather than a softer version of the control room.
- The attention queue centers the production decision, not the raw render job.
- Review provides sufficient media scale at 1280/1440 while preserving exact timestamp, diagnosis, and repair evidence.
- Scene planning communicates batch readiness, per-scene hold, duration, and WAN routing without exposing a node graph.
- Set planning uses track/time semantics without infecting scene generation with DAW complexity.
- Semantic HTML snapshot includes landmarks, headings, native buttons/details/dialogs, labels, tab roles, and named timeline markers.

## Weaknesses and open questions

- Initial 390px render had sticky-header anchor occlusion and page-wide overflow from the attention queue. Prototype CSS was corrected; Playwright then measured viewport/document/body width all at `390px`, with the target section beginning below the `91px` header.
- Dynamically inserted inspector actions initially appeared interactive but did not open dialogs. Event binding was corrected and Playwright verified the cloud dialog `open=true` with the expected authorization content.
- The mock comparison dialog’s “Select attempt 1” language may imply promotion rather than comparison; adversarial review should test the label and consequence model.
- Prototype media is intentionally abstract, so it validates hierarchy and space—not real visual-QC acuity or video playback performance.

## Adversarial mitigation iteration

- Hard blockers now disable and visibly mute video approval. A queued fifth exception repair remains approval-blocked; only an explicit audited override unlocks the mock approval.
- Exhausted repair is a bounded `Authorize exception repair` decision showing attempt 5, changed stage/input, local execution, time/cost, blast radius, plan/master versions, and escalation. Acceptance becomes durable inline `request UX-204 · queued` state and prevents a duplicate intent.
- Scene-plan stale state binds to plan hash/version and offers only compare/reload; fixture changes reset to a clean base state.
- Timeline markers update the selected time, finding, evidence, playhead position, and accessible label.
- Attention tabs update the labelled panel and support click, ArrowLeft/Right, Home, and End with roving focus.
- Dialogs use stable `aria-labelledby`, Escape, shared ghost-X, and focus restoration.
- Set plan v6 now enumerates five source-master versions and four connective derivatives with trims/overlap/edge replacement/regeneration scope, duration, local 41-minute estimate, and $0 cost.
- Release reports `1 of 3 released`; each destination names target/account, master version, visibility/delivery scope, and recovery context.
- Effective automation evidence names source scope, affected scene, attempt bound, local cost/time, and escalation.

## Responsive, accessibility, and realistic-data checks

- Desktop: 1440×900 and laptop: 1280×800 visually inspected.
- Tablet: 768×1024 review and set/release compositions inspected.
- Phone monitoring: 390×844 inspected; global overflow eliminated, nav/tabs scroll internally, set timeline retains intentional internal pan.
- Normal, running/partial, missing-media, exhausted repair, stale plan, paid cloud, empty attention, and partial release fixtures are implemented. Normal, degraded, stale, cloud, and empty were exercised directly.
- Keyboard-visible focus styles, skip link, native dialog Escape behavior, and labeled timeline markers are present. Full screen-reader announcement behavior remains unverified because this is a static mock.
- `node --check .ux-review/prototype/prototype.js` passes. Browser console is clean after adding the local data favicon.
- Independent deterministic browser validation passed the blocker, exception/override, marker, tab keyboard, dialog, stale/reset, release/set evidence, and 390px overflow checks. No external network/API requests were present.

## Platform/runtime coverage and intentional differences

Web only. Desktop/laptop are primary; tablet and phone validate monitoring/approval continuity, not full editing parity.

## Adversarial review findings

See `.ux-review/06-adversarial-design-review.md`. Initial blockers were mitigated in the isolated prototype and independently rechecked.

## Owner feedback and next iteration

The representative prototype is a design-direction artifact, not evidence that unrepresented production capability may be removed. Complete `.ux-review/feature-capability-parity.md` and feature/data parity validation before returning to the design-approval gate.
