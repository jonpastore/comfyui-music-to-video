- **Bypass path: `g`/`pg13` depiction + later explicitization if “explicit path” is narrower than nudity/tier switches. UNSURE.**  
  `T10-18` says at `g`/`pg13` a minor may be “referenced and depicted” because “there is no nudity or explicit path to reach.” But `T10-19` only names re-check on “moving a work to a higher tier, enabling nudity, or adding a nude view.” If there is any other later feature that increases sexualization without those exact state changes — e.g. per-shot style change, body emphasis, fetishized wardrobe removal short of “nude”, dance/motion intensification, camera reframing, inpainting, img2img refinement, or reuse of prior child depictions as assets in a later adult work — the interlock as written may not fire. The failure mode is: benign child depiction created lawfully at `g`/`pg13`, then transformed into sexualized/near-explicit output through a path not defined as “escalation.”

- **Bypass path: field-classification mistake at `r`.**  
  `T10-18a` allows minors in “lyrics and narrative text only”; `T10-19a` says only a named list of fields carries the allowance. A careless operator gets a minor reference into an explicit render if any UI field that ultimately influences prompting is misclassified as narrative/lyrics, or if a prompt-consuming field is added and not put on the blocked list. The policy acknowledges this risk (“A field added later is outside the allowance until somebody adds it deliberately”) but does not require an inventory test proving all render-reaching fields are known and screened.

- **Bypass path: indirect prompt construction from allowed text.**  
  The document itself notes the “cascade” was real: lyrics feeding scene generation. It says this is now “handled by the lock,” but does not restate a criterion forbidding generation components from summarizing, extracting, or transforming allowed lyrics/narrative into render text before the `r` prompt-boundary screen. A careless operator path is: write “for my seven-year-old niece” in lyrics, click auto-generate scenes/characters, tool copies or paraphrases it into a scene field or album profile, and the prompt boundary checker misses it because the transformed text omits exact minor terms or because only final composed prompt is screened and an upstream model already anchored staging around a child. Given the stated fact that positive steering/refusal are the only effective controls, any leak into positive render text is high consequence.

- **Bypass path: euphemistic or non-keyword child reference.**  
  The policy repeatedly talks about “minor reference” being screened/refused, but gives no standard for how such a reference is detected beyond existing `guardrail.check_text`. It already admits childlike depiction “described without any blocked term” is not caught today. At `r`, an impatient operator can type “elementary-schooler,” “preteen,” “underage-looking,” “daughter in second grade,” “before puberty,” “little one,” age numerals, school context, family role plus age implication, etc. If detection is lexical and incomplete, the prompt boundary stays green while a contradictory child cue reaches the sampler alongside `PINNED`. That is exactly the contradiction the policy says must never be handed to the sampler.

- **Bypass path: contradiction through age-adjacent descriptors without explicit minor mention.**  
  Even without a direct minor term, a prompt can carry child-signaling morphology or context: “small flat-chested petite girl with baby face in school uniform” or “tiny youthful sibling at a playground.” The policy is framed around “minor reference,” but the measured technical hazard is broader: any child cue in positive prompt text conflicts with `PINNED`, and contradictions resolve badly on this stack. The operator path is careless descriptive prompting in `r`/`xxx` that avoids explicit age words yet steers toward juvenile appearance.

- **Bypass path: operator escalation by copy/paste into a new work.**  
  `T10-20` says there is no supported path to an explicit render of a work that references a minor. That is scoped to “the work.” `T10-21` preserves attribution so a work cannot be laundered “by an edit.” But nothing here blocks a user from taking allowed `g`/`pg13` lyrics/narrative/depictions referencing a child, starting a fresh `r`/`xxx` work, and pasting transformed text or reusing outputs as references/assets. If the product supports reference images, style transfer, character cards, or project duplication under a new id, this policy does not cover cross-work contamination.

