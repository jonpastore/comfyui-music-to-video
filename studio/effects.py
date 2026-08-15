"""Per-item DJ audio effects as ffmpeg filter fragments for Meow P Studio sets.

Pure functions: plain numbers/strings in, an ffmpeg filter-graph fragment
string out. No database access, no subprocess call inside any effect
function -- only demo() shells out, to prove the fragments are graphs ffmpeg
actually accepts rather than ones that merely look right.

Every fragment is filter syntax with no I/O labels ("highpass=f=200", not
"[0:a]highpass=f=200[out]") so the caller composes them into whatever
filtergraph position they belong at, chaining most of them with commas.
duck() is the one exception -- sidechaincompress takes two inputs, so it
can't be comma-chained with the rest; parse_effects() returns it separately.

Loudness matching (loudnorm) is ON by default for every item. Two Suno
tracks at different loudness ruin an otherwise good mix, and it's the
unglamorous thing that matters most -- everything else here is off unless a
set item asks for it.
"""
import json
import re
import subprocess

# --- filter_sweep -----------------------------------------------------
# Measured on this box's ffmpeg (6.1.1): highpass/lowpass's "f" option does
# NOT accept a time expression -- `f='200+1800*t'` fails with "Undefined
# constant ... in 't'". Only asendcmd's runtime command interface actually
# moves f over the duration here, so a sweep is a fast staircase of
# `asendcmd` commands driving a same-named filter, not a continuous curve.
FREQ_MIN_HZ = 20.0
FREQ_MAX_HZ = 20000.0
SWEEP_DUR_MIN_S = 0.05
SWEEP_DUR_MAX_S = 60.0
SWEEP_STEP_S = 0.1     # command granularity -- audible as a sweep, not steppy
SWEEP_MAX_STEPS = 200  # caps the command string length on a long sweep

# --- eq_kill ------------------------------------------------------------
EQ_GAIN_MIN_DB = -24.0
EQ_GAIN_MAX_DB = 24.0
EQ_LOW_HZ = 100.0
EQ_MID_HZ = 1000.0
EQ_HIGH_HZ = 8000.0

# --- echo_out -------------------------------------------------------------
ECHO_DECAY_MIN = 0.05
ECHO_DECAY_MAX = 0.95
ECHO_DELAY_MIN_MS = 50.0
ECHO_DELAY_MAX_MS = 2000.0

# --- gain -----------------------------------------------------------------
GAIN_MIN_DB = -60.0
GAIN_MAX_DB = 24.0

# --- duck -------------------------------------------------------------
DUCK_MIN = 0.0
DUCK_MAX = 1.0
DUCK_THRESH_MIN = 0.05   # sidechaincompress's own linear-amplitude range
DUCK_THRESH_MAX = 0.9
DUCK_RATIO_MIN = 2.0
DUCK_RATIO_MAX = 20.0
DUCK_ATTACK_MS = 5.0
DUCK_RELEASE_MS = 300.0

# --- loudnorm ---------------------------------------------------------
LOUDNORM_I = -16.0   # EBU R128 target LUFS for streaming, not broadcast's -23
LOUDNORM_TP = -1.5
LOUDNORM_LRA = 11.0


def _range(name, value, lo, hi):
    """Validate rather than emit a graph ffmpeg will refuse -- every numeric
    input funnels through here so an out-of-range value fails loud, in
    Python, before it ever reaches a filter string."""
    value = float(value)
    if not (lo <= value <= hi):
        raise ValueError(f"{name}={value} out of range [{lo}, {hi}]")
    return value


