"""T7-5: portrait is a head-and-shoulders crop measured on the image.

String omit of BACKDROP's "full body head to toe" is already covered by
test_portrait_and_seated_drop_the_standing_fullbody_backdrop in test_app.py.
That half is one-sided: absence of a conflicting string. The positive half is
this file — the portrait crop must beat a head-to-toe full-body figure when
measured on pixels, and a full-body sheet asked as portrait FLAGs.

docs/TRD-7 T7-5. No GPU claim. Synthetic fixtures only.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import make_anchor
import qc


WALL = (140, 140, 140)
FIGURE = (18, 18, 18)


def _figure_band(path, y0, y1, size=(96, 128), wall=WALL, figure=FIGURE):
    """Dark figure spanning vertical fraction [y0, y1) on a mid-grey wall."""
    from PIL import Image
    w, h = size
    im = Image.new("RGB", (w, h), wall)
    top = max(0, int(h * y0))
    bot = min(h, int(h * y1))
    x0, x1 = int(w * 0.25), int(w * 0.75)
    for y in range(top, bot):
        for x in range(x0, x1):
            im.putpixel((x, y), figure)
    im.save(path)
    return str(path)


def _by_check(findings, name):
    return [f for f in findings if f["check"] == name]


def test_t7_5_tests_do_not_skip():
    """A skip call is not a reading."""
    src = open(__file__, encoding="utf-8").read()
    assert "pytest" + ".skip(" not in src
    assert "pytest" + ".mark.skip" not in src


def test_t7_5_string_omit_still_holds():
    """String half stays green: portrait must not sit beside head-to-toe."""
    a = make_anchor.anchor_from({})
    port = make_anchor.prompt_for("portrait", a)
    assert "full body head to toe inside the frame" not in port
    assert "head and shoulders" in port
    assert "stands upright and unsupported" not in port


def test_t7_5_measure_subject_bottom_raises_on_missing():
    """No pixels is NOT MEASURED, never 0.0."""
    with pytest.raises(ValueError, match="NOT MEASURED"):
        qc.measure_subject_bottom("/no/such/portrait.png")


def test_t7_5_head_and_shoulders_scores_above_full_body(tmp_path):
    """Portrait crop (top band) beats head-to-toe (full height) on the image.

    Mutation: metric that returns a constant or inverts the ranking → red.
    """
    portrait = _figure_band(tmp_path / "portrait.png", 0.05, 0.45)
    fullbody = _figure_band(tmp_path / "fullbody.png", 0.05, 0.95)
    p_score = qc.portrait_crop_score(portrait)
    f_score = qc.portrait_crop_score(fullbody)
    assert p_score > f_score, (p_score, f_score)
    report = qc.t7_5_portrait_crop_differential(portrait, fullbody)
    assert report["held"] is True, report
    assert report["portrait"] > report["fullbody"], report
    assert report["threshold"] is None


def test_t7_5_head_to_toe_must_not_win(tmp_path):
    """A full-body figure is not a portrait crop. Head-to-toe loses.

    Mutation: check that always PASSes, or ranks fullbody above portrait → red.
    """
    portrait = _figure_band(tmp_path / "p.png", 0.05, 0.40)
    fullbody = _figure_band(tmp_path / "f.png", 0.05, 0.95)

    p_hit = _by_check(
        qc.check_portrait_crop(portrait, {"view": "portrait"}),
        qc.PORTRAIT_CROP)
    assert p_hit and p_hit[0]["verdict"] == qc.PASS, p_hit

    f_hit = _by_check(
        qc.check_portrait_crop(fullbody, {"view": "portrait"}),
        qc.PORTRAIT_CROP)
    assert f_hit and f_hit[0]["verdict"] == qc.FLAG, f_hit
    assert float(f_hit[0]["measured"]) > float(p_hit[0]["measured"]), (
        f_hit[0], p_hit[0])

    # Ranking: portrait crop wins; fullbody loses
    assert qc.t7_5_portrait_crop_differential(portrait, fullbody)["held"] is True
    # Reversed paths: head-to-toe does not win
    assert qc.t7_5_portrait_crop_differential(fullbody, portrait)["held"] is False


def test_t7_5_unasked_view_emits_no_crop_finding(tmp_path):
    """Front sheets are full-body by design; the check is opt-in on portrait."""
    fullbody = _figure_band(tmp_path / "front.png", 0.05, 0.95)
    found = qc.check_portrait_crop(fullbody, {"view": "front"})
    assert found == []
    found = qc.check_image(fullbody, {})
    assert _by_check(found, qc.PORTRAIT_CROP) == []


def test_t7_5_portrait_view_reaches_check_image(tmp_path):
    """check_image with view=portrait runs the crop measurement."""
    fullbody = _figure_band(tmp_path / "bad.png", 0.05, 0.95)
    found = qc.check_image(fullbody, {"view": "portrait"})
    hit = _by_check(found, qc.PORTRAIT_CROP)
    assert hit and hit[0]["verdict"] == qc.FLAG, found


def test_t7_5_portrait_prefers_square_size_over_fullbody_frame():
    """896x1216 is a standing full-body frame; portrait defaults to 1024x1024.

    A head-and-shoulders framing inside 896x1216 renders a distant figure
    (docs/TRD-7 T7-5 / T7-12). size_for owns the default so app.py is not a
    second table.
    """
    assert make_anchor.size_for("portrait") == "1024x1024"
    assert make_anchor.size_for("portrait_nude") == "1024x1024"
    assert make_anchor.size_for("portrait", None) == "1024x1024"
    assert make_anchor.size_for("portrait", "") == "1024x1024"
    assert make_anchor.size_for("portrait", "896x1216") == "1024x1024"
    # Operator-chosen non-default wins
    assert make_anchor.size_for("portrait", "1216x832") == "1216x832"
    # Full-body views keep the standing frame
    assert make_anchor.size_for("front") == "896x1216"
    assert make_anchor.size_for("front", "896x1216") == "896x1216"
    assert make_anchor.size_for("seated") == "896x1216"
