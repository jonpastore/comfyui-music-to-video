"""T2-12a legal 8n+1 rounding and T5-1 / T5-3 / T5-4 / T5-10 refine.

Asserted through the public functions the routes actually call
(docs/TRD-6 T6-A10): build_song.legal_frames, grok.generate_storyboard /
grok.validate, and build_song.workflow -- not an inner helper those
never reach.
"""
import json
import math
import os
import sys

import httpx
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import build_song
from conftest import _real_module


SCENE = {
    "scene_number": 1, "name": "s", "camera": "wide", "lighting": "neon",
    "video_motion_prompt": "she walks", "negative_prompt": "",
    "duration_guidance": "5 sec", "image_prompt": "a rooftop",
}


def _grok():
    return _real_module("grok")


# ------------------------------------------------------------------ T2-12a --

def test_legal_frames_is_8n1_at_the_clip_fps():
    """Nearest 8n+1. 27.97s (195.792/7) is the hole §3.4 opened."""
    frames = build_song.legal_frames(195.792 / 7, build_song.LTX_FPS)
    assert isinstance(frames, int)
    assert frames >= 9
    assert (frames - 1) % 8 == 0


def test_legal_frames_half_to_even_77_lands_on_81():
    """77 is equidistant from 73 and 81; DDD-1-3 §5.5 pins the tie-break."""
    assert build_song.legal_frames(77 / 16.0, 16.0) == 81
    assert build_song.legal_frames(build_song.CHUNK, 16.0) == 81


def test_legal_frames_already_legal_is_unchanged():
    assert build_song.legal_frames(build_song.CHUNK, build_song.LTX_FPS) == 81
    assert build_song.legal_frames(81 / build_song.LTX_FPS, build_song.LTX_FPS) == 81
    assert build_song.legal_frames(9 / 16.0, 16.0) == 9


def test_legal_frames_rejects_non_positive():
    with pytest.raises(ValueError):
        build_song.legal_frames(0, 16.0)
    with pytest.raises(ValueError):
        build_song.legal_frames(-1, 16.0)
    with pytest.raises(ValueError):
        build_song.legal_frames(4.0, 0)
    with pytest.raises(ValueError):
        build_song.legal_frames(float("nan"), 16.0)


def test_generate_storyboard_records_the_rounded_length():
    """Storyboard arithmetic and the renderer share one number (T2-12a)."""
    grok = _grok()
    want = build_song.legal_frames(8.0, build_song.LTX_FPS)
    lyrics = "[A]\na\n[B]\nb\n[C]\nc\n[D]\nd\n[E]\ne\n"
    song = {"title": "T", "album": "A", "slug": "t", "duration": 16.0, "genre": "pop"}
    scenes = [
        {"scene_number": 1, "name": "Verse 1", "cue": "Verse",
         "duration_guidance": "4-8 sec", "story": "s1", "camera": "wide",
         "motion": "walk", "lighting": "neon", "location": "alley",
         "image_prompt": "a rooftop 1", "video_motion_prompt": "m1",
         "negative_prompt": "blurry"},
        {"scene_number": 2, "name": "Chorus 1", "cue": "Chorus",
         "duration_guidance": "4-8 sec", "story": "s2", "camera": "close",
         "motion": "walk", "lighting": "amber", "location": "roof",
         "image_prompt": "a rooftop 2", "video_motion_prompt": "m2",
         "negative_prompt": "blurry"},
    ]
    orig = httpx.stream
    orig_key = grok._api_key

    class _Resp:
        status_code = 200

        def iter_lines(self):
            body = json.dumps({"scenes": scenes})
            yield "data: " + json.dumps({"choices": [{"delta": {"content": body}}]})
            yield "data: [DONE]"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    grok._api_key = lambda: "test-key"
    httpx.stream = lambda *a, **k: _Resp()
    try:
        sb = grok.generate_storyboard(
            lyrics, "pg13", "TEST GUARD", "neon lock", song,
            model="grok-test", scene_seconds=8.0)
    finally:
        httpx.stream = orig
        grok._api_key = orig_key

    # song LENGTH is the clip-count source: 16s / 8s = 2, not 5 lyric sections
    assert len(sb["scenes"]) == 2
    for s in sb["scenes"]:
        assert s["frames"] == want, s
        assert (s["frames"] - 1) % 8 == 0
        assert s["length_seconds"] == pytest.approx(round(want / build_song.LTX_FPS, 4))