def filter_sweep(kind, f_start, f_end, dur):
    """highpass/lowpass sweep from f_start to f_end over dur seconds -- the
    classic build into a drop. See module comment for why this is an
    asendcmd staircase rather than a continuous expression."""
    if kind not in ("highpass", "lowpass"):
        raise ValueError(f"kind must be 'highpass' or 'lowpass', got {kind!r}")
    f_start = _range("f_start", f_start, FREQ_MIN_HZ, FREQ_MAX_HZ)
    f_end = _range("f_end", f_end, FREQ_MIN_HZ, FREQ_MAX_HZ)
    dur = _range("dur", dur, SWEEP_DUR_MIN_S, SWEEP_DUR_MAX_S)
    n = max(2, min(SWEEP_MAX_STEPS, round(dur / SWEEP_STEP_S) + 1))
    cmds = "; ".join(
        f"{i * dur / (n - 1):.3f} {kind} f {f_start + (f_end - f_start) * i / (n - 1):.1f}"
        for i in range(n))
    return f"asendcmd=commands='{cmds}',{kind}=f={f_start:.1f}"


def eq_kill(low_db, mid_db, high_db):
    """Three-band kill via three `equalizer` stages -- the bass swap through
    a transition that stops two kicks fighting, this is the important one.
    Three plain `equalizer` stages over one `firequalizer`: firequalizer's
    gain_entry needs the same comma-in-an-expression escaping that just
    failed for filter_sweep above; equalizer takes one number per band."""
    low_db = _range("low_db", low_db, EQ_GAIN_MIN_DB, EQ_GAIN_MAX_DB)
    mid_db = _range("mid_db", mid_db, EQ_GAIN_MIN_DB, EQ_GAIN_MAX_DB)
    high_db = _range("high_db", high_db, EQ_GAIN_MIN_DB, EQ_GAIN_MAX_DB)
    bands = ((EQ_LOW_HZ, low_db), (EQ_MID_HZ, mid_db), (EQ_HIGH_HZ, high_db))
    return ",".join(f"equalizer=f={hz:.0f}:width_type=o:width=2:g={db:.2f}" for hz, db in bands)


def echo_out(decay, delay):
    """aecho tail so an outgoing track fades into itself instead of
    stopping dead. delay is in milliseconds."""
    decay = _range("decay", decay, ECHO_DECAY_MIN, ECHO_DECAY_MAX)
    delay = _range("delay", delay, ECHO_DELAY_MIN_MS, ECHO_DELAY_MAX_MS)
    return f"aecho=in_gain=1.0:out_gain=1.0:delays={delay:.0f}:decays={decay:.2f}"


def gain(db):
    """Flat level shift. Same `volume=<db>dB` shape mixer.py already uses
    for per-item gain_db, so a value round-trips identically either way."""
    db = _range("gain_db", db, GAIN_MIN_DB, GAIN_MAX_DB)
    return f"volume={db:.3f}dB"


PAN_MIN, PAN_MAX = -1.0, 1.0


def pan(position):
    """Stereo BALANCE, -1 hard left .. +1 hard right. docs/TRD-1 3.1.

    Decided 2026-08-12 by Jon: "L/R split" is three different features -- dual
    mono, stereo pan, mid/side -- and outside review was right that one has to
    be picked before any timeline UI is drawn. This is the one. Dual mono and
    mid/side are not built; the upgrade path is a channel_mode added later with
    this as its default, so nothing stored now has to move.

    BALANCE, not a pan law, and the difference matters at the centre. An
    equal-power pan (cos/sin) puts 0.707 on both channels at centre, which is
    -3 dB on every item that never asked to be panned at all. Attenuating only
    the opposite channel leaves centre at unity: a set with no panning renders
    bit-identically to one built before the feature existed.

    Sources here are stereo tracks, so this is the right operation anyway --
    "pan" on a stereo source means balance between its channels, not placing a
    mono point source in a field.
    """
    p = _range("position", position, PAN_MIN, PAN_MAX)
    left = min(1.0, 1.0 - p)
    right = min(1.0, 1.0 + p)
    return f"pan=stereo|c0={left:.4f}*c0|c1={right:.4f}*c1"


