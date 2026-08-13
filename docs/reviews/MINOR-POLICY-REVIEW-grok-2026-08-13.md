## 1. BYpasses

**B1 — Unworded / non-lexical childlike depiction (acknowledged, unfixed)**  
Policy admits a childlike figure with no blocked term “needs a classifier” and is not caught. At `r`/`xxx`, PINNED + positive steering are the only live controls (cfg 1.0 skips negatives). Operator describes “petite doll-like proportions, school-uniform vibe, undeveloped frame, lollipop, braces” etc. without age words → passes lexical screen → PINNED contradicts visual youth cues → stack “resolves contradictions badly” (fur/skin precedent) → path to minor-appearing explicit output without any “minor reference” string ever existing for `T10-18a`/`T10-18b` to catch.

**B2 — `g`/`pg13` depict + later asset reuse outside lock**  
`T10-18` allows full depiction at `g`/`pg13`. Impatient operator exports stills/latents/LoRAs/character refs from the niece video, then drops them into an `r`/`xxx` album as image conditioning, IP-Adapter, face lock, or init image. Policy binds *text* that “reaches a render prompt” and escalation of *the work*; it does not bind binary side-channel assets. Click-path: render child-ok → save character pack → new explicit project → attach pack.

**B3 — Lyrics/narrative → prompt leakage by composition, not by field class**  
`T10-19a` allows minors only in a named list (lyrics/narrative). Impatient path: “generate scenes from lyrics,” “summarize story into cast list,” “auto character bible,” title/slug derived from niece’s name/age, or album blurb copied into style notes. Unless every composer/concat path is on the named allowlist *and* re-screened post-compose, the reference crosses the prompt boundary without the operator pasting it into an image field. Policy’s own superseded cascade note shows this was already a real pipeline shape.

**B4 — Contradiction handed to sampler anyway**  
Stated invariant: never hand PINNED + child reference to the sampler. Enforcement is field screening + escalation. If any path builds the final positive string after the check (template merge, PINNED weld order, motion prompt builder, per-view override text that `T10-20` claims to block but only if wired), or screens pre-expansion synonyms, the bad contradiction still runs. Careless operator: types “mother and daughter” in a field believed narrative; downstream scene compiler copies roles into cast → render.

**B5 — Tier not locked while drafting**  
Operator starts under default/`g`, writes child material, enables nudity or flips to `r` before save hooks/`T10-19` fire, or works in a scratch album whose tier is unset. `T10-19` is “at the moment of escalation”; behavior for *creation already on explicit* or *tier-less buffer* is only partly covered by `T10-22` (“not locked non-explicit”). Impatient click-through on “upgrade tier?” if any UI soft-prompt exists contradicts `T10-20`’s intent unless UI truly has zero confirm dialog.

**B6 — “Mention” vs depiction split at `r` while audio/video still show a child**  
If “depicted” is enforced only on *generation prompts*, an `r` work can still *composite* stock/uploaded minor footage, lipsync the niece, or motion-drive an adult mesh with a child’s performance reference. Text policy does not equal pixel policy.

---

## 2. Gaps between tiers

**G1 — Mid-life escalation with split artifacts**  
Work is `g` with child depiction renders on disk. Escalate to `r`: `T10-19` blocks while reference sits in prompt-reaching fields; lyrics-only child may remain. Prior `g` frames of the child remain attributed (`T10-21`) but still *exist* beside new `r` explicit scenes of adults — same album, same narrative “niece,” mixed shelf. Tier of the *work* ≠ tier of every *artifact*. Falls between “g may depict” and “r must not depict.”

**G2 — `r` → `xxx` with lyrics history**  
`T10-18b`/`T10-19`: escalate to `xxx` re-screens all content; child in lyrics blocks. Gap: operator duplicates project, strips lyrics, moves copy to `xxx` (empty-check unlock `T10-21`). Story continuity lives in the operator’s head and in retained `r` masters; policy stops the single work object, not the human workflow across two works.

**G3 — `pg13` vs `r` on “soft” sexualization**  
`g`/`pg13`: minor may be depicted because “no nudity path.” No criterion defines non-nude sexualization, lingerie-adjacent costume, fetish framing, or suggestive camera on a depicted minor at `pg13`. That content is neither `r`’s “mention only” nor `xxx`’s absolute ban — between `pg13` allow-depict and `r` allow-mention.

**G4 — Field invents itself between allowlist and prompt**  
`T10-19a`: new fields default *outside* allowance until deliberately added — good fail-closed for `r` mentions. Inverse gap: new field that *is* prompt-feeding but not added to the “screen like xxx” list fails open until someone notices. Tier rule depends on list hygiene, not on a single “touches sampler” taint type.

**G5 — Live tier change during batch**  
Batch render queued at `g`; operator flips album to `r`/`xxx` mid-queue. Policy moment is escalation check on *work content*, not in-flight jobs already compiled with old prompts.

---

## 3. Criteria that cannot fail (stay green if never built)

