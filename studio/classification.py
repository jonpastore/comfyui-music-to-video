"""T4-21 / T4-22: album pose library as versioned classification_json.

The sqlite document is the store. Sidecars may seed an import; they are
not the runtime source. character_id NULL is the protagonist.
No FastAPI.
"""
import json
import os
import time

import db

IMAGE_FIELDS = ("id", "path", "kind", "view", "pose", "wardrobe", "usable",
                "notes", "seed")
REQUIRED_IMAGE_FIELDS = ("id", "path", "kind", "view", "pose", "wardrobe",
                         "usable")
QUERY_FIELDS = ("view", "pose", "wardrobe", "usable")

# Repo-root sidecar used only by ensure_sidecar_seed / import_sidecar.
# library() never reads this path.
_DEFAULT_SIDECAR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "anchor5", "image-classification.json")


def _character_id(character_id):
    return int(character_id) if character_id else None


def _album(album):
    album = (album or "").strip()
    if not album:
        raise ValueError("an album is needed to store classification")
    return album


def _parse_document(document):
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except json.JSONDecodeError as e:
            raise ValueError(f"classification document is not JSON: {e}") from e
    if not isinstance(document, dict):
        raise ValueError("classification document must be a JSON object")
    images = document.get("images")
    if not isinstance(images, list):
        raise ValueError("classification document needs an images list")
    cleaned = []
    for i, raw in enumerate(images):
        if not isinstance(raw, dict):
            raise ValueError(f"images[{i}] must be an object")
        missing = [k for k in REQUIRED_IMAGE_FIELDS if not str(raw.get(k) or "").strip()]
        if missing:
            raise ValueError(f"images[{i}] missing {', '.join(missing)}")
        item = {k: raw[k] for k in IMAGE_FIELDS if k in raw}
        item["id"] = str(item["id"]).strip()
        item["path"] = str(item["path"]).strip()
        item["kind"] = str(item["kind"]).strip()
        item["view"] = str(item["view"]).strip()
        item["pose"] = str(item["pose"]).strip()
        item["wardrobe"] = str(item["wardrobe"]).strip()
        item["usable"] = str(item["usable"]).strip()
        if "notes" in item and item["notes"] is not None:
            item["notes"] = str(item["notes"])
        cleaned.append(item)
    out = dict(document)
    out["images"] = cleaned
    return out


def _payload(row):
    document = json.loads(row["document_json"])
    return {
        "id": row["id"],
        "album": row["album"],
        "character_id": row["character_id"],
        "version_number": row["version_number"],
        "created": row["created"],
        "document": document,
        "images": list(document.get("images") or []),
    }


def versions(album, character_id=None):
    """Saved versions for this album+character, newest first. Numbers stay."""
    album = _album(album)
    character_id = _character_id(character_id)
    rows = db.q(
        """SELECT id, album, character_id, version_number, created
           FROM classification_json
           WHERE album=? AND character_id IS ?
           ORDER BY version_number DESC""",
        album, character_id)
    return [{k: r[k] for k in r.keys()} for r in rows]


def latest(album, character_id=None):
    """Newest stored document, or None."""
    album = _album(album)
    character_id = _character_id(character_id)
    row = db.one(
        """SELECT * FROM classification_json
           WHERE album=? AND character_id IS ?
           ORDER BY version_number DESC LIMIT 1""",
        album, character_id)
    return _payload(row) if row else None


def library(album, character_id=None):
    """Runtime album library. Reads sqlite only — never a sidecar file."""
    album = _album(album)
    character_id = _character_id(character_id)
    row = latest(album, character_id)
    if row:
        return row
    return {
        "id": None,
        "album": album,
        "character_id": character_id,
        "version_number": None,
        "created": None,
        "document": None,
        "images": [],
    }


def _is_skip(image):
    return (image.get("usable") or "").strip().lower() == "skip"


def _paths_match(stored, given):
    stored = str(stored or "").strip()
    given = str(given or "").strip()
    if not stored or not given:
        return False
    if stored == given:
        return True
    return os.path.abspath(stored) == os.path.abspath(given)


def _classified_image(album, path=None, image_id=None, character_id=None):
    """Latest classification row matching path or id, or None."""
    if not (album or "").strip():
        return None
    want_id = str(image_id or "").strip()
    want_path = str(path or "").strip()
    if not want_id and not want_path:
        return None
    for im in library(album, character_id)["images"]:
        if want_id and str(im.get("id") or "").strip() == want_id:
            return im
        if want_path and _paths_match(im.get("path"), want_path):
            return im
    return None