def duck(amount):
    """sidechaincompress params for ducking one track under another (a bed
    under a vocal). amount 0..1 maps to threshold/ratio -- 0 barely
    compresses, 1 slams it. Needs a second (sidechain) input, so unlike
    every other fragment here it can't be comma-chained into a single-input
    filter list; parse_effects() below keeps it separate for that reason."""
    amount = _range("duck_amount", amount, DUCK_MIN, DUCK_MAX)
    threshold = DUCK_THRESH_MAX - amount * (DUCK_THRESH_MAX - DUCK_THRESH_MIN)
    ratio = DUCK_RATIO_MIN + amount * (DUCK_RATIO_MAX - DUCK_RATIO_MIN)
    return (f"sidechaincompress=threshold={threshold:.3f}:ratio={ratio:.2f}:"
            f"attack={DUCK_ATTACK_MS:.0f}:release={DUCK_RELEASE_MS:.0f}")


def phaser():
    """Fixed-parameter aphaser. Off by default -- see DEFAULT_EFFECTS."""
    return "aphaser=in_gain=0.4:out_gain=0.74:delay=3:decay=0.4:speed=0.5"


def flanger():
    """Fixed-parameter flanger. Off by default -- see DEFAULT_EFFECTS."""
    return "flanger=delay=5:depth=2:regen=0"


def measure_loudness(path):
    """Measured integrated loudness and true peak of a rendered file.

    {"lufs": float, "true_peak_db": float}. EBU R128 via ffmpeg's own ebur128,
    read off the Summary block it prints at end of stream.

    THIS IS THE ONE IMPLEMENTATION. docs/TRD-1 T1-25 and docs/TRD-3 4.3 both
    measure loudness and both call this: the export path names it on the asset
    row, QC's audio tier compares it against the target. Two implementations
    would eventually disagree, and a disagreement between two loudness numbers
    is invisible until someone plays the file.

    It lives here, next to LOUDNORM_I and loudnorm_filter(), because those
    already own what the target IS -- measuring against a target from another
    module is how the two drift apart.

    Raises RuntimeError if ebur128 printed no summary. That is deliberate and it
    is this project's most-repeated lesson: a filter that emits nothing returns
    0.0 to a caller that cannot tell the difference between silence and no
    reading, and the comparison then passes on no data.
    """
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "info", "-i", path, "-af", "ebur128=peak=true",
         "-f", "null", "-"],
        capture_output=True, text=True)
    # Summary block, last occurrence:  I:  -14.2 LUFS  /  Peak:  -1.0 dBFS
    lufs = peak = None
    for line in r.stderr.splitlines():
        s = line.strip()
        m = re.match(r"^I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", s)
        if m:
            lufs = float(m.group(1))
        m = re.match(r"^Peak:\s+(-?\d+(?:\.\d+)?)\s+dBFS", s)
        if m:
            peak = float(m.group(1))
    if lufs is None:
        raise RuntimeError(
            "ebur128 printed no integrated loudness for %s -- refusing to report 0.0 "
            "for a measurement that did not happen:\n%s"
            % (path, "\n".join(r.stderr.splitlines()[-15:])))
    return {"lufs": lufs, "true_peak_db": peak}


def loudnorm_filter(I=None, TP=None, LRA=None):
    """Level matching, on by default for every set item (see module
    docstring). -16 LUFS / -1.5dB true peak is the streaming-platform
    target, not broadcast's -23 -- these are Suno tracks headed for the
    same casual listening as everything else on a feed.

    Optional I/TP/LRA override the module defaults so the one-button
    master can record the numbers that actually ran (docs/TRD-1 T1-19)
    without a second loudnorm implementation.
    """
    i = LOUDNORM_I if I is None else float(I)
    tp = LOUDNORM_TP if TP is None else float(TP)
    lra = LOUDNORM_LRA if LRA is None else float(LRA)
    return f"loudnorm=I={i:.1f}:TP={tp:.1f}:LRA={lra:.1f}"


