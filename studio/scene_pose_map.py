"""T2-51 / T2-52: draft keeper→scene map; Accept/Reject per scene.

Classify never writes here. Generate refs reads accepted rows only.
A draft or rejected scene is refused by start_refs. Reject restores
the previous accepted keeper (T2-15 shape). No FastAPI.
"""
import os
import time

import classification
import db
import pose_coverage
import storyboard_service
import tiers

_UNACCEPTED = frozenset({"draft", "rejected"})
_NUDE = frozenset({"nude", "naked", "unclothed", "undressed"})


def _public(row):
    return {
        "song_id": row["song_id"],
        "tier": row["tier"],
        "scene_number": row["scene_number"],
        "keeper_id": row["keeper_id"],
        "path": row["path"],
        "status": row["status"],
        "prev_keeper_id": row["prev_keeper_id"],
        "prev_path": row["prev_path"],
    }


def _row(song_id, tier, num):
    return db.one(
        """SELECT * FROM scene_pose_map
           WHERE song_id=? AND tier=? AND scene_number=?""",
        song_id, tier, num)


def _rows(song_id, tier):
    return list(db.q(
        """SELECT * FROM scene_pose_map
           WHERE song_id=? AND tier=? ORDER BY scene_number""",
        song_id, tier))


def _is_nude(image):
    wardrobe = (image.get("wardrobe") or "").strip().lower()
    if wardrobe in _NUDE:
        return True
    pose = (image.get("pose") or "").lower()
    path = (image.get("path") or "").lower()
    return "nude" in pose or "nude" in path


def _image_need(image, tier):
    return pose_coverage.need_from_scene({
        "scene_number": 0,
        "pose": image.get("pose") or "",
        "view": image.get("view") or "",
        "camera": image.get("view") or "",
        "wardrobe": image.get("wardrobe") or "",
    }, tier)


def _best_keeper(need, images, tier):
    """Exact (pose, view, wardrobe) first; pose-only fallback. Nude skipped on g/pg13."""
    allow_nude = tiers.allows_nudity(tier)
    exact = pose_only = None
    want = (need["pose"], need["view"], need["wardrobe"])
    for image in images:
        if _is_nude(image) and not allow_nude:
            continue
        got = _image_need(image, tier)
        key = (got["pose"], got["view"], got["wardrobe"])
        if key == want:
            exact = image
            break
        if got["pose"] == need["pose"] and pose_only is None:
            pose_only = image
    return exact or pose_only


def listed(song_id, tier):
    """Map rows for this song+tier. Empty before draft."""
    song = storyboard_service.require_song(song_id)
    storyboard_service.require_tier(tier)
    rows = [_public(r) for r in _rows(song["id"], tier)]
    return {
        "song_id": song["id"],
        "tier": tier,
        "n_rows": len(rows),
        "n_draft": sum(1 for r in rows if r["status"] == "draft"),
        "n_accepted": sum(1 for r in rows if r["status"] == "accepted"),
        "n_rejected": sum(1 for r in rows if r["status"] == "rejected"),
        "scenes": rows,
    }


def has_rows(song_id, tier):
    return bool(_rows(song_id, tier))


def unaccepted(song_id, tier):
    return [r for r in _rows(song_id, tier) if r["status"] in _UNACCEPTED]


def require_accepted(song_id, tier):
    """Raise when any map row is still draft or rejected. Empty map is ok."""
    song = storyboard_service.require_song(song_id)
    storyboard_service.require_tier(tier)
    bad = unaccepted(song["id"], tier)
    if not bad:
        return
    nums = ", ".join(str(r["scene_number"]) for r in bad)
    raise ValueError(
        f"pose map for tier '{tier}' has draft or rejected scenes "
        f"({nums}) — Accept first")


def accepted_bases(song, tier):
    """{scene_number: path} for accepted rows with a readable file."""
    song = song if hasattr(song, "keys") else storyboard_service.require_song(song)
    storyboard_service.require_tier(tier)
    album = (song["album"] or "").strip()
    out = {}
    for row in _rows(song["id"], tier):
        if row["status"] != "accepted":
            continue
        path = row["path"] or ""
        classification.refuse_skip(album, path=path, image_id=row["keeper_id"])
        if path and os.path.isfile(path):
            out[int(row["scene_number"])] = path
    return out


