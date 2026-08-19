"""Generate form: sticky album/tier, missing catalog poses, actor identity."""
import os
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import classification
from test_uiux_classification_chips import _album_song, _scene


def test_generate_form_uses_sticky_album_and_missing_poses():
    stamp = f"gen-cat-{time.time_ns()}"
    album, sid, _song = _album_song(stamp, scenes=[
        _scene(1, "standing", "wide"),
        _scene(2, "kneeling", "medium"),
    ])
    prev = classification._DEFAULT_SIDECAR
    classification._DEFAULT_SIDECAR = os.path.join(db.DATA, f"{stamp}-missing.json")
    try:
        with TestClient(appmod.app) as client:
            page = client.get("/anchors", params={
                "scope_value": album, "song_id": sid, "gap_tier": "xxx"})
    finally:
        classification._DEFAULT_SIDECAR = prev
    assert page.status_code == 200, page.text
    html = page.text
    assert "<select name=\"album\"" not in html
    assert 'type="hidden" name="album"' in html
    assert 'class="view-matrix"' not in html
    assert "Tick at least one" not in html
    assert "need_key" in html or "No missing catalog poses" in html or "Pick a tier chip" in html
    assert "actor-card" in html
    assert "help-tip" in html.split('id="generate-pose"', 1)[1][:800]