# What a set_item gets when effects_json is empty. loudnorm on, everything
# creative off -- Phase 4 of the plan calls level matching "the unglamorous
# one that matters most" and every other effect "per-item and off by default".
# Empty: layer and duck are both wired into the join now (mixer._layer_join and
# mixer._duck_join). Kept as the place a future validated-but-unwired effect
# goes, because the callers that consult it -- the set editor and the mix
# suggester -- already refuse rather than accept-and-ignore what is on it.
UNSUPPORTED_KEYS = ()

# Effects consumed at the TRANSITION between two items, not on one item's own
# chain. Both were originally filed as per-item effects, which is exactly why
# they sat unwired for so long: on one clip each looks like a filter that merely
# "needs a second input", and there is no second input until the join.
JOIN_KEYS = ("duck", "layer")

# Transitions with no overlap window for a join effect to act in. A fade to
# black is sequential -- A fades out, black holds, B fades in -- so like a
# cut it gives duck and layer nothing to work on.
NO_OVERLAP = ("cut", "black")


def join_effects_without_overlap(effects_json, transition, secs):
    """The JOIN_KEYS in this item's effects that its transition gives no window
    to work in -- empty when there is nothing wrong.

    Both blend or compress ACROSS the transition overlap, so a cut, or any
    transition of zero length, has nothing for them to act on. Asked by every
    caller that can know the answer: the set editor before it stores, mixadvice
    before it suggests, and mixer before it renders. One predicate rather than
    three, because three would drift and the drift would show up as an editor
    accepting a setting the renderer refuses -- this codebase's recurring
    defect, and the one day 4 recorded six instances of.
    """
    if not effects_json:
        return []
    try:
        raw = json.loads(effects_json) if isinstance(effects_json, str) else effects_json
    except (ValueError, TypeError):
        return []
    if not isinstance(raw, dict):
        return []
    present = [k for k in JOIN_KEYS if k in raw]
    if not present:
        return []
    try:
        secs = float(secs or 0)
    except (TypeError, ValueError):
        secs = 0.0
    return present if (transition or "cut") in NO_OVERLAP or secs <= 0 else []

# The keys THIS module owns. parse_effects deliberately ignores anything it
# does not recognise, so callers that want "unknown key is a mistake" -- the
# set editor and the mix suggester both do -- check against this plus
# video_fx.VIDEO_KEYS rather than relying on the parser to complain.
# "duck" is here even though it is not part of the single-input chain, for the
# same reason video_fx.VIDEO_KEYS carries "layer": both are keys this module
# owns and validates, and the callers that use this tuple are asking "is this a
# real key or a typo?". Leaving it out made a wired effect look invented.
AUDIO_KEYS = ("sweep", "eq_kill", "echo_out", "phaser", "flanger", "gain_db", "loudnorm",
              "duck", "pan")

DEFAULT_EFFECTS = {
    "loudnorm": True,
    # Centre. At 0 the filter is not emitted at all (see parse_effects), so an
    # item that never asked to be panned renders exactly as it did before this
    # existed -- no extra stage, no rounding, nothing to explain in a diff.
    "pan": 0.0,
    "gain_db": 0.0,
    "sweep": None,
    "eq_kill": None,
    "echo_out": None,
    "duck": None,
    "phaser": False,
    "flanger": False,
}


def duration_delta(effects_json):
    """Seconds this effect chain ADDS to an item's length.

    aecho appends its delay to the stream: a 2000ms echo makes a 30s item run
    32s. mixer._item_duration is pure trim arithmetic and cannot know that, so
    without this the editor's predicted length is short by exactly the delay --
    and the same wrong duration feeds the crossfade offsets and the transition
    fit guard. Measured against real ffmpeg: drift equals the delay, exactly.

    Only echo_out extends anything today. Every other filter here is
    length-preserving; loudnorm, the equalizers, the sweeps and the modulation
    effects all return a stream as long as they were given.
    """
    if not effects_json:
        return 0.0
    data = effects_json if isinstance(effects_json, dict) else json.loads(effects_json)
    echo = data.get("echo_out")
    if not isinstance(echo, dict):
        return 0.0
    try:
        return _range("delay", echo["delay"], ECHO_DELAY_MIN_MS, ECHO_DELAY_MAX_MS) / 1000.0
    except (KeyError, ValueError):
        return 0.0


