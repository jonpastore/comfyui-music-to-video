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

-- Which box produced each rendered file. Tier 0 of docs/OUTPUT_QC_PLAN.md.
--
-- Keyed by PATH rather than being a column on anchors/clips/refs/assets,
-- because pipeline knows the backend at the moment it has the file and those
-- four tables are written later, in four different places, by app.py. One
-- write where the render lands cannot be forgotten by the next gen_* wrapper;
-- four columns can. Join on path when you want it per artefact.
--
-- `backend` is Swarm's numeric id and is NOT stable -- adding a backend
-- renumbers them (studio/models.py BACKEND_STABILITY says the same thing and
-- keys by host for the same reason). `host` is the durable identity; group by
-- that. Either may be NULL: SwarmUI does not report which backend served an
-- unpinned render, and a guess that cannot be checked is worse than a blank.
CREATE TABLE IF NOT EXISTS artefacts (
  path TEXT PRIMARY KEY, backend TEXT, host TEXT, via TEXT, created REAL,
  status TEXT);

-- T6-5: every job status change, with its time. jobs.created/started/finished
-- are the endpoints; this is the chain that answers "why did this take four hours".
CREATE TABLE IF NOT EXISTS job_transitions (
  id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, status TEXT NOT NULL, at REAL NOT NULL);

CREATE INDEX IF NOT EXISTS idx_job_transitions ON job_transitions(job_id, id);

-- One automation POINT. docs/TRD-1 4.1 and 5.
--
-- A row per point, not a JSON blob on set_items: the decimator has to DELETE
-- points, and a blob would make every mouse-up a read-modify-write of the whole
-- curve.
--
-- `t` is seconds FROM THE START OF THE ITEM, never from the start of the set.
-- A set-relative time is invalidated by every reorder, trim and transition
-- length change -- four ways for a curve to end up describing a moment that no
-- longer exists.
--
-- The timeline model lives on the SERVER, not in the DOM. These rows are the
-- model; the browser is a view of them.
CREATE TABLE IF NOT EXISTS automation (
  id INTEGER PRIMARY KEY,
  set_item_id INTEGER NOT NULL,
  lane TEXT NOT NULL,               -- gain_db | pan | lowpass_hz | highpass_hz
  t REAL NOT NULL,
  value REAL NOT NULL,
  curve TEXT DEFAULT 'linear',      -- linear | hold; no others, see automation.py
  UNIQUE(set_item_id, lane, t));

CREATE INDEX IF NOT EXISTS idx_automation ON automation(set_item_id, lane, t);

-- What QC measured about one artefact, one row per check. docs/TRD-3 3.
--
-- THE FINDING IS THE QUEUE. There is no second "review_queue" table, because
-- two stores of the same finding are two places for it to be in different
-- states -- and the review queue is just the open rows.
--
-- measured/expected/unit are carried on every check that has them: a finding
-- that says only "failed" cannot be argued with, and cannot be re-checked
-- after a repair to see whether the repair helped.
--
-- remedy_prompt_id points at prompt_versions. The remedy is an EDITABLE,
-- VERSIONED prompt and approving it is the human sign-off -- QC never
-- auto-heals. repair_path is the NEW candidate and is never the input path:
-- an overwrite destroys the evidence that anything was wrong along with the
-- comparison that would show whether the repair helped.
--
-- Join to artefacts on `path` for which box produced it. Group by artefacts.host,
-- never by backend -- Swarm renumbers backend ids when one is added.
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL,
  kind TEXT NOT NULL,                 -- image|audio|clip|song|set
  tier INTEGER NOT NULL,
  check_name TEXT NOT NULL,
  verdict TEXT NOT NULL,              -- pass|flag|reject
  measured TEXT, expected TEXT, unit TEXT,
  detail TEXT,
  remedy TEXT,                        -- what approving it would RUN
  remedy_prompt_id INTEGER,           -- prompt_versions.id; editable, versioned
  status TEXT DEFAULT 'open',         -- open|approved|running|repaired|dismissed
  dismissed_why TEXT,
  repair_path TEXT,
  created REAL, resolved REAL,
  UNIQUE(path, check_name));

