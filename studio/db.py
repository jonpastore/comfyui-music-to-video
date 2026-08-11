"""sqlite state for Meow P Studio. Plain sqlite3 -- no ORM, no migrations tool.

Schema is created on import. Adding a column later means adding an ALTER to
MIGRATIONS; sqlite tolerates the duplicate-column error which is checked for.
"""
import json, os, sqlite3, threading, time

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("STUDIO_DATA", os.path.join(ROOT, "data"))
DB_PATH = os.path.join(DATA, "studio.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS songs (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, album TEXT, genre TEXT,
  slug TEXT UNIQUE NOT NULL, mp3_path TEXT, duration REAL, lyrics TEXT,
  anchor_path TEXT, style_path TEXT, bpm REAL, created REAL);

-- Anchor character sheets. Scoped to an ALBUM or PLAYLIST and a TIER, not to a
-- song: every track on Street Cats shares one look, and the clean and explicit
-- cuts differ only in wardrobe. One row per generated candidate; chosen=1 marks
-- the one that reference rendering will use for that scope+tier+view.
CREATE TABLE IF NOT EXISTS anchors (
  id INTEGER PRIMARY KEY,
  scope_kind TEXT NOT NULL,          -- 'album' | 'playlist'
  scope_value TEXT NOT NULL,         -- album name, or playlist id as text
  tier TEXT NOT NULL,
  view TEXT DEFAULT 'front',         -- front | back
  path TEXT NOT NULL,
  chosen INTEGER DEFAULT 0,
  created REAL);

CREATE TABLE IF NOT EXISTS tiers (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, guardrail TEXT NOT NULL,
  builtin INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS storyboards (
  id INTEGER PRIMARY KEY, song_id INTEGER NOT NULL, tier TEXT NOT NULL,
  json_path TEXT, md_path TEXT, scene_count INTEGER, created REAL,
  UNIQUE(song_id, tier));

CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY, song_id INTEGER, kind TEXT NOT NULL, path TEXT NOT NULL,
  meta_json TEXT, created REAL);

CREATE TABLE IF NOT EXISTS refs (
  id INTEGER PRIMARY KEY, song_id INTEGER NOT NULL, tier TEXT NOT NULL,
  clip_idx INTEGER NOT NULL, path TEXT NOT NULL, seed INTEGER,
  approved INTEGER DEFAULT 0, created REAL,
  UNIQUE(song_id, tier, clip_idx, seed));

CREATE TABLE IF NOT EXISTS clips (
  id INTEGER PRIMARY KEY, song_id INTEGER NOT NULL, tier TEXT NOT NULL,
  clip_idx INTEGER NOT NULL, path TEXT, status TEXT DEFAULT 'pending',
  UNIQUE(song_id, tier, clip_idx));

CREATE TABLE IF NOT EXISTS renders (
  id INTEGER PRIMARY KEY, song_id INTEGER NOT NULL, tier TEXT NOT NULL,
  path TEXT NOT NULL, created REAL);

CREATE TABLE IF NOT EXISTS playlists (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT DEFAULT 'playlist',
  UNIQUE(name, kind));

CREATE TABLE IF NOT EXISTS playlist_items (
  id INTEGER PRIMARY KEY, playlist_id INTEGER NOT NULL, song_id INTEGER NOT NULL,
  tier TEXT, position INTEGER NOT NULL, transition TEXT DEFAULT 'fade',
  secs REAL DEFAULT 2.0);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, args_json TEXT,
  status TEXT DEFAULT 'queued', progress TEXT, log_path TEXT,
  song_id INTEGER, created REAL, started REAL, finished REAL, error TEXT);

CREATE INDEX IF NOT EXISTS idx_anchors ON anchors(scope_kind, scope_value, tier, view);
CREATE INDEX IF NOT EXISTS idx_refs_song ON refs(song_id, tier, clip_idx);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, id);
"""

# Columns added after the initial schema. CREATE TABLE IF NOT EXISTS does not
# alter an existing table, so a deployed database keeps its old shape forever
# without this. Applied once each; the duplicate-column error is expected.
MIGRATIONS = [
    "ALTER TABLE songs ADD COLUMN subgenre TEXT",
    "ALTER TABLE songs ADD COLUMN genre2 TEXT",
    "ALTER TABLE songs ADD COLUMN subgenre2 TEXT",
    # Does the TRACK contain explicit lyrics. Nothing to do with which tier a
    # video is rendered at -- that is chosen per render, not stored per song.
    "ALTER TABLE songs ADD COLUMN explicit INTEGER DEFAULT 0",
    # song_tiers was a modelling mistake: ratings are not a property of a title.
    "DROP TABLE IF EXISTS song_tiers",
]


def _migrate(c):
    for stmt in MIGRATIONS:
        try:
            c.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    c.commit()


_local = threading.local()


def conn():
    """One connection per thread. WAL so the worker and web requests coexist."""
    c = getattr(_local, "c", None)
    if c is None:
        os.makedirs(DATA, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(SCHEMA)
        _migrate(c)
        _local.c = c
    return c


def q(sql, *args):
    return conn().execute(sql, args).fetchall()


def one(sql, *args):
    return conn().execute(sql, args).fetchone()


def run(sql, *args):
    c = conn()
    cur = c.execute(sql, args)
    c.commit()
    return cur.lastrowid


def upsert_song(slug, **f):
    row = one("SELECT id FROM songs WHERE slug=?", slug)
    if row:
        if f:
            sets = ", ".join(f"{k}=?" for k in f)
            run(f"UPDATE songs SET {sets} WHERE id=?", *f.values(), row["id"])
        return row["id"]
    f.setdefault("title", slug)
    f["slug"], f["created"] = slug, time.time()
    cols = ", ".join(f)
    return run(f"INSERT INTO songs ({cols}) VALUES ({', '.join('?' * len(f))})", *f.values())


def jset(row, key="meta_json"):
    """Decode a JSON column, tolerating NULL."""
    v = row[key] if row and key in row.keys() else None
    return json.loads(v) if v else {}
