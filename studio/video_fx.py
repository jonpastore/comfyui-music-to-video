"""Per-item video look and layering as ffmpeg filter fragments, for
SETS_MIXING_PLAN.md phase 4/5. Every filter used here (eq, hue, rgbashift,
chromashift, blend) is already in the ffmpeg on this box -- no new
dependency (see the plan's own filter table). Pure string/number
generation: no ffmpeg subprocess, no file I/O, inside any function below.
Only demo() shells out, to prove the fragments are valid ffmpeg syntax.

grade()/glitch() build a single-input filter CHAIN meant to sit next to
mixer.py's own _normalize_filter for one item; layer() builds a two-input
blend fragment for a transition window between two items' video labels --
that one needs two labelled inputs, so it is returned separately rather
than comma-chained with the rest. Wiring either into the actual
filter_complex graph (labels, -i list) is the integrator's job, not this
module's -- same boundary mixer.py itself draws between filter-string
generation (pure, unit-tested) and the ffmpeg call that uses it.
"""
import json

import beatmatch

# --- named ranges, one constant per knob (SETS_MIXING_PLAN.md phase 4/5) ---
# ffmpeg's eq filter accepts a wider technical range on contrast/saturation
# than is ever useful for a look; these are the plan's own creative ceiling,
# a starting point to move once someone has actually graded a clip -- same
# footing as mixer.MAX_TEMPO_STRETCH.
BRIGHTNESS_RANGE = (-1.0, 1.0)   # eq's own hard range
CONTRAST_RANGE = (0.0, 3.0)      # 1.0 = identity
SATURATION_RANGE = (0.0, 3.0)    # 1.0 = identity, 0 = grayscale
HUE_RANGE = (-180.0, 180.0)      # degrees, hue filter's h=

# The keys this module owns. effects.parse_effects IGNORES keys it does not
# recognise; parse_effects_json REFUSES them, so a caller holding one blob for
# both must hand this module only its own subset. Named here so the split is
# defined once rather than retyped by every caller that does it.
# "layer" is here even though it is not a per-item fragment: it is a key this
# module owns and validates, and callers use this tuple to decide what to hand
# to parse_effects_json. mixer.py picks the per-item subset with its own
# _VIDEO_EFFECT_KEYS, because layer is consumed at the JOIN, not on one clip.
VIDEO_KEYS = ("grade", "glitch", "layer")

GLITCH_KINDS = ("rgba", "chroma")
GLITCH_AMOUNT_RANGE = (0, 40)    # pixel shift -- rgbashift/chromashift take ints

# blend's all_mode has dozens of algorithms; these three are the ones the
# plan names for VJ-style double exposure between two songs' footage.
LAYER_MODES = ("screen", "overlay", "difference")
OPACITY_RANGE = (0.0, 1.0)


def _ranged(name, value, lo, hi):
    v = float(value)
    if not (lo <= v <= hi):
        raise ValueError(f"{name}={v} outside [{lo}, {hi}]")
    return v


def grade(brightness=0.0, contrast=1.0, saturation=1.0, hue=0.0):
    """eq (brightness/contrast/saturation) + hue (rotation), chained. All
    four default to identity, so grade() with no args is a no-op fragment
    -- callers skip it entirely rather than render an identity filter, but
    it stays correct either way."""
    b = _ranged("brightness", brightness, *BRIGHTNESS_RANGE)
    c = _ranged("contrast", contrast, *CONTRAST_RANGE)
    s = _ranged("saturation", saturation, *SATURATION_RANGE)
    h = _ranged("hue", hue, *HUE_RANGE)
    return f"eq=brightness={b:.3f}:contrast={c:.3f}:saturation={s:.3f},hue=h={h:.3f}"


def glitch(kind, amount):
    """rgbashift (RGB channels punched apart) or chromashift (chroma planes
    only, subtler) -- one directional shift, red/luma-adjacent channel one
    way and the other channel the opposite way, for a hit. amount is a
    pixel offset, not a percentage: ffmpeg's own units for these filters."""
    if kind not in GLITCH_KINDS:
        raise ValueError(f"kind={kind!r} not in {GLITCH_KINDS}")
    a = int(_ranged("amount", amount, *GLITCH_AMOUNT_RANGE))
    if kind == "rgba":
        return f"rgbashift=rh={a}:bh=-{a}"
    return f"chromashift=cbh={a}:crh=-{a}"


def layer(mode, opacity):
    """blend=all_mode=<mode>:all_opacity=<opacity> -- a two-input fragment
    ([a][b]blend=...[out]), for VJ-style double exposure between two songs'
    footage through a long transition. Not comma-chainable with grade()/
    glitch(): those are single-input, this needs both labels wired by the
    caller."""
    if mode not in LAYER_MODES:
        raise ValueError(f"mode={mode!r} not in {LAYER_MODES}")
    o = _ranged("opacity", opacity, *OPACITY_RANGE)
    return f"blend=all_mode={mode}:all_opacity={o:.3f}"


