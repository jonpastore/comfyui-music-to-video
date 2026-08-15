"""Shared test infrastructure for studio/'s pytest suite.

pipeline/grok/lyrics/mixer are stubbed via sys.modules exactly ONCE, here,
before pytest imports any test module -- and therefore before app.py's own
`import mixer` (etc.) runs. That import binds app.py's name to whichever
module OBJECT sits in sys.modules at that moment; a second test file
re-stubbing sys.modules afterwards does NOT change what app.py already
bound to, since it holds a direct reference to the object, not a
by-name lookup. So there must be exactly one stub object per module for
the whole session -- conftest.py guarantees that by running first. A test
that needs different behaviour mutates an attribute on that same live
object (see `patch_stub` below) and restores it afterwards, instead of
trying to swap the module out.
"""
import json
import os
import re
import sys
import tempfile
import types

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="studio_test_")


_REAL_CACHE = {}


def _real_module(name):
    """The genuine module, loaded under a private name so it does not disturb
    the stub sitting in sys.modules[name]. None if it cannot be imported at all
    (lyrics pulls in faster-whisper, which is exactly the sort of thing a stub
    exists to avoid)."""
    if name not in _REAL_CACHE:
        import importlib.util
        path = os.path.join(ROOT, f"{name}.py")
        mod = None
        if os.path.isfile(path):
            try:
                spec = importlib.util.spec_from_file_location(f"_real_{name}", path)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod
                spec.loader.exec_module(mod)
            except Exception:
                mod = None
        _REAL_CACHE[name] = mod
    return _REAL_CACHE[name]


def _stub(name, **attrs):
    """A stubbed module that falls through to the real one for plain DATA.

    A stub exists to keep ffmpeg, the GPU and the network out of the tests --
    not to hide constants. Every time app.py started reading a new constant off
    a stubbed module (`mixer._XFADE_NAMES`, `_item_duration`'s shape,
    `plan_tempo_ramp`, `comfy_queue`, and most recently `mixer.TRANSITIONS` and
    `mixer.BLACK`) the whole suite died at IMPORT with a bare AttributeError,
    which points at conftest rather than at the line that needs changing. Five
    times.

    So an attribute the stub does not define is looked up on the real module:

    - plain data (a string, number, tuple, dict, frozenset) is returned as-is,
      which means a constant can never again need mirroring here, and cannot
      drift from the real value if it is
    - anything CALLABLE is refused, loudly and by name. That is the half a stub
      is actually for: falling through to a real function would let a test shell
      out to ffmpeg or reach the network, silently. The message says which
      module, which attribute, and what to do.
    """
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)

    _SAFE = (str, bytes, int, float, bool, tuple, list, dict, set, frozenset, type(None))

    def __getattr__(attr, _name=name):
        # Dunders are module IDENTITY, not module data. Serving the real
        # module's __file__/__path__/__spec__ here makes the stub claim to be
        # the real file -- which fooled the first version of this fix's own
        # test -- and hands the import machinery answers about a module that is
        # deliberately not present.
        if attr.startswith("__") and attr.endswith("__"):
            raise AttributeError(f"module {_name!r} has no attribute {attr!r}")
        real = _real_module(_name)
        if real is None or not hasattr(real, attr):
            raise AttributeError(f"module {_name!r} has no attribute {attr!r}")
        value = getattr(real, attr)
        if isinstance(value, _SAFE) and not callable(value):
            return value
        raise AttributeError(
            f"{_name}.{attr} is callable and the test stub does not define it. "
            f"Stubs deliberately do not fall through to real functions -- this one would "
            f"have run the real {_name}.{attr}, which is what the stub exists to prevent. "
            f"Add {attr}= to the _stub({_name!r}, ...) call in conftest.py.")

    mod.__getattr__ = __getattr__
    sys.modules[name] = mod
    return mod


# ---- grok ------------------------------------------------------------
grok_calls = {}


