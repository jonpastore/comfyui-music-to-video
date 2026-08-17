"""Every dialog dismisses with the shared modal_close icon."""
import os
import re

import app as appmod

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "templates")

_CLOSE_TEXT = re.compile(
    r"""onclick=["']this\.closest\(['\"]dialog['\"]\)\.close\(\)["']\s*>\s*Close\s*<""")


def test_modal_close_macro_is_the_icon():
    src = open(os.path.join(TEMPLATES, "_macros.html"), encoding="utf-8").read()
    assert "macro modal_close" in src
    assert 'class="modal-close"' in src
    assert "aria-label=\"Close\"" in src
    assert "<svg" in src


def test_no_dialog_uses_the_word_close():
    offenders = []
    for name in os.listdir(TEMPLATES):
        if not name.endswith(".html"):
            continue
        text = open(os.path.join(TEMPLATES, name), encoding="utf-8").read()
        if _CLOSE_TEXT.search(text):
            offenders.append(name)
    assert offenders == [], offenders


def test_base_lightboxes_use_modal_close():
    src = open(os.path.join(TEMPLATES, "base.html"), encoding="utf-8").read()
    assert src.count("modal_close()") == 3
    assert "lightbox-close" not in src


def test_css_modal_close_is_not_a_circle():
    css = open(os.path.join(HERE, "static", "style.css"), encoding="utf-8").read()
    block = re.search(r"button\.modal-close\s*\{[^}]+\}", css)
    assert block, "button.modal-close rule missing"
    assert "50%" not in block.group(0)
    assert "transparent" in block.group(0)
