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
import sqlite3
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
# needs_lip_sync (T2-55) sits beside camera: true → LTX then hop; false → LTX only.
EDITABLE_SCENE_FIELDS = (
    "name", "cue", "duration_guidance", "story",
    "camera", "video_model", "needs_lip_sync", "motion", "lighting",
    "location", "pose",
    "image_prompt", "video_motion_prompt", "negative_prompt",
)
BOOL_SCENE_FIELDS = ("needs_lip_sync",)
MAX_SCENE_FIELD = 4000


def _as_scene_bool(raw):
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
    return db.chosen_anchor(scope_kind, scope_value, tier, view, character_id)


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
    """Chosen sheets at this tier: album keepers plus the shared library."""
    return db.visible_chosen_anchors(album, tier)


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


def direction_from_board(sb):
    """Human brief from a storyboard JSON: concept + numbered scene beats.

    Used when the stored prompt is a filename pointer, so the direction box
    shows the board, not '… from foo.json'.
    """
    if not isinstance(sb, dict):
        return ""
    parts = []
    for key in ("concept", "version_definition"):
        text = (sb.get(key) or "").strip()
        if text:
            parts.append(text)
    scenes = sb.get("scenes") or []
    if scenes:
        lines = ["Scenes:"]
        for s in scenes:
            if not isinstance(s, dict):
                continue
            num = s.get("scene_number") or ""
            name = (s.get("name") or "").strip()
            story = (s.get("story") or "").strip()
            pose = (s.get("pose") or "").strip()
            camera = (s.get("camera") or "").strip()
            bit = f"{num}. {name}: {story}".strip()
            if pose:
                bit += f" Pose: {pose}."
            if camera:
                bit += f" Camera: {camera}."
            lines.append(bit)
        parts.append("\n".join(lines))
    text = "\n\n".join(p for p in parts if p).strip()
    if len(text) > grok.MAX_DIRECTION:
        text = text[: grok.MAX_DIRECTION - 1].rstrip() + "…"
    return text


def direction_from_board_path(path):
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path) as f:
            return direction_from_board(json.load(f))
    except (OSError, ValueError):
        return ""


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
    """Optional pacing pin. Empty/None means the storyboard chooses the count."""
    if scene_seconds is None or scene_seconds == "":
        return None
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


def stamp_ref_scenes(song, tier, sb=None, scene_seconds=None):
    """Backfill refs.scene_number from clip_chain_plan heads only.

    New stills stamp scene_number at insert. A NULL row whose clip_idx is a
    scene head is that scene's still. clip_plan is a different clip_idx
    space and must not assign a successor-part still to the next scene.
    """
    pending = db.q(
        "SELECT id, clip_idx, seed FROM refs WHERE song_id=? AND tier=? AND scene_number IS NULL",
        song["id"], tier)
    if not pending:
        return 0
    if sb is None:
        row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?",
                     song["id"], tier)
        if not row:
            return 0
        try:
            sb = load(row)
        except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError):
            return 0
    scene_list = (sb or {}).get("scenes") or []
    if not scene_list:
        return 0
    head_to_scene = {h: sn for sn, h in
                     build_song.scene_heads(scene_list, models.default_cli("video")).items()}
    n = 0
    for r in pending:
        seed = r["seed"]
        # Old clip_plan gens used 7000+ci; rerolls used 8000–11000. Those
        # clip_idx values are a different space. Do not hang them on a chain
        # head that happens to share the integer.
        if seed is not None and 7000 <= int(seed) < 17000:
            continue
        sn = head_to_scene.get(r["clip_idx"])
        if sn is None:
            continue
        db.run("UPDATE refs SET scene_number=? WHERE id=?", sn, r["id"])
        n += 1
    return n


