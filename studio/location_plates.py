"""T2-53 / T7-22: one location plate per location key.

Album or song + key → one asset path. Unset / "studio" is no plate.
Character sheets and anchor_ref assets are refused as plates.
A stored plate is never build_refs --anchor / image1.
No FastAPI.
"""
import os
import re
import time

import db

_SCOPES = frozenset({"album", "song"})
_NO_PLATE = frozenset({"", "studio", "unset"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS location_plates (
  id INTEGER PRIMARY KEY,
  scope_kind TEXT NOT NULL,
  scope_value TEXT NOT NULL,
  location_key TEXT NOT NULL,
  path TEXT NOT NULL,
  created REAL NOT NULL,
  updated REAL NOT NULL,
  UNIQUE(scope_kind, scope_value, location_key));

CREATE INDEX IF NOT EXISTS idx_location_plates
  ON location_plates(scope_kind, scope_value);
CREATE INDEX IF NOT EXISTS idx_location_plates_path ON location_plates(path);
"""


def _ensure():
    schema = getattr(db, "LOCATION_PLATES_SCHEMA", _SCHEMA)
    db.conn().executescript(schema)


def _scope(kind, value):
    kind = str(kind or "").strip()
    value = str(value or "").strip()
    if kind not in _SCOPES:
        raise ValueError("location plate scope is album or song")
    if not value:
        raise ValueError("location plate scope_value is required")
    return kind, value


def _key(location_key):
    return re.sub(r"\s+", " ", str(location_key or "").strip().lower())


def _no_plate(key):
    return key in _NO_PLATE


def _public(row):
    return {
        "id": row["id"],
        "scope_kind": row["scope_kind"],
        "scope_value": row["scope_value"],
        "location_key": row["location_key"],
        "path": row["path"],
    }


def _paths_match(stored, given, abs_given):
    if not stored:
        return False
    if stored == given:
        return True
    return os.path.abspath(stored) == abs_given


def _is_character_sheet(path):
    given = str(path or "").strip()
    if not given:
        return False
    abs_given = os.path.abspath(given)
    for row in db.q("SELECT path FROM anchors"):
        if _paths_match(row["path"], given, abs_given):
            return True
    for row in db.q("SELECT path FROM assets WHERE kind='anchor_ref'"):
        if _paths_match(row["path"], given, abs_given):
            return True
    return False


def _refuse_character_sheet(path):
    if _is_character_sheet(path):
        raise ValueError(
            "character sheet / anchor_ref cannot be a location plate")


def set_plate(scope_kind, scope_value, location_key, path):
    """Store one path for this scope + key. Unset/studio has no plate."""
    _ensure()
    kind, value = _scope(scope_kind, scope_value)
    key = _key(location_key)
    if _no_plate(key):
        raise ValueError("unset/studio has no location plate")
    path = str(path or "").strip()
    if not path:
        raise ValueError("location plate path is required")
    _refuse_character_sheet(path)
    now = time.time()
    existing = db.one(
        """SELECT * FROM location_plates
           WHERE scope_kind=? AND scope_value=? AND location_key=?""",
        kind, value, key)
    if existing:
        db.run(
            """UPDATE location_plates SET path=?, updated=?
               WHERE scope_kind=? AND scope_value=? AND location_key=?""",
            path, now, kind, value, key)
    else:
        db.run(
            """INSERT INTO location_plates
               (scope_kind, scope_value, location_key, path, created, updated)
               VALUES (?,?,?,?,?,?)""",
            kind, value, key, path, now, now)
    return _public(db.one(
        """SELECT * FROM location_plates
           WHERE scope_kind=? AND scope_value=? AND location_key=?""",
        kind, value, key))


def get_plate(scope_kind, scope_value, location_key):
    """The one path for this key, or None for unset/studio/missing."""
    _ensure()
    key = _key(location_key)
    if _no_plate(key):
        return None
    kind, value = _scope(scope_kind, scope_value)
    row = db.one(
        """SELECT * FROM location_plates
           WHERE scope_kind=? AND scope_value=? AND location_key=?""",
        kind, value, key)
    return row["path"] if row else None


def for_scenes(scope_kind, scope_value, scenes):
    """{scene_number: path} — same location key is the same path."""
    out = {}
    for scene in scenes or []:
        if not isinstance(scene, dict):
            continue
        num = scene.get("scene_number")
        if num is None:
            continue
        path = get_plate(scope_kind, scope_value, scene.get("location"))
        if path:
            out[int(num)] = path
    return out


def is_location_plate(path):
    """True when this path is stored as a location plate."""
    _ensure()
    path = str(path or "").strip()
    if not path:
        return False
    if db.one("SELECT id FROM location_plates WHERE path=?", path):
        return True
    abs_p = os.path.abspath(path)
    for row in db.q("SELECT path FROM location_plates"):
        if _paths_match(row["path"], path, abs_p):
            return True
    return False


def refuse_as_identity(path):
    """T7-22: a location plate is never --anchor / image1."""
    if is_location_plate(path):
        raise ValueError(
            "location plate cannot be --anchor / image1 (T7-22)")