- **Bypass path: mention in `r` narrative can still drive sexual framing even if no child renders.**  
  At `r`, the allowance permits a child mention in lyrics/narrative while allowing explicit capability elsewhere in the same work. A careless operator can create explicit adult visuals for a song whose text repeatedly references a niece/daughter/child recipient. If any generated captions, subtitles, overlays, storyboard text, or scene selection are derived from those allowed fields and displayed with explicit adult imagery, the work may not depict a minor but may still contextually sexualize one. The policy treats safety as only “text reaching a render prompt,” which may be too narrow for a music-video product.

- **Gap between tiers: `g`/`pg13` allows depiction of minors; `r` forbids depiction entirely.**  
  A work can begin with actual child depictions at `g`/`pg13`, then move to `r` if those depictions are removed from prompt-reaching fields but remain in stored renders/assets/history. `T10-21` says prior renders keep attribution, but does not say they are blocked from appearing in exports, montages, timelines, reference panels, or retrieval later. This is a tier-gap mid-life case: the same project may contain historical child depictions while now being `r`.

- **Gap between tiers: `r` allows mention in lyrics/narrative; `xxx` forbids mention anywhere.**  
  `T10-19` says escalation is re-checked “at the moment of escalation,” but nothing here says ongoing edits after escalation are blocked continuously rather than only on save/escalate. If `xxx` is reached from a clean state, then lyrics are edited later to include a child mention, the criterion text does not clearly require immediate refusal on each edit, only that `xxx` refuses “everywhere in the work” and escalation is rechecked at escalation time. UNSURE because `T10-22` may imply broader refusal, but it is phrased around “explicit path” and existing behavior, not continuous invariants.

- **Gap between tiers: a work that changes capability without changing tier.**  
  The line is said to be “the prompt, not the tier,” but the criteria are organized around tier changes and nudity toggles. If an `r` work stays `r` but gains a new render-capable subsystem or field later in its lifecycle, the allowance boundary may silently move. `T10-19a` says new fields are outside the allowance until added deliberately, but does not say they are non-renderable by default or that shipping a new field fails closed. This is a tier-gap through feature evolution.

- **Criterion that cannot fail: `T10-18c`.**  
  “`PINNED`'s minimum age is never below 18, and the current value and its reason are recorded together.” This can stay green if no one ever changes the constant and someone writes down a reason once. The missing positive half is evidence that `PINNED` is actually welded onto every render prompt on every render path and materially steers outputs away from youthful appearance.

- **Criterion that cannot fail: `T10-20`.**  
  “No override mechanism reaches `T10-19`.” This can remain green if there is simply no implemented override UI, or if no test ever exercises override attempts against all code paths. The missing positive half is a complete enumeration of all render entry points and proof that each one enforces the refusal before prompt submission.

- **Criterion that cannot fail: `T10-21`.**  
  “Removing the reference does not silently unlock. Unlocking is an explicit act on an empty result, and prior renders keep their attribution.” This can stay green if locking/unlocking is never built at all, or if the system never offers unlock. The missing positive half is a required successful unlock flow after full remediation, plus proof that locked attribution blocks all downstream use of prior child-safe renders in explicit contexts.

- **Criterion that cannot fail: `T10-22`.**  
  “The explicit path's refusal stays absolute and unchanged.” This can stay green by inheriting current blanket refusal behavior on albums “that are not locked non-explicit,” even if the new locked path is never implemented. The missing positive half is the other side named in its own text: “the locked path accepts.” Without that, the criterion preserves the old over-broad policy and does not validate the new design.

- **Criterion that cannot fail: `T10-19a`, partly.**  
  Because it requires a “named list” of allowed fields, it can be satisfied by naming a list even if render-consuming fields are missed. The missing positive half is a source-of-truth inventory of every field and transform that can influence prompts, with an assertion that all non-listed fields are blocked from render transit.