def remap_legacy_refs(song, tier, video_model=None):
    """Move clip_plan-era stills onto clip_chain_plan heads.

    Old gens keyed refs by the 4.8s allocator (song 3: 0..49). Operator
    stills are one slot per scene. Every old clip that clip_plan assigned
    to a scene becomes a candidate on that scene's chain head.
    Rows that already have scene_number are left alone (T2-13b).
    """
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?",
                 song["id"], tier)
    if not row:
        return {"moved": 0, "stamped": 0, "skipped": 0}
    try:
        sb = load(row)
    except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError):
        return {"moved": 0, "stamped": 0, "skipped": 0}
    scenes = sb.get("scenes") or []
    nclips = clip_count(song, row["scene_seconds"])
    if not scenes or not nclips:
        return {"moved": 0, "stamped": 0, "skipped": 0}
    old_of = {}
    for ci, scene, _shot in build_song.clip_plan(scenes, nclips=nclips):
        old_of[ci] = scene.get("scene_number")
    heads = build_song.scene_heads(
        scenes, video_model or models.default_cli("video"))
    pending = db.q(
        """SELECT id, clip_idx, seed FROM refs
           WHERE song_id=? AND tier=? AND scene_number IS NULL""",
        song["id"], tier)
    moved = stamped = skipped = 0
    for r in pending:
        sn = old_of.get(r["clip_idx"])
        if sn is None or sn not in heads:
            skipped += 1
            continue
        head = heads[sn]
        try:
            db.run("UPDATE refs SET scene_number=?, clip_idx=? WHERE id=?",
                   sn, head, r["id"])
        except sqlite3.IntegrityError:
            db.run("UPDATE refs SET scene_number=? WHERE id=?", sn, r["id"])
            stamped += 1
            continue
        if head != r["clip_idx"]:
            moved += 1
        else:
            stamped += 1
    return {"moved": moved, "stamped": stamped, "skipped": skipped,
            "heads": dict(heads), "n_old": len(old_of)}


def scenes(song, sb, tier, anchored=(), scene_seconds=None):
    """Per-scene timing, one still slot, and the video-chain length.

    Timing and clip_idx come from clip_chain_plan (T2-10 / T2-11). Operator
    stills are one per scene. Chain parts after the head are not tiles.
    """
    anchored = set(anchored)
    scene_list = sb.get("scenes") or []
    default_model = models.default_cli("video")
    plan = build_song.clip_chain_plan(scene_list, default_model) if scene_list else []
    nclips = len(plan)

    stamp_ref_scenes(song, tier, sb, scene_seconds)

    by_scene = {}
    by_clip = {}
    for r in db.q("SELECT * FROM refs WHERE song_id=? AND tier=? ORDER BY clip_idx, id",
                  song["id"], tier):
        by_clip.setdefault(r["clip_idx"], []).append(r)
        sn = r["scene_number"]
        if sn is not None:
            by_scene.setdefault(sn, []).append(r)

    videos_of = {}
    for v in db.q(
            """SELECT clip_idx, path, status, qc_json FROM clips
               WHERE song_id=? AND tier=? ORDER BY clip_idx""",
            song["id"], tier):
        if v["path"]:
            videos_of[v["clip_idx"]] = v

    parts_of = {}
    shots_of = {}
    for rec in plan:
        sn = rec.get("scene_number")
        parts_of.setdefault(sn, []).append(rec)
        scene = next((s for s in scene_list if s.get("scene_number") == sn), None)
        if scene is not None:
            shots_of.setdefault(sn, []).append(
                build_song.shot_directive(scene, rec["clip_idx"]))

    rows = []
    for scene in scene_list:
        num = scene.get("scene_number")
        recs = parts_of.get(num, [])
        head = recs[0]["clip_idx"] if recs else None
        start = recs[0]["start_s"] if recs else None
        end = recs[-1]["end_s"] if recs else None
        length = (end - start) if start is not None and end is not None else 0.0
        edited = float(scene.get("edited") or 0)
        cands = list(by_scene.get(num, []))
        if not cands and head is not None:
            for row in by_clip.get(head, []):
                seed = row["seed"]
                if seed is not None and 7000 <= int(seed) < 17000:
                    continue
                if row["scene_number"] is None or row["scene_number"] == num:
                    cands.append(row)
        refs = []
        if head is not None or cands:
            refs.append({
                "idx": head,
                "candidates": cands,
                "approved": any(c["approved"] for c in cands),
                "stale": bool(edited and cands and
                              all((c["created"] or 0) < edited for c in cands)),
            })
        videos = []
        for rec in recs:
            raw = videos_of.get(rec["clip_idx"])
            if not raw:
                continue
            v = dict(raw)
            v["scene_num"] = num
            v["motion"] = scene.get("video_motion_prompt") or ""
            videos.append(v)
        pending, failed = _clip_job_cards(
            song["id"], tier, num, recs, videos,
            dismissed=scene.get("dismissed_clip_jobs"))
        rows.append({
            "scene": scene, "num": num, "name": build_song.sname(scene),
            "clips": [head] if head is not None else [],
            "videos": videos,
            "clip_pending": pending,
            "clip_failed": failed,
            "n_parts": len(recs) or 1,
            "start": start, "end": end, "length": length,
            "guidance": build_song.guidance_seconds(scene),
            "shots": sorted(set(shots_of.get(num, []))),
            "refs": refs, "edited": edited,
            "cast": [_scene_figure(n, anchored)
                     for n in (scene.get("characters") or [])
                     if _figure_name(n)],
        })
    return rows, nclips


