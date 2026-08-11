"""mp3 -> editable lyrics via Whisper ASR.

Backend choice (checked at call time, not import time): prefer faster-whisper
(CTranslate2 backend -- faster and lighter on VRAM for the same accuracy) if
it's importable, else fall back to openai-whisper. If neither is installed,
available() reports that instead of raising. Neither package is added to any
requirements file here; see the deploy note at the bottom of this docstring.

Accuracy note, read before trusting the output: this is raw Whisper run on
sung vocals over dense electronic production, not a music-tuned ASR model.
Expect a mediocre transcript -- garbled words, missed adlibs, drifting
timestamps. That's expected, not a bug, and it's exactly why the app always
lets the user edit the transcript before it feeds a storyboard.

Deploy note: cerberus-ai's venv (~/ComfyUI/venv, torch 2.11.0+cu128 already
present) needs `pip install faster-whisper` (preferred) or `pip install
openai-whisper` for transcribe() to work. available() explains this to the UI
when neither is present.
"""

import os
import subprocess

MODEL_SIZE = os.environ.get("WHISPER_MODEL", "medium")

_model_cache = {}  # (backend, size, device) -> loaded model, kept warm across requests
_device_cache = {}  # backend -> (device, detail)


def _pick_backend():
    try:
        import faster_whisper  # noqa: F401
        return "faster-whisper"
    except ImportError:
        pass
    try:
        import whisper  # noqa: F401
        return "openai-whisper"
    except ImportError:
        pass
    return None


def _device(backend):
    """(device, detail). Cached per backend, never raises.

    faster-whisper runs on CTranslate2, which talks to CUDA directly -- it has
    no torch dependency, and the studio venv deliberately doesn't carry one
    (ComfyUI's torch lives in its own venv). So ask CTranslate2, not torch.
    get_cuda_device_count() doesn't load a model or touch the network, just
    queries the CUDA runtime -- cheap enough to call from available().

    openai-whisper is different: it's built on torch and requires it as a
    hard dependency, so if that's the active backend torch is already there.
    """
    if backend in _device_cache:
        return _device_cache[backend]

    if backend == "faster-whisper":
        try:
            import ctranslate2
            count = ctranslate2.get_cuda_device_count()
        except Exception as e:
            result = "cpu", f"no CUDA device visible to CTranslate2 ({e})"
        else:
            result = (("cuda", f"CTranslate2, {count} GPU{'s' if count != 1 else ''}")
                      if count > 0 else ("cpu", "no CUDA device visible to CTranslate2"))
    else:
        try:
            import torch
            result = ("cuda", "torch") if torch.cuda.is_available() else ("cpu", "no CUDA device visible to torch")
        except ImportError:
            result = "cpu", "torch not installed (required by openai-whisper)"

    _device_cache[backend] = result
    return result


def available():
    """(usable, human explanation). Never raises."""
    try:
        backend = _pick_backend()
        if backend is None:
            return False, "no whisper backend installed (pip install faster-whisper or openai-whisper)"
        device, detail = _device(backend)
        return True, f"{backend} ready, device={device} ({detail})"
    except Exception as e:  # belt-and-suspenders: this must never raise
        return False, f"error probing whisper: {e}"


def _load_model(size, device, backend, progress):
    key = (backend, size, device)
    if key in _model_cache:
        return _model_cache[key]
    if progress:
        progress(f"loading model {size} on {device}")
    if backend == "faster-whisper":
        from faster_whisper import WhisperModel
        compute_type = "float16" if device == "cuda" else "int8"
        model = WhisperModel(size, device=device, compute_type=compute_type)
    else:
        import whisper
        model = whisper.load_model(size, device=device)
    _model_cache[key] = model
    return model


# CTranslate2, torch and the CUDA runtime each word an exhausted GPU
# differently, and none of them raise a dedicated exception type -- the real
# failure on this box was a bare RuntimeError reading "CUDA failed with error
# out of memory". Matching on the message is the only handle available.
_OOM_MARKERS = ("out of memory", "cuda failed", "cuda error", "cublas", "cudnn",
                "cuda_error_out_of_memory")


def _is_oom(exc):
    return any(m in str(exc).lower() for m in _OOM_MARKERS)


def transcribe(mp3_path, progress=None, model_size=None):
    def note(msg):
        if progress:
            progress(msg)

    size = model_size or MODEL_SIZE
    backend = _pick_backend()
    if backend is None:
        raise RuntimeError("no whisper backend installed; " + available()[1])
    device, _detail = _device(backend)
    try:
        return _transcribe_on(mp3_path, backend, size, device, note)
    except Exception as e:
        if device != "cuda" or not _is_oom(e):
            raise
        # ComfyUI holds ~21.5 GB of this card between renders. The caller
        # (h_transcribe) asks it to unload first, but a render can start in
        # between -- CPU is slower, never unavailable, and a slow transcript
        # beats a failed job.
        note(f"GPU is full ({e}); retrying on CPU")
        _model_cache.pop((backend, size, "cuda"), None)
        return _transcribe_on(mp3_path, backend, size, "cpu", note)


