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
import make_anchor
import storyboard_service
import tiers

_LOOK_KEYS = (
    "identity", "wardrobe", "body", "nude_wardrobe", "anatomy",
    "backdrop", "composite",
)

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
    "spit": ("spit-roast", "spit roast", "spitroast", "split roast", "split-roast",
             "both ends", "oral in front"),
    "bent": ("bent over", "bent at", "bent,"),
    "spread": ("spread", "spreading", "legs apart", "legs parted", "labia"),
    "rear": ("looking back", "look back", "over her shoulder", "over shoulder",
             "from behind", "rear", "3qtr-rear"),
    "crouch": ("crouch", "crouching", "squat"),
}

# Auto-bind only when the best sheet beats this. Token-only ties stay unbound.
_MIN_SCORE = 0.34

# Stance that is not a solo still — Mage needs a ref for each body.
_PARTNERED = frozenset({
    "cowgirl", "oral", "spit", "supine", "allfours", "bent", "side",
    "kneel",
})

# Always more than one body, even when the operator never stamped actors.
# allfours / oral / side can be solo — those only become ensemble when
# another character's name is on the sheet.
_ENSEMBLE_FAMILIES = frozenset({"cowgirl", "spit"})


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


# Still-frame body for a pose *name*. "all fours then spring" is a slot
# label; without this, Mage paints a standing character sheet.
_STANCE = {
    "allfours": "on hands and knees, back arched or level, tail aside",
    "crouch": "crouching low, weight forward",
    "cowgirl": "straddling, seated on top facing forward",
    "kneel": "kneeling",
    "seated": "sitting",
    "supine": "lying on the back",
    "side": "lying on one side",
    "bent": "bent over at the hips",
    "spread": "legs apart so the pose reads",
    "oral": "this figure only, mouth-forward",
    "rear": "looking back over the shoulder",
}


def stance_clause(pose):
    """Body still for this pose name. Not the scene story."""
    pose = " ".join(str(pose or "").split())
    if not pose:
        return ""
    fams = _families(pose)
    hints = [_STANCE[k] for k in (
        "allfours", "crouch", "cowgirl", "kneel", "seated", "supine",
        "side", "bent", "spread", "oral", "rear",
    ) if k in fams]
    low = pose.lower()
    if "spring" in low:
        hints.append("coiled to spring forward")
    standing_only = fams <= {"stand"} or fams <= {"stand", "rear"}
    if hints and not standing_only:
        return f"{pose}: {'; '.join(hints)}; not standing upright"
    if hints:
        return f"{pose}: {'; '.join(hints)}"
    if "stand" not in fams:
        return f"{pose}, full-body still of that pose, not a standing idle"
    return pose


def _look_fields(album, character_id=None):
    """Identity/wardrobe/body for one album person. No FastAPI."""
    out = {}
    row = db.one(
        "SELECT * FROM playlists WHERE name=? AND kind='playlist'", album or "")
    if row:
        for key in _LOOK_KEYS:
            if key in row.keys() and row[key]:
                out[key] = row[key]
    if character_id:
        char = db.one("SELECT * FROM characters WHERE id=?", character_id)
        if char:
            for key in _LOOK_KEYS:
                if key in char.keys() and char[key]:
                    out[key] = char[key]
    return out


def sheet_prompt(album, pose, character_id=None, tier=""):
    """Grey-studio character sheet. Stance first. Not a scene render."""
    pose = " ".join(str(pose or "").split())
    if not pose:
        return ""
    stance = stance_clause(pose)
    fields = _look_fields(album, character_id)
    fields["pose"] = stance
    slug = re.sub(r"[^a-z0-9]+", "_", pose.lower()).strip("_") or "pose"
    nude = bool(tier) and tiers.allows_nudity(tier)
    view = f"pose_{slug}_nude" if nude else f"pose_{slug}"
    a = make_anchor.anchor_from(fields)
    wardrobe = a.get("nude_wardrobe") if nude else a["wardrobe"]
    parts = [
        stance + ".",
        ("Nude " if nude else "") +
        "character reference sheet of a single adult character, "
        "one figure, full body, head to toe inside the frame.",
        wardrobe,
        a["body"],
        a["identity"],
    ]
    if nude and a.get("anatomy"):
        parts.insert(4, a["anatomy"])
    parts.append(make_anchor.backdrop_for(view, a.get("backdrop")))
    return " ".join(p.strip() for p in parts if p and str(p).strip())


def mage_text(scene, album="", character_id=None, tier=""):
    """Paste for Mage: one figure, grey studio, asked pose. Not the scene still."""
    pose = " ".join(str(scene.get("pose") or "").split())
    return sheet_prompt(album, pose, character_id, tier)


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


