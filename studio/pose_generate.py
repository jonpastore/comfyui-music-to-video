"""T4-24 / T7-21: ceiling-tier pose generate from pose-gap holes.

Library sheets at the highest ticked tier this run. Clothed+nude iff
that ceiling allows nudity (r, xxx). g/pg13: clothed only, no anatomy.
Never invent a higher tier than the ceiling. Studio `anchor` jobs, not
sidecar batch_edit. No FastAPI.

T7-21: one resolver picks C1 (same-pose: image latent, denoise 1.0,
pose text matches the source) vs C2 (new-pose: empty 896×1216, her
keepers as image1, asked pose replaces the standing clause). Denoise
labels come from that same latent so they cannot disagree with the
graph.
"""
import os

import classification
import db
import jobs
import make_anchor
import pose_coverage
import storyboard_service
import tiers

C2_SIZE = (896, 1216)
C1_C2_DENOISE = 1.0
HER_KINDS = ("operator", "generated")
PLATE_KINDS = ("plate",)
DENOISE_VALUES = ("0.35", "0.45", "0.55", "0.65", "0.75", "1.0")
_POSE_CLAUSE = {
    "standing": "standing upright, arms relaxed at their sides, feet apart",
    "kneeling": "kneeling",
    "all-fours": (
        "on hands and knees, hips toward the camera, back arched, "
        "tail lifted aside, head turned to look back, knees apart"
    ),
    "cowgirl": "straddling, sitting on top",
    "supine": "lying on her back, knees bent, legs parted",
    "seated": "sitting facing the camera",
    "crouch": "crouching",
    "bent": "bent over",
    "spread": "standing with legs apart",
}

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


def denoise_labels(latent, values=None):
    """[(value, label)] for the latent the sampler will start from.

    Same resolver the anchors form uses (T7-8). Below 1.0 from an empty
    latent returns leftover noise; below 1.0 from an encoded image is
    the point of the control.
    """
    values = values or DENOISE_VALUES
    if latent == "image":
        wording = {
            "0.35": "0.35 — barely touched; the reference with a new surface",
            "0.45": "0.45 — light refine, composition and pose held",
            "0.55": "0.55 — the usable middle: same sheet, re-rendered",
            "0.65": "0.65 — the spec's default; pose held, detail redrawn",
            "0.75": "0.75 — heavy; keeps little more than the layout",
            "1.0": "1.0 — full denoise, which discards the reference entirely",
        }
        return tuple((v, wording[v]) for v in values)
    return tuple(
        (v, f"{v} — refine-from-image only; from an empty latent this returns noise")
        if v != "1.0" else
        (v, "1.0 — full denoise, the only correct value from an empty latent")
        for v in values
    )


def _canon_pose(text):
    return (pose_coverage._match(text, pose_coverage._POSE_CANON)
            or pose_coverage._slug(text))


def _canon_view(text):
    return pose_coverage._match(
        text, pose_coverage._VIEW_CANON,
        default=pose_coverage._slug(text) or "front")


def pose_clause(pose):
    """Positive pose wording for apply_pose. Empty stays the view stance."""
    raw = " ".join((pose or "").split())
    if not raw:
        return ""
    return _POSE_CLAUSE.get(_canon_pose(raw), raw)


def is_her_keeper(image):
    """Identity/generated stills of her. A plate is never image1 (T7-21)."""
    if not image:
        return False
    kind = (image.get("kind") or "").strip().lower()
    if kind in PLATE_KINDS:
        return False
    if kind and kind not in HER_KINDS:
        return False
    usable = (image.get("usable") or "").strip().lower()
    return usable != "skip"


