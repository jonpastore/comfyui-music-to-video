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
  image_path TEXT, created REAL,
  UNIQUE(name, kind));

-- A playlist item is a SONG, in an order, with the transition used to reach
-- the next one. No tier: a tier is a rendering choice made when the set is
-- rendered (and a set can be rendered at several tiers from one playlist),
-- exactly as it is for a single song. transition/secs are VIDEO effects that
-- also drive the audio crossfade of the mix.
CREATE TABLE IF NOT EXISTS playlist_items (
  id INTEGER PRIMARY KEY, playlist_id INTEGER NOT NULL, song_id INTEGER NOT NULL,
  position INTEGER NOT NULL, transition TEXT DEFAULT 'fade',
  secs REAL DEFAULT 2.0);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, args_json TEXT,
  status TEXT DEFAULT 'queued', progress TEXT, log_path TEXT,
  song_id INTEGER, created REAL, started REAL, finished REAL, error TEXT);

-- The CAST of an album. The album profile (playlists.identity/wardrobe/body)
-- describes the protagonist and keeps doing so; these are the OTHER named
-- characters -- a duet partner, an antagonist -- each with its own anchors.
-- Scoped by album NAME, exactly as anchors.scope_value already is, so nothing
-- new has to be linked up.
--
-- Extras and background characters deliberately have no row: the storyboard is
-- told to name only main actors, because only a main actor needs an anchor to
-- stay consistent across 50 frames.
CREATE TABLE IF NOT EXISTS characters (
  id INTEGER PRIMARY KEY,
  scope_value TEXT NOT NULL,         -- album name
  name TEXT NOT NULL,
  role TEXT,                         -- free text: "antagonist", "duet partner"
  identity TEXT, wardrobe TEXT, body TEXT,
  created REAL,
  UNIQUE(scope_value, name));

-- Remembered per-role model choices (see models.py). Not per song: picking
-- a renderer is a studio-wide preference, and a per-song copy would go stale
-- the moment a model is replaced.
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT);

-- Where finished work may be published. One row per DESTINATION, not per
-- service: each subreddit has its own rules and its own NSFW status, and its
-- own adult policy, and that is exactly the distinction that must not be lost.
-- adult_ok is the per-target switch (an NSFW subreddit vs an ordinary one);
-- publish.SERVICES holds the policy of the service itself, which a target can
-- never exceed.
CREATE TABLE IF NOT EXISTS publish_targets (
  id INTEGER PRIMARY KEY,
  service TEXT NOT NULL,
  name TEXT NOT NULL,
  adult_ok INTEGER DEFAULT 0,
  note TEXT,
  enabled INTEGER DEFAULT 1,
  created REAL,
  UNIQUE(service, name));

-- A set is a DOCUMENT now, not just a render. playlist_id is nullable: a set
-- need not come from a playlist. mode/tier live here rather than only on the
-- rendered asset, because they are what the EDITOR shows, and a set can be
-- re-rendered any number of times without them being re-chosen each time.
CREATE TABLE IF NOT EXISTS sets (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, playlist_id INTEGER,
  tier TEXT, mode TEXT DEFAULT 'video',
  created REAL, updated REAL);

-- One song, in order, with the trim/transition/gain that gets it there.
-- effects_json is carried but unused until phase 4 fills it in.
CREATE TABLE IF NOT EXISTS set_items (
  id INTEGER PRIMARY KEY, set_id INTEGER NOT NULL, song_id INTEGER NOT NULL,
  position INTEGER NOT NULL,
  in_secs REAL, out_secs REAL,
  transition TEXT DEFAULT 'fade', secs REAL DEFAULT 2.0,
  gain_db REAL DEFAULT 0,
  effects_json TEXT);

