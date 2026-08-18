#!/usr/bin/env python3
"""Topbar navigation links shared by HTML and JSON.

UIUX §8 / TRD-6 T6-A2-nav: base.html and GET /api/nav both read LINKS.
No FastAPI import — same rule as library_service (T6-A3).

    python3 -c "import nav_service; print(nav_service.links())"
"""

# Order matches today's topbar. One list; do not hardcode a second set in the
# template. Labels and hrefs are the operator-facing contract.
LINKS = [
    {"href": "/", "label": "Library"},
    {"href": "/media", "label": "Media"},
    {"href": "/anchors", "label": "Anchors"},
    {"href": "/playlists", "label": "Playlists"},
    {"href": "/sets", "label": "Sets"},
    {"href": "/tiers", "label": "Tiers"},
    {"href": "/models", "label": "Models"},
    {"href": "/jobs", "label": "Jobs"},
    {"href": "/config", "label": "Config"},
]


def links():
    """Topbar entries for base.html and GET /api/nav.

    Returns a list of {href, label}. Template hardcoding the old
    links misses a monkeypatched probe (test_uiux_nav.py).
    """
    return list(LINKS)
