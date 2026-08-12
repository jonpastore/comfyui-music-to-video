# Continuation archive

Session hand-off docs, oldest first. The **latest three live at the repo root**;
everything older is moved here when a fourth is written.

Most recent: **[CONTINUATION-2026-08-12-meowp-studio-day6.md](../../CONTINUATION-2026-08-12-meowp-studio-day6.md)**
(at the repo root, along with the two before it).

| Doc | Session |
|---|---|
| [CONTINUATION-2026-08-10-meowp-video-pipeline.md](CONTINUATION-2026-08-10-meowp-video-pipeline.md) | Hardware verdict, model settings, the eight rendering findings. Still the reference for how the renderer behaves. |
| [CONTINUATION-2026-08-11-meowp-studio.md](CONTINUATION-2026-08-11-meowp-studio.md) | The studio app, the guardrail architecture, tiers as a render-time choice. Still the reference for why the guardrail lives in one place. |
| [CONTINUATION-2026-08-11-meowp-studio-overnight.md](CONTINUATION-2026-08-11-meowp-studio-overnight.md) | Song page rebuild, songbook import, albums as playlists, local vision, the first complete song |
| [CONTINUATION-2026-08-11-meowp-studio-day2.md](CONTINUATION-2026-08-11-meowp-studio-day2.md) | Character consistency, the model-pick bug, UI corrections |
| [CONTINUATION-2026-08-11-meowp-studio-day3.md](CONTINUATION-2026-08-11-meowp-studio-day3.md) | Storyboard authoring, cast, reference repair, MPA tiers, LTX-2.3, publishing config |

At the root right now:

| Doc | Session |
|---|---|
| `CONTINUATION-2026-08-11-meowp-studio-day4.md` | Sets as documents, per-song analysis, beat matching, DJ effects, the timeline, AI mix suggestions, Python 3.12 |
| `CONTINUATION-2026-08-12-meowp-studio-day5.md` | The prompt/seed/VRAM chain behind missing and wrong anchors; nude anchors settled |
| `CONTINUATION-2026-08-12-meowp-studio-day6.md` | The anchor set completed and unpicked, async generate with a live queue indicator, `gpu.py` taking the card back from ollama, the bind that was set and ignored |

The next continuation archives `CONTINUATION-2026-08-11-meowp-studio-day4.md`.

## Standalone hand-offs

Scoped to one machine or one piece of work rather than to a session, so they do
not take part in the rotation above.

| Doc | For |
|---|---|
| [`ETHAN-CONTINUE.md`](../../ETHAN-CONTINUE.md) | Bringing `ethan-wsl` up as a second ComfyUI backend: what is staged there, how to resume after the reboot that interrupted it, and why a 16 GB card does not help with the video renders |
