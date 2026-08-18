#!/usr/bin/env python3
"""Copy operator pose models into the shared anchors library.

Usage (from repo root, against a live STUDIO_DATA):

    STUDIO_DATA=~/meowp-studio/data python3 scripts/import_shared_poses.py

Idempotent on basename. Does not copy reddit/hops/generated kitty QC fails.
"""
import hashlib
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "anchor5")
sys.path.insert(0, os.path.join(ROOT, "studio"))
import db  # noqa: E402

# Already on Street Cats (basename match). Skip.
SKIP_SUBSTR = (
    "panther-blowjob-nude",
    "tiger-standing-erect",
    "tiger-standing-side-erect",
    "panther-standing-side-erect",
    "cowgirl-dp-panther-tiger-nude",
    "cowgirl-panther-fully-inserted-nude",
    "cowgirl-panther-nude",
    "mounting-cowgirl-panther-nude",
    "reverse-cowgirl-cumming-on-panther-sucking-tiger-dick",
    "panther-couching-spring",
    "panther-carried-thigh-hold-slip",
    "reverse-cowgirl-fully-inserted-rear",
    "reverse-cowgirl-cumming-on-inserted-dick-rear",
    "reverse-cowgirl-nude",
    "reverse-cowgirl-cumming-nude",
    "reverse-cowgirl-leaning",
    "kitty_cover_crop",
    "mouthfail",
)

# (filename, character_name or None, actors, pose_name, nude, view_override)
SHEETS = [
    ("kitty-standing front-nude.jpg", "Kitty", ["Kitty"], "standing front", True, "front"),
    ("kitty-standing-forward-3qtr-nude.jpg", "Kitty", ["Kitty"], "standing forward three-quarter", True, None),
    ("kitty-standing-rear-looking-back.jpg", "Kitty", ["Kitty"], "standing rear looking back", False, None),
    ("kitty-portrait-nude.jpg", "Kitty", ["Kitty"], "portrait nude", True, None),
    ("kitty-seated-nude.jpg", "Kitty", ["Kitty"], "seated", True, None),
    ("kitty-seated-leaning-nude.jpg", "Kitty", ["Kitty"], "seated leaning", True, None),
    ("kitty-seated-touching-pussy-nude.jpg", "Kitty", ["Kitty"], "seated touching pussy", True, None),
    ("kitty-kneeling-wide-spread-nude.jpg", "Kitty", ["Kitty"], "kneeling wide spread", True, None),
    ("litty-kneeling-side-tongue-out-nude.jpg", "Kitty", ["Kitty"], "kneeling side tongue out", True, None),
    ("kitty-all-fours-forward.jpg", "Kitty", ["Kitty"], "all fours forward", False, None),
    ("kitty-all-fours-rear-looking-back.jpg", "Kitty", ["Kitty"], "all fours rear looking back", False, None),
    ("kitty-all-fours-rear-nude.jpg", "Kitty", ["Kitty"], "all fours rear", True, None),
    ("kitty-all-fours-rear-wet-pussy-nude.jpg", "Kitty", ["Kitty"], "all fours rear wet pussy", True, None),
    ("kitty-all-fours-wide-knees-rear-nude.jpg", "Kitty", ["Kitty"], "all fours wide knees rear", True, None),
    ("kitty-grog-legged-erar-looking-back-nude.jpg", "Kitty", ["Kitty"], "frog-legged rear looking back", True, None),
    ("kitty-cobra0stretch-nude-rear.jpg", "Kitty", ["Kitty"], "cobra stretch rear", True, None),
    ("kitty-laying-nude.jpg", "Kitty", ["Kitty"], "laying", True, None),
    ("kitty-laying-side-knee-up-spread-nude.jpg", "Kitty", ["Kitty"], "laying side knee up spread", True, None),
    ("kitty-laying-sperad-eagle.jpg", "Kitty", ["Kitty"], "laying spread eagle", False, None),
    ("kitty-laying-spread-eagle-1-knee-up-nude.jpg", "Kitty", ["Kitty"], "laying spread eagle one knee up", True, None),
    ("kitty-sleepging-nude.jpg", "Kitty", ["Kitty"], "sleeping", True, None),
    ("kitty-fuck-licking-cum-from-meow-p-panther-anal-nude.jpg", None,
     ["Kitty", "Meow P", "Panther"], "kitty fucklicking Meow P and Panther anal", True, None),
    ("meow-p-cumming-on-kitty-face.jpg", None, ["Meow P", "Kitty"],
     "Meow P cumming on Kitty face", True, None),
    ("meow-p-kitty-facesitting-squirting.jpg", None, ["Meow P", "Kitty"],
     "Kitty facesitting Meow P squirting", True, None),
    ("meow-p-licking-kitty-pussy-while-sucking-dick.jpg", None,
     ["Meow P", "Kitty"], "Meow P licking Kitty while sucking", True, None),
    ("panther-front-squat-nude.jpg", "Panther", ["Panther"], "front squat", True, None),
    ("panther-standing-3qtr.jpg", "Panther", ["Panther"], "standing three-quarter", False, None),
    ("cowgirl-meowp-panther-2p-v1.jpg", None, ["Meow P", "Panther"],
     "cowgirl Meow P Panther", True, None),
]

