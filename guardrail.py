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


def allows_minor_depiction(tier):
    """True only at the locked non-explicit tiers named by T10-18."""
    return (tier or "").strip().lower() in LOCKED_DEPICT_TIERS

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


def check_text(text, where="input", *, tier=None):
    """Refuse text that references minors, except at g/pg13 (T10-18).

    A song for a child, and a video for it, is a first-class thing this
    studio can make — but only where explicit content cannot be reached.
    Unset tier is xxx (T10-25). Raises ContentRefused (terminal).
    """
    if allows_minor_depiction(tier):
        return text
    raw = (text or "").lower()
    m = _AGE_RE.search(raw)
    if m and int(m.group(1)) < 18:
        raise ContentRefused(
            f"This text specifies an age under 18 ({m.group(0).strip()}) in {where}. "
            "Every character in this pipeline is an adult; remove it and try again.")

    toks = [t for t in _tokens(text) if t not in _ALLOW]
    # PREFIX, not substring: a term must start the word. That is what separates
    # "teenage" from "eighteen"/"canteen"/"protein", "shota" from "shot",
    # "tween" from "between", "loli" from "halo", "minors" from "minor",
    # "girlish" from "girl". Suffixes are what morphology adds ("child's",
    # "childlike", "underaged", "lolicon"), so a prefix test still catches those.
    hits = {t for t in _SINGLE for tok in toks if tok.startswith(t)}
    joined = " ".join(toks)
    hits |= {p for p in _PHRASES if re.search(r"\b" + p.replace(" ", r"\s+"), joined)}
    hits = sorted(hits)
    if hits:
        raise ContentRefused(
            f"This text refers to minors and cannot be used in {where}: "
            f"{', '.join(hits)}. Every character in this pipeline is an adult; "
            "remove the reference and try again.")
    return text


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

    Screens the text first, then attaches the clause -- that order matters,
    because PINNED itself enumerates the forbidden terms ("no minors, no
    children ..."), so checking afterwards would match our own wording and refuse
    every prompt. Attaching is idempotent, so a storyboard that already carries
    the clause does not get it twice.

    Raises ContentRefused (terminal) if the text references a minor, except at
    g/pg13 where T10-18 permits depiction.
    """
    # Strip our own clause BEFORE screening. PINNED enumerates the forbidden
    # terms, so any text already carrying it (a storyboard generated before the
    # clause moved into code, or one that echoed it) matches the filter and gets
    # refused. Doing this here rather than only in build_song.normalize() means a
    # caller that forgets to normalize is still safe -- reroll_refs.py did exactly
    # that and refused every scene.
    text = strip(text)
    check_text(text, where, tier=tier)
    # stripped comparison, same reason as compose(): a trailing space must not
    # decide whether the clause is attached twice
    return text if PINNED.strip() in text else (text + " " + compose(tier_text)).strip()
