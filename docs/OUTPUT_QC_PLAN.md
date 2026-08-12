# Output QC — a post-render stage that measures instead of judging

Asked for on 2026-08-12: a pipeline stage that, after the jobs, analyses output
for reference compliance and for artifacts that need cleaning up, and returns a
final. Nothing here is built. This is the recommendation and the order.

## The trap this plan exists to avoid

**This project's recurring defect is the editor promising what the renderer does
not produce.** It has been found and fixed at least six times: `set_duration`
predicting a length both renderers refuse, a tempo ramp reported as applied when
`_apply_beatmatch` was unreachable, `echo_out` never priced, an anchor form
offering a Reference method with no counterpart in the architecture.

A QC stage is the same defect with a lab coat on, if it is built the obvious
way. Ask a vision model "does this clip match the reference?" and it will answer
yes, confidently, nearly always — and now the studio has a green tick that means
nothing, attached to a render nobody looked at. **A measurement that cannot fail
is not evidence.** That rule decides the whole shape below.

So the stage is split into three tiers that are never mixed, and each tier has
to earn the next one.

## Tier 0 — record which box produced each artefact · one column · do this first

`anchors`, `clips`, `refs` and `assets` record no backend. Nothing in the studio
can say which box rendered a given file.

Until that column exists, **"peaches output needs cleaning up" is unfalsifiable**
— you cannot compare two boxes' output if you cannot tell which box made which
file. Every other item here is measurement, and this is the axis the measurement
would be grouped by.

It is also the smallest change on this page: `submit_swarm` already knows the
`exactbackendid` it pinned, and the comfy path is by definition backend 0.

## Tier 1 — deterministic checks, on every artefact · cheap, objective, cannot lie

ffprobe, PIL and numpy. No model, no opinion, ~100ms per artefact. Every one of
these compares the output against **what the workflow asked for**, which the
studio already knows because it wrote the workflow — so each is a real
differential with an expected value, not a vibe.

Video, per clip:

| check | expected | what it catches |
|---|---|---|
| opens, and is over a floor size | — | the 38KB toy that looked like a 827KB clip |
| duration | 4.8125s ± tolerance | a truncated render; a 2.3-vs-2.5 graph mismatch |
| frame count / fps | 81 @ 16.8312 | LTX's 8n+1 rule violated silently |
| resolution | what the workflow requested | a box that quietly downscaled |
| audio and video stream durations agree | — | desync before it reaches the assembly |
| mean luma per frame | above a floor | black frames from a dead sampler |
| consecutive-frame difference | above a floor | a frozen segment |
| channel saturation | within range | NaN/green garbage frames |

Images, per candidate: opens; resolution as requested; not uniform; not blank.

Tier 1 is the only tier allowed to **auto-reject**, and only on the checks where
no judgement exists: unreadable, zero-length, wrong duration, all-black. A
rejection writes a row saying which check failed and keeps the file. Everything
else flags and is still shown.

## Tier 2 — reference compliance, as a NUMBER · needs calibration before it gates anything

Not "ask a VLM". An embedding distance — face or CLIP cosine — between the
chosen anchor and N sampled frames of the artefact. A number can be calibrated,
can be plotted, and can be wrong in a way you can see.

**The calibration set already exists and cost nothing:** the Z-Image sweep in
`zimage_sweep/` renders the same prompt at six step counts across three seeds,
and on seeds …380 and …517 the model draws a woman with bare human legs and a
cat's head at *every* step count, while …654 holds fur head to toe. That is
twelve known-bad images and six known-good ones, same prompt, same anchor, same
day. A compliance metric that cannot separate those two groups is not a metric,
and there is no reason to write the gate before checking that it can.

Order: implement the score, run it over that set, look at the two
distributions. If they overlap, say so and stop — do not ship a threshold that
splits noise.

## Tier 3 — repair · only if tier 2 discriminates

The actuators already exist and none of this needs new models:

- images — `fix_ref.py` already does face swap, inpaint and outpaint
- clips — the `refine` role (`wan22_i2v_low`) is catalogued for exactly this and
  is marked `proven: opportunistic` because **nothing here has measured whether
  it helps**. Measuring that is tier 3's first task, not its assumption.

**A repair produces a NEW candidate. It never overwrites.** The studio's whole
design is candidates plus a human pick; an auto-repair that overwrites destroys
the evidence that anything was wrong and removes the comparison that would show
whether the repair helped.

## Where it runs, and the one thing that blocks it

QC **measurement** runs wherever the studio runs, on the file `collect()` already
brought back. It is not blocked by anything.

QC **repair on a remote box's output** is blocked. If peaches renders and
cerberus refines, the artefact has to move between boxes, and that is the same
shared-filesystem problem as inputs: `UploadImage` returns HTTP 400 and there is
no upload API. Repair routing waits on that work.

Note also that the refiner is a model like any other, so it is subject to
`models.ALIASES` and `models.where()` — a refine pass pinned to a box has to
name the file *that* box uses.

## Order

1. Tier 0. One column. Nothing else is measurable per box without it.
2. Tier 1. Objective, cheap, catches the failures this project has actually had.
3. Tier 2 **calibration only**, against the Z-Image set. Report the two
   distributions. No gate, no threshold, no UI yet.
4. Tier 2 gate, only if 3 separates them.
5. Tier 3, only if 4 exists.

Steps 1 and 2 are worth doing on their own merits and do not depend on the rest.
Steps 4 and 5 are conditional on a measurement that has not been taken, and
writing them before taking it is how the editor starts promising again.
