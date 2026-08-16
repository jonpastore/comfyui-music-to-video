"""UIUX §8: The scales are the only values.

§2.2 is not yet tokenized: style.css has fourteen font-size literals and many
spacing/radius literals outside :root, and :root has colour/elevation/motion
tokens only. This check is a **ratchet**, not a hard token rule:

  1. Parse :root custom properties (any scale tokens that appear later are
     accepted via var(--…)).
  2. Collect font-size / padding|margin|gap / border-radius declarations
     outside :root.
  3. Raw length literals must be either var(--…), an allowlisted exception
     (0, 1px hairlines, auto, 50%, CSS keywords), or a member of today's
     recorded ceiling set.
  4. A *new* distinct literal (not in the ceiling) fails.

Mutation arm: inject `font-size: 3.14159rem` into a copy → red. Live style.css
is not rewritten by this suite.

docs/UIUX-DEFINITION-AND-STYLE-GUIDE.md §8 "The scales are the only values."
"""
from __future__ import annotations

import os
import re
from typing import Iterable

import app as appmod

_CSS_PATH = os.path.join(os.path.dirname(appmod.__file__), "static", "style.css")

# Unavoidable non-scale values. Documented here so the ratchet stays honest
# about what is allowed without being a design token.
_ALLOWLIST = frozenset({
    "0",  # reset / collapse
    "1px",  # hairline used as spacing edge case
    "auto",  # margin centering
    "50%",  # full-circle / half-box radius
    "inherit",
    "initial",
    "unset",
    "none",
    "normal",
})

# Ceiling recorded 2026-08-16 from studio/static/style.css. §2.2 is not yet
# tokenized — do not add values here when new literals appear; tokenize or
# reuse an existing one. Shrinking this set is always fine.
_LITERAL_CEILING = frozenset({
    # font-size (14 distinct, matches §2.2 count)
    "0.66rem",
    "0.7rem",
    "0.72rem",
    "0.75rem",
    "0.78rem",
    "0.8rem",
    "0.85rem",
    "0.9rem",
    "0.95rem",
    "1rem",
    "1.15rem",
    "1.2rem",
    "1.35rem",
    "1.6rem",
    # spacing (padding / margin / gap)
    "-1.25rem",
    "-1px",
    "-4px",
    "-5px",
    "0.05rem",
    "0.1rem",
    "0.15rem",
    "0.2rem",
    "0.25rem",
    "0.3rem",
    "0.35em",
    "0.35rem",
    "0.4rem",
    "0.45rem",
    "0.5rem",
    "0.55rem",
    "0.6rem",
    "0.7rem",
    "0.75rem",
    "0.8rem",
    "0.9rem",
    "1rem",
    "1.2rem",
    "1.25rem",
    "1.5rem",
    "1.75rem",
    "2rem",
    "2px",
    "4px",
    # border-radius (6 distinct, matches §2.2)
    "3px",
    "4px",
    "5px",
    "6px",
    "8px",
    "999px",
})

_PROP_RE = re.compile(
    r"(?P<prop>"
    r"font-size|"
    r"padding(?:-(?:top|right|bottom|left))?|"
    r"margin(?:-(?:top|right|bottom|left))?|"
    r"gap|row-gap|column-gap|"
    r"border-radius|"
    r"border-(?:top|bottom)-(?:left|right)-radius"
    r")\s*:\s*(?P<val>[^;{}]+)",
    re.I,
)

_ATOM_RE = re.compile(
    r"var\(\s*--[a-zA-Z0-9_-]+(?:\s*,[^)]+)?\s*\)"
    r"|[+-]?(?:\d+\.?\d*|\.\d+)(?:px|rem|em|%|vh|vw|ch|ex)?"
    r"|auto|inherit|initial|unset|none|normal|smaller|larger",
    re.I,
)


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _root_block_and_outside(css: str) -> tuple[str, str]:
    """Return (:root body, stylesheet with :root block removed)."""
    body = _strip_css_comments(css)
    m = re.search(r":root\s*\{", body)
    if not m:
        return "", body
    start = m.end()
    depth = 1
    i = start
    while i < len(body) and depth:
        if body[i] == "{":
            depth += 1
        elif body[i] == "}":
            depth -= 1
        i += 1
    return body[start : i - 1], body[: m.start()] + body[i:]


def parse_root_custom_properties(css: str) -> dict[str, str]:
    """Custom properties declared on :root (names include leading --)."""
    root_body, _ = _root_block_and_outside(css)
    out: dict[str, str] = {}
    for m in re.finditer(r"(--[a-zA-Z0-9_-]+)\s*:\s*([^;]+);", root_body):
        out[m.group(1)] = m.group(2).strip()
    return out


def _atoms(val: str) -> Iterable[str]:
    val = re.sub(r"\s*!important\s*$", "", val.strip(), flags=re.I)
    for m in _ATOM_RE.finditer(val):
        yield m.group(0).strip()


