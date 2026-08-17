#!/usr/bin/env python3
"""Sets as a service: create, items, payload, preview, render.

docs/TRD-6 T6-A3 / TRD-1 §10. This is the layer the web routes call and it
imports NOTHING from FastAPI, so every operation is reachable from a test,
a shell, or a mobile client written later against the same JSON. If a route
handler decides something, a mobile client cannot -- so nothing is decided
in a route handler.

    python3 sets_service.py      # self-check against a temporary database
"""
import json
import os
import tempfile
import time

import automation
import db
import jobs
import mixer
import qc_service
import tiers

AUDIENCES = ("easy", "normal", "advanced")
DEFAULT_MODE = "video"
DEFAULT_TRANSITION = "fade"
DEFAULT_SECS = 2.0
DEFAULT_CURVE = "linear"


def _json_row(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return {k: row[k] for k in row.keys()}


def get(sid):
    row = db.one("SELECT * FROM sets WHERE id=?", sid)
    if not row:
        raise LookupError("no such set")
    return row


def require_song(sid):
    song = db.one("SELECT * FROM songs WHERE id=?", sid)
    if not song:
        raise LookupError("no such song")
    return song


def require_playlist(pid):
    row = db.one("SELECT * FROM playlists WHERE id=?", pid)
    if not row:
        raise LookupError("no such playlist")
    return row


def require_tier(name):
    if not db.one("SELECT id FROM tiers WHERE name=?", name):
        raise ValueError(f"no such tier: {name}")
    return name


def audience(row):
    mode = row["mode_audience"] if "mode_audience" in row.keys() else None
    return mode if mode in AUDIENCES else "normal"


def hold_of(row):
    try:
        return float(row["hold"] or 0.0)
    except (KeyError, IndexError, TypeError):
        return 0.0


def is_card_row(row):
    try:
        return row["song_id"] is None
    except (KeyError, IndexError, TypeError):
        return False


def card_mix_item(row):
    return {"kind": mixer.CARD, "card": row["card_path"] or "",
            "duration": float(row["card_secs"] or 0.0),
            "transition": row["transition"] or "cut",
            "secs": row["secs"] or 0.0, "hold": hold_of(row),
            "in_secs": None, "out_secs": None,
            "beatmatch": False, "bpm": None, "beat_grid": [],
            "downbeat_offset": 0}


def beatmatch_fields(it, song):
    return {"beatmatch": bool(it["beatmatch"]),
            "bpm": song["bpm"],
            "beat_grid": json.loads(song["beat_grid_json"]) if song["beat_grid_json"] else [],
            "downbeat_offset": song["downbeat_offset"] or 0}


def brand_of(item_row, set_row):
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


def mix_items(set_id, overrides=None, extra_item=None):
    rows = db.q("""SELECT si.id, si.song_id, si.transition, si.secs, si.in_secs, si.out_secs,
                          si.beatmatch, si.card_path, si.card_secs, si.hold,
                          s.mp3_path, s.bpm, s.beat_grid_json, s.downbeat_offset
                   FROM set_items si LEFT JOIN songs s ON s.id = si.song_id
                   WHERE si.set_id=? ORDER BY si.position""", set_id)
    overrides = overrides or {}
    items = []
    for r in rows:
        row = dict(r)
        row.update(overrides.get(row["id"], {}))
        if is_card_row(row):
            items.append(card_mix_item(row))
        elif row["mp3_path"] and os.path.isfile(row["mp3_path"]):
            items.append({"audio": row["mp3_path"], "transition": row["transition"],
                          "secs": row["secs"], "in_secs": row["in_secs"],
                          "out_secs": row["out_secs"],
                          "hold": hold_of(row),
                          **beatmatch_fields(row, row)})
    if extra_item is not None:
        items.append(extra_item)
    return items


def duration(items):
    """mixer.set_duration or (None, error). One place for the number."""
    if not items:
        return 0.0, None
    try:
        return mixer.set_duration(items, key="audio"), None
    except ValueError as e:
        return None, str(e)


def refuse_if_unrenderable(items):
    if len(items) < 2:
        return
    try:
        mixer.set_duration(items, key="audio")
    except ValueError as e:
        raise ValueError(str(e)) from e


def item_rows(set_id):
    return db.q("""SELECT si.*, s.title AS song_title, s.mp3_path AS mp3_path,
                          s.bpm AS song_bpm, s.key AS song_key,
                          s.beat_grid_json AS song_beat_grid_json,
                          s.downbeat_offset AS song_downbeat_offset
                   FROM set_items si LEFT JOIN songs s ON s.id = si.song_id
                   WHERE si.set_id=? ORDER BY si.position""", set_id)


def render_row(a):
    meta = db.jset(a)
    missing = not (a["path"] and os.path.isfile(a["path"]))
    size = dur = None
    if not missing:
        size = os.path.getsize(a["path"])
        try:
            dur = mixer.probe(a["path"])["duration"]
        except Exception:
            pass
    return {"asset": a, "mode": meta.get("mode", "video"), "tier": meta.get("tier"),
            "missing": missing, "size": size, "duration": dur,
            "master_chain": meta.get("master_chain"),
            "loudness": meta.get("loudness")}


def renders(row):
    out = []
    for a in db.q("SELECT * FROM assets WHERE kind='set' ORDER BY id DESC"):
        meta = db.jset(a)
        if meta.get("set_id") != row["id"]:
            continue
        rec = render_row(a)
        out.append({
            "id": a["id"], "path": a["path"], "set_id": row["id"],
            "mode": rec["mode"], "tier": rec["tier"],
            "duration": rec["duration"], "missing": rec["missing"],
        })
    return out


def _item_block_duration(it):
    if is_card_row(it):
        return float(it["card_secs"] or 0.0)
    try:
        info = mixer.probe(it["mp3_path"]) if it["mp3_path"] else None
        if info:
            return mixer._item_duration(info, dict(it))
    except (OSError, RuntimeError, KeyError):
        pass
    return 0.0


def rounding_for(row, items, total):
    """T1-6: per-join delta and abs_delta_sum for the JSON payload."""
    blocks = [{"id": it["id"], "duration": _item_block_duration(it),
               "transition": it["transition"], "secs": it["secs"],
               "hold": hold_of(it)} for it in items]
    fps = mixer.DEFAULT_OUT_FPS
    try:
        stored_fps = row["out_fps"]
    except (KeyError, IndexError):
        stored_fps = None
    if stored_fps not in (None, ""):
        fps = float(stored_fps)
    return mixer.rounding_report(blocks, fps)


def peaks_envelope(it):
    """T1-13/T1-15 envelope for one set item. Empty always carries a reason."""
    if is_card_row(it):
        return {"pairs": [], "reason": "no_audio", "song_id": None, "n": 0}
    try:
        song_id = it["song_id"]
    except (KeyError, IndexError, TypeError):
        song_id = None
    try:
        path = it["mp3_path"]
    except (KeyError, IndexError, TypeError):
        path = None
    if song_id is None:
        return {"pairs": [], "reason": "no_audio", "song_id": None, "n": 0}
    env = mixer.peaks_from_path(path)
    return {"pairs": env["pairs"], "reason": env["reason"],
            "song_id": song_id, "n": len(env["pairs"])}


def timeline_peaks(items):
    """Per-item peaks envelopes in running order — the set editor's source."""
    return [{"id": it["id"], **peaks_envelope(it)} for it in items]


def _loudness_mix_items(row):
    """Audio items for the on-demand meter: same gain/automation/audience as render."""
    items = db.q("SELECT * FROM set_items WHERE set_id=? ORDER BY position", row["id"])
    if not items:
        return []
    mode = audience(row)
    build = []
    for it in items:
        if is_card_row(it):
            build.append({**card_mix_item(it),
                          "automation": automation.item_audio(it["id"]),
                          "mode_audience": mode})
            continue
        song = db.one("SELECT * FROM songs WHERE id=?", it["song_id"])
        if not song or not song["mp3_path"] or not os.path.isfile(song["mp3_path"]):
            continue
        build.append({
            "audio": song["mp3_path"],
            "transition": it["transition"], "secs": it["secs"],
            "in_secs": it["in_secs"], "out_secs": it["out_secs"],
            "hold": hold_of(it),
            "gain_db": it["gain_db"], "effects_json": it["effects_json"],
            "automation": automation.item_audio(it["id"]),
            "mode_audience": mode,
            **beatmatch_fields(it, song),
        })
    return build


def live_loudness(row):
    """On-demand loudness of the current mix via mixer.export_loudness.

    Mixes through mixer.mix_audio. Do not call this on every GET /sets/{id}
    or GET /api/sets/{id} — that remuxes the set on a page load. The
    endpoint is GET /api/sets/{id}/loudness.
    """
    items = _loudness_mix_items(row)
    if not items:
        return None
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    rec = None
    try:
        mixer.mix_audio(items, path)
        rec = mixer.export_loudness(path, items)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if not rec:
        return None
    target = rec.get("target_lufs")
    lufs = rec.get("lufs")
    if target and lufs is not None and target != 0:
        fill = min(100.0, abs(float(lufs) / float(target)) * 100.0)
    else:
        fill = 0.0
    rec = dict(rec)
    rec["fill_pct"] = fill
    rec["source"] = "live_mix"
    return rec


def payload(sid, with_peaks=True, with_meter=False):
    """JSON body for one set.

    with_peaks: timeline envelopes from mixer.peaks (cheap). HTML and
    GET /api/sets/{id} both report these (T6-A2).
    with_meter: remuxes the set. Default False. listed() never asks.
    """
    row = get(sid) if not hasattr(sid, "keys") else sid
    items = item_rows(row["id"])
    total, err = duration(mix_items(row["id"]))
    out = {
        "set": _json_row(row),
        "items": [_json_row(it) for it in items],
        "count": len(items),
        "total_secs": total,
        "renders": renders(row),
        "mode_audience": audience(row),
        "duration_error": err,
        "rounding": rounding_for(row, items, total),
    }
    if with_peaks:
        out["timeline"] = timeline_peaks(items)
    if with_meter:
        out["loudness"] = live_loudness(row)
    return out


def listed():
    rows = db.q("SELECT * FROM sets WHERE mode != ? ORDER BY updated DESC, id DESC",
                automation.SONG_EDITOR_MODE)
    return [payload(r, with_peaks=False, with_meter=False) for r in rows]


def create(name, mode=None, tier=None, playlist_id=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("name required")
    try:
        tiers.check_text(name, "set name")
        tiers.check_override(name)
    except ValueError:
        raise
    mode = (mode or "").strip() or DEFAULT_MODE
    if mode not in ("audio", "video"):
        raise ValueError("mode must be 'audio' or 'video'")
    tier = (tier or "").strip() or None
    if tier:
        require_tier(tier)
    if playlist_id is not None and playlist_id != "":
        playlist_id = int(playlist_id)
        require_playlist(playlist_id)
    else:
        playlist_id = None
    now = time.time()
    sid = db.run("""INSERT INTO sets (name, playlist_id, tier, mode, created, updated)
                    VALUES (?,?,?,?,?,?)""", name, playlist_id, tier, mode, now, now)
    if playlist_id is not None:
        pl_row = db.one("SELECT name FROM playlists WHERE id=?", playlist_id)
        by_song = {s["song_id"]: s.get("transition_out") or {}
                   for s in album_arc(pl_row["name"] if pl_row else "").get("songs") or []}
        for it in db.q("SELECT * FROM playlist_items WHERE playlist_id=? ORDER BY position",
                       playlist_id):
            t = by_song.get(it["song_id"]) or {}
            kind = t.get("kind") if t.get("kind") in mixer.TRANSITIONS else it["transition"]
            secs = t.get("secs") if t.get("kind") in mixer.TRANSITIONS else it["secs"]
            hold = float(t.get("hold") or 0.0) if kind == mixer.BLACK else 0.0
            db.run("""INSERT INTO set_items (set_id, song_id, position, transition, secs, hold)
                      VALUES (?,?,?,?,?,?)""", sid, it["song_id"], it["position"],
                   kind, float(secs or 0.0), hold)
    return sid


def add_item(set_id, song_id, transition=None, secs=None, beatmatch=None):
    row = get(set_id)
    if row["mode"] == automation.SONG_EDITOR_MODE:
        raise ValueError("the song editor is a one-item timeline")
    if song_id in (None, ""):
        raise ValueError("song_id required")
    song = require_song(int(song_id))
    transition = (transition or "").strip() or DEFAULT_TRANSITION
    if transition not in mixer.TRANSITIONS:
        raise ValueError(f"transition must be one of {', '.join(mixer.TRANSITIONS)}")
    if secs in (None, ""):
        secs = DEFAULT_SECS
    secs = float(secs)
    beatmatch = bool(beatmatch) and beatmatch not in (0, "0", "false", "False")
    extra = ({"audio": song["mp3_path"], "transition": transition, "secs": secs, "hold": 0.0,
              "in_secs": None, "out_secs": None, **beatmatch_fields({"beatmatch": beatmatch}, song)}
             if song["mp3_path"] and os.path.isfile(song["mp3_path"]) else None)
    refuse_if_unrenderable(mix_items(set_id, extra_item=extra))
    pos_row = db.one("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM set_items WHERE set_id=?",
                     set_id)
    iid = db.run("""INSERT INTO set_items (set_id, song_id, position, transition, secs, beatmatch)
              VALUES (?,?,?,?,?,?)""", set_id, int(song_id), pos_row["p"], transition, secs,
                 int(beatmatch))
    db.run("UPDATE sets SET updated=? WHERE id=?", time.time(), set_id)
    return iid


def render_items(row):
    items = db.q("SELECT * FROM set_items WHERE set_id=? ORDER BY position", row["id"])
    if not items:
        raise ValueError("this set has no items yet -- add one first")
    songs = {}
    for it in items:
        if it["song_id"] is not None:
            songs[it["song_id"]] = require_song(it["song_id"])

    build = []
    if row["mode"] == "audio":
        missing = [songs[it["song_id"]]["title"] for it in items
                   if it["song_id"] is not None and not songs[it["song_id"]]["mp3_path"]]
        if missing:
            raise ValueError(f"no audio for: {', '.join(missing)}")
        aud = audience(row)
        for it in items:
            if is_card_row(it):
                build.append({**card_mix_item(it),
                              "automation": automation.item_audio(it["id"]),
                              "mode_audience": aud})
                continue
            build.append({"audio": songs[it["song_id"]]["mp3_path"],
                          "transition": it["transition"],
                          "secs": it["secs"], "in_secs": it["in_secs"],
                          "out_secs": it["out_secs"],
                          "hold": hold_of(it),
                          "gain_db": it["gain_db"], "effects_json": it["effects_json"],
                          "automation": automation.item_audio(it["id"]),
                          "mode_audience": aud,
                          **beatmatch_fields(it, songs[it["song_id"]])})
    else:
        if not row["tier"]:
            raise ValueError("pick a tier before rendering video")
        aud = audience(row)
        missing = []
        for it in items:
            if is_card_row(it):
                build.append({**card_mix_item(it),
                              "automation": automation.item_audio(it["id"]),
                              "mode_audience": aud})
                continue
            r = db.one("""SELECT * FROM renders WHERE song_id=? AND tier=?
                         ORDER BY id DESC LIMIT 1""", it["song_id"], row["tier"])
            if not r:
                missing.append(songs[it["song_id"]]["title"])
            else:
                build.append({"video": r["path"], "transition": it["transition"],
                              "secs": it["secs"],
                              "in_secs": it["in_secs"], "out_secs": it["out_secs"],
                              "hold": hold_of(it), "brand_path": brand_of(it, row),
                              "gain_db": it["gain_db"], "effects_json": it["effects_json"],
                              "automation": automation.item_audio(it["id"]),
                              "mode_audience": aud,
                              **beatmatch_fields(it, songs[it["song_id"]])})
        if missing:
            raise ValueError(f"tier '{row['tier']}' has no video for: {', '.join(missing)}")
    return build


def enqueue_render(sid):
    row = get(sid)
    build = render_items(row)
    return jobs.enqueue("render_set", {"set_id": sid, "playlist_id": row["playlist_id"],
                                       "mode": row["mode"], "tier": row["tier"],
                                       "items": build})


def preview(sid):
    get(sid)
    items = [dict(r) for r in db.q(
        "SELECT id, effects_json FROM set_items WHERE set_id=? ORDER BY position", sid)]
    return mixer.preview_proxy(items)


def preview_render(sid, at=0.0, secs=None):
    row = get(sid)
    build = render_items(row)
    key = "audio" if row["mode"] == "audio" else "video"
    ext = "mp3" if key == "audio" else "mp4"
    outdir = os.path.join(db.DATA, "sets", str(sid))
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"preview.{ext}")
    return mixer.render_preview(build, out, at=at, secs=secs, key=key)


def save_automation(set_id, item_id, lane, points, curve=None):
    get(set_id)
    if not db.one("SELECT id FROM set_items WHERE id=? AND set_id=?", item_id, set_id):
        raise LookupError("no such item")
    if points is None:
        raise ValueError("points required")
    curve = curve or DEFAULT_CURVE
    stored = automation.save(item_id, lane, points, curve=curve)
    return {"lane": lane, "points": stored, "curve": curve}


def pick_render(sid, path):
    get(sid)
    group = qc_service.lineage_group("set_rerender", set_id=sid)
    return qc_service.select("set_rerender", group, path)


def discard(sid):
    """Delete the set document and its assembled takes. Songs stay."""
    row = get(sid)
    if row["mode"] == automation.SONG_EDITOR_MODE:
        raise LookupError("no such set")
    for it in db.q("SELECT id FROM set_items WHERE set_id=?", sid):
        db.delete_set_item(it["id"])
    assets = []
    for a in db.q("SELECT * FROM assets WHERE kind='set'"):
        if db.jset(a).get("set_id") == sid:
            assets.append(a)
            db.run("DELETE FROM assets WHERE id=?", a["id"])
    db.run("DELETE FROM sets WHERE id=?", sid)
    return assets