def _transcribe_on(mp3_path, backend, size, device, note):
    model = _load_model(size, device, backend, note)

    dur = estimate_duration(mp3_path)
    note(f"transcribing {int(dur // 60)}:{int(dur % 60):02d}")

    segments = []
    if backend == "faster-whisper":
        raw_segments, info = model.transcribe(mp3_path, vad_filter=True)
        language = info.language
        for seg in raw_segments:
            segments.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
        text = " ".join(s["text"] for s in segments)
    else:
        result = model.transcribe(mp3_path)
        language = result.get("language", "")
        for seg in result.get("segments", []):
            segments.append({"start": seg["start"], "end": seg["end"], "text": seg["text"].strip()})
        text = result.get("text", "").strip()

    note(f"done, {len(segments)} segments")
    return {
        "text": text,
        "segments": segments,
        "language": language,
        "model": size,
        "device": device,
    }


def to_sections(result, gap=3.0):
    """Segments -> Suno-style lyrics text, "[Section N]" headers on silence
    gaps >= `gap` seconds. Leading silence before the first vocal becomes
    "[Intro]". build_storyboard.parse_sections() reads these tags as scene
    boundaries -- see its docstring for the merge rules on tag-only sections.
    """
    cleaned = []
    for seg in result.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = seg.get("start", 0.0) or 0.0
        end = seg.get("end", start) or start
        if end < start:
            end = start
        cleaned.append((start, end, text))
    if not cleaned:
        return ""
    cleaned.sort(key=lambda s: s[0])

    out = []
    if cleaned[0][0] >= gap:
        out.append("[Intro]")

    section_num = 0
    prev_end = None
    for start, end, text in cleaned:
        if prev_end is None or (start - prev_end) >= gap:
            section_num += 1
            out.append(f"[Section {section_num}]")
        out.append(text)
        prev_end = end if prev_end is None else max(prev_end, end)

    return "\n".join(out) + "\n"