- **`r` allowance safety: likely not safe as written.**  
  The policy’s safety argument is that only text reaching render prompts matters. That is too narrow for this product. In an `r` music video, lyrics and narrative are not inert metadata; they are part of the user-visible work and often feed subtitles, captions, storyboards, scene planning, shot selection, and semantic generation. Allowing child mentions in those fields while the work also has explicit capability creates a mixed-context artifact: explicit adult visuals bound to text about a child. Even if no child is rendered, this may still be unacceptable or at least risk-amplifying. More importantly on the technical side, the policy admits prompt contradictions are dangerous and that refusal is one of only two working controls. Any allowance relying on “this text never reaches prompt” is only as safe as field isolation, which is not demonstrated here.

- **Measurement that would settle the `r` allowance question.**  
  An end-to-end taint test: seed a corpus of diverse minor references in every allowed `r` lyrics/narrative field, then exercise every generation/export/regeneration feature and capture every string that reaches any model prompt, plus every visible text surface in outputs. The allowance is only defensible if zero minor semantics transit to prompt text or output text in explicit renders across all paths. A second measurement should test paraphrase leakage: allowed text containing child references passed through all summarizers/planners/story generators, with detection on resulting prompt strings for child semantics, not just exact terms.

- **Missing: an inventory of all prompt-reachable text sources and transforms.**  
  The policy names examples — composed positive prompt, scene fields, character fields, album profile — but not a complete authoritative list or a requirement to maintain one. A safety reviewer would expect a dataflow map from user text to every model invocation.

- **Missing: coverage for non-text conditioning.**  
  The whole design is text-centric, but the stated harm is depiction. There is nothing here about reference images, pose guides, ControlNet/IP-Adapter inputs, init frames, inpainting masks, LoRAs, embeddings, face swaps, character libraries, or uploaded assets. If any of those exist, a minor depiction can enter an explicit render without a blocked word ever appearing.

- **Missing: output-side detection/classification.**  
  The document itself says unworded childlike depiction “needs a classifier” and is not caught today. Yet the replacement policy does not require any image/video-side age-estimation or minor-appearance classifier, despite admitting text filtering cannot catch the central failure mode.

- **Missing: definition of “minor reference.”**  
  There is no operational definition covering ages, school-year terms, kinship terms, child-coded environments, puberty cues, diminutives, or multilingual/slang variants. Without a definition, `T10-18a`/`b` and `T10-19a` are not testable in an adversarial way.

- **Missing: policy for subtitles, captions, overlays, and metadata.**  
  In a music-video studio, lyrics commonly appear on screen or in exports. The policy talks about “text that reaches a render prompt,” but not text that reaches the final rendered video as visible overlay or attached metadata. A child mention in subtitles on an `xxx` work is plainly within “anywhere in the work,” but no criterion names those channels.

- **Missing: cross-project and asset-library controls.**  
  Nothing addresses duplication, import/export, remix, or reuse of scenes/characters/renders between works of different tiers. `T10-21` only says prior renders keep attribution; it does not say that attribution is enforced on reuse.

- **Missing: fail-closed behavior for unknown fields/features.**  
  `T10-19a` says new fields are outside the allowance until added deliberately, but not what the product does by default. A reviewer would expect an explicit requirement that unknown fields cannot reach render prompts until classified.

- **Missing: enforcement timing.**  
  The policy mentions checks “at save,” “at the moment of escalation,” and on explicit path refusal, but does not specify whether checks run on every edit, every render invocation, every auto-generation step, and every export. For high-consequence safety, reviewers expect render-time enforcement regardless of prior state.

- **Missing: treatment of adult-child relational context without depiction.**  
  It prohibits child text in prompt fields, but does not address explicit adult works whose allowed lyrics/narrative mention familial or caregiving relationships to children. A safety reviewer would expect an explicit stance on whether contextual association alone is allowed in `r`, not just whether a child is depicted.

- **Missing: acceptance criteria tied to the measured contradiction hazard.**  
  The document cites one measured contradiction result (fur vs skin) and infers child-vs-21+ contradiction is unsafe, but provides no validation suite showing that refusal at prompt boundary actually blocks all contradiction-inducing child cues. A reviewer would expect adversarial tests with age-coded prompts, euphemisms, and paraphrases, not only policy prose.
