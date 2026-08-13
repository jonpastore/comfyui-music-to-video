# Continuation archive

Session hand-off docs, oldest first. The **latest three live at the repo root**;
everything older is moved here when a fourth is written.

Most recent: **[CONTINUATION-2026-08-13-meowp-studio-day14.md](../../CONTINUATION-2026-08-13-meowp-studio-day14.md)**
(at the repo root, along with the two before it).

These docs are in `.gitignore` -- only this index is tracked. `git mv` fails on
them; use `mv` when rotating one in.

| Doc | Session |
|---|---|
| [CONTINUATION-2026-08-10-meowp-video-pipeline.md](CONTINUATION-2026-08-10-meowp-video-pipeline.md) | Hardware verdict, model settings, the eight rendering findings. Still the reference for how the renderer behaves. |
| [CONTINUATION-2026-08-11-meowp-studio.md](CONTINUATION-2026-08-11-meowp-studio.md) | The studio app, the guardrail architecture, tiers as a render-time choice. Still the reference for why the guardrail lives in one place. |
| [CONTINUATION-2026-08-11-meowp-studio-overnight.md](CONTINUATION-2026-08-11-meowp-studio-overnight.md) | Song page rebuild, songbook import, albums as playlists, local vision, the first complete song |
| [CONTINUATION-2026-08-11-meowp-studio-day2.md](CONTINUATION-2026-08-11-meowp-studio-day2.md) | Character consistency, the model-pick bug, UI corrections |
| [CONTINUATION-2026-08-11-meowp-studio-day3.md](CONTINUATION-2026-08-11-meowp-studio-day3.md) | Storyboard authoring, cast, reference repair, MPA tiers, LTX-2.3, publishing config |
| [CONTINUATION-2026-08-11-meowp-studio-day4.md](CONTINUATION-2026-08-11-meowp-studio-day4.md) | Sets as documents, beat matching, DJ effects, the timeline, AI mix suggestions. **Its Traps section still governs render code.** |
| [CONTINUATION-2026-08-12-meowp-studio-day5.md](CONTINUATION-2026-08-12-meowp-studio-day5.md) | The prompt/seed/VRAM chain behind missing and wrong anchors; nude anchors settled |
| [CONTINUATION-2026-08-12-meowp-studio-day6.md](CONTINUATION-2026-08-12-meowp-studio-day6.md) | The anchor set completed and unpicked, async generate with a live queue indicator, `gpu.py` taking the card back from ollama, the bind that was set and ignored |
| [CONTINUATION-2026-08-12-meowp-studio-day7.md](CONTINUATION-2026-08-12-meowp-studio-day7.md) | The anchor form spec, the CFG sweep that measured its defaults, prompt versioning, and the review that found a set which predicted a length it could not render |
| [CONTINUATION-2026-08-12-meowp-studio-day8.md](CONTINUATION-2026-08-12-meowp-studio-day8.md) | Cast members owning their own nude wording and anatomy, the uniform copy, and the review findings behind them. **Its "a diffusion model has no NOT" still governs prompts.** |

At the root right now:

| Doc | Session |
|---|---|
| [CONTINUATION-2026-08-12-meowp-studio-day9.md](CONTINUATION-2026-08-12-meowp-studio-day9.md) | **Infrastructure, not features.** LTX-2.5 as the default renderer, the cu130 finding that had every quantised matmul running eager, five anchor-form defects, peaches-unraid as a real backend, and the fleet allocation |
| `CONTINUATION-2026-08-12-meowp-studio-day10.md` | **Measurement, then specification.** 30s and 60s clips render; identity comes from the TEXT and not the reference image; swarm on in production; production video was dead at argparse; TRD-2 drafted. **Holds the standing instruction for the TRD -> PRD -> DDD -> style guide -> critique pipeline.** |
| `CONTINUATION-2026-08-13-meowp-studio-day11.md` | **The TRDs finished, then built from.** All three TRDs written with 106 failable criteria; the loudnorm finding that would have flattened every level curve the DAW draws; scene_seconds winning over a floor that sat in two places; QC tier 1 with every threshold measured rather than picked. **Nothing deployed.** |

| `CONTINUATION-2026-08-13-meowp-studio-day12.md` | **Deployed.** Five live anchor defects fixed, QC's 8n+1 bug, the TRD set consolidated to 7 documents with TRD-6 s0 holding what they all inherit. |

The next continuation archives `CONTINUATION-2026-08-13-meowp-studio-day12.md`.

## Standalone hand-offs

Scoped to one machine or one piece of work rather than to a session, so they do
not take part in the rotation above.

| Doc | For |
|---|---|
| [`ETHAN-CONTINUE.md`](../../ETHAN-CONTINUE.md) | Bringing `ethan-wsl` up as a second ComfyUI backend: what is staged there, how to resume after the reboot that interrupted it, and why a 16 GB card does not help with the video renders |

| `CONTINUATION-2026-08-13-meowp-studio-day13.md` | **The specification set completed, and one policy rewritten twice.** Ten TRDs, three PRDs, three DDDs and a style guide, every TRD externally reviewed and every one carrying a positive-half table and a built-state ledger. TRD-8/9/10 written to absorb five orphaned plans and ~4,600 lines of uncited code. The minor policy went from a blanket keyword refusal to a per-tier rule, then to an artefact lock after adversarial review found the hole the loosening opened. `T1-20d` fixed; canonical host shipped. **The PRDs, DDDs and the style guide have never been externally reviewed — that is the next session's job.** |

| `CONTINUATION-2026-08-13-meowp-studio-day14.md` | **The first images, and what they said.** An xxx nude sheet rendered through the new prompt and came back a plain human woman -- correct behaviour for an empty album profile, and the identity-comes-from-text thesis demonstrated on a real render. The composed prompt logged and validated by grok: 15 negations, 9 skin words, species in the last quarter. The agent-lane finding retracted -- it works, and the probe that said otherwise measured a haiku agent echoing a word. |
