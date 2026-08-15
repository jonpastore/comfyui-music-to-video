"""T1-10: a fully-populated lane's filter expression is under 8 KB and renders.

docs/TRD-1 §5.1 / T1-10. MAX_POINTS bounds the stored curve. That cap is
not a cap if the emitted asendcmd string is over 8 KB or if ffmpeg refuses
it. Both halves: length, then mix_audio actually writes a file.

Asserted on automation.fragment (the lane expression) and through
mix_audio (the shared render entry), not _audio_chain.
"""
import os
import subprocess

import pytest

import automation
from conftest import _real_module


mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"

# Long enough that linear sampling hits SWEEP_MAX_STEPS. A 3 s ramp
# stays well under the bound and would not catch a cap that only works
# on short items.
_SPAN_S = 1800.0


def _full_lane(lo, hi):
    n = automation.MAX_POINTS
    return [(_SPAN_S * i / (n - 1), lo if i % 2 == 0 else hi) for i in range(n)]


def _sine(path, seconds=2, freq=1000):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
         "-c:a", "pcm_s16le", path],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def _item(audio, auto):
    return {"audio": audio, "transition": "cut", "secs": 0.0, "automation": auto}


@pytest.mark.parametrize("lane,lo,hi", [
    ("gain_db", automation.LANES["gain_db"]["lo"], automation.LANES["gain_db"]["hi"]),
    ("lowpass_hz", automation.LANES["lowpass_hz"]["lo"], automation.LANES["lowpass_hz"]["hi"]),
    ("highpass_hz", automation.LANES["highpass_hz"]["lo"], automation.LANES["highpass_hz"]["hi"]),
])
def test_t1_10_full_lane_filter_expr_under_8kb_and_renders(tmp_path, lane, lo, hi):
    assert automation.FILTER_EXPR_MAX_BYTES == 8 * 1024
    pts = _full_lane(lo, hi)
    assert len(pts) == automation.MAX_POINTS

    frag = automation.fragment(lane, pts)
    assert frag, f"{lane} emitted nothing"
    assert len(frag.encode("utf-8")) <= automation.FILTER_EXPR_MAX_BYTES, (
        f"{lane} filter expression is {len(frag.encode('utf-8'))} bytes; "
        f"cap is {automation.FILTER_EXPR_MAX_BYTES}")

    src = str(tmp_path / f"{lane}.wav")
    out = str(tmp_path / f"{lane}.mp3")
    _sine(src)
    mixer.mix_audio([_item(src, {"frags": [frag], "suppress_loudnorm": True})], out)
    assert os.path.isfile(out) and os.path.getsize(out) > 0, (
        f"ffmpeg refused the {lane} expression ({len(frag)} bytes)")
