#!/usr/bin/env python3
"""Playlist card numbers HTML and JSON share.

docs/TRD-6 T6-A2-playlists. This is the layer the web routes call and it
imports NOTHING from FastAPI, so every operation is reachable from a test,
a shell, or a mobile client written later against the same JSON. song_count
and total_secs are service-owned: a template that recomputes from
len(rows) fails the stub arm.

    python3 -c "import playlist_service; print('ok')"
"""
import db


def require_playlist(pid):
    row = db.one("SELECT * FROM playlists WHERE id=?", pid)
    if not row:
        raise LookupError("no such playlist")
    return row


def numbers(playlist_id):
    """song_count and total_secs for HTML /playlists card and GET /api/playlists/{id}.

    song_count is not len() at the template. total_secs is the sum of song
    durations the collapsed card shows.
    """
    require_playlist(playlist_id)
    items = db.q(
        """SELECT s.duration AS duration
           FROM playlist_items pi JOIN songs s ON s.id = pi.song_id
           WHERE pi.playlist_id=? ORDER BY pi.position""",
        playlist_id)
    total = 0.0
    for it in items:
        total += it["duration"] or 0.0
    # T6-A2: HTML and JSON report these from this function.
    return {
        "playlist_id": playlist_id,
        "song_count": len(items),
        "total_secs": total,
    }