CREATE INDEX IF NOT EXISTS idx_set_items ON set_items(set_id, position);
CREATE INDEX IF NOT EXISTS idx_anchors ON anchors(scope_kind, scope_value, tier, view);
CREATE INDEX IF NOT EXISTS idx_characters ON characters(scope_value, name);
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
    # The music-generation style prompt (written elsewhere, e.g. ChatGPT, and
    # pasted into Suno). Kept beside the lyrics because they are the pair that
    # made the track. Distinct from style_path, which is a visual reference
    # IMAGE for the video -- this one describes the AUDIO.
    "ALTER TABLE songs ADD COLUMN style_text TEXT",
    # Playlist cards: cover art, and a creation date to show on the collapsed
    # card. Existing rows get created=NULL, which the page renders as blank
    # rather than pretending to know when they were made.
    "ALTER TABLE playlists ADD COLUMN image_path TEXT",
    "ALTER TABLE playlists ADD COLUMN created REAL",
    # Playlists do not have tiers. Membership is the SONG; the tier is picked
    # when the set is rendered, and one playlist can render a set per tier.
    "ALTER TABLE playlist_items DROP COLUMN tier",
    # THE ALBUM PROFILE. An album and a playlist are the same record here.
    # These are the descriptions that used to be hardcoded in make_anchor.py
    # and build_refs.py -- who the character is, what they wear, the world they
    # are in. A second album is now a row to fill in, not a script to fork, and
    # every one of these has a UI field with default text.
    "ALTER TABLE playlists ADD COLUMN style_text TEXT",   # overarching theme
    "ALTER TABLE playlists ADD COLUMN identity TEXT",     # face / hair / who
    "ALTER TABLE playlists ADD COLUMN wardrobe TEXT",
    "ALTER TABLE playlists ADD COLUMN body TEXT",         # colouring, consistency
    "ALTER TABLE playlists ADD COLUMN world TEXT",
    "ALTER TABLE playlists ADD COLUMN render_tail TEXT",
    # The DIRECTION the storyboard was generated from: the editable prompt, as
    # sent. Stored so re-opening a storyboard shows what produced it -- the
    # composed prompt was previously invisible, which is why a bad storyboard
    # could not be diagnosed without reading grok.py.
    "ALTER TABLE storyboards ADD COLUMN prompt TEXT",
    # How a reference frame came to exist: gen | reroll | face | inpaint |
    # outpaint. Existing rows read NULL, which the UI shows as 'gen' -- they
    # all predate repair and were all generated.
    "ALTER TABLE refs ADD COLUMN origin TEXT",
    # WHICH character an anchor depicts. NULL = the album's protagonist, which
    # is every row that existed before the cast did -- so chosen_anchor() and
    # every refs job keep working untouched.
    "ALTER TABLE anchors ADD COLUMN character_id INTEGER",
    # Whether this tier may depict nudity. A CAPABILITY, not prompt text: it
    # gates whether a nude anchor can be generated. Default 0 is the safe one --
    # an existing custom tier does not silently acquire the permission.
    # The built-ins set their own (pg13=0, r=1, xxx=1) in tiers.ensure_builtins.
    "ALTER TABLE tiers ADD COLUMN allow_nudity INTEGER DEFAULT 0",
    # Per-song metadata from analyse.py (SETS_MIXING_PLAN.md phase 2). bpm
    # already existed and had never been written to; these are its partners.
    # key is Camelot notation ("8A"), beat_grid_json a JSON list of beat
    # times in seconds, energy the mean RMS. downbeat_offset is which of the
    # first four beats analyse.py guessed is bar one -- left editable because
    # a wrong guess sounds wrong in a way no amount of tuning fixes, and a
    # human listening once fixes it in a second.
    "ALTER TABLE songs ADD COLUMN key TEXT",
    "ALTER TABLE songs ADD COLUMN beat_grid_json TEXT",
    "ALTER TABLE songs ADD COLUMN energy REAL",
    "ALTER TABLE songs ADD COLUMN downbeat_offset INTEGER DEFAULT 0",
    # Per-item opt-in to beat matching the transition into the NEXT item
    # (SETS_MIXING_PLAN.md phase 3). Default 0: an existing set's transitions
    # keep behaving exactly as rendered until a user turns this on.
    "ALTER TABLE set_items ADD COLUMN beatmatch INTEGER DEFAULT 0",
    # Plain-language mixing note for this handover, kept beside the JSON it
    # produces. The JSON stays the source of truth -- this records what was
    # ASKED for, so a re-suggest starts from the intent rather than the output.
    "ALTER TABLE set_items ADD COLUMN mix_direction TEXT",
    # How long the screen stays black between two songs, for transition='black'
    # (ALBUM_ARC_AND_STAGING_PLAN.md sec 1). The ONLY new number that shape
    # needs: the fades either side come out of `secs`, and the hold is the
    # only part that lengthens the set. Default 0 so an existing row cannot
    # acquire a pause nobody asked for.
    "ALTER TABLE set_items ADD COLUMN hold REAL DEFAULT 0",
    # A branding still faded over a handover (ALBUM_ARC_AND_STAGING_PLAN.md
    # sec 2). One default per SET -- an album mark is the normal case -- and a
    # per-item override for the handover that wants a different card. An
    # overlay changes no duration, so neither column touches any length
    # arithmetic.
    "ALTER TABLE sets ADD COLUMN brand_path TEXT",
    "ALTER TABLE set_items ADD COLUMN brand_path TEXT",
    # Which handovers actually get the set's default mark. Off by default: a
    # mark on every transition is a slideshow, the same objection the plan
    # makes to a fade to black between every song.
    "ALTER TABLE set_items ADD COLUMN branded INTEGER DEFAULT 0",
    # The render settings this candidate was actually produced with, as the
    # JSON that pipeline.gen_anchor turned into command-line flags. A CFG sweep
    # puts a dozen sheets in one group that differ only by guidance, and
    # nothing in the filename says which is which -- so "cfg 6.0 haloes" was a
    # claim about an image nobody could identify afterwards. NULL on every row
    # that predates this, which the UI shows as no badge rather than as a
    # setting nobody chose.
    "ALTER TABLE anchors ADD COLUMN render_json TEXT",
    # Which BOX a saved version came out of: 'positive' | 'negative'. The
    # negative prompt is per ALBUM, not per tier -- it lists this release's
    # failure modes, and another album's art wants a different list -- so a
    # negative row carries tier='' and character_id NULL. NULL reads as
    # 'positive', which is what every row written before this column is.
    "ALTER TABLE anchor_prompts ADD COLUMN kind TEXT DEFAULT 'positive'",
    # WHICH generation produced this candidate (anchor_runs.id). NULL on every
    # row that predates the table, which is why render_json below it stays as
    # the fallback rather than being dropped -- 33 sheets from the first CFG
    # sweep carry their settings there and nowhere else.
    "ALTER TABLE anchors ADD COLUMN run_id INTEGER",
    # The nude swap and the anatomy clause, per album. make_anchor's default
    # nude wording says "bare skin over the whole body", which contradicts a
    # furred or scaled body clause in the same prompt; and nothing ever asked
    # for anatomy, so nude sheets came back featureless. Both are prompt text
    # the album owns, so they live beside identity/wardrobe/body.
    "ALTER TABLE playlists ADD COLUMN nude_wardrobe TEXT",
    "ALTER TABLE playlists ADD COLUMN anatomy TEXT",
    # ...and per CHARACTER, for the same reason they exist per album. Only
    # identity/wardrobe/body were per-character, so every cast member's nude
    # sheet was rendered with the PROTAGONIST's nude wording and the
    # protagonist's anatomy clause -- a duet partner of a different species got
    # the lead's fur described onto her. Invisible unless two characters are
    # compared side by side, and nothing in the anchors table records which.
    "ALTER TABLE characters ADD COLUMN nude_wardrobe TEXT",
    "ALTER TABLE characters ADD COLUMN anatomy TEXT",
]

