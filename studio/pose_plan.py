"""Map storyboard scenes to chosen pose sheets, then feed those as ref plates.

image1 stays the identity front (TRD-2 refs-identity). image2 is the bound
pose sheet: pose, not prompt, is what lands the body. A scene with no
confident match renders from text + front, same as before.

No FastAPI. Routes and tests call this directly (T6-A3).
"""
import json
import os
import re
import time

import db
import grok
import storyboard_service
import tiers

_STOP = {
    "the", "a", "an", "and", "or", "of", "on", "in", "at", "to", "her", "his",
    "she", "he", "with", "from", "for", "as", "is", "being", "one", "same",
    "wet", "black", "feline", "woman", "camera", "looking", "looks", "look",
    "this", "that", "into", "over", "her", "own", "still",
}

# Family tokens. A scene and a sheet must share at least one family to auto-bind.
_FAMILIES = {
    "allfours": (
        "all fours", "all-fours", "allfours", "hands and knees",
        "hands-and-knees", "doggy", "on all fours",
    ),
    "kneel": ("kneel", "kneeling", "on her knees", "on knees"),
    "stand": ("stand", "standing", "walk", "walking"),
    "cowgirl": ("cowgirl", "riding", "on top", "sits on", "sitting on"),
    "seated": ("seated", "sitting", "sit "),
    "supine": ("supine", "on her back", "on back", "lying on back", "laying on back"),
    "side": ("on side", "laying on side", "lying on side", "on her side"),
    "portrait": ("portrait", "close portrait", "face close", "afterglow", "cum on face"),
    "oral": ("oral", "blowjob", "mouth on", "in her mouth"),
    "spit": ("spit-roast", "spit roast", "spitroast", "both ends", "oral in front"),
    "bent": ("bent over", "bent at", "bent,"),
    "spread": ("spread", "spreading", "legs apart", "legs parted", "labia"),
    "rear": ("looking back", "look back", "over her shoulder", "over shoulder",
             "from behind", "rear", "3qtr-rear"),
    "crouch": ("crouch", "crouching", "squat"),
}

# Auto-bind only when the best sheet beats this. Token-only ties stay unbound.
_MIN_SCORE = 0.34


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _families(text):
    t = _norm(text)
    if not t:
        return set()
    padded = f" {t} "
    hit = set()
    for fam, words in _FAMILIES.items():
        if any(w in t or f" {w} " in padded for w in words):
            hit.add(fam)
    return hit


def _tokens(text):
    return {w for w in _norm(text).split() if w and w not in _STOP and len(w) > 2}


def need_text(scene):
    """What the scene asks the body to do. pose first; else story/camera/prompt."""
    bits = [
        scene.get("pose") or "",
        scene.get("story") or "",
        scene.get("camera") or "",
    ]
    prompt = scene.get("image_prompt") or ""
    if prompt:
        bits.append(prompt[:240])
    return " ".join(b for b in bits if b).strip()


def sheet_name(row):
    """Operator pose name, then the encoded view label."""
    meta = {}
    raw = row["render_json"] if "render_json" in row.keys() else None
    if raw:
        try:
            meta = json.loads(raw)
        except ValueError:
            pass
    name = " ".join(str(meta.get("pose_name") or "").split())
    if name:
        return name
    view = str(row["view"] or "")
    m = re.match(r"^pose_(\d+)(?:_nude)?$", view)
    if m:
        asset = db.one(
            "SELECT meta_json FROM assets WHERE id=? AND kind='anchor_ref'",
            int(m.group(1)))
        if asset:
            name = " ".join(str(db.jset(asset).get("pose_name") or "").split())
            if name:
                return name
        return f"pose {m.group(1)}" + (" nude" if view.endswith("_nude") else "")
    return view.replace("_", " ")


def is_nude_sheet(row):
    view = str(row["view"] or "")
    if view.endswith("_nude") or "nude" in view:
        return True
    return "nude" in sheet_name(row).lower()


def is_identity_front(row):
    return str(row["view"] or "") == "front"


def library(album, tier, character_id=None):
    """Chosen protagonist sheets at this album+tier, identity front last."""
    rows = db.q(
        """SELECT * FROM anchors
           WHERE scope_kind='album' AND scope_value=? AND tier=?
             AND chosen=1 AND character_id IS ?
           ORDER BY id""",
        album or "", tier, character_id)
    return list(rows)