TIER = "xxx"


def _already(basename):
    key = basename.lower().replace(" ", "_")
    for row in db.q("SELECT path FROM anchors"):
        if key in os.path.basename(row["path"] or "").lower().replace(" ", "_"):
            return True
    for row in db.q("SELECT path FROM assets WHERE kind='anchor_ref'"):
        if key in os.path.basename(row["path"] or "").lower().replace(" ", "_"):
            return True
    return False


def _character_id(name):
    if not name:
        return None
    row = db.one("SELECT id FROM characters WHERE name=? ORDER BY id", name)
    return row["id"] if row else None


def _basename_key(path):
    return os.path.basename(path or "").lower().replace(" ", "_")


def _should_promote(row):
    """Album-scoped operator plates → shared. Meow P NULL candidates stay.

    Matches render_json.shared_pending (the first 28 Kitty/actor promotes) or a
    historical Street Cats basename in SKIP_SUBSTR. Protagonist candidates
    (character_id IS NULL, no actors stamp, not a SKIP plate) stay album-scoped.
    """
    if (row["scope_kind"] or "") != "album":
        return False
    key = _basename_key(row["path"])
    if any(s in key for s in SKIP_SUBSTR):
        return True
    try:
        meta = json.loads(row["render_json"] or "{}")
    except (TypeError, ValueError):
        meta = {}
    if not meta.get("shared_pending"):
        return False
    if row["character_id"] is None and not (meta.get("actors") or []):
        return False
    return True


def promote_pending():
    """Flip album-scoped operator plates to scope_kind=shared."""
    rows = db.q("""SELECT id, scope_kind, character_id, path, render_json
                   FROM anchors""")
    n = 0
    for r in rows:
        if not _should_promote(r):
            continue
        db.run("""UPDATE anchors SET scope_kind=?, scope_value=? WHERE id=?""",
               db.SHARED_KIND, db.SHARED_VALUE, r["id"])
        n += 1
    print(f"promoted {n} pending rows to shared")
    return 0


def main():
    if "--promote-pending" in sys.argv or "--promote" in sys.argv:
        return promote_pending()
    dest = db.shared_anchor_dir()
    now = time.time()
    added = []
    skipped = []
    for fname, who, actors, label, nude, view_override in SHEETS:
        src = os.path.join(SRC, fname)
        if not os.path.isfile(src):
            skipped.append((fname, "missing"))
            continue
        if any(s in fname.lower() for s in SKIP_SUBSTR):
            skipped.append((fname, "already-listed"))
            continue
        if _already(fname):
            skipped.append((fname, "in-db"))
            continue
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in fname)
        path = os.path.join(dest, f"pose_{int(time.time() * 1000)}_{safe}")
        shutil.copy2(src, path)
        cid = _character_id(who)
        meta = {
            "scope_kind": db.SHARED_KIND, "scope_value": "Street Cats",
            "role": "pose", "pose_name": label, "pose_tier": TIER,
            "pose_nude": nude, "source": "upload", "character_id": cid,
            "actors": actors, "sha256": hashlib.sha256(open(src, "rb").read()).hexdigest(),
        }
        aid = db.run(
            "INSERT INTO assets (song_id, kind, path, meta_json, created) VALUES (?,?,?,?,?)",
            None, "anchor_ref", path, json.dumps(meta), now)
        view = view_override or (f"pose_{aid}_nude" if nude else f"pose_{aid}")
        db.run("""UPDATE anchors SET chosen=0 WHERE scope_kind=? AND scope_value=?
                  AND tier=? AND view=? AND character_id IS ?""",
               db.SHARED_KIND, db.SHARED_VALUE, TIER, view, cid)
        new_id = db.run(
            """INSERT INTO anchors (scope_kind, scope_value, tier, view, path,
                                    chosen, created, character_id, render_json)
               VALUES (?,?,?,?,?,1,?,?,?)""",
            db.SHARED_KIND, db.SHARED_VALUE, TIER, view, path, now, cid,
            json.dumps({"source": "upload", "asset_id": aid, "pose_name": label,
                        "character_id": cid, "actors": actors}))
        added.append((new_id, who or "ensemble", label, view))
        now += 0.001
    print(f"added {len(added)}")
    for row in added:
        print(" ", row)
    print(f"skipped {len(skipped)}")
    for row in skipped:
        print(" ", row)
    return 0 if added or skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
