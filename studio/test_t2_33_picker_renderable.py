"""T2-33: add a catalogue model and it appears in the picker.

docs/TRD-2 §6: the model picker reads models.renderable(role), so a
model added to the catalogue appears with no UI change.

A picker that calls renderable() and discards it, or post-filters to a
stale fixed list, stays green on a presence check and fails this.

Mutation: keep the select, ignore renderable() / hardcode s2v+i2v+ltx
→ the probe cli is absent and this fails.
Mutation: renderable() values are computed then replaced with catalog
keys → option values no longer match renderable().values().
"""
import html as htmlmod
import re

from fastapi.testclient import TestClient

import app as appmod
import models
from test_app import _upload_song

_KEY = "t233_probe"
_CLI = "t233probe"
_LABEL = "T2-33 Probe"
_PURPOSE = "T2-33 probe purpose: appears without a UI change."


def _probe_entry():
    return {
        "role": "video",
        "label": _LABEL,
        "file": "t233_probe.safetensors",
        "loader": "UNETLoader",
        "cli": _CLI,
        "companions": {},
        "proven": "opportunistic",
        "purpose": _PURPOSE,
    }


def _video_options(page):
    page = htmlmod.unescape(page)
    block = re.search(r'<select name="video_model">(.*?)</select>', page, re.S)
    assert block, "video_model picker is missing from the song page"
    return re.findall(r'<option value="([^"]+)"[^>]*>(.*?)</option>',
                      block.group(1), re.S)


def test_t2_33_added_catalogue_model_appears_in_the_picker(monkeypatch):
    catalog = dict(models.CATALOG)
    catalog[_KEY] = _probe_entry()
    monkeypatch.setattr(models, "CATALOG", catalog)
    monkeypatch.setattr(models, "installed", lambda *a, **k: None)

    wired = models.renderable("video")
    assert wired[_KEY] == _CLI, "probe is catalogued but not renderable"

    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T2-33 Picker Song")
        page = client.get(f"/songs/{song['id']}")
        assert page.status_code == 200, page.text
        options = _video_options(page.text)

    values = [value for value, _label in options]
    labels = [label.strip() for _value, label in options]
    assert _CLI in values, values
    assert _LABEL in labels, labels
    assert set(values) == set(wired.values()), (sorted(values), sorted(wired.values()))
    assert _PURPOSE in htmlmod.unescape(page.text)
