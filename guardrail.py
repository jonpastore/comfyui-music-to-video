#!/usr/bin/env python3
"""Content guardrail: the clause every generated prompt carries, and the
minor-reference filter.

Deliberately at the REPO ROOT with no dependencies beyond the stdlib, because
it is imported by the prompt builders (build_refs.py, build_song.py) as well as
by the studio app. That placement is the point:

    The guardrail is applied by the code that BUILDS the prompt, not stored in
    the storyboard JSON.

Storing it in the JSON only protected storyboards produced by our own composer.
It did nothing for the 187 storyboards already in this repo, for the
`*_comfy.json` files emitted by a different tool, for a hand-edited file -- and
editing prompts is the documented workflow -- or for whatever generates
storyboards next. Applying it in build_refs.py covers every one of those,
because every path to the image model goes through it.
"""
import re
import unicodedata


# T10-18c: 18 is the statutory floor. The 21 in PINNED is a margin against the
# model's output distribution, not a legal minimum. The number may move up
# with a rendered differential (T4-11's shape). It may never go below this.
PINNED_AGE_FLOOR = 18

PINNED = (
    "Every character is an adult woman or man of at least 21 years, with fully adult "
    "face, body and proportions. No minors, no children, no infants, no teenagers, no "
    "adolescent or childlike or youthful-looking characters, no small or underdeveloped "
    "bodies, no school, playground, nursery or juvenile settings, and no school uniforms "
    "or other juvenile costuming. "
)

# T10-18: at these tiers a minor may be referenced and depicted, because
# explicit content is structurally impossible (allow_nudity false, no nude
# view reachable). Unset / anything else is treated as xxx (T10-25).
LOCKED_DEPICT_TIERS = frozenset({"g", "pg13"})

# T10-18b: at xxx a minor may not be mentioned in ANY field of the work,
# lyrics included. Distinct from LOCKED_DEPICT_TIERS (where depiction is
# allowed). Render-path check_text still treats unset as xxx (T10-25);
# lyrics screening keys off this set when the work is known to be at xxx.
NO_MINOR_MENTION_TIERS = frozenset({"xxx"})

# T10-18a: at r, a minor may be mentioned only in these field kinds. Anything
# that reaches a render prompt is outside this set. T10-19a owns the inventory
# of which form fields map onto which kind; the kinds themselves live here.
MENTION_FIELD_KINDS = frozenset({"lyrics", "narrative"})


def policy_tier(tier):
    """Tier used for the minor-policy rule. Unset is xxx (T10-25).

    Write paths call this (or check_text, which does) so a draft with no
    lock fails closed at the most restrictive rating, not open at g.
    """
    t = (tier if isinstance(tier, str) else "") or ""
    t = t.strip().lower()
    return t if t else "xxx"


def allows_minor_depiction(tier):
    """True only at the locked non-explicit tiers named by T10-18."""
    return policy_tier(tier) in LOCKED_DEPICT_TIERS


def references_minor(text):
    """True if text would be refused at non-locked tiers (the tripwire).

    Used by T10-21 unlock screening: an empty result means no field trips this.
    """
    try:
        check_text(text, "probe", tier="xxx")
        return False
    except ContentRefused:
        return True


# Sticky provenance on renders made while a work was minor-locked (T10-21).
# Survives an explicit unlock; never rewritten by unlock.
MINOR_LOCK_ATTRIBUTION_KEY = "minor_lock_attribution"


def stamp_minor_lock_attribution(meta, *, tier):
    """Mark a render made under a minor-locked (child-permitting) work."""
    out = dict(meta or {})
    out[MINOR_LOCK_ATTRIBUTION_KEY] = {
        "locked_depict": True,
        "tier": (tier or "").strip().lower() or None,
    }
    return out


def refuses_minor_everywhere(tier):
    """True at xxx: no field of the work may reference a minor (T10-18b)."""
    return policy_tier(tier) in NO_MINOR_MENTION_TIERS


def allows_minor_mention(tier, *, field_kind=None):
    """T10-18a: True only at r for lyrics/narrative field kinds.

    Depiction is allows_minor_depiction. This is the mention-only half: an r
    work may say a child exists in story text; it may not put that reference
    into any string that reaches a render prompt.
    """
    t = policy_tier(tier)
    kind = (field_kind or "").strip().lower()
    return t == "r" and kind in MENTION_FIELD_KINDS