def _row_get(row, key, default=None):
    if row is None:
        return default
    if hasattr(row, "keys") and key in row.keys():
        return row[key]
    if isinstance(row, dict):
        return row.get(key, default)
    return default


def actor_names(row, album=""):
    """Who is on this sheet. Stamped actors first; else names in the pose label."""
    raw = _row_get(row, "render_json")
    meta = {}
    if raw:
        try:
            meta = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (TypeError, ValueError):
            meta = {}
    names = []
    seen = set()
    for a in meta.get("actors") or []:
        if isinstance(a, dict):
            n = " ".join(str(a.get("name") or "").split())
        else:
            n = " ".join(str(a or "").split())
        key = n.lower()
        if not n or key in seen:
            continue
        seen.add(key)
        names.append(n)
    if len(names) >= 2:
        return names
    hay = _norm(f"{sheet_name(row)} {_row_get(row, 'view') or ''}")
    if album and hay:
        candidates = [lead_name(album)]
        for c in db.q("SELECT name FROM characters WHERE scope_value=? ORDER BY name",
                      album):
            candidates.append(c["name"])
        for n in candidates:
            n = " ".join(str(n or "").split())
            key = n.lower()
            if not n or key in seen:
                continue
            if _norm(n) and _norm(n) in hay:
                seen.add(key)
                names.append(n)
    return names


def is_ensemble(row, album="", owner_name=""):
    """True when this plate is more than one character.

    Split-roast / cowgirl are ensemble even without stamps. A solo all-fours
    stays on the owner's tab unless another cast name is on the label.
    """
    names = actor_names(row, album)
    if len(names) >= 2:
        return True
    if _families(sheet_name(row)) & _ENSEMBLE_FAMILIES:
        return True
    owner = (owner_name or "").strip().lower()
    return any(n.lower() != owner for n in names if n)


def is_nude_sheet(row):
    view = str(row["view"] or "")
    if view.endswith("_nude") or "nude" in view:
        return True
    return "nude" in sheet_name(row).lower()


def is_identity_front(row):
    return str(row["view"] or "") == "front"


def _lead_name_key(album):
    return f"lead_name:{album or ''}"


def lead_name(album):
    """Operator name for the album lead. Not the word protagonist."""
    row = db.one("SELECT value FROM settings WHERE key=?", _lead_name_key(album))
    if row:
        name = " ".join(str(row["value"] or "").split())
        if name:
            return name[:40]
    prow = db.one(
        "SELECT style_text FROM playlists WHERE name=? AND kind='playlist'",
        album or "")
    st = " ".join(str((prow["style_text"] if prow else "") or "").split())
    for sep in (" — ", " – ", " - ", ":"):
        if sep in st:
            name = st.split(sep, 1)[0].strip()
            if name and len(name) <= 40:
                return name
    return "Lead"


def set_lead_name(album, name):
    """Remember the album lead's tab name. Empty clears to the fallback."""
    name = " ".join(str(name or "").split())[:40]
    key = _lead_name_key(album)
    if not name:
        db.run("DELETE FROM settings WHERE key=?", key)
        return ""
    db.run("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", key, name)
    return name


def _album_lead_name(album):
    """Tab label for the album lead. Same as app.lead_display_name."""
    return lead_name(album)


