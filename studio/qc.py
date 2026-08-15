#!/usr/bin/env python3
"""Tier 1 of docs/TRD-3: deterministic checks on what was actually rendered.

T3-13's identity score also lives here (pure; no database). T3-15 is the
histogram embed; T3-16 is identity_verdict. T3-17 scores each artefact
against the chosen anchor (cause-agnostic). The threshold setter is not
in this file. T3-26's labelled-set refiner measurement lives here too.
T3-28's identity-wrong remedy: edit the text, never swap the reference image.

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
import mixer    # noqa: E402  -- probe(), SET_DURATION_TOLERANCE, spliced_duration


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

# Channel saturation (TRD-3 §4.2): whole-frame green dominance
# G - (R+B)/2. NaN frames from a dead sampler encode as solid green
# garbage. Measured 2026-08-15 on lavfi fixtures (scale=64:64 RGB):
#
#     testsrc2                          max ~ -8
#     color=gray / black                max ~  0
#     color=green (lavfi)               max ~127
#     color=0x00FF00 / geq green        max ~253
#     half-frame green                  max ~126
#
# Real neon-noir content sits near 0. 80 clears a green-heavy scene and
# still catches solid green garbage. Re-measure before moving it.
CHANNEL_SAT_LIMIT = 80.0
_CHANNEL_SAT_SAMPLE = 64

# TRD-3 §4.1 alpha not fully transparent. Max alpha over the sheet
# (0–255). Fully transparent is max 0 — a blank render by another name.
# RGB without an alpha channel is treated as 255 (opaque). ALPHA_MIN
# is 1 so any non-zero opacity PASSes; only all-zero alpha REJECTs.
ALPHA_MIN = 1.0

# A take whose loudest of low/mid/high *mean* band energy is under this
# is empty, not quiet. Peak volumedetect is refused: a 1-sample click
# reads peak -20.0 dB and still has band means below -70 (measured
# 2026-08-14). Digital silence is -91.0 in every band; a 440 Hz tone
# at -14 dB is mid -35.5. -60 sits a long way from both.
SILENCE_FLOOR_DB = -60.0

# TRD-3 §4.3 clipped-sample count. Samples at the s16 rails
# (±32767/32768) are hard-clipped. Zero is the only PASS. Measured
# 2026-08-15: sine@-14dB → 0 rails; sine+20dB / 2*sin aevalsrc →
# thousands of rails. Not peak volumedetect and not Peak_count (a
# clean sine still has a Peak_count > 0).
CLIPPED_SAMPLES_LIMIT = 0

# DC offset (TRD-3 §4.3 / T3-4.3-dc): abs mean sample as a fraction of
# full scale. Calibrated 2026-08-15 on lavfi fixtures (f32le decode):
#
#     clean 440 Hz at -14 dB                 ~ 3e-7
#     digital silence                        0.0
#     constant aevalsrc=0.05                 ~ 0.05
#     sine + dcshift=0.15                    ~ 0.15
#
# Real takes sit near 0. 0.02 clears residual encoder bias and still
# catches a constant bias that would thump a speaker on stop/start.
# Re-measure before moving it.
DC_OFFSET_LIMIT = 0.02

# T3-4.3-edge: max leading or trailing silence before FLAG. Measured
# 2026-08-15 on lavfi fixtures (silencedetect noise=-50dB:d=0.05):
#
#     clean sine -14 dB 2s              leading 0, trailing 0
#     0.5s null + 1s tone + 0.5s        leading 0.5, trailing 0.5
#     0.15s null on each edge           leading 0.15, trailing 0.15
#
# Sub-50 ms encoder/container pad is common; 0.25 clears that and still
# catches a half-second dead pad on a take. Whole-file band energy is
# T3-9, not this check.
EDGE_SILENCE_LIMIT_S = 0.25
_EDGE_SILENCE_NOISE_DB = -50
_EDGE_SILENCE_MIN_S = 0.05

# Image not_uniform (TRD-3 §4.1 / T3-4.1-not_uniform): max per-channel
# spatial std of RGB. A single flat colour is constant in every channel
# (std 0) even when R≠G≠B — whole-array std wrongly PASSes solid red
# because inter-channel spread looks like "variation". Measured 2026-08-15:
#
#     solid black / gray / red / blue      max channel std ~ 0
#     testsrc2 colour bars 256x192         max channel std >> 50
#
# 1.0 clears encoder/quantisation noise and still rejects flat fills.
UNIFORM_STD_FLOOR = 1.0

# T3-9 bands. Brick-wall they are not — 440 Hz leaks into low at -45 —
# but 80 / 440 / 8000 Hz each light exactly one band as the loudest.
BANDS = (
    ("low", "highpass=f=20,lowpass=f=250"),
    ("mid", "highpass=f=250,lowpass=f=4000"),
    ("high", "highpass=f=4000,lowpass=f=16000"),
)

# docs/TRD-7 T7-7: the sheet must be HER, not the pose-plate person. The look
# itself is human-judged; this is the finding kind for the offline hook.
IDENTITY_LOOK = "identity_look"

# docs/TRD-3 T3-28: identity wrong from the first frame. The measured
# fix is edit the text, then re-render. Swapping the reference image
# does not fix it.
IDENTITY_WRONG = "identity_wrong"
IDENTITY_WRONG_REMEDY = (
    "edit the text, then re-render. Identity comes from the text, "
    "not the reference image")
_REFERENCE_SWAP_MARKERS = (
    "swap", "swapping", "replace", "replacing", "attach", "attaching",
    "new reference", "different reference", "another reference",
    "change the reference", "changing the reference",
)

# docs/TRD-3 T3-13: identity score, not pixel distance. The metric name is
# stored on the calibrations row so a later extractor is a new row, not a
# silent rewrite of this one.
IDENTITY_METRIC = "identity_cosine_v1"

# docs/TRD-3 T3-17: per-artefact drift against the chosen anchor.
# N sampled frames; a still is n=1. Not a gate.
IDENTITY_DRIFT = "identity_drift"

# docs/TRD-10 T10-13: classify_sheet text on a finding. Never a verdict.
SHEET_REVIEW = "sheet_review"
IDENTITY_SAMPLE_N = 8
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# docs/TRD-3 T3-26: whether the refiner helps is measured on a labelled
# set. Catalogue proven: opportunistic is not that measurement.
REFINER_HELP_CHECK = "refiner_help"
REFINER_HELP_METRIC = "tier2_score_delta_v1"

# docs/TRD-5 T5-2: MAD + Laplacian on a same-seed refine-off / refine-on
# pair. Graph growth is T5-1. This check is measurement-only.
REFINE_DIFFERENTIAL = "refine_differential"

# docs/TRD-3 T3-16: overlap is a decision, not a number the operator
# has to interpret. "inconclusive" is a success; a threshold is not.
INCONCLUSIVE = "inconclusive"
SEPARATED = "separated"

# zimage_sweep seeds recorded in docs/TRD-3 §2.2. …654 holds fur; the other
# two draw a cat head on human legs at every step count.
ZIMAGE_GOOD_SEEDS = frozenset({29364654})
ZIMAGE_BAD_SEEDS = frozenset({29364380, 29364517})
_ZIMAGE_SEED_RE = re.compile(r"_s(\d+)_")

# docs/TRD-4 T4-14: a nude compose that asserts a human body is the measured
# identity collapse (cat head on a human form). Offline, no pixels.
# "human form" is nude_wardrobe; the live-studio body clause said
# "Human woman's body" / "human anatomy" without those four strings.
HUMAN_BODY_PHRASES = (
    "human form", "human body", "human skin", "bare skin",
    "human woman's body", "human anatomy", "human musculature",
    "human proportions",
)

# docs/TRD-5 T5-2: the renderer assigns decoded (plain, refined) uint8/float
# arrays here after a same-seed pair lands. None is NOT MEASURED. skip is
# not a reading. Deleting this name is the mutation the harness test uses.
# T5_2_REAL_CLIP_MEASURED stays False until accept_t5_2_gpu_pair(...,
# source="gpu") records a decoded pair. Flipping it without populating
# the hook is the lie the harness test catches.
T5_2_REAL_CLIP_FRAMES = None
T5_2_REAL_CLIP_MEASURED = False
T5_2_REAL_CLIP_SEED = None

# docs/TRD-4 T4-13: positive lighting lock on rendered channel balance.
# Green/magenta casts are the reported symptom. BACKDROP already says
# "evenly lit"; that string is not this criterion. The metric is
# |G - (R+B)/2| on the outer border (studio wall), not the whole-image
# mean — a black figure on an olive wall averages toward equal channels.
LIGHTING_LOCK = "channel_balance"
LIGHTING_CAST_LIMIT = 12.0
# Job 257 (2026-08-14): Street Cats xxx front_nude seed 5151, empty latent,
# CFG 2.0 / 50 / dpmpp_2m+karras. Backdrop olive mag=8.06 PASS
# (R=144.6 G=143.5 B=126.3). Sibling seed 5288 still FLAGs 14.76.
T4_13_REAL_SHEET_PATH = (
    "/home/jon/ComfyUI/output/anchor_v2/front_nude_s5151_00001_.png")
T4_13_REAL_SHEET_SHA256 = (
    "ac56dc7206b5701bb6dfdf084815376e806085c3899ada2ff66e93a67a238f1b")
T4_13_REAL_SHEET_MEASURED = True

# docs/TRD-7 T7-7: identity held across views. The ranking is
# identity(front, three_quarter) from an anchor vs the same pair from
# raw photographs. No threshold. None is NOT MEASURED. skip is not a
# reading. T7_7_REAL_PAIR_MEASURED stays False until a GPU four-image
# set is recorded; flipping it with an empty hook or unpinned bytes is
# the lie. Do not claim the fleet to populate this.
# Photo-conditioned halves landed: Catatonic jobs 244/248 (front_nude
# s1002911869 + three_quarter_nude s836704466; identity-collapsed human
# woman, not her) and Street Cats jobs 264/268 (front_nude s1943749893 +
# three_quarter_nude s1096561198; 262 cancelled). Both used base
# photographs as image1/image2. No use-as-ref pair has been rendered —
# no job's images list is a generated anchors path. Flip MEASURED only
# after that four-image set is pinned and t7_7_claim passes on those
# bytes.
T7_7_REAL_PAIR = None
T7_7_REAL_PAIR_SHA256 = None
T7_7_REAL_PAIR_MEASURED = False

# docs/TRD-3 T3-27 / §6.2. The class is what approve() runs. A check with
# NONE says so and offers no button.
REMEDY_NONE = "none"
REMEDY_RERENDER = "re-render"
REMEDY_RERENDER_SEED = "re-render-seed"
REMEDY_RERENDER_PINNED = "re-render-pinned"
REMEDY_REASSEMBLE = "re-assemble"
REMEDY_LOUDNORM = "loudnorm"
REMEDY_UPSCALE = "upscale"
REMEDY_EDIT_TEXT = "edit-text"

CHECK_REMEDY_CLASS = {
    "opens": REMEDY_RERENDER,
    "size_floor": REMEDY_RERENDER,
    "duration": REMEDY_RERENDER,
    "frame_count": REMEDY_RERENDER,
    "latent_8n1": REMEDY_RERENDER,
    "fps": REMEDY_RERENDER_PINNED,
    "resolution": REMEDY_RERENDER_PINNED,
    "has_audio": REMEDY_REASSEMBLE,
    "av_sync": REMEDY_REASSEMBLE,
    "luma": REMEDY_RERENDER_SEED,
    "black_frames": REMEDY_RERENDER_SEED,
    "join_black_gap": REMEDY_REASSEMBLE,
    "frozen": REMEDY_RERENDER_SEED,
    "channel_sat": REMEDY_RERENDER_SEED,
    "loudness": REMEDY_LOUDNORM,
    "true_peak": REMEDY_LOUDNORM,
    "sample_rate": REMEDY_RERENDER,
    "clipped_samples": REMEDY_LOUDNORM,
    "silence": REMEDY_RERENDER,
    "channels": REMEDY_RERENDER,
    "dc_offset": REMEDY_RERENDER,
    "edge_silence": REMEDY_RERENDER,
    "not_uniform": REMEDY_RERENDER_SEED,
    "not_blank": REMEDY_RERENDER_SEED,
    "alpha": REMEDY_RERENDER_SEED,
    IDENTITY_LOOK: REMEDY_EDIT_TEXT,
    LIGHTING_LOCK: REMEDY_RERENDER,
    IDENTITY_WRONG: REMEDY_EDIT_TEXT,
    IDENTITY_DRIFT: REMEDY_NONE,
    SHEET_REVIEW: REMEDY_NONE,
    "duration_matches_prediction": REMEDY_NONE,
    "transition_lands": REMEDY_NONE,
    "splice_duration": REMEDY_RERENDER,
    "nclips": REMEDY_REASSEMBLE,
    REFINER_HELP_CHECK: REMEDY_NONE,
    REFINE_DIFFERENTIAL: REMEDY_NONE,
}

_DEFAULT_REMEDY = {
    REMEDY_NONE: "this check has no remedy — it cannot be approved",
    REMEDY_RERENDER: "re-render",
    REMEDY_RERENDER_SEED: "re-render with a different seed",
    REMEDY_RERENDER_PINNED: "re-render pinned to a box that honours it",
    REMEDY_REASSEMBLE: "re-assemble",
    REMEDY_LOUDNORM: "re-run loudnorm",
    REMEDY_UPSCALE: "upscale pass",
    REMEDY_EDIT_TEXT: "edit the text, then re-render",
}


def is_actionable(remedy_class):
    """True when approve() has something to run. NONE is a named refusal.

    A missing class is not a refusal: finding() already rejects an
    unknown check. Legacy rows without a stored class still approve
    and fall back to kind + wording.
    """
    return remedy_class != REMEDY_NONE


def actuator_for(remedy_class, kind=None):
    """What approving this class would submit. None when there is no repair."""
    if not is_actionable(remedy_class):
        return None
    kind = (kind or "").lower()
    if remedy_class == REMEDY_UPSCALE:
        return "gen_postproc", "ltx25_latent_upscaler"
    if remedy_class == REMEDY_EDIT_TEXT:
        return "fix_ref", "qwen_image_edit_2511"
    if remedy_class in (REMEDY_LOUDNORM, REMEDY_REASSEMBLE):
        return "gen_postproc", "ltx25_latent_upscaler"
    if kind == "image":
        return "fix_ref", "qwen_image_edit_2511"
    return "gen_postproc", "ltx25_latent_upscaler"


def finding(path, kind, check, verdict, detail, measured=None, expected=None,
            unit=None, remedy=None, remedy_class=None):
    """One row of docs/TRD-3 3. measured/expected/unit are carried on every
    check that has them, because a finding that says only "failed" cannot be
    argued with and cannot be re-checked after a repair.

    remedy_class is required (T3-27). An unknown check raises rather than
    handing the reviewer a button that does nothing.
    """
    cls = remedy_class or CHECK_REMEDY_CLASS.get(check)
    if not cls:
        raise ValueError(f"check {check!r} has no remedy class (T3-27)")
    if remedy is None:
        remedy = _DEFAULT_REMEDY.get(cls)
    return {"path": path, "kind": kind, "tier": 1, "check": check,
            "verdict": verdict, "measured": measured, "expected": expected,
            "unit": unit, "detail": detail, "remedy": remedy,
            "remedy_class": cls}


def sheet_review_detail(verdict):
    """classify_sheet reasons as one sentence. Not a verdict (T10-13)."""
    parts = []
    for f in (verdict or {}).get("flagged") or []:
        if not isinstance(f, dict):
            continue
        bit = f"clip {f.get('clip')}"
        issue = str(f.get("issue") or "").strip()
        reason = str(f.get("reason") or "").strip()
        if issue:
            bit += f" {issue}"
        if reason:
            bit += f": {reason}"
        parts.append(bit)
    return "; ".join(parts) if parts else "nothing flagged"


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


def _band_mean_db(text):
    m = re.search(r"mean_volume:\s*(-?(?:\d+(?:\.\d+)?|inf)) dB", text or "")
    if not m:
        return None
    raw = m.group(1)
    if raw == "-inf":
        return float("-inf")
    if raw == "inf":
        return float("inf")
    return float(raw)


def measure_band_energy(path):
    """Mean energy in low/mid/high. RAISES if a band printed nothing.

    T3-9. Not peak volumedetect (a 1-sample click peaks at -20 dB and
    is still empty). Not aspectralstats (emits nothing without a
    metadata printer and once compared 0.0 to 0.0).
    """
    out = {}
    for name, filt in BANDS:
        r = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "info", "-i", path,
             "-af", f"{filt},volumedetect", "-f", "null", "-"],
            capture_output=True, text=True)
        val = _band_mean_db(r.stderr)
        if val is None:
            raise RuntimeError(
                f"band {name} printed no mean_volume for {path} -- refusing "
                "to report a measurement that did not happen:\n"
                + "\n".join((r.stderr or "").splitlines()[-15:]))
        out[name] = val
    return out


def measure_clipped_samples(path):
    """Count of s16 samples at digital full scale (hard-clipped rails).

    TRD-3 §4.3 clipped-sample count. Decode every channel to pcm_s16le
    and count samples at ≤−32767 or ≥32767. RAISES when no sample can
    be read — never 0 on no data. Not Peak_count (a clean sine still
    reports peaks) and not true-peak LUFS (that is effects.py).
    """
    if not path or not os.path.isfile(path):
        raise RuntimeError(
            f"clipped samples not measured: no audio file at {path}")
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path,
         "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        capture_output=True)
    raw = r.stdout or b""
    if len(raw) < 2:
        raise RuntimeError(
            f"clipped samples not measured: no pcm samples from {path}:\n"
            + "\n".join((r.stderr or b"").decode("utf-8", "replace").splitlines()[-15:]))
    import array
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
    if not samples:
        raise RuntimeError(
            f"clipped samples not measured: empty pcm from {path}")
    # s16 full scale is ±32767; lavfi hard-clips also land on -32768.
    return sum(1 for s in samples if s <= -32767 or s >= 32767)


def measure_dc_offset(path):
    """Abs mean sample as a fraction of full scale (0..1 FS).

    T3-4.3-dc / TRD-3 §4.3. Decodes every sample as f32le — not
    `astats=metadata=1,metadata=print`, which once failed to initialise
    and reported nothing on good and bad files alike. RAISES when no
    sample can be read — never 0.0 on no data.
    """
    import numpy as np
    if not path or not os.path.isfile(path):
        raise RuntimeError(
            f"dc_offset produced no readings for {path} -- refusing to "
            "report a measurement that did not happen")
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path,
         "-f", "f32le", "-acodec", "pcm_f32le", "-"],
        capture_output=True)
    raw = r.stdout or b""
    n = len(raw) // 4
    if n < 1:
        raise RuntimeError(
            f"dc_offset produced no sample readings for {path} -- refusing "
            "to report a measurement that did not happen:\n"
            + "\n".join((r.stderr or b"").decode("utf-8", "replace").splitlines()[-15:]))
    samples = np.frombuffer(raw[: n * 4], dtype=np.float32)
    # Drop non-finite; if nothing remains the file was not measured.
    samples = samples[np.isfinite(samples)]
    if samples.size < 1:
        raise RuntimeError(
            f"dc_offset produced no finite sample readings for {path} -- "
            "refusing to report a measurement that did not happen")
    return float(abs(samples.mean()))


def measure_edge_silence(path):
    """Leading and trailing silence in seconds via silencedetect.

    T3-4.3-edge / TRD-3 §4.3. Not whole-file band energy (T3-9). Zero
    on both edges is a real reading (a continuous tone). RAISES when
    audio cannot be read — never 0.0 on no data.
    """
    if not path or not os.path.isfile(path):
        raise RuntimeError(
            f"edge_silence produced no readings for {path} -- refusing to "
            "report a measurement that did not happen")
    try:
        info = mixer.probe(path)
    except Exception as e:
        raise RuntimeError(
            f"edge_silence produced no readings for {path} -- refusing to "
            f"report a measurement that did not happen: {e}") from e
    if not info.get("has_audio"):
        raise RuntimeError(
            f"edge_silence produced no audio readings for {path} -- refusing "
            "to report a measurement that did not happen")
    duration = float(info.get("duration") or 0.0)
    if duration <= 0:
        raise RuntimeError(
            f"edge_silence produced no duration for {path} -- refusing to "
            "report a measurement that did not happen")
    filt = (f"silencedetect=noise={_EDGE_SILENCE_NOISE_DB}dB:"
            f"d={_EDGE_SILENCE_MIN_S}")
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "info", "-i", path,
         "-af", filt, "-f", "null", "-"],
        capture_output=True, text=True)
    if r.returncode not in (0, None) and not (r.stderr or ""):
        raise RuntimeError(
            f"edge_silence produced no readings for {path} -- refusing to "
            "report a measurement that did not happen")
    text = r.stderr or ""
    starts = [float(m.group(1)) for m in
              re.finditer(r"silence_start:\s*(-?(?:\d+(?:\.\d+)?|inf))", text)]
    ends = [float(m.group(1)) for m in
            re.finditer(r"silence_end:\s*(-?(?:\d+(?:\.\d+)?|inf))", text)]
    # Pair starts with ends; a trailing pad may omit silence_end at EOF on
    # some builds — treat file duration as the end then.
    spans = []
    for i, start in enumerate(starts):
        if i < len(ends):
            end = ends[i]
        else:
            end = duration
        if end < start:
            continue
        spans.append((start, end, end - start))
    leading = 0.0
    trailing = 0.0
    # Leading: a span that begins at the start of the file.
    for start, end, length in spans:
        if start <= _EDGE_SILENCE_MIN_S:
            leading = max(leading, min(length, duration))
            break
    # Trailing: a span that reaches the end of the file.
    for start, end, length in reversed(spans):
        if end >= duration - _EDGE_SILENCE_MIN_S:
            trailing = max(trailing, min(length, duration))
            break
    return {"leading": leading, "trailing": trailing}


def _stderr_events(path, filt, pattern):
    """Count of events a detector filter printed to stderr (blackdetect,
    freezedetect). Absence of events is a real answer here -- "no frozen span
    found" -- so unlike _readings this does not raise on empty."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "info", "-i", path, "-vf", filt, "-f", "null", "-"],
        capture_output=True, text=True)
    return re.findall(pattern, r.stderr)


