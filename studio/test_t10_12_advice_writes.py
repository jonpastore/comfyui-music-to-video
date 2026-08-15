"""T10-12: no advice surface writes a stored value; accept does and records the model.

docs/TRD-10 T10-12. mixadvice proposes a running order; accepting is a
separate act. The one-sided failure is a check that stays green with the
advice surface deleted: 'suggest does not write' is true of a no-op.
The positive half requires accept to write the stored mix values and to
name the model, with the proposal still readable afterwards.
"""
from fastapi.testclient import TestClient

import advice
import app as appmod
import db
import mixadvice
from test_app import _upload_song, wait_job


def _two_song_set(client, name="T10-12 Mix"):
    a = _upload_song(client, f"{name} Song A")
    b = _upload_song(client, f"{name} Song B")
    for s in (a, b):
        wait_job(db.one("SELECT id FROM jobs WHERE song_id=? AND kind='analyse'",
                        s["id"])["id"])
    client.post("/sets/new", data={"name": name, "mode": "audio"})
    sid = db.one("SELECT id FROM sets WHERE name=?", name)["id"]
    for s in (a, b):
        client.post(f"/sets/{sid}/items",
                    data={"song_id": s["id"], "transition": "fade", "secs": "2.0"})
    return sid


def _item_mix(sid):
    return [dict(r) for r in db.q(
        "SELECT id, transition, secs, beatmatch, effects_json FROM set_items "
        "WHERE set_id=? ORDER BY position", sid)]


def test_t10_12_retain_does_not_write_a_stored_value():
    """A proposal sits in the advice store. apply is never invoked."""
    wrote = []
    rec = advice.retain(
        "mixadvice",
        {"suggestions": [{"id": 1, "transition": "dissolve", "secs": 3.5}]},
        model="qwen-stub",
        target="set:1",
    )
    assert rec["id"]
    assert rec["accepted"] is False
    assert rec["model"] == "qwen-stub"
    assert rec["applied"] is None
    assert wrote == []
    kept = advice.get(rec["id"])
    assert kept["payload"]["suggestions"][0]["transition"] == "dissolve"


def test_t10_12_accept_writes_and_records_the_model():
    """Deleting retain/accept keeps 'suggest does not write' green.

    Accepting must invoke the writer and leave the model on the record.
    """
    wrote = []

    def apply(proposal):
        wrote.append(proposal["payload"])
        return {"transition": "dissolve", "secs": 3.5}

    rec = advice.retain(
        "mixadvice",
        {"suggestions": [{"id": 1, "transition": "dissolve", "secs": 3.5}]},
        model="qwen-stub",
        target="set:1",
    )
    got = advice.accept(rec["id"], apply)
    assert wrote == [rec["payload"]], "accept did not apply the retained proposal"
    assert got["accepted"] is True
    assert got["model"] == "qwen-stub"
    assert got["applied"] == {"transition": "dissolve", "secs": 3.5}
    kept = advice.get(rec["id"])
    assert kept["payload"]["suggestions"][0]["secs"] == 3.5
    assert kept["applied"] == got["applied"]
    assert kept["model"] == "qwen-stub"


def test_t10_12_retain_without_a_model_is_refused():
    try:
        advice.retain("mixadvice", {"suggestions": []}, model="", target="set:1")
    except ValueError as e:
        assert "model" in str(e).lower(), e
    else:
        raise AssertionError("a proposal with no model was retained")


def test_t10_12_mixadvice_propose_does_not_write_set_items():
    with TestClient(appmod.app) as client:
        sid = _two_song_set(client, "T10-12 Propose")
        before = _item_mix(sid)
        assert [r["transition"] for r in before] == ["fade", "fade"]
        items = [dict(r) for r in db.q(
            """SELECT si.id, s.title, s.bpm, s.key, s.energy
               FROM set_items si JOIN songs s ON s.id = si.song_id
               WHERE si.set_id=? AND si.song_id IS NOT NULL
               ORDER BY si.position""", sid)]
        rec, sug = mixadvice.propose(items, "keep it moving", target=f"set:{sid}")
        after = _item_mix(sid)
        assert after == before, (
            "propose wrote stored mix values; T10-12 requires a separate accept")
        assert rec["accepted"] is False
        assert rec["model"]
        assert rec["target"] == f"set:{sid}"
        assert sug, "propose returned no suggestion; accept would have nothing to write"


def test_t10_12_mixadvice_accept_writes_set_items_and_records_the_model():
    """The half that fails if the advice surface is deleted."""
    with TestClient(appmod.app) as client:
        sid = _two_song_set(client, "T10-12 Accept")
        before = _item_mix(sid)
        items = [dict(r) for r in db.q(
            """SELECT si.id, s.title, s.bpm, s.key, s.energy
               FROM set_items si JOIN songs s ON s.id = si.song_id
               WHERE si.set_id=? AND si.song_id IS NOT NULL
               ORDER BY si.position""", sid)]
        rec, sug = mixadvice.propose(items, "keep it moving", target=f"set:{sid}")
        assert rec["accepted"] is False
        got = mixadvice.accept_proposal(rec["id"])
        after = _item_mix(sid)
        assert after != before, "accept wrote nothing to set_items"
        first = next(iter(sug.values()))
        written = after[0]
        assert written["transition"] == first["transition"]
        assert float(written["secs"]) == float(first["secs"])
        assert got["accepted"] is True
        assert got["model"]
        assert got["applied"]
        kept = advice.get(rec["id"])
        assert kept["payload"]["suggestions"]
        assert kept["applied"] == got["applied"]
        assert kept["model"] == got["model"]


def test_t10_12_suggest_json_does_not_write_accept_does():
    """Live surface: Accept JSON, suggest is not a write, accept is."""
    with TestClient(appmod.app) as client:
        sid = _two_song_set(client, "T10-12 HTTP")
        before = _item_mix(sid)
        r = client.post(f"/sets/{sid}/suggest",
                        data={"mix_direction": "keep it moving"},
                        headers={"Accept": "application/json"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("proposal_id"), body
        assert body.get("model"), body
        mid = _item_mix(sid)
        assert mid == before, "POST /suggest wrote stored mix values"
        acc = client.post(
            f"/sets/{sid}/proposals/{body['proposal_id']}/accept",
            headers={"Accept": "application/json"})
        assert acc.status_code == 200, acc.text
        done = acc.json()
        after = _item_mix(sid)
        assert after != before, "POST accept wrote nothing"
        assert after[0]["transition"] == "dissolve"
        assert float(after[0]["secs"]) == 3.5
        assert done["model"] == body["model"]
        assert done["accepted"] is True
        kept = advice.get(body["proposal_id"])
        assert kept["payload"]["suggestions"]
        assert kept["model"] == done["model"]
