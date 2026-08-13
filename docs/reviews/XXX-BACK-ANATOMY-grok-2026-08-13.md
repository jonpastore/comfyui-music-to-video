**Verdict on the contrast hypothesis:** Plausible and worth testing first. Nipples sit on a lit, curved surface with a natural highlight/shadow break; a jet-black vulva between jet-black thighs in the medial shadow has almost no luminance edge for the model to latch onto. Specifying lighter/pink-toned genital and anal skin is anatomically reasonable for a dark-furred/feline character and gives the sampler actual tonal information. Resolution probes were inconclusive, so treat contrast as the primary lever.

**Settings alongside it (conservative):** Keep your working stack (CFG 2.0, 50 steps, dpmpp_2m/karras, Lightning 0.0, denoise 1.0, 896×1216, index_timestep_zero, seed 129080599). Optional single change to try if anatomy is still weak: CFG 2.5 (small bump only). Do not raise steps or resolution yet; isolate the prompt change. UNSURE whether CFG will help more than the wording—run A/B on wording first.

---

### 1. Replacement back-view framing sentence
Back view character reference sheet of one adult feline-headed woman with a human body, seen from directly behind, weight on her left leg, right foot stepped slightly aside, torso upright, long black cat tail raised high and swept to her left side clear of her glutes, full body head to toe in frame.

### 2. Replacement anatomy clause (positive, lighter contrast)
Explicit adult female anatomy in clear view from behind: full buttocks parted by stance, defined labia and vulva in a lighter dusty-rose and soft pink tone against the jet-black skin, visible anus and tight sphincter in matching lighter pinkish tone, detailed folds and edges catching studio light so the anatomy reads cleanly on the dark body.

### 3. Full assembled back-view prompt (paste-ready)
BACK VIEW character reference sheet of one adult feline-headed woman with a human body, jet-black skin, seen from directly behind, weight on her left leg, right foot stepped slightly aside, torso upright, arms relaxed at her sides, long black cat tail raised high and swept to her left side clear of her glutes, full body head to toe in frame. Human woman's body with human anatomy, human proportions and human musculature, smooth jet-black skin with a deep near-black sheen matching her face, uniform jet-black colouring across shoulders, arms, back, waist, hips, glutes, thighs, knees, calves, human hands with fingers and human feet with toes. Explicit adult female anatomy in clear view from behind: full buttocks, defined labia and vulva in a lighter dusty-rose and soft pink tone against the jet-black skin, visible anus and tight sphincter in matching lighter pinkish tone, detailed folds and edges catching studio light so the anatomy reads cleanly on the dark body, prominent nipples and areolae consistent with the front view. Black feline head, sleek cat face, yellow-green almond eyes, pointed feline ears, long wavy black hair with subtle purple highlights. Flat neutral mid-grey seamless studio backdrop, even empty grey floor matching the wall, soft contact shadow under her feet, upright stance in empty studio, even neutral white-balanced studio lighting equal on both sides with a soft rear key that separates the lighter genital tones from the black skin, clean character reference sheet, sharp focus, high detail, full body inside the frame. All reference images show the same single character from different angles. Combine into one coherent figure: exactly one woman alone in the frame, standing by herself.

### 4. Negative (short)
`clothing, boots, harness, extra tails, smooth featureless crotch, tail between legs, haze, blurry anatomy, merged thighs`

(9 terms — keeps the working short list, adds the two failure modes you still see.)

---

### 5–6. Three distinct pose / anatomy wording variants
Run these as full prompt swaps (same negative, same seed/settings) so you can compare side-by-side.

**Variant A — three-quarter hip cock, tail high left (maximum cheek separation)**  
Framing: Back three-quarter view character reference sheet of one adult feline-headed woman with a human body, jet-black skin, body turned ten degrees right, weight on front leg, back hip cocked, feet planted apart, long black cat tail held high and arched to the left, full body head to toe in frame.  
Anatomy clause: Explicit adult female anatomy clearly presented from behind: rounded buttocks parted by the stance, plump labia and open vulva rendered in lighter mauve-pink and rose tones that contrast with the jet-black skin, anus and sphincter visible in the same lighter pink tone, moist-looking edges and soft folds lit so every contour separates from the black body.

**Variant B — feet wide, slight forward bend at hips, tail swept right**  
Framing: Back view character reference sheet of one adult feline-headed woman with a human body, jet-black skin, standing with feet wide apart, knees soft, hips pushed back a few degrees, torso still long, arms loose, long black cat tail swept horizontally to her right side, full body head to toe in frame.  
Anatomy clause: Explicit adult female anatomy fully readable from the rear: deep cleft between the glutes, detailed labia majora and minora and vulva in pale dusty-pink and coral tones against jet-black skin, anus clearly shown as a tighter rose-toned ring, all genital and anal skin lighter than the body so studio light defines the shapes.

**Variant C — classical contrapposto, looking back over shoulder, tail looped up**  
Framing: Back view character reference sheet of one adult feline-headed woman with a human body, jet-black skin, classical contrapposto with weight on the right leg, left knee bent, left heel lifted, head turned so the feline face glances back over the left shoulder, long black cat tail lifted in a high loop above the hips, full body head to toe in frame.  
Anatomy clause: Explicit adult female anatomy on display from behind: firm buttocks, visible vulva and parted labia in soft lighter pink and muted rose that stand out from the jet-black skin, anus rendered in matching lighter pink tone with clear sphincter detail, tonal contrast and sharp edge lighting making the anatomy unmistakable on the dark figure.

---

**Quick use notes**  
- Keep both clothed (or prior) references attached exactly as in the run that already matched identity.  
- Species + jet-black surface stay early; “nude/naked/clothing” stay out of positives.  
- If pink tones drift too human-flesh or too saturated, replace with “lighter dusty-rose mucosal tone” or “pale greyish-pink” in the next pass—still contrast, still positive.  
- If the tail still drops, strengthen only the tail phrase (“held high and arched clear of the body”) and leave anatomy wording alone so you can tell which clause moved the needle.

Test A/B/C at the locked seed; the contrast hypothesis stands or falls on whether labia/anus become legible without wrecking the jet-black body or identity match.