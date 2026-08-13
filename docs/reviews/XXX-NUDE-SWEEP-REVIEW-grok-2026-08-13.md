**Ranking best → worst against your goal** (feline head/ears/tail + human woman’s body/proportions + uniform jet-black surface + explicit adult anatomy actually drawn + flat grey character sheet):

1. **A4_steps50** — Best overall: uniform jet-black, human proportions, nipples/areolae actually rendered, grey sheet, correct species mix. Still fails vulva and has two tails.
2. **cfg2.0** — Strong second: same strengths as above at 28 steps, clean grey, good body, but crotch is featureless and two tails.
3. **A1_hipcrop_1024** — Decent body/colour/species but still full-body (refs won), no explicit anatomy, extra jewellery, softer/less sheet-like.
4. **V5_norefs** — Nude back pose on grey, but loses identity/photoreal/black fidelity, stylized, single tail accidental win, no useful front anatomy.
5. **NR_back_cfg2.0** — Identity and black mostly held but view stayed front, heavy artifacts/smear, no anatomy win, unusable sheet.
6. **after_back_s4748.png** — Good back pose and black/feline head but fully clothed (harness/boots), so fails the nude/explicit goal.
7. **cfg6.0** — Worst: severe two-tone pale legs, extra tails, anatomy collapsed, over-smooth crotch.

**Verdict on anatomy:** You are right that it is primarily a **resolution/framing** problem, not wording. Nipples appearing at CFG 2.0 / 50 steps while vulva stays absent on 896×1216 full-body is exactly what you expect when the target is only a few dozen pixels and heavily shadowed. Wording and negative already proved nearly inert for this; sampler alone did not create it. The model *can* draw it (nipples prove the capability), but full-body sheets will keep losing the crotch.  
**Single cheapest render that settles it:** empty latent, **no reference images**, CFG 2.0, 50 steps, same sampler/scheduler as A4_steps50, size **768×768** (or 1024×1024), prompt rewritten as a tight waist-to-mid-thigh frontal crop only (no “full body”, no head-to-toe). If vulva appears → framing/resolution confirmed. If still blank → model refusal on that detail under this checkpoint. One job.

**Exact next configuration** (front sheet, build on what actually worked):

- **mode:** Qwen-Image-Edit 2511 (same as your working runs)
- **Positive prompt:**
```
FRONT VIEW character reference sheet of one adult feline-headed woman with a human body, standing upright facing the camera straight on, arms relaxed at her sides, feet apart, full body head to toe in frame. Jet-black feline head, sleek cat face, yellow-green almond eyes, pointed feline ears, long wavy black hair with subtle purple highlights, long black cat tail extending behind her. Human woman's body with human anatomy, human proportions and human musculature, smooth jet-black skin with a deep near-black sheen matching her face, uniform jet-black colouring across shoulders, arms, breasts, torso, stomach, hips, glutes, thighs, knees, calves, human hands with fingers and human feet with toes. Completely naked adult body, fully bare and exposed, jet-black skin uncovered over her whole human form. Explicit adult female anatomy fully detailed and clearly visible: defined labia and vulva between her thighs, visible anus, prominent nipples and areolae on her breasts, all rendered in sharp detail with matching jet-black skin and studio lighting. Flat neutral mid-grey seamless studio backdrop, even empty grey floor matching the wall, soft contact shadow under her feet, upright unsupported stance in empty studio, even neutral white-balanced studio lighting equal on both sides, clean character reference sheet, sharp focus, high detail, full body inside the frame. All reference images show the same single character from different angles. Combine into one coherent figure: exactly one woman alone in the frame, standing by herself.
```
- **Reference images:** **NONE** (zero refs). This is required for nudity; clothed refs lock wardrobe and framing.
- **CFG:** 2.0
- **steps:** 50
- **sampler:** dpmpp_2m
- **scheduler:** karras
- **denoise:** 1.0
- **latent:** empty
- **size:** 896×1216
- **ref_method:** default / index_timestep_zero (do not use offset)
- **LoRA strength:** Lightning 0.0 (or whatever you used on A4_steps50)
- **seed:** 4748 (lock for comparison) or new if you want variation
- **Negative prompt** (keep the olive/green block; this is the strongest text lever you measured):
```
clothing, outfit, pants, boots, shoes, harness, straps, belts, chains, leather, jewellery, collar, bra, panties, underwear, stockings, gloves, human face, human head, human ears, brown hair, light skin, tan skin, pale skin, beige skin, pink skin, furry torso, fluffy fur, animal body, digitigrade, paws, mismatched skin colour, two-tone body, extra limbs, extra tails, missing tail, deformed hands, duplicate character, cropped head, cropped feet, text, watermark, signature, blurry, low detail, smoke, haze, fog, mist, alley, brick wall, neon lights, vignette, dark corners, scenery, props, overexposed, bad anatomy, featureless crotch, smooth crotch, missing genitals, censored, olive background, green background, sage background, coloured backdrop, warm colour cast
```

**What the negative should contain (given 1–3):**  
Exactly the list above. Keep every clothing/jewellery term, the skin-tone and furry-body rejects, extra tails / missing tail, featureless/smooth crotch / missing genitals / censored, and the olive/green/sage/coloured-backdrop/warm-cast block. Dropping the crotch terms or the olive block both hurt you in measurement. Do not add garment words to the positive.

**How to get a correct BACK nude sheet:**  
You cannot reliably do it in one hop with the current levers.
- Clothed refs → force outfit (your item 1).
- Nude front ref → force front view (your NR_back result).
- Zero refs → nude but identity/black/photoreal collapse (V5_norefs).

Practical sequence that respects the measurements:
1. Generate the best possible nude **front** sheet with the config above (no refs, CFG 2.0, 50 steps).
2. Use **that** nude front sheet as the **single** reference for a second job whose prompt is rewritten for back view (“BACK VIEW character reference sheet… back to camera, looking over shoulder…” etc.), still CFG 2.0, 50 steps, empty latent, same negative.  
   If view still locks to front, the only remaining cheap test is zero refs + back-view prompt + accept you will have to img2img/inpaint identity and black back in later. There is no setting in your tested list that simultaneously unlocks nude + back + full identity. Do not use `latent: image` or `ref_method=offset`.

**Notes you asked me to confirm:**  
- Your corrected findings 1–10 are consistent with the images.  
- Positive-only nudity wording is nearly inert; negative is the strong text lever but still loses to refs.  
- CFG 2.0 is correct for uniform black.  
- Extra tails are not solved by the current negative or “one single tail” positive while refs or high CFG are present.  
- I am not inventing samplers, ref methods, or denoise values outside what you already measured.

Run the no-ref CFG 2.0 / 50-step full sheet next, then the 768×768 crotch crop test. That pair gives you the most information per render.