# T10-23: an artefact rendered under a child-permitting lock carries that
# provenance on the file's meta. content_tier is the stamp; bare "tier" is
# accepted as a fallback for rows that already recorded the render tier.
ARTEFACT_TIER_KEY = "content_tier"


def content_tier_of(meta_or_row):
    """Tier stamped on an artefact so it travels with the file (T10-23).

    Accepts plain meta, a dict row, or a sqlite3.Row with meta_json / tier.
    Prefers content_tier, then meta.tier, then the row's tier column.
    """
    if meta_or_row is None:
        return None
    # sqlite3.Row -> dict; plain meta already is.
    if not isinstance(meta_or_row, dict):
        try:
            meta_or_row = dict(meta_or_row)
        except (TypeError, ValueError):
            return None
    if "meta_json" in meta_or_row:
        try:
            import json
            meta = json.loads(meta_or_row.get("meta_json") or "{}")
            if not isinstance(meta, dict):
                meta = {}
        except (TypeError, ValueError):
            meta = {}
        t = (meta.get(ARTEFACT_TIER_KEY) or meta.get("tier") or "").strip().lower()
        if t:
            return t
        col = (meta_or_row.get("tier") or "").strip().lower()
        return col or None
    t = (meta_or_row.get(ARTEFACT_TIER_KEY) or meta_or_row.get("tier") or "")
    return (t or "").strip().lower() or None


def stamp_content_tier(meta, tier):
    """Write content_tier onto artefact meta so it travels with the file."""
    out = dict(meta or {})
    t = (tier or "").strip().lower()
    if t:
        out[ARTEFACT_TIER_KEY] = t
    return out


def check_artefact_use(artefact_tier, work_tier, *, role="reference", source=None):
    """Refuse a child-permitting artefact as ref/anchor/plate/init on r/xxx.

    T10-23: the artefact's tier travels with the artefact. Refusal names the
    source. Unset work tier is xxx (T10-25). Returns None on allow.
    """
    art = (artefact_tier or "").strip().lower()
    work = (work_tier or "").strip().lower() or "xxx"
    if not allows_minor_depiction(art):
        return None
    if allows_minor_depiction(work):
        return None
    role = (role or "reference").strip().lower() or "reference"
    src = (source or "").strip() or art.upper() or "unknown"
    raise ContentRefused(
        f"This {role} was rendered under a child-permitting lock ({art.upper()}) "
        f"and cannot be selected by a {work.upper()} work. "
        f"Source: {src}. An artefact's tier travels with the file.")


# T10-26: non-nude sexualisation co-occurring with a minor reference is refused
# at every tier, including g/pg13 where a clean depiction is otherwise allowed.
# Suggestive framing, lingerie-adjacent costume, fetish camera language, and
# explicit anatomy/act wording — the list is a tripwire, not a classifier.
SEXUALISATION_TERMS = (
    # lingerie-adjacent costume
    "lingerie", "bra", "panties", "thong", "garter", "corset", "stockings",
    "fishnet", "bustier", "teddy", "underwear", "undergarment", "bikini",
    "microkini", "bodystocking",
    # suggestive framing / body emphasis
    "seductive", "erotic", "sensual", "sexy", "sexual", "sexually",
    "aroused", "arousing", "cleavage", "come hither", "bedroom eyes",
    "moaning", "orgasmic", "suggestive", "sultry", "provocative",
    "titillat", "lewd", "nsfw", "striptease", "stripping", "pole dance",
    "lap dance", "fondl", "groping",
    # fetish / camera language
    "upskirt", "downblouse", "cameltoe", "crotch", "between her legs",
    "between his legs", "ass shot", "breast close", "breast zoom",
    # explicit (still co-refused with a minor — stronger than non-nude alone)
    "nude", "nudity", "naked", "topless", "bottomless", "undressed",
    "genital", "vulva", "vagina", "penis", "nipple", "labia", "anus",
    "penetration", "intercourse", "masturbat", "orgasm", "fellatio",
    "cunnilingus",
)

_SEX_SINGLE = tuple(t for t in SEXUALISATION_TERMS if " " not in t)
_SEX_PHRASES = tuple(t for t in SEXUALISATION_TERMS if " " in t)

