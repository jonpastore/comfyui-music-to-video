#!/usr/bin/env python3
"""Write ComfyUI API graphs for New Image exploration models.

Qwen-Image-Edit stays in make_anchor.py. This file is Flux 2 Dev, Flux 2 Klein,
Z-Image Turbo, and Krea 2 Turbo OSS — empty-latent text-to-image only.
Identity sheets stay Qwen. Mage Mango/Guava/Kiwi are not local graphs.

Official node lists (ComfyUI templates on cerberus, 2026-08-19):
  Flux 2 Dev: UNET + CLIP(flux2/mistral) + VAE + CLIPTextEncode + FluxGuidance
              + EmptyFlux2LatentImage + Flux2Scheduler + SamplerCustomAdvanced
  Flux 2 Klein: same latent/scheduler, CLIP is qwen_3_4b type=flux2, CFGGuider
  Z-Image: UNET + CLIP(lumina2/qwen_3_4b) + ae VAE + CLIPTextEncodeLumina2
           + EmptySD3LatentImage + KSampler
"""
import argparse
import json
import os
import random
import sys


SPECS = {
    "flux2_t2i": {
        "unet": "flux2_dev_fp8mixed.safetensors",
        "clip": "mistral_3_small_flux2_fp8.safetensors",
        "clip_type": "flux2",
        "vae": "flux2-vae.safetensors",
        "kind": "flux2",
        "steps": 20,
        "guidance": 4.0,
        "sampler": "euler",
    },
    "flux2_klein_t2i": {
        "unet": "flux-2-klein-4b-fp8.safetensors",
        "clip": "qwen_3_4b_fp8_mixed.safetensors",
        "clip_type": "flux2",
        "vae": "flux2-vae.safetensors",
        "kind": "klein",
        "steps": 4,
        "cfg": 1.0,
        "sampler": "euler",
    },
    "z_image_t2i": {
        "unet": "z_image_turbo_fp8mix.safetensors",
        "clip": "qwen_3_4b_fp8_mixed.safetensors",
        "clip_type": "lumina2",
        "vae": "ae.safetensors",
        "kind": "zimage",
        "steps": 8,
        "cfg": 1.0,
        "sampler": "euler",
        "scheduler": "simple",
    },
    "krea2_t2i": {
        "unet": "krea2_turbo_fp8_scaled.safetensors",
        "clip": "qwen3vl_4b_fp8_scaled.safetensors",
        "clip_type": "krea2",
        "vae": "qwen_image_vae.safetensors",
        "kind": "krea",
        "steps": 8,
        "cfg": 1.0,
        "sampler": "euler",
        "scheduler": "simple",
    },
}


def snap16(n):
    return max(16, int(n) // 16 * 16)


def size_for(kind, width, height):
    w, h = snap16(width), snap16(height)
    if kind == "zimage" and w * h > 1024 * 1024:
        scale = (1024 * 1024 / float(w * h)) ** 0.5
        w, h = snap16(int(w * scale)), snap16(int(h * scale))
    return w, h


def _flux2(spec, prompt, w, h, seed, prefix, style_lora="", style_lora_strength=1.0):
    wf = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": spec["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": spec["clip"], "type": spec["clip_type"]}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": spec["vae"]}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["2", 0]}},
        "7": {"class_type": "EmptyFlux2LatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "8": {"class_type": "Flux2Scheduler",
              "inputs": {"steps": spec["steps"], "width": w, "height": h}},
        "9": {"class_type": "KSamplerSelect",
              "inputs": {"sampler_name": spec["sampler"]}},
        "10": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "12": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["10", 0], "guider": ["6", 0],
                          "sampler": ["9", 0], "sigmas": ["8", 0],
                          "latent_image": ["7", 0]}},
        "13": {"class_type": "VAEDecode",
               "inputs": {"samples": ["12", 0], "vae": ["3", 0]}},
        "14": {"class_type": "SaveImage",
               "inputs": {"images": ["13", 0], "filename_prefix": prefix}},
    }
    model = ["1", 0]
    if style_lora:
        wf["1b"] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": ["1", 0], "lora_name": style_lora,
                               "strength_model": float(style_lora_strength)}}
        model = ["1b", 0]
    if spec["kind"] == "flux2":
        wf["5"] = {"class_type": "FluxGuidance",
                   "inputs": {"conditioning": ["4", 0],
                              "guidance": float(spec["guidance"])}}
        wf["6"] = {"class_type": "BasicGuider",
                   "inputs": {"model": model, "conditioning": ["5", 0]}}
    else:
        wf["4n"] = {"class_type": "CLIPTextEncode",
                    "inputs": {"text": "", "clip": ["2", 0]}}
        wf["6"] = {"class_type": "CFGGuider",
                   "inputs": {"model": model, "positive": ["4", 0],
                              "negative": ["4n", 0],
                              "cfg": float(spec["cfg"])}}
    return wf


