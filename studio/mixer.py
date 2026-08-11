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


_XFADE_NAMES = {"fade": "fade", "dissolve": "dissolve", "wipe": "wipeleft"}  # xfade has no generic "wipe"


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
    base = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}")
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
    "layer" (two-input blend) is deliberately not read here -- it needs a
    second labelled video stream from the transition window, a bigger change
    to _build_render_set_filter's xfade-based join than this pass makes;
    video_fx.layer() stays available and tested, just uncalled from here."""
    if not effects_json:
        return None
    raw = json.loads(effects_json) if isinstance(effects_json, str) else effects_json
    video_only = {k: v for k, v in raw.items() if k in _VIDEO_EFFECT_KEYS}
    if not video_only:
        return None
    parsed = video_fx.parse_effects_json(video_only)
    frags = [parsed[k] for k in _VIDEO_EFFECT_KEYS if k in parsed]
    return ",".join(frags) if frags else None


def _audio_chain(gain_db, effects_json):
    """Per-item audio filter fragments, comma-joinable, ending with
    loudnorm (on by default -- see effects.py's own docstring: it's the
    unglamorous one that matters most). gain_db is the item's own existing
    field, applied first and separately from effects_json's -- effects_json
    never carries its own "gain_db" from this caller, so parse_effects's
    internal gain stage stays inert unless a set item's JSON explicitly asks
    for one. duck is validated by parse_effects but never read here: it
    needs a second (sidechain) input this per-item chain doesn't have."""
    frags = []
    gain_db = float(gain_db or 0.0)
    if gain_db:
        frags.append(f"volume={gain_db:.3f}dB")
    frags += effects.parse_effects(effects_json)["chain"]
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
    out = []
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
                # ramp=False for the VIDEO path: render_set has no counterpart
                # to mix_audio's ramp-rendering loop, so planning one there
                # priced a stretch that never happened and pushed every xfade
                # offset off by it. app._beatmatch_plan already refuses to ramp
                # video ("video isn't tempo-stretched"); this is mixer's matching
                # gate, which was missing.
                nxt = items[idx + 1] if idx + 1 < len(items) and ramp else None
                out_bpm, in_bpm = it.get("bpm"), (nxt or {}).get("bpm")
                exit_at = it.get("out_secs")
                if nxt is not None and can_beatmatch(out_bpm, in_bpm) and exit_at is not None:
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
        out.append(it)
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
    lines = []
    for idx, info in enumerate(infos):
        video_extra = _video_fragment(items[idx].get("effects_json"))
        lines.append(_normalize_filter(idx, w, h, fps, video_extra))
        if info["has_audio"]:
            chain = _audio_chain(items[idx].get("gain_db"), items[idx].get("effects_json"))
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
        if transition == "cut" or secs <= 0:
            lines.append(f"[{running_v}][{nxt_v}]concat=n=2:v=1:a=0[{out_v}]")
            lines.append(f"[{running_a}][{nxt_a}]concat=n=2:v=0:a=1[{out_a}]")
            running_dur += durations[i + 1]
        else:
            _check_transition_fits(secs, running_dur)
            offset = running_dur - secs
            xf = _XFADE_NAMES.get(transition, "fade")
            lines.append(f"[{running_v}][{nxt_v}]xfade=transition={xf}:duration={secs:.3f}:offset={offset:.3f}[{out_v}]")
            lines.append(f"[{running_a}][{nxt_a}]acrossfade=d={secs:.3f}[{out_a}]")
            running_dur += durations[i + 1] - secs
        running_v, running_a = out_v, out_a
    return lines, running_v, running_a, running_dur


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
    lines, out_v, out_a, predicted_dur = _build_render_set_filter(infos, durations, items, w, h, fps)

    inputs = []
    for it in items:
        inputs += _trim_input_args(it) + ["-i", it["video"]]

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

    lines = []
    for i, it in enumerate(items):
        chain = _audio_chain(it.get("gain_db"), it.get("effects_json"))
        vol = f"{chain}," if chain else ""
        lines.append(f"[{i}:a]{vol}aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}n]")
    running, running_dur = "a0n", durations[0]
    for i in range(len(items) - 1):
        secs = 0.0 if items[i].get("transition") == "cut" else float(items[i].get("secs", 0.0))
        out = f"am{i}"
        if secs <= 0:
            lines.append(f"[{running}][a{i + 1}n]concat=n=2:v=0:a=1[{out}]")
            running_dur += durations[i + 1]
        else:
            _check_transition_fits(secs, running_dur)
            lines.append(f"[{running}][a{i + 1}n]acrossfade=d={secs:.3f}[{out}]")
            running_dur += durations[i + 1] - secs
        running = out

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
        secs = 0.0 if items[i].get("transition") == "cut" else float(items[i].get("secs", 0.0))
        if secs > 0:
            _check_transition_fits(secs, running_dur)
        running_dur += durations[i + 1] - secs
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
        assert abs(probe(out_bm_video)["duration"] - pred_bm_video) <= 0.3

        bm_audio_items = [{"audio": beat_clip, "transition": "fade", "secs": 2.5,
                           "beatmatch": True, "beat_grid": grid4, "downbeat_offset": 0},
                          {"audio": mp3}]
        out_bm_audio = os.path.join(tmpdir, "mix_beatmatch.mp3")
        mix_audio(bm_audio_items, out_bm_audio)
        pred_bm_audio = set_duration(bm_audio_items, key="audio")
        assert abs(probe(out_bm_audio)["duration"] - pred_bm_audio) <= 0.3

        assert logs, "progress callback never fired"
        print(f"mixer.py OK  assemble={info1['duration']:.2f}s fade={info2['duration']:.2f}s "
              f"set2={actual2:.2f}s set5={actual5:.2f}s cut={actual_cut:.2f}s audio={adur:.2f}s "
              f"ramp={ramped_dur:.2f}s")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    demo()