def parse_effects(effects_json):
    """The one entry point that turns a set_item's effects_json into
    validated fragments. Accepts JSON text, an already-parsed dict, or
    None/"" (-> DEFAULT_EFFECTS). Raises ValueError on anything malformed or
    out of range -- never emits a filter graph ffmpeg would refuse.

    Returns {"chain": [fragment, ...], "duck": fragment_or_None}. "chain" is
    comma-joinable in the order shaping effects, then gain, then loudnorm
    last so it normalizes whatever the shaping/gain stages produced. "duck"
    is separate because sidechaincompress needs a second input the caller
    must wire up itself.
    """
    if effects_json in (None, ""):
        cfg = dict(DEFAULT_EFFECTS)
    else:
        if isinstance(effects_json, str):
            try:
                data = json.loads(effects_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"invalid effects_json: {e}") from e
        else:
            data = effects_json
        if not isinstance(data, dict):
            raise ValueError(f"effects_json must decode to an object, got {type(data).__name__}")
        cfg = dict(DEFAULT_EFFECTS)
        cfg.update(data)

    try:
        chain = []
        sweep = cfg.get("sweep")
        if sweep:
            chain.append(filter_sweep(sweep["kind"], sweep["f_start"], sweep["f_end"], sweep["dur"]))
        eqk = cfg.get("eq_kill")
        if eqk:
            chain.append(eq_kill(eqk.get("low_db", 0), eqk.get("mid_db", 0), eqk.get("high_db", 0)))
        echo = cfg.get("echo_out")
        if echo:
            chain.append(echo_out(echo["decay"], echo["delay"]))
        if cfg.get("phaser"):
            chain.append(phaser())
        if cfg.get("flanger"):
            chain.append(flanger())
        if cfg.get("gain_db"):
            chain.append(gain(cfg["gain_db"]))
        # Pan before loudnorm: loudnorm measures the whole stereo programme and
        # does not rebalance channels, so it cannot undo a pan -- unlike a gain
        # curve, which it flattens (docs/TRD-1 5.0c).
        if cfg.get("pan"):
            chain.append(pan(cfg["pan"]))
        if cfg.get("loudnorm", True):
            chain.append(loudnorm_filter())
        duck_amount = cfg.get("duck")
        duck_fragment = duck(duck_amount) if duck_amount is not None else None
    except KeyError as e:
        raise ValueError(f"effects_json missing required key {e}") from e

    return {"chain": chain, "duck": duck_fragment}


