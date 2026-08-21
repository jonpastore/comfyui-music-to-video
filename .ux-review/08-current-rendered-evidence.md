# Current rendered prototype evidence — 2026-08-21

Status: COMPLETE for the disposable UX decision artifact
Prototype: `.ux-review/prototype/`
Runtime: Python `http.server` on `127.0.0.1:8011`; no FastAPI route, database,
production API, GPU, render-fleet, or external media was used.

## Current-product baseline

The current FastAPI studio was run locally with a new temporary `STUDIO_DATA`
directory. Fresh Playwright captures establish the actual baseline as a wide
top-nav operational product:

- `output/playwright/current-library-empty.png` — Library is upload-first and
  table-oriented.
- `output/playwright/current-anchors-empty.png` — Anchors combines coverage,
  keeper catalogue, missing-pose generation, and low-level render controls in
  one dense work surface.

The current local routes, templates, and the earlier rendered discovery form the
input to the capability parity matrix; the prototype is not inferred from source
alone.

## Fresh prototype render and interaction evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Three distinct directions at desktop density | PASS | `output/playwright/ux-review/directions-1440-final.png` |
| Media-led review at laptop size | PASS | `output/playwright/ux-review/review-1280-final.png` |
| Timeline warning selects its matching time and finding | PASS | Playwright snapshot changed to `02:22.0 · Lip-sync drift` after marker activation. |
| Attention tabs support click plus roving ArrowLeft/ArrowRight selection | PASS | The selected tab and labelled panel both changed. |
| Missing-media hard blocker | PASS | Fixture renders an explicit unavailable artifact and recovery/escalation actions, not a blank approvable frame. |
| Empty attention state | PASS | Fixture renders “No decisions waiting” while keeping the review deep link. |
| Stale plan | PASS | Fixture replaces approval with `Compare / reload plan v13`. |
| 390×844 monitoring/review | PASS | `output/playwright/ux-review/review-390-final.png`; root/document/body width all 390px. |
| 150% text zoom at 1280px | PASS | Root scroll width remained 1280px; `output/playwright/ux-review/zoom-150-1280.png`. |
| Console and network | PASS | No console warning/error on final fresh browser session; static localhost files only. |
| Shared-keeper context and safe review state | PASS | `output/playwright/ux-review/keeper-review-1280-final.png`; the synthetic `Keeper needs review` fixture holds new reference use while preserving scene evidence. |
| Direction-card actions | PASS | Each representative action is a real anchor to Attention, Scene plan, or Review; Production Desk’s “Review repair” navigated to `#review`. |

## Accessibility remediation and result

The initial fresh axe pass found invalid tab-to-panel ARIA linkage, list items
under a `tabpanel`, and insufficient metadata contrast. The disposable prototype
was changed to give the tabpanel a stable container, keep list semantics inside
it, and raise quiet metadata contrast. The independent UX review then caught
inert direction-card controls and non-rendered keeper states. Those controls are
now anchors, and the keeper cards use valid image semantics. A fresh `axe-core
4.13.0` WCAG 2 A/AA scan returned **zero violations** after those fixes.

The package lock and technology record are isolated under `.ux-review/tooling/`
and `.project/`; no production dependency was added.

## Known prototype boundary

This evidence proves visual hierarchy and mock interaction only. It does not
prove production authorization, storage, mutation idempotency, SSE/poll
reconciliation, screen-reader announcements, real media playback, or P0-1 data
migration. Those remain separate implementation/release workstreams.