def _generate_storyboard(lyrics_text, tier, guardrail, style_note, song, model, scene_seconds,
                          progress, direction="", cast=(), arc_ctx=None):
    grok_calls["guardrail"] = guardrail
    grok_calls["args"] = dict(lyrics=lyrics_text, tier=tier, style_note=style_note,
                               song=song, model=model, scene_seconds=scene_seconds,
                               direction=direction, cast=list(cast), arc_ctx=arc_ctx)
    return {"scenes": [{"scene_number": 1}, {"scene_number": 2}]}


def _require_figure_roles(sb):
    real = _real_module("grok")
    if real is not None:
        real.require_figure_roles(sb)


def _write_storyboard(sb, outdir, slug, tier):
    """Same contract as the real grok.write_storyboard, and it renders the REAL
    markdown.

    grok is stubbed to keep xAI out of the tests, but write_storyboard makes no
    network call -- it is json.dump plus build_storyboard.to_md. Writing a
    placeholder "# storyboard" here stubbed out a seam that genuinely needs
    testing: the storyboard page rewrites the JSON in place, and the markdown
    beside it has to be regenerated or the two silently drift apart.
    """
    from build_storyboard import to_md
    os.makedirs(outdir, exist_ok=True)
    json_path = os.path.join(outdir, f"{slug}_{tier}.json")
    md_path = os.path.join(outdir, f"{slug}_{tier}.md")
    json.dump(sb, open(json_path, "w"))
    with open(md_path, "w") as f:
        f.write(to_md(sb))
    return json_path, md_path


classify_calls = []
describe_calls = []
draft_calls = []
edit_prompt_calls = []
refs_calls = []


def _classify_sheet(sheet_path, note="", model=None, progress=None):
    classify_calls.append({"sheet": sheet_path, "note": note})
    return {"flagged": [{"clip": 1, "issue": "broken", "reason": "two of her"}],
            "cells_seen": 2}


cover_calls = []


def _describe_cover(image_path, field, progress=None):
    cover_calls.append((image_path, field))
    return f"drafted {field} from the cover"


def _propose_character(image_path, progress=None):
    cover_calls.append((image_path, "cast"))
    return {"name": "Vex", "role": "rival DJ", "identity": "a white-furred rival",
            "wardrobe": "a long grey coat", "body": "white fur on every limb"}


genre_calls = []


def _ask_text(system, user_text, progress=None, model=None):
    """Answer a genre-classification prompt the way the real fleet does.

    Echoes back one in-taxonomy suggestion per track it was shown, quoting the
    phrase before the first comma -- which is exactly the contract app.py checks
    (evidence must be verbatim). A test that wants a bad reply patches this.
    """
    genre_calls.append(user_text)
    tracks = []
    for line in user_text.splitlines():
        m = re.match(r'^(\d+)\. ".*" :: (.+)$', line.strip())
        if not m:
            continue
        tracks.append({"id": int(m.group(1)), "evidence": m.group(2).split(",")[0],
                       "genre": "Electronic", "subgenre": "Tech House",
                       "genre2": "", "subgenre2": ""})
    return json.dumps({"tracks": tracks}), "qwen-stub"


_stub("vision",
      classify_sheet=_classify_sheet,
      describe_cover=_describe_cover,
      propose_character=_propose_character,
      ask_text=_ask_text,
      # the real one is pure parsing, so the stub does the real thing rather
      # than pretending -- a test asserting a malformed reply is refused would
      # otherwise be testing the stub
      json_or_raise=lambda out, what: json.loads(out),
      describe_anchor=lambda image_path, field, model=None, progress=None: (
          describe_calls.append((image_path, field))
          or f"drafted {field} from the anchor"),
      draft_view_prompt=lambda image_path=None, view="front", current="",
                               fields=None, progress=None: (
          draft_calls.append({"image": image_path, "view": view, "current": current})
          or f"drafted {view} prompt"),
      available=lambda: ("local", "stub"),
      score_candidate=lambda path, bases, prompt="", progress=None: {
          "confidence": None, "identity": None, "prompt": None,
          "notes": "", "error": "stub", "backend": "stub"},
      read_edit_instruction=lambda prompt, duration, progress=None: (
          edit_prompt_calls.append((prompt, duration))
          or ({"trim_start": 4.0, "trim_end": None, "gain_db": 0.0,
               "fade_in": 0.0, "fade_out": 0.0}, "cut the first 4s", "qwen-stub")))