def demo():
    import subprocess

    # filter_sweep: exact string, both directions, out-of-range rejected
    frag = filter_sweep("highpass", 200, 200, 1.0)
    assert frag.startswith("asendcmd=commands='0.000 highpass f 200.0;") and frag.endswith(
        "1.000 highpass f 200.0',highpass=f=200.0"), frag
    assert frag.count(" highpass f ") == 11, frag  # dur/step + 1 commands
    frag2 = filter_sweep("lowpass", 8000, 200, 0.2)
    assert frag2.startswith("asendcmd=commands='0.000 lowpass f 8000.0;") and frag2.endswith("lowpass=f=8000.0")
    assert "0.200 lowpass f 200.0" in frag2
    try:
        filter_sweep("bandpass", 200, 2000, 1.0)
        assert False, "bad kind must raise"
    except ValueError:
        pass
    try:
        filter_sweep("highpass", 10, 2000, 1.0)  # below FREQ_MIN_HZ
        assert False, "out-of-range f_start must raise"
    except ValueError:
        pass

    # eq_kill: exact string, out-of-range rejected
    assert eq_kill(-12, 0, 3) == (
        "equalizer=f=100:width_type=o:width=2:g=-12.00,"
        "equalizer=f=1000:width_type=o:width=2:g=0.00,"
        "equalizer=f=8000:width_type=o:width=2:g=3.00")
    try:
        eq_kill(-99, 0, 0)
        assert False, "out-of-range low_db must raise"
    except ValueError:
        pass

    # echo_out
    assert echo_out(0.5, 400) == "aecho=in_gain=1.0:out_gain=1.0:delays=400:decays=0.50"
    try:
        echo_out(0.5, 99999)
        assert False, "out-of-range delay must raise"
    except ValueError:
        pass

    # gain
    assert gain(-6) == "volume=-6.000dB"
    try:
        gain(-999)
        assert False, "out-of-range gain must raise"
    except ValueError:
        pass

    # pan: string shape, then the MEASURED differential. A fragment ffmpeg
    # accepts is not proof it moved the audio -- that is the whole reason this
    # demo shells out at all -- so the levels are read back per channel.
    assert pan(0.0) == "pan=stereo|c0=1.0000*c0|c1=1.0000*c1", pan(0.0)
    assert pan(1.0) == "pan=stereo|c0=0.0000*c0|c1=1.0000*c1", pan(1.0)
    assert pan(-1.0) == "pan=stereo|c0=1.0000*c0|c1=0.0000*c1", pan(-1.0)
    try:
        pan(1.5)
        assert False, "out-of-range pan must raise"
    except ValueError:
        pass

    import os
    import re as _re
    import tempfile
    with tempfile.TemporaryDirectory() as _d:
        src = os.path.join(_d, "src.wav")
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=1",
                        "-af", "pan=stereo|c0=c0|c1=c0", src],
                       check=True, capture_output=True)

        def level(path, chan):
            """max_volume of ONE channel, in dB."""
            r = subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "info", "-i", path,
                 "-af", f"pan=mono|c0=c{chan},volumedetect", "-f", "null", "-"],
                capture_output=True, text=True)
            m = _re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", r.stderr)
            assert m, f"volumedetect printed no level for channel {chan}:\n{r.stderr[-400:]}"
            return float(m.group(1))

        def applied(frag, name):
            out = os.path.join(_d, name)
            subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", src,
                            "-af", frag, out], check=True, capture_output=True)
            return level(out, 0), level(out, 1)

        l0, r0 = level(src, 0), level(src, 1)
        assert abs(l0 - r0) < 0.5, f"the source is not centred: {l0} vs {r0}"

        # hard right: the left channel must be gone, not merely quieter
        lR, rR = applied(pan(1.0), "right.wav")
        assert rR - lR > 40.0, f"pan(+1) left {lR} dB, right {rR} dB -- not panned"
        assert abs(rR - r0) < 0.5, f"pan(+1) changed the right channel: {r0} -> {rR}"

        # and the mirror, so the check cannot pass by silencing a fixed channel
        lL, rL = applied(pan(-1.0), "left.wav")
        assert lL - rL > 40.0, f"pan(-1) left {lL} dB, right {rL} dB -- not panned"

        # centre is UNITY: an item nobody panned must be untouched, which is the
        # reason this is a balance and not an equal-power law (that would be
        # -3 dB on every unpanned item in the set)
        lC, rC = applied(pan(0.0), "centre.wav")
        assert abs(lC - l0) < 0.1 and abs(rC - r0) < 0.1, \
            f"pan(0) is not unity: {l0},{r0} -> {lC},{rC}"

        # and pan=0 emits NO filter at all, so the ordinary path is unchanged
        assert not [f for f in parse_effects({"pan": 0.0})["chain"] if f.startswith("pan=")]
        assert [f for f in parse_effects({"pan": 0.6})["chain"] if f.startswith("pan=")]

    # duck: string shape and range check
    d0 = duck(0.0)
    d1 = duck(1.0)
    assert d0 == f"sidechaincompress=threshold={DUCK_THRESH_MAX:.3f}:ratio={DUCK_RATIO_MIN:.2f}:attack=5:release=300"
    assert d1 == f"sidechaincompress=threshold={DUCK_THRESH_MIN:.3f}:ratio={DUCK_RATIO_MAX:.2f}:attack=5:release=300"
    try:
        duck(1.5)
        assert False, "out-of-range duck amount must raise"
    except ValueError:
        pass

    # phaser/flanger: fixed strings, off by default
    assert phaser().startswith("aphaser=")
    assert flanger().startswith("flanger=")
    assert DEFAULT_EFFECTS["phaser"] is False and DEFAULT_EFFECTS["flanger"] is False
    assert DEFAULT_EFFECTS["loudnorm"] is True

    # loudnorm_filter
    assert loudnorm_filter() == "loudnorm=I=-16.0:TP=-1.5:LRA=11.0"

    # parse_effects: empty -> loudnorm only, no duck
    empty = parse_effects(None)
    assert empty == {"chain": [loudnorm_filter()], "duck": None}
    assert parse_effects("") == empty
    assert parse_effects("{}") == empty

    # parse_effects: full config, order is shaping -> gain -> loudnorm, duck separate
    full_cfg = {
        "sweep": {"kind": "highpass", "f_start": 200, "f_end": 4000, "dur": 1.0},
        "eq_kill": {"low_db": -12, "mid_db": 0, "high_db": 2},
        "echo_out": {"decay": 0.4, "delay": 300},
        "phaser": True,
        "flanger": False,
        "gain_db": -3.0,
        "duck": 0.5,
    }
    parsed = parse_effects(json.dumps(full_cfg))
    assert parsed["chain"] == [
        filter_sweep("highpass", 200, 4000, 1.0),
        eq_kill(-12, 0, 2),
        echo_out(0.4, 300),
        phaser(),
        gain(-3.0),
        loudnorm_filter(),
    ], parsed["chain"]
    assert parsed["duck"] == duck(0.5)

    # parse_effects: same dict passed directly (not JSON text) matches
    assert parse_effects(full_cfg) == parsed

    # parse_effects: loudnorm explicitly off is honoured
    off = parse_effects({"loudnorm": False})
    assert off == {"chain": [], "duck": None}

    # parse_effects: malformed input rejected, not silently coerced
    for bad in ("{not json", "[1, 2, 3]", {"sweep": {"kind": "highpass"}}):  # sweep missing f_start/f_end/dur
        try:
            parse_effects(bad)
            assert False, f"{bad!r} must raise"
        except ValueError:
            pass

    # Real ffmpeg run: the full chain (minus duck, which needs a 2nd input)
    # actually gets accepted as a filtergraph on synthesised audio -- this
    # is the check that caught filter_sweep's original t-expression design
    # failing on this box's ffmpeg, so it stays.
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "1", "-i", "sine=frequency=440",
         "-filter_complex", f"[0:a]{','.join(parsed['chain'])}[out]",
         "-map", "[out]", "-f", "null", "-"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    # Real ffmpeg run: duck's sidechaincompress fragment with its second input wired up
    r2 = subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-t", "1", "-i", "sine=frequency=440",
         "-f", "lavfi", "-t", "1", "-i", "sine=frequency=220",
         "-filter_complex", f"[0:a][1:a]{parsed['duck']}[out]",
         "-map", "[out]", "-f", "null", "-"],
        capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr

    # duration_delta: only echo_out extends anything, and by exactly its delay
    assert duration_delta(None) == 0.0 and duration_delta("") == 0.0
    assert duration_delta(json.dumps({"eq_kill": {"low_db": -6}})) == 0.0
    assert duration_delta(json.dumps({"echo_out": {"decay": 0.5, "delay": 2000}})) == 2.0
    assert duration_delta(json.dumps({"echo_out": {"decay": 0.5, "delay": 300}})) == 0.3
    assert duration_delta({"echo_out": {"decay": 0.5, "delay": 1000}}) == 1.0
    assert duration_delta(json.dumps({"echo_out": "nonsense"})) == 0.0
    assert duration_delta(json.dumps({"echo_out": {"decay": 0.5}})) == 0.0

    print("effects.py demo OK")


if __name__ == "__main__":
    demo()
