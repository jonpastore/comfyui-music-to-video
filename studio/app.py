"""FastAPI web layer for Meow P Studio. Routes only -- all real work happens
in db/tiers/jobs/pipeline/grok/lyrics/mixer; this file wires HTTP to them and
does upload validation + path-traversal-safe media serving.
"""
import hashlib, json, math, os, random, re, shutil, sqlite3, tempfile, time
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
import qc_service   # recording those findings and answering the review queue
import sets_service  # TRD-1 / T6-A3: sets, items, render — no FastAPI
import cleanup_service  # T6-19: confirmed clip cleanup — no FastAPI
import storyboard_service  # TRD-2 / T6-A3: arc, board, meter — no FastAPI
import arc_service  # TRD-6 T6-A2-arc: playlist arc meter — no FastAPI
import playlist_service  # TRD-6 T6-A2-playlists: song_count / total_secs — no FastAPI
import library_service  # TRD-6 T6-A2-library: library song_count — no FastAPI
import media_service  # TRD-8 T8-16: song media bag — no FastAPI
import nav_service  # UIUX §8 / T6-A2-nav: topbar links — no FastAPI
import pose_plan  # scene pose → chosen sheet → refs image2
import scene_pose_map  # T2-51 / T2-52: Accept-gated keeper→scene map
import classification  # T4-21 / T4-22: album pose library in sqlite
import civitai  # Civitai LoRA search/download — registers download_lora handler
import storyboard_versions
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
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".oga", ".m4a", ".aac",
              ".opus", ".wma", ".aiff", ".aif", ".caf"}
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
# UIUX §8: one list drives the topbar; template iterates, never hardcodes.
templates.env.globals["nav_links"] = nav_service.links


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
def pose_asset_id(view):
    """asset id encoded in pose_<id> / pose_<id>_nude, else None."""
    m = re.match(r"^pose_(\d+)(?:_nude)?$", str(view or ""))
    return int(m.group(1)) if m else None


def pose_view_key(asset_id, nude=False):
    return f"pose_{int(asset_id)}_nude" if nude else f"pose_{int(asset_id)}"


def known_anchor_view(view):
    return view in ANCHOR_VIEWS or pose_asset_id(view) is not None


def view_label(view):
    if view in ANCHOR_VIEWS:
        return ANCHOR_VIEWS[view]
    aid = pose_asset_id(view)
    if aid:
        row = db.one("SELECT meta_json FROM assets WHERE id=? AND kind='anchor_ref'", aid)
        name = (db.jset(row).get("pose_name") if row else "") or f"pose {aid}"
        return f"{name}, {'nude' if str(view).endswith('_nude') else 'clothed'}"
    return view or ""


templates.env.filters["viewname"] = lambda v: view_label(v)
templates.env.filters["actorlist"] = (
    lambda row, album="": pose_plan.actor_names(row, album))


def view_base(view):
    """Camera/position key with the nude suffix stripped."""
    key = str(view or "")
    return key[:-5] if key.endswith("_nude") else key


def view_family(view):
    return "nude" if _make_anchor().is_nude_view(view) else "clothed"


def view_position_label(view):
    """Row label for a camera: 'front', 'on all fours', or a named pose."""
    if view in ANCHOR_VIEWS:
        return ANCHOR_VIEWS[view].split(",")[0].strip()
    label = view_label(view)
    return (label.split(",")[0].strip()
            or view_base(view).replace("_", " "))
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


