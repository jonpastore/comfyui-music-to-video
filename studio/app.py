"""FastAPI web layer for Meow P Studio. Routes only -- all real work happens
in db/tiers/jobs/pipeline/grok/lyrics/mixer; this file wires HTTP to them and
does upload validation + path-traversal-safe media serving.
"""
import json, math, os, re, shutil, sqlite3, tempfile, time
from contextlib import asynccontextmanager
from typing import List, Optional
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import (HTMLResponse, RedirectResponse, FileResponse,
                                PlainTextResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db
import tiers  # also puts the repo-root scripts on sys.path (STUDIO_SCRIPTS)
import build_song  # clip_plan/allocate/sname -- the renderers' own definitions
from build_song import CHUNK
import jobs
import pipeline
import grok
import models
import vision
import lyrics
import mixer

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
GAIN_DB_RANGE = (-30.0, 30.0)

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
ANCHOR_VIEWS = {
    "front": "front, clothed",
    "back": "back, clothed",
    "front_nude": "front, nude",
    "back_nude": "back, nude",
}
NUDE_VIEWS = {"front_nude", "back_nude"}
templates.env.filters["viewname"] = lambda v: ANCHOR_VIEWS.get(v, v or "")
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


def clip_count(song):
    """How many 4.8125 s clips this track is cut into.

    Comes from the AUDIO LENGTH, never from the storyboard's scene count:
    build_song.clip_plan() spreads a 20-scene storyboard across all 41 clips of
    a 3:16 track. Using scene_count here hid clips 20..40 from the approve grid
    and let clip generation start with two thirds of its references missing.
    """
    return math.ceil((song["duration"] or 0) / CHUNK)


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


@jobs.handler("anchor")
def h_anchor(args, progress):
    # anchors are scoped to an ALBUM/PLAYLIST and a TIER, never a song -- see
    # db.py's anchors table. Not tied to any song_id.
    view = args.get("view", "front")
    # the album's own look, edited in the UI, is what describes the character --
    # make_anchor.py no longer knows about any particular one
    prof = album_profile(args["scope_value"] if args["scope_kind"] == "album" else "")
    cid = args.get("character_id")
    if cid:
        # a CAST member's sheet describes that character, not the protagonist.
        # Anything they leave blank falls back to the album's wording, so a
        # supporting character inherits the album's body-consistency rule -- the
        # one thing that must never be silently absent from a prompt.
        char = db.one("SELECT * FROM characters WHERE id=?", cid)
        if char:
            prof = {k: (char[k] or prof[k]) for k in ("identity", "wardrobe", "body")}
            progress(f"anchor for cast member: {char['name']}")
    anchor_profile = {"anchor": {"identity": prof["identity"], "wardrobe": prof["wardrobe"],
                                 "body": prof["body"]}}
    if view in NUDE_VIEWS:
        progress(f"nude anchor for tier '{args['tier']}' -- permitted by its allow_nudity flag")
    paths = pipeline.gen_anchor(args["face"], args["outfit"], view, args.get("n", 4), progress,
                                 profile=anchor_profile,
                                 guard=tiers.compose_guardrail(args["tier"]),
                                 prompt=args.get("prompt", ""))
    now = time.time()
    for p in paths:
        db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen, created,
                                        character_id)
                  VALUES (?,?,?,?,?,0,?,?)""",
               args["scope_kind"], args["scope_value"], args["tier"], view, p, now, cid)
    return {"n": len(paths)}


@jobs.handler("storyboard")
def h_storyboard(args, progress):
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    guardrail = tiers.compose_guardrail(tier)
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
    if direction:
        guardrail = tiers.PINNED
    # The cast the model is allowed to name. Only characters with an anchor at
    # THIS tier: naming someone with no anchor produces a scene the renderer
    # cannot keep consistent, which is the problem the cast exists to solve.
    cast = [(c["name"], " ".join(p for p in (c["role"], c["identity"], c["wardrobe"]) if p))
            for c, _a in cast_anchors(song["album"] or "", tier)]
    if cast:
        progress(f"cast offered to the storyboard: {', '.join(n for n, _ in cast)}")
    sb = grok.generate_storyboard(song["lyrics"] or "", tier, guardrail, style_note,
                                   song_fields, args.get("model"), args.get("scene_seconds"), progress,
                                   direction=direction, cast=cast)
    outdir = os.path.join(db.DATA, "storyboards", song["slug"])
    os.makedirs(outdir, exist_ok=True)
    json_path, md_path = grok.write_storyboard(sb, outdir, song["slug"], tier)
    scene_count = len(sb.get("scenes", [])) if isinstance(sb, dict) else None
    # the direction is stored with the result, not just used and forgotten: a
    # storyboard you cannot see the prompt for is one you cannot tune.
    db.run("""INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created, prompt)
              VALUES (?,?,?,?,?,?,?)
              ON CONFLICT(song_id, tier) DO UPDATE SET json_path=excluded.json_path,
              md_path=excluded.md_path, scene_count=excluded.scene_count,
              created=excluded.created, prompt=excluded.prompt""",
           sid, tier, json_path, md_path, scene_count, time.time(), args.get("direction", ""))
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
                                 guard=tiers.compose_guardrail(tier), body=body, cast=cast)
    now = time.time()
    for r in results:
        db.run("""INSERT OR IGNORE INTO refs (song_id, tier, clip_idx, path, seed, approved,
                                               created, origin)
                  VALUES (?,?,?,?,?,0,?,'gen')""",
               sid, tier, r["clip_idx"], r["path"], r.get("seed"), now)
    return {"count": len(results)}


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
                               guard=tiers.compose_guardrail(tier),
                               body=album_profile(album)["body"],
                               note=args.get("note", ""), cast=cast)
    now = time.time()
    for r in results:
        db.run("""INSERT OR IGNORE INTO refs (song_id, tier, clip_idx, path, seed, approved,
                                               created, origin)
                  VALUES (?,?,?,?,?,0,?,'reroll')""",
               sid, tier, r["clip_idx"], r["path"], r.get("seed"), now)
    return {"count": len(results)}


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
        guard=tiers.compose_guardrail(tier), body=body)
    now = time.time()
    for r in results:
        db.run("""INSERT OR IGNORE INTO refs (song_id, tier, clip_idx, path, seed, approved,
                                               created, origin)
                  VALUES (?,?,?,?,?,0,?,?)""",
               sid, tier, r["clip_idx"], r["path"], r.get("seed"), now, args["mode"])
    return {"count": len(results), "mode": args["mode"]}


@jobs.handler("clips")
def h_clips(args, progress):
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    sb = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", sid, tier)
    approved = db.q("SELECT clip_idx, path FROM refs WHERE song_id=? AND tier=? AND approved=1", sid, tier)
    ref_paths = [{"clip_idx": r["clip_idx"], "path": r["path"]} for r in approved]
    video_model = args.get("video_model") or "s2v"
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
    playlist = db.one("SELECT * FROM playlists WHERE id=?", args["playlist_id"])
    outdir = os.path.join(db.DATA, "sets")
    os.makedirs(outdir, exist_ok=True)
    base = safe_name(playlist["name"])
    # mode defaults to video so a job enqueued by an older build still means
    # what it meant when it was queued
    if args.get("mode") == "audio":
        out = os.path.join(outdir, f"{base}.mp3")
        mixer.mix_audio(args["items"], out, progress)
    else:
        tier = args.get("tier")
        out = os.path.join(outdir, f"{base}_{tier}.mp4" if tier else f"{base}.mp4")
        mixer.render_set(args["items"], out, progress)
    db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
           None, "set", out, json.dumps({"playlist_id": args["playlist_id"],
                                          "mode": args.get("mode", "video"),
                                          "tier": args.get("tier")}), time.time())
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

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    songs = db.q("SELECT * FROM songs ORDER BY created DESC")
    entries = []
    for s in songs:
        board_tiers = {r["tier"] for r in db.q("SELECT DISTINCT tier FROM storyboards WHERE song_id=?", s["id"])}
        rendered_tiers = {r["tier"] for r in db.q("SELECT DISTINCT tier FROM renders WHERE song_id=?", s["id"])}
        tier_status = [{"tier": t, "rendered": t in rendered_tiers} for t in sorted(board_tiers)]
        entries.append({"song": s, "tiers": tier_status})
    return templates.TemplateResponse(request, "index.html", {"songs": entries, "genre_data": GENRE_DATA})


@app.post("/songs")
async def create_song(title: str = Form(...), album: str = Form(""), genre: str = Form(""),
                       subgenre: str = Form(""), genre2: str = Form(""), subgenre2: str = Form(""),
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
    return RedirectResponse(f"/songs/{sid}", status_code=303)


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
    n_clips = clip_count(song)
    for t, sb in storyboards.items():
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
    return templates.TemplateResponse(request, "song.html", {
        "song": song, "tiers": all_tiers, "storyboards": storyboards,
        "approved_tiers": approved_tiers, "reviews": reviews,
        "style_assets": style_assets, "chosen_anchors": chosen_anchors,
        "clips_ready_tiers": clips_ready_tiers, "anchor_by_tier": anchor_by_tier,
        "video_models": video_models,
        "renders": renders, "song_jobs": song_jobs, "active_job": active_job,
        "models": chat_models,
        "audio_duration": audio_duration, "audio_edits": audio_edits, "audio_original": audio_original,
        "best_model": best, "render_tiers": render_tiers,
        **storyboard_form_ctx(song, form_tier, chat_models, best),
    })


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


@app.get("/anchors", response_class=HTMLResponse)
def anchors_page(request: Request, scope_kind: str = "", scope_value: str = ""):
    # grouped by CHARACTER as well: two characters' candidates in one grid, with
    # one "chosen" between them, is unreadable and mispicks are invisible
    rows = db.q("""SELECT a.*, c.name AS character_name
                   FROM anchors a LEFT JOIN characters c ON c.id = a.character_id
                   ORDER BY a.scope_kind, a.scope_value, c.name, a.tier, a.view, a.id DESC""")
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
    return templates.TemplateResponse(request, "anchors.html", dict(
        anchor_form_ctx(scope_kind, scope_value, ""),
        groups=group_list, albums=albums, playlists=playlists))


@app.post("/anchors")
async def start_anchor(scope_kind: str = Form(...), scope_value: str = Form(...), tier: str = Form(...),
                        view: str = Form("front"), face: UploadFile = File(...),
                        outfit: UploadFile = File(...), n: int = Form(4),
                        character_id: Optional[int] = Form(None), prompt: str = Form("")):
    if scope_kind not in ("album", "playlist"):
        raise HTTPException(400, "scope_kind must be 'album' or 'playlist'")
    scope_value = scope_value.strip()
    if not scope_value:
        raise HTTPException(400, "scope_value is required")
    valid_tier_or_400(tier)
    if view not in ANCHOR_VIEWS:
        raise HTTPException(400, f"view must be one of {', '.join(ANCHOR_VIEWS)}")
    # A nude anchor is only generated for a tier that permits nudity. The flag
    # is the capability; refusing here is what makes it mean something, rather
    # than being a label the UI shows and the renderer ignores.
    if view in NUDE_VIEWS and not tiers.allows_nudity(tier):
        raise HTTPException(400, f"the '{tier}' tier does not permit nudity, so it cannot have "
                                  f"a nude anchor. Turn nudity on for that tier first.")
    prompt = (prompt or "").strip()
    if len(prompt) > MAX_ANCHOR_PROMPT:
        raise HTTPException(400, f"the anchor prompt is {len(prompt)} characters; keep it under "
                                  f"{MAX_ANCHOR_PROMPT}")
    try:
        tiers.check_text(prompt, "anchor prompt")
        tiers.check_override(prompt)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if character_id is not None:
        # a character belongs to the album it was defined on; anchoring one
        # under a different scope would silently make an unreachable anchor
        char = get_character_or_404(character_id)
        if scope_kind != "album" or char["scope_value"] != scope_value:
            raise HTTPException(400, f"character {char['name']!r} belongs to album "
                                      f"{char['scope_value']!r}, not to {scope_kind} {scope_value!r}")
    dest_dir = os.path.join(db.DATA, "uploads", "anchors", safe_name(scope_kind), safe_name(scope_value))
    face_path = await save_upload(face, MAX_IMAGE, dest_dir, "image", prefix=f"face_{int(time.time() * 1000)}")
    outfit_path = await save_upload(outfit, MAX_IMAGE, dest_dir, "image",
                                     prefix=f"outfit_{int(time.time() * 1000)}")
    n = max(1, min(int(n), 8))
    jobs.enqueue("anchor", {"scope_kind": scope_kind, "scope_value": scope_value, "tier": tier,
                             "view": view, "face": face_path, "outfit": outfit_path, "n": n,
                             "character_id": character_id, "prompt": prompt})
    return RedirectResponse(f"/anchors?scope_kind={scope_kind}&scope_value={quote(scope_value)}",
                             status_code=303)


# ------------------------------------------------------------- characters --

CHARACTER_FIELDS = ("role", "identity", "wardrobe", "body")
MAX_CHARACTER_FIELD = 1000


def check_character_fields(form):
    """Character prose lands in image prompts, so it is screened exactly as the
    album profile's own fields would be if they were free text from a form."""
    out = {}
    for field in CHARACTER_FIELDS:
        if field not in form:
            continue
        value = " ".join((form.get(field) or "").split())   # single line: prompt fragment
        if len(value) > MAX_CHARACTER_FIELD:
            raise HTTPException(400, f"{field} is {len(value)} characters; keep it under "
                                      f"{MAX_CHARACTER_FIELD}")
        try:
            tiers.check_text(value, f"character {field}")
        except ValueError as e:
            raise HTTPException(400, str(e))
        out[field] = value
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
    try:
        db.run("""INSERT INTO characters (scope_value, name, role, identity, wardrobe, body, created)
                  VALUES (?,?,?,?,?,?,?)""", p["name"], name, fields.get("role", ""),
               fields.get("identity", ""), fields.get("wardrobe", ""), fields.get("body", ""),
               time.time())
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