def parse_effects_json(effects_json):
    """set_items.effects_json (JSON string, dict, or None/"") -> {"grade":
    fragment, "glitch": fragment, "layer": fragment}, one key per effect
    that was actually present -- an absent effect means "off", not
    "identity" (SETS_MIXING_PLAN.md phase 4: "off by default"). Same shape
    as the audio side's effects_json: whatever top-level keys are present
    get validated and built, unknown keys are refused rather than silently
    ignored, and every numeric field runs through the same named-range
    constants grade()/glitch()/layer() themselves enforce -- this function
    adds no ranges of its own, it is purely JSON-shape plus dispatch."""
    if not effects_json:
        return {}
    raw = json.loads(effects_json) if isinstance(effects_json, str) else effects_json
    if not isinstance(raw, dict):
        raise ValueError(f"effects_json must be an object, got {type(raw).__name__}")
    unknown = set(raw) - set(VIDEO_KEYS)
    if unknown:
        raise ValueError(f"effects_json has unknown keys: {sorted(unknown)}")

    out = {}
    try:
        if "grade" in raw:
            out["grade"] = grade(**raw["grade"])
        if "glitch" in raw:
            out["glitch"] = glitch(**raw["glitch"])
        if "layer" in raw:
            out["layer"] = layer(**raw["layer"])
    except TypeError as e:
        raise ValueError(f"effects_json malformed: {e}")
    return out


def beat_cut_offsets(beat_grid, downbeat_offset, want_secs, out_point):
    """(out_secs, secs) for a transition that lands on THIS item's own exit
    point: out_point (the item's existing out_secs, or the track's full
    duration if it has none -- the caller's job to supply, mirroring
    app._beatmatch_plan's own out_point calc) snapped to its nearest
    downbeat via beatmatch.snap_to_downbeat -- the SAME function the set
    editor's preview uses, so the two can never compute a different cut
    point. secs is the actual bar-snapped transition length, chosen as the
    downbeat nearest "want_secs before that snapped point" rather than an
    arbitrary constant.

    This is the whole "both sides follow" story in SETS_MIXING_PLAN.md
    phase 5: mixer.render_set's xfade offset (offset = running_dur - secs,
    in _build_render_set_filter) and mixer.mix_audio's acrossfade both read
    secs/out_secs off the very same set_items row, so fixing these two
    numbers here -- once, in the item's own data -- makes the video cut and
    the audio cut identical. There is no separate video-only offset for the
    audio side to independently reproduce.

    Degrades to (None, want_secs) -- caller keeps its own out_secs,
    unsnapped -- when there's no usable grid, fewer than 2 downbeats, or no
    downbeat strictly before the snapped exit point to start a transition
    from, the same shape as mixer.nearest_downbeat degrading to "no snap".
    """
    if not beat_grid or not (0 <= downbeat_offset < 4):
        return None, want_secs
    bars = beat_grid[downbeat_offset::4]
    if len(bars) < 2:
        return None, want_secs
    end = beatmatch.snap_to_downbeat(out_point, beat_grid, downbeat_offset)
    candidates = [b for b in bars if b < end]
    if not candidates:
        return None, want_secs
    start = min(candidates, key=lambda b: abs(b - (end - want_secs)))
    return end, round(end - start, 6)