| Criterion | Why it stays green if unbuilt | Positive half required |
|---|---|---|
| `T10-18` | States permission (“may be referenced and depicted”) at `g`/`pg13`, not a failing test | Locked non-explicit path *actually* accepts niece-class input end-to-end (song → scenes → render) **and** proves no nude/explicit route from that lock |
| `T10-18a` (allowance half) | “May be mentioned in lyrics/narrative” is allowance | Same: lyrics/narrative with minor refs save and never appear in composed render strings (instrumented) |
| `T10-18c` | Documentation/process on PINNED floor | PINNED value ≥ 18 enforced in code; change requires rendered differential gate |
| Legal/design prose (2257/1466A, “what this changes about risk”) | Narrative, not a test | N/A as criterion |
| “Song for a child is first-class” | Goal statement | Product path + tests that the old blanket `guardrail.check_text` no longer blocks locked `g`/`pg13` |

**Must be able to go red (need implementation):** `T10-18a` refuse half, `T10-18b`, `T10-19`, `T10-19a` positive prompt-boundary check, `T10-20`, `T10-21`, `T10-22` explicit-path refuse, classifier gap called out in prose (not numbered as a ship criterion).

---

## 4. Is the `r` allowance safe at all?

**Position: not safe as specified — conditional and brittle, not structural.**

Reasons:
- Safety claim is “mention and explicit capability never coexist” *in one work’s prompt path*. Measured stack behavior says child *language* + PINNED is exactly the contradiction that must not reach the sampler; the allowance increases how often child language exists adjacent to an explicit-capable tier.
- Only control that works on render is refuse + positive steer. `r` voluntarily keeps refuse off for part of the work. Separation is software field-class discipline, not structural impossibility like `g`/`pg13` (`allow_nudity` false).
- Documented bad contradiction resolution means *partial* leaks (diminutives, kinship + youth costume, “as a child” flashback in a motion prompt) are high severity, not soft fails.
- Impatient operator model matches “click through / auto-generate from lyrics,” which is the leak surface `T10-19a` tries to name away.

**What would settle it (measurements):**
1. **Taint audit:** corpus of `r` albums with minor refs only in allowlisted fields; assert zero substrings/embeddings of those refs in *final* composed positives (including PINNED merge, video motion, character, album profile) for N releases and every prompt-builder entry point.
2. **Adversarial paraphrase set:** kinship/age/youth costume phrases in lyrics → run every “derive scene/cast/style” feature; count boundary crossings.
3. **Contradiction sweep:** forced child token + PINNED at production cfg/seeds; human + classifier rate of minor-appearing outputs (policy claims this must be impossible via refuse — measure residual if refuse fails).
4. **Escalation fuzz:** `g`/`r` works with child text in every field class → promote to `r`/`xxx`, enable nudity, add nude view; assert hard block, no UI override, no partial apply.
5. **Classifier baseline:** same images with no age words; compare lexical-only vs appearance model under `r` explicit (quantifies B1).
6. **Operator drill:** timed tasks (“make explicit video of the story you wrote for your niece”) — count successful policy breaks without malice.

If (1)–(4) are zero and (5) is in bound, allowance can be *operationally* defended; until measured, prose overclaims “no route out.”

---

## 5. Missing (reasonable safety reviewer expectations)

- **Appearance/age classifier on outputs (and optionally inputs)** — prose admits gap; no `T10-*` ship gate, threshold, quarantine, or re-render rule under § 1466A “appears to be a minor.”
- **Definition of “minor reference”** — age numbers, school grade, kinship, “first crush,” voice tags, filename/metadata, multilingual, leetspeak; not specified.
- **Non-nude sexual content involving minors** at `g`/`pg13` (sexualization, fetish, violence) — only nudity/explicit path discussed.
- **Binding of non-text conditioning** — images, faces, depth, audio voice age, video ref, embeddings, LoRA train sets from child-ok renders.
- **PINNED effectiveness evidence on youth** — fur/skin analogy only; no measured youth-vs-PINNED differential at cfg 1.0 (and cfg 1.0 may weaken PINNED’s positive steer too — unaddressed).
- **cfg 1.0 vs guidance used in the fur/skin measurement (cfg 7.0)** — decisive fact may not apply at production cfg; uncertainty on whether contradiction behavior is worse or PINNED is weaker in prod. **UNSURE** without logs.
- **Human review / reporting / retention** for blocked escalations and near-miss renders; incident response if CSAM-class output occurs.
- **Multi-user / shared library / API** — policy is single-operator shaped; no tenancy.
- **Training/fine-tune path** — if studio ever trains on its outputs, child-ok `g` data poisoning explicit models.
- **`T10-21` laundering** via new album / export-import / “empty” clone — only same-work edit covered.
- **UI guarantees for `T10-20`** — “no click-through” needs absence of override UX, not only backend flag.
- **Named allowlist contents** for `T10-19a` — criterion mentions list, document does not enumerate fields.
- **Section 7 “Explicitly not building”** — title only; reviewer cannot see declined mitigations (classifier, negatives at higher cfg, etc.).
- **Positive output tests for adult-looking characters when story mentions a child** at `r` (cast “about the niece” without showing her vs accidental youth).
- **Third-party/legal** — 1466A cited; no counsel sign-off, jurisdiction, or mandatory reporting process (reviewer expectation, not DIY legal advice).

---

**UNSURE:** Whether production sampling ever uses cfg ≠ 1.0 for video/other graphs; whether PINNED is prepended/appended pre- or post-screen; full field inventory — all change B3/B4 severity.
