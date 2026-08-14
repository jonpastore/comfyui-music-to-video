#!/usr/bin/env python3
"""Tier 1 of docs/TRD-3: deterministic checks on what was actually rendered.

ffprobe, ffmpeg's own analysis filters, PIL and numpy. No model, no opinion.

THE RULE THAT SHAPES EVERY CHECK HERE: each one compares the artefact against
WHAT THE WORKFLOW ASKED FOR, which the studio knows because it wrote the
workflow. Nothing in this file compares against a constant. The predecessor plan
(docs/OUTPUT_QC_PLAN.md) tabulated "4.8125s" and "81 frames @ 16.8312" as the
expected values; clip length is per song now, so those numbers would fail every
correct 30-second clip. `expect` is a parameter, always.

THE SECOND RULE, and this project has paid for it three times in one day: a
measurement that produced no reading must RAISE, never return 0.0. An
aspectralstats check once compared two readings that were both 0.0 because the
filter emits nothing without a metadata printer, and it passed on no data,
behind an `if` that made it a no-op. Every _readings() call here raises when it
parses nothing.

Pure by design (docs/TRD-3 T3-30): no FastAPI import, no database, no app. A
check takes a path and an expectation and returns findings, so it can be run
over a directory of old output from a shell. Recording findings is somebody
else's job.

    python3 qc.py          # self-check: renders real media and checks it
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import effects  # noqa: E402  -- the ONE loudness implementation lives there
import mixer    # noqa: E402  -- probe() and SET_DURATION_TOLERANCE


# ---------------------------------------------------------------- verdicts --
# Only checks with NO judgement in them may reject: unreadable, zero-length,
# wrong duration, all-black. Everything else flags and the file is still shown.
# A rejection keeps the file -- docs/TRD-3 4, and the studio's whole design is
# candidates plus a human pick.
PASS, FLAG, REJECT = "pass", "flag", "reject"

# A clip that is a container and nothing else. The 38KB toy that looked like an
# 827KB clip is the case; this is a floor on "is there video in here at all",
# not a quality judgement.
MIN_VIDEO_BYTES = 2000

# Tolerances. Duration is the one that matters and it is generous on purpose:
# a container rounds, and an interpolated clip is legitimately (n-1)*m+1 frames.
DURATION_TOL_S = 0.10
FPS_TOL = 0.01

# Below this mean luma a frame is black. CALIBRATED against this project's own
# output on 2026-08-13 rather than picked, because the obvious value is wrong:
# black in limited-range yuv420p is Y=16, NOT 0, so a floor under 16 passes a
# fully black render. Measured:
#
#     ffmpeg color=c=black, yuv420p        mean 16.0
#     clipmax/cerberus_505f_30s.mp4        mean 34.8   min frame 31.6
#     clipmax/cerberus_1009f_60s.mp4       mean 35.1   min frame 32.5
#     meowp_test_00001_.mp4                mean 39.9   min frame 31.6
#
# The darkest real clip this studio has made sits at 31.6 on its darkest frame,
# and these are neon-noir night renders -- the dark end of what it produces. 24
# has 8 levels of margin on both sides. Re-measure before moving it; the album
# getting darker is a reason to re-run those numbers, not to nudge this one.
LUMA_FLOOR = 24.0

# A take whose loudest sample is under this is empty, not quiet. Measured
# 2026-08-13 with volumedetect: a 440 Hz tone peaks at -18.1 dB and digital
# silence at -91.0 dB, so -60 sits a long way from both.
SILENCE_FLOOR_DB = -60.0

# docs/TRD-7 T7-7: the sheet must be HER, not the pose-plate person. The look
# itself is human-judged; this is the finding kind for the offline hook.
IDENTITY_LOOK = "identity_look"

# docs/TRD-4 T4-14: a nude compose that asserts a human body is the measured
# identity collapse (cat head on a human form). Offline, no pixels.
HUMAN_BODY_PHRASES = ("human form", "human body", "human skin", "bare skin")


def finding(path, kind, check, verdict, detail, measured=None, expected=None,
            unit=None, remedy=None):
    """One row of docs/TRD-3 3. measured/expected/unit are carried on every
    check that has them, because a finding that says only "failed" cannot be
    argued with and cannot be re-checked after a repair."""
    return {"path": path, "kind": kind, "tier": 1, "check": check,
            "verdict": verdict, "measured": measured, "expected": expected,
            "unit": unit, "detail": detail, "remedy": remedy}


# ------------------------------------------------------------ measurement --

def _ffprobe_frames(path):
    """Frame count. nb_frames when the container carries it, else counted
    packets. NOT computed from duration*fps -- that is the arithmetic the
    check exists to verify, and deriving it would make the check compare a
    number against itself."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
         "-show_entries", "stream=nb_frames,nb_read_packets",
         "-print_format", "json", path],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    streams = (json.loads(r.stdout or "{}").get("streams") or [{}])
    s = streams[0] if streams else {}
    for key in ("nb_frames", "nb_read_packets"):
        v = s.get(key)
        if v not in (None, "", "N/A"):
            try:
                return int(v)
            except ValueError:
                pass
    return None


