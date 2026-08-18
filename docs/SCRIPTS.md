# Operator utilities

Indexed so the next session does not write another one-off.
Product pipeline CLIs (`make_anchor.py`, `build_refs.py`, `build_song.py`,
…) stay at repo root and are listed in `README.md`. This page is the
*recycle* shelf: batch jobs, fleet helpers, and hold-area tools.

A new dated helper goes here only after it has a reusable entry point
(flags, no hardcoded stamp/host). One-off job JSON stays on the machine
(`config.json` is gitignored). The template is `config.json.example`.

## `scripts/`

| Tool | Recycle as | Do not |
|---|---|---|
| `scripts/deprecate.py` | `python3 scripts/deprecate.py STAMP path [path…]` moves into `deprecated/<stamp>/` and writes `MANIFEST.md`. `--list` shows batches. | Do not write another `deprecate_*_junk.py`. Restore with `mv`; delete only after Jon says so. |
| `scripts/reddit-egress-proxy.py` | Rate-limited HTTP/HTTPS proxy, Reddit hosts only. `--bind` `--port` `--token-file` `--state-file`. Unit template: `scripts/reddit-egress-proxy.service`. | Do not hit Reddit from a new box without this gate. Token is not in git. Bind a Tailscale IP, not `0.0.0.0`. |
| `scripts/gen_reddit_catalog.py` | Rebuild the scene-act catalog (`reddit-pose-catalog.json` / `.md`). `--out` defaults to the local `anchor5/` lab. Tables in the script are the source. | Do not scrape Reddit. Do not use catalog stills as image1 or a person-plate in image2. |

`deprecated/` is gitignored (failed hops, stills). The tool is tracked;
the junk is not.

Spent: `scripts/deprecate_pose_junk.py` (2026-08-16 pose-grind path
list). That batch already moved. Use `deprecate.py`.

## Root helpers that are easy to forget

| Tool | Recycle as |
|---|---|
| `batch_edit.py` | Fleet Qwen-Image-Edit job set. `--config config.json.example`. Local `config.json` is a one-off (machine paths + one prompt) and is not tracked. Dated `config.nude-*.json` are historical job sets already in git. |
| `qc_stills.py` | Score a directory of stills with the studio QC stack (not a histogram gate). |
| `make_contact_sheet.py` | `python3 make_contact_sheet.py <src-dir> <out.png>` labelled sheet of `clip_NNN_*.png`. |
| `cast_bf16_to_fp16.py` | ACE-Step weights for Turing (peaches). Refuses to write if a tensor is near the fp16 ceiling. |
| `run_anat_inpaint.py` | Anatomy inpaint at the measured quality sampler (cfg 2 / 50 / LoRA off). Not the Lightning default. |
| `fetch_ltx25.sh` / `update_ltx25.sh` | Pull / refresh LTX 2.5 on a fleet box. |
| `fix_ref.py` | Single-sheet repair graph (used by studio QC). |


## Do not commit

| Path | Why |
|---|---|
| `.grok/` | Session / workflow scratch. Named workflows live in `~/.grok/workflows/`. |
| `deprecated/` | Hold-area stills. |
| `config.json` | Local `batch_edit` job set. Use `config.json.example`. |
| leftover `_scene_row.html` / `_storyboard_panel.html` | Unfinished storyboard dirt. Not this shelf. |
| `anchor5/` | Operator photo lab, Reddit samples, pose-hop runbooks. On disk only. |
