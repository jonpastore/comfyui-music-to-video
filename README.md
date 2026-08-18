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
| `batch_edit.py` | fleet Qwen-Image-Edit job set (`--config config.json.example`) |
| `profiles/*.json` | per-album template: locations, palettes, camera vocabulary, outfits, guardrails |

Operator recycle shelf (deprecate, Reddit proxy, QC stills, LTX fetch):
`docs/SCRIPTS.md`.

Storyboards come in four schemas across the project's history; `build_song.normalize()`
maps them all onto the keys the builders read.

## studio/

    db.py        sqlite schema + queries          jobs.py     serialized queue, one worker, SSE
    tiers.py     content tiers + guardrail        pipeline.py wraps the scripts + ComfyUI submit
    lyrics.py    faster-whisper transcription     grok.py     xAI storyboard generation
    mixer.py     ffmpeg assemble / crossfade / set rendering
    app.py       FastAPI routes                   templates/, static/   server-rendered UI

Run `python3 <module>.py` for any of them — each carries its own self-check.
`check_integration.py` checks the seams (run directly, not under pytest); `test_app.py` covers the web layer.

### Deploy

    studio/deploy.sh

Rsyncs to the render box, builds a **separate venv** (ComfyUI's is left untouched),
installs a `systemd --user` unit, and smoke-tests the live endpoints plus ComfyUI
reachability and API-key presence. Binds to the tailnet only.

### ComfyUI service

ComfyUI runs under `systemd --user` on the render box, bound to `0.0.0.0:8188`,
so it is reachable both on the tailnet and at `127.0.0.1` where the studio app
expects it. `--listen` takes a single address, so binding tailnet-only would cut
off the studio.

    ~/.config/systemd/user/comfyui.service
    ExecStart=%h/ComfyUI/venv/bin/python main.py --listen 0.0.0.0 --port 8188

`systemctl --user enable --now comfyui` plus `loginctl enable-linger` means it
survives logout and reboot -- it previously ran from a `nohup` one-liner that did
not. Note it is unauthenticated and can read and write files and execute
workflows, so the network it is bound to is the only thing gating it.

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
no depicted sex acts. `tiers.check_text()` refuses a minor reference except at
`g`/`pg13` (`T10-18`: a child may be referenced and depicted where explicit
content cannot be reached). Unset tier is treated as `xxx`. `grok.validate()`
applies the same check to model output.

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
