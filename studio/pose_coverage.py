"""T2-50 / T4-23 / T4-24: board coverage, gap vs keepers, then generate.

Analyze persists (pose, view, wardrobe, exposure) per scene. Gap reads the
open song's ceiling board, compares to classification_json keepers, and
emits holes only. Analyze and gap write no refs, jobs, or scene_pose_map.
T4-24 generate lives in pose_generate (studio jobs, not batch_edit).
Does not import pose_plan.
"""
import re
import time

import classification
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
    needs = _needs_from_board(song["id"], tier)
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


def _tier_rank(name):
    return list(tiers.BUILTIN).index(name) if name in tiers.BUILTIN else -1


def ceiling_tier(song_id):
    """Highest storyboard tier on this song. That board is the ceiling."""
    song = storyboard_service.require_song(song_id)
    rows = db.q("SELECT DISTINCT tier FROM storyboards WHERE song_id=?",
                song["id"])
    if not rows:
        raise LookupError("no storyboard")
    return max((r["tier"] for r in rows), key=_tier_rank)


def _needs_from_board(song_id, tier):
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
    return needs


def _keeper_key(image):
    pose_raw = image.get("pose") or ""
    view_raw = image.get("view") or ""
    pose = _match(pose_raw, _POSE_CANON) or _slug(pose_raw)
    view = _match(view_raw, _VIEW_CANON, default=_slug(view_raw) or "front")
    wardrobe = _norm(image.get("wardrobe") or "")
    if wardrobe in ("nude", "naked", "unclothed", "undressed"):
        wardrobe = "nude"
    else:
        wardrobe = "clothed"
    return (pose, view, wardrobe)


def _need_key(item):
    return (item["pose"], item["view"], item["wardrobe"])


def gap(song_id, character_id=None, tier=None):
    """T4-23: board needs vs classification keepers. Holes only.

    Default board is the song's ceiling (highest tier). A named tier
    gaps that board instead. Does not write pose_coverage, refs, jobs,
    or scene_pose_map. usable=skip never covers a need.
    """
    song = storyboard_service.require_song(song_id)
    album = (song["album"] or "").strip()
    if not album:
        raise ValueError("an album is needed to compare coverage")
    if tier:
        storyboard_service.require_tier(tier)
    else:
        tier = ceiling_tier(song["id"])
    needs = _needs_from_board(song["id"], tier)
    covered = {_keeper_key(im) for im in
               classification.keepers(album, character_id)["images"]}
    grouped = {}
    for item in needs:
        key = _need_key(item)
        if key in covered:
            continue
        hole = grouped.get(key)
        if hole is None:
            hole = {
                "pose": item["pose"],
                "view": item["view"],
                "wardrobe": item["wardrobe"],
                "exposure": item["exposure"],
                "scenes": [],
            }
            grouped[key] = hole
        num = item["scene_number"]
        if num not in hole["scenes"]:
            hole["scenes"].append(num)
        if item["exposure"] == "exposed":
            hole["exposure"] = "exposed"
    holes = sorted(grouped.values(), key=lambda h: (h["scenes"][:1] or [0])[0])
    n_covered = sum(1 for item in needs if _need_key(item) in covered)
    return {
        "song_id": song["id"],
        "album": album,
        "tier": tier,
        "n_needs": len(needs),
        "n_covered": n_covered,
        "n_holes": len(holes),
        "holes": holes,
    }


def generate(song_id, run_tiers, character_id=None, images=None):
    """T4-24: ceiling-tier sheets from gap holes. Delegates to pose_generate."""
    import pose_generate
    return pose_generate.generate(
        song_id, run_tiers, character_id=character_id, images=images)
