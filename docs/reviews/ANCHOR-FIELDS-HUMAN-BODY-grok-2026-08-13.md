# The anchor fields rewritten for a HUMAN body in the character's own black, per tier

Lane: **grok-4.5 vision, xAI API direct** (`api.x.ai/v1/chat/completions`, key from
`~/.config/morpheus/grok-mcp.env`). Four images attached in one call: both uploaded
references and both failed renders. Script and answer kept at
`/tmp/.../scratchpad/{ask_grok.py,grok_brief.md,grok_answer.md}` for this session only;
everything load-bearing is reproduced below.

**The goal changed, and this document is the change.** The old wording fought for
full-body FUR and spent most of its length denying human skin. Jon's instruction:
the body should read as a **human woman's body** — human anatomy, proportions and
surface — in **the character's own jet-black colouring taken from the reference
images**, with the **feline head, ears and tail** kept, and **explicit anatomy
visibly rendered**. Cat head, human body, black surface, explicit.

---

## READ THIS FIRST — the final state, after ~30 renders

This document was written as the work happened and **three of its own conclusions
were overturned by later renders.** The corrections are left in place rather than
edited away, because in each case the wrong conclusion was drawn from a real
observation and the failure mode is the point. But read this section for what is
actually true, and treat §4, §7 and §9b as history.

**Use this configuration** (§10 has the table): **CFG 2.0**, **50 steps**, a
**six-term negative** rather than sixty, **both clothed references kept**, empty
latent, `index_timestep_zero`, dpmpp_2m/karras, LoRA 0.0, 896x1216 — and **not seed
4748**.

**What is solid:**
- CFG 2.0 is the only value with uniform black legs; 3.5+ gives pale legs and a
  third tail. The Anchors form says 4.5 is best; that was measured on the old
  prompt and no longer applies (§8).
- 50 steps, or a six-term negative, each make **nipples render** — the first
  anatomy this project has produced (§9e, §9g).
- `latent: image` + `denoise` is **an inert control** — it returns the reference
  image at every value (§8a). Open defect.
- `ref_method=offset` is an unusable smear (§8c).
- The prompt's nudity wording is **nearly inert**; the negative is the strongest
  text lever, and sixty terms dilute it (§9a, §9g).

**What was overturned, and by what:**
1. §4 said removing `purple or magenta lighting` fixed the olive backdrop.
   **Wrong** — that edit also *added* olive/green/sage negations, and emptying the
   whole negative brings the olive back. The added terms did it (§9a).
2. §9a's earlier draft said the negative looked inert. **Wrong** — it is the
   strongest lever measured (26.09 vs 1.07 for the positive).
3. §9b said the clothed references impose the outfit. **Wrong, and this is the big
   one** — seed 4748 does. Final tally **6 of 6 clothed at seed 4748** (across CFG
   2.0 and 4.5, three wordings, one ref vs two, and an emptied negative) against
   **4 of 4 nude at every other seed**, everything else identical (§9b-CORRECTED).

The third one is worth stating as a rule, because five careful differentials were
run inside it before the control was allowed to return:

> **A fixed seed makes a comparison readable and makes a conclusion local. Pin the
> seed to compare; vary it before you generalise.** `make_anchor` says composition
> here is seed-dominated. Six runs inside one seed's basin agreed with each other
> and were all wrong about the cause.

All three share one shape: **a conclusion drawn from a change that moved two things
at once, or from a single seed.** In the third case I identified the confound myself,
queued the control, and then wrote the conclusion before the control returned.

**Result:** one configuration produces a correct FRONT sheet (`C1`) and a correct
BACK sheet (`BEST_back_s129080599`) — nude, one tail, uniform jet black, grey
backdrop, identity intact, photoreal. Both are in `anchor_sweep_2026-08-13/`.

**Still unsolved:** the vulva has never rendered at any setting. The two-tail defect
IS fixed — by the six-term negative, in `C1`.

**One further trap, recorded because it nearly became a finding:** both close-crop
probes came back as incoherent smears, and "the vulva did not appear" in an image
where nothing appeared correctly is not evidence of anything. **An incoherent output
is not a negative result.** The probe has to produce a readable image before its
absences count.

---

## 1. What was rendered, and what it proves

Four candidates were pulled off the studio and LOOKED AT.

| render | album | profile | result |
|---|---|---|---|
| `back_nude_s129080599` | Street Cats | populated | **the character.** Feline head, ears, yellow eye, tail, uniform black head to toe. Backdrop rendered **olive/sage**, not neutral grey. Feet collapsed into dark blobs. |
| `front_nude_s770589615` | Street Cats | populated | **the character, and no anatomy whatever.** Feline head, ears, yellow eyes, black body, undressed — and smooth, featureless, no nipples and no vulva. Backdrop **olive/sage** again. Visible **haze at the feet**. |
| `front_nude_s323303730` | Catatonic | EMPTY | **a plain human woman.** Brown hair, human skin, no feline feature anywhere, no tail. Crotch smooth and featureless — the explicit clause produced nothing. |

**The same two reference images were attached in both cases** — refs 14/15 on Street
Cats and refs 18/19 on Catatonic are both copies of `front_s4748` / `back_s4748`.
Same references, different text, different species. That is a controlled result and
it settles the question the profile finding opened:

> **The reference images carry almost no species signal. The TEXT carries the identity.**

It also answers job 3 in the day-14 handoff — the Catatonic front sheet no longer
needs running as a controlled test. It ran, and it is a human.

**The day-14 prediction resolves NEGATIVE.** 236 was queued with the prediction
written first: *if the harness or bare patches appear, the profile's fifteen
negations are the cause.* No harness appeared. No bare patches appeared. The body
is uniform black head to toe. The negations did not produce the predicted failure,
and the prediction is recorded as not confirmed rather than quietly dropped.

### Measured on the string, by the repo's own walker

`make_anchor._NEGATION_PATTERNS` run over the composed prompt logged in
`XXX-NUDE-PROMPT-AS-COMPOSED-2026-08-13.txt`:

| | current | after this rewrite |
|---|---|---|
| front_nude length | 2250 chars | **1541 chars** |
| negations in the positive | **11** (`no g`, `no u`, `no s`, `no a`, `no j`, `no h`, `no t`, `no b`, `no b`, `no p`, `no l`) | **0** |
| back_nude negations | 12 (the 11 above plus `not v`) | **0** |
| first `feline` | char **1625** of 2250 | char **50** of 1541 |

The handoff's "15 negations" was measured on a longer string than the composed
prompt alone; by `_NEGATION_PATTERNS` on the composed text it is 11 front / 12 back.
The direction and the conclusion are unchanged — the number is corrected because
this document is where it gets cited from next.

---

## 2. The replacement values, field by field

Every one of these ran through `make_anchor._NEGATION_PATTERNS` (0 hits, all fields)
and through `guardrail.check_text` (all 9 pass, none refused). Paste verbatim.

### `views.front_nude`
```
FRONT VIEW character reference sheet of one adult feline-headed woman with a human body, standing upright facing the camera straight on, arms relaxed at her sides, feet apart, full body head to toe in frame.
```

### `views.back_nude`
```
BACK VIEW character reference sheet of one adult feline-headed woman with a human body, seen from directly behind, back to the camera, standing upright, arms relaxed at her sides, feet apart, full body head to toe in frame, rear view with face hidden.
```

### `nude_wardrobe`
```
Completely naked adult body, fully bare and exposed, jet-black skin uncovered over her whole human form.
```

