#!/usr/bin/env python3
"""Write video post-processing workflows (API format) into --outdir. Renders nothing.

Same contract as make_anchor.py / build_refs.py / build_song.py / make_audio.py:
this writes workflow JSON, and studio/pipeline.py submits it.

WHAT THIS IS FOR. A rendered clip is 832x480 at 16 fps, because that is what the
video model produces at a price anyone is willing to pay. Frame interpolation and
an ESRGAN upscale raise both AFTER the fact, on a box that is not generating, so
the render budget is untouched.

WHY INTERPOLATION IS THE DEFAULT AND UPSCALING IS NOT. Measured 2026-08-12 on
this fleet, one real clip (77 frames, 832x480), warm, pinned so nothing else can
have run it:

    pass          peaches (2080 Ti)   cerberus (5090 laptop)
    interpolate x2        2.1 s              2.9 s
    upscale x2           29.7 s             22.5 s
    both                 58.2 s             42.4 s

Generating that clip costs about 40 s. So interpolation is 5% of a render and is
free in any sense that matters, while an upscale is most of a second render --
and both passes together cost MORE than generating the clip did. On an 80-clip
song that is over an hour of GPU. Upscaling is therefore something you ask for
per clip, on the ones worth it, and never the default for a whole song.

The 3.5x per-pixel gap between those two boxes does NOT appear here: peaches is
FASTER at interpolation and only 1.3x slower at upscaling. ESRGAN and RIFE are
small convnets with per-frame CPU work around them, not the tensor-core diffusion
workload that ratio was measured on. Do not carry that ratio across workloads.

FILENAMES. Both boxes were given the same two files by the same commands, so
unlike ACE-Step and the Z-Image VAE there is no per-box spelling to resolve here
(studio/models.py ALIASES). Keep it that way -- installing a differently named
copy on one box is how a workflow becomes unable to run on the other.
"""
import argparse, json, os, sys

UPSCALE_MODEL = "RealESRGAN_x2plus.pth"      # x2: 832x480 -> 1664x960
INTERP_MODEL = "rife_v4.26.safetensors"


def out_fps(fps, frames, multiplier):
    """The frame rate that keeps an interpolated clip the length it already was.

    NOT fps * multiplier, and this is the trap in the whole file. RIFE
    interpolates BETWEEN pairs, so it returns `(n-1)*m + 1` frames, not `n*m`
    (ComfyUI's nodes_frame_interpolation.py computes exactly that). Played at
    double the rate, a doubled 77-frame clip is 153/32 = 4.781 s where the
    source was 4.8125 s -- one frame short.

    One frame is nothing. Eighty clips is 2.5 seconds of drift against the
    audio, on a project whose clips are cut to a beat grid and whose stated
    contract is 4.8125 s each. And it fails in the direction nobody checks: the
    clip plays, looks smoother, and is silently the wrong length.
    """
    return float(fps) * ((frames - 1) * multiplier + 1) / frames


def workflow(source, prefix, fps, frames=None, *, multiplier=2, upscale=None):
    """One post-processing graph over an existing video.

    source      a filename ALREADY IN the backend's input dir (LoadVideo takes a
                name, not a path -- the same reason stage_refs exists for images)
    fps         the SOURCE's frame rate. Passed in rather than wired from
                GetVideoComponents because interpolating changes it, and core
                ComfyUI has no float-multiply node; every node that could do the
                arithmetic comes from a custom pack, which would make this
                workflow depend on which boxes have that pack installed.
    frames      the SOURCE's frame count. Required when interpolating -- see
                out_fps for what guessing it costs.
    multiplier  1 leaves the frame rate alone. 2 doubles the frame count.
    upscale     an upscale model filename, or None for no upscale.
    """
    if multiplier < 1:
        raise ValueError(f"multiplier must be at least 1, got {multiplier}")
    if multiplier > 1 and not frames:
        raise ValueError("interpolating needs the source frame count, or the "
                         "result is one frame short of the length it started")
    if not upscale and multiplier == 1:
        raise ValueError("neither an upscale nor an interpolation was asked for; "
                         "that workflow would re-encode the clip and change nothing")
    wf = {
        "10": {"class_type": "LoadVideo", "inputs": {"file": source}},
        "11": {"class_type": "GetVideoComponents", "inputs": {"video": ["10", 0]}},
    }
    images = ["11", 0]
    if multiplier > 1:
        wf["30"] = {"class_type": "FrameInterpolationModelLoader",
                    "inputs": {"model_name": INTERP_MODEL}}
        wf["31"] = {"class_type": "FrameInterpolate",
                    "inputs": {"interp_model": ["30", 0], "images": images,
                               "multiplier": int(multiplier)}}
        images = ["31", 0]
    if upscale:
        wf["20"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": upscale}}
        wf["21"] = {"class_type": "ImageUpscaleWithModel",
                    "inputs": {"upscale_model": ["20", 0], "image": images}}
        images = ["21", 0]
    # The AUDIO is carried across from the source. A clip whose video was
    # interpolated and whose audio was dropped is silent, and silent is a defect
    # that survives every check that only looks at the picture.
    wf["90"] = {"class_type": "CreateVideo",
                "inputs": {"images": images,
                           "fps": out_fps(fps, frames, multiplier) if multiplier > 1
                                  else float(fps),
                           "audio": ["11", 1]}}
    wf["99"] = {"class_type": "SaveVideo",
                "inputs": {"video": ["90", 0], "filename_prefix": prefix,
                           "format": "auto", "codec": "auto"}}
    return wf


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True,
                    help="filename ALREADY IN the backend's input dir")
    ap.add_argument("--fps", type=float, required=True,
                    help="the source's frame rate. Wrong here means a clip that "
                         "plays at the wrong speed, which nothing downstream checks.")
    ap.add_argument("--frames", type=int, default=0,
                    help="the source's frame count. Required when interpolating: "
                         "RIFE returns (n-1)*m+1 frames, so the output rate that "
                         "preserves the clip's LENGTH is not fps*multiplier.")
    ap.add_argument("--multiplier", type=int, default=2,
                    help="frame-rate multiplier, or 1 for no interpolation")
    ap.add_argument("--upscale", default="",
                    help=f"upscale model filename, e.g. {UPSCALE_MODEL}. Empty "
                         f"(the default) means no upscale: measured, it costs "
                         f"most of a second render per clip.")
    ap.add_argument("--prefix", default="post", help="output subdir/name prefix")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    name = os.path.splitext(os.path.basename(args.source))[0]
    wf = workflow(args.source, f"{args.prefix}/{name}", args.fps, args.frames,
                  multiplier=args.multiplier, upscale=args.upscale or None)
    with open(os.path.join(args.outdir, f"{name}.json"), "w") as f:
        json.dump(wf, f)
    did = ([f"{args.multiplier}x frames -> {wf['90']['inputs']['fps']:g} fps"]
           if args.multiplier > 1 else []) + ([args.upscale] if args.upscale else [])
    print(f"  {name}  {', '.join(did)}")
    print(f"1 workflow -> {args.outdir}")