def measure_luma(path):
    """Mean YAVG over frames via signalstats. RAISES if no readings.

    TRD-3 §4.2 mean luma. Limited-range black sits near Y=16, below
    LUMA_FLOOR (24). Real neon-noir content sits above. Never 0.0 on
    no data — a missing reading raises.
    """
    vals = _readings(path, "signalstats", "lavfi.signalstats.YAVG")
    mean = sum(vals) / len(vals)
    dark = sum(1 for v in vals if v < LUMA_FLOOR)
    return {
        "mean": mean,
        "n_frames": len(vals),
        "n_dark": dark,
        "min": min(vals),
    }


def measure_pixel_std(path):
    """Max per-channel spatial RGB std for not_uniform (TRD-3 §4.1).

    A single flat colour (constant R, G and B across the frame) is 0
    even when the three channel values differ — whole-array std is not
    that reading. RAISES when the file cannot be opened as an image —
    never 0.0 on no data.
    """
    import numpy as np
    from PIL import Image
    if not path or not os.path.isfile(path):
        raise RuntimeError(
            f"pixel_std produced no readings for {path} -- refusing to "
            "report a measurement that did not happen")
    try:
        with Image.open(path) as im:
            im.load()
            arr = np.asarray(im.convert("RGB"), dtype="float32")
    except Exception as e:
        raise RuntimeError(
            f"pixel_std produced no readings for {path} -- refusing to "
            f"report a measurement that did not happen: {e}") from e
    if arr.size < 1:
        raise RuntimeError(
            f"pixel_std produced no readings for {path} -- refusing to "
            "report a measurement that did not happen")
    # axis (0,1) = spatial; channel axis left. max of R/G/B spatial std.
    return float(arr.std(axis=(0, 1)).max())


