#!/usr/bin/env python3
"""Storyboard as a service: arc, generate, scene edit, meter, cast.

docs/TRD-6 T6-A3 / TRD-2 §8. This is the layer the web routes call and it
imports NOTHING from FastAPI, so every operation is reachable from a test,
a shell, or a mobile client written later against the same JSON. If a route
handler decides something, a mobile client cannot -- so nothing is decided
in a route handler.
"""
import json
import math
import os
import time
from urllib.parse import quote

import db
import tiers  # STUDIO_SCRIPTS / repo root on path before build_song
import arc
import build_song
import grok
import jobs
import models
import mixer

SCENE_TIME_TOLERANCE = 0.15
# video_model is a directorial fact on the scene (T2-42 / T2-43 / T2-44).
EDITABLE_SCENE_FIELDS = ("image_prompt", "video_motion_prompt", "story",
                         "video_model")
MAX_SCENE_FIELD = 4000
DEFAULT_SCENE_SECONDS = 4.0
SCENE_SECONDS_MIN = 1.0
SCENE_SECONDS_MAX = 60.0


def require_song(sid):
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    if not song:
        raise LookupError("no such song")
    return song


def require_tier(name):
    if not db.one("SELECT id FROM tiers WHERE name=?", name):
        raise ValueError(f"no such tier: {name}")
    return name


def require_playlist(pid):
    row = db.one("SELECT * FROM playlists WHERE id=?", pid)
    if not row:
        raise LookupError("no such playlist")
    return row


def clip_count(song, scene_seconds=None):
    return build_song.n_clips_for(song["duration"], scene_seconds)


def chosen_anchor(scope_kind, scope_value, tier, view="front", character_id=None):
    return db.one("""SELECT * FROM anchors WHERE scope_kind=? AND scope_value=? AND tier=?
                      AND view=? AND chosen=1 AND character_id IS ?""",
                  scope_kind, scope_value, tier, view, character_id)


def album_cast(album):
    return db.q("SELECT * FROM characters WHERE scope_value=? ORDER BY name", album or "")


def cast_anchors(album, tier):
    out = []
    for c in album_cast(album):
        anchor = chosen_anchor("album", album or "", tier, "front", c["id"])
        if anchor:
            out.append((c, anchor))
    return out


def album_chosen_anchors(album, tier):
    """Chosen album sheets at this tier: protagonist first, then cast by name."""
    return db.q("""SELECT a.*, c.name AS character_name
                   FROM anchors a LEFT JOIN characters c ON c.id = a.character_id
                   WHERE a.scope_kind='album' AND a.scope_value=? AND a.tier=? AND a.chosen=1
                   ORDER BY (a.character_id IS NOT NULL), c.name, a.view, a.id""",
                album or "", tier)


def anchors_by_character(album, tier):
    """T2-26: chosen album anchors grouped per character (JSON-serializable)."""
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
            "url": _media_url(row["path"]),
        })
    return groups


def album_arc(album):
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


def check_direction(direction, tier=None):
    """Screen direction. Minor refs allowed only at g/pg13 (T10-18)."""
    direction = (direction or "").strip()
    if len(direction) > grok.MAX_DIRECTION:
        raise ValueError(
            f"the direction is {len(direction)} characters; keep it "
            f"under {grok.MAX_DIRECTION}. It is a brief, not a script.")
    tiers.check_text(direction, "storyboard direction", tier=tier)
    tiers.check_override(direction)
    return direction


def clamp_scene_seconds(scene_seconds):
    if scene_seconds is None or scene_seconds == "":
        scene_seconds = DEFAULT_SCENE_SECONDS
    try:
        scene_seconds = float(scene_seconds)
    except (TypeError, ValueError):
        raise ValueError("scene_seconds must be a finite number") from None
    if not math.isfinite(scene_seconds):
        raise ValueError("scene_seconds must be a finite number")
    return min(max(scene_seconds, SCENE_SECONDS_MIN), SCENE_SECONDS_MAX)


def load(row, normalized=True):
    with open(row["json_path"]) as f:
        sb = json.load(f)
    return build_song.normalize(sb) if normalized else sb


def foreign_tier_in_storyboard(sb, tier):
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


