"""FastAPI web layer for Meow P Studio. Routes only -- all real work happens
in db/tiers/jobs/pipeline/grok/lyrics/mixer; this file wires HTTP to them and
does upload validation + path-traversal-safe media serving.
"""
import json, os, re, time
from contextlib import asynccontextmanager
from typing import List
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import (HTMLResponse, RedirectResponse, FileResponse,
                                PlainTextResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db
import tiers
import jobs
import pipeline
import grok
import lyrics
import mixer

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT, "static")
TEMPLATES_DIR = os.path.join(ROOT, "templates")

HOST = os.environ.get("STUDIO_HOST", "0.0.0.0")
PORT = int(os.environ.get("STUDIO_PORT", "8000"))

MAX_MP3 = 50 * 1024 * 1024
MAX_IMAGE = 20 * 1024 * 1024
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# Anything servable over /media must resolve inside one of these -- reuses
# pipeline's own ComfyUI paths rather than inventing a parallel config knob.
MEDIA_ROOTS = [os.path.realpath(db.DATA), os.path.realpath(pipeline.COMFY_INPUT),
               os.path.realpath(pipeline.COMFY_OUTPUT)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    jobs.start()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["media_url"] = lambda p: media_url(p)


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
    return name or "file"


def media_url(path):
    if not path:
        return None
    return "/media/" + quote(os.path.realpath(path), safe="/")


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


async def save_upload(upload: UploadFile, cap: int, dest_dir: str, kind: str):
    """kind: 'mp3' or 'image'. Validates ext + content-type + size, writes
    under dest_dir with a sanitized name, returns the saved path."""
    data = await upload.read(cap + 1)
    if len(data) > cap:
        raise HTTPException(413, f"{kind} file too large (max {cap // (1024 * 1024)}MB)")
    if not data:
        raise HTTPException(400, f"{kind} file is empty")
    name = safe_name(upload.filename)
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


# ------------------------------------------------------------- job handlers --

@jobs.handler("transcribe")
def h_transcribe(args, progress):
    song = db.one("SELECT * FROM songs WHERE id=?", args["song_id"])
    if not song:
        return
    ok, msg = lyrics.available()
    if not ok:
        raise RuntimeError(msg)
    result = lyrics.transcribe(song["mp3_path"], progress)
    text = lyrics.to_sections(result)
    db.run("UPDATE songs SET lyrics=? WHERE id=?", text, song["id"])
    return {"chars": len(text)}


@jobs.handler("anchor")
def h_anchor(args, progress):
    sid = args["song_id"]
    paths = pipeline.gen_anchor(args["face"], args["outfit"], args.get("view", "front"),
                                 args.get("n", 4), progress)
    now = time.time()
    for p in paths:
        db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
               sid, "anchor_candidate", p, None, now)
    return {"n": len(paths)}