def _readings(path, filt, key, audio=False):
    """Per-frame metadata from an ffmpeg analysis filter, as a list of floats.

    RAISES if it parsed nothing. That is the whole reason this helper exists
    rather than each caller running ffmpeg itself: a filter that silently emits
    no metadata hands its caller an empty list, the caller takes a mean of
    nothing or compares 0.0 against 0.0, and the check passes having measured
    precisely nothing. It has happened here. It raises now.
    """
    flag = "-af" if audio else "-vf"
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "info", "-i", path,
         flag, f"{filt},metadata=print:key={key}:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True)
    # -inf is a REAL READING, not a missing one: astats reports RMS_level as
    # -inf dB for digital silence, which is exactly the case the silence check
    # exists for. Parsing only decimals made the one measurement that matters
    # look like a filter that had emitted nothing.
    vals = [float(m.group(1)) for m in
            re.finditer(rf"{re.escape(key)}=(-?(?:\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|inf|nan))",
                        r.stdout)]
    vals = [v for v in vals if v == v]        # drop NaN, keep +/-inf
    if not vals:
        raise RuntimeError(
            f"{filt} produced no {key} readings for {path} -- refusing to report a "
            "measurement that did not happen:\n"
            + "\n".join(r.stderr.splitlines()[-15:]))
    return vals


def _volume(path):
    """{"mean_db", "max_db"} via ffmpeg's volumedetect.

    Not astats: `astats=metadata=1,metadata=print` will not initialise in this
    filtergraph at all ("Error initializing a simple filtergraph"), so it
    produced no readings for every file including ones that plainly have audio
    -- a measurement that fails identically on good and bad input is worse than
    none, because it looks like a finding. volumedetect prints one line to
    stderr and separates the cases cleanly: measured 2026-08-13, a 440 Hz tone
    reads max -18.1 dB and digital silence reads -91.0 dB.

    Raises if it printed nothing, for the reason in the module docstring.
    """
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "info", "-i", path, "-af", "volumedetect",
         "-f", "null", "-"], capture_output=True, text=True)
    got = {}
    for name in ("mean_volume", "max_volume"):
        m = re.search(rf"{name}:\s*(-?\d+(?:\.\d+)?) dB", r.stderr)
        if m:
            got[name.split("_")[0] + "_db"] = float(m.group(1))
    if "max_db" not in got:
        raise RuntimeError(
            f"volumedetect printed no level for {path} -- refusing to report a "
            "measurement that did not happen:\n"
            + "\n".join(r.stderr.splitlines()[-15:]))
    return got


