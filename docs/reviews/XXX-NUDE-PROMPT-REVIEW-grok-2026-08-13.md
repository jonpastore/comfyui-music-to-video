## Findings

### 1. Clauses most likely to force human skin (ranked)

Failure mode that already happened: plain human bare skin. Ranked by how hard each clause pulls toward that under pure positive conditioning (cfg 1.0, no negative pass).

| Rank | Clause / pattern | Why it fails |
|---|---|---|
| 1 | **Every “no / nothing / none” bundle** (“no garments, no underwear…”, “nothing is shaved, bare-skinned or human-toned”, “She has no human skin anywhere: no tan skin, no brown skin…”) — **15 negations** | Pipeline has no NOT. Each negated token is positive evidence. “bare-skinned / human-toned / tan / brown / beige / pale skin” are strong nude-human priors; repeating them floods the sheet with skin. |
| 2 | **“nude” + “She wears nothing at all” + clothing litany** (opening + early body) | “Nude / wears nothing” in training massively co-occurs with human bare skin, not fur. Early position weights it before species exists. |
| 3 | **Nine skin / bare / shaved / human-toned tokens** | Even inside “denials,” the embedding is skin. Measured project rule: saying the forbidden attribute paints it. |
| 4 | **“Anatomically complete… defined labia and vulva… nipples and areolae” without a fur-first anchor in the same breath** | Explicit human-anatomy vocabulary is almost entirely photographed/drawn on bare skin in the prior. At cfg 1.0 the model resolves “visible genitals/nipples” → skin patches unless fur is the dominant, earlier noun. |
| 5 | **“rather than smooth or featureless”** | Introduces “smooth / featureless” as active tokens (often = bare doll skin). |
| 6 | **“exactly as the body description states” / “Combine them… Take her build… none of their clothing”** | Meta + reference-image pull. Recent empty-profile render → plain human woman; refs without a welded fur identity will re-inject bare skin. |
| 7 | **Late species** (“feline” ~char 1813/2519) | Face/species arrives after hundreds of tokens of nude/skin/anatomy. Composition and body material lock first. |

“Black-furred shoulders… calves” list is directionally right but **too late and too weak** next to the skin/negation stack; it does not cancel earlier nude-human conditioning.

---

### 2. Ordering

**Yes — late species matters.**  
Diffusion conditioning is front-heavy in practice: early tokens set identity, material, and body plan; late tokens decorate. With species in the last quarter, the run already committed to “nude adult woman reference sheet.”

**Order to use (positive only):**
1. Species + material identity (anthro feline, jet-black fur continuous head-to-toe)  
2. Body plan / view / framing  
3. Fur coverage restated as material, not as denial  
4. Explicit anatomy **as furred anatomy**  
5. Head/face/tail specifics  
6. Studio / lighting / sheet  

Do not open with “nude” or “wears nothing.”

---

### 3. Self-reference

| Phrase | Verdict |
|---|---|
| “exactly as the body description states” | **Harmful / inert at best** — no separate “body description” channel at cfg 1.0; adds mush tokens, invites ignoring the actual nouns. |
| “rather than smooth or featureless” | **Harmful** — plants the unwanted attributes. |
| “Combine them into one coherent character…” / “All of the reference images…” | **Mostly harmful** here — pulls clothing/skin from refs; “none of their clothing” is another negation. |

Instructing the model *about* the prompt is not reliable control; state the visible facts only.

---

### 4. Contradictions (fur vs explicit anatomy)

They do not average; the model picks.

- **Fur side:** “sleek jet-black fur… only covering… unbroken… entire body… same as face.”  
- **Anatomy side:** “defined labia and vulva… visible anus… nipples and areolae” + nine skin words + “nude.”  

Training prior: those anatomy words ↔ bare human skin. Under contradiction the sheet often resolves to **human body (skin) + maybe feline head** (matches your measured cat-head/human-body failure) or full human nude.

**Fix pattern (positive):** bind anatomy to fur in one clause — e.g. furred breasts with furred nipples/areolae, fur-edged vulva/labia, furred perineum/anus — not “nude” + “no skin.”

Adult intent is fine; the conflict is material (fur vs skin tokens), not the adult content itself.

---

### 5. Rewrite — `front_nude` (fully positive, &lt;1200 chars)

```
FRONT VIEW character reference sheet: one adult anthropomorphic feline woman, fully bipedal cat-person, standing upright facing camera, arms relaxed at sides, feet apart, head-to-toe entire figure in frame, alone.

Continuous sleek jet-black cat fur covers her entire body with no gaps: scalp, face, neck, shoulders, arms, hands, breasts, torso, stomach, hips, glutes, thighs, knees, calves, feet, and long black tail. Same jet-black fur shade and pile everywhere as on her feline face. Fur-only surface head to toe.

Feline head: sleek black cat face, yellow-green almond eyes, pointed feline ears, long wavy black hair with subtle purple highlights, long black cat tail.

Adult female proportions, anatomically complete and explicit: full furred breasts with visible furred nipples and areolae; defined fur-edged labia and vulva between her thighs; visible furred anus; adult pelvis and chest. All anatomy shown through the same jet-black fur and lighting as the rest of her body.

Empty neutral mid-grey studio, wall and floor one unbroken grey flat, soft contact shadow under feet, even white-balanced daylight, crisp focus, high detail, full body clear of frame edges.
```

(~1,050 chars; zero negations; species and fur first; anatomy fur-bound; studio last. Weld your existing “21+ adult proportions” constant at the end as you already do.)

---

### 6. Delete outright

| Delete | Reason |
|---|---|
| All 15+ negations (“no garments…”, “nothing is shaved…”, “no human skin…”, “no tan/brown/beige/pale…”) | Positive pipeline treats them as paint-this. |
| “nude” / “wears nothing at all” / underwear-strap-jewellery litany | Human-bare prior; redundant if fur-only is stated. |
| “bare-skinned”, “human-toned”, “shaved”, every “skin” color list | Direct skin tokens. |
| “exactly as the body description states” | Meta, inert/harmful. |
| “rather than smooth or featureless” | Plants bare/smooth. |
| “Combine them… SAME single character… Take her build… none of their clothing” | Ref-skin/clothing pull + negation. |
| Repeated “black-furred X” laundry list after a global fur sentence | Low value once “entire body continuous jet-black fur” is early; burns front budget. |
| Dual copy-paste of face block after body already said “fur as her face” | Keep one early face/species block. |
| “She has no human skin anywhere” and synonyms | Worst offenders for the measured failure. |

Keep: single figure, full body in frame, adult explicit anatomy, jet-black fur continuity, feline head/tail/eyes/hair, flat mid-grey studio, even light. Re-state fur as the surface on anatomy once, positively.

---

**UNSURE:** exact token-position curves on *your* checkpoint at cfg 1.0 (front-loading is strongly indicated by your own empty-profile human render + late “feline” placement, but not re-measured seed-by-seed here).  
**NOTHING FOUND** on minor/CSAM issues — subject is specified adult; welded 21+ constant is appropriate and should stay.
