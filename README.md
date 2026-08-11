# comfyui-music-to-video

Turns a song into a music video: mp3 → lyrics → storyboard → reference images →
video clips → assembled cut, with playlist/genre set mixing on top. Rendering is
local ComfyUI on a single GPU; storyboards come from the xAI (Grok) API.

Two layers:

- **Pipeline scripts** (repo root) — the part that does the work. Each writes
  ComfyUI API-format workflow JSONs; nothing renders until they are submitted.
- **`studio/`** — a FastAPI web front end that drives those scripts, tracks state
  in sqlite, and serializes every GPU job through one worker.

## Pipeline scripts

| Script | Does |
|---|---|
| `build_storyboard.py` | lyrics + mp3 + album profile → storyboard `.json` + `.md`, scene count derived from lyric `[Section]` tags and track length |
| `make_anchor.py` | composes a character anchor sheet: face/hair from one image, wardrobe from another (`--view front\|back`) |
| `build_refs.py` | one Qwen-Image-Edit workflow per clip → reference images |
| `reroll_refs.py` | best-of-N re-roll for specific clips (composition is seed-dominated) |
| `build_song.py` | one WAN 2.2 S2V workflow per 4.8125 s clip; also holds the shared shot/allocation logic |
| `make_contact_sheet.py` | labelled contact sheet for approving a batch |
| `profiles/*.json` | per-album template: locations, palettes, camera vocabulary, outfits, guardrails |

Storyboards come in four schemas across the project's history; `build_song.normalize()`
maps them all onto the keys the builders read.

## studio/

    db.py        sqlite schema + queries          jobs.py     serialized queue, one worker, SSE
    tiers.py     content tiers + guardrail        pipeline.py wraps the scripts + ComfyUI submit
    lyrics.py    faster-whisper transcription     grok.py     xAI storyboard generation
    mixer.py     ffmpeg assemble / crossfade / set rendering
    app.py       FastAPI routes                   templates/, static/   server-rendered UI

Run `python3 <module>.py` for any of them — each carries its own self-check.
`test_integration.py` checks the seams; `test_app.py` covers the web layer.

### Deploy

    studio/deploy.sh

Rsyncs to the render box, builds a **separate venv** (ComfyUI's is left untouched),
installs a `systemd --user` unit, and smoke-tests the live endpoints plus ComfyUI
reachability and API-key presence. Binds to the tailnet only.

### Configuration

| Env | Meaning |
|---|---|
| `STUDIO_SCRIPTS` | directory holding the pipeline scripts |
| `STUDIO_DATA` | sqlite db, uploads, job logs |
| `COMFY_URL` / `COMFY_INPUT` / `COMFY_OUTPUT` | ComfyUI endpoint and its io dirs |
| `STUDIO_TEMPLATE_JSON` / `_MD` | storyboard pair used as the few-shot exemplar |
| `XAI_API_KEY` | read from env or `~/.config/morpheus/grok-mcp.env`; never committed |
| `WHISPER_MODEL`, `XAI_MODEL`, `XAI_TIMEOUT`, `SUBMIT_TIMEOUT` | overrides |

## Content tiers

`pg13` and `r` ship built in, and you can define your own with their own wording.
A tier controls tone, wardrobe coverage and intensity. `tiers.compose_guardrail()`
always appends `tiers.PINNED`, which is not user-editable: adults only, no nudity,
no depicted sex acts. `tiers.check_text()` refuses any input referencing minors, and
`grok.validate()` applies the same check to model output.

This matters mechanically, not just as policy: the image pipeline runs at **cfg 1.0**,
where ComfyUI skips the negative pass entirely — negative prompts are inert on this
stack. Positive-text steering and refusing input are the only controls that do anything.

## Hard-won constraints

- Framing must lead the prompt. `Camera: detail close` buried mid-prompt is ignored.
- Whole-word camera matching — `"slow push"` contains `"low"`.
- Reference images: `EmptySD3LatentImage`, not a VAEEncode of the anchor, or the
  output clones the anchor's pose and aspect ratio.
- Anchors must be neutral character sheets on plain grey; album art as an anchor
  leaks its title text and composition into every scene.
- One reference image per **clip**, not per scene — sharing one across three clips
  yields 15 s of identical footage.
- Seed variance dominates composition. Re-roll bad clips; don't tune settings.
- Clips render silent; the master mp3 is muxed over the assembled timeline once,
  so per-clip audio cannot drift.
