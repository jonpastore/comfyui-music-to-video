Status: COMPLETE
Phase: 2 — Product understanding and owner interview
Last Updated: 2026-08-19
Inputs Used: `.ux-review/01-discovery.md`; product-owner interview in the active Codex session
Open Questions: Exact initial QC thresholds and automation defaults are tunable implementation policy, not blockers to UX direction
Blocking Findings: None
Next Recommended Phase: UX strategy and design directions

# Product-owner decisions

## User and maturity

- One expert owner/operator today, still learning ComfyUI/models while making the pipeline work.
- The present product must support diagnosis without freezing the long-term UX into an engineering console.
- No explicit commissioning/production modes; use one coherent experience with progressive technical disclosure.

## Desired operating model

- Default priority: failures/decisions → productions ready for review → last workspace → Library.
- Successful stages advance automatically when QC passes.
- Attention includes approval gates, exhausted repair attempts, uncertain/hard-blocker QC, missing input, fleet/job failure, and paid/cloud authorization.
- Automation has global defaults, production overrides, and exceptional scene overrides; policies remain configurable.
- Self-hosted models may act with considerable autonomy. Paid/cloud activity requires configurable approval.
- Initial retry boundary: four total attempts per failing unit/stage, then escalate with evidence.

## Approval and QC contract

- Pre-render approval combines storyboard description, pose/location, generated references, and low-cost motion previews.
- Human gates: combined scene plan; completed individual video; proposed set plan; completed set.
- Video review starts with AI findings on the timeline.
- Available decisions: approve, override, repair scenes, change repair instructions, return to storyboard, compare attempts.
- Failure evidence should retain failed media/timestamp, plain-language explanation, stage/model, attempts, confidence, proposed repair, estimated time, and prompt/settings.
- Overrides remain auditable and may improve local recommendations.
- QC separates technical validity, creative quality, and declared G-to-Mature tier adherence; authorized mature content is not itself a defect.

## Pipeline behavior

- Anchors create scene references; LTX 2.5 animates scenes.
- WAN s2v is slow and reserved for prompt-identified lip-sync scenes; it consumes frames rather than an LTX video directly.
- LTX 25 fps → WAN 16 fps must preserve requested duration by timestamp sampling and decoded duration/audio validation. Naive replay risks 1.5625× elongation.
- Post-processing and validation are important, but repair should restart the smallest failing unit rather than the full pipeline.

## Mixed-production model

- AI proposes song order and reasons; operator can override.
- Inputs combine song storyboards, lyrics/music analysis, and a set-level narrative.
- Operator approves order, story, transition concepts, timing, and proposed regeneration before GPU work.
- Sets may trim/overlap edges, replace edge scenes, regenerate elsewhere, and use fades/effects/images/connective material.
- Standalone approved videos remain intact; short set-specific scenes are derivatives, not promotion candidates.
- Individual music videos and a continuously playable production are both first-class outputs.
- Set/mix interaction should borrow useful arrangement concepts from ACID Pro, Ableton, and FL Studio. Scene generation should be substantially simpler than ComfyUI.

## IA and visual direction

- Neutral, professional visual character; avoid theatrical Meow P branding and generic AI-SaaS decoration.
- Improve media presentation and organization while retaining operational function.
- Desktop/laptop first.
- All normal mutations stay in-page with explicit pending/success/error/partial states.

## Lifecycle and communication

- Lifecycle: Preparing → Needs approval → Rendering → Validating/repairing → Ready for review → Approved → Exported → Released.
- “Needs attention” is a blocker/decision overlay rather than a lifecycle stage.
- Release may be automated per destination through APIs such as YouTube; destinations can succeed/fail independently.
- Email: approval ready, final video/set ready, repairs exhausted, fleet failure, and paid-action authorization.
- Local QC outcomes may improve future recommendations; nothing goes to cloud without the configured approval.

## Decision impact

The product should be designed around an attention inbox and media-led review, with technical evidence one level behind the decision. The scene-production workspace remains guided and stage-aware. The set editor is the only surface that should adopt a DAW-like timeline mental model.