### `body`
```
Human woman's body with human anatomy, human proportions and human musculature, smooth jet-black skin with a deep near-black sheen matching her face, uniform jet-black colouring across shoulders, arms, breasts, torso, stomach, hips, glutes, thighs, knees, calves, human hands with fingers and human feet with toes.
```

### `anatomy`
```
Explicit adult female anatomy fully detailed and clearly visible: defined labia and vulva between her thighs, visible anus, prominent nipples and areolae on her breasts, all rendered in sharp detail with matching jet-black skin and studio lighting.
```

### `identity`
```
Black feline head, sleek cat face, yellow-green almond eyes, pointed feline ears, long wavy black hair with subtle purple highlights, long black cat tail extending behind her.
```

### `backdrop`
```
Flat neutral mid-grey seamless studio backdrop, even empty grey floor matching the wall, soft contact shadow under her feet, upright unsupported stance in empty studio, even neutral white-balanced studio lighting equal on both sides, clean character reference sheet, sharp focus, high detail, full body inside the frame.
```
`daylight colour temperature` is deliberately gone — see §4.

### `composite`
```
All reference images show the same single character from different angles. Combine into one coherent figure: exactly one woman alone in the frame, standing by herself.
```

### `negative` (album-level, live at CFG 4.5)
```
clothing, outfit, pants, boots, shoes, harness, straps, belts, chains, leather, jewellery, collar, bra, panties, underwear, stockings, gloves, human face, human head, human ears, brown hair, light skin, tan skin, pale skin, beige skin, pink skin, furry torso, fluffy fur, animal body, digitigrade, paws, mismatched skin colour, two-tone body, extra limbs, extra tails, missing tail, deformed hands, duplicate character, cropped head, cropped feet, text, watermark, signature, blurry, low detail, smoke, haze, fog, mist, alley, brick wall, neon lights, vignette, dark corners, scenery, props, overexposed, bad anatomy, featureless crotch, smooth crotch, missing genitals, censored, olive background, green background, sage background, coloured backdrop, warm colour cast
```

Two edits made to grok's list before it was written down here:

- **`Caucasian skin` removed.** It named an ethnicity to steer a colour that
  `light skin, pale skin, beige skin, pink skin` already steers. The character's
  black is a cat's coat, not a human ethnicity, and the prompt should not conflate
  them.
- **`purple or magenta lighting` removed** — see §4. It is the leading suspect for
  the olive backdrop, and leaving it in would make the A/B unreadable.

### `tone_xxx`
```
Explicit adult content is permitted. Full nudity and graphic sexual imagery of consenting adults are in scope. Keep the same adult character identity; every figure remains an adult.
```

### Run settings — unchanged, all of them

quality · CFG 4.5 · ref_method default · latent EMPTY · denoise 1.0 · 896x1216 ·
28 steps · dpmpp_2m · karras · Lightning LoRA 0.0 · 2 candidates · both references
ticked. **Seed: pin it.** The prompt is the lever being moved; nothing else changes.

### The assembled front_nude string, end to end

```
FRONT VIEW character reference sheet of one adult feline-headed woman with a human body, standing upright facing the camera straight on, arms relaxed at her sides, feet apart, full body head to toe in frame. Completely naked adult body, fully bare and exposed, jet-black skin uncovered over her whole human form. Human woman's body with human anatomy, human proportions and human musculature, smooth jet-black skin with a deep near-black sheen matching her face, uniform jet-black colouring across shoulders, arms, breasts, torso, stomach, hips, glutes, thighs, knees, calves, human hands with fingers and human feet with toes. Explicit adult female anatomy fully detailed and clearly visible: defined labia and vulva between her thighs, visible anus, prominent nipples and areolae on her breasts, all rendered in sharp detail with matching jet-black skin and studio lighting. Black feline head, sleek cat face, yellow-green almond eyes, pointed feline ears, long wavy black hair with subtle purple highlights, long black cat tail extending behind her. Flat neutral mid-grey seamless studio backdrop, even empty grey floor matching the wall, soft contact shadow under her feet, upright unsupported stance in empty studio, even neutral white-balanced studio lighting equal on both sides, clean character reference sheet, sharp focus, high detail, full body inside the frame. All reference images show the same single character from different angles. Combine into one coherent figure: exactly one woman alone in the frame, standing by herself.
```

Ordering, and why it is this ordering: conditioning is front-heavy, so
**species + body plan → nudity → surface → explicit anatomy → head/face/tail →
studio**. `feline-headed woman with a human body` is in the first ten words, where
the old string put it at 1625. The string does not open with the word `nude`.

---

## 3. Translating it to every tier

Only three fields vary by tier. The rest are the character and are identical
everywhere — which is the point of keeping them in the album profile rather than
in a per-tier prompt box.

| field | `g` | `pg13` | `r` | `xxx` |
|---|---|---|---|---|
| `identity` | same | same | same | same |
| `body` | same | same | same | same |
| `backdrop` | same | same | same | same |
| `composite` | same | same | same | same |
| `views.*` | clothed pair | clothed pair | both pairs | both pairs |
| `wardrobe` | **must be rewritten — see below** | as `g` | as `g` | dropped on nude views |
| `nude_wardrobe` | unreachable (`allow_nudity` 0) | unreachable | used | used |
| `anatomy` | **empty** | **empty** | soft form | explicit form, as above |
| `tone_<tier>` | the tier's own | the tier's own | the tier's own | as above |

`anatomy` for `r` — nudity in scope, graphic anatomy not the subject:
```
Adult female form fully and naturally rendered, breasts and hips defined, the whole figure lit evenly and drawn with the same detail as her face.
```

`anatomy` for `g` and `pg13`: **leave empty.** The field exists because a nude sheet
came back featureless; a clothed sheet has nothing for it to say, and text that
describes anatomy under a tier that forbids nudity is a tier violation waiting for
someone to tick the wrong box.

### The clothed tiers are now broken and this is the reason

`wardrobe` still reads, three times, in the live stored profile:

> "…the leg openings cut high and narrow so her glutes and the full length of her
> thighs and hips are **uncovered black fur**" … "buckled leather straps fastened
> around one **bare black-furred thigh**"

With `body` changed to jet-black **skin**, every clothed sheet at `g`/`pg13`/`r`
now carries a fur clause beside a skin clause — the exact contradiction the
2026-08-12 CFG sweep measured and found no CFG value could satisfy, only pointing
the other way. **Swap `black fur` → `black skin` and `black-furred` → `black-skinned`
in `wardrobe` in the same edit, or do not make the `body` edit at all.**
`character_base` in `profiles/street_cats.json` carries `sleek black fur` too and
feeds the storyboard path, not the anchor path — same swap, separate blast radius.

---

## 4. The olive backdrop — WITHDRAWN, see §9a for what actually fixed it

Grok attributed it to "residual colour-cast pressure … and model bias". That is not
a mechanism and it is not actionable. **Marked UNVERIFIED.**

The mechanism worth testing: the negative prompt contained **`purple or magenta
lighting`**, and it is live at CFG 4.5. Pushing the latent away from magenta pushes
it toward magenta's complement, which is green. Olive/sage is what anti-magenta on
a neutral grey field looks like. The character's own hair highlights are purple,
which is a second reason that term was always going to cost something.

It is a hypothesis, not a finding. It is falsifiable in one render: the term is
already removed from the negative above, so **if the backdrop comes back grey at
the same seed, that was it.** If it stays olive, the cause is in `backdrop` and the
next suspect is `daylight colour temperature`, which has also been dropped.

Do not record either as fixed until a render says so.

---