def demo():
    # THE CLIP COMES OUT THE LENGTH IT WENT IN. Measured against the real thing:
    # 77 frames at 16 fps is 4.8125 s, RIFE x2 returned 153 frames (verified on
    # peaches, and (n-1)*m+1 is what ComfyUI's own node computes), and 153 at
    # the naive 32 fps would be 4.781 s -- one frame short, every clip, in the
    # direction nothing checks.
    assert abs(out_fps(16.0, 77, 2) - 31.7922) < 1e-3, out_fps(16.0, 77, 2)
    assert abs(((77 - 1) * 2 + 1) / out_fps(16.0, 77, 2) - 77 / 16.0) < 1e-9, \
        "an interpolated clip is not the length the source was"
    # and the same must hold at a multiplier nobody has run yet, and at LTX-2.5's
    # own rate, or this is a constant that happened to fit one case
    for f, n, m in [(16.0, 77, 4), (16.8312, 81, 2), (16.8312, 81, 3), (24.0, 2, 2)]:
        assert abs(((n - 1) * m + 1) / out_fps(f, n, m) - n / f) < 1e-9, (f, n, m)

    wf = workflow("clip_000.mp4", "post_x/clip_000", 16.8312, 81)
    assert wf["31"]["class_type"] == "FrameInterpolate", wf
    assert "21" not in wf, "an upscale was added to a workflow that did not ask for one"
    assert wf["90"]["inputs"]["images"] == ["31", 0], wf["90"]
    assert wf["90"]["inputs"]["audio"] == ["11", 1], "the source audio was dropped"

    # interpolating without the frame count is refused rather than guessed
    try:
        workflow("clip_000.mp4", "p", 16.0, multiplier=2)
        raise AssertionError("interpolation guessed at the source frame count")
    except ValueError:
        pass

    # upscale only: the frame rate is untouched -- and it is the SOURCE rate, not
    # a rate derived from a frame count that was never multiplied
    up = workflow("clip_000.mp4", "p", 16.0, multiplier=1, upscale=UPSCALE_MODEL)
    assert up["90"]["inputs"]["fps"] == 16.0, up["90"]
    assert up["90"]["inputs"]["images"] == ["21", 0], up["90"]
    assert "31" not in up, up

    # both: the upscale runs AFTER the interpolation, so the 2x frames it has to
    # enlarge is the cost the 58.2s in this module's docstring measured
    two = workflow("clip_000.mp4", "p", 16.0, 77, multiplier=2, upscale=UPSCALE_MODEL)
    assert two["21"]["inputs"]["image"] == ["31", 0], two["21"]

    for graph in (wf, up, two):
        for nid, node in graph.items():
            for v in node["inputs"].values():
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                    assert v[0] in graph, f"node {nid} references missing node {v[0]}"

    # a workflow that does neither is a re-encode wearing a post-processing hat
    for bad in ({"multiplier": 1}, {"multiplier": 1, "upscale": ""}):
        try:
            workflow("clip_000.mp4", "p", 16.0, 77, **bad)
            raise AssertionError(f"a no-op post-process was accepted: {bad}")
        except ValueError:
            pass
    print("make_postproc.py OK")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        demo()
    else:
        main()
