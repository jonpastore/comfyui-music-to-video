"""T10-1: backend selection is per call, not import time.

docs/TRD-10 T10-1. A studio started while the local gateway was down uses
it once it is up, with no restart. Asserted by a differential — gateway
absent then present, same process, two different providers — for both
lyrics.py and vision.py. Reading the source is not the check.
"""
import json
import os
import subprocess
import sys
import tempfile
import types
from contextlib import contextmanager

import httpx

from conftest import _real_module


def _vision():
    mod = _real_module("vision")
    assert mod is not None, "real vision.py failed to load"
    return mod


def _lyrics():
    mod = _real_module("lyrics")
    assert mod is not None, "real lyrics.py failed to load"
    return mod


class _Ok:
    status_code = 200

    def __init__(self, payload):
        self._p = payload
        self.text = ""

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


@contextmanager
def _mock_modules(**mapping):
    """Install fake sys.modules entries; None forces ImportError on that name."""
    sentinel = object()
    saved = {name: sys.modules.get(name, sentinel) for name in mapping}
    absent = {k for k, v in mapping.items() if v is None}
    present = {k: v for k, v in mapping.items() if v is not None}

    class _Block:
        def find_spec(self, fullname, path=None, target=None):
            root = fullname.split(".")[0]
            if fullname in absent or root in absent:
                raise ImportError(f"blocked {fullname}")
            return None

    block = _Block()
    sys.meta_path.insert(0, block)
    try:
        for name in absent:
            sys.modules.pop(name, None)
        sys.modules.update(present)
        yield
    finally:
        sys.meta_path.remove(block)
        for name, v in saved.items():
            if v is sentinel:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = v
        lyrics = _lyrics()
        lyrics._device_cache.clear()
        lyrics._model_cache.clear()


def test_t10_1_vision_switches_after_gateway_comes_up():
    """Gateway absent then present, same process → xai then local.

    One long-lived process. A studio that probed while the gateway was down
    must use it on the next call once it answers, without a restart.
    """
    vision = _vision()
    real_get, real_post = httpx.get, httpx.post
    real_base, real_key, real_model = vision.BASE, vision.KEY, vision.MODEL
    # vision.ask falls through to grok._chat on the paid path. The test
    # stub has no _chat/_resolve_model; install them for this differential.
    import grok
    had_chat = hasattr(grok, "_chat")
    had_resolve = hasattr(grok, "_resolve_model")
    real_chat = getattr(grok, "_chat", None)
    real_resolve = getattr(grok, "_resolve_model", None)

    vision.BASE = "http://gw-t10-1/v1"
    vision.KEY = "t10-1-key"
    vision.MODEL = ""
    try:
        with tempfile.TemporaryDirectory() as d:
            sheet = os.path.join(d, "sheet.jpg")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:s=64x64",
                 "-frames:v", "1", sheet],
                check=True, capture_output=True)

            def gateway_down(url, headers=None, timeout=None):
                raise httpx.ConnectError("refused")

            httpx.get = gateway_down
            where_down, _ = vision.available()
            assert where_down == "xai", where_down

            xai_payload = json.dumps({"flagged": [], "cells_seen": 1})
            xai_hits = []

            def fake_xai(model, messages, progress=None):
                xai_hits.append(model)
                return xai_payload

            grok._chat = fake_xai
            grok._resolve_model = lambda m: m
            v_down = vision.classify_sheet(sheet)
            assert v_down["backend"] == "xai", v_down
            assert xai_hits, "absent gateway must take the paid path"

            local_hits = []

            def gateway_up(url, headers=None, timeout=None):
                return _Ok({"data": [{"id": "gpt-oss-120b"}, {"id": "qwen3-vl"}]})

            def local_post(url, headers=None, json=None, timeout=None):
                local_hits.append(json.get("model") if json else None)
                body = json.dumps({"flagged": [], "cells_seen": 4})
                return _Ok({"choices": [{"message": {"content": body}}]})

            httpx.get = gateway_up
            httpx.post = local_post
            where_up, detail_up = vision.available()
            assert where_up == "local", (where_up, detail_up)
            assert "qwen3-vl" in detail_up, detail_up

            v_up = vision.classify_sheet(sheet)
            assert v_up["backend"] == "local", v_up
            assert local_hits and local_hits[-1] == "qwen3-vl", local_hits
            assert v_down["backend"] != v_up["backend"], (
                f"same process must switch providers; got {v_down['backend']!r} then "
                f"{v_up['backend']!r}")
    finally:
        httpx.get, httpx.post = real_get, real_post
        vision.BASE, vision.KEY, vision.MODEL = real_base, real_key, real_model
        if had_chat:
            grok._chat = real_chat
        elif hasattr(grok, "_chat"):
            delattr(grok, "_chat")
        if had_resolve:
            grok._resolve_model = real_resolve
        elif hasattr(grok, "_resolve_model"):
            delattr(grok, "_resolve_model")


def test_t10_1_lyrics_switches_after_preferred_backend_appears():
    """Preferred backend absent then present, same process → two providers.

    lyrics.py chooses faster-whisper over openai-whisper at call time. A
    process that only had the fallback installed must pick the preferred
    package on the next call once it is importable, without a restart.
    """
    lyrics = _lyrics()

    fake_whisper = types.ModuleType("whisper")
    fake_fw = types.ModuleType("faster_whisper")

    with _mock_modules(faster_whisper=None, whisper=fake_whisper):
        first = lyrics._pick_backend()
        ok, msg = lyrics.available()
        assert first == "openai-whisper", first
        assert ok is True and "openai-whisper" in msg, msg

    with _mock_modules(faster_whisper=fake_fw, whisper=fake_whisper):
        second = lyrics._pick_backend()
        ok2, msg2 = lyrics.available()
        assert second == "faster-whisper", second
        assert ok2 is True and "faster-whisper" in msg2, msg2

    assert first != second, (
        f"same process must switch providers; got {first!r} then {second!r}")


def test_t10_1_vision_available_is_not_frozen_at_first_probe():
    """available() itself must re-probe; not a once-at-import answer."""
    vision = _vision()
    real_get = httpx.get
    real_base, real_key, real_model = vision.BASE, vision.KEY, vision.MODEL
    try:
        vision.BASE = "http://gw-t10-1b/v1"
        vision.KEY = "t10-1b"
        vision.MODEL = ""

        def down(url, headers=None, timeout=None):
            raise httpx.ConnectError("refused")

        httpx.get = down
        a1 = vision.available()[0]
        assert a1 == "xai", a1

        httpx.get = lambda url, headers=None, timeout=None: _Ok(
            {"data": [{"id": "qwen3-vl"}]})
        a2 = vision.available()[0]
        assert a2 == "local", a2
        assert a1 != a2
    finally:
        httpx.get = real_get
        vision.BASE, vision.KEY, vision.MODEL = real_base, real_key, real_model