## 5. The anatomy clause is not merely weak — it produced nothing, twice

Job 237 (Street Cats `xxx/front_nude`, OLD wording, populated profile) landed while
this was being written and it is the cleanest evidence in the set. The character is
correct. The body is undressed. And there is **no anatomy on it at all** — smooth,
featureless, no nipples, no vulva — with the explicit clause present in the prompt
the whole time.

So the featureless result is NOT explained by "Catatonic's profile was empty". It
happens with the full profile too. Two of two front nude sheets came back
anatomically blank. That is what §2's `anatomy` rewrite has to beat, and it is a
higher bar than "the old clause was a bit vague".

Same render, two more facts:

- **Olive backdrop, 2 for 2** on Street Cats nude sheets. Consistent, not a fluke.
- **Haze at the feet**, with `smoke, haze, fog, mist, atmospheric particles` sitting
  in the negative and live at CFG 4.5. The negative did not remove it. Worth
  knowing before anything else gets attributed to the negative's power.

## 6. The view sentence is NOT an album field — and that is why the first apply fell short

After writing all six profile fields to the live studio (playlist 2), the studio
re-composed and the result was measured:

| | composed from the profile | typed into the per-view box |
|---|---|---|
| front_nude length | 1353 | 1541 |
| negations | 0 | 0 |
| first `feline` | char **863** | char **50** |
| opens with the word `nude` | **yes** | no |
| back_nude negations | **1** (`not v`, from `face not visible`) | 0 |

`views` has no entry in `ALBUM_FIELDS`. The per-view framing sentence comes from
`make_anchor.DEFAULT_VIEWS`, a code constant, so the profile cannot front-load the
species however it is worded — the string still opens `FRONT VIEW nude character
reference sheet of a single adult character`, which is both the word `nude` in the
highest-weight position and the species pushed back to char 863.

The A/B was therefore run with the assembled string **typed into the per-view prompt
box**, which is used verbatim and reaches only the sheet it was typed into. That
gets the wording under test today without a code change touching every album.
**If the A/B wins, the durable fix is a `views` entry in `ALBUM_FIELDS`** — the same
shape as `4032aba` and the same shape as the `nude_wardrobe` gap: the guarded
constant is not what reaches the model.

## 7. THE A/B RAN. The backdrop fix worked and the nudity broke.

Job 238 — Street Cats `xxx/back_nude`, seed 4748, the §2 wording typed into the
per-view box, both references ticked, everything else unchanged from 236.

**Won:** the backdrop is **neutral mid-grey**. The olive is gone, at the same seed,
in the same album, on the same view — the first thing in this project to fix it.

> **§4's mechanism was wrong and is withdrawn — see §9a.** The edit moved two things
> at once (removed `purple or magenta lighting`, added `olive/green/sage background`)
> and I credited the removal. `V1_nonegative` shows the olive returns when the whole
> negative goes, so it is the added olive/green/sage terms doing the work. The fix is
> real; the explanation given here and in §4 was not.

Identity also held: feline head, ears, tail, the purple hair highlights, black body,
correct proportions.

**Lost, and it is the thing that matters:** she came back **fully clothed** — leather
harness, gold-buckled belt, leather shorts, buckled thigh straps, knee-high platform
boots, a studded cuff, a gold earring. The entire album outfit.

**The positive prompt contains no garment word anywhere.** It says "Completely naked
adult body, fully bare and exposed". Every one of those garments —
`harness`, `belts`, `boots`, `leather`, `chains`, `straps`, `clothing` — is sitting
in the negative prompt at CFG 4.5, where the negative is supposed to be live.

So the day-8 rule as applied to this clause is now contradicted by measurement:

| wording | negations | result |
|---|---|---|
| old (`no garments, no underwear, no straps…`) | 11 | **nude**, olive backdrop, no anatomy |
| new (positive only) | 0 | **fully clothed**, grey backdrop |

### …and job 239 immediately narrowed it

Job 239 is the FRONT view of the same wording, same seed 4748, same CFG 4.5, same
references, queued in the same submit. It came back **nude**.

**So "the positive-only wording loses the nudity" is too broad a claim, and I made
it too early.** What is actually observed:

| view | CFG | wording | clothed? |
|---|---|---|---|
| back | 4.5 | positive-only | **CLOTHED** |
| front | 4.5 | positive-only | nude |
| front | 2.0 | positive-only | nude |

The clothed failure has only ever appeared on the **back** view. That is consistent
with M1 and not with M2: the back reference shows the outfit's trousers, belt and
boots filling most of the frame, and it is the back sheet that copied them. The
five variants running on cerberus are all back-view for exactly this reason.

### CORRECTION, and it invalidates the table above: seed was confounded with wording

`V2_oldnudeclause` — back view, CFG 4.5, the old negation sentence restored,
everything else identical — came back **still fully clothed**, the same outfit as
238. So M2 is refuted: the negations are not what was holding the clothes off.

Checking why that contradicted 236 exposed a mistake in my own comparison:

| sheet | wording | view | **seed** | clothed? |
|---|---|---|---|---|
| 236 | old | back | **129080599** | no |
| 238 | new | back | **4748** | **yes** |
| V2 | new + old nude clause | back | **4748** | **yes** |

**Every clothed back sheet is seed 4748 and the one nude back sheet is a different
seed.** I pinned the seed for the new runs and then compared them against an old run
at another seed, which is precisely the comparison `make_anchor` warns against in
its own source: *"composition here is seed-dominated, and comparing two random seeds
tells you nothing about what you changed."*

So the honest position is weaker than §7 claimed: **on seed 4748, back view, both
wordings give a clothed sheet, and there is no seed-matched evidence that the
wording changed anything on the back view at all.** The §7 table stands as a record
of what rendered; it does not support the conclusion I drew from it.

The control is now queued — the same new wording, back view, at seeds 129080599,
4885, 777001 and 20260813, plus seed 4748 at CFG 2.0. If some of those come back
nude the effect is seed variance and the wording is exonerated; if all four are
clothed at 4.5 while 4748 at CFG 2.0 is nude, it is CFG.

### Measured: on the back view at seed 4748, the nudity wording is nearly inert

Three back sheets, same view, same seed, same settings, three different nudity
wordings — `V3_nudefirst` asserts nudity emphatically in the FIRST position. All
three came back clothed, in the same outfit. Mean absolute per-channel difference:

| comparison | diff |
|---|---|
| 238 (positive-only) vs V2 (+ the old negation sentence) | **1.07** |
| 238 vs V3 (emphatic nudity, first position) | **2.50** |
| V2 vs V3 | **2.72** |
| *for scale:* cfg2.0 vs cfg4.5, **prompt identical, CFG alone** | **7.98** |

**Rewriting the nudity clause moves the image less than a third as much as moving
CFG with the prompt untouched.** Adding a whole sentence of explicit negation moved
it by 1.07 — visually nothing. Whatever is putting the outfit on this sheet is not
reading the nudity wording, and no wording tested reaches it.

That is the quantitative form of the day-8 lesson pointed the other way: the rule
was that a negation in the positive *acts* (draws what it denies). Here neither the
negation nor its positive replacement acts at all.

### What 239 also shows, and 238 could not

- **Three tails.** Two at CFG 2.0, three at 3.5 and three here. `extra tails` is in
  the negative throughout.
- **Two-tone legs are back** — below the knee the black fades to pale grey. Present
  at CFG 3.5 and 4.5, **absent at CFG 2.0**, which stayed uniform black head to toe.
  That is the old fur-era defect returning, and CFG 2.0 is so far the only thing
  that suppresses it.
