"""T1-5: off-grid join — video nearest frame, audio exact second.

docs/TRD-1 §4.3: a transition placed at a time that is not a frame
boundary renders with the video cut on the nearest frame and the audio
crossfade at the exact second, and the API reports the rounding delta
for that join. A delta of zero on a deliberately off-grid time is a
failure, not a pass.

Rounding lives on mixer.frame_round (T1-6 already owns the sum bound).
This slice asserts the filter graph uses it for video only.
"""
from fastapi.testclient import TestClient

from conftest import _real_module
import app as appmod
from test_app import _upload_song


mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"

# 30 fps. First item ends at 2.01 s → 60.3 frames.
# Overlap 0.5 s: exact offset 1.51 s (45.3 frames).
# Nearest frame for the join start: 1.5 s. Truncation of 1.51 is also 1.5
# at integer fps — use 2.02 so nearest and truncation disagree.
# 2.02 s duration, 0.5 s fade → offset 1.52 s = 45.6 frames.
# nearest → 46/30 = 1.5333…; truncation → 45/30 = 1.5.
_FPS = 30.0
_DUR = 2.02
_SECS = 0.5
_EXACT_OFFSET = _DUR - _SECS          # 1.52
_NEAREST_OFFSET = 46 / _FPS           # 1.5333…
_TRUNC_OFFSET = int(_EXACT_OFFSET * _FPS) / _FPS  # 1.5


def test_t1_5_frame_round_off_grid_nonzero():
    """Off-grid t has a non-zero delta; truncation is not nearest."""
    rounded, delta = mixer.frame_round(_EXACT_OFFSET, _FPS)
    assert abs(rounded - _NEAREST_OFFSET) < 1e-12, rounded
    assert abs(delta) > 1e-12, "delta of zero on a deliberately off-grid time"
    assert abs(rounded - _TRUNC_OFFSET) > 1e-12, "truncation is not nearest"
    on_t, on_d = mixer.frame_round(2.0, _FPS)
    assert on_t == 2.0 and on_d == 0.0


def test_t1_5_video_cut_nearest_audio_exact():
    """xfade offset is nearest frame; acrossfade stays on the stored second.

    Using the exact second for video, or truncating, turns this red.
    """
    lines, _, _, _, _ = mixer._build_render_set_filter(
        [{"has_audio": True}, {"has_audio": True}],
        [_DUR, 2.0],
        [{"transition": "fade", "secs": _SECS},
         {"transition": "cut", "secs": 0.0}],
        320, 240, _FPS)
    joined = "\n".join(lines)

    v_want = (
        f"xfade=transition=fade:duration={_SECS:.3f}"
        f":offset={_NEAREST_OFFSET:.3f}"
    )
    v_exact = (
        f"xfade=transition=fade:duration={_SECS:.3f}"
        f":offset={_EXACT_OFFSET:.3f}"
    )
    v_trunc = (
        f"xfade=transition=fade:duration={_SECS:.3f}"
        f":offset={_TRUNC_OFFSET:.3f}"
    )
    assert v_want in joined, joined
    assert v_exact not in joined, joined
    assert v_trunc not in joined, joined
    assert f"acrossfade=d={_SECS:.3f}" in joined, joined
    # Audio duck/acrossfade must not carry the rounded video offset.
    for ln in joined.splitlines():
        if "acrossfade" in ln or "afade" in ln:
            assert f"{_NEAREST_OFFSET:.3f}" not in ln, ln

    report = mixer.rounding_report(
        [{"id": 1, "duration": _DUR, "transition": "fade", "secs": _SECS},
         {"id": 2, "duration": 2.0, "transition": "cut", "secs": 0.0}],
        _FPS)
    assert len(report["joins"]) == 1, report
    j = report["joins"][0]
    assert abs(j["t"] - _EXACT_OFFSET) < 1e-12, j
    assert abs(j["delta"]) > 1e-12, j
    assert abs(j["t_rounded"] - _NEAREST_OFFSET) < 1e-12, j


def test_t1_5_api_reports_nonzero_delta_for_off_grid_join():
    """GET /api/sets/{id} carries per-join delta. Zero on off-grid fails."""
    with TestClient(appmod.app) as client:
        songs = [_upload_song(client, f"T1-5 {n}") for n in ("A", "B")]
        created = client.post("/api/sets", json={"name": "T1-5 Off-grid",
                                                 "mode": "audio"})
        assert created.status_code == 200, created.text
        set_id = created.json()["set"]["id"]
        for song in songs:
            added = client.post(
                f"/api/sets/{set_id}/items",
                json={"song_id": song["id"], "transition": "cut", "secs": 0})
            assert added.status_code == 200, added.text

        # Force an off-grid first-item length via duration on the model path
        # that set_detail already uses (probe length). Song uploads are short
        # and on-grid enough; the pure report above owns the 1.52 s case.
        # Here: two items → one join; any real duration yields a rounding
        # object. Off-grid is forced by setting out_secs on the first item.
        import db
        first = db.one(
            "SELECT * FROM set_items WHERE set_id=? ORDER BY position", set_id)
        db.run(
            "UPDATE set_items SET out_secs=?, transition=?, secs=? WHERE id=?",
            _DUR, "fade", _SECS, first["id"])

        r = client.get(f"/api/sets/{set_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        rounding = body.get("rounding")
        assert rounding is not None, body
        joins = rounding.get("joins") or []
        assert len(joins) == 1, rounding
        delta = joins[0]["delta"]
        assert abs(delta) > 1e-12, (
            "delta of zero on a deliberately off-grid time: " + repr(joins[0]))
        expect_t, expect_d = mixer.frame_round(joins[0]["t"], rounding["fps"])
        assert abs(joins[0]["t_rounded"] - expect_t) < 1e-12, joins[0]
        assert abs(delta - expect_d) < 1e-12, joins[0]
