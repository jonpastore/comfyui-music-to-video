"""T1-6: sum of |rounding delta| is reported and bounded by half a frame.

docs/TRD-1 §4.3: video rounds to the nearest whole frame at the set's
output fps; audio stays at the exact second. The sum of |delta| over a
set is reported and must stay at or under half a frame per join.
Nearest, not truncation: truncation of the same off-grid joins shares
a sign and exceeds the bound (0.0594 s/join at 16.8312 fps). A delta
of zero on a deliberately off-grid time is a failure, not a pass.

The bound is checkable from the model — mixer.rounding_report walks
the same joins as timeline_joins; GET /api/sets/{id} carries the
per-join delta and the summed |delta|. No render.
"""
import math

from conftest import _real_module
from fastapi.testclient import TestClient

import app as appmod
from test_app import _upload_song


mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"

# TRD-1 §4.3 / DDD-1 §5.1: the rate where truncation accumulates.
FPS = 16.8312
HALF_FRAME = 0.5 / FPS

# First item lands every join at *.75 of a frame so nearest is 0.25
# frames and truncation is 0.75 — the mutation the bound exists to
# catch. Later items are whole frames so the fraction does not walk.
_FIRST_FRAMES = 10.75
_NEXT_FRAMES = 8.0
_N_JOINS = 3


def _secs(frames):
    return frames / FPS


def _off_grid_set():
    items = [{"id": 1, "duration": _secs(_FIRST_FRAMES),
              "transition": "cut", "secs": 0.0}]
    for i in range(_N_JOINS):
        items.append({"id": i + 2, "duration": _secs(_NEXT_FRAMES),
                      "transition": "cut", "secs": 0.0})
    return items


def _trunc(t, fps):
    return math.floor(t * fps) / fps


def test_t1_6_off_grid_sum_is_reported_and_bounded():
    """A set of off-grid joins reports sum |delta| ≤ half a frame each.

    Swapping frame_round's nearest for truncation makes abs_delta_sum
    miss the same bound — that is the check, not a second assertion
    about a helper.
    """
    items = _off_grid_set()
    report = mixer.rounding_report(items, FPS)

    assert report["fps"] == FPS
    assert len(report["joins"]) == _N_JOINS, report
    assert "abs_delta_sum" in report, report
    bound = _N_JOINS * HALF_FRAME
    assert report["bound"] == bound, report

    for j in report["joins"]:
        assert abs(j["delta"]) > 1e-12, j
        assert abs(j["delta"]) <= HALF_FRAME + 1e-12, j

    assert report["abs_delta_sum"] <= bound + 1e-12, report

    times = [j["t"] for j in report["joins"]]
    trunc_sum = sum(abs(_trunc(t, FPS) - t) for t in times)
    assert trunc_sum > bound, (
        f"fixture is not the truncation mutation: trunc_sum={trunc_sum} "
        f"bound={bound}")


def test_t1_6_api_reports_per_join_delta_and_sum():
    """GET /api/sets/{id} carries per-join delta and summed |delta|."""
    with TestClient(appmod.app) as client:
        songs = [_upload_song(client, f"T1-6 {name}") for name in ("A", "B", "C")]
        created = client.post("/api/sets", json={"name": "T1-6 Rounding Set",
                                                 "mode": "audio"})
        assert created.status_code == 200, created.text
        set_id = created.json()["set"]["id"]
        for song in songs:
            added = client.post(f"/api/sets/{set_id}/items",
                                json={"song_id": song["id"],
                                      "transition": "cut", "secs": 0})
            assert added.status_code == 200, added.text

        r = client.get(f"/api/sets/{set_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        rounding = body.get("rounding")
        assert rounding is not None, body
        joins = rounding.get("joins") or []
        assert len(joins) == 2, rounding
        assert all("delta" in j for j in joins), rounding
        assert "abs_delta_sum" in rounding, rounding
        assert rounding["abs_delta_sum"] <= rounding["bound"] + 1e-12, rounding
        expected = sum(abs(j["delta"]) for j in joins)
        assert abs(rounding["abs_delta_sum"] - expected) < 1e-12, rounding
