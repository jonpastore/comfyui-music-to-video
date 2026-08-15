"""T8-14: song-editor predicted length equals rendered length.

docs/TRD-8 §6. The predicted length is the rendered length, to
mixer.SET_DURATION_TOLERANCE — imported, never restated (TRD-1 T1-7,
TRD-3 T3-11). Positive half: a real render emits a prediction first
and lands within the named constant. Vacuous if nothing renders or
nothing is predicted.
"""
import inspect
import json
import os
import subprocess
import tempfile

from fastapi.testclient import TestClient

from conftest import _real_module
import app as appmod
import automation
import db
import mixer as mixer_mod


mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"


def _mp3(path, seconds, freq=440):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi",
         "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
         "-c:a", "libmp3lame", "-b:a", "192k", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


def _song_with_audio(seconds=4.0):
    """Song whose mp3 is long enough for echo and probe to be meaningful."""
    fd, path = tempfile.mkstemp(suffix=".mp3", dir=db.DATA)
    os.close(fd)
    _mp3(path, seconds)
    sid = db.upsert_song(
        "t8-14-editor", title="T8-14 Song Editor Duration",
        duration=seconds, mp3_path=path)
    return sid, path


def _use_real_mixer(patch_stub):
    """conftest's mixer stub writes empty files; T8-14 needs a real mix."""
    patch_stub(
        "mixer",
        set_duration=mixer.set_duration,
        mix_audio=mixer.mix_audio,
        probe=mixer.probe,
    )


def test_t8_14_imports_named_tolerance_not_restated():
    """Two copies of 0.05 are the defect T1-7 / T3-11 exist to stop."""
    src = inspect.getsource(appmod.api_song_editor_render)
    assert "mixer.set_duration" in src
    assert "mixer.mix_audio" in src
    # Prediction is emitted before the mix: set_duration precedes mix_audio
    # in source order so a reverse call order fails this.
    assert src.index("mixer.set_duration") < src.index("mixer.mix_audio")
    assert mixer.SET_DURATION_TOLERANCE == mixer_mod.SET_DURATION_TOLERANCE
    assert mixer.SET_DURATION_TOLERANCE == 0.05
    this = open(__file__, encoding="utf-8").read()
    assert "mixer.SET_DURATION_TOLERANCE" in this
    assert "<= mixer.SET_DURATION_TOLERANCE" in this


def test_t8_14_render_emits_prediction_first_and_matches(patch_stub):
    """Positive half: real render returns a prediction, then a file whose
    probed length sits within SET_DURATION_TOLERANCE of that prediction.

    Echo is the duration-moving effect so a length-blind re-encode cannot
    pass by accident (effects.duration_delta).
    """
    _use_real_mixer(patch_stub)
    sid, src = _song_with_audio(4.0)
    echo = json.dumps({"echo_out": {"decay": 0.4, "delay": 500},
                       "loudnorm": False})
    item = automation.editor_item(sid)
    db.run("UPDATE set_items SET effects_json=? WHERE id=?", echo, item)

    with TestClient(appmod.app) as client:
        pred_r = client.get(f"/api/songs/{sid}/editor/duration")
        assert pred_r.status_code == 200, pred_r.text
        predicted = pred_r.json()["predicted"]
        assert isinstance(predicted, (int, float)) and predicted > 0

        # Echo must move the prediction off the bare probe length.
        bare = mixer.probe(src)["duration"]
        assert predicted >= bare + 0.4, (
            f"echo did not move prediction: bare={bare:.3f} predicted={predicted:.3f}")

        render = client.post(f"/api/songs/{sid}/editor/render")
        assert render.status_code == 200, render.text
        body = render.json()
        assert "predicted" in body, "render did not emit a prediction"
        assert abs(body["predicted"] - predicted) < 1e-9, (
            f"render prediction drifted from duration endpoint: "
            f"{body['predicted']} vs {predicted}")
        assert body.get("path") and os.path.isfile(body["path"]), body
        actual = mixer.probe(body["path"])["duration"]
        if "duration" in body:
            assert abs(body["duration"] - actual) <= 0.001, body

        gap = abs(actual - body["predicted"])
        assert gap <= mixer.SET_DURATION_TOLERANCE, (
            f"T8-14: predicted {body['predicted']:.3f}s rendered {actual:.3f}s "
            f"gap={gap:.3f}s (tol={mixer.SET_DURATION_TOLERANCE})")
