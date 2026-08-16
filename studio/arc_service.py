#!/usr/bin/env python3
"""Album arc as a service: meter numbers HTML and JSON share.

docs/TRD-6 T6-A2-arc / TRD-2. This is the layer the web routes call and it
imports NOTHING from FastAPI, so every operation is reachable from a test,
a shell, or a mobile client written later against the same JSON. song_count
and act_count are service-owned: a template that recomputes from
len(arc.songs) fails the stub arm.

    python3 -c "import arc_service; print('ok')"
"""
import json
import os
import re

import arc
import db


def require_playlist(pid):
    row = db.one("SELECT * FROM playlists WHERE id=?", pid)
    if not row:
        raise LookupError("no such playlist")
    return row


def _safe_name(name):
    name = os.path.basename(name or "")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name[:200] or "file"


def album_arc_dir(pl):
    slug = _safe_name(pl["name"])
    return os.path.join(db.DATA, "arcs", slug), slug


def load_arc(pid):
    row = db.one("SELECT * FROM arcs WHERE playlist_id=?", pid)
    if not row or not row["json_path"] or not os.path.isfile(row["json_path"]):
        return None
    try:
        with open(row["json_path"]) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load_row(pid):
    return db.one("SELECT * FROM arcs WHERE playlist_id=?", pid)


def load_proposal(pl):
    outdir, slug = album_arc_dir(pl)
    return arc.load_proposal(outdir, slug)


def payload(playlist_id):
    """Meter numbers for HTML /playlists/{id}/arc and GET /api/playlists/{id}/arc.

    song_count / act_count are not len() at the template. has_proposal matches
    the page's proposal section gate (proposal present with a premise).
    """
    pl = require_playlist(playlist_id)
    data = load_arc(pl["id"])
    songs = (data or {}).get("songs") or []
    acts = (data or {}).get("acts") or []
    proposal = load_proposal(pl) or {}
    # T6-A2: HTML and JSON report these from this function.
    return {
        "playlist_id": pl["id"],
        "song_count": len(songs),
        "act_count": len(acts),
        "premise": (data or {}).get("premise") or "",
        "has_proposal": bool(proposal.get("premise")),
        "arc": data,
        "proposal": proposal,
        "row": load_row(pl["id"]),
    }
