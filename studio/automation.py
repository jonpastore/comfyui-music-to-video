#!/usr/bin/env python3
"""Automation curves for set items: store, decimate, and turn into filter text.

docs/TRD-1 4.1 and 5. The timeline model lives on the SERVER and the browser is
a view of it, so this module owns the curve and app.py owns nothing about it.

THREE THINGS THIS MODULE EXISTS TO NOT DO, all found by reading effects.py
before writing it:

1. It does not invent a second sweep. `effects.filter_sweep` already builds a
   time-varying filter as an `asendcmd` staircase, and this uses the SAME
   mechanism -- automation is the model, asendcmd is the one emitter, and a
   sweep is a preset that writes points. One cap, not two.

2. It does not become a second place for gain. The `gain_db` LANE is a curve
   RELATIVE to `set_items.gain_db`, which stays the static offset. Gain already
   had two inputs before this (the column and effects_json's key, resolved in
   mixer._audio_chain); a lane that ignored the column would have made three.

3. It does not let loudnorm undo it. THE SERIOUS ONE: effects.parse_effects
   appends loudnorm_filter() LAST, every item defaults to loudnorm on, and
   single-pass loudnorm is a DYNAMIC normaliser -- so a drawn level curve would
   be flattened by a filter two stages later. `wants_master_loudnorm()` is how
   the renderer knows to take per-item loudnorm off for an item that has a gain
   curve. See docs/TRD-1 5.0(c).

WIRED INTO THE RENDERER 2026-08-13. `item_audio()` returns the fragments and the
loudnorm decision as plain data; app.py puts that on the item dict and
mixer._audio_chain applies it, so a curve drawn on a set item now reaches the
rendered audio. mixer still imports neither this module nor db -- the curve
travels as a value, exactly as effects_json does.

T1-9b (2026-08-14) measures that reach on the file, not the graph:
`mixer.rms_per_second` / `mixer.rms_slope` of a `mix_audio` render of a
stored `gain_db` ramp. T1-9a is the graph half.

T1-10 (2026-08-14): a MAX_POINTS lane's fragment is under
`FILTER_EXPR_MAX_BYTES` (8 KB) and mix_audio accepts it.

T1-12 (2026-08-14) is the remaining lanes as a differential: `pan` by
L/R energy (aeval, same balance law as effects.pan — ffmpeg's pan
filter takes no runtime command), `lowpass_hz`/`highpass_hz` by band
energy. `item_audio` emits all four lanes.

    python3 automation.py        # self-check
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db       # noqa: E402
import effects  # noqa: E402

# T8-13: the song editor is a one-item set. Same automation rows as the
# timeline; hidden from the sets shelf so it is not a second document.
SONG_EDITOR_MODE = "song_editor"

# Linear between points, `hold` steps. NO other curve type, and the reason is
# not taste: every shape that is drawable but not expressible in the filter
# text is another way for the editor to promise what the renderer will not
# produce. If a curve type cannot be emitted, it cannot be drawn.
CURVES = ("linear", "hold")

# Per-lane: the filter the staircase drives, the command parameter, the range,
# and the decimation epsilon -- how far a decimated curve may sit from the drawn
# one before the difference is audible.
LANES = {
    "gain_db":     {"filter": "volume", "param": "volume", "unit": "dB",
                    "lo": effects.GAIN_MIN_DB, "hi": effects.GAIN_MAX_DB,
                    "eps": 0.25, "fmt": "{:.3f}dB"},
    "pan":         {"filter": "pan", "param": None, "unit": "",
                    "lo": effects.PAN_MIN, "hi": effects.PAN_MAX,
                    "eps": 0.02, "fmt": None},
    "lowpass_hz":  {"filter": "lowpass", "param": "f", "unit": "Hz",
                    "lo": effects.FREQ_MIN_HZ, "hi": effects.FREQ_MAX_HZ,
                    "eps": None, "fmt": "{:.1f}"},     # eps is 2% of the value
    "highpass_hz": {"filter": "highpass", "param": "f", "unit": "Hz",
                    "lo": effects.FREQ_MIN_HZ, "hi": effects.FREQ_MAX_HZ,
                    "eps": None, "fmt": "{:.1f}"},
}

# The hard cap after decimation. A 60 Hz drag over 30 seconds is ~1800 points;
# every one of them becomes a command in the filter string, and effects.py's own
# sweep caps at 200 for exactly this reason. 64 is well inside what ffmpeg will
# take and well past what a hand can draw meaningfully.
MAX_POINTS = 64

# T1-10: the emitted asendcmd string for one fully-populated lane. MAX_POINTS
# bounds the MODEL; this bounds the STRING. A cap that produces a graph
# ffmpeg refuses is not a cap.
FILTER_EXPR_MAX_BYTES = 8 * 1024

# Points closer together than this are the same instant as far as any renderer
# is concerned, and two values at one instant have no defined render.
MIN_DT = 1e-6


def _lane(lane):
    if lane not in LANES:
        raise ValueError(f"unknown automation lane {lane!r}; known: {', '.join(sorted(LANES))}")
    return LANES[lane]


def _eps(lane, values):
    """Decimation tolerance. Frequency lanes are proportional -- 40 Hz matters
    at 100 Hz and is inaudible at 8 kHz -- so a flat epsilon would either
    over-keep at the bottom or flatten the top."""
    spec = _lane(lane)
    if spec["eps"] is not None:
        return spec["eps"]
    typical = max(abs(v) for v in values) if values else 1000.0
    return max(1.0, 0.02 * typical)


def decimate(points, lane):
    """Ramer-Douglas-Peucker, then a hard cap. Returns [(t, value), ...].

    Runs on WRITE, on the server. The client may post whatever the mouse
    produced; what is stored is this, and the client re-reads what was stored --
    so what is drawn and what is rendered cannot diverge.

    Both halves are needed and each is useless alone. RDP alone has no bound: a
    deliberately jagged drag survives it almost intact. A cap alone would keep
    the first 64 points and throw the shape away, which is why the self-check
    asserts the SHAPE survives and not merely the count.
    """
    pts = sorted(((float(t), float(v)) for t, v in points), key=lambda p: p[0])
    if len(pts) <= 2:
        return pts
    eps = _eps(lane, [v for _, v in pts])
    kept = _rdp(pts, eps)
    if len(kept) > MAX_POINTS:
        kept = _cap(pts, kept, eps)
    return kept


def _rdp(pts, eps):
    if len(pts) < 3:
        return list(pts)
    (t0, v0), (t1, v1) = pts[0], pts[-1]
    span = t1 - t0
    worst_i, worst = 0, -1.0
    for i in range(1, len(pts) - 1):
        t, v = pts[i]
        # vertical distance to the chord: the axes are seconds and dB, which are
        # not comparable, so perpendicular distance would be meaningless here
        at = v0 if span <= 0 else v0 + (v1 - v0) * (t - t0) / span
        d = abs(v - at)
        if d > worst:
            worst_i, worst = i, d
    if worst <= eps:
        return [pts[0], pts[-1]]
    left = _rdp(pts[:worst_i + 1], eps)
    right = _rdp(pts[worst_i:], eps)
    return left[:-1] + right


def _cap(pts, kept, eps):
    """Raise epsilon until the curve fits the cap. Keeps taking the
    highest-error points first, which is what RDP already does -- rather than
    truncating, which would keep the start of the drag and drop the end."""
    lo, hi = eps, eps
    for _ in range(40):
        hi *= 2
        if len(_rdp(pts, hi)) <= MAX_POINTS:
            break
    for _ in range(40):                       # bisect for the loosest curve that fits
        mid = (lo + hi) / 2
        if len(_rdp(pts, mid)) <= MAX_POINTS:
            hi = mid
        else:
            lo = mid
    out = _rdp(pts, hi)
    return out[:MAX_POINTS] if len(out) > MAX_POINTS else out


def value_at(points, t):
    """The curve's value at t: linear between points, flat outside them."""
    if not points:
        return None
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= t <= t1:
            if t1 == t0:
                return v1
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return points[-1][1]


