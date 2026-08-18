"""T5-15: a graph that wires an LTX VAE latent into a WAN node is refused.

docs/TRD-5 §5a / §6: node 21/22 samples and LTXVSeparateAVLatent must
not feed wan22_i2v_low / a wan UNET. build_song.refuse_ltx_latent_into_wan
is the positive half. workflow() and _refine_ltx() call it.

Mutation: accept the handoff (node 21/22 samples → wan22_i2v_low) → red.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import build_song


SCENE = {
    "scene_number": 1, "name": "s", "camera": "wide", "lighting": "neon",
    "video_motion_prompt": "she walks", "negative_prompt": "",
    "duration_guidance": "5 sec", "image_prompt": "a rooftop",
}


def _good_ltx(refine=False):
    return build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "",
        video_model="ltx25", refine=refine)


def _wire_handoff(wf, latent_id):
    """Mutate: feed an LTX latent into a wan22_i2v_low sampler."""
    wf = {k: dict(n, inputs=dict(n.get("inputs") or {})) for k, n in wf.items()}
    wf["40"] = {
        "class_type": "UNETLoader",
        "inputs": {"unet_name": build_song.I2V_LOW, "weight_dtype": "default"},
    }
    wf["41"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["40", 0],
            "seed": 0,
            "steps": 6,
            "cfg": 1.0,
            "sampler_name": "uni_pc",
            "scheduler": "simple",
            "positive": ["3", 0],
            "negative": ["4", 0],
            "latent_image": [latent_id, 0],
            "denoise": 0.25,
        },
    }
    return wf


def test_t5_15_good_ltx_and_wan_graphs_are_accepted():
    build_song.refuse_ltx_latent_into_wan(_good_ltx())
    build_song.refuse_ltx_latent_into_wan(_good_ltx(refine=True))
    wan = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", refine=True)
    build_song.refuse_ltx_latent_into_wan(wan)
    assert any(
        "wan" in str((n.get("inputs") or {}).get("unet_name") or "").lower()
        for n in wan.values())


def test_t5_15_handoff_21_22_to_wan22_i2v_low_is_refused():
    """Mutation: accept the handoff → this goes red."""
    wf = _good_ltx()
    assert wf["21"]["class_type"] == "SamplerCustomAdvanced"
    assert wf["22"]["class_type"] == "LTXVSeparateAVLatent"
    for latent_id in ("21", "22"):
        dirty = _wire_handoff(wf, latent_id)
        with pytest.raises(ValueError, match="T5-15"):
            build_song.refuse_ltx_latent_into_wan(dirty)


def test_t5_15_accepting_the_handoff_is_the_red_mutation():
    """If refuse becomes a no-op, the handoff is accepted and this fails."""
    dirty = _wire_handoff(_good_ltx(), "22")
    try:
        build_song.refuse_ltx_latent_into_wan(dirty)
    except ValueError as e:
        assert "T5-15" in str(e)
        assert "22" in str(e)
        return
    raise AssertionError("accepted LTX latent into wan22_i2v_low")


def test_t5_15_workflow_and_refine_ltx_call_refuse(monkeypatch):
    seen = []
    orig = build_song.refuse_ltx_latent_into_wan

    def spy(wf):
        seen.append(wf)
        return orig(wf)

    monkeypatch.setattr(build_song, "refuse_ltx_latent_into_wan", spy)
    build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="ltx25")
    assert seen, "workflow() must call refuse_ltx_latent_into_wan"
    seen.clear()
    build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "",
        video_model="ltx25", refine=True)
    assert len(seen) >= 2, "_refine_ltx and workflow must both call refuse"
