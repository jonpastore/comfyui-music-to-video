"""T10-11 / T10-12: mark model-authored strings; retain proposals; accept writes.

One shape, used by lyrics, chat, mixadvice and vision. A client that cannot
tell advice from a measurement will show the wrong one (T2-36's shape). The
mark is a field the client reads, not a sentence in a template.

T10-12: no advice surface writes a stored value. retain() keeps the proposal
so "what did it suggest and what did I do" is answerable. accept() is the
human act that writes, and it records the model.
"""
import json
import time

import db

MODEL = "model"
MEASUREMENT = "measurement"
OPERATOR = "operator"

SURFACES = ("mixadvice", "vision", "lyrics", "chat")


def mark(text, authored, *, unit=None):
    """One payload record a client can attribute.

    Measurements require a unit: a number without one is a claim
    (UIUX §7b.5), which is how 41.1 vs 64.7 would have become a gate.
    """
    if authored not in (MODEL, MEASUREMENT, OPERATOR):
        raise ValueError(f"unknown authored {authored!r}")
    rec = {"text": text, "authored": authored}
    if authored == MEASUREMENT:
        if not unit:
            raise ValueError("a measurement without a unit is a claim, not a measurement")
        rec["unit"] = unit
    elif unit:
        rec["unit"] = unit
    return rec


def walk(payload):
    """Yield every marked record in a payload."""
    if isinstance(payload, dict):
        if "authored" in payload and "text" in payload:
            yield payload
        for v in payload.values():
            yield from walk(v)
    elif isinstance(payload, (list, tuple)):
        for v in payload:
            yield from walk(v)


def separate(payload):
    """Client entry point: split a payload by the authored mark."""
    out = {MODEL: [], MEASUREMENT: [], OPERATOR: []}
    for rec in walk(payload):
        kind = rec.get("authored")
        if kind in out:
            out[kind].append(rec)
    return out


def retain(surface, payload, *, model, target=None):
    """Store a proposal. Writes nothing to the target the proposal is about."""
    if surface not in SURFACES:
        raise ValueError(f"unknown advice surface {surface!r}")
    model = (model or "").strip()
    if not model:
        raise ValueError("a proposal without a model cannot be attributed")
    pid = db.run(
        """INSERT INTO advice_proposals
           (surface, model, target, payload_json, accepted, created)
           VALUES (?,?,?,?,0,?)""",
        surface, model, target, json.dumps(payload), time.time())
    return get(pid)


def get(pid):
    """The retained proposal, or None."""
    row = db.one("SELECT * FROM advice_proposals WHERE id=?", pid)
    if row is None:
        return None
    return {
        "id": row["id"],
        "surface": row["surface"],
        "model": row["model"],
        "target": row["target"],
        "payload": json.loads(row["payload_json"]),
        "accepted": bool(row["accepted"]),
        "applied": json.loads(row["applied_json"]) if row["applied_json"] else None,
        "created": row["created"],
        "accepted_at": row["accepted_at"],
    }


def accept(pid, apply):
    """Human act: apply writes the stored value. The model stays on the row."""
    rec = get(pid)
    if rec is None:
        raise KeyError(pid)
    if rec["accepted"]:
        raise ValueError("proposal already accepted")
    written = apply(rec)
    db.run(
        """UPDATE advice_proposals SET accepted=1, applied_json=?, accepted_at=?
           WHERE id=?""",
        json.dumps(written), time.time(), pid)
    return get(pid)


def demo():
    mixed = [mark("close tempo", MODEL),
             mark(128.0, MEASUREMENT, unit="bpm"),
             mark("keep the hats", OPERATOR)]
    got = separate(mixed)
    assert [r["text"] for r in got[MODEL]] == ["close tempo"]
    assert [(r["text"], r["unit"]) for r in got[MEASUREMENT]] == [(128.0, "bpm")]
    assert [r["text"] for r in got[OPERATOR]] == ["keep the hats"]
    try:
        mark(41.1, MEASUREMENT)
        raise AssertionError("a unit-less measurement was accepted")
    except ValueError as e:
        assert "unit" in str(e).lower(), e
    print("advice.py OK")


if __name__ == "__main__":
    demo()