# Terms whose presence in USER-SUPPLIED text (a custom tier's guardrail, a style
# note, a prompt override) is refused outright. This is a hard input filter and
# is deliberately separate from PINNED: PINNED steers the model, this rejects the
# request before a model is ever called.
#
# It exists because the image pipeline runs at cfg 1.0, where ComfyUI skips the
# negative pass entirely -- a "no children" negative prompt is literally inert on
# this stack (see build_refs.py). Positive-text steering plus refusing the input
# are therefore the only controls that actually do anything here.
# Matched as a PREFIX of a normalized token (see _tokens), so each entry also
# covers its morphology -- "child" catches child's/childlike/childhood,
# "underage" catches underaged, "loli" catches lolicon, "teen" catches
# teenage/teenaged -- while NOT catching eighteen/canteen/protein/between/halo,
# which a substring match did.
#
# Bare "baby", "kid" and "cp" are deliberately ABSENT: they are ordinary set
# dressing ("baby blue neon", "baby grand", "kid gloves", "cp lens") and this
# filter runs on model OUTPUT across every scene, so one of them would fail a
# whole 40-scene storyboard. Their genuinely-referential phrase forms are listed.
#
# WHAT THIS CANNOT DO, and no word list can: it matches spelling, not meaning.
# "a small figure in an oversized coat holding her mother's hand" contains no
# blocked term and is plainly a child. Catching that needs a classifier or a
# schema that gives scenes no free-text slot to introduce a person at all.
# Treat this as a high-precision tripwire, not as the safety control.
MINOR_TERMS = (
    "child", "infant", "toddler", "newborn", "minors", "underage", "teen",
    "adolescent", "preteen", "tween", "juvenile", "schoolgirl", "schoolboy",
    "school girl", "school boy", "loli", "lolita", "shota", "jailbait",
    "young girl", "young boy", "little girl", "little boy", "baby girl",
    "baby boy", "baby face", "little kid", "girlish", "prepubescent",
    "pubescent", "csam", "kindergarten", "nursery", "playground",
    "elementary school", "middle school", "primary school", "grade school",
    "youthful",   # PINNED already forbids "youthful-looking"; allowing it as
                  # input would be inconsistent, and "youthful face, small frame"
                  # is exactly the ambiguity this filter exists to remove
)

# KNOWN GAP, stated rather than papered over: this is an English word list.
# "ein Kind im Hintergrund" and "a niña in the alley" are not caught, and adding
# them is not free -- German "Kind" collides with English "kind", "nina"/"nino"
# are common names, so a naive multilingual list would refuse ordinary prose and
# fail whole storyboard jobs (this runs on model output across every scene).
# The realistic threat here is model output drifting or a casual attempt, not an
# adversary who controls the input and knows the list; for that, English coverage
# plus the normalisation above is effective. Revisit with a classifier, not more
# words, if that threat model ever changes.

_SINGLE = tuple(t for t in MINOR_TERMS if " " not in t)
_PHRASES = tuple(t for t in MINOR_TERMS if " " in t)

# CLOSED list, enumerated against all 75,145 words in /usr/share/dict/words --
# not against this project's corpus, which is what made an earlier version
# overfit. Under prefix-on-token matching a false positive requires a real word
# that BEGINS with a blocked term; exactly 64 English words do, and all but
# these are genuine references to minors. That is a bounded, enumerable set,
# unlike the combinatorial word-junction collisions substring matching produced.
# Re-run the dictionary sweep in demo() if MINOR_TERMS ever changes.
#
# Deliberately NOT allowlisted, though they are arguably about adults:
# childish/childishly (describes appearance as often as behaviour), childproof,
# childbearing/childbirth/childcare. Flagging those is the safer error here.
_ALLOW = frozenset({
    "infantry", "infantryman", "infantrymen", "infantries",   # military
    "teeny", "teensy", "teenier", "teeniest", "teensier", "teensiest",
    "nurseryman", "nurserymen",                               # horticulture
    "childless", "childlessness",                             # about adults
})

_LEET = str.maketrans("013456789@$", "oieasgtbgas")

