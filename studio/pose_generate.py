"""T4-24: ceiling-tier pose generate from pose-gap holes.

Library sheets at the highest ticked tier this run. Clothed+nude iff
that ceiling allows nudity (r, xxx). g/pg13: clothed only, no anatomy.
Never invent a higher tier than the ceiling. Studio `anchor` jobs, not
sidecar batch_edit. No FastAPI.
"""
import db
import jobs
import make_anchor
import pose_coverage
import storyboard_service
import tiers

# Coverage cameras → make_anchor VIEWS keys. 3qtr-rear is from-behind.
_VIEW_TO_SHEET = {
    "front": "front",
    "back": "back",
    "side": "profile",
    "3qtr": "three_quarter",
    "3qtr-rear": "back",
    "profile": "profile",
    "three_quarter": "three_quarter",
}


def _tier_rank(name):
    return list(tiers.BUILTIN).index(name) if name in tiers.BUILTIN else -1


def _normalize_tiers(run_tiers):
    names = []
    for raw in run_tiers or []:
        name = (raw or "").strip()
        if not name:
            continue
        storyboard_service.require_tier(name)
        if name not in names:
            names.append(name)
    if not names:
        raise ValueError("select at least one tier")
    return names


def ceiling_of(run_tiers):
    """Highest ticked tier this run. That is the generate ceiling."""
    return max(_normalize_tiers(run_tiers), key=_tier_rank)


def required_wardrobes(tier):
    """Clothed+nude at r/xxx; clothed only at g/pg13."""
    return ("clothed", "nude") if tiers.allows_nudity(tier) else ("clothed",)


def sheet_view(view, wardrobe):
    """Coverage (view, wardrobe) → make_anchor view key."""
    base = _VIEW_TO_SHEET.get((view or "").strip()) or (view or "").strip() or "front"
    if (wardrobe or "").strip().lower() == "nude":
        return base if make_anchor.is_nude_view(base) else f"{base}_nude"
    if make_anchor.is_nude_view(base):
        return base[:-5]
    return base


def coverage_status(tier, sheets, holes):
    """green only when every hole pair has every required wardrobe planned."""
    required = required_wardrobes(tier)
    have = {(s.get("pose"), s.get("view"), s.get("wardrobe")) for s in sheets}
    pairs = []
    seen = set()
    for hole in holes:
        key = (hole.get("pose"), hole.get("view"))
        if key not in seen:
            seen.add(key)
            pairs.append(key)
    need = {(pose, view, wardrobe) for pose, view in pairs for wardrobe in required}
    return "green" if need <= have else "holes"


def _album_images(album, character_id=None):
    paths = []
    for row in db_assets(album, character_id):
        path = row["path"]
        if path:
            paths.append(path)
    return paths


def db_assets(album, character_id=None):
    cid = int(character_id) if character_id else None
    out = []
    for row in db.q("SELECT * FROM assets WHERE kind='anchor_ref' ORDER BY id DESC"):
        meta = db.jset(row)
        if meta.get("scope_value") != album:
            continue
        if (meta.get("character_id") or None) != cid:
            continue
        out.append(row)
    return out


def plan(song_id, run_tiers, character_id=None):
    """Expand pose-gap holes into ceiling-tier sheets. Does not enqueue."""
    song = storyboard_service.require_song(song_id)
    album = (song["album"] or "").strip()
    if not album:
        raise ValueError("an album is needed to generate poses")
    names = _normalize_tiers(run_tiers)
    ceiling = max(names, key=_tier_rank)
    holes = pose_coverage.gap(song["id"], character_id=character_id)["holes"]
    wardrobes = required_wardrobes(ceiling)
    pairs = []
    seen = set()
    for hole in holes:
        key = (hole["pose"], hole["view"])
        if key not in seen:
            seen.add(key)
            pairs.append(key)
    sheets = []
    for pose, view in pairs:
        for wardrobe in wardrobes:
            sheets.append({
                "pose": pose,
                "view": view,
                "sheet_view": sheet_view(view, wardrobe),
                "wardrobe": wardrobe,
                "tier": ceiling,
                "anatomy": False,
            })
    return {
        "song_id": song["id"],
        "album": album,
        "tier": ceiling,
        "tiers": names,
        "sheets": sheets,
        "n_sheets": len(sheets),
        "n_holes": len(holes),
        "coverage": coverage_status(ceiling, sheets, holes),
        "anatomy": False,
    }


def generate(song_id, run_tiers, character_id=None, images=None, n=4):
    """Plan from holes and enqueue studio anchor jobs. Not batch_edit."""
    planned = plan(song_id, run_tiers, character_id=character_id)
    if images is None:
        images = _album_images(planned["album"], character_id)
    images = list(images or [])
    n = max(1, min(int(n or 4), 8))
    queued = []
    for sheet in planned["sheets"]:
        jid = jobs.enqueue("anchor", {
            "scope_kind": "album",
            "scope_value": planned["album"],
            "tier": sheet["tier"],
            "view": sheet["sheet_view"],
            "images": images,
            "n": n,
            "character_id": character_id,
            "prompt": "",
            "pose": sheet["pose"],
            "wardrobe": sheet["wardrobe"],
            "anatomy": False,
            "source": "pose-gap",
        }, song_id=planned["song_id"])
        queued.append({
            "id": jid,
            "tier": sheet["tier"],
            "view": sheet["sheet_view"],
            "pose": sheet["pose"],
            "wardrobe": sheet["wardrobe"],
            "anatomy": False,
        })
    planned["jobs"] = queued
    planned["queued"] = len(queued)
    return planned
