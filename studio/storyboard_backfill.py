"""T2-54: ceiling + ticked-lower backfill of storyboards.

The run's ceiling is the highest ticked tier. Every ticked tier at or
below that ceiling gets a board from the ceiling board, stamped with
that tier's guardrail and the wardrobe it permits. Nude clamps to
clothed on g/pg13. Unticked and higher tiers are not written.
No FastAPI.
"""
import copy
import os
import time

import db
import grok
import storyboard_service
import tiers

_NUDE_WARDROBE = frozenset({"nude", "naked", "unclothed", "undressed"})


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
    """Highest ticked tier this run. That is the board ceiling."""
    return max(_normalize_tiers(run_tiers), key=_tier_rank)


def _wardrobe_for(raw, tier):
    token = (raw or "").strip().lower()
    if token in _NUDE_WARDROBE:
        token = "nude"
    elif not token or token in ("clothed", "dressed"):
        token = "clothed"
    if token == "nude" and not tiers.allows_nudity(tier):
        return "clothed"
    return token


def _view_for(raw, tier):
    view = (raw or "").strip()
    if view.endswith("_nude") and not tiers.allows_nudity(tier):
        return view[:-5] or "front"
    return view


def _adapt(sb, song, tier):
    out = copy.deepcopy(sb)
    if not isinstance(out, dict):
        raise ValueError("storyboard must be a JSON object")
    album = (song.get("album") or "") if hasattr(song, "get") else ""
    out["version"] = str(tier)
    out["guardrail"] = tiers.compose_guardrail(str(tier), album)
    scenes = out.get("scenes") or []
    if not isinstance(scenes, list):
        raise ValueError("storyboard needs a scenes list")
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        scene["wardrobe"] = _wardrobe_for(scene.get("wardrobe"), tier)
        if "view" in scene:
            scene["view"] = _view_for(scene.get("view"), tier)
    return out


def _persist(song, source, sb, tier):
    outdir = os.path.join(db.DATA, "storyboards", song["slug"])
    json_path, md_path = grok.write_storyboard(sb, outdir, song["slug"], tier)
    scene_count = len(sb.get("scenes") or [])
    db.run(
        """INSERT INTO storyboards
           (song_id, tier, json_path, md_path, scene_count, created,
            prompt, scene_seconds)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(song_id, tier) DO UPDATE SET
             json_path=excluded.json_path, md_path=excluded.md_path,
             scene_count=excluded.scene_count, created=excluded.created,
             prompt=excluded.prompt, scene_seconds=excluded.scene_seconds""",
        song["id"], tier, json_path, md_path, scene_count, time.time(),
        source["prompt"] if "prompt" in source.keys() else "",
        source["scene_seconds"] if "scene_seconds" in source.keys() else None)
    return {
        "tier": tier,
        "json_path": json_path,
        "md_path": md_path,
        "scene_count": scene_count,
    }


def backfill(song_id, run_tiers):
    """Write ticked boards at or below the run ceiling from that ceiling board."""
    song = storyboard_service.require_song(song_id)
    names = _normalize_tiers(run_tiers)
    ceiling = max(names, key=_tier_rank)
    source = db.one(
        "SELECT * FROM storyboards WHERE song_id=? AND tier=?",
        song["id"], ceiling)
    if not source:
        raise LookupError(f"no storyboard for tier '{ceiling}'")
    try:
        source_sb = storyboard_service.load(source, normalized=False)
    except (OSError, ValueError, TypeError, KeyError) as e:
        raise RuntimeError(f"storyboard file is unreadable: {e}") from None
    cap = _tier_rank(ceiling)
    targets = [t for t in names if _tier_rank(t) <= cap]
    targets.sort(key=_tier_rank)
    boards = []
    for tier in targets:
        boards.append(_persist(song, source, _adapt(source_sb, song, tier), tier))
    return {
        "song_id": song["id"],
        "ceiling": ceiling,
        "tiers": names,
        "written": [b["tier"] for b in boards],
        "boards": boards,
    }