def _job_err_line(err):
    lines = [ln.strip() for ln in str(err or "").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _clip_job_cards(song_id, tier, scene_num, recs, videos, dismissed=None):
    """Queued/running/failed clip jobs for this scene. Jobs table is the state.

    The sticky chip is the latest job of any kind, so a QC row hides a clip
    render. The scene strip reads jobs itself.
    """
    skip = {int(x) for x in (dismissed or []) if str(x).lstrip("-").isdigit()}
    idxs = {int(r["clip_idx"]) for r in recs}
    have = {int(v["clip_idx"]) for v in videos}
    pending, failed = [], []
    seen = set()
    for j in db.q(
            """SELECT id, status, error, args_json FROM jobs
               WHERE song_id=? AND kind='clips'
                 AND status IN ('queued','running','cancelling','failed')
               ORDER BY id DESC""",
            song_id):
        try:
            args = json.loads(j["args_json"] or "{}")
        except (TypeError, ValueError):
            args = {}
        if str(args.get("tier") or "") != str(tier):
            continue
        sn = args.get("scene_number")
        if sn is None:
            sn = args.get("scene")
        ci = args.get("clip_idx")
        if sn is None and ci is not None:
            try:
                if int(ci) in idxs:
                    sn = scene_num
            except (TypeError, ValueError):
                pass
        try:
            if sn is None or int(sn) != int(scene_num):
                continue
        except (TypeError, ValueError):
            continue
        if int(j["id"]) in skip:
            continue
        key = int(ci) if ci is not None else "scene"
        if key in seen:
            continue
        seen.add(key)
        card = {
            "id": j["id"],
            "status": j["status"],
            "error": _job_err_line(j["error"]),
            "clip_idx": ci,
            "n": max(1, int(args.get("n") or 1)),
        }
        if j["status"] == "failed":
            if ci is None or int(ci) not in have:
                failed.append(card)
        else:
            pending.append(card)
    return pending, failed


PROMPT_FIELDS = (
    "story", "image_prompt", "negative_prompt", "video_motion_prompt", "pose")
PROMPT_HINTS = {
    "story": "What happens in this shot — action, not camera gear.",
    "image_prompt": "The still: who, pose, place, light. Self-contained; the image model sees only this.",
    "negative_prompt": "Stills and clips share this box. Sent as the image negative and the video negative.",
    "video_motion_prompt": "What the clip does over time: body motion, camera move, lips.",
    "pose": "The scene's pose word. The matcher uses this to suggest a plate.",
}


def _open_scene(song_id, tier, num):
    song = require_song(song_id)
    require_tier(tier)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?",
                 song["id"], tier)
    if not row:
        raise LookupError("no storyboard for this tier yet")
    sb = load(row, normalized=False)
    scene = next((s for s in sb.get("scenes") or []
                  if s.get("scene_number") == num), None)
    if scene is None:
        raise LookupError(f"no scene {num} in this storyboard")
    return song, row, sb, scene