# ------------------------------------------------------------------ store --

def save(set_item_id, lane, points, curve="linear"):
    """Replace one lane's curve. Decimates first; returns what was STORED.

    The return value is the point of the signature: the client asked for
    whatever the mouse gave, and what it gets back is what will actually
    render.
    """
    spec = _lane(lane)
    if curve not in CURVES:
        raise ValueError(f"curve must be one of {', '.join(CURVES)}, got {curve!r}")
    seen = []
    for t, v in sorted(((float(t), float(v)) for t, v in points), key=lambda p: p[0]):
        if not (spec["lo"] <= v <= spec["hi"]):
            raise ValueError(f"{lane}={v} out of range [{spec['lo']}, {spec['hi']}] at t={t}")
        if t < 0:
            raise ValueError(f"automation time must be >= 0, got {t}")
        if seen and abs(t - seen[-1]) < MIN_DT:
            raise ValueError(
                f"two {lane} points at t={t}: one instant cannot have two values")
        seen.append(t)
    kept = decimate(points, lane)
    db.run("DELETE FROM automation WHERE set_item_id=? AND lane=?", int(set_item_id), lane)
    for t, v in kept:
        db.run("""INSERT INTO automation (set_item_id, lane, t, value, curve)
                  VALUES (?,?,?,?,?)""", int(set_item_id), lane, t, v, curve)
    return kept