- **No anatomy.** Faint nipples, smooth featureless crotch. Six sheets now.

## 8. The CFG scan, and the studio's own help text is wrong for this prompt

Twelve-point settings scan driven straight at gamingpc, front view, seed 4748,
positive-only wording, everything else held. Five CFG points looked at by eye:

| CFG | nude | two-tone legs | tails | anatomy | style |
|---|---|---|---|---|---|
| **2.0** | yes | **none — uniform black head to toe** | 2 | none | closest to photoreal |
| 3.0 | yes | pale below the knee | 3 | none | glossy |
| 3.5 | yes | pale below the knee | 3 | none | glossier |
| 4.5 (job 239) | yes | pale below the knee | 3 | none | glossy latex |
| 6.0 | yes | **severe — legs pale grey to white** | 3 | none | flat stylised illustration |

Monotonic in the wrong direction on every axis that moves. **CFG 2.0 wins outright.**

The Anchors form tells you the opposite — `4.5 — stronger prompt adherence… Best`,
and the 2026-08-12 sweep is recorded as finding that *every* cfg above 1.0 fixed the
human-skin drift. Both were measured on the OLD prompt, whose eleven negations
included `no lighter skin tone on the legs or body`. That clause was suppressing the
model's own prior toward pale legs, and higher guidance amplified the suppression.
Take the clause out and higher guidance amplifies the prior instead. **The old
measurement was not wrong; it no longer applies, because the string it measured is
gone.** The help text should say so.

Practical consequence: pale legs need to live in the NEGATIVE now. The current
negative has `mismatched skin colour, two-tone body` and neither bit at CFG 6.0 —
which is the fourth independent thing in that list that did not bite.

## 8a. OPEN DEFECT: `latent: image` returns the reference, and `denoise` does nothing

Four points of the sweep used **Sampler starts from = from the first reference**,
the mode the form describes as *"denoise below 1.0 is the point of the control: it
keeps that image's composition and size and redraws the surface."*

Measured, mean absolute per-channel difference against the reference image itself:

| run | vs the REFERENCE |
|---|---|
| `img_dn0.45` | **2.41** |
| `img_dn0.55` | **2.42** |
| `img_dn0.65` | **2.46** |
| `img_dn0.75` | **2.55** |
| `cfg4.5`, empty latent, for scale | **30.33** |

Every value the dropdown offers, 0.45 through 0.75, lands within 0.14 of the same
answer, and that answer is the reference image.

And against each other, `img_dn0.45` vs `img_dn0.65`: mean **0.208**, max 20.
Different md5s, so they genuinely re-rendered — it is not a ComfyUI cache hit.

**The output is the reference image.** All three were checked by eye against
`ref_front.png` and are the same picture: same walking pose, same harness, same
belt, same boots, same tail. Moving the denoise knob across 45% → 65% moves the
result by 0.05 of one channel step.

Two things are wrong at once:

1. **`denoise` is inert in this mode** across the range the dropdown offers. It is
   not "refining" anything; the surface is not redrawn.
2. **The size claim is false too.** The hint says the output inherits the
   reference's size. The reference is 896x1216 and the output is **880x1184**.

### Where it comes from, as far as the tree shows

The wiring is structurally correct. `build_refs.workflow` builds
`LoadImage(7) → FluxKontextImageScale(8) → VAEEncode(15) → KSampler.latent_image`,
and the sampler does carry the requested `denoise`. The 880x1184 is explained too:
`FluxKontextImageScale` rebuckets 896x1216, so the hint's "inherits the reference's
size" was never true of this graph — it inherits the *scaled* size.

**Hypothesis for the inertness, UNVERIFIED:** the same image is used twice — it is
fed to `TextEncodeQwenImageEditPlus` as `image1` *and* VAEEncoded into
`latent_image`. Qwen-Image-Edit exists to reproduce its conditioning image, so
conditioning on the reference while also starting from it reconstructs it whatever
the denoise. The test is one render: VAEEncode the reference while conditioning on a
different image, or on none. Nothing in the tree does that today.

This is the most promising lever for "make it look like the reference" and it is
not connected to anything. Everything the form says about it is unverified. It
needs a criterion of its own; it should not be recommended to anyone until one
exists, and the four `img_dn*` runs in this sweep carry no information about
prompt or CFG because the prompt never got a chance to act.

## 8c. `ref_method` is live — and `offset` is unusable

Unlike `denoise`, the reference-adherence knob does something large:

| run | vs the default (`index_timestep_zero`) | vs the reference |
|---|---|---|
| `refm_offset` | **36.25** | 16.49 |

**But it is much closer to the reference for the wrong reason.** Looked at:
`refm_offset` is a murky, blurred, underexposed smear — no detail, no contrast, the
figure barely readable. It scores "close to the reference" because a dark blur
averages toward a dark image.

Two consequences, and the second matters more than the first:

1. `offset` is not a candidate. The default `index_timestep_zero` is right, and the
   form's note that `uxo/uno` is "the same as offset on this model" now also means
   "the same as unusable".
2. **Mean-absolute-difference-to-the-reference is NOT a quality score, and must not
   be used as one.** It rewarded the worst image in the sweep. It is trustworthy
   only for what it was used for in §8a — detecting that a control is INERT, where
   a near-zero distance means something specific. Every quality ordering in this
   document is by eye, and this is the second automated scorer in it that would
   have ranked wrongly.

## 8b. The studio's QC vision lane cannot grade these sheets, and that is a finding

Jon asked for the QC framework and model to compare the uploaded reference against
the output. Built on the studio's own lane — `studio/vision.py`, which resolves to
**`qwen3-vl` via the litellm gateway** (free, local). Eleven narrow visible yes/no
criteria plus a side-by-side identity call, the composite score computed here from
the booleans rather than asked for.

**It was validated against three sheets whose ground truth was established by eye
first, and it failed the criterion that matters.**

What it gets right: `nude` (it correctly caught job 238 as clothed), `feline_head`
and `black_body` (it correctly failed the plain-human Catatonic render on both, and
scored its identity match 0).

What it gets wrong: **`anatomy`.** It passed the Catatonic human render as
anatomically explicit — that sheet is smooth and featureless. It then passed
`cfg3.0` with **no fails at all and a score of 91.4**, ranking it above `cfg2.0` at
76.2. Looked at directly, `cfg3.0` has a smooth featureless crotch, **three tails**
and **pale lower legs**, and `cfg2.0` has none of those.

So the ranking is inverted on exactly the axis being tuned. Per CLAUDE.md — this
fleet fabricates, and confidence is uncorrelated with correctness in both
directions — the `anatomy` verdict carries no information and is reported but never
ranked on. **The ordering in this document is by eye.** The scorer is kept for
`nude`/`feline_head`/`black_body` triage across a large batch, which is real work it
does reliably, and for nothing else.

## 9. The differential now running

Two mechanisms explain a clothed sheet from a prompt with no garment word, and they
need different fixes:

- **M1 — the clothed REFERENCE images impose the outfit.** Qwen-Image-Edit conditions
  on them; the old negations were fighting the *reference*, not a text clause. Fix is
  `ref_method` / CFG / a nude reference.
- **M2 — the old negations were the only thing asserting nudity**, and the positive
  wording is too weak. Fix is in the text.

Held fixed: view (`back_nude`), seed 4748, CFG 4.5, quality, empty latent, dpmpp_2m,
karras. One thing moves per run.