CREATE INDEX IF NOT EXISTS idx_findings ON findings(status, kind, tier);
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

    # What the workflow that produced this artefact ASKED FOR (frames, fps,
    # width, height, duration). studio/qc.py compares the rendered file against
    # it; without it the duration and frame-count checks have nothing to compare
    # to and do not run. Derived from the submitted graph, never from the file.
    "ALTER TABLE artefacts ADD COLUMN expect_json TEXT",
    # T6-7: landed is a status, not implied by the row existing. NULL on every
    # row that predates this — those were written when the file was collected.
    "ALTER TABLE artefacts ADD COLUMN status TEXT",

    # What scene_seconds this storyboard was GENERATED with. The divisor for
    # every clip-length answer about this song (build_song.clip_seconds). NULL
    # means a storyboard from before clip length was per song, and the answer is
    # CHUNK -- so nothing already on disk changes length.
    "ALTER TABLE storyboards ADD COLUMN scene_seconds REAL",
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
    # Advisory vision score of this candidate vs the base photographs and
    # the prompt (T3-31). NULL on every row that predates scoring.
    "ALTER TABLE anchors ADD COLUMN qc_json TEXT",
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
    # The studio backdrop and the multi-reference clause, per album. Both were
    # constants in make_anchor with no override and no history, and both are
    # load-bearing prompt text: BACKDROP is five clauses of studio, lighting,
    # framing and focus that reach EVERY sheet, and COMPOSITE is the sentence
    # deciding whether three references are one character or three. An album
    # shot against a black cyclorama, or a project whose references are stills
    # rather than photographs, needs different words and had nowhere to put
    # them. docs/TRD-7 T7-14, T7-15.
    "ALTER TABLE playlists ADD COLUMN backdrop TEXT",
    "ALTER TABLE playlists ADD COLUMN composite TEXT",
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

TAKES_SCHEMA = """
-- A TAKE is one generated candidate for a song, exactly as a refs row is one
-- candidate frame. Generation is cheap and the good one is picked by ear, so a
-- take is never written over songs.mp3_path -- picking one is a separate act,
-- and the take that was not picked survives to be compared against it.
--
-- tags/lyrics/seed/duration/params are copied ONTO the take rather than read
-- back off the song: the song row moves on, and a take that cannot say what it
-- was asked for can be neither regenerated nor explained six months later.
-- songs.style_text is that ask for songs that predate takes, so insert_take
-- copies it into tags when no tags are supplied (T8-2a).
CREATE TABLE IF NOT EXISTS takes (
  id INTEGER PRIMARY KEY, song_id INTEGER NOT NULL,
  path TEXT NOT NULL, seed INTEGER,
  tags TEXT, lyrics TEXT,
  bpm REAL, keyscale TEXT, timesig TEXT, language TEXT,
  duration REAL, params_json TEXT,
  parent_id INTEGER,
  origin TEXT NOT NULL,              -- generated | resynthesised | bridged
  picked INTEGER DEFAULT 0,
  created REAL);

CREATE INDEX IF NOT EXISTS idx_takes_song ON takes(song_id, id);

-- A VOICE is a timbre reference. source and consent are why the row exists:
-- a nullable consent column that nothing enforces is a record filled with
-- silence. kind decides which of path/reference_id is meaningful.
CREATE TABLE IF NOT EXISTS voices (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL,                -- 'local' (a clip) | 'fish' (a hosted id)
  path TEXT, reference_id TEXT,
  source TEXT NOT NULL, consent TEXT NOT NULL,
  note TEXT, created REAL);

-- WHICH voice sings WHERE. Not a column on takes: a track can have several
-- singers per region. start/end are seconds on the take; 0/duration is the
-- whole track (NULL/NULL is not used -- it overlaps every bounded region).
CREATE TABLE IF NOT EXISTS take_voices (
  id INTEGER PRIMARY KEY, take_id INTEGER NOT NULL, voice_id INTEGER NOT NULL,
  start_secs REAL NOT NULL DEFAULT 0, end_secs REAL,
  params_json TEXT);

CREATE INDEX IF NOT EXISTS idx_take_voices ON take_voices(take_id);
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
        c.executescript(TAKES_SCHEMA)
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


# generated / resynthesised / bridged -- the three paths the audio job already
# names in assets.meta_json["mode"]. A free-text origin would make T8-3 pass
# for a take that recorded something else.
TAKE_ORIGINS = ("generated", "resynthesised", "bridged")


def insert_take(song_id, path, origin, *, tags=None, lyrics=None, seed=None,
                duration=None, params=None, parent_id=None, bpm=None,
                keyscale=None, timesig=None, language=None):
    """Record a candidate. Never writes songs.mp3_path.

    If tags is omitted the song's style_text is copied on, so a take generated
    from a song keeps the ask after the song row moves (T8-2a).
    """
    if origin not in TAKE_ORIGINS:
        raise ValueError(f"unknown take origin: {origin!r}")
    song = one("SELECT * FROM songs WHERE id=?", song_id)
    if song is None:
        raise ValueError(f"no song {song_id}")
    if tags is None:
        tags = song["style_text"]
    params_json = json.dumps(params) if params is not None else None
    return run(
        """INSERT INTO takes (song_id, path, seed, tags, lyrics, bpm, keyscale,
           timesig, language, duration, params_json, parent_id, origin, picked, created)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)""",
        song_id, path, seed, tags, lyrics, bpm, keyscale, timesig, language,
        duration, params_json, parent_id, origin, time.time())


def get_take(take_id):
    return one("SELECT * FROM takes WHERE id=?", take_id)


def list_takes(song_id):
    """Every take for a song, picked and unpicked, oldest first."""
    return q("SELECT * FROM takes WHERE song_id=? ORDER BY id", song_id)


def pick_take(take_id):
    """Mark this take as the picked one. Does not delete the others and does
    not write the take over songs.mp3_path -- that is the Use route's act."""
    take = get_take(take_id)
    if take is None:
        raise ValueError(f"no take {take_id}")
    c = conn()
    c.execute("UPDATE takes SET picked=0 WHERE song_id=?", (take["song_id"],))
    c.execute("UPDATE takes SET picked=1 WHERE id=?", (take_id,))
    c.commit()
    return take_id