MAX_ANCHOR_PROMPT = 2000


def default_anchor_prompt(scope_value, view, character_id=None):
    """The prompt make_anchor would compose, shown so it can be edited.

    Built by the REAL composer (make_anchor.prompt_for) from the album's own
    identity/wardrobe/body, so what the box shows is what would otherwise have
    been sent -- not a lookalike that drifts from it.
    """
    import make_anchor
    prof = album_profile(scope_value or "")
    fields = {k: prof[k] for k in ("identity", "wardrobe", "body")}
    if character_id:
        char = db.one("SELECT * FROM characters WHERE id=?", character_id)
        if char:
            fields = {k: (char[k] or fields[k]) for k in fields}
    return make_anchor.prompt_for(view, make_anchor.load_anchor(None) | fields)


def anchor_form_ctx(scope_kind, scope_value, tier, view="front", character_id=None):
    all_t = tiers.all_tiers()
    tier = tier or (all_t[0]["name"] if all_t else "")
    allows = tiers.allows_nudity(tier) if tier else False
    return {
        "tiers": all_t, "prefill_scope_kind": scope_kind or "album",
        "prefill_scope_value": scope_value, "form_tier": tier,
        "form_view": view, "allows_nudity": allows,
        # a nude view is not merely disabled -- it is absent from the list for a
        # tier that cannot use it, the same way a tier with no storyboard is not
        # offered for reference generation
        "views": [(k, v) for k, v in ANCHOR_VIEWS.items()
                  if allows or k not in NUDE_VIEWS],
        "anchor_prompt": default_anchor_prompt(scope_value, view, character_id),
        "pinned": tiers.PINNED.strip(), "tier_text": tier_tone(tier),
        "max_anchor_prompt": MAX_ANCHOR_PROMPT,
        "characters": (album_cast(scope_value) if scope_value
                       else db.q("SELECT * FROM characters ORDER BY scope_value, name")),
    }