def demo():
    # --- grade: identity args round-trip, range violations refused ---
    assert grade() == "eq=brightness=0.000:contrast=1.000:saturation=1.000,hue=h=0.000"
    assert grade(brightness=0.2, contrast=1.5, saturation=0.0, hue=90) == \
        "eq=brightness=0.200:contrast=1.500:saturation=0.000,hue=h=90.000"
    for bad in (dict(brightness=2.0), dict(contrast=-1.0), dict(saturation=5.0), dict(hue=200)):
        try:
            grade(**bad)
            raise AssertionError(f"grade accepted out-of-range {bad}")
        except ValueError:
            pass

    # --- glitch: rgba and chroma both shift one channel each direction ---
    assert glitch("rgba", 10) == "rgbashift=rh=10:bh=-10"
    assert glitch("chroma", 5) == "chromashift=cbh=5:crh=-5"
    try:
        glitch("nope", 5)
        raise AssertionError("glitch accepted an unknown kind")
    except ValueError:
        pass
    try:
        glitch("rgba", 999)
        raise AssertionError("glitch accepted an out-of-range amount")
    except ValueError:
        pass

    # --- layer: mode + opacity, mode is a closed set ---
    assert layer("screen", 0.5) == "blend=all_mode=screen:all_opacity=0.500"
    assert layer("overlay", 1.0) == "blend=all_mode=overlay:all_opacity=1.000"
    assert layer("difference", 0.75) == "blend=all_mode=difference:all_opacity=0.750"
    try:
        layer("multiply", 0.5)
        raise AssertionError("layer accepted a mode outside LAYER_MODES")
    except ValueError:
        pass
    try:
        layer("screen", 1.5)
        raise AssertionError("layer accepted an out-of-range opacity")
    except ValueError:
        pass

    # --- parse_effects_json: JSON-shape dispatch over the same functions ---
    assert parse_effects_json(None) == {}
    assert parse_effects_json("") == {}
    assert parse_effects_json({}) == {}
    full = parse_effects_json(json.dumps({
        "grade": {"brightness": 0.1, "contrast": 1.2, "saturation": 0.9, "hue": -30},
        "glitch": {"kind": "rgba", "amount": 8},
        "layer": {"mode": "screen", "opacity": 0.4},
    }))
    assert full["grade"] == grade(brightness=0.1, contrast=1.2, saturation=0.9, hue=-30)
    assert full["glitch"] == glitch("rgba", 8)
    assert full["layer"] == layer("screen", 0.4)
    # only the keys actually present get built -- absent means off, not identity
    assert parse_effects_json({"glitch": {"kind": "chroma", "amount": 3}}) == \
        {"glitch": glitch("chroma", 3)}
    for bad in ('{"grade": {"brightness": 9.0}}', '{"nope": {}}', "[1, 2]", '{"grade": {"typo": 1}}'):
        try:
            parse_effects_json(bad)
            raise AssertionError(f"parse_effects_json accepted {bad!r}")
        except ValueError:
            pass

    # --- beat_cut_offsets: pure arithmetic, no ffmpeg ---
    grid = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]  # bars at 0,2,4 for offset 0
    # out_point at the track's own end (5.0, no explicit trim) snaps to the
    # nearest bar, 4.0 -- same numbers a caller passing bars[-1] used to get,
    # but now because 4.0 is nearest to out_point, not because it's last.
    out_secs, secs = beat_cut_offsets(grid, 0, 2.0, 5.0)
    assert (out_secs, secs) == (4.0, 2.0), (out_secs, secs)   # exact bar hit both ends
    out_secs, secs = beat_cut_offsets(grid, 0, 1.7, 5.0)
    assert (out_secs, secs) == (4.0, 2.0), (out_secs, secs)   # 1.7 snaps to the 2.0-long bar
    out_secs, secs = beat_cut_offsets(grid, 1, 1.5, 5.0)
    assert (out_secs, secs) == (4.5, 2.0), (out_secs, secs)   # bars at 0.5,2.5,4.5 for offset 1
    # THE regression: an item trimmed to out_point=2.1 (well before the
    # track's own end) must snap around ITS OWN exit, not jump to bars[-1]
    # (4.0) -- turning beatmatch on must never silently discard a trim.
    out_secs, secs = beat_cut_offsets(grid, 0, 2.5, 2.1)
    assert (out_secs, secs) == (2.0, 2.0), (out_secs, secs)
    # no grid / bad offset / too few bars -> unsnapped fallback, want_secs untouched
    assert beat_cut_offsets([], 0, 3.0, 5.0) == (None, 3.0)
    assert beat_cut_offsets(grid, 9, 3.0, 5.0) == (None, 3.0)
    assert beat_cut_offsets([0.0], 0, 3.0, 5.0) == (None, 3.0)
    assert beat_cut_offsets([0.0, 0.5, 1.0, 1.5], 0, 3.0, 5.0) == (None, 3.0), \
        "single downbeat (offset 0, only bar at t=0) has no start candidate before it"

    # --- one real ffmpeg run: prove grade/glitch/layer fragments are valid syntax ---
    import os
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        clip_a = os.path.join(d, "a.mp4")
        clip_b = os.path.join(d, "b.mp4")
        for path in (clip_a, clip_b):
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                                 "-i", "color=c=red:s=64x64", "-t", "1", "-r", "8",
                                 "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
                                capture_output=True, text=True)
            assert r.returncode == 0, r.stderr

        # grade + glitch chained on one input
        graded = os.path.join(d, "graded.mp4")
        chain = grade(brightness=0.1, contrast=1.2, saturation=0.8, hue=45) + "," + glitch("rgba", 4)
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", clip_a, "-vf", chain,
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", graded],
                            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert os.path.exists(graded) and os.path.getsize(graded) > 0

        # layer blend across two inputs
        blended = os.path.join(d, "blended.mp4")
        fc = f"[0:v][1:v]{layer('screen', 0.5)}[out]"
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", clip_a, "-i", clip_b,
                             "-filter_complex", fc, "-map", "[out]",
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", blended],
                            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert os.path.exists(blended) and os.path.getsize(blended) > 0

    print("video_fx.py OK")


if __name__ == "__main__":
    demo()
