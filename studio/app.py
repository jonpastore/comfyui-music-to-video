"""FastAPI web layer for Meow P Studio. Routes only -- all real work happens
in db/tiers/jobs/pipeline/grok/lyrics/mixer; this file wires HTTP to them and
does upload validation + path-traversal-safe media serving.
"""
import json, math, os, random, re, shutil, sqlite3, tempfile, time
from contextlib import asynccontextmanager
from typing import Annotated, List, Optional
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Query, Request, UploadFile, File
from pydantic import BeforeValidator
from fastapi.responses import (HTMLResponse, JSONResponse, RedirectResponse, FileResponse,
                                PlainTextResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db
import tiers  # also puts the repo-root scripts on sys.path (STUDIO_SCRIPTS)
import build_song  # clip_plan/allocate/sname -- the renderers' own definitions
import make_anchor  # is_nude_view: nudity is DERIVED from the view, not listed twice
# CHUNK is NOT imported here any more: clip length is per song, and a module
# level constant in the web layer is how it would silently become global again.
# build_song.clip_seconds() answers it, falling back to CHUNK itself for a
# storyboard generated before the length was recorded.
import jobs
import pipeline
import grok
import models
import vision
import lyrics
import mixer
import mixadvice
import arc
import chat
import creds
import publish
import prompts
import analyse
import effects    # per-item audio DJ effects -- pure, no deps, validated for real (not stubbed)
import automation  # set-item curves: fragments + the loudnorm decision
import qc          # tier-1 output checks: pure measurement, no db, no app
import qc_service   # recording those findings and answering the review queue
import video_fx   # per-item video look effects -- same, pure/no deps

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT, "static")
TEMPLATES_DIR = os.path.join(ROOT, "templates")

# Read once at import -- genres.json is data, not config that changes per request.
with open(os.path.join(ROOT, "genres.json")) as _f:
    GENRE_DATA = json.load(_f)["genres"]

HOST = os.environ.get("STUDIO_HOST", "0.0.0.0")
PORT = int(os.environ.get("STUDIO_PORT", "8000"))

MAX_MP3 = 50 * 1024 * 1024
MAX_IMAGE = 20 * 1024 * 1024
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_REROLL_CLIPS = 64
# The FORM's gain bound is the FILTER BUILDER's bound, imported rather than
# retyped. These were (-30, +30) here and (-60, +24) in effects.gain() -- two
# sanity bounds for one field, which never fired only because the gain_db column
# did not go through effects.gain() until 2026-08-13. It does now, so a value
# this form accepted at +30 would have raised at RENDER time, on a set already
# saved. One source, and the filter builder owns it because it is the thing that
# has to emit a filter ffmpeg accepts.
GAIN_DB_RANGE = (effects.GAIN_MIN_DB, effects.GAIN_MAX_DB)

# A BLANK form field arrives as "", and a bare Optional[int]/Optional[float]
# answers 422 rather than None. Both places that hit this mean "not given":
# the protagonist is the EMPTY option on every character <select>, and an empty
# trim-end means play to the end.
#
# On the anchor form the 422 was silent and total: hx-include sends the whole
# form on every tier or view tick, htmx does not swap a non-2xx response, so the
# tier tabs, the plan and the sheet count all froze at the last render that
# happened to succeed while the checkboxes kept moving underneath them.
_blank_none = BeforeValidator(lambda v: None if v in ("", None) else v)
CharacterId = Annotated[Optional[int], _blank_none]
BlankFloat = Annotated[Optional[float], _blank_none]
BlankInt = CharacterId  # same blank-string -> None coercion, for any optional-id field

# mixer owns this: it is the only module that knows what it can render.
SET_TRANSITIONS = mixer.TRANSITIONS

# docs/TRD-1 §7. Audiences, not densities. One data model; three affordance
# sets. Easy is a feature set (auto-level / auto-fade / one-button master),
# not a CSS class -- mixer.master_engaged reads mode_audience == "easy".
AUDIENCES = ("easy", "normal", "advanced")
_AFFORDANCES = {
    "easy": frozenset({
        "auto_level", "auto_fade", "one_button_master",
        "trim", "transition", "mix_direction",
    }),
    "normal": frozenset({
        "trim", "gain", "transition", "hold", "beatmatch", "branded",
        "mix_direction", "effects", "automation_lanes", "defaults_visible",
    }),
    "advanced": frozenset({
        "trim", "gain", "transition", "hold", "beatmatch", "branded",
        "mix_direction", "effects", "automation_lanes", "defaults_visible",
        "mastering_chain", "unrounded_numbers",
    }),
}


def audience_affordances(mode):
    """Controls this audience may operate. Unknown / missing -> normal."""
    return _AFFORDANCES[mode if mode in _AFFORDANCES else "normal"]


def _set_audience(row):
    mode = row["mode_audience"] if "mode_audience" in row.keys() else None
    return mode if mode in AUDIENCES else "normal"

# Anything servable over /media must resolve inside one of these -- reuses
# pipeline's own ComfyUI paths rather than inventing a parallel config knob.
MEDIA_ROOTS = [os.path.realpath(db.DATA), os.path.realpath(pipeline.COMFY_INPUT),
               os.path.realpath(pipeline.COMFY_OUTPUT)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed the built-in tiers HERE, not lazily. ensure_builtins() used to run
    # only from all_tiers(), so on a fresh database every tier-validating route
    # -- refs, clips, classify, video sets -- answered "no such tier: pg13"
    # until someone happened to load a page that listed tiers. The deployed box
    # worked only because /tiers had been visited early.
    tiers.ensure_builtins()
    jobs.start()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["media_url"] = lambda p: media_url(p)
templates.env.globals["jset"] = db.jset


def hms(secs):
    """Seconds -> m:ss, or h:mm:ss past an hour. Blank for unknown, because a
    playlist of un-probed songs should not claim to be 0:00 long."""
    if not secs:
        return "" if secs is None else "0:00"
    secs = int(round(float(secs)))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


templates.env.filters["hms"] = hms
# Tier names are DISPLAYED uppercase everywhere -- PG13, R, XXX read as the
# content ratings they are, where "pg13" reads as a variable name. The stored
# value stays lowercase: it is the key every form, route and query uses, so
# only the presentation changes.
templates.env.filters["tiername"] = lambda t: (t or "").upper()
# Anchor views are stored as keys (front / back / front_nude / back_nude) and
# read as prose.
# Derived from make_anchor.VIEWS — the only table. A label edited here used
# to drift from the framing in DEFAULT_VIEWS; adding a view meant two files.
# docs/TRD-7 T7-1.
ANCHOR_VIEWS = {k: v["label"] for k, v in make_anchor.VIEWS.items()}
NUDE_VIEWS = frozenset(v for v in ANCHOR_VIEWS if make_anchor.is_nude_view(v))
templates.env.filters["viewname"] = lambda v: ANCHOR_VIEWS.get(v, v or "")


def view_base(view):
    """Camera/position key with the nude suffix stripped."""
    key = str(view or "")
    return key[:-5] if key.endswith("_nude") else key


def view_family(view):
    return "nude" if _make_anchor().is_nude_view(view) else "clothed"


def view_position_label(view):
    """Row label for a camera: 'front', 'on all fours'."""
    label = ANCHOR_VIEWS.get(view) or view or ""
    return label.split(",")[0].strip() or view_base(view).replace("_", " ")
# UTC ISO-8601 with the Z. The server runs UTC and the studio is used from a
# machine that does not, so the BROWSER converts this to local time (app.js).
# Formatting it server-side would show whichever timezone cerberus happens to
# be in, which is never the one the reader is in.
templates.env.filters["isotime"] = lambda t: (
    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else "")


def candidate_settings(row):
    """The resolved sampler settings behind one candidate, as a dict.

    The RUN is the source. render_json is read only when there is no run, which
    means a sheet from before anchor_runs existed -- 33 of them, from the first
    CFG sweep, carry their settings there and nowhere else. Two readers, one
    at a time, never both for the same row.
    """
    if not row:
        return {}
    run_id = row["run_id"] if "run_id" in row.keys() else None
    if run_id:
        run = anchor_run(run_id)
        if run:
            return db.jset(run, "settings_json")
    raw = row["render_json"] if "render_json" in row.keys() else None
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def render_tag(render_json):
    """The settings a candidate was rendered at, in one line, or "".

    Takes either the stored JSON string or an already-decoded dict, so the
    template can hand it a candidate's settings from whichever place they live.
    Empty when nothing is known -- an unlabelled thumbnail is honest about that,
    and a guessed default stamped on it would not be.
    """
    if isinstance(render_json, dict):
        s = render_json
    else:
        try:
            s = json.loads(render_json) if render_json else {}
        except ValueError:
            return ""
    if not s:
        return ""
    # "cfg 1.0", not "cfg 1" -- the badge has to read as the same value the
    # dropdown offered, or the thumbnail and the control name it differently.
    cfg = f"{float(s['cfg']):g}" if "cfg" in s else ""
    bits = [f"cfg {cfg}{'' if '.' in cfg else '.0'}"] if cfg else []
    if s.get("steps"):
        bits.append(f"{s['steps']} steps")
    if s.get("sampler_name"):
        bits.append(str(s["sampler_name"]))
    if s.get("lora_strength"):
        bits.append("Lightning LoRA")
    return " · ".join(bits)


templates.env.filters["rendertag"] = render_tag
# a candidate row -> the settings that produced it, run first
templates.env.filters["runsettings"] = lambda row: candidate_settings(row)


def score_generated_still(path, bases, prompt="", progress=None):
    """Advisory T3-31 score for any landed still. Never a gate."""
    try:
        return json.dumps(vision.score_candidate(
            path, bases or [], prompt or "", progress))
    except Exception as e:
        if progress:
            progress(f"vision score skipped: {e}")
        return json.dumps({
            "confidence": None, "identity": None, "prompt": None,
            "notes": "", "error": str(e)[:200], "backend": "local",
        })


def refine_generated_still(src, progress=None, extra=None):
    """Postproc repair: a NEW file beside src. Never overwrite (T3-6)."""
    root, ext = os.path.splitext(src)
    dest = f"{root}_refine{ext or '.png'}"
    if os.path.abspath(dest) == os.path.abspath(src):
        dest = src + ".refine.png"
    args = {
        "kind": "image",
        "path": src,
        "repair_path": dest,
        "remedy": "refine identity, asked pose and surface; keep the same adult character",
        "mode": "inpaint",
        "slug": extra.get("slug") if extra else "still",
        "tier": (extra or {}).get("tier") or "r",
        "clip_idx": int((extra or {}).get("clip_idx") or 0),
        "seed": int((extra or {}).get("seed") or 0),
    }
    if extra:
        args.update({k: v for k, v in extra.items() if v is not None})
    return qc_service.produce_repair(src, dest, args, progress)


def qc_tag(row):
    """One-line advisory vision score, or "" if this row was never scored."""
    if not row:
        return ""
    raw = row["qc_json"] if hasattr(row, "keys") and "qc_json" in row.keys() else (
        row.get("qc_json") if isinstance(row, dict) else None)
    try:
        s = json.loads(raw) if raw else {}
    except ValueError:
        return ""
    n = s.get("confidence")
    if n is None:
        err = (s.get("error") or "").strip()
        if not err:
            return ""
        # "vision unknown" hid the two live causes: no local VL, xAI 400.
        short = err.split(":")[0].strip()
        backend = (s.get("backend") or "").strip()
        if backend and backend.lower() not in short.lower():
            short = f"{backend} {short}".strip()
        return f"vision: {short[:48]}"
    return f"{int(n)}% match"


templates.env.filters["qctag"] = qc_tag


def opposite_view(view):
    """The other side of the same sheet: front <-> back, keeping clothed/nude.

    A character sheet is read as a PAIR -- you check the back against the front
    -- so the viewer opens both at once.
    """
    pairs = {"front": "back", "back": "front",
             "front_nude": "back_nude", "back_nude": "front_nude"}
    # clothed <-> nude of the same camera for the new views
    for key in make_anchor.VIEWS:
        if key.endswith("_nude"):
            pairs.setdefault(key, key[:-5])
            pairs.setdefault(key[:-5], key)
    return pairs.get(view)


def album_anchor_tiers(album):
    """Anchors for one album, grouped tier -> clothed/nude row -> sheets.

    Each sheet carries its version (its position within its own character +
    tier + view group, oldest first) and the path of its opposite view, so the
    viewer can show front and back together without another query.
    """
    rows = db.q("""SELECT a.*, c.name AS character_name
                   FROM anchors a LEFT JOIN characters c ON c.id = a.character_id
                   WHERE a.scope_kind='album' AND a.scope_value=?
                   ORDER BY a.tier, c.name, a.view, a.created, a.id""", album or "")
    # version numbering and opposite-view lookup both key off the same group
    by_group, version = {}, {}
    for r in rows:
        key = (r["tier"], r["character_id"], r["view"])
        by_group.setdefault(key, []).append(r)
    for key, group in by_group.items():
        for i, r in enumerate(group, 1):
            version[r["id"]] = i

    def opposite_path(r):
        other = by_group.get((r["tier"], r["character_id"], opposite_view(r["view"])))
        if not other:
            return None
        return next((o["path"] for o in other if o["chosen"]), other[-1]["path"])

    out = []
    for tier in sorted({r["tier"] for r in rows}):
        allows = tiers.allows_nudity(tier)
        tier_rows, count = [], 0
        for nude, label in ((False, "Clothed"), (True, "Nude")):
            # a nude row is only shown for a tier that permits nudity -- but if
            # sheets exist from before the flag was turned off, they are still
            # listed rather than becoming invisible and undeletable
            group = [r for r in rows
                     if r["tier"] == tier and ((r["view"] in NUDE_VIEWS) == nude)]
            if not group or (nude and not allows and not group):
                continue
            tier_rows.append({"label": label, "nude": nude, "anchors": [
                dict(r, version=version[r["id"]], opposite=opposite_path(r)) for r in group]})
            count += len(group)
        if tier_rows:
            out.append({"name": tier, "count": count, "rows": tier_rows})
    return out, rows
templates.env.filters["ts"] = lambda t: (
    time.strftime("%Y-%m-%d", time.localtime(t)) if t else "date unknown")
# time of day for job rows: a date is useless for telling this render from the
# one before it, which is the whole point of showing start and end
templates.env.filters["clock"] = lambda t: (
    time.strftime("%H:%M:%S", time.localtime(t)) if t else "")


@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    """Reject oversized uploads by Content-Length before the multipart body is
    parsed -- File(...)/Form(...) params are resolved before the route function
    runs, so a check inside the handler happens after the whole body (up to
    several GB) is already spooled to disk."""
    if request.method == "POST":
        path = request.url.path
        if path == "/songs":
            cap = MAX_MP3 + 8192
        elif path.endswith("/style"):
            cap = MAX_IMAGE + 8192
        elif path == "/anchors":
            cap = 2 * MAX_IMAGE + 8192
        else:
            cap = None
        if cap is not None:
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > cap:
                return PlainTextResponse("upload too large", status_code=413)
    return await call_next(request)


# ---------------------------------------------------------------- helpers --

def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "song"


def unique_slug(title):
    base = slugify(title)
    slug, i = base, 2
    while db.one("SELECT id FROM songs WHERE slug=?", slug):
        slug = f"{base}-{i}"
        i += 1
    return slug


def safe_name(name):
    name = os.path.basename(name or "")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name[:200] or "file"


def media_url(path):
    if not path:
        return None
    return "/media/" + quote(os.path.realpath(path), safe="/")


def scene_seconds_for(song_id, tier):
    """What scene length this song's storyboard at this tier was generated with.

    None for a storyboard written before it was recorded, which build_song reads
    as CHUNK. Every clip-count and clip-timing answer routes through here, so
    there is one lookup rather than a constant repeated at six call sites.
    """
    row = db.one("SELECT scene_seconds FROM storyboards WHERE song_id=? AND tier=?",
                 song_id, tier)
    return row["scene_seconds"] if row else None


def clip_count(song, scene_seconds=None):
    """How many clips this track is cut into.

    Comes from the AUDIO LENGTH, never from the storyboard's scene count:
    build_song.clip_plan() spreads a 20-scene storyboard across all 41 clips of
    a 3:16 track. Using scene_count here hid clips 20..40 from the approve grid
    and let clip generation start with two thirds of its references missing.

    That invariant SURVIVES the clip-length decision (docs/TRD-2 3.4) and this
    is how. `scene_seconds` is what the storyboard was generated with, so the
    divisor is per song now -- but the dividend is still the duration and the
    count is still ours, never the model's. One scene is one clip because grok
    is asked for exactly this many and validate() refuses any other number, not
    because anything here counts what came back.

    The arithmetic itself lives in build_song, called by four modules that each
    used to carry their own copy of it.
    """
    return build_song.n_clips_for(song["duration"], scene_seconds)


def get_song_or_404(sid):
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    if not song:
        raise HTTPException(404, "no such song")
    return song


def get_playlist_or_404(pid):
    row = db.one("SELECT * FROM playlists WHERE id=?", pid)
    if not row:
        raise HTTPException(404, "no such playlist")
    return row


def valid_tier_or_400(name):
    if not db.one("SELECT id FROM tiers WHERE name=?", name):
        raise HTTPException(400, f"no such tier: {name}")
    return name


def chosen_anchor(scope_kind, scope_value, tier, view="front", character_id=None):
    """The anchors row picked for this scope+tier+view, or None. Reference/clip
    generation always resolves anchors this way -- never by song.

    character_id=None means THE PROTAGONIST, whose anchors carry a NULL
    character_id -- which is every anchor that existed before the cast did. The
    NULL test is not optional: without it a supporting character's chosen anchor
    could be returned as the protagonist's and every reference frame for the
    song would render the wrong person.
    """
    # `IS ?` is sqlite's null-safe equality: it matches NULL when the parameter
    # is None and matches the id otherwise, in one query. (`= ?` never matches
    # NULL, and IS NOT DISTINCT FROM needs sqlite 3.39 -- cerberus has 3.37.)
    return db.one("""SELECT * FROM anchors WHERE scope_kind=? AND scope_value=? AND tier=?
                      AND view=? AND chosen=1 AND character_id IS ?""",
                  scope_kind, scope_value, tier, view, character_id)


def album_cast(album):
    """The album's named supporting characters, in name order.

    The PROTAGONIST is not in here: they are the album profile
    (playlists.identity/wardrobe/body), which every existing album already has.
    Extras and background characters are not in here either, and must not be --
    a row exists so a character can have an ANCHOR, and only a main actor needs
    one to stay consistent across fifty frames.
    """
    return db.q("SELECT * FROM characters WHERE scope_value=? ORDER BY name", album or "")


def cast_anchors(album, tier):
    """[(character_row, anchor_row)] for cast members with a chosen anchor at
    this tier. A character without one is skipped rather than failing the job:
    the storyboard can legitimately name someone you have not anchored yet, and
    refusing the whole song for it would be worse than rendering them from the
    scene text alone."""
    out = []
    for c in album_cast(album):
        anchor = chosen_anchor("album", album or "", tier, "front", c["id"])
        if anchor:
            out.append((c, anchor))
    return out


def get_character_or_404(cid):
    row = db.one("SELECT * FROM characters WHERE id=?", cid)
    if not row:
        raise HTTPException(404, "no such character")
    return row


def valid_genre_or_400(genre, subgenre, field):
    """Both optional; a subgenre must belong to its genre's list in genres.json."""
    genre = (genre or "").strip()
    subgenre = (subgenre or "").strip()
    if not genre:
        if subgenre:
            raise HTTPException(400, f"{field}: subgenre given without a genre")
        return "", ""
    if genre not in GENRE_DATA:
        raise HTTPException(400, f"{field}: unknown genre {genre!r}")
    if subgenre and subgenre not in GENRE_DATA[genre]:
        raise HTTPException(400, f"{field}: {subgenre!r} is not a subgenre of {genre!r}")
    return genre, subgenre


def _within_data(path):
    """True if path resolves inside db.DATA. Used to gate destructive file
    deletes -- never follow a path outside the data root, and never touch
    COMFY_INPUT/COMFY_OUTPUT (shared with ComfyUI)."""
    if not path:
        return False
    real = os.path.realpath(path)
    root = os.path.realpath(db.DATA)
    return real == root or real.startswith(root + os.sep)


def _song_file_paths(sid):
    """Every file path this song's rows reference, across all the tables
    that key off song_id."""
    paths = []
    song = db.one("SELECT mp3_path, style_path, anchor_path FROM songs WHERE id=?", sid)
    if song:
        paths += [song["mp3_path"], song["style_path"], song["anchor_path"]]
    for r in db.q("SELECT json_path, md_path FROM storyboards WHERE song_id=?", sid):
        paths += [r["json_path"], r["md_path"]]
    for table in ("assets", "refs", "clips", "renders"):
        for r in db.q(f"SELECT path FROM {table} WHERE song_id=?", sid):
            paths.append(r["path"])
    return paths


async def save_upload(upload: UploadFile, cap: int, dest_dir: str, kind: str, prefix=None):
    """kind: 'mp3' or 'image'. Validates ext + content-type + size, writes
    under dest_dir with a sanitized name, returns the saved path. `prefix` (e.g.
    "face_1699999999999") avoids two same-named uploads in one dir silently
    overwriting each other -- face.png and outfit.png would otherwise collide."""
    data = await upload.read(cap + 1)
    if len(data) > cap:
        raise HTTPException(413, f"{kind} file too large (max {cap // (1024 * 1024)}MB)")
    if not data:
        raise HTTPException(400, f"{kind} file is empty")
    name = safe_name(upload.filename)
    if prefix:
        name = safe_name(f"{prefix}_{name}")
    ext = os.path.splitext(name)[1].lower()
    ct = (upload.content_type or "").lower()
    if kind == "mp3":
        if ext != ".mp3":
            raise HTTPException(400, "expected a .mp3 file")
        if ct and not (ct.startswith("audio/") or ct == "application/octet-stream"):
            raise HTTPException(400, f"expected audio, got {ct}")
    else:
        if ext not in IMAGE_EXTS:
            raise HTTPException(400, f"unsupported image type {ext or '(none)'}")
        if ct and not ct.startswith("image/"):
            raise HTTPException(400, f"expected an image, got {ct}")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def upload_dir(slug):
    return os.path.join(db.DATA, "uploads", slug)


def clamp_audio_edit_params(trim_start, trim_end, gain_db, fade_in, fade_out):
    """Reject (400) anything hostile before it reaches mixer.edit_audio or the
    job queue -- a prior review found scene_seconds unvalidated let nan/inf
    reach the db. These are all plain floats off a form, so every one gets
    the same finite check, then range checks straight from the ffmpeg args
    they end up in (-ss/-to offsets, volume=NdB, afade durations)."""
    for name, v in (("trim_start", trim_start), ("gain_db", gain_db),
                     ("fade_in", fade_in), ("fade_out", fade_out)):
        if not math.isfinite(v):
            raise HTTPException(400, f"{name} must be a finite number")
    if trim_end is not None and not math.isfinite(trim_end):
        raise HTTPException(400, "trim_end must be a finite number")
    if trim_start < 0:
        raise HTTPException(400, "trim_start must be >= 0")
    if trim_end is not None and trim_end <= trim_start:
        raise HTTPException(400, "trim_end must be greater than trim_start")
    lo, hi = GAIN_DB_RANGE
    if not (lo <= gain_db <= hi):
        raise HTTPException(400, f"gain_db must be between {lo} and {hi}")
    if fade_in < 0:
        raise HTTPException(400, "fade_in must be >= 0")
    if fade_out < 0:
        raise HTTPException(400, "fade_out must be >= 0")
    return trim_start, trim_end, gain_db, fade_in, fade_out


def clamp_set_item_params(in_secs, out_secs, gain_db, transition, secs):
    """Same shape as clamp_audio_edit_params, for one set_items row. These
    feed mixer's -ss/-to input options and the xfade/acrossfade duration."""
    for name, v in (("gain_db", gain_db), ("secs", secs)):
        if not math.isfinite(v):
            raise HTTPException(400, f"{name} must be a finite number")
    if in_secs is not None and not math.isfinite(in_secs):
        raise HTTPException(400, "in_secs must be a finite number")
    if out_secs is not None and not math.isfinite(out_secs):
        raise HTTPException(400, "out_secs must be a finite number")
    if in_secs is not None and in_secs < 0:
        raise HTTPException(400, "in_secs must be >= 0")
    if out_secs is not None and in_secs is not None and out_secs <= in_secs:
        raise HTTPException(400, "out_secs must be greater than in_secs")
    lo, hi = GAIN_DB_RANGE
    if not (lo <= gain_db <= hi):
        raise HTTPException(400, f"gain_db must be between {lo} and {hi}")
    if transition not in SET_TRANSITIONS:
        raise HTTPException(400, f"transition must be one of {', '.join(SET_TRANSITIONS)}")
    if secs < 0:
        raise HTTPException(400, "secs must be >= 0")
    return in_secs, out_secs, gain_db, transition, secs


MAX_HOLD_SECS = 30.0


def _hold_of(row):
    """A set_items row's black-hold, tolerating a row that never selected the
    column (a playlist item has no hold, and neither did any row before the
    migration). 0 means "no hold", which is what every other transition wants."""
    try:
        return float(row["hold"] or 0.0)
    except (KeyError, IndexError, TypeError):
        return 0.0


def _brand_of(item_row, set_row):
    """The mark for THIS handover: the item's own override, else the set's
    default when the item is ticked for branding, else nothing.

    Resolved in one place because the render path and the editor's preview must
    answer it identically -- an editor that shows a mark the renderer will not
    draw is the same defect as one that promises a tempo ramp nothing applies.
    """
    try:
        own = (item_row["brand_path"] or "").strip()
    except (KeyError, IndexError, TypeError):
        own = ""
    if own:
        return own
    try:
        if not item_row["branded"]:
            return ""
    except (KeyError, IndexError, TypeError):
        return ""
    try:
        return (set_row["brand_path"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return ""


def clamp_hold(hold, transition):
    """The black-hold, validated against the transition it belongs to.

    Stored as 0 for every other transition kind rather than kept: a hold that
    survives switching away from `black` is a number the renderer ignores and
    the length prediction does not, and the two would disagree the moment the
    transition was switched back.
    """
    hold = float(hold or 0.0)
    if not math.isfinite(hold):
        raise HTTPException(400, "hold must be a finite number")
    if transition != mixer.BLACK:
        return 0.0
    if hold < 0:
        raise HTTPException(400, "hold must be >= 0")
    if hold > MAX_HOLD_SECS:
        raise HTTPException(400, f"hold is {hold}s; {MAX_HOLD_SECS:.0f}s is the most this "
                                  f"editor accepts -- a longer silence is an interstitial, "
                                  f"not a transition")
    return hold


# Nothing is unsupported any more -- duck and layer are both wired at the join
# (mixer._duck_join, mixer._layer_join). This stays as the hook a future
# validated-but-unwired effect goes on, because refusing rather than silently
# accepting-and-ignoring is this codebase's own rule: a choice that looks
# available but does nothing is worse than one that doesn't exist (see the
# anchor-view trap in CONTINUATION-*.md).
_UNSUPPORTED_EFFECT_KEYS = effects.UNSUPPORTED_KEYS


def _is_card_row(row):
    """T1-28: a card is a set_items row whose song_id is NULL."""
    try:
        return row["song_id"] is None
    except (KeyError, IndexError, TypeError):
        return False


def _card_mix_item(row):
    """mixer.set_duration / mix_audio / render_set shape for one card."""
    return {"kind": mixer.CARD, "card": row["card_path"] or "",
            "duration": float(row["card_secs"] or 0.0),
            "transition": row["transition"] or "cut",
            "secs": row["secs"] or 0.0, "hold": _hold_of(row),
            "in_secs": None, "out_secs": None,
            "beatmatch": False, "bpm": None, "beat_grid": [],
            "downbeat_offset": 0}


def clamp_set_item_effects(effects_json):
    """Validate and screen a set_item's effects_json before it is stored.
    Free text a user typed in -- screened exactly like the anchor prompt and
    tier wording, then checked structurally against the exact functions
    mixer.py will call at render time (effects.parse_effects for the audio
    keys, video_fx.parse_effects_json for the video-only subset), so a value
    that would blow up ffmpeg's filtergraph is refused at edit time instead.
    Returns the trimmed text, or None for "no effects" (blank input)."""
    text = (effects_json or "").strip()
    if not text:
        return None
    try:
        tiers.check_text(text, "set item effects")
        tiers.check_override(text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"invalid effects_json: {e}")
    if not isinstance(data, dict):
        raise HTTPException(400, "effects_json must be a JSON object")
    unsupported = [k for k in _UNSUPPORTED_EFFECT_KEYS if k in data]
    if unsupported:
        raise HTTPException(400, f"not supported in set rendering yet: {', '.join(unsupported)}")
    # gain_db has a field of its own on this same form, so accepting it here too
    # gives one value two inputs -- and an item with -3 in both rendered at -6 dB
    # with nothing saying which was meant. mixer._audio_chain resolves an already
    # saved item (the column wins, never summed); this refuses a NEW one, because
    # entry is the right place to reject an ambiguity and render time is the
    # worst. docs/TRD-1 5.0(b).
    if data.get("gain_db"):
        raise HTTPException(400, "put gain in the Gain (dB) field, not in effects_json -- "
                                 "they are one value, and the field is the one that wins")
    # parse_effects ignores keys it does not know, so a typo like "eq_kil" would
    # be stored and then silently do nothing at render. Accepted-and-ignored is
    # the one outcome this form must not have.
    known = set(effects.AUDIO_KEYS) | set(video_fx.VIDEO_KEYS)
    unknown = sorted(set(data) - known)
    if unknown:
        raise HTTPException(400, f"unknown effect keys: {', '.join(unknown)}. "
                                  f"Known: {', '.join(sorted(known))}")
    try:
        effects.parse_effects(data)
        video_only = {k: v for k, v in data.items() if k in video_fx.VIDEO_KEYS}
        if video_only:
            video_fx.parse_effects_json(video_only)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return text


def _mix_items_for_set(id, overrides=None, extra_item=None):
    """This set's items in mixer.set_duration's shape (audio key, key=id ->
    the SONG's mp3, since render_set/mix_audio predict length off the track
    audio either way -- see set_detail's own comment on why). `overrides` is
    {item_id: {field: value}}, applied over the stored row so a pending edit
    not yet written to the db is checked before it exists there. A song
    whose mp3 is missing from disk is skipped, same tolerance set_detail
    already has for a deleted/moved file. A card has no song; it is priced
    by card_secs.

    Also pulls beatmatch/beat_grid/downbeat_offset (via _beatmatch_fields, the
    same helper render_set_route uses) so mixer.set_duration's own
    _apply_beatmatch actually snaps here too -- without these, a beatmatch=1
    item validates its raw, un-snapped secs/out_secs and an edit that beat-
    snapping later makes impossible would slip past this guard."""
    rows = db.q("""SELECT si.id, si.song_id, si.transition, si.secs, si.in_secs, si.out_secs,
                          si.beatmatch, si.card_path, si.card_secs, si.hold,
                          s.mp3_path, s.bpm, s.beat_grid_json, s.downbeat_offset
                   FROM set_items si LEFT JOIN songs s ON s.id = si.song_id
                   WHERE si.set_id=? ORDER BY si.position""", id)
    overrides = overrides or {}
    items = []
    for r in rows:
        row = dict(r)
        row.update(overrides.get(row["id"], {}))
        if _is_card_row(row):
            items.append(_card_mix_item(row))
        elif row["mp3_path"] and os.path.isfile(row["mp3_path"]):
            items.append({"audio": row["mp3_path"], "transition": row["transition"],
                          "secs": row["secs"], "in_secs": row["in_secs"], "out_secs": row["out_secs"],
                          "hold": _hold_of(row),
                          **_beatmatch_fields(row, row)})
    if extra_item is not None:
        items.append(extra_item)
    return items


def _refuse_if_unrenderable(items):
    """The edit-time half of mixer.py's shared transition-fit guard: run the
    SAME check set_duration()/render_set()/mix_audio() run, before an edit
    that would make the sequence impossible to render is ever written --
    "an impossible transition is refused at edit time" (SETS_MIXING_PLAN.md).
    A single item has nothing to overlap, so nothing to check."""
    if len(items) < 2:
        return
    try:
        mixer.set_duration(items, key="audio")
    except ValueError as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------------------- job handlers --

@jobs.handler("transcribe")
def h_transcribe(args, progress):
    song = db.one("SELECT * FROM songs WHERE id=?", args["song_id"])
    if not song:
        return
    ok, msg = lyrics.available()
    if not ok:
        raise RuntimeError(msg)
    # ComfyUI and whisper share one 24 GB card and ComfyUI keeps its models
    # resident, so a transcription that follows a render OOMs. Ask it to let go
    # first; lyrics.transcribe falls back to CPU if that was not enough.
    pipeline.free_vram(progress)
    result = lyrics.transcribe(song["mp3_path"], progress)
    text = lyrics.to_sections(result)
    db.run("UPDATE songs SET lyrics=? WHERE id=?", text, song["id"])
    return {"chars": len(text)}


@jobs.handler("analyse")
def h_analyse(args, progress):
    """bpm/key/beat-grid/energy for one song -- see analyse.py. Same CPU-vs-GPU
    reasoning as transcribe: negligible beside a render (measured ~19s for an
    8-minute track), so it runs through the same serialized worker rather than
    a second lane."""
    song = db.one("SELECT * FROM songs WHERE id=?", args["song_id"])
    if not song or not song["mp3_path"]:
        return
    result = analyse.analyse(song["mp3_path"], progress)
    db.run("""UPDATE songs SET bpm=?, key=?, beat_grid_json=?, energy=?, downbeat_offset=?
              WHERE id=?""",
           result["bpm"], result["key"], json.dumps(result["beat_grid"]),
           result["energy"], result["downbeat_offset"], song["id"])
    # The waveform picture, written HERE rather than by a job of its own: this
    # handler already decodes the track, already runs on upload, and already
    # has a "do it for everything" button. Measured 1.3s against this job's
    # ~19s, so it is noise.
    #
    # NOT generated lazily when a page asks for it: a 20-song set would fire 20
    # concurrent ffmpeg processes on first load, on the box that is also
    # rendering. A song with no picture yet says so and points at this button.
    wave = write_song_waveform(song, progress)
    return {"bpm": result["bpm"], "key": result["key"], "waveform": bool(wave)}


def write_song_waveform(song, progress=None):
    """Render (or re-render) one song's waveform PNG and record it as an asset.

    An `assets` row, not a songs column: that bag already holds style images,
    reviews, anchor refs and renders, it is already served by /media, and it is
    already swept when a song is deleted -- so this needs no new table, no new
    route and no new cleanup path. Newest row wins, exactly as the other kinds
    behave.

    A failure here is REPORTED and swallowed: the waveform is decoration on a
    page, and losing a whole bpm/key analysis because a picture would not draw
    is the wrong trade. The caller learns from the returned None.
    """
    if not song or not song["mp3_path"] or not os.path.isfile(song["mp3_path"]):
        return None
    out = os.path.join(db.DATA, "waveforms", f"{song['id']}.png")
    try:
        mixer.waveform_png(song["mp3_path"], out, progress)
    except Exception as e:                      # ffmpeg, a codec, a full disk
        if progress:
            progress(f"no waveform picture: {e}")
        return None
    db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
           song["id"], "waveform", out,
           json.dumps({"w": mixer.WAVEFORM_SIZE[0], "h": mixer.WAVEFORM_SIZE[1]}), time.time())
    return out


def song_waveform(song_id):
    """The newest waveform PNG for a song, or None. Missing is normal: every
    song analysed before this existed has none until it is analysed again."""
    row = db.one("""SELECT path FROM assets WHERE song_id=? AND kind='waveform'
                    ORDER BY id DESC LIMIT 1""", song_id)
    return row["path"] if row and os.path.isfile(row["path"]) else None


@jobs.handler("anchor")
def h_anchor(args, progress):
    # anchors are scoped to an ALBUM/PLAYLIST and a TIER, never a song -- see
    # db.py's anchors table. Not tied to any song_id.
    view = args.get("view", "front")
    # the album's own look, edited in the UI, is what describes the character --
    # make_anchor.py no longer knows about any particular one
    album = args["scope_value"] if args["scope_kind"] == "album" else ""
    cid = args.get("character_id")
    prof = anchor_profile_fields(album, cid)
    if cid:
        char = db.one("SELECT * FROM characters WHERE id=?", cid)
        if char:
            progress(f"anchor for cast member: {char['name']}")
    # THE REASSEMBLY POINT. Everything the composer takes is put back together
    # here and travels as one profile dict: app.py -> gen_anchor -> a temp
    # profile json -> make_anchor.load_anchor -> prompt_for. Every field the
    # form can edit has to appear in this dict or the edit reaches nothing.
    #
    # `views` was missing, and that was a silent hole: profiles/street_cats.json
    # defines its own front and back sentences -- written for THIS character --
    # and none of them ever reached the renderer, which fell back to
    # make_anchor's generic DEFAULT_VIEWS on every sheet this studio has ever
    # produced. Found by the parallel session's review.
    anchor_profile = {"anchor": prof}
    if view in NUDE_VIEWS:
        progress(f"nude anchor for tier '{args['tier']}' -- permitted by its allow_nudity flag")
        if not anchor_profile["anchor"].get("anatomy"):
            # Permitting explicit content is not the same as asking for it.
            # Nothing filters anatomical language here; a nude sheet with no
            # anatomy clause comes back featureless because nothing requested
            # otherwise, and that is worth saying once per render rather than
            # leaving it to be rediscovered from the images.
            progress("no anatomy wording for this album -- a nude sheet will be "
                     "anatomically featureless unless one is set")
    render = args.get("render") or {}
    paths = pipeline.gen_anchor(args["images"], view, args.get("n", 4), progress,
                                 profile=anchor_profile,
                                 # this ALBUM's wording for the tier if it has its
                                 # own, else the tier's -- the same call the form
                                 # composed its panel and its preview from
                                 guard=tiers.compose_guardrail(args["tier"], album),
                                 prompt=args.get("prompt", ""),
                                 render=render)
    # Each candidate points back at the RUN that made it, so a sheet can always
    # answer what produced it -- prompt, negative, references and sampler
    # together, not just the numbers. A CFG sweep makes that load-bearing:
    # eleven runs land in one grid and differ only by guidance.
    #
    # render_json is still written when there is no run, which is only a job
    # queued before runs existed. New rows leave it NULL and read the run.
    run_id = args.get("run_id")
    settings = None if run_id else json.dumps(resolved_settings(render))
    now = time.time()
    asked = args.get("prompt") or ""
    bases = args.get("images") or []
    landed = list(paths)
    if args.get("refine", True):
        for p in list(paths):
            try:
                dest = refine_generated_still(p, progress, {
                    "slug": "anchor", "tier": args["tier"],
                })
                landed.append(dest)
            except Exception as e:
                progress(f"refine skipped: {e}")
    for p in landed:
        qc = score_generated_still(p, bases, asked, progress)
        db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen, created,
                                        character_id, render_json, run_id, qc_json)
                  VALUES (?,?,?,?,?,0,?,?,?,?,?)""",
               args["scope_kind"], args["scope_value"], args["tier"], view, p, now, cid,
               settings, run_id, qc)
    # Refs refuse a tier with no chosen sheet. Every live row sat at chosen=0
    # because generate never picked. If this group still has none, the first
    # new candidate is it. Pick still overrides. Mutation: delete this block
    # → a generate leaves chosen=0 and start_refs 400s.
    if paths:
        picked = db.one("""SELECT id FROM anchors WHERE scope_kind=? AND scope_value=?
                            AND tier=? AND view=? AND character_id IS ? AND chosen=1""",
                        args["scope_kind"], args["scope_value"], args["tier"], view, cid)
        if not picked:
            first = db.one("""SELECT id FROM anchors WHERE path=? AND scope_kind=?
                               AND scope_value=? AND tier=? AND view=? AND character_id IS ?
                               ORDER BY id""",
                           paths[0], args["scope_kind"], args["scope_value"],
                           args["tier"], view, cid)
            if first:
                db.run("UPDATE anchors SET chosen=1 WHERE id=?", first["id"])
    return {"n": len(paths), "run_id": run_id}


@jobs.handler("arc")
def h_arc(args, progress):
    """The album's story, in ONE request over every track.

    One request, not one per song: what track seven does depends on what track
    six did, and a per-song call would be guessing at exactly the thing the
    document exists to decide -- the same reason mixadvice shows the model the
    whole running order.
    """
    pl = db.one("SELECT * FROM playlists WHERE id=?", args["playlist_id"])
    if not pl:
        raise RuntimeError("that album no longer exists")
    songs = [dict(r) for r in db.q(
        """SELECT s.id, s.title, s.lyrics FROM playlist_items pi
           JOIN songs s ON s.id = pi.song_id
           WHERE pi.playlist_id=? ORDER BY pi.position""", pl["id"])]
    if not songs:
        raise RuntimeError("this album has no songs yet -- add some before writing its arc")
    data, used = arc.generate(pl["name"], songs, direction=args.get("direction", ""),
                              backend=args.get("backend"), model=args.get("model"),
                              progress=progress, transitions=mixer.TRANSITIONS)
    outdir = os.path.join(db.DATA, "arcs", safe_name(pl["name"]))
    titles = {s["id"]: s["title"] for s in songs}
    json_path, md_path = arc.write(data, outdir, safe_name(pl["name"]), titles)
    db.run("""INSERT INTO arcs (playlist_id, json_path, md_path, model, prompt, created)
              VALUES (?,?,?,?,?,?)
              ON CONFLICT(playlist_id) DO UPDATE SET json_path=excluded.json_path,
              md_path=excluded.md_path, model=excluded.model, prompt=excluded.prompt,
              created=excluded.created""",
           pl["id"], json_path, md_path, used, args.get("direction", ""), time.time())
    return {"songs": len(data["songs"]), "acts": len(data["acts"]), "model": used}


def album_arc(album):
    """The stored arc for an album NAME, as a dict, or {}.

    By name because that is how everything else in this studio reaches an album:
    songs carry the name, anchors are scoped by it, and the arc has to be
    findable from a song row that knows nothing about playlist ids.
    """
    if not album:
        return {}
    row = db.one("""SELECT a.json_path FROM arcs a JOIN playlists p ON p.id = a.playlist_id
                    WHERE p.name=? AND p.kind='playlist'""", album)
    if not row or not row["json_path"] or not os.path.isfile(row["json_path"]):
        return {}
    try:
        with open(row["json_path"]) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


@jobs.handler("storyboard")
def h_storyboard(args, progress):
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    # the ALBUM's wording for this tier when it has its own. Composing without
    # the album here would storyboard a song against wording its own anchors
    # were never rendered from.
    guardrail = tiers.compose_guardrail(tier, song["album"] or "")
    # The style note used to come from a per-song style-guide upload. That UI
    # moved to the album, so it comes from the ALBUM now: its theme, its world
    # and its render style are exactly what "the look of this release" means.
    # Without this the note was silently EMPTY for every storyboard generated
    # after the move -- the upload form was gone but nothing replaced it.
    # A legacy per-song asset still wins, so songs set up before the move keep
    # the note they were given.
    style_row = db.one("SELECT * FROM assets WHERE song_id=? AND kind='style' ORDER BY id DESC LIMIT 1", sid)
    legacy_note = db.jset(style_row).get("note", "") if style_row else ""
    prof = album_profile(song["album"] or "")
    style_note = legacy_note or " ".join(
        p for p in (prof["style_text"], prof["world"], prof["render_tail"]) if p)
    # `explicit` is a fact about the LYRICS, not a rendering instruction -- the
    # tier picked for this storyboard already carries the tone/wardrobe choice.
    # Passing both to the model is exactly the conflation this rework removes.
    song_fields = dict(song)
    song_fields.pop("explicit", None)
    # style_text is the prompt the AUDIO was generated from -- drums, BPM,
    # vocal delivery. The storyboard is about pictures. Storyboards carried
    # exactly this text as `suno_style_reference` until it was stripped off
    # disk as dead weight; passing it here would put it straight back.
    # dict(song) hands grok every column, so a new column leaks by DEFAULT:
    # anything added to the songs table has to be considered here.
    song_fields.pop("style_text", None)
    # The direction box is PREFILLED from the tier's tone wording and then edited,
    # so when one is supplied it already carries that channel -- sending the tier
    # row's text as well would put it in front of the model twice. PINNED stays
    # unconditional either way, and the tier's real guardrail is re-applied at
    # RENDER time by guardrail.build_prompt() whatever the storyboard ends up
    # saying, which is what makes this safe to hand over.
    direction = (args.get("direction") or "").strip()
    # DO NOT replace the guardrail with PINNED when a direction is supplied.
    #
    # It used to, and the comment above defended it: the direction box is
    # prefilled from the tier's TONE wording, so sending the tier row as well
    # would show the model the same words twice. True, and it cost the tier its
    # PERMISSION clause -- which is a different sentence from its tone.
    #
    # Measured on `rear-entrance_xxx.json`: all 25 scenes came back "fully
    # clothed, tasteful and non-graphic, no explicit gesture" -- the MAINSTREAM
    # wording -- while tiers.compose_guardrail("xxx") says "Explicit adult
    # content is permitted... full nudity, sexual acts between consenting adults
    # and graphic sexual imagery are in scope", and even `r` says "nudity,
    # including graphic nudity, is in scope". A PG-13 body filed as xxx.
    #
    # The mechanism: grok._system_prompt is handed the tier's own wording with
    # PINNED stripped out, so a guardrail of exactly PINNED leaves it EMPTY and
    # the model is told nothing about what this tier permits. And because the
    # box is prefilled, the normal path always supplies a direction -- so the
    # tier never reached the model on any storyboard anyone actually generated.
    #
    # Duplicated tone wording is cosmetic. A tier that cannot say what it
    # permits is the file whose job is to be true saying something false.
    # The cast the model is allowed to name. Only characters with an anchor at
    # THIS tier: naming someone with no anchor produces a scene the renderer
    # cannot keep consistent, which is the problem the cast exists to solve.
    cast = [(c["name"], " ".join(p for p in (c["role"], c["identity"], c["wardrobe"]) if p))
            for c, _a in cast_anchors(song["album"] or "", tier)]
    if cast:
        progress(f"cast offered to the storyboard: {', '.join(n for n, _ in cast)}")
    # Where this song sits in the album's story, if the album has one. Passed
    # separately from style_note on purpose: that is the album's LOOK and this is
    # its STORY, and folding one into the other is how the two stop being
    # editable apart.
    arc_ctx = arc.for_song(album_arc(song["album"] or ""), sid)
    if arc_ctx:
        progress(f"album arc: this is track {arc_ctx.get('beat', '')[:60]!r}")
    sb = grok.generate_storyboard(song["lyrics"] or "", tier, guardrail, style_note,
                                   song_fields, args.get("model"), args.get("scene_seconds"), progress,
                                   direction=direction, cast=cast, arc_ctx=arc_ctx)
    outdir = os.path.join(db.DATA, "storyboards", song["slug"])
    os.makedirs(outdir, exist_ok=True)
    json_path, md_path = grok.write_storyboard(sb, outdir, song["slug"], tier)
    scene_count = len(sb.get("scenes", [])) if isinstance(sb, dict) else None
    # the direction is stored with the result, not just used and forgotten: a
    # storyboard you cannot see the prompt for is one you cannot tune.
    # T2-13b: upsert the storyboard row only. Approved (clip_idx, seed) stays;
    # a re-plan must not delete, unapprove, or remap refs.
    db.run("""INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count,
                                       created, prompt, scene_seconds)
              VALUES (?,?,?,?,?,?,?,?)
              ON CONFLICT(song_id, tier) DO UPDATE SET json_path=excluded.json_path,
              md_path=excluded.md_path, scene_count=excluded.scene_count,
              created=excluded.created, prompt=excluded.prompt,
              scene_seconds=excluded.scene_seconds""",
           sid, tier, json_path, md_path, scene_count, time.time(), args.get("direction", ""),
           args.get("scene_seconds"))
    return {"json": json_path, "md": md_path}


@jobs.handler("refs")
def h_refs(args, progress):
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    sb = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", sid, tier)
    # resolve the chosen anchor candidate (an output image) into a name usable
    # as ComfyUI input -- start_refs already checked one is chosen for this tier
    anchor_name = pipeline.install_input(args["anchor_path"])
    # the album's body-consistency wording goes into EVERY frame's prompt, not
    # just the anchor's -- see build_refs.workflow
    album = song["album"] or ""
    body = album_profile(album)["body"]
    # Supporting characters with a chosen anchor at this tier. A scene attaches
    # only the ones it NAMES; extras and background characters are deliberately
    # never named by the storyboard and so never get an anchor slot.
    cast = {c["name"]: {"path": a["path"],
                        "desc": " ".join(p for p in (c["identity"], c["wardrobe"], c["body"]) if p)}
            for c, a in cast_anchors(album, tier)}
    if cast:
        progress(f"cast for this tier: {', '.join(sorted(cast))}")
    results = pipeline.gen_refs(song["slug"], tier, sb["json_path"], anchor_name,
                                 song["mp3_path"], progress, limit=args.get("limit"),
                                 guard=tiers.compose_guardrail(tier, album), body=body,
                                 cast=cast)
    now = time.time()
    bases = [args.get("anchor_path")] if args.get("anchor_path") else []
    landed = list(results)
    if args.get("refine", True):
        for r in list(results):
            try:
                dest = refine_generated_still(r["path"], progress, {
                    "slug": song["slug"], "tier": tier,
                    "clip_idx": r["clip_idx"], "seed": r.get("seed") or 0,
                })
                landed.append({"clip_idx": r["clip_idx"], "path": dest,
                               "seed": (r.get("seed") or 0) + 100000})
            except Exception as e:
                progress(f"refine skipped: {e}")
    n_gen = len(results)
    for i, r in enumerate(landed):
        qc = score_generated_still(r["path"], bases, f"{tier} ref", progress)
        origin = "refine" if i >= n_gen else "gen"
        db.run("""INSERT OR IGNORE INTO refs (song_id, tier, clip_idx, path, seed, approved,
                                               created, origin, qc_json)
                  VALUES (?,?,?,?,?,0,?,?,?)""",
               sid, tier, r["clip_idx"], r["path"], r.get("seed"), now, origin, qc)
    return {"count": len(landed)}


@jobs.handler("reroll")
def h_reroll(args, progress):
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    sb = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", sid, tier)
    anchor = chosen_anchor("album", song["album"] or "", tier)
    if not anchor:
        raise RuntimeError(f"no chosen anchor for tier '{tier}' on this album")
    anchor_name = pipeline.install_input(anchor["path"])
    # the SAME wording every other reference prompt gets. A re-roll that drops
    # the album's body text comes back with the drift it was meant to fix.
    album = song["album"] or ""
    cast = {c["name"]: {"path": a["path"],
                        "desc": " ".join(p for p in (c["identity"], c["wardrobe"], c["body"]) if p)}
            for c, a in cast_anchors(album, tier)}
    results = pipeline.reroll(song["slug"], tier, sb["json_path"], anchor_name,
                               song["mp3_path"], args["clip_indices"], progress,
                               guard=tiers.compose_guardrail(tier, album),
                               body=album_profile(album)["body"],
                               note=args.get("note", ""), cast=cast)
    now = time.time()
    bases = [anchor["path"]] if anchor else []
    landed = list(results)
    if args.get("refine", True):
        for r in list(results):
            try:
                dest = refine_generated_still(r["path"], progress, {
                    "slug": song["slug"], "tier": tier,
                    "clip_idx": r["clip_idx"], "seed": r.get("seed") or 0,
                })
                landed.append({"clip_idx": r["clip_idx"], "path": dest,
                               "seed": (r.get("seed") or 0) + 100000})
            except Exception as e:
                progress(f"refine skipped: {e}")
    for i, r in enumerate(landed):
        qc = score_generated_still(r["path"], bases, args.get("note") or "reroll", progress)
        origin = "refine" if i >= len(results) else "reroll"
        db.run("""INSERT OR IGNORE INTO refs (song_id, tier, clip_idx, path, seed, approved,
                                               created, origin, qc_json)
                  VALUES (?,?,?,?,?,0,?,?,?)""",
               sid, tier, r["clip_idx"], r["path"], r.get("seed"), now, origin, qc)
    return {"count": len(landed)}


@jobs.handler("artwork")
def h_artwork(args, progress):
    """Render an album cover from the album look."""
    p = db.one("SELECT * FROM playlists WHERE id=?", args["playlist_id"])
    if not p:
        return
    prof = album_profile(p["name"])
    # the cover is a composed piece of artwork, so the theme and world lead and
    # the character follows -- the reverse of a character sheet, where the
    # character is the whole subject
    # What is said depends on which references are attached. Naming an image
    # that is not there is how a model gets told to invent one.
    parts = [f"Album cover artwork for the release \"{p['name']}\".", prof["style_text"],
             prof["world"]]
    if args.get("source_path"):
        parts.append("Start from the existing cover supplied as a reference image and modify "
                     "it, keeping its overall composition and palette.")
    if args.get("anchor_path"):
        parts.append(f"It depicts the album's protagonist: {prof['identity']} "
                     f"{prof['wardrobe']} {prof['body']}")
    else:
        parts.append(f"{prof['identity']} {prof['wardrobe']}")
    if args.get("instruction"):
        parts.append(args["instruction"])
    parts += ["Striking single composition, square format, no text, no lettering, no logo, "
              "no typography, no border.", prof["render_tail"]]
    prompt = " ".join(x for x in parts if x and x.strip())
    # An album cover carries no tier of its own. It uses the tier of whichever
    # anchor it is rendered from, so a cover generated from an explicit anchor
    # is permitted what that tier permits -- and PINNED applies either way.
    guard = tiers.compose_guardrail(args["tier"], p["name"]) if args.get("tier") else ""
    paths = pipeline.gen_artwork(safe_name(p["name"]), prompt, progress,
                                  anchor_path=args.get("anchor_path"),
                                  source_path=args.get("source_path"), guard=guard)
    if not paths:
        raise RuntimeError("the artwork render produced no image")
    cover = paths[0]
    if args.get("refine", True):
        try:
            cover = refine_generated_still(paths[0], progress, {"slug": safe_name(p["name"])})
            paths = [cover] + paths
        except Exception as e:
            progress(f"refine skipped: {e}")
    bases = [args.get("anchor_path") or args.get("source_path")]
    qc = score_generated_still(cover, [b for b in bases if b], prompt, progress)
    db.run("INSERT INTO assets (song_id, kind, path, meta_json, created, qc_json) VALUES (?,?,?,?,?,?)",
           None, "artwork", cover,
           json.dumps({"playlist_id": args["playlist_id"], "model": args.get("model"),
                       "prompt": prompt}), time.time(), qc)
    progress(f"{len(paths)} cover candidate(s); using the first")
    db.run("UPDATE playlists SET image_path=? WHERE id=?", paths[0], args["playlist_id"])
    return {"path": paths[0]}


@jobs.handler("fix_ref")
def h_fix_ref(args, progress):
    """Repair one reference frame. The result is another CANDIDATE for that
    clip, never a replacement: the original stays until you approve the fix."""
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    body = album_profile(song["album"] or "")["body"]
    results = pipeline.fix_ref(
        song["slug"], tier, args["clip_idx"], args["mode"], args["image_path"],
        args["seed"], progress, face_path=args.get("face_path"),
        mask_path=args.get("mask_path"), pad=args.get("pad", (0, 0, 0, 0)),
        instruction=args.get("instruction", ""),
        guard=tiers.compose_guardrail(tier, song["album"] or ""), body=body)
    now = time.time()
    bases = [args.get("face_path") or args.get("image_path")]
    landed = list(results)
    if args.get("refine", False):
        for r in list(results):
            try:
                dest = refine_generated_still(r["path"], progress, {
                    "slug": song["slug"], "tier": tier,
                    "clip_idx": r["clip_idx"],
                })
                landed.append({"clip_idx": r["clip_idx"], "path": dest,
                               "seed": r.get("seed")})
            except Exception as e:
                progress(f"refine skipped: {e}")
    for r in landed:
        qc = score_generated_still(r["path"], bases, args.get("instruction") or args["mode"],
                                   progress)
        db.run("""INSERT OR IGNORE INTO refs (song_id, tier, clip_idx, path, seed, approved,
                                               created, origin, qc_json)
                  VALUES (?,?,?,?,?,0,?,?,?)""",
               sid, tier, r["clip_idx"], r["path"], r.get("seed"), now, args["mode"], qc)
    return {"count": len(landed), "mode": args["mode"]}


@jobs.handler("clips")
def h_clips(args, progress):
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    sb = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", sid, tier)
    approved = db.q("SELECT clip_idx, path FROM refs WHERE song_id=? AND tier=? AND approved=1", sid, tier)
    ref_paths = [{"clip_idx": r["clip_idx"], "path": r["path"]} for r in approved]
    video_model = args.get("video_model") or models.default_cli("video")
    if video_model == "i2v":
        progress("i2v: prompt-driven only -- this render has no beat sync or mouth movement")
    if args.get("refine"):
        progress("refiner pass ON: roughly double the render time, and unproven on s2v output")
    results = pipeline.gen_clips(song["slug"], tier, sb["json_path"], song["mp3_path"], ref_paths,
                                  progress, video_model=video_model,
                                  ref_motion=args.get("ref_motion"),
                                  control_video=args.get("control_video"),
                                  refine=bool(args.get("refine")))
    for r in results:
        db.run("""INSERT INTO clips (song_id, tier, clip_idx, path, status) VALUES (?,?,?,?,'done')
                  ON CONFLICT(song_id, tier, clip_idx) DO UPDATE SET path=excluded.path, status='done'""",
               sid, tier, r["clip_idx"], r["path"])
    return {"count": len(results)}


@jobs.handler("classify")
def h_classify(args, progress):
    """Vision review of the approved references for one tier.

    The approved refs are scattered across the refs/ and reroll/ output dirs, so
    they are copied into one scratch dir under the clip_NNN name
    make_contact_sheet.py globs for -- the sheet must show the frames actually
    approved, not everything ever rendered for this song.
    """
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    rows = db.q("""SELECT clip_idx, path FROM refs WHERE song_id=? AND tier=? AND approved=1
                   ORDER BY clip_idx""", sid, tier)
    if not rows:
        raise RuntimeError(f"no approved references for tier '{tier}' to review")
    outdir = os.path.join(db.DATA, "review", song["slug"])
    os.makedirs(outdir, exist_ok=True)
    sheet = os.path.join(outdir, f"{song['slug']}_{tier}_sheet.jpg")
    with tempfile.TemporaryDirectory() as staged:
        for r in rows:
            if os.path.isfile(r["path"]):
                shutil.copy(r["path"], os.path.join(staged, f"clip_{r['clip_idx']:03d}.png"))
        progress(f"contact sheet: {len(os.listdir(staged))} approved frames")
        pipeline.contact_sheet(staged, sheet)
    verdict = vision.classify_sheet(sheet, note=f"{song['title']} ({tier} tier)",
                                    progress=progress)
    verdict["sheet"] = sheet
    db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
           sid, "review", sheet, json.dumps({"tier": tier, **verdict}), time.time())
    flagged = verdict["flagged"]
    progress(f"reviewed {len(rows)} frames: "
             + (", ".join(f"clip {f['clip']} {f['issue']}" for f in flagged) if flagged
                else "nothing flagged"))
    return {"flagged": len(flagged), "clips": [f["clip"] for f in flagged]}


@jobs.handler("edit_audio")
def h_edit_audio(args, progress):
    sid = args["song_id"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    if not song:
        return
    # always a fresh file -- never the same path as song["mp3_path"], so the
    # original upload (and whatever edit is currently in use) is untouched.
    outdir = os.path.join(db.DATA, "audio", song["slug"])
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"edit_{int(time.time() * 1000)}.mp3")
    mixer.edit_audio(song["mp3_path"], out, args["trim_start"], args["trim_end"],
                      args["gain_db"], args["fade_in"], args["fade_out"], progress)
    meta = {k: args[k] for k in ("trim_start", "trim_end", "gain_db", "fade_in", "fade_out")}
    # what produced these numbers, stored with them: an edit you cannot explain
    # six months later is an edit you cannot reproduce
    meta.update({k: args.get(k, "") for k in ("prompt", "note", "model")})
    db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
           sid, "audio_edit", out, json.dumps(meta), time.time())
    return {"path": out}


@jobs.handler("audio")
def h_audio(args, progress):
    """Generate music with ACE-Step, and KEEP it.

    pipeline.gen_audio leaves its takes in ComfyUI's output directory with
    nothing recording that they exist -- no row, no song, no way to find them
    from the studio. ComfyUI's output is also where every anchor candidate and
    clip lands, so a generated track there is a file nobody will ever identify
    again. Each take is copied into the studio's own data dir and given an
    assets row plus a takes row (T8-1): tags/lyrics/seed/duration/params
    are stored on the take so a later song edit cannot rewrite the ask.
    params include voice_id (T8-11): which voice produced the take, or None.

    Never writes over song["mp3_path"]. A take becomes the song's audio only
    when someone presses Use, which is the same route an edit goes through.
    """
    sid = args.get("song_id")
    song = db.one("SELECT * FROM songs WHERE id=?", sid) if sid else None
    slug = song["slug"] if song else "loose"
    took = pipeline.gen_audio(safe_name(slug), args["tags"], args.get("lyrics", ""),
                              seconds=args["seconds"], n=args["n"], progress=progress,
                              seed=args.get("seed"), source_path=args.get("source_path"),
                              denoise=args.get("denoise", 1.0))
    if not took:
        raise RuntimeError("the audio render produced no track")
    # safe_name here as well as on the render prefix above. Nothing can reach
    # this today -- slugify() collapses a slug to [a-z0-9-] and no route writes
    # songs.slug directly -- but this function was calling safe_name(slug) for
    # the prefix on one line and joining the raw slug into a WRITE PATH four
    # lines later, which is an invariant held in another function's regex.
    outdir = os.path.join(db.DATA, "audio", safe_name(slug))
    os.makedirs(outdir, exist_ok=True)
    stamp = int(time.time() * 1000)
    span = args.get("bridge")
    kept = []
    for i, src in enumerate(took):
        out = os.path.join(outdir, f"gen_{stamp}_{i}.mp3")
        if span:
            # THE cut-from-the-middle. ACE-Step supplies the bridge and ffmpeg
            # does the cutting, because no backend has a region node -- see the
            # ACE-Step entry in models.py, which used to claim the opposite.
            mixer.splice_bridge(song["mp3_path"], src, out, span["start"], span["end"],
                                progress=progress)
        else:
            shutil.copy2(src, out)
        # WHICH PATH RAN, stored beside the file rather than inferred later.
        # models.py's ACE-Step entry is explicit that whatever comes back is NEW
        # audio and never a shortened original, so a take that was seeded from
        # an existing track has to say so or it will be mistaken for an edit of
        # it. denoise below 1.0 re-synthesises the WHOLE clip -- there is no
        # region node on any backend -- so "resynthesised" means all of it.
        origin = ("bridged" if span else
                  "resynthesised" if args.get("source_path") else "generated")
        # T8-11: which voice produced the take is part of the ask. Missing
        # and blank are recorded as None so a take generated without a
        # voice is not the same row as one that never considered the field.
        voice_id = args.get("voice_id")
        if voice_id == "" or voice_id is None:
            voice_id = None
        else:
            voice_id = int(voice_id)
        meta = {
            "mode": origin,
            "tags": args["tags"], "lyrics": args.get("lyrics", ""),
            "seconds": args["seconds"], "seed": args.get("seed"),
            "denoise": args.get("denoise", 1.0),
            "source_path": args.get("source_path") or "",
            "bridge_start": (span or {}).get("start"),
            "bridge_end": (span or {}).get("end"),
            "model": models.default_for("audio"),
            "voice_id": voice_id}
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               sid, "audio_gen", out, json.dumps(meta), time.time())
        # T8-1: the ask is copied onto the take. insert_take never writes
        # songs.mp3_path -- picking is a separate act (T8-2).
        if sid:
            tid = db.insert_take(
                sid, out, origin,
                tags=args["tags"], lyrics=args.get("lyrics", ""),
                seed=args.get("seed"), duration=args["seconds"],
                params={k: meta[k] for k in (
                    "denoise", "source_path", "bridge_start", "bridge_end",
                    "model", "voice_id")})
            if voice_id is not None:
                db.assign_take_voice(tid, voice_id, start_secs=0,
                                     end_secs=args["seconds"])
        kept.append(out)
    progress(f"{len(kept)} take(s) kept in {outdir}")
    return {"path": kept[0], "takes": len(kept)}


@jobs.handler("render_song")
def h_render_song(args, progress):
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    clip_rows = db.q("SELECT * FROM clips WHERE song_id=? AND tier=? ORDER BY clip_idx", sid, tier)
    clip_paths = [r["path"] for r in clip_rows]
    outdir = os.path.join(db.DATA, "renders", song["slug"])
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"{song['slug']}_{tier}.mp4")
    mixer.assemble_song(clip_paths, song["mp3_path"], out, progress, args.get("fade", 0.0))
    db.run("INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)", sid, tier, out, time.time())
    return {"path": out}


@jobs.handler("render_set")
def h_render_set(args, progress):
    """Render a set. Two callers feed this one handler: the quick playlist
    render (playlist_id only) and the set editor (set_id, with or without a
    playlist_id behind it).

    A set-editor render is versioned -- the output filename carries a
    timestamp, so re-rendering lands a new asset beside the old one rather
    than overwriting it, the same shape as anchors keeping every candidate.
    The playlist quick-render keeps its old, unversioned filename: that path
    is exercised by assets rows that predate the sets table and must not move.
    """
    set_id = args.get("set_id")
    set_row = db.one("SELECT * FROM sets WHERE id=?", set_id) if set_id else None
    playlist = db.one("SELECT * FROM playlists WHERE id=?", args["playlist_id"]) \
        if args.get("playlist_id") else None
    outdir = os.path.join(db.DATA, "sets")
    os.makedirs(outdir, exist_ok=True)
    base = safe_name((set_row["name"] if set_row else None) or
                      (playlist["name"] if playlist else None) or "set")
    tier = args.get("tier")
    suffix = f"_{tier}" if tier else ""
    ext = "mp3" if args.get("mode") == "audio" else "mp4"
    fname = f"{base}{suffix}_{int(time.time() * 1000)}.{ext}" if set_row else f"{base}{suffix}.{ext}"
    out = os.path.join(outdir, fname)
    # mode defaults to video so a job enqueued by an older build still means
    # what it meant when it was queued
    if args.get("mode") == "audio":
        mixer.mix_audio(args["items"], out, progress)
    else:
        mixer.render_set(args["items"], out, progress)
    meta = {"playlist_id": args.get("playlist_id"), "mode": args.get("mode", "video"), "tier": tier}
    if set_id:
        meta["set_id"] = set_id
    # T1-19: the named chain that ran, not a default stamped on every render.
    # applied_master_chain is None when the master is off, so easy-off with
    # no curve stays empty — recording a name over a no-op fails the check.
    chain = mixer.applied_master_chain(args.get("items") or [])
    if chain:
        meta["master_chain"] = chain
    db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
           None, "set", out, json.dumps(meta), time.time())
    if set_id:
        db.run("UPDATE sets SET updated=? WHERE id=?", time.time(), set_id)
    return {"path": out}


# ------------------------------------------------------------------ media --

@app.get("/media/{path:path}")
def media(path: str):
    if "\x00" in path:
        raise HTTPException(400, "invalid path")
    real = os.path.realpath("/" + path)
    if not any(real == root or real.startswith(root + os.sep) for root in MEDIA_ROOTS):
        raise HTTPException(403, "path not allowed")
    if not os.path.isfile(real):
        raise HTTPException(404)
    return FileResponse(real)


# ------------------------------------------------------------------ songs --

def sets_by_song():
    """{song_id: [{id, label}]} -- the rendered sets each song appears in.

    A rendered asset's membership comes from ONE of two places, depending on
    which built it: a set-editor render (meta.set_id) reads set_items
    directly, since an editable set need not have a playlist at all. A
    playlist quick-render (no set_id, meta.playlist_id only) still reads
    playlist_items -- that is every asset row that predates the sets table,
    and it must keep resolving exactly as it always did.
    """
    pl_members = {}
    for it in db.q("SELECT playlist_id, song_id FROM playlist_items"):
        pl_members.setdefault(it["playlist_id"], []).append(it["song_id"])
    set_members = {}
    for it in db.q("SELECT set_id, song_id FROM set_items"):
        set_members.setdefault(it["set_id"], []).append(it["song_id"])
    pl_names = {p["id"]: p["name"] for p in db.q("SELECT id, name FROM playlists")}
    set_names = {s["id"]: s["name"] for s in db.q("SELECT id, name FROM sets")}
    out = {}
    for a in db.q("SELECT * FROM assets WHERE kind='set' ORDER BY id DESC"):
        meta = db.jset(a)
        sid = meta.get("set_id")
        if sid is not None:
            label = set_names.get(sid, "(deleted set)")
            song_ids = set_members.get(sid, [])
        else:
            pid = meta.get("playlist_id")
            label = pl_names.get(pid, "(deleted playlist)")
            song_ids = pl_members.get(pid, [])
        if meta.get("tier"):
            label += f" {meta['tier'].upper()}"
        if meta.get("mode") == "audio":
            label += " (audio)"
        for song_id in song_ids:
            out.setdefault(song_id, []).append({"id": a["id"], "label": label})
    return out


def wants_json(request):
    """True when the caller asked for JSON rather than a redirect.

    The Library's buttons all go through app.js's api() helper, which sets this
    header; the same routes still answer a plain form post with a redirect, so
    the page keeps working with JavaScript off. One convention, both paths --
    rather than a parallel /api/* tree that would double every route here.
    """
    return "application/json" in (request.headers.get("accept") or "")


def song_entry(s, in_sets=None):
    """One Library row's worth of context. Extracted so the row can be rendered
    on its own after an async upload -- the alternative was building the markup
    a second time in JavaScript, which is how the two drift apart."""
    in_sets = sets_by_song() if in_sets is None else in_sets
    board_tiers = {r["tier"] for r in db.q("SELECT DISTINCT tier FROM storyboards WHERE song_id=?", s["id"])}
    rendered_tiers = {r["tier"] for r in db.q("SELECT DISTINCT tier FROM renders WHERE song_id=?", s["id"])}
    tier_status = [{"tier": t, "rendered": t in rendered_tiers} for t in sorted(board_tiers)]
    # newest render per tier: re-assembling a song adds a row, and the
    # column is "what can I watch", not "everything ever produced"
    latest = {}
    for r in db.q("SELECT * FROM renders WHERE song_id=? ORDER BY id DESC", s["id"]):
        latest.setdefault(r["tier"], r)
    return {"song": s, "tiers": tier_status,
            "videos": [latest[t] for t in sorted(latest)],
            "sets": in_sets.get(s["id"], [])}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    songs = db.q("SELECT * FROM songs ORDER BY created DESC")
    in_sets = sets_by_song()
    entries = [song_entry(s, in_sets) for s in songs]
    return templates.TemplateResponse(request, "index.html", {"songs": entries, "genre_data": GENRE_DATA})


@app.get("/songs/{id}/row", response_class=HTMLResponse)
def song_row(request: Request, id: int):
    """The Library row for one song, rendered by the SAME partial the table uses.
    Asked for after an async upload so a new song appears without a reload."""
    return templates.TemplateResponse(request, "_song_row.html",
                                       {"e": song_entry(get_song_or_404(id))})


@app.post("/songs")
async def create_song(request: Request, title: str = Form(...), album: str = Form(""),
                       genre: str = Form(""), subgenre: str = Form(""), genre2: str = Form(""),
                       subgenre2: str = Form(""),
                       explicit: bool = Form(False), mp3: UploadFile = File(...)):
    genre, subgenre = valid_genre_or_400(genre, subgenre, "genre")
    genre2, subgenre2 = valid_genre_or_400(genre2, subgenre2, "genre2")
    slug = unique_slug(title)
    dest = await save_upload(mp3, MAX_MP3, upload_dir(slug), "mp3")
    duration = None
    try:
        duration = lyrics.estimate_duration(dest)
    except Exception:
        pass
    sid = db.upsert_song(slug, title=title.strip() or slug, album=album.strip(), genre=genre,
                          subgenre=subgenre, genre2=genre2, subgenre2=subgenre2,
                          mp3_path=dest, duration=duration, explicit=int(explicit))
    jobs.enqueue("transcribe", {"song_id": sid}, song_id=sid)
    jobs.enqueue("analyse", {"song_id": sid}, song_id=sid)
    if wants_json(request):
        # the Library stays put and gets the new row; it does not follow the
        # redirect off to the song page mid-upload of the next file
        return JSONResponse({"song_id": sid, "title": title.strip() or slug})
    return RedirectResponse(f"/songs/{sid}", status_code=303)


@app.post("/songs/analyse-all")
def analyse_all_songs(request: Request):
    """Runnable on demand for the songs that predate analyse.py -- everything
    already in the library on the day this shipped.

    Answers JSON to a fetch and a redirect to a plain form post, so the page can
    patch rows as they land without giving up the no-JavaScript path.
    """
    rows = db.q("SELECT id FROM songs WHERE mp3_path IS NOT NULL AND bpm IS NULL")
    queued = [{"song_id": r["id"], "job_id": jobs.enqueue("analyse", {"song_id": r["id"]},
                                                           song_id=r["id"])}
              for r in rows]
    if wants_json(request):
        return JSONResponse({"queued": queued})
    return RedirectResponse("/", status_code=303)


# A poll is a query string, and a query string is not a place to accept an
# unbounded list -- the library is 31 songs and this is generous.
MAX_ANALYSIS_POLL = 500


# Registered BEFORE /songs/{id}: FastAPI matches in declaration order, and
# "analysis" would otherwise be read as a song id and 422.
@app.get("/songs/analysis")
def songs_analysis(ids: str = ""):
    """bpm/key/energy for the given song ids, for polling while analyse runs.

    One poll for the whole batch rather than an EventSource per job: analysing
    the library is 31 jobs, and 31 open streams to watch a single worker do them
    one at a time is a lot of machinery to learn nothing sooner.
    """
    want = [int(i) for i in ids.split(",") if i.strip().isdigit()][:MAX_ANALYSIS_POLL]
    rows = [db.one("SELECT id, bpm, key, energy FROM songs WHERE id=?", i) for i in want]
    return JSONResponse({"songs": [
        {"song_id": r["id"], "bpm": r["bpm"], "key": r["key"], "energy": r["energy"]}
        for r in rows if r]})


# How much of style_text the classifier is shown. The genre is always named in
# the opening clause; sending a whole three-minute production prompt is the
# obvious way to make this expensive for no gain. MEASURED at 240: 31/31 of the
# deployed library classified correctly inside the taxonomy at this length.
GENRE_CLIP = 240

# The ordering sentence and the evidence field are the tuned parts, and both are
# load-bearing. Asked for the four values alone the model JUDGED instead of READ
# and inverted the primary on 3 of the first 10 -- "chunky tech house / UK
# garage-infused bass house" came back as Bass House. Making it copy the phrase
# before choosing fixed all three with no other change.
GENRE_SUGGEST_SYSTEM = (
    "You classify music tracks into a CLOSED taxonomy. You may only use the exact "
    "strings given to you. You never invent a genre or a subgenre.")

GENRE_SUGGEST_USER = """TAXONOMY (genre -> allowed subgenres). Use ONLY these exact strings:
{taxonomy}

Each track below is given with its production style prompt, which usually names
the genre directly. Where the prompt names two styles (often separated by a
slash), the first is the primary and the second goes in genre2/subgenre2.

First COPY the exact style phrase before the first comma. The FIRST style named
there is always the primary -- do not reorder by what seems more specific.

Reply with a JSON object: {{"tracks": [
  {{"id": 1, "evidence": "<the copied phrase>", "genre": "...", "subgenre": "...",
   "genre2": "...", "subgenre2": "..."}}]}}

Use "" for genre2/subgenre2 when only one style is named. Every non-empty value
MUST appear verbatim in the taxonomy above.

TRACKS:
{listing}
"""


@app.post("/songs/genres/suggest")
async def suggest_genres(request: Request):
    """Propose the four genre fields by READING songs.style_text.

    Not an audio classifier, and deliberately so: style_text is the prompt that
    made the track and it opens by naming the genre, on 31 of the 31 songs in the
    library. A CLAP/MERT-class model would be a new dependency and a second
    tenant on the one GPU to work out something already written down.

    It SUGGESTS. Nothing is written -- the caller reviews and posts to
    /songs/genres, exactly as the audio-edit route lets a model fill in the same
    parameters the sliders set and then clamps them the same way.
    """
    body = await request.json()
    ids = [int(i) for i in (body.get("song_ids") or [])]
    if not ids:
        raise HTTPException(400, "no songs selected")
    rows = [r for r in (db.one("SELECT id, title, style_text FROM songs WHERE id=?", i)
                        for i in ids) if r and (r["style_text"] or "").strip()]
    if not rows:
        raise HTTPException(400, "none of those songs has a style prompt to read")
    listing = "\n".join(f'{r["id"]}. "{r["title"]}" :: {(r["style_text"] or "")[:GENRE_CLIP]}'
                        for r in rows)
    try:
        out, model = vision.ask_text(GENRE_SUGGEST_SYSTEM,
                                      GENRE_SUGGEST_USER.format(
                                          taxonomy=json.dumps(GENRE_DATA), listing=listing))
        data = vision.json_or_raise(out, "genre suggestion")
    except Exception as e:
        raise HTTPException(502, f"could not read the style prompts: {e}") from None

    style = {r["id"]: (r["style_text"] or "") for r in rows}
    suggestions, dropped = [], []
    for item in (data.get("tracks") if isinstance(data, dict) else data) or []:
        sid = item.get("id")
        if sid not in style:
            dropped.append({"song_id": sid, "why": "not a song that was asked about"})
            continue
        # TWO checks, not one. The taxonomy check catches an invented label; only
        # the evidence check catches a confident answer about a track the model
        # never actually read, and that is the failure no vocabulary can see.
        evidence = (item.get("evidence") or "").strip()
        if not evidence or evidence not in style[sid]:
            dropped.append({"song_id": sid, "why": "evidence is not quoted from the style prompt"})
            continue
        try:
            g, sg = valid_genre_or_400(item.get("genre"), item.get("subgenre"), "genre")
            g2, sg2 = valid_genre_or_400(item.get("genre2"), item.get("subgenre2"), "genre2")
        except HTTPException as e:
            dropped.append({"song_id": sid, "why": e.detail})
            continue
        suggestions.append({"song_id": sid, "genre": g, "subgenre": sg,
                            "genre2": g2, "subgenre2": sg2, "evidence": evidence})
    return JSONResponse({"suggestions": suggestions, "dropped": dropped, "model": model})


@app.post("/songs/genres")
async def bulk_set_genres(request: Request):
    """Apply one genre decision to many songs at once.

    A BLANK genre means LEAVE IT ALONE, never "clear it": someone setting only
    the secondary genre on twelve songs must not silently lose the primary on all
    twelve. Clearing is a different intention and deliberately has no control
    here. A genre carries its own subgenre, so picking a genre and leaving the
    subgenre blank does clear that subgenre -- they are one choice, not two.
    """
    body = await request.json()
    ids = [int(i) for i in (body.get("song_ids") or [])]
    if not ids:
        raise HTTPException(400, "no songs selected")
    genre, subgenre = valid_genre_or_400(body.get("genre"), body.get("subgenre"), "genre")
    genre2, subgenre2 = valid_genre_or_400(body.get("genre2"), body.get("subgenre2"), "genre2")
    fields = {}
    if genre:
        fields["genre"], fields["subgenre"] = genre, subgenre
    if genre2:
        fields["genre2"], fields["subgenre2"] = genre2, subgenre2
    if not fields:
        raise HTTPException(400, "pick a genre to apply")
    sets = ", ".join(f"{k}=?" for k in fields)
    existing = [sid for sid in ids if db.one("SELECT id FROM songs WHERE id=?", sid)]
    # One transaction (T10-6 / T6-14): a crash mid-loop rolls back every row.
    c = db.conn()
    c.execute("BEGIN")
    try:
        for sid in existing:
            c.execute(f"UPDATE songs SET {sets} WHERE id=?", (*fields.values(), sid))
        c.commit()
    except Exception:
        c.rollback()
        raise
    updated = []
    for sid in existing:
        row = db.one("SELECT id, genre, subgenre, genre2, subgenre2 FROM songs WHERE id=?", sid)
        updated.append({"song_id": row["id"], "genre": row["genre"] or "",
                        "subgenre": row["subgenre"] or "", "genre2": row["genre2"] or "",
                        "subgenre2": row["subgenre2"] or ""})
    # the STORED values, so the page paints what was saved rather than what was
    # typed -- otherwise a value dropped by validation stays visible and looks fine
    return JSONResponse({"updated": updated})


@app.get("/api/songs/{id}/peaks")
def song_peaks(id: int, z: int = 0):
    """T1-13 / T1-15: peaks as data. Empty carries a reason, not a flat line."""
    song = get_song_or_404(id)
    try:
        z = max(0, int(z))
    except (TypeError, ValueError):
        z = 0
    env = mixer.peaks_from_path(song["mp3_path"], z=z)
    return {"song_id": id, "z": z, "n": len(env["pairs"]),
            "pairs": env["pairs"], "reason": env["reason"]}


@app.get("/songs/{id}", response_class=HTMLResponse)
def song_page(request: Request, id: int):
    song = get_song_or_404(id)
    storyboards = {r["tier"]: r for r in db.q("SELECT * FROM storyboards WHERE song_id=?", id)}
    style_assets = db.q("SELECT * FROM assets WHERE song_id=? AND kind='style' ORDER BY id DESC", id)
    renders = db.q("SELECT * FROM renders WHERE song_id=? ORDER BY id DESC", id)
    song_jobs = db.q("SELECT * FROM jobs WHERE song_id=? ORDER BY id DESC LIMIT 20", id)
    active_job = next((j for j in song_jobs if j["status"] in ("queued", "running", "cancelling")), None)
    try:
        # the xAI CHAT models -- named chat_models, not models, because `models`
        # is this app's model CATALOGUE module and shadowing it here silently
        # turned models.default_for() into a list attribute lookup
        chat_models = grok.list_models()
    except Exception:
        chat_models = []
    # what "(highest available)" will actually pick, named in the dropdown so
    # the default is not a mystery
    best = grok.best_model(chat_models) if chat_models else None
    # assembling needs CLIPS, not a tier that merely exists
    render_tiers = sorted({r["tier"] for r in
                           db.q("SELECT DISTINCT tier FROM clips WHERE song_id=? AND status='done'", id)})
    audio_duration = None
    if song["mp3_path"]:
        try:
            audio_duration = mixer.probe(song["mp3_path"])["duration"]
        except Exception:
            pass
    audio_edits = db.q("SELECT * FROM assets WHERE song_id=? AND kind='audio_edit' ORDER BY id DESC", id)
    audio_gens = db.q("SELECT * FROM assets WHERE song_id=? AND kind='audio_gen' ORDER BY id DESC", id)
    audio_original = db.one("SELECT * FROM assets WHERE song_id=? AND kind='audio_original'", id)
    # anchors belong to the song's ALBUM, not the song -- this is a read-only
    # summary for convenience; management happens on /anchors.
    chosen_anchors = db.q(
        """SELECT * FROM anchors WHERE scope_kind='album' AND scope_value=? AND chosen=1
           ORDER BY tier, view""", song["album"] or "")
    # a tier is offered for clip generation only once every scene of its
    # storyboard has an approved reference -- otherwise start_clips just 400s
    # one click later.
    clips_ready_tiers = []
    # PER TIER, because clip length is per storyboard now: two tiers of one song
    # can be generated at different scene lengths and therefore have different
    # clip counts. Hoisting this out of the loop, as it was, would test one
    # tier's approvals against another tier's clip count.
    for t, sb in storyboards.items():
        n_clips = clip_count(song, scene_seconds_for(song["id"], t))
        if not n_clips:
            continue
        approved_idxs = {r["clip_idx"] for r in
                          db.q("SELECT clip_idx FROM refs WHERE song_id=? AND tier=? AND approved=1", id, t)}
        if all(i in approved_idxs for i in range(n_clips)):
            clips_ready_tiers.append(t)
    # tiers with ANY approved ref can be image-reviewed; that is a weaker
    # condition than clips_ready_tiers on purpose -- reviewing early is the
    # point, waiting for all 41 to be approved defeats it.
    approved_tiers = sorted({r["tier"] for r in
                             db.q("SELECT DISTINCT tier FROM refs WHERE song_id=? AND approved=1", id)})
    # newest review PER TIER. Listing the last N assets showed the same tier
    # twice whenever the check was run more than once, which reads as a bug in
    # the review rather than a second run of it.
    reviews, seen_tiers = [], set()
    for a in db.q("SELECT * FROM assets WHERE song_id=? AND kind='review' ORDER BY id DESC", id):
        meta = json.loads(a["meta_json"] or "{}")
        tier = meta.get("tier", "?")
        if tier in seen_tiers:
            continue
        seen_tiers.add(tier)
        reviews.append({"tier": tier, "flagged": meta.get("flagged", []),
                        "path": a["path"], "backend": meta.get("backend", "")})
    # Whether each storyboard tier can actually render references: it needs a
    # chosen anchor for the album. start_refs 400s without one (see its own
    # check), and answering that BEFORE the click is the whole point -- the same
    # correction already made for tiers that have no storyboard.
    anchor_by_tier = {t: chosen_anchor("album", song["album"] or "", t) for t in storyboards}
    # the video models offered for the clip pass, each named with what it is
    # designed for -- the catalogue is the single place that knows. Only WIRED
    # ones are offered: a catalogued evaluation candidate has no renderer value
    # and must not be selectable.
    default_video = models.default_for("video")
    wired = models.renderable("video")
    video_models = [{"value": wired[e["key"]], "label": e["label"], "purpose": e["purpose"],
                     "available": e["available"], "default": e["key"] == default_video}
                    for e in models.catalog(role="video") if e["key"] in wired]
    all_tiers = tiers.all_tiers()
    form_tier = next(iter(storyboards), None) or (all_tiers[0]["name"] if all_tiers else "")
    beat_count = len(json.loads(song["beat_grid_json"])) if song["beat_grid_json"] else 0
    return templates.TemplateResponse(request, "song.html", {
        "song": song, "tiers": all_tiers, "storyboards": storyboards, "beat_count": beat_count,
        "approved_tiers": approved_tiers, "reviews": reviews,
        "style_assets": style_assets, "chosen_anchors": chosen_anchors,
        "clips_ready_tiers": clips_ready_tiers, "anchor_by_tier": anchor_by_tier,
        "video_models": video_models,
        "renders": renders, "song_jobs": song_jobs, "active_job": active_job,
        "models": chat_models,
        "audio_duration": audio_duration, "audio_edits": audio_edits, "audio_original": audio_original,
        "audio_gens": audio_gens, "audio_model": models.get(models.default_for("audio")),
        "best_model": best, "render_tiers": render_tiers,
        **storyboard_form_ctx(song, form_tier, chat_models, best),
    })


# --------------------------------------------------------------------- QC --
#
# docs/TRD-3. The checks live in qc.py (pure, no db) and the recording and queue
# in qc_service.py (no FastAPI), so everything below is a thin call -- no
# arithmetic, no defaulting, no decision. If a route handler decided something,
# a mobile client could not.
#
# JSON ONLY, deliberately: a review-queue PAGE is a UI, and the UI/UX pass that
# produces the style guide has not run. Building a page now would pre-empt it.


def _clip_expect(path):
    """What the workflow that produced this clip asked for, or {}.

    Written by pipeline._stamp_expect at collect time from the submitted graph.
    Absent for every clip rendered before 2026-08-13, and absent is not zero:
    an empty dict makes qc skip the comparisons rather than compare against a
    guess, which is the whole difference between a check and a fabrication.
    """
    row = db.one("SELECT expect_json FROM artefacts WHERE path=?",
                 jobs.canonical_path(path))
    if not row or not row["expect_json"]:
        return {}
    try:
        return json.loads(row["expect_json"])
    except ValueError:
        return {}


@jobs.handler("qc")
def h_qc(args, progress):
    """Tier 1 over one song's artefacts at one tier.

    Assembled render is checked against songs.duration (T6-13a) and must carry
    audio. Clips get artefacts.expect_json via _clip_expect; absent stays
    absent (T6-13) so duration/frame comparisons skip rather than invent a
    baseline from the file.
    """
    song = db.one("SELECT * FROM songs WHERE id=?", args["song_id"])
    if not song:
        return
    tier = args.get("tier") or ""
    found, seen = [], 0

    for r in db.q("SELECT * FROM renders WHERE song_id=? AND tier=? ORDER BY id DESC",
                  song["id"], tier)[:1]:
        progress(f"qc: assembled render {os.path.basename(r['path'])}")
        found += qc_service.run_artefact(
            r["path"], "song",
            {"duration": song["duration"], "want_audio": True} if song["duration"]
            else {"want_audio": True})
        seen += 1

    for c in db.q("""SELECT * FROM clips WHERE song_id=? AND tier=? AND path IS NOT NULL
                     ORDER BY clip_idx""", song["id"], tier):
        progress(f"qc: clip {c['clip_idx']}")
        found += qc_service.run_artefact(c["path"], "clip", _clip_expect(c["path"]))
        seen += 1

    for f in db.q("SELECT * FROM refs WHERE song_id=? AND tier=? ORDER BY clip_idx",
                  song["id"], tier):
        found += qc_service.run_artefact(f["path"], "image", {})
        seen += 1

    counts = {v: sum(1 for x in found if x["verdict"] == v)
              for v in (qc.PASS, qc.FLAG, qc.REJECT)}
    return {"artefacts": seen, "checks": len(found), **counts}


@app.post("/songs/{id}/qc")
def start_qc(id: int, tier: str = Form("")):
    get_song_or_404(id)
    jobs.enqueue("qc", {"song_id": id, "tier": tier}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.get("/api/qc/findings")
def api_qc_findings(status: str = "open", kind: str = "", tier: int = 0,
                    include_pass: bool = False):
    return JSONResponse({"findings": [
        dict(r) for r in qc_service.queue(status=status or None, kind=kind or None,
                                          tier=tier or None, include_pass=include_pass)]})


@app.get("/api/qc/by-host")
def api_qc_by_host():
    """T3-1: per-box report. qc_service.by_host decides; this route forwards."""
    return JSONResponse({"groups": qc_service.by_host()})


@app.get("/api/qc/findings/{fid}")
def api_qc_finding(fid: int):
    try:
        return JSONResponse(dict(qc_service.get(fid)))
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/qc/findings/{fid}/remedy")
def api_qc_remedy(fid: int, text: str = Form(""), album: str = Form("")):
    try:
        return JSONResponse(dict(qc_service.set_remedy(fid, text, album=album or None)))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/qc/findings/{fid}/dismiss")
def api_qc_dismiss(fid: int, why: str = Form("")):
    try:
        return JSONResponse(dict(qc_service.dismiss(fid, why)))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/qc/findings/{fid}/approve")
def api_qc_approve(fid: int):
    """Human sign-off. qc_service.approve enqueues the repair; this route
    only forwards. A ValueError is a bad finding (dismissed, no remedy)."""
    try:
        row = qc_service.approve(fid)
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except KeyError:
        raise HTTPException(404, f"no finding {fid}")
    return {"ok": True, "id": row["id"], "status": row["status"]}


@app.post("/songs/{id}/analyse")
def start_analyse(id: int):
    song = get_song_or_404(id)
    if not song["mp3_path"]:
        raise HTTPException(400, "no audio to analyse -- upload an mp3 first")
    jobs.enqueue("analyse", {"song_id": id}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/downbeat-offset")
def set_downbeat_offset(id: int, downbeat_offset: int = Form(...)):
    """analyse.py only guesses bar one from the first four beats -- a set
    built on the wrong guess sounds wrong in a way no tuning fixes, and a
    human fixes it in a second by ear. See db.MIGRATIONS' comment."""
    get_song_or_404(id)
    if not 0 <= downbeat_offset <= 3:
        raise HTTPException(400, "downbeat_offset must be 0-3")
    db.run("UPDATE songs SET downbeat_offset=? WHERE id=?", downbeat_offset, id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/explicit")
def toggle_explicit(id: int):
    """Toggle whether this track's LYRICS are explicit. Metadata about the
    lyrics only -- never gates or selects a tier, see h_storyboard's comment."""
    song = get_song_or_404(id)
    db.run("UPDATE songs SET explicit=? WHERE id=?", 0 if song["explicit"] else 1, id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/lyrics")
def save_lyrics(id: int, lyrics_text: str = Form(...)):
    get_song_or_404(id)
    db.run("UPDATE songs SET lyrics=? WHERE id=?", lyrics_text, id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/style-text")
def save_style_text(id: int, style_text: str = Form(...)):
    """The prompt the TRACK was generated from. Stored, shown and editable --
    it is not sent to grok or the renderer: it describes drums and vocals, and
    the storyboard prompt is about pictures. Storyboards used to carry exactly
    this text as `suno_style_reference` and it was stripped out as dead weight.
    """
    get_song_or_404(id)
    db.run("UPDATE songs SET style_text=? WHERE id=?", style_text, id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/style")
async def upload_style(id: int, image: UploadFile = File(...), note: str = Form("")):
    song = get_song_or_404(id)
    # the style note is free text that flows straight into every scene prompt,
    # so it gets the same minor-reference screening as a custom tier definition
    try:
        tiers.check_text(note, "style note")
    except ValueError as e:
        raise HTTPException(400, str(e))
    dest = await save_upload(image, MAX_IMAGE, upload_dir(song["slug"]), "image",
                              prefix=f"style_{int(time.time() * 1000)}")
    db.run("UPDATE songs SET style_path=? WHERE id=?", dest, id)
    db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
           id, "style", dest, json.dumps({"note": note}), time.time())
    return RedirectResponse(f"/songs/{id}", status_code=303)


def nest_anchor_groups(group_list):
    """Tier tabs → clothed/nude sub-tabs → one row per camera position.

    Flat groups stay available for tests that walk candidates; the page
    renders this nest so a dozen sheets do not dump as one long column.
    """
    sections = []
    index = {}
    for g in group_list:
        key = (g["scope_kind"], g["scope_value"], g["character_id"], g["character_name"])
        if key not in index:
            index[key] = {"scope_kind": key[0], "album": key[1],
                          "character_id": key[2],
                          "character_name": key[3] or "protagonist",
                          "tier_map": {}}
            sections.append(index[key])
        sec = index[key]
        tier = g["tier"] or ""
        if tier not in sec["tier_map"]:
            sec["tier_map"][tier] = {"clothed": {}, "nude": {}}
        family = view_family(g["view"])
        pos = view_position_label(g["view"])
        sec["tier_map"][tier][family].setdefault(pos, []).append(g)
    out = []
    for sec in sections:
        tiers = []
        for name, fams in sec["tier_map"].items():
            families = []
            for fam_key in ("clothed", "nude"):
                rows = [{"position": pos, "groups": gs}
                        for pos, gs in fams[fam_key].items()]
                families.append({"key": fam_key, "rows": rows})
            tiers.append({"name": name, "families": families})
        out.append({"scope_kind": sec["scope_kind"], "album": sec["album"],
                    "character_id": sec["character_id"],
                    "character_name": sec["character_name"],
                    "tab_id": f"anchor-gallery-{len(out)}",
                    "tiers": tiers})
    return out


@app.get("/anchors", response_class=HTMLResponse)
def anchors_page(request: Request, scope_kind: str = "", scope_value: str = ""):
    # This route has always ACCEPTED scope_kind/scope_value and never applied
    # them: every link that passes one -- six templates and four redirects, all
    # of them "manage anchors for THIS album" -- got every anchor in the database
    # back and rendered every one. Filtering here is what those links already
    # promise, and it is the only bound this page has.
    # ponytail: unfiltered /anchors is still unbounded. A LIMIT cannot go here
    # without splitting a group across the boundary and miscounting `unpicked`;
    # if it ever hurts, paginate by GROUP (scope, character, tier, view).
    clauses, params = [], []
    if scope_kind:
        clauses.append("a.scope_kind=?")
        params.append(scope_kind)
    if scope_value:
        clauses.append("a.scope_value=?")
        params.append(scope_value)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    # grouped by CHARACTER as well: two characters' candidates in one grid, with
    # one "chosen" between them, is unreadable and mispicks are invisible
    rows = db.q(f"""SELECT a.*, c.name AS character_name
                    FROM anchors a LEFT JOIN characters c ON c.id = a.character_id{where}
                    ORDER BY a.scope_kind, a.scope_value, c.name, a.tier, a.view, a.id DESC""",
                *params)
    groups = {}
    for r in rows:
        key = (r["scope_kind"], r["scope_value"], r["character_id"], r["character_name"],
               r["tier"], r["view"])
        groups.setdefault(key, []).append(r)
    group_list = [{"scope_kind": k[0], "scope_value": k[1], "character_id": k[2],
                   "character_name": k[3], "tier": k[4], "view": k[5], "candidates": v,
                   # how many rejects this group is carrying: every generation
                   # adds N candidates and only one is ever picked
                   "unpicked": sum(1 for c in v if not c["chosen"])}
                  for k, v in groups.items()]
    albums = sorted({s["album"] for s in db.q("SELECT DISTINCT album FROM songs") if s["album"]})
    playlists = db.q("SELECT id, name FROM playlists WHERE kind='playlist' ORDER BY name")
    # Failures belong on the page the work was STARTED from. Nine sheets died to
    # a five-second ComfyUI restart and the only trace was on /jobs -- from here
    # it looked as though the button had done nothing at all, which is exactly
    # what the user reported.
    failed = [j for j in db.q("""SELECT * FROM jobs WHERE kind='anchor' AND status='failed'
                                 ORDER BY id DESC LIMIT 20""")]
    fresh = [j for j in failed if (time.time() - (j["finished"] or 0)) < 86400]
    # Work already in flight, so the queued indicator survives a reload and a
    # second browser tab. Without this the only evidence a batch existed was in
    # the JavaScript of the tab that started it -- reload, and twelve running
    # sheets looked exactly like nothing having happened.
    active = [{"id": j["id"], "tier": db.jset(j, "args_json").get("tier", ""),
               "view": db.jset(j, "args_json").get("view", "")}
              for j in db.q("""SELECT * FROM jobs WHERE kind='anchor'
                               AND status IN ('queued','running') ORDER BY id""")]
    return templates.TemplateResponse(request, "anchors.html", dict(
        anchor_form_ctx(scope_value),
        groups=group_list, gallery=nest_anchor_groups(group_list),
        known_albums=albums, playlists=playlists,
        failed_jobs=fresh, active_jobs=active))


MAX_ANCHOR_UPLOADS = 8


def form_files(form, field):
    """The genuinely-uploaded files under `field`, from an already-parsed form.

    NOT `List[UploadFile] = File([])`. A browser with an EMPTY file input still
    sends a part for it, with filename="", and python-multipart hands that back
    as a str -- which fails UploadFile validation with a 422 before any handler
    code runs. That made "generate from saved base images without adding a new
    one" impossible, which is the whole point of keeping them. Reading the parsed
    form instead accepts both encodings and filters on what actually matters:
    whether a part carries a filename.
    """
    return [f for f in form.getlist(field)
            if hasattr(f, "filename") and (f.filename or "").strip()]


def anchor_refs(album, character_id=None):
    """The saved base images for one album and character, newest first.

    Reference images used to be uploaded per generation and then forgotten: the
    files stayed on disk, nothing recorded them, and the same photographs had to
    be picked off the filesystem again for every sheet. They are kept now, in
    the `assets` bag that already holds sets, style images and reviews, so a
    kind is all this needed rather than a table of its own.

    Scoped to album AND character, exactly as anchors are -- a cast member's
    reference photographs are not the protagonist's, and pooling them would
    condition one character's sheet on another's face.
    """
    out = []
    for a in db.q("SELECT * FROM assets WHERE kind='anchor_ref' ORDER BY id DESC"):
        meta = db.jset(a)
        if meta.get("scope_value") != album:
            continue
        if (meta.get("character_id") or None) != (character_id or None):
            continue
        out.append(a)
    return out


async def _save_anchor_refs(album, character_id, uploads):
    """Persist uploaded base images and return their asset rows."""
    dest_dir = os.path.join(db.DATA, "uploads", "anchors", "album", safe_name(album))
    stamp = int(time.time() * 1000)
    saved = []
    for i, f in enumerate(uploads):
        path = await save_upload(f, MAX_IMAGE, dest_dir, "image", prefix=f"ref{i}_{stamp}")
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               None, "anchor_ref", path,
               json.dumps({"scope_value": album, "character_id": character_id}), time.time())
        saved.append(db.one("SELECT * FROM assets WHERE path=? AND kind='anchor_ref'", path))
    return saved


def _anchor_ctx_from_form(form, album, character_id):
    """Rebuild the generate form from what was SUBMITTED, not from defaults.

    The htmx branches used to call anchor_form_ctx(album) and let every other
    argument default, which silently reset the ticked tiers, the chosen views,
    every typed per-tier prompt and (on delete) the selected character. The
    page did not reload, as asked -- so the state loss was invisible instead of
    being announced by a navigation, which is worse than the reload it replaced.

    hx-include sends the whole form with both requests, so all of it is here.
    """
    tiers_sel = [t for t in form.getlist("tier") if t]
    views_sel = [v for v in form.getlist("view") if v]
    typed = {k[len("prompt_"):]: v for k, v in form.items() if k.startswith("prompt_")}
    return anchor_form_ctx(album, tiers_sel, views_sel, character_id, typed,
                            negative=form.get("negative") or "",
                            latent=form.get("latent"),
                            pose=form.get("pose") or "")


@app.post("/anchors/refs")
async def add_anchor_refs(request: Request, album: str = Form(...),
                           character_id: CharacterId = Form(None)):
    """Save base images WITHOUT generating anything.

    Uploading and generating were one action, so there was no way to build up a
    set of references and come back to it -- and every re-generation meant
    finding the same photographs again.
    """
    album = (album or "").strip()
    if not db.one("SELECT id FROM playlists WHERE name=? AND kind='playlist'", album):
        raise HTTPException(400, f"no album called {album!r}")
    uploads = form_files(await request.form(), "images")
    if not uploads:
        raise HTTPException(400, "choose at least one image to save")
    if len(uploads) > MAX_ANCHOR_UPLOADS:
        raise HTTPException(400, f"that is {len(uploads)} images; {MAX_ANCHOR_UPLOADS} at a time")
    if character_id is not None:
        char = get_character_or_404(character_id)
        if char["scope_value"] != album:
            raise HTTPException(400, f"character {char['name']!r} belongs to {char['scope_value']!r}")
    await _save_anchor_refs(album, character_id, uploads)
    # htmx swaps the form back in with the new thumbnails; a plain browser still
    # gets the redirect, so this works with JavaScript off exactly as before
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request, "_anchor_form.html",
            _anchor_ctx_from_form(await request.form(), album, character_id))
    return RedirectResponse(f"/anchors?scope_value={quote(album)}", status_code=303)


@app.post("/anchors/refs/{asset_id}/delete")
async def delete_anchor_ref(request: Request, asset_id: int):
    """Remove a saved base image, row and file. Anchors already generated from
    it are untouched -- they are their own images, not references to this one."""
    a = db.one("SELECT * FROM assets WHERE id=? AND kind='anchor_ref'", asset_id)
    if not a:
        raise HTTPException(404, "no such reference image")
    meta = db.jset(a)
    album = meta.get("scope_value", "")
    # A BORROWED reference is a row pointing at a sheet this studio rendered,
    # not an upload of its own (see use_anchor_as_ref). The row goes; the file
    # stays, because it is the anchor's -- removing it here would delete the
    # chosen sheet out from under the anchors gallery and every clip that
    # renders from it.
    if not meta.get("anchor_id"):
        if _within_data(a["path"]) and os.path.isfile(a["path"]):
            try:
                os.remove(a["path"])
            except OSError:
                pass
    db.run("DELETE FROM assets WHERE id=?", asset_id)
    # the anchor lightbox's Delete button hits this same route via api(), which
    # asks for JSON same as every other button in that modal -- htmx's own
    # Delete button below the thumbnail still gets the swapped form back
    if wants_json(request):
        return JSONResponse({"deleted": [asset_id]})
    return await _anchor_form_or_redirect(request, album)


async def _anchor_form_or_redirect(request, album):
    """The htmx-or-navigate tail every /anchors/refs route ends with."""
    if request.headers.get("HX-Request"):
        form = await request.form()
        # the character too: deleting one of a CHARACTER's base images used to
        # swap the form back to the protagonist and show the protagonist's
        # gallery, because character_id defaulted to None
        cid = form.get("character_id")
        cid = int(cid) if cid not in (None, "") else None
        return templates.TemplateResponse(request, "_anchor_form.html",
                                           _anchor_ctx_from_form(form, album, cid))
    return RedirectResponse(f"/anchors?scope_value={quote(album)}", status_code=303)


@app.post("/anchors/{id}/use-as-ref")
async def use_anchor_as_ref(request: Request, id: int):
    """Condition the NEXT sheet on a sheet this studio already rendered.

    The single largest consistency lever this pipeline has, and it was unwired.
    Clips stay on-model because gen_refs hands the chosen anchor to the model as
    image1 -- the identity lock -- for every scene. The anchors form could only
    read `assets` of kind `anchor_ref`, which are UPLOADS, so every sheet was a
    fresh interpretation of the source photographs and sheet 2 was never a
    variation of the sheet you approved. docs/TRD-7 T7-6.

    The row points at the anchor's OWN file. No copy: pipeline.gen_anchor puts
    every picked path through install_input at render time, exactly as gen_refs
    does, so duplicating the bytes here would only create a second thing to keep
    in step. That is also why deleting this reference deletes the row and not
    the file (see delete_anchor_ref), and why deleting the ANCHOR takes its
    borrowed references with it (_drop_anchor) -- a reference to a file that no
    longer exists renders a job that fails at load.

    Scope comes from the anchor ROW, never the form: an anchor already carries
    the album and character it belongs to, and reading them from a submitted
    field is how one character's face ends up conditioning another's sheet.
    """
    row = db.one("SELECT * FROM anchors WHERE id=?", id)
    if not row:
        raise HTTPException(404, "no such anchor candidate")
    if row["scope_kind"] != "album":
        raise HTTPException(400, "only an album's anchors can be used as references")
    album, cid = row["scope_value"], row["character_id"]
    existing = db.one("""SELECT * FROM assets WHERE kind='anchor_ref' AND path=?
                         ORDER BY id DESC""", row["path"])
    if existing:
        # Idempotent. Pressing it twice used to be the only way to find out it
        # had worked, and two rows for one file would fill the gallery with the
        # same picture and count twice against MAX_ANCHOR_REFS.
        asset = existing
    else:
        aid = db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) "
                     "VALUES (?,?,?,?,?)", None, "anchor_ref", row["path"],
                     json.dumps({"scope_value": album, "character_id": cid,
                                 # what makes it borrowed rather than uploaded
                                 "anchor_id": row["id"], "tier": row["tier"],
                                 "view": row["view"]}), time.time())
        asset = db.one("SELECT * FROM assets WHERE id=?", aid)
    if wants_json(request):
        return JSONResponse({"id": asset["id"], "path": asset["path"],
                             "already": bool(existing)})
    return await _anchor_form_or_redirect(request, album)


def _build_refs():
    """build_refs lives at the repo root beside make_anchor.py, and is imported
    lazily so the studio still starts on a checkout without the CLI scripts."""
    import build_refs
    return build_refs


def _make_anchor():
    """Same reason as _build_refs: the composer is a repo-root CLI script."""
    import make_anchor
    return make_anchor


def anchor_prompt_field(tier, view):
    """The form field one tier's ONE VIEW writes its prompt into.

    Per tier AND view. Four routes read these boxes -- the form, the plan, the
    preview and the submit -- and a field name spelled out at each of them is
    how three of them agree and the fourth renders something else. `__` is the
    separator because a view key never contains one, so the suffix splits back
    exactly (see /anchors/form, which carries these keys opaquely).
    """
    return f"prompt_{tier}__{view}"


ANCHOR_MODES = ("fast", "quality")
# ONE default, read by both the form parser and the settings resolver. They had
# their own, and they disagreed: anchor_render_settings defaulted to quality
# while resolved_settings defaulted to fast, so the same absent field produced
# cfg 4.5 with the negative live down one path and cfg 1.0 with it inert down
# the other. Caught by the check asserting the backdrop's absences landed in a
# negative the default mode actually applies.
DEFAULT_ANCHOR_MODE = "quality"
MAX_NEGATIVE = 1200

# The negative the form starts with, PRE-FILLED rather than offered as a
# placeholder -- placeholder text is grey, vanishes the moment you type, and is
# never submitted, so a field that looked populated sent nothing.
#
# Deliberately generic. This studio will anchor other characters, other species
# and other palettes, so nothing here names a colour the CURRENT album happens
# to want: every term is a failure MODE (a patch that disagrees with the rest of
# the body, skin where fur belongs, clothing on a nude sheet, a limb count) not
# a character trait. Edit it per album; it is a starting point, not a rule.
DEFAULT_NEGATIVE = (
    "mismatched fur colour, lighter fur patches, discoloured tail, two-tone body, "
    "human skin, bare skin where fur belongs, clothing on a nude sheet, underwear, "
    "extra limbs, extra tails, missing tail, deformed hands, duplicate character, "
    "cropped head, cropped feet, text, watermark, signature, blurry, low detail, "
    # The studio backdrop's absences live HERE now, not in make_anchor.BACKDROP.
    # Naming them in the positive prompt is what put smoke around every sheet's
    # edges and a wet-looking haze across its bottom for the life of this
    # project -- "no smoke" reads as "smoke" to the model. In the negative they
    # do what they were meant to do, and only above cfg 1.0, which is where
    # quality mode already puts us.
    "smoke, haze, fog, mist, atmospheric particles, wet ground, wet reflective floor, "
    "puddles, alley, brick wall, neon lighting, purple or magenta lighting, vignette, "
    "dark corners, scenery, props"
)

# CFG, as the choice it actually is rather than a free number. 1.0 is the
# Lightning LoRA's own operating point and the only one where a negative prompt
# is ignored; everything above it drops the LoRA (build_refs.sampler_settings)
# and costs steps. Values are the sampler's, not a scale invented here.
#
# The list is the operator's spec (1.0, 3.0, 5.0, 7.0, 7.5, 8.0, 9.0) merged
# with the five a fixed-seed sweep rendered on 2026-08-12.
#
# THE LABELS NO LONGER QUOTE THAT SWEEP, and why is worth keeping. It measured
# fur turning to human skin as guidance rose, and the cause turned out to be a
# contradiction in the PROMPT -- make_anchor.NUDE_WARDROBE asserting "bare skin
# over the whole body" beside a body clause describing fur -- not a property of
# the sampler. That contradiction is gone, so those numbers describe renders
# that can no longer be reproduced, and a label quoting a measurement that no
# longer holds is worse than a label with no measurement in it.
#
# 4.5 stays the default because it is mid-range and it worked; the high end is
# now described by what guidance DOES rather than by what one sweep saw. Re-run
# the sweep against the corrected prompt if the default is worth moving.
CFG_CHOICES = (
    ("1.0", "1.0 — Lightning LoRA, 4 steps, fastest. Negative prompt IGNORED."),
    ("2.0", "2.0 — gentle guidance, closest to the references"),
    ("3.0", "3.0 — gentle-to-balanced"),
    ("3.5", "3.5 — balanced; follows the prompt without flattening the references"),
    ("4.5", "4.5 — stronger prompt adherence, more contrast. Best of the measured five."),
    ("5.0", "5.0 — stronger still"),
    ("6.0", "6.0 — heavy guidance; oversaturates and stiffens poses"),
    ("7.0", "7.0 — heavier still"),
    ("7.5", "7.5 — the written spec's default. Never measured well here."),
    ("8.0", "8.0"),
    ("9.0", "9.0 — the top of the range"),
)

# Steps, spanning the spec's 10-50 range plus the Lightning LoRA's own 4. The
# empty option stays FIRST and stays the default: an unset field must reach
# make_anchor as absent, so the mode's own number applies, rather than as a
# number this form happened to list.
STEPS_CHOICES = (
    ("4", "4 — the Lightning LoRA's own count; only meaningful at CFG 1.0"),
    ("10", "10 — fast, soft detail"),
    ("14", "14"),
    ("20", "20"),
    ("28", "28 — quality mode's own"),
    ("36", "36"),
    ("50", "50 — slowest, diminishing returns"),
)

# Denoise. The spec asks for 0.65 by default and that would produce noise HERE:
# an anchor renders from EmptySD3LatentImage (build_refs.workflow,
# latent_mode="empty"), so there is no base latent to preserve and anything
# below 1.0 leaves it partly un-denoised. The values are offered because the
# spec asks for them and a refine-from-image pass genuinely wants them; the
# default stays 1.0 and each lower value says what it is for.
#
# ...and the labels are computed from the latent mode rather than written down,
# because both halves used to be true at once: the values were offered AND every
# one of them was documented as broken. What made them broken was
# latent_mode="empty", which is now a control (LATENT_CHOICES), so the same list
# is honest under one mode and useless under the other. One resolver, so the
# label and the graph cannot disagree -- an editor promising what the renderer
# does not produce is this codebase's recurring defect. docs/TRD-7 T7-8.
LATENT_CHOICES = (
    ("empty", "empty latent — generate a new sheet from noise, at the size below"),
    ("image", "from the first reference — refine it, keeping its composition and size"),
)
DEFAULT_LATENT = "empty"

# Sheet size, as a chosen PAIR. gen_anchor never passed --width/--height, so
# every sheet this studio has rendered was make_anchor's 896x1216 -- which is a
# full-body portrait frame, and a head-and-shoulders framing asked for inside it
# renders a distant figure. Offered as presets rather than two free numbers
# because a latent that is not a multiple of 16 is a refusal from ComfyUI one
# queue round-trip later, and because these are the shapes the model was
# packaged for. The first entry is make_anchor's own default and stays first.
# docs/TRD-7 T7-12.
SIZE_CHOICES = (
    ("896x1216", "896 × 1216 — the standing full-body sheet (the default)"),
    ("832x1216", "832 × 1216 — taller and narrower; more headroom, tighter sides"),
    ("1024x1024", "1024 × 1024 — square; head-and-shoulders and seated framings"),
    ("1216x832", "1216 × 832 — landscape; a lying or reclining sheet"),
    ("1152x896", "1152 × 896 — gentle landscape"),
)
# The Lightning LoRA weight, as the three points that mean something plus the
# two between them. Blank stays the default and means "the mode decides".
LORA_CHOICES = (
    ("1.0", "1.0 — the Lightning distillation at full strength (fast mode's own)"),
    ("0.75", "0.75"),
    ("0.5", "0.5 — half; between the two modes, and unmeasured here"),
    ("0.25", "0.25"),
    ("0.0", "0.0 — LoRA off, which is what quality mode does to allow CFG above 1"),
)
DENOISE_VALUES = ("0.35", "0.45", "0.55", "0.65", "0.75", "1.0")


def denoise_choices(latent=DEFAULT_LATENT):
    """[(value, label)], worded for the latent the sampler will actually start
    from. Below 1.0 from an EMPTY latent leaves part of the noise in the output;
    below 1.0 from an encoded image is the point of the control."""
    if latent == "image":
        return tuple(
            (v, {"0.35": "0.35 — barely touched; the reference with a new surface",
                 "0.45": "0.45 — light refine, composition and pose held",
                 "0.55": "0.55 — the usable middle: same sheet, re-rendered",
                 "0.65": "0.65 — the spec's default; pose held, detail redrawn",
                 "0.75": "0.75 — heavy; keeps little more than the layout",
                 "1.0": "1.0 — full denoise, which discards the reference entirely"}[v])
            for v in DENOISE_VALUES)
    return tuple(
        (v, f"{v} — refine-from-image only; from an empty latent this returns noise")
        if v != "1.0" else
        (v, "1.0 — full denoise, the only correct value from an empty latent")
        for v in DENOISE_VALUES)

# How many candidates a CFG sweep renders at each guidance value. Off is the
# default and everything else is a deliberate multi-sheet job.
CFG_SWEEP_CHOICES = (2, 3, 4)
# Ceiling on one sweep, in sheets. Eleven values at four each is 44 renders on
# a single card at roughly a minute apiece -- long, but it is one queued job per
# value and each is separately cancellable, so this is a bound against a typo
# rather than a policy.
MAX_SWEEP_SHEETS = 44

# What each technical control DOES, shown by the "?" beside it (templates/
# _macros.html). One dict, not prose inline in the template: the wording is
# needed by more than one template and duplicated prose drifts.
#
# What is deliberately NOT in here: any warning whose absence produces silently
# wrong or wasted output. A modal takes a deliberate click, so the negative
# prompt being dropped below cfg 1.0, denoise returning noise from an empty
# latent, and an edited prompt overriding the per-view framing all stay pinned
# beside their controls. So does anything computed from the current selections --
# that is the form reporting your own choices back, not reference material.
ANCHOR_HELP = {
    "n": {"label": "Candidates per sheet", "body": [
        "How many images one sheet renders. Each gets its own seed, spaced off the base "
        "(seed, +137, +274&hellip;), so they are variations rather than repeats.",
        "Composition here is <strong>seed-dominated</strong> &mdash; the pose and framing vary "
        "far more between seeds than between small prompt changes. That is why more than one "
        "is worth rendering: you pick the composition you want and discard the rest.",
        "Eight is the ceiling for one sheet. A CFG sweep goes far past it by queueing one job "
        "per guidance value instead of one big job."]},
    "mode": {"label": "Generation mode", "body": [
        "<strong>quality</strong> is 28 steps with the Lightning LoRA switched off, about a "
        "minute a sheet. <strong>fast</strong> is the LoRA's own 4 steps at CFG 1.0, about "
        "fifteen seconds.",
        "The difference is not only speed. At CFG 1.0 ComfyUI skips the negative pass "
        "entirely, so a negative prompt in fast mode is <strong>dropped, not weakened</strong>. "
        "Quality mode is the only one where it does anything.",
        "The two knobs move together and cannot be separated: raising CFG above 1.0 forces the "
        "LoRA to zero, because a 4-step distillation driven at CFG 4.5 produces mush."]},
    "cfg": {"label": "Guidance (CFG)", "body": [
        "How hard the model is pushed to follow the prompt rather than its own instincts. "
        "1.0 means no classifier-free guidance at all; higher values follow the words more "
        "literally and start to oversaturate and stiffen poses.",
        "A fixed-seed sweep on this model, three seeds at each of eleven values, measured "
        "something worth knowing: on a <strong>nude</strong> sheet, higher guidance made the "
        "model follow the nude wording more literally and progressively replaced fur with "
        "human skin. Two of three seeds were a human body with a cat's head by 7.0. The "
        "contradiction causing that has since been fixed in the nude wording, but the lesson "
        "stands &mdash; higher is not better here.",
        "The values above 6.0 are offered because the written spec asked for them, not because "
        "they measured well."]},
    "ref_method": {"label": "Reference method", "body": [
        "How the ticked base images are folded into the latent this model conditions on. "
        "There is no IP-Adapter to weight and no ControlNet installed, so this and the prompt "
        "are the only levers on reference adherence.",
        "Try another if fur colour, markings or overall identity drift between sheets.",
        "<code>uxo/uno</code> is the same as <code>offset</code> on this model &mdash; read "
        "from ComfyUI's source, where the Qwen path only branches on <code>index</code>, "
        "<code>index_timestep_zero</code> and <code>negative_index</code>, so uxo falls "
        "through to offset's branch."]},
    "cfg_sweep": {"label": "CFG sweep", "body": [
        "Renders the same sheet at every guidance value in the dropdown, holding the "
        "references, the prompt and the <strong>base seed</strong> fixed so the only thing "
        "changing between the images is the guidance.",
        "That is the whole method. Without a pinned seed the images would differ by seed and "
        "by guidance at once, and nothing in the result would be attributable to the knob "
        "being swept &mdash; which is why the earlier one-sample-per-value sweep settled "
        "nothing.",
        "One queued job per value, each separately cancellable, so this goes far past the "
        "eight candidates a single sheet allows. It needs quality mode, a single tier and a "
        "single view, and Guidance left on &ldquo;follow the mode&rdquo;; anything else is "
        "refused rather than quietly adjusted, and the panel above Generate says so before "
        "you press it."]},
    "steps": {"label": "Steps", "body": [
        "How many denoising steps the sampler takes. More steps means more compute and, up to "
        "a point, more detail; past roughly 30 on this model the returns are hard to see.",
        "4 is the Lightning LoRA's own count and is only meaningful at CFG 1.0 with the LoRA "
        "on. Four steps <em>without</em> the LoRA is an undercooked image, not a fast one."]},
    "size": {"label": "Sheet size", "body": [
        "The latent's dimensions, and therefore the frame the character is composed into.",
        "Every sheet this studio rendered before now was 896&times;1216 &mdash; a standing "
        "full-body frame &mdash; because the size was never passed to the renderer at all. A "
        "head-and-shoulders or seated framing asked for inside that frame comes back as a "
        "distant figure with empty space above and below it: the prompt was followed and the "
        "shape fought it.",
        "Ignored when the sampler starts from a reference, which inherits that image's size."]},
    "lora_strength": {"label": "Lightning LoRA", "body": [
        "How strongly the 4-step Lightning distillation is applied. Fast mode is 1.0, quality "
        "mode is 0.0, and the two modes are exactly this knob plus the step count.",
        "Left on <em>mode decides</em>, raising CFG above 1.0 forces it to 0 &mdash; a 4-step "
        "distillation driven at CFG 4.5 is mush. Setting it here overrides that interlock, "
        "which is the one case build_refs deliberately allows: a partial weight at moderate "
        "guidance is the experiment nobody here has run.",
        "Nothing between 0.0 and 1.0 has been measured on this pipeline. Treat a value in the "
        "middle as an experiment, and pin the seed before you judge it."]},
    "latent": {"label": "Sampler starts from", "body": [
        "<strong>empty latent</strong> is pure noise at the size you asked for &mdash; a new "
        "sheet, and the only thing this form could do until now.",
        "<strong>from the first reference</strong> <code>VAEEncode</code>s your first base "
        "image and denoises from there, so the output keeps its composition and its size and "
        "the width and height controls stop applying. This is what makes Denoise below 1.0 "
        "mean anything: with an empty latent there is nothing to preserve, which is why every "
        "value under 1.0 was labelled as returning noise.",
        "The pairing worth knowing: press <strong>Use as reference</strong> on a sheet you have "
        "already picked, then refine it here at 0.55. That varies a sheet you approved instead "
        "of re-interpreting the photographs and hoping."]},
    "denoise": {"label": "Denoise", "body": [
        "How much of the starting latent is replaced. 1.0 denoises it completely; lower values "
        "preserve some of what was already there.",
        "That only makes sense when something WAS already there. An anchor renders from "
        "<code>EmptySD3LatentImage</code> &mdash; pure noise &mdash; so there is nothing to "
        "preserve and anything below 1.0 leaves part of the noise in the output.",
        "The lower values exist because a refine-from-an-image pass genuinely wants them. "
        "This is not one of those."]},
    "sampler_name": {"label": "Sampler", "body": [
        "The <strong>algorithm</strong> that removes noise at each step &mdash; the solver.",
        "<code>euler</code> takes one naive step at a time. <code>dpmpp_2m</code> is a "
        "second-order multistep method: it uses the previous step to correct the current one, "
        "so it converges in fewer steps, which is why quality mode uses it.",
        "Pairs with the scheduler: the sampler decides HOW to step, the scheduler decides "
        "WHERE the steps land. &ldquo;DPM++ 2M Karras&rdquo; is just that pair, and quality "
        "mode already is it."]},
    "scheduler": {"label": "Scheduler", "body": [
        "The <strong>spacing</strong> of the steps &mdash; how much noise comes out at each "
        "one. Same step count, different distribution of the work.",
        "<code>karras</code> bunches steps at the low-noise end, where fine detail is decided, "
        "and takes bigger strides early where only the composition is at stake. "
        "<code>simple</code> spaces them evenly.",
        "See the Sampler help for how the two fit together."]},
    "seed": {"label": "Seed", "body": [
        "The number the noise is generated from. The same seed with the same prompt and "
        "settings gives the same image.",
        "Blank draws a new one every time, which is what makes a second Generate produce "
        "different sheets. <strong>Set it</strong> and the same composition comes back, so a "
        "prompt or sampler change can be judged on its own &mdash; composition here is "
        "seed-dominated, and comparing two random seeds tells you nothing about what you "
        "changed.",
        "The candidates within one sheet are spaced off it (seed, +137, +274&hellip;), and a "
        "CFG sweep reuses it at every guidance value."]},
    "refs": {"label": "Base images", "body": [
        "The photographs this model conditions on natively. They are an unordered "
        "<strong>set</strong>, not face-then-outfit: one image carrying both is fine, and with "
        "several the prompt tells the model they are the same character rather than several to "
        "line up side by side.",
        "The model conditions on three. A fourth is refused rather than silently narrowed to "
        "whichever three came first by row id.",
        "Anything uploaded here is KEPT for this album and character, so the next sheet can be "
        "built from it without finding the photographs again."]},
    "negative": {"label": "Negative prompt", "body": [
        "What the render should avoid. It fights what the positive cannot: colour drift, wrong "
        "markings, stray clothing on a nude sheet.",
        "Saved <strong>per album</strong> and versioned. Its terms are this release's failure "
        "modes &mdash; the fur colours that drift, the skin that appears where fur belongs "
        "&mdash; and other music with other artwork wants a different list, so the generic "
        "starting point is only where an album that has saved none begins.",
        "Naming a version is required: the picker lists them by name, and an unnamed one "
        "cannot be told from the rest. What is in the box is exactly what is sent."]},
    "tone": {"label": "Tier wording", "body": [
        "The tone-and-wardrobe wording attached on top of the pinned safety clause for this "
        "tier's sheets.",
        "Editing it here stores it <strong>for this album only</strong>. It does not touch the "
        "tier itself, so no other release's sheets change wording &mdash; the badge beside the "
        "box says which of the two is currently in force.",
        "One line, and text that argues with the pinned clause is refused. Clear the box to go "
        "back to the tier's own wording; <strong>Save wording</strong> keeps an edit without "
        "spending a render on it."]},
    "prompt_versions": {"label": "Saved versions", "body": [
        "Every save is a new numbered version, never an overwrite: prompts are tuned by "
        "comparing renders, and the one worth going back to is usually the one before last.",
        "The count beside each version is how many <strong>renders</strong> it produced, not "
        "how many times it was loaded &mdash; a wording you looked at and rejected is not one "
        "you used.",
        "Version numbers are not reused after a delete. The number is how a render gets "
        "referred to afterwards, so closing the gap would quietly repoint an old note at "
        "different text."]},
}


def anchor_render_settings(form):
    """The render knobs off the form, clamped, in the shape pipeline.gen_anchor
    takes. Values the user did not set are simply absent, so make_anchor's own
    defaults apply -- an unset field must never become a number nobody chose."""
    import build_refs
    # QUALITY, not fast. Every cfg above 1.0 fixed the human-skin drift in the
    # 2026-08-12 sweep and quality mode is what raises it; the form defaults to
    # it, and the server agreeing means a submit that omits the field renders
    # what the form would have sent rather than the other mode.
    mode = (form.get("mode") or DEFAULT_ANCHOR_MODE).strip().lower()
    if mode not in ANCHOR_MODES:
        raise HTTPException(400, f"mode must be one of {', '.join(ANCHOR_MODES)}")
    out = {"mode": mode}

    negative = " ".join((form.get("negative") or "").split())
    if negative:
        if len(negative) > MAX_NEGATIVE:
            raise HTTPException(400, f"the negative prompt is {len(negative)} characters; "
                                      f"keep it under {MAX_NEGATIVE}")
        # free text headed for a model: screened exactly like the positive
        try:
            tiers.check_text(negative, "negative prompt")
            tiers.check_override(negative)
        except ValueError as e:
            raise HTTPException(400, str(e))
        out["negative"] = negative

    ref = (form.get("ref_method") or "").strip()
    if ref:
        if ref not in build_refs.REF_METHODS:
            raise HTTPException(400, f"reference method must be one of "
                                      f"{', '.join(build_refs.REF_METHODS)}")
        out["ref_method"] = ref

    # What the sampler starts from. Sent ALWAYS, not only when it differs from
    # the default: it decides whether the denoise value the form is showing means
    # anything, and a control whose effect depends on another control has to
    # travel with it. docs/TRD-7 T7-8.
    latent = (form.get("latent") or DEFAULT_LATENT).strip().lower()
    if latent not in dict(LATENT_CHOICES):
        raise HTTPException(400, f"the latent must be one of "
                                  f"{', '.join(k for k, _ in LATENT_CHOICES)}")
    out["latent"] = latent

    # Sheet size, as a chosen pair rather than two free numbers: these are the
    # shapes this model was packaged to render and a latent that is not a
    # multiple of 16 is a refusal from ComfyUI, one queue round-trip later.
    # Absent means make_anchor's own default, which is today's behaviour.
    # docs/TRD-7 T7-12.
    size = (form.get("size") or "").strip()
    if size:
        if size not in dict(SIZE_CHOICES):
            raise HTTPException(400, f"the sheet size must be one of "
                                      f"{', '.join(k for k, _ in SIZE_CHOICES)}")
        w, h = size.split("x")
        out["width"], out["height"] = int(w), int(h)

    # The base seed. Blank means make_anchor draws a random one, which is what
    # makes a second click of Generate produce different sheets -- so blank
    # stays the default and is not silently replaced with a number. Set it to
    # re-render the SAME composition after changing a prompt or a sampler knob,
    # which is the only way to see what the change itself did: composition here
    # is seed-dominated, and comparing two random seeds tells you nothing.
    # make_anchor spaces the n candidates off it deterministically (base + k*137).
    for key, lo, hi, cast in (("steps", 1, 60, int), ("cfg", 1.0, 12.0, float),
                              ("denoise", 0.1, 1.0, float),
                              # The Lightning LoRA weight. Left blank the mode
                              # decides, and raising cfg above 1.0 still forces
                              # it to 0 (build_refs.sampler_settings) -- passing
                              # it here is the explicit escape that interlock
                              # deliberately kept, and the studio could not reach
                              # it because ANCHOR_RENDER_FLAGS had no entry for
                              # the flag make_anchor already declared.
                              ("lora_strength", 0.0, 1.0, float),
                              ("seed", 1, 2 ** 31 - 2, int)):
        raw = (form.get(key) or "").strip()
        if raw == "":
            continue
        try:
            v = cast(raw)
        except ValueError:
            raise HTTPException(400, f"{key} must be a number")
        if not (lo <= v <= hi):
            raise HTTPException(400, f"{key} must be between {lo} and {hi}")
        out[key] = v

    for key, allowed in (("sampler_name", build_refs.SAMPLERS),
                         ("scheduler", build_refs.SCHEDULERS)):
        raw = (form.get(key) or "").strip()
        if raw:
            if raw not in allowed:
                raise HTTPException(400, f"{key} must be one of {', '.join(allowed)}")
            out[key] = raw
    return out


def sweep_blockers(form, render, combos):
    """(candidates per point, [every reason this sweep cannot run]).

    Returns (None, []) when the sweep box is off. Split out from
    cfg_sweep_points so the rules exist ONCE and are read twice: the route
    raises the first as a 400, the preflight shows all of them before you press
    anything. Re-deriving them in the preflight -- or in JavaScript -- is how
    the form comes to disagree with the route about what it will accept.
    """
    raw = (form.get("cfg_sweep") or "").strip()
    if not raw or raw == "0":
        return None, []
    try:
        per_point = int(raw)
    except ValueError:
        return None, ["the CFG sweep count must be a number"]
    reasons = []
    if per_point not in CFG_SWEEP_CHOICES:
        reasons.append(f"a CFG sweep renders "
                       f"{', '.join(str(c) for c in CFG_SWEEP_CHOICES)} candidates at each "
                       f"value, not {per_point}")
    if len(combos) != 1:
        reasons.append(f"a CFG sweep renders ONE sheet at every guidance value, and this "
                       f"would render {len(combos)}. Tick a single tier and a single view -- "
                       f"with two, the candidates land in two different grids and neither one "
                       f"is a comparison.")
    if render.get("mode") != "quality":
        reasons.append("a CFG sweep needs quality mode. Above cfg 1.0 the Lightning LoRA is "
                       "dropped, and fast mode's step count is the LoRA's four -- so every "
                       "point above the first would render four undistilled steps, which is "
                       "mush, not a comparison.")
    if "cfg" in render:
        reasons.append("the sweep sets the guidance at every point, so leave Guidance on "
                       "'follow the mode'.")
    if per_point in CFG_SWEEP_CHOICES and per_point * len(CFG_CHOICES) > MAX_SWEEP_SHEETS:
        reasons.append(f"that is {per_point * len(CFG_CHOICES)} sheets; {MAX_SWEEP_SHEETS} is "
                       f"this sweep's ceiling")
    return per_point, reasons


def cfg_sweep_points(form, render, combos):
    """The CFG sweep, or None when the box is off.

    What it is for: day 7's guidance sweep was n=1 per point, so 3.5 sitting
    between two good neighbours is single-sample noise and not a property of
    3.5. This renders every value in the dropdown at n candidates each -- more
    sheets than the 8 one form submit has ever been allowed, because it is one
    queued job PER VALUE rather than one big one, and each is separately
    cancellable.

    Three things are refused rather than quietly worked around, because each
    would produce images that cannot answer the question the sweep is asked:

    - MORE THAN ONE SHEET. A sweep of two views is two experiments interleaved,
      and the grid it lands in is grouped by tier and view, so they would mix.
    - FAST MODE. sampler_settings drops the Lightning LoRA the moment cfg goes
      above 1.0, and fast mode's step count is the LoRA's four. Four steps of
      euler with no distillation is mush at every point above the first, so the
      sweep would compare ten pictures of noise.
    - A CHOSEN CFG. The sweep sets it. A form that let you pick one and then
      ignored it is a control that does nothing.

    The base SEED is drawn once and pinned to every point. Without it each job
    draws its own random base, so the images differ by seed AND by guidance at
    once and nothing in the result is attributable to the knob being swept --
    which is exactly what "same references, same prompt, only guidance
    changing" meant in the sweep this one re-runs.
    """
    per_point, reasons = sweep_blockers(form, render, combos)
    if per_point is None:
        return None
    # The route reports the FIRST, because a 400 carries one message. The
    # preflight shows them all, from this same list -- which is why the rules
    # are a list rather than a run of raises: collecting them was the whole
    # reason the form could only ever tell you about one problem at a time.
    if reasons:
        raise HTTPException(400, reasons[0])
    cfgs = [float(v) for v, _ in CFG_CHOICES]
    sheets = per_point * len(cfgs)
    # One base seed for the whole sweep. make_anchor spaces the n candidates off
    # it deterministically (base + k*137), so point-for-point the SAME n seeds
    # are rendered at every guidance value.
    #
    # A seed set on the form is HONOURED rather than treated as a conflict: it
    # is the same method, and it is what makes a sweep repeatable against a
    # changed prompt. Only an unset one is drawn here.
    return {"cfgs": cfgs, "n": per_point, "sheets": sheets,
            "seed": int(render.get("seed") or random.randrange(1, 2 ** 31 - 1))}


MAX_RUN_HISTORY = 25


def create_anchor_run(album, tier, view, character_id, n, prompt, render, refs, guardrail,
                       chosen=None):
    """Record ONE generation, with everything that was sent, before it is queued.

    Written in the route rather than in the handler so the settings are stored
    even if the render never happens -- a failed job whose settings vanished
    with it is exactly how "what did I have set when that worked?" became
    unanswerable.

    Both dicts are kept. settings_json is RESOLVED, the dict build_refs hands
    the KSampler, so a candidate can be labelled with the cfg it truly used.
    form_json is what was CHOSEN, so "leave it on the mode default" reloads as
    a default rather than as the number it happened to resolve to that day.

    `chosen` exists for the sweep, and it is the difference between the two
    being real. A sweep's per-point render carries a cfg this form never picked
    and a seed the server drew, and storing THAT as form_json meant the newest
    run was the sweep's last point: the form reopened at cfg 9.0 -- past every
    measured degradation point -- with the seed pinned, so the next ordinary
    Generate silently rendered there, a second click no longer produced
    different sheets, and a second sweep was refused for a reason the user did
    not cause. The swept values stay recoverable from settings_json, which is
    what the thumbnail badge reads.
    """
    chosen = render if chosen is None else chosen
    return db.run("""INSERT INTO anchor_runs (scope_value, tier, view, character_id, n,
                                               prompt, negative, guardrail, settings_json,
                                               form_json, refs_json, created)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                  album, tier, view, character_id, n, prompt or "",
                  (render or {}).get("negative", ""), guardrail,
                  json.dumps(resolved_settings(render)), json.dumps(chosen or {}),
                  json.dumps(list(refs or [])), time.time())


def anchor_run(run_id):
    return db.one("SELECT * FROM anchor_runs WHERE id=?", run_id) if run_id else None


def recent_anchor_runs(album, character_id=None, limit=MAX_RUN_HISTORY):
    """This album's generation history, newest first, as rows the form can load
    settings back out of."""
    if not album:
        return []
    return db.q("""SELECT * FROM anchor_runs WHERE scope_value=? AND character_id IS ?
                   ORDER BY id DESC LIMIT ?""", album, character_id, limit)


def run_summary(row):
    """One line naming a run, for the picker. The numbers first, because that is
    what you are choosing between."""
    s = db.jset(row, "settings_json")
    bits = [f"cfg {float(s.get('cfg', 0)):g}", f"{s.get('steps', '?')} steps",
            str(s.get("sampler_name", "")), f"{row['n']}x",
            f"{row['tier']}/{row['view'].replace('_', ' ')}"]
    return " · ".join(b for b in bits if b)


# What resolved_settings hands to build_refs.sampler_settings -- the KSampler's
# own knobs. width/height are NOT here: they size the latent, not the sampler,
# and passing them would have sampler_settings quietly drop them (it only copies
# keys already in FAST/QUALITY) while the badge on a candidate claimed they were
# part of the settings.
SAMPLER_KEYS = ("steps", "cfg", "sampler_name", "scheduler", "denoise", "lora_strength")


def resolved_settings(render):
    """What the KSampler will ACTUALLY be built with, from what the form chose.

    The mode's defaults with the user's overrides on top, resolved by
    build_refs -- the one function make_anchor also resolves through, so the
    preview panel, the stored badge on a candidate and the workflow cannot hold
    three different opinions about the cfg.
    """
    import build_refs
    render = render or {}
    return build_refs.sampler_settings(
        render.get("mode", DEFAULT_ANCHOR_MODE),
        **{k: v for k, v in render.items() if k in SAMPLER_KEYS})


MAX_PROMPT_VERSIONS = 20


def anchor_prompt_versions(album, tier, character_id=None, kind="positive"):
    """Saved versions of one prompt, newest first.

    Reads prompts.py now, not the old anchor_prompts table. The two half-systems
    that preceded it -- a `kind` column bolted on to fit the negative, and the
    component fields with no history at all -- are one table with one numbering
    rule and one CRUD surface.
    """
    return prompts.versions(album, kind, tier, character_id)


def negative_versions(album):
    """Saved NEGATIVE prompts for one album, newest first.

    Per album and not per tier or character, because that is the scope of what
    the text says: it lists this release's failure modes -- the fur colours that
    drift, the skin that appears where fur belongs. Another album, another
    species or another palette wants a different list, and DEFAULT_NEGATIVE is
    only a starting point for the first one.
    """
    return prompts.versions(album, "negative")


def _draft_ref_image(album, character_id=None):
    """A photograph to look at while drafting. Saved base first, then a sheet."""
    refs = anchor_refs(album, character_id)
    if refs:
        return refs[0]["path"]
    row = db.one("""SELECT path FROM anchors WHERE scope_kind='album' AND scope_value=?
                    AND (? IS NULL OR character_id IS ? OR character_id=?)
                    ORDER BY chosen DESC, (view='front') DESC, id DESC""",
                 album, character_id, character_id, character_id)
    return row["path"] if row else None


def _draft_one(album, view, current="", character_id=None):
    if view not in ANCHOR_VIEWS:
        raise HTTPException(400, f"view must be one of {', '.join(ANCHOR_VIEWS)}")
    fields = anchor_profile_fields(album or "", character_id)
    image = _draft_ref_image(album, character_id)
    try:
        text = vision.draft_view_prompt(image, view, current or "", fields)
    except Exception as e:
        raise HTTPException(502, f"could not draft the {view} prompt: {e}") from None
    if not text:
        raise HTTPException(502, "the draft came back empty")
    return screen_prompt_field(text, "prompt", f"{view} draft")


@app.post("/anchors/draft")
async def draft_anchor_prompt(request: Request):
    """Recommend one view's prompt. Lands in the box; nothing is saved."""
    form = await request.form()
    album = (form.get("album") or "").strip()
    view = (form.get("view") or "").strip()
    tier = (form.get("tier") or "").strip()
    cid = form.get("character_id")
    character_id = int(cid) if cid else None
    current = (form.get("current") or "").strip()
    text = _draft_one(album, view, current, character_id)
    return {"text": text, "view": view, "tier": tier}


@app.post("/anchors/draft-related")
async def draft_related_anchor_prompts(request: Request):
    """Recommend every selected view in one clothed or nude family."""
    form = await request.form()
    album = (form.get("album") or "").strip()
    family = (form.get("family") or "").strip()
    if family not in ("clothed", "nude"):
        raise HTTPException(400, "family must be clothed or nude")
    cid = form.get("character_id")
    character_id = int(cid) if cid else None
    views = [v for v in form.getlist("view") if v in ANCHOR_VIEWS
             and view_family(v) == family]
    if not views:
        raise HTTPException(400, "no views in that family are selected")
    prompts_out = {}
    for v in views:
        current = (form.get(anchor_prompt_field(form.get("tier") or "", v))
                   or form.get(f"current_{v}") or "")
        prompts_out[v] = _draft_one(album, v, current, character_id)
    return {"family": family, "prompts": prompts_out}


@app.post("/anchors/prompt")
async def save_anchor_prompt(request: Request):
    """Save the prompt currently in the box as a new VERSION.

    A new row every time rather than an update: a prompt is tuned by comparing
    renders, and the one worth going back to is usually the one before last.
    Screened exactly like the prompt that goes to the model, because it is the
    same text -- saving is not a way around the guardrail.
    """
    form = await request.form()
    album = (form.get("album") or "").strip()
    tier = (form.get("tier") or "").strip()
    text = (form.get("text") or "").strip()
    label = " ".join((form.get("label") or "").split())[:80]
    cid = form.get("character_id")
    cid = int(cid) if cid not in (None, "") else None
    if not album or not tier:
        raise HTTPException(400, "an album and a tier are needed to save a prompt")
    valid_tier_or_400(tier)
    if not text:
        raise HTTPException(400, "nothing to save -- the prompt is empty")
    # A version with no name is a version you cannot find again: the picker
    # lists them BY name, so unnamed ones are indistinguishable from each other
    # and the one worth going back to is unrecoverable.
    if not label:
        raise HTTPException(400, "name this version -- the picker lists saved prompts by "
                                  "name, and an unnamed one cannot be told from the rest")
    if len(text) > MAX_ANCHOR_PROMPT:
        raise HTTPException(400, f"the prompt is {len(text)} characters; keep it under "
                                  f"{MAX_ANCHOR_PROMPT}")
    try:
        tiers.check_text(text, "anchor prompt")
        tiers.check_override(text)
        # ...and whether it belongs at THIS TIER. The two screens above ask
        # "does this mention a minor" and "is this instructing the model about
        # its own rules"; neither asked whether the text was allowed at the tier
        # it is being stored under, so explicit wording saved cleanly under `g`.
        # docs/TRD-4 T4-5/T4-6/T4-7 -- the tier's own allow_nudity decides, so
        # this cannot disagree with what it permits at render time.
        tiers.check_tier_policy(text, tier, "anchor prompt")
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        v = prompts.save(album, "positive", text, label, tier=tier, character_id=cid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"id": v["id"], "label": v["label"], "created": v["created"],
                         "version_number": v["version_number"],
                         "versions": [dict(r) for r in
                                      anchor_prompt_versions(album, tier, cid)]})


@app.post("/anchors/tier-wording")
async def save_tier_wording(request: Request):
    """Store this ALBUM's own wording for a tier, without spending a render.

    It saved only as a side effect of pressing Generate, so the only way to keep
    an edit was to render something. Same validation and the same scope as the
    generate path -- it calls the identical tiers.set_override -- so the button
    and the render cannot disagree about what was stored.

    Empty text REMOVES the override and the album goes back to the tier's own
    wording, which is why this cannot be a plain "save": there has to be a way
    back that is not retyping the tier's text from memory.
    """
    form = await request.form()
    album = (form.get("album") or "").strip()
    tier = (form.get("tier") or "").strip()
    text = " ".join((form.get("text") or "").split())
    if not album:
        raise HTTPException(400, "an album is needed to store its own tier wording")
    valid_tier_or_400(tier)
    # typing the tier's own wording back means "use the tier's", not "store a
    # copy of it" -- the same rule the generate path applies
    if text == tiers.tier_text(tier).strip():
        text = ""
    try:
        if text:
            tiers.check_tier_policy(text, tier, "tier wording")
        stored = tiers.set_override(album, tier, text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"album": album, "tier": tier, "overridden": bool(stored),
                         "text": tiers.tier_text(tier, album)})


@app.post("/anchors/version/delete")
async def delete_prompt_version(request: Request):
    """Delete one saved version.

    Versions accumulated with no way to remove one, so a picker filled up with
    attempts and the one you wanted was somewhere among them. Deleting cannot
    affect a rendered sheet: an anchor carries what it was rendered with in its
    own run row, never a reference to this list.
    """
    form = await request.form()
    try:
        vid = int(form.get("id") or 0)
    except ValueError:
        raise HTTPException(400, "which version?")
    try:
        row = prompts.delete(vid)
    except ValueError as e:
        raise HTTPException(404, str(e))
    kind = row["prompt_type"]
    left = prompts.versions(row["scope_value"], kind, row["tier"], row["character_id"])
    return JSONResponse({"deleted": vid, "kind": kind,
                         "versions": [dict(r) for r in left]})


@app.post("/anchors/version/update")
async def update_prompt_version(request: Request):
    """Correct a version in place -- a typo, or a better name.

    NOT how a new wording is stored: that is Save, which takes the next number.
    This exists because a version whose label says "with the tail fix" and whose
    text has a typo in it is worth repairing rather than superseding.
    """
    form = await request.form()
    try:
        vid = int(form.get("id") or 0)
    except ValueError:
        raise HTTPException(400, "which version?")
    row = prompts.get(vid)
    if not row:
        raise HTTPException(404, "that version no longer exists")
    text = form.get("text")
    if text is not None:
        try:
            tiers.check_text(text, f"{row['prompt_type']} prompt")
            tiers.check_override(text)
        except ValueError as e:
            raise HTTPException(400, str(e))
    try:
        v = prompts.update(vid, text=text, label=form.get("label"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"id": v["id"], "label": v["label"], "text": v["text"],
                         "version_number": v["version_number"], "updated": v["updated"]})


@app.post("/anchors/negative")
async def save_anchor_negative(request: Request):
    """Save the negative prompt as a new version, for THIS ALBUM.

    Its own route rather than a flag on the one above: the two boxes have
    different limits and a different scope, and a negative has no tier. The
    album's newest saved negative is what the form then prefills, so
    DEFAULT_NEGATIVE is the starting point for an album that has never saved
    one and stops being anybody's wording after that.

    Screened like the positive, for the same reason: text on its way to a model.
    """
    form = await request.form()
    album = (form.get("album") or "").strip()
    text = " ".join((form.get("text") or "").split())
    label = " ".join((form.get("label") or "").split())[:80]
    if not album:
        raise HTTPException(400, "an album is needed to save a negative prompt")
    if not text:
        raise HTTPException(400, "nothing to save -- the negative prompt is empty. To render "
                                  "with no negative, clear the box and generate; saving an "
                                  "empty one would make 'no negative' indistinguishable from "
                                  "'not set up yet'")
    if len(text) > MAX_NEGATIVE:
        raise HTTPException(400, f"the negative prompt is {len(text)} characters; keep it "
                                  f"under {MAX_NEGATIVE}")
    if not label:
        raise HTTPException(400, "name this version -- the picker lists saved negatives by "
                                  "name, and an unnamed one cannot be told from the rest")
    try:
        tiers.check_text(text, "negative prompt")
        tiers.check_override(text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        v = prompts.save(album, "negative", text, label)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"id": v["id"], "label": v["label"], "created": v["created"],
                         "version_number": v["version_number"],
                         "versions": [dict(r) for r in negative_versions(album)]})


def anchor_prompt_preview(album, tier, view, character_id=None, typed="",
                           negative="", settings=None):
    """EXACTLY what ComfyUI will be sent for one tier/view, composed by the same
    functions the renderer uses.

    Not a lookalike. The positive runs through make_anchor.prompt_for and then
    guardrail.build_prompt with this tier's real wording -- the identical
    chokepoint build_refs.workflow puts it through -- so a preview that differs
    from the render is impossible by construction rather than by discipline.

    The always-on safety clause is REMOVED FROM THE DISPLAY only. It is
    unconditional, it is the same paragraph on every prompt in the studio, and
    showing it buries the wording that actually steers a render. It is still
    attached to what is sent, and the panel says so.
    """
    import make_anchor
    import guardrail as g
    settings = settings or {}
    pos = (typed or "").strip() or default_anchor_prompt(album, view, character_id)
    tier_text = tiers.compose_guardrail(tier, album)
    try:
        final = g.build_prompt(pos, tier_text, "anchor prompt preview")
        refused = ""
    except Exception as e:
        final, refused = "", str(e)
    # Both forms. build_prompt strips the whole prompt, which eats PINNED's
    # trailing space when the clause lands last -- so matching only the constant
    # leaves the clause on screen, which is precisely what this hides. The same
    # trailing-space trap is recorded in check_integration.py's guardrail check.
    def _hide(text):
        return (text or "").replace(g.PINNED, " ").replace(g.PINNED.strip(), " ")

    shown = " ".join(_hide(final).split())
    tier_only = " ".join(_hide(tier_text).split())
    applies = build_refs_negative_applies(settings)
    return {"tier": tier, "view": view,
            "positive": shown, "refused": refused,
            "tier_wording": tier_only,
            "negative": (negative or "").strip(),
            "negative_applies": applies,
            "pinned_len": len(g.PINNED.strip()),
            "settings": settings}


def build_refs_negative_applies(settings):
    """Whether a negative does anything at these settings -- asked of build_refs,
    which is the module that builds the sampler node, so the answer can never be
    a different opinion from the workflow's."""
    try:
        import build_refs
        return build_refs.negative_applies(settings or {})
    except Exception:
        return False


@app.get("/anchors/group", response_class=HTMLResponse)
def anchor_group(request: Request, scope_value: str, tier: str, view: str,
                 character_id: CharacterId = None):
    """One group's candidates, as the same fragment the page renders.

    So a sheet that finishes can appear WITHOUT a reload -- the batch panel
    watches each job over SSE and pulls this in when one is done. Rendered from
    the shared partial rather than rebuilt in JavaScript: a second copy of this
    markup is a second copy that drifts from the pick and delete forms, and
    those are the controls that make a candidate usable.
    """
    valid_tier_or_400(tier)
    rows = db.q("""SELECT a.*, c.name AS character_name
                   FROM anchors a LEFT JOIN characters c ON c.id = a.character_id
                   WHERE a.scope_kind='album' AND a.scope_value=? AND a.tier=? AND a.view=?
                     AND a.character_id IS ?
                   ORDER BY a.id DESC""", scope_value, tier, view, character_id)
    if not rows:
        return HTMLResponse("")          # nothing yet: the caller leaves the page alone
    g = {"scope_kind": "album", "scope_value": scope_value, "tier": tier, "view": view,
         "character_id": character_id, "character_name": rows[0]["character_name"],
         "candidates": rows, "unpicked": sum(1 for c in rows if not c["chosen"])}
    return templates.TemplateResponse(request, "_anchor_group.html", {"g": g})


# Rough, and honest about being rough: measured 186s a sheet at 28 steps and
# ~20s at the Lightning LoRA's four, on the 5090 this studio renders on.
SECS_PER_SHEET = {"quality": 186.0, "fast": 20.0}


@app.post("/anchors/plan")
async def anchor_preflight(request: Request):
    """What this form would do, and what would stop it -- BEFORE you press it.

    Every refusal in the generate route was a 400 discovered after submitting,
    which is a poor way to learn that a sweep needs one view or that four
    references is one too many. This runs the SAME functions the real submit
    runs -- anchor_plan, anchor_render_settings, cfg_sweep_points -- and reports
    what they say. Re-deriving the rules in JavaScript would have been less
    code and would have drifted from the route the first time either changed.

    Refusals are collected rather than raised: the point is to show ALL of them
    at once, where the route can only ever report the first.
    """
    form = await request.form()
    album = (form.get("album") or "").strip()
    tiers_sel = sorted({t for t in form.getlist("tier") if t})
    # No default: these panels say what WILL render, and generate refuses an
    # empty selection (docs/TRD-4 T4-1). Inventing "front" here would have the
    # preview promise a sheet the render then refuses -- the editor promising
    # what the renderer does not produce, in the one place whose whole job is
    # to agree with it.
    views_sel = sorted({v for v in form.getlist("view") if v})
    blockers, notes = [], []

    if not album:
        blockers.append("Choose an album.")
    elif not db.one("SELECT id FROM playlists WHERE name=? AND kind='playlist'", album):
        blockers.append(f"No album called {album!r} -- create it on Playlists first.")
    if not tiers_sel:
        blockers.append("Tick at least one tier.")
    for t in tiers_sel:
        if not db.one("SELECT id FROM tiers WHERE name=?", t):
            blockers.append(f"No tier called {t!r}.")

    plan = anchor_plan(tiers_sel, views_sel) if tiers_sel else []
    combos = [(p["tier"], v) for p in plan for v in p["views"]]
    skipped = [(p["tier"], s) for p in plan for s in p.get("skipped", [])]
    for tier, view in skipped:
        notes.append(f"{ANCHOR_VIEWS.get(view, view)} is skipped for {tier.upper()} "
                     f"-- that tier permits no nudity.")
    if tiers_sel and not combos:
        blockers.append("Every view you picked is a nude one and no tier you picked permits "
                        "nudity, so there is nothing to render.")

    # Count what the ROUTE counts: ticked gallery images PLUS anything in the
    # upload input. Counting only the ticks reported "no blockers, 4 sheets,
    # about 12 min" for the two commonest refusals there are -- four references,
    # and none at all.
    uploads = len(form_files(form, "images"))
    refs = len(form.getlist("ref_id")) + uploads
    if uploads > MAX_ANCHOR_UPLOADS:
        blockers.append(f"That is {uploads} images at once; {MAX_ANCHOR_UPLOADS} is the most "
                        f"this form accepts.")
    if refs > pipeline.MAX_ANCHOR_REFS:
        blockers.append(f"{refs} reference images selected; the model conditions on "
                        f"{pipeline.MAX_ANCHOR_REFS}. Untick some.")
    if not refs:
        blockers.append("Pick at least one saved reference image, or upload one.")

    # The per-tier-and-view prompt boxes, through the SAME three checks the route
    # runs. Collected rather than raised, so a screening refusal and a length
    # refusal both show at once instead of one revealing the next.
    for t, v in combos:
        text = (form.get(anchor_prompt_field(t, v)) or "").strip()
        if not text:
            continue
        if len(text) > MAX_ANCHOR_PROMPT:
            blockers.append(f"The {t.upper()} {ANCHOR_VIEWS.get(v, v)} prompt is {len(text)} "
                            f"characters; keep it under {MAX_ANCHOR_PROMPT}.")
        try:
            tiers.check_text(text, f"{t.upper()} anchor prompt")
            tiers.check_override(text)
        except ValueError as e:
            blockers.append(str(e))

    settings, sweep, settings_ok = {}, None, True
    try:
        render = anchor_render_settings(form)
        settings = resolved_settings(render)
    except HTTPException as e:
        blockers.append(str(e.detail))
        render, settings_ok = {}, False
    # Every sweep reason at once, from the same list the route raises from --
    # but skipped when the settings themselves would not parse. render is {}
    # there, so sweep_blockers would report "a CFG sweep needs quality mode" on
    # top of the real error: a blocker the user did not cause.
    per_point, sweep_reasons = (sweep_blockers(form, render, combos) if settings_ok
                                else (None, []))
    blockers += sweep_reasons
    if per_point and not sweep_reasons:
        sweep = {"cfgs": [float(v) for v, _ in CFG_CHOICES], "n": per_point,
                 "sheets": per_point * len(CFG_CHOICES)}

    try:
        n = max(1, min(int(form.get("n") or 4), 8))
    except ValueError:
        n = 4
    sheets = sweep["sheets"] if sweep else len(combos) * n
    jobs_queued = len(sweep["cfgs"]) if sweep else len(combos)
    secs = sheets * SECS_PER_SHEET.get(render.get("mode", "quality"), 186.0)

    if settings and not build_refs_negative_applies(settings) and (form.get("negative") or "").strip():
        notes.append("The negative prompt will be DROPPED: it needs CFG above 1.0, and "
                     "ComfyUI skips the negative pass entirely below that.")
    # ...and only when the latent it is true OF is the one selected. This note
    # was unconditional, which was correct while latent_mode was pinned to
    # "empty" and became a false warning the moment it was not: the same
    # sentence that warned about wasted renders would have talked the operator
    # out of the refine pass the control now does. docs/TRD-7 T7-8.
    if settings.get("denoise", 1.0) < 1.0 and render.get("latent", DEFAULT_LATENT) == "empty":
        notes.append(f"Denoise {settings['denoise']:g} from an empty latent returns noise -- "
                     f"there is nothing to preserve. Set the sampler to start from the first "
                     f"reference and it refines that instead.")
    return JSONResponse({"sheets": sheets, "jobs": jobs_queued, "seconds": round(secs),
                         "sweep": bool(sweep), "blockers": blockers, "notes": notes,
                         "settings": settings})


@app.post("/anchors/preview")
async def anchor_preview(request: Request):
    """The assembled prompts for every tier/view the form currently selects."""
    form = await request.form()
    album = (form.get("album") or "").strip()
    cid = form.get("character_id")
    cid = int(cid) if cid not in (None, "") else None
    tiers_sel = sorted({t for t in form.getlist("tier") if t})
    # No default: these panels say what WILL render, and generate refuses an
    # empty selection (docs/TRD-4 T4-1). Inventing "front" here would have the
    # preview promise a sheet the render then refuses -- the editor promising
    # what the renderer does not produce, in the one place whose whole job is
    # to agree with it.
    views_sel = sorted({v for v in form.getlist("view") if v})
    chosen = anchor_render_settings(form)
    settings = resolved_settings(chosen)
    form_pose = (form.get("pose") or "").strip()
    out = []
    for p in anchor_plan(tiers_sel, views_sel):
        for v in p["views"]:
            # Each box against ITS OWN view's default, exactly as the submit does
            # it -- this panel exists to agree with the renderer, so it reads the
            # same field and makes the same comparison. docs/TRD-7 T7-19.
            typed = (form.get(anchor_prompt_field(p["tier"], v)) or "").strip()
            composed = (default_anchor_prompt(album, v, cid, pose=form_pose or None)
                        or "").strip()
            if typed and typed == composed:
                typed = ""      # untouched: this view composes its own, as at render
            if not typed and form_pose:
                typed = composed
            out.append(anchor_prompt_preview(album, p["tier"], v, cid, typed,
                                              form.get("negative") or "", settings))
    return JSONResponse({"sheets": out, "settings": settings,
                         "negative_applies": build_refs_negative_applies(settings)})


@app.post("/anchors")
async def start_anchor(request: Request, album: str = Form(...), tier: List[str] = Form([]),
                        view: List[str] = Form([]),
                        n: int = Form(4), character_id: CharacterId = Form(None)):
    """Generate anchor candidates for one album, across any number of tiers and
    views, from an unordered set of reference images.

    An ALBUM IS A PLAYLIST -- the same record, matched by the name songs already
    carry -- so there is no scope to choose. There was a scope_kind select and a
    free-text scope_value here, and typing an album name that did not match one
    produced anchors nothing could ever find.

    Tiers and views are both multi-select because the same references usually
    want rendering several ways at once: front and back, clothed and nude, at
    every tier the album ships. One job per combination, so each is separately
    cancellable and a failure in one does not lose the rest.

    Each tier carries its OWN prompt, arriving as prompt_<tier> -- the field
    names are not known until the tiers are, so they are read off the raw form
    rather than declared. A nude view asked of a tier that forbids nudity is
    skipped for that tier and rendered for the ones that permit it; refusing the
    whole request meant a single restrictive tier in the selection blocked work
    that was perfectly legal for the others.
    """
    album = (album or "").strip()
    if not album:
        raise HTTPException(400, "choose an album")
    if not db.one("SELECT id FROM playlists WHERE name=? AND kind='playlist'", album):
        raise HTTPException(400, f"no album called {album!r} -- create it on /playlists first")

    selected_tiers = sorted(set(t for t in tier if t))
    # NO SILENT DEFAULT. This was `or ["front"]`, so submitting with every view
    # unticked rendered a front clothed sheet nobody asked for -- and the two
    # controls then behaved differently, since an empty TIER has always been
    # refused. docs/TRD-4 T4-1, T4-3, T4-4: each control names itself, because a
    # form with two empty multi-selects and one generic error is a form you fix
    # twice.
    selected_views = sorted(set(v for v in view if v))
    if not selected_tiers:
        raise HTTPException(400, "select at least one tier")
    if not selected_views:
        raise HTTPException(400, "select at least one view")
    for t in selected_tiers:
        valid_tier_or_400(t)
    for v in selected_views:
        if v not in ANCHOR_VIEWS:
            raise HTTPException(400, f"view must be one of {', '.join(ANCHOR_VIEWS)}")

    # Same plan the form displayed, from the same function -- what it said would
    # render is what renders.
    plan = anchor_plan(selected_tiers, selected_views)
    combos = [(p["tier"], v) for p in plan for v in p["views"]]
    if not combos:
        raise HTTPException(400, "every view you picked is a nude one and no tier you picked "
                                  "permits nudity, so there is nothing to render. Tick a clothed "
                                  "view, or turn nudity on for a tier under Tiers.")

    # One prompt per tier AND VIEW, named prompt_<tier>__<view>. Every one is
    # screened: a box on this form is a free-text field like any other.
    form = await request.form()
    # Each box is compared against the default composed FOR ITS OWN VIEW, so an
    # untouched box can be told apart from a deliberate edit. There used to be
    # one box per tier and one comparison against the first selected view's
    # default, which is what made an edit apply to every view of its tier --
    # overriding the framing sentence and the nude wardrobe swap on every sheet
    # but the one the operator was looking at. docs/TRD-7 T7-19.
    form_pose = (form.get("pose") or "").strip()
    if form_pose:
        if len(form_pose) > MAX_PROMPT_FIELD:
            raise HTTPException(400, f"pose is {len(form_pose)} characters; keep it under "
                                      f"{MAX_PROMPT_FIELD}")
        try:
            tiers.check_text(form_pose, "pose")
            tiers.check_override(form_pose)
        except ValueError as e:
            raise HTTPException(400, str(e))
    view_prompts = {}
    for t, v in combos:
        text = (form.get(anchor_prompt_field(t, v)) or "").strip()
        if len(text) > MAX_ANCHOR_PROMPT:
            raise HTTPException(400, f"the {t.upper()} {ANCHOR_VIEWS.get(v, v)} prompt is "
                                      f"{len(text)} characters; keep it under "
                                      f"{MAX_ANCHOR_PROMPT}")
        try:
            tiers.check_text(text, f"{t.upper()} anchor prompt")
            tiers.check_override(text)
        except ValueError as e:
            raise HTTPException(400, str(e))
        composed = (default_anchor_prompt(album, v, character_id, pose=form_pose or None)
                    or "").strip()
        if text and text == composed:
            # untouched: send it as EMPTY so make_anchor composes this view's own
            text = ""
        # a typed pose is not in the profile the job will load, so an empty
        # prompt would drop it. Ship this view's own composition instead.
        if not text and form_pose:
            text = composed
        view_prompts[(t, v)] = text

    # TIER WORDING, arriving as tone_<tier> for the same reason the prompts do.
    # Stored BEFORE anything is queued, so the wording the box showed is the
    # wording compose_guardrail() then hands the renderer -- an edit that
    # rendered but did not persist would put the form and the next render into
    # disagreement, which is this codebase's recurring defect.
    #
    # Scoped to this ALBUM. Typing in this box cannot re-word another release's
    # sheets, and typing the tier's own wording back removes the override
    # rather than storing a duplicate of it.
    for t in selected_tiers:
        if f"tone_{t}" not in form:
            continue                        # no box on the page: leave the wording alone
        typed_tone = " ".join((form.get(f"tone_{t}") or "").split())
        if typed_tone == tiers.tier_text(t).strip():
            typed_tone = ""
        if typed_tone != tiers.override_text(album, t):
            try:
                tiers.set_override(album, t, typed_tone)
            except ValueError as e:
                raise HTTPException(400, str(e))

    if character_id is not None:
        # a character belongs to the album it was defined on; anchoring one
        # elsewhere would silently make an unreachable anchor
        char = get_character_or_404(character_id)
        if char["scope_value"] != album:
            raise HTTPException(400, f"character {char['name']!r} belongs to album "
                                      f"{char['scope_value']!r}, not to {album!r}")

    # References now come from two places: images already saved for this album
    # and character (ticked in the gallery) and anything uploaded in this same
    # submit, which is saved too rather than used once and forgotten.
    uploads = form_files(form, "images")
    if len(uploads) > MAX_ANCHOR_UPLOADS:
        raise HTTPException(400, f"that is {len(uploads)} reference images; {MAX_ANCHOR_UPLOADS} "
                                  f"is the most this form accepts")
    picked = []
    for rid in form.getlist("ref_id"):
        row = db.one("SELECT * FROM assets WHERE id=? AND kind='anchor_ref'", int(rid))
        if not row:
            raise HTTPException(400, "a reference image you picked no longer exists")
        meta = db.jset(row)
        if meta.get("scope_value") != album or (meta.get("character_id") or None) != (character_id or None):
            raise HTTPException(400, "a reference image you picked belongs to another album "
                                      "or character")
        picked.append(row["path"])
    picked += [a["path"] for a in await _save_anchor_refs(album, character_id, uploads)]

    if not picked:
        raise HTTPException(400, "pick at least one saved reference image, or upload one")
    # The model conditions on MAX_ANCHOR_REFS and pipeline.gen_anchor silently
    # drops the rest. That was tolerable when the form was "upload some, the
    # first three win" and invisible; with a saved gallery it would mean an
    # arbitrary three of eight, chosen by row id. Refuse instead of guessing.
    if len(picked) > pipeline.MAX_ANCHOR_REFS:
        raise HTTPException(400, f"{len(picked)} reference images selected; the model conditions "
                                  f"on {pipeline.MAX_ANCHOR_REFS}. Untick some.")
    paths = picked

    render = anchor_render_settings(form)
    n = max(1, min(int(n), 8))
    sweep = cfg_sweep_points(form, render, combos)
    # An UNEDITED prompt is sent as empty so make_anchor composes it PER VIEW.
    # That comparison happened above, per box, against its own view's default.
    #
    # make_anchor's `--prompt` is `args.prompt.strip() or prompt_for(view, ...)`,
    # so an explicit prompt REPLACES the per-view composition entirely -- and the
    # form always prefills the box, so a prompt was always sent. The consequences
    # were exactly what a user reported after rendering twelve sheets: every
    # "back" sheet carried the FRONT VIEW sentence and looked like the front, and
    # no nude sheet was nude, because prompt_for's NUDE_WARDROBE swap ("the
    # album's wardrobe wording is the one thing that must NOT be used") never
    # ran. Twelve tier/view combinations received one identical prompt.
    #
    # An EDITED prompt is still honoured verbatim, and now reaches ONLY the view
    # whose box it was typed into: every box is composed for its own view, so the
    # sheet an edit governs is the sheet the operator was looking at.
    #
    # A CFG SWEEP replaces the per-combination loop with a per-GUIDANCE one: the
    # single tier and view, rendered once at every cfg value, n candidates each.
    # Everything else is held fixed, including the base SEED -- see
    # cfg_sweep_points for why that is the whole point of it.
    queued = []
    plan_points = ([(t, v, None) for t, v in combos] if not sweep else
                   [(combos[0][0], combos[0][1], c) for c in sweep["cfgs"]])
    for t, v, cfg in plan_points:
        text = view_prompts[(t, v)]
        this_render = render if cfg is None else dict(render, cfg=cfg, seed=sweep["seed"])
        this_n = n if cfg is None else sweep["n"]
        # The run row goes in FIRST, so what was sent survives a job that fails.
        run_id = create_anchor_run(album, t, v, character_id, this_n, text, this_render,
                                    paths, tiers.compose_guardrail(t, album),
                                    # what the FORM chose, not the sweep's point
                                    chosen=render)
        jid = jobs.enqueue("anchor", {"scope_kind": "album", "scope_value": album, "tier": t,
                                       "view": v, "images": paths, "n": this_n,
                                       "character_id": character_id, "prompt": text,
                                       "render": this_render, "run_id": run_id})
        queued.append({"id": jid, "tier": t, "view": v, "prompt": text, "cfg": cfg,
                       "run_id": run_id})

    # Count the saved versions this render was actually built from. Sent by the
    # form as hidden fields the pickers set, and cleared the moment the box is
    # edited away from the loaded text -- so usage_count counts RENDERS from a
    # version, not the times one was loaded and then changed or rejected.
    prompts.mark_used(form.getlist("used_version"))

    # The async caller paints from THIS, never from what it typed -- and this is
    # the whole answer to "I clicked generate and I don't think it generated any
    # anchors": it names every sheet that was accepted, with the job to watch.
    # It echoes the tiers, the views and each sheet's prompt because those are
    # exactly the fields an async handler has historically dropped; a response
    # that carries them can be asserted on.
    if wants_json(request):
        return JSONResponse({"queued": len(queued), "jobs": queued, "album": album,
                             "tiers": selected_tiers, "views": selected_views,
                             "n": sweep["n"] if sweep else n,
                             "refs": len(paths), "render": render,
                             # the sweep's own numbers, so a caller can assert
                             # that every point got the SAME seed rather than
                             # take it on trust
                             "sweep": ({"cfgs": sweep["cfgs"], "seed": sweep["seed"],
                                        "sheets": sweep["sheets"]} if sweep else None)})
    return RedirectResponse(f"/anchors?scope_value={quote(album)}", status_code=303)


# ------------------------------------------------------------- characters --

# Every prose field a cast member owns. The last two arrived late: without them
# a cast member's nude sheet used the PROTAGONIST's nude wording and anatomy
# clause, because anchor_profile_fields only overrode the first three.
CHARACTER_FIELDS = ("role", "identity", "wardrobe", "body", "nude_wardrobe", "anatomy")

# What may be copied from one cast member to another. IDENTITY is deliberately
# absent: a band shares a uniform, not a face, and copying identity would give
# two characters one appearance -- the exact thing a cast exists to keep apart.
# Role is absent because it is a label for you, not prompt text.
COPYABLE_CHARACTER_FIELDS = ("wardrobe", "body", "nude_wardrobe", "anatomy")

# Was MAX_CHARACTER_FIELD = 1000, and the album profile it now also covers holds
# a 961-character wardrobe today -- 39 from being refused by a bound it had never
# been subject to. The point of the cap is to refuse absurd input, not to shape
# prose, so it sits well clear of what the studio actually stores.
MAX_PROMPT_FIELD = 2000


def screen_prompt_field(value, field, where):
    """One guard for prose a form is about to put into an image prompt.

    Shared rather than copied per route. `check_character_fields` used to say the
    cast was screened "exactly as the album profile's own fields would be if they
    were free text from a form" -- and the album profile's fields ARE free text
    from a form, and had no screening at all: no check_text, no check_override,
    no bound, while every sibling path had all three. One guard, both callers, so
    the next field added to either table cannot land unscreened.
    """
    if len(value) > MAX_PROMPT_FIELD:
        raise HTTPException(400, f"{field} is {len(value)} characters; keep it under "
                                 f"{MAX_PROMPT_FIELD}")
    try:
        tiers.check_text(value, f"{where} {field}")
        tiers.check_override(value)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return value


def check_character_fields(form):
    """Character prose lands in image prompts, so it is screened."""
    out = {}
    for field in CHARACTER_FIELDS:
        if field not in form:
            continue
        value = " ".join((form.get(field) or "").split())   # single line: prompt fragment
        out[field] = screen_prompt_field(value, field, "character")
    return out


@app.post("/playlists/{id}/characters")
async def add_character(id: int, request: Request):
    """Add a named character to this album's cast."""
    p = get_playlist_or_404(id)
    form = await request.form()
    name = " ".join((form.get("name") or "").split())
    if not name:
        raise HTTPException(400, "a character needs a name")
    if len(name) > 60:
        raise HTTPException(400, "character name is too long (max 60)")
    try:
        tiers.check_text(name, "character name")
    except ValueError as e:
        raise HTTPException(400, str(e))
    fields = check_character_fields(form)
    # Built from CHARACTER_FIELDS rather than naming the columns here. This
    # INSERT listed six of them by hand, so adding nude_wardrobe and anatomy to
    # the tuple reached the FORM, the validator and the renderer -- and not the
    # row: a new cast member's nude wording was accepted, screened, and silently
    # dropped on the way to the database. The same class of defect as the one
    # ANCHOR_PROFILE_FIELDS exists to prevent, one table over.
    cols = ["scope_value", "name"] + list(CHARACTER_FIELDS) + ["created"]
    values = [p["name"], name] + [fields.get(f, "") for f in CHARACTER_FIELDS] + [time.time()]
    try:
        db.run(f"INSERT INTO characters ({', '.join(cols)}) "
               f"VALUES ({', '.join('?' * len(cols))})", *values)
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"'{p['name']}' already has a character called {name!r}")
    return RedirectResponse("/playlists", status_code=303)


@app.post("/characters/{cid}/save")
async def save_character(cid: int, request: Request):
    get_character_or_404(cid)
    fields = check_character_fields(await request.form())
    for field, value in fields.items():
        db.run(f"UPDATE characters SET {field}=? WHERE id=?", value, cid)
    return RedirectResponse("/playlists", status_code=303)


@app.post("/characters/{cid}/copy-from")
async def copy_character_fields(cid: int, request: Request):
    """Copy chosen prose fields from another character on the same album.

    For a cast that shares something by design -- a band in matching uniforms, a
    team in the same kit -- where the wardrobe wording should be identical and
    the identity must NOT be. So it is per FIELD, not a whole-record clone:
    copying identity too would give two characters one face, which is the defect
    a cast exists to avoid.

    Fields are COPIED, not linked. Editing the source afterwards does not change
    the copy, and that is deliberate: a shared uniform still gets described per
    character once someone's sleeve is torn, and a link would have to be broken
    at exactly the moment it mattered.

    The source must be on the same ALBUM. Characters are scoped by album name
    everywhere else in this studio, and reaching across would let one release's
    wording arrive somewhere nothing on the page mentions it.
    """
    target = get_character_or_404(cid)
    form = await request.form()
    try:
        source = get_character_or_404(int(form.get("source_id") or 0))
    except ValueError:
        raise HTTPException(400, "choose a character to copy from")
    if source["id"] == target["id"]:
        raise HTTPException(400, "that is the same character")
    if source["scope_value"] != target["scope_value"]:
        raise HTTPException(400, f"{source['name']!r} belongs to another album")

    wanted = [f for f in form.getlist("field") if f in COPYABLE_CHARACTER_FIELDS]
    if not wanted:
        raise HTTPException(400, "tick at least one field to copy")
    copied = {}
    for field in wanted:
        value = source[field] if field in source.keys() else None
        # An empty source field means "inherit the album's", and copying that
        # emptiness over a target that has its own wording would silently delete
        # the target's. Refused for the whole request rather than skipped, so
        # the count reported back is never a lie about what happened.
        if not value:
            raise HTTPException(400, f"{source['name']!r} has no {field.replace('_', ' ')} of "
                                      f"its own -- it inherits the album's, so there is nothing "
                                      f"to copy")
        db.run(f"UPDATE characters SET {field}=? WHERE id=?", value, cid)
        copied[field] = value
    if wants_json(request):
        return JSONResponse({"copied": sorted(copied), "from": source["name"],
                             "to": target["name"]})
    return RedirectResponse("/playlists", status_code=303)


@app.post("/characters/{cid}/delete")
def delete_character(cid: int):
    """Remove a character and their anchor ROWS. The image FILES are left on
    disk -- they cost GPU time to make and are recoverable by hand.

    The rows have to go, not just be unchosen: sqlite hands out the next rowid
    as max+1, so deleting the highest-numbered character and adding another
    reuses that id, and anchors still pointing at it would silently become the
    new character's."""
    get_character_or_404(cid)
    db.run("DELETE FROM anchors WHERE character_id=?", cid)
    db.run("DELETE FROM characters WHERE id=?", cid)
    return RedirectResponse("/playlists", status_code=303)


# The prompt is COMPOSED from the album's identity, wardrobe and body wording
# plus a per-view framing sentence, and a detailed album profile runs past 2000
# on its own -- the XXX default measured 2157, so the form shipped a prompt it
# would then refuse to accept. This is a sanity bound, not a safety one: what
# makes a prompt safe is tiers.check_text/check_override, which run regardless.
MAX_ANCHOR_PROMPT = 4000


def _tier_prompt_panel(tier, album, chosen_views, typed_prompts, character_id,
                       pose, tones):
    """One tab: this tier's wording plus one prompt row per selected view."""
    views = []
    for v in chosen_views:
        composed = default_anchor_prompt(album, v, character_id, pose=pose or None)
        views.append({
            "key": v, "label": ANCHOR_VIEWS.get(v, v),
            "position": view_position_label(v),
            "field": anchor_prompt_field(tier, v),
            "nude": _make_anchor().is_nude_view(v),
            "family": view_family(v),
            "prompt": typed_prompts.get(f"{tier}__{v}", composed),
            "composed": composed,
        })
    clothed = [vb for vb in views if not vb["nude"]]
    nude = [vb for vb in views if vb["nude"]]
    return {
        "name": tier,
        "text": (tones or {}).get(tier, tier_tone(tier, album)),
        "tier_default": tiers.tier_text(tier).strip(),
        "overridden": bool(tiers.override_text(album, tier)),
        "views": views,
        "clothed_views": clothed,
        "nude_views": nude,
        "versions": anchor_prompt_versions(album, tier, character_id),
    }


def default_anchor_prompt(scope_value, view, character_id=None, pose=None):
    """The prompt make_anchor would compose, shown so it can be edited.

    Built by the REAL composer (make_anchor.prompt_for) from the album's own
    identity/wardrobe/body, so what the box shows is what would otherwise have
    been sent -- not a lookalike that drifts from it.
    """
    import make_anchor
    # The SAME fields h_anchor ships to the renderer, merged by the same
    # function -- including the per-view sentences, the nude swap and the
    # anatomy clause. Composing the preview from a narrower set is how a preview
    # comes to describe a render nobody will get.
    fields = anchor_profile_fields(scope_value or "", character_id)
    if pose:
        fields["pose"] = pose.strip()
    return make_anchor.prompt_for(view, make_anchor.anchor_from(fields))


def anchor_plan(selected_tiers, selected_views):
    """What each ticked tier will actually render: [{tier, views, skipped}].

    A nude view against a tier that forbids nudity is SKIPPED for that tier. It
    is not withdrawn from the form and it does not refuse the request -- the
    views used to be gated across the whole selection, so one restrictive tier
    made nude sheets unreachable for the permissive ones ticked beside it, and
    the greyed-out explanation named a tier that was no longer ticked.

    One place decides it, shared by the form's count and the POST that enqueues.
    """
    plan = []
    for t in selected_tiers:
        ok = tiers.allows_nudity(t)
        keep = [v for v in selected_views if ok or v not in NUDE_VIEWS]
        plan.append({"tier": t, "views": keep,
                     "skipped": [v for v in selected_views if v not in keep]})
    return plan


def anchor_form_ctx(album="", selected_tiers=(), selected_views=(), character_id=None,
                    typed_prompts=None, negative=None, tones=None, latent=None, pose=None):
    """The generate form for one album, across any number of tiers and views.

    Every view is offered against every tier; see anchor_plan() for what gets
    dropped and why. Each ticked tier gets its own TAB carrying that tier's
    wording and its own prompt: one shared textarea sitting under one tier's
    rules read as though it applied only to that tier, and it was in fact the
    only prompt sent for all of them.

    No silent default: an empty tier or view selection stays empty (docs/TRD-4
    T4-3). The form used to pre-tick G (first alphabetically) or the album's
    last-used tier, and front when no view was ticked -- which is how a
    restrictive rating nobody chose became the opening state.

    typed_prompts: {tier: text} to redisplay after a rejected submit, so an edit is
    not thrown away by the error.
    """
    all_t = tiers.all_tiers()
    albums = [p["name"] for p in
              db.q("SELECT name FROM playlists WHERE kind='playlist' ORDER BY name")]
    album = album if album in albums else (albums[0] if albums else "")
    selected = [t for t in selected_tiers if any(x["name"] == t for x in all_t)]
    # Every view is always offered, against every tier. Nothing here is disabled
    # or hidden: a view a tier cannot use is simply not rendered for that tier,
    # and the plan below says so in words.
    views = [{"key": k, "label": v, "short": v.split(",")[0], "nude": k in NUDE_VIEWS}
             for k, v in ANCHOR_VIEWS.items()]
    chosen_views = [v["key"] for v in views if v["key"] in set(selected_views)]
    plan = anchor_plan(selected, chosen_views)
    typed_prompts = typed_prompts or {}
    # The negative is the ALBUM's, and DEFAULT_NEGATIVE is only where an album
    # that has never saved one starts. Its terms are failure modes of THIS
    # release's art -- fur colour, a tail, skin where fur belongs -- and other
    # music with other artwork wants a different list, which is why saving one
    # is per album and why the constant is a starting point rather than a rule.
    saved_negatives = negative_versions(album)
    if negative is None:
        negative = saved_negatives[0]["text"] if saved_negatives else DEFAULT_NEGATIVE
    # LAST USED settings, so the form opens where you left it rather than at the
    # defaults every time. form_json, not settings_json: what was chosen, so a
    # control left on "follow the mode" comes back on "follow the mode" instead
    # of pinned to whatever number it resolved to that day.
    runs = recent_anchor_runs(album, character_id)
    last = db.jset(runs[0], "form_json") if runs else {}
    # First visit only. A saved run that left CFG/steps on "follow the mode"
    # must reopen that way (form_json, not the resolved numbers). Measured
    # stack for a first visit: CFG 2.0 / 50, not quality's 4.5 / 28.
    if not runs:
        last = {**last, "cfg": 2.0, "steps": 50}
    # The latent the denoise labels are worded for: what this swap carries, else
    # what was last generated with, else empty. Carried like the negative and the
    # tier wordings, because a control that resets itself on every swap is a
    # control you cannot set.
    last_latent = latent or last.get("latent") or DEFAULT_LATENT
    if last_latent not in dict(LATENT_CHOICES):
        last_latent = DEFAULT_LATENT
    clothed = [v for v in views if not v["nude"]]
    nude = [v for v in views if v["nude"]]
    picked = set(chosen_views)
    nude_by_base = {view_base(v["key"]): v for v in nude}
    used_bases = set()
    view_pairs = []
    for v in clothed:
        view_pairs.append({"short": view_position_label(v["key"]), "clothed": v,
                           "nude": nude_by_base.get(view_base(v["key"]))})
        used_bases.add(view_base(v["key"]))
    for v in nude:
        if view_base(v["key"]) not in used_bases:
            view_pairs.append({"short": view_position_label(v["key"]),
                               "clothed": None, "nude": v})
    return {
        "tiers": all_t, "albums": albums, "form_album": album,
        "selected_tiers": selected, "views": views, "selected_views": chosen_views,
        "clothed_views": clothed, "nude_views": nude, "view_pairs": view_pairs,
        "all_clothed": bool(clothed) and all(v["key"] in picked for v in clothed),
        "all_nude": bool(nude) and all(v["key"] in picked for v in nude),
        "all_views": bool(views) and all(v["key"] in picked for v in views),
        "plan": plan, "sheet_count": sum(len(p["views"]) for p in plan),
        "view_labels": ANCHOR_VIEWS,
        "pinned": tiers.PINNED.strip(),
        # One panel per ticked tier: the wording that applies, its own prompt,
        # and whether that wording is this ALBUM's or the tier's. `text` is what
        # the box shows and `tier_default` is what "use the tier's wording"
        # would put back -- both are needed, because a panel that showed only
        # the effective text could not tell you it was an override.
        "tier_panels": [_tier_prompt_panel(t, album, chosen_views, typed_prompts,
                                           character_id, pose, tones)
                        for t in selected],
        # the album+character's saved base images, so a sheet can be generated
        # from photographs already here instead of finding them again
        "saved_refs": anchor_refs(album, character_id),
        "max_anchor_prompt": MAX_ANCHOR_PROMPT, "max_uploads": MAX_ANCHOR_UPLOADS,
        "max_refs": pipeline.MAX_ANCHOR_REFS,
        # the sampler vocabulary the RENDERER accepts, read from the module that
        # builds the node -- offering a name ComfyUI would reject is the same
        # class of lie as a control that does nothing
        "samplers": _build_refs().SAMPLERS, "schedulers": _build_refs().SCHEDULERS,
        "ref_methods": _build_refs().REF_METHODS,
        "max_negative": MAX_NEGATIVE,
        "negative": negative, "negative_versions": saved_negatives,
        "cfg_choices": CFG_CHOICES, "default_negative": DEFAULT_NEGATIVE,
        # Worded for the latent the form is currently set to, and the form
        # re-fetches itself when that changes -- the labels are the only thing
        # saying whether a denoise value does anything at all.
        "steps_choices": STEPS_CHOICES,
        "latent_choices": LATENT_CHOICES, "latent": last_latent,
        "size_choices": SIZE_CHOICES, "lora_choices": LORA_CHOICES,
        "denoise_choices": denoise_choices(last_latent),
        # (candidates per point, total sheets) -- the cost is computed here so
        # the form states it rather than leaving it to be discovered
        "sweep_choices": [(c, c * len(CFG_CHOICES)) for c in CFG_SWEEP_CHOICES],
        "sweep_values": [v for v, _ in CFG_CHOICES],
        "max_tier_guardrail": tiers.MAX_TIER_GUARDRAIL,
        # what the "?" beside each technical control says
        "help_text": ANCHOR_HELP,
        # the last generation's chosen settings, and the history to load any
        # earlier one back out of
        "last": last,
        "last_n": (runs[0]["n"] if runs else 4),
        "runs": [{"id": r["id"], "summary": run_summary(r), "created": r["created"],
                  "form": json.dumps(db.jset(r, "form_json")), "n": r["n"]}
                 for r in runs],
        "character_id": character_id,
        "characters": (album_cast(album) if album
                       else db.q("SELECT * FROM characters ORDER BY scope_value, name")),
        "pose": pose or "",
    }


@app.get("/anchors/form", response_class=HTMLResponse)
def anchor_form(request: Request, album: str = "", tier: List[str] = Query([]),
                 view: List[str] = Query([]), character_id: CharacterId = None):
    """The generate form, re-rendered when the album, tiers or views change.

    Its own route because the tabs below depend on which tiers are ticked, and
    the wording shown in each has to be the one that will actually apply.

    The prompt textareas come back in the query string (hx-include sends the
    whole form), so ticking a second tier does not discard a prompt already
    written for the first.
    """
    qp = request.query_params
    # Whether this swap is still the SAME subject. A prompt describes one
    # character on one album, so carrying it across a change of either renders
    # the wrong person: the box kept character A's wording, the submit compared
    # it against B's freshly composed default, found them different, called it a
    # hand edit and sent A's identity and wardrobe verbatim -- stored as B's
    # anchor, and with the nude swap skipped. Changing only the VIEW is not a
    # change of subject, so an edit still survives ticking a view.
    same_subject = qp.get("composed_for") == f"{album}|{character_id or ''}"
    typed_prompts = ({k[len("prompt_"):]: v for k, v in qp.items()
                if k.startswith("prompt_") and not k.startswith("prompt_default_")}
               if same_subject else {})
    # Drop a box that was never touched, so it RE-COMPOSES for whatever is now
    # selected. It used to be carried forward unconditionally, which meant the
    # box kept the text composed for the previous view/album/character while the
    # submit compared it against the default for the new one -- never equal, so
    # an untouched box was classified as a hand edit and sent verbatim to every
    # sheet. That is how ticking nude-only produced clothed FRONT VIEW sheets:
    # make_anchor's BACK VIEW framing and its NUDE_WARDROBE swap only run when
    # the prompt is empty. A genuinely edited box still differs from its own
    # carried default, so real edits survive the swap exactly as before.
    typed_prompts = {t: v for t, v in typed_prompts.items()
               if v.strip() != (qp.get(f"prompt_default_{t}") or "").strip()}
    # The negative and the tier wordings were preserved on the POST-side rebuild
    # (_anchor_ctx_from_form) but not here, so typing a negative and then ticking
    # anything silently put the album's last SAVED one back. Both are
    # album-scoped, hence the same_subject guard: carrying them across an album
    # switch would be the bug above wearing a different hat.
    negative = qp.get("negative") if same_subject else None
    tones = ({k[len("tone_"):]: v for k, v in qp.items() if k.startswith("tone_")}
             if same_subject else {})
    pose = qp.get("pose") if same_subject else None
    return templates.TemplateResponse(request, "_anchor_form.html",
                                       anchor_form_ctx(album, tier, view,
                                                       character_id, typed_prompts, negative, tones,
                                                       latent=qp.get("latent"), pose=pose))


def _drop_anchor(row):
    """Delete one anchor candidate, file then row.

    The file is removed only if it resolves inside db.DATA -- ComfyUI's own
    output dir is shared and is not ours to delete from. Three callers now
    (one, many, and a whole group's rejects), so the containment rule lives here
    rather than being restated at each of them.
    """
    if _within_data(row["path"]) and os.path.isfile(row["path"]):
        try:
            os.remove(row["path"])
        except OSError:
            pass
    # Borrowed references point at THIS file (use_anchor_as_ref) and the file is
    # going. Left behind, the gallery would offer a thumbnail with no image and
    # a ticked reference would queue a render that fails at load -- the failure
    # arriving one GPU minute after the cause, which is the shape of it that
    # costs the most to diagnose.
    for a in db.q("SELECT * FROM assets WHERE kind='anchor_ref' AND path=?", row["path"]):
        if db.jset(a).get("anchor_id"):
            db.run("DELETE FROM assets WHERE id=?", a["id"])
    db.run("DELETE FROM anchors WHERE id=?", row["id"])


@app.post("/anchors/{id}/delete")
def delete_anchor(request: Request, id: int):
    """Delete one anchor candidate, row and file.

    Anchors accumulate: every generation adds N candidates and only one is ever
    picked, so a scope+tier+view group is mostly rejects.
    """
    row = db.one("SELECT * FROM anchors WHERE id=?", id)
    if not row:
        raise HTTPException(404, "no such anchor candidate")
    _drop_anchor(row)
    if wants_json(request):
        return JSONResponse({"deleted": [id]})
    return RedirectResponse(
        f"/anchors?scope_kind={row['scope_kind']}&scope_value={quote(row['scope_value'])}",
        status_code=303)


@app.post("/anchors/delete")
async def delete_anchors(request: Request):
    """Delete the ticked candidates in one call.

    Multi-select exists because a generation makes N candidates and N-1 are
    rejects: picking them off one request at a time is the slow path this page
    was mostly used for. The CHOSEN one is deletable here exactly as it is
    singly -- refusing would make a group of one undeletable, and refs already
    refuses a tier with no chosen anchor in its own words.
    """
    body = await request.json()
    ids = [int(i) for i in (body.get("anchor_ids") or [])]
    if not ids:
        raise HTTPException(400, "no candidates selected")
    gone = []
    for i in ids:
        row = db.one("SELECT * FROM anchors WHERE id=?", i)
        if row:
            _drop_anchor(row)
            gone.append(i)
    return JSONResponse({"deleted": gone})


@app.post("/anchors/delete-unpicked")
def delete_unpicked_anchors(request: Request, scope_kind: str = Form(...),
                             scope_value: str = Form(...),
                             tier: str = Form(...), view: str = Form(...),
                             character_id: CharacterId = Form(None)):
    """Clear out one group's rejects, keeping whichever is chosen.

    Deleting six candidates one at a time is the slow path, and the chosen one
    is explicitly protected so this can never leave a tier with no anchor --
    which would silently block every refs job for it.
    """
    rows = db.q("""SELECT * FROM anchors WHERE scope_kind=? AND scope_value=? AND tier=?
                   AND view=? AND character_id IS ? AND chosen=0""",
                scope_kind, scope_value, tier, view, character_id)
    for r in rows:
        _drop_anchor(r)
    if wants_json(request):
        return JSONResponse({"deleted": [r["id"] for r in rows]})
    return RedirectResponse(
        f"/anchors?scope_kind={scope_kind}&scope_value={quote(scope_value)}", status_code=303)


@jobs.handler("fix_anchor")
def h_fix_anchor(args, progress):
    """Repair an anchor sheet. Same engine as a reference frame's repair --
    fix_ref.py does not care whether the image it is given is a sheet or a
    frame, so a second repair path would be a second thing to keep correct."""
    row = db.one("SELECT * FROM anchors WHERE id=?", args["anchor_id"])
    if not row:
        return
    prof = album_profile(row["scope_value"] if row["scope_kind"] == "album" else "")
    if row["character_id"]:
        char = db.one("SELECT * FROM characters WHERE id=?", row["character_id"])
        if char and char["body"]:
            prof = dict(prof, body=char["body"])
    results = pipeline.fix_ref(
        f"anchor_{row['id']}", row["tier"], 0, args["mode"], row["path"], args["seed"],
        progress, face_path=args.get("face_path"), mask_path=args.get("mask_path"),
        pad=args.get("pad", (0, 0, 0, 0)), instruction=args.get("instruction", ""),
        guard=tiers.compose_guardrail(
            row["tier"], row["scope_value"] if row["scope_kind"] == "album" else ""),
        body=prof["body"])
    now = time.time()
    for r in results:
        # a NEW candidate in the same group, never a replacement: the sheet you
        # were fixing stays until you pick the fix
        db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen,
                                        created, character_id)
                  VALUES (?,?,?,?,?,0,?,?)""",
               row["scope_kind"], row["scope_value"], row["tier"], row["view"],
               r["path"], now, row["character_id"])
    return {"count": len(results), "mode": args["mode"]}


@app.post("/anchors/{id}/fix")
async def start_fix_anchor(id: int, mode: str = Form(...), instruction: str = Form(""),
                            face: Optional[UploadFile] = File(None), mask_data: str = Form(""),
                            pad_left: int = Form(0), pad_top: int = Form(0),
                            pad_right: int = Form(0), pad_bottom: int = Form(0)):
    """Face swap, inpaint or outpaint an anchor sheet.

    The same three repairs a reference frame gets, on the same model, because a
    bad anchor is worse than a bad frame: every frame in the song is rendered
    from it.
    """
    row = db.one("SELECT * FROM anchors WHERE id=?", id)
    if not row:
        raise HTTPException(404, "no such anchor")
    if mode not in FIX_MODES:
        raise HTTPException(400, f"mode must be one of {', '.join(FIX_MODES)}")
    if not os.path.isfile(row["path"]):
        raise HTTPException(400, "that anchor's file is missing on disk")

    instruction = (instruction or "").strip()
    if len(instruction) > MAX_INSTRUCTION:
        raise HTTPException(400, f"instruction is {len(instruction)} characters; keep it under "
                                  f"{MAX_INSTRUCTION}")
    try:
        tiers.check_text(instruction, "anchor repair instruction")
        tiers.check_override(instruction)
    except ValueError as e:
        raise HTTPException(400, str(e))

    work_dir = os.path.join(db.DATA, "fixes", "anchors")
    stamp = int(time.time() * 1000)
    face_path = mask_path = None
    if mode == "face":
        if not (face and face.filename):
            raise HTTPException(400, "a face swap needs a face image to swap in")
        face_path = await save_upload(face, MAX_IMAGE, work_dir, "image", prefix=f"face_{stamp}")
    elif mode == "inpaint":
        mask_path = save_mask_data_url(mask_data, work_dir, f"amask_{id}_{stamp}")
    else:
        if not any((pad_left, pad_top, pad_right, pad_bottom)):
            raise HTTPException(400, "outpainting needs a non-zero pad on at least one side")
        for name, v in (("left", pad_left), ("top", pad_top),
                         ("right", pad_right), ("bottom", pad_bottom)):
            if v < 0:
                raise HTTPException(400, f"pad {name} must be >= 0")

    jobs.enqueue("fix_anchor", {
        "anchor_id": id, "mode": mode, "face_path": face_path, "mask_path": mask_path,
        "pad": (pad_left, pad_top, pad_right, pad_bottom), "instruction": instruction,
        "seed": stamp % 2_000_000_000})
    return RedirectResponse("/playlists", status_code=303)


@app.post("/anchors/{id}/pick")
def pick_anchor(request: Request, id: int):
    row = db.one("SELECT * FROM anchors WHERE id=?", id)
    if not row:
        raise HTTPException(404, "no such anchor candidate")
    # exactly one chosen per (scope_kind, scope_value, tier, view, CHARACTER)
    # group. Without the character in the key, picking a supporting character's
    # anchor would unpick the protagonist's for that tier -- and the next refs
    # job would refuse to run for want of an anchor that was chosen a moment ago.
    # `IS ?`, not `= ?`: character_id is NULL for the protagonist and NULL = NULL
    # is never true in SQL. sqlite's IS is null-safe equality and works on every
    # version; IS NOT DISTINCT FROM needs 3.39 and cerberus runs 3.37.2, so it
    # would have passed here and been a syntax error on the deployed box.
    db.run("""UPDATE anchors SET chosen=0 WHERE scope_kind=? AND scope_value=? AND tier=?
              AND view=? AND character_id IS ?""",
           row["scope_kind"], row["scope_value"], row["tier"], row["view"], row["character_id"])
    db.run("UPDATE anchors SET chosen=1 WHERE id=?", id)
    if wants_json(request):
        # which one is now chosen AND which lost it: the page has to move the
        # highlight off the old one, and only the server knows which that was
        peers = db.q("""SELECT id, chosen FROM anchors WHERE scope_kind=? AND scope_value=?
                        AND tier=? AND view=? AND character_id IS ?""",
                     row["scope_kind"], row["scope_value"], row["tier"], row["view"],
                     row["character_id"])
        return JSONResponse({"chosen": id,
                             "group": [{"id": p["id"], "chosen": bool(p["chosen"])} for p in peers]})
    return RedirectResponse(
        f"/anchors?scope_kind={row['scope_kind']}&scope_value={quote(row['scope_value'])}",
        status_code=303)


def tier_tone(tier, album=""):
    """The tone/wardrobe wording that APPLIES, with the pinned clause removed.

    This album's own wording for the tier if it has one, else the tier's --
    tiers.tier_text is the single place that decides, so a panel showing this
    and a render composing through compose_guardrail() cannot disagree about
    which wording is in force. Unknown tier -> "" rather than an exception,
    because this feeds a form that must still render.
    """
    try:
        return tiers.tier_text(tier, album).strip()
    except ValueError:
        return ""


def default_direction(song, tier):
    """Prefill for the storyboard direction box.

    Every part of it already exists and was previously composed INVISIBLY on the
    way to the model: the tier's tone wording, and the album's theme, world and
    render style. Putting it in a textarea is the whole feature -- the storyboard
    is written from this text, so it is the text that should be editable.
    """
    prof = album_profile(song["album"] or "")
    parts = [(f"Tone and wardrobe ({tier} tier)", tier_tone(tier, song["album"] or "")),
             ("Look", prof["style_text"]), ("World", prof["world"]),
             ("Render style", prof["render_tail"])]
    return "\n\n".join(f"{label}: {text.strip()}" for label, text in parts if text and text.strip())


def storyboard_form_ctx(song, tier, chat_models=None, best=None, direction=None):
    """The direction form for one tier: the prefill, plus the limits shown above
    it. `direction` overrides the prefill -- used to redisplay what was actually
    sent for an already-generated storyboard."""
    if direction is None:
        row = db.one("SELECT prompt FROM storyboards WHERE song_id=? AND tier=?", song["id"], tier)
        # An album arc, when there is one, is the better starting point than the
        # tier's generic tone wording: it is what this SONG does in the story.
        # A prefill, not a cage -- the box stays editable and what is actually
        # sent is stored beside the storyboard, as it always was.
        beat = arc.for_song(album_arc(song["album"] or ""), song["id"]).get("beat", "")
        direction = ((row["prompt"] if row else "") or beat
                     or default_direction(song, tier))
    return {"song": song, "tier": tier, "tiers": tiers.all_tiers(),
            "direction": direction, "pinned": tiers.PINNED.strip(),
            "tier_text": tier_tone(tier, song["album"] or ""),
            "max_direction": grok.MAX_DIRECTION,
            "models": chat_models if chat_models is not None else [], "best_model": best}


def check_direction(direction):
    """Screen the direction box exactly as a custom tier's wording is screened.

    Same two functions, for the same two reasons: check_text() refuses minor
    references before any model is called, and check_override() refuses text
    that argues with the pinned clause. The length cap is larger than a tier's
    500 because this is a brief for one song, not a reusable rating.
    """
    direction = (direction or "").strip()
    if len(direction) > grok.MAX_DIRECTION:
        raise HTTPException(400, f"the direction is {len(direction)} characters; keep it "
                                  f"under {grok.MAX_DIRECTION}. It is a brief, not a script.")
    try:
        tiers.check_text(direction, "storyboard direction")
        tiers.check_override(direction)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return direction


@app.get("/songs/{id}/storyboard-form", response_class=HTMLResponse)
def storyboard_form(request: Request, id: int, tier: str):
    """The direction form, re-rendered for another tier.

    Its own route so changing the tier select swaps the prefill in place (htmx),
    rather than the prompt silently belonging to whichever tier was selected
    when the page loaded.
    """
    song = get_song_or_404(id)
    valid_tier_or_400(tier)
    try:
        chat_models = grok.list_models()
    except Exception:
        chat_models = []
    return templates.TemplateResponse(
        request, "_storyboard_form.html",
        storyboard_form_ctx(song, tier, chat_models,
                            grok.best_model(chat_models) if chat_models else None))


@app.post("/songs/{id}/storyboard")
def start_storyboard(id: int, tier: str = Form(...), model: str = Form(""),
                      scene_seconds: float = Form(4.0), direction: str = Form("")):
    get_song_or_404(id)
    valid_tier_or_400(tier)
    direction = check_direction(direction)
    if not math.isfinite(scene_seconds):
        raise HTTPException(400, "scene_seconds must be a finite number")
    scene_seconds = min(max(scene_seconds, 1.0), 60.0)
    # blank means "use the studio default", which /models sets; blank there too
    # means grok.best_model() picks the highest available
    jobs.enqueue("storyboard", {"song_id": id, "tier": tier,
                                 "model": (model or models.chat_default()) or None,
                                 "scene_seconds": scene_seconds, "direction": direction},
                 song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


# Scene fields the storyboard page lets you edit. image_prompt is what the
# reference renderer actually sends; video_motion_prompt is what the clip
# renderer sends; story is the human line the detail-shot path falls back to
# (build_refs.tighten_for_detail). Nothing else is editable here on purpose --
# camera feeds SHOT_RULES matching and scene_number keys the whole allocation.
EDITABLE_SCENE_FIELDS = ("image_prompt", "video_motion_prompt", "story")
MAX_SCENE_FIELD = 4000


def load_storyboard(row, normalized=True):
    """The storyboard JSON.

    normalized=True (for DISPLAY): build_song.normalize() maps the older
    '*_comfy.json' schema and strips guardrail text baked into legacy scene
    prose, so the page shows the prompt that will actually render rather than
    the prompt as filed. Showing the raw text would defeat the point of the page.

    normalized=False (for WRITING): normalize() also deletes every scene's
    negative_prompt and the top-level global_negative_prompt/global_guardrail.
    Saving that back would silently strip them from disk on an unrelated one-line
    edit -- and negative_prompt is in grok.REQUIRED_SCENE_KEYS, so the file would
    then fail validate(). An edit must change the field it was given and nothing
    else, so writes patch the file as it is on disk.
    """
    with open(row["json_path"]) as f:
        sb = json.load(f)
    return build_song.normalize(sb) if normalized else sb


def storyboard_scenes(song, sb, tier, anchored=(), scene_seconds=None):
    """Per-scene timing, prompts and reference frames for the storyboard page.

    Timing comes from build_song.clip_plan() -- THE clip->scene mapping, shared
    with build_refs/build_song/reroll_refs. Deriving it here a second time is
    exactly the drift clip_plan's docstring exists to prevent, so this calls it.

    `anchored` is the set of cast names with a chosen anchor at this tier, so a
    scene naming somebody unanchored shows it BEFORE fifty frames render them
    from scene text alone.
    """
    anchored = set(anchored)
    scenes = sb.get("scenes") or []
    # One divisor for the whole function: the length THIS song's clips are, from
    # what its storyboard was generated with. None means a storyboard from
    # before that was recorded and build_song answers CHUNK, which is exactly
    # the old behaviour for every song already on disk.
    clip_secs = build_song.clip_seconds(scene_seconds)
    nclips = clip_count(song, scene_seconds)
    plan = build_song.clip_plan(scenes, nclips=nclips) if (scenes and nclips) else []

    # refs for this tier, newest candidate last, keyed by clip
    by_clip = {}
    for r in db.q("SELECT * FROM refs WHERE song_id=? AND tier=? ORDER BY clip_idx, id", song["id"], tier):
        by_clip.setdefault(r["clip_idx"], []).append(r)

    clips_of = {}
    shots_of = {}
    for ci, scene, shot in plan:
        clips_of.setdefault(scene["scene_number"], []).append(ci)
        shots_of.setdefault(scene["scene_number"], []).append(shot)

    rows = []
    for scene in scenes:
        num = scene.get("scene_number")
        idxs = clips_of.get(num, [])
        edited = float(scene.get("edited") or 0)
        refs = []
        for ci in idxs:
            cands = by_clip.get(ci, [])
            refs.append({
                "idx": ci,
                "candidates": cands,
                "approved": any(c["approved"] for c in cands),
                # a frame rendered BEFORE the scene text was last edited no
                # longer shows what the prompt now says. Surfaced, never
                # auto-re-rolled: re-rolling 50 frames over a typo is worse.
                "stale": bool(edited and cands and
                              all((c["created"] or 0) < edited for c in cands)),
            })
        rows.append({
            "scene": scene, "num": num, "name": build_song.sname(scene),
            "clips": idxs,
            # SECOND IMPLEMENTATION OF SCENE TIMING, removed 2026-08-13. This
            # was idx * CHUNK, which is the studio's own copy of an arithmetic
            # docs/TRD-2 T2-41 says has exactly one home -- and with clip length
            # per song, a hardcoded CHUNK here would time every storyboard
            # against 4.8125s whatever the song was generated at. One divisor,
            # from the song, passed in.
            "start": idxs[0] * clip_secs if idxs else None,
            "end": (idxs[-1] + 1) * clip_secs if idxs else None,
            "length": len(idxs) * clip_secs,
            "guidance": build_song.guidance_seconds(scene),
            "shots": sorted(set(shots_of.get(num, []))),
            "refs": refs, "edited": edited,
            "cast": [{"name": n, "anchored": n in anchored}
                     for n in (scene.get("characters") or [])],
        })
    return rows, nclips


def coverage(rows, nclips, duration, clip_secs=None):
    """How the storyboard's PACING INTENT compares with the track.

    Not "is the video the right length" -- allocate() always spends exactly
    nclips, so the render is always the length of the song. What can be wrong is
    the intent: a storyboard whose duration_guidance totals 90s for a 240s track
    is being stretched 2.7x, and every scene will run far longer than it was
    written for. That is what this measures.
    """
    intent = sum(r["guidance"] for r in rows)
    # this song's clip length, not a module constant -- one divisor, from
    # build_song, so the meter cannot describe a different render than the page
    rendered = nclips * build_song.clip_seconds(clip_secs)
    return {
        "intent": intent, "rendered": rendered, "duration": duration or 0.0,
        "nclips": nclips, "scenes": len(rows),
        "ratio": (rendered / intent) if intent else 0.0,
        # within 15% either way is ordinary rounding; beyond that the pacing was
        # written for a different length of song
        "ok": bool(intent) and 0.85 <= (rendered / intent) <= 1.15,
    }


@app.get("/songs/{id}/storyboard/{tier}", response_class=HTMLResponse)
def view_storyboard(request: Request, id: int, tier: str):
    song = get_song_or_404(id)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    if not row:
        raise HTTPException(404, "no storyboard for this tier yet")
    md = ""
    if row["md_path"] and os.path.isfile(row["md_path"]):
        with open(row["md_path"]) as f:
            md = f.read()
    try:
        sb = load_storyboard(row)
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(500, f"storyboard file is unreadable: {e}") from None
    album = song["album"] or ""
    cast = cast_anchors(album, tier)
    sb_secs = row["scene_seconds"] if row else None
    rows, nclips = storyboard_scenes(song, sb, tier, {c["name"] for c, _a in cast},
                                     scene_seconds=sb_secs)
    # the anchors this tier will actually render from, at the top, because a
    # storyboard is read against the character it is for. The protagonist's
    # (character_id IS NULL) first, then the cast.
    anchors = db.q("""SELECT a.*, c.name AS character_name
                      FROM anchors a LEFT JOIN characters c ON c.id = a.character_id
                      WHERE a.scope_kind='album' AND a.scope_value=? AND a.tier=? AND a.chosen=1
                      ORDER BY (a.character_id IS NOT NULL), c.name, a.view, a.id""", album, tier)
    return templates.TemplateResponse(request, "storyboard.html", {
        "song": song, "tier": tier, "row": row, "md": md, "sb": sb,
        # the page shows THIS song's clip length, not the old constant
        "scene_rows": rows, "anchors": anchors, "chunk": build_song.clip_seconds(sb_secs),
        "unanchored": sorted({n["name"] for r in rows for n in r["cast"] if not n["anchored"]}),
        "coverage": coverage(rows, nclips, song["duration"], sb_secs),
        "fields": EDITABLE_SCENE_FIELDS,
    })


@app.post("/songs/{id}/storyboard/{tier}/scene/{num}", response_class=HTMLResponse)
async def save_scene(request: Request, id: int, tier: str, num: int):
    """Patch one scene's prompts in the storyboard JSON, in place.

    The JSON on disk is the source of truth -- build_refs.py and build_song.py
    read it directly -- so this writes there rather than into a parallel table
    that would then have to be reconciled. Both files are rewritten through
    grok.write_storyboard(), the same function that created them, so the
    markdown never drifts from the JSON.
    """
    song = get_song_or_404(id)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    if not row:
        raise HTTPException(404, "no storyboard for this tier yet")
    form = await request.form()
    sb = load_storyboard(row, normalized=False)
    scene = next((s for s in sb.get("scenes", []) if s.get("scene_number") == num), None)
    if scene is None:
        raise HTTPException(404, f"no scene {num} in this storyboard")

    changed = False
    for field in EDITABLE_SCENE_FIELDS:
        if field not in form:
            continue
        value = (form.get(field) or "").strip()
        if len(value) > MAX_SCENE_FIELD:
            raise HTTPException(400, f"{field} is {len(value)} characters; keep it under {MAX_SCENE_FIELD}")
        # Same screening the model's own output gets in grok.validate(): this is
        # text that goes straight into an image prompt, and hand-editing is
        # exactly the path that bypasses the generator's checks.
        try:
            tiers.check_text(value, f"scene {num} {field}")
        except ValueError as e:
            raise HTTPException(400, str(e))
        if (scene.get(field) or "") != value:
            scene[field] = value
            changed = True
    if changed:
        # stamp the edit so frames rendered before it can be shown as stale.
        # An unknown key in a scene is ignored by every builder (they read named
        # fields), so this costs nothing downstream.
        scene["edited"] = time.time()
        outdir = os.path.dirname(row["json_path"])
        grok.write_storyboard(sb, outdir, song["slug"], tier)
    anchored = {c["name"] for c, _a in cast_anchors(song["album"] or "", tier)}
    rows, _ = storyboard_scenes(song, load_storyboard(row), tier, anchored,
                                scene_seconds=row["scene_seconds"])
    r = next(x for x in rows if x["num"] == num)
    return templates.TemplateResponse(request, "_scene_row.html", {
        "song": song, "tier": tier, "r": r, "fields": EDITABLE_SCENE_FIELDS,
        "chunk": build_song.clip_seconds(row["scene_seconds"])})


@app.post("/songs/{id}/refs")
def start_refs(id: int, tier: List[str] = Form([]), limit: int = Form(0)):
    # Form([]) not Form(...): an unticked checkbox group is simply absent from
    # the POST, and a required field turns that into FastAPI's raw 422 validation
    # blob. Defaulting to empty lets the handler answer "select at least one
    # tier" instead.
    song = get_song_or_404(id)
    selected = sorted(set(tier))
    if not selected:
        raise HTTPException(400, "select at least one tier")
    # resolve every tier's anchor up front -- one bad tier must refuse the
    # whole request, not enqueue the good ones and 400 partway through
    anchors = {}
    for t in selected:
        valid_tier_or_400(t)
        if not db.one("SELECT id FROM storyboards WHERE song_id=? AND tier=?", id, t):
            raise HTTPException(400, f"generate a storyboard for tier '{t}' first")
        anchor = chosen_anchor("album", song["album"] or "", t)
        if not anchor:
            raise HTTPException(400, f"no chosen anchor for tier '{t}' on this album "
                                      f"-- generate and pick one on /anchors first")
        anchors[t] = anchor
    limit = max(0, limit)
    for t in selected:
        # one refs job per tier, each carrying that tier's own chosen anchor --
        # this is what makes two tiers yield two independent reference sets
        jobs.enqueue("refs", {"song_id": id, "tier": t, "limit": limit or None,
                               "anchor_path": anchors[t]["path"]}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


def latest_flags(sid, tier):
    """{clip_idx: {issue, reason}} from the newest vision review of this tier.

    classify_sheet already returns clip numbers; they were only ever printed as
    a list of indices, which means reading "clip 18, clip 34" and then counting
    tiles to find them. Putting the flag ON the frame is the whole difference
    between a review you act on and one you skim.
    """
    for a in db.q("SELECT * FROM assets WHERE song_id=? AND kind='review' ORDER BY id DESC", sid):
        meta = db.jset(a)
        if meta.get("tier") != tier:
            continue
        return {int(f["clip"]): f for f in meta.get("flagged", []) if "clip" in f}
    return {}


def approve_context(song, tier):
    """Shared by the grid and by the single-tile htmx swap, so a tile rendered
    on its own carries the same flags, cast and seeds as one rendered in place."""
    refs_rows = db.q("SELECT * FROM refs WHERE song_id=? AND tier=? ORDER BY clip_idx, id",
                      song["id"], tier)
    by_clip = {}
    for r in refs_rows:
        by_clip.setdefault(r["clip_idx"], []).append(r)
    flags = latest_flags(song["id"], tier)
    nclips = clip_count(song, scene_seconds_for(song["id"], tier))
    clips = []
    for i in range(nclips):
        cands = by_clip.get(i, [])
        clips.append({"idx": i, "candidates": cands,
                      "approved": any(c["approved"] for c in cands),
                      "flag": flags.get(i)})
    # face sources: whoever has a chosen anchor at this tier
    faces = []
    if chosen_anchor("album", song["album"] or "", tier):
        faces.append(("protagonist", "protagonist"))
    faces += [(str(c["id"]), c["name"]) for c, _a in cast_anchors(song["album"] or "", tier)]
    return {"song": song, "tier": tier, "clips": clips, "nclips": nclips,
            "faces": faces, "flagged_idxs": sorted(flags)}


@app.get("/songs/{id}/approve/{tier}", response_class=HTMLResponse)
def approve_grid(request: Request, id: int, tier: str):
    song = get_song_or_404(id)
    return templates.TemplateResponse(request, "approve.html", approve_context(song, tier))


@app.post("/songs/{id}/approve/{tier}/all")
def approve_all(id: int, tier: str, replace: bool = Form(False)):
    """Approve one candidate for every clip that has none.

    At fifty frames, clicking Approve fifty times is the slow path and the
    common case is "these are fine except three". This approves the NEWEST
    candidate per clip -- newest because a re-roll or a repair is the frame you
    asked for most recently -- and by default leaves clips you have already
    decided alone, so it never silently overrides a deliberate pick.
    """
    song = get_song_or_404(id)
    valid_tier_or_400(tier)
    decided = {r["clip_idx"] for r in
                db.q("SELECT DISTINCT clip_idx FROM refs WHERE song_id=? AND tier=? AND approved=1",
                     id, tier)}
    n = 0
    for i in range(clip_count(song, scene_seconds_for(song["id"], tier))):
        if i in decided and not replace:
            continue
        newest = db.one("""SELECT id FROM refs WHERE song_id=? AND tier=? AND clip_idx=?
                           ORDER BY id DESC LIMIT 1""", id, tier, i)
        if not newest:
            continue
        db.run("UPDATE refs SET approved=0 WHERE song_id=? AND tier=? AND clip_idx=?", id, tier, i)
        db.run("UPDATE refs SET approved=1 WHERE id=?", newest["id"])
        n += 1
    return RedirectResponse(f"/songs/{id}/approve/{tier}", status_code=303)


@app.post("/songs/{id}/refs/{clip_idx}/approve", response_class=HTMLResponse)
def approve_ref(request: Request, id: int, clip_idx: int, tier: str = Form(...), ref_id: int = Form(...)):
    song = get_song_or_404(id)
    ref = db.one("SELECT * FROM refs WHERE id=? AND song_id=? AND tier=? AND clip_idx=?",
                  ref_id, id, tier, clip_idx)
    if not ref:
        raise HTTPException(404, "no such ref candidate")
    new_val = 0 if ref["approved"] else 1
    if new_val:
        db.run("UPDATE refs SET approved=0 WHERE song_id=? AND tier=? AND clip_idx=?", id, tier, clip_idx)
    db.run("UPDATE refs SET approved=? WHERE id=?", new_val, ref_id)
    # rebuilt through approve_context so the swapped-in tile carries the same
    # flags, face sources and seeds as one rendered in the grid -- a tile that
    # loses its Fix controls the moment you approve something is worse than none
    ctx = approve_context(song, tier)
    clip = next((c for c in ctx["clips"] if c["idx"] == clip_idx), None)
    return templates.TemplateResponse(request, "_clip_tile.html", dict(ctx, clip=clip))


MAX_REROLL_NOTE = 400


@app.post("/songs/{id}/reroll")
def start_reroll(id: int, tier: str = Form(...), clip_idx: List[int] = Form(...),
                  note: str = Form("")):
    """note: what to change about these clips.

    A bare re-roll is four new seeds on the same prompt -- a blind gamble that
    the composition you disliked does not come back. One line of "she is facing
    away, turn her toward the camera" is appended to those clips' prompts only,
    which turns the gamble into a correction. It is screened like any other
    prompt text.
    """
    song = get_song_or_404(id)
    sb = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    if not sb:
        raise HTTPException(400, "generate a storyboard for this tier first")
    idxs = sorted({i for i in clip_idx if 0 <= i < clip_count(song, scene_seconds_for(song["id"], tier))})
    if not idxs:
        raise HTTPException(400, "no valid clip indices given")
    if len(idxs) > MAX_REROLL_CLIPS:
        raise HTTPException(400, f"too many clips to reroll at once (max {MAX_REROLL_CLIPS})")
    note = " ".join((note or "").split())
    if len(note) > MAX_REROLL_NOTE:
        raise HTTPException(400, f"the note is {len(note)} characters; keep it under "
                                  f"{MAX_REROLL_NOTE}. It is one correction, not a new scene.")
    try:
        tiers.check_text(note, "reroll note")
        tiers.check_override(note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    jobs.enqueue("reroll", {"song_id": id, "tier": tier, "clip_indices": idxs, "note": note},
                 song_id=id)
    return RedirectResponse(f"/songs/{id}/approve/{tier}", status_code=303)


FIX_MODES = ("face", "inpaint", "outpaint")
MAX_INSTRUCTION = 1000
# A 1280x720 mask as a base64 data URL is ~30-120KB. 4MB is generous headroom
# and still refuses a pasted photograph, which would not be a mask.
MAX_MASK_DATA_URL = 4 * 1024 * 1024
_DATA_URL_RE = re.compile(r"^data:image/png;base64,([A-Za-z0-9+/=\s]+)$")


def save_mask_data_url(data_url, dest_dir, prefix):
    """Decode the mask painted in the browser into a PNG on disk.

    Strictly png-only and base64-only: this string comes from a form field, and
    the decoded bytes are handed to ComfyUI as an image. Anything that is not
    exactly the shape a canvas.toDataURL('image/png') produces is refused rather
    than written and hoped about.
    """
    import base64
    if len(data_url or "") > MAX_MASK_DATA_URL:
        raise HTTPException(413, "mask image is too large")
    m = _DATA_URL_RE.match((data_url or "").strip())
    if not m:
        raise HTTPException(400, "mask must be a base64 image/png data URL")
    try:
        raw = base64.b64decode(m.group(1), validate=False)
    except Exception:
        raise HTTPException(400, "mask is not valid base64") from None
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(400, "mask is not a PNG")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{prefix}.png")
    with open(dest, "wb") as f:
        f.write(raw)
    return dest


@app.post("/songs/{id}/refs/{clip_idx}/fix")
async def start_fix_ref(id: int, clip_idx: int, tier: str = Form(...), mode: str = Form(...),
                         ref_id: int = Form(...), instruction: str = Form(""),
                         face_from: str = Form(""), face: Optional[UploadFile] = File(None),
                         mask_data: str = Form(""), pad_left: int = Form(0), pad_top: int = Form(0),
                         pad_right: int = Form(0), pad_bottom: int = Form(0)):
    """Repair an existing reference frame instead of re-rolling it.

    A re-roll is a new seed: it throws away the composition you liked in order
    to fix the one thing you did not. This keeps the frame and changes the part
    you point at, and lands as another candidate so nothing is lost either way.
    """
    song = get_song_or_404(id)
    valid_tier_or_400(tier)
    if mode not in FIX_MODES:
        raise HTTPException(400, f"mode must be one of {', '.join(FIX_MODES)}")
    ref = db.one("SELECT * FROM refs WHERE id=? AND song_id=? AND tier=? AND clip_idx=?",
                  ref_id, id, tier, clip_idx)
    if not ref:
        raise HTTPException(404, "no such reference frame")
    if not os.path.isfile(ref["path"]):
        raise HTTPException(400, "that reference frame's file is missing on disk")

    instruction = (instruction or "").strip()
    if len(instruction) > MAX_INSTRUCTION:
        raise HTTPException(400, f"instruction is {len(instruction)} characters; keep it under "
                                  f"{MAX_INSTRUCTION}")
    try:
        tiers.check_text(instruction, "repair instruction")
        tiers.check_override(instruction)
    except ValueError as e:
        raise HTTPException(400, str(e))

    work_dir = os.path.join(db.DATA, "fixes", song["slug"])
    stamp = int(time.time() * 1000)
    face_path = mask_path = None

    if mode == "face":
        # the face comes from an upload, or from an anchor already on the box --
        # "use her own anchor" is the common case and should not need a file
        if face_from:
            if face_from == "protagonist":
                src = chosen_anchor("album", song["album"] or "", tier)
            else:
                if not face_from.isdigit():
                    raise HTTPException(400, "face_from must be 'protagonist' or a character id")
                char = get_character_or_404(int(face_from))
                src = chosen_anchor("album", song["album"] or "", tier, character_id=char["id"])
            if not src:
                raise HTTPException(400, "that character has no chosen anchor at this tier")
            face_path = src["path"]
        elif face and face.filename:
            face_path = await save_upload(face, MAX_IMAGE, work_dir, "image", prefix=f"face_{stamp}")
        else:
            raise HTTPException(400, "a face swap needs a face: upload one or pick an anchor")
    elif mode == "inpaint":
        mask_path = save_mask_data_url(mask_data, work_dir, f"mask_{clip_idx:03d}_{stamp}")
    else:
        if not any((pad_left, pad_top, pad_right, pad_bottom)):
            raise HTTPException(400, "outpainting needs a non-zero pad on at least one side")
        for name, v in (("left", pad_left), ("top", pad_top),
                         ("right", pad_right), ("bottom", pad_bottom)):
            if v < 0:
                raise HTTPException(400, f"pad {name} must be >= 0")

    jobs.enqueue("fix_ref", {
        "song_id": id, "tier": tier, "clip_idx": clip_idx, "mode": mode,
        "image_path": ref["path"], "face_path": face_path, "mask_path": mask_path,
        "pad": (pad_left, pad_top, pad_right, pad_bottom),
        "instruction": instruction,
        # a distinct seed per repair: refs is UNIQUE(song_id, tier, clip_idx, seed),
        # so reusing the frame's own seed would silently drop the result
        "seed": stamp % 2_000_000_000,
    }, song_id=id)
    return RedirectResponse(f"/songs/{id}/approve/{tier}", status_code=303)


@app.post("/songs/{id}/classify")
def start_classify(id: int, tier: str = Form(...)):
    """Vision review of a tier's approved references. Advisory only: it reports
    clips to look at, it never unapproves or deletes anything."""
    get_song_or_404(id)
    valid_tier_or_400(tier)
    if not db.one("SELECT id FROM refs WHERE song_id=? AND tier=? AND approved=1", id, tier):
        raise HTTPException(400, f"no approved references for tier '{tier}' yet")
    jobs.enqueue("classify", {"song_id": id, "tier": tier}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


MAX_DRIVING_VIDEO = 200 * 1024 * 1024
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv"}


async def save_driving_video(upload, dest_dir, prefix):
    """A motion-style or control clip for s2v. Read by PATH, so it is stored
    under db.DATA rather than installed into COMFY_INPUT like the images."""
    if not upload or not upload.filename:
        return None
    ext = os.path.splitext(safe_name(upload.filename))[1].lower()
    if ext not in VIDEO_EXTS:
        raise HTTPException(400, f"unsupported video type {ext or '(none)'}")
    data = await upload.read(MAX_DRIVING_VIDEO + 1)
    if len(data) > MAX_DRIVING_VIDEO:
        raise HTTPException(413, f"video too large (max {MAX_DRIVING_VIDEO // (1024 * 1024)}MB)")
    if not data:
        raise HTTPException(400, "video file is empty")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, safe_name(f"{prefix}_{upload.filename}"))
    with open(dest, "wb") as f:
        f.write(data)
    return dest


@app.post("/songs/{id}/clips")
async def start_clips(id: int, tier: str = Form(...), video_model: str = Form(""),
                       refine: bool = Form(False),
                       ref_motion: Optional[UploadFile] = File(None),
                       control_video: Optional[UploadFile] = File(None)):
    song = get_song_or_404(id)
    sb = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    if not sb:
        raise HTTPException(400, "generate a storyboard for this tier first")
    n_clips = clip_count(song, scene_seconds_for(song["id"], tier))
    if not n_clips:
        # duration is what defines the clip list; without it the job would
        # render every clip build_song computes from the mp3 with no staged
        # references at all, and fail deep inside ComfyUI instead of here.
        raise HTTPException(400, "this song has no known duration -- re-upload the mp3")
    approved_idxs = {r["clip_idx"] for r in
                      db.q("SELECT clip_idx FROM refs WHERE song_id=? AND tier=? AND approved=1", id, tier)}
    missing = [i for i in range(n_clips) if i not in approved_idxs]
    if missing:
        raise HTTPException(400, f"clips missing an approved reference: {missing}")
    # The catalogue is the single place that knows which renderers exist -- the
    # song page already builds its dropdown from models.renderable("video") and
    # marks models.default_for("video"). Hardcoding the pair here meant the page
    # offered a default the API answered with a 400.
    allowed = set(models.renderable("video").values())
    video_model = video_model or models.default_cli("video")
    if video_model not in allowed:
        raise HTTPException(400, f"video_model must be one of {sorted(allowed)}")
    work_dir = os.path.join(db.DATA, "driving", song["slug"])
    stamp = int(time.time() * 1000)
    motion_path = await save_driving_video(ref_motion, work_dir, f"motion_{stamp}")
    control_path = await save_driving_video(control_video, work_dir, f"control_{stamp}")
    if video_model == "i2v" and (motion_path or control_path):
        # WanImageToVideo has neither input; accepting the upload and ignoring
        # it would look like it worked
        raise HTTPException(400, "ref_motion and control_video are s2v inputs -- i2v has "
                                  "neither. Switch to s2v or remove the clips.")
    jobs.enqueue("clips", {"song_id": id, "tier": tier, "video_model": video_model,
                            "refine": bool(refine), "ref_motion": motion_path,
                            "control_video": control_path}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/render")
def start_render(id: int, tier: str = Form(...), fade: float = Form(0.0)):
    get_song_or_404(id)
    valid_tier_or_400(tier)
    jobs.enqueue("render_song", {"song_id": id, "tier": tier, "fade": fade}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/audio")
def edit_song_audio(id: int, trim_start: float = Form(0.0), trim_end: BlankFloat = Form(None),
                     gain_db: float = Form(0.0), fade_in: float = Form(0.0), fade_out: float = Form(0.0),
                     prompt: str = Form("")):
    song = get_song_or_404(id)
    # A prompt REPLACES the sliders: a local model reads the instruction and
    # fills in the same five parameters, which are then clamped by exactly the
    # same validation. The model never touches audio -- what runs is ffmpeg.
    prompt, note, model = (prompt or "").strip(), "", ""
    if prompt:
        try:
            duration = mixer.probe(song["mp3_path"])["duration"] if song["mp3_path"] else 0.0
        except Exception:
            duration = song["duration"] or 0.0
        try:
            params, note, model = vision.read_edit_instruction(prompt, duration)
        except Exception as e:
            raise HTTPException(502, f"could not read that instruction: {e}") from None
        trim_start, trim_end = params["trim_start"], params["trim_end"]
        gain_db, fade_in, fade_out = params["gain_db"], params["fade_in"], params["fade_out"]
    trim_start, trim_end, gain_db, fade_in, fade_out = clamp_audio_edit_params(
        trim_start, trim_end, gain_db, fade_in, fade_out)
    # record the true original exactly once, before mp3_path can ever move --
    # this is what "revert to original" restores.
    if not db.one("SELECT id FROM assets WHERE song_id=? AND kind='audio_original'", id):
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               id, "audio_original", song["mp3_path"], None, time.time())
    jobs.enqueue("edit_audio", {"song_id": id, "trim_start": trim_start, "trim_end": trim_end,
                                 "gain_db": gain_db, "fade_in": fade_in, "fade_out": fade_out,
                                 "prompt": prompt, "note": note, "model": model}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


# Form sanity bounds, and NOT the model's limits -- ACE-Step's own
# TextEncodeAceStepAudio publishes `lyrics` as a plain multiline STRING with no
# declared maximum, so there is no number to read off the box and none is
# invented here. These exist so a paste accident or a hostile field cannot
# occupy a GPU for an hour; where the model actually truncates is unmeasured.
MAX_TAGS = 600
MAX_LYRICS = 10000
MAX_AUDIO_SECS = 240.0
MAX_AUDIO_TAKES = 4


@app.post("/songs/{id}/audio/generate")
def generate_audio(id: int, tags: str = Form(""), lyrics: str = Form(""),
                   seconds: float = Form(30.0), n: int = Form(1),
                   seed: str = Form(""), denoise: float = Form(1.0),
                   from_current: str = Form(""),
                   bridge_start: str = Form(""), bridge_end: str = Form("")):
    """Queue an ACE-Step take for this song.

    Deliberately NOT screened by tiers.check_text: the image guardrail is off
    the audio path on purpose (it refused nursery rhymes), and ACE-Step reads
    tags as musical style tokens, so wording about what must not be DEPICTED is
    noise there at best. The bounds below are the only thing this route asserts.
    """
    song = get_song_or_404(id)
    tags = " ".join((tags or "").split())
    # Form("") and not Form(...): an empty value for a REQUIRED form field is
    # reported by FastAPI as "field required" and answered 422 before any
    # handler code runs, so the check below -- and its message -- would have
    # been unreachable for the one case it exists for. Whitespace-only tags get
    # here either way, so the check is needed regardless of the default.
    if not tags:
        raise HTTPException(400, "a take needs at least one style tag")
    for value, bound, what in ((tags, MAX_TAGS, "tags"), (lyrics or "", MAX_LYRICS, "lyrics")):
        if len(value) > bound:
            raise HTTPException(400, f"{what} is {len(value)} characters; keep it under {bound}")
    # Replacing a span is the only thing here that is an EDIT of this track
    # rather than a new one, so it computes its own length and ignores the
    # seconds box: the bridge has to be the gap PLUS the two crossfades that
    # will be eaten joining it, or the song comes back shorter than it went in.
    span = None
    if (bridge_start or "").strip() or (bridge_end or "").strip():
        if not song["mp3_path"] or not os.path.exists(song["mp3_path"]):
            raise HTTPException(400, "this song has no audio to splice into")
        try:
            span = {"start": float(bridge_start), "end": float(bridge_end)}
        except ValueError:
            raise HTTPException(400, "the span needs a start and an end, in seconds") from None
        if span["end"] <= span["start"] or span["start"] < 0:
            raise HTTPException(400, "the span must end after it starts")
        # Refuse a span outside the track HERE, not in the job. splice_bridge
        # checks it too and raises -- but it runs after gen_audio, so a typo in
        # the end box would spend a full ACE-Step render on the GPU and then
        # throw the result away. The job's check stays as the backstop for a
        # track that changed length between enqueue and run.
        try:
            duration = mixer.probe(song["mp3_path"])["duration"]
        except Exception:
            duration = None   # unreadable here is the job's problem, not a 500 here
        if duration and span["end"] > duration + 0.001:
            raise HTTPException(400, f"the span ends at {span['end']:g}s but the track is "
                                     f"only {duration:.1f}s long")
        # mixer owns this arithmetic. Computing it here as gap + 2*xfade was
        # wrong for a span touching either edge of the track: that has only ONE
        # seam, so only one crossfade is consumed and the song came back a
        # quarter-second long. A review caught it; the fix is to stop having two
        # places that both think they know.
        try:
            seconds = mixer.bridge_seconds(song["mp3_path"], span["start"], span["end"])
        except Exception:
            seconds = (span["end"] - span["start"]) + 2 * mixer.SPLICE_XFADE
    if not 1.0 <= seconds <= MAX_AUDIO_SECS:
        raise HTTPException(400, f"seconds must be between 1 and {MAX_AUDIO_SECS:g}")
    if not 1 <= n <= MAX_AUDIO_TAKES:
        raise HTTPException(400, f"takes must be between 1 and {MAX_AUDIO_TAKES}")
    if not 0.0 < denoise <= 1.0:
        raise HTTPException(400, "denoise must be above 0 and at most 1.0")
    args = {"song_id": id, "tags": tags, "lyrics": lyrics or "", "seconds": float(seconds),
            "n": int(n), "denoise": float(denoise)}
    if span:
        args["bridge"] = span
    if (seed or "").strip():
        try:
            args["seed"] = int(seed)
        except ValueError:
            raise HTTPException(400, "seed must be a whole number, or blank for random") from None
    if from_current:
        # The two are alternatives, and the form presents them as such -- but
        # nothing stopped both being filled in, and the result was a bridge
        # re-synthesised from the whole track spliced back into that same track,
        # labelled "bridged" with the seeding lost from the label. Refuse it.
        if span:
            raise HTTPException(400, "replace a span OR re-synthesise the whole track, "
                                     "not both in one take")
        # Re-synthesising takes the song's CURRENT audio as the starting point,
        # and produces a whole new track rather than a patched one.
        if not song["mp3_path"] or not os.path.exists(song["mp3_path"]):
            raise HTTPException(400, "this song has no audio to re-synthesise from")
        if denoise >= 1.0:
            raise HTTPException(400, "re-synthesising needs a denoise below 1.0; at 1.0 the "
                                     "source is ignored entirely and it is a plain generation")
        args["source_path"] = song["mp3_path"]
    # Record the true original before any take can be pressed into use, exactly
    # as the edit route does. Without this, using a generated take as the song's
    # audio on a song that had never been EDITED left nothing for revert to
    # restore -- the upload would still be on disk with nothing pointing at it.
    if song["mp3_path"] and not db.one(
            "SELECT id FROM assets WHERE song_id=? AND kind='audio_original'", id):
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               id, "audio_original", song["mp3_path"], None, time.time())
    jobs.enqueue("audio", args, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/audio/{asset_id}/use")
def use_audio_edit(id: int, asset_id: int):
    get_song_or_404(id)
    # Both kinds, one route. A generated take and an edit are both "an audio
    # file this song could use", and a second near-identical route is how the
    # two drift apart -- revert still restores audio_original either way.
    asset = db.one("SELECT * FROM assets WHERE id=? AND song_id=? "
                   "AND kind IN ('audio_edit','audio_gen')", asset_id, id)
    if not asset:
        raise HTTPException(404, "no such audio edit")
    db.run("UPDATE songs SET mp3_path=? WHERE id=?", asset["path"], id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/audio/revert")
def revert_audio(id: int):
    get_song_or_404(id)
    original = db.one("SELECT * FROM assets WHERE song_id=? AND kind='audio_original' ORDER BY id LIMIT 1", id)
    if not original:
        raise HTTPException(400, "no original recorded for this song")
    db.run("UPDATE songs SET mp3_path=? WHERE id=?", original["path"], id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/delete")
def delete_song(request: Request, id: int, confirm: str = Form("")):
    get_song_or_404(id)
    if confirm != "DELETE":
        raise HTTPException(400, "confirm=DELETE is required to delete a song")
    if db.one("SELECT id FROM jobs WHERE song_id=? AND status IN ('queued','running')", id):
        raise HTTPException(409, "a job is queued or running for this song")
    for path in _song_file_paths(id):
        if _within_data(path):
            try:
                os.remove(path)
            except OSError:
                pass
    # remove the now-empty per-song directories. rmdir, never rmtree: it fails
    # rather than recursing if anything unexpected is still in there, and the
    # same containment rule applies as for the files themselves.
    song = db.one("SELECT slug FROM songs WHERE id=?", id)
    if song:
        for sub in ("uploads", "storyboards", "renders", "audio"):
            d = os.path.join(db.DATA, sub, song["slug"])
            if _within_data(d) and os.path.isdir(d):
                try:
                    os.rmdir(d)
                except OSError:
                    pass          # not empty: leave it, deleting more is not our call

    db.delete_song_rows(id)
    if wants_json(request):
        return JSONResponse({"deleted": id})
    return RedirectResponse("/", status_code=303)


# -------------------------------------------------------------- playlists --

# Default album-profile text. Neutral on purpose: it describes a character
# sheet, not a character. Every field is editable per album in the UI, which is
# where anything album-specific belongs -- make_anchor.py and build_refs.py used
# to carry one project's protagonist in their source.
# (label, default, hint). The hints are the hard-won findings from this
# project's own render logs, put where the text is actually typed -- every one
# of them is something that cost a regeneration to learn.
ALBUM_FIELDS = {
    "style_text": (
        "Overarching theme",
        "The look and mood of the whole album, in a sentence or two.",
        "The first thing the storyboard model is told about this release."),
    "identity": (
        "Character identity",
        "Head, face and hair come from the identity image; keep that identity exactly.",
        "Name every feature that must not drift between frames: eye colour and shape, ear "
        "shape, hair length and colour, markings, build. Anything you leave unsaid is free "
        "to change from clip to clip."),
    "wardrobe": (
        "Wardrobe",
        "The outfit and accessories of the wardrobe image, same hardware and materials.",
        "Say what is WORN, never what is absent: at cfg 1.0 the negative prompt is skipped "
        "entirely, so \"no jacket\" does nothing. Name garments, cut and hardware."),
    "body": (
        "Body consistency",
        # WORD FOR WORD make_anchor.DEFAULT_BODY, asserted by
        # test_no_positive_prompt_constant_tries_to_negate. This default was the
        # negating wording ("...with no lighter or differently-toned patches
        # anywhere") for as long as the constant was, and it OUTLIVED the fix:
        # album_profile() fills every field from these defaults, so a truthy body
        # value always reaches anchor_from() and always wins over the constant.
        # T4-11's positive nine-part clause was therefore unreachable for every
        # album in the database, and what rendered was the exact sentence
        # _NEGATION_ALLOWED was emptied to forbid. Two copies of one fact, and
        # the studio held the one that ships.
        "Her entire body from shoulders to feet carries the same colouring and texture as her "
        "face, uniform in shade on shoulders, upper arms, forearms, hands, torso, hips, thighs, "
        "calves and feet, every part the same single tone.",
        "Re-assert colouring PER BODY PART. One mention at the top does not hold below the "
        "waist -- this is the fix for a black-furred character rendering with human-toned "
        "legs, and it has to be positive wording, not a negative."),
    # The studio backdrop and the multi-reference clause. Both were constants in
    # make_anchor with no override and no history, and both reach every sheet:
    # BACKDROP is the studio, the lighting lock and the framing in one string,
    # COMPOSITE is what stops three photographs of one character rendering as
    # three people. Defaults are WORD FOR WORD make_anchor.BACKDROP and
    # make_anchor.COMPOSITE, asserted by
    # test_no_positive_prompt_constant_tries_to_negate -- the body clause is
    # already one lesson in what two copies of one sentence cost.
    # docs/TRD-7 T7-14, T7-15.
    "backdrop": (
        "Backdrop and framing",
        "The background is one flat sheet of neutral mid-grey, evenly lit and completely empty, "
        "with the floor the same unbroken grey as the wall behind her and a soft contact shadow "
        "under her feet. She stands upright and unsupported in an empty studio, clear of the "
        "edges of the frame. Even neutral studio lighting, white balanced, daylight colour "
        "temperature, the same light on both sides of her. Clean neutral studio character "
        "sheet, crisp air, sharp focus, high detail, full body head to toe inside the frame.",
        "Reaches every sheet, so it is the widest-acting text here. Say what IS there: the "
        "absences that belong to a backdrop (no smoke, no scenery) go in the negative prompt "
        "on the Anchors page, and naming them here draws them -- that is not a rule of thumb, "
        "it put smoke round the edge of every sheet this studio rendered for a month."),
    "composite": (
        "Multiple references",
        "All of the reference images show the SAME single character from different angles or in "
        "different outfits. Combine them into one coherent character: exactly one figure, alone "
        "in the frame, standing by herself.",
        "Used only when more than one base image is attached. Without it several unlabelled "
        "references read as several PEOPLE and the sheet comes back as a group shot."),
    # The nude swap, per album, because the default is wrong for anything that
    # is not bare-skinned. make_anchor's own default says "bare skin over the
    # whole body", which on a furred character lands in the same prompt as
    # "her entire body is covered in the same sleek jet-black fur" -- two
    # contradictory instructions, and a fixed-seed CFG sweep measured the model
    # resolving them towards SKIN harder the higher the guidance went.
    "nude_wardrobe": (
        "Nude wording",
        "",
        "Replaces the wardrobe sentence on nude sheets only. Say the character is unclothed "
        "WITHOUT saying what her surface is -- the body wording above already owns that. "
        "\"Bare skin over the whole body\" is the default and it fights a furred or scaled "
        "body clause; leave this blank only if the character really is bare-skinned."),
    "anatomy": (
        "Anatomy on nude sheets",
        "",
        "What a nude sheet DEPICTS, as opposed to what it omits. Nothing here filters "
        "anatomical language -- the only input filter refuses references to minors -- but "
        "permitting explicit content is not the same as asking for it, and a nude prompt "
        "that only lists absent clothing comes back featureless because nothing requested "
        "otherwise. Applies to nude views only, and only where the tier permits nudity."),
    "world": (
        "World",
        "The recurring places this album's videos happen in.",
        "Goes to the storyboard model as this album's world. List real, distinct "
        "locations: scenes rotate through them, and that is what stops every frame "
        "being the same corridor in the same purple light."),
    "render_tail": (
        "Render style",
        "photorealistic cinematic frame, premium music video still, high detail, 16:9",
        "Part of the look handed to the storyboard model, which writes it into each "
        "scene's image prompt. Medium, quality and aspect only -- no subject."),
}

# Fields the wand can draft from a look at the album's anchor image.
DESCRIBABLE = ("identity", "wardrobe", "body")

# EVERYTHING make_anchor.prompt_for composes from. The form edits these, the run
# records them and gen_anchor ships them as one profile dict -- so a field
# missing from this tuple is a field whose edit reaches nothing.
ANCHOR_PROFILE_FIELDS = ("identity", "wardrobe", "body", "nude_wardrobe", "anatomy",
                         "backdrop", "composite", "pose", "views")


# NOTHING is taken from the global profile FILE any more, and that is a
# deliberate reversal of an earlier fix in this same session.
#
# The parallel session reported that profiles/street_cats.json defines its own
# `views` -- per-character framing sentences -- which h_anchor never shipped, so
# every sheet used make_anchor's generic defaults. True. I wired it through, and
# the critic then reproduced the other half of the same fact: STUDIO_PROFILE is
# ONE file for the whole studio, that file's views read "FRONT VIEW character
# reference sheet of a single adult anthropomorphic black feline woman", and
# `views` has no database column and no UI -- so wiring it welded one album's
# SPECIES into every other album's clothed sheets with no way to change it.
#
# Both reports are right; the wiring was wrong. An album owns its wording
# through its own columns (identity, wardrobe, body, nude_wardrobe, anatomy) and
# the framing stays species-neutral in make_anchor.DEFAULT_VIEWS. That also
# leaves render output exactly as every anchor in this database was made --
# those sentences never reached the renderer, so nothing regresses.
#
# Per-album view framing is a real feature and this is where it would go: four
# columns and four boxes, at which point the album overrides the default the way
# every other field does. It is not a global.


def anchor_profile_fields(album, character_id=None):
    """The composer's fields for one album and character, in precedence order:
    the character's own wording, then the album's, then the profile file's.

    One function, because the preview, the run record and the render must all
    compose from the same values -- the recurring defect in this codebase is the
    editor showing something the renderer does not build.
    """
    prof = album_profile(album)
    out = {}
    for key in ANCHOR_PROFILE_FIELDS:
        if key == "views":
            continue          # framing is make_anchor's, and species-neutral
        value = prof.get(key)
        if value:
            out[key] = value
    if character_id:
        # a cast member's sheet describes THAT character; anything they leave
        # blank falls back to the album's, so a supporting character still
        # inherits the body-consistency rule
        char = db.one("SELECT * FROM characters WHERE id=?", character_id)
        if char:
            # EVERY composer field, not just the first three. A cast member
            # who leaves one blank still falls back to the album's, so a
            # supporting character keeps inheriting the body-consistency rule --
            # but a duet partner of a different species no longer inherits the
            # lead's nude wording and anatomy.
            for key in ANCHOR_PROFILE_FIELDS:
                if key == "views":
                    continue
                if key in char.keys() and char[key]:
                    out[key] = char[key]
    # T7-13: latest view:<key> version overlays the table framing. playlists.views
    # stays ignored — that column welded one album's species into every other.
    overlays = {}
    for vkey in make_anchor.VIEWS:
        # album first, then this character — same fallback as identity/wardrobe
        row = prompts.latest(album, f"view:{vkey}", character_id=None)
        if character_id:
            own = prompts.latest(album, f"view:{vkey}", character_id=character_id)
            if own and own["text"]:
                row = own
        if row and row["text"]:
            overlays[vkey] = row["text"]
    if overlays:
        out["views"] = overlays
    # T7-16: latest pose version, album then this character. No playlists.pose
    # column — the type is versioned like view:<key>, not a profile field.
    pose_row = prompts.latest(album, "pose", character_id=None)
    if character_id:
        own_pose = prompts.latest(album, "pose", character_id=character_id)
        if own_pose and own_pose["text"]:
            pose_row = own_pose
    if pose_row and pose_row["text"]:
        out["pose"] = pose_row["text"]
    return {k: v for k, v in out.items() if v}


def album_profile(name):
    """The album's profile row, defaults filled in for anything blank.

    An album and a playlist are the same record: the playlist whose name is the
    song's album. Songs carry the album as text, and anchors are already scoped
    by that same name, so nothing new has to be linked up.
    """
    row = db.one("SELECT * FROM playlists WHERE name=? AND kind='playlist'", name or "")
    out = {}
    for key, (_label, default, _hint) in ALBUM_FIELDS.items():
        value = (row[key] if row and row[key] else "") or default
        out[key] = value
    out["_row"] = row
    return out


def playlist_detail(p):
    """One playlist card: its songs in order, each with length and whatever
    videos exist for it, plus the totals the collapsed card shows."""
    items = db.q("""SELECT pi.*, s.title AS song_title, s.slug AS song_slug,
                            s.duration AS duration, s.mp3_path AS mp3_path
                     FROM playlist_items pi JOIN songs s ON s.id = pi.song_id
                     WHERE pi.playlist_id=? ORDER BY pi.position""", p["id"])
    rows, total, tiers_with_video = [], 0.0, {}
    for it in items:
        # every rendered video for this song, newest first per tier -- this is
        # what makes a set renderable at a given tier, and what the card offers
        # to play next to the track itself
        videos = {}
        for r in db.q("SELECT * FROM renders WHERE song_id=? ORDER BY id DESC", it["song_id"]):
            videos.setdefault(r["tier"], r["path"])
        total += it["duration"] or 0.0
        for t in videos:
            tiers_with_video[t] = tiers_with_video.get(t, 0) + 1
        rows.append({"item": it, "videos": sorted(videos.items())})
    # a tier can render a set only if EVERY song in the playlist has a video
    # at that tier; offering one that cannot render just moves the failure
    ready = sorted(t for t, n in tiers_with_video.items() if n == len(items)) if items else []
    sets = [a for a in db.q("SELECT * FROM assets WHERE kind='set' ORDER BY id DESC")
            if db.jset(a).get("playlist_id") == p["id"]]
    # the album profile, as (key, label, current value) for the form
    prof = album_profile(p["name"])
    profile_fields = [{"key": k, "label": ALBUM_FIELDS[k][0], "value": prof[k],
                       "hint": ALBUM_FIELDS[k][2], "wand": k in DESCRIBABLE}
                      for k in ALBUM_FIELDS]
    anchor_tiers, all_anchors = album_anchor_tiers(p["name"])
    # how many sheets each character has, for the filter -- an anchor you cannot
    # find among fifty is one you will regenerate rather than reuse
    per_character = {}
    for a in all_anchors:
        per_character[a["character_name"] or "protagonist"] = \
            per_character.get(a["character_name"] or "protagonist", 0) + 1
    # the cast, with how many anchors each has -- an unanchored character is the
    # thing worth seeing here, since naming one in a scene achieves nothing
    cast = []
    for c in album_cast(p["name"]):
        n = db.one("SELECT COUNT(*) n FROM anchors WHERE character_id=? AND chosen=1", c["id"])["n"]
        cast.append({"c": c, "anchors": n})
    has_anchor = bool(db.one("""SELECT id FROM anchors WHERE scope_kind='album' AND scope_value=?
                                 AND chosen=1 AND character_id IS NULL""", p["name"]))
    artwork_default = models.default_for("artwork")
    artwork_models = [{"key": e["key"], "label": e["label"], "available": e["available"],
                       "default": e["key"] == artwork_default}
                      for e in models.catalog(role="artwork")]
    return {"playlist": p, "rows": rows, "count": len(items), "total_secs": total,
            "video_tiers": ready, "sets": sets, "profile_fields": profile_fields,
            "anchors": all_anchors, "anchor_tiers": anchor_tiers,
            "anchor_count": len(all_anchors),
            "anchor_characters": sorted(per_character.items()),
            "character_count": len(per_character) or 1,
            "artwork_models": artwork_models, "has_anchor": has_anchor,
            "cast": cast, "character_fields": CHARACTER_FIELDS,
            "copyable_fields": COPYABLE_CHARACTER_FIELDS,
            "partial_tiers": sorted(t for t in tiers_with_video if t not in ready)}


@app.get("/playlists", response_class=HTMLResponse)
def playlists_page(request: Request):
    # 'genre' rows can still exist in the db (a legacy row, or one inserted
    # directly rather than through this route) -- only 'playlist' rows are
    # listed here; genres belong on the song now, not as a playlist kind.
    playlists = db.q("SELECT * FROM playlists WHERE kind='playlist' ORDER BY name")
    songs = db.q("SELECT * FROM songs ORDER BY title")
    return templates.TemplateResponse(request, "playlists.html", {
        "playlists": [playlist_detail(p) for p in playlists], "songs": songs})


@app.post("/playlists")
async def create_playlist(name: str = Form(...), kind: str = Form("playlist"),
                           image: Optional[UploadFile] = File(None)):
    # Genres are set on the song at upload now (genre/subgenre/genre2/subgenre2
    # columns) -- 'genre' is no longer a creatable playlist kind.
    if kind != "playlist":
        raise HTTPException(400, "kind must be 'playlist'")
    name = name.strip()
    if not name:
        raise HTTPException(400, "name required")
    try:
        pid = db.run("INSERT INTO playlists (name, kind, created) VALUES (?,?,?)",
                     name, kind, time.time())
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"playlist '{name}' ({kind}) already exists")
    # the cover at creation, so setting one is not a second trip through the page
    if image is not None and image.filename:
        dest = await save_upload(image, MAX_IMAGE, os.path.join(db.DATA, "playlists", str(pid)),
                                  "image", prefix="cover")
        db.run("UPDATE playlists SET image_path=? WHERE id=?", dest, pid)
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{id}/image")
async def set_playlist_image(id: int, image: UploadFile = File(...)):
    """Cover art for the playlist card."""
    get_playlist_or_404(id)
    dest = await save_upload(image, MAX_IMAGE, os.path.join(db.DATA, "playlists", str(id)),
                              "image", prefix="cover")
    db.run("UPDATE playlists SET image_path=? WHERE id=?", dest, id)
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{id}/profile")
async def save_album_profile(id: int, request: Request):
    """The album's look: identity, wardrobe, body, world, render style, theme.

    Accepts only the known keys, so the form cannot write arbitrary columns.
    A field left exactly at its default is stored as NULL rather than a copy,
    so changing a default later still reaches every album that never edited it.
    """
    get_playlist_or_404(id)
    form = await request.form()
    # Screened before anything is written. Every one of these fields is composed
    # into an anchor prompt, and this was the only free-text path in the studio
    # that reached a render with no check_text, no check_override and no length
    # bound -- and it is the widest-reaching one, because an album's profile is
    # inherited by every sheet and every cast member who copies from it.
    values = {key: screen_prompt_field((form.get(key) or "").strip(), key, "album")
              for key in ALBUM_FIELDS if key in form}
    for key, (_label, default, _hint) in ALBUM_FIELDS.items():
        if key not in values:
            continue
        value = values[key]
        db.run(f"UPDATE playlists SET {key}=? WHERE id=?",
               None if not value or value == default else value, id)
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{id}/describe", response_class=HTMLResponse)
def describe_album_field(request: Request, id: int, field: str = Form(...)):
    """Wand: draft one profile field by looking at this album's anchor.

    Synchronous rather than a job: it is one call, the user is staring at the
    box waiting for it, and a queued job would land behind an hour of rendering.
    Nothing is saved -- the text lands in the textarea for editing, and the
    existing Save button is still what writes it.
    """
    p = get_playlist_or_404(id)
    if field not in DESCRIBABLE:
        raise HTTPException(400, f"cannot describe {field!r}")
    anchor = db.one("""SELECT * FROM anchors WHERE scope_kind='album' AND scope_value=?
                       ORDER BY chosen DESC, (view='front') DESC, id DESC LIMIT 1""", p["name"])
    if not anchor:
        raise HTTPException(400, f"no anchor for album '{p['name']}' yet -- generate one first")
    try:
        text = vision.describe_anchor(anchor["path"], field)
    except Exception as e:
        raise HTTPException(502, f"could not describe the anchor: {e}") from None
    label, _default, hint = ALBUM_FIELDS[field]
    return templates.TemplateResponse(request, "_album_field.html", {
        "playlist": p,
        "f": {"key": field, "label": label, "value": text, "hint": hint, "wand": True}})


@app.post("/playlists/{id}/fill", response_class=HTMLResponse)
def fill_album_look(request: Request, id: int):
    """Draft every describable field at once by reading the album COVER.

    The wand does one field from the anchor; this does the set from the cover,
    which is the image that exists first. Nothing is saved -- the text lands in
    the boxes and the existing Save button is still what writes it.
    """
    p = get_playlist_or_404(id)
    if not p["image_path"] or not os.path.isfile(p["image_path"]):
        raise HTTPException(400, "this album has no cover image yet -- upload one first")
    prof = album_profile(p["name"])
    fields = []
    for key in ALBUM_FIELDS:
        label, _default, hint = ALBUM_FIELDS[key]
        value = prof[key]
        if key in DESCRIBABLE:
            try:
                drafted = vision.describe_cover(p["image_path"], key)
            except Exception as e:
                raise HTTPException(502, f"could not read the cover: {e}") from None
            # an empty answer means the cover does not show it -- keep what is
            # already there rather than blanking a field that was filled in
            value = drafted or value
        fields.append({"key": key, "label": label, "value": value, "hint": hint,
                       "wand": key in DESCRIBABLE})
    return templates.TemplateResponse(request, "_album_look_form.html",
                                       {"playlist": p, "profile_fields": fields})


@app.post("/playlists/{id}/propose-cast", response_class=HTMLResponse)
def propose_cast(request: Request, id: int):
    """Look at the album cover and draft ONE supporting character.

    One, not a whole cast: each named character costs a reference slot at render
    time (three images total, the protagonist holds the first), so proposing
    five would be proposing three that can never be attached.
    """
    p = get_playlist_or_404(id)
    if not p["image_path"] or not os.path.isfile(p["image_path"]):
        raise HTTPException(400, "this album has no cover image yet -- upload one first")
    try:
        proposed = vision.propose_character(p["image_path"])
    except Exception as e:
        raise HTTPException(502, f"could not read the cover: {e}") from None
    # screened before it reaches a form, exactly as typed text is on submit
    try:
        for k, v in proposed.items():
            tiers.check_text(v, f"proposed character {k}")
    except ValueError as e:
        raise HTTPException(502, f"the model proposed something that cannot be used: {e}") from None
    where, _detail = vision.available()
    return templates.TemplateResponse(request, "_cast_form.html",
                                       {"playlist": p, "proposed": proposed,
                                        "proposed_backend": where})


@app.post("/playlists/{id}/artwork")
def create_album_artwork(id: int, model: str = Form(""), use_anchor: bool = Form(False),
                          from_cover: bool = Form(False), instruction: str = Form("")):
    """Generate a new album cover from the album look.

    The reverse of Fill: those fields were written to describe the character,
    and this renders them. Uses the album's chosen anchor as a reference when
    there is one, so the cover shows the actual protagonist rather than a
    lookalike the model invented from the same words.
    """
    p = get_playlist_or_404(id)
    wired = models.renderable("artwork")
    key = model or models.default_for("artwork")
    if key not in wired:
        raise HTTPException(400, f"'{key}' is not an artwork model that can render yet")
    instruction = (instruction or "").strip()
    if len(instruction) > MAX_INSTRUCTION:
        raise HTTPException(400, f"the instruction is {len(instruction)} characters; keep it "
                                  f"under {MAX_INSTRUCTION}")
    try:
        tiers.check_text(instruction, "artwork instruction")
        tiers.check_override(instruction)
    except ValueError as e:
        raise HTTPException(400, str(e))
    anchor = db.one("""SELECT * FROM anchors WHERE scope_kind='album' AND scope_value=?
                       AND chosen=1 AND character_id IS NULL
                       ORDER BY (view='front') DESC, id DESC LIMIT 1""", p["name"])
    # THREE modes, and none of them is required:
    #   use_anchor  the cover shows this album's actual protagonist
    #   from_cover  the existing cover is a second reference, so the prompt
    #               MODIFIES it rather than starting over
    #   neither     plain text-to-image from the album look alone
    anchor_path = anchor["path"] if (anchor and use_anchor) else None
    source_path = p["image_path"] if (from_cover and p["image_path"]
                                       and os.path.isfile(p["image_path"])) else None
    if from_cover and not source_path:
        raise HTTPException(400, "there is no existing cover to modify -- upload one, or "
                                  "untick 'modify the current cover'")
    if use_anchor and not anchor:
        raise HTTPException(400, "this album has no chosen anchor yet -- generate and pick "
                                  "one on /anchors, or untick 'use the album anchor'")
    jobs.enqueue("artwork", {"playlist_id": id, "model": key, "anchor_path": anchor_path,
                             "source_path": source_path, "instruction": instruction,
                             "tier": anchor["tier"] if anchor else ""})
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{id}/delete")
def delete_playlist(id: int, confirm: str = Form("")):
    """Delete the playlist and its membership rows.

    Songs, renders and everything generated stay: a playlist is an ordering,
    not the material. Only the cover image, which nothing else references, is
    removed -- and only if it resolves inside db.DATA.
    """
    p = get_playlist_or_404(id)
    if confirm != "DELETE":
        raise HTTPException(400, "deleting a playlist requires confirm=DELETE")
    if p["image_path"] and _within_data(p["image_path"]) and os.path.isfile(p["image_path"]):
        os.remove(p["image_path"])
    db.run("DELETE FROM playlist_items WHERE playlist_id=?", id)
    db.run("DELETE FROM playlists WHERE id=?", id)
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{id}/items")
def add_playlist_item(id: int, song_id: int = Form(...),
                       transition: str = Form("fade"), secs: float = Form(2.0)):
    # No tier: membership is the song. Which tier's video (if any) is used is
    # decided when the set is rendered.
    get_playlist_or_404(id)
    get_song_or_404(song_id)
    pos_row = db.one("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM playlist_items WHERE playlist_id=?", id)
    db.run("""INSERT INTO playlist_items (playlist_id, song_id, position, transition, secs)
              VALUES (?,?,?,?,?)""", id, song_id, pos_row["p"], transition, secs)
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{id}/items/{item_id}/delete")
def remove_playlist_item(id: int, item_id: int):
    get_playlist_or_404(id)
    db.run("DELETE FROM playlist_items WHERE id=? AND playlist_id=?", item_id, id)
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{id}/reorder")
def reorder_playlist(id: int, order: str = Form(...)):
    get_playlist_or_404(id)
    ids = [int(x) for x in order.split(",") if x.strip().isdigit()]
    for pos, item_id in enumerate(ids):
        db.run("UPDATE playlist_items SET position=? WHERE id=? AND playlist_id=?", pos, item_id, id)
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{id}/arc")
def start_arc(id: int, direction: str = Form(""), backend: str = Form(""),
              model: str = Form("")):
    """Queue the album's story arc. One job, one request, every track."""
    pl = get_playlist_or_404(id)
    try:
        direction = arc.check_direction(direction)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not db.one("SELECT 1 FROM playlist_items WHERE playlist_id=?", id):
        raise HTTPException(400, "this album has no songs yet -- add some first")
    if backend:
        try:
            chat.resolve(backend)
        except ValueError as e:
            raise HTTPException(400, str(e))
    elif not chat.available():
        raise HTTPException(400, "no chat backend has an API key -- set one on the Config page")
    # A model belongs to ONE backend. The form offers both lists in one select,
    # so picking xai beside an OpenAI model would send that name straight to xAI
    # (grok._resolve_model returns whatever it is given) and fail at job-run time
    # on a submission the page accepted.
    if model:
        target = backend or chat.resolve(None)
        allowed = chat.list_models(target)
        if allowed and model not in allowed:
            raise HTTPException(400, f"{model!r} is not a {target} model -- pick one from the "
                                      f"{target} group, or change the backend.")
    jobs.enqueue("arc", {"playlist_id": id, "direction": direction,
                          "backend": backend or None, "model": model or None})
    return RedirectResponse(f"/playlists/{id}/arc", status_code=303)


@app.get("/playlists/{id}/arc", response_class=HTMLResponse)
def view_arc(request: Request, id: int):
    pl = get_playlist_or_404(id)
    row = db.one("SELECT * FROM arcs WHERE playlist_id=?", id)
    data, md = {}, ""
    if row and row["json_path"] and os.path.isfile(row["json_path"]):
        with open(row["json_path"]) as f:
            data = json.load(f)
    if row and row["md_path"] and os.path.isfile(row["md_path"]):
        md = open(row["md_path"]).read()
    titles = {r["id"]: r["title"] for r in db.q(
        """SELECT s.id, s.title FROM playlist_items pi JOIN songs s ON s.id = pi.song_id
           WHERE pi.playlist_id=? ORDER BY pi.position""", id)}
    # Every chat model each backend will actually accept, so the arc is not
    # locked to whatever is pinned beside the key. The pinned one is shown as
    # the default rather than hidden, because "which model wrote this" is the
    # first question asked of any arc that reads badly.
    have = chat.available()
    models = {b: chat.list_models(b) for b in have}
    defaults = {}
    for b in have:
        try:
            defaults[b] = chat.openai_model() if b == "openai" else grok._resolve_model(None)
        except Exception:
            defaults[b] = ""
    return templates.TemplateResponse(request, "arc.html", {
        "playlist": pl, "arc": data, "row": row, "md": md, "titles": titles,
        "backends": have, "models": models, "defaults": defaults})


@app.post("/playlists/{id}/render")
def render_playlist(id: int, include_videos: bool = Form(False), tier: List[str] = Form([])):
    """Render the set.

    Without videos it is an audio mix: one mp3, crossfaded by each item's
    transition. With videos it is one SET PER SELECTED TIER -- a playlist has
    no tier of its own, so rendering at r and pg13 is two outputs from the one
    ordering, the same shape as generating references for several tiers.
    """
    get_playlist_or_404(id)
    items = db.q("""SELECT pi.*, s.mp3_path AS mp3_path, s.title AS title
                     FROM playlist_items pi JOIN songs s ON s.id = pi.song_id
                     WHERE pi.playlist_id=? ORDER BY pi.position""", id)
    if not items:
        # mixer raises on an empty list, so this used to enqueue a job whose
        # only purpose was to fail. Refuse where the user can see it.
        raise HTTPException(400, "this playlist has no songs yet -- add one first")

    if not include_videos:
        missing = [it["title"] for it in items if not it["mp3_path"]]
        if missing:
            raise HTTPException(400, f"no audio for: {', '.join(missing)}")
        mix = [{"audio": it["mp3_path"], "transition": it["transition"], "secs": it["secs"]}
               for it in items]
        jobs.enqueue("render_set", {"playlist_id": id, "mode": "audio", "items": mix})
        return RedirectResponse("/playlists", status_code=303)

    selected = sorted(set(tier))
    if not selected:
        raise HTTPException(400, "select at least one tier to render videos")
    # Validate EVERY tier before enqueuing anything, and name the songs that
    # are missing a video -- half a set is worse than a refusal.
    per_tier = {}
    for t in selected:
        valid_tier_or_400(t)
        build, missing = [], []
        for it in items:
            row = db.one("SELECT * FROM renders WHERE song_id=? AND tier=? ORDER BY id DESC LIMIT 1",
                          it["song_id"], t)
            if not row:
                missing.append(it["title"])
            else:
                build.append({"video": row["path"], "transition": it["transition"], "secs": it["secs"]})
        if missing:
            raise HTTPException(400, f"tier '{t}' has no video for: {', '.join(missing)}")
        per_tier[t] = build
    for t, build in per_tier.items():
        jobs.enqueue("render_set", {"playlist_id": id, "mode": "video", "tier": t, "items": build})
    return RedirectResponse("/playlists", status_code=303)


# ------------------------------------------------------------------ tiers --

@app.get("/tiers", response_class=HTMLResponse)
def tiers_page(request: Request):
    return templates.TemplateResponse(request, "tiers.html", {
        "tiers": tiers.all_tiers(), "mpa_notes": tiers.MPA_NOTE,
        "max_guardrail": tiers.MAX_TIER_GUARDRAIL})


@app.post("/tiers")
def create_tier(name: str = Form(...), guardrail: str = Form(""),
                 allow_nudity: bool = Form(False)):
    try:
        tiers.add_tier(name, guardrail, allow_nudity)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse("/tiers", status_code=303)


@app.post("/tiers/{name}/nudity")
def toggle_tier_nudity(name: str, allow: int = Form(...)):
    """Whether this tier may depict nudity.

    A capability, not prompt text -- it gates whether a NUDE anchor can be
    generated for the tier. What the model is told about nudity comes from the
    tier's wording, so that there is only ever one thing steering it.
    """
    try:
        tiers.set_allow_nudity(name, bool(allow))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse("/tiers", status_code=303)


@app.post("/tiers/{name}/delete")
def remove_tier(name: str):
    try:
        tiers.delete_tier(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse("/tiers", status_code=303)


# ------------------------------------------------------------------ config --

@app.get("/config", response_class=HTMLResponse)
def config_page(request: Request):
    """Where finished work may be published, and what each destination permits.

    Nothing uploads yet. What this page does is record the destinations and
    their policies, and show -- per tier -- exactly which ones would accept a
    render and which would refuse it and why.
    """
    all_tiers = tiers.all_tiers()
    rows = []
    for t in publish.targets():
        svc = publish.service(t["service"]) or {}
        rows.append({"t": t, "svc": svc,
                     "verdicts": [{"tier": x["name"], "refusal": publish.refusal(t, x["name"])}
                                  for x in all_tiers]})
    return templates.TemplateResponse(request, "config.html", {
        "services": publish.SERVICES, "targets": rows, "tiers": all_tiers,
        "recheck": publish.RECHECK,
        "adult_tiers": [t["name"] for t in all_tiers if tiers.allows_nudity(t["name"])],
        "FORBIDDEN": publish.FORBIDDEN, "TAGGED": publish.TAGGED,
        "OPEN": publish.OPEN, "UNKNOWN": publish.UNKNOWN,
        "credentials": creds.status()})


@app.post("/config/credentials")
def set_credential(name: str = Form(...), value: str = Form(...)):
    """Store an API key. WRITE-ONLY: no route ever renders a stored value, so a
    secret cannot be shoulder-surfed out of a page that has no login."""
    try:
        creds.put(name, value)
    except creds.Unavailable as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse("/config", status_code=303)


@app.post("/config/credentials/{name}/clear")
def clear_credential(name: str):
    if name not in creds.PROVIDERS:
        raise HTTPException(404, f"unknown credential {name!r}")
    creds.clear(name)
    return RedirectResponse("/config", status_code=303)


@app.post("/config/targets")
def add_publish_target(service: str = Form(...), name: str = Form(...),
                        adult_ok: bool = Form(False), note: str = Form("")):
    try:
        publish.add_target(service, name, adult_ok, note[:500])
    except ValueError as e:
        raise HTTPException(400, str(e))
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"{name} is already a target for {service}")
    return RedirectResponse("/config", status_code=303)


@app.post("/config/targets/{id}/toggle")
def toggle_publish_target(id: int):
    row = db.one("SELECT * FROM publish_targets WHERE id=?", id)
    if not row:
        raise HTTPException(404, "no such target")
    db.run("UPDATE publish_targets SET enabled=? WHERE id=?", 0 if row["enabled"] else 1, id)
    return RedirectResponse("/config", status_code=303)


@app.post("/config/targets/{id}/adult")
def set_target_adult(id: int, adult_ok: int = Form(...)):
    """Whether THIS destination accepts adult material.

    Refused outright when the service itself forbids it -- a target must never
    be able to claim a permission its service does not grant.
    """
    row = db.one("SELECT * FROM publish_targets WHERE id=?", id)
    if not row:
        raise HTTPException(404, "no such target")
    svc = publish.service(row["service"]) or {}
    if adult_ok and svc.get("adult") == publish.FORBIDDEN:
        raise HTTPException(400, f"{svc.get('label', row['service'])} forbids adult content, "
                                  f"so this target cannot accept it")
    db.run("UPDATE publish_targets SET adult_ok=? WHERE id=?", 1 if adult_ok else 0, id)
    return RedirectResponse("/config", status_code=303)


@app.post("/config/targets/{id}/delete")
def delete_publish_target(id: int):
    db.run("DELETE FROM publish_targets WHERE id=?", id)
    return RedirectResponse("/config", status_code=303)


# -------------------------------------------------------------------- sets --

def get_set_or_404(id):
    row = db.one("SELECT * FROM sets WHERE id=?", id)
    if not row:
        raise HTTPException(404, "no such set")
    return row


def _set_render_row(a):
    """One rendered asset (kind='set'), formatted for display -- shared by the
    shelf (legacy renders with no set of their own) and the editor (renders
    that belong to this set)."""
    meta = db.jset(a)
    missing = not (a["path"] and os.path.isfile(a["path"]))
    size = duration = None
    if not missing:
        size = os.path.getsize(a["path"])
        try:
            duration = mixer.probe(a["path"])["duration"]
        except Exception:
            pass
    return {"asset": a, "mode": meta.get("mode", "video"), "tier": meta.get("tier"),
            "missing": missing, "size": size, "duration": duration,
            "master_chain": meta.get("master_chain")}


def _beatmatch_plan(items, songs, mode):
    """For each item with beatmatch=1 and a next item: snap the transition to
    the nearest downbeat on both sides, and (audio sets only -- video isn't
    time-stretched here; cutting video on the beat is SETS_MIXING_PLAN.md
    phase 5, not this one) plan a tempo ramp toward the incoming track's bpm
    when the stretch is within mixer.MAX_TEMPO_STRETCH. Pure: no db write,
    no ffmpeg call -- used both to render (POST .../render) and to preview
    what render would do (GET /sets/{id}, via set_detail).

    `songs` maps song_id -> a row/dict with bpm, key, beat_grid_json,
    downbeat_offset, mp3_path. Returns {item_id: {out_secs?, in_secs?,
    ramp?, note}} -- out_secs patches THIS item, in_secs patches the NEXT
    one, matching where those fields already live on set_items.
    """
    plan = {}
    for i in range(len(items) - 1):
        it, nxt = items[i], items[i + 1]
        if not it["beatmatch"]:
            continue
        song, next_song = songs.get(it["song_id"]), songs.get(nxt["song_id"])
        entry = plan.setdefault(it["id"], {})
        if not song or not next_song:
            entry["note"] = "song missing"
            continue
        grid = json.loads(song["beat_grid_json"]) if song["beat_grid_json"] else []
        next_grid = json.loads(next_song["beat_grid_json"]) if next_song["beat_grid_json"] else []
        if not grid or not next_grid:
            entry["note"] = "not analysed yet -- run BPM analysis on both songs to beat-match"
            continue
        mp3 = song["mp3_path"]
        full = mixer.probe(mp3)["duration"] if mp3 and os.path.isfile(mp3) else 0.0
        out_point = it["out_secs"] if it["out_secs"] is not None else full
        in_point = nxt["in_secs"] or 0.0
        # snapped_out goes through video_fx.beat_cut_offsets -- the SAME
        # function mixer._apply_beatmatch calls at render time, given the
        # same out_point -- not a separate copy of the nearest-downbeat
        # maths, so this note can never describe a cut the real render
        # doesn't produce. The in-side snap has no render-time counterpart
        # (mixer._apply_beatmatch never touches the NEXT item), so it still
        # uses the plain nearest-downbeat.
        snapped_out, _ = video_fx.beat_cut_offsets(
            grid, song["downbeat_offset"] or 0, float(it["secs"] or 0.0), out_point)
        if snapped_out is None:
            snapped_out = out_point
        snapped_in = mixer.nearest_downbeat(next_grid, next_song["downbeat_offset"] or 0, in_point)
        entry["out_secs"] = snapped_out
        plan.setdefault(nxt["id"], {})["in_secs"] = snapped_in
        if mode != "audio":
            entry["note"] = "snapped to the beat, both sides (video isn't tempo-stretched)"
            continue
        out_bpm, in_bpm = song["bpm"], next_song["bpm"]
        if not mixer.can_beatmatch(out_bpm, in_bpm):
            entry["note"] = (f"snapped only — {out_bpm or '?'}→{in_bpm or '?'} BPM exceeds "
                              f"the {mixer.MAX_TEMPO_STRETCH}x stretch limit, so no tempo ramp")
            continue
        bar_times, ratios = mixer.plan_tempo_ramp(grid, song["downbeat_offset"] or 0,
                                                    snapped_out, out_bpm, in_bpm)
        if ratios:
            in_secs = it["in_secs"] or 0.0
            entry["ramp"] = {"in_secs": in_secs,
                              "bar_times": [b - in_secs for b in bar_times], "ratios": ratios}
            # Applied for real now: mixer._apply_beatmatch plans the ramp in the
            # ONE pass set_duration, render_set and mix_audio all share, and
            # _item_duration prices it via ramped_duration(), so the length the
            # editor predicts is the length that renders (verified end to end to
            # within mp3 frame padding). mix_audio renders the ramp before
            # anything probes, which is what makes the prediction true rather
            # than a claim.
            entry["note"] = (f"snapped to the beat on both sides, and tempo-ramped "
                              f"{out_bpm:.0f}→{in_bpm:.0f} BPM over {len(ratios)} bars")
        else:
            entry["note"] = "snapped on both sides — not enough bars before the transition to ramp"
    return plan


def set_detail(row):
    """Editor context for one set: its items in order, the predicted running
    length, whether it is ready to render video, the beat-matching plan for
    any item that asked for it, a suggested Camelot-adjacency running order,
    and every file ever rendered from it (newest first, so re-rendering
    never hides what you are comparing against -- the same shape as an
    anchor's candidates).
    """
    items = db.q("""SELECT si.*, s.title AS song_title, s.mp3_path AS mp3_path,
                           s.bpm AS song_bpm, s.key AS song_key,
                           s.beat_grid_json AS song_beat_grid_json,
                           s.downbeat_offset AS song_downbeat_offset
                    FROM set_items si LEFT JOIN songs s ON s.id = si.song_id
                    WHERE si.set_id=? ORDER BY si.position""", row["id"])
    # Length is always predicted off the song's own AUDIO: build_song.py cuts
    # every clip to match the track exactly, so the mp3 duration is the set's
    # real running length whether or not this set includes video. Skip items
    # whose mp3 is missing from disk (deleted, moved, or swapped by the
    # audio-edit undo/original-swap feature) -- same guard _set_render_row
    # already applies to its own probe, so a missing file degrades the total
    # instead of 500ing the page the Remove button lives on. A card has no
    # mp3; mixer.set_duration prices card_secs instead.
    mix_items = []
    for it in items:
        if _is_card_row(it):
            mix_items.append(_card_mix_item(it))
        elif it["mp3_path"] and os.path.isfile(it["mp3_path"]):
            mix_items.append({"audio": it["mp3_path"], "transition": it["transition"],
                              "secs": it["secs"], "in_secs": it["in_secs"],
                              "out_secs": it["out_secs"], "hold": _hold_of(it),
                              **_beatmatch_fields(it, {"bpm": it["song_bpm"],
                                                       "beat_grid_json": it["song_beat_grid_json"],
                                                       "downbeat_offset": it["song_downbeat_offset"]})})
    # A set edited before this guard existed (or whose file lengths changed
    # since) can already be in an impossible state -- set_duration now
    # raises rather than lying about a length that can't be rendered. Show
    # that as a plain warning, not a 500 on the page with the Remove button.
    duration_error = None
    try:
        total = mixer.set_duration(mix_items, key="audio") if mix_items else 0.0
    except ValueError as e:
        total, duration_error = None, str(e)
    missing_video = []
    if row["mode"] == "video" and row["tier"]:
        for it in items:
            if _is_card_row(it):
                continue
            if not db.one("""SELECT id FROM renders WHERE song_id=? AND tier=?
                             ORDER BY id DESC LIMIT 1""", it["song_id"], row["tier"]):
                missing_video.append(it["song_title"])
    renders = [_set_render_row(a) for a in db.q("SELECT * FROM assets WHERE kind='set' ORDER BY id DESC")
               if db.jset(a).get("set_id") == row["id"]]

    songs_by_id = {it["song_id"]: {"bpm": it["song_bpm"], "beat_grid_json": it["song_beat_grid_json"],
                                    "downbeat_offset": it["song_downbeat_offset"], "mp3_path": it["mp3_path"]}
                   for it in items if it["song_id"] is not None}
    beatmatch_plan = _beatmatch_plan(items, songs_by_id, row["mode"]) if len(items) > 1 else {}

    suggested_order = mixer.suggest_running_order(
        [{"id": it["id"], "title": it["song_title"], "key": it["song_key"], "bpm": it["song_bpm"]}
         for it in items if it["song_id"] is not None]) if len(items) > 1 else []
    suggested_order_ids = ",".join(str(o["song"]["id"]) for o in suggested_order)

    # Timeline widths come from mixer._item_duration, the SAME helper
    # render_set, mix_audio and set_duration share -- a block whose width was
    # computed separately would drift from what actually renders, which is the
    # defect this codebase has already fixed three times.
    timeline, longest = [], 0.0
    for it in items:
        secs = 0.0
        if _is_card_row(it):
            secs = float(it["card_secs"] or 0.0)
            title, bpm, key, wave = "MEOW P", None, None, None
        else:
            try:
                # OSError/RuntimeError only: a file that is missing or unreadable is
                # a real condition and zero is the honest width for it. A broad
                # except swallowed an AttributeError once and rendered every block
                # at zero width, which looked like a layout bug rather than a
                # missing helper.
                info = mixer.probe(it["mp3_path"]) if it["mp3_path"] else None
                if info:
                    secs = mixer._item_duration(info, dict(it))
            except (OSError, RuntimeError, KeyError):
                secs = 0.0
            title, bpm, key = it["song_title"], it["song_bpm"], it["song_key"]
            wave = song_waveform(it["song_id"])
        longest = max(longest, secs)
        timeline.append({"id": it["id"], "title": title, "secs": secs,
                          "bpm": bpm, "key": key,
                          "transition": it["transition"], "trans_secs": it["secs"],
                          "hold": _hold_of(it), "beatmatch": it["beatmatch"],
                          "branded": bool(_brand_of(it, row)),
                          "waveform": wave})
    for t in timeline:
        # a floor so a very short item is still clickable rather than a hairline
        t["pct"] = max(8.0, 100.0 * t["secs"] / longest) if longest else 100.0

    audience = _set_audience(row)
    return {"set": row, "items": items, "count": len(items), "total_secs": total,
            "timeline": timeline,
            "duration_error": duration_error, "missing_video": missing_video, "renders": renders,
            "beatmatch_plan": beatmatch_plan, "suggested_order": suggested_order,
            "suggested_order_ids": suggested_order_ids,
            "audiences": AUDIENCES, "affordances": audience_affordances(audience),
            "mode_audience": audience,
            "loudnorm_i": effects.LOUDNORM_I,
            "loudnorm_tp": effects.LOUDNORM_TP,
            "loudnorm_lra": effects.LOUDNORM_LRA,
            "one_button_master_name": mixer.ONE_BUTTON_MASTER_NAME,
            "one_button_master_version": mixer.ONE_BUTTON_MASTER_VERSION}


@app.get("/sets", response_class=HTMLResponse)
def sets_page(request: Request):
    """The Sets shelf: every editable set (the document you can open and
    change), plus every rendered file that predates the sets table and so has
    no set of its own -- assets from the old playlist quick-render.
    """
    editable = [set_detail(r) for r in db.q("SELECT * FROM sets ORDER BY updated DESC, id DESC")]
    names = {p["id"]: p["name"] for p in db.q("SELECT id, name FROM playlists")}
    rows = []
    for a in db.q("SELECT * FROM assets WHERE kind='set' ORDER BY id DESC"):
        meta = db.jset(a)
        if meta.get("set_id") is not None:
            continue  # shown under its own set's card above, not here too
        row = _set_render_row(a)
        row["playlist"] = names.get(meta.get("playlist_id"), "(deleted playlist)")
        row["playlist_id"] = meta.get("playlist_id")
        rows.append(row)
    return templates.TemplateResponse(request, "sets.html",
                                      {"sets": rows, "editable_sets": editable})


@app.get("/sets/new", response_class=HTMLResponse)
def new_set_page(request: Request):
    playlists = db.q("SELECT id, name FROM playlists WHERE kind='playlist' ORDER BY name")
    return templates.TemplateResponse(request, "set_new.html",
                                      {"playlists": playlists, "all_tiers": tiers.all_tiers()})


@app.post("/sets/new")
def create_set(name: str = Form(...), mode: str = Form("video"), tier: str = Form(""),
               playlist_id: BlankInt = Form(None)):
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    # free text a user typed -- screened exactly like the anchor prompt and
    # tier wording, for the same reason: it flows into no prompt today, but a
    # field nobody screens is the one that eventually does.
    try:
        tiers.check_text(name, "set name")
        tiers.check_override(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if mode not in ("audio", "video"):
        raise HTTPException(400, "mode must be 'audio' or 'video'")
    tier = (tier or "").strip() or None
    if tier:
        valid_tier_or_400(tier)
    if playlist_id is not None:
        get_playlist_or_404(playlist_id)
    now = time.time()
    sid = db.run("""INSERT INTO sets (name, playlist_id, tier, mode, created, updated)
                    VALUES (?,?,?,?,?,?)""", name, playlist_id, tier, mode, now, now)
    if playlist_id is not None:
        # Seeds from the playlist's current ordering -- a STARTING POINT, not a
        # link: editing the set afterward never writes back to the playlist,
        # and re-ordering the playlist later never reaches this set either.
        #
        # If the album has a story arc, its transition_out DEFAULTS each
        # handover: the arc is where a fade to black was argued for, so this is
        # where that argument arrives. It is still only a default -- the arc
        # proposes and the set editor disposes, and every one is overridable.
        pl_row = db.one("SELECT name FROM playlists WHERE id=?", playlist_id)
        by_song = {s["song_id"]: s.get("transition_out") or {}
                   for s in album_arc(pl_row["name"] if pl_row else "").get("songs") or []}
        for it in db.q("SELECT * FROM playlist_items WHERE playlist_id=? ORDER BY position", playlist_id):
            t = by_song.get(it["song_id"]) or {}
            kind = t.get("kind") if t.get("kind") in SET_TRANSITIONS else it["transition"]
            secs = t.get("secs") if t.get("kind") in SET_TRANSITIONS else it["secs"]
            hold = float(t.get("hold") or 0.0) if kind == mixer.BLACK else 0.0
            db.run("""INSERT INTO set_items (set_id, song_id, position, transition, secs, hold)
                      VALUES (?,?,?,?,?,?)""", sid, it["song_id"], it["position"],
                   kind, float(secs or 0.0), hold)
    return RedirectResponse(f"/sets/{sid}", status_code=303)


@app.get("/sets/{id}", response_class=HTMLResponse)
def set_edit_page(request: Request, id: int):
    row = get_set_or_404(id)
    songs = db.q("SELECT id, title FROM songs ORDER BY title")
    ctx = {**set_detail(row), "songs": songs, "all_tiers": tiers.all_tiers(),
           "transitions": SET_TRANSITIONS}
    return templates.TemplateResponse(request, "set_edit.html", ctx)


def _suggest_ctx(request, id, suggested, note="", form=None, item_id=None):
    """Re-render the editor with a suggestion filled into the form fields.

    A suggestion POPULATES; it does not save. Writing straight to the database
    would make an AI proposal indistinguishable from a decision, and there would
    be nothing to compare it against. The values sit in the form until the human
    presses Save, exactly as if they had typed them.

    `form` is what was submitted, and it is layered UNDER the suggestion and
    OVER the database. Rebuilding purely from the database discarded whatever
    was typed but not yet saved -- including the mix_direction that had just
    been typed to DRIVE the suggestion, which then vanished from the box that
    produced it, and the whole-set direction, which came back blank every time.
    """
    if wants_json(request):
        direction = (form.get("mix_direction") if form else "") or ""
        return JSONResponse(mixadvice.interface_payload(
            suggested, _suggest_items(id), direction=direction))
    row = get_set_or_404(id)
    ctx = {**set_detail(row), "songs": db.q("SELECT id, title FROM songs ORDER BY title"),
           "all_tiers": tiers.all_tiers(), "transitions": SET_TRANSITIONS,
           "suggest_note": note,
           # the box that drove this, still holding what was typed in it
           "set_direction": (form.get("mix_direction") if form else "") or ""}
    # A per-item suggest posts THAT item's form; a whole-set suggest posts only
    # the direction. Either way, only the submitting item's typed values are in
    # hand, so they are applied to that item alone.
    typed = {}
    if form is not None and item_id is not None:
        for k in ("transition", "secs", "hold", "in_secs", "out_secs", "gain_db",
                  "effects_json", "mix_direction"):
            if k in form:
                typed[k] = form.get(k)
        typed["beatmatch"] = 1 if form.get("beatmatch") else 0
    items = []
    for it in ctx["items"]:
        d = dict(it)
        if d["id"] == item_id:
            for k, v in typed.items():
                if v != "" or k in ("effects_json", "mix_direction"):
                    d[k] = v
        s = suggested.get(d["id"]) or {}
        d["suggested"] = sorted(k for k in s if k != "why")
        d["suggest_why"] = s.get("why", "")
        d["suggest_authored"] = "model" if s.get("why") else ""
        for k in ("transition", "secs", "effects_json"):
            if k in s:
                d[k] = s[k]
        if "beatmatch" in s:
            d["beatmatch"] = 1 if s["beatmatch"] else 0
        items.append(d)
    ctx["items"] = items
    return templates.TemplateResponse(request, "set_edit.html", ctx)


def _suggest_items(id):
    """The set's items in the shape mixadvice wants: the analysis a mixing
    decision depends on, in running order."""
    return [dict(r) for r in db.q(
        """SELECT si.id, s.title, s.bpm, s.key, s.energy
           FROM set_items si JOIN songs s ON s.id = si.song_id
           WHERE si.set_id=? AND si.song_id IS NOT NULL ORDER BY si.position""", id)]


@app.post("/sets/{id}/suggest", response_class=HTMLResponse)
async def suggest_set(request: Request, id: int):
    """Suggest settings for the WHOLE set at once.

    Mixing is relational -- what happens at item 3 depends on item 2 -- so the
    whole-order pass is the one that can be coherent. The per-item button below
    exists to re-roll one handover without disturbing the rest.
    """
    get_set_or_404(id)
    form = await request.form()
    items = _suggest_items(id)
    try:
        sug = mixadvice.suggest(items, (form.get("mix_direction") or "").strip())
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"the model could not be reached: {e}") from None
    note = (f"suggested settings for {len(sug)} of {len(items)} items -- nothing is saved until "
            f"you press Save on an item") if sug else "the model returned nothing usable"
    return _suggest_ctx(request, id, sug, note, form=form)


@app.post("/sets/{id}/items/{item_id}/suggest", response_class=HTMLResponse)
async def suggest_set_item(request: Request, id: int, item_id: int):
    """Suggest one item's settings, judged against the whole running order."""
    get_set_or_404(id)
    if not db.one("SELECT id FROM set_items WHERE id=? AND set_id=?", item_id, id):
        raise HTTPException(404, "no such item in this set")
    form = await request.form()
    items = _suggest_items(id)
    try:
        sug = mixadvice.suggest(items, (form.get("mix_direction") or "").strip(),
                                 only_id=item_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"the model could not be reached: {e}") from None
    note = ("suggested -- press Save to keep it" if sug
            else "the model returned nothing usable for that item")
    return _suggest_ctx(request, id, sug, note, form=form, item_id=item_id)


@app.post("/sets/{id}")
def update_set(id: int, name: str = Form(...), mode: str = Form("video"),
               tier: str = Form(""), mode_audience: str = Form(None)):
    row = get_set_or_404(id)
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    try:
        tiers.check_text(name, "set name")
        tiers.check_override(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if mode not in ("audio", "video"):
        raise HTTPException(400, "mode must be 'audio' or 'video'")
    tier = (tier or "").strip() or None
    if tier:
        valid_tier_or_400(tier)
    # Absent field keeps the stored audience so a name/tier save cannot
    # silently reset it. Present-but-invalid is a 400, not a coerce: a typo
    # that became "normal" would make T1-20's read-back lie.
    if mode_audience is None or mode_audience == "":
        mode_audience = _set_audience(row)
    elif mode_audience not in AUDIENCES:
        raise HTTPException(400, f"mode_audience must be one of {', '.join(AUDIENCES)}")
    db.run("UPDATE sets SET name=?, mode=?, tier=?, mode_audience=?, updated=? WHERE id=?",
           name, mode, tier, mode_audience, time.time(), id)
    return RedirectResponse(f"/sets/{id}", status_code=303)


@app.post("/sets/{id}/items")
def add_set_item(id: int, song_id: int = Form(...), transition: str = Form("fade"),
                 secs: float = Form(2.0), beatmatch: bool = Form(False)):
    get_set_or_404(id)
    song = get_song_or_404(song_id)
    if transition not in SET_TRANSITIONS:
        raise HTTPException(400, f"transition must be one of {', '.join(SET_TRANSITIONS)}")
    # Appending a song activates the PREVIOUS last item's own transition/secs
    # (unused while it had no next item) -- check the whole sequence still
    # renders before adding, not just this one new row. Same tolerance
    # _mix_items_for_set gives every existing row: a missing mp3 (deleted,
    # moved) is skipped rather than treated as a validation failure.
    extra = ({"audio": song["mp3_path"], "transition": transition, "secs": secs, "hold": 0.0,
             "in_secs": None, "out_secs": None, **_beatmatch_fields({"beatmatch": beatmatch}, song)}
             if song["mp3_path"] and os.path.isfile(song["mp3_path"]) else None)
    _refuse_if_unrenderable(_mix_items_for_set(id, extra_item=extra))
    pos_row = db.one("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM set_items WHERE set_id=?", id)
    db.run("""INSERT INTO set_items (set_id, song_id, position, transition, secs, beatmatch)
              VALUES (?,?,?,?,?,?)""", id, song_id, pos_row["p"], transition, secs, int(beatmatch))
    db.run("UPDATE sets SET updated=? WHERE id=?", time.time(), id)
    return RedirectResponse(f"/sets/{id}", status_code=303)


@app.post("/sets/{id}/cards")
async def add_set_card(id: int, duration: float = Form(3.0), image: UploadFile = File(...)):
    """T1-27 / T1-28: a title card is a set_items row with song_id NULL."""
    get_set_or_404(id)
    if not math.isfinite(duration) or duration <= 0:
        raise HTTPException(400, "duration must be a finite number greater than 0")
    dest = await save_upload(image, MAX_IMAGE, os.path.join(db.DATA, "sets", str(id)),
                              "image", prefix="card")
    extra = _card_mix_item({"song_id": None, "card_path": dest, "card_secs": duration,
                            "transition": "cut", "secs": 0.0, "hold": 0.0})
    _refuse_if_unrenderable(_mix_items_for_set(id, extra_item=extra))
    pos_row = db.one("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM set_items WHERE set_id=?", id)
    db.run("""INSERT INTO set_items (set_id, song_id, position, transition, secs,
                                     card_path, card_secs)
              VALUES (?,?,?,?,?,?,?)""",
           id, None, pos_row["p"], "cut", 0.0, dest, duration)
    db.run("UPDATE sets SET updated=? WHERE id=?", time.time(), id)
    return RedirectResponse(f"/sets/{id}", status_code=303)


@app.post("/sets/{id}/items/{item_id}")
def edit_set_item(id: int, item_id: int, in_secs: BlankFloat = Form(None),
                  out_secs: BlankFloat = Form(None), gain_db: float = Form(0.0),
                  transition: str = Form("fade"), secs: float = Form(2.0),
                  hold: float = Form(0.0), branded: bool = Form(False),
                  beatmatch: bool = Form(False), effects_json: str = Form(""),
                  mix_direction: str = Form("")):
    get_set_or_404(id)
    if not db.one("SELECT id FROM set_items WHERE id=? AND set_id=?", item_id, id):
        raise HTTPException(404, "no such item")
    in_secs, out_secs, gain_db, transition, secs = clamp_set_item_params(
        in_secs, out_secs, gain_db, transition, secs)
    hold = clamp_hold(hold, transition)
    effects_json = clamp_set_item_effects(effects_json)
    # duck and layer are checked HERE, not inside clamp_set_item_effects,
    # because they are the effects whose validity depends on a field outside
    # the JSON: both act across the transition window, and this is the first
    # place that knows what transition was submitted alongside them.
    no_window = effects.join_effects_without_overlap(effects_json, transition, secs)
    if no_window:
        raise HTTPException(400, f"{', '.join(no_window)} act across the transition between "
                                  f"this clip and the next, so they need a transition with a "
                                  f"duration -- a cut has no overlap. Pick fade, dissolve or "
                                  f"wipe, or remove them.")
    # The mixing note is free text that will be handed to a model, so it is
    # screened exactly like the anchor prompt, the tier wording and the
    # storyboard direction. Kept beside the JSON it produced: the JSON stays
    # the source of truth, this records what was asked for.
    mix_direction = (mix_direction or "").strip()
    if mix_direction:
        if len(mix_direction) > mixadvice.MAX_DIRECTION:
            raise HTTPException(400, f"mix direction is {len(mix_direction)} characters; keep it "
                                      f"under {mixadvice.MAX_DIRECTION}")
        try:
            tiers.check_text(mix_direction, "mix direction")
            tiers.check_override(mix_direction)
        except ValueError as e:
            raise HTTPException(400, str(e))
    # The trim slider is exactly how this state gets reached one drag away
    # (SETS_MIXING_PLAN.md): shortening THIS item's out_secs can leave its
    # own already-stored transition too long to fit. Check before writing.
    _refuse_if_unrenderable(_mix_items_for_set(id, overrides={
        item_id: {"transition": transition, "secs": secs, "hold": hold,
                  "in_secs": in_secs, "out_secs": out_secs,
                  "beatmatch": int(beatmatch)}}))
    db.run("""UPDATE set_items SET in_secs=?, out_secs=?, gain_db=?, transition=?, secs=?,
              beatmatch=?, effects_json=?, mix_direction=?, hold=?, branded=?
              WHERE id=?""",
           in_secs, out_secs, gain_db, transition, secs, int(beatmatch), effects_json,
           mix_direction or None, hold, int(branded), item_id)
    db.run("UPDATE sets SET updated=? WHERE id=?", time.time(), id)
    return RedirectResponse(f"/sets/{id}", status_code=303)


@app.post("/sets/{id}/brand")
async def set_brand_image(id: int, image: UploadFile = File(...)):
    """The album mark this set overlays on its branded handovers. Same shape as
    the playlist cover upload, and the same validation."""
    get_set_or_404(id)
    dest = await save_upload(image, MAX_IMAGE, os.path.join(db.DATA, "sets", str(id)),
                              "image", prefix="brand")
    db.run("UPDATE sets SET brand_path=?, updated=? WHERE id=?", dest, time.time(), id)
    return RedirectResponse(f"/sets/{id}", status_code=303)


@app.post("/sets/{id}/brand/clear")
def clear_brand_image(id: int):
    """Removes the row's pointer, not the file: another set may be using it, and
    a mark is cheap to re-point at."""
    get_set_or_404(id)
    db.run("UPDATE sets SET brand_path=NULL, updated=? WHERE id=?", time.time(), id)
    return RedirectResponse(f"/sets/{id}", status_code=303)


@app.post("/sets/{id}/items/{item_id}/delete")
def delete_set_item(id: int, item_id: int):
    get_set_or_404(id)
    row = db.one("SELECT id FROM set_items WHERE id=? AND set_id=?", item_id, id)
    if row:
        db.delete_set_item(item_id)
    db.run("UPDATE sets SET updated=? WHERE id=?", time.time(), id)
    return RedirectResponse(f"/sets/{id}", status_code=303)


@app.post("/sets/{id}/reorder")
def reorder_set(id: int, order: str = Form(...)):
    get_set_or_404(id)
    ids = [int(x) for x in order.split(",") if x.strip().isdigit()]
    # A song's own duration differs, so reordering can make an already-fine
    # transition too long for its new predecessor -- check the PROPOSED
    # order before writing it, same guard as an edit or an add.
    # _mix_items_for_set orders by the STORED position -- reordering needs the
    # PROPOSED one, so fetch keyed by id and walk `ids` instead.
    rows = {r["id"]: r for r in db.q(
        """SELECT si.id, si.song_id, si.transition, si.secs, si.in_secs, si.out_secs,
                  si.beatmatch, si.card_path, si.card_secs, si.hold,
                  s.bpm, s.mp3_path, s.beat_grid_json, s.downbeat_offset
           FROM set_items si LEFT JOIN songs s ON s.id = si.song_id WHERE si.set_id=?""", id)}
    reordered = []
    for i in ids:
        if i not in rows:
            continue
        row = rows[i]
        if _is_card_row(row):
            reordered.append(_card_mix_item(row))
        elif row["mp3_path"] and os.path.isfile(row["mp3_path"]):
            reordered.append({"audio": row["mp3_path"], "transition": row["transition"],
                              "secs": row["secs"], "in_secs": row["in_secs"],
                              "out_secs": row["out_secs"],
                              **_beatmatch_fields(row, row)})
    _refuse_if_unrenderable(reordered)
    for pos, item_id in enumerate(ids):
        db.run("UPDATE set_items SET position=? WHERE id=? AND set_id=?", pos, item_id, id)
    db.run("UPDATE sets SET updated=? WHERE id=?", time.time(), id)
    return RedirectResponse(f"/sets/{id}", status_code=303)


def _beatmatch_fields(it, song):
    """The analysis a beatmatch=1 item needs mixer._apply_beatmatch to snap its
    own cut AND to plan its tempo ramp -- pulled from the SONG's own analysis
    (analyse.py), the same source _beatmatch_plan's preview already reads.

    bpm is NOT optional. mixer._apply_beatmatch reads it.get("bpm") and the next
    item's, and can_beatmatch(None, None) is False -- so leaving bpm out made
    apply_tempo_ramp unreachable from every route while the editor's preview,
    which reads bpm straight off the song row, went on promising a ramp. The
    preview and the render must read the same fields or they describe different
    renders."""
    return {"beatmatch": bool(it["beatmatch"]),
            "bpm": song["bpm"],
            "beat_grid": json.loads(song["beat_grid_json"]) if song["beat_grid_json"] else [],
            "downbeat_offset": song["downbeat_offset"] or 0}


@app.post("/sets/{id}/render")
def render_set_route(id: int):
    row = get_set_or_404(id)
    items = db.q("SELECT * FROM set_items WHERE set_id=? ORDER BY position", id)
    if not items:
        raise HTTPException(400, "this set has no items yet -- add one first")
    songs = {it["song_id"]: get_song_or_404(it["song_id"])
             for it in items if it["song_id"] is not None}

    build = []
    if row["mode"] == "audio":
        missing = [songs[it["song_id"]]["title"] for it in items
                   if it["song_id"] is not None and not songs[it["song_id"]]["mp3_path"]]
        if missing:
            raise HTTPException(400, f"no audio for: {', '.join(missing)}")
        audience = _set_audience(row)
        for it in items:
            if _is_card_row(it):
                build.append({**_card_mix_item(it),
                              "automation": automation.item_audio(it["id"]),
                              "mode_audience": audience})
                continue
            build.append({"audio": songs[it["song_id"]]["mp3_path"], "transition": it["transition"],
                          "secs": it["secs"], "in_secs": it["in_secs"], "out_secs": it["out_secs"],
                          "hold": _hold_of(it),
                          "gain_db": it["gain_db"], "effects_json": it["effects_json"],
                          # the item's drawn curves, as plain data: the fragments and
                          # whether per-item loudnorm comes off for a gain curve
                          "automation": automation.item_audio(it["id"]),
                          # T1-18: easy is a set-level fact mixer reads off the
                          # item dict, same shape as automation. Not stamping
                          # this leaves master_engaged blind and easy a no-op.
                          "mode_audience": audience,
                          **_beatmatch_fields(it, songs[it["song_id"]])})
    else:
        if not row["tier"]:
            raise HTTPException(400, "pick a tier before rendering video")
        audience = _set_audience(row)
        missing = []
        for it in items:
            if _is_card_row(it):
                build.append({**_card_mix_item(it),
                              "automation": automation.item_audio(it["id"]),
                              "mode_audience": audience})
                continue
            r = db.one("""SELECT * FROM renders WHERE song_id=? AND tier=?
                         ORDER BY id DESC LIMIT 1""", it["song_id"], row["tier"])
            if not r:
                missing.append(songs[it["song_id"]]["title"])
            else:
                build.append({"video": r["path"], "transition": it["transition"], "secs": it["secs"],
                              "in_secs": it["in_secs"], "out_secs": it["out_secs"],
                              "hold": _hold_of(it), "brand_path": _brand_of(it, row),
                              "gain_db": it["gain_db"], "effects_json": it["effects_json"],
                              # the item's drawn curves, as plain data: the fragments and
                              # whether per-item loudnorm comes off for a gain curve
                              "automation": automation.item_audio(it["id"]),
                              "mode_audience": audience,
                              **_beatmatch_fields(it, songs[it["song_id"]])})
        if missing:
            raise HTTPException(400, f"tier '{row['tier']}' has no video for: {', '.join(missing)}")

    jobs.enqueue("render_set", {"set_id": id, "playlist_id": row["playlist_id"],
                                "mode": row["mode"], "tier": row["tier"], "items": build})
    return RedirectResponse(f"/sets/{id}", status_code=303)


@app.post("/sets/{asset_id}/delete")
def delete_set(asset_id: int):
    """Remove a rendered set, row and file. The songs and their own renders are
    untouched -- a set is an assembly of them, not the material."""
    a = db.one("SELECT * FROM assets WHERE id=? AND kind='set'", asset_id)
    if not a:
        raise HTTPException(404, "no such set")
    if _within_data(a["path"]) and os.path.isfile(a["path"]):
        try:
            os.remove(a["path"])
        except OSError:
            pass
    db.run("DELETE FROM assets WHERE id=?", asset_id)
    return RedirectResponse("/sets", status_code=303)


# ------------------------------------------------------------------ models --

def models_ctx(saved=""):
    """Everything both the whole page and one role's section need.

    Shared because setting a default swaps just that section back in: the
    'default' tag moves to another card and disappears from the old one, so the
    fragment has to be rendered from the same data the page was.
    """
    entries = models.catalog()
    by_role = {}
    for e in entries:
        by_role.setdefault(e["role"], []).append(e)
    try:
        chat = grok.list_models()
        chat_best = grok.best_model(chat)
        chat_error = ""
    except Exception as e:
        chat, chat_best, chat_error = [], None, str(e)
    return {
        "roles": models.ROLES, "by_role": by_role,
        "role_labels": {r: r.replace("_", " ").title() for r in models.ROLES},
        "chat_default": models.chat_default(),
        "defaults": {r: models.default_for(r) for r in models.ROLES},
        "reachable": models.installed() is not None,
        "chat": chat, "chat_best": chat_best, "chat_error": chat_error,
        "vision_model": grok.VISION_MODEL, "saved": saved,
    }


@app.get("/models/fleet", response_class=HTMLResponse)
def models_fleet(request: Request):
    """What each RENDER BACKEND holds, which is not the same question as what
    this box holds.

    Its own endpoint, loaded after the page, rather than part of models_ctx():
    models_ctx runs again on every role swap, and asking three ComfyUIs for
    /object_info costs up to OBJECT_INFO_TIMEOUT each when a box is off. Setting
    a default should not wait on a sleeping gaming PC.

    pipeline supplies the backend list and models does the reading -- pipeline
    imports models, so the list has to be passed in from here rather than
    fetched there.
    """
    return templates.TemplateResponse(request, "_fleet.html", {
        "fleet": models.by_backend(pipeline.swarm_backends()),
        "render_backend": pipeline.RENDER_BACKEND,
    })


@app.get("/models", response_class=HTMLResponse)
def models_page(request: Request):
    """Every model this studio can use, what each one is designed for, and
    whether it is actually on the box.

    The point is that adding a model is a catalogue entry, not a code edit, and
    that nobody has to read build_song.py to find out what renders the clips.
    """
    return templates.TemplateResponse(request, "models.html", models_ctx())


def role_section(request, role, saved=""):
    """One role's section, for an htmx swap. A full-page reload to move a tag
    scrolled the page back to the top and lost which section you were reading."""
    return templates.TemplateResponse(request, "_model_section.html",
                                       dict(models_ctx(saved), role=role,
                                            role_label=models.ROLES[role]))


@app.post("/models/storyboard/default")
def set_storyboard_default(request: Request, key: str = Form("")):
    """The xAI chat model storyboards are written with.

    Its own route because a storyboard model is an xAI model ID discovered at
    runtime, not a key in the local catalogue -- there is nothing to validate it
    against but the live list. Blank means "highest available", which is what
    grok.best_model() resolves.
    """
    key = (key or "").strip()
    if key:
        try:
            available = grok.list_models()
        except Exception as e:
            raise HTTPException(502, f"could not reach xAI to check that model: {e}") from None
        if key not in available:
            raise HTTPException(400, f"xAI does not list a chat model called {key!r}")
    models.set_chat_default(key)
    # htmx swaps the section back in; a plain browser still gets the redirect,
    # so the page works with JavaScript off exactly as it did before
    if request.headers.get("HX-Request"):
        return role_section(request, "storyboard", saved=key or "highest available")
    return RedirectResponse("/models", status_code=303)


@app.post("/models/{role}/default")
def set_model_default(request: Request, role: str, key: str = Form(...)):
    try:
        models.set_default(role, key)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if request.headers.get("HX-Request"):
        return role_section(request, role, saved=key)
    return RedirectResponse("/models", status_code=303)


# ------------------------------------------------------------------- jobs --

JOBS_REFRESH_CHOICES = [("auto", "auto (10s busy / 60s idle)"), ("5", "5s"),
                       ("15", "15s"), ("30", "30s"), ("60", "60s"), ("off", "off")]
JOBS_REFRESH_BUSY, JOBS_REFRESH_IDLE = 10, 60
JOBS_REFRESH_RANGE = (5, 3600)


def jobs_refresh_secs(choice, busy):
    """Seconds between polls, or 0 for no polling.

    'auto' is the point of the feature: a queue with something running is worth
    watching every 10s, an idle one is not. Any explicit number wins over that
    and is clamped -- 'refresh=0' in a hand-edited URL must not become a
    hot loop hammering the box the renderer is running on.
    """
    if choice == "off":
        return 0
    if choice == "auto":
        return JOBS_REFRESH_BUSY if busy else JOBS_REFRESH_IDLE
    try:
        return max(JOBS_REFRESH_RANGE[0], min(JOBS_REFRESH_RANGE[1], int(choice)))
    except (TypeError, ValueError):
        return JOBS_REFRESH_BUSY if busy else JOBS_REFRESH_IDLE


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, refresh: str = "auto", partial: int = 0):
    now = time.time()
    entries = []
    for j in jobs.recent():
        elapsed = None
        if j["started"]:
            elapsed = (j["finished"] or now) - j["started"]
        entries.append({"job": j, "desc": jobs.describe(j), "elapsed": elapsed,
                         "cancelable": j["status"] in ("queued", "running")})
    busy = any(e["job"]["status"] in ("queued", "running", "cancelling") for e in entries)
    if refresh not in dict(JOBS_REFRESH_CHOICES):
        refresh = "auto"
    ctx = {"jobs": entries, "active": jobs.active(), "refresh": refresh,
           "refresh_secs": jobs_refresh_secs(refresh, busy),
           "refresh_choices": JOBS_REFRESH_CHOICES,
           # ComfyUI's OWN queue, which this app does not control: it is
           # unauthenticated on the tailnet, so work can arrive there from
           # anywhere and "nothing running" here never meant the card was idle
           "comfy": pipeline.comfy_queue(),
           # SwarmUI's backends, if it is running. A sibling of the count above,
           # never a replacement: with two backends there are two answers.
           "swarm": pipeline.swarm_backends(),
           # WHICH of them actually renders. Read live rather than hardcoded in
           # the template: this panel told everyone "nothing routes through
           # Swarm yet" for as long as that was a sentence someone had typed,
           # and a page that describes a render nobody is performing is the
           # defect this codebase keeps making.
           "render_backend": pipeline.RENDER_BACKEND}
    # the poll swaps the panel only -- returning the whole page would nest a
    # second <html> inside the one already on screen
    return templates.TemplateResponse(request, "_jobs_panel.html" if partial else "jobs.html", ctx)


# How recently a finished job is still worth showing on the page that queued
# it. Long enough that a render finishing while you look away is still there
# when you look back; short enough that the panel does not become a log.
QUEUE_RECENT_SECS = 300
QUEUE_REFRESH_SECS = 5


def queue_ctx():
    """The work in flight, for the panel any page can include.

    Deliberately GLOBAL. There is one serialized worker and one GPU, so a set
    render really does wait behind an anchor sweep started from another tab --
    a queue filtered to "this page's" jobs would show an empty list while the
    thing actually blocking you ran invisibly. That was the state of every page
    except /jobs.

    Polling stops when nothing is moving. A page that polls forever is a page
    that never lets the machine idle, and the panel says which state it is in
    rather than looking identical either way.
    """
    now = time.time()

    def entry(j):
        return {"job": j, "desc": jobs.describe(j),
                "elapsed": ((j["finished"] or now) - j["started"]) if j["started"] else None}

    rows = [dict(r) for r in db.q(
        """SELECT * FROM jobs WHERE status IN ('queued','running','cancelling')
              OR (finished IS NOT NULL AND finished > ?)
           ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'cancelling' THEN 0
                                WHEN 'queued' THEN 1 ELSE 2 END, id""",
        now - QUEUE_RECENT_SECS)]
    active = [entry(j) for j in rows if j["status"] in ("running", "cancelling")]
    waiting = [entry(j) for j in rows if j["status"] == "queued"]
    recent = [entry(j) for j in rows if j["status"] not in ("running", "cancelling", "queued")]
    recent.reverse()                       # newest of the finished ones first
    return {"queue_active": active, "queue_waiting": waiting, "queue_recent": recent,
            "queue_refresh_secs": QUEUE_REFRESH_SECS if (active or waiting) else 0}


@app.get("/queue", response_class=HTMLResponse)
def queue_panel(request: Request):
    """The queue panel, as the same fragment every page embeds.

    One route and one template, included wherever work is started, rather than
    a mini job list per page -- five copies of this markup would be five copies
    to keep in step with what a job row can say.
    """
    return templates.TemplateResponse(request, "_queue.html", queue_ctx())


@app.post("/jobs/{id}/retry")
def retry_job(request: Request, id: int):
    """Re-queue a failed job with its own stored arguments.

    There was no way to recover a failed batch except to fill the form in again
    from memory. Nine anchor sheets were lost to a five-second ComfyUI restart,
    and every one of them still had its exact arguments -- album, tier, view,
    image paths, prompt -- sitting in args_json.

    A NEW row, not a reset of the old one: the failure is part of the record,
    and overwriting it would erase the evidence of what went wrong.
    """
    row = jobs.get(id)
    if not row:
        raise HTTPException(404, "no such job")
    if row["status"] not in ("failed", "cancelled"):
        raise HTTPException(400, f"job #{id} is {row['status']}, not failed -- nothing to retry")
    args = json.loads(row["args_json"] or "{}")
    new_id = jobs.enqueue(row["kind"], args, song_id=row["song_id"])
    if wants_json(request):
        return JSONResponse({"retried": id, "job_id": new_id, "kind": row["kind"]})
    return RedirectResponse(f"/jobs#job-{new_id}", status_code=303)


@app.post("/jobs/{id}/cancel")
def cancel_job(request: Request, id: int):
    """Cancel a queued or running job.

    The JSON branch is not decoration: Cancel appears on /jobs, on a song page
    and beside a running batch, and the redirect sent every one of them back to
    /jobs -- so cancelling one sheet from a song page navigated away from the
    page you were working on.
    """
    try:
        jobs.cancel(id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if wants_json(request):
        row = jobs.get(id)
        return JSONResponse({"cancelled": id, "status": row["status"] if row else "cancelled"})
    return RedirectResponse("/jobs", status_code=303)


@app.get("/jobs/{id}/stream")
async def job_stream(id: int):
    if jobs.get(id) is None:
        raise HTTPException(404, "no such job")
    return StreamingResponse(jobs.stream(id), media_type="text/event-stream")


@app.get("/jobs/{id}/log", response_class=PlainTextResponse)
def job_log(id: int):
    row = jobs.get(id)
    if row is None:
        raise HTTPException(404, "no such job")
    if not row["log_path"] or not os.path.isfile(row["log_path"]):
        return ""
    with open(row["log_path"]) as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
