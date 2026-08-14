"""ffmpeg-only video/audio assembly for Meow P Studio. No moviepy, no librosa.

Silent WAN 2.2 S2V clips (832x480, 16fps, 4.8125s) get concatenated and the
master mp3 is muxed over the assembled timeline exactly once -- per-clip audio
drifts, so audio never touches an individual clip. Matches the pattern in
build_song.py (FPS/LEN/CHUNK/W/H) and Street Cats/Back Alley Pussy/assemble.sh
(concat demuxer, re-encode always -- stream copy trips on encoder-parameter
drift between separately-rendered clips).

Every ffmpeg call is explicit-arg-list (no shell=True), checked for return
code, and writes to a temp file that's os.replace()'d into out_path so a
failed render never clobbers a good one.
"""
import json, os, re, subprocess, tempfile, shutil

import beatmatch
import effects
import video_fx

_NOOP = lambda *a, **k: None


def probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffprobe failed:\n" + "\n".join(r.stderr.splitlines()[-20:]))
    data = json.loads(r.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    vstream = next((s for s in streams if s["codec_type"] == "video"), None)
    astream = next((s for s in streams if s["codec_type"] == "audio"), None)
    return {
        "duration": float(fmt["duration"]) if fmt.get("duration") else 0.0,
        "width": int(vstream["width"]) if vstream else 0,
        "height": int(vstream["height"]) if vstream else 0,
        "fps": _parse_rate(vstream.get("avg_frame_rate") or vstream.get("r_frame_rate", "0/1")) if vstream else 0.0,
        "has_audio": astream is not None,
        "has_video": vstream is not None,
    }


def _parse_rate(rate):
    try:
        num, den = rate.split("/")
        return float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def _atomic_out(out_path):
    out_path = os.path.abspath(out_path)
    d = os.path.dirname(out_path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(out_path)[1] or ".mp4", dir=d)
    os.close(fd)
    return tmp


def _run_ffmpeg(args, progress, total_duration=None, stage="ffmpeg"):
    """Run ffmpeg, streaming stderr to progress() as time= is parsed. On
    failure raise RuntimeError with the last 20 lines of stderr."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats"] + list(args)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, bufsize=1)
    time_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
    lines = []
    for line in proc.stderr:
        line = line.rstrip()
        if not line:
            continue
        lines.append(line)
        m = time_re.search(line)
        if m:
            secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            if total_duration:
                progress(f"{stage}: {min(100.0, secs / total_duration * 100.0):.0f}%")
            else:
                progress(f"{stage}: {secs:.1f}s")
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + "\n".join(lines[-20:]))


# The waveform picture behind a set's channels. A PNG from ffmpeg's own
# showwavespic, not a JSON peaks array: measured on this project's own 479s
# track, 2000x120 is 9.3 KB in 1.3s, against 24-90 KB for a peaks array at any
# useful resolution -- and the PNG needs an <img> where the array needs a
# bucketing pass, a decoder and a canvas renderer.
#
# Transparent background, one accent colour, so a single file serves whatever
# the page's theme is.
WAVEFORM_SIZE = (2000, 120)
WAVEFORM_COLOR = "0x8ab4f8"


def waveform_png(audio_path, out_path, progress=None, size=WAVEFORM_SIZE):
    """One track's waveform as a transparent PNG.

    Of the RAW track. The renderer level-matches every item with loudnorm
    (effects.py, on by default), so the picture is not what the mix sounds
    like -- generating it through loudnorm closes that gap and costs 10x the
    time, measured. The UI says so instead. It is a cosmetic mismatch and not a
    correctness one: an envelope drawn on it is a RELATIVE gain and behaves the
    same either way.
    """
    w, h = size
    tmp = _atomic_out(out_path)
    try:
        _run_ffmpeg(["-i", audio_path,
                     "-filter_complex", f"showwavespic=s={w}x{h}:colors={WAVEFORM_COLOR}",
                     "-frames:v", "1", tmp],
                    progress or (lambda _m: None), stage="waveform")
        os.replace(tmp, out_path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return out_path


# Timeline peaks. waveform_png stays for the static picture; the editor needs
# numbers so regions can be dragged (docs/TRD-1 T1-13 / T1-14). Cap is a hard
# bound on every zoom: a 60-minute set must not decode in the browser.
PEAKS_MAX_POINTS = 2048


def peaks(samples, z=0):
    """Decimated min/max envelope for zoom level *z*.

    At most PEAKS_MAX_POINTS [min, max] pairs, regardless of song length or
    z, and at least one pair when samples is non-empty. Empty input is []
    (T1-15 owns the explicit reason). Decimation is a min/max reduce over
    contiguous spans, not a resample: a bucket's pair is exactly the
    full-resolution min and max over that span.

    z is the zoom the request asked for. The cap holds at every z. A
    windowed zoom is a later slice; this one covers the whole signal.
    """
    if samples is None:
        return []
    n = len(samples)
    if n == 0:
        return []
    n_buckets = min(PEAKS_MAX_POINTS, n)
    out = []
    for i in range(n_buckets):
        start = i * n // n_buckets
        end = (i + 1) * n // n_buckets
        span = samples[start:end]
        out.append([float(min(span)), float(max(span))])
    return out


def peaks_from_path(audio_path, z=0):
    """Decode one file to samples, then peaks(). Missing path is []."""
    if not audio_path or not os.path.isfile(audio_path):
        return []
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", audio_path, "-ac", "1", "-ar", "8000",
         "-f", "f32le", "-"],
        capture_output=True, check=False)
    if raw.returncode != 0 or not raw.stdout:
        return []
    import struct
    n = len(raw.stdout) // 4
    samples = list(struct.unpack("<" + "f" * n, raw.stdout[:n * 4]))
    return peaks(samples, z=z)


def _write_concat_list(paths):
    fd, list_path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w") as f:
        for p in paths:
            escaped = os.path.abspath(p).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
    return list_path


def _crossfade_chain(n, durations, fade, transition="fade"):
    """[i:v]xfade... lines chaining n video inputs with a constant crossfade.
    Returns (lines, final_label, final_duration). Pure string generation --
    no ffmpeg call -- so it's unit-testable on its own (see demo())."""
    running, running_dur, lines = "0:v", durations[0], []
    for i in range(1, n):
        offset = running_dur - fade
        if offset < 0:
            raise ValueError(f"fade={fade}s longer than clip {i - 1} duration={running_dur}s")
        label = f"vx{i}"
        lines.append(f"[{running}][{i}:v]xfade=transition={transition}:duration={fade:.3f}:offset={offset:.3f}[{label}]")
        running, running_dur = label, running_dur + durations[i] - fade
    return lines, running, running_dur


def assemble_song(clip_paths, mp3_path, out_path, progress=None, fade=0.0):
    progress = progress or _NOOP
    if not clip_paths:
        raise ValueError("clip_paths is empty")
    progress(f"probing {len(clip_paths)} clips + audio")
    # The song is as long as the TRACK. Clips are quantised to 4.8125s so the
    # video always overruns -- 50 clips of Back Alley Pussy are 240.63s against
    # a 237.67s song, and the first complete render ended with 3 seconds of
    # silent picture. -shortest was supposed to prevent exactly that and did
    # not (it is unreliable when the video is re-encoded from a concat
    # demuxer), so the length is stated outright as well.
    audio_dur = probe(mp3_path)["duration"]

    tmp = _atomic_out(out_path)
    list_path = None
    try:
        if fade <= 0:
            # concat demuxer: fast, and stream-copy-friendly if callers ever
            # want to skip the re-encode -- kept re-encoding here to match
            # assemble.sh's fix for encoder-parameter drift between clips.
            list_path = _write_concat_list(clip_paths)
            args = ["-f", "concat", "-safe", "0", "-i", list_path, "-i", mp3_path,
                    "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", "-t", f"{audio_dur:.3f}", tmp]
        else:
            durations = [probe(p)["duration"] for p in clip_paths]
            lines, vlabel, _ = _crossfade_chain(len(clip_paths), durations, fade)
            inputs = []
            for p in clip_paths:
                inputs += ["-i", p]
            inputs += ["-i", mp3_path]
            args = inputs + ["-filter_complex", ";\n".join(lines),
                              "-map", f"[{vlabel}]", "-map", f"{len(clip_paths)}:a",
                              "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                              "-c:a", "aac", "-b:a", "192k", "-shortest", "-t", f"{audio_dur:.3f}", tmp]
        progress("assembling")
        _run_ffmpeg(args, progress, total_duration=audio_dur, stage="assemble")
        os.replace(tmp, out_path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    finally:
        if list_path and os.path.exists(list_path):
            os.remove(list_path)
    progress("done")
    return out_path


def edit_audio(mp3_path, out_path, trim_start=0.0, trim_end=None, gain_db=0.0,
               fade_in=0.0, fade_out=0.0, progress=None):
    progress = progress or _NOOP
    duration = probe(mp3_path)["duration"]
    seg_len = max(0.0, (trim_end if trim_end is not None else duration) - trim_start)

    filters = []
    if gain_db:
        filters.append(f"volume={float(gain_db):.3f}dB")
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0:
        filters.append(f"afade=t=out:st={max(0.0, seg_len - fade_out):.3f}:d={fade_out:.3f}")

    args = ["-ss", str(trim_start)]  # -to after -i is absolute-from-file-start, matching trim_end
    if trim_end is not None:
        args += ["-to", str(trim_end)]
    args += ["-i", mp3_path]
    if filters:
        args += ["-af", ",".join(filters)]
    codec = "libmp3lame" if os.path.splitext(out_path)[1].lower() == ".mp3" else "aac"
    args += ["-c:a", codec, "-b:a", "192k"]

    tmp = _atomic_out(out_path)
    try:
        progress("editing audio")
        _run_ffmpeg(args + [tmp], progress, total_duration=seg_len, stage="edit_audio")
        os.replace(tmp, out_path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    progress("done")
    return out_path


SPLICE_XFADE = 0.25   # seconds of overlap at each seam; short enough not to eat a bar


def bridge_seconds(mp3_path, start, end, xfade=SPLICE_XFADE):
    """How long a bridge must BE for splice_bridge to return the original length.

    The caller cannot compute this as gap + 2*xfade, which is what it did until
    a review caught it: a span that reaches the start or the end of the track
    has only ONE seam, so only one crossfade is consumed, and a bridge sized for
    two comes back a quarter of a second long. The arithmetic lives here, beside
    the code that performs it, so the two cannot disagree -- the same reason
    set_duration and render_set share theirs.
    """
    duration = probe(mp3_path)["duration"]
    seams = (1 if start > 0 else 0) + (1 if end < duration else 0)
    return (float(end) - float(start)) + seams * xfade


def splice_bridge(mp3_path, bridge_path, out_path, start, end, xfade=SPLICE_XFADE,
                  progress=None):
    """Replace [start, end) of mp3_path with bridge_path. THE cut-from-the-middle.

    models.py used to catalogue ACE-Step as the answer to this, on the grounds
    that "ffmpeg can only trim the ENDS of a track". Both halves were wrong.
    ffmpeg can cut from anywhere -- it just needs three pieces and two seams --
    and ACE-Step cannot do it at all, because no backend publishes a region or
    mask node, so a denoise below 1.0 re-synthesises the whole track. What
    ACE-Step supplies is the BRIDGE; the cutting and the joining are here.

    Seams are crossfaded rather than butt-joined: a hard splice between two
    unrelated renders clicks, and a click is the one artefact a listener hears
    every time. acrossfade consumes `xfade` seconds from each side, so the
    result runs about 2*xfade shorter than head + bridge + tail.

    Raises rather than guessing when the span is not inside the track: a
    silently clamped range would return a file that is not the edit that was
    asked for, and nothing downstream could tell.
    """
    progress = progress or _NOOP
    duration = probe(mp3_path)["duration"]
    start, end = float(start), float(end)
    if not 0.0 <= start < end <= duration + 0.001:
        raise ValueError(f"the span {start:.3f}-{end:.3f}s is not inside a "
                         f"{duration:.3f}s track")
    bridge_len = probe(bridge_path)["duration"]
    if bridge_len <= 0:
        raise ValueError("the bridge has no audio in it")

    head, tail = start, max(0.0, duration - end)
    # A piece of exactly ZERO is fine -- the span reaches the edge of the track
    # and there is simply no seam on that side. A piece SHORTER than the fade is
    # not: acrossfade would be asked to consume audio that is not there, and the
    # first version of this dropped such a piece silently. Measured on a 20s
    # track spliced at 0.1s: the first 0.1s vanished and the result came back
    # 0.193s LONGER than the original, because the caller had sized the bridge
    # for two crossfades and only one happened. Refusing is the honest answer --
    # the span the user wants is start=0, and they can say so.
    for piece, which, edge in ((head, "before", "0"), (tail, "after", f"{duration:.3f}")):
        if 0 < piece <= xfade:
            raise ValueError(
                f"only {piece:.3f}s of track is left {which} the span, which is shorter "
                f"than the {xfade:.2f}s crossfade -- there is not enough audio there to "
                f"fade into. Use {edge} for that end of the span instead.")
    parts, chain, n = [], [], 0
    if head:
        parts += ["-ss", "0", "-to", f"{start:.3f}", "-i", mp3_path]
        n += 1
    parts += ["-i", bridge_path]
    n += 1
    if tail:
        parts += ["-ss", f"{end:.3f}", "-i", mp3_path]
        n += 1
    if n == 1:
        raise ValueError("that span covers the whole track -- generate a take instead "
                         "of splicing one into nothing")
    prev = "[0:a]"
    for i in range(1, n):
        out = f"[x{i}]"
        chain.append(f"{prev}[{i}:a]acrossfade=d={xfade:.3f}:c1=tri:c2=tri{out}")
        prev = out
    codec = "libmp3lame" if os.path.splitext(out_path)[1].lower() == ".mp3" else "aac"
    args = parts + ["-filter_complex", ";".join(chain), "-map", prev,
                    "-c:a", codec, "-b:a", "192k"]

    tmp = _atomic_out(out_path)
    try:
        progress(f"splicing {end - start:.2f}s at {start:.2f}s into a {duration:.2f}s track")
        _run_ffmpeg(args + [tmp], progress,
                    total_duration=head + bridge_len + tail, stage="splice_bridge")
        os.replace(tmp, out_path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    progress("done")
    return out_path


_XFADE_NAMES = {"fade": "fade", "dissolve": "dissolve", "wipe": "wipeleft"}  # xfade has no generic "wipe"

# Every transition a set may ask for, in the order the editor offers them.
# Defined HERE because mixer is the only module that knows what it can
# actually render; app.SET_TRANSITIONS and mixadvice.transitions() both read
# this rather than keeping their own list to drift out of step with it.
TRANSITIONS = ("fade", "dissolve", "wipe", "cut", "black")


def _item_duration(info, it):
    """An item's playing length after in_secs/out_secs trim, clamped to the
    file's own probed length. Shared by render_set, mix_audio and set_duration
    so the three never disagree about how long a trimmed item runs -- the same
    reason they already share their overlap arithmetic."""
    # A ramped item is exactly as long as apply_tempo_ramp will make it: the
    # ramp both stretches the closing bars AND drops everything past the exit
    # point, so its output length replaces the trim arithmetic rather than
    # adjusting it. _apply_beatmatch plans the ramp before anything reads a
    # duration, so prediction and render read the same plan.
    # Computed ONCE, before the ramp branch: that branch returns early, so an
    # echo tail on a ramped item was silently dropped and the mix came out
    # longer than predicted by exactly the delay. Both paths add it.
    extra = effects.duration_delta(it.get("effects_json"))
    ramp = it.get("_ramp")
    if ramp:
        rl = ramped_duration(ramp["bar_times"], ramp["ratios"])
        if rl is not None:
            return max(0.0, rl) + extra
    full = info["duration"]
    in_s = float(it.get("in_secs") or 0.0)
    out_s = it.get("out_secs")
    out_s = float(out_s) if out_s is not None else full
    # aecho appends its delay to the stream, so a trimmed length alone is short
    # by exactly that -- and the same number drives the crossfade offsets and the
    # fit guard, not just the total shown in the editor.
    return max(0.0, min(out_s, full) - in_s) + extra


def _trim_input_args(it):
    """-ss/-to as INPUT options, placed before -i. Matches edit_audio's own
    seek pattern: -to here is absolute-from-file-start, not relative to -ss."""
    args = []
    if it.get("in_secs"):
        args += ["-ss", str(it["in_secs"])]
    if it.get("out_secs") is not None:
        args += ["-to", str(it["out_secs"])]
    return args


def _normalize_filter(idx, w, h, fps, video_extra=None):
    """Geometry normalisation, plus one item's own look/glitch chain
    (video_fx.grade/glitch) tacked on before the label -- same single-input
    chain, so it costs nothing extra to wire in."""
    # settb=AVTB is not cosmetic. concat emits timebase 1/1000000 while a raw
    # normalized input carries 1/fps, and xfade REFUSES two inputs whose
    # timebases differ ("First input link main timebase (1/1000000) do not match
    # ... (1/16)"). Any join that ends in concat -- a cut, a fade to black, a
    # layer blend -- therefore could not be followed by a fade, dissolve or wipe:
    # set_duration predicted a confident length and ffmpeg then refused the
    # graph. Pinning every input to the same base makes the two producers agree.
    base = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},settb=AVTB")
    if video_extra:
        base += "," + video_extra
    return f"[{idx}:v]{base}[v{idx}n]"


# effects_json keys video_fx.py owns. Shared with the audio side's own
# effects_json (effects.parse_effects ignores keys it doesn't recognise, so
# one JSON blob per item can carry both) -- video_fx.parse_effects_json is
# the strict one, so only this subset is ever handed to it.
_VIDEO_EFFECT_KEYS = ("grade", "glitch")


def _video_fragment(effects_json):
    """grade/glitch chain for one item's video, or None if neither is set.
    "layer" is not read here because it is not a per-item fragment: it is a
    two-input blend consumed at the JOIN, by _layer_join below, out of the
    transition window where both clips exist."""
    if not effects_json:
        return None
    raw = json.loads(effects_json) if isinstance(effects_json, str) else effects_json
    video_only = {k: v for k, v in raw.items() if k in _VIDEO_EFFECT_KEYS}
    if not video_only:
        return None
    parsed = video_fx.parse_effects_json(video_only)
    frags = [parsed[k] for k in _VIDEO_EFFECT_KEYS if k in parsed]
    return ",".join(frags) if frags else None


def _layer_fragment(effects_json):
    """The blend fragment for the transition OUT of this item, or None.

    Read off the same item that carries `transition` and `secs`, because that
    is the item the transition belongs to -- layer was filed as a per-ITEM
    effect but it is a per-TRANSITION one, which is the whole reason it sat
    unwired: on one clip it looks like a filter that merely "needs a second
    input", and there is no second input until the join.
    """
    if not effects_json:
        return None
    raw = json.loads(effects_json) if isinstance(effects_json, str) else effects_json
    if "layer" not in raw:
        return None
    return video_fx.parse_effects_json({"layer": raw["layer"]})["layer"]


def _layer_join(running_v, nxt_v, out_v, offset, secs, blend, i):
    """Blend the two clips across the transition window instead of xfading.

    xfade has no blend modes, so the overlap is cut out of both streams,
    blended, and spliced back:

        [running_v] = head(0..offset) + overlap(offset..offset+secs)
        [nxt_v]     = overlap(0..secs) + tail(secs..end)

    `running_v` ends exactly at offset+secs -- it is the accumulated chain up
    to this join -- so it splits in two, not three.

    The result is the SAME LENGTH as the xfade it replaces (head + secs +
    tail), which is why the caller's duration arithmetic is untouched. That
    also means no duration measurement can tell layer from xfade: the
    difference is in the pixels, and demo() checks it there.
    """
    h, oa, ob, t, ov = (f"lh{i}", f"loa{i}", f"lob{i}", f"lt{i}", f"lov{i}")
    return [
        f"[{running_v}]split=2[{h}s][{oa}s]",
        f"[{h}s]trim=0:{offset:.3f},setpts=PTS-STARTPTS[{h}]",
        f"[{oa}s]trim={offset:.3f}:{offset + secs:.3f},setpts=PTS-STARTPTS,format=gbrp[{oa}]",
        f"[{nxt_v}]split=2[{ob}s][{t}s]",
        f"[{ob}s]trim=0:{secs:.3f},setpts=PTS-STARTPTS,format=gbrp[{ob}]",
        f"[{t}s]trim={secs:.3f},setpts=PTS-STARTPTS[{t}]",
        # gbrp in, yuv420p back out. blend works PER PLANE on whatever it is
        # given, so on yuv420p "screen" screens the chroma planes: red over
        # green came out magenta instead of yellow, which no duration check
        # could have seen and the frame comparison in demo() did.
        f"[{oa}][{ob}]{blend},format=yuv420p[{ov}]",
        f"[{h}][{ov}][{t}]concat=n=3:v=1:a=0[{out_v}]",
    ]


# A fade to black is a TRANSITION KIND, not an inserted clip
# (ALBUM_ARC_AND_STAGING_PLAN.md §1). An inserted clip has to be kept in step by
# hand on two render paths; a transition cannot drift, because one place
# computes where it starts.
#
#     [song A] --fade out--> BLACK + SILENCE --fade in--> [song B]
#                secs/2          hold                secs/2
#
# `secs` is the total fade time, split either side of the hold, and both halves
# happen INSIDE the neighbouring items rather than overlapping them -- so a
# black handover lengthens the set by exactly `hold` and nothing else.
BLACK = "black"


def _black_plan(it):
    """(fade_secs_each_side, hold_secs) for a fade-to-black handover."""
    return (max(0.0, float(it.get("secs") or 0.0)) / 2.0,
            max(0.0, float(it.get("hold") or 0.0)))


def _advance(it, next_duration):
    """How much the running length grows when this item hands over to the next.

    ONE definition, called by all three walkers -- set_duration,
    _build_render_set_filter and mix_audio. They already shared their overlap
    arithmetic by writing it out three times; adding a third transition shape to
    three copies is how a predicted length and a rendered length start to
    disagree, which is this codebase's oldest and most repeated defect.
    """
    kind = it.get("transition", "cut")
    if kind == BLACK:
        return next_duration + _black_plan(it)[1]
    secs = 0.0 if kind == "cut" else float(it.get("secs", 0.0))
    return next_duration - secs


def _black_audio_lines(running_a, nxt_a, out_a, st, fade, hold, i):
    fo, sil, fi = f"bafo{i}", f"bsil{i}", f"bafi{i}"
    lines = [f"[{running_a}]afade=t=out:st={st:.3f}:d={fade:.3f}[{fo}]",
             f"[{nxt_a}]afade=t=in:st=0:d={fade:.3f}[{fi}]"]
    if hold > 0:
        lines += [f"anullsrc=r=48000:cl=stereo:d={hold:.3f}[{sil}]",
                  f"[{fo}][{sil}][{fi}]concat=n=3:v=0:a=1[{out_a}]"]
    else:
        lines.append(f"[{fo}][{fi}]concat=n=2:v=0:a=1[{out_a}]")
    return lines


def _black_video_lines(running_v, nxt_v, out_v, st, fade, hold, w, h, fps, i):
    fo, blk, fi = f"bvfo{i}", f"blk{i}", f"bvfi{i}"
    lines = [f"[{running_v}]fade=t=out:st={st:.3f}:d={fade:.3f}[{fo}]",
             f"[{nxt_v}]fade=t=in:st=0:d={fade:.3f}[{fi}]"]
    if hold > 0:
        # matched to _normalize_filter's own tail, or concat refuses the join
        lines += [f"color=c=black:s={w}x{h}:r={fps}:d={hold:.3f},"
                  f"format=yuv420p,setsar=1[{blk}]",
                  f"[{fo}][{blk}][{fi}]concat=n=3:v=1:a=0[{out_v}]"]
    else:
        lines.append(f"[{fo}][{fi}]concat=n=2:v=1:a=0[{out_v}]")
    return lines


# A branding still, faded in and out over a handover
# (ALBUM_ARC_AND_STAGING_PLAN.md sec 2). An overlay changes NO duration, which
# is the whole reason it comes before the interstitial card: it is the version
# that cannot disturb the arithmetic every other part of this file depends on.
#
# ponytail: fixed placement and size -- centred, in the lower third, a quarter
# of the frame wide. Per-item x/y/scale when someone actually wants a mark
# somewhere else; a knob nobody has asked for is a knob nobody has tested.
BRAND_MIN_SECS = 2.0        # a mark shorter than this reads as a flicker
BRAND_FADE_SECS = 0.4
BRAND_WIDTH_FRACTION = 0.25
BRAND_BOTTOM_MARGIN = 0.12  # of frame height


def _brand_window(centre, span, total):
    """(start, end) for a mark anchored ON a handover rather than near it.

    Widened to BRAND_MIN_SECS when the transition itself is shorter -- a
    half-second wipe would otherwise flash the mark for half a second -- and
    clamped into the timeline so a handover near either end cannot ask ffmpeg
    for a negative start or an end past the last frame.
    """
    span = max(float(span or 0.0), BRAND_MIN_SECS)
    st = max(0.0, centre - span / 2.0)
    en = min(float(total), st + span)
    return st, max(st, en)


def _brand_lines(idx, label, out_label, src, st, en, w, h):
    """One overlay pass: the still, faded up and down on its alpha channel, shown
    only between st and en. yuva420p because overlay wants an alpha-carrying
    pixel format for the top layer; -2 on the scale keeps the height even."""
    lbl = f"brnd{idx}"
    fade = min(BRAND_FADE_SECS, (en - st) / 2.0)
    return [
        f"[{idx}:v]format=yuva420p,scale={int(w * BRAND_WIDTH_FRACTION)}:-2,"
        f"fade=t=in:st={st:.3f}:d={fade:.3f}:alpha=1,"
        f"fade=t=out:st={max(st, en - fade):.3f}:d={fade:.3f}:alpha=1[{lbl}]",
        # shortest=1, with the still deliberately made LONGER than the video by
        # its caller: overlay otherwise runs to the LONGEST input and a looped
        # image added exactly one frame to the set. An overlay that changes the
        # duration is the one thing this feature is supposed not to do.
        f"[{label}][{lbl}]overlay=x=(W-w)/2:y=H-h-{int(h * BRAND_BOTTOM_MARGIN)}:"
        f"shortest=1:enable='between(t,{st:.3f},{en:.3f})'[{out_label}]",
    ]


def _brand_at(brands, it, centre, span):
    """Record this item's mark, if it has one, against the handover it belongs
    to. Reads brand_path off the SAME item that carries transition and secs."""
    path = (it.get("brand_path") or "").strip() if it.get("brand_path") else ""
    if path:
        brands.append((path, centre, span))


def _check_join_effects(items):
    """Refuse a join effect that no join will ever read.

    layer and duck act on the transition INTO the next item. Two ways to ask
    for one that nothing consumes: on a cut, which has no overlap, and on the
    LAST item, which has no next item -- the join loops run to n-1, so an effect
    there is read by nobody. Both were silent drops until this existed, which is
    the accepted-and-ignored outcome this codebase does not allow.
    """
    for i, it in enumerate(items):
        fx_json = it.get("effects_json")
        if i == len(items) - 1:
            present = [k for k in effects.JOIN_KEYS
                       if k in (json.loads(fx_json) if isinstance(fx_json, str) else (fx_json or {}))]
            if present:
                raise ValueError(
                    f"the last item asks for {', '.join(present)}, which act on the transition "
                    f"into the NEXT item -- and it has none. Move it to an earlier item, or "
                    f"remove it.")
            continue
        no_window = effects.join_effects_without_overlap(
            fx_json, it.get("transition"), it.get("secs"))
        if no_window:
            raise ValueError(
                f"item {i + 1} asks for {', '.join(no_window)} across a cut, which has no "
                f"overlap for them to act on. Give it a fade, dissolve or wipe with a "
                f"duration, or remove them.")


def _duck_fragment(effects_json):
    """The sidechaincompress fragment for the transition OUT of this item, or
    None. Read off the same item that carries `transition` and `secs`, for the
    same reason layer is."""
    if not effects_json:
        return None
    return effects.parse_effects(effects_json).get("duck") or None


def _duck_join(running_a, nxt_a, out_a, offset, secs, comp, i):
    """Push the outgoing mix down under the incoming track across the handover.

    THE TRAP, and the whole reason this sat unwired: `running_a` is the
    ACCUMULATED chain -- every item so far, `offset + secs` long -- while
    `nxt_a` starts at 0 of its own stream. Feeding `nxt_a` straight into
    sidechaincompress therefore ducks the WHOLE SET from its first second,
    because as far as the compressor is concerned the incoming track is playing
    over all of it.

    adelay puts the sidechain copy where the incoming track actually lands, so
    the compressor sees silence until `offset` and only pulls the mix down
    across the handover. asplit is what makes that possible: one copy is
    delayed and used only to drive the compressor, the other is the real
    incoming audio that crossfades in undelayed.
    """
    dk, dkd, dm, dd = f"dk{i}", f"dkd{i}", f"dm{i}", f"dd{i}"
    ms = max(0, int(round(offset * 1000)))
    return [
        f"[{nxt_a}]asplit=2[{dk}][{dm}]",
        f"[{dk}]adelay=delays={ms}:all=1[{dkd}]",
        f"[{running_a}][{dkd}]{comp}[{dd}]",
        f"[{dd}][{dm}]acrossfade=d={secs:.3f}[{out_a}]",
    ]


def master_engaged(items):
    """Whether this SET renders a master loudnorm. docs/TRD-1 T1-20d.

    A SET-LEVEL fact, and that is the whole point of it being a function. It
    used to be decided twice from two different tests: _master_lines engaged the
    master when ANY item suppressed its own loudnorm, while _audio_chain
    suppressed only for the item carrying the curve. So an UNCURVED item in a
    set that has a curve kept its own loudnorm AND passed through the master --
    two dynamic normalisers in series on one signal path, which is the level
    being pulled twice on exactly the item nobody drew a curve on.

    Counting loudnorm per signal path, calling the real functions:

        both curved          per-item=[0, 0]  master=1   worst path = 1
        neither curved       per-item=[1, 1]  master=0   worst path = 1
        one curved, one not  per-item=[0, 1]  master=1   worst path = 2   <-- bug

    One reading, both callers, so the two cannot disagree again.
    """
    return any((it.get("automation") or {}).get("suppress_loudnorm") for it in items)


def item_chains(items):
    """The per-item audio chain for every item in a set, master decision applied.

    ONE wiring point, and that is the reason it exists rather than each caller
    calling _audio_chain in its own loop. The video path and the audio path each
    built their own chains, so the set-level master flag had to be threaded
    correctly in two places -- and a mutation passing master=False at the video
    site alone left every assertion in this file green, because they exercise
    _audio_chain directly. Two renders of one document disagreeing about the mix
    is the exact failure _check_join_effects already exists to prevent; this is
    the same failure one stage earlier. docs/TRD-1 T1-20d.
    """
    master = master_engaged(items)
    return [_audio_chain(it.get("gain_db"), it.get("effects_json"),
                         it.get("automation"), master=master) for it in items]


def _master_lines(items, lines, running):
    """THE MASTER STAGE. docs/TRD-1 8a.

    One loudnorm, after every item and every join, and ONLY when some item had
    its own suppressed for a gain curve -- otherwise a set that draws no curve
    renders exactly as it did before automation existed.

    Its own function so it can be asserted without rendering: a master stage
    that quietly stopped being added is a set losing its level precisely where
    somebody drew one, and "the graph has a loudnorm in it" is not something a
    duration check would ever notice.
    """
    if master_engaged(items):
        lines = lines + [f"[{running}]{effects.loudnorm_filter()}[master]"]
        running = "master"
    return lines, running


def _audio_chain(gain_db, effects_json, auto=None, master=False):
    """Per-item audio filter fragments, comma-joinable, ending with
    loudnorm (on by default -- see effects.py's own docstring: it's the
    unglamorous one that matters most).

    GAIN COMES FROM ONE PLACE AND IS NEVER SUMMED. docs/TRD-1 5.0(b).

    There are two inputs for it and there always were: the item's own gain_db
    column, and a "gain_db" key inside effects_json. This function's docstring
    used to assert that "effects_json never carries its own gain_db from this
    caller" -- which is true of the code that calls it and false of the form the
    user types into, because the set editor exposes the Gain field and the raw
    effects_json textarea side by side. An item with -3 in both rendered at -6
    dB, silently, and nothing anywhere said which one the user meant.

    The rule: the COLUMN wins. effects_json's key is an alias for it, read only
    when the column is zero, and it is stripped before parse_effects sees it so
    the gain stage cannot be emitted twice.

    Resolved rather than refused, deliberately: a refusal here fires at RENDER
    time, on a set somebody already saved, which is the worst moment to discover
    it. The ambiguity is refused at the point of ENTRY instead -- app.py's
    effects_json validation rejects a gain_db key and names the Gain field --
    so no new item can carry both while an old one still renders.

    A duck is not read here and that is not the same as being dropped: it is a
    two-input effect consumed at the JOIN by _duck_join, out of the transition
    window, exactly as layer is by _layer_join. parse_effects already keeps it
    out of "chain" for that reason. An item whose duck reaches NO join -- a cut,
    or the last item in the set -- is refused by _build_render_set_filter and
    mix_audio rather than silently ignored."""
    column = float(gain_db or 0.0)
    cfg, inline = effects_json, 0.0
    if effects_json:
        data = json.loads(effects_json) if isinstance(effects_json, str) else dict(effects_json)
        if isinstance(data, dict) and data.get("gain_db"):
            inline = float(data["gain_db"])
            cfg = {**data, "gain_db": 0.0}   # parse_effects must not emit it too

    frags = []
    resolved = column if column else inline
    if resolved:
        frags.append(effects.gain(resolved))

    # AUTOMATION. `auto` is {"frags": [...], "suppress_loudnorm": bool}, built by
    # automation.item_audio() and carried in the item dict exactly as
    # effects_json is -- mixer stays pure media code and never touches the
    # database or the curve model.
    #
    # suppress_loudnorm is docs/TRD-1 5.0(c) reaching the renderer at last:
    # loudnorm is a DYNAMIC normaliser and parse_effects appends it LAST, so an
    # item with a drawn level curve would have that curve flattened by a filter
    # two stages after it. The item's own loudnorm comes off and the caller adds
    # one at the master instead.
    #
    # `master` is the SET-level answer from master_engaged(), and it is why this
    # takes an argument the item dict cannot supply: an item can only see its own
    # automation, so it could never tell that ANOTHER item's curve had engaged a
    # master loudnorm downstream of it. It kept its own, passed through the
    # master, and got normalised twice. docs/TRD-1 T1-20d.
    auto = auto or {}
    if auto.get("suppress_loudnorm") or master:
        cfg = dict(cfg) if isinstance(cfg, dict) else json.loads(cfg or "{}")
        cfg["loudnorm"] = False
    frags += effects.parse_effects(cfg)["chain"]
    frags += list(auto.get("frags") or [])
    return ",".join(frags)


def _apply_beatmatch(items, ramp=False):
    """Items with beatmatch=1 get out_secs/secs recomputed from their OWN
    beat grid (video_fx.beat_cut_offsets) before anything else runs. Both
    render_set's xfade offset and mix_audio's acrossfade read out_secs/secs
    off this same, now-snapped, item -- so whichever path renders, the cut
    lands in the same place by construction (see video_fx.beat_cut_offsets'
    own docstring: "there is no separate video-only offset for the audio
    side to independently reproduce"). Off by default: an item without
    beatmatch=1, or with no usable beat_grid, passes through untouched.

    beat_cut_offsets snaps around the item's own exit point, not the whole
    grid's last bar -- that point is this item's existing out_secs, or (no
    trim set) the source file's own full duration, probed here. The same
    out_point rule app._beatmatch_plan uses for its preview, so render and
    preview can never disagree about where the cut lands. No source to
    probe and no out_secs already set means there's nothing to snap
    around -- the item passes through untouched, same as no beat_grid."""
    out, pending_in = [], {}
    for idx, it in enumerate(items):
        if it.get("beatmatch"):
            out_point = it.get("out_secs")
            if out_point is None:
                src = it.get("video") or it.get("audio")
                if src:
                    try:
                        out_point = probe(src)["duration"]
                    except Exception:
                        out_point = None
            if out_point is not None:
                out_secs, secs = video_fx.beat_cut_offsets(
                    it.get("beat_grid") or [], it.get("downbeat_offset") or 0,
                    float(it.get("secs") or 0.0), out_point)
                it = dict(it, secs=secs)
                if out_secs is not None:
                    it["out_secs"] = out_secs
                # The tempo ramp is planned HERE, in the one pass set_duration,
                # render_set and mix_audio all run, so the length the editor
                # predicts and the length that renders come from the same
                # numbers. Planning it anywhere else is how the two drift.
                nxt = items[idx + 1] if idx + 1 < len(items) else None
                out_bpm, in_bpm = it.get("bpm"), (nxt or {}).get("bpm")
                exit_at = it.get("out_secs")
                # SNAPPING applies to both paths -- it moves a cut, it does not
                # stretch anything. RAMPING is audio only: render_set has no
                # counterpart to mix_audio's ramp-rendering loop, so planning one
                # there priced a stretch that never happened and pushed every
                # xfade offset off by it. app._beatmatch_plan already refuses to
                # ramp video ("video isn't tempo-stretched"); this is mixer's
                # matching gate, which was missing.
                if ramp and nxt is not None and can_beatmatch(out_bpm, in_bpm) \
                        and exit_at is not None:
                    bar_times, ratios = plan_tempo_ramp(
                        it.get("beat_grid") or [], it.get("downbeat_offset") or 0,
                        exit_at, out_bpm, in_bpm)
                    if ratios:
                        # SEEK-RELATIVE, because apply_tempo_ramp seeks in_secs
                        # first and reads bar_times against that point while
                        # plan_tempo_ramp returns raw-file coordinates. Getting
                        # this wrong is silently wrong by exactly in_secs.
                        in_s = float(it.get("in_secs") or 0.0)
                        it["_ramp"] = {"bar_times": [b - in_s for b in bar_times],
                                        "ratios": ratios}
                # THE IN SIDE. snap_transition has always done both sides and
                # never had a caller, so "snapped to the beat" described only
                # where the outgoing track handed off -- the incoming one still
                # entered wherever its raw in_secs happened to fall, which is
                # the half that makes two grids line up.
                #
                # The next item's in_secs moves, which changes ITS duration --
                # and that is fine, because _item_duration prices in_secs and
                # every path reaches it through this same pass.
                if nxt is not None:
                    nxt_in = nearest_downbeat(nxt.get("beat_grid") or [],
                                               nxt.get("downbeat_offset") or 0,
                                               float(nxt.get("in_secs") or 0.0))
                    if nxt_in is not None:
                        pending_in[idx + 1] = nxt_in
        out.append(it)
    # applied after the walk: rewriting items[idx+1] mid-loop would have the
    # next iteration read a value this one just changed
    for i, in_secs in pending_in.items():
        out[i] = dict(out[i], in_secs=in_secs)
    return out


def ramped_duration(bar_times, ratios):
    """How long apply_tempo_ramp's OUTPUT runs, without rendering it.

    bar_times are SEEK-RELATIVE, the same convention apply_tempo_ramp
    documents: everything before bar_times[0] is copied untouched and each
    segment after it is divided by its own tempo ratio. Everything after
    bar_times[-1] is dropped, which is why this is the whole length and not a
    delta.

    Analytic on purpose. Pre-rendering to measure would mean an ffmpeg call
    inside set_duration, which the editor calls on every page load -- and
    set_duration promises "no ffmpeg call beyond ffprobe". Verified against
    real renders to within mp3 frame padding (~40ms) across faster, slower,
    trimmed and untrimmed cases.
    """
    if not ratios or len(bar_times) != len(ratios) + 1:
        return None
    head = max(0.0, bar_times[0])
    return head + sum((bar_times[i + 1] - bar_times[i]) / r
                      for i, r in enumerate(ratios) if r)


def _check_transition_fits(secs, running_dur):
    """The ONE guard set_duration(), the editor (via app.py) and both render
    paths (_build_render_set_filter, mix_audio) route through: a transition
    cannot outlast the duration accumulated so far, or ffmpeg's xfade/
    acrossfade offset goes negative and the graph is refused. Raised here
    instead of copied at each call site, so a set that predicts a length via
    set_duration() is always one that render_set()/mix_audio() can actually
    produce -- an impossible transition is caught wherever it is first
    computed, not just at render time."""
    if secs > running_dur:
        raise ValueError(f"transition secs={secs} longer than preceding duration={running_dur}")


def _build_render_set_filter(infos, durations, items, w, h, fps):
    """Programmatically build the join filtergraph for n items (works for 2
    or 20 without a hand-written deep chain). Returns (lines, out_v, out_a,
    predicted_duration). No ffmpeg call -- unit-tested directly in demo().

    `durations` are each item's length AFTER in_secs/out_secs trim -- the
    input itself already arrives trimmed (via _trim_input_args), so this is
    just the bookkeeping needed to place transitions correctly.
    """
    n = len(infos)
    _check_join_effects(items)
    lines = []
    # (path, centre_on_the_finished_timeline, transition_span) per branded
    # handover. Collected in the SAME walk that places the transitions, because
    # a mark that computed its own timeline would drift off the cut it is
    # supposed to land on -- which is the entire reason sec 2 anchors to sec 0's
    # numbers instead of inventing its own clock.
    brands = []
    # Built ONCE for the whole set, before any item's line is emitted: an item
    # cannot see another item's curve, and that is exactly what decides whether
    # its own loudnorm comes off. docs/TRD-1 T1-20d.
    chains = item_chains(items)
    for idx, info in enumerate(infos):
        video_extra = _video_fragment(items[idx].get("effects_json"))
        lines.append(_normalize_filter(idx, w, h, fps, video_extra))
        if info["has_audio"]:
            chain = chains[idx]
            vol = f"{chain}," if chain else ""
            lines.append(f"[{idx}:a]{vol}aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[a{idx}n]")
        else:
            lines.append(f"anullsrc=r=48000:cl=stereo:d={durations[idx]:.3f}[a{idx}n]")

    running_v, running_a, running_dur = "v0n", "a0n", durations[0]
    for i in range(n - 1):
        transition = items[i].get("transition", "cut")
        secs = float(items[i].get("secs", 0.0))
        nxt_v, nxt_a = f"v{i + 1}n", f"a{i + 1}n"
        out_v, out_a = f"vj{i}", f"aj{i}"
        blend = _layer_fragment(items[i].get("effects_json"))
        if transition == BLACK:
            fade, hold = _black_plan(items[i])
            # the fade-out lives inside the accumulated chain, so it has to fit
            # there exactly as a crossfade would
            _check_transition_fits(fade, running_dur)
            st = max(0.0, running_dur - fade)
            lines += _black_video_lines(running_v, nxt_v, out_v, st, fade, hold, w, h, fps, i)
            lines += _black_audio_lines(running_a, nxt_a, out_a, st, fade, hold, i)
            # the middle of the black, where a mark has the screen to itself
            _brand_at(brands, items[i], running_dur + hold / 2.0, hold or fade * 2)
            running_dur += _advance(items[i], durations[i + 1])
        elif transition == "cut" or secs <= 0:
            # a join effect on a cut was already refused by _check_join_effects
            lines.append(f"[{running_v}][{nxt_v}]concat=n=2:v=1:a=0[{out_v}]")
            lines.append(f"[{running_a}][{nxt_a}]concat=n=2:v=0:a=1[{out_a}]")
            _brand_at(brands, items[i], running_dur, 0.0)   # a cut has no span
            running_dur += _advance(items[i], durations[i + 1])
        else:
            _check_transition_fits(secs, running_dur)
            offset = running_dur - secs
            if blend:
                # layer REPLACES the xfade -- the two are alternative ways of
                # crossing the same window, and running them both would fade
                # the footage the blend is made of.
                lines += _layer_join(running_v, nxt_v, out_v, offset, secs, blend, i)
            else:
                xf = _XFADE_NAMES.get(transition, "fade")
                lines.append(f"[{running_v}][{nxt_v}]xfade=transition={xf}:duration={secs:.3f}:offset={offset:.3f}[{out_v}]")
            # audio crosses the same window either way: layer is video-only
            comp = _duck_fragment(items[i].get("effects_json"))
            if comp:
                lines += _duck_join(running_a, nxt_a, out_a, offset, secs, comp, i)
            else:
                lines.append(f"[{running_a}][{nxt_a}]acrossfade=d={secs:.3f}[{out_a}]")
            _brand_at(brands, items[i], running_dur - secs / 2.0, secs)
            running_dur += _advance(items[i], durations[i + 1])
        running_v, running_a = out_v, out_a
    return lines, running_v, running_a, running_dur, brands


def render_set(items, out_path, progress=None):
    progress = progress or _NOOP
    if not items:
        raise ValueError("items is empty")
    items = _apply_beatmatch(items)
    progress(f"probing {len(items)} items")
    infos = [probe(it["video"]) for it in items]
    if any(not i["has_video"] for i in infos):
        raise RuntimeError("one or more items have no video stream")
    durations = [_item_duration(info, it) for info, it in zip(infos, items)]

    # Items may differ in resolution/fps (finished videos from different
    # songs) -- normalize every input to the first item's geometry/fps with
    # scale+pad+fps before joining. Lazy default: revisit if a mismatched
    # hero clip should drive dimensions instead.
    w, h, fps = infos[0]["width"], infos[0]["height"], infos[0]["fps"] or 30
    lines, out_v, out_a, predicted_dur, brands = _build_render_set_filter(
        infos, durations, items, w, h, fps)

    inputs = []
    for it in items:
        inputs += _trim_input_args(it) + ["-i", it["video"]]

    # Branding stills, chained onto the FINISHED video. Each is a looped image
    # input bounded by -t: without the loop it is one frame at t=0 and the
    # overlay only ever shows at t=0, and without the -t it is an infinite
    # input that never lets the encode finish.
    for k, (path, centre, span) in enumerate(brands):
        if not os.path.isfile(path):
            raise ValueError(f"branding image not found: {path}")
        idx = len(items) + k
        # a second longer than the video, so overlay's shortest=1 always ends
        # on the video rather than on the still
        inputs += ["-loop", "1", "-t", f"{predicted_dur + 1.0:.3f}", "-i", path]
        st, en = _brand_window(centre, span, predicted_dur)
        nxt = f"vbr{k}"
        lines += _brand_lines(idx, out_v, nxt, path, st, en, w, h)
        out_v = nxt

    tmp = _atomic_out(out_path)
    try:
        args = inputs + ["-filter_complex", ";\n".join(lines),
                          "-map", f"[{out_v}]", "-map", f"[{out_a}]",
                          "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                          "-c:a", "aac", "-b:a", "192k", tmp]
        progress("rendering set")
        _run_ffmpeg(args, progress, total_duration=predicted_dur, stage="render_set")
        os.replace(tmp, out_path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    progress("done")
    return out_path


def mix_audio(items, out_path, progress=None):
    """Crossfaded audio mix of a playlist: [{audio, transition, secs}] -> mp3.

    The audio-only half of a set render. Same overlap arithmetic as
    render_set, so a playlist mixed with and without video runs to the same
    length and cuts in the same places -- acrossfade here is exactly what
    render_set pairs with xfade there.
    """
    progress = progress or _NOOP
    if not items:
        raise ValueError("items is empty")
    items = _apply_beatmatch(items, ramp=True)
    # Render the tempo ramps FIRST, so what follows sees ordinary audio files.
    # _item_duration already predicted these lengths analytically; rendering
    # them here is what makes that prediction true rather than a claim. Once an
    # item is ramped its trim is spent (apply_tempo_ramp seeks in_secs and drops
    # everything past the exit point), so the trim args must not be applied a
    # second time.
    ramp_dir = None
    ramped = []
    for i, it in enumerate(items):
        if not it.get("_ramp"):
            ramped.append(it)
            continue
        if ramp_dir is None:
            ramp_dir = tempfile.mkdtemp(prefix="setramp_")
        dst = os.path.join(ramp_dir, f"ramp{i}.mp3")
        progress(f"tempo ramp for item {i + 1}")
        apply_tempo_ramp(it["audio"], dst, float(it.get("in_secs") or 0.0),
                          it["_ramp"]["bar_times"], it["_ramp"]["ratios"], progress)
        nit = dict(it, audio=dst)
        nit.pop("_ramp", None)
        nit["in_secs"] = None
        nit["out_secs"] = None
        ramped.append(nit)
    items = ramped
    progress(f"probing {len(items)} tracks")
    infos = [probe(it["audio"]) for it in items]
    missing = [it["audio"] for it, i in zip(items, infos) if not i["has_audio"]]
    if missing:
        raise RuntimeError(f"no audio stream in: {missing[0]}")
    durations = [_item_duration(info, it) for info, it in zip(infos, items)]

    # the same refusal render_set makes, on the same items: an audio-only set
    # that silently dropped a duck the video render honours would be two
    # renders of one document disagreeing about the mix
    _check_join_effects(items)
    lines = []
    # The SAME builder the video path uses, so the two renders of one document
    # cannot disagree about the mix.
    chains = item_chains(items)
    for i, it in enumerate(items):
        chain = chains[i]
        vol = f"{chain}," if chain else ""
        lines.append(f"[{i}:a]{vol}aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}n]")
    running, running_dur = "a0n", durations[0]
    for i in range(len(items) - 1):
        it = items[i]
        secs = 0.0 if it.get("transition") == "cut" else float(it.get("secs", 0.0))
        out = f"am{i}"
        if it.get("transition") == BLACK:
            fade, hold = _black_plan(it)
            _check_transition_fits(fade, running_dur)
            lines += _black_audio_lines(running, f"a{i + 1}n", out,
                                         max(0.0, running_dur - fade), fade, hold, i)
        elif secs <= 0:
            lines.append(f"[{running}][a{i + 1}n]concat=n=2:v=0:a=1[{out}]")
        else:
            _check_transition_fits(secs, running_dur)
            comp = _duck_fragment(it.get("effects_json"))
            if comp:
                lines += _duck_join(running, f"a{i + 1}n", out,
                                     running_dur - secs, secs, comp, i)
            else:
                lines.append(f"[{running}][a{i + 1}n]acrossfade=d={secs:.3f}[{out}]")
        running_dur += _advance(it, durations[i + 1])
        running = out

    lines, running = _master_lines(items, lines, running)

    tmp = _atomic_out(out_path)
    inputs = []
    for it in items:
        inputs += _trim_input_args(it) + ["-i", it["audio"]]
    try:
        args = inputs + ["-filter_complex", ";\n".join(lines), "-map", f"[{running}]",
                          "-c:a", "libmp3lame", "-b:a", "320k", tmp]
        progress("mixing audio")
        _run_ffmpeg(args, progress, total_duration=running_dur, stage="mix_audio")
        os.replace(tmp, out_path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    progress("done")
    return out_path


# How far a rendered set may sit from what set_duration() predicted before it is
# a defect rather than container rounding. ONE constant: docs/TRD-1 T1-7 checks
# it at build time and docs/TRD-3 T3-11 checks it on the artefact, and the two
# documents originally each carried the literal 0.05 -- two copies of a number
# free to drift into a check that passes while its twin fails. qc.py imports
# this rather than restating it.
SET_DURATION_TOLERANCE = 0.05


def set_duration(items, key="video"):
    """Predicted set length: item durations (after in_secs/out_secs trim and
    any beatmatch snap) minus each transition's overlap, walked the same way
    _build_render_set_filter/mix_audio walk it, through the same
    _check_transition_fits guard -- so a length shown here is always one
    render_set()/mix_audio() can actually produce, and an impossible
    transition raises HERE, at prediction time, not only when a render is
    already underway. No ffmpeg call beyond ffprobe. key='audio' prices the
    mp3 mix, key='video' the rendered set."""
    if not items:
        return 0.0
    # ramp only when pricing the AUDIO mix -- mix_audio renders ramps, render_set
    # does not, so pricing one for video would predict a length nothing produces
    items = _apply_beatmatch(items, ramp=(key == "audio"))
    durations = [_item_duration(probe(it[key]), it) for it in items]
    running_dur = durations[0]
    for i in range(len(items) - 1):
        it = items[i]
        if it.get("transition") == BLACK:
            # only the fade-out has to fit; the hold is added, not overlapped
            _check_transition_fits(_black_plan(it)[0], running_dur)
        else:
            secs = 0.0 if it.get("transition") == "cut" else float(it.get("secs", 0.0))
            if secs > 0:
                _check_transition_fits(secs, running_dur)
        running_dur += _advance(it, durations[i + 1])
    return max(0.0, running_dur)


# --------------------------------------------------------- beat matching --
# SETS_MIXING_PLAN.md phase 3. Everything down to apply_tempo_ramp is pure
# arithmetic / string generation -- no ffmpeg call, no file on disk -- so
# demo() proves it correct without rendering anything. Only apply_tempo_ramp
# itself touches ffmpeg, and it does so through the same _atomic_out/
# _run_ffmpeg plumbing as edit_audio above.

# A DJ pitch fader tops out around +/-8% on most hardware and can be pushed
# to +/-16% before a track audibly drags or gallops -- Mixxx's Sync Lock
# treats that range as "still a transition, not damage". 1.16 sits at the
# top of it: a starting point for SETS_MIXING_PLAN.md's open question 3
# ("pick one after listening, not before"), not a measured value -- one
# constant to move once someone has listened to a few.
MAX_TEMPO_STRETCH = 1.16

# How many bars of the outgoing track ease toward the incoming tempo. 4 bars
# is a short, common mixing point -- long enough that no single step is a
# jarring jump, short enough to fit inside an ordinary crossfade.
RAMP_BARS = 4


def nearest_downbeat(beat_grid, downbeat_offset, t):
    """Nearest downbeat (every 4th beat starting at downbeat_offset) to time
    t, in seconds. A song with no beat grid yet (never analysed) or a
    corrupt offset both degrade to "no snap" -- t itself -- so an unanalysed
    song still mixes, just not beat-matched. Delegates to beatmatch.py's
    identical maths (beatmatch.snap_to_downbeat) -- this module used to carry
    its own copy; kept as a thin wrapper so every existing caller here keeps
    its argument order (beat_grid, offset, t) rather than beatmatch's own
    (t, beat_grid, offset)."""
    return beatmatch.snap_to_downbeat(t, beat_grid, downbeat_offset)


def snap_transition(out_beat_grid, out_downbeat_offset, out_point,
                     in_beat_grid, in_downbeat_offset, in_point=0.0):
    """Snap a transition to the nearest downbeat on BOTH sides: where the
    outgoing track hands off, and where the incoming one picks up. This
    alone needs no time-stretching and is most of what "beat matched" means
    to a listener -- implemented and usable on its own, before any tempo
    ramp. Returns (snapped_out_point, snapped_in_point)."""
    return (nearest_downbeat(out_beat_grid, out_downbeat_offset, out_point),
            nearest_downbeat(in_beat_grid, in_downbeat_offset, in_point))


def tempo_ratio(out_bpm, in_bpm):
    """Ratio to stretch the OUTGOING track's tempo onto the incoming one's.
    >1 speeds it up (shorter output), <1 slows it down (longer output) --
    measured on this box: a 4s clip at tempo=1.2 renders 3.33s, at
    tempo=0.8 renders 5.0s. 1.0 (no-op) if either bpm is unknown."""
    if not out_bpm or not in_bpm:
        return 1.0
    return in_bpm / out_bpm


def can_beatmatch(out_bpm, in_bpm):
    """False when the stretch needed exceeds MAX_TEMPO_STRETCH either
    direction -- e.g. 128->174 BPM is a ratio of 1.36. That is not a
    transition, it is damage; the caller falls back to a plain crossfade
    instead of stretching."""
    if not out_bpm or not in_bpm or out_bpm <= 0 or in_bpm <= 0:
        return False
    ratio = tempo_ratio(out_bpm, in_bpm)
    return ratio <= MAX_TEMPO_STRETCH and (1.0 / ratio) <= MAX_TEMPO_STRETCH


def plan_tempo_ramp(beat_grid, downbeat_offset, out_point, out_bpm, in_bpm, n_bars=RAMP_BARS):
    """(bar_times, ratios) for a stepped tempo ramp across the last n_bars
    before out_point, using the outgoing track's OWN downbeat timestamps --
    not an assumed constant bar length. bar_times has len(ratios)+1 entries;
    ratios[i] is the rubberband tempo for the segment [bar_times[i],
    bar_times[i+1]], easing from 1.0 (untouched) toward the full
    tempo_ratio -- a human riding a pitch fader across a phrase rather than
    snapping it, the way pyCrossfade's gradual BPM shift across downbeats
    works. Returns ([], []) if beatmatching is refused (see can_beatmatch)
    or there are fewer than 2 downbeats before out_point to ramp across."""
    if not can_beatmatch(out_bpm, in_bpm):
        return [], []
    bars = [b for b in (beat_grid or [])[downbeat_offset::4] if b <= out_point]
    if len(bars) < 2:
        return [], []
    bar_times = bars[-(n_bars + 1):]
    target = tempo_ratio(out_bpm, in_bpm)
    steps = len(bar_times) - 1
    ratios = [target] if steps == 1 else \
        [round(1.0 + (target - 1.0) * i / (steps - 1), 6) for i in range(steps)]
    return bar_times, ratios


def apply_tempo_ramp(audio_path, out_path, in_secs, bar_times, ratios, progress=None):
    """Rewrite audio_path so everything before bar_times[0] is untouched and
    each segment after it is rubberband-stretched by its own ratio (see
    plan_tempo_ramp) -- the stepped approximation of a tempo ramp, since
    rubberband exposes tempo as one constant per filter instance, not a
    curve over time. in_secs seeks the input first (matches _trim_input_args'
    -ss/-to convention elsewhere in this module); bar_times are relative to
    that seek point, not the raw file. Everything after bar_times[-1] is
    dropped -- callers pass the transition's own snapped exit point as the
    last entry, so there is nothing musically meaningful beyond it anyway.
    """
    if len(bar_times) != len(ratios) + 1:
        raise ValueError("bar_times must have one more entry than ratios")
    progress = progress or _NOOP
    total = bar_times[-1] - in_secs

    lines, seg_labels = [], []
    if bar_times[0] > 0:
        lines.append(f"[0:a]atrim=0:{bar_times[0]:.3f},asetpts=PTS-STARTPTS[head]")
        seg_labels.append("[head]")
    for i, ratio in enumerate(ratios):
        start, end = bar_times[i], bar_times[i + 1]
        seg = f"rt{i}"
        lines.append(f"[0:a]atrim={start:.3f}:{end:.3f},asetpts=PTS-STARTPTS,"
                     f"rubberband=tempo={ratio:.4f}[{seg}]")
        seg_labels.append(f"[{seg}]")
    lines.append(f"{''.join(seg_labels)}concat=n={len(seg_labels)}:v=0:a=1[out]")

    args = ["-ss", str(in_secs), "-i", audio_path, "-filter_complex", ";\n".join(lines),
            "-map", "[out]",
            "-c:a", "libmp3lame" if os.path.splitext(out_path)[1].lower() == ".mp3" else "aac",
            "-b:a", "192k"]
    tmp = _atomic_out(out_path)
    try:
        progress("tempo ramp")
        _run_ffmpeg(args + [tmp], progress, total_duration=total, stage="tempo_ramp")
        os.replace(tmp, out_path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    progress("done")
    return out_path


def camelot_neighbors(code):
    """Camelot codes compatible with `code` for a harmonic mix. Delegates to
    beatmatch.camelot_neighbours (identical maths, this module used to carry
    its own copy) -- kept as a thin US-spelling wrapper since every existing
    caller here (suggest_running_order, app.py) already calls it this way."""
    return beatmatch.camelot_neighbours(code)


def suggest_running_order(songs):
    """Suggested running order by Camelot adjacency. Delegates to
    beatmatch.suggest_order (identical maths, this module used to carry its
    own copy) -- a SUGGESTION the caller may apply (e.g. by posting the
    resulting order to the existing reorder endpoint), never an automatic
    reorder (SETS_MIXING_PLAN.md phase 3)."""
    return beatmatch.suggest_order(songs)


def demo():
    # T1-13 / T1-14 are pure arithmetic and must not wait on ffmpeg.
    _tone = [0.0] * 4096
    _tone[7] = 0.91
    _tone[9] = -0.73
    _env = peaks(_tone, z=0)
    assert 1 <= len(_env) <= PEAKS_MAX_POINTS, len(_env)
    assert max(p[1] for p in _env) == 0.91 and min(p[0] for p in _env) == -0.73
    assert peaks([], z=0) == []
    tmpdir = tempfile.mkdtemp(prefix="mixer_demo_")
    try:
        clip_a = os.path.join(tmpdir, "clip a.mp4")   # space in path, deliberately
        clip_b = os.path.join(tmpdir, "clip b.mp4")
        clip_c = os.path.join(tmpdir, "clip c.mp4")    # different resolution
        for path, size in ((clip_a, "320x240"), (clip_b, "320x240"), (clip_c, "640x360")):
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                                 "-i", f"color=c=red:s={size}:d=1", "-r", "16",
                                 "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
                                capture_output=True, text=True)
            assert r.returncode == 0, r.stderr

        mp3 = os.path.join(tmpdir, "song.mp3")
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "4",
                             "-i", "sine=frequency=440", "-c:a", "libmp3lame", mp3],
                            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

        logs = []
        progress = lambda m: logs.append(m)

        # ---- waveform_png: a real PNG, and a DIFFERENT one for different audio.
        # Size alone proves nothing -- ffmpeg writing a valid empty-looking
        # picture would pass that -- so a silent track and a tone must not
        # produce the same bytes. That is the check that fails if the filter
        # ever stops being fed the audio.
        wf = os.path.join(tmpdir, "wave.png")
        waveform_png(mp3, wf, progress)
        head = open(wf, "rb").read(8)
        assert head == b"\x89PNG\r\n\x1a\n", head
        assert os.path.getsize(wf) > 200, os.path.getsize(wf)

        silent = os.path.join(tmpdir, "silence.mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "4",
                        "-i", "anullsrc", "-c:a", "libmp3lame", silent], check=True)
        wf2 = os.path.join(tmpdir, "wave2.png")
        waveform_png(silent, wf2, progress)
        assert open(wf, "rb").read() != open(wf2, "rb").read(), \
            "silence and a tone drew the same waveform -- the filter is not seeing the audio"

        # a failure leaves NO half-written file behind for the next reader to
        # serve as a broken image
        try:
            waveform_png(os.path.join(tmpdir, "nope.mp3"), os.path.join(tmpdir, "bad.png"),
                         progress)
            raise AssertionError("a missing input did not raise")
        except RuntimeError:
            pass
        assert not os.path.exists(os.path.join(tmpdir, "bad.png"))

        # assemble_song: 3x 1s same-res clips, 4s audio -> video-limited ~3s
        out1 = os.path.join(tmpdir, "song1.mp4")
        assemble_song([clip_a, clip_b, clip_a], mp3, out1, progress=progress)
        info1 = probe(out1)
        assert 2.5 <= info1["duration"] <= 3.5, info1
        assert info1["has_audio"] and info1["has_video"], info1
        assert subprocess.run(["ffprobe", "-v", "error", out1], capture_output=True).returncode == 0

        # crossfade path: shorter than the hard-cut version
        out2 = os.path.join(tmpdir, "song2.mp4")
        assemble_song([clip_a, clip_b, clip_a], mp3, out2, fade=0.25)
        info2 = probe(out2)
        assert info2["duration"] < info1["duration"], (info2, info1)

        # render_set: mixed resolutions, 2 items (also exercises silent-clip
        # audio synthesis, since clip_a/clip_c have no audio stream)
        items2 = [{"video": clip_a, "transition": "fade", "secs": 0.3},
                  {"video": clip_c, "transition": "cut", "secs": 0.0}]
        out_set2 = os.path.join(tmpdir, "set2.mp4")
        render_set(items2, out_set2)
        pred2, actual2 = set_duration(items2), probe(out_set2)["duration"]
        assert abs(actual2 - pred2) <= 0.3, (actual2, pred2)

        # render_set: 5 items, every transition type
        items5 = [
            {"video": clip_a, "transition": "fade", "secs": 0.2},
            {"video": clip_b, "transition": "dissolve", "secs": 0.2},
            {"video": clip_c, "transition": "wipe", "secs": 0.2},
            {"video": clip_a, "transition": "cut", "secs": 0.0},
            {"video": clip_b, "transition": "cut", "secs": 0.0},
        ]
        out_set5 = os.path.join(tmpdir, "set5.mp4")
        render_set(items5, out_set5)
        pred5, actual5 = set_duration(items5), probe(out_set5)["duration"]
        assert abs(actual5 - pred5) <= 0.3, (actual5, pred5)

        # all-cut -> duration == sum of inputs
        items_cut = [{"video": clip_a, "transition": "cut", "secs": 0.0},
                     {"video": clip_b, "transition": "cut", "secs": 0.0}]
        out_cut = os.path.join(tmpdir, "set_cut.mp4")
        render_set(items_cut, out_cut)
        expected_cut = probe(clip_a)["duration"] + probe(clip_b)["duration"]
        actual_cut = probe(out_cut)["duration"]
        assert abs(actual_cut - expected_cut) <= 0.3, (actual_cut, expected_cut)

        # _item_duration: pure trim arithmetic, no ffmpeg call
        assert _item_duration({"duration": 10.0}, {}) == 10.0
        assert _item_duration({"duration": 10.0}, {"in_secs": 2.0, "out_secs": 6.0}) == 4.0
        assert _item_duration({"duration": 10.0}, {"in_secs": 2.0}) == 8.0
        # an out_secs past the file's own length clamps rather than lying about it
        assert _item_duration({"duration": 10.0}, {"in_secs": 1.0, "out_secs": 99.0}) == 9.0

        # render_set: in/out trim shortens the item, and set_duration predicts it.
        # out1 (assembled above) has real audio+video and runs ~2.5-3.5s.
        items_trim = [{"video": out1, "transition": "cut", "secs": 0.0, "in_secs": 0.5, "out_secs": 2.0},
                      {"video": clip_a, "transition": "cut", "secs": 0.0}]
        out_trim = os.path.join(tmpdir, "set_trim.mp4")
        render_set(items_trim, out_trim)
        pred_trim, actual_trim = set_duration(items_trim), probe(out_trim)["duration"]
        assert abs(actual_trim - pred_trim) <= 0.3, (actual_trim, pred_trim)
        assert actual_trim < probe(out1)["duration"] + probe(clip_a)["duration"] - 0.3, \
            "in/out trim did not shorten the render"

        # render_set: per-item gain_db must not break the filtergraph
        items_gain = [{"video": out1, "transition": "cut", "secs": 0.0, "gain_db": -6.0},
                      {"video": clip_a, "transition": "cut", "secs": 0.0}]
        out_gain = os.path.join(tmpdir, "set_gain.mp4")
        render_set(items_gain, out_gain)
        assert probe(out_gain)["has_audio"], "gain_db item lost its audio stream"

        # edit_audio: trim/gain/fade
        out_audio = os.path.join(tmpdir, "trimmed.mp3")
        edit_audio(mp3, out_audio, trim_start=0.5, trim_end=2.5, gain_db=-3.0, fade_in=0.2, fade_out=0.2)
        adur = probe(out_audio)["duration"]
        assert 1.7 <= adur <= 2.3, adur

        # bad input: RuntimeError with ffmpeg stderr, out_path untouched
        bad_out = os.path.join(tmpdir, "should_not_exist.mp4")
        try:
            assemble_song([os.path.join(tmpdir, "nope.mp4")], mp3, bad_out)
            raise AssertionError("expected RuntimeError for missing clip")
        except RuntimeError as e:
            assert "nope.mp4" in str(e) or "No such file" in str(e), str(e)
        assert not os.path.exists(bad_out)

        # generated filtergraph is deterministic and unit-testable on its own
        lines, label, _ = _crossfade_chain(3, [1.0, 1.0, 1.0], 0.25)
        assert len(lines) == 2
        assert "xfade=transition=fade:duration=0.250:offset=0.750" in lines[0]
        assert label == "vx2"

        # the assembled song is as long as the TRACK, not the clip total. Clips
        # are quantised, so three 1s clips over a 2.5s song overrun by 0.5s --
        # the same shape as 50 clips overrunning Back Alley Pussy by 3s.
        short_mp3 = os.path.join(tmpdir, "short.mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=2.5", "-c:a", "libmp3lame", short_mp3],
                       capture_output=True, check=True)
        out_quant = os.path.join(tmpdir, "quantised.mp4")
        assemble_song([clip_a, clip_b, clip_a], short_mp3, out_quant)
        iq = probe(out_quant)
        assert abs(iq["duration"] - probe(short_mp3)["duration"]) <= 0.2, \
            f"assembled to {iq['duration']:.2f}s, track is {probe(short_mp3)['duration']:.2f}s"
        assert iq["duration"] < 2.9, f"clip overrun survived: {iq['duration']:.2f}s"

        # mix_audio: crossfaded mp3 set, same overlap arithmetic as render_set
        mp3_b = os.path.join(tmpdir, "second track.mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=330:duration=3", "-c:a", "libmp3lame", mp3_b],
                       capture_output=True, check=True)
        mix_items = [{"audio": mp3, "transition": "fade", "secs": 0.5},
                     {"audio": mp3_b, "transition": "fade", "secs": 0.5}]
        out_mix = os.path.join(tmpdir, "set mix.mp3")
        mix_audio(mix_items, out_mix)
        predicted_mix = set_duration(mix_items, key="audio")
        actual_mix = probe(out_mix)["duration"]
        assert abs(actual_mix - predicted_mix) <= 0.35, (actual_mix, predicted_mix)
        # the overlap is real: a crossfaded pair is shorter than the two tracks
        assert actual_mix < probe(mp3)["duration"] + probe(mp3_b)["duration"] - 0.2

        # mix_audio: in/out trim shortens an item, same as render_set. mp3 is 4s;
        # trimmed to [1.0, 3.0] it contributes 2s instead of 4s.
        mix_trim_items = [{"audio": mp3, "transition": "cut", "secs": 0.0,
                            "in_secs": 1.0, "out_secs": 3.0},
                           {"audio": mp3_b, "transition": "cut", "secs": 0.0}]
        out_mix_trim = os.path.join(tmpdir, "set mix trim.mp3")
        mix_audio(mix_trim_items, out_mix_trim)
        pred_mix_trim = set_duration(mix_trim_items, key="audio")
        actual_mix_trim = probe(out_mix_trim)["duration"]
        assert abs(actual_mix_trim - pred_mix_trim) <= 0.3, (actual_mix_trim, pred_mix_trim)
        assert actual_mix_trim < probe(mp3)["duration"] + probe(mp3_b)["duration"] - 1.5, \
            "in/out trim did not shorten the mix"

        # mix_audio: per-item gain_db must not break the filtergraph
        mix_gain_items = [{"audio": mp3, "transition": "cut", "secs": 0.0, "gain_db": -6.0},
                           {"audio": mp3_b, "transition": "cut", "secs": 0.0}]
        out_mix_gain = os.path.join(tmpdir, "set mix gain.mp3")
        mix_audio(mix_gain_items, out_mix_gain)
        assert probe(out_mix_gain)["has_audio"]

        # a file with no audio stream is refused by name, not by ffmpeg later
        try:
            mix_audio([{"audio": clip_a, "transition": "cut", "secs": 0}], out_mix)
            raise AssertionError("silent video accepted as a mix input")
        except RuntimeError as e:
            assert "clip a.mp4" in str(e), e

        # --- beat matching: pure arithmetic, no ffmpeg (SETS_MIXING_PLAN.md phase 3) ---

        # nearest_downbeat: every 4th beat from the offset is a bar; ties round
        # to the closer one, and an absent/short grid degrades to no snap.
        grid = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
        assert nearest_downbeat(grid, 0, 2.1) == 2.0   # bars at 0,2,4 for offset 0
        assert nearest_downbeat(grid, 0, 3.4) == 4.0
        assert nearest_downbeat(grid, 1, 2.6) == 2.5   # bars at 0.5,2.5 for offset 1
        assert nearest_downbeat([], 0, 7.3) == 7.3, "no grid -- fall back to unsnapped"
        assert nearest_downbeat(grid, 9, 7.3) == 7.3, "bad offset -- fall back to unsnapped"

        out_s, in_s = snap_transition(grid, 0, 2.1, grid, 0, 0.3)
        assert (out_s, in_s) == (2.0, 0.0), (out_s, in_s)

        # tempo_ratio / can_beatmatch: the plan's own worked example, 128->174,
        # is refused; a same-genre gap is not.
        assert abs(tempo_ratio(120.0, 120.0) - 1.0) < 1e-9
        assert abs(tempo_ratio(120.0, 126.0) - 1.05) < 1e-9
        assert can_beatmatch(120.0, 126.0) is True
        assert can_beatmatch(128.0, 174.0) is False, "128->174 must be refused, not stretched"
        assert can_beatmatch(174.0, 128.0) is False, "refusal is symmetric"
        assert can_beatmatch(0, 120.0) is False
        assert can_beatmatch(120.0, None) is False

        # The ramp is AUDIO-ONLY. render_set has no ramp-rendering loop, so
        # planning one for video priced a stretch nothing performed and pushed
        # every xfade offset off by it. Measured before the gate: video set
        # predicted 30.807s, rendered 31.000s.
        _g = [i * 0.5 for i in range(120)]
        _it = [{"beatmatch": 1, "bpm": 120.0, "beat_grid": _g, "downbeat_offset": 0,
                "out_secs": 20.0, "secs": 3.0},
               {"beatmatch": 0, "bpm": 126.0, "beat_grid": _g, "downbeat_offset": 0,
                "out_secs": 15.0, "secs": 0.0}]
        assert _apply_beatmatch([dict(i) for i in _it], ramp=True)[0].get("_ramp"), \
            "audio path stopped planning ramps"
        assert not _apply_beatmatch([dict(i) for i in _it], ramp=False)[0].get("_ramp"), \
            "video path planned a ramp render_set will not apply"
        assert not _apply_beatmatch([dict(i) for i in _it])[0].get("_ramp"), \
            "the default must be the safe one"

        # duck is not in the per-item chain -- it is consumed at the JOIN by
        # _duck_join, so _audio_chain leaves it alone rather than refusing it.
        # Not the same as ignoring it: _check_join_effects refuses a duck no
        # join will read, and the differential further down proves the one that
        # IS read reaches the audio.
        assert "sidechaincompress" not in _audio_chain(0, json.dumps({"duck": 0.5})), \
            "duck leaked into the single-input per-item chain, which has no sidechain"
        assert _duck_fragment(json.dumps({"duck": 0.5})), \
            "the join can no longer see a duck, so it would render as a no-op"

        # GAIN IS ONE VALUE FROM TWO INPUTS, AND IT IS NEVER SUMMED.
        # docs/TRD-1 5.0(b). The set editor shows the Gain field and the raw
        # effects_json box side by side, so -3 in both used to render at -6 dB
        # with nothing saying which the user meant.
        both = _audio_chain(-3.0, json.dumps({"gain_db": -3.0}))
        vols = [f for f in both.split(",") if f.startswith("volume=")]
        assert vols == ["volume=-3.000dB"], f"gain was summed or emitted twice: {vols}"
        # the column wins when both are set...
        assert _audio_chain(-6.0, json.dumps({"gain_db": -3.0})).startswith("volume=-6.000dB")
        # ...and the json is an ALIAS, read only when the column is silent, so an
        # already-saved item that used it still renders at the level it asked for
        assert _audio_chain(0, json.dumps({"gain_db": -3.0})).startswith("volume=-3.000dB")
        # neither set: no gain stage at all, so the ordinary item is untouched
        assert not [f for f in _audio_chain(0, None).split(",") if f.startswith("volume=")]

        # AUTOMATION REACHES THE CHAIN, and takes per-item loudnorm off with it.
        # docs/TRD-1 5.0(c): loudnorm is dynamic and parse_effects appends it
        # LAST, so an item with a drawn level curve would have that curve
        # flattened two stages later. The item is levelled at the master instead.
        auto = {"frags": ["asendcmd=commands='0.000 volume volume -12.000dB'"],
                "suppress_loudnorm": True}
        curved = _audio_chain(0, None, auto)
        assert "asendcmd" in curved, "the automation fragment never reached the chain"
        assert "loudnorm" not in curved, \
            "an item with a gain curve kept its own loudnorm, which flattens the curve"
        # and an item WITHOUT a curve is completely unchanged
        assert "loudnorm" in _audio_chain(0, None), "the ordinary item lost its loudnorm"
        assert "asendcmd" not in _audio_chain(0, None)

        # THE MASTER STAGE, asserted both ways (docs/TRD-1 8a, T1-20a/T1-20b).
        curved_item = {"automation": {"suppress_loudnorm": True}}
        plain_item = {"automation": {"suppress_loudnorm": False}}
        ml, mr = _master_lines([plain_item, curved_item], ["x"], "a3")
        assert mr == "master" and len(ml) == 2 and "loudnorm" in ml[-1], ml
        # exactly ONE loudnorm in the graph: none on the curved item, one here
        assert ml[-1].count("loudnorm") == 1, ml[-1]
        # and a set nobody drew a curve on is untouched -- no master, no change
        nl, nr = _master_lines([plain_item, plain_item], ["x"], "a3")
        assert (nl, nr) == (["x"], "a3"), (nl, nr)

        # TWO LOUDNORMS IN SERIES, counted per SIGNAL PATH. docs/TRD-1 T1-20d.
        #
        # The assertion above says "exactly ONE loudnorm in the graph" and only
        # ever counted the master LINE. It was true of that line and false of the
        # graph: _master_lines engaged the master when ANY item suppressed its
        # own, while _audio_chain suppressed only for the item carrying the
        # curve, so the UNCURVED item in a mixed set kept its loudnorm AND passed
        # through the master. Two dynamic normalisers in series, on precisely the
        # item nobody drew a curve on.
        #
        # Counted end to end rather than asserted per function: the defect lived
        # in the DISAGREEMENT between two functions that each looked right alone,
        # so a per-function check is what missed it for as long as it existed.
        for label, autos, want_master in (
                ("both curved", [{"suppress_loudnorm": True}] * 2, 1),
                ("neither curved", [{"suppress_loudnorm": False}] * 2, 0),
                ("one curved, one not",
                 [{"suppress_loudnorm": True}, {"suppress_loudnorm": False}], 1)):
            its = [{"automation": a} for a in autos]
            # through item_chains, the ONE builder both render paths use -- not
            # _audio_chain directly. Asserting on _audio_chain left the wiring
            # unguarded: a mutation passing master=False at the video call site
            # kept every check in this file green.
            per = [c.count("loudnorm") for c in item_chains(its)]
            mls, _ = _master_lines(its, [], "a0")
            n_master = sum(l.count("loudnorm") for l in mls)
            assert n_master == want_master, (label, n_master, want_master)
            worst = max(p + n_master for p in per)
            assert worst == 1, (
                f"{label}: {worst} loudnorms in series on one signal path "
                f"(per-item={per}, master={n_master}). A set is levelled ONCE.")
        # ...and the widening that looks like the fix is not it: engaging the
        # master for everyone WITHOUT taking the per-item ones off would make
        # "neither curved" 2-in-series, which is worse than the bug on the path
        # that is currently correct. Hence one set-level reading, both callers.
        assert not master_engaged([{"automation": {"suppress_loudnorm": False}}])

        # aecho APPENDS its delay, and _item_duration is otherwise pure trim
        # arithmetic -- the editor was short by exactly the delay, up to 2s.
        _fake = {"duration": 30.0}
        _echo = json.dumps({"echo_out": {"decay": 0.5, "delay": 2000}})
        assert abs(_item_duration(_fake, {"out_secs": 30.0}) - 30.0) < 1e-6
        assert abs(_item_duration(_fake, {"out_secs": 30.0, "effects_json": _echo}) - 32.0) < 1e-6
        # and it must survive the ramp branch's early return
        _ramped = {"_ramp": {"bar_times": [0.0, 2.0], "ratios": [1.0]}, "effects_json": _echo}
        assert abs(_item_duration(_fake, _ramped) - 4.0) < 1e-6, \
            "an echo tail on a ramped item was dropped by the early return"

        # plan_tempo_ramp: refused pair -> nothing to render
        assert plan_tempo_ramp(grid, 0, 4.0, 128.0, 174.0) == ([], [])
        # not enough bars before out_point -> nothing to render
        assert plan_tempo_ramp([0.0], 0, 4.0, 120.0, 126.0) == ([], [])
        # a matchable pair over a long grid: bar_times climbs to out_point,
        # ratios ease from 1.0 toward the full tempo_ratio, same length - 1
        long_grid = [i * 0.5 for i in range(40)]  # bars every 2.0s at offset 0
        bar_times, ratios = plan_tempo_ramp(long_grid, 0, 18.0, 120.0, 126.0, n_bars=4)
        assert len(bar_times) == 5 and len(ratios) == 4, (bar_times, ratios)
        assert bar_times[-1] == 18.0
        assert ratios[0] == 1.0, "ramp must start untouched"
        assert abs(ratios[-1] - tempo_ratio(120.0, 126.0)) < 1e-6, "ramp must end at the full ratio"
        assert ratios == sorted(ratios), "ramp must ease monotonically toward the target"

        # camelot_neighbors: relative major/minor plus a fifth either way, and
        # nothing else -- exactly 3 compatible codes, all distinct from 8A itself
        neighbors = dict(camelot_neighbors("8A"))
        assert set(neighbors) == {"8B", "9A", "7A"}, neighbors
        assert camelot_neighbors("8B")[0] == ("8A", "relative major/minor")
        assert camelot_neighbors("not a key") == []
        assert camelot_neighbors("") == []

        # suggest_running_order: a harmonic chain gets threaded together over an
        # unrelated key; the odd one out falls back to closest tempo
        songs = [
            {"id": 1, "title": "A", "key": "8A", "bpm": 120},
            {"id": 2, "title": "B", "key": "3B", "bpm": 90},   # unrelated to 8A/9A/7A/8B
            {"id": 3, "title": "C", "key": "9A", "bpm": 122},  # a fifth up from 8A
            {"id": 4, "title": "D", "key": "8B", "bpm": 121},  # relative of 8A
        ]
        order = suggest_running_order(songs)
        assert [o["song"]["id"] for o in order[:1]] == [1]
        assert order[0]["reason"] == "starting point"
        assert {o["song"]["id"] for o in order[1:]} == {2, 3, 4}
        # right after A(8A), the greedy pick must be C or D -- both are
        # harmonically compatible with it -- and the reason must say so, not
        # fall back to tempo
        second = order[1]
        assert second["song"]["id"] in (3, 4), second
        assert "relative" in second["reason"] or "fifth" in second["reason"], second
        # B(3B) is compatible with none of A/C/D's neighbourhoods, so it must
        # land by the tempo fallback, wherever the chain puts it
        b_entry = next(o for o in order if o["song"]["id"] == 2)
        assert "tempo" in b_entry["reason"], b_entry
        assert suggest_running_order([]) == []

        # apply_tempo_ramp: real ffmpeg call. A 6s tone, ramp the last 3 of its
        # 3 one-second "bars" from untouched up to tempo=1.5 (33% shorter) --
        # total duration must shrink by roughly that ratio's share of the ramp.
        tone = os.path.join(tmpdir, "tone.mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "6",
                         "-i", "sine=frequency=440", "-c:a", "libmp3lame", tone],
                        capture_output=True, check=True)
        out_ramp = os.path.join(tmpdir, "ramped.mp3")
        # bar_times/ratios as plan_tempo_ramp would hand them: 3 one-second
        # segments starting at t=3 (in_secs=0), easing 1.0 -> 1.2 -> 1.5
        apply_tempo_ramp(tone, out_ramp, 0.0, [3.0, 4.0, 5.0, 6.0], [1.0, 1.2, 1.5], progress=progress)
        ramped_dur = probe(out_ramp)["duration"]
        # head (3s, untouched) + seg1 (1s/1.0=1.0s) + seg2 (1s/1.2=0.833s) +
        # seg3 (1s/1.5=0.667s) = 5.5s, comfortably shorter than the 6s original
        assert 5.2 <= ramped_dur <= 5.8, ramped_dur
        assert ramped_dur < probe(tone)["duration"], "tempo>1 ramp must shorten the tail"

        # in_secs offsets bar_times the same way _trim_input_args seeks -- the
        # seek itself drops a second of head, so this is ramped_dur minus that
        # dropped second, not the same total
        out_ramp_seek = os.path.join(tmpdir, "ramped_seek.mp3")
        apply_tempo_ramp(tone, out_ramp_seek, 1.0, [2.0, 3.0, 4.0, 5.0], [1.0, 1.2, 1.5])
        assert abs(probe(out_ramp_seek)["duration"] - (ramped_dur - 1.0)) < 0.3

        # --- shared transition-fit guard: set_duration and render_set/mix_audio
        # must refuse the SAME impossible transition (SETS_MIXING_PLAN.md defect:
        # a 2.0s trimmed clip cannot host a 5.0s transition; set_duration used to
        # happily report a fictional length instead of raising) ---
        bad_items = [{"video": out1, "in_secs": 0.0, "out_secs": 2.0,
                      "transition": "fade", "secs": 5.0},
                     {"video": clip_a, "transition": "cut", "secs": 0.0}]
        try:
            set_duration(bad_items)
            raise AssertionError("set_duration accepted an impossible transition")
        except ValueError as e:
            assert "longer than preceding duration" in str(e), e
        bad_render_out = os.path.join(tmpdir, "impossible.mp4")
        try:
            render_set(bad_items, bad_render_out)
            raise AssertionError("render_set accepted an impossible transition")
        except ValueError as e:
            assert "longer than preceding duration" in str(e), e
        assert not os.path.exists(bad_render_out)

        bad_mix_items = [{"audio": mp3, "in_secs": 0.0, "out_secs": 1.0,
                          "transition": "fade", "secs": 2.5},
                         {"audio": mp3_b, "transition": "cut", "secs": 0.0}]
        try:
            set_duration(bad_mix_items, key="audio")
            raise AssertionError("set_duration accepted an impossible audio transition")
        except ValueError:
            pass
        try:
            mix_audio(bad_mix_items, os.path.join(tmpdir, "impossible.mp3"))
            raise AssertionError("mix_audio accepted an impossible transition")
        except ValueError:
            pass

        # --- effects.py wired in: an item's effects_json actually reaches the
        # rendered audio, in both render_set and mix_audio, not just effects.py's
        # own isolated demo ---
        eff_items = [{"video": clip_a, "transition": "cut", "secs": 0.0,
                      "effects_json": json.dumps({"eq_kill": {"low_db": -6, "mid_db": 0, "high_db": 2}})},
                     {"video": clip_b, "transition": "cut", "secs": 0.0}]
        out_eff = os.path.join(tmpdir, "set_effects.mp4")
        render_set(eff_items, out_eff)
        assert probe(out_eff)["has_audio"], "effects_json item lost its audio stream"

        eff_mix_items = [{"audio": mp3, "transition": "cut", "secs": 0.0,
                          "effects_json": json.dumps({"echo_out": {"decay": 0.4, "delay": 300}})},
                         {"audio": mp3_b, "transition": "cut", "secs": 0.0}]
        out_eff_mix = os.path.join(tmpdir, "mix_effects.mp3")
        mix_audio(eff_mix_items, out_eff_mix)
        assert probe(out_eff_mix)["has_audio"]

        # malformed effects_json is refused before ffmpeg ever sees the graph.
        # out1 (not clip_a) -- effects only ever apply to an item's own audio
        # track, so a silent clip has nothing to validate against.
        bad_eff_items = [{"video": out1, "transition": "cut", "secs": 0.0,
                          "effects_json": '{"eq_kill": {"low_db": 999}}'},
                         {"video": clip_a, "transition": "cut", "secs": 0.0}]
        try:
            render_set(bad_eff_items, os.path.join(tmpdir, "should_not_exist2.mp4"))
            raise AssertionError("render_set accepted out-of-range effects_json")
        except ValueError:
            pass

        # --- video_fx.py wired in: grade/glitch reach the rendered video. "layer"
        # is deliberately not wired here -- see _video_fragment's own docstring ---
        grade_items = [{"video": clip_a, "transition": "cut", "secs": 0.0,
                        "effects_json": json.dumps({
                            "grade": {"brightness": 0.1, "contrast": 1.2, "saturation": 0.8, "hue": 20},
                            "glitch": {"kind": "rgba", "amount": 4}})},
                       {"video": clip_b, "transition": "cut", "secs": 0.0}]
        out_grade = os.path.join(tmpdir, "set_grade.mp4")
        render_set(grade_items, out_grade)
        info_grade = probe(out_grade)
        assert info_grade["has_video"] and info_grade["duration"] > 0

        # --- layer: a per-TRANSITION blend, wired into the join ---------------
        # Two clips of DIFFERENT colours and a 1s transition, so the overlap can
        # be looked at. Everything else in this demo renders red on red, where a
        # blend and a crossfade are indistinguishable.
        lay_a = os.path.join(tmpdir, "lay_red.mp4")
        lay_b = os.path.join(tmpdir, "lay_green.mp4")
        for path, colour in ((lay_a, "red"), (lay_b, "lime")):
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                                 "-i", f"color=c={colour}:s=320x240:d=2", "-r", "16",
                                 "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
                                capture_output=True, text=True)
            assert r.returncode == 0, r.stderr

        def mean_rgb(path, at):
            """Average colour of one frame, straight out of ffmpeg -- no image
            library, and it is the only thing that can tell these two renders
            apart."""
            r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", path,
                                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                capture_output=True)
            b = r.stdout
            assert b, f"no frame at {at}s of {path}: {r.stderr[-300:]}"
            px = len(b) // 3
            return (sum(b[0::3]) // px, sum(b[1::3]) // px, sum(b[2::3]) // px)

        lay_json = json.dumps({"layer": {"mode": "screen", "opacity": 1.0}})
        layered = [{"video": lay_a, "transition": "fade", "secs": 1.0,
                    "effects_json": lay_json},
                   {"video": lay_b, "transition": "cut", "secs": 0.0}]
        plain = [{"video": lay_a, "transition": "fade", "secs": 1.0},
                 {"video": lay_b, "transition": "cut", "secs": 0.0}]

        out_lay = os.path.join(tmpdir, "set_layer.mp4")
        out_plain = os.path.join(tmpdir, "set_plain.mp4")
        render_set(layered, out_lay)
        render_set(plain, out_plain)

        # Same length either way -- head + secs + tail is exactly what the xfade
        # it replaces produces, which is WHY set_duration needs no special case.
        # It is also why duration is not evidence here.
        dur_lay, dur_plain = probe(out_lay)["duration"], probe(out_plain)["duration"]
        assert abs(dur_lay - dur_plain) <= 0.2, (dur_lay, dur_plain)
        assert abs(dur_lay - set_duration(layered)) <= 0.3, (dur_lay, set_duration(layered))

        # THE DIFFERENTIAL: mid-overlap (2s + 2s with a 1s transition -> the
        # window is 1.0-2.0s), same input, layer on vs off. A screen blend of
        # red and lime is yellow; a crossfade halfway is dim olive. If layer
        # were silently ignored these two frames would be identical.
        lit = mean_rgb(out_lay, 1.5)
        dim = mean_rgb(out_plain, 1.5)
        assert lit[0] - dim[0] > 60 and lit[1] - dim[1] > 60, \
            f"layer changed nothing in the overlap: layered={lit} plain={dim}"
        assert lit[0] > 180 and lit[1] > 180, f"screen blend did not brighten both: {lit}"

        # a blend has no window to work in on a cut, and is refused rather than
        # rendered as a silent no-op
        try:
            render_set([{"video": lay_a, "transition": "cut", "secs": 0.0,
                         "effects_json": lay_json},
                        {"video": lay_b, "transition": "cut", "secs": 0.0}],
                       os.path.join(tmpdir, "should_not_exist3.mp4"))
            raise AssertionError("layer on a cut was accepted")
        except ValueError as e:
            assert "no overlap" in str(e), e

        # and the graph itself: layer REPLACES the xfade, it does not run beside
        # it -- both would fade the footage the blend is made from
        lay_lines, _, _, _, _ = _build_render_set_filter(
            [{"has_audio": False}, {"has_audio": False}], [2.0, 2.0],
            [{"transition": "fade", "secs": 1.0, "effects_json": lay_json},
             {"transition": "cut", "secs": 0.0}], 320, 240, 16)
        joined = "\n".join(lay_lines)
        assert "blend=all_mode=screen" in joined, joined
        assert "xfade" not in joined, f"layer ran alongside the xfade it replaces:\n{joined}"
        assert "acrossfade=d=1.000" in joined, f"layer swallowed the audio transition:\n{joined}"

        # --- fade to black as a TRANSITION KIND ------------------------------
        def mean_db(path, ss, t):
            r = subprocess.run(["ffmpeg", "-v", "info", "-ss", f"{ss:.3f}", "-t", f"{t:.3f}",
                                 "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                                capture_output=True, text=True)
            m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", r.stderr)
            assert m, f"no volumedetect output for {path}: {r.stderr[-400:]}"
            return float(m.group(1))

        # ALBUM_ARC_AND_STAGING_PLAN.md sec 1. The number that matters: a black
        # handover is the only transition that makes a set LONGER, and by
        # exactly the hold -- the fades happen inside the neighbouring items.
        black_items = [{"video": lay_a, "transition": "black", "secs": 1.0, "hold": 2.0},
                       {"video": lay_b, "transition": "cut", "secs": 0.0}]
        cut_items = [{"video": lay_a, "transition": "cut", "secs": 0.0},
                     {"video": lay_b, "transition": "cut", "secs": 0.0}]
        out_black = os.path.join(tmpdir, "set_black.mp4")
        out_cutref = os.path.join(tmpdir, "set_cutref.mp4")
        render_set(black_items, out_black)
        render_set(cut_items, out_cutref)

        # predicted and rendered, on BOTH sides, against the same set rendered
        # as a cut. A prediction that merely agrees with its own render proves
        # nothing -- these two renders have to differ by the hold and no more.
        pred_black, pred_cut = set_duration(black_items), set_duration(cut_items)
        assert abs((pred_black - pred_cut) - 2.0) < 0.01, (pred_black, pred_cut)
        got_black, got_cut = probe(out_black)["duration"], probe(out_cutref)["duration"]
        assert abs((got_black - got_cut) - 2.0) < 0.3, \
            f"a 2s hold did not add 2s to the render: {got_black} vs {got_cut}"
        assert abs(got_black - pred_black) < 0.3, (got_black, pred_black)

        # and the middle really is black -- the hold sits at 2.0-4.0s
        assert max(mean_rgb(out_black, 3.0)) < 24, \
            f"the hold is not black: {mean_rgb(out_black, 3.0)}"
        assert max(mean_rgb(out_cutref, 3.0)) > 40, \
            "the reference render is black there too, so the check proves nothing"

        # mix_audio prices and renders it the same way, or the audio-only and
        # video renders of one document run to different lengths
        black_audio = [{"audio": mp3, "transition": "black", "secs": 1.0, "hold": 2.0},
                       {"audio": mp3_b, "transition": "cut", "secs": 0.0}]
        cut_audio = [{"audio": mp3, "transition": "cut", "secs": 0.0},
                     {"audio": mp3_b, "transition": "cut", "secs": 0.0}]
        out_ba = os.path.join(tmpdir, "mix_black.mp3")
        mix_audio(black_audio, out_ba)
        assert abs(set_duration(black_audio, key="audio")
                   - set_duration(cut_audio, key="audio") - 2.0) < 0.01
        assert abs(probe(out_ba)["duration"] - set_duration(black_audio, key="audio")) < 0.35, \
            (probe(out_ba)["duration"], set_duration(black_audio, key="audio"))
        # the hold is SILENT, not just dark. 4s + 2s hold + 4s, so the silence
        # sits at 4.0-6.0s; sampled inside it, clear of the fade either side.
        assert mean_db(out_ba, 4.6, 1.0) < -60, \
            f"the black hold is not silent: {mean_db(out_ba, 4.6, 1.0)} dB"

        # a hold of zero is still a legal fade-through-black, just with no pause
        nohold = [{"audio": mp3, "transition": "black", "secs": 1.0, "hold": 0.0},
                  {"audio": mp3_b, "transition": "cut", "secs": 0.0}]
        out_nh = os.path.join(tmpdir, "mix_black0.mp3")
        mix_audio(nohold, out_nh)
        assert abs(probe(out_nh)["duration"] - set_duration(cut_audio, key="audio")) < 0.35

        # --- branding overlay on a handover ----------------------------------
        # ALBUM_ARC_AND_STAGING_PLAN.md sec 2. The claim being checked is the
        # one that makes it safe to build before the interstitial card: it
        # changes pixels and changes NO duration.
        mark = os.path.join(tmpdir, "mark.png")
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                             "-i", "color=c=white:s=80x40:d=1", "-frames:v", "1", mark],
                            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

        branded = [{"video": lay_a, "transition": "fade", "secs": 1.0, "brand_path": mark},
                   {"video": lay_b, "transition": "cut", "secs": 0.0}]
        unbranded = [{"video": lay_a, "transition": "fade", "secs": 1.0},
                     {"video": lay_b, "transition": "cut", "secs": 0.0}]
        out_brand = os.path.join(tmpdir, "set_brand.mp4")
        out_nobrand = os.path.join(tmpdir, "set_nobrand.mp4")
        render_set(branded, out_brand)
        render_set(unbranded, out_nobrand)

        # identical length, both against each other and against the prediction
        db_, dn = probe(out_brand)["duration"], probe(out_nobrand)["duration"]
        assert abs(db_ - dn) < 0.05, f"an overlay changed the set length: {db_} vs {dn}"
        assert abs(db_ - set_duration(branded)) < 0.3, (db_, set_duration(branded))

        # ...and a different picture at the handover it is anchored to. 2s + 2s
        # with a 1s fade -> the handover is centred at 1.5s; the mark is white
        # on dark footage, so the frame there gets brighter.
        on, off = mean_rgb(out_brand, 1.5), mean_rgb(out_nobrand, 1.5)
        assert sum(on) > sum(off) + 12, \
            f"the mark never reached the picture: branded={on} plain={off}"
        # and it is GONE well away from the handover, rather than stamped over
        # the whole set
        assert mean_rgb(out_brand, 0.3) == mean_rgb(out_nobrand, 0.3), \
            "the mark is on screen far from the handover it belongs to"

        # a mark on a missing file is refused, not skipped in silence
        try:
            render_set([{"video": lay_a, "transition": "fade", "secs": 1.0,
                         "brand_path": os.path.join(tmpdir, "nope.png")},
                        {"video": lay_b, "transition": "cut", "secs": 0.0}],
                       os.path.join(tmpdir, "should_not_exist5.mp4"))
            raise AssertionError("a missing branding image was accepted")
        except ValueError as e:
            assert "not found" in str(e), e

        # --- a concat-producing join BEFORE a crossfade ----------------------
        # THE ordering that was broken and that nothing here tried. cut, black
        # and layer all end in concat (timebase 1/1000000); fade/dissolve/wipe
        # are xfade, which REFUSES inputs whose timebases differ. Every case
        # above happens to put its crossfades first, so a confident
        # set_duration was followed by ffmpeg refusing the graph outright.
        for kind, extra in (("cut", {}), ("black", {"hold": 1.0}),
                            ("fade", {"effects_json": lay_json})):
            mixed = [{"video": lay_a, "transition": kind, "secs": 1.0, **extra},
                     {"video": lay_b, "transition": "fade", "secs": 1.0},
                     {"video": lay_a, "transition": "cut", "secs": 0.0}]
            out_mixed = os.path.join(tmpdir, f"set_then_xfade_{kind}.mp4")
            render_set(mixed, out_mixed)          # raised before settb=AVTB
            pred, got = set_duration(mixed), probe(out_mixed)["duration"]
            assert abs(got - pred) <= 0.3, (kind, got, pred)

        # --- duck: the outgoing mix pushed under the incoming track ----------
        duck_json = json.dumps({"duck": 1.0})
        ducked = [{"audio": mp3, "transition": "fade", "secs": 1.5,
                   "effects_json": duck_json},
                  {"audio": mp3_b, "transition": "cut", "secs": 0.0}]
        undicked = [{"audio": mp3, "transition": "fade", "secs": 1.5},
                    {"audio": mp3_b, "transition": "cut", "secs": 0.0}]
        out_duck = os.path.join(tmpdir, "mix_duck.mp3")
        out_flat = os.path.join(tmpdir, "mix_flat.mp3")
        mix_audio(ducked, out_duck)
        mix_audio(undicked, out_flat)

        # 4s + 4s with a 1.5s transition -> the handover is 2.5-4.0s
        # THE TRAP, asserted first: running_a is the ACCUMULATED chain and
        # nxt_a starts at 0 of its own stream, so a sidechain fed the incoming
        # track undelayed ducks the ENTIRE mix from its first second. Before the
        # handover the two renders must be indistinguishable.
        early_duck, early_flat = mean_db(out_duck, 0.5, 1.5), mean_db(out_flat, 0.5, 1.5)
        assert abs(early_duck - early_flat) < 0.5, \
            f"duck reached audio before the transition: {early_duck} vs {early_flat} dB"

        # and across the handover it must actually pull the mix down
        mid_duck, mid_flat = mean_db(out_duck, 2.6, 1.3), mean_db(out_flat, 2.6, 1.3)
        assert mid_duck < mid_flat - 1.0, \
            f"duck changed nothing across the handover: {mid_duck} vs {mid_flat} dB"

        # the graph: the sidechain copy is DELAYED onto the running timeline,
        # which is the whole fix -- 4s of item one, 1.5s transition -> 2500ms
        duck_lines, _, _, _, _ = _build_render_set_filter(
            [{"has_audio": True}, {"has_audio": True}], [4.0, 4.0],
            [{"transition": "fade", "secs": 1.5, "effects_json": duck_json},
             {"transition": "cut", "secs": 0.0}], 320, 240, 16)
        joined_d = "\n".join(duck_lines)
        assert "sidechaincompress" in joined_d, joined_d
        assert "adelay=delays=2500:all=1" in joined_d, \
            f"the sidechain was not aligned to the running chain:\n{joined_d}"
        assert "asplit=2" in joined_d, "the incoming track must feed both the sidechain and the mix"

        # a join effect nothing will read is refused, both ways it can happen
        for bad_items, why in (
            ([{"audio": mp3, "transition": "cut", "secs": 0.0, "effects_json": duck_json},
              {"audio": mp3_b, "transition": "cut", "secs": 0.0}], "no overlap"),
            ([{"audio": mp3, "transition": "fade", "secs": 1.0},
              {"audio": mp3_b, "transition": "cut", "secs": 0.0,
               "effects_json": duck_json}], "the last item"),
        ):
            try:
                mix_audio(bad_items, os.path.join(tmpdir, "should_not_exist4.mp3"))
                raise AssertionError(f"a duck with {why} was accepted")
            except ValueError:
                pass

        # --- beatmatch application: an item with beatmatch=1 gets out_secs/secs
        # recomputed from its OWN beat grid (video_fx.beat_cut_offsets). Both
        # render_set's xfade offset and mix_audio's acrossfade read the same
        # resulting numbers off the same item, so a beat-snapped cut moves both
        # together by construction (SETS_MIXING_PLAN.md phase 5) ---
        grid4 = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]  # bars at 0, 2, 4 (offset 0)
        # THE regression: a 2.1s-trimmed item must snap around ITS OWN
        # out_secs (nearest bar 2.0), never the whole grid's last bar (4.0) --
        # turning beatmatch on must never silently discard a user's trim.
        bm_pure = _apply_beatmatch(
            [{"secs": 2.5, "beatmatch": True, "beat_grid": grid4, "downbeat_offset": 0,
              "out_secs": 2.1}])
        assert bm_pure[0]["secs"] == 2.0 and bm_pure[0]["out_secs"] == 2.0, bm_pure
        # trimmed near the track's own end still snaps to ITS nearest bar (4.0)
        bm_near_end = _apply_beatmatch(
            [{"secs": 2.5, "beatmatch": True, "beat_grid": grid4, "downbeat_offset": 0,
              "out_secs": 4.2}])
        assert bm_near_end[0]["secs"] == 2.0 and bm_near_end[0]["out_secs"] == 4.0, bm_near_end
        # no out_secs at all, but a real source file -> probes the file's own
        # full duration as the exit point instead of leaving it a no-op
        bm_probed = _apply_beatmatch(
            [{"secs": 2.5, "beatmatch": True, "beat_grid": grid4, "downbeat_offset": 0,
              "audio": mp3, "out_secs": None}])
        assert bm_probed[0]["out_secs"] == 4.0, bm_probed
        # no out_secs AND no source to probe -> nothing to snap around, no-op
        bm_no_anchor = _apply_beatmatch(
            [{"secs": 3.0, "beatmatch": True, "beat_grid": grid4, "downbeat_offset": 0}])
        assert bm_no_anchor[0] == {"secs": 3.0, "beatmatch": True, "beat_grid": grid4,
                                    "downbeat_offset": 0}, bm_no_anchor
        # no beatmatch flag -> untouched, byte-for-byte
        unmatched = _apply_beatmatch([{"secs": 3.0, "beat_grid": grid4}])
        assert unmatched[0] == {"secs": 3.0, "beat_grid": grid4}

        beat_clip = os.path.join(tmpdir, "beat clip.mp4")
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                             "-i", "color=c=blue:s=320x240:d=4", "-r", "16",
                             "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                             "-shortest", "-c:v", "libx264", "-c:a", "aac",
                             "-pix_fmt", "yuv420p", beat_clip],
                            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

        bm_video_items = [{"video": beat_clip, "transition": "fade", "secs": 2.5,
                           "beatmatch": True, "beat_grid": grid4, "downbeat_offset": 0},
                          {"video": clip_a}]
        out_bm_video = os.path.join(tmpdir, "set_beatmatch.mp4")
        render_set(bm_video_items, out_bm_video)
        pred_bm_video = set_duration(bm_video_items)
        actual = probe(out_bm_video)["duration"]
        assert abs(actual - pred_bm_video) <= 1.2, f"beatmatch video duration drift: pred={pred_bm_video:.3f} actual={actual:.3f}"

        bm_audio_items = [{"audio": beat_clip, "transition": "fade", "secs": 2.5,
                           "beatmatch": True, "beat_grid": grid4, "downbeat_offset": 0},
                          {"audio": mp3}]
        out_bm_audio = os.path.join(tmpdir, "mix_beatmatch.mp3")
        mix_audio(bm_audio_items, out_bm_audio)
        pred_bm_audio = set_duration(bm_audio_items, key="audio")
        actual_audio = probe(out_bm_audio)["duration"]
        assert abs(actual_audio - pred_bm_audio) <= 0.2, f"beatmatch audio duration drift: pred={pred_bm_audio:.3f} actual={actual_audio:.3f}"

        # ---- splice_bridge: the cut-from-the-middle ACE-Step cannot do.
        # A DIFFERENTIAL on the audio itself, not just on the duration: the
        # spliced region has to actually be the bridge. The source is a 440 Hz
        # tone for 4s and the bridge is 1s of 880 Hz, so a mean-volume read over
        # the replaced window differs from the same window of the original only
        # if the splice really landed there. Duration alone would pass even if
        # ffmpeg had concatenated the source with itself.
        bridge = os.path.join(tmpdir, "bridge.mp3")
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "1",
                            "-i", "sine=frequency=880:sample_rate=44100", "-c:a", "libmp3lame",
                            bridge], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        spliced = os.path.join(tmpdir, "spliced.mp3")
        splice_bridge(mp3, bridge, spliced, 1.5, 2.5, progress=progress)
        # head 1.5 + bridge 1.0 + tail 1.5, less 2 * 0.25 of crossfade overlap
        assert abs(probe(spliced)["duration"] - 3.5) <= 0.35, probe(spliced)["duration"]

        def _band_db(path, start, dur, freq):
            """Energy in a narrow band around freq, in a window. NEVER returns a
            default: the first version of this check used aspectralstats, which
            emits nothing without a metadata printer, so both readings came back
            0.0 and the comparison silently passed on no data at all. A
            measurement that cannot fail is not evidence, so a missing reading
            raises here instead of degrading into one."""
            r = subprocess.run(
                ["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(dur), "-i", path,
                 "-af", f"bandpass=f={freq}:width_type=h:w=80,volumedetect", "-f", "null", "-"],
                capture_output=True, text=True)
            m = re.search(r"mean_volume:\s*(-?\d+\.?\d*) dB", r.stderr or "")
            assert m, f"volumedetect reported nothing for {freq} Hz at {start}s"
            return float(m.group(1))

        # Three readings, because two would not distinguish "the bridge landed"
        # from "the whole file was replaced by the bridge".
        assert _band_db(mp3, 1.8, 0.4, 880) < _band_db(mp3, 1.8, 0.4, 440) - 12, \
            "the fixture is not a 440 Hz tone, so the rest of this proves nothing"
        assert _band_db(spliced, 1.8, 0.4, 880) > _band_db(spliced, 1.8, 0.4, 440) + 5, \
            "the 880 Hz bridge is not in the window it was spliced into"
        assert _band_db(spliced, 0.3, 0.4, 440) > _band_db(spliced, 0.3, 0.4, 880) + 12, \
            "the head was overwritten -- the splice replaced more than its span"

        # EDGE SPANS. demo() only ever spliced an interior span (head and tail
        # both 1.5s), so the boundary arithmetic was never run and a review
        # found it broken: a sliver of head shorter than the crossfade was
        # dropped silently and the result came back LONGER than the original.
        # bridge_seconds is what the route asks, so ask it the same way here.
        src_len = probe(mp3)["duration"]
        for a, b, seams in ((0.0, 1.0, 1),               # touches the start: ONE seam
                            (src_len - 1.0, src_len, 1),  # touches the end: ONE seam
                            (1.0, 2.0, 2)):               # interior: two
            want = bridge_seconds(mp3, a, b)
            assert abs(want - ((b - a) + seams * SPLICE_XFADE)) < 1e-6, (a, b, want, seams)
            eb = os.path.join(tmpdir, f"eb_{a:.2f}.mp3")
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t",
                                f"{want:.3f}", "-i", "sine=frequency=880", "-c:a",
                                "libmp3lame", eb], capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
            edged = os.path.join(tmpdir, f"edged_{a:.2f}.mp3")
            splice_bridge(mp3, eb, edged, a, b)
            # THE contract: a bridge sized by bridge_seconds returns the track's
            # own length, at every position. Sizing edge spans as gap + 2*xfade
            # -- which the route did -- came back 0.25s long here.
            assert abs(probe(edged)["duration"] - src_len) <= 0.12, (
                f"span {a:.2f}-{b:.2f} came back {probe(edged)['duration']:.3f}s "
                f"against the original {src_len:.3f}s")

        # A SLIVER outside the span is refused, not silently dropped. Measured
        # before this was fixed: splicing at 0.1s deleted the first 0.1s of the
        # track and returned a file 0.193s LONGER than the original.
        for a, b, why in ((0.1, 1.1, "a head shorter than the crossfade"),
                          (src_len - 1.1, src_len - 0.1, "a tail shorter than the crossfade")):
            try:
                splice_bridge(mp3, bridge, os.path.join(tmpdir, "sliver.mp3"), a, b)
                raise AssertionError(f"splice_bridge silently accepted {why}")
            except ValueError as e:
                assert "crossfade" in str(e), e
        for bad, why in (((5.0, 6.0), "a span past the end of the track"),
                         ((2.0, 1.0), "an end before its start"),
                         ((-1.0, 1.0), "a negative start"),
                         ((0.0, 4.0), "a span covering the whole track")):
            try:
                splice_bridge(mp3, bridge, os.path.join(tmpdir, "no.mp3"), *bad)
                raise AssertionError(f"splice_bridge accepted {why}")
            except ValueError:
                pass

        assert logs, "progress callback never fired"
        print(f"mixer.py OK  assemble={info1['duration']:.2f}s fade={info2['duration']:.2f}s "
              f"set2={actual2:.2f}s set5={actual5:.2f}s cut={actual_cut:.2f}s audio={adur:.2f}s "
              f"ramp={ramped_dur:.2f}s")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    demo()
