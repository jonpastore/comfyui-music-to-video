"""UIUX §8: Focus is everywhere.

Asserts studio/static/style.css has a real `:focus-visible` rule that applies
to interactive controls (`a`, `button`, `input`, `select`, `textarea`, or a
shared group of them). Mutation arm: strip that rule text from a copy and the
checker fails; the live file still has the rule.

Also loads one rendered page (`/`, `/songs`, or `/playlists`) that includes
those controls and links the stylesheet. TestClient + CSS source parse is
enough — no real browser, no computed-style engine.

docs/UIUX-DEFINITION-AND-STYLE-GUIDE.md §8 "Focus is everywhere."
"""
from __future__ import annotations

import os
import re

from fastapi.testclient import TestClient

import app as appmod

_INTERACTIVE = ("a", "button", "input", "select", "textarea")
_CSS_PATH = os.path.join(os.path.dirname(appmod.__file__), "static", "style.css")


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def focus_visible_rule_covers_interactive(css: str) -> bool:
    """True when CSS has a non-comment `:focus-visible` rule for interactive tags.

    Requires a selector that names at least one of a/button/input/select/textarea
    with `:focus-visible`, and a declaration block that sets outline (or
    outline-color/width). The bare word "focus" in a comment does not pass.
    """
    body = _strip_css_comments(css)
    # Rule blocks: selector { declarations }
    for m in re.finditer(r"([^{}]+)\{([^{}]+)\}", body):
        selector = m.group(1)
        decls = m.group(2)
        if ":focus-visible" not in selector:
            continue
        # Interactive tag (or class that is only button-link) in the selector.
        covers = False
        for tag in _INTERACTIVE:
            # tag:focus-visible or tag.foo:focus-visible or tag:focus-visible,...
            if re.search(rf"(?<![\w-]){tag}(?:\.[A-Za-z0-9_-]+)*:focus-visible", selector):
                covers = True
                break
        if not covers:
            continue
        if re.search(r"(?<![\w-])outline(?:-color|-width|-style|-offset)?\s*:", decls):
            return True
    return False


def _css_without_focus_visible_rules(css: str) -> str:
    """Mutation: drop every non-comment rule whose selector has :focus-visible."""
    parts = []
    pos = 0
    for m in re.finditer(r"/\*.*?\*/", css, flags=re.DOTALL):
        parts.append(("code", css[pos : m.start()]))
        parts.append(("comment", m.group(0)))
        pos = m.end()
    parts.append(("code", css[pos:]))

    rebuilt = []
    for kind, chunk in parts:
        if kind == "comment":
            rebuilt.append(chunk)
            continue
        rebuilt.append(
            re.sub(r"[^{}]*:focus-visible[^{}]*\{[^{}]*\}", "", chunk)
        )
    return "".join(rebuilt)


def test_focus_visible_rule_exists_and_deleting_it_fails():
    """Live CSS has the interactive :focus-visible rule; stripped copy fails.

    Distinctive: a comment containing the word focus does not satisfy the
    checker. Mutation arm deletes rule text from a copy only — style.css is
    unchanged.
    """
    css = open(_CSS_PATH, encoding="utf-8").read()
    assert focus_visible_rule_covers_interactive(css), (
        "style.css must define :focus-visible with outline on a/button/input/"
        "select/textarea (UIUX §5.7 one rule for every interactive control)"
    )

    # Bare "focus" in a comment is not a rule.
    assert not focus_visible_rule_covers_interactive(
        "/* keyboard focus is everywhere */\nbody { color: red; }\n"
    ), "checker must not pass on the word focus in a comment"

    # Selector without a real outline declaration is not enough.
    assert not focus_visible_rule_covers_interactive(
        "button:focus-visible { color: red; }\n"
    ), "checker requires an outline declaration, not any :focus-visible block"

    mutated = _css_without_focus_visible_rules(css)
    assert not focus_visible_rule_covers_interactive(mutated), (
        "mutation arm: after removing :focus-visible rules the checker must go red"
    )
    # Live file still has the rule (we only mutated a copy).
    assert focus_visible_rule_covers_interactive(open(_CSS_PATH, encoding="utf-8").read())


def test_rendered_pages_include_interactive_controls_and_stylesheet():
    """/, /songs, /playlists link style.css and emit interactive elements.

    No browser: presence of tags + stylesheet link is the contract the
    CSS-source check applies to.
    """
    with TestClient(appmod.app) as client:
        pages = {
            "/": client.get("/"),
            "/songs": client.get("/songs"),
            "/playlists": client.get("/playlists"),
        }

    for path, resp in pages.items():
        assert resp.status_code == 200, (path, resp.status_code, resp.text[:300])
        html = resp.text
        assert re.search(
            r'href=["\']/static/style\.css["\']', html
        ), f"{path} must link /static/style.css"
        found = {tag: bool(re.search(rf"<{tag}\b", html, re.I)) for tag in _INTERACTIVE}
        # Nav links + at least one form control family on studio pages.
        assert found["a"], f"{path} has no <a> (nav)"
        assert found["button"] or found["input"] or found["select"] or found["textarea"], (
            f"{path} has no button/input/select/textarea: {found}"
        )