def _commit_scene(song, row, sb):
    grok.write_storyboard(sb, os.path.dirname(row["json_path"]),
                          song["slug"], tier=row["tier"])


def delete_clip(song_id, tier, clip_idx):
    """Remove one landed take. File goes if nothing else points at the path."""
    song_id = int(song_id)
    clip_idx = int(clip_idx)
    row = db.one(
        "SELECT * FROM clips WHERE song_id=? AND tier=? AND clip_idx=?",
        song_id, tier, clip_idx)
    if not row:
        raise LookupError(f"no clip {clip_idx} at {tier}")
    path = row["path"]
    db.run("DELETE FROM clips WHERE id=?", row["id"])
    if path and os.path.isfile(path):
        still = db.one("SELECT id FROM clips WHERE path=?", path)
        render = db.one("SELECT id FROM renders WHERE path=?", path)
        if still is None and render is None:
            os.remove(path)
    return {"ok": True, "deleted": clip_idx, "path": path}


def dismiss_clip_job(song_id, tier, num, job_id):
    song, row, sb, scene = _open_scene(song_id, tier, num)
    jid = int(job_id)
    ids = [int(x) for x in (scene.get("dismissed_clip_jobs") or [])
           if str(x).lstrip("-").isdigit()]
    if jid not in ids:
        ids.append(jid)
        scene["dismissed_clip_jobs"] = ids
        scene["edited"] = time.time()
        _commit_scene(song, row, sb)
    return {"ok": True, "dismissed": jid}


def save_field_version(song_id, tier, num, field, text, label=""):
    if field not in PROMPT_FIELDS:
        raise ValueError(f"unknown prompt field {field!r}")
    song, row, sb, scene = _open_scene(song_id, tier, num)
    text = (text or "").strip()
    if not text:
        raise ValueError("nothing to version")
    if len(text) > MAX_SCENE_FIELD:
        raise ValueError(f"{field} is {len(text)} characters; keep it under {MAX_SCENE_FIELD}")
    tiers.check_text(text, f"scene {num} {field}", tier=tier)
    bag = dict(scene.get("field_versions") or {})
    vers = list(bag.get(field) or [])
    n = (max((int(v.get("n") or 0) for v in vers), default=0) + 1)
    vers.append({
        "n": n,
        "label": (label or "").strip() or f"v{n}",
        "text": text,
        "created": time.time(),
    })
    bag[field] = vers[-12:]
    scene["field_versions"] = bag
    scene[field] = text
    current = dict(scene.get("field_current") or {})
    current[field] = n
    scene["field_current"] = current
    scene["edited"] = time.time()
    _commit_scene(song, row, sb)
    return {"ok": True, "field": field, "versions": bag[field], "n": n,
            "text": text}


def apply_field_version(song_id, tier, num, field, n):
    """Make a named version the live field so a refresh loads it."""
    if field not in PROMPT_FIELDS:
        raise ValueError(f"unknown prompt field {field!r}")
    song, row, sb, scene = _open_scene(song_id, tier, num)
    vers = list(((scene.get("field_versions") or {}).get(field)) or [])
    try:
        want = int(n)
    except (TypeError, ValueError) as e:
        raise ValueError("a version number is needed") from e
    hit = next((v for v in vers if int(v.get("n") or 0) == want), None)
    if not hit:
        raise LookupError(f"no {field} version {want}")
    text = str(hit.get("text") or "")
    scene[field] = text
    current = dict(scene.get("field_current") or {})
    current[field] = want
    scene["field_current"] = current
    scene["edited"] = time.time()
    _commit_scene(song, row, sb)
    return {"ok": True, "field": field, "n": want, "text": text,
            "versions": vers}


