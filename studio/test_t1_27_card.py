"""T1-27 / T1-28 interstitial card.

docs/TRD-1 §8b: a title/branding card is its own timeline item with its
own duration — [song A][ MEOW P — 3s ][song B]. It is a set_items row
whose song_id is NULL. mixer.set_duration() prices it; omitting it does
not change the prediction. A comment in set_edit.html is not this.
"""
import os
import subprocess

import pytest

from conftest import _real_module


mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"

_CARD_SECS = 3.0
_GRID = [i * 0.5 for i in range(17)]


def _ffmpeg(args):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *args],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r


def _wav(path, seconds, freq):
    _ffmpeg([
        "-f", "lavfi",
        "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
        "-c:a", "pcm_s16le", path,
    ])


def _mp4(path, seconds, colour, freq, fps=30):
    _ffmpeg([
        "-f", "lavfi", "-i", f"color=c={colour}:s=320x240:r={fps}:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-shortest", path,
    ])


def _png(path, colour="white"):
    _ffmpeg([
        "-f", "lavfi", "-i", f"color=c={colour}:s=80x40:d=1",
        "-frames:v", "1", path,
    ])


def _song(path, transition="cut"):
    return {"audio": path, "video": path, "transition": transition,
            "secs": 0.0, "hold": 0.0}


def _card(path, duration=_CARD_SECS, transition="cut"):
    return {"kind": "card", "card": path, "duration": duration,
            "transition": transition, "secs": 0.0, "hold": 0.0}


def test_t1_27_inserting_a_card_adds_its_duration_omitting_it_does_not(tmp_path):
    """The differential §8b is for: one variable, the card, moves the price."""
    a = str(tmp_path / "a.wav")
    b = str(tmp_path / "b.wav")
    card_png = str(tmp_path / "card.png")
    _wav(a, 2.0, 440)
    _wav(b, 2.0, 550)
    _png(card_png)

    songs = [_song(a), _song(b)]
    with_card = [_song(a), _card(card_png, _CARD_SECS), _song(b)]
    without = list(songs)

    base = mixer.set_duration(without, key="audio")
    priced = mixer.set_duration(with_card, key="audio")
    again = mixer.set_duration(without, key="audio")

    assert abs(priced - base - _CARD_SECS) < 1e-6, (
        f"card did not add {_CARD_SECS}s: base={base:.3f} priced={priced:.3f}")
    assert abs(again - base) < 1e-6, (
        f"omitting the card still moved the prediction: {base:.3f} -> {again:.3f}")


def test_t1_27_is_card_is_not_a_comment():
    """A HTML comment cannot satisfy is_card. The mixer has to name the kind."""
    assert mixer.is_card({"kind": "card", "duration": 3.0})
    assert mixer.is_card({"card": "/tmp/x.png", "duration": 3.0})
    assert not mixer.is_card({"audio": "a.wav", "transition": "cut"})
    assert not mixer.is_card({"brand_path": "/tmp/mark.png"})


def test_t1_28_card_first_last_and_between_beatmatched_songs(tmp_path):
    """Join arithmetic must not assume a neighbouring song exists."""
    a = str(tmp_path / "a.wav")
    b = str(tmp_path / "b.wav")
    card_png = str(tmp_path / "card.png")
    _wav(a, 4.0, 440)
    _wav(b, 4.0, 550)
    _png(card_png)
    card = _card(card_png, 1.5)
    song_a = {**_song(a), "beatmatch": True, "beat_grid": list(_GRID),
              "downbeat_offset": 0, "bpm": 120.0, "transition": "fade", "secs": 1.0}
    song_b = {**_song(b), "beat_grid": list(_GRID),
              "downbeat_offset": 0, "bpm": 128.0}

    first = mixer.set_duration([card, _song(a)], key="audio")
    last = mixer.set_duration([_song(a), card], key="audio")
    mid = mixer.set_duration([song_a, card, song_b], key="audio")

    assert first > 0 and last > 0 and mid > 0
    assert first >= 1.5
    assert last >= 1.5
    no_card = mixer.set_duration([song_a, song_b], key="audio")
    assert mid > no_card


@pytest.mark.slow
def test_t1_27_mix_audio_render_matches_priced_card(tmp_path):
    a = str(tmp_path / "a.wav")
    b = str(tmp_path / "b.wav")
    card_png = str(tmp_path / "card.png")
    _wav(a, 2.0, 440)
    _wav(b, 2.0, 550)
    _png(card_png)
    items = [_song(a), _card(card_png, 1.0), _song(b)]
    pred = mixer.set_duration(items, key="audio")
    out = str(tmp_path / "set.mp3")
    mixer.mix_audio(items, out)
    actual = mixer.probe(out)["duration"]
    gap = abs(actual - pred)
    assert gap <= mixer.SET_DURATION_TOLERANCE, (
        f"T1-27 audio: predicted {pred:.3f}s rendered {actual:.3f}s "
        f"gap={gap:.3f}s (tol={mixer.SET_DURATION_TOLERANCE})")


@pytest.mark.slow
def test_t1_27_render_set_matches_priced_card(tmp_path):
    a = str(tmp_path / "a.mp4")
    b = str(tmp_path / "b.mp4")
    card_png = str(tmp_path / "card.png")
    _mp4(a, 2.0, "red", 440)
    _mp4(b, 2.0, "blue", 550)
    _png(card_png, "white")
    items = [
        {"video": a, "transition": "cut", "secs": 0.0},
        _card(card_png, 1.0),
        {"video": b, "transition": "cut", "secs": 0.0},
    ]
    pred = mixer.set_duration(items, key="video")
    out = str(tmp_path / "set.mp4")
    mixer.render_set(items, out)
    actual = mixer.probe(out)["duration"]
    gap = abs(actual - pred)
    assert gap <= mixer.SET_DURATION_TOLERANCE, (
        f"T1-27 video: predicted {pred:.3f}s rendered {actual:.3f}s "
        f"gap={gap:.3f}s (tol={mixer.SET_DURATION_TOLERANCE})")
    def _rgb(path, t):
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True)
        assert r.returncode == 0, r.stderr
        px = r.stdout
        n = max(1, len(px) // 3)
        return (sum(px[0::3]) / n, sum(px[1::3]) / n, sum(px[2::3]) / n)
    on_card = _rgb(out, 2.4)
    on_song = _rgb(out, 0.4)
    assert sum(on_card) > sum(on_song) + 40, (
        f"card never reached the picture: card={on_card} song={on_song}")