def _krea(spec, prompt, w, h, seed, prefix, style_lora="", style_lora_strength=1.0):
    """Official Krea 2 Turbo t2i: EmptyLatentImage + KSampler 8/cfg1/euler/simple."""
    wf = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": spec["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": spec["clip"], "type": spec["clip_type"]}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": spec["vae"]}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyLatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "seed": seed, "steps": spec["steps"],
                         "cfg": float(spec["cfg"]), "sampler_name": spec["sampler"],
                         "scheduler": spec["scheduler"], "positive": ["4", 0],
                         "negative": ["5", 0], "latent_image": ["6", 0],
                         "denoise": 1.0}},
        "8": {"class_type": "VAEDecode",
              "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }
    if style_lora:
        wf["1b"] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": ["1", 0], "lora_name": style_lora,
                               "strength_model": float(style_lora_strength)}}
        wf["7"]["inputs"]["model"] = ["1b", 0]
    return wf


def _zimage(spec, prompt, w, h, seed, prefix, style_lora="", style_lora_strength=1.0):
    wf = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": spec["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": spec["clip"], "type": spec["clip_type"]}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": spec["vae"]}},
        "4": {"class_type": "CLIPTextEncodeLumina2",
              "inputs": {"system_prompt": "superior", "user_prompt": prompt,
                         "clip": ["2", 0]}},
        "5": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "seed": seed, "steps": spec["steps"],
                         "cfg": float(spec["cfg"]), "sampler_name": spec["sampler"],
                         "scheduler": spec["scheduler"], "positive": ["4", 0],
                         "negative": ["4", 0], "latent_image": ["5", 0],
                         "denoise": 1.0}},
        "7": {"class_type": "VAEDecode",
              "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage",
              "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
    }
    if style_lora:
        wf["1b"] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": ["1", 0], "lora_name": style_lora,
                               "strength_model": float(style_lora_strength)}}
        wf["6"]["inputs"]["model"] = ["1b", 0]
    return wf


def workflow(model, prompt, width, height, seed, prefix, style_lora="",
             style_lora_strength=1.0):
    if model not in SPECS:
        raise ValueError(f"unknown t2i model {model!r}")
    spec = SPECS[model]
    w, h = size_for(spec["kind"], width, height)
    if spec["kind"] == "zimage":
        return _zimage(spec, prompt, w, h, seed, prefix, style_lora,
                       style_lora_strength)
    if spec["kind"] == "krea":
        return _krea(spec, prompt, w, h, seed, prefix, style_lora,
                     style_lora_strength)
    return _flux2(spec, prompt, w, h, seed, prefix, style_lora,
                  style_lora_strength)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=sorted(SPECS))
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--prefix", default="t2i")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--style-lora", default="")
    ap.add_argument("--style-lora-strength", type=float, default=1.0)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    base = args.seed if args.seed is not None else random.randint(1, 2**31 - 1)
    for i in range(max(1, args.n)):
        seed = base + i
        name = f"{args.prefix}_s{seed}.json"
        wf = workflow(args.model, args.prompt, args.width, args.height, seed,
                      args.prefix, args.style_lora, args.style_lora_strength)
        dest = os.path.join(args.outdir, name)
        with open(dest, "w") as f:
            json.dump(wf, f)
        print(dest)


if __name__ == "__main__":
    sys.exit(main() or 0)