def read(set_item_id, lane):
    return [(r["t"], r["value"]) for r in db.q(
        "SELECT t, value FROM automation WHERE set_item_id=? AND lane=? ORDER BY t",
        int(set_item_id), lane)]


def read_curve(set_item_id, lane):
    row = db.one(
        "SELECT curve FROM automation WHERE set_item_id=? AND lane=? ORDER BY t",
        int(set_item_id), lane)
    return row["curve"] if row else "linear"


def editor_item(song_id, create=True):
    """The one-item timeline that is this song's editor (T8-13).

    Shares set_items + automation with the set timeline. mode=song_editor
    keeps it off the shelf. GET does not mint a row; POST does.
    """
    song_id = int(song_id)
    if db.one("SELECT id FROM songs WHERE id=?", song_id) is None:
        raise ValueError(f"no song {song_id}")
    row = db.one(
        """SELECT si.id FROM set_items si
           JOIN sets s ON s.id = si.set_id
           WHERE s.mode=? AND si.song_id=?
           ORDER BY si.id""",
        SONG_EDITOR_MODE, song_id)
    if row:
        return row["id"]
    if not create:
        return None
    now = time.time()
    sid = db.run(
        "INSERT INTO sets (name, mode, created, updated) VALUES (?,?,?,?)",
        f"song-editor:{song_id}", SONG_EDITOR_MODE, now, now)
    return db.run(
        """INSERT INTO set_items (set_id, song_id, position, transition, secs)
           VALUES (?,?,?,?,?)""",
        sid, song_id, 0, "cut", 0.0)


def lanes_for(set_item_id):
    return {r["lane"] for r in db.q(
        "SELECT DISTINCT lane FROM automation WHERE set_item_id=?", int(set_item_id))}


def clear(set_item_id, lane=None):
    if lane:
        db.run("DELETE FROM automation WHERE set_item_id=? AND lane=?", int(set_item_id), lane)
    else:
        db.run("DELETE FROM automation WHERE set_item_id=?", int(set_item_id))


# ----------------------------------------------------------------- render --