def _draft_fallback(scene, field):
    if field == "video_motion_prompt":
        bits = [str(scene.get("motion") or "").strip(),
                str(scene.get("camera") or "").strip()]
        return "; ".join(b for b in bits if b) or "holds the asked pose"
    if field == "story":
        return (scene.get("story") or scene.get("name") or "").strip()
    if field == "negative_prompt":
        return "blurry, watermark, extra limbs, child, teen, underage"
    if field == "image_prompt":
        parts = [scene.get("story"), scene.get("pose"),
                 scene.get("location"), scene.get("lighting")]
        return ". ".join(str(p).strip() for p in parts if p and str(p).strip())
    return ""


def draft_scene_field(song_id, tier, num, field):
    if field not in PROMPT_FIELDS:
        raise ValueError(f"unknown prompt field {field!r}")
    song, _row, _sb, scene = _open_scene(song_id, tier, num)
    ctx = {k: scene.get(k) for k in (
        "name", "story", "pose", "camera", "motion", "lighting", "location",
        "image_prompt", "video_motion_prompt", "negative_prompt",
        "characters", "duration_guidance")}
    ctx["song"] = song["title"]
    ctx["album"] = song["album"]
    ctx["tier"] = tier
    text = ""
    try:
        import vision
        raw, _model = vision.ask_text(
            "Return JSON {\"text\": \"...\"} only. Adult music-video scene. "
            "Write the requested field. Use the other fields as context. "
            "Do not invent a different character.",
            json.dumps({"field": field, "hint": PROMPT_HINTS[field],
                        "scene": ctx}, ensure_ascii=False))
        data = json.loads(raw) if raw else {}
        text = str((data or {}).get("text") or "").strip()
    except (RuntimeError, ValueError, TypeError, json.JSONDecodeError):
        text = _draft_fallback(scene, field)
    if not text:
        raise ValueError("draft came back empty")
    if len(text) > MAX_SCENE_FIELD:
        text = text[:MAX_SCENE_FIELD]
    tiers.check_text(text, f"scene {num} {field}", tier=tier)
    return {"ok": True, "field": field, "text": text}


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
    rendered = sum((r.get("length") or 0) for r in rows)
    if not rendered:
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
        "needs_lip_sync": bool(scene.get("needs_lip_sync")),
        "cast": r["cast"],
        "clips": r["clips"],
        "n_parts": r.get("n_parts", 1),
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
    album = song["album"] or ""
    album_leads = []
    for c in album_cast(album):
        front = chosen_anchor("album", album, tier, "front", c["id"])
        album_leads.append({
            "id": c["id"],
            "name": c["name"],
            "role": c["role"] or "",
            "has_front": bool(front and front["path"]),
            "used": any(n["name"].lower() == c["name"].lower()
                        for r in rows for n in r["cast"]
                        if n.get("role") == "lead"),
        })
    return {
        "song_id": song["id"],
        "tier": tier,
        "scenes": [_scene_json(r) for r in rows],
        "coverage": cov,
        "unanchored": unanchored,
        "album_leads": album_leads,
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
        if field in BOOL_SCENE_FIELDS:
            value = _as_scene_bool(fields.get(field))
            if bool(scene.get(field)) != value:
                scene[field] = value
                changed = True
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


def analyze_poses(song_id, tier):
    """T2-50: write (pose, view, wardrobe, exposure) per scene. No bind."""
    import pose_coverage
    return pose_coverage.analyze(song_id, tier)


def pose_coverage_list(song_id, tier):
    """Stored T2-50 coverage for this song+tier. Empty before analyze."""
    import pose_coverage
    return pose_coverage.listed(song_id, tier)


def pose_gap(song_id, character_id=None):
    """T4-23: ceiling-board needs vs classification keepers. Holes only."""
    import pose_coverage
    return pose_coverage.gap(song_id, character_id=character_id)


def generate_poses(song_id, run_tiers, character_id=None, images=None):
    """T4-24: ceiling-tier pose generate from pose-gap holes."""
    import pose_generate
    return pose_generate.generate(
        song_id, run_tiers, character_id=character_id, images=images)


def backfill(song_id, run_tiers):
    """T2-54: ceiling + ticked-lower boards from the ceiling board."""
    import storyboard_backfill
    return storyboard_backfill.backfill(song_id, run_tiers)


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