_stub("grok",
      MAX_DIRECTION=4000,
      VISION_MODEL="grok-vision-stub",
      list_models=lambda: ["grok-x", "grok-2"],
      best_model=lambda models: max(models) if models else None,
      generate_storyboard=_generate_storyboard,
      classify_sheet=_classify_sheet,
      describe_anchor=lambda image_path, field, model=None, progress=None: (
          describe_calls.append((image_path, field))
          or f"drafted {field} from the anchor"),
      require_figure_roles=_require_figure_roles,
      write_storyboard=_write_storyboard)

# ---- lyrics ------------------------------------------------------------
_stub("lyrics",
      available=lambda: (True, "stub ready"),
      transcribe=lambda mp3, progress=None: {"segments": [{"start": 0, "end": 1, "text": "hi"}]},
      to_sections=lambda result, gap=3.0: "[Section 1]\nhi\n",
      estimate_duration=lambda mp3: 12.3)

# ---- analyse ------------------------------------------------------------
# librosa is not installed on the system python the test suite runs on
# (analyse.py imports it lazily, only inside analyse()) -- stubbed exactly
# like pipeline/grok/lyrics/mixer so h_analyse never needs the real thing.
analyse_calls = []
_stub("analyse",
      analyse=lambda mp3_path, progress=None: (
          analyse_calls.append(mp3_path) or
          {"bpm": 128.0, "key": "8A", "beat_grid": [0.0, 0.5, 1.0, 1.5],
           "energy": 0.05, "downbeat_offset": 0}))

# ---- mixer -------------------------------------------------------------
# beatmatch.py is real here (not stubbed) -- it has no heavy deps, same
# reasoning as effects/video_fx below, so the mixer stub's beat-matching
# pieces delegate to it instead of hand-duplicating that maths a third time.
import beatmatch as _beatmatch_for_stub

render_set_calls = []
mix_audio_calls = []
_STUB_ITEM_DUR = 12.3  # matches probe()'s fake duration below
_STUB_MAX_TEMPO_STRETCH = 1.16


def _stub_snap_transition(out_grid, out_offset, out_point, in_grid, in_offset, in_point=0.0):
    return (_beatmatch_for_stub.snap_to_downbeat(out_point, out_grid, out_offset),
            _beatmatch_for_stub.snap_to_downbeat(in_point, in_grid, in_offset))


def _stub_tempo_ratio(out_bpm, in_bpm):
    return (in_bpm / out_bpm) if out_bpm and in_bpm else 1.0


def _stub_can_beatmatch(out_bpm, in_bpm):
    if not out_bpm or not in_bpm or out_bpm <= 0 or in_bpm <= 0:
        return False
    ratio = _stub_tempo_ratio(out_bpm, in_bpm)
    return ratio <= _STUB_MAX_TEMPO_STRETCH and (1.0 / ratio) <= _STUB_MAX_TEMPO_STRETCH


def _stub_plan_tempo_ramp(beat_grid, downbeat_offset, out_point, out_bpm, in_bpm, n_bars=4):
    if not _stub_can_beatmatch(out_bpm, in_bpm):
        return [], []
    bars = [b for b in (beat_grid or [])[downbeat_offset::4] if b <= out_point]
    if len(bars) < 2:
        return [], []
    bar_times = bars[-(n_bars + 1):]
    target = _stub_tempo_ratio(out_bpm, in_bpm)
    steps = len(bar_times) - 1
    ratios = ([target] if steps == 1 else
              [round(1.0 + (target - 1.0) * i / (steps - 1), 6) for i in range(steps)])
    return bar_times, ratios


def _is_card(it):
    return bool(it) and (it.get("kind") == "card" or bool(it.get("card")))


def _render_set(items, out, progress=None):
    # real mixer.render_set: raises on empty input, and every item must
    # carry "video" -- a past bug passed "path" instead. A card is the
    # exception: it is a still, not a song render.
    if not items:
        raise ValueError("items is empty")
    for it in items:
        if _is_card(it):
            continue
        assert "video" in it, f"render_set item missing 'video' key: {it}"
    render_set_calls.append(items)
    open(out, "w").close()