@app.get("/anchors/form", response_class=HTMLResponse)
def anchor_form(request: Request, scope_kind: str = "album", scope_value: str = "",
                 tier: str = "", view: str = "front", character_id: Optional[int] = None):
    """The generate form, re-rendered for another tier or view.

    Its own route because the prefill and the offered views both depend on the
    tier: a tier that does not permit nudity must not list a nude view, and the
    guardrail shown has to be the one that will actually apply.
    """
    if view not in ANCHOR_VIEWS:
        view = "front"
    return templates.TemplateResponse(request, "_anchor_form.html",
                                       anchor_form_ctx(scope_kind, scope_value, tier, view,
                                                       character_id))


@app.post("/anchors/{id}/delete")
def delete_anchor(id: int):
    """Delete one anchor candidate, row and file.

    Anchors accumulate: every generation adds N candidates and only one is ever
    picked, so a scope+tier+view group is mostly rejects. The file is removed
    only if it resolves inside db.DATA -- ComfyUI's own output dir is shared and
    is not ours to delete from.
    """
    row = db.one("SELECT * FROM anchors WHERE id=?", id)
    if not row:
        raise HTTPException(404, "no such anchor candidate")
    if _within_data(row["path"]) and os.path.isfile(row["path"]):
        try:
            os.remove(row["path"])
        except OSError:
            pass
    db.run("DELETE FROM anchors WHERE id=?", id)
    return RedirectResponse(
        f"/anchors?scope_kind={row['scope_kind']}&scope_value={quote(row['scope_value'])}",
        status_code=303)


