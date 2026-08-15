"""T1-4: the filter graph is regenerated from the stored model.

docs/TRD-1 §4.2: mutate a stored mix value and the next render's graph
CHANGES. A cached ffmpeg string would stay put. Nothing parses ffmpeg
back into the model — that prohibition lives in §12.

Positive half: regeneration is observed, not merely that no cache key
exists. One variable: stored gain_db.
"""
import subprocess
import time

from fastapi.testclient import TestClient

from conftest import _real_module
import app as appmod
import db
from test_app import _upload_song


mixer = _real_module("mixer")
assert mixer is not None, "mixer.py failed to import"


def _ffmpeg(args):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *args],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r


def _mp4(path, seconds, colour, freq, fps=16):
    _ffmpeg([
        "-f", "lavfi", "-i", f"color=c={colour}:s=320x240:r={fps}:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-shortest", path,
    ])


def _json(client, method, path, **kw):
    headers = dict(kw.pop("headers", None) or {})
    headers["Accept"] = "application/json"
    r = getattr(client, method)(path, headers=headers, **kw)
    assert r.status_code < 400, f"{method.upper()} {path} -> {r.status_code}: {r.text[:400]}"
    return r.json()


def _graph_from_stored(sid):
    row = db.one("SELECT * FROM sets WHERE id=?", sid)
    items = appmod._set_render_items(row)
    graph = mixer.render_set_graph(items)
    assert isinstance(graph, str) and graph, graph
    return graph


def test_t1_4_mutating_stored_mix_changes_next_render_graph(tmp_path):
    """Stored gain_db mutation must change the next regenerated graph.

    A reused ffmpeg string would keep volume=-6.000dB after the column
    moved to -3. The graph is compared, not file bytes.
    """
    assert callable(mixer.render_set_graph)

    clip_a = str(tmp_path / "a.mp4")
    clip_b = str(tmp_path / "b.mp4")
    _mp4(clip_a, 2.0, "red", 220)
    _mp4(clip_b, 2.0, "blue", 880)

    with TestClient(appmod.app) as client:
        song_a = _upload_song(client, "T1-4 Song A")
        song_b = _upload_song(client, "T1-4 Song B")
        created = _json(client, "post", "/api/sets",
                        json={"name": "T1-4 Graph Set", "mode": "video",
                              "tier": "pg13"})
        sid = created.get("set", created).get("id")
        assert sid, created

        _json(client, "post", f"/api/sets/{sid}/items",
              json={"song_id": song_a["id"], "transition": "fade", "secs": 0.4})
        _json(client, "post", f"/api/sets/{sid}/items",
              json={"song_id": song_b["id"], "transition": "cut", "secs": 0})

        items = db.q(
            "SELECT * FROM set_items WHERE set_id=? ORDER BY position", sid)
        assert len(items) == 2
        db.run("UPDATE set_items SET gain_db=? WHERE id=?", -6.0, items[0]["id"])
        db.run(
            "INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
            song_a["id"], "pg13", clip_a, time.time())
        db.run(
            "INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
            song_b["id"], "pg13", clip_b, time.time())

        before = _graph_from_stored(sid)
        assert "volume=-6.000dB" in before, before

        db.run("UPDATE set_items SET gain_db=? WHERE id=?", -3.0, items[0]["id"])
        stored = db.one("SELECT gain_db FROM set_items WHERE id=?", items[0]["id"])
        assert float(stored["gain_db"]) == -3.0

        after = _graph_from_stored(sid)

    assert before != after, (
        "T1-4: graph did not change after stored gain_db -6 -> -3; "
        "a cached ffmpeg string was reused")
    assert "volume=-3.000dB" in after, after
    assert "volume=-6.000dB" not in after, after