def _image_roots():
    """Dirs that hold operator plates when classification only stored a name."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    data = getattr(db, "DATA", "") or ""
    return [p for p in (
        os.path.join(root, "scripts", "anchor5"),
        os.path.join(root, "anchor5"),
        os.path.join(here, "seed"),
        data,
        os.path.join(data, "uploads") if data else "",
        os.path.join(data, "uploads", "anchors") if data else "",
    ) if p]


def resolve_image_path(path):
    """Absolute file, or a sidecar basename found under the known plate dirs.

    Live Street Cats keepers are `tense.jpg` from the import sidecar. The
    bytes live in meowp-studio/scripts/anchor5/. A missing name is None,
    never the bare filename that FileNotFoundError'd job 343.
    """
    path = (path or "").strip()
    if not path:
        return None
    if os.path.isfile(path):
        return path
    name = os.path.basename(path)
    if not name or name in (".", ".."):
        return None
    for root in _image_roots():
        cand = os.path.join(root, name)
        if os.path.isfile(cand):
            return cand
    return None


def existing_images(paths):
    """Keep only paths that resolve to a real file, in order, no dupes."""
    out, seen = [], set()
    for path in paths or []:
        real = resolve_image_path(path)
        if not real or real in seen:
            continue
        seen.add(real)
        out.append(real)
    return out


def _her_keepers(keepers, album_images=None):
    her = [im for im in (keepers or []) if is_her_keeper(im) and im.get("path")]
    if her:
        return her
    out = []
    for path in album_images or []:
        if path:
            out.append({
                "path": path, "kind": "operator", "usable": "identity",
                "pose": "", "view": "", "wardrobe": "clothed",
            })
    return out


def _same_pose_source(asked, her):
    want_pose = _canon_pose(asked.get("pose"))
    want_view = _canon_view(asked.get("view"))
    if not want_pose:
        return None
    for image in her:
        if (_canon_pose(image.get("pose")) == want_pose
                and _canon_view(image.get("view")) == want_view):
            return image
    return None


def resolve_c1_c2(asked, keepers=None, album_images=None):
    """C1 same-pose vs C2 new-pose. Latent, denoise labels, and pose text.

    C1: her same pose+view still exists — encode it, denoise 1.0, pose
    wording matches that source. C2: empty 896×1216, her keepers as
    image1, asked pose replaces the standing clause. A stranger plate
    never becomes the encoded latent or image1.
    """
    her = _her_keepers(keepers, album_images)
    source = _same_pose_source(asked, her)
    if source:
        latent = "image"
        kind = "c1"
        pose_label = "same-pose"
        pose = pose_clause(source.get("pose") or asked.get("pose"))
        images = [source["path"]]
        width = height = None
        source_path = source["path"]
    else:
        latent = "empty"
        kind = "c2"
        pose_label = "new-pose"
        pose = pose_clause(asked.get("pose"))
        images = [im["path"] for im in her][:3]
        width, height = C2_SIZE
        source_path = None
    labels = denoise_labels(latent)
    return {
        "kind": kind,
        "latent": latent,
        "denoise": C1_C2_DENOISE,
        "width": width,
        "height": height,
        "pose": pose,
        "pose_label": pose_label,
        "images": images,
        "source_path": source_path,
        "denoise_label": dict(labels)[str(C1_C2_DENOISE)],
        "denoise_labels": labels,
    }


def c1_c2_render(resolved):
    """make_anchor flags for a T7-21 decision. Keys match ANCHOR_RENDER_FLAGS."""
    render = {
        "latent": resolved["latent"],
        "denoise": resolved["denoise"],
    }
    if resolved.get("kind") == "c2":
        render["width"] = resolved.get("width") or C2_SIZE[0]
        render["height"] = resolved.get("height") or C2_SIZE[1]
    return render


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
    keepers = classification.keepers(planned["album"], character_id)["images"]
    n = max(1, min(int(n or 4), 8))
    queued = []
    for sheet in planned["sheets"]:
        decided = resolve_c1_c2(sheet, keepers, images)
        refs = existing_images(decided["images"]) or existing_images(images)[:3]
        jid = jobs.enqueue("anchor", {
            "scope_kind": "album",
            "scope_value": planned["album"],
            "tier": sheet["tier"],
            "view": sheet["sheet_view"],
            "images": refs,
            "n": n,
            "character_id": character_id,
            "prompt": decided["pose"],
            "pose": decided["pose"],
            "wardrobe": sheet["wardrobe"],
            "anatomy": False,
            "source": "pose-gap",
            "job_kind": decided["kind"],
            "pose_label": decided["pose_label"],
            "render": c1_c2_render(decided),
        }, song_id=planned["song_id"])
        queued.append({
            "id": jid,
            "tier": sheet["tier"],
            "view": sheet["sheet_view"],
            "pose": sheet["pose"],
            "wardrobe": sheet["wardrobe"],
            "anatomy": False,
            "job_kind": decided["kind"],
            "pose_label": decided["pose_label"],
            "latent": decided["latent"],
        })
    planned["jobs"] = queued
    planned["queued"] = len(queued)
    return planned


def generate_one(song_id, pose, view, wardrobe, run_tiers, character_id=None,
                 n=4):
    """One hole, one wardrobe. Used when the operator picks nude vs clothed."""
    song = storyboard_service.require_song(song_id)
    album = (song["album"] or "").strip()
    if not album:
        raise ValueError("an album is needed to generate poses")
    names = _normalize_tiers(run_tiers)
    ceiling = max(names, key=_tier_rank)
    wardrobe = "nude" if (wardrobe or "").strip().lower() == "nude" else "clothed"
    if wardrobe == "nude" and not tiers.allows_nudity(ceiling):
        raise ValueError(f"{ceiling} cannot generate a nude sheet")
    pose = (pose or "").strip()
    view = (view or "").strip() or "front"
    if not pose:
        raise ValueError("name the pose to generate")
    sheet = {
        "pose": pose,
        "view": view,
        "sheet_view": sheet_view(view, wardrobe),
        "wardrobe": wardrobe,
        "tier": ceiling,
        "anatomy": False,
    }
    images = _album_images(album, character_id)
    keepers = classification.keepers(album, character_id)["images"]
    decided = resolve_c1_c2(sheet, keepers, images)
    refs = existing_images(decided["images"]) or existing_images(images)[:3]
    n = max(1, min(int(n or 4), 8))
    jid = jobs.enqueue("anchor", {
        "scope_kind": "album",
        "scope_value": album,
        "tier": sheet["tier"],
        "view": sheet["sheet_view"],
        "images": refs,
        "n": n,
        "character_id": character_id,
        "prompt": decided["pose"],
        "pose": decided["pose"],
        "wardrobe": sheet["wardrobe"],
        "anatomy": False,
        "source": "pose-gap",
        "job_kind": decided["kind"],
        "pose_label": decided["pose_label"],
        "render": c1_c2_render(decided),
    }, song_id=song["id"])
    return {
        "song_id": song["id"],
        "album": album,
        "tier": ceiling,
        "queued": 1,
        "jobs": [{
            "id": jid,
            "tier": sheet["tier"],
            "view": sheet["sheet_view"],
            "pose": sheet["pose"],
            "wardrobe": sheet["wardrobe"],
            "job_kind": decided["kind"],
        }],
    }