def fragment(lane, points, curve="linear"):
    """The filter text for one lane, or "" for an empty curve.

    Same asendcmd staircase effects.filter_sweep uses, for the reason in the
    module docstring: one emitter, not two.
    """
    spec = _lane(lane)
    pts = [(float(t), float(v)) for t, v in points]
    if not pts:
        return ""
    if lane == "pan":
        out = _pan_fragment(pts, curve)
        nbytes = len(out.encode("utf-8"))
        if nbytes > FILTER_EXPR_MAX_BYTES:
            raise ValueError(
                f"{lane} filter expression is {nbytes} bytes; "
                f"cap is {FILTER_EXPR_MAX_BYTES}")
        return out

    # THE STORED POINTS ARE NOT THE EMITTED COMMANDS, and conflating them
    # renders the wrong curve. asendcmd HOLDS a value until the next command,
    # so emitting only the drawn points turns "linear from -12 dB to 0 dB over
    # three seconds" into a step that sits at -12 and jumps at the end. Measured:
    # first second and last second came back identical.
    #
    # A linear segment is therefore SAMPLED into the staircase, at
    # effects.SWEEP_STEP_S, exactly as effects.filter_sweep does -- which is the
    # "one emitter" this module exists to keep. Two caps, two jobs: MAX_POINTS
    # bounds the MODEL (what a human drew, what the client re-reads),
    # SWEEP_MAX_STEPS bounds the STRING (what ffmpeg parses).
    if curve == "hold":
        samples = pts
    else:
        t0, t1 = pts[0][0], pts[-1][0]
        span = t1 - t0
        n = 1 if span <= 0 else min(effects.SWEEP_MAX_STEPS,
                                    max(2, int(round(span / effects.SWEEP_STEP_S)) + 1))
        samples = ([(t0, pts[0][1])] if n == 1 else
                   [(t0 + span * i / (n - 1), value_at(pts, t0 + span * i / (n - 1)))
                    for i in range(n)])

    cmds = "; ".join(
        f"{t:.3f} {spec['filter']} {spec['param']} {spec['fmt'].format(v)}"
        for t, v in samples)
    first = spec["fmt"].format(samples[0][1])
    out = f"asendcmd=commands='{cmds}',{spec['filter']}={spec['param']}={first}"
    nbytes = len(out.encode("utf-8"))
    if nbytes > FILTER_EXPR_MAX_BYTES:
        raise ValueError(
            f"{lane} filter expression is {nbytes} bytes; "
            f"cap is {FILTER_EXPR_MAX_BYTES}")
    return out


def _pan_position_expr(pts, curve):
    """ffmpeg expression for balance position at time t.

    Linear between points, hold outside them, `hold` steps. Same
    interpolation as value_at; written as `if(lt(t,...))` so aeval can
    evaluate it per sample. ffmpeg's pan filter takes no runtime command
    (asendcmd cannot drive it), so the curve lives here rather than as a
    second asendcmd staircase.
    """
    if len(pts) == 1:
        return f"{pts[0][1]:.4f}"
    expr = f"{pts[-1][1]:.4f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(pts, pts[1:]))):
        if curve == "hold" or abs(t1 - t0) < MIN_DT:
            seg = f"{v0:.4f}"
        else:
            seg = (f"({v0:.4f}+({v1:.4f}-{v0:.4f})"
                   f"*(t-{t0:.3f})/{(t1 - t0):.3f})")
        expr = f"if(lt(t,{t1:.3f}),{seg},{expr})"
    t0, v0 = pts[0]
    return f"if(lt(t,{t0:.3f}),{v0:.4f},{expr})"


def _pan_fragment(pts, curve="linear"):
    """Time-varying stereo BALANCE, same law as effects.pan.

    L = min(1, 1-p), R = min(1, 1+p). ffmpeg's pan filter cannot be
    driven by asendcmd, so this is one aeval (comma-chainable, no join
    graph change) rather than per-channel volume labels.

    aformat first: aeval `val(1)` is 0 on a mono lavfi source, and
    `c=same` would keep the stream mono so mix_audio's later stereo
    upmix restores centre. Two explicit exprs so each side is a
    channel, not one gain applied twice.
    """
    p = _pan_position_expr(pts, curve)
    return (
        "aformat=channel_layouts=stereo,"
        f"aeval=exprs='val(0)*min(1,1-({p}))|val(1)*min(1,1+({p}))'"
    )


def item_audio(set_item_id):
    """What the renderer needs from this item's curves, as plain data.

    {"frags": [filter, ...], "suppress_loudnorm": bool}. Carried in the item
    dict exactly as effects_json is, so mixer never imports this module, never
    touches the database and stays pure media code -- the same reason the curve
    is decimated here and not there.

    suppress_loudnorm is docs/TRD-1 5.0(c): an item with a drawn gain curve
    renders with per-item loudnorm OFF and is levelled at the master, because
    loudnorm is dynamic and runs last and would otherwise flatten the curve.
    """
    frags = []
    for lane in ("gain_db", "pan", "lowpass_hz", "highpass_hz"):
        pts = read(set_item_id, lane)
        if pts:
            frags.append(fragment(lane, pts))
    return {"frags": frags, "suppress_loudnorm": wants_master_loudnorm(set_item_id)}