# API keys, encrypted at rest (ALBUM_ARC_AND_STAGING_PLAN.md sec 5, and
# creds.py's own docstring for what that does and does not buy). Its own
# statement rather than a line in SCHEMA because it is the only table holding
# anything sensitive, and that is worth being able to find.
ANCHOR_PROMPTS_SCHEMA = """
-- Saved anchor prompts, VERSIONED. The per-tier prompt had nowhere to live: it
-- was recomposed from the album profile on every page load and only travelled
-- with the job, so an edit was lost the moment you navigated away. Versions
-- rather than one row because a prompt is tuned by comparing renders, and the
-- one you want back is usually the one before last.
CREATE TABLE IF NOT EXISTS anchor_prompts (
  id INTEGER PRIMARY KEY,
  scope_value TEXT NOT NULL,          -- album name, as anchors are scoped
  tier TEXT NOT NULL,
  character_id INTEGER,               -- NULL is the protagonist, as everywhere else
  label TEXT,
  text TEXT NOT NULL,
  created REAL);

CREATE INDEX IF NOT EXISTS idx_anchor_prompts
  ON anchor_prompts(scope_value, tier, character_id, id);
"""

PROMPT_VERSIONS_SCHEMA = """
-- Versioned prompt text, for every kind of prompt this studio sends. See
-- prompts.py for what a version means and why usage_count counts renders
-- rather than loads.
--
-- One table for all types, replacing two half-systems: anchor_prompts with a
-- `kind` column bolted on to fit the negative, and the component fields
-- (identity/wardrobe/body) which had no history at all -- editing one
-- overwrote the previous wording with nothing kept.
--
-- tier is "" for a type that is album-wide; character_id NULL is the
-- protagonist, as everywhere else. version_number is per (album, tier,
-- character, type) and is NOT renumbered when one is deleted: the number is how
-- a render is referred to afterwards, so closing the gap would repoint an old
-- note at different text.
CREATE TABLE IF NOT EXISTS prompt_versions (
  id INTEGER PRIMARY KEY,
  scope_value TEXT NOT NULL,          -- album name, as anchors are scoped
  tier TEXT NOT NULL DEFAULT '',
  character_id INTEGER,
  prompt_type TEXT NOT NULL,
  version_number INTEGER NOT NULL,
  label TEXT,
  text TEXT NOT NULL,
  created REAL NOT NULL,
  updated REAL,
  usage_count INTEGER DEFAULT 0,
  UNIQUE(scope_value, tier, character_id, prompt_type, version_number));

CREATE INDEX IF NOT EXISTS idx_prompt_versions
  ON prompt_versions(scope_value, prompt_type, tier, character_id, version_number);
"""