@app.post("/anchors/delete-unpicked")
def delete_unpicked_anchors(scope_kind: str = Form(...), scope_value: str = Form(...),
                             tier: str = Form(...), view: str = Form(...),
                             character_id: Optional[int] = Form(None)):
    """Clear out one group's rejects, keeping whichever is chosen.

    Deleting six candidates one at a time is the slow path, and the chosen one
    is explicitly protected so this can never leave a tier with no anchor --
    which would silently block every refs job for it.
    """
    rows = db.q("""SELECT * FROM anchors WHERE scope_kind=? AND scope_value=? AND tier=?
                   AND view=? AND character_id IS ? AND chosen=0""",
                scope_kind, scope_value, tier, view, character_id)
    for r in rows:
        if _within_data(r["path"]) and os.path.isfile(r["path"]):
            try:
                os.remove(r["path"])
            except OSError:
                pass
        db.run("DELETE FROM anchors WHERE id=?", r["id"])
    return RedirectResponse(
        f"/anchors?scope_kind={scope_kind}&scope_value={quote(scope_value)}", status_code=303)


@app.post("/anchors/{id}/pick")
def pick_anchor(id: int):
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
    return RedirectResponse(
        f"/anchors?scope_kind={row['scope_kind']}&scope_value={quote(row['scope_value'])}",
        status_code=303)