def _upsert_draft(song_id, tier, num, keeper, now, album=None,
                  character_id=None):
    kid = str(keeper.get("id") or "").strip()
    path = str(keeper.get("path") or "").strip()
    if not album:
        song = db.one("SELECT album FROM songs WHERE id=?", song_id)
        album = ((song["album"] if song else "") or "").strip()
    classification.refuse_skip(album, path=path, image_id=kid,
                               character_id=character_id)
    if _is_nude(keeper) and not tiers.allows_nudity(tier):
        raise ValueError(f"a nude map row is refused on {tier}")
    existing = _row(song_id, tier, num)
    if existing and existing["status"] == "accepted" and str(
            existing["keeper_id"] or "") == kid:
        return _public(existing)
    if existing:
        prev_id, prev_path = existing["prev_keeper_id"], existing["prev_path"]
        if existing["status"] == "accepted":
            prev_id, prev_path = existing["keeper_id"], existing["path"]
        db.run(
            """UPDATE scene_pose_map
               SET keeper_id=?, path=?, status='draft',
                   prev_keeper_id=?, prev_path=?, updated=?
               WHERE song_id=? AND tier=? AND scene_number=?""",
            kid, path, prev_id, prev_path, now, song_id, tier, num)
    else:
        db.run(
            """INSERT INTO scene_pose_map
               (song_id, tier, scene_number, keeper_id, path, status,
                prev_keeper_id, prev_path, created, updated)
               VALUES (?,?,?,?,?,'draft',NULL,NULL,?,?)""",
            song_id, tier, num, kid, path, now, now)
    return _public(_row(song_id, tier, num))


def draft(song_id, tier, character_id=None):
    """Keeper → scene from classified tags + scene text. Status is draft.

    Does not overwrite an accepted row that already names the same keeper.
    Classify never calls this.
    """
    song = storyboard_service.require_song(song_id)
    storyboard_service.require_tier(tier)
    album = (song["album"] or "").strip()
    if not album:
        raise ValueError("an album is needed to draft the pose map")
    board = db.one("SELECT * FROM storyboards WHERE song_id=? AND tier=?",
                   song["id"], tier)
    if not board:
        raise LookupError(f"no storyboard for tier '{tier}'")
    sb = storyboard_service.load(board, normalized=False)
    images = classification.keepers(album, character_id)["images"]
    now = time.time()
    for scene in sb.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        need = pose_coverage.need_from_scene(scene, tier)
        if need["scene_number"] is None:
            continue
        keeper = _best_keeper(need, images, tier)
        if not keeper:
            continue
        _upsert_draft(song["id"], tier, need["scene_number"], keeper, now,
                      album=album, character_id=character_id)
    return listed(song["id"], tier)


def _require_row(song_id, tier, scene_number):
    song = storyboard_service.require_song(song_id)
    storyboard_service.require_tier(tier)
    try:
        num = int(scene_number)
    except (TypeError, ValueError) as e:
        raise ValueError("scene_number must be an integer") from e
    row = _row(song["id"], tier, num)
    if not row:
        raise LookupError(f"no pose map row for scene {num}")
    return song, row


def accept(song_id, tier, scene_number):
    """Persist status=accepted. Nude on g/pg13 is refused."""
    song, row = _require_row(song_id, tier, scene_number)
    if row["status"] == "accepted":
        return _public(row)
    keeper = {"id": row["keeper_id"], "path": row["path"],
              "wardrobe": "", "pose": ""}
    album = (song["album"] or "").strip()
    if album:
        for image in classification.keepers(album)["images"]:
            if str(image.get("id") or "") == str(row["keeper_id"] or ""):
                keeper = image
                break
    if _is_nude(keeper) and not tiers.allows_nudity(tier):
        raise ValueError(f"a nude map row is refused on {tier}")
    db.run(
        """UPDATE scene_pose_map SET status='accepted', updated=?
           WHERE song_id=? AND tier=? AND scene_number=?""",
        time.time(), song["id"], tier, row["scene_number"])
    return _public(_row(song["id"], tier, row["scene_number"]))


def reject(song_id, tier, scene_number):
    """Leave the previous accepted binding (or none). Does not overwrite it."""
    song, row = _require_row(song_id, tier, scene_number)
    if row["status"] != "draft":
        return _public(row)
    now = time.time()
    if row["prev_keeper_id"]:
        db.run(
            """UPDATE scene_pose_map
               SET keeper_id=?, path=?, status='accepted', updated=?
               WHERE song_id=? AND tier=? AND scene_number=?""",
            row["prev_keeper_id"], row["prev_path"], now,
            song["id"], tier, row["scene_number"])
    else:
        db.run(
            """UPDATE scene_pose_map SET status='rejected', updated=?
               WHERE song_id=? AND tier=? AND scene_number=?""",
            now, song["id"], tier, row["scene_number"])
    return _public(_row(song["id"], tier, row["scene_number"]))
