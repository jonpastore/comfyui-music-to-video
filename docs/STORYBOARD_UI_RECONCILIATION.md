# The storyboard UI requirements, against what is already built

A set of storyboard-page requirements was given on 2026-08-12 and nearly got
lost in the day's traffic. Reconciled here against the code rather than against
memory, because most of it turned out to exist already and specifying it again
would have been the expensive kind of mistake.

This is the input to TRD-2 (story arc and storyboards).

## Already built — do not respecify

| requirement | where it lives |
|---|---|
| Per-scene timing on the storyboard page | `app.storyboard_scenes()` derives it from `build_song.clip_plan()` — THE scene-to-clip mapping, shared with `build_refs`/`build_song`/`reroll_refs`. Its docstring says deriving it a second time is the drift `clip_plan` exists to prevent. |
| Editable scene text | `EDITABLE_SCENE_FIELDS = ("image_prompt", "video_motion_prompt", "story")`, `MAX_SCENE_FIELD = 4000`. `image_prompt` is what the reference renderer sends; `video_motion_prompt` is what the clip renderer sends. |
| Characters as first-class, with their own fields | `characters` table, `CHARACTER_FIELDS` = role, identity, wardrobe, body, nude_wardrobe, anatomy. Copyable between cast members except identity — "a band shares a uniform, not a face". |
| Reference images PER CHARACTER | `anchors.character_id`, and `chosen_anchor(scope_kind, scope_value, tier, view, character_id)`. `character_id=None` means the protagonist, which is every anchor that existed before the cast did. `anchor_refs(album, character_id)` holds the saved base images per album AND character. |
| Warning when a scene names someone with no anchor | `storyboard_scenes(..., anchored=)` takes the set of cast names with a chosen anchor at that tier, so a scene naming somebody unanchored says so BEFORE fifty frames render them from scene text alone. |
| Face swap, inpaint, outpaint | `fix_ref.py`, three modes, all on Qwen-Image-Edit 2511 — the model that rendered the frame in the first place. No ReActor, no IPAdapter, no InstantID, because a multi-image edit model does not need them. Wired: `@jobs.handler("fix_ref")` plus a route. |
| Model selection, with what each model is FOR | `/models`, grouped by role, carrying purpose, measured caveats, per-role defaults, and (since today) per-backend availability, weights size, and whether the model fits that card. |

## Not built

1. **Editing the storyboard GENERATION prompt.** The form takes tier, model,
   `scene_seconds` and `direction`. `direction` is a free-text steer that reaches
   the model, but the prompt template itself is neither visible nor editable, and
   the limits and guardrails that apply to it are not shown anywhere near the box.
2. **A total-time-versus-song-length meter.** Nothing validates that the scenes
   sum to the track. Given `scene_seconds` cannot lengthen a scene (below), this
   is the check that would have surfaced that immediately.
3. **Main actor / extra / background classification at generation time.** The
   page can warn that a named character has no anchor; nothing decides who NEEDS
   one. Extras and background do not need anchors and currently look identical to
   leads.
4. **ComfyUI reference-image best practices.** Not researched.

## The catalogue has fallen behind the box

Sixteen models are installed on cerberus and absent from `models.CATALOG`.
Checked by diffing every loader enum against the catalogue's files, companions
and aliases:

    LTX-2/ltx-2-19b-ic-lora-detailer.safetensors
    LTX-2/ltx-2-19b-lora-camera-control-static.safetensors
    ltx-2-19b-lora-camera-control-dolly-left.safetensors
    ltx-2-19b-distilled-lora-384.safetensors
    ltx-2-19b-dev-fp8.safetensors
    ltx-2.5-22b-distilled-transformer-nvfp4.safetensors
    Qwen-Image-Edit-Unblur-Upscale_15.safetensors
    qwen-edit-skin.safetensors
    ZImage/SwarmUI_Z-Image-Turbo-FP8Mix.safetensors
    z_image_turbo_fp8mix.safetensors
    OfficialStableDiffusion/sd_xl_base_1.0.safetensors
    taeltx2_3.safetensors
    ae.safetensors, qwen_3_4b_fp8_mixed.safetensors,
    QwenImage/qwen_image_vae.safetensors, pixel_space

Some of that is deliberate — `ae.safetensors` and `qwen_image_vae` are companions
under an alias, `pixel_space` is a built-in. But the LoRAs are a real gap, and
one of them matters more than the rest.

### The camera-control LoRAs are the interesting find

`ltx-2-19b-lora-camera-control-{static,dolly-left}` are named for the 19B base,
which suggested they were locked to a model this project does not run. They are
not, dimensionally:

    camera LoRA   transformer_blocks.0.attn1.to_k.lora_A.weight  [32, 4096]
    LTX-2.5 22B   transformer_blocks.0.attn1.to_k                [4096]

Same inner dimension. If the LoRA applies to 2.5, the 19B base never needs
installing — and every storyboard scene already carries a `camera` field
("over-shoulder", "low", "macro", "wide") that today is prose the renderer may or
may not honour. A camera-control LoRA turns the storyboard's shot language into
something the renderer executes.

**The risk is not an error, it is silence.** 2.5 is int8-quantised (it carries
`weight_scale` tensors), and a LoRA half-applied over quantised weights looks
exactly like a LoRA that did not help. So the test is a differential — same seed,
same prompt, LoRA on and off — and the question is whether the picture moves
differently, not whether the job succeeded.

**The 19B base model itself is not worth wiring.** LTX-2.5 supersedes it, is
measured stable on two boxes, renders 30s and 60s, and is audio-conditioned.

## Feeding into TRD-2, from the day's measurements

Three findings from elsewhere in the day change what the storyboard UI has to do:

- **`scene_seconds` cannot lengthen a scene.** `n_scenes = max(len(sections),
  ceil(duration / scene_seconds))`, so a 25-section song returns 25 scenes
  whether 15s or 30s is asked for. Requirement 2's time meter would have caught
  this on the first generation.
- **The reference image does not hold identity; the TEXT does.** Measured with a
  one-variable differential. This makes `character_reference` load-bearing, and
  an empty one renders a stranger in every clip while passing every deterministic
  check. A storyboard UI that lets a human edit prompts needs to refuse to save
  an empty character reference, not just accept it.
- **Clip length is not bound to 4.8125s.** 30s and 60s both render. The page's
  timing display and the time meter both have to read the real per-song clip
  length rather than the old constant.