def measure_channel_sat(path):
    """Per-frame green dominance G-(R+B)/2 on a scaled RGB decode.

    TRD-3 §4.2 channel saturation. Solid green garbage (the encoded form
    of NaN frames) pushes max well above CHANNEL_SAT_LIMIT. RAISES when
    no frame could be read — never 0.0 on no data.
    """
    import numpy as np
    if not path or not os.path.isfile(path):
        raise RuntimeError(
            f"channel_sat produced no readings for {path} -- refusing to "
            "report a measurement that did not happen")
    side = _CHANNEL_SAT_SAMPLE
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path,
         "-vf", f"scale={side}:{side}", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-"],
        capture_output=True)
    raw = r.stdout or b""
    px = side * side * 3
    n = len(raw) // px
    if n < 1:
        raise RuntimeError(
            f"channel_sat produced no frame readings for {path} -- refusing "
            "to report a measurement that did not happen:\n"
            + "\n".join((r.stderr or b"").decode("utf-8", "replace").splitlines()[-15:]))
    frames = np.frombuffer(raw[: n * px], dtype=np.uint8).reshape(n, side, side, 3)
    frames = frames.astype("float64")
    # NaN cannot survive uint8 encode, but a float path that somehow
    # handed us non-finite values is the same failure mode.
    if not np.isfinite(frames).all():
        nan_frac = float((~np.isfinite(frames)).mean())
        return {
            "max": float("inf"),
            "mean": float("inf"),
            "n_frames": n,
            "n_over": n,
            "nan": True,
            "nan_frac": nan_frac,
        }
    r_m = frames[..., 0].mean(axis=(1, 2))
    g_m = frames[..., 1].mean(axis=(1, 2))
    b_m = frames[..., 2].mean(axis=(1, 2))
    dom = g_m - (r_m + b_m) / 2.0
    return {
        "max": float(dom.max()),
        "mean": float(dom.mean()),
        "n_frames": n,
        "n_over": int((dom > CHANNEL_SAT_LIMIT).sum()),
        "nan": False,
        "nan_frac": 0.0,
    }


# --------------------------------------------------------------- T5-2 MAD --

def t5_2_real_clip_frames():
    """Hook the renderer populates. None until a same-seed GPU pair lands."""
    return T5_2_REAL_CLIP_FRAMES


def record_t5_2_real_clip(plain_frames, refined_frames, seed=None):
    """Renderer calls this with decoded arrays after a refine-on/off pair."""
    global T5_2_REAL_CLIP_FRAMES, T5_2_REAL_CLIP_SEED
    T5_2_REAL_CLIP_FRAMES = (plain_frames, refined_frames)
    T5_2_REAL_CLIP_SEED = seed


