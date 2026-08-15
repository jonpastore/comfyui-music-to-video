"""T10-11: mark model-authored strings in the payload.

One shape, used by lyrics, chat, mixadvice and vision. A client that cannot
tell advice from a measurement will show the wrong one (T2-36's shape). The
mark is a field the client reads, not a sentence in a template.
"""

MODEL = "model"
MEASUREMENT = "measurement"
OPERATOR = "operator"


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