def _album_leads(album):
    """Protagonist (id None) then named leads. Extras do not get a plate."""
    out = [{"id": None, "name": _album_lead_name(album)}]
    seen = {out[0]["name"].lower()}
    for c in db.q(
            "SELECT id, name, figure_role FROM characters WHERE scope_value=? ORDER BY name",
            album or ""):
        role = ""
        if "figure_role" in c.keys() and c["figure_role"]:
            role = c["figure_role"]
        if role and role != "lead":
            continue
        name = (c["name"] or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append({"id": c["id"], "name": name})
    return out


def _figure_name(entry):
    if isinstance(entry, dict):
        return str(entry.get("name") or "").strip()
    return str(entry or "").strip()


def _figure_role(entry):
    if isinstance(entry, dict):
        return str(entry.get("role") or "").strip().lower() or "lead"
    return "lead"


def scene_leads(scene, people):
    """Leads on this scene who need a pose plate. Empty cast → album lead."""
    by_key = {p["name"].lower(): p for p in people}
    found, seen = [], set()
    for raw in (scene or {}).get("characters") or []:
        name = _figure_name(raw)
        if not name:
            continue
        if _figure_role(raw) not in ("", "lead"):
            continue
        person = by_key.get(name.lower())
        if person is None:
            continue
        key = person["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(person)
    return found or list(people[:1])


def scene_actors(scene, people, pose=None):
    """Named bodies Mage needs refs for. Partnered stance adds the album lead."""
    leads = scene_leads(scene, people)
    pose = pose if pose is not None else (scene or {}).get("pose") or ""
    if not people:
        return leads
    partnered = bool(_families(pose) & _PARTNERED)
    if not partnered:
        return leads
    lead0 = people[0]
    if any(p.get("id") == lead0.get("id") for p in leads):
        return leads
    return [lead0] + list(leads)


def _sheet_pool(sheets, people):
    """Sheets this bind may use. Lead id is None (album protagonist)."""
    ids = {p.get("id") for p in people}
    return [s for s in sheets if s["character_id"] in ids]


def _append_people(dst, extra):
    seen = {(p.get("id"), (p.get("name") or "").lower()) for p in dst}
    for p in extra or []:
        key = (p.get("id"), (p.get("name") or "").lower())
        if key in seen:
            continue
        seen.add(key)
        dst.append(p)


def _who_key(who):
    parts = []
    for p in who or []:
        parts.append("lead" if p.get("id") is None else str(p["id"]))
    return "+".join(parts) or "lead"


def _who_label(who):
    return " · ".join(p["name"] for p in (who or []) if p.get("name")) or "Lead"


def library(album, tier, character_id=None):
    """Chosen protagonist sheets at this album+tier, identity front last."""
    if character_id is None:
        rows = db.q(
            f"""SELECT * FROM anchors
                WHERE {db.visible_anchor_sql()} AND tier=?
                  AND chosen=1 AND character_id IS NULL
                ORDER BY id""",
            album or "", tier)
    else:
        rows = db.q(
            f"""SELECT a.* FROM anchors a
                LEFT JOIN characters c ON c.id = a.character_id
                WHERE {db.visible_anchor_sql('a')} AND a.tier=?
                  AND a.chosen=1
                  AND (a.character_id=? OR (a.scope_kind='shared'
                       AND c.name=(SELECT name FROM characters WHERE id=?)))
                ORDER BY a.id""",
            album or "", tier, character_id, character_id)
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
    people = _album_leads(album)
    sheets = db.q(
        f"""SELECT * FROM anchors
            WHERE {db.visible_anchor_sql()} AND tier=? AND chosen=1
            ORDER BY id""",
        album or "", tier)
    by_id = {s["id"]: s for s in sheets}
    prefer_nude = tiers.allows_nudity(tier)
    rows_out, groups = [], {}
    for scene in sb.get("scenes") or []:
        num = scene.get("scene_number")
        need = need_text(scene)
        who = scene_leads(scene, people)
        actors = scene_actors(scene, people, scene.get("pose") or "")
        saved = _scene_sheet_id(scene)
        sheet, score, source = None, 0.0, "none"
        if saved and saved in by_id:
            sheet, score, source = by_id[saved], 1.0, "saved"
        elif saved:
            source = "missing"
        else:
            pool = _sheet_pool(sheets, actors)
            sheet, score = match_sheet(need, pool, prefer_nude=prefer_nude)
            if sheet:
                source = "auto"
        pose_key = sheet["id"] if sheet else _norm(scene.get("pose") or need)[:48] or f"scene-{num}"
        key = f"{_who_key(who)}|{pose_key}"
        groups.setdefault(key, {
            "key": key,
            "label": sheet_name(sheet) if sheet else (scene.get("pose") or need or "unspecified")[:80],
            "sheet_id": sheet["id"] if sheet else None,
            "path": sheet["path"] if sheet else None,
            "scenes": [],
            "source": source if source != "none" else "unbound",
            "characters": who,
            "character_label": _who_label(who),
            "actors": list(actors),
            "actor_label": _who_label(actors),
        })
        groups[key]["scenes"].append(num)
        _append_people(groups[key]["actors"], actors)
        groups[key]["actor_label"] = _who_label(groups[key]["actors"])
        rows_out.append({
            "num": num,
            "name": scene.get("name") or f"scene {num}",
            "pose": (scene.get("pose") or "").strip(),
            "need": need,
            "mage": mage_text(scene, album=album,
                              character_id=(who[0].get("id") if who else None),
                              tier=tier),
            "sheet_id": sheet["id"] if sheet else None,
            "path": sheet["path"] if sheet else None,
            "label": sheet_name(sheet) if sheet else "",
            "score": round(score, 3),
            "source": source,
            "characters": who,
            "character_label": _who_label(who),
            "actors": actors,
            "actor_label": _who_label(actors),
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
        sheet = db.visible_anchor_by_id(want, song["album"] or "", tier)
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
    people = _album_leads(album)
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
            who = item.get("characters") or people[:1]
            pose_key = (str(item["sheet_id"]) if item["sheet_id"]
                        else _norm(pose_line)[:64]
                        or f"scene-{song['id']}-{item['num']}")
            key = f"{_who_key(who)}|{pose_key}"
            g = groups.get(key)
            if g is None:
                g = {
                    "key": key,
                    "who": _who_key(who),
                    "label": (item.get("label") or item.get("pose")
                              or item.get("need") or "unspecified")[:80],
                    "sheet_id": item.get("sheet_id"),
                    "path": item.get("path"),
                    "source": item.get("source") or "unbound",
                    "characters": who,
                    "character_label": item.get("character_label") or _who_label(who),
                    "actors": list(item.get("actors") or who),
                    "actor_label": item.get("actor_label") or _who_label(
                        item.get("actors") or who),
                    "songs": [],
                    "binds": [],
                    "needs": [],
                    "mage_parts": [],
                    "n_scenes": 0,
                }
                groups[key] = g
            _append_people(g["actors"], item.get("actors") or who)
            g["actor_label"] = _who_label(g["actors"])
            g["n_scenes"] += 1
            need = (item.get("need") or item.get("pose") or "").strip()
            if need and need not in g["needs"] and len(g["needs"]) < 6:
                g["needs"].append(need[:800])
            mage = (item.get("mage") or "").strip()
            if mage and mage not in g["mage_parts"] and len(g["mage_parts"]) < 4:
                g["mage_parts"].append(mage)
            g["binds"].append({"song_id": song["id"], "num": item["num"]})
            if not any(s["id"] == song["id"] for s in g["songs"]):
                g["songs"].append({"id": song["id"], "title": song["title"]})
            if item.get("sheet_id") and not g.get("sheet_id"):
                g["sheet_id"] = item["sheet_id"]
                g["path"] = item["path"]
                g["source"] = item["source"]
    needed = sorted(groups.values(),
                    key=lambda r: (r["sheet_id"] is not None,
                                   r["character_label"].lower(),
                                   r["label"].lower()))
    for g in needed:
        g["mage"] = "\n\n".join(g.get("mage_parts") or [])
    sheets = []
    for row in db.q(
            f"""SELECT a.*, c.name AS character_name
                FROM anchors a LEFT JOIN characters c ON c.id = a.character_id
                WHERE {db.visible_anchor_sql('a')} AND a.tier=?
                ORDER BY a.chosen DESC, a.id""",
            album or "", tier):
        sheets.append({
            "id": row["id"], "label": sheet_name(row), "path": row["path"],
            "view": row["view"], "chosen": bool(row["chosen"]),
            "character_id": row["character_id"],
            "character_name": row["character_name"] or _album_lead_name(album),
        })
    for g in needed:
        g["sheets"] = _sheet_pool(sheets, g.get("actors") or g["characters"])
    people_out = []
    for person in people:
        n = sum(1 for g in needed
                if any(c.get("id") == person["id"] for c in g["characters"]))
        miss = sum(1 for g in needed if not g["sheet_id"]
                   and any(c.get("id") == person["id"] for c in g["characters"]))
        if n:
            people_out.append({
                "id": person["id"], "name": person["name"],
                "who": "lead" if person["id"] is None else str(person["id"]),
                "n_needed": n, "n_have": n - miss, "n_missing": miss,
            })
    return {
        "album": album or "",
        "tier": tier,
        "needed": needed,
        "n_needed": len(needed),
        "n_have": sum(1 for r in needed if r["sheet_id"]),
        "n_missing": sum(1 for r in needed if not r["sheet_id"]),
        "sheets": sheets,
        "people": people_out,
    }


def stamp_sheet_pose_name(sheet_id, name):
    """Write the operator pose name onto the sheet. The view key stays."""
    if not sheet_id:
        return
    name = " ".join(str(name or "").split())[:80]
    if not name:
        return
    row = db.one("SELECT render_json FROM anchors WHERE id=?", int(sheet_id))
    if not row:
        return
    try:
        meta = json.loads(row["render_json"] or "{}")
    except ValueError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    if meta.get("pose_name") == name:
        return
    meta["pose_name"] = name
    db.run("UPDATE anchors SET render_json=? WHERE id=?",
           json.dumps(meta), int(sheet_id))


def stamp_binds(tier, binds, sheet_id):
    """Write pose_sheet_id onto these scenes. Does not recompute coverage."""
    want = None if sheet_id in (None, "", 0, "0") else int(sheet_id)
    for b in binds or []:
        try:
            bind_scene(b["song_id"], tier, b["num"], want)
        except (LookupError, ValueError):
            continue
