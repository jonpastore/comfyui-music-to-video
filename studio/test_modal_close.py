"""Every dialog dismisses with the shared modal_close icon."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "templates")

_CLOSE_TEXT = re.compile(
    r"""onclick=["']this\.closest\(['\"]dialog['\"]\)\.close\(\)["']\s*>\s*Close\s*<""")


def test_modal_close_macro_is_the_icon():
    src = open(os.path.join(TEMPLATES, "_macros.html"), encoding="utf-8").read()
    assert "macro modal_close" in src
    assert 'class="modal-close"' in src
    assert "aria-label=\"Close\"" in src
    assert 'viewBox="0 0 24 24"' in src
    assert "glyph_edit" in src
    assert "glyph_delete" in src


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
    assert src.count("modal_close()") >= 6
    assert 'id="tip-modal"' in src
    assert 'id="pose-brief"' in src
    assert 'id="media-player"' in src
    assert "lightbox-close" not in src


def test_tip_modal_close_is_on_the_right():
    src = open(os.path.join(TEMPLATES, "base.html"), encoding="utf-8").read()
    bar = src.split('id="tip-modal"', 1)[1].split("</dialog>", 1)[0]
    assert "lightbox-spacer" in bar
    assert bar.index("lightbox-spacer") < bar.index("modal_close")


def test_qc_tag_button_is_not_a_primary():
    css = open(os.path.join(HERE, "static", "style.css"), encoding="utf-8").read()
    block = re.search(r"button\.qc-tag\s*\{[^}]+\}", css)
    assert block, "button.qc-tag rule missing"
    assert "transparent" in block.group(0)
    assert "padding: 0" in block.group(0)
    hover = re.search(
        r"button\.qc-tag:hover:not\(:disabled\)[^\{]*\{[^}]+\}", css)
    assert hover, "button.qc-tag hover reset missing"
    assert "transparent" in hover.group(0)
    card = re.search(r"\.candidate p\.qc-tag\s*\{[^}]+\}", css)
    assert card, "candidate qc-tag height rule missing"
    assert "overflow-y: auto" in card.group(0)
    assert "height:" in card.group(0)


def test_clip_preview_has_nav_and_repair_actions():
    src = open(os.path.join(TEMPLATES, "base.html"), encoding="utf-8").read()
    assert "media_nav_prev" in src and "media_nav_next" in src
    assert 'id="clip-rerender"' in src
    assert 'id="clip-edit-motion"' in src
    assert 'id="clip-open-still"' in src
    assert "lightbox-spacer" in src


def test_image_viewers_share_still_stage_chevrons():
    macros = open(os.path.join(TEMPLATES, "_macros.html"), encoding="utf-8").read()
    assert "macro media_nav_prev" in macros
    assert "media-nav-prev" in macros
    anchors = open(os.path.join(TEMPLATES, "anchors.html"), encoding="utf-8").read()
    assert 'id="anchor-lightbox"' in anchors
    assert "still-stage" in anchors
    assert "media_nav_prev" in anchors
    base = open(os.path.join(TEMPLATES, "base.html"), encoding="utf-8").read()
    assert "still-stage" in base
    css = open(os.path.join(HERE, "static", "style.css"), encoding="utf-8").read()
    assert ".clip-stage, .still-stage" in css
    playlists = open(os.path.join(TEMPLATES, "playlists.html"), encoding="utf-8").read()
    assert "lightbox-pair" in playlists
    assert "media_nav_prev" in playlists
    assert "lightbox-pair-pos" in playlists


def test_ref_preview_close_is_on_the_bar():
    src = open(os.path.join(TEMPLATES, "base.html"), encoding="utf-8").read()
    bar = src.split('id="ref-preview"', 1)[1].split("</dialog>", 1)[0]
    assert "modal_close" in bar


def test_css_modal_close_is_not_a_circle():
    css = open(os.path.join(HERE, "static", "style.css"), encoding="utf-8").read()
    block = re.search(r"button\.modal-close\s*\{[^}]+\}", css)
    assert block, "button.modal-close rule missing"
    assert "50%" not in block.group(0)
    assert "transparent" in block.group(0)