def score_sheet(need, row, prefer_nude=None):
    """0..~1.5. Zero means do not auto-bind this sheet to this scene."""
    label = sheet_name(row)
    view = str(row["view"] or "")
    hay = f"{label} {view.replace('_', ' ')}"
    nf, sf = _families(need), _families(hay)
    if not nf:
        nt, st = _tokens(need), _tokens(hay)
        if not nt or not st:
            return 0.0
        overlap = nt & st
        if len(overlap) < 2:
            return 0.0
        return len(overlap) / len(nt | st)
    if not (nf & sf):
        return 0.0
    score = len(nf & sf) / len(nf | sf) + 0.12 * len(nf & sf)
    nt, st = _tokens(need), _tokens(hay)
    if nt and st:
        score += 0.08 * len(nt & st) / max(1, len(nt))
    if prefer_nude is True and is_nude_sheet(row):
        score += 0.08
    if prefer_nude is False and not is_nude_sheet(row):
        score += 0.08
    # identity front is the lock, not a pose plate, unless nothing else fits
    if is_identity_front(row):
        score *= 0.45
    return score


def match_sheet(need, sheets, prefer_nude=None):
    """Best sheet or None."""
    ranked = []
    for row in sheets:
        s = score_sheet(need, row, prefer_nude=prefer_nude)
        if s >= _MIN_SCORE:
            ranked.append((s, row["id"], row))
    if not ranked:
        return None, 0.0
    ranked.sort(key=lambda t: (-t[0], t[1]))
    return ranked[0][2], ranked[0][0]


def _scene_sheet_id(scene):
    raw = scene.get("pose_sheet_id")
    if raw in (None, "", 0, "0"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def plan(song, tier):
    """Per-scene bind + unique needed groups for one song+tier.

    saved pose_sheet_id wins. Otherwise auto-match. Does not write.
    """
    song = song if hasattr(song, "keys") else storyboard_service.require_song(song)
    storyboard_service.require_tier(tier)
    album = song["album"] or ""
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?",
                 song["id"], tier)
    if not row:
        raise LookupError(f"no storyboard for tier '{tier}'")
    sb = storyboard_service.load(row, normalized=False)
    sheets = library(album, tier)
    by_id = {s["id"]: s for s in sheets}
    prefer_nude = tiers.allows_nudity(tier)
    rows_out, groups = [], {}
    for scene in sb.get("scenes") or []:
        num = scene.get("scene_number")
        need = need_text(scene)
        saved = _scene_sheet_id(scene)
        sheet, score, source = None, 0.0, "none"
        if saved and saved in by_id:
            sheet, score, source = by_id[saved], 1.0, "saved"
        elif saved:
            source = "missing"
        else:
            sheet, score = match_sheet(need, sheets, prefer_nude=prefer_nude)
            if sheet:
                source = "auto"
        key = sheet["id"] if sheet else _norm(scene.get("pose") or need)[:48] or f"scene-{num}"
        groups.setdefault(key, {
            "key": key,
            "label": sheet_name(sheet) if sheet else (scene.get("pose") or need or "unspecified")[:80],
            "sheet_id": sheet["id"] if sheet else None,
            "path": sheet["path"] if sheet else None,
            "scenes": [],
            "source": source if source != "none" else "unbound",
        })
        groups[key]["scenes"].append(num)
        rows_out.append({
            "num": num,
            "name": scene.get("name") or f"scene {num}",
            "pose": (scene.get("pose") or "").strip(),
            "need": need,
            "sheet_id": sheet["id"] if sheet else None,
            "path": sheet["path"] if sheet else None,
            "label": sheet_name(sheet) if sheet else "",
            "score": round(score, 3),
            "source": source,
        })
    bound = sum(1 for r in rows_out if r["sheet_id"])
    return {
        "song_id": song["id"],
        "tier": tier,
        "album": album,
        "scenes": rows_out,
        "needed": list(groups.values()),
        "n_scenes": len(rows_out),
        "n_bound": bound,
        "n_unbound": len(rows_out) - bound,
        "n_sheets": len(sheets),
        "sheets": [{"id": s["id"], "label": sheet_name(s), "path": s["path"],
                    "view": s["view"], "nude": is_nude_sheet(s)}
                   for s in sheets],
    }


def scene_bases(song, tier):
    """{scene_number: local path} for bound scenes with a readable file."""
    out = {}
    for row in plan(song, tier)["scenes"]:
        if row["path"] and os.path.isfile(row["path"]):
            out[int(row["num"])] = row["path"]
    return out


def bind_scene(song_id, tier, num, sheet_id):
    """Write pose_sheet_id onto one scene. sheet_id 0/None clears."""
    song = storyboard_service.require_song(song_id)
    storyboard_service.require_tier(tier)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?",
                 song["id"], tier)
    if not row:
        raise LookupError("no storyboard for this tier yet")
    sb = storyboard_service.load(row, normalized=False)
    scene = next((s for s in sb.get("scenes", []) if s.get("scene_number") == num), None)
    if scene is None:
        raise LookupError(f"no scene {num} in this storyboard")
    want = None
    if sheet_id not in (None, "", 0, "0"):
        want = int(sheet_id)
        sheet = db.one(
            """SELECT * FROM anchors WHERE id=? AND scope_kind='album'
               AND scope_value=? AND tier=? AND chosen=1""",
            want, song["album"] or "", tier)
        if not sheet:
            raise ValueError(
                f"anchor {want} is not a chosen sheet for {song['album']!r} {tier}")
    if _scene_sheet_id(scene) == want:
        return scene
    if want is None:
        scene.pop("pose_sheet_id", None)
    else:
        scene["pose_sheet_id"] = want
    scene["edited"] = time.time()
    grok.write_storyboard(sb, os.path.dirname(row["json_path"]), song["slug"], tier)
    return scene


