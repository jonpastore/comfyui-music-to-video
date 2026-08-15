"""T10-24: screening runs on the FINAL composed string after every merge
and after PINNED is welded — not on the field as typed.

docs/TRD-10 T10-24. Field-as-typed checks (T10-19a) decide what may be
*entered*. This decides what may be *sent*. A check that runs only on
fragments pre-composition misses phrases that form when those fragments
are joined (shot + image_prompt, cast clause, template pieces, motion
locks). The send chokepoint is guardrail.build_prompt.

Asserted through build_prompt and the build_refs / build_song workflows
that call it after their own merges.
"""
import pytest

import build_refs
import build_song
import guardrail
import tiers


# Fragments that each pass field-as-typed screening; their join forms
# the blocked phrase "young girl".
LEFT = "portrait of a young"
RIGHT = "girl under soft key light"
MERGED = f"{LEFT} {RIGHT}"


def test_t10_24_field_as_typed_passes_each_fragment():
    """The field screen alone is not the send gate."""
    assert guardrail.check_text(LEFT, "field") == LEFT
    assert guardrail.check_text(RIGHT, "field") == RIGHT


def test_t10_24_build_prompt_refuses_merged_user_fragments():
    """Joined user text is what the send path screens (T10-24)."""
    assert guardrail.check_text(LEFT, "shot") == LEFT
    assert guardrail.check_text(RIGHT, "image_prompt") == RIGHT
    with pytest.raises(guardrail.ContentRefused) as err:
        guardrail.build_prompt(MERGED, "No nudity.", "composed send")
    msg = str(err.value).lower()
    assert "young girl" in msg or "girl" in msg or "minor" in msg, msg


def test_t10_24_clean_compose_still_welds_pinned():
    """Positive half: clean compose screens, welds PINNED, does not self-trip."""
    out = guardrail.build_prompt(
        "a woman stands in neon rain", "No nudity.", "clean send")
    assert "woman stands" in out
    assert guardrail.PINNED.strip() in out
    assert out.rstrip().endswith(guardrail.PINNED.strip())


def test_t10_24_xxx_tier_wording_does_not_self_trip():
    """xxx tier enumerates 'minors'/'juvenile'; peel the weld, not refuse clean text."""
    guard = tiers.compose_guardrail("xxx")
    assert "minors" in guard.lower() or "juvenile" in guard.lower()
    out = guardrail.build_prompt(
        "a woman stands in neon rain", guard, "xxx send", tier="xxx")
    assert "woman stands" in out
    assert guardrail.PINNED.strip() in out


def test_t10_24_build_refs_screens_composed_not_field_alone():
    """build_refs merges shot + image_prompt before the send screen."""
    assert guardrail.check_text(LEFT, "shot") == LEFT
    assert guardrail.check_text(RIGHT, "image_prompt") == RIGHT
    scene = {
        "scene_number": 1,
        "image_prompt": RIGHT,
        "negative_prompt": "",
    }
    with pytest.raises(guardrail.ContentRefused):
        build_refs.workflow(
            scene, "a.png", None, "empty", 1280, 720, 7000,
            LEFT, "")


def test_t10_24_build_song_screens_composed_motion_merge():
    """build_song merges motion/camera/locks then screens the final string."""
    scene = {
        "scene_number": 1,
        "image_prompt": "alley at night",
        "video_motion_prompt": MERGED,
        "camera": "wide",
        "lighting": "neon",
        "length_seconds": 5,
    }
    with pytest.raises(guardrail.ContentRefused):
        build_song.workflow(
            0, scene, "c.png", "song.mp3", "char", "world", "",
            video_model="ltx25")


def test_t10_24_g_tier_still_allows_depiction():
    """T10-18 is unchanged: locked g/pg13 may depict; the screen still runs."""
    out = guardrail.build_prompt(
        "a 7 year old child dancing", "No nudity.", "niece", tier="g")
    assert "child" in out
    assert guardrail.PINNED.strip() in out