def score_landed_clip(path, song, tier, clip_idx, progress=None):
    """First-frame identity score vs her photographs (and the approved still).

    Wardrobe is not an identity defect. Never a gate. A missing ffmpeg
    frame or a vision miss stores nothing and does not fail the clip job.
    """
    if not path or not os.path.isfile(path):
        return None
    dest = path + ".qc.png"
    try:
        import build_song as _bs
        _bs.extract_video_frame(path, "first", dest=dest)
    except Exception as e:
        if progress:
            progress(f"clip qc frame skipped: {e}")
        return None
    bases = list(ref_score_bases(song, tier))
    still = db.one(
        """SELECT path FROM refs WHERE song_id=? AND tier=? AND clip_idx=?
           AND approved=1""",
        song["id"], tier, clip_idx)
    if still and still["path"] and still["path"] not in bases:
        bases.append(still["path"])
    qc = score_generated_still(
        dest, bases, "clip first frame; score physical identity, not wardrobe",
        progress)
    db.run("UPDATE clips SET qc_json=? WHERE path=?", qc, path)
    return qc


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
    dest = qc_service.produce_repair(src, dest, args, progress)
    qc_service.record_pair("refine", src, dest,
                           group=qc_service.lineage_group("refine", src))
    qc_service.persist_still_qc(
        dest, src=src, prompt=args.get("remedy") or "",
        progress=progress, kind="image")
    return dest


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
    ident, prompt = s.get("identity"), s.get("prompt")
    tag = f"confidence {int(n)}%"
    if ident is not None:
        tag += f" · identity {int(ident)}%"
    if prompt is not None and (ident is None or prompt != ident or prompt != n):
        tag += f" · pose {int(prompt)}%"
    notes = (s.get("notes") or "").strip()
    if notes:
        tag += f" — {notes[:80]}"
    return tag


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
    rows = db.q(f"""SELECT a.*, c.name AS character_name
                    FROM anchors a LEFT JOIN characters c ON c.id = a.character_id
                    WHERE {db.visible_anchor_sql('a')}
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
                     if r["tier"] == tier
                     and (_make_anchor().is_nude_view(r["view"]) == nude)]
            if not group or (nude and not allows and not group):
                continue
            tier_rows.append({"label": label, "nude": nude, "anchors": [
                dict(r, version=version[r["id"]], opposite=opposite_path(r)) for r in group]})
            count += len(group)
        if tier_rows:
            out.append({"name": tier, "count": count, "rows": tier_rows})
    stamped = [dict(r, version=version[r["id"]], opposite=opposite_path(r))
               for r in rows]
    return out, stamped
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
    # realpath is /abs/path. A leading slash here becomes /media//abs… and
    # Chrome treats the empty segment badly next to loading=lazy + overflow-x.
    return "/media/" + quote(os.path.realpath(path).lstrip("/"), safe="/")


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

    Comes from the AUDIO LENGTH, never from the storyboard's scene count.
    Operator stills are one per scene (clip_chain_plan heads). This count is
    the song-quantum allocator used by T2-13 / T3-4.4, not the approve grid.

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


def chosen_pose_count(scope_kind, scope_value, tier, character_id=None):
    """How many chosen sheets this character has at the tier, any view.

    Named pose sheets (pose_21, pose_60_nude, …) count. Generate refs still
    needs view='front'; this number is what the UI uses to say "library is
    full, identity front is missing" instead of "no anchor". Shared
    sheets with the same character name count for every album.
    """
    if character_id is None:
        row = db.one(f"""SELECT COUNT(*) AS n FROM anchors
                         WHERE {db.visible_anchor_sql()} AND tier=?
                           AND chosen=1 AND character_id IS NULL""",
                     scope_value or "", tier)
    else:
        row = db.one(f"""SELECT COUNT(*) AS n FROM anchors a
                         LEFT JOIN characters c ON c.id = a.character_id
                         WHERE {db.visible_anchor_sql('a')} AND a.tier=?
                           AND a.chosen=1
                           AND (a.character_id=? OR (a.scope_kind='shared'
                                AND c.name=(SELECT name FROM characters WHERE id=?)))""",
                     scope_value or "", tier, character_id, character_id)
    return int(row["n"]) if row else 0


def identity_front_blocker(album, tier):
    """Why Generate refs cannot start for this album+tier, or None.

    chosen_anchor defaults to view='front'. A pose library does not satisfy
    that gate. When sheets exist, name the count so the operator is not told
    to create an anchor they already have.
    """
    if chosen_anchor("album", album or "", tier):
        return None
    n = chosen_pose_count("album", album or "", tier)
    if n:
        return (f"{n} pose sheet(s) for tier '{tier}' but none is the identity "
                "front — Generate refs needs a chosen front sheet on /anchors")
    return (f"no chosen anchor for tier '{tier}' on this album — "
            "generate and pick one on /anchors first")


def chosen_anchor(scope_kind, scope_value, tier, view="front", character_id=None):
    """The anchors row picked for this scope+tier+view, or None. Reference/clip
    generation always resolves anchors this way -- never by song.

    character_id=None means THE PROTAGONIST, whose anchors carry a NULL
    character_id -- which is every anchor that existed before the cast did. The
    NULL test is not optional: without it a supporting character's chosen anchor
    could be returned as the protagonist's and every reference frame for the
    song would render the wrong person.

    A shared keeper (scope_kind='shared') is used when this album has no
    row of its own. Kitty's standing nude is one file, not one copy per album.
    """
    return db.chosen_anchor(scope_kind, scope_value, tier, view, character_id)


def ref_score_bases(song, tier, fallback=None):
    """Identity bases for scoring a landed ref: the album's chosen anchor.

    A job arg plate, the broken source, or empty bases still produce a
    qc_json row — that is not enough. score_candidate must see the chosen
    sheet so the confidence is identity vs the lock, not vs itself.
    """
    album = (song["album"] if song else None) or ""
    row = chosen_anchor("album", album, tier)
    if row and row["path"]:
        return [row["path"]]
    if fallback:
        return [fallback]
    return []


def album_cast(album):
    """The album's named supporting characters, in name order.

    The PROTAGONIST is not in here: they are the album profile
    (playlists.identity/wardrobe/body), which every existing album already has.
    """
    return db.q("SELECT * FROM characters WHERE scope_value=? ORDER BY name", album or "")


def character_is_lead(c):
    """Named rows default to lead (T2-49). extra/background are an explicit unset."""
    if c is None:
        return False
    if "figure_role" not in c.keys() or not c["figure_role"]:
        return True
    return c["figure_role"] == "lead"


def offered_cast(album):
    """Album characters the storyboard writer may name as leads.

    A chosen front is not required. T2-49: generate has to know each LEAD
    exists from the character row. Extra/background stay out so they can
    be invented in a scene without an identity slot. Missing fronts block
    Generate refs (T2-28), not the writer.
    """
    out = []
    for c in album_cast(album):
        if not character_is_lead(c):
            continue
        desc = " ".join(p for p in (c["role"], c["identity"], c["wardrobe"]) if p)
        out.append((c["name"], desc or "album lead"))
    return out


def album_leads_for_form(album, tier, named=None):
    """Consistency characters for the generate form and storyboard page."""
    named = {str(n).strip().lower() for n in (named or []) if str(n).strip()}
    rows = []
    for c in album_cast(album):
        if not character_is_lead(c):
            continue
        front = chosen_anchor("album", album or "", tier, "front", c["id"])
        name = c["name"]
        rows.append({
            "id": c["id"],
            "name": name,
            "role": c["role"] or "",
            "identity": (c["identity"] or "").strip(),
            "has_front": bool(front and front["path"]),
            "used": name.lower() in named,
        })
    return rows


def named_scene_leads(rows):
    return sorted({n["name"] for r in rows for n in (r.get("cast") or [])
                   if n.get("role") == "lead" and n.get("name")})


def album_playlist(album):
    if not album:
        return None
    return db.one("SELECT * FROM playlists WHERE name=? AND kind='playlist'", album)


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


def album_chosen_anchors(album, tier):
    """Chosen sheets at this tier: protagonist first, then cast by name.

    Album-scoped keepers plus the shared library. Same rows the
    storyboard page already showed at the top. T2-26 puts them on the
    JSON so a client that is not that page can show them too.
    """
    return db.visible_chosen_anchors(album, tier)


def anchors_by_character(album, tier):
    """T2-26: chosen album anchors grouped per character.

    A flat list of images is not this: a client has to know which sheet is
    whose without another query. Unchosen candidates and other albums/tiers
    stay out.
    """
    groups, index = [], {}
    for row in album_chosen_anchors(album, tier):
        key = row["character_id"]
        if key not in index:
            index[key] = len(groups)
            groups.append({
                "character": row["character_name"] or "protagonist",
                "character_id": row["character_id"],
                "images": [],
            })
        groups[index[key]]["images"].append({
            "id": row["id"],
            "view": row["view"],
            "path": row["path"],
            "url": media_url(row["path"]),
        })
    return groups


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
        if ext not in AUDIO_EXTS:
            raise HTTPException(
                400, f"unsupported audio type {ext or '(none)'}; "
                     f"use {', '.join(sorted(AUDIO_EXTS))}")
        if ct and not (ct.startswith("audio/") or ct in (
                "application/ogg", "application/octet-stream")):
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
    force = bool(args.get("force"))
    # T10-9: a human edit survives a re-fetch. Only force (explicit
    # re-transcribe) may overwrite lyrics_edited rows.
    if not lyrics.may_replace_lyrics(song, force=force):
        progress("keeping edited lyrics; re-transcribe explicitly to replace")
        return {"chars": len(song["lyrics"] or ""), "kept_edit": True}
    try:
        ok, msg = lyrics.available()
        if not ok:
            raise RuntimeError(msg)
        # ComfyUI and whisper share one 24 GB card and ComfyUI keeps its models
        # resident, so a transcription that follows a render OOMs. Ask it to let go
        # first; lyrics.transcribe falls back to CPU if that was not enough.
        pipeline.free_vram(progress)
        result = lyrics.transcribe(song["mp3_path"], progress)
    except Exception:
        # T10-10: fetch failed is stored on the song so T2-8c can tell it
        # from a genuine empty result. The job still fails. Content screens
        # after a successful fetch are not fetch_failed.
        db.store_lyrics(song["id"], "", source="transcription",
                        status="fetch_failed")
        raise
    text = lyrics.to_sections(result)
    # T10-18b: transcription into an xxx work is still a lyrics write.
    if db.one("SELECT id FROM storyboards WHERE song_id=? AND tier=?",
              song["id"], "xxx"):
        lyrics.screen(text, tier="xxx")
    # T10-10: empty is a stored state, not a bare empty string.
    status = lyrics.result_status(text)
    # T10-8: which backend produced it, and that it is a transcription.
    # store_lyrics also clears lyrics_edited (T10-9).
    db.store_lyrics(song["id"], text, source="transcription",
                    backend=result.get("backend"), status=status)
    return {"chars": len(text), "backend": result.get("backend"),
            "status": status, "replaced": force, "kept_edit": False}


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
    pose = (args.get("pose") or "").strip()
    if pose:
        prof["pose"] = pose
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
    # pose-gap prompt is the decided clause for T3-34 scoring; --prompt
    # would replace the composed sheet. Pose is already on the profile.
    render_prompt = (
        "" if args.get("source") == "pose-gap" else args.get("prompt", ""))
    import pose_generate
    images = pose_generate.existing_images(args.get("images") or [])
    if not images:
        images = pose_generate.existing_images(
            pose_generate._album_images(album, cid))[:3]
        if images:
            progress("identity files were missing; using album photographs")
    paths = pipeline.gen_anchor(images, view, args.get("n", 4), progress,
                                 profile=anchor_profile,
                                 # this ALBUM's wording for the tier if it has its
                                 # own, else the tier's -- the same call the form
                                 # composed its panel and its preview from
                                 guard=tiers.compose_guardrail(args["tier"], album),
                                 prompt=render_prompt,
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
    actors = [a for a in (args.get("actors") or []) if a]
    if actors:
        meta = {}
        if settings:
            try:
                meta = json.loads(settings)
            except (TypeError, ValueError):
                meta = {}
        meta["actors"] = actors
        settings = json.dumps(meta)
    now = time.time()
    asked = args.get("prompt") or args.get("pose") or ""
    bases = images
    prev = db.q("""SELECT path FROM anchors WHERE scope_kind=? AND scope_value=?
                   AND tier=? AND view=? AND character_id IS ?
                   ORDER BY chosen DESC, id DESC""",
                args["scope_kind"], args["scope_value"], args["tier"], view, cid)
    pred_path = prev[0]["path"] if prev else None
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
    if pred_path:
        group = qc_service.lineage_group(
            "anchor_reroll", pred_path,
            scope_kind=args["scope_kind"], scope_value=args["scope_value"],
            tier=args["tier"], view=view, character_id=cid)
        for p in landed:
            if jobs.canonical_path(p) != jobs.canonical_path(pred_path):
                qc_service.record_pair("anchor_reroll", pred_path, p, group=group)
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
    outdir, slug = album_arc_dir(pl)
    titles = {s["id"]: s["title"] for s in songs}
    data["_used"] = used
    data["_titles"] = titles
    # T2-15: the job writes a proposal. Accept is what lands the committed pair.
    path = arc.write_proposal(data, outdir, slug)
    return {"songs": len(data["songs"]), "acts": len(data["acts"]),
            "model": used, "proposal": path}


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
    # Album characters are offered as leads whether or not they have a
    # chosen front yet (T2-49). A missing front blocks Generate refs, not
    # the writer -- otherwise Tiger/Panther never reach the board.
    cast = offered_cast(song["album"] or "")
    if cast:
        progress(f"cast offered to the storyboard: {', '.join(n for n, _ in cast)}")
    else:
        progress("cast offered to the storyboard: protagonist only")
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
    if isinstance(sb, dict):
        # T2-22: declared clause is compose_guardrail (album override when
        # one exists). Stub generate has no field; the real composer stamps
        # compose_guardrail(tier) and this overwrites with the applied text.
        sb["guardrail"] = guardrail
        foreign = foreign_tier_in_storyboard(sb, tier)
        if foreign:
            raise ValueError(
                f"storyboard carries {foreign} wording; this board is {tier}")
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
    try:
        prompts.touch(f"song:{sid}", "storyboard_direction",
                      args.get("direction") or "", "saved", tier=tier)
    except ValueError:
        pass
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
    # Supporting leads with a chosen front at this tier. A scene attaches
    # only the ones it NAMES as leads. Extras and background may be named
    # on the board; they never take an image2/image3 slot.
    cast = {c["name"]: {"path": a["path"],
                        "desc": " ".join(p for p in (c["identity"], c["wardrobe"], c["body"]) if p)}
            for c, a in cast_anchors(album, tier)}
    if cast:
        progress(f"cast for this tier: {', '.join(sorted(cast))}")
    # Job args own plates. Do not fall back to plan() auto scene_bases.
    pose_bases = args.get("pose_bases") or {}
    if pose_bases:
        progress(f"pose plates: {len(pose_bases)} scene(s)")
    scene_anchors = args.get("anchors") or None
    if scene_anchors:
        progress(f"per-scene keepers: {len(scene_anchors)} scene(s)")
    extra = {"anchors": scene_anchors} if scene_anchors else {}
    results = pipeline.gen_refs(song["slug"], tier, sb["json_path"], anchor_name,
                                 song["mp3_path"], progress, limit=args.get("limit"),
                                 guard=tiers.compose_guardrail(tier, album), body=body,
                                 cast=cast, bases=pose_bases, **extra)
    now = time.time()
    bases = ref_score_bases(song, tier, args.get("anchor_path"))
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
        sn = _clip_scene_number(song, tier, r["clip_idx"])
        db.run("""INSERT OR IGNORE INTO refs (song_id, tier, clip_idx, path, seed, approved,
                                               created, origin, qc_json, scene_number)
                  VALUES (?,?,?,?,?,0,?,?,?,?)""",
               sid, tier, r["clip_idx"], r["path"], r.get("seed"), now, origin, qc, sn)
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
    # Job args own plates. Do not fall back to plan() auto scene_bases.
    pose_bases = args.get("pose_bases") or {}
    results = pipeline.reroll(song["slug"], tier, sb["json_path"], anchor_name,
                               song["mp3_path"], args["clip_indices"], progress,
                               guard=tiers.compose_guardrail(tier, album),
                               body=album_profile(album)["body"],
                               note=args.get("note", ""), cast=cast,
                               bases=pose_bases,
                               n=args.get("n") or 0,
                               seed_min=args.get("seed_min", 8000),
                               seed_max=args.get("seed_max", 11000),
                               step=args.get("step") or "equal")
    now = time.time()
    bases = ref_score_bases(song, tier, anchor["path"] if anchor else None)
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
        sn = _clip_scene_number(song, tier, r["clip_idx"])
        db.run("""INSERT OR IGNORE INTO refs (song_id, tier, clip_idx, path, seed, approved,
                                               created, origin, qc_json, scene_number)
                  VALUES (?,?,?,?,?,0,?,?,?,?)""",
               sid, tier, r["clip_idx"], r["path"], r.get("seed"), now, origin, qc, sn)
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
    landed = list(paths)
    if args.get("refine", True):
        for src in list(paths):
            try:
                dest = refine_generated_still(src, progress, {"slug": safe_name(p["name"])})
                landed.append(dest)
            except Exception as e:
                progress(f"refine skipped: {e}")
    bases = [args.get("anchor_path") or args.get("source_path")]
    now = time.time()
    n_gen = len(paths)
    for i, cover in enumerate(landed):
        qc = score_generated_still(cover, [b for b in bases if b], prompt, progress)
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created, qc_json) VALUES (?,?,?,?,?,?)",
               None, "artwork", cover,
               json.dumps({"playlist_id": args["playlist_id"], "model": args.get("model"),
                           "prompt": prompt,
                           "origin": "refine" if i >= n_gen else "gen"}),
               now, qc)
    shown = landed[-1] if len(landed) > n_gen else landed[0]
    progress(f"{len(landed)} cover candidate(s); using the first")
    db.run("UPDATE playlists SET image_path=? WHERE id=?", shown, args["playlist_id"])
    return {"path": shown}


@jobs.handler("t2i")
def h_t2i(args, progress):
    """Local text-to-image for Media → New Image. Not Mage."""
    album = (args.get("album") or "").strip()
    parts = []
    if album:
        prof = album_profile(album)
        parts += [prof.get("identity"), prof.get("wardrobe"), prof.get("body"),
                  prof.get("style_text"), prof.get("world")]
    parts.append(args["prompt"])
    composed = " ".join(x for x in parts if x and str(x).strip())
    try:
        tiers.check_text(composed, "image prompt")
    except ValueError as e:
        raise RuntimeError(str(e)) from e
    guard = tiers.compose_guardrail(args.get("tier") or "xxx", album)
    lora = 1.0 if args.get("lightning") else 0.0
    paths = pipeline.gen_artwork(
        safe_name(f"t2i_{int(time.time())}"), composed, progress,
        anchor_path=args.get("anchor_path"),
        guard=guard, n=int(args.get("n") or 1),
        size=int(args.get("width") or 1024),
        height=int(args.get("height") or args.get("width") or 1024),
        lora_strength=lora,
        style_lora=args.get("style_lora") or "",
        style_lora_strength=args.get("style_lora_strength") or 1.0)
    if not paths:
        raise RuntimeError("the image render produced no file")
    now = time.time()
    dest_dir = os.path.join(db.DATA, "t2i")
    os.makedirs(dest_dir, exist_ok=True)
    kept = []
    for i, src in enumerate(paths):
        dest = os.path.join(dest_dir, f"t2i_{int(now * 1000)}_{i}.png")
        shutil.copy2(src, dest)
        db.run(
            "INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
            None, "t2i", dest,
            json.dumps({"album": album, "prompt": args["prompt"], "composed": composed,
                        "model": args.get("model"), "width": args.get("width"),
                        "height": args.get("height"),
                        "lightning": bool(args.get("lightning")),
                        "style_lora": args.get("style_lora") or ""}),
            now)
        kept.append(dest)
    progress(f"{len(kept)} image(s) in {dest_dir}")
    return {"path": kept[0], "n": len(kept)}


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
    bases = ref_score_bases(
        song, tier, args.get("face_path") or args.get("image_path"))
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
        sn = _clip_scene_number(song, tier, r["clip_idx"])
        db.run("""INSERT OR IGNORE INTO refs (song_id, tier, clip_idx, path, seed, approved,
                                               created, origin, qc_json, scene_number)
                  VALUES (?,?,?,?,?,0,?,?,?,?)""",
               sid, tier, r["clip_idx"], r["path"], r.get("seed"), now, args["mode"], qc, sn)
    return {"count": len(landed), "mode": args["mode"]}


@jobs.handler("clips")
def h_clips(args, progress):
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    sb = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", sid, tier)
    video_model = args.get("video_model") or models.default_cli("video")
    ref_paths = _approved_scene_ref_paths(song, tier, video_model)
    if video_model == "i2v":
        progress("i2v: prompt-driven only -- this render has no beat sync or mouth movement")
    if args.get("refine"):
        progress("refiner pass ON: T5-A on the LTX take (not the s2v hop); roughly double LTX render time")
    # T2-11: a chain successor is its own job with clip_idx set; only render that
    # clip. A batch job (no clip_idx) still renders the whole song.
    only = None
    prev_clip = None
    if "clip_idx" in args and args["clip_idx"] is not None:
        only = [int(args["clip_idx"])]
        pred = args.get("depends_on_clip")
        if pred is None:
            try:
                board = load_storyboard(sb)
                plan = build_song.clip_chain_plan(
                    board.get("scenes") or [], video_model)
                item = next((p for p in plan if p["clip_idx"] == only[0]), None)
                pred = None if item is None else item.get("depends_on")
            except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError):
                pred = None
        if pred is not None:
            landed = db.one(
                "SELECT path FROM clips WHERE song_id=? AND tier=? AND clip_idx=?",
                sid, tier, int(pred))
            if not landed or not landed["path"] or not os.path.isfile(landed["path"]):
                raise RuntimeError(
                    f"T2-11: clip {only[0]} waits on clip {pred}, which has not landed")
            prev_clip = landed["path"]
    results = pipeline.gen_clips(song["slug"], tier, sb["json_path"], song["mp3_path"], ref_paths,
                                  progress, video_model=video_model,
                                  ref_motion=args.get("ref_motion"),
                                  control_video=args.get("control_video"),
                                  refine=bool(args.get("refine")),
                                  only=only, prev_clip=prev_clip)
    for r in results:
        db.run("""INSERT INTO clips (song_id, tier, clip_idx, path, status) VALUES (?,?,?,?,'done')
                  ON CONFLICT(song_id, tier, clip_idx) DO UPDATE SET path=excluded.path, status='done'""",
               sid, tier, r["clip_idx"], r["path"])
        try:
            score_landed_clip(r["path"], song, tier, r["clip_idx"], progress)
        except Exception as e:
            progress(f"clip identity qc skipped: {e}")
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
    qc_service.attach_sheet_review(sheet, verdict, kind="image")
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

    Never writes over song["mp3_path"]. Picking a take is a separate act
    (T8-2) and does not write that column. Use is for edits, not takes.
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
    # New Song (Media): there is no upload. The first generated take IS the
    # original. Pick still does not overwrite a song that already has audio
    # (T8-2). Opt-in via as_new_song so existing-song takes stay candidates.
    if (sid and args.get("as_new_song") and kept and origin == "generated"
            and song and not song["mp3_path"]):
        db.run("UPDATE songs SET mp3_path=?, duration=? WHERE id=?",
               kept[0], args["seconds"], sid)
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               sid, "audio_original", kept[0], None, time.time())
        progress("first take is this song's original")
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
    fname = f"{base}{suffix}_{time.time_ns()}.{ext}" if set_row else f"{base}{suffix}.{ext}"
    out = os.path.join(outdir, fname)
    if set_row and os.path.exists(out):
        fname = f"{base}{suffix}_{time.time_ns()}_{os.getpid()}.{ext}"
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
    # T1-25: name measured I/TP on the asset; flag a miss of its own target.
    meta["loudness"] = mixer.export_loudness(out, args.get("items") or [])
    new_id = db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
                    None, "set", out, json.dumps(meta), time.time())
    if set_id:
        db.run("UPDATE sets SET updated=? WHERE id=?", time.time(), set_id)
        prevs = [a for a in db.q(
            "SELECT * FROM assets WHERE kind='set' AND id<? ORDER BY id DESC", new_id)
                 if db.jset(a).get("set_id") == set_id]
        if prevs:
            qc_service.record_pair(
                "set_rerender", prevs[0]["path"], out,
                group=qc_service.lineage_group("set_rerender", out, set_id=set_id))
    return {"path": out}


# ------------------------------------------------------------------ media --

def _media_thumb(real, width):
    """Grid-sized JPEG so 100+ candidate tiles do not stall the single worker."""
    from PIL import Image
    width = max(64, min(int(width), 640))
    stamp = f"{os.path.getmtime(real):.3f}:{os.path.getsize(real)}:{width}"
    key = hashlib.sha256(f"{real}:{stamp}".encode()).hexdigest()[:20]
    dest = os.path.join(db.DATA, "thumbs", str(width), key + ".jpg")
    if not os.path.isfile(dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with Image.open(real) as im:
            im = im.convert("RGB")
            im.thumbnail((width, width * 2), Image.Resampling.BILINEAR)
            im.save(dest, "JPEG", quality=70, optimize=True)
    return FileResponse(dest, media_type="image/jpeg")


@app.get("/media/{path:path}")
def media(path: str, w: int = 0):
    if "\x00" in path:
        raise HTTPException(400, "invalid path")
    real = os.path.realpath("/" + path)
    if not any(real == root or real.startswith(root + os.sep) for root in MEDIA_ROOTS):
        raise HTTPException(403, "path not allowed")
    if not os.path.isfile(real):
        raise HTTPException(404)
    if w:
        try:
            return _media_thumb(real, w)
        except Exception:
            pass
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
    seen = set()
    for a in db.q("SELECT * FROM assets WHERE kind='set' ORDER BY id DESC"):
        meta = db.jset(a)
        sid = meta.get("set_id")
        if sid is not None:
            label = set_names.get(sid, "(deleted set)")
            song_ids = set_members.get(sid, [])
            href = f"/sets/{sid}"
            key = ("set", sid, meta.get("mode") or "", meta.get("tier") or "")
        else:
            pid = meta.get("playlist_id")
            label = pl_names.get(pid, "(deleted playlist)")
            song_ids = pl_members.get(pid, [])
            href = "/sets"
            key = ("pl", pid, meta.get("mode") or "", meta.get("tier") or "")
        if key in seen:
            continue
        seen.add(key)
        if meta.get("tier"):
            label += f" {meta['tier'].upper()}"
        if meta.get("mode") == "audio":
            label += " (audio)"
        for song_id in song_ids:
            out.setdefault(song_id, []).append(
                {"id": a["id"], "label": label, "href": href})
    return out


def wants_json(request):
    """True when the caller asked for JSON rather than a redirect.

    The Library's buttons all go through app.js's api() helper, which sets this
    header; the same routes still answer a plain form post with a redirect, so
    the page keeps working with JavaScript off. One convention, both paths --
    rather than a parallel /api/* tree that would double every route here.
    """
    return "application/json" in (request.headers.get("accept") or "")


def wants_hx(request):
    return (request.headers.get("hx-request") or "").lower() in ("1", "true")


def json_or_redirect(request, payload, loc):
    """Same route, two answers: JSON for fetch, 303 for a plain form post."""
    if wants_json(request):
        return JSONResponse(payload)
    return RedirectResponse(loc, status_code=303)


async def _api_body(request):
    """JSON object or form fields. T6-A1 curl loops send either."""
    ctype = request.headers.get("content-type") or ""
    if "application/json" in ctype:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "body must be JSON")
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise HTTPException(400, "body must be a JSON object")
        return body
    form = await request.form()
    return {k: form.get(k) for k in form}


def _json_row(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return {k: row[k] for k in row.keys()}


def _svc_http(exc):
    """Map a service error to HTTP. The service decides; this only translates."""
    if isinstance(exc, LookupError):
        raise HTTPException(404, str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(400, str(exc))
    if isinstance(exc, RuntimeError):
        raise HTTPException(500, str(exc))
    raise exc


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
            "video_by_tier": latest,
            "video_matrix": VIDEO_MATRIX_TIERS,
            "sets": in_sets.get(s["id"], [])}


def _library_ctx():
    """Library page context. song_count from library_service (T6-A2-library)."""
    songs = db.q("SELECT * FROM songs ORDER BY created DESC")
    in_sets = sets_by_song()
    entries = [song_entry(s, in_sets) for s in songs]
    nums = library_service.numbers()
    album_genres = {}
    for p in db.q(
            "SELECT name, genre, subgenre, genre2, subgenre2 FROM playlists "
            "WHERE kind='playlist'"):
        if not (p["genre"] or p["genre2"]):
            continue
        album_genres[p["name"]] = {
            "genre": p["genre"] or "", "subgenre": p["subgenre"] or "",
            "genre2": p["genre2"] or "", "subgenre2": p["subgenre2"] or "",
        }
    return {
        "songs": entries,
        "genre_data": GENRE_DATA,
        "song_count": nums["song_count"],
        "album_genres": album_genres,
    }


@app.get("/", response_class=HTMLResponse)
@app.get("/songs", response_class=HTMLResponse)
def index(request: Request):
    """Library list. GET / and GET /songs share one handler; JSON is GET /api/songs."""
    return templates.TemplateResponse(request, "index.html", _library_ctx())


@app.get("/api/songs")
def api_songs():
    """Library list as JSON. song_count from library_service (T6-A2-library)."""
    nums = library_service.numbers()
    songs = db.q(
        "SELECT id, slug, title, album, genre, duration, created FROM songs "
        "ORDER BY created DESC")
    return JSONResponse({
        "song_count": nums["song_count"],
        "songs": [_json_row(s) for s in songs],
    })


@app.get("/api/songs/{id}")
def api_song(id: int):
    """One song's state for the song page. Fetch updates cards without a reload."""
    song = get_song_or_404(id)
    boards = db.q(
        "SELECT tier, scene_count, created FROM storyboards WHERE song_id=? ORDER BY tier",
        id)
    job_rows = db.q(
        "SELECT id, kind, status, progress, error, started, finished FROM jobs "
        "WHERE song_id=? ORDER BY id DESC LIMIT 20", id)
    active = next((j for j in job_rows
                   if j["status"] in ("queued", "running", "cancelling")), None)
    return JSONResponse({
        "song": _json_row(song),
        "storyboards": [_json_row(b) for b in boards],
        "jobs": [_json_row(j) for j in job_rows],
        "active_job": _json_row(active),
    })


@app.get("/api/nav")
def api_nav():
    """Topbar links as JSON. Same list base.html iterates (UIUX §8 / T6-A2-nav)."""
    return JSONResponse({"links": nav_service.links()})


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
    album = album.strip()
    if album and not genre:
        pl = db.one(
            "SELECT genre, subgenre, genre2, subgenre2 FROM playlists "
            "WHERE name=? AND kind='playlist'", album)
        if pl and (pl["genre"] or pl["genre2"]):
            genre, subgenre = pl["genre"] or "", pl["subgenre"] or ""
            genre2, subgenre2 = pl["genre2"] or "", pl["subgenre2"] or ""
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


@app.get("/media", response_class=HTMLResponse)
def media_page(request: Request, new: str = ""):
    """Create surface: New Song (ACE-Step) or New Image (local t2i)."""
    albums = [r["name"] for r in db.q(
        "SELECT name FROM playlists WHERE kind='playlist' ORDER BY name") if r["name"]]
    default = models.default_for("t2i") or models.default_for("artwork")
    t2i_models = []
    seen = set()
    live = {}
    try:
        live = {e["key"]: e for e in models.catalog()}
    except Exception:
        live = {}
    for key, spec in models.CATALOG.items():
        if spec.get("role") not in ("t2i", "artwork") or key in seen:
            continue
        seen.add(key)
        row = live.get(key) or {}
        wired = key in models.T2I_WIRED
        on_box = bool(row.get("available", True))
        t2i_models.append({
            "key": key, "label": spec["label"],
            "available": on_box,
            "runnable": wired and on_box,
            "default": key == default and wired,
        })
    loras = civitai.list_installed()
    recent = db.q(
        "SELECT * FROM assets WHERE kind='t2i' ORDER BY id DESC LIMIT 24")
    images = []
    for row in recent:
        meta = db.jset(row)
        images.append({
            "id": row["id"], "path": row["path"],
            "label": (meta.get("prompt") or "t2i")[:48],
        })
    pane = (new or "").strip().lower()
    if pane not in ("song", "image"):
        pane = ""
    return templates.TemplateResponse(request, "media.html", {
        "albums": albums, "t2i_models": t2i_models, "images": images,
        "pane": pane, "loras": loras,
        "civitai_set": bool(creds.get("civitai")),
    })


@app.post("/media/songs")
def media_new_song(request: Request, title: str = Form(...), album: str = Form(""),
                   tags: str = Form(""), lyrics: str = Form(""),
                   seconds: float = Form(30.0), n: int = Form(1),
                   seed: str = Form(""), explicit: bool = Form(False)):
    """Create a song from ACE-Step. First take becomes the original."""
    tags = " ".join((tags or "").split())
    if not tags:
        raise HTTPException(400, "a song needs at least one style tag")
    if len(tags) > MAX_TAGS:
        raise HTTPException(400, f"tags is {len(tags)} characters; keep it under {MAX_TAGS}")
    if len(lyrics or "") > MAX_LYRICS:
        raise HTTPException(400, f"lyrics is {len(lyrics)} characters; keep it under {MAX_LYRICS}")
    if not 1.0 <= seconds <= MAX_AUDIO_SECS:
        raise HTTPException(400, f"seconds must be between 1 and {MAX_AUDIO_SECS:g}")
    if not 1 <= n <= MAX_AUDIO_TAKES:
        raise HTTPException(400, f"takes must be between 1 and {MAX_AUDIO_TAKES}")
    seed_n = None
    if (seed or "").strip():
        try:
            seed_n = int(seed)
        except ValueError:
            raise HTTPException(400, "seed must be a whole number, or blank for random") from None
    slug = unique_slug(title)
    sid = db.upsert_song(
        slug, title=title.strip() or slug, album=(album or "").strip(),
        style_text=tags, explicit=int(explicit))
    if (lyrics or "").strip():
        db.store_lyrics(sid, lyrics, source="supplied")
        try:
            prompts.touch(f"song:{sid}", "audio_gen_lyrics", lyrics, "saved")
        except ValueError:
            pass
        try:
            prompts.touch(f"song:{sid}", "song_lyrics", lyrics, "saved")
        except ValueError:
            pass
    args = {"song_id": sid, "tags": tags, "lyrics": lyrics or "",
            "seconds": float(seconds), "n": int(n), "as_new_song": True}
    if seed_n is not None:
        args["seed"] = seed_n
    jid = jobs.enqueue("audio", args, song_id=sid)
    return json_or_redirect(
        request, {"job_id": jid, "kind": "audio", "song_id": sid},
        f"/songs/{sid}")


@app.post("/media/images")
def media_new_image(request: Request, prompt: str = Form(...), album: str = Form(""),
                    model: str = Form(""), size: str = Form("896x1216"),
                    n: int = Form(1), attach_her: str = Form(""),
                    lightning: str = Form(""), style_lora: str = Form(""),
                    style_lora_strength: float = Form(1.0)):
    """Queue local t2i. Album look is retrieved into the prompt."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "an image needs a prompt")
    try:
        tiers.check_text(prompt, "image prompt")
    except ValueError as e:
        raise HTTPException(400, str(e))
    n = max(1, min(int(n or 1), 4))
    width, height = 896, 1216
    if "x" in (size or ""):
        try:
            w_s, h_s = size.lower().split("x", 1)
            width, height = int(w_s), int(h_s)
        except ValueError:
            raise HTTPException(400, "size must look like 896x1216") from None
    album = (album or "").strip()
    key = model or models.default_for("t2i") or models.default_for("artwork")
    spec = models.CATALOG.get(key) or {}
    if spec.get("role") not in ("t2i", "artwork") or key not in models.T2I_WIRED:
        raise HTTPException(
            400,
            f"'{key}' is on the box but has no studio t2i graph yet — "
            "use Qwen-Image-Edit 2511")
    style_lora = " ".join((style_lora or "").replace("\\", "/").split())
    if style_lora.startswith("/") or ".." in style_lora.split("/"):
        raise HTTPException(400, "style LoRA must be a filename under models/loras")
    if style_lora and style_lora not in set(civitai.list_installed()):
        raise HTTPException(400, f"LoRA {style_lora!r} is not installed — fetch it below")
    anchor_path = None
    if attach_her:
        if not album:
            raise HTTPException(400, "pick an album to attach her identity front")
        front = chosen_anchor("album", album, "xxx") or chosen_anchor("album", album, "r")
        if not front:
            raise HTTPException(400, f"no chosen identity front on {album!r}")
        anchor_path = front["path"]
    try:
        strength = float(style_lora_strength)
    except (TypeError, ValueError):
        strength = 1.0
    strength = max(0.0, min(strength, 1.5))
    jid = jobs.enqueue("t2i", {
        "prompt": prompt, "album": album, "model": key,
        "width": width, "height": height, "n": n,
        "anchor_path": anchor_path, "lightning": bool(lightning),
        "style_lora": style_lora, "style_lora_strength": strength,
        "tier": "xxx" if album else "r",
    })
    return json_or_redirect(
        request, {"job_id": jid, "kind": "t2i"}, "/media?new=image")


@app.post("/media/images/delete")
async def media_delete_images(request: Request):
    """Remove selected t2i assets and their files."""
    ids = []
    if wants_json(request):
        body = await _api_body(request)
        raw = body.get("ids") if isinstance(body, dict) else None
        if isinstance(raw, list):
            ids = raw
    if not ids:
        form = await request.form()
        ids = list(form.getlist("id"))
    gone = []
    for raw in ids:
        try:
            aid = int(raw)
        except (TypeError, ValueError):
            continue
        row = db.one("SELECT * FROM assets WHERE id=? AND kind='t2i'", aid)
        if not row:
            continue
        if _within_data(row["path"]) and os.path.isfile(row["path"]):
            try:
                os.remove(row["path"])
            except OSError:
                pass
        db.run("DELETE FROM assets WHERE id=?", aid)
        gone.append(aid)
    if not gone:
        raise HTTPException(400, "no selected images to delete")
    return json_or_redirect(request, {"deleted": gone}, "/media?new=image")


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
        genre_ids = [r["id"] for r in db.q("SELECT id FROM songs")]
        return JSONResponse({"queued": queued, "genre_ids": genre_ids})
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

Each track below may include a production style prompt, title, album, and lyrics.
If a style prompt is present it usually names the genre directly. Where the
prompt names two styles (often separated by a slash), the first is the primary
and the second goes in genre2/subgenre2. If there is no style prompt, classify
from title, album and lyrics using ONLY the taxonomy.

First COPY a short exact phrase from the track text as evidence. The FIRST
style named in a style prompt is always the primary -- do not reorder by
what seems more specific.

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
    rows = [r for r in (db.one(
        "SELECT id, title, album, style_text, lyrics FROM songs WHERE id=?", i)
                        for i in ids) if r]
    if not rows:
        raise HTTPException(400, "those songs were not found")

    def _genre_blob(r):
        bits = [f'title="{r["title"]}"', f'album="{(r["album"] or "")}"']
        st = (r["style_text"] or "").strip()
        if st:
            bits.append("style=" + st[:GENRE_CLIP])
        ly = " ".join((r["lyrics"] or "").split())[:200]
        if ly:
            bits.append("lyrics=" + ly)
        return " ".join(bits)

    blobs = {r["id"]: _genre_blob(r) for r in rows}
    listing = "\n".join(f'{r["id"]}. {blobs[r["id"]]}' for r in rows)
    try:
        out, model = vision.ask_text(GENRE_SUGGEST_SYSTEM,
                                      GENRE_SUGGEST_USER.format(
                                          taxonomy=json.dumps(GENRE_DATA), listing=listing))
        data = vision.json_or_raise(out, "genre suggestion")
    except Exception as e:
        raise HTTPException(502, f"could not read the style prompts: {e}") from None

    suggestions, dropped = [], []
    for item in (data.get("tracks") if isinstance(data, dict) else data) or []:
        sid = item.get("id")
        if sid not in blobs:
            dropped.append({"song_id": sid, "why": "not a song that was asked about"})
            continue
        # TWO checks, not one. The taxonomy check catches an invented label; only
        # the evidence check catches a confident answer about a track the model
        # never actually read, and that is the failure no vocabulary can see.
        evidence = (item.get("evidence") or "").strip()
        if not evidence or evidence not in blobs[sid]:
            dropped.append({"song_id": sid, "why": "evidence is not quoted from the track text"})
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


def _bulk_genre_fields(body):
    """Validated genre columns to write. Blank means leave alone (T10-3)."""
    genre, subgenre = valid_genre_or_400(body.get("genre"), body.get("subgenre"), "genre")
    genre2, subgenre2 = valid_genre_or_400(body.get("genre2"), body.get("subgenre2"), "genre2")
    fields = {}
    if genre:
        fields["genre"], fields["subgenre"] = genre, subgenre
    if genre2:
        fields["genre2"], fields["subgenre2"] = genre2, subgenre2
    if not fields:
        raise HTTPException(400, "pick a genre to apply")
    return fields


def _bulk_genre_changing(ids, fields):
    """Song ids whose stored values would actually differ. Missing ids skipped."""
    changing = []
    for sid in ids:
        row = db.one(
            "SELECT id, genre, subgenre, genre2, subgenre2 FROM songs WHERE id=?", sid)
        if not row:
            continue
        if any((row[k] or "") != fields[k] for k in fields):
            changing.append(int(row["id"]))
    return changing


@app.post("/songs/genres")
async def bulk_set_genres(request: Request):
    """Apply one genre decision to many songs at once.

    A BLANK genre means LEAVE IT ALONE, never "clear it": someone setting only
    the secondary genre on twelve songs must not silently lose the primary on all
    twelve. Clearing is a different intention and deliberately has no control
    here. A genre carries its own subgenre, so picking a genre and leaving the
    subgenre blank does clear that subgenre -- they are one choice, not two.

    preview=true returns the count that would change and writes nothing (T10-7).
    Values are checked against genres.json before any write (T10-5).
    """
    body = await request.json()
    ids = [int(i) for i in (body.get("song_ids") or [])]
    if not ids:
        raise HTTPException(400, "no songs selected")
    fields = _bulk_genre_fields(body)
    changing = _bulk_genre_changing(ids, fields)
    if body.get("preview"):
        return JSONResponse({"would_change": len(changing), "song_ids": changing})
    sets = ", ".join(f"{k}=?" for k in fields)
    # One transaction (T10-6 / T6-14): a crash mid-loop rolls back every row.
    c = db.conn()
    c.execute("BEGIN")
    try:
        for sid in changing:
            c.execute(f"UPDATE songs SET {sets} WHERE id=?", (*fields.values(), sid))
        c.commit()
    except Exception:
        c.rollback()
        raise
    updated = []
    for sid in changing:
        row = db.one("SELECT id, genre, subgenre, genre2, subgenre2 FROM songs WHERE id=?", sid)
        updated.append({"song_id": row["id"], "genre": row["genre"] or "",
                        "subgenre": row["subgenre"] or "", "genre2": row["genre2"] or "",
                        "subgenre2": row["subgenre2"] or ""})
    # the STORED values, so the page paints what was saved rather than what was
    # typed -- otherwise a value dropped by validation stays visible and looks fine
    return JSONResponse({"updated": updated, "changed": len(updated)})


@app.post("/albums/genres")
async def set_album_genres(request: Request):
    """Save album default genres and copy them onto every song on that album."""
    body = await request.json()
    album = (body.get("album") or "").strip()
    if not album:
        raise HTTPException(400, "name the album")
    fields = {
        "genre": "", "subgenre": "", "genre2": "", "subgenre2": "",
    }
    fields.update(_bulk_genre_fields(body))
    pl = db.one("SELECT id FROM playlists WHERE name=? AND kind='playlist'", album)
    if pl:
        db.run(
            "UPDATE playlists SET genre=?, subgenre=?, genre2=?, subgenre2=? WHERE id=?",
            fields.get("genre") or "", fields.get("subgenre") or "",
            fields.get("genre2") or "", fields.get("subgenre2") or "", pl["id"])
    ids = [r["id"] for r in db.q("SELECT id FROM songs WHERE album=?", album)]
    changing = _bulk_genre_changing(ids, fields) if ids else []
    if changing:
        sets = ", ".join(f"{k}=?" for k in fields)
        c = db.conn()
        c.execute("BEGIN")
        try:
            for sid in changing:
                c.execute(f"UPDATE songs SET {sets} WHERE id=?", (*fields.values(), sid))
            c.commit()
        except Exception:
            c.rollback()
            raise
    updated = []
    for sid in ids:
        row = db.one("SELECT id, genre, subgenre, genre2, subgenre2 FROM songs WHERE id=?", sid)
        if row:
            updated.append({
                "song_id": row["id"], "genre": row["genre"] or "",
                "subgenre": row["subgenre"] or "", "genre2": row["genre2"] or "",
                "subgenre2": row["subgenre2"] or "",
            })
    return JSONResponse({
        "album": album, "updated": updated, "changed": len(changing),
        "defaults": fields,
    })


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


def _song_lane_payload(item_id, lane, points=None, curve=None):
    if points is None:
        points = automation.read(item_id, lane) if item_id else []
    if curve is None:
        curve = automation.read_curve(item_id, lane) if item_id else "linear"
    audio = (automation.item_audio(item_id) if item_id
             else {"frags": [], "suppress_loudnorm": False})
    return {"lane": lane, "points": points, "curve": curve, "automation": audio}


@app.get("/api/songs/{id}/automation")
def api_song_automation(id: int):
    """T8-13: read every lane the song editor has stored."""
    get_song_or_404(id)
    item = automation.editor_item(id, create=False)
    lanes = {}
    if item:
        for lane in sorted(automation.lanes_for(item)):
            lanes[lane] = _song_lane_payload(item, lane)
    return JSONResponse({"song_id": id, "lanes": lanes})


@app.get("/api/songs/{id}/automation/{lane}")
def api_song_automation_lane(id: int, lane: str):
    """T8-13: read one lane. Empty is a missing curve, not a 404."""
    get_song_or_404(id)
    try:
        automation._lane(lane)
    except ValueError as e:
        raise HTTPException(400, str(e))
    item = automation.editor_item(id, create=False)
    return JSONResponse(_song_lane_payload(item, lane))


@app.post("/api/songs/{id}/automation/{lane}")
async def api_song_automation_write(id: int, lane: str, request: Request):
    """T8-13: write one lane through automation.save. The stored,
    decimated curve comes back and item_audio consumes it."""
    get_song_or_404(id)
    body = await _api_body(request)
    points = body.get("points")
    if points is None:
        raise HTTPException(400, "points required")
    curve = body.get("curve") or "linear"
    try:
        item = automation.editor_item(id)
        stored = automation.save(item, lane, points, curve=curve)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse(_song_lane_payload(item, lane, stored, curve))


def _song_editor_mix_items(song_id):
    """One-item list for the song editor in mix_audio / set_duration shape.

    T8-14: same fields _set_render_items stamps on a set item (audio path,
    trim, effects_json, automation fragments) so prediction and render walk
    the same document. No editor row yet is still one plain track.
    """
    song = get_song_or_404(song_id)
    mp3 = song["mp3_path"]
    if not mp3 or not os.path.isfile(mp3):
        raise HTTPException(400, "no audio on this song")
    item_id = automation.editor_item(song_id, create=False)
    if item_id is None:
        return [{"audio": mp3, "transition": "cut", "secs": 0.0, "hold": 0.0,
                 "in_secs": None, "out_secs": None, "gain_db": 0.0,
                 "effects_json": None,
                 "automation": {"frags": [], "suppress_loudnorm": False}}]
    row = db.one("SELECT * FROM set_items WHERE id=?", item_id)
    return [{"audio": mp3, "transition": row["transition"] or "cut",
             "secs": row["secs"] or 0.0, "hold": _hold_of(row),
             "in_secs": row["in_secs"], "out_secs": row["out_secs"],
             "gain_db": row["gain_db"] or 0.0,
             "effects_json": row["effects_json"],
             "automation": automation.item_audio(item_id)}]


@app.get("/api/songs/{id}/preview")
def api_song_editor_preview(id: int):
    """T8-15: browser playback is a proxy (T1-16 on this surface).

    not_applied is computed from the editor item's effects_json via
    mixer.preview_proxy — not a static catalogue.
    """
    get_song_or_404(id)
    item_id = automation.editor_item(id, create=False)
    if item_id is None:
        items = [{"effects_json": None}]
    else:
        row = db.one("SELECT effects_json FROM set_items WHERE id=?", item_id)
        items = [{"effects_json": row["effects_json"] if row else None}]
    return mixer.preview_proxy(items)


@app.get("/api/songs/{id}/editor/duration")
def api_song_editor_duration(id: int):
    """T8-14: predicted length for the song editor, via mixer.set_duration."""
    items = _song_editor_mix_items(id)
    try:
        predicted = mixer.set_duration(items, key="audio")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"song_id": id, "predicted": predicted})


@app.post("/api/songs/{id}/editor/render")
def api_song_editor_render(id: int):
    """T8-14: emit prediction first, then mix_audio. Predicted length is
    the rendered length to mixer.SET_DURATION_TOLERANCE (imported by the
    criterion's check, never restated here)."""
    song = get_song_or_404(id)
    items = _song_editor_mix_items(id)
    try:
        predicted = mixer.set_duration(items, key="audio")
    except ValueError as e:
        raise HTTPException(400, str(e))
    outdir = os.path.join(db.DATA, "audio", song["slug"])
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"editor_{int(time.time() * 1000)}.mp3")
    mixer.mix_audio(items, out)
    duration = mixer.probe(out)["duration"]
    return JSONResponse({
        "song_id": id, "predicted": predicted, "duration": duration, "path": out,
    })


@app.get("/api/songs/{id}/media")
def api_song_media(id: int):
    """T8-16: song-level media bag. Same payload the song HTML card reads."""
    try:
        return media_service.list_bag(id)
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.get("/songs/{id}", response_class=HTMLResponse)
def song_page(request: Request, id: int):
    song = get_song_or_404(id)
    storyboards = {r["tier"]: r for r in db.q("SELECT * FROM storyboards WHERE song_id=?", id)}
    style_assets = db.q("SELECT * FROM assets WHERE song_id=? AND kind='style' ORDER BY id DESC", id)
    renders = db.q("SELECT * FROM renders WHERE song_id=? ORDER BY id DESC", id)
    media = media_service.list_bag(id)
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
    takes = db.list_takes(id)
    audio_original = db.one("SELECT * FROM assets WHERE song_id=? AND kind='audio_original'", id)
    # anchors belong to the song's ALBUM, not the song -- this is a read-only
    # summary for convenience; management happens on /anchors. Shared
    # Kitty/actor keepers must appear here too (T4-25).
    chosen_anchors = db.q(
        f"""SELECT * FROM anchors WHERE {db.visible_anchor_sql()} AND chosen=1
            ORDER BY tier, view""", song["album"] or "")
    # a tier is offered for clip generation once every SCENE has an approved
    # still. Chain parts after the first use the previous clip's last frame.
    clips_ready_tiers = []
    for t, sb in storyboards.items():
        heads = _scene_head_idxs(song, t)
        if not heads:
            continue
        storyboard_service.stamp_ref_scenes(song, t)
        approved_sns = {r["scene_number"] for r in
                        db.q("""SELECT scene_number FROM refs
                                WHERE song_id=? AND tier=? AND approved=1
                                  AND scene_number IS NOT NULL""", id, t)}
        if all(sn in approved_sns for sn in heads):
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
    # chosen identity front. start_refs 400s without one (see its own check).
    # Pose sheets on other views do not satisfy that gate — the page says so
    # instead of "no anchor" when the library is already full.
    album = song["album"] or ""
    anchor_by_tier = {t: chosen_anchor("album", album, t) for t in storyboards}
    pose_count_by_tier = {t: chosen_pose_count("album", album, t) for t in storyboards}
    pose_library_by_tier = {}
    for a in db.q(f"""SELECT a.*, c.name AS character_name
                      FROM anchors a LEFT JOIN characters c ON c.id = a.character_id
                      WHERE {db.visible_anchor_sql('a')} AND a.chosen=1
                      ORDER BY a.tier, c.name, a.view, a.id""", album):
        pose_library_by_tier.setdefault(a["tier"], []).append(a)
    ref_progress_by_tier = {}
    for t in storyboards:
        heads = _scene_head_idxs(song, t)
        n_scenes = len(heads) if heads else (storyboards[t]["scene_count"] or 0)
        n_refs = 0
        n_approved = 0
        storyboard_service.stamp_ref_scenes(song, t)
        sns = list(heads)
        if sns:
            n_refs = db.one(
                f"SELECT COUNT(*) n FROM refs WHERE song_id=? AND tier=? AND scene_number IN ({','.join('?'*len(sns))})",
                id, t, *sns)["n"]
            n_approved = db.one(
                f"SELECT COUNT(*) n FROM refs WHERE song_id=? AND tier=? AND approved=1 AND scene_number IN ({','.join('?'*len(sns))})",
                id, t, *sns)["n"]
        n_clips = db.one(
            "SELECT COUNT(*) n FROM clips WHERE song_id=? AND tier=? AND status='done'",
            id, t)["n"]
        ref_progress_by_tier[t] = {
            "scenes": n_scenes, "refs": n_refs, "approved": n_approved, "clips": n_clips}
    # the video models offered for the clip pass, each named with what it is
    # designed for -- the catalogue is the single place that knows. Only WIRED
    # ones are offered: a catalogued evaluation candidate has no renderer value
    # and must not be selectable.
    default_video = models.default_for("video")
    wired = models.renderable("video")
    backends = pipeline.swarm_backends()
    video_models = [{"value": wired[e["key"]], "label": e["label"], "purpose": e["purpose"],
                     "available": models.available_on_fleet(e["key"], backends),
                     "default": e["key"] == default_video}
                    for e in models.catalog(role="video") if e["key"] in wired]
    all_tiers = tiers.all_tiers()
    form_tier = next(iter(storyboards), None) or (all_tiers[0]["name"] if all_tiers else "")
    beat_count = len(json.loads(song["beat_grid_json"])) if song["beat_grid_json"] else 0
    song_paths = set()
    for row in renders:
        if row["path"]:
            song_paths.add(jobs.canonical_path(row["path"]))
    for row in db.q("SELECT path FROM clips WHERE song_id=?", id):
        if row["path"]:
            song_paths.add(jobs.canonical_path(row["path"]))
    for row in db.q("SELECT path FROM refs WHERE song_id=?", id):
        if row["path"]:
            song_paths.add(jobs.canonical_path(row["path"]))
    findings = [f for f in qc_service.queue() if f["path"] in song_paths]
    splice_eaten_secs = 2 * mixer.SPLICE_XFADE
    # T6-19: dry-run plans only for operator-confirmed tiers. Template
    # interpolates; no recompute (T6-A4). Unconfirmed → no cleanup card.
    cleanup_plans = []
    seen_cleanup_tiers = set()
    for r in renders:
        if not cleanup_service.is_confirmed(r):
            continue
        t = r["tier"]
        if t in seen_cleanup_tiers:
            continue
        seen_cleanup_tiers.add(t)
        try:
            cleanup_plans.append(cleanup_service.plan_clip_cleanup(id, t))
        except cleanup_service.UnconfirmedError:
            continue
    pose_plan_by_tier = {}
    for t in storyboards:
        try:
            pose_plan_by_tier[t] = pose_plan.plan(song, t)
        except (LookupError, OSError, json.JSONDecodeError, ValueError):
            pose_plan_by_tier[t] = None
    face_tier = "xxx" if "xxx" in storyboards else (next(iter(storyboards), "") or "")
    faces = _face_choices(song, face_tier) if face_tier else []
    return templates.TemplateResponse(request, "song.html", {
        "song": song, "tiers": all_tiers, "storyboards": storyboards, "beat_count": beat_count,
        "approved_tiers": approved_tiers, "reviews": reviews,
        "style_assets": style_assets, "chosen_anchors": chosen_anchors,
        "clips_ready_tiers": clips_ready_tiers, "anchor_by_tier": anchor_by_tier,
        "pose_count_by_tier": pose_count_by_tier,
        "pose_library_by_tier": pose_library_by_tier,
        "ref_progress_by_tier": ref_progress_by_tier,
        "pose_plan_by_tier": pose_plan_by_tier,
        "faces": faces,
        "video_models": video_models,
        "renders": renders, "song_jobs": song_jobs, "active_job": active_job,
        "models": chat_models,
        "audio_duration": audio_duration, "audio_edits": audio_edits, "audio_original": audio_original,
        "takes": takes, "audio_model": models.get(models.default_for("audio")),
        "best_model": best, "render_tiers": render_tiers,
        "findings": findings,
        "media": media,
        "cleanup_plans": cleanup_plans,
        "lyrics_replace_warning": lyrics.REPLACE_WARNING,
        "splice_eaten_secs": splice_eaten_secs,
        "song_arc": _song_arc_beat(song),
        "playlist_id": _playlist_id_for_album(album),
        "lyrics_box": prompts.box(f"song:{song['id']}", "song_lyrics",
                                  song["lyrics"] or ""),
        "style_box": prompts.box(f"song:{song['id']}", "song_style",
                                 song["style_text"] or ""),
        "audio_edit_box": prompts.box(f"song:{song['id']}", "audio_edit", ""),
        "audio_lyrics_box": prompts.box(f"song:{song['id']}", "audio_gen_lyrics", ""),
        **storyboard_form_ctx(song, form_tier, chat_models, best),
    })


# --------------------------------------------------------------------- QC --
#
# docs/TRD-3. The checks live in qc.py (pure, no db) and the recording and queue
# in qc_service.py (no FastAPI), so everything below is a thin call -- no
# arithmetic, no defaulting, no decision. If a route handler decided something,
# a mobile client could not.
#
# JSON stays the contract (T6-A1). GET /qc is the finding-row page (T3-19):
# measured / expected / unit, editable remedy, approve. The template
# interpolates queue() rows; it does not compute (T6-A4).


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
    """Tier 1 over one song's artefacts at one tier. Forwards to run_song.

    Assembled expect is songs.duration (T6-13a). T3-32: the operator
    path is start_qc, which calls run_song in-process and does not
    enqueue behind the one worker thread.
    """
    return qc_service.run_song(args["song_id"], args.get("tier") or "", progress)


@app.post("/songs/{id}/qc")
def start_qc(request: Request, id: int, tier: str = Form("")):
    get_song_or_404(id)
    qc_service.run_song(id, tier)
    return json_or_redirect(request, {"ok": True, "kind": "qc"}, f"/songs/{id}")


@app.get("/qc", response_class=HTMLResponse)
def qc_queue_page(request: Request):
    """The review queue as finding-rows (T3-4 / T3-19 / T3-27 / T3-17-ui)."""
    return templates.TemplateResponse(request, "qc.html", {
        "findings": qc_service.queue(),
    })


@app.post("/qc/findings/{fid}/approve")
def qc_approve_form(fid: int, text: str = Form("")):
    """HTML sign-off: store the edited remedy, then approve (T3-19)."""
    try:
        if (text or "").strip():
            qc_service.set_remedy(fid, text)
        qc_service.approve(fid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except KeyError:
        raise HTTPException(404, f"no finding {fid}")
    return RedirectResponse("/qc", status_code=303)


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
    only forwards. A ValueError is a bad finding (dismissed, no remedy).
    Missing is 404 (get raises ValueError 'no finding …')."""
    try:
        row = qc_service.approve(fid)
    except ValueError as e:
        msg = str(e)
        if msg.startswith("no finding"):
            raise HTTPException(404, msg)
        raise HTTPException(400, msg)
    except KeyError:
        raise HTTPException(404, f"no finding {fid}")
    return {"ok": True, "id": row["id"], "status": row["status"]}


@app.get("/api/qc/lineage")
def api_lineage(kind: str, group: str):
    """T6-A5: predecessor and successor, both listed and selectable."""
    try:
        return JSONResponse({"candidates": qc_service.listed(kind, group)})
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/qc/lineage/select")
async def api_lineage_select(request: Request, kind: str = Form(""),
                             group: str = Form(""), path: str = Form("")):
    """T6-A5: pick either listed candidate. The route forwards; listed/select decide."""
    ctype = (request.headers.get("content-type") or "")
    if "json" in ctype:
        body = await request.json()
        kind = body.get("kind") or kind
        group = body.get("group") or group
        path = body.get("path") or path
    try:
        return JSONResponse({"candidates": qc_service.select(kind, group, path)})
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/qc/run")
async def api_qc_run(request: Request):
    """T6-A1 / TRD-3: run QC over JSON. Findings appear without the HTML page."""
    body = await _api_body(request)
    path = (body.get("path") or "").strip()
    kind = (body.get("kind") or "image").strip() or "image"
    if not path:
        raise HTTPException(400, "path required")
    found = qc_service.run_artefact(path, kind)
    return JSONResponse({"findings": found})


@app.post("/api/qc/findings/{fid}/recheck")
def api_qc_recheck(fid: int):
    """Re-run the finding's artefact against the same stored expectation."""
    try:
        row = qc_service.get(fid)
    except ValueError as e:
        raise HTTPException(404, str(e))
    found = qc_service.run_artefact(row["path"], row["kind"] or "image")
    return JSONResponse({"findings": found, "finding": _json_row(qc_service.get(fid))})


@app.post("/songs/{id}/analyse")
def start_analyse(request: Request, id: int):
    song = get_song_or_404(id)
    if not song["mp3_path"]:
        raise HTTPException(400, "no audio to analyse -- upload an mp3 first")
    jid = jobs.enqueue("analyse", {"song_id": id}, song_id=id)
    return json_or_redirect(request, {"job_id": jid, "kind": "analyse"}, f"/songs/{id}")


@app.post("/songs/{id}/downbeat-offset")
def set_downbeat_offset(request: Request, id: int, downbeat_offset: int = Form(...)):
    """analyse.py only guesses bar one from the first four beats -- a set
    built on the wrong guess sounds wrong in a way no tuning fixes, and a
    human fixes it in a second by ear. See db.MIGRATIONS' comment."""
    get_song_or_404(id)
    if not 0 <= downbeat_offset <= 3:
        raise HTTPException(400, "downbeat_offset must be 0-3")
    db.run("UPDATE songs SET downbeat_offset=? WHERE id=?", downbeat_offset, id)
    return json_or_redirect(
        request, {"ok": True, "downbeat_offset": downbeat_offset}, f"/songs/{id}")


@app.post("/songs/{id}/explicit")
def toggle_explicit(request: Request, id: int):
    """Toggle whether this track's LYRICS are explicit. Metadata about the
    lyrics only -- never gates or selects a tier, see h_storyboard's comment."""
    song = get_song_or_404(id)
    new = 0 if song["explicit"] else 1
    db.run("UPDATE songs SET explicit=? WHERE id=?", new, id)
    return json_or_redirect(request, {"ok": True, "explicit": new}, f"/songs/{id}")


@app.post("/songs/{id}/lyrics")
def save_lyrics(request: Request, id: int, lyrics_text: str = Form(...)):
    get_song_or_404(id)
    # T10-18b: an xxx work refuses a minor reference in lyrics too.
    if db.one("SELECT id FROM storyboards WHERE song_id=? AND tier=?", id, "xxx"):
        try:
            lyrics.screen(lyrics_text, tier="xxx")
        except ValueError as e:
            raise HTTPException(400, str(e))
    # T10-8: supplied text is not a transcription; clear any prior backend.
    # T10-9: store_lyrics marks lyrics_edited so a re-fetch cannot discard it.
    db.store_lyrics(id, lyrics_text, source="supplied")
    try:
        prompts.touch(f"song:{id}", "song_lyrics", lyrics_text, "saved")
    except ValueError:
        pass
    return json_or_redirect(request, {"ok": True, "lyrics": lyrics_text}, f"/songs/{id}")


@app.post("/songs/{id}/retranscribe")
def retranscribe_lyrics(request: Request, id: int):
    """Explicit re-transcribe replaces stored lyrics, including edits (T10-9)."""
    song = get_song_or_404(id)
    if not song["mp3_path"]:
        raise HTTPException(400, "this song has no audio to transcribe")
    jid = jobs.enqueue("transcribe", {"song_id": id, "force": True}, song_id=id)
    return json_or_redirect(
        request, {"job_id": jid, "kind": "transcribe"}, f"/songs/{id}")


@app.post("/songs/{id}/unlock-minor")
def unlock_minor_route(id: int):
    """T10-21: explicit unlock on an empty re-screen. Never silent."""
    get_song_or_404(id)
    try:
        return JSONResponse(unlock_minor(id))
    except tiers.ContentRefused as e:
        raise HTTPException(400, str(e)) from e


@app.post("/songs/{id}/style-text")
def save_style_text(request: Request, id: int, style_text: str = Form(...)):
    """The prompt the TRACK was generated from. Stored, shown and editable --
    it is not sent to grok or the renderer: it describes drums and vocals, and
    the storyboard prompt is about pictures. Storyboards used to carry exactly
    this text as `suno_style_reference` and it was stripped out as dead weight.
    """
    get_song_or_404(id)
    db.run("UPDATE songs SET style_text=? WHERE id=?", style_text, id)
    try:
        prompts.touch(f"song:{id}", "song_style", style_text, "saved")
    except ValueError:
        pass
    return json_or_redirect(request, {"ok": True, "style_text": style_text}, f"/songs/{id}")


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


def _empty_gallery_families(tier):
    default_key = "nude" if tier == "xxx" else "clothed"
    return [
        {"key": "clothed", "rows": [], "default": default_key == "clothed"},
        {"key": "nude", "rows": [], "default": default_key == "nude"},
    ]


def _pad_gallery_cast(album, tier, characters):
    """Lead + every album character gets a tab, even with no sheets this tier.

    nest_anchor_groups only saw people who already had a row. Tiger/Panther
    then vanished on R. Actors stays last and only if a multi-body plate exists.
    """
    lead = pose_plan.lead_name(album) or "Lead"
    cast = list(db.q(
        "SELECT id, name FROM characters WHERE scope_value=? ORDER BY name",
        album or ""))
    have = {c["character_id"]: c for c in characters if not c.get("ensemble")}
    actors = [c for c in characters if c.get("ensemble")]
    padded = []
    for cid, name in [(None, lead)] + [(r["id"], r["name"]) for r in cast]:
        existing = have.get(cid)
        if existing:
            padded.append(existing)
        else:
            padded.append({
                "character_id": cid,
                "character_name": name,
                "ensemble": False,
                "families": _empty_gallery_families(tier),
            })
    return padded + actors


def nest_anchor_groups(group_list):
    """Tier → character → clothed/nude → one row per camera position.

    Multi-body plates (split roast, cowgirl, stamped actors) sit on an
    Actors tab, not under the lead. Flat groups stay available for tests
    that walk candidates; the page renders this nest so a dozen sheets
    do not dump as one long column.
    """
    albums = {}
    for g in group_list:
        album = g["scope_value"]
        if album not in albums:
            albums[album] = {"scope_kind": g["scope_kind"], "album": album,
                             "tier_map": {}}
        tmap = albums[album]["tier_map"]
        tier = g["tier"] or ""
        tmap.setdefault(tier, {})
        owner = g["character_name"] or pose_plan.lead_name(g.get("scope_value"))
        sample = (g.get("candidates") or [g])[0]
        row = dict(sample) if hasattr(sample, "keys") else (sample or g)
        row.setdefault("view", g.get("view"))
        if g.get("ensemble") or pose_plan.is_ensemble(row, album, owner):
            who = ("__actors__", "Actors")
        else:
            who = (g["character_id"], owner)
        tmap[tier].setdefault(who, {"clothed": {}, "nude": {}})
        family = view_family(g["view"])
        pos = view_position_label(g["view"])
        tmap[tier][who][family].setdefault(pos, []).append(g)
    out = []
    for album, sec in albums.items():
        tiers = []
        for name, chars in sec["tier_map"].items():
            characters = []
            ordered = sorted(chars.items(), key=lambda it: (
                2 if it[0][0] == "__actors__" else (0 if it[0][0] is None else 1),
                it[0][1] or ""))
            for (cid, cname), fams in ordered:
                families = []
                for fam_key in ("clothed", "nude"):
                    rows = [{"position": pos, "groups": gs}
                            for pos, gs in fams[fam_key].items()]
                    families.append({"key": fam_key, "rows": rows})
                default_key = ("nude" if name == "xxx"
                               and any(f["key"] == "nude" and f["rows"] for f in families)
                               else "clothed")
                for fam in families:
                    fam["default"] = fam["key"] == default_key
                characters.append({
                    "character_id": None if cid == "__actors__" else cid,
                    "character_name": cname,
                    "ensemble": cid == "__actors__",
                    "families": families,
                })
            characters = _pad_gallery_cast(album, name, characters)
            tiers.append({"name": name, "characters": characters})
        out.append({"scope_kind": sec["scope_kind"], "album": sec["album"],
                    "tab_id": f"anchor-gallery-{len(out)}",
                    "tiers": tiers})
    return out


def _anchors_classification_ctx(album, song_id="", gap_tier=""):
    """T4-21 / T4-23: keepers and holes for the open song + selected tier."""
    album = (album or "").strip()
    keepers, songs, gap, open_id, song_tiers = [], [], None, None, []
    if album:
        # Empty live DB: seed once from repo sidecar (T4-21/T4-22). library()
        # still never reads a file — ensure_sidecar_seed calls import_sidecar.
        classification.ensure_sidecar_seed(album)
        keepers = classification.keepers(album)["images"]
        songs = list(db.q(
            "SELECT id, title FROM songs WHERE album=? ORDER BY id", album))
        raw = str(song_id or "").strip()
        wanted = int(raw) if raw.isdigit() else None
        if wanted and any(s["id"] == wanted for s in songs):
            open_id = wanted
        else:
            for s in songs:
                if db.one("SELECT 1 AS n FROM storyboards WHERE song_id=? LIMIT 1",
                          s["id"]):
                    open_id = s["id"]
                    break
            if open_id is None and songs:
                open_id = songs[0]["id"]
        if open_id:
            song_tiers = [r["tier"] for r in db.q(
                "SELECT DISTINCT tier FROM storyboards WHERE song_id=? ORDER BY tier",
                open_id)]
            want = (gap_tier or "").strip()
            if want not in song_tiers:
                want = None
            try:
                gap = storyboard_service.pose_gap(open_id, tier=want)
            except (LookupError, ValueError, RuntimeError):
                gap = None
    import pose_generate
    for im in keepers:
        path = pose_generate.resolve_image_path(im.get("path") or "")
        if path:
            im["path"] = path
            im["url"] = media_url(path)
    rows = classification.group_rows(keepers)
    n_clothed = sum(1 for im in keepers if im.get("wardrobe") == "clothed")
    n_nude = sum(1 for im in keepers if im.get("wardrobe") == "nude")
    return {
        "class_album": album,
        "class_keepers": keepers,
        "class_keeper_rows": rows,
        "class_keeper_chips": rows,
        "class_n_clothed": n_clothed,
        "class_n_nude": n_nude,
        "album_songs": songs,
        "pose_gap": gap,
        "open_song_id": open_id,
        "song_tiers": song_tiers,
    }


@app.get("/anchors", response_class=HTMLResponse)
def anchors_page(request: Request, scope_kind: str = "", scope_value: str = "",
                 album: str = "", roster_tier: str = "", song_id: str = "",
                 gap_tier: str = ""):
    # One album at a time. The generate form's album select is the same
    # subject as the gallery; swapping the form via htmx left every album's
    # groups on the page. `album` is the select's name so a full-page GET
    # from that control filters without a second parameter.
    # ponytail: unfiltered /anchors is still unbounded. A LIMIT cannot go here
    # without splitting a group across the boundary and miscounting `unpicked`;
    # if it ever hurts, paginate by GROUP (scope, character, tier, view).
    playlists = db.q("SELECT id, name FROM playlists WHERE kind='playlist' ORDER BY name")
    names = [p["name"] for p in playlists]
    scope_value = (scope_value or album or "").strip()
    if not scope_value and names:
        scope_value = names[0]
    clauses, params = [], []
    if scope_value and not scope_kind:
        clauses.append(db.visible_anchor_sql("a"))
        params.append(scope_value)
    else:
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
        shown_scope = scope_value if r["scope_kind"] == db.SHARED_KIND else r["scope_value"]
        key = (r["scope_kind"], shown_scope, r["character_id"], r["character_name"],
               r["tier"], r["view"])
        groups.setdefault(key, []).append(r)
    group_list = [{"scope_kind": k[0], "scope_value": k[1], "character_id": k[2],
                   "character_name": k[3], "tier": k[4], "view": k[5], "candidates": v,
                   # how many rejects this group is carrying: every generation
                   # adds N candidates and only one is ever picked
                   "unpicked": sum(1 for c in v if not c["chosen"])}
                  for k, v in groups.items()]
    albums = sorted({s["album"] for s in db.q("SELECT DISTINCT album FROM songs") if s["album"]})
    coverage_by_tier = {}
    if scope_value:
        tiers_needed = {g["tier"] for g in group_list}
        for row in db.q(
                """SELECT DISTINCT sb.tier FROM storyboards sb
                   JOIN songs s ON s.id = sb.song_id WHERE s.album=?""",
                scope_value):
            tiers_needed.add(row["tier"])
        for t in sorted(tiers_needed):
            try:
                coverage_by_tier[t] = pose_plan.album_coverage(scope_value, t)
            except (LookupError, OSError, ValueError, json.JSONDecodeError):
                continue
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
    shown_roster = (roster_tier or "").strip()
    if shown_roster not in coverage_by_tier:
        shown_roster = ""
    gallery = nest_anchor_groups(group_list)
    sticky_tiers = []
    for trow in tiers.all_tiers():
        t = trow["name"]
        cov = coverage_by_tier.get(t) or {}
        n_chars = 0
        for sec in gallery:
            for tr in sec.get("tiers") or []:
                if tr.get("name") != t:
                    continue
                for ch in tr.get("characters") or []:
                    if any((f.get("rows") or []) for f in (ch.get("families") or [])):
                        n_chars += 1
        sticky_tiers.append({
            "name": t,
            "n_have": cov.get("n_have") or 0,
            "n_needed": cov.get("n_needed") or 0,
            "n_chars": n_chars,
        })
    gen_tier = (gap_tier or "").strip()
    return templates.TemplateResponse(request, "anchors.html", dict(
        anchor_form_ctx(scope_value, selected_tiers=[gen_tier] if gen_tier else []),
        groups=group_list, gallery=gallery,
        known_albums=albums, playlists=playlists,
        coverage_by_tier=coverage_by_tier,
        roster_tier=shown_roster,
        sticky_tiers=sticky_tiers,
        failed_jobs=fresh, active_jobs=active,
        **_anchors_classification_ctx(scope_value, song_id, gap_tier)))


MAX_ANCHOR_UPLOADS = 24


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
        if not _ref_visible_for_character(meta, album, character_id):
            continue
        # Assign / upload-pose share this file with the chosen sheet.
        # Dropping the sheet used to delete the bytes and leave the row,
        # which then reappeared here as an empty card (Street Cats #141).
        if not a["path"] or not os.path.isfile(a["path"]):
            db.run("DELETE FROM assets WHERE id=?", a["id"])
            continue
        if _ref_assigned_as_sheet(a["id"], album, character_id):
            continue
        out.append(ref_fields(a))
    return out


def _ref_visible_for_character(meta, album, character_id):
    """Solo photos stay on their owner. A multi-body base is visible to
    every named actor (and on the lead form)."""
    names = [n for n in (meta.get("actors") or []) if n]
    if len(names) >= 2:
        if character_id is None:
            return True
        row = db.one("SELECT name FROM characters WHERE id=?", character_id)
        return bool(row and row["name"] in names)
    return (meta.get("character_id") or None) == (character_id or None)


def _ref_assigned_as_sheet(asset_id, album, character_id=None):
    """True when this upload is already a chosen pose sheet (T7-20).

    Assigned files live in the candidate grid. Showing them again under
    Base images is the same photograph twice.
    """
    for row in db.q(f"""SELECT render_json FROM anchors
                        WHERE {db.visible_anchor_sql()}
                          AND chosen=1 AND character_id IS ?""",
                    album, character_id):
        meta = db.jset(row, "render_json")
        if meta.get("source") == "upload" and meta.get("asset_id") == asset_id:
            return True
    return False


def ref_fields(row):
    """Base-image row plus named-pose fields stored in meta_json."""
    meta = db.jset(row)
    d = dict(row)
    d["pose_name"] = " ".join(str(meta.get("pose_name") or "").split())[:80]
    d["pose_tier"] = (meta.get("pose_tier") or "").strip()
    d["role"] = (meta.get("role") or "identity").strip() or "identity"
    d["pose_nude"] = bool(meta.get("pose_nude"))
    d["actors"] = [n for n in (meta.get("actors") or []) if n]
    return d


def _one_form_value(form, key):
    """Exactly one non-empty value, or ''. Repeated fields on the generate form
    make form.get() return the first card — often an unnamed identity photo."""
    vals = [" ".join(str(v or "").split()) for v in form.getlist(key)]
    vals = [v for v in vals if v]
    return vals[0] if len(vals) == 1 else ""


def update_ref_meta(asset_id, **fields):
    row = db.one("SELECT * FROM assets WHERE id=? AND kind='anchor_ref'", asset_id)
    if not row:
        raise HTTPException(404, "no such base image")
    meta = db.jset(row)
    for k, v in fields.items():
        if v is None:
            meta.pop(k, None)
        else:
            meta[k] = v
    db.run("UPDATE assets SET meta_json=? WHERE id=?", json.dumps(meta), asset_id)
    return db.one("SELECT * FROM assets WHERE id=?", asset_id)


async def _save_anchor_refs(album, character_id, uploads, actors=None):
    """Persist uploaded base images and return their asset rows.

    Files live once under uploads/anchors/shared/. The album name stays
    in meta so the generate form still filters "this album's bases", but
    assigning the photo as a sheet writes a shared anchors row.
    """
    dest_dir = db.shared_anchor_dir()
    stamp = int(time.time() * 1000)
    saved = []
    for i, f in enumerate(uploads):
        path = await save_upload(f, MAX_IMAGE, dest_dir, "image", prefix=f"ref{i}_{stamp}")
        meta = {"scope_kind": db.SHARED_KIND, "scope_value": album,
                "character_id": character_id}
        if actors:
            meta["actors"] = list(actors)
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               None, "anchor_ref", path,
               json.dumps(meta), time.time())
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
                            pose=form.get("pose") or "",
                            selected_actor_ids=_selected_actor_ids(
                                form, album, character_id))


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
    form = await request.form()
    if character_id is not None:
        char = get_character_or_404(character_id)
        if char["scope_value"] != album:
            raise HTTPException(400, f"character {char['name']!r} belongs to {char['scope_value']!r}")
    actor_names, _extra = _form_actors(form, album, character_id)
    await _save_anchor_refs(album, character_id, uploads, actors=actor_names)
    # htmx swaps the form back in with the new thumbnails; a plain browser still
    # gets the redirect, so this works with JavaScript off exactly as before
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request, "_anchor_form.html",
            _anchor_ctx_from_form(await request.form(), album, character_id))
    return RedirectResponse(f"/anchors?scope_value={quote(album)}", status_code=303)


@app.post("/anchors/refs/{asset_id}/meta")
async def save_anchor_ref_meta(request: Request, asset_id: int):
    """Name a pose, assign a tier, mark identity vs pose plate."""
    form = await request.form()
    name = " ".join((form.get("pose_name") or "").split())[:80]
    if name:
        try:
            tiers.check_text(name, "pose name")
            tiers.check_override(name)
        except ValueError as e:
            raise HTTPException(400, str(e))
    tier = (form.get("pose_tier") or "").strip()
    if tier:
        valid_tier_or_400(tier)
    role = (form.get("role") or "identity").strip()
    if role not in ("identity", "pose"):
        raise HTTPException(400, "role must be identity or pose")
    nude = str(form.get("pose_nude") or "") in ("1", "on", "true", "yes")
    if name and role == "identity":
        role = "pose"
    actors = []
    seen = set()
    for raw in form.getlist("actor_name"):
        n = " ".join(str(raw or "").split())
        key = n.lower()
        if not n or key in seen:
            continue
        seen.add(key)
        actors.append(n)
    update_ref_meta(asset_id, pose_name=name, pose_tier=tier or None,
                    role=role, pose_nude=nude,
                    actors=actors or None)
    return JSONResponse({"ok": True, "id": asset_id, "pose_name": name,
                         "pose_tier": tier, "role": role, "pose_nude": nude,
                         "actors": actors})


@app.post("/anchors/refs/{asset_id}/assign")
async def assign_anchor_ref_as_sheet(request: Request, asset_id: int):
    """Use the uploaded photo itself as the chosen sheet for a named pose + tier."""
    row = db.one("SELECT * FROM assets WHERE id=? AND kind='anchor_ref'", asset_id)
    if not row:
        raise HTTPException(404, "no such base image")
    form = await request.form()
    fields = ref_fields(row)
    album = db.jset(row).get("scope_value") or (form.get("album") or "").strip()
    if not album:
        raise HTTPException(400, "this base image has no album")
    # The generate form repeats name="pose_name" / pose_tier on every card.
    # form.get() is the first card — often the unnamed identity pair. Trust
    # the saved meta, and only a single submitted value (htmx includes one
    # .ref-thumb).
    name = fields["pose_name"] or _one_form_value(form, "pose_name")[:80]
    if not name:
        raise HTTPException(400, "name the pose before assigning it as a sheet")
    tier = (fields["pose_tier"] or _one_form_value(form, "pose_tier")
            or _one_form_value(form, "tier"))
    if not tier:
        raise HTTPException(400, "pick a tier for this pose, or tick one on the form")
    valid_tier_or_400(tier)
    # T10-23: child-locked artefact cannot become an r/xxx sheet (plate/anchor).
    art_tier = tiers.content_tier_of(row)
    src = os.path.basename(row["path"] or "") or f"asset#{asset_id}"
    role = "plate" if (fields.get("role") == "pose" or form.get("role") == "pose") else "anchor"
    try:
        tiers.check_artefact_use(art_tier, tier, role=role, source=src)
    except tiers.ContentRefused as e:
        raise HTTPException(400, str(e))
    nude = fields["pose_nude"] or str(form.get("pose_nude") or "") in ("1", "on")
    if nude and not tiers.allows_nudity(tier):
        raise HTTPException(400, f"{tier.upper()} does not permit a nude sheet")
    view = pose_view_key(asset_id, nude)
    cid = db.jset(row).get("character_id")
    actor_names = list(fields.get("actors") or [])
    if not actor_names:
        seen = set()
        for raw in form.getlist("actor_name"):
            n = " ".join(str(raw or "").split())
            if n and n.lower() not in seen:
                seen.add(n.lower())
                actor_names.append(n)
    now = time.time()
    db.run("""UPDATE anchors SET chosen=0 WHERE scope_kind=? AND scope_value=?
              AND tier=? AND view=? AND (? IS NULL AND character_id IS NULL
                   OR character_id=?)""",
           db.SHARED_KIND, db.SHARED_VALUE, tier, view, cid, cid)
    db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen,
                                    created, character_id, render_json)
              VALUES (?,?,?,?,?,1,?,?,?)""",
           db.SHARED_KIND, db.SHARED_VALUE, tier, view, row["path"], now, cid,
           json.dumps({"source": "upload", "asset_id": asset_id, "pose_name": name,
                       "content_tier": art_tier or tier, "actors": actor_names}))
    update_ref_meta(asset_id, pose_name=name, pose_tier=tier, role="pose",
                    pose_nude=nude, actors=actor_names or None)
    return await _anchor_form_or_redirect(request, album)


@app.post("/anchors/upload-pose")
async def upload_pose_sheet(request: Request, album: str = Form(...),
                            tier: str = Form(...), key: str = Form(""),
                            label: str = Form("uploaded pose"),
                            nude: str = Form(""),
                            character_id: CharacterId = Form(None),
                            image: UploadFile = File(...)):
    """A sheet generated elsewhere (Mage, etc.) becomes the shared keeper.

    One file, one anchors row (scope_kind=shared). Any album can reference
    it. `album` is still required so the roster/redirect knows where the
    operator was standing; it is not a copy destination.
    """
    album = album.strip()
    if not album:
        raise HTTPException(400, "album required")
    valid_tier_or_400(tier)
    name = " ".join((label or "uploaded pose").split())[:80]
    is_nude = str(nude).lower() in ("1", "on", "true", "yes") or "nude" in name.lower()
    if is_nude and not tiers.allows_nudity(tier):
        raise HTTPException(400, f"{tier.upper()} does not permit a nude sheet")
    dest_dir = db.shared_anchor_dir()
    path = await save_upload(image, MAX_IMAGE, dest_dir, "image",
                             prefix=f"pose_{int(time.time() * 1000)}")
    now = time.time()
    cid = character_id
    group = None
    if cid is not None:
        char = get_character_or_404(cid)
        if char["scope_value"] != album:
            raise HTTPException(400, f"character {char['name']!r} belongs to {char['scope_value']!r}")
    if key:
        try:
            cov = pose_plan.album_coverage(album, tier)
            group = next((x for x in cov["needed"] if str(x["key"]) == str(key)), None)
            who = (group or {}).get("actors") or (group or {}).get("characters") or []
            if who and cid is None:
                cid = who[0].get("id")
        except (LookupError, OSError, ValueError, json.JSONDecodeError):
            group = None
    form = await request.form()
    actor_names = [n for n in form.getlist("actor_name") if str(n).strip()]
    if not actor_names and group:
        actor_names = [p.get("name") for p in
                       ((group.get("actors") or group.get("characters") or []))
                       if p.get("name")]
    aid = db.run(
        "INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
        None, "anchor_ref", path,
        json.dumps({"scope_kind": db.SHARED_KIND, "scope_value": album, "role": "pose",
                    "pose_name": name, "pose_tier": tier, "pose_nude": is_nude,
                    "source": "upload", "character_id": cid,
                    "actors": actor_names}),
        now)
    view = pose_view_key(aid, is_nude)
    db.run("""UPDATE anchors SET chosen=0 WHERE scope_kind=? AND scope_value=?
              AND tier=? AND view=? AND character_id IS ?""",
           db.SHARED_KIND, db.SHARED_VALUE, tier, view, cid)
    new_id = db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path,
                                            chosen, created, character_id, render_json)
                       VALUES (?,?,?,?,?,1,?,?,?)""",
                    db.SHARED_KIND, db.SHARED_VALUE, tier, view, path, now, cid,
                    json.dumps({"source": "upload", "asset_id": aid, "pose_name": name,
                                "character_id": cid, "actors": actor_names}))
    if group:
        try:
            pose_plan.stamp_binds(tier, group.get("binds") or [], new_id)
        except (LookupError, OSError, ValueError, json.JSONDecodeError):
            pass
    loc = f"/anchors?scope_value={quote(album)}&roster_tier={quote(tier)}"
    if wants_json(request):
        return JSONResponse({
            "ok": True, "id": new_id, "path": path, "media_url": media_url(path),
            "label": name, "key": key, "tier": tier, "album": album,
            "chosen": True,
        })
    if wants_hx(request):
        return _playlist_hx_album(request, album)
    return RedirectResponse(loc, status_code=303)


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
    payload = _use_anchor_as_ref(id)
    if wants_json(request):
        return JSONResponse(payload)
    row = db.one("SELECT * FROM anchors WHERE id=?", id)
    return await _anchor_form_or_redirect(request, row["scope_value"] if row else "")


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
    below 1.0 from an encoded image is the point of the control.

    T7-21 C1/C2 uses this same resolver so a same-pose label cannot sit
    on an empty-latent graph.
    """
    import pose_generate
    return pose_generate.denoise_labels(latent, DENOISE_VALUES)

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
        "The pairing worth knowing: mark a keeper with <strong>Use as this pose</strong>, "
        "then refine it here at 0.55 from the first reference. That varies a sheet you "
        "approved instead of re-interpreting the photographs and hoping."]},
    "denoise": {"label": "Denoise", "body": [
        "How much of the starting latent is replaced. 1.0 denoises it completely; lower values "
        "preserve some of what was already there.",
        "That only makes sense when something WAS already there. An empty latent is "
        "pure noise, so anything below 1.0 leaves part of the noise in the output.",
        "Starting from the first reference is the refine pass: denoise below 1.0 keeps "
        "that image's composition and size and redraws the surface. Sheet size is "
        "ignored then &mdash; the output inherits the reference."]},
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
        "CFG sweep reuses it at every guidance value.",
        "Clip reroll uses a min/max band with equal or fibonacci steps because that mint is "
        "N independent stills. This form is one base seed plus offsets. A range here would "
        "be a second, different contract."]},
    "pose": {"label": "Pose override", "body": [
        "Missing catalog ticks already send that pose's stance. This box replaces "
        "the camera view's standing clause when you generate without a catalog tick. "
        "Two contradictory positives do not average."]},
    "actors": {"label": "Actors", "body": [
        "Tick every body on this sheet. The photograph beside the name is that person's "
        "identity front, the image1 lock. All is every lead and cast member.",
        "Two or more land on the Actors tab. A multi-body photograph is the lock for "
        "intertwined poses &mdash; not three solo fronts glued together."]},
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

# T2-36: kind marks a help note (behind `?`) vs a day-8 warning that must stay
# visible. A client that cannot tell them apart will hide the wrong one.
HELP_NOTE = "note"
HELP_WARNING = "warning"

# Warnings that stay pinned beside the control on the HTML form (day 8). The
# API carries the same strings so a replacement client does not invent them.
ANCHOR_WARNINGS = {
    "negative": "not applied in fast mode — dropped, not sent at CFG 1.0",
    "denoise": "returns noise below 1.0",
}


def controls_help_payload(help_map=None, warnings=None):
    """T2-36: help text per control for any client.

    Empty entries are omitted (not present-and-empty). Each help entry is
    kind=note; day-8 footguns are kind=warning (as entry.warning or the
    whole entry when there is no note).
    """
    help_map = ANCHOR_HELP if help_map is None else help_map
    warnings = ANCHOR_WARNINGS if warnings is None else warnings
    out = {}
    for key, entry in (help_map or {}).items():
        if not entry:
            continue
        if isinstance(entry, dict):
            label = str(entry.get("label") or "").strip()
            body = entry.get("body")
            paras = [p for p in (body or []) if str(p).strip()] if body else []
            if not label and not paras:
                continue
            out[key] = {"kind": HELP_NOTE, "label": label, "body": list(body or [])}
        else:
            text = str(entry).strip()
            if not text:
                continue
            out[key] = {"kind": HELP_NOTE, "text": text}
    for key, text in (warnings or {}).items():
        text = str(text or "").strip()
        if not text:
            continue
        warn = {"kind": HELP_WARNING, "text": text}
        if key in out:
            out[key]["warning"] = warn
        else:
            out[key] = warn
    return out


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


def apply_view_default_size(view, render):
    """Portrait uses a head-and-shoulders latent by default. docs/TRD-7 T7-5.

    make_anchor.size_for_view is the source of truth. Unset width/height, and
    the standing full-body form default (896×1216), both become the view's
    size for portrait. An operator-chosen non-default size wins. Full-body
    views leave the dict alone so make_anchor's own default still applies when
    the form sent nothing.

    Must set width/height — a `size` string is dropped by ANCHOR_RENDER_FLAGS
    and never reaches EmptySD3LatentImage.
    """
    out = dict(render or {})
    want_w, want_h = make_anchor.size_for_view(view)
    full_w, full_h = make_anchor.DEFAULT_SIZE
    if (want_w, want_h) == (full_w, full_h):
        return out
    w, h = out.get("width"), out.get("height")
    if (w is None and h is None) or (w, h) == (full_w, full_h):
        out["width"], out["height"] = want_w, want_h
    out.pop("size", None)
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
    row = db.one(f"""SELECT path FROM anchors WHERE {db.visible_anchor_sql()}
                    AND (? IS NULL OR character_id IS ? OR character_id=?)
                    ORDER BY chosen DESC, (view='front') DESC, id DESC""",
                 album, character_id, character_id, character_id)
    return row["path"] if row else None


def _draft_one(album, view, current="", character_id=None, tier=None):
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
    # Unset tier is xxx (T10-25); a named lock is the T10-18 gate.
    return screen_prompt_field(text, "prompt", f"{view} draft", tier=tier)


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
    text = _draft_one(album, view, current, character_id, tier=tier or None)
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
    tier = (form.get("tier") or "").strip() or None
    prompts_out = {}
    for v in views:
        current = (form.get(anchor_prompt_field(tier or "", v))
                   or form.get(f"current_{v}") or "")
        prompts_out[v] = _draft_one(album, v, current, character_id, tier=tier)
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
        tiers.check_text(text, "anchor prompt", tier=tier)
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


@app.get("/prompt-versions/{vid}/text")
def prompt_version_text(vid: int):
    """One saved wording, for loading back into an album-look box."""
    row = prompts.get(vid)
    if not row:
        raise HTTPException(404, "that version no longer exists")
    return JSONResponse({"id": row["id"], "text": row["text"],
                         "label": row["label"],
                         "version": row["version_number"]})


@app.post("/prompt-versions/select")
async def select_prompt_version(request: Request):
    """Make this version the one a refresh loads."""
    body = await _api_body(request)
    row = prompts.get(body.get("id"))
    if not row:
        raise HTTPException(404, "that version no longer exists")
    prompts.remember(row["scope_value"], row["prompt_type"], row["id"],
                     tier=row["tier"], character_id=row["character_id"])
    return JSONResponse({"ok": True, "id": row["id"], "text": row["text"]})


@app.post("/prompt-versions/touch")
async def touch_prompt_version(request: Request):
    """Save a new wording if it changed, and remember it as current."""
    body = await _api_body(request)
    try:
        row = prompts.touch(
            str(body.get("scope") or ""),
            str(body.get("type") or ""),
            str(body.get("text") or ""),
            str(body.get("label") or "saved") or "saved",
            tier=str(body.get("tier") or ""),
            character_id=body.get("character_id"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    vers = [dict(v) for v in prompts.versions(
        row["scope_value"], row["prompt_type"], row["tier"], row["character_id"])]
    return JSONResponse({"ok": True, "id": row["id"], "text": row["text"],
                         "versions": vers})


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
    import guardrail as g
    settings = settings or {}
    pos = (typed or "").strip() or default_anchor_prompt(album, view, character_id)
    tier_text = tiers.compose_guardrail(tier, album)
    try:
        final = g.build_prompt(pos, tier_text, "anchor prompt preview", tier=tier)
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
    rows = db.q(f"""SELECT a.*, c.name AS character_name
                    FROM anchors a LEFT JOIN characters c ON c.id = a.character_id
                    WHERE {db.visible_anchor_sql('a')} AND a.tier=? AND a.view=?
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
        front = None
        for t in tiers_sel:
            front = chosen_anchor("album", album, t, "front")
            if front and front["path"]:
                break
        if front:
            notes.append("No base ticked — using the chosen identity front as image1 "
                         "(empty latent + her, the measured pose-candidate path).")
        else:
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
            tiers.check_text(text, f"{t.upper()} anchor prompt", tier=t)
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


def _as_str_list(value):
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v not in (None, "")]
    return [str(value)]


def _optional_int(value):
    if value in (None, ""):
        return None
    return int(value)


class _JsonForm:
    """form.get / getlist over a JSON object so enqueue is one path."""

    def __init__(self, data):
        self._d = data or {}

    def get(self, key, default=None):
        v = self._d.get(key, default)
        if isinstance(v, list):
            return v[0] if v else default
        return v

    def getlist(self, key):
        v = self._d.get(key)
        if v is None:
            return []
        if isinstance(v, list):
            return list(v)
        return [v]

    def items(self):
        return self._d.items()

    def __contains__(self, key):
        return key in self._d


def _named_pose_views(album, character_id, pose_ids):
    """Tick boxes on named base images become pose_<id>[_nude] views."""
    views = []
    for raw in pose_ids:
        try:
            aid = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(400, "a named pose id is not a number")
        row = db.one("SELECT * FROM assets WHERE id=? AND kind='anchor_ref'", aid)
        if not row:
            raise HTTPException(400, "a named pose you ticked no longer exists")
        fields = ref_fields(row)
        meta = db.jset(row)
        if meta.get("scope_value") != album or (meta.get("character_id") or None) != (character_id or None):
            raise HTTPException(400, "a named pose you ticked belongs to another album "
                                      "or character")
        if not fields["pose_name"]:
            raise HTTPException(400, "name every pose you tick before generating")
        views.append(pose_view_key(aid, fields["pose_nude"]))
    return views


def _paths_for_view(view, identity_paths):
    """A named pose conditions on identity photos plus that one plate."""
    aid = pose_asset_id(view)
    if not aid:
        return identity_paths
    row = db.one("SELECT path FROM assets WHERE id=? AND kind='anchor_ref'", aid)
    if not row:
        raise HTTPException(400, "a named pose image is missing")
    pose_path = row["path"]
    id_paths = [p for p in identity_paths if os.path.abspath(p) != os.path.abspath(pose_path)][:2]
    return (id_paths + [pose_path])[:pipeline.MAX_ANCHOR_REFS]


def _validate_anchor_request(album, tiers_sel, views_sel):
    """Shared by the HTML form and the T6-A1 JSON loop."""
    album = (album or "").strip()
    if not album:
        raise HTTPException(400, "choose an album")
    if not db.one("SELECT id FROM playlists WHERE name=? AND kind='playlist'", album):
        raise HTTPException(400, f"no album called {album!r} -- create it on /playlists first")
    selected_tiers = sorted(set(t for t in tiers_sel if t))
    # NO SILENT DEFAULT. This was `or ["front"]`. docs/TRD-4 T4-1, T4-3, T4-4.
    selected_views = sorted(set(v for v in views_sel if v))
    if not selected_tiers:
        raise HTTPException(400, "select at least one tier")
    if not selected_views:
        raise HTTPException(400, "select at least one view")
    for t in selected_tiers:
        valid_tier_or_400(t)
    for v in selected_views:
        if not known_anchor_view(v):
            raise HTTPException(400, f"view must be one of {', '.join(ANCHOR_VIEWS)} "
                                      f"or a named pose")
    plan = anchor_plan(selected_tiers, selected_views)
    combos = [(p["tier"], v) for p in plan for v in p["views"]]
    if not combos:
        raise HTTPException(400, "every view you picked is a nude one and no tier you picked "
                                  "permits nudity, so there is nothing to render. Tick a clothed "
                                  "view, or turn nudity on for a tier under Tiers.")
    return album, selected_tiers, selected_views, combos


def _selected_actor_ids(src, album, character_id):
    """actor_id ticks, or All, or the current character as a default."""
    getlist = getattr(src, "getlist", None)
    raw = [str(v) for v in (getlist("actor_id") if getlist else []) if v]
    all_on = str((src.get("actor_all") if hasattr(src, "get") else "") or "") in (
        "1", "on", "true", "yes")
    if all_on:
        return ["lead"] + [str(c["id"]) for c in album_cast(album)]
    if raw:
        return raw
    return ["lead"] if character_id is None else [str(character_id)]


def _form_actors(form, album, character_id):
    """Every body ticked on the generate form (All = every lead + cast)."""
    names, extra_ids, seen = [], [], set()
    for raw in _selected_actor_ids(form, album, character_id):
        if str(raw) == "lead":
            n = pose_plan.lead_name(album)
            if n and n.lower() not in seen:
                seen.add(n.lower())
                names.append(n)
            if character_id is not None:
                extra_ids.append(None)
            continue
        try:
            cid = int(raw)
        except (TypeError, ValueError):
            continue
        row = db.one("SELECT * FROM characters WHERE id=? AND scope_value=?",
                     cid, album)
        if not row:
            continue
        n = row["name"]
        if n and n.lower() not in seen:
            seen.add(n.lower())
            names.append(n)
        if cid != character_id:
            extra_ids.append(cid)
    if not names:
        names.append(pose_plan.lead_name(album) if character_id is None
                     else get_character_or_404(character_id)["name"])
    return names, extra_ids


def _actor_identity_paths(album, character_ids, work_tiers):
    """Chosen identity front for each extra body, first ticked tier that has one."""
    out = []
    for cid in character_ids:
        for t in work_tiers or []:
            front = chosen_anchor("album", album, t, "front", cid)
            if front and front["path"] and os.path.isfile(front["path"]):
                out.append(front["path"])
                break
    return out


def _collect_anchor_ref_paths(album, character_id, ref_ids, extra_paths=None,
                              work_tiers=None):
    """Resolve selected anchor_ref assets to paths. T10-23: a child-locked
    artefact cannot feed an r/xxx (or unset) work tier."""
    picked = []
    tiers_to_check = list(work_tiers) if work_tiers is not None else [None]
    for rid in ref_ids:
        row = db.one("SELECT * FROM assets WHERE id=? AND kind='anchor_ref'", int(rid))
        if not row:
            raise HTTPException(400, "a reference image you picked no longer exists")
        meta = db.jset(row)
        if meta.get("scope_value") != album or (meta.get("character_id") or None) != (character_id or None):
            raise HTTPException(400, "a reference image you picked belongs to another album "
                                      "or character")
        art_tier = tiers.content_tier_of(row)
        src = os.path.basename(row["path"] or "") or f"asset#{row['id']}"
        for wt in tiers_to_check:
            try:
                tiers.check_artefact_use(
                    art_tier, wt, role="reference", source=src)
            except tiers.ContentRefused as e:
                raise HTTPException(400, str(e))
        picked.append(row["path"])
    for p in extra_paths or []:
        path = os.path.abspath(str(p))
        if not os.path.isfile(path):
            raise HTTPException(400, "a reference path does not exist")
        picked.append(path)
    if not picked:
        # Empty latent + her front as image1 is the measured pose-candidate
        # path. Zero images is a stranger (plain t2i). Prefer a ticked base;
        # fall back to the chosen identity front so Generate can mint a new
        # pose without re-uploading photographs.
        for wt in (work_tiers or []):
            if not wt:
                continue
            front = chosen_anchor("album", album, wt, "front", character_id)
            if front and front["path"] and os.path.isfile(front["path"]):
                picked.append(front["path"])
                break
    if not picked:
        raise HTTPException(400, "pick at least one saved reference image, or upload one")
    for p in picked:
        try:
            classification.refuse_skip(album, path=p, character_id=character_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    if len(picked) > pipeline.MAX_ANCHOR_REFS:
        raise HTTPException(400, f"{len(picked)} reference images selected; the model conditions "
                                  f"on {pipeline.MAX_ANCHOR_REFS}. Untick some.")
    return picked


def _enqueue_anchor_jobs(album, selected_tiers, selected_views, combos, n,
                         character_id, form, paths, actors=None, pose=None):
    """Queue one job per planned sheet. Shared by HTML POST /anchors and /api/anchors."""
    if character_id is not None:
        char = get_character_or_404(character_id)
        if char["scope_value"] != album:
            raise HTTPException(400, f"character {char['name']!r} belongs to album "
                                      f"{char['scope_value']!r}, not to {album!r}")
    # T10-19: adding a nude view (or any non-locked tier sheet) re-screens each
    # album work at the destination tier before jobs land.
    album_songs = db.q(
        "SELECT id FROM songs WHERE album=? ORDER BY id", album or "")
    dests = set()
    for t, v in combos:
        if make_anchor.is_nude_view(v) or not tiers.allows_minor_depiction(t):
            dests.add(t if not tiers.allows_minor_depiction(t) else "xxx")
    for dest in sorted(dests):
        for srow in album_songs:
            try:
                tiers.screen_work_for_tier(srow["id"], dest)
            except ValueError as e:
                raise HTTPException(400, str(e))
    form_pose = (pose if pose is not None else (form.get("pose") or "")).strip()
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
            tiers.check_text(text, f"{t.upper()} anchor prompt", tier=t)
            tiers.check_override(text)
        except ValueError as e:
            raise HTTPException(400, str(e))
        pose_text = form_pose
        aid = pose_asset_id(v)
        if aid:
            prow = db.one("SELECT * FROM assets WHERE id=? AND kind='anchor_ref'", aid)
            pose_text = (ref_fields(prow)["pose_name"] if prow else "") or pose_text
        composed = (default_anchor_prompt(album, v, character_id, pose=pose_text or None)
                    or "").strip()
        if text and text == composed:
            text = ""
        if not text and form_pose:
            text = composed
        view_prompts[(t, v)] = text
    for t in selected_tiers:
        if f"tone_{t}" not in form:
            continue
        typed_tone = " ".join((form.get(f"tone_{t}") or "").split())
        if typed_tone == tiers.tier_text(t).strip():
            typed_tone = ""
        if typed_tone != tiers.override_text(album, t):
            try:
                tiers.set_override(album, t, typed_tone)
            except ValueError as e:
                raise HTTPException(400, str(e))
    render = anchor_render_settings(form)
    n = max(1, min(int(n or 4), 8))
    sweep = cfg_sweep_points(form, render, combos)
    queued = []
    plan_points = ([(t, v, None) for t, v in combos] if not sweep else
                   [(combos[0][0], combos[0][1], c) for c in sweep["cfgs"]])
    for t, v, cfg in plan_points:
        text = view_prompts[(t, v)]
        this_render = dict(render if cfg is None else dict(render, cfg=cfg, seed=sweep["seed"]))
        this_render = apply_view_default_size(v, this_render)
        this_n = n if cfg is None else sweep["n"]
        this_paths = _paths_for_view(v, paths)
        run_id = create_anchor_run(album, t, v, character_id, this_n, text, this_render,
                                    this_paths, tiers.compose_guardrail(t, album),
                                    chosen=render)
        jid = jobs.enqueue("anchor", {"scope_kind": "album", "scope_value": album, "tier": t,
                                       "view": v, "images": this_paths, "n": this_n,
                                       "character_id": character_id, "prompt": text,
                                       "render": this_render, "run_id": run_id,
                                       "actors": list(actors or [])})
        queued.append({"id": jid, "tier": t, "view": v, "prompt": text, "cfg": cfg,
                       "run_id": run_id})
    prompts.mark_used(form.getlist("used_version"))
    return {"queued": len(queued), "jobs": queued, "album": album,
            "tiers": selected_tiers, "views": selected_views,
            "n": sweep["n"] if sweep else n,
            "refs": len(paths), "render": render,
            "sweep": ({"cfgs": sweep["cfgs"], "seed": sweep["seed"],
                       "sheets": sweep["sheets"]} if sweep else None)}


def _record_anchor_ref(album, path, character_id=None):
    """Persist one existing image as an operator base photograph."""
    album = (album or "").strip()
    if not album:
        raise HTTPException(400, "choose an album")
    if not db.one("SELECT id FROM playlists WHERE name=? AND kind='playlist'", album):
        raise HTTPException(400, f"no album called {album!r}")
    if character_id is not None:
        char = get_character_or_404(character_id)
        if char["scope_value"] != album:
            raise HTTPException(400, f"character {char['name']!r} belongs to {char['scope_value']!r}")
    path = os.path.abspath(path or "")
    if not path or not os.path.isfile(path):
        raise HTTPException(400, "path must be an existing image file")
    existing = db.one("""SELECT * FROM assets WHERE kind='anchor_ref' AND path=?
                         ORDER BY id DESC""", path)
    if existing:
        meta = db.jset(existing)
        if (meta.get("scope_value") == album
                and (meta.get("character_id") or None) == (character_id or None)):
            return existing
    db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
           None, "anchor_ref", path,
           json.dumps({"scope_value": album, "character_id": character_id}), time.time())
    return db.one("SELECT * FROM assets WHERE path=? AND kind='anchor_ref' ORDER BY id DESC", path)


def _ref_payload(row):
    return {"id": row["id"], "path": row["path"]}


def _refs_payload(album, character_id=None):
    return [_ref_payload(a) for a in anchor_refs(album, character_id)]


def _anchor_groups(scope_kind="", scope_value=""):
    clauses, params = [], []
    if scope_value and not scope_kind:
        clauses.append(db.visible_anchor_sql("a"))
        params.append(scope_value)
    else:
        if scope_kind:
            clauses.append("a.scope_kind=?")
            params.append(scope_kind)
        if scope_value:
            clauses.append("a.scope_value=?")
            params.append(scope_value)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = db.q(f"""SELECT a.*, c.name AS character_name
                    FROM anchors a LEFT JOIN characters c ON c.id = a.character_id{where}
                    ORDER BY a.scope_kind, a.scope_value, c.name, a.tier, a.view, a.id DESC""",
                *params)
    groups = {}
    for r in rows:
        key = (r["scope_kind"], r["scope_value"], r["character_id"], r["character_name"],
               r["tier"], r["view"])
        groups.setdefault(key, []).append(r)
    return [{"scope_kind": k[0], "scope_value": k[1], "character_id": k[2],
             "character_name": k[3], "tier": k[4], "view": k[5],
             "candidates": [{"id": c["id"], "path": c["path"], "chosen": bool(c["chosen"]),
                             "tier": c["tier"], "view": c["view"],
                             "character_id": c["character_id"]} for c in v],
             "unpicked": sum(1 for c in v if not c["chosen"])}
            for k, v in groups.items()]


def _pick_anchor(id):
    row = db.one("SELECT * FROM anchors WHERE id=?", id)
    if not row:
        raise HTTPException(404, "no such anchor candidate")
    db.run("""UPDATE anchors SET chosen=0 WHERE scope_kind=? AND scope_value=? AND tier=?
              AND view=? AND character_id IS ?""",
           row["scope_kind"], row["scope_value"], row["tier"], row["view"], row["character_id"])
    db.run("UPDATE anchors SET chosen=1 WHERE id=?", id)
    peers = db.q("""SELECT id, chosen FROM anchors WHERE scope_kind=? AND scope_value=?
                    AND tier=? AND view=? AND character_id IS ?""",
                 row["scope_kind"], row["scope_value"], row["tier"], row["view"],
                 row["character_id"])
    return {"chosen": id,
            "group": [{"id": p["id"], "chosen": bool(p["chosen"])} for p in peers]}


def _use_anchor_as_ref(id):
    row = db.one("SELECT * FROM anchors WHERE id=?", id)
    if not row:
        raise HTTPException(404, "no such anchor candidate")
    if row["scope_kind"] not in ("album", db.SHARED_KIND):
        raise HTTPException(400, "only an album's anchors can be used as references")
    album, cid = row["scope_value"] or "", row["character_id"]
    try:
        classification.refuse_skip(album, path=row["path"], character_id=cid)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    existing = db.one("""SELECT * FROM assets WHERE kind='anchor_ref' AND path=?
                         ORDER BY id DESC""", row["path"])
    # T10-23: content_tier travels with the file. A sheet rendered under g/pg13
    # keeps that lock when borrowed as a reference.
    stamp = tiers.stamp_content_tier(
        {"scope_value": album, "character_id": cid,
         "anchor_id": row["id"], "tier": row["tier"], "view": row["view"]},
        row["tier"])
    if existing:
        meta = db.jset(existing)
        if tiers.content_tier_of(meta) != tiers.content_tier_of(stamp):
            meta = tiers.stamp_content_tier(
                {**meta, "anchor_id": row["id"], "tier": row["tier"],
                 "view": row["view"]}, row["tier"])
            db.run("UPDATE assets SET meta_json=? WHERE id=?",
                   json.dumps(meta), existing["id"])
            existing = db.one("SELECT * FROM assets WHERE id=?", existing["id"])
        asset = existing
    else:
        aid = db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) "
                     "VALUES (?,?,?,?,?)", None, "anchor_ref", row["path"],
                     json.dumps(stamp), time.time())
        asset = db.one("SELECT * FROM assets WHERE id=?", aid)
    return {"id": asset["id"], "path": asset["path"], "already": bool(existing)}


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
    form = await request.form()
    need_keys = [k for k in form.getlist("need_key") if k]
    if need_keys:
        if not album:
            raise HTTPException(400, "choose an album")
        selected = [t for t in tier if t]
        if not selected:
            raise HTTPException(400, "pick a tier chip in the sticky bar")
        work_tier = selected[0]
        nude_keys = set(form.getlist("need_nude"))
        miss = {g["key"]: g for g in missing_catalog_poses(album, work_tier)}
        actor_names, extra_ids = _form_actors(form, album, character_id)
        uploads = form_files(form, "images")
        extra = [a["path"] for a in await _save_anchor_refs(
            album, character_id, uploads, actors=actor_names)]
        ref_ids = form.getlist("ref_id")
        if not ref_ids:
            ref_ids = [str(r["id"]) for r in identity_base_refs(album, character_id)][:2]
        extra.extend(_actor_identity_paths(album, extra_ids, [work_tier]))
        paths = _collect_anchor_ref_paths(album, character_id, ref_ids,
                                          extra_paths=extra, work_tiers=[work_tier])
        queued = []
        for key in need_keys:
            g = miss.get(key)
            if not g:
                continue
            views = ["front"]
            if key in nude_keys and tiers.allows_nudity(work_tier):
                views.append("front_nude")
            album, st, sv, combos = _validate_anchor_request(album, [work_tier], views)
            payload = _enqueue_anchor_jobs(
                album, st, sv, combos, n, character_id, form, paths,
                actors=actor_names, pose=(g.get("label") or "")[:400])
            queued.extend(payload.get("jobs") or [])
        if not queued:
            raise HTTPException(400, "select at least one missing pose")
        if wants_json(request):
            return JSONResponse({"queued": len(queued), "jobs": queued, "album": album})
        return RedirectResponse(f"/anchors?scope_value={quote(album)}&gap_tier={quote(work_tier)}",
                                status_code=303)
    view = list(view) + _named_pose_views(album, character_id, form.getlist("pose_id"))
    album, selected_tiers, selected_views, combos = _validate_anchor_request(
        album, tier, view)
    if character_id is not None:
        char = get_character_or_404(character_id)
        if char["scope_value"] != album:
            raise HTTPException(400, f"character {char['name']!r} belongs to album "
                                      f"{char['scope_value']!r}, not to {album!r}")
    uploads = form_files(form, "images")
    if len(uploads) > MAX_ANCHOR_UPLOADS:
        raise HTTPException(400, f"that is {len(uploads)} reference images; {MAX_ANCHOR_UPLOADS} "
                                  f"is the most this form accepts")
    actor_names, extra_ids = _form_actors(form, album, character_id)
    extra = [a["path"] for a in await _save_anchor_refs(
        album, character_id, uploads, actors=actor_names)]
    ref_ids = form.getlist("ref_id")
    if not ref_ids:
        ref_ids = [str(r["id"]) for r in anchor_refs(album, character_id)
                   if r.get("role") == "identity"][:2]
    extra.extend(_actor_identity_paths(album, extra_ids, selected_tiers))
    paths = _collect_anchor_ref_paths(album, character_id, ref_ids,
                                      extra_paths=extra,
                                      work_tiers=selected_tiers)
    payload = _enqueue_anchor_jobs(album, selected_tiers, selected_views, combos, n,
                                   character_id, form, paths,
                                   actors=actor_names)
    if wants_json(request):
        return JSONResponse(payload)
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


def screen_prompt_field(value, field, where, tier=None):
    """One guard for prose a form is about to put into an image prompt.

    Shared rather than copied per route. `check_character_fields` used to say the
    cast was screened "exactly as the album profile's own fields would be if they
    were free text from a form" -- and the album profile's fields ARE free text
    from a form, and had no screening at all: no check_text, no check_override,
    no bound, while every sibling path had all three. One guard, both callers, so
    the next field added to either table cannot land unscreened.

    Unset tier is xxx (T10-25): a draft with no lock fails closed.
    """
    if len(value) > MAX_PROMPT_FIELD:
        raise HTTPException(400, f"{field} is {len(value)} characters; keep it under "
                                 f"{MAX_PROMPT_FIELD}")
    try:
        tiers.check_text(value, f"{where} {field}", tier=tier)
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
    return _playlist_hx(request, id)


@app.post("/characters/{cid}/save")
async def save_character(cid: int, request: Request):
    char = get_character_or_404(cid)
    form = await request.form()
    if "name" in form:
        new_name = " ".join((form.get("name") or "").split())
        if not new_name:
            raise HTTPException(400, "a character needs a name")
        if len(new_name) > 60:
            raise HTTPException(400, "character name is too long (max 60)")
        try:
            tiers.check_text(new_name, "character name")
        except ValueError as e:
            raise HTTPException(400, str(e))
        if new_name != char["name"]:
            try:
                db.run("UPDATE characters SET name=? WHERE id=?", new_name, cid)
            except sqlite3.IntegrityError:
                raise HTTPException(
                    400, f"'{char['scope_value']}' already has a character called {new_name!r}")
    if "figure_role_present" in form:
        fig = "lead" if (form.get("figure_role") or "") == "lead" else "extra"
        db.run("UPDATE characters SET figure_role=? WHERE id=?", fig, cid)
    fields = check_character_fields(form)
    for t in VIDEO_MATRIX_TIERS:
        raw = form.get(f"wardrobe_{t}")
        if raw is None:
            continue
        text = screen_prompt_field((raw or "").strip(), "wardrobe", "character")
        _save_look_version(char["scope_value"], "look_wardrobe", text,
                           tier=t, character_id=cid)
        if t == "xxx":
            fields["wardrobe"] = text
    for field, value in fields.items():
        db.run(f"UPDATE characters SET {field}=? WHERE id=?", value, cid)
        if field != "role":
            _save_look_version(char["scope_value"], field, value, character_id=cid)
    p = db.one("SELECT * FROM playlists WHERE name=? AND kind='playlist'",
               char["scope_value"])
    if p:
        return _after_name_save(request, p)
    return _playlist_hx_album(request, char["scope_value"])


@app.post("/characters/{cid}/describe", response_class=HTMLResponse)
def describe_character_field(request: Request, cid: int, field: str = Form(...),
                             tier: str = Form("")):
    """Wand: draft one supporting-character field from album lyrics + cover."""
    char = get_character_or_404(cid)
    p = db.one("SELECT * FROM playlists WHERE name=? AND kind='playlist'",
               char["scope_value"])
    if not p:
        raise HTTPException(400, f"no playlist for album '{char['scope_value']}'")
    box_key = field
    box_tier = (tier or "").strip()
    if field.startswith("wardrobe_") and field != "wardrobe":
        box_tier = field.split("_", 1)[1]
        field = "wardrobe"
    if field not in ("identity", "body", "wardrobe", "nude_wardrobe", "anatomy"):
        raise HTTPException(400, f"cannot describe {field!r}")
    lyrics = _album_lyrics(p["id"])
    existing = char[field] if field in char.keys() and char[field] else ""
    note = f"Supporting character {char['name']}"
    if char["role"]:
        note += f" ({char['role']})"
    current = (note + ". " + existing).strip()
    text = _draft_one_look(p, field, lyrics, tier=box_tier, current=current)
    who = f"c{cid}"
    if field == "wardrobe" and box_tier:
        f = _wardrobe_field(p["name"], box_tier, text, character_id=cid, who=who)["field"]
        f["value"] = text
        f["key"] = box_key if box_key.startswith("wardrobe_") else f"wardrobe_{box_tier}"
        return templates.TemplateResponse(request, "_album_field.html", {
            "playlist": p, "character": char, "f": f})
    label, _default, hint = ALBUM_FIELDS[field]
    return templates.TemplateResponse(request, "_album_field.html", {
        "playlist": p, "character": char,
        "f": {"key": field, "label": label, "value": text, "hint": hint,
              "wand": True, "tier": box_tier, "who": who,
              "history": _look_history(p["name"], field, character_id=cid)}})


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
    return _playlist_hx_album(request, target["scope_value"])


@app.post("/characters/{cid}/delete")
def delete_character(request: Request, cid: int):
    """Remove a character and their anchor ROWS. The image FILES are left on
    disk -- they cost GPU time to make and are recoverable by hand.

    The rows have to go, not just be unchosen: sqlite hands out the next rowid
    as max+1, so deleting the highest-numbered character and adding another
    reuses that id, and anchors still pointing at it would silently become the
    new character's."""
    char = get_character_or_404(cid)
    album = char["scope_value"]
    db.run("DELETE FROM anchors WHERE character_id=?", cid)
    db.run("DELETE FROM characters WHERE id=?", cid)
    return _playlist_hx_album(request, album)


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
    cur = prompts.recalled(album, "positive", tier, character_id)
    if cur:
        for vb in views:
            if vb["prompt"] == vb["composed"]:
                vb["prompt"] = cur["text"]
    return {
        "name": tier,
        "text": (tones or {}).get(tier, tier_tone(tier, album)),
        "tier_default": tiers.tier_text(tier).strip(),
        "overridden": bool(tiers.override_text(album, tier)),
        "views": views,
        "clothed_views": clothed,
        "nude_views": nude,
        "versions": anchor_prompt_versions(album, tier, character_id),
        "current_id": cur["id"] if cur else None,
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


def actor_identity_url(album, character_id=None):
    """Chosen identity front for this body, else an identity photograph."""
    for t in ("xxx", "r", "pg13", "g"):
        row = chosen_anchor("album", album or "", t, "front", character_id)
        if row and row["path"] and os.path.isfile(row["path"]):
            return media_url(row["path"])
    for r in anchor_refs(album, character_id):
        if (r.get("role") or "identity") == "identity" and not r.get("pose_name"):
            if r.get("path") and os.path.isfile(r["path"]):
                return media_url(r["path"])
    return ""


def form_actor_rows(album):
    """Lead + album cast, each with the identity photograph to use as image1."""
    album = (album or "").strip()
    lead = pose_plan.lead_name(album) if album else "Lead"
    rows, seen = [], set()
    rows.append({"id": "lead", "name": lead or "Lead",
                 "thumb": actor_identity_url(album, None)})
    seen.add((lead or "Lead").lower())
    for c in album_cast(album):
        name = (c["name"] or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        rows.append({"id": str(c["id"]), "name": name,
                     "thumb": actor_identity_url(album, c["id"])})
    return rows


def missing_catalog_poses(album, tier):
    """Unbound album-coverage rows at this tier (the generate checklist)."""
    album, tier = (album or "").strip(), (tier or "").strip()
    if not album or not tier:
        return []
    try:
        cov = pose_plan.album_coverage(album, tier)
    except (LookupError, OSError, ValueError, json.JSONDecodeError):
        return []
    return [g for g in (cov.get("needed") or []) if not g.get("sheet_id")]


def identity_base_refs(album, character_id=None):
    """Operator identity photographs, not named pose plates."""
    return [r for r in anchor_refs(album, character_id)
            if (r.get("role") or "identity") == "identity" and not r.get("pose_name")]


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
        keep = [v for v in selected_views if ok or not make_anchor.is_nude_view(v)]
        plan.append({"tier": t, "views": keep,
                     "skipped": [v for v in selected_views if v not in keep]})
    return plan


def anchor_form_ctx(album="", selected_tiers=(), selected_views=(), character_id=None,
                    typed_prompts=None, negative=None, tones=None, latent=None, pose=None,
                    selected_actor_ids=None):
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
        "saved_refs": identity_base_refs(album, character_id),
        "all_refs": anchor_refs(album, character_id),
        "generate_tier": (selected[0] if selected else ""),
        "allow_nude": bool(selected and tiers.allows_nudity(selected[0])),
        "missing_poses": missing_catalog_poses(album, selected[0] if selected else ""),
        "form_actors": form_actor_rows(album),
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
        "lead_name": pose_plan.lead_name(album) if album else "Lead",
        "selected_actor_ids": selected_actor_ids or (
            ["lead"] if character_id is None else [str(character_id)]),
        "pose": pose or "",
        "selected_need_keys": [],
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
                                                       latent=qp.get("latent"), pose=pose,
                                                       selected_actor_ids=_selected_actor_ids(
                                                           qp, album, character_id)))


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
    # Every base-image row pointing at this file goes with it. Borrowed
    # refs (use_as_ref, meta.anchor_id) used to be the only ones dropped;
    # upload-pose / Assign as sheet write an upload row on the SAME path
    # without that key. Leaving it resurrects an empty Base images card
    # the moment this sheet is no longer chosen.
    for a in db.q("SELECT * FROM assets WHERE kind='anchor_ref' AND path=?", row["path"]):
        db.run("DELETE FROM assets WHERE id=?", a["id"])
    db.run("DELETE FROM anchors WHERE id=?", row["id"])


def _anchor_done(request, row):
    """HX from a playlist card stays on the card. Else the anchors page."""
    if wants_hx(request) and row and row["scope_kind"] == "album":
        return _playlist_hx_album(request, row["scope_value"])
    if wants_json(request):
        return JSONResponse({"ok": True})
    kind = row["scope_kind"] if row else "album"
    value = row["scope_value"] if row else ""
    return RedirectResponse(
        f"/anchors?scope_kind={kind}&scope_value={quote(value)}",
        status_code=303)


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
    return _anchor_done(request, row)


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
    bases = [args.get("face_path") or row["path"]]
    asked = args.get("instruction") or args["mode"]
    for r in results:
        # a NEW candidate in the same group, never a replacement: the sheet you
        # were fixing stays until you pick the fix
        qc = score_generated_still(r["path"], bases, asked, progress)
        db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen,
                                        created, character_id, qc_json)
                  VALUES (?,?,?,?,?,0,?,?,?)""",
               row["scope_kind"], row["scope_value"], row["tier"], row["view"],
               r["path"], now, row["character_id"], qc)
    return {"count": len(results), "mode": args["mode"]}


@app.post("/anchors/{id}/fix")
async def start_fix_anchor(request: Request, id: int, mode: str = Form(...),
                            instruction: str = Form(""),
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
    return _anchor_done(request, row)


@app.post("/anchors/{id}/pick")
def pick_anchor(request: Request, id: int):
    # exactly one chosen per (scope_kind, scope_value, tier, view, CHARACTER)
    # group. Without the character in the key, picking a supporting character's
    # anchor would unpick the protagonist's for that tier -- and the next refs
    # job would refuse to run for want of an anchor that was chosen a moment ago.
    # `IS ?`, not `= ?`: character_id is NULL for the protagonist and NULL = NULL
    # is never true in SQL. sqlite's IS is null-safe equality and works on every
    # version; IS NOT DISTINCT FROM needs 3.39 and cerberus runs 3.37.2, so it
    # would have passed here and been a syntax error on the deployed box.
    payload = _pick_anchor(id)
    if wants_json(request):
        return JSONResponse(payload)
    row = db.one("SELECT * FROM anchors WHERE id=?", id)
    return _anchor_done(request, row)


@app.post("/anchors/{id}/clear")
def clear_anchor(request: Request, id: int):
    """Stop using this sheet as the pose keeper. The file stays."""
    row = db.one("SELECT * FROM anchors WHERE id=?", id)
    if not row:
        raise HTTPException(404, "no such anchor candidate")
    db.run("UPDATE anchors SET chosen=0 WHERE id=?", id)
    if wants_json(request):
        return JSONResponse({"cleared": id, "chosen": 0})
    return _anchor_done(request, row)


@app.post("/anchors/keeper")
def set_album_pose_keeper(request: Request, album: str = Form(...),
                          tier: str = Form(...),
                          key: str = Form(...), sheet_id: str = Form("0")):
    """Roster dropdown: this album pose uses this sheet as keeper."""
    valid_tier_or_400(tier)
    album = (album or "").strip()
    if not album:
        raise HTTPException(400, "album required")
    sid = None if sheet_id in (None, "", "0") else int(sheet_id)
    cov = pose_plan.album_coverage(album, tier)
    group = next((g for g in cov["needed"] if g["key"] == key), None)
    if group is None:
        raise HTTPException(404, "no such pose on this album")
    picked = None
    if sid:
        sheet = db.one(
            f"""SELECT * FROM anchors WHERE id=? AND tier=?
                AND {db.visible_anchor_sql()}""",
            sid, tier, album)
        if not sheet:
            raise HTTPException(400, "that sheet is not on this album and tier")
        picked = _pick_anchor(sid)
        pose_plan.stamp_sheet_pose_name(sid, group.get("label"))
    elif group.get("sheet_id"):
        db.run("UPDATE anchors SET chosen=0 WHERE id=?", group["sheet_id"])
    pose_plan.stamp_binds(tier, group.get("binds"), sid)
    if wants_json(request):
        out = {"ok": True, "sheet_id": sid, "key": key,
               "label": group.get("label") or "", "chosen": bool(sid)}
        if picked:
            out["group"] = picked.get("group")
        return JSONResponse(out)
    if wants_hx(request):
        return _playlist_hx_album(request, album)
    return RedirectResponse(f"/anchors?scope_value={quote(album)}", status_code=303)


@app.post("/anchors/{id}/actors")
async def save_anchor_actors(request: Request, id: int):
    """Stamp who is on this plate. Two or more names make it an Actors sheet."""
    row = db.one("SELECT * FROM anchors WHERE id=?", id)
    if not row:
        raise HTTPException(404, "no such anchor candidate")
    form = await request.form()
    names = []
    seen = set()
    for raw in form.getlist("actor_name"):
        n = " ".join(str(raw or "").split())
        key = n.lower()
        if not n or key in seen:
            continue
        seen.add(key)
        names.append(n)
    meta = db.jset(row, "render_json")
    if names:
        meta["actors"] = names
    else:
        meta.pop("actors", None)
    db.run("UPDATE anchors SET render_json=? WHERE id=?", json.dumps(meta), id)
    if wants_json(request):
        return JSONResponse({"ok": True, "id": id, "actors": names,
                             "ensemble": pose_plan.is_ensemble(
                                 db.one("SELECT * FROM anchors WHERE id=?", id),
                                 row["scope_value"], "")})
    return _anchor_done(request, row)


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
        row = db.one("SELECT prompt, json_path FROM storyboards WHERE song_id=? AND tier=?",
                     song["id"], tier)
        # An album arc, when there is one, is the better starting point than the
        # tier's generic tone wording: it is what this SONG does in the story.
        # A prefill, not a cage -- the box stays editable and what is actually
        # sent is stored beside the storyboard, as it always was.
        beat = arc.for_song(album_arc(song["album"] or ""), song["id"]).get("beat", "")
        stored = (row["prompt"] if row else "") or ""
        # A filename pointer is not a brief. Prefer the board already on disk.
        if (not stored.strip() or ".json" in stored.lower()) and row:
            from_board = storyboard_service.direction_from_board_path(row["json_path"])
            if from_board:
                stored = from_board
        direction = stored or beat or default_direction(song, tier)
    dbox = prompts.box(f"song:{song['id']}", "storyboard_direction",
                       direction, tier=tier)
    if dbox["text"]:
        direction = dbox["text"]
    album = song["album"] or ""
    return {"song": song, "tier": tier, "tiers": tiers.all_tiers(),
            "direction": direction,
            "direction_box": dbox,
            "pinned": tiers.PINNED.strip(),
            "tier_text": tier_tone(tier, song["album"] or ""),
            "max_direction": grok.MAX_DIRECTION,
            "models": chat_models if chat_models is not None else [], "best_model": best,
            "album_leads": album_leads_for_form(album, tier),
            "album_playlist": album_playlist(album)}


def storyboard_generation_payload(song, tier):
    """T2-17 prompt + T2-18 limits for a client that edits before generate.

    Defaulted from the tier when nothing has been stored. A stored prompt
    (what was actually sent) wins, which is the same prefill the HTML form
    uses -- one function, both answers. max_characters is grok.MAX_DIRECTION,
    the same number check_direction enforces.
    """
    ctx = storyboard_form_ctx(song, tier)
    return {
        "prompt": ctx["direction"],
        "tier": ctx["tier"],
        "pinned": ctx["pinned"],
        "tier_text": ctx["tier_text"],
        "max_characters": ctx["max_direction"],
        "pinned_added_at_use": True,
        "pinned_editable": False,
        "album_leads": ctx["album_leads"],
    }


def enqueue_storyboard(song_id, tier, model="", scene_seconds=None, direction=""):
    """Queue a storyboard generate. Shared by the HTML form and the JSON API."""
    try:
        direction = storyboard_service.check_direction(direction, tier)
        jid = storyboard_service.enqueue(song_id, tier, model, scene_seconds, direction)
        return jid, direction
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


def check_direction(direction, tier=None):
    """Screen the direction box exactly as a custom tier's wording is screened.

    check_text() refuses minor references except at g/pg13 (T10-18), and
    check_override() refuses text that argues with the pinned clause. The
    length cap is larger than a tier's 500 because this is a brief for one
    song, not a reusable rating.
    """
    try:
        return storyboard_service.check_direction(direction, tier)
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


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
def start_storyboard(request: Request, id: int, tier: str = Form(...),
                      model: str = Form(""),
                      scene_seconds: str = Form(""), direction: str = Form("")):
    secs = scene_seconds.strip() if isinstance(scene_seconds, str) else scene_seconds
    jid, direction = enqueue_storyboard(id, tier, model, secs or None, direction)
    return json_or_redirect(
        request,
        {"job_id": jid, "kind": "storyboard", "tier": tier, "prompt": direction},
        f"/songs/{id}")


@app.get("/api/songs/{id}/storyboard/{tier}")
def api_storyboard_prompt(id: int, tier: str):
    """T2-17 prompt always; T2-26 board+anchors when a readable board exists.

    T6-A2: board numbers (scene_time, song_length, clip_seconds, scene_count,
    mismatch) come from storyboard_service.payload — same function the HTML
    page reads.
    """
    song = get_song_or_404(id)
    tier = valid_tier_or_400(tier)
    gen = storyboard_generation_payload(song, tier)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", song["id"], tier)
    if not row or not row["json_path"] or not os.path.isfile(row["json_path"]):
        return JSONResponse(gen)
    try:
        payload = storyboard_service.payload(song["id"], tier)
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)
    board_leads = payload.get("album_leads")
    payload.update(gen)
    if board_leads is not None:
        payload["album_leads"] = board_leads
    return JSONResponse(payload)


@app.post("/api/songs/{id}/storyboard/{tier}")
async def api_start_storyboard(id: int, tier: str, request: Request):
    """T2-17: the edited prompt is what the generate job is handed."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(400, "JSON object required")
    prompt = body.get("prompt", body.get("direction", ""))
    jid, direction = enqueue_storyboard(
        id, tier,
        model=body.get("model") or "",
        scene_seconds=body.get("scene_seconds"),
        direction=prompt)
    return JSONResponse({"job_id": jid, "tier": tier, "prompt": direction})


# Scene fields the storyboard page lets you edit. image_prompt is what the
# reference renderer actually sends; video_motion_prompt is what the clip
# renderer sends; story is the human line the detail-shot path falls back to
# (build_refs.tighten_for_detail). video_model is a directorial fact on the
# scene (T2-42 / T2-43) and sits beside camera. needs_lip_sync (T2-55) is the
# lip-sync fact beside camera: true → LTX then s2v hop; false/absent → LTX only.
# scene_number keys the allocation and is not editable here.
EDITABLE_SCENE_FIELDS = (
    "name", "cue", "duration_guidance", "story",
    "camera", "video_model", "needs_lip_sync", "motion", "lighting",
    "location", "pose",
    "image_prompt", "video_motion_prompt", "negative_prompt",
)
BOOL_SCENE_FIELDS = ("needs_lip_sync",)
BOARD_LOCK_FIELDS = ("character_reference", "album_world_reference")
SHORT_SCENE_FIELDS = (
    "name", "cue", "duration_guidance", "camera", "video_model",
    "needs_lip_sync", "motion", "lighting", "location", "pose",
)
MAX_SCENE_FIELD = 4000


def _as_scene_bool(raw):
    """Checkbox / JSON bool for BOOL_SCENE_FIELDS (T2-55)."""
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    if isinstance(raw, (int, float)):
        return raw != 0
    s = str(raw).strip().lower()
    if s in ("", "0", "false", "no", "off"):
        return False
    return s in ("1", "true", "yes", "on")

# Fields re-screened on T10-21 unlock. Lyrics may mention a child at r
# (T10-18a); for unlock-to-explicit the work must be empty of minor
# references in every stored field that can feed a prompt or narrative.
_UNLOCK_SCENE_FIELDS = ("image_prompt", "video_motion_prompt", "story",
                        "camera", "motion", "lighting", "location", "name",
                        "cue")


def note_minor_reference(song_id, text, tier):
    """T10-21: accepting a minor reference under g/pg13 locks the work.

    Clearing the wording later does not unlock; only unlock_minor does.
    """
    if not text or not tiers.allows_minor_depiction(tier):
        return
    if tiers.references_minor(text):
        db.set_minor_locked(song_id, True)


def attributed_meta_for_song(song_id, tier, meta=None):
    """Stamp sticky minor-lock attribution when the work is locked (T10-21)."""
    meta = dict(meta or {})
    if db.is_minor_locked(song_id):
        return tiers.stamp_minor_lock_attribution(meta, tier=tier)
    return meta


def work_text_fields(song_id):
    """(where, text) pairs re-screened for T10-21 unlock."""
    song = db.one("SELECT * FROM songs WHERE id=?", song_id)
    if not song:
        return []
    out = []
    for col in ("lyrics", "style_text", "title"):
        val = (song[col] if col in song.keys() else None) or ""
        if str(val).strip():
            out.append((col, str(val)))
    for row in db.q(
            "SELECT tier, json_path FROM storyboards WHERE song_id=?",
            song_id):
        path = row["json_path"]
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path) as f:
                sb = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        tier = row["tier"]
        for key in ("character_reference", "album_world_reference",
                    "audio_lyrics", "direction", "prompt"):
            val = sb.get(key) or ""
            if str(val).strip():
                out.append((f"storyboard {tier} {key}", str(val)))
        for scene in sb.get("scenes") or []:
            num = scene.get("scene_number")
            for field in _UNLOCK_SCENE_FIELDS:
                val = scene.get(field) or ""
                if str(val).strip():
                    out.append(
                        (f"storyboard {tier} scene {num} {field}", str(val)))
    return out


def unlock_minor(song_id):
    """T10-21: explicit unlock only when the re-screen is empty.

    Does not rewrite asset meta — prior renders keep their attribution.
    """
    if not db.is_minor_locked(song_id):
        return {"unlocked": False, "was_locked": False}
    hits = []
    for where, text in work_text_fields(song_id):
        if tiers.references_minor(text):
            hits.append(where)
    if hits:
        raise tiers.ContentRefused(
            "Cannot unlock: minor reference still present in "
            f"{', '.join(hits[:8])}. Remove every reference, then unlock "
            "explicitly.")
    db.set_minor_locked(song_id, False)
    return {"unlocked": True, "was_locked": True}


def foreign_tier_in_storyboard(sb, tier):
    """Other-tier name whose stored wording appears in the board, or None.

    T2-22: a storyboard carrying another tier's clause is refused at save.
    PINNED is shared, so this matches the tone half (tiers.guardrail), not
    compose_guardrail(). Clauses shorter than 24 characters are skipped so
    a one-word custom tier cannot false-positive.
    """
    tiers.ensure_builtins()
    hay = json.dumps(sb, ensure_ascii=False)
    own = (tiers.tier_text(tier) or "").strip()
    for row in db.q("SELECT name, guardrail FROM tiers WHERE name != ?", str(tier)):
        clause = (row["guardrail"] or "").strip()
        if len(clause) < 24:
            continue
        if clause == own or (own and clause in own):
            continue
        if clause in hay:
            return row["name"]
    return None


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


def _figure_name(entry):
    if isinstance(entry, dict):
        return str(entry.get("name") or "").strip()
    return str(entry or "").strip()


def _scene_figure(entry, anchored):
    """Named scene figure with T2-29 role. A bare name is a legacy lead."""
    name = _figure_name(entry)
    if isinstance(entry, dict):
        role = str(entry.get("role") or "").strip().lower()
    else:
        role = "lead"
    return {"name": name, "role": role, "anchored": name in anchored}


def unanchored_leads(rows):
    """Lead names with no chosen anchor. T2-30: extras/background do not warn."""
    return sorted({n["name"] for r in rows for n in r["cast"]
                   if not n["anchored"] and n.get("role") == "lead"})


def refs_plan_blockers(song, tier, rows):
    """What would stop Generate refs for this tier (T2-28 plan-panel).

    Same reasons start_refs refuses. Named unanchored leads are listed
    individually; extras/background never block. The button is marked
    when this is non-empty, never disabled (UIUX §7a.3).
    """
    blockers = []
    if not chosen_anchor("album", song["album"] or "", tier):
        msg = identity_front_blocker(song["album"] or "", tier)
        if msg:
            blockers.append(msg)
    for name in unanchored_leads(rows):
        blockers.append(
            f"{name} has no chosen anchor at this tier — "
            "anchor them, or stop naming them as a lead")
    sid = song["id"] if "id" in song.keys() else None
    if sid:
        try:
            scene_pose_map.require_accepted(sid, tier)
        except (LookupError, ValueError) as e:
            blockers.append(str(e))
    return blockers


def storyboard_scenes(song, sb, tier, anchored=(), scene_seconds=None):
    """Per-scene timing, prompts and the one still slot. Delegates to the service."""
    return storyboard_service.scenes(song, sb, tier, anchored, scene_seconds)


# Fraction of song length. T2-23: |scene_time - song_length| beyond this
# is a miss. coverage.ok still compares intent against rendered clip total.
SCENE_TIME_TOLERANCE = 0.15


def scene_time_report(scene_time, song_length):
    """Total scene time against song length. T2-23.

    mismatch is True when the absolute delta exceeds SCENE_TIME_TOLERANCE
    of the song length. Returning the two numbers and never flagging
    satisfies the presence half only.
    """
    scene_time = float(scene_time or 0.0)
    song_length = float(song_length or 0.0)
    allowed = song_length * SCENE_TIME_TOLERANCE
    return {
        "scene_time": scene_time,
        "song_length": song_length,
        "tolerance": SCENE_TIME_TOLERANCE,
        "mismatch": bool(song_length) and abs(scene_time - song_length) > allowed,
    }


def refuse_if_scene_time_mismatch(song, tier):
    """T2-25: a miss is refused before full-song clips enqueue.

    Scene-scoped Render clip (scene= / clip_idx=) skips this gate the same
    way build_song --only skips T2-13e. Unreadable boards are skipped so a
    missing fixture path still hits the existing duration/refs gates rather
    than a new 500.
    """
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?",
                 song["id"], tier)
    path = row["json_path"] if row else None
    if not row or not path or not os.path.isfile(path):
        return
    try:
        sb = load_storyboard(row)
    except (OSError, json.JSONDecodeError):
        return
    scene_time = sum(build_song.guidance_seconds(s) for s in (sb.get("scenes") or []))
    report = scene_time_report(scene_time, song["duration"])
    if report["mismatch"]:
        raise HTTPException(
            400,
            f"scene time {report['scene_time']}s does not match song length "
            f"{report['song_length']}s (tolerance {report['tolerance']}) -- "
            "fix the storyboard before queuing clips")


def coverage(rows, nclips, duration, clip_secs=None):
    """How the storyboard's PACING INTENT compares with the track."""
    return storyboard_service.coverage(rows, nclips, duration, clip_secs)


def storyboard_page_ctx(song, tier):
    """Shared ctx for the standalone page (T6-A2) and the in-song panel."""
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?",
                 song["id"], tier)
    if not row:
        raise HTTPException(404, "no storyboard for this tier yet")
    try:
        board = storyboard_service.payload(song["id"], tier)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from None
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
    album_leads = album_leads_for_form(album, tier, named_scene_leads(rows))
    anchors = album_chosen_anchors(album, tier)
    identity_fronts = [a for a in anchors if a["view"] == "front"]
    clip_secs = board["clip_seconds"]
    raw = {}
    try:
        raw = json.load(open(row["json_path"])) if row["json_path"] else sb
    except (OSError, json.JSONDecodeError, TypeError):
        raw = sb
    return {
        "song": song, "tier": tier, "row": row, "md": md, "sb": sb,
        "board_json": json.dumps(raw, indent=1, ensure_ascii=False),
        "scene_rows": rows, "anchors": anchors,
        "identity_fronts": identity_fronts, "chunk": clip_secs,
        "unanchored": unanchored_leads(rows),
        "album_leads": album_leads,
        "album_playlist": album_playlist(album),
        "refs_blockers": refs_plan_blockers(song, tier, rows),
        "pose_plan": pose_plan.plan(song, tier),
        "coverage": board["coverage"],
        "fields": EDITABLE_SCENE_FIELDS,
        "short_fields": SHORT_SCENE_FIELDS,
        "scene_time": board["scene_time"],
        "song_length": board["song_length"],
        "clip_seconds": clip_secs,
        "scene_count": board["scene_count"],
        "mismatch": board["mismatch"],
        "versions": storyboard_versions.list_versions(row["json_path"], tier),
        "all_videos": [v for r in rows for v in (r.get("videos") or [])],
        "faces": _face_choices(song, tier),
        "flagged_idxs": sorted(latest_flags(song["id"], tier)),
        "ref_flags": latest_flags(song["id"], tier),
        "nclips": nclips,
        "lock_char_box": prompts.box(
            f"song:{song['id']}", "character_reference",
            sb.get("character_reference") or "", tier=tier),
        "lock_world_box": prompts.box(
            f"song:{song['id']}", "album_world_reference",
            sb.get("album_world_reference") or sb.get("world_reference") or "",
            tier=tier),
    }


@app.get("/songs/{id}/storyboard/{tier}", response_class=HTMLResponse)
def view_storyboard(request: Request, id: int, tier: str):
    song = get_song_or_404(id)
    return templates.TemplateResponse(
        request, "storyboard.html", storyboard_page_ctx(song, tier))


@app.get("/songs/{id}/storyboard/{tier}/panel", response_class=HTMLResponse)
def storyboard_panel(request: Request, id: int, tier: str):
    """Fragment the song page hx-gets so 50 scenes are not in GET /songs/{id}."""
    song = get_song_or_404(id)
    return templates.TemplateResponse(
        request, "_storyboard_panel.html", storyboard_page_ctx(song, tier))


@app.post("/songs/{id}/storyboard/{tier}/save")
async def save_storyboard_board(request: Request, id: int, tier: str):
    """Write the textarea JSON as the live board. Snapshot first if asked."""
    song = get_song_or_404(id)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    if not row:
        raise HTTPException(404, "no storyboard for this tier yet")
    form = await request.form()
    raw = (form.get("board_json") or "").strip()
    try:
        sb = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"storyboard is not JSON: {e}") from None
    try:
        models.refuse_unknown_video_model(sb.get("scenes") if isinstance(sb, dict) else None)
        jp, mp, n = storyboard_versions.save_board(
            sb, os.path.dirname(row["json_path"]), song["slug"], tier)
    except (ValueError, LookupError) as e:
        raise HTTPException(400, str(e)) from None
    db.run("UPDATE storyboards SET json_path=?, md_path=?, scene_count=? WHERE id=?",
           jp, mp, n, row["id"])
    if wants_json(request):
        return JSONResponse({"ok": True, "scene_count": n, "tier": tier})
    return RedirectResponse(f"/songs/{id}#fold-storyboard", status_code=303)


@app.post("/songs/{id}/storyboard/{tier}/lock")
async def save_storyboard_lock(request: Request, id: int, tier: str):
    """Patch board-level identity / world text without a raw JSON edit."""
    song = get_song_or_404(id)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    if not row:
        raise HTTPException(404, "no storyboard for this tier yet")
    form = await request.form()
    sb = load_storyboard(row, normalized=False)
    changed = False
    for field in BOARD_LOCK_FIELDS:
        if field not in form:
            continue
        value = (form.get(field) or "").strip()
        if len(value) > MAX_SCENE_FIELD:
            raise HTTPException(
                400, f"{field} is {len(value)} characters; keep it under {MAX_SCENE_FIELD}")
        try:
            tiers.check_text(value, field, tier=tier)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if field == "character_reference" and not value:
            raise HTTPException(400, grok.EMPTY_CHARACTER_REFERENCE)
        if (sb.get(field) or "") != value:
            sb[field] = value
            changed = True
        try:
            ptype = "character_reference" if field == "character_reference" \
                else "album_world_reference"
            prompts.touch(f"song:{id}", ptype, value, "saved", tier=tier)
        except ValueError:
            pass
    if not str((sb.get("character_reference") or "")).strip():
        raise HTTPException(400, grok.EMPTY_CHARACTER_REFERENCE)
    if changed:
        grok.write_storyboard(sb, os.path.dirname(row["json_path"]), song["slug"], tier)
    if wants_json(request):
        return JSONResponse({"ok": True, "changed": changed})
    return RedirectResponse(f"/songs/{id}#fold-storyboard", status_code=303)


@app.post("/songs/{id}/storyboard/{tier}/versions")
async def snapshot_storyboard(request: Request, id: int, tier: str):
    get_song_or_404(id)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    if not row:
        raise HTTPException(404, "no storyboard for this tier yet")
    form = await request.form()
    try:
        ver = storyboard_versions.snapshot(
            row["json_path"], row["md_path"], tier, form.get("label") or "")
    except LookupError as e:
        raise HTTPException(400, str(e)) from None
    if wants_json(request):
        return JSONResponse({
            "ok": True, "version": ver,
            "versions": storyboard_versions.list_versions(row["json_path"], tier),
        })
    return RedirectResponse(f"/songs/{id}#fold-storyboard", status_code=303)


@app.post("/songs/{id}/storyboard/{tier}/versions/restore")
async def restore_storyboard(request: Request, id: int, tier: str):
    song = get_song_or_404(id)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    if not row:
        raise HTTPException(404, "no storyboard for this tier yet")
    form = await request.form()
    try:
        n = int(form.get("n") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "which version?")
    try:
        jp, mp = storyboard_versions.restore(
            row["json_path"], row["md_path"], tier, n, song["slug"])
    except (LookupError, ValueError) as e:
        raise HTTPException(400, str(e)) from None
    nscenes = 0
    try:
        nscenes = len(json.load(open(jp)).get("scenes") or [])
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    db.run("UPDATE storyboards SET json_path=?, md_path=?, scene_count=? WHERE id=?",
           jp, mp, nscenes, row["id"])
    if wants_json(request):
        return JSONResponse({
            "ok": True, "restored": n, "scene_count": nscenes,
            "versions": storyboard_versions.list_versions(jp, tier),
        })
    return RedirectResponse(f"/songs/{id}#fold-storyboard", status_code=303)


@app.post("/songs/{id}/storyboard/{tier}/versions/delete")
async def delete_storyboard_version(request: Request, id: int, tier: str):
    """Remove one named snapshot. The live board is not touched."""
    get_song_or_404(id)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    if not row:
        raise HTTPException(404, "no storyboard for this tier yet")
    form = await request.form()
    try:
        n = int(form.get("n") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "which version?")
    if n < 1:
        raise HTTPException(400, "which version?")
    left = storyboard_versions.list_versions(row["json_path"], tier)
    if not any(r.get("n") == n for r in left):
        raise HTTPException(404, f"no version {n}")
    left = storyboard_versions.delete(row["json_path"], tier, n)
    if wants_json(request):
        return JSONResponse({"ok": True, "deleted": n, "versions": left})
    return RedirectResponse(f"/songs/{id}#fold-storyboard", status_code=303)


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
        if field in BOOL_SCENE_FIELDS:
            # Unchecked checkbox is omitted from multipart; treat as false.
            value = _as_scene_bool(form.get(field)) if field in form else False
            if bool(scene.get(field)) != value:
                scene[field] = value
                changed = True
            continue
        if field not in form:
            continue
        value = (form.get(field) or "").strip()
        if len(value) > MAX_SCENE_FIELD:
            raise HTTPException(400, f"{field} is {len(value)} characters; keep it under {MAX_SCENE_FIELD}")
        # Same screening the model's own output gets in grok.validate(): this is
        # text that goes straight into an image prompt, and hand-editing is
        # exactly the path that bypasses the generator's checks.
        try:
            tiers.check_text(value, f"scene {num} {field}", tier=tier)
        except ValueError as e:
            raise HTTPException(400, str(e))
        # T10-21: accepting a minor ref under g/pg13 locks; clear does not unlock.
        note_minor_reference(id, value, tier)
        if (scene.get(field) or "") != value:
            scene[field] = value
            changed = True
    # T2-22: refuse after the proposed values are patched so an edit that
    # introduces another tier's clause cannot land. Whole board, not just
    # the field that changed — the criterion is about the storyboard.
    foreign = foreign_tier_in_storyboard(sb, tier)
    if foreign:
        raise HTTPException(
            400, f"storyboard carries {foreign} wording; this board is {tier}")
    # T2-31 / T2-32: identity lives in the text. An empty lock renders a
    # stranger; a message that points at the reference image is the wrong lesson.
    if not str((sb.get("character_reference") or "")).strip():
        raise HTTPException(400, grok.EMPTY_CHARACTER_REFERENCE)
    try:
        grok.require_figure_roles(sb)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # T2-44: a scene naming a model the catalogue cannot render is refused
    # here, naming the scene and the value — not later, not defaulted.
    try:
        models.refuse_unknown_video_model(sb.get("scenes"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if changed:
        # stamp the edit so frames rendered before it can be shown as stale.
        # An unknown key in a scene is ignored by every builder (they read named
        # fields), so this costs nothing downstream.
        scene["edited"] = time.time()
        outdir = os.path.dirname(row["json_path"])
        grok.write_storyboard(sb, outdir, song["slug"], tier)
    nxt = (form.get("next") or "").strip()
    if nxt.startswith(f"/songs/{id}"):
        return RedirectResponse(f"{nxt}#scene-{num}", status_code=303)
    anchored = {c["name"] for c, _a in cast_anchors(song["album"] or "", tier)}
    rows, _ = storyboard_scenes(song, load_storyboard(row), tier, anchored,
                                scene_seconds=row["scene_seconds"])
    r = next(x for x in rows if x["num"] == num)
    if wants_json(request):
        return JSONResponse({"ok": True, "num": num, "changed": changed})
    return templates.TemplateResponse(request, "_scene_row.html", {
        "song": song, "tier": tier, "r": r, "fields": EDITABLE_SCENE_FIELDS,
        "short_fields": SHORT_SCENE_FIELDS,
        "scene_open": True,
        "chunk": build_song.clip_seconds(row["scene_seconds"]),
        "pose_plan": pose_plan.plan(song, tier),
        "ref_flags": latest_flags(song["id"], tier)})


@app.post("/songs/{id}/storyboard/{tier}/scene/{num}/draft")
async def draft_scene_prompt(request: Request, id: int, tier: str, num: int):
    body = await _api_body(request)
    field = str(body.get("field") or "").strip()
    try:
        return JSONResponse(storyboard_service.draft_scene_field(id, tier, num, field))
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/songs/{id}/storyboard/{tier}/scene/{num}/field-version/apply")
async def apply_scene_field_version(request: Request, id: int, tier: str, num: int):
    body = await _api_body(request)
    try:
        return JSONResponse(storyboard_service.apply_field_version(
            id, tier, num,
            str(body.get("field") or "").strip(),
            body.get("n")))
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/songs/{id}/storyboard/{tier}/scene/{num}/field-version")
async def save_scene_field_version(request: Request, id: int, tier: str, num: int):
    body = await _api_body(request)
    try:
        return JSONResponse(storyboard_service.save_field_version(
            id, tier, num,
            str(body.get("field") or "").strip(),
            str(body.get("text") or ""),
            str(body.get("label") or "")))
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/songs/{id}/clips/{clip_idx}/delete")
async def delete_landed_clip(request: Request, id: int, clip_idx: int):
    """Operator delete of one landed take. Stills stay."""
    get_song_or_404(id)
    body = await _api_body(request)
    tier = str(body.get("tier") or request.query_params.get("tier") or "")
    try:
        out = storyboard_service.delete_clip(id, valid_tier_or_400(tier), clip_idx)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    return json_or_redirect(
        request, out, f"/songs/{id}/storyboard/{tier}")


@app.post("/songs/{id}/storyboard/{tier}/scene/{num}/clip-job/{jid}/dismiss")
def dismiss_scene_clip_job(id: int, tier: str, num: int, jid: int):
    try:
        return JSONResponse(storyboard_service.dismiss_clip_job(id, tier, num, jid))
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/songs/{id}/storyboard/{tier}/scene/{num}", response_class=HTMLResponse)
def storyboard_scene_row(request: Request, id: int, tier: str, num: int):
    """One open scene row — swap after a reroll so placeholders become stills."""
    song = get_song_or_404(id)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    if not row:
        raise HTTPException(404, "no storyboard for this tier yet")
    sb = load_storyboard(row, normalized=False)
    anchored = {c["name"] for c, _a in cast_anchors(song["album"] or "", tier)}
    rows, _ = storyboard_scenes(song, sb, tier, anchored,
                                scene_seconds=row["scene_seconds"])
    r = next((x for x in rows if x["num"] == num), None)
    if r is None:
        raise HTTPException(404, f"no scene {num} in this storyboard")
    return templates.TemplateResponse(request, "_scene_row.html", {
        "song": song, "tier": tier, "r": r, "fields": EDITABLE_SCENE_FIELDS,
        "short_fields": SHORT_SCENE_FIELDS,
        "scene_open": True,
        "chunk": build_song.clip_seconds(row["scene_seconds"]),
        "pose_plan": pose_plan.plan(song, tier),
        "ref_flags": latest_flags(song["id"], tier)})


def _ref_candidate_json(row):
    path = row["path"]
    return {
        "id": row["id"],
        "path": path,
        "url": media_url(path),
        "seed": row["seed"],
        "approved": bool(row["approved"]),
    }


def _scene_refs_json(r):
    """T2-27: this scene's stills. Latest candidate is path/url on the clip."""
    out = []
    for ref in r.get("refs") or []:
        cands = [_ref_candidate_json(c) for c in (ref.get("candidates") or [])]
        latest = cands[-1] if cands else None
        out.append({
            "idx": ref["idx"],
            "approved": bool(ref.get("approved")),
            "stale": bool(ref.get("stale")),
            "path": None if latest is None else latest["path"],
            "url": None if latest is None else latest["url"],
            "candidates": cands,
        })
    return out


def _scene_json(r):
    scene = r.get("scene") or {}
    return {
        "num": r["num"],
        "scene_number": r["num"],
        "name": r["name"],
        "start": r["start"],
        "end": r["end"],
        "length": r["length"],
        "guidance": r["guidance"],
        "image_prompt": scene.get("image_prompt") or "",
        "video_motion_prompt": scene.get("video_motion_prompt") or "",
        "story": scene.get("story") or "",
        "camera": scene.get("camera") or "",
        "video_model": scene.get("video_model") or "",
        "needs_lip_sync": bool(scene.get("needs_lip_sync")),
        "cast": r["cast"],
        "clips": r["clips"],
        "refs": _scene_refs_json(r),
    }


def _storyboard_payload(song, tier):
    """Board JSON via storyboard_service.payload (T6-A2 / T6-A3)."""
    try:
        return storyboard_service.payload(song["id"], tier)
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


def _enqueue_storyboard(song_id, tier, model="", scene_seconds=None, direction=""):
    try:
        return storyboard_service.enqueue(song_id, tier, model, scene_seconds, direction)
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


def _apply_scene_fields(song, tier, num, fields):
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", song["id"], tier)
    if not row:
        raise HTTPException(404, "no storyboard for this tier yet")
    sb = load_storyboard(row, normalized=False)
    scene = next((s for s in sb.get("scenes", []) if s.get("scene_number") == num), None)
    if scene is None:
        raise HTTPException(404, f"no scene {num} in this storyboard")
    changed = False
    for field in EDITABLE_SCENE_FIELDS:
        if field not in fields:
            continue
        if field in BOOL_SCENE_FIELDS:
            value = _as_scene_bool(fields.get(field))
            if bool(scene.get(field)) != value:
                scene[field] = value
                changed = True
            continue
        value = (fields.get(field) or "").strip()
        if len(value) > MAX_SCENE_FIELD:
            raise HTTPException(400, f"{field} is {len(value)} characters; keep it under {MAX_SCENE_FIELD}")
        try:
            tiers.check_text(value, f"scene {num} {field}", tier=tier)
        except ValueError as e:
            raise HTTPException(400, str(e))
        note_minor_reference(song["id"], value, tier)
        if (scene.get(field) or "") != value:
            scene[field] = value
            changed = True
    if not str((sb.get("character_reference") or "")).strip():
        raise HTTPException(400, grok.EMPTY_CHARACTER_REFERENCE)
    try:
        grok.require_figure_roles(sb)
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        models.refuse_unknown_video_model(sb.get("scenes"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if changed:
        scene["edited"] = time.time()
        outdir = os.path.dirname(row["json_path"])
        grok.write_storyboard(sb, outdir, song["slug"], tier)
    return scene


@app.post("/api/songs/{id}/storyboard/{tier}/scene/{num}")
async def api_storyboard_edit_scene(id: int, tier: str, num: int, request: Request):
    song = get_song_or_404(id)
    valid_tier_or_400(tier)
    body = await _api_body(request)
    scene = _apply_scene_fields(song, tier, num, body)
    payload = _storyboard_payload(song, tier)
    payload["scene"] = {
        "num": num,
        "image_prompt": scene.get("image_prompt") or "",
        "video_motion_prompt": scene.get("video_motion_prompt") or "",
        "story": scene.get("story") or "",
        "camera": scene.get("camera") or "",
        "video_model": scene.get("video_model") or "",
        "needs_lip_sync": bool(scene.get("needs_lip_sync")),
    }
    return JSONResponse(payload)


@app.get("/api/songs/{id}/storyboard/{tier}/meter")
def api_storyboard_meter(id: int, tier: str):
    try:
        return JSONResponse(storyboard_service.meter(id, tier))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.get("/api/songs/{id}/storyboard/{tier}/cast")
def api_storyboard_cast(id: int, tier: str):
    payload = _storyboard_payload(get_song_or_404(id), valid_tier_or_400(tier))
    return JSONResponse({"unanchored": payload["unanchored"],
                         "album_leads": payload.get("album_leads") or [],
                         "scenes": [{"num": s["num"], "cast": s["cast"]}
                                    for s in payload["scenes"]]})


@app.get("/api/albums/{album}/pose-coverage/{tier}")
def api_album_pose_coverage(album: str, tier: str):
    """Album pose roster: have / missing across every song board at this tier."""
    try:
        return JSONResponse(pose_plan.album_coverage(album, valid_tier_or_400(tier)))
    except (LookupError, OSError, json.JSONDecodeError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/albums/{album}/sheet-prompt")
def api_sheet_prompt(album: str, pose: str = "", tier: str = "",
                     character_id: Optional[int] = None):
    """Grey-studio pose sheet for Mage. Not the scene still."""
    t = valid_tier_or_400(tier) if (tier or "").strip() else ""
    text = pose_plan.sheet_prompt(album, pose, character_id, t)
    if not text:
        raise HTTPException(400, "name the pose")
    return JSONResponse({"prompt": text, "pose": pose, "tier": t})


@app.get("/api/albums/{album}/classification/versions")
def api_classification_versions(album: str, character_id: Optional[int] = None):
    """T4-21: version list for this album+character. Newest first."""
    try:
        return JSONResponse(classification.versions(album, character_id))
    except (LookupError, ValueError) as e:
        _svc_http(e)


@app.get("/api/albums/{album}/classification")
def api_classification(album: str, character_id: Optional[int] = None,
                       view: Optional[str] = None, pose: Optional[str] = None,
                       wardrobe: Optional[str] = None, usable: Optional[str] = None):
    """T4-21: latest DB library, optionally filtered. Never a sidecar."""
    try:
        return JSONResponse(classification.query(
            album, character_id=character_id, view=view, pose=pose,
            wardrobe=wardrobe, usable=usable))
    except (LookupError, ValueError) as e:
        _svc_http(e)


@app.post("/api/albums/{album}/classification/import")
async def api_classification_import(request: Request, album: str,
                                    character_id: Optional[int] = None):
    """T4-22: seed one version from a sidecar path. Sidecar is not the store."""
    body = await _api_body(request)
    path = body.get("path") or ""
    try:
        return JSONResponse(classification.import_sidecar(
            album, path, character_id=character_id))
    except (LookupError, ValueError) as e:
        _svc_http(e)


@app.get("/api/albums/{album}/sheets")
def api_album_sheets(album: str, family: str = ""):
    """Chosen sheets for the hole picker. family=clothed|nude filters."""
    want = (family or "").strip().lower()
    rows = []
    for row in db.q(
            """SELECT * FROM anchors WHERE scope_value=? AND chosen=1
               ORDER BY id DESC""", album):
        path = row["path"] or ""
        if not path or not os.path.isfile(path):
            continue
        fam = view_family(row["view"])
        if want in ("clothed", "nude") and fam != want:
            continue
        meta = db.jset(row, "render_json")
        actors = pose_plan.actor_names(row, album)
        rows.append({
            "id": row["id"],
            "path": path,
            "url": media_url(path),
            "view": row["view"],
            "family": fam,
            "pose": (meta.get("pose_name") or row["view"] or "").strip(),
            "label": view_position_label(row["view"]),
            "actors": actors,
        })
    return JSONResponse({"album": album, "family": want or None,
                         "n": len(rows), "sheets": rows})


@app.post("/api/keepers/apply")
async def api_apply_keeper(request: Request):
    """Point many albums and tiers at one file. Does not copy bytes."""
    import pose_generate
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required")
    if not isinstance(body, dict):
        raise HTTPException(400, "JSON object required")
    path = pose_generate.resolve_image_path(body.get("path") or "")
    if not path:
        raise HTTPException(400, "that sheet has no file")
    pose = classification.pose_label(body.get("pose") or "")
    wardrobe = "nude" if (body.get("wardrobe") or "") == "nude" else "clothed"
    view = (body.get("view") or "front").strip() or "front"
    if wardrobe == "nude" and not make_anchor.is_nude_view(view):
        view = "front_nude" if view == "front" else view + "_nude"
    if wardrobe != "nude":
        view = view.replace("_nude", "") or "front"
    albums = [a.strip() for a in (body.get("albums") or []) if str(a).strip()]
    work_tiers = [t.strip() for t in (body.get("tiers") or []) if str(t).strip()]
    if not albums:
        raise HTTPException(400, "tick at least one album")
    if not work_tiers:
        raise HTTPException(400, "tick at least one tier")
    names = {p["name"] for p in db.q("SELECT name FROM playlists WHERE kind='playlist'")}
    for album in albums:
        if album not in names:
            raise HTTPException(400, f"no album called {album!r}")
        classification.add_keeper(album, {
            "id": f"apply-{os.path.basename(path)}-{wardrobe}",
            "path": path,
            "kind": "operator",
            "view": view,
            "pose": pose,
            "wardrobe": wardrobe,
            "usable": "pose",
        })
    picked = []
    for album in albums:
        for t in work_tiers:
            valid_tier_or_400(t)
            if wardrobe == "nude" and not tiers.allows_nudity(t):
                continue
            row = db.one(
                """SELECT * FROM anchors WHERE scope_kind='album' AND scope_value=?
                   AND tier=? AND view=? AND path=? AND character_id IS NULL""",
                album, t, view, path)
            if not row:
                aid = db.run(
                    """INSERT INTO anchors
                       (scope_kind, scope_value, tier, view, path, chosen, created)
                       VALUES ('album',?,?,?,?,0,?)""",
                    album, t, view, path, time.time())
                row = db.one("SELECT * FROM anchors WHERE id=?", aid)
            picked.append(_pick_anchor(row["id"]))
            pose_plan.stamp_sheet_pose_name(row["id"], pose)
    return JSONResponse({
        "ok": True, "path": path, "pose": pose, "view": view,
        "albums": albums, "tiers": work_tiers, "n": len(picked),
    })


@app.post("/api/albums/{album}/classification/from-sheets")
def api_classification_from_sheets(album: str,
                                   character_id: Optional[int] = None):
    """Tag chosen gallery sheets as keepers. No sidecar path, no GPU."""
    try:
        return JSONResponse(classification.tag_from_anchors(
            album, character_id=character_id))
    except (LookupError, ValueError) as e:
        _svc_http(e)


@app.post("/api/albums/{album}/classification/keeper")
async def api_classification_keeper(request: Request, album: str,
                                    character_id: Optional[int] = None):
    """Tag one sheet as covering a hole."""
    body = await _api_body(request)
    try:
        return JSONResponse(classification.add_keeper(
            album, body, character_id=character_id))
    except (LookupError, ValueError) as e:
        _svc_http(e)


@app.post("/api/albums/{album}/classification")
async def api_classification_save(request: Request, album: str,
                                  character_id: Optional[int] = None):
    """T4-21: persist a new classification_json version."""
    body = await _api_body(request)
    document = body.get("document") if isinstance(body.get("document"), dict) else body
    try:
        return JSONResponse(classification.save(
            album, document, character_id=character_id))
    except (LookupError, ValueError) as e:
        _svc_http(e)


@app.post("/api/songs/{id}/storyboard/{tier}/analyze-poses")
def api_analyze_poses(id: int, tier: str):
    """T2-50: write coverage from the board. Does not bind or enqueue refs."""
    try:
        return JSONResponse(storyboard_service.analyze_poses(
            get_song_or_404(id)["id"], valid_tier_or_400(tier)))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.get("/api/songs/{id}/storyboard/{tier}/pose-coverage")
def api_song_pose_coverage(id: int, tier: str):
    """T2-50: stored (pose, view, wardrobe, exposure) per scene."""
    try:
        return JSONResponse(storyboard_service.pose_coverage_list(
            get_song_or_404(id)["id"], valid_tier_or_400(tier)))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.get("/api/songs/{id}/pose-gap")
def api_pose_gap(id: int, character_id: Optional[int] = None):
    """T4-23: ceiling-board needs vs classification keepers. Holes only."""
    try:
        return JSONResponse(storyboard_service.pose_gap(
            get_song_or_404(id)["id"], character_id=character_id))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.post("/api/songs/{id}/pose-generate")
async def api_pose_generate(request: Request, id: int,
                            character_id: Optional[int] = None):
    """T4-24: ceiling-tier pose generate from pose-gap holes."""
    body = await _api_body(request)
    run_tiers = _as_str_list(
        body.get("tier") if "tier" in body else body.get("tiers"))
    cid = character_id if character_id is not None else _optional_int(
        body.get("character_id"))
    try:
        pose = (body.get("pose") or "").strip()
        if pose:
            import pose_generate
            return JSONResponse(pose_generate.generate_one(
                get_song_or_404(id)["id"], pose,
                body.get("view") or "front",
                body.get("wardrobe") or "clothed",
                run_tiers, character_id=cid,
                n=int(body.get("n") or 4)))
        return JSONResponse(storyboard_service.generate_poses(
            get_song_or_404(id)["id"], run_tiers, character_id=cid))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.post("/api/songs/{id}/storyboard/{tier}/pose-map")
def api_pose_map_draft(id: int, tier: str,
                       character_id: Optional[int] = None):
    """T2-51: draft keeper→scene. Classify never writes this."""
    try:
        return JSONResponse(scene_pose_map.draft(
            get_song_or_404(id)["id"], valid_tier_or_400(tier),
            character_id=character_id))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.get("/api/songs/{id}/storyboard/{tier}/pose-map")
def api_pose_map_list(id: int, tier: str):
    """T2-51 / T2-52: current draft/accepted/rejected bindings."""
    try:
        return JSONResponse(scene_pose_map.listed(
            get_song_or_404(id)["id"], valid_tier_or_400(tier)))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.post("/api/songs/{id}/storyboard/{tier}/scene/{num}/pose-map/accept")
def api_pose_map_accept(id: int, tier: str, num: int):
    """T2-52: persist status=accepted for this scene."""
    try:
        return JSONResponse(scene_pose_map.accept(
            get_song_or_404(id)["id"], valid_tier_or_400(tier), num))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.post("/api/songs/{id}/storyboard/{tier}/scene/{num}/pose-map/reject")
def api_pose_map_reject(id: int, tier: str, num: int):
    """T2-52: leave the previous accepted keeper (or none)."""
    try:
        return JSONResponse(scene_pose_map.reject(
            get_song_or_404(id)["id"], valid_tier_or_400(tier), num))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.get("/api/songs/{id}/pose-plan/{tier}")
def api_pose_plan(id: int, tier: str):
    """Scenes this song needs vs chosen pose sheets. Does not write."""
    try:
        return JSONResponse(pose_plan.plan(get_song_or_404(id), valid_tier_or_400(tier)))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.post("/songs/{id}/storyboard/{tier}/scene/{num}/pose-sheet")
def bind_scene_pose_sheet(request: Request, id: int, tier: str, num: int,
                          sheet_id: str = Form("0")):
    """Operator override: this scene uses this chosen sheet as the pose plate."""
    song = get_song_or_404(id)
    valid_tier_or_400(tier)
    try:
        pose_plan.bind_scene(id, tier, num, sheet_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    plan = pose_plan.plan(song, tier)
    row = next((s for s in plan["scenes"] if s["num"] == num), None) or {}
    path = row.get("path")
    return json_or_redirect(request, {
        "ok": True,
        "num": num,
        "source": row.get("source") or "none",
        "sheet_id": row.get("sheet_id"),
        "path": path,
        "url": media_url(path) if path else None,
        "label": row.get("label") or "",
        "pose": row.get("pose") or "",
    }, f"/songs/{id}/storyboard/{tier}#scene-{num}")


@app.post("/songs/{id}/refs")
def start_refs(request: Request, id: int, tier: List[str] = Form([]),
               limit: int = Form(0)):
    # Form([]) not Form(...): an unticked checkbox group is simply absent from
    # the POST, and a required field turns that into FastAPI's raw 422 validation
    # blob. Defaulting to empty lets the handler answer "select at least one
    # tier" instead.
    song = get_song_or_404(id)
    selected = sorted(set(tier))
    jids = []
    if not selected:
        raise HTTPException(400, "select at least one tier")
    # resolve every tier's anchor up front -- one bad tier must refuse the
    # whole request, not enqueue the good ones and 400 partway through
    anchors = {}
    for t in selected:
        valid_tier_or_400(t)
        sb_row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, t)
        if not sb_row:
            raise HTTPException(400, f"generate a storyboard for tier '{t}' first")
        anchor = chosen_anchor("album", song["album"] or "", t)
        if not anchor:
            raise HTTPException(400, identity_front_blocker(song["album"] or "", t))
        # T2-28: named leads need chosen sheets too. Banner/cast (T2-30) is not
        # enough — refuse before a refs job is written. Extras/background stay out.
        try:
            sb = load_storyboard(sb_row)
        except (OSError, json.JSONDecodeError) as e:
            raise HTTPException(500, f"storyboard file is unreadable: {e}") from None
        cast = cast_anchors(song["album"] or "", t)
        rows, _ = storyboard_scenes(
            song, sb, t, {c["name"] for c, _a in cast},
            scene_seconds=sb_row["scene_seconds"])
        missing = unanchored_leads(rows)
        if missing:
            raise HTTPException(
                400,
                f"named lead(s) have no chosen anchor for tier '{t}': "
                f"{', '.join(missing)} -- generate and pick sheets on /anchors first")
        anchors[t] = anchor
    limit = max(0, limit)
    for t in selected:
        # T2-52: empty / draft / rejected map is not a bind. Draft+Accept
        # is required before refs; no pose_plan.freeze_auto_binds fallback.
        try:
            scene_pose_map.require_accepted(id, t)
            scene_anchors = scene_pose_map.accepted_bases(song, t)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        job = {"song_id": id, "tier": t, "limit": limit or None,
               "anchor_path": anchors[t]["path"],
               "pose_bases": {}}
        if scene_anchors:
            job["anchors"] = scene_anchors
        jid = jobs.enqueue("refs", job, song_id=id)
        jids.append(jid)
    return json_or_redirect(
        request,
        {"job_id": jids[0] if jids else None, "job_ids": jids,
         "kind": "refs", "tiers": selected},
        f"/songs/{id}")


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


_REF_ORIGINS = frozenset({"gen", "reroll", "refine", "face", "inpaint", "outpaint"})


def _face_choices(song, tier):
    faces = []
    if chosen_anchor("album", song["album"] or "", tier):
        faces.append(("protagonist", "protagonist"))
    faces += [(str(c["id"]), c["name"]) for c, _a in cast_anchors(song["album"] or "", tier)]
    return faces


def _scene_head_idxs(song, tier, video_model=None):
    """scene_number → first clip_idx in the video chain."""
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", song["id"], tier)
    if not row:
        return {}
    try:
        sb = load_storyboard(row)
        return build_song.scene_heads(
            sb.get("scenes") or [], video_model or models.default_cli("video"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError):
        return {}


def _clip_scene_number(song, tier, clip_idx):
    """scene_number for a chain-head clip_idx. None if it is not a head."""
    for sn, head in _scene_head_idxs(song, tier).items():
        if head == clip_idx:
            return sn
    return None


def _approved_scene_ref_paths(song, tier, video_model=None):
    """Approved stills keyed as video-chain heads for stage_refs / gen_clips."""
    storyboard_service.stamp_ref_scenes(song, tier)
    heads = _scene_head_idxs(song, tier, video_model)
    by_sn = {}
    for r in db.q(
            """SELECT scene_number, path FROM refs
               WHERE song_id=? AND tier=? AND approved=1 AND scene_number IS NOT NULL
               ORDER BY id""",
            song["id"], tier):
        by_sn[r["scene_number"]] = r["path"]
    return [{"clip_idx": heads[sn], "path": path}
            for sn, path in by_sn.items() if sn in heads]


def approve_context(song, tier):
    """Shared by the grid and by the single-tile htmx swap, so a tile rendered
    on its own carries the same flags, cast and seeds as one rendered in place."""
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?",
                 song["id"], tier)
    sb = {}
    if row:
        try:
            sb = load_storyboard(row)
        except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError):
            sb = {}
    scene_rows, nclips = storyboard_service.scenes(
        song, sb, tier, scene_seconds=scene_seconds_for(song["id"], tier))
    flags = latest_flags(song["id"], tier)
    clips = []
    groups = []
    for r in scene_rows:
        head = r["clips"][0] if r["clips"] else None
        cands = r["refs"][0]["candidates"] if r["refs"] else []
        clip = {
            "idx": head,
            "candidates": cands,
            "approved": any(c["approved"] for c in cands),
            "flag": flags.get(head) if head is not None else None,
            "scene_name": r["name"],
            "scene_num": r["num"],
            "pose": (r["scene"].get("pose") or "").strip(),
            "secs": r["length"],
            "n_parts": r.get("n_parts", 1),
        }
        clips.append(clip)
        groups.append({
            "num": r["num"], "name": r["name"], "pose": clip["pose"],
            "prompt": r["scene"].get("image_prompt") or "",
            "clips": [clip],
            "n_parts": clip["n_parts"],
            "secs": clip["secs"],
            "n_ok": 1 if clip["approved"] else 0,
            "open": not clip["approved"],
        })
    if not groups:
        by_idx = {}
        for r in db.q(
                "SELECT * FROM refs WHERE song_id=? AND tier=? ORDER BY clip_idx, id",
                song["id"], tier):
            by_idx.setdefault(r["clip_idx"], []).append(r)
        for idx, cands in sorted(by_idx.items()):
            clip = {
                "idx": idx, "candidates": cands,
                "approved": any(c["approved"] for c in cands),
                "flag": flags.get(idx),
                "scene_name": "", "scene_num": cands[0]["scene_number"],
                "pose": "", "secs": 0, "n_parts": 1,
            }
            clips.append(clip)
            groups.append({
                "num": clip["scene_num"], "name": "", "pose": "",
                "prompt": "", "clips": [clip], "n_parts": 1, "secs": 0,
                "n_ok": 1 if clip["approved"] else 0,
                "open": not clip["approved"],
            })
    faces = []
    if chosen_anchor("album", song["album"] or "", tier):
        faces.append(("protagonist", "protagonist"))
    faces += [(str(c["id"]), c["name"]) for c, _a in cast_anchors(song["album"] or "", tier)]
    quantum = build_song.clip_seconds(scene_seconds_for(song["id"], tier))
    plan_secs = sum((g["secs"] or 0) for g in groups)
    flagged = []
    for i in flags:
        if any(c["idx"] == i for c in clips):
            flagged.append(i)
    return {"song": song, "tier": tier, "clips": clips, "nclips": nclips,
            "groups": groups, "faces": faces, "flagged_idxs": flagged,
            "clip_secs": quantum, "song_secs": float(song["duration"] or 0),
            "plan_secs": plan_secs}


@app.get("/songs/{id}/approve/{tier}", response_class=HTMLResponse)
def approve_grid(request: Request, id: int, tier: str):
    get_song_or_404(id)
    valid_tier_or_400(tier)
    return RedirectResponse(f"/songs/{id}#fold-storyboard", status_code=303)


@app.post("/songs/{id}/approve/{tier}/all")
def approve_all(request: Request, id: int, tier: str, replace: bool = Form(False)):
    """Approve one candidate for every clip that has none.

    At fifty frames, clicking Approve fifty times is the slow path and the
    common case is "these are fine except three". This approves the NEWEST
    candidate per clip -- newest because a re-roll or a repair is the frame you
    asked for most recently -- and by default leaves clips you have already
    decided alone, so it never silently overrides a deliberate pick.
    """
    song = get_song_or_404(id)
    valid_tier_or_400(tier)
    storyboard_service.stamp_ref_scenes(song, tier)
    n = 0
    heads = _scene_head_idxs(song, tier)
    if heads:
        decided = {r["scene_number"] for r in
                   db.q("""SELECT DISTINCT scene_number FROM refs
                           WHERE song_id=? AND tier=? AND approved=1
                             AND scene_number IS NOT NULL""",
                        id, tier)}
        for sn in heads:
            if sn in decided and not replace:
                continue
            newest = db.one("""SELECT id FROM refs
                               WHERE song_id=? AND tier=? AND scene_number=?
                               ORDER BY id DESC LIMIT 1""", id, tier, sn)
            if not newest:
                continue
            db.run("UPDATE refs SET approved=0 WHERE song_id=? AND tier=? AND scene_number=?",
                   id, tier, sn)
            db.run("UPDATE refs SET approved=1 WHERE id=?", newest["id"])
            n += 1
    else:
        decided = {r["clip_idx"] for r in
                   db.q("""SELECT DISTINCT clip_idx FROM refs
                           WHERE song_id=? AND tier=? AND approved=1""",
                        id, tier)}
        idxs = [r["clip_idx"] for r in
                db.q("SELECT DISTINCT clip_idx FROM refs WHERE song_id=? AND tier=?",
                     id, tier)]
        for i in idxs:
            if i in decided and not replace:
                continue
            newest = db.one("""SELECT id FROM refs WHERE song_id=? AND tier=? AND clip_idx=?
                               ORDER BY id DESC LIMIT 1""", id, tier, i)
            if not newest:
                continue
            db.run("UPDATE refs SET approved=0 WHERE song_id=? AND tier=? AND clip_idx=?",
                   id, tier, i)
            db.run("UPDATE refs SET approved=1 WHERE id=?", newest["id"])
            n += 1
    return json_or_redirect(
        request, {"ok": True, "n": n, "replace": bool(replace)},
        f"/songs/{id}#fold-storyboard")


@app.post("/songs/{id}/refs/{clip_idx}/approve", response_class=HTMLResponse)
def approve_ref(request: Request, id: int, clip_idx: int, tier: str = Form(...), ref_id: int = Form(...)):
    song = get_song_or_404(id)
    ref = db.one("SELECT * FROM refs WHERE id=? AND song_id=? AND tier=?",
                  ref_id, id, tier)
    if not ref:
        raise HTTPException(404, "no such ref candidate")
    new_val = 0 if ref["approved"] else 1
    if new_val:
        if ref["scene_number"] is not None:
            db.run("UPDATE refs SET approved=0 WHERE song_id=? AND tier=? AND scene_number=?",
                   id, tier, ref["scene_number"])
        else:
            db.run("UPDATE refs SET approved=0 WHERE song_id=? AND tier=? AND clip_idx=?",
                   id, tier, ref["clip_idx"])
    db.run("UPDATE refs SET approved=? WHERE id=?", new_val, ref_id)
    if wants_json(request):
        return JSONResponse({"ok": True, "approved": bool(new_val), "ref_id": ref_id,
                             "clip_idx": ref["clip_idx"], "scene_number": ref["scene_number"]})
    ctx = approve_context(song, tier)
    clip = None
    if ref["scene_number"] is not None:
        clip = next((c for c in ctx["clips"] if c.get("scene_num") == ref["scene_number"]), None)
    if clip is None:
        want = clip_idx if clip_idx >= 0 else ref["clip_idx"]
        clip = next((c for c in ctx["clips"] if c["idx"] == want), None)
    if clip is None:
        return HTMLResponse("")
    return templates.TemplateResponse(request, "_clip_tile.html", dict(ctx, clip=clip))


def _delete_ref_row(song_id, ref_id):
    row = db.one("SELECT * FROM refs WHERE id=? AND song_id=?", ref_id, song_id)
    if not row:
        raise HTTPException(404, "ref not found")
    path = row["path"] or ""
    db.run("DELETE FROM refs WHERE id=?", ref_id)
    still = db.one("SELECT id FROM refs WHERE path=?", path) if path else True
    data = os.path.realpath(db.DATA)
    real = os.path.realpath(path) if path else ""
    if (not still) and real and real.startswith(data + os.sep) and os.path.isfile(real):
        try:
            os.remove(real)
        except OSError:
            pass
    return row


@app.post("/songs/{id}/refs/{ref_id}/delete")
def html_delete_ref(request: Request, id: int, ref_id: int, tier: str = Form(""),
                    clip_idx: int = Form(-1)):
    """Operator delete of one still candidate. Clips and the scene stay."""
    get_song_or_404(id)
    row = _delete_ref_row(id, ref_id)
    if request.headers.get("HX-Request"):
        song = get_song_or_404(id)
        t = tier or row["tier"]
        ctx = approve_context(song, t)
        clip = next((c for c in ctx["clips"] if c["idx"] == row["clip_idx"]), None)
        return templates.TemplateResponse(request, "_clip_tile.html", dict(ctx, clip=clip))
    if wants_json(request):
        return JSONResponse({"ok": True, "deleted": ref_id})
    dest = f"/songs/{id}#fold-storyboard" if tier else f"/songs/{id}"
    return RedirectResponse(dest, status_code=303)


MAX_REROLL_NOTE = 400
MAX_REROLL_N = 16


@app.post("/songs/{id}/reroll")
def start_reroll(request: Request, id: int, tier: str = Form(...), clip_idx: List[int] = Form(...),
                  note: str = Form(""), n: int = Form(4),
                  seed_min: int = Form(8000), seed_max: int = Form(11000),
                  step: str = Form("equal")):
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
    heads = set(_scene_head_idxs(song, tier).values())
    if heads:
        idxs = sorted({i for i in clip_idx if i in heads})
    else:
        idxs = sorted({i for i in clip_idx if i >= 0})
    if not idxs:
        raise HTTPException(400, "no valid scene stills given")
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
    n = max(1, min(int(n or 4), MAX_REROLL_N))
    step = "fib" if (step or "").lower() == "fib" else "equal"
    try:
        import reroll_refs
        reroll_refs.seed_plan(n, seed_min, seed_max, step)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # Scene-row Reroll uses the pinned plate (saved pose_sheet_id) as image2.
    # Auto plan() plates stay out — scene_bases is saved-only. Draft+Accept
    # is the start_refs / image1 gate, not this button. Live boards never
    # had a map row and the storyboard page has no Accept control.
    saved = pose_plan.scene_bases(song, tier)
    pose_bases = {}
    missing = []
    for i in idxs:
        sn = _clip_scene_number(song, tier, i)
        if sn is None:
            continue
        path = saved.get(int(sn))
        if path:
            pose_bases[int(sn)] = path
        else:
            missing.append(str(sn))
    if missing:
        raise HTTPException(
            400,
            "pin a pose plate on scene " + ", ".join(missing)
            + " first — Reroll uses that plate, not an auto match")
    if not pose_bases:
        raise HTTPException(400, "no valid scene stills given")
    jid = jobs.enqueue("reroll", {"song_id": id, "tier": tier, "clip_indices": idxs, "note": note,
                             "pose_bases": pose_bases,
                             "n": n, "seed_min": int(seed_min), "seed_max": int(seed_max),
                             "step": step},
                 song_id=id)
    return json_or_redirect(
        request, {"job_id": jid, "kind": "reroll", "tier": tier, "n": n,
                  "clip_indices": idxs},
        f"/songs/{id}#fold-storyboard")


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
    return RedirectResponse(f"/songs/{id}#fold-storyboard", status_code=303)


@app.post("/songs/{id}/classify")
def start_classify(request: Request, id: int, tier: str = Form(...)):
    """Vision review of a tier's approved references. Advisory only: it reports
    clips to look at, it never unapproves or deletes anything."""
    get_song_or_404(id)
    valid_tier_or_400(tier)
    if not db.one("SELECT id FROM refs WHERE song_id=? AND tier=? AND approved=1", id, tier):
        raise HTTPException(400, f"no approved references for tier '{tier}' yet")
    jid = jobs.enqueue("classify", {"song_id": id, "tier": tier}, song_id=id)
    return json_or_redirect(
        request, {"job_id": jid, "kind": "classify", "tier": tier}, f"/songs/{id}")


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
async def start_clips(request: Request, id: int, tier: str = Form(...),
                       video_model: str = Form(""),
                       refine: bool = Form(False),
                       auto_qc: bool = Form(False),
                       scene: str = Form(""),
                       clip_idx: str = Form(""),
                       head_only: bool = Form(False),
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
    allowed = set(models.renderable("video").values())
    video_model = video_model or models.default_cli("video")
    if video_model not in allowed:
        raise HTTPException(400, f"video_model must be one of {sorted(allowed)}")
    storyboard_service.stamp_ref_scenes(song, tier)
    scene_num = None
    if str(scene).strip():
        try:
            scene_num = int(scene)
        except (TypeError, ValueError):
            raise HTTPException(400, "scene must be an integer") from None
    only_idx = None
    if str(clip_idx).strip():
        try:
            only_idx = int(clip_idx)
        except (TypeError, ValueError):
            raise HTTPException(400, "clip_idx must be an integer") from None
    board = load_storyboard(sb)
    if only_idx is not None and scene_num is None:
        plan0 = build_song.clip_chain_plan((board or {}).get("scenes") or [], video_model)
        hit = next((p for p in plan0 if int(p.get("clip_idx")) == only_idx), None)
        if hit is not None:
            scene_num = hit.get("scene_number")
    approved_sns = {r["scene_number"] for r in
                    db.q("""SELECT scene_number FROM refs
                            WHERE song_id=? AND tier=? AND approved=1
                              AND scene_number IS NOT NULL""", id, tier)}
    heads = _scene_head_idxs(song, tier, video_model)
    if scene_num is not None:
        heads = {sn: idx for sn, idx in heads.items() if int(sn) == scene_num}
    missing = sorted(sn for sn in heads if sn not in approved_sns)
    if missing:
        raise HTTPException(400, f"scenes missing an approved still (scene {missing})")
    # T2-45: a mixed-model song that names a model False on every reachable
    # backend is refused here, before enqueue. None is a candidate.
    bad = models.mixed_unavailable(
        (board or {}).get("scenes") or [],
        pipeline.swarm_backends(),
        default=video_model)
    if bad:
        raise HTTPException(
            400,
            "mixed-model song refused before enqueue: "
            + ", ".join(bad)
            + " unavailable on every reachable backend")
    work_dir = os.path.join(db.DATA, "driving", song["slug"])
    stamp = int(time.time() * 1000)
    motion_path = await save_driving_video(ref_motion, work_dir, f"motion_{stamp}")
    control_path = await save_driving_video(control_video, work_dir, f"control_{stamp}")
    if video_model == "i2v" and (motion_path or control_path):
        # WanImageToVideo has neither input; accepting the upload and ignoring
        # it would look like it worked
        raise HTTPException(400, "ref_motion and control_video are s2v inputs -- i2v has "
                                  "neither. Switch to s2v or remove the clips.")
    # T2-13e/T2-25 seam: scene-scoped Render clip matches build_song --only.
    if scene_num is None and only_idx is None:
        refuse_if_scene_time_mismatch(song, tier)
    jids = enqueue_clips(id, tier, video_model, refine=bool(refine),
                  ref_motion=motion_path, control_video=control_path,
                  scenes=(board or {}).get("scenes") or [],
                  scene_number=scene_num, head_only=bool(head_only),
                  clip_idx=only_idx)
    if auto_qc and jids:
        jobs.enqueue("qc", {"song_id": id, "tier": tier}, song_id=id,
                     depends_on=jids[-1])
    return json_or_redirect(
        request,
        {"job_id": jids[0] if jids else None, "job_ids": jids,
         "kind": "clips", "tier": tier, "scene": scene_num,
         "head_only": bool(head_only),
         "n": len(jids) or 1},
        (f"/songs/{id}/storyboard/{tier}#scene-{scene_num}"
         if scene_num is not None else f"/songs/{id}"))


def enqueue_clips(song_id, tier, video_model, refine=False, ref_motion=None,
                  control_video=None, scenes=None, scene_number=None,
                  head_only=False, clip_idx=None):
    """Enqueue clip render job(s). T2-11 wires depends_on for scene chains.

    No chain → one batch job (unchanged). A T2-48 over-ceiling scene is a
    chain: one job per clip, successor depends_on predecessor so _claim
    (T6-2) will not pull it until the predecessor is done.
    scene_number limits the plan to that scene. head_only keeps the first
    clip of the scene so the operator can preview before chaining the rest.
    clip_idx re-renders one already-planned take (successor still reads
    the predecessor's last frame from disk).
    """
    base = {"song_id": song_id, "tier": tier, "video_model": video_model,
            "refine": bool(refine), "ref_motion": ref_motion,
            "control_video": control_video}
    plan = build_song.clip_chain_plan(scenes or [], video_model)
    if clip_idx is not None:
        plan = [p for p in plan if int(p.get("clip_idx")) == int(clip_idx)]
        if not plan:
            raise HTTPException(400, f"no clip {clip_idx} in the plan")
        scene_number = plan[0].get("scene_number")
    elif scene_number is not None:
        plan = [p for p in plan if int(p.get("scene_number") or -1) == int(scene_number)]
        if not plan:
            raise HTTPException(400, f"no clips for scene {scene_number}")
        if head_only:
            plan = [plan[0]]
    base["n"] = max(1, len(plan)) if plan else 1
    if scene_number is not None:
        base["scene_number"] = int(scene_number)
    if (clip_idx is None and scene_number is None
            and not any(p.get("depends_on") is not None for p in plan)):
        return [jobs.enqueue("clips", base, song_id=song_id)]
    # Only the first clip of each scene needs an operator still. Successors
    # take the predecessor's last frame (T2-10 / T2-11).
    heads = build_song.scene_heads(scenes or [], video_model)
    if scene_number is not None:
        heads = {sn: idx for sn, idx in heads.items() if int(sn) == int(scene_number)}
    song = db.one("SELECT * FROM songs WHERE id=?", song_id)
    if song:
        storyboard_service.stamp_ref_scenes(song, tier)
    approved = {r["scene_number"] for r in
                db.q("""SELECT scene_number FROM refs
                        WHERE song_id=? AND tier=? AND approved=1
                          AND scene_number IS NOT NULL""",
                     song_id, tier)}
    missing = sorted(sn for sn in heads if sn not in approved)
    if missing:
        raise HTTPException(400, f"scenes missing an approved still (scene {missing})")
    jids = {}
    out = []
    for p in plan:
        pred = p.get("depends_on")
        dep = jids.get(pred) if pred is not None else None
        args = dict(base, clip_idx=p["clip_idx"],
                    depends_on_clip=pred)
        jid = jobs.enqueue("clips", args, song_id=song_id, depends_on=dep)
        jids[p["clip_idx"]] = jid
        out.append(jid)
    return out


@app.post("/songs/{id}/render")
def start_render(request: Request, id: int, tier: str = Form(...),
                 fade: float = Form(0.0)):
    get_song_or_404(id)
    valid_tier_or_400(tier)
    jid = jobs.enqueue("render_song", {"song_id": id, "tier": tier, "fade": fade},
                       song_id=id)
    return json_or_redirect(
        request, {"job_id": jid, "kind": "render_song", "tier": tier}, f"/songs/{id}")


@app.post("/songs/{id}/renders/{render_id}/confirm")
def html_confirm_render(request: Request, id: int, render_id: int):
    get_song_or_404(id)
    try:
        cleanup_service.confirm_render(render_id)
    except (LookupError, ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    return json_or_redirect(
        request, {"ok": True, "confirmed": render_id}, f"/songs/{id}")


def _delete_render_row(song_id, render_id):
    row = db.one("SELECT * FROM renders WHERE id=? AND song_id=?", render_id, song_id)
    if not row:
        raise HTTPException(404, "render not found")
    path = row["path"] or ""
    db.run("DELETE FROM renders WHERE id=?", render_id)
    # Two assemble rows can share one file. Unlink only when nothing else
    # still points at it — otherwise the sibling card 404s.
    still = db.one("SELECT id FROM renders WHERE path=?", path) if path else True
    data = os.path.realpath(db.DATA)
    real = os.path.realpath(path) if path else ""
    if (not still) and real and real.startswith(data + os.sep) and os.path.isfile(real):
        try:
            os.remove(real)
        except OSError:
            pass
    return row


@app.post("/songs/{id}/renders/{render_id}/delete")
def html_delete_render(request: Request, id: int, render_id: int):
    """Operator delete of one assembled output. T6-18 does not own this."""
    get_song_or_404(id)
    _delete_render_row(id, render_id)
    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return json_or_redirect(request, {"ok": True, "deleted": render_id}, f"/songs/{id}")


@app.get("/songs/{id}/renders/{render_id}/delete")
def html_delete_render_get(id: int, render_id: int):
    """Confirm page. A GET to this URL used to 405 / look like the studio died."""
    get_song_or_404(id)
    row = db.one("SELECT * FROM renders WHERE id=? AND song_id=?", render_id, id)
    if not row:
        raise HTTPException(404, "render not found")
    name = os.path.basename(row["path"] or "") or f"render #{render_id}"
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><title>Delete render</title>"
        f"<p>Delete assembled file <strong>{name}</strong> (#{render_id})?</p>"
        f"<form method=post action='/songs/{id}/renders/{render_id}/delete'>"
        "<button type=submit>Delete</button> "
        f"<a href='/songs/{id}'>Cancel</a></form>")


@app.post("/api/renders/{render_id}/confirm")
def api_confirm_render(render_id: int):
    try:
        row = cleanup_service.confirm_render(render_id)
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)
    return JSONResponse({
        "id": row["id"], "song_id": row["song_id"], "tier": row["tier"],
        "path": row["path"], "confirmed": 1,
        "confirmed_at": row["confirmed_at"],
    })


@app.post("/api/assets/{asset_id}/confirm")
def api_confirm_set_asset(asset_id: int):
    try:
        row = cleanup_service.confirm_set_asset(asset_id)
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)
    return JSONResponse({
        "id": row["id"], "path": row["path"], "kind": row["kind"],
        "confirmed": 1, "confirmed_at": row["confirmed_at"],
    })


@app.get("/api/songs/{id}/cleanup")
def api_cleanup_plan(id: int, tier: str):
    """Dry-run listing of clip files that would be deleted. Writes nothing."""
    get_song_or_404(id)
    valid_tier_or_400(tier)
    try:
        plan = cleanup_service.plan_clip_cleanup(id, tier)
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)
    return JSONResponse(plan)


@app.post("/api/songs/{id}/cleanup")
def api_cleanup_run(id: int, tier: str = Form(...), dry_run: str = Form("1"),
                    confirm: str = Form("")):
    """Dry-run (default) or delete clip files after operator confirm.

    Real delete needs dry_run=0 and confirm=DELETE. Local files only.
    """
    get_song_or_404(id)
    valid_tier_or_400(tier)
    want_dry = str(dry_run).lower() not in ("0", "false", "no", "off")
    if not want_dry and confirm != "DELETE":
        raise HTTPException(
            400, "real cleanup requires confirm=DELETE (and dry_run=0)")
    try:
        out = cleanup_service.run_clip_cleanup(id, tier, dry_run=want_dry)
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)
    return JSONResponse(out)


@app.post("/songs/{id}/audio")
def edit_song_audio(request: Request, id: int, trim_start: float = Form(0.0),
                     trim_end: BlankFloat = Form(None),
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
    jid = jobs.enqueue("edit_audio", {"song_id": id, "trim_start": trim_start, "trim_end": trim_end,
                                 "gain_db": gain_db, "fade_in": fade_in, "fade_out": fade_out,
                                 "prompt": prompt, "note": note, "model": model}, song_id=id)
    return json_or_redirect(request, {"job_id": jid, "kind": "edit_audio"}, f"/songs/{id}")


# Form sanity bounds, and NOT the model's limits -- ACE-Step's own
# TextEncodeAceStepAudio publishes `lyrics` as a plain multiline STRING with no
# declared maximum, so there is no number to read off the box and none is
# invented here. These exist so a paste accident or a hostile field cannot
# occupy a GPU for an hour; where the model actually truncates is unmeasured.
MAX_TAGS = 600
MAX_LYRICS = 10000
MAX_AUDIO_SECS = 240.0
MAX_AUDIO_TAKES = 4


def _screen_xxx_audio_text(text, where):
    """T10-18b work-level screen. Named so generate_audio's `lyrics` form
    param cannot shadow the lyrics module at the call site."""
    return lyrics.screen(text, tier="xxx", where=where)


@app.post("/songs/{id}/audio/generate")
def generate_audio(request: Request, id: int, tags: str = Form(""), lyrics: str = Form(""),
                   seconds: float = Form(30.0), n: int = Form(1),
                   seed: str = Form(""), denoise: float = Form(1.0),
                   from_current: str = Form(""),
                   bridge_start: str = Form(""), bridge_end: str = Form("")):
    """Queue an ACE-Step take for this song.

    The image guardrail is off the bare audio path on purpose (T8-4 / T10-16:
    it refused nursery rhymes). T10-18b is the exception: when this song already
    has an xxx storyboard, tags and lyrics are work fields of an explicit work
    and a minor reference is refused. ACE-Step still reads tags as style tokens;
    the work-level ban is the only policy that runs here.
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
    if (lyrics or "").strip():
        try:
            prompts.touch(f"song:{id}", "audio_gen_lyrics", lyrics, "saved")
        except ValueError:
            pass
    for value, bound, what in ((tags, MAX_TAGS, "tags"), (lyrics or "", MAX_LYRICS, "lyrics")):
        if len(value) > bound:
            raise HTTPException(400, f"{what} is {len(value)} characters; keep it under {bound}")
    # T10-18b: xxx work — refuse minor references in tags and lyrics.
    # Form param is also named `lyrics`, so call the module through a helper.
    if db.one("SELECT id FROM storyboards WHERE song_id=? AND tier=?", id, "xxx"):
        try:
            _screen_xxx_audio_text(tags, "tags")
            _screen_xxx_audio_text(lyrics or "", "lyrics")
        except ValueError as e:
            raise HTTPException(400, str(e))
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
    # Record the true original the same way the edit route does. Pick does not
    # write songs.mp3_path (T8-2); this is so revert still has the upload if
    # an edit is later pressed into use.
    if song["mp3_path"] and not db.one(
            "SELECT id FROM assets WHERE song_id=? AND kind='audio_original'", id):
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               id, "audio_original", song["mp3_path"], None, time.time())
    jid = jobs.enqueue("audio", args, song_id=id)
    return json_or_redirect(request, {"job_id": jid, "kind": "audio"}, f"/songs/{id}")


@app.post("/songs/{id}/audio/{asset_id}/use")
def use_audio_edit(request: Request, id: int, asset_id: int):
    get_song_or_404(id)
    # Edits only. A generated take is picked on the take, not pressed into
    # songs.mp3_path through this route -- that is how the pick used to be
    # recorded, and T8-2 forbids it.
    asset = db.one("SELECT * FROM assets WHERE id=? AND song_id=? "
                   "AND kind IN ('audio_edit','audio_gen')", asset_id, id)
    if not asset:
        raise HTTPException(404, "no such audio edit")
    if asset["kind"] == "audio_gen":
        raise HTTPException(400, "a take is picked, not used; songs.mp3_path is not the pick")
    db.run("UPDATE songs SET mp3_path=? WHERE id=?", asset["path"], id)
    return json_or_redirect(
        request, {"ok": True, "asset_id": asset_id, "mp3_path": asset["path"]},
        f"/songs/{id}")


@app.post("/songs/{id}/takes/{take_id}/pick")
def pick_song_take(request: Request, id: int, take_id: int):
    get_song_or_404(id)
    take = db.get_take(take_id)
    if not take or take["song_id"] != id:
        raise HTTPException(404, "no such take")
    db.pick_take(take_id)
    listed = db.list_takes(id)
    if wants_json(request):
        return JSONResponse({
            "picked": take_id,
            "takes": [{"id": t["id"], "picked": bool(t["picked"]), "path": t["path"]}
                      for t in listed]})
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/audio/revert")
def revert_audio(request: Request, id: int):
    get_song_or_404(id)
    original = db.one("SELECT * FROM assets WHERE song_id=? AND kind='audio_original' ORDER BY id LIMIT 1", id)
    if not original:
        raise HTTPException(400, "no original recorded for this song")
    db.run("UPDATE songs SET mp3_path=? WHERE id=?", original["path"], id)
    return json_or_redirect(
        request, {"ok": True, "mp3_path": original["path"]}, f"/songs/{id}")


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
VIDEO_MATRIX_TIERS = ("g", "pg13", "r", "xxx")
LOOK_TABS = (
    ("identity", "Identity", ("identity", "body")),
    ("wardrobe", "Wardrobe", ("wardrobe", "nude_wardrobe")),
    ("world", "World", ("style_text", "world", "backdrop", "render_tail")),
    ("sheets", "Sheet wording", ("composite", "anatomy")),
)
# Supporting characters share the look UI but not album-wide world/composite.
CHAR_LOOK_TABS = (
    ("identity", "Identity", ("identity", "body")),
    ("wardrobe", "Wardrobe", ("wardrobe", "nude_wardrobe")),
    ("sheets", "Sheet wording", ("anatomy",)),
)


def _playlist_id_for_album(album):
    if not album:
        return None
    row = db.one("SELECT id FROM playlists WHERE name=? AND kind='playlist'", album)
    return row["id"] if row else None


def _song_arc_beat(song):
    """This song's role/beat from the album arc, or None."""
    pid = _playlist_id_for_album(song["album"] or "")
    if not pid:
        return None
    data = _load_arc(pid)
    if not data:
        return None
    for s in data.get("songs") or []:
        if s.get("song_id") == song["id"]:
            return s
    return None


def lead_display_name(prof):
    """Tab label for the album lead. Not the word protagonist."""
    album = ""
    if isinstance(prof, str):
        album = prof
    elif isinstance(prof, dict):
        album = prof.get("name") or ""
        row = prof.get("_row")
        if not album and row is not None:
            try:
                album = row["name"] or ""
            except (TypeError, KeyError):
                album = ""
    return pose_plan.lead_name(album)


ALBUM_FIELDS = {
    "style_text": (
        "Album premise",
        "What this record is ABOUT, in a sentence or two — not a product name.",
        "The first thing the storyboard model is told about this release. Write the "
        "story premise from the lyrics, not a studio slogan or a tool name."),
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
        "Her entire body from shoulders to feet is covered in the same sleek charcoal-brown "
        "fur as her face, uniform in shade and texture on shoulders, upper arms, forearms, "
        "hands, torso, hips, thighs, calves and feet, every part the same single tone.",
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
DESCRIBABLE = tuple(ALBUM_FIELDS)
LOOK_TAB_HELP = {
    "identity": "This character's fixed face and body. The Lead checkbox on the character bar is the pipeline bit — this tab is not a second Lead control.",
    "wardrobe": "Most graphic clothed look on XXX, then refine per rating against that rating's guidelines. Nude wording is the unclothed swap.",
    "world": "Premise, places, studio backdrop, and render medium. Album-wide — not per character. Premise is what the record is ABOUT.",
    "sheets": "Prompt wording for composing a sheet (multiple references, anatomy). The pictures live in the Anchors fold, not here.",
}


def _album_lyrics(playlist_id, limit=10000):
    """Join every track's lyrics on this playlist, in order."""
    parts = []
    for r in db.q("""SELECT s.title, s.lyrics FROM playlist_items pi
                     JOIN songs s ON s.id = pi.song_id
                     WHERE pi.playlist_id=? ORDER BY pi.position""", playlist_id):
        ly = " ".join(str(r["lyrics"] or "").split())
        if ly:
            parts.append(f"{r['title']}: {ly[:1800]}")
    return "\n".join(parts)[:limit]


def _look_history(album, prompt_type, tier="", character_id=None):
    if prompt_type not in prompts.PROMPT_TYPES:
        return []
    return [dict(r) for r in prompts.versions(
        album, prompt_type, tier=tier, character_id=character_id)[:8]]


def _save_look_version(album, prompt_type, text, tier="", character_id=None):
    """A new prompts row only when the wording actually changed."""
    text = (text or "").strip()
    if not text or prompt_type not in prompts.PROMPT_TYPES:
        return
    try:
        prompts.touch(album, prompt_type, text, "album look",
                      tier=tier, character_id=character_id)
    except ValueError:
        return


def _wardrobe_field(album, tier, fallback, character_id=None, who="lead"):
    row = prompts.latest(album, "look_wardrobe", tier=tier, character_id=character_id)
    bx = prompts.box(album, "look_wardrobe",
                     (row["text"] if row and row["text"] else "") or fallback,
                     tier=tier, character_id=character_id)
    value = bx["text"] or fallback
    label = f"Wardrobe ({'PG-13' if tier == 'pg13' else tier.upper()})"
    return {
        "tier": tier,
        "field": {
            "key": f"wardrobe_{tier}",
            "label": label,
            "value": value,
            "hint": ALBUM_FIELDS["wardrobe"][2],
            "wand": True,
            "who": who,
            "tier": tier,
            "current_id": bx["current_id"],
            "history": _look_history(album, "look_wardrobe", tier=tier,
                                     character_id=character_id),
        },
    }


def _character_look(album, char):
    """Same look boxes as the lead, scoped to one supporting character."""
    who = f"c{char['id']}"
    fields = []
    for k in ("identity", "body", "wardrobe", "nude_wardrobe", "anatomy"):
        label, _default, hint = ALBUM_FIELDS[k]
        val = char[k] if k in char.keys() and char[k] else ""
        bx = prompts.box(album, k, val, character_id=char["id"])
        fields.append({
            "key": k, "label": label, "value": bx["text"] or val, "hint": hint,
            "wand": True,
            "history": _look_history(album, k, character_id=char["id"]),
            "current_id": bx["current_id"],
            "who": who,
        })
    fallback = (char["wardrobe"] if "wardrobe" in char.keys() and char["wardrobe"] else "")
    tiers_out = [_wardrobe_field(album, t, fallback, character_id=char["id"], who=who)
                 for t in VIDEO_MATRIX_TIERS]
    return fields, tiers_out


def _describe_image(p):
    """Cover first, then the chosen identity front. Either may be missing."""
    cover = p["image_path"] if p["image_path"] and os.path.isfile(p["image_path"]) else None
    if cover:
        return cover
    anchor = db.one(f"""SELECT * FROM anchors WHERE {db.visible_anchor_sql()}
                       ORDER BY chosen DESC, (view='front') DESC, id DESC LIMIT 1""",
                    p["name"])
    return anchor["path"] if anchor else None


def _draft_one_look(p, field, lyrics, tier="", current=""):
    image = _describe_image(p)
    if not image and not lyrics:
        raise HTTPException(
            400, f"no cover, lyrics, or anchor for album '{p['name']}' yet")
    guide = ""
    if field == "wardrobe" and tier:
        try:
            guide = tiers.compose_guardrail(tier, p["name"])
        except Exception:
            guide = ""
    try:
        return vision.draft_look_field(image, field, lyrics=lyrics,
                                       tier_guide=guide, current=current)
    except Exception as e:
        raise HTTPException(502, f"could not draft {field}: {e}") from None

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
    rows, tiers_with_video = [], {}
    for it in items:
        # every rendered video for this song, newest first per tier -- this is
        # what makes a set renderable at a given tier, and what the card offers
        # to play next to the track itself
        videos = {}
        for r in db.q("SELECT * FROM renders WHERE song_id=? ORDER BY id DESC", it["song_id"]):
            videos.setdefault(r["tier"], r["path"])
        for t in videos:
            tiers_with_video[t] = tiers_with_video.get(t, 0) + 1
        rows.append({"item": it, "videos": sorted(videos.items()),
                     "video_by_tier": videos})
    # T6-A2-playlists: song_count / total_secs from playlist_service — same
    # function GET /api/playlists/{id} uses. Not len(items) at the template.
    nums = playlist_service.numbers(p["id"])
    song_count = nums["song_count"]
    total = nums["total_secs"]
    # a tier can render a set only if EVERY song in the playlist has a video
    # at that tier; offering one that cannot render just moves the failure
    ready = sorted(t for t, n in tiers_with_video.items() if n == len(items)) if items else []
    sets = []
    for a in db.q("SELECT * FROM assets WHERE kind='set' ORDER BY id DESC"):
        if db.jset(a).get("playlist_id") != p["id"]:
            continue
        row = dict(a)
        row["caption"] = set_caption(a)
        sets.append(row)
    # the album profile, as (key, label, current value) for the form
    prof = album_profile(p["name"])
    profile_fields = []
    for k in ALBUM_FIELDS:
        bx = prompts.box(p["name"], k, prof[k])
        profile_fields.append({
            "key": k, "label": ALBUM_FIELDS[k][0],
            "value": bx["text"] or prof[k],
            "hint": ALBUM_FIELDS[k][2], "wand": k in DESCRIBABLE,
            "history": _look_history(p["name"], k),
            "current_id": bx["current_id"], "who": "lead"})
    wardrobe_tiers = [_wardrobe_field(p["name"], t, prof["wardrobe"], who="lead")
                      for t in VIDEO_MATRIX_TIERS]
    has_lyrics = bool(_album_lyrics(p["id"]))
    arc_data = _load_arc(p["id"]) or {}
    arc_by_sid = {s.get("song_id"): s for s in (arc_data.get("songs") or [])}
    for r in rows:
        r["arc"] = arc_by_sid.get(r["item"]["song_id"])
    n_sheets = db.one(
        f"""SELECT COUNT(*) n FROM anchors WHERE {db.visible_anchor_sql()}""",
        p["name"])["n"]
    anchor_tiers, all_anchors, per_character, pose_need = [], [], {}, []
    # the cast, with how many anchors each has -- an unanchored character is the
    # thing worth seeing here, since naming one in a scene achieves nothing
    cast = []
    for c in album_cast(p["name"]):
        n = db.one("SELECT COUNT(*) n FROM anchors WHERE character_id=? AND chosen=1", c["id"])["n"]
        cfields, cward = _character_look(p["name"], c)
        cast.append({"c": c, "anchors": n, "profile_fields": cfields,
                     "wardrobe_tiers": cward, "is_lead": character_is_lead(c)})
    has_anchor = bool(db.chosen_anchor("album", p["name"], "xxx") or
                      db.chosen_anchor("album", p["name"], "r") or
                      db.one(f"""SELECT id FROM anchors WHERE {db.visible_anchor_sql()}
                                 AND chosen=1 AND character_id IS NULL""", p["name"]))
    artwork_default = models.default_for("artwork")
    artwork_models = [{"key": e["key"], "label": e["label"], "available": e["available"],
                       "default": e["key"] == artwork_default}
                      for e in models.catalog(role="artwork")]
    return {"playlist": p, "rows": rows, "song_count": song_count,
            "count": song_count, "total_secs": total,
            "video_tiers": ready, "sets": sets, "profile_fields": profile_fields,
            "look_tabs": LOOK_TABS,
            "char_look_tabs": CHAR_LOOK_TABS,
            "look_tab_help": LOOK_TAB_HELP,
            "wardrobe_tiers": wardrobe_tiers,
            "has_lyrics": has_lyrics,
            "anchors": all_anchors, "anchor_tiers": anchor_tiers,
            "anchor_count": n_sheets,
            "anchor_characters": sorted(per_character.items()),
            "character_count": db.one(
                "SELECT COUNT(*) n FROM characters WHERE scope_value=?",
                p["name"])["n"] or 1,
            "artwork_models": artwork_models, "has_anchor": has_anchor,
            "instruction_box": prompts.box(p["name"], "playlist_instruction", ""),
            "cast": cast, "character_fields": CHARACTER_FIELDS,
            "copyable_fields": COPYABLE_CHARACTER_FIELDS,
            "partial_tiers": sorted(t for t in tiers_with_video if t not in ready),
            "video_matrix": VIDEO_MATRIX_TIERS,
            "transitions": list(mixer.TRANSITIONS),
            "lead_name": pose_plan.lead_name(p["name"]),
            "pose_need": pose_need,
            "released": p["released"] if "released" in p.keys() else None,
            "album_date": album_date_iso(p)}


def playlist_gallery(p):
    """Sheets + pose roster. Loaded when the Anchors fold opens, not on card."""
    prof = album_profile(p["name"])
    anchor_tiers, all_anchors = album_anchor_tiers(p["name"])
    per_character = {}
    lead_n = lead_display_name(prof)
    for a in all_anchors:
        owner = a["character_name"] or lead_n
        if pose_plan.is_ensemble(a, p["name"], owner):
            who = "Actors"
            a["ensemble"] = True
        else:
            who = owner
            a["ensemble"] = False
        a["gallery_who"] = who
        per_character[who] = per_character.get(who, 0) + 1
    pose_need = []
    for t in VIDEO_MATRIX_TIERS:
        try:
            cov = pose_plan.album_coverage(p["name"], t)
        except (LookupError, OSError, ValueError):
            continue
        if cov.get("n_needed"):
            pose_need.append(cov)
    return {"playlist": p, "anchors": all_anchors, "anchor_tiers": anchor_tiers,
            "anchor_count": len(all_anchors),
            "anchor_characters": sorted(per_character.items()),
            "lead_name": lead_display_name(prof), "pose_need": pose_need}


def _playlist_payload(p):
    """JSON playlist card. Arc only when one is defined (T2-37).

    song_count / total_secs from playlist_service (T6-A2-playlists).
    """
    nums = playlist_service.numbers(p["id"])
    out = {
        "id": p["id"],
        "name": p["name"],
        "kind": p["kind"],
        "image_path": p["image_path"],
        "created": p["created"],
        "song_count": nums["song_count"],
        "total_secs": nums["total_secs"],
    }
    arc_data = _load_arc(p["id"])
    if arc_data is not None:
        out["arc"] = arc_data
    return out


@app.get("/api/playlists/{id}")
def api_playlist_get(id: int):
    """Playlist payload a row can show. Arc is present only when defined."""
    return JSONResponse(_playlist_payload(get_playlist_or_404(id)))


def album_date_iso(p):
    t = None
    if "released" in p.keys() and p["released"]:
        t = p["released"]
    elif p["created"]:
        t = p["created"]
    return time.strftime("%Y-%m-%d", time.localtime(t)) if t else ""


def set_caption(asset):
    """Human label for a rendered set: 'Audio mix · 2026-08-17', not the file."""
    meta = db.jset(asset)
    mode = meta.get("mode") or "video"
    tier = meta.get("tier") or ""
    created = asset["created"] if "created" in asset.keys() else None
    when = time.strftime("%Y-%m-%d", time.localtime(created)) if created else ""
    if mode == "audio" or not tier:
        title = "Audio mix"
    else:
        title = f"{'PG-13' if tier == 'pg13' else tier.upper()} video set"
    return f"{title} · {when}" if when else title


def _playlist_hx(request, id, *, gone=False):
    """HX: swap the open card. JSON: ok. Else 303 to the list."""
    if wants_hx(request):
        if gone:
            return HTMLResponse("")
        return playlist_card(request, id)
    if wants_json(request):
        return JSONResponse({"ok": True, "playlist_id": id, "gone": gone})
    return RedirectResponse("/playlists", status_code=303)


def _playlist_hx_album(request, album, *, gone=False):
    pid = _playlist_id_for_album(album)
    if not pid:
        if wants_hx(request):
            return HTMLResponse("")
        if wants_json(request):
            return JSONResponse({"ok": True, "gone": gone})
        return RedirectResponse("/playlists", status_code=303)
    return _playlist_hx(request, pid, gone=gone)


def _after_name_save(request, playlist):
    """Stay on /anchors when the name was saved from the gallery."""
    ref = request.headers.get("referer") or ""
    if "/anchors" in ref:
        return RedirectResponse(
            f"/anchors?album={quote(playlist['name'])}", status_code=303)
    return _playlist_hx(request, playlist["id"])


def cover_slot_html(p):
    if p["image_path"]:
        url = media_url(p["image_path"])
        return (
            f'<button type="button" class="cover-open js-cover-open" '
            f'data-full="{url}" data-playlist="{p["id"]}" '
            f'title="View, replace, or delete this cover">'
            f'<img class="cover" src="{url}" alt=""></button>'
        )
    return '<span class="cover cover-empty">no art</span>'


def playlist_summary(p):
    """Collapsed card only. song_count / total_secs from playlist_service
    (T6-A2-playlists). Heavy album look / anchors load on expand."""
    nums = playlist_service.numbers(p["id"])
    return {"playlist": p, "song_count": nums["song_count"],
            "total_secs": nums["total_secs"],
            "album_date": album_date_iso(p)}


@app.get("/playlists", response_class=HTMLResponse)
def playlists_page(request: Request):
    # 'genre' rows can still exist in the db (a legacy row, or one inserted
    # directly rather than through this route) -- only 'playlist' rows are
    # listed here; genres belong on the song now, not as a playlist kind.
    playlists = db.q("SELECT * FROM playlists WHERE kind='playlist' ORDER BY name")
    return templates.TemplateResponse(request, "playlists.html", {
        "playlists": [playlist_summary(p) for p in playlists]})


@app.get("/playlists/{id}/card", response_class=HTMLResponse)
def playlist_card(request: Request, id: int):
    """Album body for one playlist card. Loaded when the operator opens it."""
    p = get_playlist_or_404(id)
    on_ids = {r["song_id"] for r in
              db.q("SELECT song_id FROM playlist_items WHERE playlist_id=?", id)}
    songs = [s for s in db.q("SELECT * FROM songs ORDER BY title")
             if s["id"] not in on_ids]
    ctx = {"d": playlist_detail(p), "songs": songs, "playlist": p}
    ctx.update(_arc_template_vars(id))
    return templates.TemplateResponse(request, "_playlist_card.html", ctx)


@app.get("/playlists/{id}/anchors", response_class=HTMLResponse)
def playlist_anchors_partial(request: Request, id: int):
    """Gallery for the Anchors fold. Not part of the first card payload."""
    p = get_playlist_or_404(id)
    return templates.TemplateResponse(request, "_playlist_anchors.html", {
        "d": playlist_gallery(p)})


@app.get("/playlists/{id}/sheets", response_class=HTMLResponse)
def playlist_sheets_partial(request: Request, id: int, who: str = "lead"):
    """Chosen (and other) sheets for one look tab. Loads when that tab is shown."""
    p = get_playlist_or_404(id)
    g = playlist_gallery(p)
    if who == "lead":
        rows = [a for a in g["anchors"] if not a.get("character_name")]
        name = g["lead_name"]
        pick_id = ""
    else:
        rows = [a for a in g["anchors"] if a.get("character_name") == who]
        name = who
        char = next((c for c in album_cast(p["name"]) if c["name"] == who), None)
        pick_id = str(char["id"]) if char else ""
    return templates.TemplateResponse(request, "_playlist_sheets.html", {
        "d": g, "sheets": rows, "who_name": name, "pick_id": pick_id})


@app.post("/playlists")
async def create_playlist(request: Request, name: str = Form(...),
                           kind: str = Form("playlist"),
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
    if wants_hx(request):
        return playlists_page(request)
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{id}/image")
async def set_playlist_image(request: Request, id: int, image: UploadFile = File(...)):
    """Cover art for the playlist card."""
    get_playlist_or_404(id)
    dest = await save_upload(image, MAX_IMAGE, os.path.join(db.DATA, "playlists", str(id)),
                              "image", prefix="cover")
    db.run("UPDATE playlists SET image_path=? WHERE id=?", dest, id)
    if wants_hx(request):
        return HTMLResponse(cover_slot_html(get_playlist_or_404(id)))
    return _playlist_hx(request, id)


@app.post("/playlists/{id}/date")
async def set_playlist_date(request: Request, id: int):
    """Album release date shown on the card. Not the row's created time."""
    get_playlist_or_404(id)
    form = await request.form()
    raw = (form.get("released") or "").strip()
    if not raw:
        db.run("UPDATE playlists SET released=NULL WHERE id=?", id)
        shown = "no date"
        if wants_hx(request):
            return HTMLResponse(shown)
        return json_or_redirect(request, {"ok": True, "released": None}, "/playlists")
    try:
        stamp = time.mktime(time.strptime(raw, "%Y-%m-%d"))
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    db.run("UPDATE playlists SET released=? WHERE id=?", stamp, id)
    if wants_hx(request):
        return HTMLResponse(raw)
    return json_or_redirect(request, {"ok": True, "released": raw}, "/playlists")


@app.post("/playlists/{id}/image/delete")
def delete_playlist_image(request: Request, id: int):
    """Clear the cover. Songs and the album look stay."""
    p = get_playlist_or_404(id)
    path = p["image_path"] or ""
    db.run("UPDATE playlists SET image_path=NULL WHERE id=?", id)
    data = os.path.realpath(db.DATA)
    real = os.path.realpath(path) if path else ""
    if real and real.startswith(data + os.sep) and os.path.isfile(real):
        try:
            os.remove(real)
        except OSError:
            pass
    if wants_hx(request):
        return HTMLResponse(cover_slot_html(get_playlist_or_404(id)))
    return _playlist_hx(request, id)


@app.post("/playlists/{id}/profile")
async def save_album_profile(id: int, request: Request):
    """The album's look: identity, wardrobe, body, world, render style, theme.

    Accepts only the known keys, so the form cannot write arbitrary columns.
    A field left exactly at its default is stored as NULL rather than a copy,
    so changing a default later still reaches every album that never edited it.
    """
    p = get_playlist_or_404(id)
    form = await request.form()
    # Screened before anything is written. Every one of these fields is composed
    # into an anchor prompt, and this was the only free-text path in the studio
    # that reached a render with no check_text, no check_override and no length
    # bound -- and it is the widest-reaching one, because an album's profile is
    # inherited by every sheet and every cast member who copies from it.
    values = {key: screen_prompt_field((form.get(key) or "").strip(), key, "album")
              for key in ALBUM_FIELDS if key in form}
    # Per-rating wardrobe. XXX (most graphic) is also the album wardrobe column.
    for t in VIDEO_MATRIX_TIERS:
        raw = form.get(f"wardrobe_{t}")
        if raw is None:
            continue
        text = screen_prompt_field((raw or "").strip(), "wardrobe", "album")
        _save_look_version(p["name"], "look_wardrobe", text, tier=t)
        if t == "xxx":
            values["wardrobe"] = text
    for key, (_label, default, _hint) in ALBUM_FIELDS.items():
        if key not in values:
            continue
        value = values[key]
        db.run(f"UPDATE playlists SET {key}=? WHERE id=?",
               None if not value or value == default else value, id)
        _save_look_version(p["name"], key, value)
    if "lead_name" in form:
        raw = " ".join((form.get("lead_name") or "").split())
        if len(raw) > 40:
            raise HTTPException(400, "lead name is too long (max 40)")
        try:
            if raw:
                tiers.check_text(raw, "lead name")
        except ValueError as e:
            raise HTTPException(400, str(e))
        pose_plan.set_lead_name(p["name"], raw)
    return _after_name_save(request, p)


@app.post("/playlists/{id}/describe", response_class=HTMLResponse)
def describe_album_field(request: Request, id: int, field: str = Form(...),
                         tier: str = Form("")):
    """Wand: draft one profile field from the album lyrics plus the cover.

    Synchronous rather than a job: it is one call, the user is staring at the
    box waiting for it, and a queued job would land behind an hour of rendering.
    Nothing is saved -- the text lands in the textarea for editing, and the
    existing Save button is still what writes it.
    """
    p = get_playlist_or_404(id)
    box_key = field
    box_tier = (tier or "").strip()
    if field.startswith("wardrobe_") and field != "wardrobe":
        box_tier = field.split("_", 1)[1]
        field = "wardrobe"
    if field not in DESCRIBABLE:
        raise HTTPException(400, f"cannot describe {field!r}")
    lyrics = _album_lyrics(id)
    text = _draft_one_look(p, field, lyrics, tier=box_tier)
    if field == "wardrobe" and box_tier:
        f = _wardrobe_field(p["name"], box_tier, text)["field"]
        f["value"] = text
        f["key"] = box_key if box_key.startswith("wardrobe_") else f"wardrobe_{box_tier}"
        f["who"] = "lead"
        return templates.TemplateResponse(request, "_album_field.html", {
            "playlist": p, "f": f})
    label, _default, hint = ALBUM_FIELDS[field]
    return templates.TemplateResponse(request, "_album_field.html", {
        "playlist": p,
        "f": {"key": field, "label": label, "value": text, "hint": hint, "wand": True,
              "tier": box_tier, "who": "lead",
              "history": _look_history(p["name"], field)}})


@app.post("/playlists/{id}/fill", response_class=HTMLResponse)
def fill_album_look(request: Request, id: int):
    """Draft every look field from the album lyrics plus the cover.

    The wand does one field; this does the set. Wardrobe is drafted at XXX
    first, then refined down each rating against that rating's guidelines.
    Nothing is saved -- the text lands in the boxes and Save still writes it.
    """
    p = get_playlist_or_404(id)
    lyrics = _album_lyrics(id)
    image = _describe_image(p)
    if not image and not lyrics:
        raise HTTPException(
            400, "add songs with lyrics or upload a cover first")
    prof = album_profile(p["name"])
    fields = []
    for key in ALBUM_FIELDS:
        label, _default, hint = ALBUM_FIELDS[key]
        value = prof[key]
        if key in DESCRIBABLE and key != "wardrobe":
            drafted = _draft_one_look(p, key, lyrics, current=value)
            value = drafted or value
        fields.append({"key": key, "label": label, "value": value, "hint": hint,
                       "wand": key in DESCRIBABLE, "who": "lead",
                       "history": _look_history(p["name"], key)})
    graphic = _draft_one_look(p, "wardrobe", lyrics, tier="xxx",
                              current=prof["wardrobe"])
    if graphic:
        for f in fields:
            if f["key"] == "wardrobe":
                f["value"] = graphic
    wardrobe_tiers = []
    current = graphic or prof["wardrobe"]
    for t in reversed(VIDEO_MATRIX_TIERS):
        drafted = _draft_one_look(p, "wardrobe", lyrics, tier=t, current=current)
        if drafted:
            current = drafted
        item = _wardrobe_field(p["name"], t, current, who="lead")
        item["field"]["value"] = current
        wardrobe_tiers.append(item)
    wardrobe_tiers.reverse()
    return templates.TemplateResponse(request, "_album_look_form.html",
                                       {"playlist": p, "profile_fields": fields,
                                        "look_tabs": LOOK_TABS,
                                        "look_tab_help": LOOK_TAB_HELP,
                                        "wardrobe_tiers": wardrobe_tiers})


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
def create_album_artwork(request: Request, id: int, model: str = Form(""),
                          use_anchor: bool = Form(False),
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
    if instruction:
        try:
            prompts.touch(p["name"], "playlist_instruction", instruction, "saved")
        except ValueError:
            pass
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
    return _playlist_hx(request, id)


@app.post("/playlists/{id}/delete")
def delete_playlist(request: Request, id: int, confirm: str = Form("")):
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
    return _playlist_hx(request, id, gone=True)


@app.post("/playlists/{id}/items")
def add_playlist_item(request: Request, id: int, song_id: int = Form(...),
                       transition: str = Form("fade"), secs: float = Form(2.0)):
    # No tier: membership is the song. Which tier's video (if any) is used is
    # decided when the set is rendered.
    get_playlist_or_404(id)
    get_song_or_404(song_id)
    pos_row = db.one("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM playlist_items WHERE playlist_id=?", id)
    db.run("""INSERT INTO playlist_items (playlist_id, song_id, position, transition, secs)
              VALUES (?,?,?,?,?)""", id, song_id, pos_row["p"], transition, secs)
    return _playlist_hx(request, id)


@app.post("/playlists/{id}/items/{item_id}")
async def edit_playlist_item(request: Request, id: int, item_id: int):
    """Change the join into the next song. The live board is not touched."""
    get_playlist_or_404(id)
    row = db.one("SELECT * FROM playlist_items WHERE id=? AND playlist_id=?",
                 item_id, id)
    if not row:
        raise HTTPException(404, "that song is not on this playlist")
    form = await request.form()
    transition = (form.get("transition") or row["transition"] or "fade").strip()
    if transition not in mixer.TRANSITIONS:
        raise HTTPException(400, f"transition must be one of {', '.join(mixer.TRANSITIONS)}")
    try:
        secs = float(form.get("secs") if form.get("secs") not in (None, "") else row["secs"] or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "secs must be a number")
    if secs < 0:
        raise HTTPException(400, "secs cannot be negative")
    db.run("UPDATE playlist_items SET transition=?, secs=? WHERE id=? AND playlist_id=?",
           transition, secs, item_id, id)
    if wants_hx(request):
        return _playlist_hx(request, id)
    return json_or_redirect(
        request, {"ok": True, "id": item_id, "transition": transition, "secs": secs},
        "/playlists")


@app.post("/playlists/{id}/items/{item_id}/delete")
def remove_playlist_item(request: Request, id: int, item_id: int):
    get_playlist_or_404(id)
    db.run("DELETE FROM playlist_items WHERE id=? AND playlist_id=?", item_id, id)
    if wants_hx(request):
        return _playlist_hx(request, id)
    return json_or_redirect(request, {"ok": True, "deleted": item_id}, "/playlists")


@app.post("/playlists/{id}/reorder")
def reorder_playlist(request: Request, id: int, order: str = Form(...)):
    get_playlist_or_404(id)
    ids = [int(x) for x in order.split(",") if x.strip().isdigit()]
    for pos, item_id in enumerate(ids):
        db.run("UPDATE playlist_items SET position=? WHERE id=? AND playlist_id=?", pos, item_id, id)
    if wants_hx(request):
        return HTMLResponse("")
    if wants_json(request):
        return JSONResponse({"ok": True, "order": ids})
    return RedirectResponse("/playlists", status_code=303)


def album_arc_dir(pl):
    slug = safe_name(pl["name"])
    return os.path.join(db.DATA, "arcs", slug), slug


def _arc_template_vars(id):
    """Context shared by GET /playlists/{id}/arc and the playlist fold."""
    pl = get_playlist_or_404(id)
    try:
        meter = arc_service.payload(id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    row = meter["row"]
    data = meter["arc"] or {}
    md = ""
    if row and row["md_path"] and os.path.isfile(row["md_path"]):
        md = open(row["md_path"]).read()
    proposal = meter["proposal"] or {}
    titles = {r["id"]: r["title"] for r in db.q(
        """SELECT s.id, s.title FROM playlist_items pi JOIN songs s ON s.id = pi.song_id
           WHERE pi.playlist_id=? ORDER BY pi.position""", id)}
    have = chat.available()
    models_by = {b: chat.list_models(b) for b in have}
    defaults = {}
    for b in have:
        try:
            defaults[b] = chat.openai_model() if b == "openai" else grok._resolve_model(None)
        except Exception:
            defaults[b] = ""
    outdir, _slug = album_arc_dir(pl)
    return {
        "playlist": pl, "arc": data, "row": row, "md": md, "titles": titles,
        "proposal": proposal, "backends": have, "models": models_by, "defaults": defaults,
        "song_count": meter["song_count"],
        "act_count": meter["act_count"],
        "premise": meter["premise"],
        "has_proposal": meter["has_proposal"],
        "arc_versions": arc.list_snapshots(outdir),
    }


def _arc_result(request, id):
    if request.headers.get("hx-request"):
        return templates.TemplateResponse(request, "_arc_panel.html",
                                          _arc_template_vars(id))
    return RedirectResponse(f"/playlists/{id}/arc", status_code=303)


@app.post("/playlists/{id}/arc")
@app.post("/playlists/{id}/arc/propose")
def start_arc(request: Request, id: int, theme: str = Form(""), direction: str = Form(""),
              backend: str = Form(""), model: str = Form("")):
    """Queue a proposal for the album's story arc. Not saved until accepted."""
    get_playlist_or_404(id)
    try:
        direction = arc.require_theme(theme or direction)
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
    return _arc_result(request, id)


@app.get("/playlists/{id}/arc", response_class=HTMLResponse)
def view_arc(request: Request, id: int):
    return templates.TemplateResponse(request, "arc.html", _arc_template_vars(id))


@app.post("/playlists/{id}/arc/accept")
def accept_arc(request: Request, id: int):
    """T2-15: accepting is the write. The proposal is discarded after."""
    pl = get_playlist_or_404(id)
    outdir, slug = album_arc_dir(pl)
    data = arc.load_proposal(outdir, slug)
    if not data:
        raise HTTPException(400, "there is no arc proposal to accept")
    used = data.pop("_used", "")
    titles = data.pop("_titles", None) or {
        r["id"]: r["title"] for r in db.q(
            """SELECT s.id, s.title FROM playlist_items pi JOIN songs s ON s.id = pi.song_id
               WHERE pi.playlist_id=? ORDER BY pi.position""", id)}
    arc.snapshot(outdir, slug, label="before-accept")
    json_path, md_path = arc.commit_proposal(data, outdir, slug, titles)
    db.run("""INSERT INTO arcs (playlist_id, json_path, md_path, model, prompt, created)
              VALUES (?,?,?,?,?,?)
              ON CONFLICT(playlist_id) DO UPDATE SET json_path=excluded.json_path,
              md_path=excluded.md_path, model=excluded.model, prompt=excluded.prompt,
              created=excluded.created""",
           pl["id"], json_path, md_path, used, data.get("direction", ""), time.time())
    arc.discard_proposal(outdir, slug)
    try:
        if data.get("premise"):
            arc.save_prompt(pl["name"], data["premise"], "accepted arc")
    except ValueError:
        pass
    return _arc_result(request, id)


@app.post("/playlists/{id}/arc/reject")
def reject_arc(request: Request, id: int):
    """T2-15: reject deletes the proposal and does not touch the committed files."""
    pl = get_playlist_or_404(id)
    outdir, slug = album_arc_dir(pl)
    if arc.load_proposal(outdir, slug) is None:
        raise HTTPException(400, "there is no arc proposal to reject")
    arc.discard_proposal(outdir, slug)
    return _arc_result(request, id)


@app.post("/playlists/{id}/arc/apply")
def apply_arc(request: Request, id: int, song_ids: str = Form(""), confirm: str = Form("")):
    """T2-16: more than one song is a confirmation, not a default."""
    pl = get_playlist_or_404(id)
    row = db.one("SELECT * FROM arcs WHERE playlist_id=?", id)
    if not row or not row["json_path"] or not os.path.isfile(row["json_path"]):
        raise HTTPException(400, "accept an arc before applying it to songs")
    with open(row["json_path"]) as f:
        data = json.load(f)
    ids = [int(x) for x in song_ids.replace(" ", "").split(",") if x.strip().isdigit()]
    if not ids:
        raise HTTPException(400, "name the songs to write")
    outdir, _slug = album_arc_dir(pl)
    try:
        arc.apply_summaries(data, outdir, ids,
                            confirm=confirm.lower() in ("1", "true", "yes", "on"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _arc_result(request, id)


@app.post("/playlists/{id}/arc/save")
async def save_arc(request: Request, id: int):
    """Edit the committed arc in place. Snapshots the previous JSON first."""
    pl = get_playlist_or_404(id)
    data = _load_arc(id)
    if not data:
        raise HTTPException(400, "accept an arc before editing it")
    form = await request.form()
    try:
        data["premise"] = arc._screen(form.get("premise") or "", "the arc premise")
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not data["premise"]:
        raise HTTPException(400, "the arc needs a premise")
    cont = form.get("continuity") or ""
    data["continuity"] = [ln.strip() for ln in cont.splitlines() if ln.strip()]
    for s in data.get("songs") or []:
        sid = s.get("song_id")
        if sid is None:
            continue
        for key in ("role", "beat", "opens", "closes"):
            raw = form.get(f"{key}_{sid}")
            if raw is None:
                continue
            try:
                s[key] = arc._screen(raw, f"arc {key}") if raw.strip() else ""
            except ValueError as e:
                raise HTTPException(400, str(e))
    songs = _playlist_tracks(id)
    try:
        data = arc.validate(data, [s["id"] for s in songs], SET_TRANSITIONS)
    except ValueError as e:
        raise HTTPException(400, str(e))
    data["album"] = pl["name"]
    row = db.one("SELECT * FROM arcs WHERE playlist_id=?", id)
    data["direction"] = (row["prompt"] if row else "") or ""
    outdir, slug = album_arc_dir(pl)
    arc.snapshot(outdir, slug, label="before-edit")
    _persist_arc(pl, data, model=(row["model"] if row else "") or "",
                 direction=data["direction"])
    try:
        arc.save_prompt(pl["name"], data["premise"], "edited arc")
    except ValueError:
        pass
    return _arc_result(request, id)


@app.post("/playlists/{id}/arc/restore")
async def restore_arc(request: Request, id: int):
    """Put a previous committed snapshot back as the live arc."""
    pl = get_playlist_or_404(id)
    form = await request.form()
    try:
        n = int(form.get("snapshot") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "pick an arc version")
    if n < 1:
        raise HTTPException(400, "pick an arc version")
    outdir, slug = album_arc_dir(pl)
    titles = {s["id"]: s["title"] for s in _playlist_tracks(id)}
    try:
        data = arc.restore_snapshot(outdir, slug, n, titles)
    except ValueError as e:
        raise HTTPException(400, str(e))
    row = db.one("SELECT * FROM arcs WHERE playlist_id=?", id)
    _persist_arc(pl, data, model=(row["model"] if row else "") or "",
                 direction=data.get("direction") or (row["prompt"] if row else "") or "")
    try:
        if data.get("premise"):
            arc.save_prompt(pl["name"], data["premise"], f"restored v{n}")
    except ValueError:
        pass
    return _arc_result(request, id)


def _playlist_tracks(pid):
    return [dict(r) for r in db.q(
        """SELECT s.id, s.title, s.lyrics FROM playlist_items pi
           JOIN songs s ON s.id = pi.song_id
           WHERE pi.playlist_id=? ORDER BY pi.position""", pid)]


def _load_arc(pid):
    row = db.one("SELECT * FROM arcs WHERE playlist_id=?", pid)
    if not row or not row["json_path"] or not os.path.isfile(row["json_path"]):
        return None
    try:
        with open(row["json_path"]) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _persist_arc(pl, data, model="", direction=""):
    songs = _playlist_tracks(pl["id"])
    titles = {s["id"]: s["title"] for s in songs}
    outdir = os.path.join(db.DATA, "arcs", safe_name(pl["name"]))
    json_path, md_path = arc.write(data, outdir, safe_name(pl["name"]), titles)
    db.run("""INSERT INTO arcs (playlist_id, json_path, md_path, model, prompt, created)
              VALUES (?,?,?,?,?,?)
              ON CONFLICT(playlist_id) DO UPDATE SET json_path=excluded.json_path,
              md_path=excluded.md_path, model=excluded.model, prompt=excluded.prompt,
              created=excluded.created""",
           pl["id"], json_path, md_path, model, direction, time.time())
    return data


@app.get("/api/playlists/{id}/arc")
def api_arc_get(id: int):
    # T6-A2-arc: same arc_service.payload numbers as the HTML page.
    # Playlist GET /api/playlists/{id} stays T2-37-shaped (arc only when defined).
    try:
        p = arc_service.payload(id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    return JSONResponse({
        "arc": p["arc"],
        "song_count": p["song_count"],
        "act_count": p["act_count"],
        "premise": p["premise"],
        "has_proposal": p["has_proposal"],
    })


@app.post("/api/playlists/{id}/arc/propose")
async def api_arc_propose(id: int, request: Request):
    """T2-15: generate a proposal and do not write it."""
    pl = get_playlist_or_404(id)
    body = await _api_body(request)
    try:
        direction = arc.check_direction(body.get("direction") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    songs = _playlist_tracks(id)
    if not songs:
        raise HTTPException(400, "this album has no songs yet -- add some first")
    try:
        data, used = arc.generate(pl["name"], songs, direction=direction,
                                  backend=body.get("backend") or None,
                                  model=body.get("model") or None,
                                  transitions=SET_TRANSITIONS)
    except ValueError as e:
        raise HTTPException(400, str(e))
    summaries = [arc.for_song(data, s["id"]) for s in songs]
    return JSONResponse({"proposal": data, "summaries": summaries, "model": used})


@app.post("/api/playlists/{id}/arc")
async def api_arc_accept(id: int, request: Request):
    """T2-15: accepting writes. The previous file is replaced only now."""
    pl = get_playlist_or_404(id)
    body = await _api_body(request)
    raw = body.get("arc") if isinstance(body.get("arc"), dict) else body
    songs = _playlist_tracks(id)
    if not songs:
        raise HTTPException(400, "this album has no songs yet -- add some first")
    try:
        data = arc.validate(raw, [s["id"] for s in songs], SET_TRANSITIONS)
    except ValueError as e:
        raise HTTPException(400, str(e))
    data["album"] = pl["name"]
    data["direction"] = raw.get("direction") or ""
    _persist_arc(pl, data, model=raw.get("model") or "", direction=data["direction"])
    return JSONResponse({"arc": data})


@app.post("/api/playlists/{id}/arc/reject")
def api_arc_reject(id: int):
    """T2-15: reject writes nothing. The previous file stays on disk."""
    get_playlist_or_404(id)
    return JSONResponse({"arc": _load_arc(id)})


@app.post("/playlists/{id}/render")
def render_playlist(request: Request, id: int, include_videos: bool = Form(False),
                    tier: List[str] = Form([])):
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
        return _playlist_hx(request, id)

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
    return _playlist_hx(request, id)


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


@app.get("/api/sets/{id}/preview")
def set_preview(id: int):
    """T1-16: browser playback is a proxy. The warning is data."""
    get_set_or_404(id)
    items = [dict(r) for r in db.q(
        "SELECT id, effects_json FROM set_items WHERE set_id=? ORDER BY position", id)]
    return mixer.preview_proxy(items)


@app.get("/api/sets/{id}/preview/render")
def set_preview_render(id: int, at: float = 0.0, secs: Optional[float] = None):
    """T1-17: real ffmpeg render of a bounded span. Not a proxy."""
    row = get_set_or_404(id)
    build = _set_render_items(row)
    key = "audio" if row["mode"] == "audio" else "video"
    ext = "mp3" if key == "audio" else "mp4"
    outdir = os.path.join(db.DATA, "sets", str(id))
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"preview.{ext}")
    try:
        return mixer.render_preview(build, out, at=at, secs=secs, key=key)
    except ValueError as e:
        raise HTTPException(400, str(e))


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
            "master_chain": meta.get("master_chain"),
            "loudness": meta.get("loudness")}


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


def set_detail(row, at=0.0):
    """Editor context for one set: its items in order, the predicted running
    length, whether it is ready to render video, the beat-matching plan for
    any item that asked for it, a suggested Camelot-adjacency running order,
    and every file ever rendered from it (newest first, so re-rendering
    never hides what you are comparing against -- the same shape as an
    anchor's candidates). at is the playhead in seconds; the page is a
    view of it, not a second clock.
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
    # Waveform is peaks data (T1-13/T1-15), not waveform_png background-image.
    timeline, longest = [], 0.0
    for it in items:
        secs = 0.0
        env = sets_service.peaks_envelope(it)
        if _is_card_row(it):
            secs = float(it["card_secs"] or 0.0)
            title, bpm, key = "MEOW P", None, None
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
        longest = max(longest, secs)
        timeline.append({"id": it["id"], "title": title, "secs": secs,
                          "bpm": bpm, "key": key,
                          "song_id": env["song_id"],
                          "peaks": env["pairs"], "peaks_reason": env["reason"],
                          "n_peaks": env["n"],
                          "transition": it["transition"], "trans_secs": it["secs"],
                          "hold": _hold_of(it), "beatmatch": it["beatmatch"],
                          "branded": bool(_brand_of(it, row))})
    for t in timeline:
        # a floor so a very short item is still clickable rather than a hairline
        t["pct"] = max(8.0, 100.0 * t["secs"] / longest) if longest else 100.0

    audience = _set_audience(row)
    affordances = audience_affordances(audience)
    blocks = [{"id": t["id"], "duration": t["secs"],
               "transition": t["transition"], "secs": t["trans_secs"],
               "hold": t["hold"]} for t in timeline]
    joins = mixer.timeline_joins(blocks, total)
    fps = mixer.DEFAULT_OUT_FPS
    try:
        stored_fps = row["out_fps"]
    except (KeyError, IndexError):
        stored_fps = None
    if stored_fps not in (None, ""):
        fps = float(stored_fps)
    rounding = mixer.rounding_report(blocks, fps)
    playhead = mixer.timeline_playhead(at, total)
    # Last *render* loudness (T1-25 on the asset). Live remux is
    # GET /api/sets/{id}/loudness — not this page load.
    last_loudness = None
    for r in renders:
        if r.get("loudness"):
            last_loudness = dict(r["loudness"])
            last_loudness.setdefault("source", "last_render")
            break
    if "automation_lanes" in affordances:
        curves = {}
        for t in timeline:
            for lane in automation.LANES:
                pts = automation.read(t["id"], lane)
                if pts:
                    curves.setdefault(t["id"], {})[lane] = pts
        ranges = {n: (s["lo"], s["hi"]) for n, s in automation.LANES.items()}
        lanes = mixer.timeline_lanes(
            blocks, total, curves, ranges=ranges,
            lane_order=tuple(automation.LANES))
        lane_items = [
            {"id": b["id"], "start": start, "duration": b["duration"]}
            for b, start in zip(blocks, mixer.timeline_item_starts(blocks))]
    else:
        lanes, lane_items = [], []
    return {"set": row, "items": items, "count": len(items), "total_secs": total,
            "timeline": timeline,
            "axis": mixer.timeline_axis(total),
            "joins": joins, "rounding": rounding, "playhead": playhead, "lanes": lanes,
            "lane_items": lane_items,
            "loudness": last_loudness,
            "duration_error": duration_error, "missing_video": missing_video, "renders": renders,
            "beatmatch_plan": beatmatch_plan, "suggested_order": suggested_order,
            "suggested_order_ids": suggested_order_ids,
            "audiences": AUDIENCES, "affordances": affordances,
            "mode_audience": audience,
            "loudnorm_i": effects.LOUDNORM_I,
            "loudnorm_tp": effects.LOUDNORM_TP,
            "loudnorm_lra": effects.LOUDNORM_LRA,
            "one_button_master_name": mixer.ONE_BUTTON_MASTER_NAME,
            "one_button_master_version": mixer.ONE_BUTTON_MASTER_VERSION}


def _set_renders(row):
    """Every candidate rendered from this set, newest first (T1-26 / T6-A5)."""
    out = []
    for a in db.q("SELECT * FROM assets WHERE kind='set' ORDER BY id DESC"):
        meta = db.jset(a)
        if meta.get("set_id") != row["id"]:
            continue
        rec = _set_render_row(a)
        out.append({
            "id": a["id"], "path": a["path"], "set_id": row["id"],
            "mode": rec["mode"], "tier": rec["tier"],
            "duration": rec["duration"], "missing": rec["missing"],
        })
    return out


def _set_payload(row):
    detail = set_detail(row)
    return {
        "set": _json_row(detail["set"]),
        "items": [_json_row(it) for it in detail["items"]],
        "count": detail["count"],
        "total_secs": detail["total_secs"],
        "renders": _set_renders(row),
        "mode_audience": detail["mode_audience"],
        "duration_error": detail["duration_error"],
        "rounding": detail["rounding"],
    }


def _editable_set_rows():
    return db.q(
        "SELECT id, name FROM sets WHERE mode != ? ORDER BY updated DESC, id DESC",
        automation.SONG_EDITOR_MODE)


@app.get("/sets", response_class=HTMLResponse)
def sets_page(request: Request, at: float = 0.0):
    """One editor. Empty studio gets a create form; otherwise the
    most recently updated set — same page as GET /sets/{id}."""
    rows = _editable_set_rows()
    if not rows:
        playlists = db.q("SELECT id, name FROM playlists WHERE kind='playlist' ORDER BY name")
        return templates.TemplateResponse(request, "sets.html",
                                          {"playlists": playlists, "all_tiers": tiers.all_tiers()})
    return set_edit_page(request, rows[0]["id"], at=at)


@app.get("/sets/new", response_class=HTMLResponse)
def new_set_page(request: Request):
    return RedirectResponse("/sets", status_code=303)


def _create_set_row(name, mode=None, tier="", playlist_id=None):
    """Mint a set. Shared by the HTML form and the T6-A1 JSON loop."""
    try:
        return sets_service.create(name, mode, tier, playlist_id)
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.post("/sets/new")
def create_set(name: str = Form(...), mode: str = Form("video"), tier: str = Form(""),
               playlist_id: BlankInt = Form(None)):
    sid = _create_set_row(name, mode, tier, playlist_id)
    return RedirectResponse(f"/sets/{sid}", status_code=303)


@app.get("/sets/{id}", response_class=HTMLResponse)
def set_edit_page(request: Request, id: int, at: float = 0.0):
    row = get_set_or_404(id)
    if row["mode"] == automation.SONG_EDITOR_MODE:
        raise HTTPException(404, "no such set")
    songs = db.q("SELECT id, title FROM songs ORDER BY title")
    playlists = db.q("SELECT id, name FROM playlists WHERE kind='playlist' ORDER BY name")
    ctx = {**set_detail(row, at=at), "songs": songs, "all_tiers": tiers.all_tiers(),
           "transitions": SET_TRANSITIONS, "all_sets": _editable_set_rows(),
           "playlists": playlists}
    return templates.TemplateResponse(request, "set_edit.html", ctx)


@app.post("/sets/{id}/discard")
def discard_set(request: Request, id: int):
    """Delete the set document and its assembled takes. Songs stay."""
    try:
        assets = sets_service.discard(id)
    except LookupError:
        raise HTTPException(404, "no such set")
    for a in assets:
        if a["path"] and _within_data(a["path"]) and os.path.isfile(a["path"]):
            try:
                os.remove(a["path"])
            except OSError:
                pass
    return RedirectResponse("/sets", status_code=303)


def _suggest_ctx(request, id, suggested, note="", form=None, item_id=None,
                 proposal=None):
    """Re-render the editor with a suggestion filled into the form fields.

    A suggestion POPULATES; it does not save. Writing straight to the database
    would make an AI proposal indistinguishable from a decision, and there would
    be nothing to compare it against. The values sit in the form until the human
    Accepts (T10-12) or presses Save, exactly as if they had typed them.

    `form` is what was submitted, and it is layered UNDER the suggestion and
    OVER the database. Rebuilding purely from the database discarded whatever
    was typed but not yet saved -- including the mix_direction that had just
    been typed to DRIVE the suggestion, which then vanished from the box that
    produced it, and the whole-set direction, which came back blank every time.
    """
    if wants_json(request):
        direction = (form.get("mix_direction") if form else "") or ""
        payload = mixadvice.interface_payload(
            suggested, _suggest_items(id), direction=direction)
        if proposal:
            payload["proposal_id"] = proposal["id"]
            payload["model"] = proposal["model"]
        return JSONResponse(payload)
    row = get_set_or_404(id)
    ctx = {**set_detail(row), "songs": db.q("SELECT id, title FROM songs ORDER BY title"),
           "all_tiers": tiers.all_tiers(), "transitions": SET_TRANSITIONS,
           "all_sets": _editable_set_rows(),
           "playlists": db.q("SELECT id, name FROM playlists WHERE kind='playlist' ORDER BY name"),
           "suggest_note": note,
           # the box that drove this, still holding what was typed in it
           "set_direction": (form.get("mix_direction") if form else "") or "",
           "proposal_id": proposal["id"] if proposal else None,
           "proposal_model": proposal["model"] if proposal else ""}
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
        rec, sug = mixadvice.propose(items, (form.get("mix_direction") or "").strip(),
                                     target=f"set:{id}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"the model could not be reached: {e}") from None
    note = (f"suggested settings for {len(sug)} of {len(items)} items -- nothing is saved until "
            f"you Accept or press Save on an item") if sug else "the model returned nothing usable"
    return _suggest_ctx(request, id, sug, note, form=form, proposal=rec)


@app.post("/sets/{id}/proposals/{pid}/accept")
def accept_set_proposal(request: Request, id: int, pid: int):
    """T10-12: accepting a retained mixadvice proposal writes the stored mix.

    Suggest retains. This is the human act. The model stays on the proposal.
    """
    get_set_or_404(id)
    try:
        rec = mixadvice.accept_proposal(pid, target=f"set:{id}")
    except KeyError:
        raise HTTPException(404, "no such proposal for this set")
    except ValueError as e:
        raise HTTPException(400, str(e))
    if wants_json(request):
        return JSONResponse({
            "id": rec["id"],
            "model": rec["model"],
            "accepted": rec["accepted"],
            "applied": rec["applied"],
            "payload": rec["payload"],
        })
    return RedirectResponse(f"/sets/{id}", status_code=303)


@app.post("/sets/{id}/items/{item_id}/suggest", response_class=HTMLResponse)
async def suggest_set_item(request: Request, id: int, item_id: int):
    """Suggest one item's settings, judged against the whole running order."""
    get_set_or_404(id)
    if not db.one("SELECT id FROM set_items WHERE id=? AND set_id=?", item_id, id):
        raise HTTPException(404, "no such item in this set")
    form = await request.form()
    items = _suggest_items(id)
    try:
        rec, sug = mixadvice.propose(items, (form.get("mix_direction") or "").strip(),
                                     only_id=item_id, target=f"set:{id}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"the model could not be reached: {e}") from None
    note = ("suggested -- Accept to keep it, or press Save" if sug
            else "the model returned nothing usable for that item")
    return _suggest_ctx(request, id, sug, note, form=form, item_id=item_id,
                        proposal=rec)


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


def _add_set_item_row(id, song_id, transition=None, secs=None, beatmatch=None):
    try:
        return sets_service.add_item(id, song_id, transition, secs, beatmatch)
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.post("/sets/{id}/items")
def add_set_item(id: int, song_id: int = Form(...), transition: str = Form("fade"),
                 secs: float = Form(2.0), beatmatch: bool = Form(False)):
    _add_set_item_row(id, song_id, transition, secs, beatmatch)
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


@app.post("/sets/{id}/items/{item_id}/join")
def edit_set_join(id: int, item_id: int, secs: float = Form(...)):
    """A dragged join writes the same secs column the item form writes."""
    get_set_or_404(id)
    row = db.one("SELECT * FROM set_items WHERE id=? AND set_id=?", item_id, id)
    if not row:
        raise HTTPException(404, "no such item")
    if not math.isfinite(secs) or secs < 0:
        raise HTTPException(400, "secs must be a finite number >= 0")
    _refuse_if_unrenderable(_mix_items_for_set(id, overrides={
        item_id: {"transition": row["transition"], "secs": secs,
                  "hold": _hold_of(row), "in_secs": row["in_secs"],
                  "out_secs": row["out_secs"],
                  "beatmatch": row["beatmatch"]}}))
    db.run("UPDATE set_items SET secs=? WHERE id=?", secs, item_id)
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


def _set_render_items(row):
    """Items in the shape mix_audio/render_set consume.

    Shared by POST /sets/{id}/render and GET /api/sets/{id}/preview/render
    so the preview cannot build a different document (T1-17).
    """
    items = db.q("SELECT * FROM set_items WHERE set_id=? ORDER BY position", row["id"])
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
    return build


def _enqueue_set_render(id):
    """Build the item list and enqueue render_set. HTML and JSON share this."""
    try:
        return sets_service.enqueue_render(id)
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.post("/sets/{id}/render")
def render_set_route(id: int):
    _enqueue_set_render(id)
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


@app.get("/api/sets")
def api_sets_list():
    return JSONResponse({"sets": sets_service.listed()})


@app.post("/api/sets")
async def api_sets_create(request: Request):
    body = await _api_body(request)
    try:
        sid = sets_service.create(body.get("name"), body.get("mode"),
                                  body.get("tier"), body.get("playlist_id"))
        return JSONResponse(sets_service.payload(sid))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.get("/api/sets/{id}")
def api_set_get(id: int):
    try:
        return JSONResponse(sets_service.payload(id, with_peaks=True, with_meter=False))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.get("/api/sets/{id}/loudness")
def api_set_loudness(id: int):
    """On-demand remux + export_loudness. Not called by GET /api/sets/{id}."""
    try:
        rec = sets_service.live_loudness(sets_service.get(id))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)
    return JSONResponse({"loudness": rec})


@app.post("/api/sets/{id}/items")
async def api_set_add_item(id: int, request: Request):
    body = await _api_body(request)
    try:
        sets_service.add_item(id, body.get("song_id"),
                              body.get("transition"), body.get("secs"),
                              body.get("beatmatch"))
        return JSONResponse(sets_service.payload(id))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.post("/api/sets/{id}/items/{item_id}/automation/{lane}")
async def api_set_item_automation(id: int, item_id: int, lane: str, request: Request):
    """T1-11: write one lane. The stored, decimated curve comes back;
    two points at the same t are 400 and the body names that t."""
    body = await _api_body(request)
    try:
        return JSONResponse(sets_service.save_automation(
            id, item_id, lane, body.get("points"), body.get("curve")))
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.post("/api/sets/{id}/render")
def api_set_render(id: int):
    try:
        jid = sets_service.enqueue_render(id)
        return JSONResponse({"job_id": jid, "set_id": id})
    except (LookupError, ValueError, RuntimeError) as e:
        _svc_http(e)


@app.get("/api/sets/{id}/renders")
def api_set_renders(id: int):
    row = get_set_or_404(id)
    return JSONResponse({"renders": _set_renders(row)})


@app.post("/api/sets/{id}/renders/pick")
async def api_set_render_pick(id: int, request: Request, path: str = Form("")):
    """T6-A5: pick either listed set render. The other stays listed."""
    get_set_or_404(id)
    ctype = (request.headers.get("content-type") or "")
    if "json" in ctype:
        body = await request.json()
        path = body.get("path") or path
    group = qc_service.lineage_group("set_rerender", set_id=id)
    try:
        return JSONResponse({"renders": qc_service.select("set_rerender", group, path)})
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/anchors")
def api_anchors_list(album: str = "", scope_kind: str = "", scope_value: str = ""):
    """T6-A1 / TRD-4+TRD-7: list candidates for the named JSON loop.

    T2-36: the list response carries help text per control (warnings marked
    distinctly from notes) so any client can put notes behind a `?` without
    hardcoding them, and cannot confuse a day-8 warning for a help note.
    """
    scope_value = (scope_value or album or "").strip()
    scope_kind = (scope_kind or ("album" if scope_value else "")).strip()
    return JSONResponse({
        "album": scope_value,
        "groups": _anchor_groups(scope_kind, scope_value),
        "refs": _refs_payload(scope_value) if scope_value else [],
        "help": controls_help_payload(),
    })


@app.post("/api/anchors")
async def api_anchors_generate(request: Request):
    """T6-A1: generate through the same enqueue the HTML form uses."""
    body = await _api_body(request)
    album, selected_tiers, selected_views, combos = _validate_anchor_request(
        body.get("album"),
        _as_str_list(body.get("tier") if "tier" in body else body.get("tiers")),
        _as_str_list(body.get("view") if "view" in body else body.get("views")))
    character_id = _optional_int(body.get("character_id"))
    form = _JsonForm(body)
    extra = _as_str_list(body.get("paths") or body.get("images") or body.get("path"))
    actor_names, extra_ids = _form_actors(form, album, character_id)
    extra.extend(_actor_identity_paths(album, extra_ids, selected_tiers))
    paths = _collect_anchor_ref_paths(
        album, character_id,
        _as_str_list(body.get("ref_id") if "ref_id" in body else body.get("ref_ids")),
        extra_paths=extra, work_tiers=selected_tiers)
    return JSONResponse(_enqueue_anchor_jobs(
        album, selected_tiers, selected_views, combos,
        body.get("n") or 4, character_id, form, paths, actors=actor_names))


@app.get("/api/anchors/refs")
def api_anchor_refs_list(album: str = "", character_id: CharacterId = None):
    album = (album or "").strip()
    if not album:
        raise HTTPException(400, "choose an album")
    return JSONResponse({"album": album, "refs": _refs_payload(album, character_id)})


@app.post("/api/anchors/refs")
async def api_anchor_refs_add(request: Request):
    body = await _api_body(request)
    row = _record_anchor_ref(body.get("album"), body.get("path"),
                             _optional_int(body.get("character_id")))
    return JSONResponse(_ref_payload(row))


@app.post("/api/anchors/{id}/pick")
def api_anchor_pick(id: int):
    return JSONResponse(_pick_anchor(id))


@app.post("/api/anchors/{id}/use-as-ref")
def api_anchor_use_as_ref(id: int):
    return JSONResponse(_use_anchor_as_ref(id))


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
    ctx = models_ctx()
    ctx["civitai_set"] = bool(creds.get("civitai"))
    return templates.TemplateResponse(request, "models.html", ctx)


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


@app.get("/models/civitai", response_class=HTMLResponse)
def civitai_search_page(request: Request, q: str = "", base: str = ""):
    err, rows = "", []
    if not creds.get("civitai"):
        err = "Store a Civitai API key on Config first."
    else:
        try:
            rows = civitai.search(q, base_model=base or None)
        except RuntimeError as e:
            err = str(e)
    return templates.TemplateResponse(request, "_civitai_results.html",
                                      {"rows": rows, "err": err, "q": q, "base": base})


@app.post("/models/civitai/download")
def civitai_download(request: Request, version_id: int = Form(...)):
    if not creds.get("civitai"):
        raise HTTPException(400, "Store a Civitai API key on Config first")
    jid = jobs.enqueue("download_lora", {"version_id": version_id})
    if wants_hx(request):
        return HTMLResponse(
            f'<p class="hint">Queued download #{jid} — watch the job chip.</p>')
    return RedirectResponse("/jobs", status_code=303)


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


def jobs_ctx(refresh: str = "auto"):
    """Jobs panel rows and refresh. Formatted elapsed lives here (T6-A4).

    Template interpolates only — no |format, no arithmetic on the seconds.
    """
    now = time.time()
    entries = []
    for j in jobs.recent():
        raw = ((j["finished"] or now) - j["started"]) if j["started"] else None
        elapsed = None if raw is None else f"{raw:.0f}s"
        entries.append({"job": j, "desc": jobs.describe(j), "elapsed": elapsed,
                         "cancelable": j["status"] in ("queued", "running")})
    busy = any(e["job"]["status"] in ("queued", "running", "cancelling") for e in entries)
    if refresh not in dict(JOBS_REFRESH_CHOICES):
        refresh = "auto"
    return {
        "jobs": entries,
        "active": jobs.active(),
        "refresh": refresh,
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
        "render_backend": pipeline.RENDER_BACKEND,
    }


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, refresh: str = "auto", partial: int = 0):
    ctx = jobs_ctx(refresh)
    # the poll swaps the panel only -- returning the whole page would nest a
    # second <html> inside the one already on screen
    return templates.TemplateResponse(request, "_jobs_panel.html" if partial else "jobs.html", ctx)


# How recently a finished job is still worth showing on the page that queued
# it. Long enough that a render finishing while you look away is still there
# when you look back; short enough that the panel does not become a log.
QUEUE_RECENT_SECS = 300
QUEUE_REFRESH_SECS = 5


def queue_ctx():
    """The work in flight, for the sticky chip and the jobs modal.

    Deliberately GLOBAL. There is one serialized worker and one GPU, so a set
    render really does wait behind an anchor sweep started from another tab --
    a queue filtered to "this page's" jobs would show an empty list while the
    thing actually blocking you ran invisibly.

    Polling stops when nothing is moving. A page that polls forever is a page
    that never lets the machine idle, and the chip says which state it is in
    rather than looking identical either way.
    """
    now = time.time()

    def entry(j):
        raw = ((j["finished"] or now) - j["started"]) if j["started"] else None
        elapsed = None if raw is None else f"{raw:.0f}s"
        args = {}
        try:
            args = json.loads(j["args_json"] or "{}")
        except (TypeError, ValueError):
            pass
        clips = args.get("clip_indices") or []
        if not isinstance(clips, list):
            clips = []
        return {"job": j, "desc": jobs.describe(j),
                "elapsed": elapsed, "elapsed_secs": raw,
                "tier": args.get("tier") or "",
                "clip_indices": [int(c) for c in clips if str(c).lstrip("-").isdigit()],
                "n": args.get("n") or 0,
                "scene": args.get("scene_number") or args.get("scene"),
                "song_id": j["song_id"] or args.get("song_id")}

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
    rows_out = active + waiting + recent
    # Chip headline: in-flight first. A cancelled QC that never started
    # (Auto QC ticked on a clip that then died) is not "work in flight".
    chip_recent = [e for e in recent
                   if e["job"].get("started") or e["job"]["status"] == "done"]
    chip_rows = active + waiting + chip_recent
    return {"queue_active": active, "queue_waiting": waiting, "queue_recent": recent,
            "queue_rows": rows_out,
            "queue_latest": chip_rows[0] if chip_rows else None,
            "queue_n_running": len(active),
            "queue_n_waiting": len(waiting),
            "queue_n_recent": len(recent),
            "queue_refresh_secs": QUEUE_REFRESH_SECS if (active or waiting) else 0}


def queue_payload(ctx=None):
    """The numbers _queue.html prints, as JSON. Same ctx so two answers
    cannot silently diverge (T6-A2). Counts and formatted elapsed live
    in queue_ctx (T6-A4); JSON elapsed stays the seconds number."""
    ctx = queue_ctx() if ctx is None else ctx

    def entry(e):
        job = dict(e["job"])
        return {
            "id": job["id"],
            "status": job["status"],
            "kind": job.get("kind"),
            "desc": e["desc"],
            "elapsed": e["elapsed_secs"],
        }

    return {
        "running": ctx["queue_n_running"],
        "waiting": ctx["queue_n_waiting"],
        "recent": ctx["queue_n_recent"],
        "refresh_secs": ctx["queue_refresh_secs"],
        "active": [entry(e) for e in ctx["queue_active"]],
        "waiting_jobs": [entry(e) for e in ctx["queue_waiting"]],
        "recent_jobs": [entry(e) for e in ctx["queue_recent"]],
    }


@app.get("/queue", response_class=HTMLResponse)
def queue_panel(request: Request, chip: int = 0):
    """Queue fragment. chip=1 is the sticky topbar summary; default is the
    modal / T6-A2 list. JSON is the same numbers either way.
    """
    ctx = queue_ctx()
    if wants_json(request):
        return JSONResponse(queue_payload(ctx))
    tmpl = "_job_chip.html" if chip else "_queue.html"
    return templates.TemplateResponse(request, tmpl, ctx)


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


@app.get("/jobs/{id}")
def job_one(request: Request, id: int):
    """JSON status for one job. HTML still lives on /jobs."""
    row = jobs.get(id)
    if row is None:
        raise HTTPException(404, "no such job")
    if not wants_json(request):
        return RedirectResponse("/jobs", status_code=303)
    args = {}
    try:
        args = json.loads(row["args_json"] or "{}")
    except (TypeError, ValueError):
        pass
    return JSONResponse({
        "id": row["id"], "status": row["status"], "progress": row["progress"],
        "error": row["error"], "kind": row["kind"],
        "song_id": row["song_id"] or args.get("song_id"),
        "tier": args.get("tier"),
        "clip_indices": args.get("clip_indices") or [],
        "n": args.get("n") or 0,
    })


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