ANCHOR_RUNS_SCHEMA = """
-- One row per GENERATION: everything that was sent, once, with the candidates
-- it produced pointing back at it (anchors.run_id).
--
-- Two things this buys that a per-candidate settings blob could not. You can
-- LOAD a previous run's settings back into the form instead of remembering
-- what you did an hour ago; and looking at a sheet you can see exactly what
-- produced it -- prompt, negative, references and sampler together, not just
-- the numbers. A CFG sweep makes the second one load-bearing: eleven runs land
-- in one grid and differ only by guidance.
--
-- settings_json is the RESOLVED sampler dict, the one build_refs hands the
-- KSampler, so it already has the mode's defaults folded in. form_json is what
-- was actually chosen on the form -- keeping both is what makes "leave it on
-- the mode default" reloadable AS a default rather than as the number it
-- happened to resolve to that day.
CREATE TABLE IF NOT EXISTS anchor_runs (
  id INTEGER PRIMARY KEY,
  scope_value TEXT NOT NULL,          -- album name, as anchors are scoped
  tier TEXT NOT NULL,
  view TEXT NOT NULL,
  character_id INTEGER,               -- NULL is the protagonist, as everywhere else
  n INTEGER NOT NULL,
  prompt TEXT,                        -- "" means make_anchor composed it per view
  negative TEXT,
  guardrail TEXT,                     -- the tier wording in force for this album
  settings_json TEXT NOT NULL,        -- resolved: what the KSampler was built with
  form_json TEXT NOT NULL,            -- chosen: what the form sent, before resolution
  refs_json TEXT,                     -- the reference images conditioned on
  created REAL);

CREATE INDEX IF NOT EXISTS idx_anchor_runs
  ON anchor_runs(scope_value, tier, character_id, id);
"""

TIER_OVERRIDES_SCHEMA = """
-- One ALBUM's own wording for a tier. The tiers table stays what it is: the
-- studio-wide definition of what R or XXX means. This is the per-album
-- exception, so tuning the XXX wording for one release cannot silently
-- re-word every other album's XXX sheets -- which is the whole reason the
-- anchor form's wording box is not simply an editor for tiers.guardrail.
--
-- The pinned adult-safety clause is NOT stored here and cannot be: it is
-- welded on by tiers.compose(), which every path through compose_guardrail()
-- ends in. An override replaces the tone-and-wardrobe half only.
CREATE TABLE IF NOT EXISTS tier_overrides (
  id INTEGER PRIMARY KEY,
  scope_value TEXT NOT NULL,          -- album name, as anchors are scoped
  tier TEXT NOT NULL,
  guardrail TEXT NOT NULL,
  created REAL,
  UNIQUE(scope_value, tier));
"""

ARCS_SCHEMA = """
-- The album's STORY (ALBUM_ARC_AND_STAGING_PLAN.md sec 4). Same shape as
-- storyboards -- JSON and markdown on disk, one row pointing at them -- so an
-- arc can be read, diffed and regenerated the same way. An album IS a playlist,
-- and UNIQUE(playlist_id) is deliberate: one story per album, replaced rather
-- than accumulated, because thirty-one storyboards need one answer.
CREATE TABLE IF NOT EXISTS arcs (
  id INTEGER PRIMARY KEY, playlist_id INTEGER NOT NULL,
  json_path TEXT, md_path TEXT, model TEXT, prompt TEXT, created REAL,
  UNIQUE(playlist_id));
"""

CREDENTIALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS credentials (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
  ciphertext BLOB NOT NULL, created REAL, updated REAL);
"""


def _migrate(c):
    for stmt in MIGRATIONS:
        try:
            c.execute(stmt)
        except sqlite3.OperationalError as e:
            # "duplicate column": an ADD COLUMN already applied.
            # "no such column": a DROP COLUMN already applied, or a fresh
            # database whose SCHEMA never had it. Both mean the migration has
            # nothing left to do; anything else is a real error.
            msg = str(e).lower()
            if "duplicate column" not in msg and "no such column" not in msg:
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
        c.executescript(ANCHOR_PROMPTS_SCHEMA)
        c.executescript(TIER_OVERRIDES_SCHEMA)
        c.executescript(ANCHOR_RUNS_SCHEMA)
        c.executescript(PROMPT_VERSIONS_SCHEMA)
        c.executescript(ARCS_SCHEMA)
        c.executescript(CREDENTIALS_SCHEMA)
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
