"""T8-2 UI surface on the T8-16 media bag: pick a take from the Media card.

T8-16 owns the bag list. This is T8-2's pick form on that card:
unpicked takes get POST /songs/{id}/takes/{id}/pick; picked takes show
a picked tag, not a second button. Does not write songs.mp3_path.
"""
import re
import time

from fastapi.testclient import TestClient

import app as appmod
import db
import media_service


def _song(title="T8-2 Media pick"):
    return db.upsert_song(
        f"t8-2-media-{time.time_ns()}", title=title, mp3_path="/keep/me.mp3")


def _two_takes(sid):
    """Distinctive take ids so two empty lists cannot pass."""
    a = db.insert_take(
        sid, f"/data/takes/t8-2-a-{sid}-{time.time_ns()}.mp3",
        "generated", tags="take-a")
    b = db.insert_take(
        sid, f"/data/takes/t8-2-b-{sid}-{time.time_ns()}.mp3",
        "generated", tags="take-b")
    assert a != b
    return a, b


def test_t8_2_media_card_shows_pick_form_on_unpicked_takes():
    """Two takes: Media HTML has both keys; each unpicked take has the pick form."""
    sid = _song("T8-2 Media form")
    a, b = _two_takes(sid)
    keep = "/keep/me.mp3"

    with TestClient(appmod.app) as client:
        page = client.get(f"/songs/{sid}")
        js = client.get(f"/api/songs/{sid}/media")

    assert page.status_code == 200, page.text
    assert js.status_code == 200, js.text
    html = page.text
    body = js.json()

    want_keys = {f"take:{a}", f"take:{b}"}
    html_keys = set(re.findall(r'data-media-key="(take:\d+)"', html))
    json_keys = {f"{it['kind']}:{it['id']}" for it in body["items"]
                 if it["kind"] == "take"}
    assert html_keys == want_keys, (html_keys, want_keys)
    assert json_keys == want_keys, (json_keys, want_keys)
    assert body["count"] == 2
    assert body["n_takes"] == 2

    # Mutation: omitting the pick form from the media card goes red.
    for tid in (a, b):
        action = f'/songs/{sid}/takes/{tid}/pick'
        assert action in html, f"missing pick form for take {tid}: {action}"
        # Form lives under the media-menu card, not only the generate table.
        m = re.search(
            rf'id="media-menu".*?action="{re.escape(action)}"',
            html, re.DOTALL)
        assert m, f"pick form for take {tid} not inside #media-menu"

    # Neither is picked yet — no picked tags for these ids.
    assert f'data-take-picked="{a}"' not in html
    assert f'data-take-picked="{b}"' not in html
    assert db.one("SELECT mp3_path FROM songs WHERE id=?", sid)["mp3_path"] == keep


def test_t8_2_media_card_pick_tags_picked_and_other_stays_listed():
    """POST pick from Media card: that take tagged picked; other remains listed."""
    sid = _song("T8-2 Media pick act")
    a, b = _two_takes(sid)
    keep = "/keep/me.mp3"
    pick_id, other_id = b, a

    with TestClient(appmod.app) as client:
        before = client.get(f"/songs/{sid}")
        assert before.status_code == 200
        assert f'/songs/{sid}/takes/{pick_id}/pick' in before.text
        assert f'/songs/{sid}/takes/{other_id}/pick' in before.text

        picked = client.post(
            f"/songs/{sid}/takes/{pick_id}/pick",
            headers={"Accept": "application/json"})
        assert picked.status_code == 200, picked.text
        body = picked.json()
        assert body["picked"] == pick_id
        by_id = {t["id"]: t for t in body["takes"]}
        assert set(by_id) == {a, b}
        assert by_id[pick_id]["picked"] is True
        assert by_id[other_id]["picked"] is False

        page = client.get(f"/songs/{sid}")
        js = client.get(f"/api/songs/{sid}/media")

    assert page.status_code == 200, page.text
    assert js.status_code == 200, js.text
    html = page.text
    media = js.json()

    # Both still listed with distinctive keys (T6-A2 / T8-16).
    want_keys = {f"take:{a}", f"take:{b}"}
    html_keys = set(re.findall(r'data-media-key="(take:\d+)"', html))
    json_keys = {f"{it['kind']}:{it['id']}" for it in media["items"]
                 if it["kind"] == "take"}
    assert html_keys == want_keys == json_keys
    assert media["count"] == 2
    assert media["n_takes"] == 2

    # Picked take: tag, no second pick button on the media card.
    assert f'data-take-picked="{pick_id}"' in html
    assert re.search(
        rf'data-media-key="take:{pick_id}"[^>]*>.*?picked',
        html, re.DOTALL)
    # The pick form for the picked take is gone from the media card.
    media_section = re.search(
        r'id="media-menu".*?</section>', html, re.DOTALL)
    assert media_section, html[:400]
    section = media_section.group(0)
    assert f'/songs/{sid}/takes/{pick_id}/pick' not in section
    # Unpicked take still has the pick form in the media card.
    assert f'/songs/{sid}/takes/{other_id}/pick' in section

    # list_bag / JSON agree on picked flags (HTML interpolates picked).
    bag = media_service.list_bag(sid)
    by_item = {it["id"]: it for it in bag["items"] if it["kind"] == "take"}
    assert by_item[pick_id]["picked"] is True
    assert by_item[other_id]["picked"] is False
    js_by = {it["id"]: it for it in media["items"] if it["kind"] == "take"}
    assert js_by[pick_id]["picked"] is True
    assert js_by[other_id]["picked"] is False

    # T8-2: pick does not write songs.mp3_path; both takes remain playable rows.
    assert db.one("SELECT mp3_path FROM songs WHERE id=?", sid)["mp3_path"] == keep
    rows = {t["id"]: t for t in db.list_takes(sid)}
    assert set(rows) == {a, b}
    assert rows[pick_id]["picked"] == 1
    assert rows[other_id]["picked"] == 0
    assert rows[a]["path"]
    assert rows[b]["path"]