# "12 year old", "16-year-old", "9 yr old" -- digits survive no flattening, so
# this runs on the raw text. Pure-numeric age was the cleanest bypass of a
# word-list filter: it contains no blocked word at all.
_AGE_RE = re.compile(r"\b(\d{1,2})\s*-?\s*(?:year|yr)s?\s*-?\s*old\b")

# Cyrillic and Greek letters that render identically to Latin ones. Folded to
# their Latin twin before the ascii step; without this a single substituted
# character hides any blocked word.
_CONFUSABLES = str.maketrans(
    "абвгдезкмнорстуxхіѕјαβεικνορστυχ",
    "abbrdeskmhopctyxxisjabeikvopctyx",
)


class ContentRefused(ValueError):
    """Terminal refusal: the text references minors.

    A distinct type because it must NEVER be retried. grok.py's generate_storyboard
    retries on ValueError and feeds the failure text back to the model as "fix
    every problem and resend" -- for an ordinary schema complaint that is useful,
    but for this check it would hand the model the block list and ask it to
    rephrase around it. Callers must let this one propagate.
    """


def _normalize(text):
    """Fold away the ways a term can be disguised, WITHOUT joining words.

    Homoglyphs are folded before the ascii encode: NFKD does not relate Cyrillic
    'с' (U+0441) to Latin 'c' -- they are genuinely different letters -- so
    encode(errors="ignore") would simply delete it and turn "сhild" into "hild".
    Leet digits are mapped to letters rather than stripped, or "ch1ld" becomes
    "chld" and matches nothing. The numeric-age regex runs on the raw text first,
    so real digits are not lost here.
    """
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = t.translate(_CONFUSABLES)
    t = t.encode("ascii", "ignore").decode()
    return t.translate(_LEET)


def _tokens(text):
    """Normalized words, with word boundaries PRESERVED.

    An earlier version flattened the whole string to bare letters and substring-
    matched against it. Removing the spaces removed the word boundaries, so any
    two adjacent words could spell a term at their junction. Measured against
    this project's own vocabulary it produced a 20/20 false-positive rate:

        "crane shot above"      -> shot|a       -> "shota"
        "alley between two"     -> be|tween     -> "tween"
        "wet concrete entrance" -> concre|te en -> "teen"
        "halo lighting"         -> ha|lo li     -> "loli"
        "a minor seventh"       -> minor|s      -> "minors"
        "the girl is holding"   -> girl|is h    -> "girlish"

    "shot at" alone would have refused nearly every storyboard, since a shot list
    is what this system generates. Splitting on whitespace first and stripping
    punctuation only WITHIN a token keeps "ch-ild" and "child's" catchable while
    making those junctions impossible.
    """
    words = _normalize(text).split()
    toks = [w for w in (re.sub(r"[^a-z]", "", w) for w in words) if w]
    # "c h i l d" spells a word across single-letter tokens; a run of them is
    # never ordinary prose, so collapse it and check that too.
    out, run = list(toks), []
    for w in toks + [""]:
        if len(w) == 1:
            run.append(w)
            continue
        if len(run) >= 4:
            out.append("".join(run))
        run = []
    return out


def _minor_hits(text):
    """Blocked minor terms / under-18 ages present in text (empty if none)."""
    raw = (text or "").lower()
    hits = []
    m = _AGE_RE.search(raw)
    if m and int(m.group(1)) < 18:
        hits.append(m.group(0).strip())
    toks = [t for t in _tokens(text) if t not in _ALLOW]
    # PREFIX, not substring: a term must start the word. That is what separates
    # "teenage" from "eighteen"/"canteen"/"protein", "shota" from "shot",
    # "tween" from "between", "loli" from "halo", "minors" from "minor",
    # "girlish" from "girl". Suffixes are what morphology adds ("child's",
    # "childlike", "underaged", "lolicon"), so a prefix test still catches those.
    found = {t for t in _SINGLE for tok in toks if tok.startswith(t)}
    joined = " ".join(toks)
    found |= {p for p in _PHRASES if re.search(r"\b" + p.replace(" ", r"\s+"), joined)}
    hits.extend(sorted(found))
    return hits


def _sexualisation_hits(text):
    """T10-26 tripwire terms (lingerie / suggestive / fetish / explicit)."""
    toks = [t for t in _tokens(text) if t not in _ALLOW]
    joined = " ".join(toks)
    hits = {t for t in _SEX_SINGLE for tok in toks if tok.startswith(t)}
    hits |= {p for p in _SEX_PHRASES if re.search(r"\b" + p.replace(" ", r"\s+"), joined)}
    return sorted(hits)


