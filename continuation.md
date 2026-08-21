# ComfyUI / Meow P Studio — current continuation

Updated: 2026-08-21

Read `AGENTS.md`, `SESSIONS.md`, this file, and the newest three dated `CONTINUATION-*.md` files before taking a worktree, GPU, deployment, or live data action.

## Project rollup

Jarvis project: `comfyui-music-to-video` (id `2018`)

| Measure | Current value | Source / meaning |
| --- | --- | --- |
| Open tasks remaining | **28** | Jarvis live project rollup, 2026-08-21 |
| Overall completion | **62%** | Task-weighted `pct_complete`: done tasks count as 100%; open tasks use recorded progress |
| Current recorded next action | P0-1 shared keeper controlled migration | Jarvis project next action |

This is the project-specific measure, not the broader Jarvis portfolio count. It does not claim production migration or GPU evidence is complete.

## Active workstreams

### UX prototype — user priority / ready for decision

- Isolated worktree: `/tmp/comfyui-ux-prototype-20260821`
- Integrated: `main@ef30cdd` (`2d74040` is the prototype-artifact commit)
- Scope: disposable static prototype only; synthetic fixtures; no production API, data mutation, deployment, render fleet, or GPU use.
- Decision package: `.ux-review/decision-package.md`
- Capability parity: `.ux-review/feature-capability-parity.md`
- Fresh evidence: `.ux-review/08-current-rendered-evidence.md`
- Independent review dispositions: `.ux-review/09-adversarial-prototype-review.md`

Directions: **A — Operations Control Room**, **B — Production Desk** (recommended), and **C — Review Theatre**. The synthetic keeper surface covers shared/tiered, reconciled, legacy-only, and verification-required states without exposing migration internals. Fresh Playwright checks proved working direction/keeper actions, no 390px horizontal overflow, and zero `axe-core 4.13.0` WCAG 2 A/AA violations.

**Gate:** user selects A, B, C, or a combination. That authorizes implementation planning, not an automatic production rewrite. The prototype is committed in the repository; it is not served as a live Studio product route.

### P0-1 shared keeper controlled migration — separate implementation readiness

- Isolated worktree: `/tmp/comfyui-p0-1-shared-keeper-K4s1Va`
- Branch: `agent/p0-1-shared-keeper`
- Latest worker commit: `c1f28e9` — reconcile mixed tier snapshots per scope.
- Worker-reported focused evidence: 97 tests; `keeper_migration.py` statement and branch coverage 100%; Ruff and diff check clean.

Do **not** integrate P0-1 yet. It remains separate from UX readiness. A fresh independent final review of `c1f28e9`, including the mixed default/tier rollout-order cases, is required before integration.

### Explicit boundaries

- **Production migration:** not authorized; do not run against live data.
- **GPU / render fleet:** separate pending workstream; do not claim a renderer for UX or migration work.
- **Studio runtime deployment:** `main@ef30cdd` restarted and smoke-tested on cerberus. This deployment did not make the disposable prototype a production route.
- **Shared/main checkout:** user-owned and dirty; use clean isolated worktrees.

## Resume order

1. On UX choice, freeze the direction and create the dependency-aware production delivery plan.
2. Independently review P0-1 at `c1f28e9`; do not integrate unless the new head has clean evidence.
3. Use Jarvis `sync`, then `comfyui-music-to-video`’s next action and task count; do not use the global portfolio dump as this project’s queue.
4. Maintain the D1–D10/#529 loop as the product path. Do not resume the parked anatomy grind without the pose-QC gate and a render-specific criterion.
