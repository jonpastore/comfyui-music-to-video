"""Beat-matching arithmetic: downbeat snapping, transition planning, the
ffmpeg rubberband fragment, and Camelot-wheel ordering suggestions.

Pure functions only -- plain data in, filter-fragment strings or numbers
out. No database access, no ffmpeg subprocess, no import of app.py. Callers
(the set editor, a render job) own the I/O; this module owns the maths.
See SETS_MIXING_PLAN.md phase 3.
"""
import re


# A DJ pitch fader tops out around +/-8% on most hardware and can be pushed
# to +/-16% before a track audibly drags or gallops. 1.16 sits at the top of
# that range: a starting point for SETS_MIXING_PLAN.md's open question 3
# ("pick one after listening, not before"), not a measured value -- one
# constant to move once someone has listened to a few. A 128->174 bpm pair
# is a ratio of 1.36, well past it: not a transition, damage.
MAX_STRETCH = 1.16


def snap_to_downbeat(time, beat_grid, downbeat_offset):
    """Nearest DOWNBEAT to `time`, in seconds. Downbeats are every 4th beat
    starting at index `downbeat_offset` (0-3) into `beat_grid` -- the same
    guessed bar-one analyse.py stores per song. An empty grid, a grid with
    no beat at that offset, or an offset outside 0-3 all degrade to "no
    snap" -- `time` itself unchanged -- so an unanalysed song still mixes,
    just not beat-matched."""
    if not beat_grid or not (0 <= downbeat_offset < 4):
        return time
    bars = beat_grid[downbeat_offset::4]
    if not bars:
        return time
    return min(bars, key=lambda b: abs(b - time))


def plan_transition(out_song, in_song, secs):
    """Where a transition of length `secs` lands on each side, and the
    tempo-stretch ratio needed to match them.

    out_song / in_song: {"bpm": float|None, "beat_grid": [seconds...],
    "downbeat_offset": int, "duration": float} -- the outgoing and incoming
    tracks' own analysis plus how long each clip runs in the set.

    Returns {"out_point", "in_point", "secs", "stretch_ratio",
    "beatmatched", "notes"}. `secs` is clamped to fit both clips.
    `stretch_ratio` is 1.0 whenever beatmatching isn't attempted (missing
    bpm, or the stretch needed exceeds MAX_STRETCH) -- a 128->174 pair
    falls back to a plain crossfade, not damage, and `notes` says why.
    """
    out_dur = float(out_song.get("duration") or 0.0)
    in_dur = float(in_song.get("duration") or 0.0)
    notes = []

    # Clamp against whichever duration(s) are actually known -- an unanalysed
    # or missing clip on ONE side (duration 0.0/falsy) must not disable the
    # clamp entirely, only drop the side that has nothing to clamp against.
    # min(secs, *known) with known=[] leaves secs untouched, matching "clamp
    # to fit both clips" degrading to "clamp to fit whichever clip is known".
    known = [d for d in (out_dur, in_dur) if d]
    fit = min([secs] + known) if known else secs
    if fit < secs:
        notes.append(f"transition {secs:.1f}s longer than the clip it sits "
                      f"on -- clamped to {fit:.1f}s")
    secs = max(0.0, fit)

    out_point = snap_to_downbeat(max(0.0, out_dur - secs),
                                  out_song.get("beat_grid") or [],
                                  out_song.get("downbeat_offset") or 0)
    in_point = snap_to_downbeat(0.0,
                                 in_song.get("beat_grid") or [],
                                 in_song.get("downbeat_offset") or 0)

    out_bpm = out_song.get("bpm") or 0
    in_bpm = in_song.get("bpm") or 0
    ratio = (in_bpm / out_bpm) if out_bpm and in_bpm else 1.0
    beatmatched = bool(out_bpm and in_bpm and ratio <= MAX_STRETCH
                        and (1.0 / ratio) <= MAX_STRETCH)
    if out_bpm and in_bpm and not beatmatched:
        notes.append(f"stretch ratio {ratio:.2f} exceeds MAX_STRETCH "
                      f"({MAX_STRETCH}) -- plain crossfade, no tempo ramp")
        ratio = 1.0

    return {
        "out_point": out_point,
        "in_point": in_point,
        "secs": secs,
        "stretch_ratio": round(ratio, 4),
        "beatmatched": beatmatched,
        "notes": notes,
    }


