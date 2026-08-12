# Outside opinion on the five new areas — grok, chatgpt, gemini, perplexity

Asked on 2026-08-12, against a brief describing the real stack (FastAPI + Jinja2
+ htmx, no build step, ffmpeg for all deterministic media work, ComfyUI behind
SwarmUI, one SQLite database, single user on a tailnet).

**Every project named below was checked against the GitHub API before it was
written down** — exists, star count, last push, archived flag. The brief told all
four models to mark uncertainty `UNSURE` and never produce a plausible repo name,
because a fabricated dependency costs more than a missing one. None of the twenty
turned out to be fabricated, which is worth recording as much as the advice is.

## The reference projects, verified 2026-08-12

| project | stars | last push | take from it |
|---|---|---|---|
| `katspaugh/wavesurfer.js` | 10,370 | 2026-08-10 | The waveform + regions interaction. Named by 5 of 5 as the default answer for a browser waveform with draggable regions. |
| `naomiaro/waveform-playlist` | 1,666 | 2026-07-27 | **Multi-track** playlist UI with per-track fades and volume — the closest existing thing to what is wanted, in plain JS. |
| `bbc/peaks.js` | 3,405 | 2025-11-08 | Pre-computed peak files and zoom levels. The technique that stops a 60-minute set from decoding into the browser. |
| `bluesky-social/atproto` | 9,585 | 2026-08-12 | Official Bluesky client + auth model. |
| `praw-dev/praw` | 4,225 | 2026-08-12 | Reddit API, including the NSFW flag that the tier gate has to set. |
| `tweepy/tweepy` | 11,178 | 2026-07-02 | X API v2 media upload. |
| `yt-dlp/yt-dlp` | 184,099 | 2026-08-04 | **Read it for the extractor/auth patterns, not for uploading — it downloads.** |
| `gitroomhq/postiz-app` | 34,593 | 2026-08-12 | A working multi-platform posting service. Take the per-platform adapter shape and the queue/retry model, not the app. |
| `Netflix/vmaf` | 5,451 | 2026-08-12 | Reference video quality metric, as a number. For QC tier 1/2. |
| `Breakthrough/PySceneDetect` | 5,094 | 2026-08-10 | Shot-change detection — usable as a frozen/black-frame and cut detector for QC. |
| `deepinsight/insightface` | 29,479 | 2026-07-27 | Face embeddings for reference-compliance scoring (the "is this the same character" number). |
| `MTG/essentia` | 3,690 | 2026-07-22 | Audio feature extraction, loudness, key/BPM — overlaps what analyse.py already does. |
| `librosa/librosa` | 8,555 | 2026-08-11 | Already a dependency here. |
| `aubio/aubio` | 3,743 | 2026-04-10 | Onset/beat detection, if the existing beat grid ever needs a second opinion. |
| `csteinmetz1/pyloudnorm` | 780 | 2026-01-04 | EBU R128 loudness measurement for the export path. |
| `slhck/ffmpeg-normalize` | 1,526 | 2026-07-10 | Loudness normalisation done correctly over ffmpeg — read it rather than depend on it. |
| `Zulko/moviepy` | 14,846 | 2026-08-11 | Reference only. It is a different architecture from this project's filter-graph approach. |
| `remotion-dev/remotion` | 56,173 | 2026-08-12 | **Wrong fit — React, needs a build step.** Listed because two models named it; do not adopt. |

### The two to be careful with

- **`kkroening/ffmpeg-python`** — 11,003 stars, **last push 2024-08-04, two years
  stale.** It was the single most-recommended library (5 of 5) for building filter
  graphs, and it is among the least maintained things on this list. It is also
  solving a problem this project already solved: `mixer.py` builds filter graphs by
  hand and its arithmetic is the part that is tested. Adding it would be a
  dependency for work already done. **Recommendation: read it, do not adopt it.**
- **`richzhang/PerceptualSimilarity` (LPIPS)** — 4,267 stars, **last push
  2024-07-02.** Still the standard perceptual-similarity reference, but unmaintained;
  treat as a paper implementation to copy from, not a dependency.

## What all four said we had missed

Listed where two or more agreed independently.

