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
from build_song import CHUNK
import jobs
import pipeline
import grok
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


def chosen_anchor(scope_kind, scope_value, tier, view="front"):
    """The anchors row picked for this scope+tier+view, or None. Reference/clip
    generation always resolves anchors this way -- never by song."""
    return db.one("""SELECT * FROM anchors WHERE scope_kind=? AND scope_value=? AND tier=? AND view=?
                      AND chosen=1""", scope_kind, scope_value, tier, view)


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
    anchor_profile = {"anchor": {"identity": prof["identity"], "wardrobe": prof["wardrobe"],
                                 "body": prof["body"]}}
    paths = pipeline.gen_anchor(args["face"], args["outfit"], view, args.get("n", 4), progress,
                                 profile=anchor_profile)
    now = time.time()
    for p in paths:
        db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path, chosen, created)
                  VALUES (?,?,?,?,?,0,?)""",
               args["scope_kind"], args["scope_value"], args["tier"], view, p, now)
    return {"n": len(paths)}


@jobs.handler("storyboard")
def h_storyboard(args, progress):
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    guardrail = tiers.compose_guardrail(tier)
    style_row = db.one("SELECT * FROM assets WHERE song_id=? AND kind='style' ORDER BY id DESC LIMIT 1", sid)
    style_note = db.jset(style_row).get("note", "") if style_row else ""
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
    sb = grok.generate_storyboard(song["lyrics"] or "", tier, guardrail, style_note,
                                   song_fields, args.get("model"), args.get("scene_seconds"), progress)
    outdir = os.path.join(db.DATA, "storyboards", song["slug"])
    os.makedirs(outdir, exist_ok=True)
    json_path, md_path = grok.write_storyboard(sb, outdir, song["slug"], tier)
    scene_count = len(sb.get("scenes", [])) if isinstance(sb, dict) else None
    db.run("""INSERT INTO storyboards (song_id, tier, json_path, md_path, scene_count, created)
              VALUES (?,?,?,?,?,?)
              ON CONFLICT(song_id, tier) DO UPDATE SET json_path=excluded.json_path,
              md_path=excluded.md_path, scene_count=excluded.scene_count, created=excluded.created""",
           sid, tier, json_path, md_path, scene_count, time.time())
    return {"json": json_path, "md": md_path}


@jobs.handler("refs")
def h_refs(args, progress):
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    sb = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", sid, tier)
    # resolve the chosen anchor candidate (an output image) into a name usable
    # as ComfyUI input -- start_refs already checked one is chosen for this tier
    anchor_name = pipeline.install_input(args["anchor_path"])
    results = pipeline.gen_refs(song["slug"], tier, sb["json_path"], anchor_name,
                                 song["mp3_path"], progress, limit=args.get("limit"),
                                 guard=tiers.compose_guardrail(tier))
    now = time.time()
    for r in results:
        db.run("""INSERT OR IGNORE INTO refs (song_id, tier, clip_idx, path, seed, approved, created)
                  VALUES (?,?,?,?,?,0,?)""",
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
    results = pipeline.reroll(song["slug"], tier, sb["json_path"], anchor_name,
                               song["mp3_path"], args["clip_indices"], progress)
    now = time.time()
    for r in results:
        db.run("""INSERT OR IGNORE INTO refs (song_id, tier, clip_idx, path, seed, approved, created)
                  VALUES (?,?,?,?,?,0,?)""",
               sid, tier, r["clip_idx"], r["path"], r.get("seed"), now)
    return {"count": len(results)}


@jobs.handler("clips")
def h_clips(args, progress):
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    sb = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", sid, tier)
    approved = db.q("SELECT clip_idx, path FROM refs WHERE song_id=? AND tier=? AND approved=1", sid, tier)
    ref_paths = [{"clip_idx": r["clip_idx"], "path": r["path"]} for r in approved]
    results = pipeline.gen_clips(song["slug"], tier, sb["json_path"], song["mp3_path"], ref_paths, progress)
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
        models = grok.list_models()
    except Exception:
        models = []
    # what "(highest available)" will actually pick, named in the dropdown so
    # the default is not a mystery
    best = grok.best_model(models) if models else None
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
    reviews = []
    for a in db.q("SELECT * FROM assets WHERE song_id=? AND kind='review' ORDER BY id DESC LIMIT 4", id):
        meta = json.loads(a["meta_json"] or "{}")
        reviews.append({"tier": meta.get("tier", "?"), "flagged": meta.get("flagged", []),
                        "path": a["path"]})
    return templates.TemplateResponse(request, "song.html", {
        "song": song, "tiers": tiers.all_tiers(), "storyboards": storyboards,
        "approved_tiers": approved_tiers, "reviews": reviews,
        "style_assets": style_assets, "chosen_anchors": chosen_anchors,
        "clips_ready_tiers": clips_ready_tiers,
        "renders": renders, "song_jobs": song_jobs, "active_job": active_job, "models": models,
        "audio_duration": audio_duration, "audio_edits": audio_edits, "audio_original": audio_original,
        "best_model": best, "render_tiers": render_tiers,
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
    rows = db.q("SELECT * FROM anchors ORDER BY scope_kind, scope_value, tier, view, id DESC")
    groups = {}
    for r in rows:
        key = (r["scope_kind"], r["scope_value"], r["tier"], r["view"])
        groups.setdefault(key, []).append(r)
    group_list = [{"scope_kind": k[0], "scope_value": k[1], "tier": k[2], "view": k[3], "candidates": v}
                  for k, v in groups.items()]
    albums = sorted({s["album"] for s in db.q("SELECT DISTINCT album FROM songs") if s["album"]})
    playlists = db.q("SELECT id, name FROM playlists WHERE kind='playlist' ORDER BY name")
    return templates.TemplateResponse(request, "anchors.html", {
        "groups": group_list, "tiers": tiers.all_tiers(), "albums": albums, "playlists": playlists,
        "prefill_scope_kind": scope_kind or "album", "prefill_scope_value": scope_value})


@app.post("/anchors")
async def start_anchor(scope_kind: str = Form(...), scope_value: str = Form(...), tier: str = Form(...),
                        view: str = Form("front"), face: UploadFile = File(...),
                        outfit: UploadFile = File(...), n: int = Form(4)):
    if scope_kind not in ("album", "playlist"):
        raise HTTPException(400, "scope_kind must be 'album' or 'playlist'")
    scope_value = scope_value.strip()
    if not scope_value:
        raise HTTPException(400, "scope_value is required")
    valid_tier_or_400(tier)
    if view not in ("front", "back"):
        raise HTTPException(400, "view must be 'front' or 'back'")
    dest_dir = os.path.join(db.DATA, "uploads", "anchors", safe_name(scope_kind), safe_name(scope_value))
    face_path = await save_upload(face, MAX_IMAGE, dest_dir, "image", prefix=f"face_{int(time.time() * 1000)}")
    outfit_path = await save_upload(outfit, MAX_IMAGE, dest_dir, "image",
                                     prefix=f"outfit_{int(time.time() * 1000)}")
    n = max(1, min(int(n), 8))
    jobs.enqueue("anchor", {"scope_kind": scope_kind, "scope_value": scope_value, "tier": tier,
                             "view": view, "face": face_path, "outfit": outfit_path, "n": n})
    return RedirectResponse(f"/anchors?scope_kind={scope_kind}&scope_value={quote(scope_value)}",
                             status_code=303)


@app.post("/anchors/{id}/pick")
def pick_anchor(id: int):
    row = db.one("SELECT * FROM anchors WHERE id=?", id)
    if not row:
        raise HTTPException(404, "no such anchor candidate")
    # exactly one chosen per (scope_kind, scope_value, tier, view) group
    db.run("UPDATE anchors SET chosen=0 WHERE scope_kind=? AND scope_value=? AND tier=? AND view=?",
           row["scope_kind"], row["scope_value"], row["tier"], row["view"])
    db.run("UPDATE anchors SET chosen=1 WHERE id=?", id)
    return RedirectResponse(
        f"/anchors?scope_kind={row['scope_kind']}&scope_value={quote(row['scope_value'])}",
        status_code=303)


@app.post("/songs/{id}/storyboard")
def start_storyboard(id: int, tier: str = Form(...), model: str = Form(""),
                      scene_seconds: float = Form(4.0)):
    get_song_or_404(id)
    valid_tier_or_400(tier)
    if not math.isfinite(scene_seconds):
        raise HTTPException(400, "scene_seconds must be a finite number")
    scene_seconds = min(max(scene_seconds, 1.0), 60.0)
    jobs.enqueue("storyboard", {"song_id": id, "tier": tier, "model": model or None,
                                 "scene_seconds": scene_seconds}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


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
    return templates.TemplateResponse(request, "storyboard.html",
                                       {"song": song, "tier": tier, "row": row, "md": md})


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


@app.get("/songs/{id}/approve/{tier}", response_class=HTMLResponse)
def approve_grid(request: Request, id: int, tier: str):
    song = get_song_or_404(id)
    refs_rows = db.q("SELECT * FROM refs WHERE song_id=? AND tier=? ORDER BY clip_idx, id", id, tier)
    by_clip = {}
    for r in refs_rows:
        by_clip.setdefault(r["clip_idx"], []).append(r)
    clips = []
    for i in range(clip_count(song)):
        cands = by_clip.get(i, [])
        clips.append({"idx": i, "candidates": cands, "approved": any(c["approved"] for c in cands)})
    return templates.TemplateResponse(request, "approve.html", {"song": song, "tier": tier, "clips": clips})


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
    candidates = db.q("SELECT * FROM refs WHERE song_id=? AND tier=? AND clip_idx=? ORDER BY id",
                       id, tier, clip_idx)
    clip = {"idx": clip_idx, "candidates": candidates, "approved": any(c["approved"] for c in candidates)}
    return templates.TemplateResponse(request, "_clip_tile.html", {"song": song, "tier": tier, "clip": clip})


@app.post("/songs/{id}/reroll")
def start_reroll(id: int, tier: str = Form(...), clip_idx: List[int] = Form(...)):
    song = get_song_or_404(id)
    sb = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    if not sb:
        raise HTTPException(400, "generate a storyboard for this tier first")
    idxs = sorted({i for i in clip_idx if 0 <= i < clip_count(song)})
    if not idxs:
        raise HTTPException(400, "no valid clip indices given")
    if len(idxs) > MAX_REROLL_CLIPS:
        raise HTTPException(400, f"too many clips to reroll at once (max {MAX_REROLL_CLIPS})")
    jobs.enqueue("reroll", {"song_id": id, "tier": tier, "clip_indices": idxs}, song_id=id)
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


@app.post("/songs/{id}/clips")
def start_clips(id: int, tier: str = Form(...)):
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
    jobs.enqueue("clips", {"song_id": id, "tier": tier}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/render")
def start_render(id: int, tier: str = Form(...), fade: float = Form(0.0)):
    get_song_or_404(id)
    valid_tier_or_400(tier)
    jobs.enqueue("render_song", {"song_id": id, "tier": tier, "fade": fade}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/audio")
def edit_song_audio(id: int, trim_start: float = Form(0.0), trim_end: Optional[float] = Form(None),
                     gain_db: float = Form(0.0), fade_in: float = Form(0.0), fade_out: float = Form(0.0)):
    song = get_song_or_404(id)
    trim_start, trim_end, gain_db, fade_in, fade_out = clamp_audio_edit_params(
        trim_start, trim_end, gain_db, fade_in, fade_out)
    # record the true original exactly once, before mp3_path can ever move --
    # this is what "revert to original" restores.
    if not db.one("SELECT id FROM assets WHERE song_id=? AND kind='audio_original'", id):
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               id, "audio_original", song["mp3_path"], None, time.time())
    jobs.enqueue("edit_audio", {"song_id": id, "trim_start": trim_start, "trim_end": trim_end,
                                 "gain_db": gain_db, "fade_in": fade_in, "fade_out": fade_out}, song_id=id)
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
        "Not sent to the renderer. Context for you and for storyboard writing."),
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
        "List real, distinct locations. Scenes rotate through them, which is what stops "
        "every frame being the same corridor in the same purple light."),
    "render_tail": (
        "Render style",
        "photorealistic cinematic frame, premium music video still, high detail, 16:9",
        "Appended to every image prompt. Medium, quality and aspect only -- no subject."),
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
    anchors = db.q("""SELECT * FROM anchors WHERE scope_kind='album' AND scope_value=?
                      ORDER BY tier, view, id DESC""", p["name"])
    return {"playlist": p, "rows": rows, "count": len(items), "total_secs": total,
            "video_tiers": ready, "sets": sets, "profile_fields": profile_fields,
            "anchors": anchors,
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
    return templates.TemplateResponse(request, "tiers.html", {"tiers": tiers.all_tiers()})


@app.post("/tiers")
def create_tier(name: str = Form(...), guardrail: str = Form("")):
    try:
        tiers.add_tier(name, guardrail)
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