def _recorded(value):
    """T8-10: empty or whitespace is not a recorded source/consent state."""
    return isinstance(value, str) and bool(value.strip())


def insert_voice(name, kind, source, consent, *, path=None, reference_id=None,
                 note=None):
    """Store a timbre reference. Refuses when source or consent is missing,
    and the refusal names which (T8-10). Does not clone anyone."""
    missing = [field for field, value in (("source", source), ("consent", consent))
               if not _recorded(value)]
    if missing:
        raise ValueError("voice missing recorded " + " and ".join(missing))
    return run(
        """INSERT INTO voices (name, kind, path, reference_id, source, consent,
           note, created) VALUES (?,?,?,?,?,?,?,?)""",
        name, kind, path, reference_id, source, consent, note, time.time())


def get_voice(voice_id):
    return one("SELECT * FROM voices WHERE id=?", voice_id)


def assign_take_voice(take_id, voice_id, start_secs=0, end_secs=None, params=None):
    return run(
        """INSERT INTO take_voices (take_id, voice_id, start_secs, end_secs, params_json)
           VALUES (?,?,?,?,?)""",
        take_id, voice_id, start_secs, end_secs,
        json.dumps(params) if params is not None else None)


def list_take_voices(take_id):
    return q("SELECT * FROM take_voices WHERE take_id=? ORDER BY id", take_id)


# T6-10: cascade policy stated per table, not inherited from sqlite defaults.
# Findings join on path, not song_id, so they are not in SONG_CASCADE.
SONG_CASCADE = (
    "storyboards", "refs", "clips", "renders", "assets",
    "playlist_items", "set_items", "jobs", "takes",
)


def delete_set_item(item_id):
    """T1-2 / T6-10: deleting a set item deletes its automation rows."""
    run("DELETE FROM automation WHERE set_item_id=?", item_id)
    run("DELETE FROM set_items WHERE id=?", item_id)


def delete_song_rows(song_id):
    """T6-10: an intended song delete does not silently orphan children.

    Files stay the caller's problem (containment rules live at the route).
    Automation is keyed by set_item_id; findings and artefacts by path.
    """
    items = q("SELECT id FROM set_items WHERE song_id=?", song_id)
    for r in items:
        run("DELETE FROM automation WHERE set_item_id=?", r["id"])
    paths = []
    for table in ("clips", "refs", "renders", "assets", "takes"):
        paths.extend(
            r["path"] for r in q(f"SELECT path FROM {table} WHERE song_id=?", song_id)
            if r["path"])
    song = one("SELECT mp3_path, style_path, anchor_path FROM songs WHERE id=?", song_id)
    if song:
        paths.extend(p for p in (song["mp3_path"], song["style_path"], song["anchor_path"]) if p)
    for p in paths:
        run("DELETE FROM findings WHERE path=?", p)
        run("DELETE FROM artefacts WHERE path=?", p)
    for table in SONG_CASCADE:
        run(f"DELETE FROM {table} WHERE song_id=?", song_id)
    run("DELETE FROM songs WHERE id=?", song_id)
