"""T8-9 / T6-A4: replace-span hint reads 2*mixer.SPLICE_XFADE, not 2*0.25.

docs/TRD-8 T8-9: bridge arithmetic (and the two-crossfade "eaten" seconds
shown on the generate card) lives with mixer, not a second hardcode in
song.html. T6-A4: no template computes.

Distinctive stub: SPLICE_XFADE=0.20 → 2*xfade = 0.40. A template that still
does 2*0.25 prints 0.50 and goes red.
"""
import re

from fastapi.testclient import TestClient

import app as appmod
from test_app import _upload_song

# Distinctive: not equal to 2 * 0.25.
_STUB_XFADE = 0.20
_STUB_EATEN = 2 * _STUB_XFADE  # 0.40
_HARDCODED = 2 * 0.25  # 0.50 — what the old template computed


def test_t8_9_song_span_hint_shows_stubbed_splice_eaten(monkeypatch):
    """GET /songs/{id} shows 2*SPLICE_XFADE; 0.50 from 2*0.25 is absent when stubbed."""
    assert abs(_STUB_EATEN - _HARDCODED) > 1e-9
    assert f"{_STUB_EATEN:.2f}" != f"{_HARDCODED:.2f}"

    monkeypatch.setattr(appmod.mixer, "SPLICE_XFADE", _STUB_XFADE)

    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T8-9 Splice Hint")
        r = client.get(f"/songs/{song['id']}")

    assert r.status_code == 200, r.text
    page = r.text
    assert "Replace a span" in page, page[:800]

    stub_s = f"{_STUB_EATEN:.2f}s"
    hard_s = f"{_HARDCODED:.2f}s"
    assert stub_s in page, f"expected service-owned {stub_s!r} in page: {page[page.find('Replace a span'):page.find('Replace a span')+400] if 'Replace a span' in page else page[:500]}"
    assert hard_s not in page, f"template still shows hardcode {hard_s!r} (2*0.25)"

    # Bound the match to the replace-span hint so other page numbers cannot pass.
    m = re.search(
        r"Replace a span.*?eaten by the two crossfades",
        page, re.DOTALL)
    assert m, "missing replace-span eaten-by-crossfades hint"
    hint = m.group(0)
    assert stub_s in hint, hint
    assert hard_s not in hint, hint
    assert "2 * 0.25" not in hint and "2*0.25" not in hint, hint
