"""T5-6: if variant B does not fit, record it in ltx25 notes and ship A.

docs/TRD-5 T5-6: silently dropping the upsampler and calling the same-resolution
pass a two-stage is the defect. A exists, is invoked by --refine, and the
finding lives on CATALOG['ltx25']['notes'].
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import build_song
import models


SCENE = {
    "scene_number": 1, "name": "s", "camera": "wide", "lighting": "neon",
    "video_motion_prompt": "she walks", "negative_prompt": "",
    "duration_guidance": "5 sec", "image_prompt": "a rooftop",
}

_B_NODES = frozenset({"LTXVLatentUpsampler", "LatentUpscaleModelLoader"})


def _classes(wf):
    return {n["class_type"] for n in wf.values()}


def test_t5_6_if_b_does_not_fit_record_it_and_ship_a():
    """Mutation: delete the B-does-not-fit finding from ltx25 notes while
    --refine still has no upsampler → this goes red.
    Mutation: drop the second pass so refine == unrefined → this goes red.
    One variable: B's absence is a recorded finding, not a silent drop.
    """
    notes = " ".join(models.CATALOG["ltx25"]["notes"]).lower()
    plain = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="ltx25")
    refined = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="ltx25",
        refine=True)
    kinds = _classes(refined)
    has_b = bool(kinds & _B_NODES)

    if has_b:
        assert "variant b" not in notes or "does not fit" not in notes, (
            "graph ships B but ltx25 notes still record B as unfit")
        return

    assert "variant b" in notes and "does not fit" in notes, (
        "B is absent from --refine; T5-6 requires that recorded as a "
        "finding in ltx25 notes, not a silent drop")
    assert "variant a" in notes, (
        "A ships; the ltx25 notes must say so")
    assert refined != plain
    extra = set(refined) - set(plain)
    assert extra, "A must be invoked; an identical graph is the silent no-op"
    assert "SplitSigmasDenoise" in kinds
    assert not (kinds & _B_NODES), kinds & _B_NODES
