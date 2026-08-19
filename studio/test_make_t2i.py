"""Flux 2 / Klein / Z-Image graphs for New Image."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import make_t2i  # noqa: E402


def _one(model):
    with tempfile.TemporaryDirectory() as d:
        wf = make_t2i.workflow(model, "a red cube", 896, 1216, 7, "t2i_x")
        path = os.path.join(d, "w.json")
        json.dump(wf, open(path, "w"))
        return wf


def test_flux2_dev_uses_mistral_and_flux_guidance():
    wf = _one("flux2_t2i")
    assert wf["1"]["inputs"]["unet_name"] == "flux2_dev_fp8mixed.safetensors"
    assert wf["2"]["inputs"]["clip_name"].startswith("mistral_3_small_flux2")
    assert wf["2"]["inputs"]["type"] == "flux2"
    assert wf["3"]["inputs"]["vae_name"] == "flux2-vae.safetensors"
    assert wf["5"]["class_type"] == "FluxGuidance"
    assert wf["5"]["inputs"]["guidance"] == 4.0
    assert wf["7"]["class_type"] == "EmptyFlux2LatentImage"
    assert wf["8"]["class_type"] == "Flux2Scheduler"
    assert wf["12"]["class_type"] == "SamplerCustomAdvanced"
    assert wf["14"]["inputs"]["filename_prefix"] == "t2i_x"


def test_flux2_klein_uses_qwen3_and_cfg_guider():
    wf = _one("flux2_klein_t2i")
    assert "klein-4b" in wf["1"]["inputs"]["unet_name"]
    assert wf["2"]["inputs"]["type"] == "flux2"
    assert "qwen_3_4b" in wf["2"]["inputs"]["clip_name"]
    assert wf["6"]["class_type"] == "CFGGuider"
    assert wf["6"]["inputs"]["cfg"] == 1.0
    assert wf["8"]["inputs"]["steps"] == 4


def test_zimage_caps_pixels_and_uses_lumina2():
    wf = _one("z_image_t2i")
    assert wf["1"]["inputs"]["unet_name"] == "z_image_turbo_fp8mix.safetensors"
    assert wf["2"]["inputs"]["type"] == "lumina2"
    assert wf["4"]["class_type"] == "CLIPTextEncodeLumina2"
    assert wf["5"]["class_type"] == "EmptySD3LatentImage"
    w, h = wf["5"]["inputs"]["width"], wf["5"]["inputs"]["height"]
    assert w % 16 == 0 and h % 16 == 0
    assert w * h <= 1024 * 1024
    assert wf["6"]["class_type"] == "KSampler"
    assert wf["6"]["inputs"]["steps"] == 8


def test_unknown_model_refused():
    try:
        make_t2i.workflow("krea_t2i", "x", 64, 64, 1, "p")
    except ValueError as e:
        assert "krea" in str(e)
    else:
        raise AssertionError("krea should not have a local graph")