def _mix_audio(items, out, progress=None):
    if not items:
        raise ValueError("items is empty")
    for it in items:
        if _is_card(it):
            continue
        assert "audio" in it, f"mix_audio item missing 'audio' key: {it}"
    mix_audio_calls.append(items)
    open(out, "w").close()


render_preview_calls = []


def _render_preview(items, out_path, at=0.0, secs=None, key="audio", progress=None):
    # T1-17: the real one shells out to ffmpeg. The stub writes a file
    # so the route can return a path that exists, and records the
    # window so a test can see at/secs reached the call.
    if not items:
        raise ValueError("items is empty")
    span_s = 20.0 if secs is None else float(secs)
    render_preview_calls.append({
        "items": items, "out_path": out_path, "at": at, "secs": secs, "key": key})
    parent = os.path.dirname(os.path.abspath(out_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    open(out_path, "wb").write(b"ID3" + b"\0" * 64)
    start = max(0.0, float(at or 0.0) - span_s / 2.0)
    return {
        "path": out_path,
        "is_proxy": False,
        "at": 0.0 if at is None else float(at),
        "secs": span_s,
        "start": start,
        "end": start + span_s,
        "duration": span_s,
    }


def _item_len(it):
    if _is_card(it):
        return max(0.0, float(it.get("duration") or 0.0))
    return _STUB_ITEM_DUR


def _item_duration(info, it):
    """Mirrors the real mixer._item_duration. app.set_detail reads it to size the
    timeline blocks, so a stub without it silently produced a zero-width
    timeline -- the missing-from-the-stub trap, again."""
    if _is_card(it):
        return max(0.0, float(it.get("duration") or 0.0))
    full = info["duration"]
    in_s = float(it.get("in_secs") or 0.0)
    out_s = it.get("out_secs")
    out_s = float(out_s) if out_s is not None else full
    return max(0.0, min(out_s, full) - in_s)


def _set_duration(items, key="video"):
    # Real mixer.set_duration: walks items, each transition's secs checked
    # against the running duration so far, raising ValueError exactly like
    # the real one on an impossible transition (app.py's edit-time guard
    # depends on this raising, not just returning a number). Approximates
    # the trim math (probe() here always answers the same duration, so a
    # trim cannot be modelled exactly) -- good enough to prove the route
    # wires items -> a number (or a refusal), which is all app.py needs.
    if not items:
        return 0.0
    running_dur = _item_len(items[0])
    for i, it in enumerate(items[:-1]):
        nxt = _item_len(items[i + 1])
        # a black handover overlaps nothing and ADDS its hold -- the one
        # transition that makes a set longer (mixer._advance)
        if it.get("transition") == "black":
            fade = float(it.get("secs", 0.0)) / 2.0
            if fade > running_dur:
                raise ValueError(
                    f"transition secs={fade} longer than preceding duration={running_dur}")
            running_dur += nxt + float(it.get("hold") or 0.0)
            continue
        secs = 0.0 if it.get("transition") == "cut" else float(it.get("secs", 0.0))
        if secs > running_dur:
            raise ValueError(f"transition secs={secs} longer than preceding duration={running_dur}")
        running_dur += nxt - secs
    return max(0.0, running_dur)


def _transition_times(items, key="video"):
    # Same walk as _set_duration, landing times only. No ffmpeg — probe
    # here is the stub's constant length. Real transition_times is on
    # mixer.py and T3-12 tests bind that.
    if not items or len(items) < 2:
        return []
    running = _item_len(items[0])
    lands = []
    for i, it in enumerate(items[:-1]):
        nxt = _item_len(items[i + 1])
        if it.get("transition") == "black":
            hold = float(it.get("hold") or 0.0)
            lands.append(running + hold / 2.0)
            running += nxt + hold
            continue
        secs = 0.0 if it.get("transition") == "cut" else float(it.get("secs", 0.0))
        lands.append(running - secs / 2.0 if secs > 0 else running)
        running += nxt - secs
    return lands


# _XFADE_NAMES, TRANSITIONS and BLACK are deliberately NOT mirrored here any
# more. They are plain data, so _stub's fallback serves them from the real
# mixer.py -- one source, and a constant added to mixer can never again break
# this suite at import. Only behaviour is stubbed below.
splice_calls = []


_stub("mixer",
      probe=lambda p: {"duration": _STUB_ITEM_DUR},
      _item_duration=_item_duration,
      assemble_song=lambda clip_paths, mp3, out, progress, fade: open(out, "w").close(),
      edit_audio=lambda *a, **k: None,
      # Records the span and writes a real file at out_path, because the audio
      # job stores that path in an assets row and the test then checks the file
      # is there -- a stub writing nothing would prove the opposite of what the
      # assertion reads as. SPLICE_XFADE is a VALUE the route does arithmetic
      # with, so it has to be the real one, not a stand-in.
      SPLICE_XFADE=0.25,
      # Mirrors the real formula rather than falling through to it, because the
      # real one calls probe() and would shell out to ffprobe. A span touching
      # either edge of the track has ONE seam, not two -- getting that wrong in
      # the route is the bug this stub's caller exists to catch, so the stub has
      # to be right about it or the test would assert against its own mistake.
      bridge_seconds=lambda mp3_path, start, end, xfade=0.25: (
          (float(end) - float(start))
          + ((1 if float(start) > 0 else 0)
             + (1 if float(end) < _STUB_ITEM_DUR else 0)) * xfade),
      splice_bridge=lambda mp3_path, bridge_path, out_path, start, end, xfade=0.25,
      progress=None: (
          splice_calls.append({"src": mp3_path, "bridge": bridge_path,
                               "start": start, "end": end})
          or open(out_path, "wb").write(b"ID3" + b"\0" * 64) and out_path),
      # h_analyse draws a waveform now. Stubbed to write a real (empty) file at
      # the path it was given, because the caller records an assets row and
      # song_waveform() then checks the file is actually there -- a stub that
      # wrote nothing would make every waveform silently absent in the tests
      # and prove the opposite of what they assert.
      waveform_png=lambda audio_path, out_path, progress=None, size=None: (
          os.makedirs(os.path.dirname(out_path), exist_ok=True)
          or open(out_path, "wb").write(b"\x89PNG\r\n\x1a\n") and out_path),
      # peaks is pure min/max reduce -- no ffmpeg -- so the stub runs the real
      # one. A fake that always returned [] would pass T1-13's upper bound
      # and take T1-14 with it (docs/TRD-1 §6.1).
      peaks=(_real_module("mixer").peaks if _real_module("mixer") is not None
             else (lambda samples, z=0: [])),
      # T1-15: empty is {pairs, reason}, never a bare []. A path that
      # exists still fakes one pair so the app suite does not decode.
      peaks_from_path=lambda audio_path, z=0: (
          {"pairs": [[-0.5, 0.5]], "reason": None}
          if audio_path and os.path.isfile(audio_path)
          else {"pairs": [], "reason": ("no_audio" if not audio_path else "missing")}),
      PEAKS_MAX_POINTS=2048,
      # T1-timeline: axis is pure. The stub must serve the real function
      # or set_detail AttributeErrors and the HTML test never reaches
      # .tl-tick. A fake that always returned [] would hide a missing
      # set_duration wire.
      timeline_axis=(_real_module("mixer").timeline_axis
                     if _real_module("mixer") is not None
                     and hasattr(_real_module("mixer"), "timeline_axis")
                     else (lambda duration_s, max_ticks=8: [])),
      # Joins / playhead / lanes are pure. A fake that always returned
      # [] would hide a missing set_detail wire the same way a blank
      # axis would (docs/TRD-1 §1).
      timeline_item_starts=(_real_module("mixer").timeline_item_starts
                            if _real_module("mixer") is not None
                            and hasattr(_real_module("mixer"), "timeline_item_starts")
                            else (lambda items: [0.0] * len(items or ()))),
      timeline_joins=(_real_module("mixer").timeline_joins
                      if _real_module("mixer") is not None
                      and hasattr(_real_module("mixer"), "timeline_joins")
                      else (lambda items, duration_s: [])),
      timeline_playhead=(_real_module("mixer").timeline_playhead
                         if _real_module("mixer") is not None
                         and hasattr(_real_module("mixer"), "timeline_playhead")
                         else (lambda at, duration_s: None)),
      timeline_lanes=(_real_module("mixer").timeline_lanes
                      if _real_module("mixer") is not None
                      and hasattr(_real_module("mixer"), "timeline_lanes")
                      else (lambda items, duration_s, curves, ranges=None,
                                   lane_order=None: [])),
      # T1-16: preview_proxy is pure (no ffmpeg). The stub must serve the
      # real one so adding an effect lists it; a fake static list would
      # stay green.
      preview_proxy=(_real_module("mixer").preview_proxy
                     if _real_module("mixer") is not None
                     else (lambda items: {"is_proxy": True, "not_applied": []})),
      # T1-17: preview_window is pure. render_preview is ffmpeg.
      preview_window=(_real_module("mixer").preview_window
                      if _real_module("mixer") is not None
                      else (lambda at, total, secs=None: (0.0, 20.0))),
      render_preview=_render_preview,
      # T1-19: applied_master_chain is pure (no ffmpeg). The stub must
      # serve the real one so h_render_set records the same chain
      # _master_lines applies, not a parallel default.
      applied_master_chain=(_real_module("mixer").applied_master_chain
                            if _real_module("mixer") is not None
                            else (lambda items: None)),
      one_button_master=(_real_module("mixer").one_button_master
                         if _real_module("mixer") is not None
                         else (lambda params=None: None)),
      # T1-25: real export_loudness shells out to ebur128. The stub
      # names in-tolerance numbers so h_render_set can write the asset
      # row without measuring the empty file mix_audio writes here.
      export_loudness=lambda path, items=None: {
          "lufs": -16.0, "true_peak_db": -1.5,
          "target_lufs": -16.0, "target_true_peak_db": -1.5,
          "flagged": False},
      render_set=_render_set,
      mix_audio=_mix_audio,
      set_duration=_set_duration,
      transition_times=_transition_times,
      is_card=_is_card,
      CARD="card",
      MAX_TEMPO_STRETCH=_STUB_MAX_TEMPO_STRETCH,
      snap_transition=_stub_snap_transition,
      nearest_downbeat=lambda beat_grid, downbeat_offset, t: (
          _beatmatch_for_stub.snap_to_downbeat(t, beat_grid, downbeat_offset)),
      can_beatmatch=_stub_can_beatmatch,
      plan_tempo_ramp=_stub_plan_tempo_ramp,
      suggest_running_order=_beatmatch_for_stub.suggest_order)

# ---- mixadvice -----------------------------------------------------------
# The REAL clean()/set_summary are used: they are the trust boundary and pure.
# Only suggest() is stubbed, because that is the part that calls xAI.
import mixadvice as _real_mixadvice          # noqa: E402
suggest_calls = []


def _suggest(items, direction="", only_id=None, model=None, progress=None):
    suggest_calls.append({"items": [i["id"] for i in items], "direction": direction,
                          "only_id": only_id})
    reply = {"items": [{"id": i["id"], "transition": "dissolve", "secs": 3.5,
                        "beatmatch": True, "effects": {"eq_kill": {"low_db": -6}},
                        "why": "stub"} for i in items]}
    return _real_mixadvice.clean(reply, {i["id"] for i in items}, only_id)


_real_mixadvice.suggest = _suggest

# ---- pipeline ------------------------------------------------------------
_PIPE_DIR = tempfile.mkdtemp(prefix="studio_pipeline_")
os.makedirs(os.path.join(_PIPE_DIR, "input"), exist_ok=True)
os.makedirs(os.path.join(_PIPE_DIR, "output"), exist_ok=True)

contact_sheet_calls = []
anchor_calls = []
free_vram_calls = []


audio_calls = []


def _gen_audio(slug, tags, lyrics="", seconds=30.0, n=1, progress=None, seed=None,
               source_path=None, denoise=1.0, steps=None, cfg=None):
    """Real files in the stub OUTPUT dir, because the point of the audio job is
    that the takes are copied OUT of there and given rows -- a stub returning
    bare paths that do not exist could not tell a kept take from a lost one."""
    audio_calls.append(dict(slug=slug, tags=tags, lyrics=lyrics, seconds=seconds, n=n,
                            seed=seed, source_path=source_path, denoise=denoise))
    out = []
    for i in range(int(n)):
        p = os.path.join(_PIPE_DIR, "output", f"audio_{slug}_take{len(audio_calls)}_{i}.mp3")
        with open(p, "wb") as fh:
            fh.write(b"ID3" + b"\0" * 64)
        out.append(p)
    return out


def _contact_sheet(src, out, cols=6):
    # records exactly which frames were staged -- the point of the review job
    # is that the sheet shows the APPROVED refs, nothing else
    contact_sheet_calls.append(sorted(os.listdir(src)))
    open(out, "w").close()
    return out


_stub("pipeline",
      COMFY_INPUT=os.path.join(_PIPE_DIR, "input"),
      COMFY_OUTPUT=os.path.join(_PIPE_DIR, "output"),
      install_input=lambda local_path, name=None: (name or os.path.basename(local_path)),
      free_vram=lambda progress=None: free_vram_calls.append(True) or True,
      submit_dir=lambda wf_dir, progress=None: [],
      # ComfyUI's OWN queue, which the studio reads but does not control. An
      # empty one is the honest default here: there is no ComfyUI in tests.
      comfy_queue=lambda: {"running": 0, "pending": 0},
      # a CALLABLE, so the real-module fallback refuses it by design --
      # letting it through would have the suite polling a live SwarmUI
      swarm_backends=lambda: None,
      # which backend renders. The jobs panel reads it, and app.py calls it on
      # THIS module, so the stub needs it -- conftest gaps have bitten five times.
      RENDER_BACKEND="comfy",
      collect=lambda prefix_dir, pattern="*.png": [],
      MAX_ANCHOR_REFS=3,
      # `render` is the anchor form's sampler settings (mode/negative/steps/cfg
      # ...). Recorded, not ignored: a test asserting the form's knobs reach the
      # renderer has to be able to see them arrive.
      gen_anchor=lambda images, view="front", n=4, progress=None, prefix=None, profile=None, guard="", prompt="", render=None: anchor_calls.append({"profile": profile, "view": view, "guard": guard, "prompt": prompt, "images": list(images), "render": dict(render or {})}) or [],
      gen_refs=lambda slug, tier, sb, anchor, mp3, progress=None, limit=None, guard="", body="", cast=None: refs_calls.append({"guard": guard, "body": body, "cast": cast}) or [],
      reroll=lambda slug, tier, sb, anchor, mp3, idxs, progress=None: [],
      stage_refs=lambda slug, tier, ref_paths: [],
      gen_artwork=lambda slug, prompt, anchor_path, progress=None, guard="", n=1, size=1024: [],
      fix_ref=lambda *a, **kw: [],
      gen_postproc=lambda clip_paths, slug, multiplier=2, upscale="", progress=None: [],
      gen_clips=lambda slug, tier, sb, mp3, ref_paths, progress=None: [],
      gen_audio=_gen_audio,
      contact_sheet=_contact_sheet)


_MISSING = object()


@pytest.fixture
def patch_stub():
    """Monkeypatch an attribute on one of the live stub modules (pipeline/
    grok/lyrics/mixer) for a single test, restored afterwards. Needed
    because app.py already bound its `mixer`/`grok`/etc. names to these
    exact module objects at import time -- only mutating an attribute on
    that same object is visible to it; assigning sys.modules[name] again
    is not."""
    patches = []

    def _patch(module_name, **attrs):
        mod = sys.modules[module_name]
        for k, v in attrs.items():
            patches.append((mod, k, getattr(mod, k, _MISSING)))
            setattr(mod, k, v)

    yield _patch
    for mod, k, old in reversed(patches):
        if old is _MISSING:
            delattr(mod, k)
        else:
            setattr(mod, k, old)
