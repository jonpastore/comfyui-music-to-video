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
import sys
import tempfile
import types

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="studio_test_")


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# ---- grok ------------------------------------------------------------
grok_calls = {}


def _generate_storyboard(lyrics_text, tier, guardrail, style_note, song, model, scene_seconds,
                          progress, direction="", cast=()):
    grok_calls["guardrail"] = guardrail
    grok_calls["args"] = dict(lyrics=lyrics_text, tier=tier, style_note=style_note,
                               song=song, model=model, scene_seconds=scene_seconds,
                               direction=direction, cast=list(cast))
    return {"scenes": [{"scene_number": 1}, {"scene_number": 2}]}


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


_stub("vision",
      classify_sheet=_classify_sheet,
      describe_cover=_describe_cover,
      propose_character=_propose_character,
      describe_anchor=lambda image_path, field, model=None, progress=None: (
          describe_calls.append((image_path, field))
          or f"drafted {field} from the anchor"),
      available=lambda: ("local", "stub"),
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


def _render_set(items, out, progress=None):
    # real mixer.render_set: raises on empty input, and every item must
    # carry "video" -- a past bug passed "path" instead.
    if not items:
        raise ValueError("items is empty")
    for it in items:
        assert "video" in it, f"render_set item missing 'video' key: {it}"
    render_set_calls.append(items)
    open(out, "w").close()


def _mix_audio(items, out, progress=None):
    if not items:
        raise ValueError("items is empty")
    for it in items:
        assert "audio" in it, f"mix_audio item missing 'audio' key: {it}"
    mix_audio_calls.append(items)
    open(out, "w").close()


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
    running_dur = _STUB_ITEM_DUR
    for it in items[:-1]:
        secs = 0.0 if it.get("transition") == "cut" else float(it.get("secs", 0.0))
        if secs > running_dur:
            raise ValueError(f"transition secs={secs} longer than preceding duration={running_dur}")
        running_dur += _STUB_ITEM_DUR - secs
    return max(0.0, running_dur)


# _XFADE_NAMES is READ by mixadvice.transitions() to decide what a model is
# allowed to suggest, so the stub has to carry it or every suggest 500s with
# "module 'mixer' has no attribute". Same real values as mixer.py.
_XFADE_NAMES = {"fade": "fade", "dissolve": "dissolve", "wipe": "wipeleft"}

_stub("mixer",
      _XFADE_NAMES=_XFADE_NAMES,
      probe=lambda p: {"duration": _STUB_ITEM_DUR},
      assemble_song=lambda clip_paths, mp3, out, progress, fade: open(out, "w").close(),
      edit_audio=lambda *a, **k: None,
      render_set=_render_set,
      mix_audio=_mix_audio,
      set_duration=_set_duration,
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
      collect=lambda prefix_dir, pattern="*.png": [],
      MAX_ANCHOR_REFS=3,
      gen_anchor=lambda images, view="front", n=4, progress=None, prefix=None, profile=None, guard="", prompt="": anchor_calls.append({"profile": profile, "view": view, "guard": guard, "prompt": prompt, "images": list(images)}) or [],
      gen_refs=lambda slug, tier, sb, anchor, mp3, progress=None, limit=None, guard="", body="", cast=None: refs_calls.append({"guard": guard, "body": body, "cast": cast}) or [],
      reroll=lambda slug, tier, sb, anchor, mp3, idxs, progress=None: [],
      stage_refs=lambda slug, tier, ref_paths: [],
      gen_artwork=lambda slug, prompt, anchor_path, progress=None, guard="", n=1, size=1024: [],
      fix_ref=lambda *a, **kw: [],
      gen_clips=lambda slug, tier, sb, mp3, ref_paths, progress=None: [],
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