def estimate_duration(mp3_path):
    """Seconds, via ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", mp3_path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def demo():
    import sys
    import tempfile
    import types

    # --- to_sections: normal gap-separated song -> 2 sections ---
    result = {"segments": [
        {"start": 0.0, "end": 2.0, "text": "hello world"},
        {"start": 2.5, "end": 4.0, "text": "still going"},
        {"start": 10.0, "end": 12.0, "text": "new section starts"},
        {"start": 12.5, "end": 14.0, "text": "continues here"},
    ]}
    text = to_sections(result)
    assert text.count("[Section") == 2, text
    assert "[Intro]" not in text

    # --- leading silence -> [Intro] ---
    result_intro = {"segments": [{"start": 8.0, "end": 9.0, "text": "first words"}]}
    text_intro = to_sections(result_intro)
    assert text_intro.startswith("[Intro]"), text_intro
    assert text_intro.count("[Section") == 1

    # --- no gaps at all -> exactly one section ---
    result_one = {"segments": [
        {"start": 0.0, "end": 1.0, "text": "a"},
        {"start": 1.2, "end": 2.0, "text": "b"},
        {"start": 2.1, "end": 3.0, "text": "c"},
    ]}
    text_one = to_sections(result_one)
    assert text_one.count("[Section") == 1, text_one

    # --- empty/whitespace segments skipped ---
    result_blank = {"segments": [
        {"start": 0.0, "end": 1.0, "text": "kept"},
        {"start": 1.1, "end": 1.5, "text": "   "},
        {"start": 1.6, "end": 1.8, "text": ""},
        {"start": 1.9, "end": 2.5, "text": "also kept"},
    ]}
    text_blank = to_sections(result_blank)
    assert "kept" in text_blank and "also kept" in text_blank
    assert text_blank.count("[Section") == 1, text_blank

    # --- out-of-order segments don't crash, still group correctly ---
    result_shuffled = {"segments": [
        {"start": 12.5, "end": 14.0, "text": "continues here"},
        {"start": 0.0, "end": 2.0, "text": "hello world"},
        {"start": 10.0, "end": 12.0, "text": "new section starts"},
        {"start": 2.5, "end": 4.0, "text": "still going"},
    ]}
    text_shuffled = to_sections(result_shuffled)
    assert text_shuffled.count("[Section") == 2, text_shuffled
    assert text_shuffled.index("hello world") < text_shuffled.index("new section starts")

    # --- zero-length / inverted segments don't crash ---
    result_degenerate = {"segments": [
        {"start": 5.0, "end": 5.0, "text": "instant"},
        {"start": 6.0, "end": 5.5, "text": "inverted"},
    ]}
    to_sections(result_degenerate)  # just must not raise

    # --- empty input ---
    assert to_sections({"segments": []}) == ""

    # --- round-trip through build_storyboard.parse_sections ---
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, repo_root)
    from build_storyboard import parse_sections

    for r, expected_headers in (
        (result, 2), (result_intro, 2), (result_one, 1), (result_blank, 1), (result_shuffled, 2),
    ):
        t = to_sections(r)
        parsed = parse_sections(t)
        assert len(parsed) == expected_headers, (t, parsed)

    # --- estimate_duration, via a real ffmpeg-generated file ---
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "silence.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-t", "7.5", "-i", "anullsrc",
             "-c:a", "libmp3lame", path],
            capture_output=True, check=True,
        )
        dur = estimate_duration(path)
        assert abs(dur - 7.5) < 0.5, dur

    # --- available() never raises, even with torch/backends absent ---
    ok, msg = available()
    assert isinstance(ok, bool) and isinstance(msg, str)

    from contextlib import contextmanager

    @contextmanager
    def mock_modules(**mapping):
        """Install fake sys.modules entries; None forces ImportError on that name."""
        sentinel = object()
        saved = {name: sys.modules.get(name, sentinel) for name in mapping}
        sys.modules.update(mapping)
        try:
            yield
        finally:
            for name, v in saved.items():
                sys.modules.pop(name, None) if v is sentinel else sys.modules.__setitem__(name, v)
            _device_cache.clear()

    # no backends at all -> never raises, reports unusable
    with mock_modules(torch=None, faster_whisper=None, whisper=None):
        ok2, msg2 = available()
        assert isinstance(ok2, bool) and isinstance(msg2, str)
        assert ok2 is False

    # ctranslate2 absent/erroring -> device probe stays "cpu", never raises
    with mock_modules(ctranslate2=None):
        device, detail = _device("faster-whisper")
        assert device == "cpu", (device, detail)

    # ctranslate2 present, no CUDA device -> "cpu"
    fake_ct2_none = types.SimpleNamespace(get_cuda_device_count=lambda: 0)
    with mock_modules(ctranslate2=fake_ct2_none):
        device, detail = _device("faster-whisper")
        assert device == "cpu", (device, detail)

    # ctranslate2 present, reports a GPU -> "cuda", no torch involved at all
    fake_ct2_cuda = types.SimpleNamespace(get_cuda_device_count=lambda: 1)
    with mock_modules(torch=None, ctranslate2=fake_ct2_cuda):
        device, detail = _device("faster-whisper")
        assert device == "cuda" and "CTranslate2" in detail and "1 GPU" in detail, (device, detail)

    # end-to-end through available(): faster-whisper + simulated GPU
    fake_faster_whisper = types.ModuleType("faster_whisper")
    with mock_modules(faster_whisper=fake_faster_whisper, ctranslate2=fake_ct2_cuda):
        ok3, msg3 = available()
        assert ok3 is True and "device=cuda" in msg3 and "CTranslate2" in msg3, msg3

    # --- a full GPU falls back to CPU instead of failing the job -----------
    # This is the exact failure seen on cerberus: ComfyUI holds ~21.5 GB of the
    # 24 GB card, and every transcribe job died with a bare RuntimeError
    # "CUDA failed with error out of memory".
    class _Seg:
        start, end, text = 0.0, 1.0, "on cpu"

    class _FakeModel:
        def __init__(self, size, device=None, compute_type=None):
            if device == "cuda":
                raise RuntimeError("CUDA failed with error out of memory")
            self.device = device

        def transcribe(self, path, vad_filter=False):
            return iter([_Seg()]), types.SimpleNamespace(language="en")

    fake_fw = types.ModuleType("faster_whisper")
    fake_fw.WhisperModel = _FakeModel
    with tempfile.TemporaryDirectory() as d:
        mp3 = os.path.join(d, "s.mp3")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-t", "2", "-i", "anullsrc",
                        "-c:a", "libmp3lame", mp3], capture_output=True, check=True)
        with mock_modules(faster_whisper=fake_fw, ctranslate2=fake_ct2_cuda):
            _model_cache.clear()
            msgs = []
            out = transcribe(mp3, progress=msgs.append)
            assert out["device"] == "cpu", out
            assert out["text"] == "on cpu", out
            assert any("GPU is full" in m for m in msgs), msgs
            assert (("faster-whisper", MODEL_SIZE, "cuda")) not in _model_cache

        # a failure that is NOT about memory must still surface, not be masked
        class _Broken(_FakeModel):
            def __init__(self, size, device=None, compute_type=None):
                raise RuntimeError("model file is corrupt")

        fake_broken = types.ModuleType("faster_whisper")
        fake_broken.WhisperModel = _Broken
        with mock_modules(faster_whisper=fake_broken, ctranslate2=fake_ct2_cuda):
            _model_cache.clear()
            try:
                transcribe(mp3)
                raise AssertionError("a non-OOM error was swallowed")
            except RuntimeError as e:
                assert "corrupt" in str(e), e
    _model_cache.clear()

    print("lyrics.py OK")


if __name__ == "__main__":
    demo()