def test_validate_rejects_a_non_8n1_requested_length():
    """Illegal frames fail in planning, not at the sampler."""
    grok = _grok()
    lyrics = "[Verse]\nline\n[Chorus]\nline\n"
    song = {"title": "T", "album": "A", "slug": "t", "duration": 16.0, "genre": "pop"}
    scenes = [
        {"scene_number": 1, "name": "V", "cue": "Verse",
         "duration_guidance": "4-8 sec", "story": "s1", "camera": "wide",
         "motion": "walk", "lighting": "neon", "location": "a",
         "image_prompt": "p1", "video_motion_prompt": "m1",
         "negative_prompt": "x"},
        {"scene_number": 2, "name": "C", "cue": "Chorus",
         "duration_guidance": "4-8 sec", "story": "s2", "camera": "close",
         "motion": "walk", "lighting": "amber", "location": "b",
         "image_prompt": "p2", "video_motion_prompt": "m2",
         "negative_prompt": "x"},
    ]
    sb = grok._compose(song, "pg13", "g", "note", lyrics, scenes, 2, 8.0)
    grok.validate(sb, expect_scenes=2)
    sb["scenes"][0]["frames"] = 77
    with pytest.raises(ValueError, match=r"8n\+1"):
        grok.validate(sb, expect_scenes=2)


def test_clip_count_follows_song_length_not_scene_count():
    """Do not reverse the invariant: duration is the dividend (T2-13 / §3.4)."""
    assert build_song.n_clips_for(195.792) == math.ceil(195.792 / build_song.CHUNK)
    assert build_song.n_clips_for(195.792, scene_seconds=30.0) == math.ceil(
        195.792 / build_song.clip_seconds(30.0))
    # renderer still builds CHUNK clips -- honouring 30s here is T2-13a, not this
    assert build_song.clip_seconds(30.0) == build_song.CHUNK


# ------------------------------------------------------------------ T5-1 --

def _wan_unets(wf):
    return [n["inputs"].get("unet_name", "") for n in wf.values()
            if "unet_name" in (n.get("inputs") or {})
            and "wan" in n["inputs"]["unet_name"].lower()]


def test_refine_ltx25_adds_a_second_pass():
    """Mutation: restore the LTX early return → this goes red (T5-1)."""
    plain = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="ltx25")
    refined = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="ltx25", refine=True)
    assert refined != plain
    extra = set(refined) - set(plain)
    assert extra, "refine must add nodes; an identical graph is the silent no-op"
    assert any(n["class_type"] == "SplitSigmasDenoise" for n in refined.values())
    split = next(n for n in refined.values() if n["class_type"] == "SplitSigmasDenoise")
    assert 0 < split["inputs"]["denoise"] < 1
    # second sampler, reusing guider 17, on the VIDEO latent (not the AV joint)
    second = next(
        n for n in refined.values()
        if n["class_type"] == "SamplerCustomAdvanced"
        and n["inputs"].get("latent_image") != ["16", 0])
    assert second["inputs"]["guider"] == ["17", 0]
    src = refined[second["inputs"]["latent_image"][0]]["class_type"]
    assert src == "LTXVSeparateAVLatent", src
    refine_id = next(
        k for k, n in refined.items()
        if n["class_type"] == "SamplerCustomAdvanced"
        and n["inputs"].get("latent_image") != ["16", 0])
    cv = next(n for n in refined.values() if n["class_type"] == "CreateVideo")
    decode = refined[cv["inputs"]["images"][0]]
    assert decode["class_type"] == "VAEDecode"
    assert decode["inputs"]["samples"] == [refine_id, 0]
    assert not _wan_unets(refined), "do not hand an LTX latent to WAN"


def test_refine_ltx_adds_a_second_pass_or_raises():
    plain = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="ltx")
    try:
        refined = build_song.workflow(
            0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="ltx", refine=True)
    except ValueError as e:
        assert e.args and e.args[0], "raise must name the reason"
        return
    assert refined != plain
    assert set(refined) - set(plain)
    assert not _wan_unets(refined), "do not hand an LTX latent to WAN"


def _refine_denoise(wf):
    """Denoise on the refine pass, read off the graph (not REFINE_DENOISE)."""
    for n in wf.values():
        if n.get("class_type") == "SplitSigmasDenoise":
            return n["inputs"]["denoise"]
    for n in wf.values():
        if n.get("class_type") == "KSampler" and n["inputs"].get("seed", 0) >= 2000:
            return n["inputs"]["denoise"]
    raise AssertionError("no refine-pass denoise node on the graph")


def _latent_length(wf):
    for n in wf.values():
        ins = n.get("inputs") or {}
        if all(k in ins for k in ("length", "width", "height")) and isinstance(ins["length"], int):
            return ins["length"]
    raise AssertionError("no latent length node on the graph")


# ------------------------------------------------------------------ T5-3 --

@pytest.mark.parametrize("video_model", ["ltx25", "s2v"])
def test_t5_3_refine_denoise_is_below_one(video_model):
    """Mutation: denoise=1.0 on the refine node → this goes red (T5-3)."""
    wf = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "",
        video_model=video_model, refine=True)
    denoise = _refine_denoise(wf)
    assert 0 < denoise < 1, f"{video_model}: a refiner at denoise {denoise} is not a refiner"


