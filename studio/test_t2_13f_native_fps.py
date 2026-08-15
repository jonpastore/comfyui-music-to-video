"""T2-13f: a clip's QC expectation is its native fps, not the song's.

docs/TRD-2 W1-5 / T2-13f: s2v renders 16.0 and LTX 16.8312. They differ
the moment a song mixes models, and normalisation happens at assembly
after the clip exists. TRD-3 T3-2 compares a clip against the workflow
that produced it. Comparing against the song's output fps flags every
correctly-rendered clip of the other model.

Asserted on a mixed-model pair: each clip passes its own fps check.
Mutation: clip_qc_expect copies song_fps onto the clip → the other
model flags.
Mutation: delete clip_qc_expect and pass the song fps as the clip
expect → this fails.
"""
import subprocess

from conftest import _real_module

import build_song
import qc


S2V_FPS = build_song.FPS
LTX_FPS = round(build_song.LTX25_FPS, 4)
assert S2V_FPS != LTX_FPS
assert abs(LTX_FPS - 16.8312) < 1e-6


def _mk(path, fps, frames=16):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate={fps}",
         "-frames:v", str(frames), "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


def _fps_row(findings):
    rows = [f for f in findings if f["check"] == "fps"]
    assert rows, findings
    return rows[0]


def _use_real_probe(monkeypatch):
    real_mixer = _real_module("mixer")
    assert real_mixer is not None, "real mixer.py failed to import"
    monkeypatch.setattr(qc, "mixer", real_mixer)


def test_t2_13f_clip_qc_expect_keeps_native_not_song_fps():
    """song_fps is assembly's target. It is not this clip's question."""
    assert hasattr(qc, "clip_qc_expect"), (
        "T2-13f lives on qc.clip_qc_expect so a clip cannot inherit "
        "the song's output fps")
    s2v = qc.clip_qc_expect({"fps": S2V_FPS, "frames": 77}, song_fps=LTX_FPS)
    ltx = qc.clip_qc_expect({"fps": LTX_FPS, "frames": 81}, song_fps=S2V_FPS)
    assert s2v["fps"] == S2V_FPS, s2v
    assert ltx["fps"] == LTX_FPS, ltx
    assert s2v["fps"] != ltx["fps"]
    absent = qc.clip_qc_expect({"frames": 77}, song_fps=LTX_FPS)
    assert "fps" not in absent, (
        "absent native fps must stay absent; inventing the song fps "
        "is the defect T2-13f exists to stop")


def test_t2_13f_mixed_s2v_ltx_each_pass_own_fps_song_fps_flags(
        tmp_path, monkeypatch):
    """Mixed s2v@16 / LTX@16.8312 pass native; song fps flags the other."""
    _use_real_probe(monkeypatch)
    s2v_path = _mk(str(tmp_path / "s2v.mp4"), S2V_FPS)
    ltx_path = _mk(str(tmp_path / "ltx.mp4"), LTX_FPS)

    s2v_expect = qc.clip_qc_expect({"fps": S2V_FPS, "latent_rule": False},
                                   song_fps=LTX_FPS)
    ltx_expect = qc.clip_qc_expect({"fps": LTX_FPS, "latent_rule": False},
                                   song_fps=S2V_FPS)

    s2v_native = _fps_row(qc.run(s2v_path, "clip", s2v_expect, song_fps=LTX_FPS))
    ltx_native = _fps_row(qc.run(ltx_path, "clip", ltx_expect, song_fps=S2V_FPS))
    assert s2v_native["verdict"] == qc.PASS, s2v_native
    assert ltx_native["verdict"] == qc.PASS, ltx_native
    assert abs(s2v_native["expected"] - S2V_FPS) <= qc.FPS_TOL, s2v_native
    assert abs(ltx_native["expected"] - LTX_FPS) <= qc.FPS_TOL, ltx_native

    s2v_vs_song = _fps_row(qc.run(s2v_path, "clip", {"fps": LTX_FPS}))
    ltx_vs_song = _fps_row(qc.run(ltx_path, "clip", {"fps": S2V_FPS}))
    assert s2v_vs_song["verdict"] == qc.FLAG, s2v_vs_song
    assert ltx_vs_song["verdict"] == qc.FLAG, ltx_vs_song