| run | what moves | nude ⇒ | clothed ⇒ |
|---|---|---|---|
| `V5_norefs` | **no reference images at all** | M1: the references impose it | M2: the text is too weak |
| `V6_backrefonly` | one reference, the back sheet | the front reference's hardware is the source | not the count of references |
| `V2_oldnudeclause` | the old negation sentence restored | M2 confirmed, the negations work here | the negations were never the cause |
| `V3_nudefirst` | emphatic positive-only nudity, asserted first | position/strength fixes it without negations | positive-only cannot assert nudity here |
| `V1_nonegative` | the negative emptied | the negative was *hurting* | — |

`V1_nonegative` is the cheap diagnostic the rest depends on. `boots`, `harness`,
`belts`, `chains` and `leather` are all in the negative and all rendered; `smoke,
haze, fog, mist` is in it and job 237 rendered haze. If the sheet is
indistinguishable with the negative emptied, **the negative is inert on this path**
and every conclusion drawn from it — including this document's own negative edits —
is unfounded.

Running in parallel with a 12-point settings scan on gamingpc (CFG 2.0→6.0, latent
from-reference at denoise 0.45→0.75, `ref_method` offset/index, 50 steps), driven
straight at the ComfyUI backends: the studio's worker is single-threaded on purpose
("single worker is the whole concurrency policy — do not add a second"), so the
sweep does not go through the studio. cerberus and gamingpc both hold
`qwen_image_edit_2511_fp8mixed`; peaches does not and ethan is down.

## 9a. CORRECTION: the negative is the strongest text lever here, and §4's mechanism was wrong

Two claims made earlier in this document are now falsified by `V1_nonegative` — the
same back sheet, same seed, same settings, with **the negative prompt emptied**.

**Wrong claim 1: "the negative prompt appears diluted or inert."** It is not. It is
the most powerful text input in this configuration:

| change | mean abs diff |
|---|---|
| empty the whole negative | **26.09** |
| add a whole explicit sentence to the positive (`V2`) | **1.07** |

Removing the negative moves the image twenty-four times as much as rewriting the
positive. The reasoning behind the "inert" claim — that `boots`, `harness`,
`leather`, `extra tails`, `smoke` are all in it and all render anyway — was a real
observation with the wrong conclusion drawn from it. The negative is potent; it is
simply **not potent enough to overcome reference-imposed structure** (§9b). Against
global colour and style attributes it works well. Against an outfit that the
reference image is supplying, it does not.

**Wrong claim 2, and §4's "CONFIRMED" is withdrawn.** `V1` came back with the
**olive/sage backdrop**. The figure is unchanged; almost the entire 26.09 is the
background colour. So the olive is the model's own prior for this scene, and the
negative is what suppresses it.

§4 credited the grey backdrop to *removing* `purple or magenta lighting`, on an
anti-magenta-pushes-to-green mechanism. **That edit was confounded**: in the same
change I also *added* `olive background, green background, sage background,
coloured backdrop, warm colour cast`. Two changes, one observation, and I attributed
it to the wrong one. `V1` separates them — with the whole negative gone the olive
returns, which the anti-magenta story does not predict.

Corrected: **the backdrop is grey because the negative now names olive, green and
sage explicitly.** Keep those terms. Whether `purple or magenta lighting` was
harmful remains untested and is no longer claimed either way.

That is the second time in this document a mechanism was asserted from a
single-observation change that moved two things at once. It is the same failure the
day-14 handoff names as dominant here.

## 9b-CORRECTED. READ THIS BEFORE §9b. The seed decides, not the references.

**§9b below is overstated and its headline is withdrawn.** The seed control returned
after it was written and reverses the conclusion.

`S129080599_cfg4.5` — the new wording, **both clothed references still attached**,
CFG 4.5, back view, everything identical to job 238 **except the seed** — came back
**fully nude**. It is also the best back sheet in the session: correct back view,
uniform jet black head to toe, **one tail**, neutral grey backdrop, human body,
human hands and feet, photoreal, identity intact.

| back view, CFG 4.5, new wording | refs | seed | clothed? |
|---|---|---|---|
| job 238 | 2 clothed | 4748 | yes |
| `V2` / `V3` / `V1` / `V6` | 2 or 1 clothed | 4748 | yes |
| `V5_norefs` | **0** | 4748 | no |
| **`S129080599`** | **2 clothed** | **129080599** | **NO — nude** |
| **`S4885`** | **2 clothed** | **4885** | **NO — nude** |
| **`S777001`** | **2 clothed** | **777001** | **NO — nude** (but heels, and soft focus) |
| **`S20260813`** | **2 clothed** | **20260813** | **NO — nude** (heels; hair missing) |

| `S4748_cfg2.0` | 2 clothed | **4748**, at **CFG 2.0** | **yes — still clothed** |

**Final tally: 6 of 6 clothed at seed 4748, 4 of 4 nude at every other seed tried**,
with the references, the wording and every sampler value held identical.

Seed 4748's back view is a **clothed attractor**, and it survived everything thrown
at it: CFG 2.0 and CFG 4.5, three different nudity wordings, one reference instead of
two, and the negative emptied. The only thing that escaped it was removing every
reference — and changing the seed, which costs nothing at all.

That is the whole lesson of this session in one line: **five careful differentials
were run inside a single seed's basin, and none of them could have found the answer,
because the variable that mattered was the one being held fixed.**

So the correct statement is much narrower:

> **Seed 4748 produces a clothed back sheet, and no wording change tested moves it.
> A different seed, with the same references and the same words, is nude.**

Three of three alternative seeds are nude, at CFG 4.5, with both clothed references
attached and the identical prompt. Seed 4748 is the outlier, and five runs
(238, `V1`, `V2`, `V3`, `V6`) were all measuring that one seed.

The references still leak: `S777001` and `S20260813` both rendered **heels**, so
footwear survives at other seeds even when the rest of the outfit does not — two of
four. The influence is real and partial. What is withdrawn is that it is decisive.

This also means **`chosen` being 0 on every anchor is now a live cost, not just a
loose end.** Seed selection is the difference between a clothed back sheet and a
correct one, and nothing in this studio has ever picked a sheet and kept its seed.

The references raise the probability of the outfit; they do not determine it.
`V5_norefs` flipping at seed 4748 is still a real observation — removing every
reference escapes that seed's attractor — but so does simply changing the seed, at
no cost to identity, colour or style.

**This is the same mistake twice in one document.** §7 was written before the seed
control existed; I identified the confound myself, queued the control — and then
wrote §9b's conclusion from the pre-control evidence anyway instead of waiting.
`make_anchor`'s own comment says composition here is seed-dominated. It is.

Everything below in §9b about *what happens at seed 4748* stands as recorded. The
generalisation to "the reference dictates wardrobe" does not. §9c's framing claim and
§9b's view claim inherit the same doubt and need the same seed control before they
are trusted — neither has had one.

## 9b. What happens at seed 4748 (conclusion withdrawn — see §9b-CORRECTED)

`V5_norefs` — the identical prompt that came back clothed three times, with **the
reference images removed and nothing else changed** — came back **NUDE**.

That closes it. No wording reaches the outfit because the outfit is not coming from
words. It is coming from the clothed reference images, which are attached to
every sheet.

The full series, back view, seed 4748, CFG 4.5, everything else held:

| run | what was attached / changed | clothed? |
|---|---|---|
| 238 | 2 clothed refs, positive-only nudity | yes |
| `V2` | + the old negation sentence | yes |
| `V3` | + emphatic nudity in first position | yes |
| `V1` | negative emptied | yes (and the olive backdrop returned) |
| `V6` | **1** clothed ref (back only) | yes |
| `V5` | **0** refs | **NO — nude** |

