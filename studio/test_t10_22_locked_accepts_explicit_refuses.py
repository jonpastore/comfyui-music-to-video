"""T10-22: dedicated paired test — locked accepts, explicit refuses.

One string on both halves. The locked non-explicit path (g/pg13) accepts a
minor reference; any album/song/scene that is not locked non-explicit refuses
the same string. The refuse half is what T8-4 / T10-16 already assert; this
criterion keeps both halves in one test so dropping either goes red.
"""
import pytest
from fastapi.testclient import TestClient

import app as appmod
import guardrail
from test_app import _real_storyboard, _scene, _upload_song

# Same string for both halves — the pair is meaningless if the paths see
# different text.
CHILD = "a 7 year old child dancing in the garden, fully clothed"


def test_t10_22_locked_accepts_explicit_refuses_same_string():
    """Both halves, one string: locked g/pg13 accepts; explicit refuses.

    Shared screen plus the scene-save surface. Mutation: drop the g/pg13
    skip and the accept half goes red; drop the refuse and explicit save
    lands the child string.
    """
    assert guardrail.LOCKED_DEPICT_TIERS == frozenset({"g", "pg13"})

    for lock in ("g", "pg13"):
        assert guardrail.allows_minor_depiction(lock)
        assert guardrail.check_text(CHILD, "scene", tier=lock) == CHILD

    for explicit in (None, "", "r", "xxx", "custom"):
        assert not guardrail.allows_minor_depiction(explicit)
        with pytest.raises(guardrail.ContentRefused) as err:
            guardrail.check_text(CHILD, "scene", tier=explicit)
        low = str(err.value).lower()
        assert "child" in low or "7 year" in low or "minor" in low, low

    with TestClient(appmod.app) as client:
        song = _upload_song(client, "T10-22 Paired Song", album="T10-22 Album")
        sid, slug = song["id"], song["slug"]

        for lock in ("g", "pg13"):
            _real_storyboard(sid, lock, slug, [_scene(1)])
            saved = client.post(
                f"/songs/{sid}/storyboard/{lock}/scene/1",
                data={"image_prompt": CHILD,
                      "video_motion_prompt": "the child twirls"},
            )
            assert saved.status_code == 200, (lock, saved.text[:300])

        _real_storyboard(sid, "xxx", slug, [_scene(1)])
        for field in ("image_prompt", "video_motion_prompt"):
            refused = client.post(
                f"/songs/{sid}/storyboard/xxx/scene/1",
                data={field: CHILD},
            )
            assert refused.status_code == 400, (
                f"explicit scene {field} accepted: {refused.text[:300]}")
            low = refused.text.lower()
            assert "child" in low or "7 year" in low or "minor" in low, refused.text[:300]

        # Direction on the explicit path (same string T10-16 also uses).
        r_xxx = client.post(
            f"/songs/{sid}/storyboard",
            data={"tier": "xxx", "direction": CHILD},
        )
        assert r_xxx.status_code == 400, (
            f"explicit direction accepted: {r_xxx.text[:300]}")
        low = r_xxx.text.lower()
        assert "child" in low or "7 year" in low or "minor" in low, r_xxx.text[:300]
