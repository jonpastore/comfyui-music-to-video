"""T2-34: unavailable (where=False) is shown unavailable; available is offered.

docs/TRD-2 §6: a catalogued model missing on every reachable backend is
shown as unavailable rather than offered. models.where() answers this:
False is a refusal, None is a candidate.

The one-sided trap: a picker that marks EVERYTHING unavailable stays
green on the refusal half. The paired positive is an available model
still offered.

Mutation: copy catalog()['available'] (this box only) → a model the
local enum holds and the fleet does not is offered.
Mutation: disable every option → the available arm fails.
Mutation: treat where() empty the same as no backends asked → None
collapses to False and the ghost-only arm fails.
"""
import re

from fastapi.testclient import TestClient

import app as appmod
import models
from test_app import _upload_song


LTX25 = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"

# Fleet: one reachable box holds only ltx25. s2v is False everywhere
# that answered. No ghost, so where("wan22_s2v") is empty, not None.
# url=None (catalog() on the song page) is deliberately absent: that
# path must not already mark s2v False, or copying catalog()['available']
# would satisfy the picker test without asking where().
FLEET_INFO = {
    "http://127.0.0.1:8188": {
        "UNETLoader": {"input": {"required": {"unet_name": [[LTX25]]}}},
    },
}
FLEET = [{"id": "0", "title": "cerberus", "status": "running",
          "address": "http://127.0.0.1:8188"}]
GHOST = [{"id": "9", "title": "ghost", "status": "running",
          "address": "http://10.0.0.99:8188"}]


def _info(url=None):
    return FLEET_INFO.get(url)


def _pin(monkeypatch, backends):
    monkeypatch.setattr(appmod.pipeline, "swarm_backends", lambda: backends)
    monkeypatch.setattr(models, "_object_info", _info)
    monkeypatch.setattr(models, "_system_stats",
                        lambda url=None: {"vram_gib": 23.42, "gpu": "5090"}
                        if url in FLEET_INFO else None)


def _options(html):
    block = re.search(r'<select name="video_model">(.*?)</select>', html, re.S)
    assert block, "song page has no video_model picker"
    out = {}
    for m in re.finditer(r'<option value="([^"]+)"([^>]*)>', block.group(1)):
        out[m.group(1)] = m.group(2)
    return out


def test_t2_34_available_on_fleet_is_three_valued(monkeypatch):
    """False is a refusal, True is confirmed, None is a candidate."""
    _pin(monkeypatch, FLEET)
    assert models.available_on_fleet("ltx25", FLEET) is True
    assert models.available_on_fleet("wan22_s2v", FLEET) is False
    assert models.available_on_fleet("wan22_s2v", None) is None
    assert models.available_on_fleet("wan22_s2v", []) is None

    _pin(monkeypatch, GHOST)
    assert models.available_on_fleet("wan22_s2v", GHOST) is None
    assert models.available_on_fleet("ltx25", GHOST) is None


def test_t2_34_picker_marks_false_unavailable_and_still_offers_true(monkeypatch):
    """s2v is False on the fleet and disabled; ltx25 is confirmed and offered.

    catalog() on this box lists s2v as installed, so reading that field
    instead of where() offers the missing model and this fails.
    """
    _pin(monkeypatch, FLEET)
    local = {e["key"]: e["available"] for e in models.catalog(role="video")}
    assert local["wan22_s2v"] is not False, (
        "catalog() must not already mark s2v unavailable — that lets a "
        "picker ignore where() and still pass")

    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T234 Picker")
        page = client.get(f"/songs/{song['id']}").text
    opts = _options(page)
    assert "s2v" in opts, opts
    assert "disabled" in opts["s2v"], (
        "a model where() says False on every reachable backend was offered")
    assert "ltx25" in opts, opts
    assert "disabled" not in opts["ltx25"], (
        "an available model was not offered — picker marked everything unavailable")