def tier_tone(tier):
    """A tier's own tone/wardrobe wording, with the pinned clause removed.

    compose_guardrail() always welds PINNED on; this is the half a human wrote
    and the half that is editable. Unknown tier -> "" rather than an exception,
    because this feeds a form that must still render.
    """
    try:
        return tiers.compose_guardrail(tier).replace(tiers.PINNED, "").strip()
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
    parts = [(f"Tone and wardrobe ({tier} tier)", tier_tone(tier)),
             ("Look", prof["style_text"]), ("World", prof["world"]),
             ("Render style", prof["render_tail"])]
    return "\n\n".join(f"{label}: {text.strip()}" for label, text in parts if text and text.strip())


def storyboard_form_ctx(song, tier, chat_models=None, best=None, direction=None):
    """The direction form for one tier: the prefill, plus the limits shown above
    it. `direction` overrides the prefill -- used to redisplay what was actually
    sent for an already-generated storyboard."""
    if direction is None:
        row = db.one("SELECT prompt FROM storyboards WHERE song_id=? AND tier=?", song["id"], tier)
        direction = (row["prompt"] if row else "") or default_direction(song, tier)
    return {"song": song, "tier": tier, "tiers": tiers.all_tiers(),
            "direction": direction, "pinned": tiers.PINNED.strip(),
            "tier_text": tier_tone(tier), "max_direction": grok.MAX_DIRECTION,
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
    jobs.enqueue("storyboard", {"song_id": id, "tier": tier, "model": model or None,
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


def storyboard_scenes(song, sb, tier, anchored=()):
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
    nclips = clip_count(song)
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
            "start": idxs[0] * CHUNK if idxs else None,
            "end": (idxs[-1] + 1) * CHUNK if idxs else None,
            "length": len(idxs) * CHUNK,
            "guidance": build_song.guidance_seconds(scene),
            "shots": sorted(set(shots_of.get(num, []))),
            "refs": refs, "edited": edited,
            "cast": [{"name": n, "anchored": n in anchored}
                     for n in (scene.get("characters") or [])],
        })
    return rows, nclips


def coverage(rows, nclips, duration):
    """How the storyboard's PACING INTENT compares with the track.

    Not "is the video the right length" -- allocate() always spends exactly
    nclips, so the render is always the length of the song. What can be wrong is
    the intent: a storyboard whose duration_guidance totals 90s for a 240s track
    is being stretched 2.7x, and every scene will run far longer than it was
    written for. That is what this measures.
    """
    intent = sum(r["guidance"] for r in rows)
    rendered = nclips * CHUNK
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
    rows, nclips = storyboard_scenes(song, sb, tier, {c["name"] for c, _a in cast})
    # the anchors this tier will actually render from, at the top, because a
    # storyboard is read against the character it is for. The protagonist's
    # (character_id IS NULL) first, then the cast.
    anchors = db.q("""SELECT a.*, c.name AS character_name
                      FROM anchors a LEFT JOIN characters c ON c.id = a.character_id
                      WHERE a.scope_kind='album' AND a.scope_value=? AND a.tier=? AND a.chosen=1
                      ORDER BY (a.character_id IS NOT NULL), c.name, a.view, a.id""", album, tier)
    return templates.TemplateResponse(request, "storyboard.html", {
        "song": song, "tier": tier, "row": row, "md": md, "sb": sb,
        "scene_rows": rows, "anchors": anchors, "chunk": CHUNK,
        "unanchored": sorted({n["name"] for r in rows for n in r["cast"] if not n["anchored"]}),
        "coverage": coverage(rows, nclips, song["duration"]),
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
    rows, _ = storyboard_scenes(song, load_storyboard(row), tier, anchored)
    r = next(x for x in rows if x["num"] == num)
    return templates.TemplateResponse(request, "_scene_row.html", {
        "song": song, "tier": tier, "r": r, "fields": EDITABLE_SCENE_FIELDS, "chunk": CHUNK})


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
    clips = []
    for i in range(clip_count(song)):
        cands = by_clip.get(i, [])
        clips.append({"idx": i, "candidates": cands,
                      "approved": any(c["approved"] for c in cands),
                      "flag": flags.get(i)})
    # face sources: whoever has a chosen anchor at this tier
    faces = []
    if chosen_anchor("album", song["album"] or "", tier):
        faces.append(("protagonist", "protagonist"))
    faces += [(str(c["id"]), c["name"]) for c, _a in cast_anchors(song["album"] or "", tier)]
    return {"song": song, "tier": tier, "clips": clips, "faces": faces,
            "flagged_idxs": sorted(flags)}


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
    for i in range(clip_count(song)):
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
    idxs = sorted({i for i in clip_idx if 0 <= i < clip_count(song)})
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
async def start_clips(id: int, tier: str = Form(...), video_model: str = Form("s2v"),
                       refine: bool = Form(False),
                       ref_motion: Optional[UploadFile] = File(None),
                       control_video: Optional[UploadFile] = File(None)):
    song = get_song_or_404(id)
    sb = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    if not sb:
        raise HTTPException(400, "generate a storyboard for this tier first")
    n_clips = clip_count(song)
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
    if video_model not in ("s2v", "i2v"):
        raise HTTPException(400, "video_model must be 's2v' or 'i2v'")
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
def edit_song_audio(id: int, trim_start: float = Form(0.0), trim_end: Optional[float] = Form(None),
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


@app.post("/songs/{id}/audio/{asset_id}/use")
def use_audio_edit(id: int, asset_id: int):
    get_song_or_404(id)
    asset = db.one("SELECT * FROM assets WHERE id=? AND song_id=? AND kind='audio_edit'", asset_id, id)
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
def delete_song(id: int, confirm: str = Form("")):
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

    for table in ("storyboards", "refs", "clips", "renders", "assets", "playlist_items"):
        db.run(f"DELETE FROM {table} WHERE song_id=?", id)
    db.run("DELETE FROM songs WHERE id=?", id)
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
        "Body colouring and texture are identical head to toe, matching the face, with no "
        "lighter or differently-toned patches anywhere.",
        "Re-assert colouring PER BODY PART. One mention at the top does not hold below the "
        "waist -- this is the fix for a black-furred character rendering with human-toned "
        "legs, and it has to be positive wording, not a negative."),
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
    anchors = db.q("""SELECT a.*, c.name AS character_name
                      FROM anchors a LEFT JOIN characters c ON c.id = a.character_id
                      WHERE a.scope_kind='album' AND a.scope_value=?
                      ORDER BY a.tier, a.view, a.id DESC""", p["name"])
    # the cast, with how many anchors each has -- an unanchored character is the
    # thing worth seeing here, since naming one in a scene achieves nothing
    cast = []
    for c in album_cast(p["name"]):
        n = db.one("SELECT COUNT(*) n FROM anchors WHERE character_id=? AND chosen=1", c["id"])["n"]
        cast.append({"c": c, "anchors": n})
    return {"playlist": p, "rows": rows, "count": len(items), "total_secs": total,
            "video_tiers": ready, "sets": sets, "profile_fields": profile_fields,
            "anchors": anchors, "cast": cast, "character_fields": CHARACTER_FIELDS,
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
def create_playlist(name: str = Form(...), kind: str = Form("playlist")):
    # Genres are set on the song at upload now (genre/subgenre/genre2/subgenre2
    # columns) -- 'genre' is no longer a creatable playlist kind.
    if kind != "playlist":
        raise HTTPException(400, "kind must be 'playlist'")
    name = name.strip()
    if not name:
        raise HTTPException(400, "name required")
    try:
        db.run("INSERT INTO playlists (name, kind, created) VALUES (?,?,?)", name, kind, time.time())
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"playlist '{name}' ({kind}) already exists")
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
    for key, (_label, default, _hint) in ALBUM_FIELDS.items():
        if key not in form:
            continue
        value = (form.get(key) or "").strip()
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


# ------------------------------------------------------------------ models --

@app.get("/models", response_class=HTMLResponse)
def models_page(request: Request):
    """Every model this studio can use, what each one is designed for, and
    whether it is actually on the box.

    The point is that adding a model is a catalogue entry, not a code edit, and
    that nobody has to read build_song.py to find out what renders the clips.
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
    return templates.TemplateResponse(request, "models.html", {
        "roles": models.ROLES, "by_role": by_role,
        "defaults": {r: models.default_for(r) for r in models.ROLES},
        "reachable": models.installed() is not None,
        "chat": chat, "chat_best": chat_best, "chat_error": chat_error,
        "vision_model": grok.VISION_MODEL,
    })


@app.post("/models/{role}/default")
def set_model_default(role: str, key: str = Form(...)):
    try:
        models.set_default(role, key)
    except ValueError as e:
        raise HTTPException(400, str(e))
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
           "refresh_choices": JOBS_REFRESH_CHOICES}
    # the poll swaps the panel only -- returning the whole page would nest a
    # second <html> inside the one already on screen
    return templates.TemplateResponse(request, "_jobs_panel.html" if partial else "jobs.html", ctx)


@app.post("/jobs/{id}/cancel")
def cancel_job(id: int):
    try:
        jobs.cancel(id)
    except ValueError as e:
        raise HTTPException(400, str(e))
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
