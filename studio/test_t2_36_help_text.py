"""T2-36: help text is carried in the API response for each control.

docs/TRD-2 §7: any client can put help behind a `?` and none has to hardcode
it. Empty help is omitted rather than present-and-empty. Warnings that must
not move (day 8) are marked distinctly from notes so a client cannot hide
the wrong one.

Mutation: return a key with empty body/label → empty-omitted arm red.
Mutation: mark every string as a note → warning-distinct arm red.
Mutation: omit help from the list response → API arm red.
"""
from fastapi.testclient import TestClient

import app as appmod


def _kinds(payload):
    """Client entry: separate notes from warnings by the kind mark."""
    notes, warnings = [], []
    if not isinstance(payload, dict):
        return notes, warnings
    for key, entry in payload.items():
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if kind == appmod.HELP_NOTE:
            notes.append((key, entry))
        elif kind == appmod.HELP_WARNING:
            warnings.append((key, entry))
        warn = entry.get("warning")
        if isinstance(warn, dict) and warn.get("kind") == appmod.HELP_WARNING:
            warnings.append((key, warn))
    return notes, warnings


def test_t2_36_empty_help_is_absent_not_present_and_empty():
    """A control with no help text is omitted, not present-and-empty.

    Mutation: stamp every known control key with {} or "" → this fails.
    """
    payload = appmod.controls_help_payload(
        help_map={
            "cfg": {"label": "Guidance (CFG)", "body": ["how hard the model is pushed"]},
            "ghost": {"label": "", "body": []},
            "blank": "",
            "none": None,
        },
        warnings={},
    )
    assert "cfg" in payload, payload
    assert payload["cfg"]["kind"] == appmod.HELP_NOTE
    assert payload["cfg"]["label"] == "Guidance (CFG)"
    assert payload["cfg"]["body"] == ["how hard the model is pushed"]
    assert "ghost" not in payload, payload
    assert "blank" not in payload, payload
    assert "none" not in payload, payload
    # present-and-empty would still list the key
    for key, entry in payload.items():
        assert entry, f"{key} is present-and-empty: {entry!r}"
        if entry.get("kind") == appmod.HELP_NOTE:
            assert entry.get("label") or entry.get("body"), entry


def test_t2_36_warnings_marked_distinctly_from_notes():
    """Day-8 footguns are kind=warning; help behind `?` is kind=note.

    Mutation: put every string under kind=note → warnings list is empty.
    Mutation: drop the kind field → client cannot separate them.
    """
    payload = appmod.controls_help_payload()
    notes, warnings = _kinds(payload)

    assert notes, "no notes in the help payload"
    assert warnings, "no warnings in the help payload"
    note_kinds = {entry["kind"] for _k, entry in notes}
    warn_kinds = {entry["kind"] for _k, entry in warnings}
    assert note_kinds == {appmod.HELP_NOTE}, note_kinds
    assert warn_kinds == {appmod.HELP_WARNING}, warn_kinds
    assert appmod.HELP_NOTE != appmod.HELP_WARNING
    assert note_kinds.isdisjoint(warn_kinds)

    # the two silent-failure warnings that already stay on the HTML form
    warn_by_key = {k: e for k, e in warnings}
    assert "denoise" in warn_by_key, warn_by_key
    assert "returns noise" in warn_by_key["denoise"].get("text", "").lower()
    assert "negative" in warn_by_key, warn_by_key
    neg = warn_by_key["negative"].get("text", "").lower()
    assert "fast" in neg or "dropped" in neg or "not applied" in neg, neg

    # a help note is not a warning
    assert payload["cfg"]["kind"] == appmod.HELP_NOTE
    assert payload["cfg"].get("warning") is None


def test_t2_36_list_response_carries_help_per_control():
    """GET /api/anchors carries the help map so a replacement client can use it.

    Mutation: drop help from the JSON body → red.
    Mutation: hardcode a different map than controls_help_payload → red.
    """
    expected = appmod.controls_help_payload()
    assert expected, "builder returned nothing"
    with TestClient(appmod.app) as client:
        r = client.get("/api/anchors")
        assert r.status_code == 200, r.text
        body = r.json()
    assert "help" in body, body
    assert body["help"] == expected
    notes, warnings = _kinds(body["help"])
    assert notes and warnings, (notes, warnings)
    # real control keys from ANCHOR_HELP, not a single free-text blob
    assert "cfg" in body["help"]
    assert body["help"]["cfg"]["kind"] == appmod.HELP_NOTE
    assert body["help"]["cfg"]["label"]
    assert body["help"]["cfg"]["body"]
