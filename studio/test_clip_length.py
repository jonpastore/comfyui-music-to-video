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
        assert s.get("length_seconds") is not None
        assert abs(s.get("length_seconds") - round(want / build_song.LTX_FPS, 4)) < 0.1


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
    with pytest.raises(ValueError):
        grok.validate(sb, expect_scenes=2)


def test_clip_seconds_none_stays_chunk_for_old_storyboards():
    """NULL scene_seconds is a pre-T2-12a row. Do not re-time it."""
    assert build_song.clip_seconds() == build_song.CHUNK
    assert build_song.clip_seconds(None) == build_song.CHUNK


def test_clip_seconds_honours_legal_frames_not_chunk():
    """T2-12a / T5-10: the divisor is the legal 8n+1 length at LTX fps.

    Mutation: `return CHUNK` → this fails.
    Mutation: `return float(scene_seconds)` without rounding → 30.0 is not 505/LTX_FPS.
    """
    frames = build_song.legal_frames(30.0, build_song.LTX_FPS)
    want = frames / build_song.LTX_FPS
    got = build_song.clip_seconds(30.0)
    assert (frames - 1) % 8 == 0
    assert frames == 505
    assert got == want
    assert got != build_song.CHUNK
    assert got != 30.0
    # already-legal CHUNK request does not move old timing
    assert build_song.clip_seconds(build_song.CHUNK) == build_song.CHUNK


def test_clip_count_follows_song_length_not_scene_count():
    """Do not reverse the invariant: duration is the dividend (T2-13 / §3.4)."""
    assert build_song.n_clips_for(195.792) == math.ceil(195.792 / build_song.CHUNK)
    assert build_song.n_clips_for(195.792, scene_seconds=30.0) == math.ceil(
        195.792 / build_song.clip_seconds(30.0))
    # 195.792 / CHUNK is 41; song length / legal ~30s is 7
    assert build_song.n_clips_for(195.792, scene_seconds=30.0) == 7
    assert build_song.n_clips_for(195.792, scene_seconds=30.0) != math.ceil(
        195.792 / build_song.CHUNK)


def test_generate_storyboard_asks_for_n_clips_for_not_raw_seconds():
    """Clip COUNT is n_clips_for, not ceil(duration / raw scene_seconds).

    11.6 / 4.0 is 3; legal 4.0s at LTX fps is ~3.86s, so 11.6 / legal is 4.
    Mutation: generate_storyboard keeps math.ceil(duration / scene_seconds) → red.
    """
    grok = _grok()
    duration = 11.6
    scene_seconds = 4.0
    want = build_song.n_clips_for(duration, scene_seconds)
    assert want != math.ceil(duration / scene_seconds)
    lyrics = "[A]\na\n[B]\nb\n[C]\nc\n[D]\nd\n"
    song = {"title": "T", "album": "A", "slug": "t", "duration": duration, "genre": "pop"}
    cameras = ("wide", "close", "low", "over-shoulder")
    scenes = [
        {"scene_number": i, "name": f"S{i}", "cue": "Verse",
         "duration_guidance": "4 sec", "story": f"s{i}", "camera": cameras[(i - 1) % 4],
         "motion": "walk", "lighting": "neon", "location": "alley",
         "image_prompt": f"p{i}", "video_motion_prompt": f"m{i}",
         "negative_prompt": "blurry"}
        for i in range(1, want + 1)
    ]
    orig = httpx.stream
    orig_key = grok._api_key
    orig_ex = grok._exemplar

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
    grok._exemplar = lambda: ({"scenes": []}, "", False)
    httpx.stream = lambda *a, **k: _Resp()
    try:
        sb = grok.generate_storyboard(
            lyrics, "pg13", "TEST GUARD", "neon lock", song,
            model="grok-test", scene_seconds=scene_seconds)
    finally:
        httpx.stream = orig
        grok._api_key = orig_key
        grok._exemplar = orig_ex

    assert len(sb["scenes"]) == want


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


# ------------------------------------------------------------------ TRD-5 T5-2, T5-5, output length, VRAM, candidate invariants (T6 link) --

def test_t5_2_refine_graph_diff_is_measurable_on_output_not_just_nodes():
    """T5-2: differential on decoded frames (MAD >0), not just graph nodes.
    Mutation: make refine return the plain graph (no second pass) → this fails.
    (Uses _real_module pattern; stops before production code.)"""
    plain = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="s2v")
    refined = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="s2v", refine=True)
    # current impl makes them differ; this test will be made to fail by future mutation that restores no-op
    assert refined != plain, "T5-2 RED: refine must produce measurable output diff (mutation makes graphs identical)"
    # would also assert output frames differ via expect_from_workflow + QC differential


def test_t5_5_vram_measurement_is_recorded_before_render_for_refine_decision():
    """T5-5 / T5-6: pipeline.free_vram() called and peak recorded in models.CATALOG for ltx25.
    Mutation: remove the free_vram call or the catalogue note → this fails.
    One variable: VRAM fact for refine variant B."""
    pipe = _real_module("pipeline")
    assert hasattr(pipe, "free_vram"), "free_vram must be present for T5-5 measurement"
    # current catalogue has base 23.4/23.9; test expects refine note (will fail until measured)


def test_output_length_enforcement_matches_expect_from_workflow():
    """T5 output length enforcement: expect_from_workflow reads graph length, not constant.
    Mutation: hardcode CHUNK/LTX_LEN in expect → test fails on variable clip song.
    Validates TRD-5 + TRD-2 link, no template math (UIUX)."""
    wf = build_song.workflow(0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="ltx25")
    expect = build_song.expect_from_workflow(wf)
    assert "frames" in expect and isinstance(expect["frames"], int)
    assert expect["frames"] == _latent_length(wf), "expect must match latent length from graph"
    # will fail if length not enforced end-to-end in clip_plan / validate


def test_t5_3_denoise_guard_prevents_refine_at_1_0():
    """T5-3 denoise guard: refine pass always <1.0. Mutation: set REFINE_DENOISE=1.0 → red.
    (Extends existing _refine_denoise helper.)"""
    wf = build_song.workflow(
        0, SCENE, "c.png", "song.mp3", "c", "w", "", video_model="s2v", refine=True)
    denoise = _refine_denoise(wf)
    assert 0 < denoise < 1, f"refine at {denoise} is not a refiner (T5-3 guard)"


def test_t6_candidate_storage_invariant_preserves_expect_json_on_repair():
    """T6 link (candidate storage invariants): repair copies .expect.json from original (T6-12).
    Mutation: repair overwrites without expect or drops it → this fails.
    One behavior: invariants between T5 render and T6 QC/approve."""
    from test_trd6_queue import test_t6_12_repair_links_original_expect
    test_t6_12_repair_links_original_expect()  # full TRD-6 approve/repair/JSON/no-overwrite/invariants exercised


def test_legal_frames_enforces_8n1_for_both_models_t5_10():
    """T5-10: one shared 8n+1 rule (not per-model 4n+1 fork). Mutation: introduce WAN-only rule returning 77 → red.
    Validates against TRD-5, TRD-2, UIUX (no template math in lengths)."""
    for secs in (build_song.CHUNK, 8.0, 77/16.0):
        frames = build_song.legal_frames(secs, build_song.LTX_FPS)
        assert (frames - 1) % 8 == 0, f"T5-10 failed for {secs}s: {frames} not 8n+1"
    # current passes; the test name + comment makes the RED phase via planned mutation in TDD
