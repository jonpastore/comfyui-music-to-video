"""T1-13 / T1-14 / T1-15 waveform peaks as data.

mixer.waveform_png() is a picture. The timeline needs numbers: a request
for zoom level z returns at most PEAKS_MAX_POINTS (2048) min/max pairs,
and at least one pair when the song has audio. Decimation is a min/max
reduce over the same span, not a resample (docs/TRD-1 §6.1).

Both halves or neither: return [] passes the upper bound and makes T1-14
vacuous over zero buckets. T1-15: no audio / missing mp3 is empty pairs
plus a reason, not a flat line. A zero-length envelope with no reason
fails; silence stays a flat envelope.

The real mixer is stubbed for the rest of the suite (ffmpeg). These
tests load it under a private name, the same way test_clip_length.py
reaches grok.
"""
from conftest import _real_module


def _mixer():
    mx = _real_module("mixer")
    assert mx is not None, "mixer.py failed to import"
    return mx


def test_t1_13_peaks_max_points_is_2048():
    assert _mixer().PEAKS_MAX_POINTS == 2048


def test_t1_13_long_signal_returns_at_most_2048_pairs_at_any_z():
    mx = _mixer()
    samples = [0.0] * 100_000
    samples[50_000] = 0.8
    samples[50_001] = -0.6
    for z in (0, 1, 2, 8, 99):
        pairs = mx.peaks(samples, z=z)
        assert 1 <= len(pairs) <= mx.PEAKS_MAX_POINTS, (z, len(pairs))
        assert all(len(p) == 2 for p in pairs), z


def test_t1_13_audio_returns_at_least_one_pair():
    pairs = _mixer().peaks([0.1, -0.2, 0.3], z=0)
    assert len(pairs) >= 1
    assert len(pairs[0]) == 2


def test_t1_13_empty_is_not_enough_for_audio():
    """Bounded above only, return [] would pass T1-13's cap. A song that
    has samples must not take that escape (TRD-1 §6.1, both halves)."""
    pairs = _mixer().peaks([0.0], z=0)
    assert pairs, "a song with audio must return at least one pair"


def test_t1_14_global_extrema_survive_decimation():
    """A waveform that under-reports a peak lies about where the loud
    part is. First-sample / mean resample would drop a mid-bucket spike."""
    mx = _mixer()
    n = 4096
    samples = [0.0] * n
    samples[7] = 0.91    # second sample of a 2-sample bucket at 2048
    samples[9] = -0.73
    pairs = mx.peaks(samples, z=0)
    assert max(p[1] for p in pairs) == 0.91
    assert min(p[0] for p in pairs) == -0.73


def test_t1_15_no_audio_is_empty_with_reason():
    """A song with no mp3 is not silence. Empty pairs plus a reason,
    or the client draws a flat line (docs/TRD-1 T1-15)."""
    env = _mixer().peaks_from_path(None)
    assert env["pairs"] == []
    assert env.get("reason"), "a zero-length envelope with no reason is a flat line"
    assert env["reason"] == "no_audio"


def test_t1_15_missing_mp3_is_empty_with_reason():
    env = _mixer().peaks_from_path("/no/such/file.mp3")
    assert env["pairs"] == []
    assert env.get("reason"), "a zero-length envelope with no reason is a flat line"
    assert env["reason"] == "missing"


def test_t1_15_empty_path_is_empty_with_reason():
    env = _mixer().peaks_from_path("")
    assert env["pairs"] == []
    assert env.get("reason"), "a zero-length envelope with no reason is a flat line"
    assert env["reason"] == "no_audio"


def test_t1_15_unreadable_file_is_empty_with_reason(tmp_path):
    junk = tmp_path / "not-audio.mp3"
    junk.write_bytes(b"this is not audio")
    env = _mixer().peaks_from_path(str(junk))
    assert env["pairs"] == []
    assert env.get("reason"), "a zero-length envelope with no reason is a flat line"
    assert env["reason"] == "unreadable"


def test_t1_15_silence_is_a_flat_line_not_empty():
    """Silence has audio. It must stay a flat envelope, not the empty
    result, or T1-15 cannot tell the two apart."""
    pairs = _mixer().peaks([0.0] * 8, z=0)
    assert pairs
    assert all(p == [0.0, 0.0] for p in pairs)


def test_t1_14_per_bucket_equals_full_resolution_minmax():
    mx = _mixer()
    samples = [((i * 37) % 200 - 100) / 100.0 for i in range(5000)]
    pairs = mx.peaks(samples, z=0)
    n = len(samples)
    n_buckets = len(pairs)
    assert 1 <= n_buckets <= mx.PEAKS_MAX_POINTS
    for i, pair in enumerate(pairs):
        start = i * n // n_buckets
        end = (i + 1) * n // n_buckets
        span = samples[start:end]
        assert pair[0] == min(span), (i, pair, min(span))
        assert pair[1] == max(span), (i, pair, max(span))
