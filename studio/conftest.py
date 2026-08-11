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


def _generate_storyboard(lyrics_text, tier, guardrail, style_note, song, model, scene_seconds, progress):
    grok_calls["guardrail"] = guardrail
    grok_calls["args"] = dict(lyrics=lyrics_text, tier=tier, style_note=style_note,
                               song=song, model=model, scene_seconds=scene_seconds)
    return {"scenes": [{"scene_number": 1}, {"scene_number": 2}]}


def _write_storyboard(sb, outdir, slug, tier):
    os.makedirs(outdir, exist_ok=True)
    json_path = os.path.join(outdir, f"{slug}_{tier}.json")
    md_path = os.path.join(outdir, f"{slug}_{tier}.md")
    json.dump(sb, open(json_path, "w"))
    with open(md_path, "w") as f:
        f.write("# storyboard\n")
    return json_path, md_path


classify_calls = []


def _classify_sheet(sheet_path, note="", model=None, progress=None):
    classify_calls.append({"sheet": sheet_path, "note": note})
    return {"flagged": [{"clip": 1, "issue": "broken", "reason": "two of her"}],
            "cells_seen": 2}


_stub("grok",
      list_models=lambda: ["grok-x"],
      generate_storyboard=_generate_storyboard,
      classify_sheet=_classify_sheet,
      write_storyboard=_write_storyboard)

# ---- lyrics ------------------------------------------------------------
_stub("lyrics",
      available=lambda: (True, "stub ready"),
      transcribe=lambda mp3, progress=None: {"segments": [{"start": 0, "end": 1, "text": "hi"}]},
      to_sections=lambda result, gap=3.0: "[Section 1]\nhi\n",
      estimate_duration=lambda mp3: 12.3)

# ---- mixer -------------------------------------------------------------
render_set_calls = []


def _render_set(items, out, progress=None):
    # real mixer.render_set: raises on empty input, and every item must
    # carry "video" -- a past bug passed "path" instead.
    if not items:
        raise ValueError("items is empty")
    for it in items:
        assert "video" in it, f"render_set item missing 'video' key: {it}"
    render_set_calls.append(items)
    open(out, "w").close()


_stub("mixer",
      probe=lambda p: {"duration": 12.3},
      assemble_song=lambda clip_paths, mp3, out, progress, fade: open(out, "w").close(),
      edit_audio=lambda *a, **k: None,
      render_set=_render_set,
      set_duration=lambda items: items)

# ---- pipeline ------------------------------------------------------------
_PIPE_DIR = tempfile.mkdtemp(prefix="studio_pipeline_")
os.makedirs(os.path.join(_PIPE_DIR, "input"), exist_ok=True)
os.makedirs(os.path.join(_PIPE_DIR, "output"), exist_ok=True)

contact_sheet_calls = []


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
      submit_dir=lambda wf_dir, progress=None: [],
      collect=lambda prefix_dir, pattern="*.png": [],
      gen_anchor=lambda face, outfit, view="front", n=4, progress=None, prefix=None: [],
      gen_refs=lambda slug, tier, sb, anchor, mp3, progress=None, limit=None: [],
      reroll=lambda slug, tier, sb, anchor, mp3, idxs, progress=None: [],
      stage_refs=lambda slug, tier, ref_paths: [],
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
