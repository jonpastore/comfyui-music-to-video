"""T2-50: analyze-for-poses writes a coverage list, not a bind.

Given a ceiling-tier storyboard, persist (pose, view, wardrobe, exposure)
per scene. Does not write refs, jobs, or scene_pose_map. Does not import
pose_plan.
"""
import re
import time

import db
import storyboard_service
import tiers

# Longest alias first so "all fours" wins over a later "stand" substring.
_POSE_CANON = (
    ("all-fours", (
        "all fours", "all-fours", "allfours", "hands and knees",
        "hands-and-knees", "on all fours",
    )),
    ("kneeling", ("kneeling", "on her knees", "on knees", "kneel")),
    ("standing", ("standing", "stand", "walk", "walking")),
    ("cowgirl", ("cowgirl", "riding", "on top", "sits on", "sitting on")),
    ("supine", ("supine", "on her back", "on back", "lying on back")),
    ("seated", ("seated", "sitting", "sit ")),
    ("crouch", ("crouching", "crouch", "squat")),
    ("bent", ("bent over", "bent at")),
    ("spread", ("legs apart", "legs parted", "spreading", "spread")),
)

_VIEW_CANON = (
    ("3qtr-rear", (
        "3qtr-rear", "3/4 rear", "three-quarter rear", "from behind",
        "over her shoulder", "over shoulder", "looking back", "look back",
        "rear",
    )),
    ("back", ("from the back", "back view", "back")),
    ("side", ("side view", "profile", "side")),
    ("3qtr", ("3qtr", "3/4", "three-quarter", "three quarter")),
    ("front", ("front", "facing", "close-up", "close up", "wide", "medium")),
)

_NUDE_WORDS = ("nude", "naked", "unclothed", "undressed")
_EXPOSE_WORDS = ("exposed", "vulva", "anus", "labia", "spread", "presenting")


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _need_text(scene):
    bits = [
        scene.get("pose") or "",
        scene.get("view") or "",
        scene.get("wardrobe") or "",
        scene.get("exposure") or "",
        scene.get("story") or "",
        scene.get("camera") or "",
    ]
    prompt = scene.get("image_prompt") or ""
    if prompt:
        bits.append(prompt[:240])
    return " ".join(b for b in bits if b).strip()


def _match(text, table, default=""):
    t = _norm(text)
    if not t:
        return default
    padded = f" {t} "
    for canon, aliases in table:
        for alias in aliases:
            a = _norm(alias)
            if not a:
                continue
            if t == a or a in t or f" {a} " in padded:
                return canon
    return default


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", _norm(text)).strip("-")[:64]


def _pose_of(scene):
    raw = (scene.get("pose") or "").strip()
    hay = raw or _need_text(scene)
    hit = _match(hay, _POSE_CANON)
    if hit:
        return hit
    return _slug(raw) or "unspecified"


def _view_of(scene):
    raw = (scene.get("view") or "").strip()
    if raw:
        return _match(raw, _VIEW_CANON, default=_slug(raw) or "front")
    hay = " ".join(b for b in (
        scene.get("camera") or "",
        scene.get("pose") or "",
        scene.get("story") or "",
    ) if b)
    return _match(hay, _VIEW_CANON, default="front") or "front"


def _wardrobe_of(scene, tier):
    raw = _norm(scene.get("wardrobe") or "")
    if raw in ("nude", "naked", "unclothed", "undressed"):
        token = "nude"
    elif raw in ("clothed", "dressed"):
        token = "clothed"
    else:
        hay = _need_text(scene).lower()
        token = "nude" if any(w in hay for w in _NUDE_WORDS) else "clothed"
    if token == "nude" and not tiers.allows_nudity(tier):
        return "clothed"
    return token


def _exposure_of(scene):
    raw = _norm(scene.get("exposure") or "")
    if raw in ("exposed", "uncovered", "open"):
        return "exposed"
    if raw in ("covered", "closed", "hidden"):
        return "covered"
    hay = _need_text(scene).lower()
    if any(w in hay for w in _EXPOSE_WORDS):
        return "exposed"
    return "covered"


def need_from_scene(scene, tier=""):
    """One coverage tuple from a scene object. Does not write."""
    try:
        num = int(scene.get("scene_number"))
    except (TypeError, ValueError):
        num = None
    return {
        "scene_number": num,
        "pose": _pose_of(scene),
        "view": _view_of(scene),
        "wardrobe": _wardrobe_of(scene, tier),
        "exposure": _exposure_of(scene),
    }


def _need_row(row):
    return {
        "scene_number": row["scene_number"],
        "pose": row["pose"],
        "view": row["view"],
        "wardrobe": row["wardrobe"],
        "exposure": row["exposure"],
    }


def listed(song_id, tier):
    """Stored coverage for this song+tier. Empty if analyze has not run."""
    song = storyboard_service.require_song(song_id)
    storyboard_service.require_tier(tier)
    rows = db.q(
        """SELECT scene_number, pose, view, wardrobe, exposure
           FROM pose_coverage WHERE song_id=? AND tier=?
           ORDER BY scene_number""",
        song["id"], tier)
    needs = [_need_row(r) for r in rows]
    return {
        "song_id": song["id"],
        "tier": tier,
        "n_scenes": len(needs),
        "needs": needs,
    }


def analyze(song_id, tier):
    """Write coverage from the board at this tier. Replaces prior rows.

    Does not attach files, write refs, enqueue jobs, or write scene_pose_map.
    """
    song = storyboard_service.require_song(song_id)
    storyboard_service.require_tier(tier)
    row = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?",
                 song["id"], tier)
    if not row:
        raise LookupError(f"no storyboard for tier '{tier}'")
    sb = storyboard_service.load(row, normalized=False)
    needs = []
    for scene in sb.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        item = need_from_scene(scene, tier)
        if item["scene_number"] is None:
            continue
        needs.append(item)
    now = time.time()
    with db.transaction():
        db.run("DELETE FROM pose_coverage WHERE song_id=? AND tier=?",
               song["id"], tier)
        for item in needs:
            db.run(
                """INSERT INTO pose_coverage
                   (song_id, tier, scene_number, pose, view, wardrobe,
                    exposure, created)
                   VALUES (?,?,?,?,?,?,?,?)""",
                song["id"], tier, item["scene_number"], item["pose"],
                item["view"], item["wardrobe"], item["exposure"], now)
    return {
        "song_id": song["id"],
        "tier": tier,
        "n_scenes": len(needs),
        "needs": needs,
    }