`V6` is the one that makes it a dose-response rather than a coincidence: dropping
from two clothed references to one changes the image by 7.82 and changes nothing
that matters. **One clothed reference is sufficient to impose the whole outfit.**

**And the trade-off is now visible, which matters as much as the answer.** Without
references the sheet loses everything the references were carrying:

| | with the 2 clothed refs | with no refs |
|---|---|---|
| nude | **no** | **yes** |
| body colour | jet black | **mid grey/charcoal** |
| style | photoreal | **flat cartoon** |
| identity | the character — purple highlights, correct face | a generic anthro cat |
| render time | 277–392s | **77s** |

The references are doing two jobs at once — identity, colour and photoreal style on
one hand, the outfit on the other — and with the current wiring you cannot take one
without the other.

### The fix that follows, and it is already a studio feature

**Use a NUDE sheet as the reference.** `cfg2.0` is nude, on-model, uniform black,
human-bodied and photoreal. Feed it back in as the reference and the deadlock
breaks: identity comes from the reference as before, and there is no outfit for it
to impose.

The studio already supports exactly this — **"Use as reference"** on a picked
candidate, which the Anchors form's own hint describes. It has never been used for
this, and `chosen` is 0 on every anchor, so no sheet has ever been picked to become
one.

### Result: it works for the clothing, and exposes that the reference also fixes the VIEW

`NR_back_cfg2.0` — `cfg2.0` (nude, on-model) as the single reference, back view
requested, CFG 2.0.

- **No clothing at all.** The fix works: a nude reference imposes nudity the same
  way a clothed one imposed the outfit.
- **Identity preserved** — purple highlights, yellow-green eyes, feline face, black
  body. The thing `V5_norefs` lost by dropping references is kept.
- **But it rendered a FRONT view.** A back view was asked for; the reference is a
  front sheet, and the reference won. Same failure as `A1`'s ignored crop.
- Heavy **artefacts**: black speckle across the backdrop, blocky corruption over the
  body. This render is degraded and would not ship.
- Two tails. Nipples faint, no vulva.

So the generalisation in §9c extends once more, and this is the load-bearing
sentence of the whole session:

> **The reference image dictates wardrobe, framing AND camera view. The prompt
> cannot override any of the three. Whatever you want the sheet to be, the
> reference has to already be it.**

Practical consequence, and it splits by view:

- **Front nude sheets are already solved** — `A4_steps50` is nude, on-model and the
  best sheet of the session, using the existing clothed references. The front view
  never had the clothing problem (§7).
- **Back nude sheets need a nude BACK reference.** The clothed refs force the
  outfit; a nude FRONT reference forces the front view; no references costs the
  identity, the black and the photoreal style. None of the three available options
  produces a correct back nude sheet today.

The way out of that is a bootstrap, and it is the concrete next step: render a back
nude with **no references** to get the pose (accepting the weak identity), then use
that as the reference for a second pass to restore the identity. Two passes, and
each one is a mode already measured here. **Not attempted — no render backs this.**

## 9c. The framing claim — SAME CONFOUND, not yet controlled

> **Caveat added after §9b-CORRECTED.** Everything below was measured at seed 4748
> only, exactly like the withdrawn wardrobe claim. It has NOT had a seed control.
> Read it as "at this seed the framing directive did not act", not as a property of
> references in general. The same applies to `NR_back_cfg2.0` rendering a front view
> in §9b. Both need the control that the wardrobe claim got.

`A1_hipcrop_1024` asked, at 1024x1024, for a *"WAIST AND HIPS DETAIL SHEET… cropped
from mid-thigh to just above the navel, filling the frame"*. It rendered a **full
body figure**, head to toe, with the anatomy as absent as ever. A thin gold chain
necklace also appeared — from the reference, like the outfit.

So the framing directive did not act, for the same reason the nudity wording did not
act: the two references are full-body sheets, and §9b established that they dominate.
Generalised, and now supported on three separate attributes:

> **With the clothed full-body references attached, the text does not control
> wardrobe, framing, or accessories. It controls what is left.**

The consequence for the open problem: **H-RES has not actually been tested.** The
resolution hypothesis needs a close crop, and no close crop can be produced while
the references are imposing full-body composition. Queued: the same close-crop
wording with **no references at all**, at 1024x1024 — hips-only, and a half-body —
so the text is the only thing describing the frame.

## 9d. H-POS refuted — and front-loading demonstrated in the other direction

`A2_anatomy_first`: the explicit-anatomy clause moved from position 4 to position 1,
CFG 2.0, everything else as `cfg2.0`. Diff from that baseline: 5.87.

- **Anatomy: still absent.** Position is not why it does not render.
- **The legs went severely two-tone** — white from the knee down, notably worse than
  `cfg2.0`, which was uniform black.

The second half is the useful part. Promoting `anatomy` demoted `body` from third to
fourth, and the leg colour degraded immediately. That is the front-heavy
conditioning principle demonstrated by damage rather than by benefit: **the `body`
clause's position is load-bearing for uniform colour, and anything promoted above it
costs leg tone.**

So the ordering in §2 is not arbitrary and should not be reshuffled to chase the
anatomy. Whatever fixes the anatomy has to come from somewhere other than the
prompt's word order.

## 9e. BEST SHEET SO FAR: CFG 2.0 at 50 steps — and the first anatomy of the session

`A4_steps50` — CFG 2.0, **50 steps**, otherwise identical to `cfg2.0`. Diff 9.89.

| | `cfg2.0` (28 steps) | `A4_steps50` (50 steps) |
|---|---|---|
| nude | yes | yes |
| leg colour | uniform black | **uniform black** |
| **nipples / areolae** | absent | **rendered and defined** |
| vulva | absent | absent |
| tails | 2 | 2 |
| backdrop | grey | grey |
| quality | good | **best of the session** — photoreal, correct musculature, correct skin sheen, hands and feet well formed |
| identity | correct | correct — purple highlights, yellow-green eyes |

**This is the first anatomy that has rendered anywhere in this project.** Nine sheets
came back completely blank; this one has breasts drawn properly and only the vulva
missing.

That is the single most useful fact in the sweep, because it converts the anatomy
problem from "the model refuses" into "the model draws what it can resolve":

> Nipples at 896x1216 full-body framing are perhaps 15 px across and they rendered
> at 50 steps. The vulva at the same framing is smaller and shadowed between the
> thighs, and it did not. **That is H-RES, and it now has supporting evidence rather
> than being a guess.**

**Current best configuration: CFG 2.0, 50 steps, quality, empty latent, denoise 1.0,
896x1216, dpmpp_2m/karras, Lightning LoRA 0.0, ref_method default.** 185s a sheet on
gamingpc.

## 9f. The extra tail resists both levers