def rubberband_filter(ratio):
    """ffmpeg filter fragment for a rubberband tempo stretch by `ratio`
    (>1 speeds up/shortens, <1 slows down/lengthens). Never atempo -- it
    chains badly past +/-2x and smears transients; rubberband is built into
    the ffmpeg on this box (verified)."""
    return f"rubberband=tempo={ratio:.4f}"


def camelot_neighbours(code):
    """Camelot codes compatible with `code` for a harmonic mix: the same
    number switching A/B (relative major/minor), or +/-1 on the wheel (a
    fifth away). Returns [(code, reason), ...], or [] for an unparseable
    code."""
    m = re.match(r"^(\d{1,2})([AB])$", (code or "").strip().upper())
    if not m:
        return []
    n, letter = int(m.group(1)), m.group(2)
    if not 1 <= n <= 12:
        return []
    other = "B" if letter == "A" else "A"
    out = [(f"{n}{other}", "relative major/minor")]
    for delta, reason in ((1, "a fifth up"), (-1, "a fifth down")):
        nn = (n - 1 + delta) % 12 + 1
        out.append((f"{nn}{letter}", reason))
    return out


def suggest_order(songs):
    """Suggested running order by Camelot adjacency: starting from the
    first song as given, greedily pick whichever remaining song is
    harmonically compatible next (same key, relative major/minor, or a
    fifth up/down), else whichever is closest in bpm. Returns
    [{"song": s, "reason": str}, ...] in the SUGGESTED order -- never an
    automatic reorder, the caller decides whether to apply it."""
    remaining = list(songs)
    if not remaining:
        return []
    order = [{"song": remaining.pop(0), "reason": "starting point"}]
    while remaining:
        cur_key = (order[-1]["song"].get("key") or "").strip().upper()
        compatible = dict(camelot_neighbours(cur_key)) if cur_key else {}
        pick = reason = None
        for s in remaining:
            skey = (s.get("key") or "").strip().upper()
            if cur_key and skey == cur_key:
                pick, reason = s, "same key"
                break
            if skey in compatible:
                pick, reason = s, compatible[skey]
                break
        if pick is None:
            cur_bpm = order[-1]["song"].get("bpm") or 0
            pick = min(remaining, key=lambda s: abs((s.get("bpm") or 0) - cur_bpm))
            reason = "closest tempo (no harmonic match left)"
        remaining.remove(pick)
        order.append({"song": pick, "reason": reason})
    return order