def refuse_skip(album, path=None, image_id=None, character_id=None):
    """T7-23: usable=skip never enters use-as-ref / map / image1."""
    image = _classified_image(album, path=path, image_id=image_id,
                              character_id=character_id)
    if image is not None and _is_skip(image):
        slot = (image.get("id") or image.get("path") or "image").strip()
        raise ValueError(
            f"usable=skip cannot enter use-as-ref / map / image1 ({slot})")


def keepers(album, character_id=None):
    """Library images that may cover a board need. usable=skip never covers."""
    lib = library(album, character_id)
    lib["images"] = [im for im in lib["images"] if not _is_skip(im)]
    return lib


def query(album, character_id=None, view=None, pose=None, wardrobe=None,
          usable=None):
    """Images from the latest DB document, filtered by the given fields."""
    lib = library(album, character_id)
    images = list(lib["images"])
    filters = {
        "view": (view or "").strip(),
        "pose": (pose or "").strip(),
        "wardrobe": (wardrobe or "").strip(),
        "usable": (usable or "").strip(),
    }
    for field, want in filters.items():
        if want:
            images = [im for im in images if im.get(field) == want]
    lib["images"] = images
    lib["filters"] = {k: v for k, v in filters.items() if v}
    return lib


def save(album, document, character_id=None):
    """A new version. Prior versions stay; numbers are not reused."""
    album = _album(album)
    character_id = _character_id(character_id)
    document = _parse_document(document)
    row = db.one(
        """SELECT MAX(version_number) AS n FROM classification_json
           WHERE album=? AND character_id IS ?""",
        album, character_id)
    number = (row["n"] or 0) + 1
    now = time.time()
    vid = db.run(
        """INSERT INTO classification_json
           (album, character_id, version_number, document_json, created)
           VALUES (?,?,?,?,?)""",
        album, character_id, number, json.dumps(document), now)
    stored = db.one("SELECT * FROM classification_json WHERE id=?", vid)
    return _payload(stored)


def add_keeper(album, image, character_id=None):
    """Append or replace one keeper. New version. No GPU."""
    parsed = _parse_document({"images": [image]})["images"][0]
    images = list(library(album, character_id)["images"])
    images = [
        im for im in images
        if im.get("id") != parsed["id"]
        and not (
            im.get("pose") == parsed["pose"]
            and im.get("view") == parsed["view"]
            and im.get("wardrobe") == parsed["wardrobe"]
        )
    ]
    images.append(parsed)
    return save(album, {"images": images}, character_id)


def tag_from_anchors(album, character_id=None):
    """Mark this album's chosen sheets as keepers. No sidecar, no GPU."""
    import make_anchor
    album = _album(album)
    rows = db.q(
        """SELECT * FROM anchors
           WHERE scope_value=? AND chosen=1 ORDER BY id""",
        album)
    images = []
    for row in rows:
        path = (row["path"] or "").strip()
        if not path:
            continue
        meta = db.jset(row, "render_json")
        view = (row["view"] or "front").strip() or "front"
        wardrobe = "nude" if make_anchor.is_nude_view(view) else "clothed"
        pose = (meta.get("pose_name") or view).strip() or view
        images.append({
            "id": f"anchor-{row['id']}",
            "path": path,
            "kind": "operator",
            "view": view,
            "pose": pose,
            "wardrobe": wardrobe,
            "usable": "pose",
        })
    if not images:
        raise ValueError("this album has no chosen sheets to tag")
    return save(album, {"images": images}, character_id)


def import_sidecar(album, path, character_id=None):
    """Seed a new version from a sidecar file. Not the runtime source."""
    album = _album(album)
    path = (path or "").strip()
    if not path:
        raise ValueError("a sidecar path is needed to import")
    if not os.path.isfile(path):
        raise LookupError(f"no sidecar at {path}")
    try:
        raw = json.load(open(path))
    except json.JSONDecodeError as e:
        raise ValueError(f"sidecar is not JSON: {e}") from e
    return save(album, raw, character_id)


def ensure_sidecar_seed(album, path=None):
    """If library images are empty and a sidecar exists, import once.

    Default path is repo `anchor5/image-classification.json`. Does not teach
    `library()` to read a file — seeding goes through `import_sidecar`.
    """
    album = _album(album)
    lib = library(album)
    if lib["images"]:
        return lib
    side = _DEFAULT_SIDECAR if path is None else path
    side = (side or "").strip()
    if not side or not os.path.isfile(side):
        return lib
    return import_sidecar(album, side)
