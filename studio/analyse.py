"""mp3 -> bpm, beat grid, musical key (Camelot) and energy, via librosa.

librosa is imported LAZILY, inside analyse() only -- never at module import
time -- because the test suite runs on the system python, which does not
have it installed. Only the studio's own deploy venv does (see
requirements.txt). Everything above analyse() is plain numpy, which the
system python does have, so demo() can exercise the real scoring logic
without needing librosa at all; it runs analyse() itself only if librosa
happens to be importable.

Key detection: mean chroma vector scored against the Krumhansl-Schmuckler
major/minor tone profiles at all 12 rotations, best correlation wins, then
converted to Camelot notation (e.g. "8A"). Downbeats are approximated as
every 4th beat starting from the strongest of the first four -- a guess, not
a claim, and stored as an editable offset for exactly that reason (see
SETS_MIXING_PLAN.md phase 2).
"""
import numpy as np

# Krumhansl-Schmuckler tone profiles. Index 0 = C, in semitone order.
_MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Camelot wheel, built from the circle of fifths rather than transcribed by
# hand: major keys advance one Camelot number per fifth, anchored on the one
# fixed real-world fact (C major = 8B), and each key's relative minor -- 3
# semitones down -- shares its number on the A side. Wrong-by-hand entries
# can't slip in; demo() checks the shape.
_CAMELOT = {}
for _n in range(12):
    _pc_major = (7 * _n) % 12                # each step is a fifth up from C (pc 0)
    _number = (_n + 7) % 12 + 1               # anchored so pc 0 (C) lands on 8
    _CAMELOT[(_pc_major, "major")] = f"{_number}B"
    _CAMELOT[((_pc_major - 3) % 12, "minor")] = f"{_number}A"
del _n, _pc_major, _number


def score_key(chroma_mean):
    """(pitch_class, mode, camelot) -- the best-correlated K-S profile.

    chroma_mean: 12 floats, index 0 = C, the mean chroma vector for a track.
    """
    best = (-2.0, 0, "major")
    for pc in range(12):
        for profile, mode in ((_MAJOR_PROFILE, "major"), (_MINOR_PROFILE, "minor")):
            score = np.corrcoef(chroma_mean, np.roll(profile, pc))[0, 1]
            if score > best[0]:
                best = (score, pc, mode)
    _, pc, mode = best
    return pc, mode, _CAMELOT[(pc, mode)]


def guess_downbeat_offset(onset_strengths):
    """Index (0-3) of the strongest beat among the first four -- the guessed
    bar-one. Editable afterward; see the module docstring."""
    window = np.asarray(onset_strengths)[:4]
    if window.size == 0:
        return 0
    return int(np.argmax(window))


def analyse(mp3_path, progress=None):
    """bpm, beat_grid (seconds), key (Camelot), energy (mean RMS) and a
    guessed downbeat_offset, for one mp3. Needs librosa."""
    def note(msg):
        if progress:
            progress(msg)

    import librosa

    note("loading audio")
    # default sr (22050): matches the measured tempo/beat-count on this box
    # (Nine Lives.mp3 -> 129.20 bpm, 1020 beats) and halves the load time
    # against loading at native rate.
    y, sr = librosa.load(mp3_path, mono=True)

    note("tracking beats")
    tempo, beat_times = librosa.beat.beat_track(y=y, sr=sr, units="time")
    tempo = float(np.asarray(tempo).reshape(-1)[0])
    beat_times = [float(t) for t in beat_times]

    note("detecting key")
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    _, _, camelot = score_key(chroma.mean(axis=1))

    note("measuring energy")
    energy = float(librosa.feature.rms(y=y).mean())

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    if beat_times and len(onset_env):
        beat_frames = librosa.time_to_frames(beat_times[:4], sr=sr)
        strengths = onset_env[np.clip(beat_frames, 0, len(onset_env) - 1)]
    else:
        strengths = np.array([])
    downbeat_offset = guess_downbeat_offset(strengths)

    note(f"done: {tempo:.1f} bpm, key {camelot}")
    return {"bpm": tempo, "key": camelot, "beat_grid": beat_times,
            "energy": energy, "downbeat_offset": downbeat_offset}


def demo():
    # --- Camelot table shape: 24 keys, all distinct, spot-checked against
    # the reference wheel (C major = 8B, its relative minor A minor = 8A) ---
    assert len(_CAMELOT) == 24, sorted(_CAMELOT.values())
    assert len(set(_CAMELOT.values())) == 24, "duplicate Camelot code"
    assert _CAMELOT[(0, "major")] == "8B", "C major must be 8B"
    assert _CAMELOT[(9, "minor")] == "8A", "A minor (relative of C) must be 8A"
    assert _CAMELOT[(7, "major")] == "9B", "G major must be 9B (a fifth up from C)"
    assert _CAMELOT[(2, "major")] == "10B", "D major must be 10B"

    # --- score_key recovers a profile handed to it verbatim, at every rotation ---
    for pc in range(12):
        got_pc, got_mode, code = score_key(np.roll(_MAJOR_PROFILE, pc))
        assert (got_pc, got_mode) == (pc, "major"), (pc, got_pc, got_mode)
        assert code == _CAMELOT[(pc, "major")]
    for pc in range(12):
        got_pc, got_mode, code = score_key(np.roll(_MINOR_PROFILE, pc))
        assert (got_pc, got_mode) == (pc, "minor"), (pc, got_pc, got_mode)
        assert code == _CAMELOT[(pc, "minor")]

    # --- guess_downbeat_offset: strongest of the first 4 wins; later beats ignored ---
    assert guess_downbeat_offset([1, 5, 2, 3, 100]) == 1, "must ignore beat 5+"
    assert guess_downbeat_offset([9, 1, 1, 1]) == 0
    assert guess_downbeat_offset([]) == 0

    # --- analyse() itself needs librosa. Prove it on real audio with the
    # verification venv (see the task's PROVE IT RUNS instructions); here,
    # skip gracefully if this interpreter doesn't have it -- exactly how
    # lyrics.py's demo() treats an absent whisper backend. ---
    try:
        import librosa  # noqa: F401
    except ImportError:
        print("analyse.py OK (librosa not installed on this interpreter -- "
              "the scoring/Camelot logic above is checked without it; run "
              "against the studio venv for the full pipeline)")
        return

    import os
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "tone.mp3")
        # A pure tone has no rhythmic content -- this only proves the pipeline
        # decodes and runs end to end without crashing (bpm may come back 0
        # and beat_grid empty, and that's fine here). The real bpm/key claim
        # is proven on a real track, per the task's own instructions, not on
        # a synthetic one.
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-t", "5", "-i",
             "sine=frequency=440:sample_rate=22050", "-c:a", "libmp3lame", path],
            capture_output=True, check=True)
        result = analyse(path)
        assert isinstance(result["bpm"], float), result
        assert isinstance(result["beat_grid"], list)
        assert isinstance(result["key"], str) and result["key"][-1] in "AB", result["key"]
        assert isinstance(result["energy"], float)
        assert isinstance(result["downbeat_offset"], int)
        assert 0 <= result["downbeat_offset"] <= 3

    print("analyse.py OK")


if __name__ == "__main__":
    demo()