`A5_one_tail` replaced the identity clause's `long black cat tail extending behind
her` with `one single long black cat tail behind her` — an explicit positive
singular. **Two tails rendered anyway.**

`extra tails` has been in the negative for every run in this session. So the defect
survives both a positive singular assertion and a negative term. It is also not
reference-imposed: the reference sheets have exactly one tail.

Consistently 2 tails at CFG 2.0 and 3 at CFG 3.5–6.0, on symmetric front views. The
working guess — untested — is that a symmetrical standing front pose gives the model
no cue for which side the tail belongs on and it renders both. A pose with a turned
hip, or a back view where the tail root is visible, would test that. Nothing here
does.

## 9g. The 60-term negative WAS diluting — six terms beat sixty

`A6_short_negative` — the negative cut from ~60 terms to **six**
(`clothing, boots, harness, extra tails, smooth featureless crotch, haze`), CFG 2.0,
**28** steps, everything else as `cfg2.0`. Diff from that baseline: 17.67.

- **Nipples and areolae clearly rendered** — matching `A4_steps50`'s result at
  **half the step count**.
- Uniform jet black head to toe, grey backdrop, nude, human hands and feet.
- **The best surface in the session** — it reads as skin with visible texture rather
  than the glossy latex sheen every other run produced.
- Two tails. Vulva still absent.

This resolves the tension in §9a properly. The negative is not inert — `V1` proved
it is the strongest text lever at 26.09. But **sixty terms spread that strength too
thin.** Cutting it to six concentrated it, and the gain showed up exactly where the
long list had been failing: on the anatomy and on the surface.

Both halves of the earlier confusion were half-right, and the synthesis is:

> The negative prompt is powerful and easily diluted. It cannot beat
> reference-imposed structure at any length (§9b), and at sixty terms it was not
> winning the things it *could* win either.

**Two independent routes to rendered nipples have now been found — 50 steps, and a
six-term negative — and nothing has tested them together.** Queued as
`C1_cfg2_50steps_shortneg`, with `C2_hips_noref_50steps` alongside it: grok's
cheapest-settling crop test, run at the step count that is now known to matter.

## 9h. Grok round 2 — seven renders, their settings and the reference

Lane: **grok-4.5 vision, xAI API direct**, one call, seven renders each labelled with
the exact settings that produced it, plus the uploaded reference and the full
positive and negative. The brief was rewritten first to carry the CORRECTED findings,
including the two claims this document retracts — feeding it my own withdrawn
conclusions would have bought a confident answer to the wrong question.

**Its ranking matched mine, arrived at independently:** `A4_steps50` first, `cfg2.0`
second, `cfg6.0` last, `after_back_s4748` marked down purely for being clothed.

**Where it agrees, and adds something:**
- Anatomy is a **resolution/framing** problem. Its reasoning is the same as §9e's:
  nipples rendering while the vulva does not, on a target a few dozen shadowed
  pixels wide, is what a resolution limit looks like — and the nipples prove the
  model is not refusing.
- Cheapest settling test: no references, CFG 2.0, tight waist-to-mid-thigh crop,
  768x768 or 1024x1024. Queued as `C2` at 1024x1024 and 50 steps.
- Keep the olive/green/sage block. Do not use `latent: image` or `ref_method=offset`.
- On the back nude sheet it reaches §9b's conclusion independently: no setting in
  the tested list unlocks nude + back + full identity at once, and the way through
  is the two-pass bootstrap.

**Where it is wrong, and I am not taking the advice.** Its "exact next
configuration" specifies **zero reference images** for the FRONT sheet, on the
grounds that refs are "required for nudity". That over-generalises §9b from the back
view to the front. The front view never had the clothing problem (§7), and
`A4_steps50` — the sheet grok itself ranked first — is nude **with both clothed
references attached**. Dropping them would import `V5_norefs`'s losses (grey instead
of black, cartoon instead of photoreal, generic face) to fix a problem the front
view does not have. `C1` therefore keeps both references.

Its proposed prompt also reorders identity ahead of body. Untested, and §9d showed
demoting `body` costs leg tone, so it is not being adopted blind either.

Full answer: `docs/reviews/XXX-NUDE-SWEEP-REVIEW-grok-2026-08-13.md`.

## 10. WHERE THIS LEAVES YOU — the configuration to use

Ordered by eye across ~30 renders. Not by the vision scorer (§8b) and not by
distance-to-reference (§8c); both would have ranked wrongly.

### Best configuration measured

| setting | value | why |
|---|---|---|
| mode | quality | — |
| **CFG** | **2.0** | §8 — the only value with uniform black legs; 3.5+ gives pale legs and a third tail |
| **steps** | **50** | §9e — nipples render at 50 and not at 28 |
| **negative** | **six terms**, not sixty | §9g — nipples render, and the best surface in the session |
| references | **both clothed sheets, attached** | §9b-CORRECTED — they carry identity, black and photoreal; dropping them costs all three |
| **seed** | **not 4748** | §9b-CORRECTED — 4748 clothes the back view and no wording moves it; 129080599 and 4885 are nude with everything else identical |
| latent | empty, denoise 1.0 | §8a — `latent: image` is broken |
| ref_method | default `index_timestep_zero` | §8c — `offset` is an unusable smear |
| sampler / scheduler | dpmpp_2m / karras | unchanged |
| Lightning LoRA | 0.0 | unchanged |
| size | 896x1216 | but see the anatomy note |

The six-term negative:
```
clothing, boots, harness, extra tails, smooth featureless crotch, haze
```

### THE SHEET: `C1_cfg2_50steps_shortneg`

CFG 2.0 + 50 steps + the six-term negative + both clothed references, all together
for the first time. **The best sheet of the session by a clear margin.**

- Nude. **ONE tail** — the first single-tailed front sheet in the whole project.
- Uniform jet black head to toe, no two-tone anywhere.
- **Nipples and areolae rendered.**
- Neutral grey backdrop, correct front view, whole body in frame.
- Human hands with claws, human feet with toes, correct musculature.
- Photoreal skin surface, not the latex sheen of the CFG 3.5+ runs.
- Identity correct: feline face, purple hair highlights, yellow-green eyes.
- **Vulva still absent.** The only remaining defect.

**The tail fix is the informative part.** `extra tails` sat in the sixty-term
negative through every two- and three-tailed render in this session. In a six-term
negative it works. That is §9g's dilution finding confirmed on a second, independent
defect — and it is the strongest practical argument for keeping the negative short.

### AND THE MATCHING BACK SHEET: `BEST_back_s129080599`

The same configuration — CFG 2.0, 50 steps, six-term negative, both clothed
references — at **seed 129080599** instead of 4748.

- Nude. **One tail.** Uniform jet black head to toe.
- Correct **back view**, grey backdrop, whole body in frame, photoreal.
- **Identity fully intact**, including the long wavy hair with purple highlights that
  the CFG 4.5 version of this seed had lost.
- Minor leak: a gold hoop earring, from the reference.
- Vulva not applicable on a back view; anus not rendered.

`BEST_front_s129080599` completes the pair, and is the best front sheet of the
session: one tail, nipples rendered, uniform jet black, human feet with toes, and
the strongest purple hair highlights of any render here — better identity than `C1`,
which used the same settings at seed 4748.

**So one configuration and one seed produce a matched front and back pair.** The back
does not need a nude reference, a bootstrap, or dropped references — all of which
§9b proposed on the strength of seed 4748. It needs a different seed.

**THE DELIVERABLE:**
```
anchor_sweep_2026-08-13/01a_BEST_FRONT_cfg2.0_50steps_shortneg_s129080599.png
anchor_sweep_2026-08-13/01b_BEST_BACK_cfg2.0_50steps_shortneg_s129080599.png
```
CFG 2.0 · 50 steps · dpmpp_2m/karras · LoRA 0.0 · empty latent · denoise 1.0 ·
896x1216 · `index_timestep_zero` · both clothed refs · **seed 129080599** ·
negative `clothing, boots, harness, extra tails, smooth featureless crotch, haze`

Copies of every sheet named in this document:
`anchor_sweep_2026-08-13/` (gitignored, same as `anchor_v2/`).

### Best sheets produced

- **Front:** `A4_steps50` (CFG 2.0 / 50 steps) and `A6_short_negative` (CFG 2.0 / 28
  steps / six-term negative). Both nude, uniform black, correct identity, nipples
  rendered. `A6` has the better surface.
- **Back:** `S129080599_cfg4.5` — nude, correct back view, uniform black, **one
  tail**, grey backdrop, human feet, photoreal, identity intact. The best back sheet
  of the session, and it came from changing nothing but the seed.

`C1` (CFG 2.0 + 50 steps + six-term negative together) and `BEST_*` (that
combination at seed 129080599, front and back) are queued. Neither had returned when
this was written.

### The anatomy tests, and what they did and did not settle

| run | refs | steps | crop honoured? | anatomy |
|---|---|---|---|---|
| `A1_hipcrop_1024` | 2 clothed | 28 | **no — rendered full body** | none |
| `H1_noref_hips_1024` | **0** | 28 | yes | **incoherent** — smeared, mirrored, doubled forms |
| `H2_noref_torso_1024` | **0** | 28 | yes | **nipples rendered**; frame cut above the crotch |
| `C2_hips_noref_50steps` | **0** | **50** | yes | **incoherent** — distorted, doubled figure, cat face on a torso, duplicated limbs |

**Settled:** a crop instruction is honoured with no references attached and ignored
with them (`A1` vs `H1`/`H2`). That is the framing half of §9c, and unlike the
wardrobe claim it is a positive result rather than an inference from one seed.

**Not settled, and the probe is the reason.** Both tight hips crops — 28 steps and
50 steps, no references — came back **incoherent**: doubled and mirrored forms, a cat
face grafted onto a torso, duplicated limbs. Neither produced a vulva and neither
produced a usable image of any kind.

**So the test failed, rather than returning an answer.** The close-crop probe that
grok and §9e both nominated as the cheapest way to settle H-RES is not a valid
instrument on this pipeline: asked for a tight anatomical crop with no reference to
anchor composition, the model loses coherence entirely. H-RES is therefore
**untested**, not refuted — and this document should not record it as either.

That is worth naming as its own trap, because it nearly went in as a finding: **an
incoherent output is not a negative result.** "The vulva did not appear in `C2`" is
true and means nothing, because nothing else in `C2` appeared correctly either. A
probe has to produce a readable image before its absences count as evidence.

What a valid test would need: composition anchored (a reference that is itself a
close crop — which does not exist yet), or the region reached on a coherent
full-body sheet by an inpaint pass rather than a re-render. Neither was attempted.

**What can be said:** nipples render under at least four configurations now, so the
model is not refusing adult anatomy outright. The vulva has never rendered under
any, at any framing tried.

### Still unsolved

1. **The vulva has never rendered**, at any setting — the one remaining defect.
   Nipples do, under four configurations, so the model is not refusing (§9e).
   The resolution hypothesis could not be tested: both close-crop probes returned
   incoherent images. Next probes are an inpaint pass on a coherent sheet, or a
   different checkpoint.

**Solved during the session, listed here because earlier sections say otherwise:**

- **Two tails: FIXED** in `C1`, by the six-term negative. §9f recorded it as
  resistant to both levers, which was true of the sixty-term negative and of the
  positive singular — and false once the negative was shortened.

## 10b. THE CONTRAST HYPOTHESIS — Jon's, and it beats mine

Jon, looking at the finished pair: *"I'm looking for the back to have the tail and
more of the anatomy details. Labia, lighter skin and sphincter."*

The **lighter skin** half of that is the best explanation this project has produced
for the missing anatomy, and it displaces the resolution theory:

> The character is jet black. The vulva sits in shadow between two jet-black thighs.
> **There is no tonal information available to render it with.** The nipples, by
> contrast, sit on a lit convex surface where a luminance break already exists — and
> they render fine, under four separate configurations.

That fits every observation in this document better than H-RES does, and unlike
H-RES it is testable without a close crop — which §10's probe table shows this
pipeline cannot produce coherently anyway.

It is also anatomically truthful rather than a trick: a dark-coated animal's genital
and anal skin is lighter than its coat.

The tail is the second half and the two are connected. On
`01b_BEST_BACK_...s129080599` the tail hangs **straight down over the glutes**,
occluding exactly the region in question. Jon: *"that's why the tail should be up
like a cat with it up in the air to the side."*

### What grok returned, and the two changes made to it

Round 3 brief: `docs/reviews/XXX-BACK-ANATOMY-grok-2026-08-13.md`. It endorsed the
contrast hypothesis as the primary lever, gave a tail-raised pose set, and advised
holding every sampler value fixed so the wording is isolated. Three pose variants
adopted as written (A: hip cocked, tail high left; B: feet wide, tail swept right;
C: contrapposto, glance over shoulder, tail looped high).

**Changed — the tone.** Grok specified `dusty-rose`, `soft pink`, `coral`,
`mauve-pink`. **Jon's instruction is "20% lighter skin".** Rose and coral would fight
the black-cat design and risk reading as human flesh, which is the failure mode this
whole rewrite exists to avoid. The three variants use *"a charcoal tone about twenty
percent lighter than the surrounding jet-black skin"*.

**Kept, as a control only.** Twenty percent lighter than jet black is still very
dark, and it may not clear the luminance threshold at all — in which case the
hypothesis would look refuted when the wording was simply too subtle. So one variant
(`T4_poseA_PINKctl`) keeps grok's rose tone on the same pose and seed. If the pink
reads and the 20% does not, that **locates the threshold** rather than guessing at
it, and the next pass can walk the tone in from there.

Four renders, seed 129080599, CFG 2.0, 50 steps, both references, an eight-term
negative that adds `tail between legs` and `merged thighs`. All four pass
`make_anchor._NEGATION_PATTERNS` with zero hits. **Not yet returned.**

## 11. What is not established, and what was left undone

**Open questions**

- **Why the vulva never renders.** Still open, and the resolution hypothesis is
  **untested** rather than refuted — both close-crop probes returned incoherent
  images, so their absences carry no information. Nipples render under four
  configurations, so it is not a blanket refusal. The next probes are an inpaint pass
  on a coherent sheet, or a different checkpoint. Neither was attempted.
- **The framing and view claims in §9b/§9c have not had a seed control**, and the one
  claim in this document that did get one was reversed by it. Treat both as local to
  seed 4748 until controlled.
- **`latent: image` / `denoise`** (§8a) — measured inert, root cause narrowed to the
  reference being used as both conditioning and init latent, but the fix is untested.
  It needs a criterion of its own.
- **Whether the six-term negative costs anything** the sixty-term one was buying.
  It fixed the tail and the surface; nothing checked what it stopped suppressing.

**Not done, deliberately**

- **The album profile still holds the §2 wording, which is not the wording that
  produced the best sheets.** `C1`'s prompt was typed into the per-view box, and the
  six-term negative was passed per-render. Neither is stored. **Nothing in the studio
  will reproduce `C1` today** — that is the first thing to fix, and it needs the
  `views` gap in §6 closed as well.
- **No sheet has been picked.** `chosen` is still 0 on every anchor, so the seed that
  matters (§9b-CORRECTED) is not recorded anywhere.
- `wardrobe` still contains three negations of its own (`Not shorts, not boy shorts,
  not a full-coverage brief`). Clothed-tier only, outside this change, and rewriting
  cut instructions would change the outfit. Written down rather than touched.
- The clothed tiers still need the §3 check: `body` is now skin and `wardrobe` was
  swapped to match, but no clothed sheet has been rendered since to confirm it.
- Nothing here has been committed.
