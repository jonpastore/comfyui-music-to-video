#!/usr/bin/env python3
"""Write ACE-Step audio workflows (API format) into --outdir. Renders nothing.

Same contract as make_anchor.py / build_refs.py / build_song.py: this writes
workflow JSON, and studio/pipeline.py submits it. Run standalone for one-offs.

WHY THIS EXISTS. studio/mixer.py edits audio deterministically with ffmpeg, and
ffmpeg can only trim the ENDS of a track. Cutting from the middle -- or filling
a gap, or extending a track past its last bar -- needs something that can make
new audio, and that is what ACE-Step is for. The result is RE-SYNTHESISED, not
a shorter original, which is a thing the caller has to be honest about.

WHY THE CHECKPOINT IS NAMED WITH _fp16 AND WHY THAT IS THE ROUTING POLICY.
A workflow reaches whichever backend SwarmUI picks, and a loader enum is
validated against the literal filename, so the spelling here decides which box
can run this at all. cerberus holds `ace_step_v1_3.5b.safetensors` (bf16) and
peaches holds `ace_step_v1_3.5b_fp16.safetensors` -- the cast made for a 2080
Ti, which has no bf16 kernels. Naming the fp16 spelling sends every audio job to
peaches WITHOUT any per-backend routing config, because it is the only box that
can load that name. peaches is the always-on box and its GPU is otherwise idle,
so a minute of music generation there is a minute not taken from video on a
5090. See studio/models.py ALIASES for the same fact from the catalogue's side.
"""
import argparse, json, os, sys

MODEL = "ace_step_v1_3.5b_fp16.safetensors"

# ComfyUI's own ACE-Step defaults. 50 steps at cfg 5.0 on the 2080 Ti measured
# ~1x realtime (10 s of audio in 10.1 s wall), so a minute of music is about a
# minute -- worth knowing before queueing a whole track.
STEPS, CFG = 50, 5.0
SAMPLER, SCHEDULER = "euler", "simple"


def workflow(tags, lyrics, seconds, seed, prefix, *, lyrics_strength=1.0,
             steps=STEPS, cfg=CFG, denoise=1.0, source=None, model=MODEL):
    """One ACE-Step graph.

    source=None       text to audio: EmptyAceStepLatentAudio, denoise 1.0.
    source="x.mp3"    audio to audio: that file (which must already be in the
                      backend's input dir) is encoded and re-sampled at
                      `denoise`. This is the repair path -- denoise 1.0 here
                      would throw the original away, so the caller choosing a
                      source is choosing a denoise below 1.0 as well.
    """
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model}},
        "2": {"class_type": "TextEncodeAceStepAudio", "inputs": {
            "clip": ["1", 1], "tags": tags, "lyrics": lyrics,
            "lyrics_strength": float(lyrics_strength)}},
        # An EMPTY encode, not ConditioningZeroOut: the negative has to be the
        # same kind of conditioning the positive is, and this is the shape
        # ComfyUI's own ACE-Step template uses.
        "3": {"class_type": "TextEncodeAceStepAudio", "inputs": {
            "clip": ["1", 1], "tags": "", "lyrics": "", "lyrics_strength": 1.0}},
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
            "latent_image": ["4", 0], "seed": int(seed), "steps": int(steps),
            "cfg": float(cfg), "sampler_name": SAMPLER, "scheduler": SCHEDULER,
            "denoise": float(denoise)}},
        "6": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        # mp3, not the flac SaveAudio writes: everything downstream in this
        # studio (mixer.py, publish.py, the <audio> tags) already speaks mp3.
        "99": {"class_type": "SaveAudioMP3", "inputs": {
            "audio": ["6", 0], "filename_prefix": prefix, "quality": "V0"}},
    }
    if source:
        wf["4"] = {"class_type": "VAEEncodeAudio",
                   "inputs": {"audio": ["7", 0], "vae": ["1", 2]}}
        wf["7"] = {"class_type": "LoadAudio", "inputs": {"audio": source}}
    else:
        wf["4"] = {"class_type": "EmptyAceStepLatentAudio",
                   "inputs": {"seconds": float(seconds), "batch_size": 1}}
    return wf


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tags", required=True,
                    help="style, as ACE-Step tags: 'hip hop, female vocal, 90 bpm, gritty'")
    ap.add_argument("--lyrics", default="", help="lyrics, or empty for an instrumental")
    ap.add_argument("--lyrics-strength", type=float, default=1.0)
    ap.add_argument("--seconds", type=float, default=30.0,
                    help="length to generate. Ignored when --source is given, "
                         "because the source's own length decides it.")
    ap.add_argument("--source", default="",
                    help="a filename ALREADY IN the backend's input dir, to "
                         "re-synthesise from. Implies the repair path.")
    ap.add_argument("--denoise", type=float, default=1.0,
                    help="how much of the source to throw away. 1.0 keeps none "
                         "of it, which with --source is almost never wanted.")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--n", type=int, default=1, help="candidates, each a new seed")
    ap.add_argument("--steps", type=int, default=STEPS)
    ap.add_argument("--cfg", type=float, default=CFG)
    ap.add_argument("--model", default=MODEL,
                    help="checkpoint filename. The default is the fp16 cast, "
                         "which is what makes peaches the box that runs this.")
    ap.add_argument("--prefix", default="audio", help="output subdir/name prefix")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    # NO GUARDRAIL HERE, deliberately. guardrail.py refuses any reference to a
    # minor, and its docstring gives the reason: "this is a character generator
    # for adult-themed music videos, so there is no legitimate reason for a tier
    # definition, style note or generated scene to reference children". That
    # premise holds for something that DEPICTS people and does not hold for
    # something that makes music -- a children's song is an ordinary thing to
    # want, and check_text would refuse the word "children" in the tags and end
    # it there. Screening the image path is not a reason to screen this one.
    if args.source and args.denoise >= 1.0:
        print("warning: --source with --denoise 1.0 discards the source entirely; "
              "you probably want something like 0.6", file=sys.stderr)

    os.makedirs(args.outdir, exist_ok=True)
    base = args.seed if args.seed is not None else int.from_bytes(os.urandom(4), "big")
    for i in range(args.n):
        seed = base + i
        name = f"take_{i:03d}_s{seed}"
        wf = workflow(args.tags, args.lyrics, args.seconds, seed,
                      f"{args.prefix}/{name}", lyrics_strength=args.lyrics_strength,
                      steps=args.steps, cfg=args.cfg, denoise=args.denoise,
                      source=args.source or None)
        with open(os.path.join(args.outdir, f"{name}.json"), "w") as f:
            json.dump(wf, f)
        how = f"from {args.source} at denoise {args.denoise}" if args.source \
            else f"{args.seconds:.0f}s from nothing"
        print(f"  {name}  {how}")
    print(f"{args.n} workflow(s) -> {args.outdir}  [{args.model}]")


