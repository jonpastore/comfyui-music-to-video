#!/usr/bin/env python3
"""Library list numbers HTML and JSON share.

docs/TRD-6 T6-A2-library / TRD-10. This is the layer the web routes call and it
imports NOTHING from FastAPI, so every operation is reachable from a test,
a shell, or a mobile client written later against the same JSON. song_count
is service-owned: a template that recomputes from len(songs) fails the stub arm.

    python3 -c "import library_service; print('ok')"
"""
import db


def numbers():
    """song_count for HTML library (GET / and GET /songs) and GET /api/songs.

    song_count is not len() at the template.
    """
    row = db.one("SELECT COUNT(*) AS n FROM songs")
    # T6-A2: HTML and JSON report this from this function.
    return {"song_count": int(row["n"] if row else 0)}