def _stderr_events(path, filt, pattern):
    """Count of events a detector filter printed to stderr (blackdetect,
    freezedetect). Absence of events is a real answer here -- "no frozen span
    found" -- so unlike _readings this does not raise on empty."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "info", "-i", path, "-vf", filt, "-f", "null", "-"],
        capture_output=True, text=True)
    return re.findall(pattern, r.stderr)


# ------------------------------------------------------------------ video --

def check_video(path, expect, kind="clip"):
    """Tier 1 over a rendered clip or an assembled song.

    expect: duration, frames, fps, width, height -- each optional, each read
    from the workflow the studio submitted. want_audio says whether an audio
    stream is REQUIRED; see the note below, it is the check that would
    otherwise fire on every correct clip this studio produces.
    """
    out = []
    if not os.path.isfile(path):
        return [finding(path, kind, "opens", REJECT, "file does not exist",
                        remedy="re-render")]

    size = os.path.getsize(path)
    if size < MIN_VIDEO_BYTES:
        out.append(finding(path, kind, "size_floor", REJECT,
                           "file is too small to contain video -- a container and "
                           "nothing else", size, MIN_VIDEO_BYTES, "bytes",
                           remedy="re-render"))
        return out

    try:
        info = mixer.probe(path)
    except Exception as e:
        return [finding(path, kind, "opens", REJECT, f"ffprobe cannot read it: {e}",
                        remedy="re-render")]

    if not info["has_video"]:
        return [finding(path, kind, "opens", REJECT, "no video stream",
                        remedy="re-render")]

    # ---- what the workflow asked for
    if expect.get("duration"):
        d, want = info["duration"], float(expect["duration"])
        out.append(finding(path, kind, "duration",
                           PASS if abs(d - want) <= DURATION_TOL_S else REJECT,
                           f"{d:.3f}s against the {want:.3f}s the workflow asked for",
                           round(d, 3), round(want, 3), "s", remedy="re-render"))

    frames = _ffprobe_frames(path)
    if frames is not None:
        if expect.get("frames"):
            want = int(expect["frames"])
            out.append(finding(path, kind, "frame_count",
                               PASS if frames == want else REJECT,
                               f"{frames} frames against {want} requested",
                               frames, want, "frames", remedy="re-render"))
        # The latent length rule is THE MODEL'S, not a universal.
        # EmptyLTXVLatentVideo declares step 8, so LTX wants 8n+1;
        # WanSoundImageToVideo declares step 4, and WAN's own LEN is 77 --
        # 4*19+1, legal for WAN and NOT 8n+1. Applying LTX's rule to every clip
        # flagged every correct s2v render, which is what this did until an
        # independent review caught it. `frame_step` comes from the submitted
        # graph; 8 when unknown, which is the default renderer's rule.
        #
        # An interpolated clip is exempt either way: RIFE returns (n-1)*m+1.
        step = int(expect.get("frame_step") or 8)
        if expect.get("latent_rule", True) and not expect.get("interpolated"):
            legal = (frames - 1) % step == 0
            near = step * round((frames - 1) / step) + 1
            out.append(finding(path, kind, "latent_8n1",
                               PASS if legal else FLAG,
                               f"{frames} frames, step {step}"
                               + ("" if legal else f"; nearest legal is {near}"),
                               frames, near, "frames", remedy="re-render"))

    if expect.get("fps"):
        f, want = info["fps"], float(expect["fps"])
        out.append(finding(path, kind, "fps",
                           PASS if abs(f - want) <= FPS_TOL else FLAG,
                           f"{f:.4f} fps against {want:.4f} requested",
                           round(f, 4), round(want, 4), "fps",
                           remedy="re-render pinned to a box that honours it"))

    if expect.get("width") and expect.get("height"):
        got = (info["width"], info["height"])
        want = (int(expect["width"]), int(expect["height"]))
        out.append(finding(path, kind, "resolution",
                           PASS if got == want else REJECT,
                           f"{got[0]}x{got[1]} against {want[0]}x{want[1]} requested",
                           f"{got[0]}x{got[1]}", f"{want[0]}x{want[1]}", None,
                           remedy="re-render pinned to a box that honours it"))

    # ---- AUDIO ON A CLIP IS NOT REQUIRED, and this is the check that would
    # otherwise fire on every clip the studio makes. Measured 2026-08-12 and
    # confirmed not-a-bug: LTX-2.5 clips are SILENT BY DESIGN. The audio is
    # loaded, trimmed and concatenated into the latent so it conditions motion,
    # then LTXVSeparateAVLatent's audio output is discarded and CreateVideo gets
    # only images; mixer.assemble_song lays the real mp3 over at assembly. So
    # want_audio is opt-in, and it is the assembled SONG that opts in.
    if expect.get("want_audio"):
        if not info["has_audio"]:
            out.append(finding(path, kind, "has_audio", REJECT,
                               "no audio stream on an assembled video",
                               remedy="re-assemble"))
        else:
            av = _av_durations(path)
            if av:
                gap = abs(av["video"] - av["audio"])
                out.append(finding(path, kind, "av_sync",
                                   PASS if gap <= DURATION_TOL_S else FLAG,
                                   f"video {av['video']:.3f}s against audio "
                                   f"{av['audio']:.3f}s",
                                   round(gap, 3), 0.0, "s", remedy="re-assemble"))

    # ---- pixels
    try:
        luma = _readings(path, "signalstats", "lavfi.signalstats.YAVG")
    except RuntimeError as e:
        out.append(finding(path, kind, "luma", FLAG, str(e).split("\n")[0]))
    else:
        mean = sum(luma) / len(luma)
        dark = sum(1 for v in luma if v < LUMA_FLOOR)
        out.append(finding(path, kind, "luma",
                           PASS if mean >= LUMA_FLOOR else REJECT,
                           f"mean luma {mean:.1f} over {len(luma)} frames, "
                           f"{dark} of them below {LUMA_FLOOR}",
                           round(mean, 2), LUMA_FLOOR, "Y",
                           remedy="re-render with a different seed"))
        if dark and mean >= LUMA_FLOOR:
            out.append(finding(path, kind, "black_frames", FLAG,
                               f"{dark} of {len(luma)} frames are below the black floor",
                               dark, 0, "frames",
                               remedy="re-render with a different seed"))

    frozen = _stderr_events(path, "freezedetect=n=-60dB:d=0.5", r"freeze_start")
    out.append(finding(path, kind, "frozen",
                       PASS if not frozen else FLAG,
                       "no frozen span" if not frozen
                       else f"{len(frozen)} frozen span(s) of 0.5s or longer",
                       len(frozen), 0, "spans",
                       remedy="re-render with a different seed"))
    return out


def _av_durations(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
         "-print_format", "json", path], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = {}
    for s in json.loads(r.stdout or "{}").get("streams", []):
        if s.get("duration") not in (None, "", "N/A"):
            out[s["codec_type"]] = float(s["duration"])
    return out if "video" in out and "audio" in out else None


# ------------------------------------------------------------------ audio --

def check_audio(path, expect):
    """Tier 1 over a generated take, a bridge or an edit. docs/TRD-3 4.3 --
    the predecessor plan had no audio tier at all."""
    out = []
    if not os.path.isfile(path):
        return [finding(path, "audio", "opens", REJECT, "file does not exist",
                        remedy="re-render")]
    try:
        info = mixer.probe(path)
    except Exception as e:
        return [finding(path, "audio", "opens", REJECT, f"ffprobe cannot read it: {e}",
                        remedy="re-render")]
    if not info["has_audio"]:
        return [finding(path, "audio", "opens", REJECT, "no audio stream",
                        remedy="re-render")]

    if expect.get("duration"):
        d, want = info["duration"], float(expect["duration"])
        tol = float(expect.get("duration_tol", DURATION_TOL_S))
        out.append(finding(path, "audio", "duration",
                           PASS if abs(d - want) <= tol else REJECT,
                           f"{d:.3f}s against {want:.3f}s requested",
                           round(d, 3), round(want, 3), "s", remedy="re-render"))

    # Loudness through effects.py -- the ONE implementation. TRD-1 T1-25.
    try:
        loud = effects.measure_loudness(path)
    except RuntimeError as e:
        out.append(finding(path, "audio", "loudness", FLAG, str(e).split("\n")[0]))
    else:
        target = float(expect.get("lufs", effects.LOUDNORM_I))
        tol = float(expect.get("lufs_tol", 2.0))
        off = abs(loud["lufs"] - target)
        out.append(finding(path, "audio", "loudness",
                           PASS if off <= tol else FLAG,
                           f"{loud['lufs']:.1f} LUFS against a {target:.1f} target",
                           loud["lufs"], target, "LUFS", remedy="re-run loudnorm"))
        if loud["true_peak_db"] is not None:
            over = loud["true_peak_db"] > effects.LOUDNORM_TP + 0.5
            out.append(finding(path, "audio", "true_peak",
                               FLAG if over else PASS,
                               f"{loud['true_peak_db']:.1f} dBFS against "
                               f"{effects.LOUDNORM_TP:.1f} ceiling",
                               loud["true_peak_db"], effects.LOUDNORM_TP, "dBFS",
                               remedy="re-run loudnorm"))

    # Silence. A take that came back empty is the failure this catches, and it
    # is measured as band energy rather than asserted -- see the module docstring.
    try:
        vol = _volume(path)
    except RuntimeError as e:
        out.append(finding(path, "audio", "silence", FLAG, str(e).split("\n")[0]))
    else:
        out.append(finding(path, "audio", "silence",
                           PASS if vol["max_db"] > SILENCE_FLOOR_DB else REJECT,
                           f"peak {vol['max_db']:.1f} dB, mean "
                           f"{vol.get('mean_db', float('nan')):.1f} dB",
                           vol["max_db"], SILENCE_FLOOR_DB, "dB", remedy="re-render"))
    return out


# ------------------------------------------------------------------ image --

def _norm_ref(value):
    text = str(value or "").strip()
    return os.path.normpath(text) if text else ""


def _compose_text(expect):
    return " ".join(str(expect.get(k) or "") for k in ("composed", "nude_wardrobe"))


def _human_body_hits(text):
    low = (text or "").lower()
    return [p for p in HUMAN_BODY_PHRASES if p in low]


def check_identity_look(path, expect, kind="image"):
    """T7-7 hook. No pixels, no model: name the identity ref, and it must not
    be the pose plate. Missing identity_path flags. A distinct named path
    passes the prerequisite; the picture stays a human look.

    A compose that asserts a human body (T4-14: nude_wardrobe "human form")
    flags even when the identity path is the chosen ref.
    """
    expect = expect or {}
    identity = _norm_ref(expect.get("identity_path"))
    plate = _norm_ref(expect.get("plate_path"))
    remedy = ("condition the sheet on the chosen identity ref "
              "(UI pair / meowp_ui_front.png), not the pose plate")
    if not identity:
        return [finding(path, kind, IDENTITY_LOOK, FLAG,
                        "T7-7 identity look needs a named identity reference; none was given",
                        None, "identity_path", None, remedy)]
    if plate and identity == plate:
        return [finding(path, kind, IDENTITY_LOOK, FLAG,
                        "identity_path is the pose plate; T7-7 requires the chosen identity ref",
                        identity, "identity_path != plate_path", None, remedy)]
    hits = _human_body_hits(_compose_text(expect))
    if hits:
        return [finding(path, kind, IDENTITY_LOOK, FLAG,
                        f"composed prompt asserts {hits[0]}; "
                        "T4-14 / T7-7 refuse a human-body sheet",
                        hits[0], "not a human-body compose", None,
                        "drop human-body wording from nude_wardrobe; "
                        "surface comes from the body clause")]
    return [finding(path, kind, IDENTITY_LOOK, PASS,
                    f"identity ref {os.path.basename(identity)}; T7-7 look remains human-judged",
                    identity, identity, None)]


def _wants_identity_look(expect):
    return bool(expect.get("identity_look")) or "identity_path" in expect or "plate_path" in expect


def check_image(path, expect):
    out = []
    if not os.path.isfile(path):
        return [finding(path, "image", "opens", REJECT, "file does not exist",
                        remedy="re-render")]
    size = os.path.getsize(path)
    # NO size floor on images, deliberately. A blank render is TINY -- a 256x192
    # all-black PNG is 244 bytes, and an 896x1216 one is not much more, because
    # a uniform image is exactly what PNG compresses best. A byte floor would
    # therefore reject blank renders with the wrong reason ("too small to be an
    # image") and hand the reviewer a remedy aimed at the wrong problem. PIL
    # opening the file answers "is this an image", and not_uniform/not_blank
    # below answer "did the model draw anything" -- which is the real question,
    # measured rather than inferred from a file size.
    try:
        from PIL import Image
        import numpy as np
        with Image.open(path) as im:
            im.load()
            got = im.size
            arr = np.asarray(im.convert("RGB"), dtype="float32")
    except Exception as e:
        return [finding(path, "image", "opens", REJECT, f"cannot be opened: {e}",
                        remedy="re-render")]

    if expect.get("width") and expect.get("height"):
        want = (int(expect["width"]), int(expect["height"]))
        out.append(finding(path, "image", "resolution",
                           PASS if got == want else REJECT,
                           f"{got[0]}x{got[1]} against {want[0]}x{want[1]} requested",
                           f"{got[0]}x{got[1]}", f"{want[0]}x{want[1]}", None,
                           remedy="re-render"))

    std = float(arr.std())
    out.append(finding(path, "image", "not_uniform",
                       PASS if std > 1.0 else REJECT,
                       f"pixel standard deviation {std:.2f}",
                       round(std, 2), 1.0, "levels",
                       remedy="re-render with a different seed"))
    mean = float(arr.mean())
    out.append(finding(path, "image", "not_blank",
                       PASS if mean >= LUMA_FLOOR else REJECT,
                       f"mean level {mean:.1f}",
                       round(mean, 1), LUMA_FLOOR, "levels",
                       remedy="re-render with a different seed"))
    if _wants_identity_look(expect):
        out.extend(check_identity_look(path, expect, kind="image"))
    return out


# -------------------------------------------------------------------- set --

def check_set(path, items):
    """The project's oldest defect, turned into a check that runs on every set.

    `items` is the set's items as mixer.set_duration() takes them, so the
    prediction here is the renderer's own arithmetic and not a second copy of
    it. docs/TRD-3 T3-11; the tolerance is mixer's, imported rather than
    restated, because two copies of a number drift into a check that passes
    while its twin fails.
    """
    out = check_video(path, {}, kind="set")
    if any(f["check"] == "opens" and f["verdict"] == REJECT for f in out):
        return out
    predicted = mixer.set_duration(items, key="video" if _has_video(path) else "audio")
    actual = mixer.probe(path)["duration"]
    gap = abs(actual - predicted)
    out.append(finding(path, "set", "duration_matches_prediction",
                       PASS if gap <= mixer.SET_DURATION_TOLERANCE else REJECT,
                       f"rendered {actual:.3f}s against a predicted {predicted:.3f}s",
                       round(actual, 3), round(predicted, 3), "s",
                       remedy="NOT a re-render -- a divergence between the stored "
                              "model and the filter graph"))
    return out


def _has_video(path):
    try:
        return mixer.probe(path)["has_video"]
    except Exception:
        return False


# ------------------------------------------------------------------- run --

def run(path, kind, expect=None, items=None):
    """Every tier-1 check for one artefact. kind: image|audio|clip|song|set."""
    expect = dict(expect or {})
    if kind == "image":
        return check_image(path, expect)
    if kind == "audio":
        return check_audio(path, expect)
    if kind == "set":
        return check_set(path, items or [])
    if kind == "song":
        expect.setdefault("want_audio", True)
        return check_video(path, expect, kind="song")
    return check_video(path, expect, kind="clip")


def worst(findings):
    """The verdict for the artefact as a whole."""
    for v in (REJECT, FLAG):
        if any(f["verdict"] == v for f in findings):
            return v
    return PASS


def summarise(findings):
    return {"verdict": worst(findings),
            "counts": {v: sum(1 for f in findings if f["verdict"] == v)
                       for v in (PASS, FLAG, REJECT)},
            "failed": [f["check"] for f in findings if f["verdict"] != PASS]}


# ------------------------------------------------------------------ demo --

def _mk(args, out):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error"] + args + [out],
                   check=True, capture_output=True)
    return out


def demo():
    """Renders real media and checks it. Every check is run against something
    it must PASS and something it must REJECT -- one direction is not evidence.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = lambda n: os.path.join(d, n)

        # --- a correct clip: 81 frames at 16.8312 fps, which is 8n+1 and is
        # what the pipeline really submits. Silent, exactly as LTX-2.5 renders.
        fps, frames = 16.8312, 81
        good = _mk(["-f", "lavfi", "-i", f"testsrc2=size=320x240:rate={fps}",
                    "-frames:v", str(frames), "-pix_fmt", "yuv420p"], p("good.mp4"))
        want = {"frames": frames, "fps": fps, "width": 320, "height": 240,
                "duration": frames / fps}
        f = run(good, "clip", want)
        assert worst(f) == PASS, summarise(f)

        # the silent clip must NOT be flagged for its missing audio (T3-3), and
        # the same file AS AN ASSEMBLED SONG must be
        assert not any(x["check"] == "has_audio" for x in f), "a clip was asked for audio"
        song = run(good, "song", want)
        assert any(x["check"] == "has_audio" and x["verdict"] == REJECT for x in song), \
            "an assembled song with no audio stream passed"

        # --- expectations are per artefact, not constants: the SAME file fails
        # when the workflow asked for something else. This is the check that the
        # old plan's hardcoded 4.8125s/81-frame table could not express.
        other = run(good, "clip", {"frames": 505, "fps": fps, "duration": 505 / fps})
        assert worst(other) == REJECT, summarise(other)
        assert {"duration", "frame_count"} <= set(summarise(other)["failed"]), \
            summarise(other)

        # --- 8n+1: 80 frames is not a legal LTX latent length, 81 is
        illegal = _mk(["-f", "lavfi", "-i", f"testsrc2=size=320x240:rate={fps}",
                       "-frames:v", "80", "-pix_fmt", "yuv420p"], p("illegal.mp4"))
        g = run(illegal, "clip", {})
        latent = [x for x in g if x["check"] == "latent_8n1"]
        assert latent and latent[0]["verdict"] == FLAG, g
        assert latent[0]["expected"] == 81, latent[0]
        # THE RULE IS THE MODEL'S. 77 frames is what WAN s2v renders and is
        # 4*19+1 -- legal for WAN, and NOT 8n+1. Applying LTX's step to every
        # clip flagged every correct s2v render. Same file, one variable, both
        # directions.
        wan = _mk(["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=16",
                   "-frames:v", "77", "-pix_fmt", "yuv420p"], p("wan.mp4"))
        ok = [x for x in run(wan, "clip", {"frame_step": 4}) if x["check"] == "latent_8n1"]
        assert ok and ok[0]["verdict"] == PASS, ok
        bad = [x for x in run(wan, "clip", {"frame_step": 8}) if x["check"] == "latent_8n1"]
        assert bad and bad[0]["verdict"] == FLAG, bad
        assert bad[0]["expected"] == 81, bad[0]

        # and an interpolated clip is exempt -- RIFE returns (n-1)*m+1, so 153
        # frames from 77 doubled is correct and must not be flagged
        assert not [x for x in run(illegal, "clip", {"interpolated": True})
                    if x["check"] == "latent_8n1"]

        # --- black: rejected, and the reading is real rather than absent
        black = _mk(["-f", "lavfi", "-i", "color=c=black:size=320x240:rate=10",
                     "-frames:v", "30", "-pix_fmt", "yuv420p"], p("black.mp4"))
        b = run(black, "clip", {})
        luma = [x for x in b if x["check"] == "luma"]
        assert luma and luma[0]["verdict"] == REJECT, b
        assert luma[0]["measured"] is not None and luma[0]["measured"] < LUMA_FLOOR, luma[0]

        # --- frozen: a still image held for 3s is a frozen span, the moving
        # source is not. Same duration, one variable.
        frozen = _mk(["-f", "lavfi", "-i", "color=c=red:size=320x240:rate=10",
                      "-frames:v", "30", "-pix_fmt", "yuv420p"], p("frozen.mp4"))
        fr = [x for x in run(frozen, "clip", {}) if x["check"] == "frozen"]
        assert fr and fr[0]["verdict"] == FLAG, fr
        mv = [x for x in run(good, "clip", {}) if x["check"] == "frozen"]
        assert mv and mv[0]["verdict"] == PASS, mv

        # --- a container with no video, and a stub too small to hold any
        open(p("stub.mp4"), "wb").write(b"\x00" * 100)
        s = run(p("stub.mp4"), "clip", {})
        assert s[0]["check"] == "size_floor" and s[0]["verdict"] == REJECT, s

        # --- audio: a real tone passes, silence is rejected
        tone = _mk(["-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-af", "volume=-14dB"], p("tone.wav"))
        a = run(tone, "audio", {"duration": 3.0, "lufs_tol": 40.0})
        assert not [x for x in a if x["verdict"] == REJECT], summarise(a)
        assert [x for x in a if x["check"] == "loudness"][0]["measured"] is not None

        quiet = _mk(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                     "-t", "3"], p("silence.wav"))
        q = run(quiet, "audio", {"duration": 3.0})
        sil = [x for x in q if x["check"] == "silence"]
        assert sil and sil[0]["verdict"] == REJECT, q

        # --- a duration the workflow did not ask for is rejected on audio too
        wrong = run(tone, "audio", {"duration": 9.0})
        assert [x for x in wrong if x["check"] == "duration"][0]["verdict"] == REJECT

        # --- images
        # 256x192 rather than a token 64x48: MIN_IMAGE_BYTES is a "this is a
        # stub, not a picture" floor and a real anchor is 896x1216, so a fixture
        # under the floor would be testing the fixture.
        img = _mk(["-f", "lavfi", "-i", "testsrc2=size=256x192", "-frames:v", "1"],
                  p("ok.png"))
        i = run(img, "image", {"width": 256, "height": 192})
        assert worst(i) == PASS, summarise(i)
        flat = _mk(["-f", "lavfi", "-i", "color=c=black:size=256x192", "-frames:v", "1"],
                   p("flat.png"))
        fl = run(flat, "image", {})
        assert {"not_uniform", "not_blank"} <= set(summarise(fl)["failed"]), fl
        assert run(img, "image", {"width": 999, "height": 192})[0]["verdict"] == REJECT

        # --- and the refusal that keeps this file honest: a measurement that
        # produced no reading raises instead of returning 0.0
        try:
            _readings(tone, "signalstats", "lavfi.signalstats.YAVG")
        except RuntimeError as e:
            assert "no lavfi.signalstats.YAVG readings" in str(e), e
        else:
            raise AssertionError("a video filter on an audio file reported a reading")

    print("qc.py OK")


if __name__ == "__main__":
    demo()