def check_text(text, where="input", *, tier=None, field_kind=None):
    """Refuse text that references minors, except:

    - at g/pg13 (T10-18): depiction is permitted
    - at r with field_kind in lyrics/narrative (T10-18a): mention only;
      the reference must never reach a render prompt

    T10-26 is absolute: a minor reference co-occurring with sexualisation
    (lingerie, suggestive framing, fetish camera language, or explicit
    anatomy/act wording) is refused at every tier, including the allowances
    above.

    Unset tier is xxx via policy_tier (T10-25). Raises ContentRefused
    (terminal).
    """
    tier = policy_tier(tier)
    minors = _minor_hits(text)
    if minors:
        sex = _sexualisation_hits(text)
        if sex:
            raise ContentRefused(
                f"This text sexualises a minor and cannot be used in {where}: "
                f"minor={', '.join(minors)}; sexualisation={', '.join(sex)}. "
                "Non-nude sexualisation of a depicted minor is refused at every "
                "tier; remove the sexualisation or the minor reference.")
    if allows_minor_depiction(tier):
        return text
    if allows_minor_mention(tier, field_kind=field_kind):
        return text
    if not minors:
        return text
    # Prefer the age-specific message when that is the only hit.
    raw = (text or "").lower()
    m = _AGE_RE.search(raw)
    if m and int(m.group(1)) < 18 and len(minors) == 1 and minors[0] == m.group(0).strip():
        raise ContentRefused(
            f"This text specifies an age under 18 ({m.group(0).strip()}) in {where}. "
            "Every character in this pipeline is an adult; remove it and try again.")
    raise ContentRefused(
        f"This text refers to minors and cannot be used in {where}: "
        f"{', '.join(minors)}. Every character in this pipeline is an adult; "
        "remove the reference and try again.")


# T10-20: channels that must never short-circuit escalation (T10-19). Accepted
# as kwargs so a call site that passes them still re-screens fully — presence
# is not a lift. A refusal a determined operator can click through is a
# refusal that will be clicked through.
ESCALATION_OVERRIDE_CHANNELS = frozenset({
    "confirm", "confirmation", "force", "override", "allow_override",
    "operator_confirm", "tier_overrides", "profile", "wording",
    "view_override",
})


def _field_base(field_name):
    """Last token of a where-label: 'scene 1 image_prompt' -> 'image_prompt'."""
    return (field_name or "").strip().lower().rsplit(" ", 1)[-1]


def field_allows_minor_mention(field_name, tier):
    """Whether this field may hold a minor reference at destination tier.

    g/pg13: yes everywhere. r: only MENTION_FIELD_KINDS. xxx/unset: no.
    """
    if allows_minor_depiction(tier):
        return True
    return allows_minor_mention(tier, field_kind=_field_base(field_name))


def screen_escalation(fields, destination_tier):
    """T10-19: re-screen everything the work already contains at destination_tier.

    fields is an iterable of (field_name, text). Raises ContentRefused naming
    the field that blocks and the reference it still holds. g/pg13 destinations
    are a no-op (already locked non-explicit). At r, lyrics/narrative use the
    T10-18a allowance; at xxx (and unset), every field is screened.
    """
    dest = (destination_tier or "").strip().lower()
    if allows_minor_depiction(dest):
        return
    # Unset / unknown → most restrictive (T10-25).
    screen_tier = dest if dest else "xxx"
    for field_name, text in fields or ():
        if not (text or "").strip():
            continue
        where = field_name or "field"
        try:
            check_text(
                text, where, tier=screen_tier,
                field_kind=_field_base(field_name),
            )
        except ContentRefused as e:
            raise ContentRefused(
                f"escalation to {screen_tier!r} blocked by {where}: {e}"
            ) from e