def scenes(song, sb, tier, anchored=(), scene_seconds=None):
    """Per-scene timing, prompts and reference frames. One clip_plan owner."""
    anchored = set(anchored)
    scene_list = sb.get("scenes") or []
    clip_secs = build_song.clip_seconds(scene_seconds)
    nclips = clip_count(song, scene_seconds)
    plan = build_song.clip_plan(scene_list, nclips=nclips) if (scene_list and nclips) else []

    by_clip = {}
    for r in db.q("SELECT * FROM refs WHERE song_id=? AND tier=? ORDER BY clip_idx, id",
                  song["id"], tier):
        by_clip.setdefault(r["clip_idx"], []).append(r)

    clips_of = {}
    shots_of = {}
    for ci, scene, shot in plan:
        clips_of.setdefault(scene["scene_number"], []).append(ci)
        shots_of.setdefault(scene["scene_number"], []).append(shot)

    rows = []
    for scene in scene_list:
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
                "stale": bool(edited and cands and
                              all((c["created"] or 0) < edited for c in cands)),
            })
        rows.append({
            "scene": scene, "num": num, "name": build_song.sname(scene),
            "clips": idxs,
            "start": idxs[0] * clip_secs if idxs else None,
            "end": (idxs[-1] + 1) * clip_secs if idxs else None,
            "length": len(idxs) * clip_secs,
            "guidance": build_song.guidance_seconds(scene),
            "shots": sorted(set(shots_of.get(num, []))),
            "refs": refs, "edited": edited,
            "cast": [_scene_figure(n, anchored)
                     for n in (scene.get("characters") or [])
                     if _figure_name(n)],
        })
    return rows, nclips


def scene_time_report(scene_time, song_length):
    scene_time = float(scene_time or 0.0)
    song_length = float(song_length or 0.0)
    allowed = song_length * SCENE_TIME_TOLERANCE
    return {
        "scene_time": scene_time,
        "song_length": song_length,
        "tolerance": SCENE_TIME_TOLERANCE,
        "mismatch": bool(song_length) and abs(scene_time - song_length) > allowed,
    }


def coverage(rows, nclips, duration, clip_secs=None):
    intent = sum(r["guidance"] for r in rows)
    rendered = nclips * build_song.clip_seconds(clip_secs)
    # T6-A4: fill_pct is service-owned. Template interpolates only.
    if rendered:
        fill_pct = min(100.0, (intent / rendered) * 100.0)
    else:
        fill_pct = 0.0
    return {
        "intent": intent, "rendered": rendered, "duration": duration or 0.0,
        "nclips": nclips, "scenes": len(rows),
        "ratio": (rendered / intent) if intent else 0.0,
        "ok": bool(intent) and 0.85 <= (rendered / intent) <= 1.15,
        "fill_pct": fill_pct,
    }


def _media_url(path):
    if not path:
        return None
    return "/media/" + quote(os.path.realpath(path), safe="/")


def _ref_candidate_json(row):
    path = row["path"]
    return {
        "id": row["id"],
        "path": path,
        "url": _media_url(path),
        "seed": row["seed"],
        "approved": bool(row["approved"]),
    }


def _scene_refs_json(r):
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
        "cast": r["cast"],
        "clips": r["clips"],
        "refs": _scene_refs_json(r),
    }


def payload(song_id, tier):
    song = require_song(song_id) if not hasattr(song_id, "keys") else song_id
    require_tier(tier)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", song["id"], tier)
    if not row:
        raise LookupError("no storyboard for this tier yet")
    try:
        sb = load(row)
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"storyboard file is unreadable: {e}") from None
    cast = cast_anchors(song["album"] or "", tier)
    sb_secs = row["scene_seconds"]
    rows, nclips = scenes(song, sb, tier, {c["name"] for c, _a in cast},
                          scene_seconds=sb_secs)
    cov = coverage(rows, nclips, song["duration"], sb_secs)
    report = scene_time_report(cov.get("intent"), cov.get("duration"))
    clip_secs = build_song.clip_seconds(sb_secs)
    # T2-30: extras/background do not warn — only unanchored leads.
    unanchored = sorted({n["name"] for r in rows for n in r["cast"]
                         if not n["anchored"] and n.get("role") == "lead"})
    # T6-A2: HTML /songs/{id}/storyboard/{tier} and GET /api/... report these
    # from this function. scene_count is not len(scenes) at the template.
    return {
        "song_id": song["id"],
        "tier": tier,
        "scenes": [_scene_json(r) for r in rows],
        "coverage": cov,
        "unanchored": unanchored,
        "scene_seconds": sb_secs,
        "nclips": nclips,
        "anchors": anchors_by_character(song["album"] or "", tier),
        "scene_time": report["scene_time"],
        "song_length": report["song_length"],
        "clip_seconds": clip_secs,
        "scene_count": cov["scenes"],
        "mismatch": report["mismatch"],
        "tolerance": report["tolerance"],
    }


def enqueue(song_id, tier, model=None, scene_seconds=None, direction=None):
    """Queue a storyboard generate. Escalation re-screens the work (T10-19)."""
    song = require_song(song_id)
    require_tier(tier)
    direction = check_direction(direction or "", tier)
    # T10-19: moving a work onto a non-locked tier re-screens everything it
    # already contains against that tier's rule, and names the blocker.
    # Covers T10-18b lyrics-at-xxx and prompt-field blocks for r/xxx.
    if not tiers.allows_minor_depiction(tier):
        tiers.screen_work_for_tier(song["id"], tier)
    scene_seconds = clamp_scene_seconds(scene_seconds)
    return jobs.enqueue("storyboard", {
        "song_id": song_id, "tier": tier,
        "model": (model or models.chat_default()) or None,
        "scene_seconds": scene_seconds, "direction": direction,
    }, song_id=song_id)