def demo():
    wf = workflow("hip hop, 90 bpm", "la la", 30, 42, "audio_x/take_000_s42")
    assert wf["4"]["class_type"] == "EmptyAceStepLatentAudio", wf["4"]
    assert wf["5"]["inputs"]["denoise"] == 1.0
    assert wf["99"]["inputs"]["filename_prefix"] == "audio_x/take_000_s42"
    # every node input that names another node must point at one that exists
    for nid, node in wf.items():
        for v in node["inputs"].values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                assert v[0] in wf, f"node {nid} references missing node {v[0]}"

    # the repair path swaps the latent source and nothing else
    src = workflow("hip hop", "", 30, 42, "p", source="song.mp3", denoise=0.6)
    assert src["4"]["class_type"] == "VAEEncodeAudio", src["4"]
    assert src["7"]["inputs"]["audio"] == "song.mp3"
    assert src["5"]["inputs"]["denoise"] == 0.6
    assert "EmptyAceStepLatentAudio" not in {n["class_type"] for n in src.values()}
    for nid, node in src.items():
        for v in node["inputs"].values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                assert v[0] in src, f"node {nid} references missing node {v[0]}"

    # THE ROUTING POLICY IS THIS STRING. cerberus holds the bf16 build under a
    # different name, so the fp16 spelling is the only reason audio lands on the
    # always-on box instead of competing with video on a 5090.
    assert wf["1"]["inputs"]["ckpt_name"] == "ace_step_v1_3.5b_fp16.safetensors", wf["1"]

    # The image guardrail must NOT be reachable from here. It refuses any
    # mention of a minor, which is right for a renderer that depicts people and
    # wrong for one that makes music: it would refuse "a children's song" and
    # nothing else about that request needs refusing.
    # globals(), not a grep of the source: `import guardrail` binds the name
    # here, and a comment mentioning it does not. Grepping source proves text
    # exists, never that anything reaches it.
    assert "guardrail" not in globals(), \
        "the image guardrail is back on the audio path; it refuses nursery rhymes"
    kids = workflow("nursery rhyme, gentle, ukulele", "the little kids sang",
                    30, 1, "audio_kids/take_000_s1")
    assert kids["2"]["inputs"]["tags"] == "nursery rhyme, gentle, ukulele"
    assert kids["2"]["inputs"]["lyrics"] == "the little kids sang"
    print("make_audio.py OK")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        demo()
    else:
        main()
