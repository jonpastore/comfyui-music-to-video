Status: COMPLETE
Phase: 1 — Discovery
Last Updated: 2026-08-19
Inputs Used: `docs/reviews/UIUX-DISCOVERY-2026-08-19.md`; `SESSIONS.md`; `CONTINUATION-2026-08-16-pose-anatomy.md`
Open Questions: Deployment hardening details; broken anchor-media root cause; full keyboard/announcement coverage
Blocking Findings: None blocking isolated design work; SEC-02 and SEC-03 block treating the current service as safely multi-operator/cloud-ready
Next Recommended Phase: Product synthesis/interview

# Discovery handoff

## Workspace mode

`SINGLE_REPOSITORY`. The current workspace is the `comfyui-music-to-video` repository and contains the FastAPI studio, rendering orchestration, SQLite persistence, templates, static assets, tests, and product specifications.

## Product facts

- Internal, Tailnet-hosted, single-operator music-video factory.
- Primary output: a completed, monetizable music video. Secondary output: a continuously playable mixed set and streaming-platform versions.
- Critical journey: song intake → preparation → pose coverage → storyboard → per-scene references → LTX-first clips → optional WAN s2v lip-sync hop → validation/assembly → set/release.
- Library is a cross-song throughput surface. Song, Anchors, Storyboard, Review/QC, Jobs/Fleet, and Sets are distinct work contexts.
- Operator requires progressive results and in-page mutations; navigation alone may change documents.

## Architecture facts

- FastAPI/Jinja server-rendered application with HTMX, fetch, SSE/polling, and SQLite.
- `studio/app.py` is a 12k-line route concentration; `studio/static/app.js` and `style.css` are large global files.
- Sound reusable server fragments and partial contracts exist; no client framework/state store exists.
- One serialized worker coordinates long-running work across a heterogeneous ComfyUI/SwarmUI fleet.
- Existing visual language is a restrained dark operational UI with partial semantic tokens and shared primitives.

## Rendered UX facts

- Desktop/laptop are usable; Library and Anchors are dense, while Song is a long disclosure stack.
- Tablet/mobile expose clipping and navigation-wrap risks, but phone support is not a product requirement.
- Semantic structure and common native controls are present; disclosure focus, tab semantics, reduced-motion coverage, and dynamic announcements are incomplete.
- Broken anchor image URLs remove decision context. A deployed dialog also drifted from shared modal-close guidance.
- Several mutations still reload or instruct the operator to refresh, contrary to the in-page rule.

## Security facts

- No application authentication/authorization; Tailnet reachability is the current boundary.
- The media route served the live SQLite database.
- Stored Library grouping text reaches an `innerHTML` XSS sink.
- Mutation routes lack CSRF/origin protection; costly work lacks caller identity/idempotency/rate controls.
- These are design inputs and production prerequisites, not reasons to add fake client-side security to a prototype.

## Discovery inference

The studio is a mature internal engineering tool but an immature autonomous product experience. The largest opportunity is not decorative modernization: it is establishing an attention-led production model, clear approval/review contracts, progressive evidence, and coherent transitions between overview, scene work, video review, and set composition.