@jobs.handler("storyboard")
def h_storyboard(args, progress):
    sid, tier = args["song_id"], args["tier"]
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    guardrail = tiers.compose_guardrail(tier)
    style_row = db.one("SELECT * FROM assets WHERE song_id=? AND kind='style' ORDER BY id DESC LIMIT 1", sid)
    style_note = db.jset(style_row).get("note", "") if style_row else ""
    sb = grok.generate_storyboard(song["lyrics"] or "", tier, guardrail, style_note,
                                   dict(song), args.get("model"), args.get("scene_seconds"), progress)
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
    results = pipeline.gen_refs(song["slug"], tier, sb["json_path"], song["anchor_path"],
                                 song["mp3_path"], progress, limit=args.get("limit"))
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
    results = pipeline.reroll(song["slug"], tier, sb["json_path"], song["anchor_path"],
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
    out = os.path.join(outdir, f"{safe_name(playlist['name'])}.mp4")
    mixer.render_set(args["items"], out, progress)
    return {"path": out}


# ------------------------------------------------------------------ media --

@app.get("/media/{path:path}")
def media(path: str):
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
    return templates.TemplateResponse(request, "index.html", {"songs": entries})


@app.post("/songs")
async def create_song(title: str = Form(...), album: str = Form(""), genre: str = Form(""),
                       mp3: UploadFile = File(...)):
    slug = unique_slug(title)
    dest = await save_upload(mp3, MAX_MP3, upload_dir(slug), "mp3")
    duration = None
    try:
        duration = lyrics.estimate_duration(dest)
    except Exception:
        pass
    sid = db.upsert_song(slug, title=title.strip() or slug, album=album.strip(), genre=genre.strip(),
                          mp3_path=dest, duration=duration)
    jobs.enqueue("transcribe", {"song_id": sid}, song_id=sid)
    return RedirectResponse(f"/songs/{sid}", status_code=303)


@app.get("/songs/{id}", response_class=HTMLResponse)
def song_page(request: Request, id: int):
    song = get_song_or_404(id)
    storyboards = {r["tier"]: r for r in db.q("SELECT * FROM storyboards WHERE song_id=?", id)}
    anchor_candidates = db.q(
        "SELECT * FROM assets WHERE song_id=? AND kind='anchor_candidate' ORDER BY id DESC", id)
    style_assets = db.q("SELECT * FROM assets WHERE song_id=? AND kind='style' ORDER BY id DESC", id)
    renders = db.q("SELECT * FROM renders WHERE song_id=? ORDER BY id DESC", id)
    song_jobs = db.q("SELECT * FROM jobs WHERE song_id=? ORDER BY id DESC LIMIT 20", id)
    active_job = next((j for j in song_jobs if j["status"] in ("queued", "running")), None)
    try:
        models = grok.list_models()
    except Exception:
        models = []
    return templates.TemplateResponse(request, "song.html", {
        "song": song, "tiers": tiers.all_tiers(), "storyboards": storyboards,
        "anchor_candidates": anchor_candidates, "style_assets": style_assets,
        "renders": renders, "song_jobs": song_jobs, "active_job": active_job, "models": models,
    })


@app.post("/songs/{id}/lyrics")
def save_lyrics(id: int, lyrics_text: str = Form(...)):
    get_song_or_404(id)
    db.run("UPDATE songs SET lyrics=? WHERE id=?", lyrics_text, id)
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
    dest = await save_upload(image, MAX_IMAGE, upload_dir(song["slug"]), "image")
    db.run("UPDATE songs SET style_path=? WHERE id=?", dest, id)
    db.run("INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
           id, "style", dest, json.dumps({"note": note}), time.time())
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/anchor")
async def start_anchor(id: int, face: UploadFile = File(...), outfit: UploadFile = File(...),
                        view: str = Form("front"), n: int = Form(4)):
    song = get_song_or_404(id)
    face_path = await save_upload(face, MAX_IMAGE, upload_dir(song["slug"]), "image")
    outfit_path = await save_upload(outfit, MAX_IMAGE, upload_dir(song["slug"]), "image")
    n = max(1, min(int(n), 8))
    jobs.enqueue("anchor", {"song_id": id, "face": face_path, "outfit": outfit_path,
                             "view": view, "n": n}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/anchor/pick")
def pick_anchor(id: int, asset_id: int = Form(...)):
    get_song_or_404(id)
    asset = db.one("SELECT * FROM assets WHERE id=? AND song_id=? AND kind='anchor_candidate'", asset_id, id)
    if not asset:
        raise HTTPException(404, "no such anchor candidate")
    name = pipeline.install_input(asset["path"])
    db.run("UPDATE songs SET anchor_path=? WHERE id=?", name, id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/storyboard")
def start_storyboard(id: int, tier: str = Form(...), model: str = Form(""),
                      scene_seconds: float = Form(4.0)):
    get_song_or_404(id)
    valid_tier_or_400(tier)
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
def start_refs(id: int, tier: str = Form(...), limit: int = Form(0)):
    song = get_song_or_404(id)
    if not song["anchor_path"]:
        raise HTTPException(400, "pick an anchor image first")
    if not db.one("SELECT id FROM storyboards WHERE song_id=? AND tier=?", id, tier):
        raise HTTPException(400, "generate a storyboard for this tier first")
    jobs.enqueue("refs", {"song_id": id, "tier": tier, "limit": limit or None}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.get("/songs/{id}/approve/{tier}", response_class=HTMLResponse)
def approve_grid(request: Request, id: int, tier: str):
    song = get_song_or_404(id)
    sb = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    scene_count = sb["scene_count"] if sb and sb["scene_count"] else 0
    refs_rows = db.q("SELECT * FROM refs WHERE song_id=? AND tier=? ORDER BY clip_idx, id", id, tier)
    by_clip = {}
    for r in refs_rows:
        by_clip.setdefault(r["clip_idx"], []).append(r)
    clips = []
    for i in range(scene_count):
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
    get_song_or_404(id)
    if not db.one("SELECT id FROM storyboards WHERE song_id=? AND tier=?", id, tier):
        raise HTTPException(400, "generate a storyboard for this tier first")
    jobs.enqueue("reroll", {"song_id": id, "tier": tier, "clip_indices": clip_idx}, song_id=id)
    return RedirectResponse(f"/songs/{id}/approve/{tier}", status_code=303)


@app.post("/songs/{id}/clips")
def start_clips(id: int, tier: str = Form(...)):
    song = get_song_or_404(id)
    sb = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", id, tier)
    if not sb:
        raise HTTPException(400, "generate a storyboard for this tier first")
    scene_count = sb["scene_count"] or 0
    approved_idxs = {r["clip_idx"] for r in
                      db.q("SELECT clip_idx FROM refs WHERE song_id=? AND tier=? AND approved=1", id, tier)}
    missing = [i for i in range(scene_count) if i not in approved_idxs]
    if missing:
        raise HTTPException(400, f"clips missing an approved reference: {missing}")
    jobs.enqueue("clips", {"song_id": id, "tier": tier}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


@app.post("/songs/{id}/render")
def start_render(id: int, tier: str = Form(...), fade: float = Form(0.0)):
    get_song_or_404(id)
    jobs.enqueue("render_song", {"song_id": id, "tier": tier, "fade": fade}, song_id=id)
    return RedirectResponse(f"/songs/{id}", status_code=303)


# -------------------------------------------------------------- playlists --

@app.get("/playlists", response_class=HTMLResponse)
def playlists_page(request: Request):
    playlists = db.q("SELECT * FROM playlists ORDER BY kind, name")
    songs = db.q("SELECT * FROM songs ORDER BY title")
    detail = []
    for p in playlists:
        items = db.q("""SELECT pi.*, s.title AS song_title, s.slug AS song_slug
                         FROM playlist_items pi JOIN songs s ON s.id = pi.song_id
                         WHERE pi.playlist_id=? ORDER BY pi.position""", p["id"])
        detail.append({"playlist": p, "playlist_items": items})
    return templates.TemplateResponse(request, "playlists.html", {"playlists": detail, "songs": songs})


@app.post("/playlists")
def create_playlist(name: str = Form(...), kind: str = Form("playlist")):
    if kind not in ("playlist", "genre"):
        raise HTTPException(400, "kind must be 'playlist' or 'genre'")
    name = name.strip()
    if not name:
        raise HTTPException(400, "name required")
    pid = db.run("INSERT INTO playlists (name, kind) VALUES (?,?)", name, kind)
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{id}/items")
def add_playlist_item(id: int, song_id: int = Form(...), tier: str = Form(...),
                       transition: str = Form("fade"), secs: float = Form(2.0)):
    get_playlist_or_404(id)
    get_song_or_404(song_id)
    pos_row = db.one("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM playlist_items WHERE playlist_id=?", id)
    db.run("""INSERT INTO playlist_items (playlist_id, song_id, tier, position, transition, secs)
              VALUES (?,?,?,?,?,?)""", id, song_id, tier, pos_row["p"], transition, secs)
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{id}/reorder")
def reorder_playlist(id: int, order: str = Form(...)):
    get_playlist_or_404(id)
    ids = [int(x) for x in order.split(",") if x.strip().isdigit()]
    for pos, item_id in enumerate(ids):
        db.run("UPDATE playlist_items SET position=? WHERE id=? AND playlist_id=?", pos, item_id, id)
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{id}/render")
def render_playlist(id: int):
    get_playlist_or_404(id)
    items = db.q("""SELECT pi.* FROM playlist_items pi WHERE pi.playlist_id=? ORDER BY pi.position""", id)
    build_items = []
    for it in items:
        render_row = db.one("SELECT * FROM renders WHERE song_id=? AND tier=? ORDER BY id DESC LIMIT 1",
                             it["song_id"], it["tier"])
        if not render_row:
            raise HTTPException(400, f"song {it['song_id']} tier {it['tier']} has no render yet")
        build_items.append({"path": render_row["path"], "transition": it["transition"], "secs": it["secs"]})
    jobs.enqueue("render_set", {"playlist_id": id, "items": build_items})
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

@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    return templates.TemplateResponse(request, "jobs.html", {"jobs": jobs.recent(), "active": jobs.active()})


@app.get("/jobs/{id}/stream")
def job_stream(id: int):
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