def album_coverage(album, tier):
    """D1 rollup: poses every song on this album needs at this tier.

    A coverage list, not a bind. have = a chosen sheet already matches.
    Missing means generate or assign that pose on /anchors, then pick it.
    """
    songs = db.q("SELECT * FROM songs WHERE album=? ORDER BY title", album or "")
    groups = {}
    for song in songs:
        if not db.one("SELECT id FROM storyboards WHERE song_id=? AND tier=?",
                      song["id"], tier):
            continue
        try:
            p = plan(song, tier)
        except (LookupError, OSError, ValueError, json.JSONDecodeError):
            continue
        for item in p["scenes"]:
            pose_line = (item.get("pose") or "").strip()
            if not pose_line and not item.get("sheet_id"):
                # Environment / no-pose scenes are not a library slot.
                continue
            key = (str(item["sheet_id"]) if item["sheet_id"]
                   else _norm(pose_line)[:64]
                   or f"scene-{song['id']}-{item['num']}")
            g = groups.get(key)
            if g is None:
                g = {
                    "key": key,
                    "label": (item.get("label") or item.get("pose")
                              or item.get("need") or "unspecified")[:80],
                    "sheet_id": item.get("sheet_id"),
                    "path": item.get("path"),
                    "source": item.get("source") or "unbound",
                    "songs": [],
                    "binds": [],
                    "n_scenes": 0,
                }
                groups[key] = g
            g["n_scenes"] += 1
            g["binds"].append({"song_id": song["id"], "num": item["num"]})
            if not any(s["id"] == song["id"] for s in g["songs"]):
                g["songs"].append({"id": song["id"], "title": song["title"]})
            if item.get("sheet_id") and not g.get("sheet_id"):
                g["sheet_id"] = item["sheet_id"]
                g["path"] = item["path"]
                g["source"] = item["source"]
    needed = sorted(groups.values(),
                    key=lambda r: (r["sheet_id"] is not None, r["label"].lower()))
    sheets = []
    for row in db.q(
            """SELECT * FROM anchors
               WHERE scope_kind='album' AND scope_value=? AND tier=?
                 AND character_id IS NULL
               ORDER BY chosen DESC, id""",
            album or "", tier):
        sheets.append({
            "id": row["id"], "label": sheet_name(row), "path": row["path"],
            "view": row["view"], "chosen": bool(row["chosen"]),
        })
    return {
        "album": album or "",
        "tier": tier,
        "needed": needed,
        "n_needed": len(needed),
        "n_have": sum(1 for r in needed if r["sheet_id"]),
        "n_missing": sum(1 for r in needed if not r["sheet_id"]),
        "sheets": sheets,
    }


def stamp_binds(tier, binds, sheet_id):
    """Write pose_sheet_id onto these scenes. Does not recompute coverage."""
    want = None if sheet_id in (None, "", 0, "0") else int(sheet_id)
    for b in binds or []:
        try:
            bind_scene(b["song_id"], tier, b["num"], want)
        except (LookupError, ValueError):
            continue


def freeze_auto_binds(song, tier):
    """Stamp auto-matches onto the board so generate/reroll stay stable.

    Returns {scene_number: path} including saved + newly stamped binds.
    """
    song = song if hasattr(song, "keys") else storyboard_service.require_song(song)
    p = plan(song, tier)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?",
                 song["id"], tier)
    sb = storyboard_service.load(row, normalized=False)
    by_num = {s.get("scene_number"): s for s in sb.get("scenes") or []}
    changed = False
    for item in p["scenes"]:
        if item["source"] != "auto" or not item["sheet_id"]:
            continue
        scene = by_num.get(item["num"])
        if scene is None or _scene_sheet_id(scene):
            continue
        scene["pose_sheet_id"] = item["sheet_id"]
        scene["edited"] = time.time()
        changed = True
    if changed:
        try:
            grok.write_storyboard(sb, os.path.dirname(row["json_path"]),
                                  song["slug"], tier)
        except ValueError:
            # A board that fails write guards still renders; binds live in
            # the job args for this generate.
            pass
    bases = {}
    for item in p["scenes"]:
        if item["path"] and os.path.isfile(item["path"]):
            bases[int(item["num"])] = item["path"]
    return bases