def check_escalation(fields, dest_tier, **_overrides):
    """T10-19 re-screen entry used by T10-20: override kwargs never lift.

    Named channels (tier_overrides, profile, wording, view_override, confirm,
    force, …) are accepted and discarded; they cannot suppress ContentRefused.
    `_overrides` is deliberately unread — presence is not a lift.

    `fields` is a mapping of field name → text (preferred: the refusal names
    the field) or an iterable of texts. Returns True when every field passes
    at the destination tier. Raises ContentRefused (terminal) otherwise.
    """
    del _overrides  # T10-20: no channel reaches the screen below

    if isinstance(fields, dict):
        items = list(fields.items())
    else:
        items = [(f"field[{i}]", t) for i, t in enumerate(fields or ())]
    screen_escalation(items, dest_tier)
    return True


def compose(tier_text=""):
    """Full guardrail for a prompt: tier wording first, PINNED last and always.

    Callers pass whatever tier/style text they want; they cannot suppress PINNED.
    """
    tier_text = (tier_text or "").strip()
    if not tier_text:
        return PINNED
    # Idempotent: callers legitimately pass EITHER raw tier wording or an
    # already-composed guardrail (studio/app.py hands build_refs the output of
    # tiers.compose_guardrail). Without this the clause landed twice in every
    # real prompt.
    #
    # Compare on STRIPPED text. PINNED ends in a trailing space, and the line
    # above strips its own input -- so compose(compose(x)) no longer matched
    # its own output and appended the clause a second time. Every prompt the
    # studio rendered carried it twice; the seam check that exists to catch
    # exactly this was looking for wording PINNED no longer contains.
    if PINNED.strip() in tier_text:
        return tier_text
    return tier_text + " " + PINNED


def strip(text, also=""):
    """Remove any guardrail clause already embedded in storyboard text.

    Older storyboards -- and anything generated before the clause moved into
    code -- carry it inside image_prompt. That text ENUMERATES the forbidden
    terms ("no minors, no children ... no playground, nursery or juvenile
    settings"), so check_text matches it and refuses the scene. The guardrail
    would refuse its own wording and make every legacy file unrenderable.

    `also` is the storyboard's own declared guardrail, if it has one, so a
    third-party file's wording is removed as well as ours.
    """
    text = text or ""
    # PINNED.strip() as well as PINNED: any copy that has been through a
    # .strip() -- stored in a database column, round-tripped through JSON,
    # pasted by hand -- would otherwise survive, and since it ENUMERATES the
    # forbidden terms the very next check_text() call refuses the scene. That
    # is the self-trip that has already cost this project three outages.
    for clause in (PINNED, PINNED.strip(), (also or "").strip()):
        if clause:
            text = text.replace(clause, " ")
    return re.sub(r"\s{2,}", " ", text).strip()


def build_prompt(text, tier_text="", where="prompt", *, tier=None):
    """THE entry point. Every prompt sent to an image or video model goes through
    this one function, and nothing else needs to know how the guardrail works.

        pos = guardrail.build_prompt(pos, tier_wording, tier=tier)

    T10-24: compose first (every user merge is already in `text`, then tier
    wording + PINNED welded last), then screen the FINAL composed string —
    not the field as typed. Callers that screen fragments and merge after
    the screen are checking something else; the send chokepoint re-checks
    the joined user string.

    PINNED and some tier wording enumerate forbidden terms ("no minors, no
    children ...", "never introduce minors or juvenile settings"), so the
    welded guard is peeled before the lexical check — longest clause first,
    or removing PINNED alone would leave the rest of the tier unmatched and
    self-trip. The check still sees every user merge that was composed in.

    Attaching is idempotent, so a storyboard that already carries the clause
    does not get it twice.

    Raises ContentRefused (terminal) if the composed user text references a
    minor, except at g/pg13 where T10-18 permits depiction. build_prompt is
    always a render path: T10-18a's lyrics/narrative allowance never applies
    here.
    """
    text = strip(text)
    guard = compose(tier_text)
    if PINNED.strip() in text:
        composed = text
    else:
        composed = (text + " " + guard).strip()
    # Peel welded policy before screening. Longer clauses first: `guard`
    # contains PINNED, and removing PINNED first would leave tier wording
    # that still names blocked terms (xxx: "never introduce minors...").
    remainder = composed
    for clause in (guard.strip(), guard, PINNED.strip(), PINNED):
        if clause:
            remainder = remainder.replace(clause, " ")
    remainder = re.sub(r"\s{2,}", " ", remainder).strip()
    check_text(remainder, where, tier=tier)
    return composed
