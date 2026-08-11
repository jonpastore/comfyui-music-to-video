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
                    "-c:a", "aac", "-b:a", "192k", "-shortest", tmp]
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
                              "-c:a", "aac", "-b:a", "192k", "-shortest", tmp]
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


def _normalize_filter(idx, w, h, fps):
    return (f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}[v{idx}n]")


def _build_render_set_filter(infos, items, w, h, fps):
    """Programmatically build the join filtergraph for n items (works for 2
    or 20 without a hand-written deep chain). Returns (lines, out_v, out_a,
    predicted_duration). No ffmpeg call -- unit-tested directly in demo()."""
    n = len(infos)
    lines = []
    for idx, info in enumerate(infos):
        lines.append(_normalize_filter(idx, w, h, fps))
        if info["has_audio"]:
            lines.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[a{idx}n]")
        else:
            lines.append(f"anullsrc=r=48000:cl=stereo:d={info['duration']:.3f}[a{idx}n]")

    running_v, running_a, running_dur = "v0n", "a0n", infos[0]["duration"]
    for i in range(n - 1):
        transition = items[i].get("transition", "cut")
        secs = float(items[i].get("secs", 0.0))
        nxt_v, nxt_a = f"v{i + 1}n", f"a{i + 1}n"
        out_v, out_a = f"vj{i}", f"aj{i}"
        if transition == "cut" or secs <= 0:
            lines.append(f"[{running_v}][{nxt_v}]concat=n=2:v=1:a=0[{out_v}]")
            lines.append(f"[{running_a}][{nxt_a}]concat=n=2:v=0:a=1[{out_a}]")
            running_dur += infos[i + 1]["duration"]
        else:
            if secs > running_dur:
                raise ValueError(f"transition secs={secs} longer than preceding duration={running_dur}")
            offset = running_dur - secs
            xf = _XFADE_NAMES.get(transition, "fade")
            lines.append(f"[{running_v}][{nxt_v}]xfade=transition={xf}:duration={secs:.3f}:offset={offset:.3f}[{out_v}]")
            lines.append(f"[{running_a}][{nxt_a}]acrossfade=d={secs:.3f}[{out_a}]")
            running_dur += infos[i + 1]["duration"] - secs
        running_v, running_a = out_v, out_a
    return lines, running_v, running_a, running_dur


def render_set(items, out_path, progress=None):
    progress = progress or _NOOP
    if not items:
        raise ValueError("items is empty")
    progress(f"probing {len(items)} items")
    infos = [probe(it["video"]) for it in items]
    if any(not i["has_video"] for i in infos):
        raise RuntimeError("one or more items have no video stream")

    # Items may differ in resolution/fps (finished videos from different
    # songs) -- normalize every input to the first item's geometry/fps with
    # scale+pad+fps before joining. Lazy default: revisit if a mismatched
    # hero clip should drive dimensions instead.
    w, h, fps = infos[0]["width"], infos[0]["height"], infos[0]["fps"] or 30
    lines, out_v, out_a, predicted_dur = _build_render_set_filter(infos, items, w, h, fps)

    inputs = []
    for it in items:
        inputs += ["-i", it["video"]]

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
    progress(f"probing {len(items)} tracks")
    infos = [probe(it["audio"]) for it in items]
    missing = [it["audio"] for it, i in zip(items, infos) if not i["has_audio"]]
    if missing:
        raise RuntimeError(f"no audio stream in: {missing[0]}")

    lines = [f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}n]"
             for i in range(len(items))]
    running, running_dur = "a0n", infos[0]["duration"]
    for i in range(len(items) - 1):
        secs = 0.0 if items[i].get("transition") == "cut" else float(items[i].get("secs", 0.0))
        out = f"am{i}"
        if secs <= 0:
            lines.append(f"[{running}][a{i + 1}n]concat=n=2:v=0:a=1[{out}]")
            running_dur += infos[i + 1]["duration"]
        else:
            if secs > running_dur:
                raise ValueError(f"transition secs={secs} longer than preceding duration={running_dur}")
            lines.append(f"[{running}][a{i + 1}n]acrossfade=d={secs:.3f}[{out}]")
            running_dur += infos[i + 1]["duration"] - secs
        running = out

    tmp = _atomic_out(out_path)
    inputs = []
    for it in items:
        inputs += ["-i", it["audio"]]
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
    """Predicted set length: sum of item durations minus each transition's
    overlap. No ffmpeg call (ffprobe only, for real durations). key='audio'
    prices the mp3 mix, key='video' the rendered set."""
    if not items:
        return 0.0
    total = sum(probe(it[key])["duration"] for it in items)
    overlap = sum(0.0 if it.get("transition") == "cut" else float(it.get("secs", 0.0))
                  for it in items[:-1])
    return max(0.0, total - overlap)


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

        # a file with no audio stream is refused by name, not by ffmpeg later
        try:
            mix_audio([{"audio": clip_a, "transition": "cut", "secs": 0}], out_mix)
            raise AssertionError("silent video accepted as a mix input")
        except RuntimeError as e:
            assert "clip a.mp4" in str(e), e

        assert logs, "progress callback never fired"
        print(f"mixer.py OK  assemble={info1['duration']:.2f}s fade={info2['duration']:.2f}s "
              f"set2={actual2:.2f}s set5={actual5:.2f}s cut={actual_cut:.2f}s audio={adur:.2f}s")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    demo()
