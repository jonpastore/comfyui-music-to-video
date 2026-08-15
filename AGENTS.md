# Meow P Studio

Music-video factory: mp3 → lyrics → storyboard → anchors → per-clip refs →
clips → assemble. FastAPI studio + sqlite. Renders on the SwarmUI / ComfyUI
fleet (cerberus 5090, gamingpc 5090, peaches 2080 Ti, ethan 5080).

Read `SESSIONS.md` and the newest `CONTINUATION-*.md` before relitigating.
Specs: `docs/TRD-*`, `docs/PRD-*`, `docs/DDD-*`, `docs/UIUX*`.

When work shows the product or the code has drifted from a written
requirement, update the TRD, PRD, DDD, **and** UI/UX docs in the same
change. Do not leave the docs describing the old world.

**Pipeline:** operator **base photographs** (`assets` kind `anchor_ref`)
→ generate **candidates** (`anchors`) → pick one → that sheet feeds
storyboard **refs** → clips. Do not upload plates or generated sheets
as bases unless the operator did.

## Character (decided)

Meow P is the black anthropomorphic cat-woman from the UI pair. Oracle files
(md5-match live Street Cats):

- front: `meowp_ui_front.png` = `00_reference_front.png` = `front_s4748`
- back: `meowp_ui_back.png` = `back_s4748`

Anchors and refs stay that person. Anatomy is a later layer on her, not a
stranger pose-plate body. Nude sheets: whole-body fur ~20% lighter than the
face reference; vulva and anus exposed, lighter than the surrounding fur,
feline and matching the base photographs' drawn style (not photoreal, not
human flesh). Tail up or aside.

## Render facts (measured, do not re-argue)

- Pose, not prompt, is what exposes anatomy. A standing figure with legs
  together and the tail across the region cannot show it.
- `image2` / the plate wins pose, hair, view, and tone.
- Identity lives in her photos as `image1`. Encode-her + denoise cannot take
  an exposing pose without becoming the plate. Empty latent can change pose.
- Working stack: Qwen-Image-Edit 2511, CFG 2.0 / 50 / `dpmpp_2m`+`karras`,
  empty latent 896×1216, `index_timestep_zero`, LoRA off. Short negatives.
- Seed dominates. 4748 clothes the back. 5151 holds plate pose. 129080599
  stands up / holds identity.
- One variable per test. Judge the picture. Do not rank on `warm px`.
- Song length owns clip count.
- Four shipped views stay byte-identical. Pose wording replaces the standing
  clause; it does not sit beside it. Frozen sha256 lives in `make_anchor.py`.

## Jarvis (this repo only)

Project name is `comfyui-music-to-video` (git remote). Do not invent
`comfyui`. Jarvis holds 200+ open tasks across other projects — ignore
those here. `my_tasks` dumps the whole portfolio and truncates (#166).

On session start: `jarvis-memory__sync`, then this project's
`next_action` and its tasks. That queue beats SESSIONS.md and chat.

- Facts (seeds, job ids, chosen anchors, judged sheets) → `remember`.
- Work → `add_task` with `source=grok` and `external_id=meowp:<key>`.
- Done → `complete_task` / `set_task_pct` only when merged or verified,
  not when an agent reports.
- Do not file 244 TRD criteria. Specs stay in `docs/TRD-*`. File the
  next product slice.
- Grind / autopilot: main thread orchestrates. Max 3 parallel worktree
  agents unless asked. Product order below beats a random task. Never
  deploy mid-render. You stay on pictures and decisions.
- Models: this session plans and reasons on **grok-4.6**. Execution
  subagents (`explore`, `general-purpose`, implementers) use **grok-4.5**
  unless a task needs 4.6 judgment. Pass `model=grok-4.5` on executor
  spawns so custom types do not inherit 4.6.

Operator guide (Grok vs Claude, compaction, UI): 
`~/.grok/docs/GROK-OPERATOR-GUIDE.pdf`.

## How to work here

- Tests: `cd studio && python3 -m pytest -q .`
- Never deploy mid-render. Deploy from a clean detached worktree at HEAD:
  rsync to `cerberus:~/meowp-studio`, then `systemctl --user restart` the
  studio unit. Smoke the pages.
- Live studio is `100.103.148.120:8000`. The worker is single-threaded.
- Parallel slices: Grok worktrees (`isolation=worktree`). Do not let two
  writers share `studio/*.py` in this tree.
- Continuation archive: keep the newest 3 `CONTINUATION-*.md` at repo root;
  move the oldest into `docs/continuations/` and fix inbound links.

## Product order

1. Anchors on-model (her, asked pose, asked view).
2. Know when a sheet is wrong (QC / repair).
3. Clips at the asked length.
4. Timeline last.
5. TRD-6 queue in full, not a stub.