1. **The timeline model lives on the server, not in the DOM.** The browser is a
   view. Export must be deterministic from the stored model with no dependency on
   pixel positions. (This project already has that instinct — `set_items` rows —
   but automation curves would be the first thing tempted to live in the browser.)
2. **Preview is not the deliverable, and users will trust the wrong one.** Browser
   playback is a proxy; ffmpeg is the truth. Both a UI label and a design rule.
   This is the same defect this codebase has already paid for six times — the
   editor promising what the renderer does not produce — arriving in a new place.
3. **Automation curves need an explicit interpolation and quantisation rule.**
   Drawing at 60 Hz mouse events produces thousands of keyframes and a pathological
   filter graph. Curves must be decimated to something ffmpeg can express.
4. **"L/R split" is three different features** — dual mono tracks, stereo pan, or
   mid/side — and the ffmpeg `pan`/`channelsplit` behaviour has to be chosen before
   any UI is drawn.
5. **Sample-accurate vs frame-accurate clock.** Audio at 48 kHz and video at a
   fixed fps disagree; store automation in seconds *and* in media timebase, with a
   stated rule for the disagreement.
6. **Peak data must be decimated per zoom level.** Do not decode a 60-minute set
   into JS.
7. **QC needs labelled failures before any threshold is trusted** — which is what
   the existing `OUTPUT_QC_PLAN.md` already says, arrived at independently.

## Where they disagree with the stated requirement

**Three modes — easy / normal / advanced — was argued against by two of the four,
independently.** The argument: three modes triples UI layout logic, state
transitions and test paths, for one data model. The proposed alternative is *one*
track layout with collapsible sub-lanes, so advanced features are disclosed
progressively rather than duplicated across three editors.

**RESOLVED 2026-08-12 by Jon, and the models were answering a different
question.** They optimised for code paths. The requirement is about *audience*:

- **easy** — "I don't know anything and I want a button that solves it for me"
- **normal** — customisation with enough context to play and learn from
- **advanced** — someone who understands audio engineering and what mastering needs

One data model, one editor, three affordance sets. But note what that means and
what a density toggle would have missed: **easy mode is a feature set, not a CSS
class.** "Solve it for me" requires real automation — auto-level, auto-fade,
one-button master — that the other modes expose as individual controls. Hiding
lanes does not make an easy button.

The reason to keep the separation, in Jon's words: assuming every user is equally
expert limits the audience. That is a product argument, and it beats the
maintenance argument the models made.

## What not to build, where they agreed

- **Never parse ffmpeg back into JSON.** One-way only: stored model → filter graph.
- **No second DSP engine in Web Audio** mirroring ffmpeg effects for preview.
- **No custom encoders or muxers** — pass codec parameters to ffmpeg
  (`pcm_s16le`, `pcm_s24le`, `flac`, `libvorbis`).
- **QC flags and scores; it does not auto-heal.** No automatic regeneration
  without human sign-off, and no "auto-repair inpainting pipeline promised as QC".
  **Resolved 2026-08-12 and it is not a conflict:** a finding goes to a review
  queue carrying its own comments and a proposed remedy, that remedy is an
  EDITABLE PROMPT, and a button approves reprocessing. That IS the human sign-off
  the advice asks for, and it is strictly better than a bare PASS/FAIL because
  the finding arrives actionable. The remedy prompt is versioned in the same
  `prompts` table as every other prompt in the studio.
- **No CV model trained from scratch** until cheap gates exist and there are
  labelled failures. Use pretrained extractors.
- **No hand-rolled chunked upload** for YouTube or TikTok; use the official SDKs.
- **No custom git** for prompt versioning — no commit trees, no merge engine. The
  existing versioned `prompts` table is the right shape.
- **Do not auto-apply an LLM rewrite across every song in an album.**
- No collaborative/multiplayer timeline, no social CMS/analytics suite, no
  scraping to bypass upload limits.

## A note on how this was collected

`llm -m <model> "<2.5KB prompt>"` returns an **empty string with exit code 0** —
four silent empty files and no error. The same prompt on **stdin** works. Recorded
because it looks exactly like a broken tool and is not, and because it is the
second time today a check produced no data while appearing to succeed.
