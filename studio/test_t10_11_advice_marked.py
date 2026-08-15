"""T10-11: model-authored strings are marked in the payload.

docs/TRD-10 T10-11. A client that cannot tell advice from a measurement
will show the wrong one (T2-36's shape). The one-sided failure is a field
that is present and never read: the test walks the payload and separates
by the mark.
"""
from fastapi.testclient import TestClient

from conftest import _real_module

import advice
import app as appmod
import chat
import db
import mixadvice
from test_app import _upload_song, wait_job

_real_lyrics = _real_module("lyrics")
_real_vision = _real_module("vision")
assert _real_lyrics is not None, "lyrics.py failed to import"
assert _real_vision is not None, "vision.py failed to import"


def _split(payload):
    """The client: read `authored`, do not just check it exists."""
    got = advice.separate(payload)
    assert got[advice.MODEL] or got[advice.MEASUREMENT] or got[advice.OPERATOR], payload
    kinds = {rec["authored"] for rec in advice.walk(payload)}
    assert advice.MODEL not in kinds or advice.MEASUREMENT not in kinds or (
        kinds >= {advice.MODEL, advice.MEASUREMENT}
    )
    return got


def test_t10_11_client_separates_model_from_measurement():
    """A measurement in the same payload is marked distinctly."""
    payload = [
        advice.mark("close tempo", advice.MODEL),
        advice.mark(128.0, advice.MEASUREMENT, unit="bpm"),
        advice.mark("keep the hats", advice.OPERATOR),
    ]
    split = _split(payload)
    assert [r["text"] for r in split[advice.MODEL]] == ["close tempo"]
    assert [(r["text"], r["unit"]) for r in split[advice.MEASUREMENT]] == [(128.0, "bpm")]
    assert [r["text"] for r in split[advice.OPERATOR]] == ["keep the hats"]
    assert {r["authored"] for r in split[advice.MODEL]} == {advice.MODEL}
    assert {r["authored"] for r in split[advice.MEASUREMENT]} == {advice.MEASUREMENT}


def test_t10_11_measurement_without_unit_is_refused():
    """A number without a unit is a claim, not a measurement (UIUX §7b.5)."""
    try:
        advice.mark(41.1, advice.MEASUREMENT)
    except ValueError as e:
        assert "unit" in str(e).lower(), e
    else:
        raise AssertionError("a unit-less measurement was accepted")


def test_t10_11_mixadvice_payload_marks_why_and_bpm():
    items = [{"id": 1, "title": "A", "bpm": 123.0, "key": "10A", "energy": 0.16},
             {"id": 2, "title": "B", "bpm": 126.0, "key": "11A", "energy": 0.22}]
    sug = mixadvice.clean(
        {"items": [{"id": 1, "transition": "fade", "secs": 4.0, "why": "close tempo"}]},
        {1, 2})
    payload = mixadvice.interface_payload(sug, items, direction="keep it moving")
    split = _split(payload)
    assert any(r["text"] == "close tempo" for r in split[advice.MODEL]), split
    assert any(r["text"] == 123.0 and r.get("unit") == "bpm"
               for r in split[advice.MEASUREMENT]), split
    assert any(r["text"] == "keep it moving" for r in split[advice.OPERATOR]), split
    # the raw why string is not a sibling the client could confuse with bpm
    assert payload["items"][0]["why"]["authored"] == advice.MODEL
    assert payload["items"][0]["bpm"]["authored"] == advice.MEASUREMENT
    assert payload["items"][0]["why"]["authored"] != payload["items"][0]["bpm"]["authored"]


def test_t10_11_vision_payload_marks_reason_and_cells():
    verdict = {"flagged": [{"clip": 1, "issue": "broken", "reason": "two of her"}],
               "cells_seen": 2, "backend": "local"}
    payload = _real_vision.interface_payload(verdict, cells=2)
    split = _split(payload)
    assert any(r["text"] == "two of her" for r in split[advice.MODEL]), split
    assert any(r["text"] == 2 and r.get("unit") == "cells"
               for r in split[advice.MEASUREMENT]), split
    assert payload["flagged"][0]["reason"]["authored"] == advice.MODEL
    assert payload["cells"]["authored"] == advice.MEASUREMENT


def test_t10_11_lyrics_payload_marks_text_and_duration():
    result = {"text": "hello world still going",
              "segments": [{"start": 0.0, "end": 2.0, "text": "hello world"},
                           {"start": 2.5, "end": 4.0, "text": "still going"}],
              "language": "en", "model": "medium", "device": "cpu"}
    payload = _real_lyrics.interface_payload(result)
    split = _split(payload)
    assert any("hello world" in str(r["text"]) for r in split[advice.MODEL]), split
    assert any(r["text"] == 4.0 and r.get("unit") == "s"
               for r in split[advice.MEASUREMENT]), split
    assert payload["text"]["authored"] == advice.MODEL
    assert payload["duration"]["authored"] == advice.MEASUREMENT


def test_t10_11_chat_payload_marks_model_strings():
    data, used = {"premise": "she leaves the city"}, "xai/grok-stub"
    payload = chat.interface_payload(data, used)
    split = advice.separate(payload)
    assert any(r["text"] == "she leaves the city" for r in split[advice.MODEL]), split
    assert all(r["authored"] == advice.MODEL for r in split[advice.MODEL])
    assert payload["used"] == used
    # original data stays readable; the mark sits where a client looks
    assert payload["data"] == data


def test_t10_11_suggest_json_is_separable():
    """The live interface: Accept JSON, walk the body, separate by the mark."""
    with TestClient(appmod.app) as client:
        a = _upload_song(client, "T10-11 Song A")
        b = _upload_song(client, "T10-11 Song B")
        for s in (a, b):
            wait_job(db.one("SELECT id FROM jobs WHERE song_id=? AND kind='analyse'",
                            s["id"])["id"])
        client.post("/sets/new", data={"name": "T10-11 Mix", "mode": "audio"})
        sid = db.one("SELECT id FROM sets WHERE name='T10-11 Mix'")["id"]
        for s in (a, b):
            client.post(f"/sets/{sid}/items",
                        data={"song_id": s["id"], "transition": "fade", "secs": "2.0"})
        r = client.post(f"/sets/{sid}/suggest",
                        data={"mix_direction": "keep it moving"},
                        headers={"Accept": "application/json"})
        assert r.status_code == 200, r.text
        body = r.json()
        split = _split(body)
        assert any(r["text"] == "stub" for r in split[advice.MODEL]), body
        assert any(r.get("unit") == "bpm" for r in split[advice.MEASUREMENT]), body
        assert any(r["text"] == "keep it moving" for r in split[advice.OPERATOR]), body
        model_texts = {r["text"] for r in split[advice.MODEL]}
        measured = {r["text"] for r in split[advice.MEASUREMENT]}
        assert model_texts.isdisjoint(measured), (model_texts, measured)