def test_t5_3_ltx_refine_denoise_is_below_one_or_raises():
    try:
        wf = build_song.workflow(
            0, SCENE, "c.png", "song.mp3", "c", "w", "",
            video_model="ltx", refine=True)
    except ValueError as e:
        assert e.args and e.args[0], "raise must name the reason"
        return
    denoise = _refine_denoise(wf)
    assert 0 < denoise < 1, f"ltx: a refiner at denoise {denoise} is not a refiner"


# ------------------------------------------------------------------ T5-4 --

@pytest.mark.parametrize("video_model", ["ltx25", "s2v"])
def test_t5_4_refine_does_not_overwrite_unrefined_output(video_model):
    """T5-4 / T6-A5: new decode. Mutation: rewire the original VAEDecode
    in place → this goes red."""
    plain = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model=video_model)
    refined = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "",
        video_model=video_model, refine=True)

    plain_decodes = {k: n["inputs"]["samples"] for k, n in plain.items()
                     if n["class_type"] == "VAEDecode"}
    refined_decodes = {k: n for k, n in refined.items()
                       if n["class_type"] == "VAEDecode"}
    extra = set(refined_decodes) - set(plain_decodes)
    assert extra, f"{video_model}: refine must add a decode, not reuse the unrefined one"
    for k, samples in plain_decodes.items():
        assert k in refined_decodes, f"{video_model}: unrefined decode {k} was deleted"
        assert refined_decodes[k]["inputs"]["samples"] == samples, (
            f"{video_model}: refine overwrote unrefined decode {k}")

    cv = next(n for n in refined.values() if n["class_type"] == "CreateVideo")
    out_id = cv["inputs"]["images"][0]
    assert out_id in extra, f"{video_model}: CreateVideo still reads the unrefined decode"


def test_t5_4_main_save_prefix_is_a_new_file(tmp_path, monkeypatch):
    """T5-4 through main() (T6-A10): --refine writes clip_NNN_refined."""
    monkeypatch.setattr(build_song, "audio_duration", lambda p: build_song.CHUNK)
    sb = {
        "scenes": [dict(SCENE, scene_number=1)],
        "character_reference": "c",
        "album_world_reference": "w",
    }
    storyboard = tmp_path / "sb.json"
    storyboard.write_text(json.dumps(sb))
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"x")

    def _write(refine, outdir):
        argv = [
            "build_song.py", "--storyboard", str(storyboard),
            "--audio", str(audio), "--slug", "t", "--outdir", str(outdir),
            "--video-model", "ltx25",
        ]
        if refine:
            argv.append("--refine")
        monkeypatch.setattr(sys, "argv", argv)
        build_song.main()

    plain_dir = tmp_path / "plain"
    ref_dir = tmp_path / "ref"
    _write(False, plain_dir)
    _write(True, ref_dir)

    def _prefix(d):
        wf = json.loads((d / "clip_000.json").read_text())
        return next(n["inputs"]["filename_prefix"] for n in wf.values()
                    if n.get("class_type") == "SaveVideo")

    assert _prefix(plain_dir) == "t/clip_000"
    assert _prefix(ref_dir) == "t/clip_000_refined"
    assert _prefix(plain_dir) != _prefix(ref_dir)


# ------------------------------------------------------------------ T5-10 --

def test_t5_10_legal_frames_is_one_8n1_rule_for_ltx_and_wan():
    """T5-10: frames ≡ 1 (mod 8) serves both. Mutation: a WAN-only 4n+1
    helper that returns 77 goes red."""
    for seconds, fps in (
        (build_song.CHUNK, build_song.LTX_FPS),
        (build_song.CHUNK, build_song.FPS),
        (8.0, build_song.LTX_FPS),
        (8.0, build_song.FPS),
        (77 / 16.0, 16.0),
        (4.8125, 16.0),
    ):
        frames = build_song.legal_frames(seconds, fps)
        assert (frames - 1) % 8 == 0, (seconds, fps, frames)
        assert (frames - 1) % 4 == 0, (seconds, fps, frames)
        assert frames >= 9

    # 77 is WAN-legal (4n+1) but the shared rule rounds it to 81
    assert build_song.legal_frames(77 / 16.0, 16.0) == 81

    ltx = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="ltx25")
    wan = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="s2v")
    ltx_len = _latent_length(ltx)
    wan_len = _latent_length(wan)
    # EmptyLTXVLatentVideo is step 8
    assert (ltx_len - 1) % 8 == 0, ltx_len
    # WanSoundImageToVideo is step 4; every 8n+1 is also 4n+1
    assert (wan_len - 1) % 4 == 0, wan_len
    planned = build_song.legal_frames(build_song.CHUNK, build_song.LTX_FPS)
    assert (planned - 1) % 8 == 0
    assert (planned - 1) % 4 == 0
    # same function, both families -- not a per-model fork
    assert build_song.legal_frames(ltx_len / build_song.LTX_FPS, build_song.LTX_FPS) == ltx_len