def decode_video_frames(path):
    """Decode every frame as float64 RGB (n, h, w, 3). Missing path raises."""
    import numpy as np
    if not path or not os.path.isfile(path):
        raise ValueError("T5-2 real clip MAD is NOT MEASURED")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-print_format", "json",
         path],
        capture_output=True, text=True)
    streams = (json.loads(probe.stdout or "{}").get("streams") or [{}])
    s = streams[0] if streams else {}
    try:
        w, h = int(s["width"]), int(s["height"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("T5-2 real clip MAD is NOT MEASURED") from None
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path,
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True)
    if raw.returncode != 0 or not raw.stdout:
        raise ValueError("T5-2 real clip MAD is NOT MEASURED")
    buf = np.frombuffer(raw.stdout, dtype="uint8")
    pix = w * h * 3
    if pix <= 0 or buf.size % pix != 0:
        raise ValueError(f"T5-2: decoded size {buf.size} is not {w}x{h}x3")
    n = buf.size // pix
    return buf.reshape(n, h, w, 3).astype("float64")


def _as_float_frames(frames, name):
    import numpy as np
    if frames is None:
        raise ValueError("T5-2 real clip MAD is NOT MEASURED")
    if isinstance(frames, (str, bytes, os.PathLike)):
        frames = decode_video_frames(frames)
    arr = np.asarray(frames, dtype="float64")
    if arr.size == 0:
        raise ValueError(f"T5-2: empty {name} frames are not a measurement")
    return arr


def mean_absolute_difference(plain, refined):
    """Pixel MAD. Missing or empty arrays RAISE, never return 0.0."""
    import numpy as np
    a = _as_float_frames(plain, "plain")
    b = _as_float_frames(refined, "refined")
    if a.shape != b.shape:
        raise ValueError(f"T5-2: frame shape {a.shape} vs {b.shape}")
    return float(np.mean(np.abs(a - b)))


def _as_gray_frames(frames, name):
    arr = _as_float_frames(frames, name)
    if arr.ndim == 2:
        arr = arr[None, ...]
    elif arr.ndim == 3 and arr.shape[-1] in (3, 4):
        arr = arr[..., :3].mean(axis=-1)[None, ...]
    elif arr.ndim == 4:
        arr = arr[..., :3].mean(axis=-1)
    elif arr.ndim != 3:
        raise ValueError(f"T5-2: unsupported {name} frame rank {arr.ndim}")
    return arr


def laplacian_sharpness(frames):
    """Mean per-frame Laplacian variance. Higher is sharper. Empty RAISE."""
    gray = _as_gray_frames(frames, "sharpness")
    if gray.shape[-2] < 3 or gray.shape[-1] < 3:
        raise ValueError("T5-2: frames too small to measure sharpness")
    c = gray[:, 1:-1, 1:-1]
    lap = (
        gray[:, :-2, 1:-1] + gray[:, 2:, 1:-1]
        + gray[:, 1:-1, :-2] + gray[:, 1:-1, 2:]
        - 4.0 * c
    )
    var = lap.reshape(lap.shape[0], -1).var(axis=1)
    return float(var.mean())


def t5_2_refine_differential(plain, refined):
    """T5-2 numbers. Missing frames fail closed (NOT MEASURED), never skip."""
    return {
        "mad": mean_absolute_difference(plain, refined),
        "sharpness_off": laplacian_sharpness(plain),
        "sharpness_on": laplacian_sharpness(refined),
    }


def t5_2_claim():
    """The real-clip gate. MEASURED with an empty hook is still NOT MEASURED."""
    if not T5_2_REAL_CLIP_MEASURED:
        raise ValueError("T5-2 real clip MAD is NOT MEASURED")
    frames = t5_2_real_clip_frames()
    if frames is None:
        raise ValueError("T5-2 real clip MAD is NOT MEASURED")
    out = t5_2_refine_differential(*frames)
    out["seed"] = T5_2_REAL_CLIP_SEED
    return out


def accept_t5_2_gpu_pair(plain, refined, seed=None, source=None):
    """Decode a same-seed refine-off / refine-on pair and record it.

    source='gpu' is the renderer path: populate the hook and flip
    T5_2_REAL_CLIP_MEASURED. Lavfi / synthetic must pass source='harness'
    (or omit it) so the GPU flag stays False. Missing frames raise.
    """
    global T5_2_REAL_CLIP_MEASURED
    d = t5_2_refine_differential(plain, refined)
    record_t5_2_real_clip(plain, refined, seed=seed)
    d["seed"] = seed
    d["source"] = source or "harness"
    if source == "gpu":
        if t5_2_real_clip_frames() is None:
            raise ValueError("T5-2 real clip MAD is NOT MEASURED")
        T5_2_REAL_CLIP_MEASURED = True
    return d


def t5_2_finding(report, path=None):
    """T5-2 finding. MAD == 0 or sharpness not up is FLAG, not a free pass."""
    if not report or report.get("mad") is None:
        raise ValueError("T5-2 real clip MAD is NOT MEASURED")
    if report.get("sharpness_off") is None or report.get("sharpness_on") is None:
        raise ValueError("T5-2 real clip MAD is NOT MEASURED")
    path = path or "t5_2_pair"
    mad = float(report["mad"])
    off = float(report["sharpness_off"])
    on = float(report["sharpness_on"])
    changed = mad > 0
    sharper = on > off
    measured = {
        "mad": mad,
        "sharpness_off": off,
        "sharpness_on": on,
        "seed": report.get("seed"),
    }
    if changed and sharper:
        detail = (f"refine-on vs off MAD {mad:.4f}, "
                  f"Laplacian {on:.4f} > {off:.4f}")
        verdict = PASS
    elif not changed:
        detail = f"refine-on vs off MAD {mad:.4f}: no-op (identical frames)"
        verdict = FLAG
    else:
        detail = (f"refine-on vs off MAD {mad:.4f} but sharpness "
                  f"{on:.4f} <= {off:.4f}")
        verdict = FLAG
    return finding(
        path, "clip", REFINE_DIFFERENTIAL, verdict, detail,
        measured, {"mad_gt": 0, "sharpness": "up"}, "mad+laplacian")


def check_refine_differential(path, expect, kind="clip"):
    """T5-2 on a named same-seed sibling. Unasked clips stay silent."""
    expect = expect or {}
    sibling = expect.get("refine_off") or expect.get("plain")
    if not sibling:
        return []
    seed = expect.get("seed")
    seed_off = expect.get("seed_off", seed)
    seed_on = expect.get("seed_on", seed)
    if seed_off is not None and seed_on is not None and seed_off != seed_on:
        return [finding(
            path, kind, REFINE_DIFFERENTIAL, FLAG,
            f"seeds {seed_off} vs {seed_on} — T5-2 needs the same seed",
            {"seed_off": seed_off, "seed_on": seed_on},
            "same seed", None)]
    try:
        d = t5_2_refine_differential(sibling, path)
    except ValueError as e:
        if "NOT MEASURED" not in str(e):
            raise
        return [finding(
            path, kind, REFINE_DIFFERENTIAL, FLAG, str(e),
            None, "decoded pair", None)]
    d["seed"] = seed if seed is not None else seed_off
    row = t5_2_finding(d, path=path)
    row["kind"] = kind
    return [row]


def t4_13_real_sheet_path():
    """Hook the renderer populates. None until a rendered sheet is pointed at."""
    return T4_13_REAL_SHEET_PATH


def record_t4_13_real_sheet(path, sha256=None):
    """Point T4-13 at a rendered sheet. Does not flip MEASURED."""
    global T4_13_REAL_SHEET_PATH, T4_13_REAL_SHEET_SHA256
    T4_13_REAL_SHEET_PATH = path
    if sha256 is not None:
        T4_13_REAL_SHEET_SHA256 = sha256


def t4_13_sheet_sha256(path):
    import hashlib
    if not path or not os.path.isfile(path):
        raise ValueError("T4-13 real sheet channel balance is NOT MEASURED")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def backdrop_channel_means(path):
    """Mean RGB of pixels at or above mean luma (the studio wall).

    Whole-image mean is not the metric: a black figure on an olive wall
    averages toward equal channels and hides the T4-13 defect. Missing
    or empty RAISE, never 0.0.
    """
    import numpy as np
    from PIL import Image
    if not path or not os.path.isfile(path):
        raise ValueError("T4-13 real sheet channel balance is NOT MEASURED")
    try:
        with Image.open(path) as im:
            arr = np.asarray(im.convert("RGB"), dtype="float64")
    except Exception as e:
        raise ValueError("T4-13 real sheet channel balance is NOT MEASURED") from e
    if arr.size == 0 or arr.ndim != 3 or arr.shape[-1] < 3:
        raise ValueError("T4-13: empty pixels are not a measurement")
    rgb = arr[..., :3]
    luma = rgb.mean(axis=-1)
    pixels = rgb[luma >= float(luma.mean())]
    if pixels.size == 0:
        raise ValueError("T4-13: empty backdrop sample is not a measurement")
    return pixels.mean(axis=0)


def lighting_cast(means):
    """Green/magenta axis: G - (R+B)/2. Positive is olive, negative magenta."""
    r, g, b = (float(means[0]), float(means[1]), float(means[2]))
    return g - (r + b) / 2.0


def check_channel_balance(path, expect=None, kind="image"):
    """T4-13 finding. Cast on the studio wall, not the BACKDROP string."""
    means = backdrop_channel_means(path)
    cast = lighting_cast(means)
    mag = abs(cast)
    side = "olive/green" if cast >= 0 else "magenta"
    ok = mag <= LIGHTING_CAST_LIMIT
    return [finding(
        path, kind, LIGHTING_LOCK,
        PASS if ok else FLAG,
        f"backdrop {side} cast {mag:.1f} (R={means[0]:.1f} G={means[1]:.1f} "
        f"B={means[2]:.1f})",
        round(mag, 2), LIGHTING_CAST_LIMIT, "levels",
        remedy="re-render; T4-13 is even neutral studio lighting, not a colour cast")]


def t4_13_claim():
    """The real-sheet gate. MEASURED with an empty hook is still NOT MEASURED."""
    if not T4_13_REAL_SHEET_MEASURED:
        raise ValueError("T4-13 real sheet channel balance is NOT MEASURED")
    path = t4_13_real_sheet_path()
    if not path:
        raise ValueError("T4-13 real sheet channel balance is NOT MEASURED")
    digest = t4_13_sheet_sha256(path)
    expect = T4_13_REAL_SHEET_SHA256
    if not expect or digest != expect:
        raise ValueError("T4-13 real sheet channel balance is NOT MEASURED")
    return check_channel_balance(path)


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

    # ---- what the workflow / source track asked for
    if expect.get("duration"):
        d, want = info["duration"], float(expect["duration"])
        # T3-4.4-mp3: assembled song expected is songs.duration (source mp3).
        # Clips still compare to the submitted workflow request (T3-2).
        if kind == "song":
            detail = (f"{d:.3f}s against the {want:.3f}s source mp3 "
                      f"(songs.duration)")
            out.append(finding(
                path, kind, "duration",
                PASS if abs(d - want) <= DURATION_TOL_S else REJECT,
                detail, round(d, 3), round(want, 3), "s",
                remedy="re-assemble", remedy_class=REMEDY_REASSEMBLE))
        else:
            out.append(finding(
                path, kind, "duration",
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

    # T3-4.2-fps: rate vs the workflow request within FPS_TOL. unit fps (T3-4).
    # Mismatch FLAGs (retime is not a hard reject). T3-8 owns RIFE out_fps.
    if expect.get("fps"):
        f, want = info["fps"], float(expect["fps"])
        out.append(finding(path, kind, "fps",
                           PASS if abs(f - want) <= FPS_TOL else FLAG,
                           f"{f:.4f} fps against {want:.4f} requested",
                           round(f, 4), round(want, 4), "fps",
                           remedy="re-render pinned to a box that honours it"))

    # T3-4.2-resolution: exact WxH vs the workflow request. unit px (T3-4).
    if expect.get("width") and expect.get("height"):
        got = (info["width"], info["height"])
        want = (int(expect["width"]), int(expect["height"]))
        out.append(finding(path, kind, "resolution",
                           PASS if got == want else REJECT,
                           f"{got[0]}x{got[1]} against {want[0]}x{want[1]} requested",
                           f"{got[0]}x{got[1]}", f"{want[0]}x{want[1]}", "px",
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
            # T3-4.4-av: stream durations must agree. No reading is a FLAG,
            # not a silent skip (same rule as channel_sat / band energy).
            try:
                av = measure_av_durations(path)
            except RuntimeError as e:
                out.append(finding(path, kind, "av_sync", FLAG,
                                   str(e).split("\n")[0],
                                   remedy="re-assemble"))
            else:
                gap = abs(av["video"] - av["audio"])
                out.append(finding(path, kind, "av_sync",
                                   PASS if gap <= DURATION_TOL_S else FLAG,
                                   f"video {av['video']:.3f}s against audio "
                                   f"{av['audio']:.3f}s",
                                   round(gap, 3), 0.0, "s", remedy="re-assemble"))

    # ---- pixels (T3-4.2-luma: mean YAVG above LUMA_FLOOR)
    try:
        luma = measure_luma(path)
    except RuntimeError as e:
        out.append(finding(path, kind, "luma", FLAG, str(e).split("\n")[0]))
    else:
        mean = luma["mean"]
        dark = luma["n_dark"]
        n = luma["n_frames"]
        out.append(finding(path, kind, "luma",
                           PASS if mean >= LUMA_FLOOR else REJECT,
                           f"mean luma {mean:.1f} over {n} frames, "
                           f"{dark} of them below {LUMA_FLOOR}",
                           round(mean, 2), LUMA_FLOOR, "Y",
                           remedy="re-render with a different seed"))
        if dark and mean >= LUMA_FLOOR:
            out.append(finding(path, kind, "black_frames", FLAG,
                               f"{dark} of {n} frames are below the black floor",
                               dark, 0, "frames",
                               remedy="re-render with a different seed"))

    frozen = _stderr_events(path, "freezedetect=n=-60dB:d=0.5", r"freeze_start")
    out.append(finding(path, kind, "frozen",
                       PASS if not frozen else FLAG,
                       "no frozen span" if not frozen
                       else f"{len(frozen)} frozen span(s) of 0.5s or longer",
                       len(frozen), 0, "spans",
                       remedy="re-render with a different seed"))

    # ---- channel saturation: NaN / green garbage (TRD-3 §4.2)
    try:
        sat = measure_channel_sat(path)
    except RuntimeError as e:
        out.append(finding(path, kind, "channel_sat", FLAG,
                           str(e).split("\n")[0]))
    else:
        measured = round(sat["max"], 2) if sat["max"] != float("inf") else sat["max"]
        over = sat["n_over"]
        if sat.get("nan"):
            detail = (f"NaN channel values on {sat['n_frames']} frames "
                      f"(green-garbage failure mode)")
            verdict = FLAG
        elif over:
            detail = (f"green dominance max {sat['max']:.1f} over "
                      f"{sat['n_frames']} frames, {over} above "
                      f"{CHANNEL_SAT_LIMIT} (green garbage)")
            verdict = FLAG
        else:
            detail = (f"green dominance max {sat['max']:.1f} over "
                      f"{sat['n_frames']} frames, in range")
            verdict = PASS
        out.append(finding(path, kind, "channel_sat", verdict, detail,
                           measured, CHANNEL_SAT_LIMIT, "levels",
                           remedy="re-render with a different seed"))

    if kind == "song":
        out.extend(check_join_black_gap(path, expect, kind=kind))
    out.extend(check_refine_differential(path, expect, kind=kind))
    return out


def measure_av_durations(path):
    """T3-4.4-av: per-stream video and audio durations from ffprobe.

    Returns ``{"video": float, "audio": float}``. Raises when either
    stream duration is missing — never a silent empty dict or 0.0.
    """
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
         "-print_format", "json", path], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"av durations not measured: ffprobe failed on {path}")
    out = {}
    for s in json.loads(r.stdout or "{}").get("streams", []):
        if s.get("duration") not in (None, "", "N/A"):
            out[s["codec_type"]] = float(s["duration"])
    if "video" not in out or "audio" not in out:
        raise RuntimeError(
            f"av durations not measured: need video and audio stream "
            f"durations on {path}, got {sorted(out)}")
    return out


# ---------------------------------------------------- song join black gap --
# docs/TRD-3 §4.4: no black gap at an assembled song join. Whole-file
# black_frames is a different check; this one only counts black spans that
# sit on a planned join from the assembly (joins / clip_durations).

# Consecutive frames below LUMA_FLOOR that form a gap, not a one-frame glitch.
_JOIN_BLACK_MIN_FRAMES = 2


def join_times_from_expect(expect):
    """Planned join seconds from the assembly plan, or None if absent.

    `joins` is explicit. `clip_durations` becomes cumulative boundaries
    (every seam except the last clip's end). No plan → the check does
    not run; an empty list would make "no joins" look like a clean pass.
    """
    expect = expect or {}
    joins = expect.get("joins")
    if joins is not None:
        out = [float(t) for t in joins]
        return out if out else None
    durs = expect.get("clip_durations")
    if not durs or len(durs) < 2:
        return None
    t, out = 0.0, []
    for d in durs[:-1]:
        t += float(d)
        out.append(round(t, 4))
    return out if out else None


def measure_black_spans(path, min_frames=_JOIN_BLACK_MIN_FRAMES):
    """Black runs as (start_s, end_s, n_frames). RAISES if no frames.

    A frame is black when mean Y < LUMA_FLOOR (same floor as black_frames).
    min_frames keeps a single encoder glitch from becoming a gap.
    """
    info = mixer.probe(path)
    fps = float(info.get("fps") or 0.0)
    if fps <= 0:
        raise RuntimeError(f"no fps on {path} — refusing a black-span measure")
    luma = _readings(path, "signalstats", "lavfi.signalstats.YAVG")
    if not luma:
        raise RuntimeError(f"no luma readings for {path}")
    spans = []
    i = 0
    n = len(luma)
    while i < n:
        if luma[i] < LUMA_FLOOR:
            j = i
            while j < n and luma[j] < LUMA_FLOOR:
                j += 1
            if j - i >= min_frames:
                spans.append((i / fps, j / fps, j - i))
            i = j
        else:
            i += 1
    return spans


def measure_join_black_gap(path, joins):
    """Join times that fall inside a black span. docs/TRD-3 §4.4.

    Half-frame slop so a join on the first black frame still hits.
    RAISES when joins is empty or frames cannot be read.
    """
    if not joins:
        raise RuntimeError("no joins — refusing a join-black-gap measure")
    info = mixer.probe(path)
    fps = float(info.get("fps") or 0.0)
    if fps <= 0:
        raise RuntimeError(f"no fps on {path} — refusing a join-black-gap measure")
    spans = measure_black_spans(path)
    half = 0.5 / fps
    hits = []
    for j in joins:
        jt = float(j)
        for start, end, _n in spans:
            if start - half <= jt <= end + half:
                hits.append(round(jt, 4))
                break
    return hits


def check_join_black_gap(path, expect, kind="song"):
    """T3-4.4-gap: no black gap at an assembled song join.

    Without joins / clip_durations the check does not run. measured is
    the count of planned joins that sit inside a black span; expected
    is always 0. Remedy is re-assemble.
    """
    joins = join_times_from_expect(expect)
    if joins is None:
        return []
    try:
        hits = measure_join_black_gap(path, joins)
    except Exception as e:
        return [finding(path, kind, "join_black_gap", REJECT,
                        str(e).split("\n")[0],
                        remedy="re-assemble")]
    n = len(hits)
    if n == 0:
        detail = f"no black gap at {len(joins)} planned join(s)"
    else:
        detail = (f"{n} black gap(s) at planned join(s) {hits} "
                  f"(of {len(joins)} join(s))")
    return [finding(path, kind, "join_black_gap",
                    PASS if n == 0 else REJECT, detail,
                    n, 0, "spans",
                    remedy="re-assemble")]


# ------------------------------------------------------------------ audio --

def _splice_expect(expect):
    """source + start + end, or nothing. Missing any one is not a splice."""
    expect = expect or {}
    source = expect.get("source") or expect.get("mp3_path")
    start = expect.get("start")
    end = expect.get("end")
    span = expect.get("span") or expect.get("bridge")
    if isinstance(span, dict):
        if start is None:
            start = span.get("start")
        if end is None:
            end = span.get("end")
        if source is None:
            source = span.get("source") or span.get("mp3_path")
    if source is None or start is None or end is None:
        return None
    return source, float(start), float(end)


def check_splice(path, expect):
    """T3-10: spliced-track duration vs mixer.bridge_seconds() arithmetic.

    The 20 s / 0.1 s case lengthened the song to 20.193 s. The prediction
    is mixer.spliced_duration, which asks bridge_seconds rather than
    restating gap + 2×xfade. No splice keys means this check does not run.
    """
    spec = _splice_expect(expect)
    if spec is None:
        return []
    source, start, end = spec
    expect = expect or {}
    if not os.path.isfile(path):
        return [finding(path, "audio", "opens", REJECT, "file does not exist",
                        remedy="re-render")]
    xfade = expect.get("xfade", mixer.SPLICE_XFADE)
    bridge_len = expect.get("bridge_len")
    if bridge_len is None:
        bridge_path = expect.get("bridge_path")
        if not bridge_path and isinstance(expect.get("bridge"), str):
            bridge_path = expect.get("bridge")
        if bridge_path:
            try:
                bridge_len = mixer.probe(bridge_path)["duration"]
            except Exception as e:
                return [finding(path, "audio", "splice_duration", FLAG,
                                f"cannot probe the bridge: {e}",
                                remedy="re-splice; size the bridge with "
                                       "mixer.bridge_seconds()")]
    try:
        predicted = mixer.spliced_duration(
            source, start, end, bridge_len=bridge_len, xfade=xfade)
        actual = mixer.probe(path)["duration"]
    except Exception as e:
        return [finding(path, "audio", "splice_duration", FLAG,
                        f"cannot predict spliced duration: {e}",
                        remedy="re-splice; size the bridge with "
                               "mixer.bridge_seconds()")]
    gap = abs(actual - predicted)
    return [finding(path, "audio", "splice_duration",
                    PASS if gap <= mixer.SPLICE_DURATION_TOLERANCE else REJECT,
                    f"spliced {actual:.3f}s against "
                    f"{predicted:.3f}s from mixer.bridge_seconds()",
                    round(actual, 3), round(predicted, 3), "s",
                    remedy="re-splice; size the bridge with "
                           "mixer.bridge_seconds()")]


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

    # T3-4.3-sr: sample rate as requested. Exact Hz; no soft tolerance.
    # Without expect.sample_rate the check is silent (as requested only).
    if expect.get("sample_rate"):
        got = int(info.get("sample_rate") or 0)
        want = int(expect["sample_rate"])
        if not got:
            out.append(finding(path, "audio", "sample_rate", REJECT,
                               "no sample_rate reading on audio stream",
                               None, want, "Hz", remedy="re-render"))
        else:
            out.append(finding(path, "audio", "sample_rate",
                               PASS if got == want else REJECT,
                               f"{got} Hz against {want} Hz requested",
                               got, want, "Hz", remedy="re-render"))

    # T3-4.3-ch: channel count as requested. Probe owns the reading.
    if expect.get("channels") is not None:
        got = int(info["channels"])
        want = int(expect["channels"])
        out.append(finding(path, "audio", "channels",
                           PASS if got == want else REJECT,
                           f"{got} channel(s) against {want} requested",
                           got, want, "ch", remedy="re-render"))

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
        # T3-4.3-true-peak: FLAG/PASS vs LOUDNORM_TP + TRUE_PEAK_TOLERANCE_DB.
        if loud["true_peak_db"] is None:
            out.append(finding(path, "audio", "true_peak", FLAG,
                               "ebur128 printed no true peak",
                               None, effects.LOUDNORM_TP, "dBFS",
                               remedy="re-run loudnorm"))
        else:
            over = (loud["true_peak_db"]
                    > effects.LOUDNORM_TP + effects.TRUE_PEAK_TOLERANCE_DB)
            out.append(finding(path, "audio", "true_peak",
                               FLAG if over else PASS,
                               f"{loud['true_peak_db']:.1f} dBFS against "
                               f"{effects.LOUDNORM_TP:.1f} ceiling",
                               loud["true_peak_db"], effects.LOUDNORM_TP, "dBFS",
                               remedy="re-run loudnorm"))

    # T3-4.3-clip: hard-clipped sample count (s16 rails). §4.3.
    try:
        n_clip = measure_clipped_samples(path)
    except RuntimeError as e:
        out.append(finding(path, "audio", "clipped_samples", FLAG,
                           str(e).split("\n")[0]))
    else:
        over = n_clip > CLIPPED_SAMPLES_LIMIT
        out.append(finding(
            path, "audio", "clipped_samples",
            FLAG if over else PASS,
            (f"{n_clip} clipped sample(s) at digital full scale"
             if over else "no clipped samples at digital full scale"),
            int(n_clip), CLIPPED_SAMPLES_LIMIT, "samples",
            remedy="re-run loudnorm"))

    # T3-9. Loudest of low/mid/high mean energy, never peak volumedetect.
    try:
        bands = measure_band_energy(path)
    except RuntimeError as e:
        out.append(finding(path, "audio", "silence", FLAG, str(e).split("\n")[0]))
    else:
        loudest = max(bands.values())
        measured = {k: round(bands[k], 1) for k in ("low", "mid", "high")}
        out.append(finding(
            path, "audio", "silence",
            PASS if loudest > SILENCE_FLOOR_DB else REJECT,
            f"low {bands['low']:.1f} / mid {bands['mid']:.1f} / high "
            f"{bands['high']:.1f} dB (loudest {loudest:.1f})",
            measured, SILENCE_FLOOR_DB, "dB", remedy="re-render"))

    # T3-4.3-dc. Abs mean sample vs DC_OFFSET_LIMIT (full-scale fraction).
    try:
        dc = measure_dc_offset(path)
    except RuntimeError as e:
        out.append(finding(path, "audio", "dc_offset", FLAG, str(e).split("\n")[0]))
    else:
        out.append(finding(
            path, "audio", "dc_offset",
            FLAG if dc > DC_OFFSET_LIMIT else PASS,
            f"DC offset {dc:.4f} FS against {DC_OFFSET_LIMIT:.2f} limit",
            round(dc, 6), DC_OFFSET_LIMIT, "FS", remedy="re-render"))

    # T3-4.3-edge. Leading/trailing pad, not whole-file band energy.
    try:
        edges = measure_edge_silence(path)
    except RuntimeError as e:
        out.append(finding(path, "audio", "edge_silence", FLAG,
                           str(e).split("\n")[0]))
    else:
        worst = max(edges["leading"], edges["trailing"])
        measured = {k: round(edges[k], 3) for k in ("leading", "trailing")}
        out.append(finding(
            path, "audio", "edge_silence",
            FLAG if worst > EDGE_SILENCE_LIMIT_S else PASS,
            f"leading {edges['leading']:.3f}s / trailing "
            f"{edges['trailing']:.3f}s (limit {EDGE_SILENCE_LIMIT_S:.2f}s)",
            measured, EDGE_SILENCE_LIMIT_S, "s", remedy="re-render"))
    out.extend(check_splice(path, expect))
    return out


# ------------------------------------------------------------------ image --

def _norm_ref(value):
    text = str(value or "").strip()
    return os.path.normpath(text) if text else ""


def _compose_text(expect):
    return " ".join(str(expect.get(k) or "") for k in
                    ("composed", "prompt", "nude_wardrobe", "body"))


def _human_body_hits(text):
    low = (text or "").lower()
    return [p for p in HUMAN_BODY_PHRASES if p in low]


def check_identity_look(path, expect, kind="image"):
    """T7-7 hook. No pixels, no model: name the identity ref, and it must not
    be the pose plate. Missing identity_path flags. A distinct named path
    passes the prerequisite; the picture stays a human look.

    A compose that asserts a human body (T4-14: nude_wardrobe "human form"
    in composed/prompt/body) flags even when the identity path is missing
    or is the chosen ref. Missing identity_path must not hide that reason.
    """
    expect = expect or {}
    identity = _norm_ref(expect.get("identity_path"))
    plate = _norm_ref(expect.get("plate_path"))
    remedy = ("condition the sheet on the chosen identity ref "
              "(UI pair / meowp_ui_front.png), not the pose plate")
    hits = _human_body_hits(_compose_text(expect))
    if hits:
        return [finding(path, kind, IDENTITY_LOOK, FLAG,
                        f"composed prompt asserts {hits[0]}; "
                        "T4-14 / T7-7 refuse a human-body sheet",
                        hits[0], "not a human-body compose", None,
                        "drop human-body wording from nude_wardrobe; "
                        "surface comes from the body clause")]
    if not identity:
        return [finding(path, kind, IDENTITY_LOOK, FLAG,
                        "T7-7 identity look needs a named identity reference; none was given",
                        None, "identity_path", None, remedy)]
    if plate and identity == plate:
        return [finding(path, kind, IDENTITY_LOOK, FLAG,
                        "identity_path is the pose plate; T7-7 requires the chosen identity ref",
                        identity, "identity_path != plate_path", None, remedy)]
    return [finding(path, kind, IDENTITY_LOOK, PASS,
                    f"identity ref {os.path.basename(identity)}; T7-7 look remains human-judged",
                    identity, identity, None)]


def _wants_identity_look(expect):
    expect = expect or {}
    if (bool(expect.get("identity_look"))
            or "identity_path" in expect
            or "plate_path" in expect):
        return True
    return bool(_human_body_hits(_compose_text(expect)))


def proposes_reference_swap(text):
    """True when a remedy tells the operator to swap the reference image."""
    low = (text or "").lower()
    if "reference" not in low:
        return False
    return any(m in low for m in _REFERENCE_SWAP_MARKERS)


def identity_wrong_remedy(text=None):
    """T3-28: identity-wrong never proposes swapping the reference image."""
    text = (text or "").strip() or IDENTITY_WRONG_REMEDY
    if proposes_reference_swap(text):
        raise ValueError(
            "identity-wrong remedy cannot propose swapping the reference "
            "image — identity comes from the text")
    return text


def check_identity_wrong(path, expect, kind="clip"):
    """Identity wrong from the first frame. Offline: expect-driven.

    T3-30: path + expect, no database. The finding's remedy is edit the
    text; swapping the reference is refused by identity_wrong_remedy.
    """
    expect = expect or {}
    if not (expect.get("identity_wrong")
            or expect.get("first_frame_identity") == "wrong"):
        return []
    return [finding(
        path, kind, IDENTITY_WRONG, FLAG,
        "identity is wrong from the first frame — edit the text, then re-render",
        expect.get("identity_wrong") or "wrong", "feline", None,
        identity_wrong_remedy())]


def measure_alpha(path):
    """Max/mean alpha over an image (0–255). RGB without alpha is 255.

    T3-4.1-alpha: fully transparent is max 0. Raises when the path is
    not a readable image — never 0.0 on no data.
    """
    from PIL import Image
    import numpy as np
    try:
        with Image.open(path) as im:
            im.load()
            has_alpha = (
                im.mode in ("RGBA", "LA", "PA")
                or (im.mode == "P" and "transparency" in im.info)
            )
            if not has_alpha:
                return {"max": 255.0, "mean": 255.0}
            a = np.asarray(im.convert("RGBA"), dtype="float32")[..., 3]
            if a.size == 0:
                raise RuntimeError(
                    f"alpha produced no readings for {path} -- refusing to "
                    f"report 0.0 on no data")
            return {"max": float(a.max()), "mean": float(a.mean())}
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(
            f"alpha not measured for {path}: {e}") from e


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

    # T3-4.1-resolution: exact WxH vs the request. unit px (T3-4).
    if expect.get("width") and expect.get("height"):
        want = (int(expect["width"]), int(expect["height"]))
        out.append(finding(path, "image", "resolution",
                           PASS if got == want else REJECT,
                           f"{got[0]}x{got[1]} against {want[0]}x{want[1]} requested",
                           f"{got[0]}x{got[1]}", f"{want[0]}x{want[1]}", "px",
                           remedy="re-render pinned to a box that honours it"))

    # T3-4.1-not_uniform: max per-channel spatial std. Whole-array std
    # PASSes solid red (R≠G≠B); channel-wise max does not.
    std = float(arr.std(axis=(0, 1)).max())
    out.append(finding(path, "image", "not_uniform",
                       PASS if std > UNIFORM_STD_FLOOR else REJECT,
                       f"pixel standard deviation {std:.2f}",
                       round(std, 2), UNIFORM_STD_FLOOR, "levels",
                       remedy="re-render with a different seed"))
    mean = float(arr.mean())
    out.append(finding(path, "image", "not_blank",
                       PASS if mean >= LUMA_FLOOR else REJECT,
                       f"mean level {mean:.1f}",
                       round(mean, 1), LUMA_FLOOR, "levels",
                       remedy="re-render with a different seed"))
    # T3-4.1-alpha: alpha not fully transparent. RGB without alpha is
    # opaque (max 255). All-zero alpha REJECTs — no judgement.
    try:
        alpha = measure_alpha(path)
    except RuntimeError as e:
        out.append(finding(path, "image", "alpha", REJECT,
                           str(e).split("\n")[0],
                           None, ALPHA_MIN, "levels",
                           remedy="re-render with a different seed"))
    else:
        amax = alpha["max"]
        out.append(finding(
            path, "image", "alpha",
            PASS if amax >= ALPHA_MIN else REJECT,
            (f"max alpha {amax:.0f}" if amax >= ALPHA_MIN
             else f"fully transparent (max alpha {amax:.0f})"),
            round(amax, 1), ALPHA_MIN, "levels",
            remedy="re-render with a different seed"))
    if _wants_identity_look(expect):
        out.extend(check_identity_look(path, expect, kind="image"))
    out.extend(check_channel_balance(path, expect, kind="image"))
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
                       remedy="no remedy — a divergence between the stored "
                              "model and the filter graph; never fixed by "
                              "re-rendering"))
    if len(items) >= 2:
        out.extend(check_transition_lands(path, items))
    return out


# A colour jump well above encoder noise on a still, well below a
# red-to-blue cut. Same number the T3-12 test uses for its independent
# reading, so measured equals that reading rather than a second threshold.
_LAND_DELTA = 40.0


def measure_transition_lands(path):
    """Landing times of visual joins, from the pixels. docs/TRD-3 T3-12.

    A cut is a single-frame colour jump. Time is first frame of the new
    colour over the file's own fps. Raises if it cannot read frames —
    an empty list would make "no join" look like a clean pass.
    """
    info = mixer.probe(path)
    fps = float(info.get("fps") or 0.0)
    if fps <= 0:
        raise RuntimeError(f"no fps on {path} — refusing a land time")
    frames = _frame_mean_rgb(path)
    if len(frames) < 2:
        raise RuntimeError(f"need 2+ frames to locate a join in {path}")
    lands = []
    prev = frames[0]
    for i in range(1, len(frames)):
        r, g, b = frames[i]
        pr, pg, pb = prev
        delta = ((r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2) ** 0.5
        if delta >= _LAND_DELTA:
            lands.append(round(i / fps, 4))
            prev = frames[i]
    if not lands:
        raise RuntimeError(
            f"no visual join in {path} — refusing a measurement that "
            "did not happen")
    return lands


def _frame_mean_rgb(path):
    """Mean RGB of every frame, 8x8. Raises if ffmpeg produced no pixels."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path,
         "-vf", "scale=8:8,format=rgb24", "-f", "rawvideo", "-"],
        capture_output=True)
    if r.returncode != 0 or not r.stdout:
        err = (r.stderr or b"").decode("utf-8", "replace")
        raise RuntimeError(
            f"no frames from {path} — refusing a land time:\n"
            + "\n".join(err.splitlines()[-10:]))
    n = 8 * 8 * 3
    buf = r.stdout
    if len(buf) < n:
        raise RuntimeError(f"no complete frame in {path}")
    frames = []
    for i in range(0, len(buf) // n * n, n):
        chunk = buf[i:i + n]
        px = len(chunk) // 3
        frames.append((
            sum(chunk[0::3]) / px,
            sum(chunk[1::3]) / px,
            sum(chunk[2::3]) / px,
        ))
    return frames


def check_transition_lands(path, items):
    """T3-12: each model join vs the picture, within half a frame.

    Tolerance is 0.5 / the file's own fps, not a restated constant.
    Remedy is none — a model/graph split is not a re-render.
    """
    try:
        expected = mixer.transition_times(items)
        measured = measure_transition_lands(path)
        fps = float(mixer.probe(path)["fps"] or 0.0)
    except Exception as e:
        return [finding(path, "set", "transition_lands", REJECT,
                        str(e).split("\n")[0],
                        remedy="no remedy — a divergence between the stored "
                               "model and the filter graph; never fixed by "
                               "re-rendering")]
    if fps <= 0:
        return [finding(path, "set", "transition_lands", REJECT,
                        "rendered file has no fps — cannot price half a frame",
                        remedy="no remedy — a divergence between the stored "
                               "model and the filter graph; never fixed by "
                               "re-rendering")]
    half = 0.5 / fps
    want = [round(float(t), 4) for t in expected]
    ok = (len(measured) == len(want)
          and all(abs(m - e) <= half for m, e in zip(measured, want)))
    if not ok:
        detail = (f"rendered lands {measured} against model {want} "
                  f"(half-frame {half:.4f}s at {fps:.4f} fps)")
    else:
        detail = (f"rendered lands {measured} match model {want} "
                  f"within half a frame ({half:.4f}s)")
    return [finding(path, "set", "transition_lands",
                    PASS if ok else REJECT, detail,
                    measured, want, "s",
                    remedy="no remedy — a divergence between the stored "
                           "model and the filter graph; never fixed by "
                           "re-rendering")]


def _has_video(path):
    try:
        return mixer.probe(path)["has_video"]
    except Exception:
        return False


# --------------------------------------------- assembled song, §4.4 --

def _build_song():
    """THE clip_plan owner. Lazy so qc import stays light for stills."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    import build_song  # noqa: E402  -- single owner of clip allocation
    return build_song


def _measured_nclips(expect):
    """How many clips went into the assemble. None when no claim."""
    expect = expect or {}
    if expect.get("nclips") is not None:
        return int(expect["nclips"])
    if expect.get("clip_count") is not None:
        return int(expect["clip_count"])
    clips = expect.get("clips")
    if clips is not None:
        return len(clips)
    return None


def planned_nclips(expect):
    """len(build_song.clip_plan(...)). THE expected count for T3-4.4-nclips.

    Goes through clip_plan, not a second ceil and not scene_count. A
    20-scene board on a 41-clip track still expects 41.
    """
    expect = expect or {}
    scenes = expect.get("scenes") or []
    if not scenes:
        raise ValueError("scenes required for clip_plan")
    bs = _build_song()
    if expect.get("audio_path"):
        plan = bs.clip_plan(scenes, audio_path=expect["audio_path"])
    else:
        if expect.get("duration") is None:
            raise ValueError("duration or audio_path required for clip_plan")
        n = bs.n_clips_for(float(expect["duration"]),
                           expect.get("scene_seconds"))
        plan = bs.clip_plan(scenes, nclips=n)
    return len(plan)


def check_nclips(path, expect, kind="song"):
    """T3-4.4-nclips: assembled clip count vs build_song.clip_plan.

    Measured is how many clips the assemble used (expect.nclips or
    len(expect.clips)). Expected is len(clip_plan). No claim → no
    finding (do not invent a pass).
    """
    measured = _measured_nclips(expect)
    if measured is None:
        return []
    try:
        expected = planned_nclips(expect)
    except Exception as e:
        return [finding(path, kind, "nclips", REJECT,
                        str(e).split("\n")[0],
                        measured, None, "clips",
                        remedy="re-assemble with every planned clip")]
    ok = measured == expected
    return [finding(
        path, kind, "nclips",
        PASS if ok else REJECT,
        (f"{measured} clips against clip_plan {expected}"
         if not ok else
         f"{measured} clips match clip_plan"),
        measured, expected, "clips",
        remedy="re-assemble with every planned clip")]


# -------------------------------------------------------- tier 2 score --
# T3-13. Pure measurement: no database, no threshold, no verdict. The
# report is overlap, separation, and every file. A later extractor plugs
# in as embed= or score_fn=; pixel MSE is not an extractor.


def zimage_label(path):
    """good|bad from the recorded seed. An unknown name raises."""
    name = os.path.basename(path)
    m = _ZIMAGE_SEED_RE.search(name)
    if not m:
        raise RuntimeError(f"zimage_sweep file has no seed: {path}")
    seed = int(m.group(1))
    if seed in ZIMAGE_GOOD_SEEDS:
        return "good", seed
    if seed in ZIMAGE_BAD_SEEDS:
        return "bad", seed
    raise RuntimeError(f"unknown zimage_sweep seed {seed} in {path}")


def list_zimage_sweep(root):
    """The 18 labelled stills. A short or extra set raises, not a skip."""
    if not os.path.isdir(root):
        raise RuntimeError(f"zimage_sweep directory missing: {root}")
    items = []
    for name in sorted(os.listdir(root)):
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        label, seed = zimage_label(path)
        items.append({"path": path, "label": label, "seed": seed})
    n_good = sum(1 for i in items if i["label"] == "good")
    n_bad = sum(1 for i in items if i["label"] == "bad")
    if n_good != 6 or n_bad != 12:
        raise RuntimeError(
            f"zimage_sweep must be 12 known-bad and 6 known-good; "
            f"got {n_bad} bad, {n_good} good under {root}")
    return items


def identity_embed_array(arr):
    """Colour histogram of an RGB array. Same bins as identity_embed."""
    import numpy as np
    arr = np.asarray(arr, dtype="float32")
    if arr.ndim == 3 and arr.shape[-1] >= 4:
        arr = arr[..., :3]
    if arr.size == 0 or arr.ndim != 3 or arr.shape[-1] != 3:
        raise RuntimeError("identity embed: empty image")
    q = np.clip((arr / 64.0).astype("int32"), 0, 3)
    idx = q[:, :, 0] * 16 + q[:, :, 1] * 4 + q[:, :, 2]
    hist = np.bincount(idx.ravel(), minlength=64).astype("float64")
    total = float(hist.sum())
    if total == 0.0:
        raise RuntimeError("identity embed: empty image")
    return (hist / total).tolist()


def identity_embed(path):
    """Colour histogram. Not flattened pixels, not a spatial grid.

    Pixel distance is refused by name (docs/TRD-3 §5 / T3-15): it ranked
    the pose-plate look above a deliberate pose change. Identity here is
    the colour distribution so pose is not the score. siglip2_naflex
    replaces this later as embed= without changing the report shape.
    """
    from PIL import Image
    import numpy as np
    if not os.path.isfile(path):
        raise RuntimeError(f"identity embed: file does not exist: {path}")
    with Image.open(path) as im:
        arr = np.asarray(im.convert("RGB"), dtype="float32")
    if arr.size == 0:
        raise RuntimeError(f"identity embed: empty image: {path}")
    return identity_embed_array(arr)


def _cosine(a, b):
    import math
    if len(a) != len(b) or not a:
        raise RuntimeError("identity score compared embeddings of different rank")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        raise RuntimeError("identity score got a zero embedding")
    return dot / (na * nb)


def identity_score(path, reference, embed=None):
    """Cosine of path's embedding against a reference vector."""
    embed = embed or identity_embed
    vec = embed(path)
    return _cosine(vec, list(reference))


def _t7_7_require(path, slot):
    if not path or not os.path.isfile(path):
        raise ValueError(f"T7-7 {slot} is NOT MEASURED")
    return os.path.normpath(path)


def _t7_7_file_digest(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.digest()


def _t7_7_view_pair_score(front, three_quarter, embed):
    if front == three_quarter or _t7_7_file_digest(front) == _t7_7_file_digest(three_quarter):
        raise ValueError(
            "T7-7 pair is not a front/three_quarter differential")
    return identity_score(three_quarter, embed(front), embed=embed)


def t7_7_identity_differential(anchor_front, anchor_three_quarter,
                               photo_front, photo_three_quarter, embed=None):
    """T7-7 ranking. Missing images raise NOT MEASURED. No threshold.

    identity_embed is the colour histogram (T3-15): pose is not the
    score. Pixel distance inverts this pair and is refused.
    """
    embed = embed or identity_embed
    af = _t7_7_require(anchor_front, "anchor_front")
    atq = _t7_7_require(anchor_three_quarter, "anchor_three_quarter")
    pf = _t7_7_require(photo_front, "photo_front")
    ptq = _t7_7_require(photo_three_quarter, "photo_three_quarter")
    anchor_pair = _t7_7_view_pair_score(af, atq, embed)
    photo_pair = _t7_7_view_pair_score(pf, ptq, embed)
    return {
        "metric": IDENTITY_METRIC,
        "views": ("front", "three_quarter"),
        "anchor_pair": anchor_pair,
        "photo_pair": photo_pair,
        "held": anchor_pair > photo_pair,
        "threshold": None,
    }


def t7_7_real_pair():
    """Hook the renderer populates. None until a GPU four-image set lands."""
    return T7_7_REAL_PAIR


def t7_7_pair_sha256(anchor_front, anchor_three_quarter,
                     photo_front, photo_three_quarter):
    """Four hex digests. Missing files raise NOT MEASURED."""
    paths = (
        _t7_7_require(anchor_front, "anchor_front"),
        _t7_7_require(anchor_three_quarter, "anchor_three_quarter"),
        _t7_7_require(photo_front, "photo_front"),
        _t7_7_require(photo_three_quarter, "photo_three_quarter"),
    )
    return tuple(_t7_7_file_digest(p).hex() for p in paths)


def record_t7_7_real_pair(anchor_front, anchor_three_quarter,
                          photo_front, photo_three_quarter, sha256=None):
    """Renderer calls this with the four rendered paths. Does not flip MEASURED."""
    global T7_7_REAL_PAIR, T7_7_REAL_PAIR_SHA256
    T7_7_REAL_PAIR = (
        anchor_front, anchor_three_quarter, photo_front, photo_three_quarter)
    T7_7_REAL_PAIR_SHA256 = sha256 or t7_7_pair_sha256(*T7_7_REAL_PAIR)


def t7_7_claim():
    """The real-pair gate. MEASURED with an empty hook is still NOT MEASURED."""
    if not T7_7_REAL_PAIR_MEASURED:
        raise ValueError("T7-7 real pair is NOT MEASURED")
    pair = t7_7_real_pair()
    if pair is None:
        raise ValueError("T7-7 real pair is NOT MEASURED")
    expect = T7_7_REAL_PAIR_SHA256
    if not expect or t7_7_pair_sha256(*pair) != expect:
        raise ValueError("T7-7 real pair is NOT MEASURED")
    return t7_7_identity_differential(*pair)


def identity_verdict(overlap):
    """T3-16: overlapping ranges cannot split known-good from known-bad."""
    if overlap is None:
        raise RuntimeError("identity verdict needs an overlap")
    return INCONCLUSIVE if float(overlap) > 0 else SEPARATED


def range_overlap(xs, ys):
    """Intersection / union of two closed score ranges. Empty raises."""
    if not xs or not ys:
        raise RuntimeError("cannot report overlap of an empty distribution")
    lo_a, hi_a = min(xs), max(xs)
    lo_b, hi_b = min(ys), max(ys)
    inter = max(0.0, min(hi_a, hi_b) - max(lo_a, lo_b))
    union = max(hi_a, hi_b) - min(lo_a, lo_b)
    if union == 0.0:
        return 1.0
    return inter / union


def mean_separation(good, bad):
    """mean(good) - mean(bad). Empty raises."""
    if not good or not bad:
        raise RuntimeError("cannot report separation of an empty distribution")
    return (sum(good) / len(good)) - (sum(bad) / len(bad))


def score_zimage_sweep(root, reference=None, embed=None, score_fn=None):
    """T3-13 report: 12 bad, 6 good, overlap, separation, every file.

    threshold is always None. A score_fn is how tests pin the arithmetic;
    production passes a reference embedding (or path) and embed=.
    """
    items = list_zimage_sweep(root)
    embed = embed or identity_embed
    ref_vec = None
    if score_fn is None:
        if reference is None:
            raise RuntimeError(
                "score_zimage_sweep needs a reference embedding or a score_fn")
        try:
            ref_vec = list(reference)
            if not ref_vec or isinstance(reference, (str, bytes)):
                raise TypeError
        except TypeError:
            ref_vec = embed(reference)
    rows = []
    for item in items:
        if score_fn is not None:
            score = float(score_fn(item["path"], item["label"]))
        else:
            score = identity_score(item["path"], ref_vec, embed=embed)
        rows.append({"path": item["path"], "label": item["label"],
                     "seed": item["seed"], "score": score})
    good = [r["score"] for r in rows if r["label"] == "good"]
    bad = [r["score"] for r in rows if r["label"] == "bad"]
    return {
        "metric": IDENTITY_METRIC,
        "dataset": "zimage_sweep",
        "n_good": len(good),
        "n_bad": len(bad),
        "overlap": range_overlap(good, bad),
        "separation": mean_separation(good, bad),
        "scores": rows,
        "threshold": None,
    }


def _sample_indices(length, n):
    if length <= 0:
        raise RuntimeError("identity drift: no frames")
    n = int(n)
    if n < 1:
        raise RuntimeError("identity drift needs a sample count")
    n = min(n, length)
    if n == 1:
        return [0]
    return [int(round(i * (length - 1) / (n - 1))) for i in range(n)]


def _stdev(xs):
    if len(xs) < 2:
        return 0.0
    mean = sum(xs) / len(xs)
    return (sum((x - mean) ** 2 for x in xs) / len(xs)) ** 0.5


def sample_identity_frames(path, n=IDENTITY_SAMPLE_N):
    """Evenly sample up to n RGB frames. A still is one frame."""
    from PIL import Image
    import numpy as np
    if not path or not os.path.isfile(path):
        raise RuntimeError(f"identity drift: file does not exist: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMAGE_EXT:
        with Image.open(path) as im:
            arr = np.asarray(im.convert("RGB"))
        if arr.size == 0:
            raise RuntimeError(f"identity drift: empty image: {path}")
        return [arr]
    frames = decode_video_frames(path)
    if frames is None or len(frames) == 0:
        raise RuntimeError(f"identity drift: no frames in {path}")
    return [frames[i] for i in _sample_indices(len(frames), n)]


def score_identity_artefact(path, anchor, n=None):
    """T3-17: identity of one artefact vs the chosen anchor.

    Cause-agnostic: does not inspect character_reference or prompt text.
    Scores the pixels. No threshold, no verdict, no gate. A still reports
    n=1 and variation 0; a clip reports the spread across sampled frames.
    """
    if not anchor or not str(anchor).strip():
        raise RuntimeError("identity drift needs a chosen anchor")
    anchor = str(anchor)
    if not os.path.isfile(anchor):
        raise RuntimeError(
            f"identity drift: chosen anchor does not exist: {anchor}")
    if not path or not os.path.isfile(path):
        raise RuntimeError(f"identity drift: file does not exist: {path}")
    ref = identity_embed(anchor)
    frames = sample_identity_frames(
        path, IDENTITY_SAMPLE_N if n is None else n)
    scores = [_cosine(identity_embed_array(frame), ref) for frame in frames]
    mean = sum(scores) / len(scores)
    return {
        "path": path,
        "anchor": anchor,
        "metric": IDENTITY_METRIC,
        "tier": 2,
        "check": IDENTITY_DRIFT,
        "score": mean,
        "compliance": mean * 100.0,
        "variation": _stdev(scores),
        "n": len(scores),
        "scores": scores,
        "threshold": None,
    }


# --------------------------------------------- T3-26 refiner help --
# Fail-closed on a labelled set. Opportunistic is not a measurement.


def _t326_not_measured(why=""):
    msg = "T3-26 labelled set is NOT MEASURED"
    if why:
        msg = f"{msg}: {why}"
    raise ValueError(msg)


def _t326_score_fn(score_fn, reference, embed):
    if score_fn is not None:
        return score_fn
    if reference is None:
        _t326_not_measured("no score_fn and no reference")
    embed = embed or identity_embed
    try:
        ref_vec = list(reference)
        if not ref_vec or isinstance(reference, (str, bytes)):
            raise TypeError
    except TypeError:
        if not os.path.isfile(reference):
            _t326_not_measured("reference missing")
        ref_vec = embed(reference)
    return lambda path, label: identity_score(path, ref_vec, embed=embed)


def measure_refiner_help(pairs, score_fn=None, reference=None, embed=None):
    """T3-26: does refine improve the tier-2 score on a labelled set?

    Empty set, missing files, missing labels, or missing scores raise
    NOT MEASURED. Equal or worse mean score is not helping. Catalogue
    `proven: opportunistic` is never returned as the answer.
    """
    if not pairs:
        _t326_not_measured("empty set")
    scorer = _t326_score_fn(score_fn, reference, embed)
    rows = []
    for item in pairs:
        if not isinstance(item, dict):
            _t326_not_measured("pair is not a labelled record")
        label = item.get("label")
        if not label:
            _t326_not_measured("unlabelled pair")
        plain = item.get("plain")
        refined = item.get("refined")
        if not plain or not refined:
            _t326_not_measured("pair missing plain or refined path")
        if not os.path.isfile(plain) or not os.path.isfile(refined):
            _t326_not_measured("file missing")
        off = scorer(plain, label)
        on = scorer(refined, label)
        if off is None or on is None:
            _t326_not_measured("score missing")
        off = float(off)
        on = float(on)
        rows.append({
            "label": label,
            "plain": plain,
            "refined": refined,
            "plain_score": off,
            "refined_score": on,
            "delta": on - off,
        })
    plains = [r["plain_score"] for r in rows]
    refineds = [r["refined_score"] for r in rows]
    mean_off = sum(plains) / len(plains)
    mean_on = sum(refineds) / len(refineds)
    delta = mean_on - mean_off
    helps = delta > 0
    return {
        "metric": REFINER_HELP_METRIC,
        "dataset": "labelled_refine_set",
        "n": len(rows),
        "plain_mean": mean_off,
        "refined_mean": mean_on,
        "delta": delta,
        "helps": helps,
        "proven": "helps" if helps else "does_not_help",
        "pairs": rows,
    }


def refiner_help_finding(report, path=None):
    """Finding whose detail says not helping when the set did not improve."""
    if not report or report.get("delta") is None or "helps" not in report:
        _t326_not_measured("no report")
    if report.get("proven") == "opportunistic":
        _t326_not_measured("opportunistic is not a measurement")
    helps = bool(report["helps"])
    path = path or report.get("dataset") or "labelled_refine_set"
    if helps:
        detail = "refine pass improved the tier-2 score on the labelled set"
        verdict = PASS
        remedy = None
    else:
        detail = ("refine pass not helping: tier-2 score on the labelled "
                  "set did not improve")
        verdict = FLAG
        remedy = "do not treat the refiner as proven; it did not help"
    row = finding(path, "clip", REFINER_HELP_CHECK, verdict, detail,
                  measured=report["delta"], expected=0.0, unit="score",
                  remedy=remedy)
    row["tier"] = 2
    return row


# ------------------------------------------------------------------- run --

def expect_interpolated(source_frames, source_fps, multiplier=2, **extra):
    """T3-8: expect for a RIFE-interpolated clip.

    RIFE returns (n-1)*m+1 frames, not n*m. Playback rate is
    make_postproc.out_fps so duration stays the source length; fps*m is
    the silent-drift trap (77→153 at 32 fps is 4.781 s vs 4.8125 s).
    Latent-rule exemption alone is not this criterion — callers get
    frames, fps and duration from one place.
    """
    n = int(source_frames)
    m = int(multiplier)
    if n < 2:
        raise ValueError(f"source_frames must be >= 2 for RIFE, got {n}")
    if m < 1:
        raise ValueError(f"multiplier must be >= 1, got {m}")
    src_fps = float(source_fps)
    if src_fps <= 0:
        raise ValueError(f"source_fps must be > 0, got {src_fps}")
    frames = (n - 1) * m + 1
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    import make_postproc  # noqa: E402  -- single owner of out_fps arithmetic
    out_fps = make_postproc.out_fps(src_fps, n, m)
    exp = {
        "frames": frames,
        "fps": out_fps,
        "duration": n / src_fps,
        "interpolated": True,
    }
    exp.update(extra)
    return exp


def clip_qc_expect(clip_expect, song_fps=None):
    """T2-13f: a clip is judged at its native fps, not the song's.

    Mixed s2v@16 / LTX@16.8312 each pass only against the rate their
    workflow asked for. song_fps is the assembly target (T2-13d) and
    is a different artefact's question; copying it here flags every
    correct clip of the other model. Absent native fps stays absent —
    inventing the song rate is the same defect.
    """
    out = dict(clip_expect or {})
    native = out.get("fps")
    if native is None:
        return out
    out["fps"] = float(native)
    if song_fps is not None:
        float(song_fps)
    return out


def run(path, kind, expect=None, items=None, song_fps=None):
    """Every tier-1 check for one artefact. kind: image|audio|clip|song|set.

    song_fps is the assembled song's output rate (T2-13d). Clips ignore
    it (T2-13f).
    """
    expect = dict(expect or {})
    if kind == "image":
        out = check_image(path, expect)
    elif kind == "audio":
        out = check_audio(path, expect)
    elif kind == "set":
        out = check_set(path, items or [])
    elif kind == "song":
        expect.setdefault("want_audio", True)
        out = check_video(path, expect, kind="song")
        out.extend(check_nclips(path, expect, kind="song"))
    else:
        expect = clip_qc_expect(expect, song_fps=song_fps)
        out = check_video(path, expect, kind="clip")
    out.extend(check_identity_wrong(path, expect, kind=kind))
    return out


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
        # testsrc2 is a colour bar, not a studio sheet — channel_balance may FLAG.
        failed = set(summarise(i)["failed"])
        assert failed <= {LIGHTING_LOCK}, summarise(i)
        flat = _mk(["-f", "lavfi", "-i", "color=c=black:size=256x192", "-frames:v", "1"],
                   p("flat.png"))
        fl = run(flat, "image", {})
        assert {"not_uniform", "not_blank"} <= set(summarise(fl)["failed"]), fl
        assert run(img, "image", {"width": 999, "height": 192})[0]["verdict"] == REJECT

        # T4-13: olive wall FLAGs; grey wall with a dark figure PASSes.
        from PIL import Image as _Im
        import numpy as np
        olive = np.full((64, 64, 3), (140, 160, 120), dtype="uint8")
        _Im.fromarray(olive).save(p("olive.png"))
        ol = [x for x in run(p("olive.png"), "image", {}) if x["check"] == LIGHTING_LOCK]
        assert ol and ol[0]["verdict"] == FLAG, ol
        grey = np.full((64, 64, 3), 128, dtype="uint8")
        grey[16:48, 16:48] = 20
        _Im.fromarray(grey).save(p("neutral.png"))
        neu = [x for x in run(p("neutral.png"), "image", {}) if x["check"] == LIGHTING_LOCK]
        assert neu and neu[0]["verdict"] == PASS, neu
        try:
            backdrop_channel_means(None)
        except ValueError as e:
            assert "NOT MEASURED" in str(e), e
        else:
            raise AssertionError("T4-13 missing path did not fail closed")

        # --- and the refusal that keeps this file honest: a measurement that
        # produced no reading raises instead of returning 0.0
        try:
            _readings(tone, "signalstats", "lavfi.signalstats.YAVG")
        except RuntimeError as e:
            assert "no lavfi.signalstats.YAVG readings" in str(e), e
        else:
            raise AssertionError("a video filter on an audio file reported a reading")

        # T5-2 harness: MAD can fail (identical = 0) and missing frames raise.
        import numpy as np
        a = np.zeros((2, 8, 8, 3), dtype="float64")
        a[:, 4:, :] = 255
        b = a.copy()
        b[:, :, ::2] += 40
        d = t5_2_refine_differential(a, b)
        assert d["mad"] > 0, d
        assert mean_absolute_difference(a, a) == 0.0
        try:
            t5_2_refine_differential(None, None)
        except ValueError as e:
            assert "NOT MEASURED" in str(e), e
        else:
            raise AssertionError("T5-2 missing frames did not fail closed")

    print("qc.py OK")


if __name__ == "__main__":
    demo()