def demo():
    # --- snap_to_downbeat: empty grid -> no snap, time passes through ---
    assert snap_to_downbeat(12.3, [], 0) == 12.3
    assert snap_to_downbeat(12.3, [], 2) == 12.3

    # --- single-beat grid -> that one beat is the only possible downbeat ---
    assert snap_to_downbeat(9.9, [2.5], 0) == 2.5
    assert snap_to_downbeat(9.9, [2.5], 1) == 9.9  # offset 1 has no bar in a 1-beat grid

    # --- ordinary grid: bars are every 4th beat from the offset, nearest wins ---
    grid = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]
    # offset 0 -> bars at 0.5, 2.5, 4.5 ... ; offset 2 -> bars at 1.5, 3.5, 5.5
    assert snap_to_downbeat(2.6, grid, 0) == 2.5
    assert snap_to_downbeat(2.6, grid, 2) == 3.5 or snap_to_downbeat(2.6, grid, 2) == 1.5
    got = snap_to_downbeat(2.6, grid, 2)
    assert got == min([1.5, 3.5, 5.5], key=lambda b: abs(b - 2.6)), got
    # offset out of 0-3 range -> no snap
    assert snap_to_downbeat(2.6, grid, 4) == 2.6

    # --- plan_transition: ordinary case, matched tempo ---
    out_song = {"bpm": 120.0, "beat_grid": grid, "downbeat_offset": 0, "duration": 6.0}
    in_song = {"bpm": 120.0, "beat_grid": [0.2, 0.7, 1.2, 1.7, 2.2], "downbeat_offset": 0, "duration": 8.0}
    plan = plan_transition(out_song, in_song, 2.0)
    assert plan["beatmatched"] is True
    assert plan["stretch_ratio"] == 1.0
    assert plan["notes"] == []
    assert plan["secs"] == 2.0

    # --- transition longer than the clip it sits on -> clamped, and said so ---
    short = {"bpm": 120.0, "beat_grid": [], "downbeat_offset": 0, "duration": 3.0}
    long_in = {"bpm": 120.0, "beat_grid": [], "downbeat_offset": 0, "duration": 20.0}
    plan = plan_transition(short, long_in, 10.0)
    assert plan["secs"] == 3.0, plan
    assert any("longer than the clip" in n for n in plan["notes"]), plan["notes"]

    # --- one side's duration unknown (unanalysed / missing mp3) -> still
    # clamps against the side that IS known, rather than skipping the clamp
    # entirely (the bug: `if out_dur and in_dur` required BOTH truthy) ---
    unknown_out = {"bpm": None, "beat_grid": [], "downbeat_offset": 0, "duration": 0.0}
    known_in = {"bpm": None, "beat_grid": [], "downbeat_offset": 0, "duration": 5.0}
    plan = plan_transition(unknown_out, known_in, 20.0)
    assert plan["secs"] == 5.0, plan
    assert any("longer than the clip" in n for n in plan["notes"]), plan["notes"]
    # and the mirror case: known out, unknown in
    plan = plan_transition(known_in, unknown_out, 20.0)
    assert plan["secs"] == 5.0, plan
    # both unknown -> nothing to clamp against, secs passes through
    plan = plan_transition(unknown_out, unknown_out, 20.0)
    assert plan["secs"] == 20.0, plan
    assert plan["notes"] == []

    # --- two songs too far apart in tempo -> refuses the stretch, plain crossfade ---
    slow = {"bpm": 128.0, "beat_grid": [], "downbeat_offset": 0, "duration": 30.0}
    fast = {"bpm": 174.0, "beat_grid": [], "downbeat_offset": 0, "duration": 30.0}
    plan = plan_transition(slow, fast, 4.0)
    assert plan["beatmatched"] is False
    assert plan["stretch_ratio"] == 1.0
    assert any("exceeds MAX_STRETCH" in n for n in plan["notes"]), plan["notes"]
    raw_ratio = fast["bpm"] / slow["bpm"]
    assert raw_ratio > MAX_STRETCH, "fixture must actually exceed the constant"

    # --- empty beat grid on both sides still produces a plan, just unsnapped ---
    a = {"bpm": None, "beat_grid": [], "downbeat_offset": 0, "duration": 10.0}
    b = {"bpm": None, "beat_grid": [], "downbeat_offset": 0, "duration": 10.0}
    plan = plan_transition(a, b, 3.0)
    assert plan["out_point"] == 7.0
    assert plan["in_point"] == 0.0
    assert plan["stretch_ratio"] == 1.0
    assert plan["beatmatched"] is False

    # --- rubberband_filter: exact fragment, never atempo ---
    assert rubberband_filter(1.0) == "rubberband=tempo=1.0000"
    assert rubberband_filter(0.85) == "rubberband=tempo=0.8500"
    assert "atempo" not in rubberband_filter(1.3)

    # --- camelot_neighbours: relative major/minor plus a fifth each way ---
    got = dict(camelot_neighbours("8A"))
    assert got["8B"] == "relative major/minor"
    assert got["9A"] == "a fifth up"
    assert got["7A"] == "a fifth down"
    assert camelot_neighbours("8A")[0][0] != "8A"  # never suggests itself
    assert camelot_neighbours("13A") == []  # out of range
    assert camelot_neighbours("junk") == []
    # wheel wraps
    assert dict(camelot_neighbours("1A"))["12A"] == "a fifth down"
    assert dict(camelot_neighbours("12A"))["1A"] == "a fifth up"

    # --- suggest_order: harmonic match preferred, tempo fallback, never mutates input ---
    songs = [
        {"name": "A", "key": "8A", "bpm": 120},
        {"name": "C", "key": "5A", "bpm": 90},   # unrelated key, far tempo
        {"name": "B", "key": "9A", "bpm": 122},  # a fifth up from A
    ]
    order = suggest_order(songs)
    assert [s["song"]["name"] for s in order] == ["A", "B", "C"]
    assert order[0]["reason"] == "starting point"
    assert order[1]["reason"] == "a fifth up"
    assert order[2]["reason"] == "closest tempo (no harmonic match left)"
    assert len(songs) == 3 and songs[0]["name"] == "A"  # input untouched
    assert suggest_order([]) == []
    single = [{"name": "solo", "key": "8A", "bpm": 100}]
    assert [s["song"]["name"] for s in suggest_order(single)] == ["solo"]

    print("beatmatch.py OK")


if __name__ == "__main__":
    demo()
