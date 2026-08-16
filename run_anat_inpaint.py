#!/usr/bin/env python3
"""Inpaint anatomy on a nude sheet. Quality sampler (cfg 2 / 50 / LoRA 0).

fix_ref.build defaults to Lightning 4-step/cfg 1 — negatives inert, mush at
cfg>1. We rewrite the sampler after build.
"""
import json, os, sys, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fix_ref
import guardrail

INSTRUCTION = (
    "In the masked region of image 1 only, draw explicit adult female anatomy "
    "on this same dark charcoal-brown body: defined human vulva with inner and outer labia, "
    "a visible clitoral hood, nipples and areolae. Areolae and labia are a darker "
    "shade of that same skin, clearly drawn. Do not change pose, face, hair, tail, "
    "jewelry, limbs, framing, background or lighting outside the masked region."
)
XXX = (
    "Explicit adult content is permitted. Full nudity, sexual acts between consenting "
    "adults, and graphic sexual imagery are in scope. Keep the same adult character "
    "identity and nightlife world; never introduce minors or juvenile settings."
)
BODY = (
    "Her entire body from shoulders to feet is the same dark charcoal-brown skin as her "
    "face, shoulders and midriff in the reference photographs, warm undertone, not jet black, "
    "uniform on breasts, abdomen, hips, vulva, labia, thighs and feet."
)


def quality_inpaint(image, mask, w, h, seed):
    wf = fix_ref.build("inpaint", image, w, h, seed, INSTRUCTION, XXX, BODY, mask=mask)
    wf["2"]["inputs"]["strength_model"] = 0.0
    wf["12"]["inputs"]["prompt"] = (
        "pink skin, peach skin, tan skin, clothing, featureless crotch, smooth crotch"
    )
    wf["16"]["inputs"].update({
        "steps": 50, "cfg": 2.0, "sampler_name": "dpmpp_2m", "scheduler": "karras",
        "denoise": 1.0, "seed": seed,
    })
    wf["18"] = {"class_type": "SaveImage", "inputs": {
        "images": ["17", 0],
        "filename_prefix": f"anat_inpaint/tense886_s{seed}"}}
    return wf


def main():
    image, mask, outdir, n = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    base = int(sys.argv[5]) if len(sys.argv) > 5 else 843167749
    os.makedirs(outdir, exist_ok=True)
    from PIL import Image
    w, h = Image.open(image).size
    for k in range(n):
        seed = base + k * 137
        wf = quality_inpaint(os.path.basename(image), os.path.basename(mask), w, h, seed)
        path = os.path.join(outdir, f"tense886_s{seed}.json")
        json.dump(wf, open(path, "w"))
        print(path)


if __name__ == "__main__":
    main()