def edit_scene(song_id, tier, num, fields):
    song = require_song(song_id) if not hasattr(song_id, "keys") else song_id
    require_tier(tier)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?", song["id"], tier)
    if not row:
        raise LookupError("no storyboard for this tier yet")
    sb = load(row, normalized=False)
    scene = next((s for s in sb.get("scenes", []) if s.get("scene_number") == num), None)
    if scene is None:
        raise LookupError(f"no scene {num} in this storyboard")
    changed = False
    for field in EDITABLE_SCENE_FIELDS:
        if field not in fields:
            continue
        value = (fields.get(field) or "").strip()
        if len(value) > MAX_SCENE_FIELD:
            raise ValueError(
                f"{field} is {len(value)} characters; keep it under {MAX_SCENE_FIELD}")
        tiers.check_text(value, f"scene {num} {field}", tier=tier)
        if (scene.get(field) or "") != value:
            scene[field] = value
            changed = True
    foreign = foreign_tier_in_storyboard(sb, tier)
    if foreign:
        raise ValueError(
            f"storyboard carries {foreign} wording; this board is {tier}")
    if not str((sb.get("character_reference") or "")).strip():
        raise ValueError(grok.EMPTY_CHARACTER_REFERENCE)
    grok.require_figure_roles(sb)
    models.refuse_unknown_video_model(sb.get("scenes"))
    if changed:
        scene["edited"] = time.time()
        outdir = os.path.dirname(row["json_path"])
        grok.write_storyboard(sb, outdir, song["slug"], tier)
    return scene


def meter(song_id, tier):
    p = payload(song_id, tier)
    out = dict(p["coverage"])
    out["nclips"] = p["nclips"]
    out["scene_time"] = p["scene_time"]
    out["song_length"] = p["song_length"]
    out["tolerance"] = p["tolerance"]
    out["mismatch"] = p["mismatch"]
    out["clip_seconds"] = p["clip_seconds"]
    out["scene_count"] = p["scene_count"]
    return out


def cast(song_id, tier):
    p = payload(song_id, tier)
    return {"unanchored": p["unanchored"],
            "scenes": [{"num": s["num"], "cast": s["cast"]}
                       for s in p["scenes"]]}


def playlist_tracks(pid):
    return [dict(r) for r in db.q(
        """SELECT s.id, s.title, s.lyrics FROM playlist_items pi
           JOIN songs s ON s.id = pi.song_id
           WHERE pi.playlist_id=? ORDER BY pi.position""", pid)]


def load_arc(pid):
    row = db.one("SELECT * FROM arcs WHERE playlist_id=?", pid)
    if not row or not row["json_path"] or not os.path.isfile(row["json_path"]):
        return None
    try:
        with open(row["json_path"]) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def persist_arc(pl, data, model="", direction=""):
    songs = playlist_tracks(pl["id"])
    titles = {s["id"]: s["title"] for s in songs}
    outdir = os.path.join(db.DATA, "arcs", _safe_name(pl["name"]))
    json_path, md_path = arc.write(data, outdir, _safe_name(pl["name"]), titles)
    db.run("""INSERT INTO arcs (playlist_id, json_path, md_path, model, prompt, created)
              VALUES (?,?,?,?,?,?)
              ON CONFLICT(playlist_id) DO UPDATE SET json_path=excluded.json_path,
              md_path=excluded.md_path, model=excluded.model, prompt=excluded.prompt,
              created=excluded.created""",
           pl["id"], json_path, md_path, model, direction, time.time())
    return data


def _safe_name(name):
    keep = "".join(c if c.isalnum() or c in "-_." else "_" for c in (name or ""))
    return keep or "untitled"


def arc_get(pid):
    require_playlist(pid)
    return {"arc": load_arc(pid)}


def arc_propose(pid, direction="", backend=None, model=None):
    pl = require_playlist(pid)
    direction = arc.check_direction(direction or "")
    songs = playlist_tracks(pid)
    if not songs:
        raise ValueError("this album has no songs yet -- add some first")
    data, used = arc.generate(pl["name"], songs, direction=direction,
                              backend=backend or None,
                              model=model or None,
                              transitions=mixer.TRANSITIONS)
    summaries = [arc.for_song(data, s["id"]) for s in songs]
    return {"proposal": data, "summaries": summaries, "model": used}


def arc_accept(pid, raw):
    pl = require_playlist(pid)
    if not isinstance(raw, dict):
        raw = {}
    songs = playlist_tracks(pid)
    if not songs:
        raise ValueError("this album has no songs yet -- add some first")
    data = arc.validate(raw, [s["id"] for s in songs], mixer.TRANSITIONS)
    data["album"] = pl["name"]
    data["direction"] = raw.get("direction") or ""
    persist_arc(pl, data, model=raw.get("model") or "", direction=data["direction"])
    return {"arc": data}