def scale_literal_violations(
    css: str,
    *,
    ceiling: frozenset[str] = _LITERAL_CEILING,
    allowlist: frozenset[str] = _ALLOWLIST,
) -> list[str]:
    """Return raw scale literals outside :root that are not var/allow/ceiling.

    Also requires that :root is present (token home). var(--…) always passes
    even when the named token is not yet defined — so future tokenization of
    §5.2 / §5.3 does not need a ceiling edit for each replacement.
    """
    root_props = parse_root_custom_properties(css)
    if not root_props:
        return [":root has no custom properties (token home missing)"]

    _, outside = _root_block_and_outside(css)
    violations: list[str] = []
    seen: set[str] = set()
    for m in _PROP_RE.finditer(outside):
        prop = m.group("prop").lower()
        for atom in _atoms(m.group("val")):
            if atom.lower().startswith("var("):
                continue
            if atom in allowlist or atom.lower() in allowlist:
                continue
            # Normalize case on keywords already handled; lengths are lowercase.
            if atom in ceiling:
                continue
            key = f"{prop}:{atom}"
            if key in seen:
                continue
            seen.add(key)
            violations.append(key)
    return violations


def scale_literals_used(css: str) -> frozenset[str]:
    """Distinct raw scale literals outside :root (excluding allowlist/var)."""
    _, outside = _root_block_and_outside(css)
    found: set[str] = set()
    for m in _PROP_RE.finditer(outside):
        for atom in _atoms(m.group("val")):
            if atom.lower().startswith("var("):
                continue
            if atom in _ALLOWLIST or atom.lower() in _ALLOWLIST:
                continue
            found.add(atom)
    return frozenset(found)


def test_root_is_parsed_for_scale_token_home():
    """:root is present and is the place scale tokens would live.

    Today it holds colour/elevation/motion only — no --text-* / --space-* /
    --radius-* yet (§2.2 / §5.2 / §5.3 not tokenized). The checker still
    parses them so a later hard token rule can promote without a rewrite.
    """
    css = open(_CSS_PATH, encoding="utf-8").read()
    props = parse_root_custom_properties(css)
    assert props, ":root custom properties missing"
    assert "--bg" in props and "--motion-standard" in props
    scale_named = [
        n for n in props
        if n.startswith(("--text-", "--space-", "--radius-", "--fs-", "--gap-"))
    ]
    # Honest: scale tokens are not in :root yet.
    assert scale_named == [], (
        f"unexpected scale tokens already present: {scale_named} — "
        "if intentional, promote this suite from ratchet to hard token rule"
    )


def test_scale_literals_stay_within_ceiling():
    """No new font-size / spacing / radius literal outside the recorded ceiling.

    §2.2 is not yet tokenized; this is a ratchet. Replacing a ceiling member
    with var(--…) shrinks usage (fine). Adding 3.14159rem fails.
    """
    css = open(_CSS_PATH, encoding="utf-8").read()
    used = scale_literals_used(css)
    assert used, "expected existing scale literals in style.css"
    assert used <= _LITERAL_CEILING, (
        "new scale literal(s) outside the UIUX §8 ceiling (tokenize or reuse): "
        f"{sorted(used - _LITERAL_CEILING)}"
    )
    violations = scale_literal_violations(css)
    assert violations == [], (
        "scale declaration(s) use a raw value not in var()/allowlist/ceiling: "
        f"{violations}"
    )


def test_new_font_size_literal_fails_mutation():
    """Distinctive mutation: inject font-size: 3.14159rem into a copy → red.

    Live style.css is only read; the probe is appended to an in-memory copy.
    """
    css = open(_CSS_PATH, encoding="utf-8").read()
    assert scale_literal_violations(css) == []

    probe = "\n/* uiux-scale-mutation-probe */\n.__uiux_scale_probe { font-size: 3.14159rem; }\n"
    mutated = css + probe
    violations = scale_literal_violations(mutated)
    assert any("3.14159rem" in v for v in violations), (
        f"mutation arm must flag 3.14159rem; got {violations!r}"
    )
    # Live file unchanged.
    assert scale_literal_violations(open(_CSS_PATH, encoding="utf-8").read()) == []


def test_var_token_and_allowlist_pass():
    """var(--…) and allowlisted atoms are not ceiling violations."""
    sample = """
    :root { --bg: #000; --text-sm: 0.875rem; }
    .a { font-size: var(--text-sm); padding: 0; margin: auto; border-radius: 50%; }
    .b { gap: 1px; }
    """
    assert scale_literal_violations(sample) == []
    # Unknown raw rem still fails even with a token home.
    bad = sample + ".c { font-size: 9.99rem; }\n"
    v = scale_literal_violations(bad)
    assert any("9.99rem" in x for x in v), v