def wants_master_loudnorm(set_item_id):
    """True when this item's per-item loudnorm must be turned OFF.

    THE SERIOUS ONE, docs/TRD-1 5.0(c). loudnorm is appended last in every
    item's chain and is a dynamic normaliser, so an item with a drawn gain curve
    would have that curve flattened by a filter two stages after it. The
    renderer asks this and moves levelling to the master for that item.

    Only the gain lane triggers it: a filter sweep is not a level curve and
    loudnorm has no quarrel with it.
    """
    return "gain_db" in lanes_for(set_item_id)


def demo():
    import tempfile

    # ---- decimation: SHAPE survives, not merely the count
    ramp = [(i * 0.01, -12.0 + 12.0 * (i / 300.0)) for i in range(301)]
    kept = decimate(ramp, "gain_db")
    assert len(kept) <= MAX_POINTS, len(kept)
    assert len(kept) < 10, f"a straight line needs two points, kept {len(kept)}"
    for t, want in [(0.0, -12.0), (1.5, -6.0), (3.0, 0.0)]:
        got = value_at(kept, t)
        assert abs(got - want) <= 0.25, f"decimated ramp is {got} at {t}, drawn {want}"

    # a drawn wobble -- three cycles over six seconds, about as fast as a hand
    # moves a fader -- keeps its SHAPE, not merely its count. A cap that kept
    # the first 64 points would pass the length assert and fail this one.
    import math
    wobble = [(i * 0.01, -6.0 + 6.0 * math.sin(i / 100.0)) for i in range(600)]
    kept = decimate(wobble, "gain_db")
    assert len(kept) <= MAX_POINTS, f"{len(kept)} points survived the cap"
    assert kept[-1][0] >= wobble[-1][0] - 1e-9, "the cap truncated the END of the drag"
    worst = max(abs(value_at(kept, t) - v) for t, v in wobble)
    assert worst <= _eps("gain_db", [6.0]) * 2, \
        f"decimated wobble is {worst:.2f} dB from the drawn one"

    # AND THE CASE WHERE THE TWO RULES FIGHT, recorded rather than hidden: a
    # curve carrying more detail than 64 points can hold cannot also stay within
    # epsilon of it. 32 sine cycles in 6 seconds is past Nyquist for this cap.
    # THE CAP WINS -- it is a hard bound on the filter string, and epsilon is a
    # target. The client re-reads what was stored, so what renders is what the
    # editor shows; it is not silently different, it is visibly simpler.
    dense = [(i * 0.01, -6.0 + 6.0 * math.sin(i / 3.0)) for i in range(600)]
    kept = decimate(dense, "gain_db")
    assert len(kept) <= MAX_POINTS, f"the cap did not hold: {len(kept)}"
    assert max(abs(value_at(kept, t) - v) for t, v in dense) > _eps("gain_db", [6.0]), \
        "this fixture is supposed to be past what the cap can represent"

    # 3000 points from a 60 Hz drag is the case the cap exists for
    drag = [(i * 0.016, -3.0 + (i % 7) * 0.05) for i in range(3000)]
    assert len(decimate(drag, "gain_db")) <= MAX_POINTS

    # frequency epsilon is proportional, or 40 Hz would be kept at 8 kHz
    assert _eps("lowpass_hz", [100.0]) < _eps("lowpass_hz", [8000.0])

    # ---- the filter text is a staircase ffmpeg accepts, and it is asendcmd
    frag = fragment("gain_db", [(0.0, -12.0), (3.0, 0.0)])
    assert frag.startswith("asendcmd=commands='0.000 volume volume -12.000dB;"), frag
    assert frag.endswith("volume=volume=-12.000dB"), frag
    assert "3.000 volume volume 0.000dB" in frag
    # sampled, not just the two drawn points -- asendcmd holds between commands,
    # so two commands are a step and not a ramp
    assert frag.count(" volume volume ") > 10, f"the ramp was not sampled: {frag[:200]}"
    assert "1.500 volume volume -6.000dB" in frag, "midpoint is not on the line"
    # a hold curve emits ONLY the drawn points, which is what hold means
    held = fragment("gain_db", [(0.0, -12.0), (3.0, 0.0)], curve="hold")
    assert held.count(" volume volume ") == 2, held
    assert fragment("gain_db", []) == ""
    import subprocess
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "s.wav")
        out = os.path.join(d, "o.wav")
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=3", src],
                       check=True, capture_output=True)
        r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", src,
                            "-af", frag, out], capture_output=True, text=True)
        assert r.returncode == 0, f"ffmpeg refused the automation fragment:\n{r.stderr[-400:]}"

        # AND IT MOVES THE AUDIO. A fragment ffmpeg accepts is not a fragment
        # that does anything -- the first second must end up quieter than the
        # last, because the curve ramps -12 dB -> 0 dB.
        def seg_db(path, ss, to):
            rr = subprocess.run(["ffmpeg", "-nostdin", "-v", "info", "-ss", str(ss),
                                 "-to", str(to), "-i", path, "-af", "volumedetect",
                                 "-f", "null", "-"], capture_output=True, text=True)
            import re
            m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", rr.stderr)
            assert m, f"no reading for {ss}-{to}:\n{rr.stderr[-300:]}"
            return float(m.group(1))
        head, tail = seg_db(out, 0, 1), seg_db(out, 2, 3)
        assert tail - head > 4.0, \
            f"the gain curve did not reach the audio: {head:.1f} dB -> {tail:.1f} dB"

    # ---- store: what comes back is what will render
    db.DATA = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(db.DATA, "t.db")
    db._local.__dict__.clear()

    stored = save(1, "gain_db", ramp)
    assert stored == read(1, "gain_db"), "what was returned is not what was stored"
    assert len(stored) < 10

    # replacing a lane does not accumulate
    save(1, "gain_db", [(0.0, -3.0), (1.0, -3.0)])
    assert len(read(1, "gain_db")) == 2, read(1, "gain_db")

    # two values at one instant have no defined render
    try:
        save(1, "gain_db", [(0.0, -3.0), (0.0, -6.0)])
    except ValueError as e:
        assert "one instant" in str(e), e
    else:
        raise AssertionError("two points at the same t were accepted")
    # (and UNIQUE(set_item_id, lane, t) is the backstop under that guard: with
    # the Python check removed this raises IntegrityError instead of accepting
    # the row, which is the layering working rather than a second check)

    # out of range is refused with the lane's own bound
    try:
        save(1, "gain_db", [(0.0, -999.0)])
    except ValueError as e:
        assert "out of range" in str(e), e
    else:
        raise AssertionError("an out-of-range automation value was accepted")

    try:
        save(1, "nonsense", [(0.0, 0.0)])
    except ValueError as e:
        assert "unknown automation lane" in str(e), e
    else:
        raise AssertionError("an unknown lane was accepted")

    # ---- THE SERIOUS ONE: an item with a gain curve takes per-item loudnorm off
    assert wants_master_loudnorm(1) is True
    assert wants_master_loudnorm(2) is False
    save(2, "lowpass_hz", [(0.0, 8000.0), (2.0, 200.0)])
    assert wants_master_loudnorm(2) is False, \
        "a filter sweep is not a level curve and must not disable loudnorm"
    clear(1, "gain_db")
    assert wants_master_loudnorm(1) is False

    # ---- a pan CURVE is the same balance law as effects.pan, via aeval
    # (ffmpeg's pan filter takes no runtime command, so asendcmd cannot
    # drive it). The expression stays under T1-10's 8 KB cap.
    pfrag = fragment("pan", [(0.0, -1.0), (1.0, 1.0)])
    assert pfrag.startswith("aformat=channel_layouts=stereo,aeval="), pfrag
    assert len(pfrag) < 8192, f"pan fragment is {len(pfrag)} bytes"
    dense_pan = [(i * 0.1, -1.0 + 2.0 * i / 63.0) for i in range(64)]
    assert len(fragment("pan", dense_pan)) < 8192

    print("automation.py OK")


if __name__ == "__main__":
    demo()
