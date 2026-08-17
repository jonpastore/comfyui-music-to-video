"""Named snapshots of a song+tier storyboard. File-backed, no FastAPI.

A new wording is a new version; restore copies that snapshot back onto
the live {slug}_{tier}.json / .md. Same idea as prompts.versions, scoped
to a song rather than an album.
"""
import json
import os
import time


def _dir(json_path, tier):
    return os.path.join(os.path.dirname(json_path), "versions", tier)


def _index_path(json_path, tier):
    return os.path.join(_dir(json_path, tier), "index.json")


def list_versions(json_path, tier):
    path = _index_path(json_path, tier)
    if not os.path.isfile(path):
        return []
    try:
        rows = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        return []
    return list(rows) if isinstance(rows, list) else []


def _write_index(json_path, tier, rows):
    dest = _dir(json_path, tier)
    os.makedirs(dest, exist_ok=True)
    with open(_index_path(json_path, tier), "w") as f:
        json.dump(rows, f, indent=1)


def snapshot(json_path, md_path, tier, label=""):
    """Copy the live board to the next version number."""
    if not json_path or not os.path.isfile(json_path):
        raise LookupError("no live storyboard to snapshot")
    rows = list_versions(json_path, tier)
    n = (max((r.get("n") or 0) for r in rows) + 1) if rows else 1
    dest = _dir(json_path, tier)
    os.makedirs(dest, exist_ok=True)
    jp = os.path.join(dest, f"v{n}.json")
    mp = os.path.join(dest, f"v{n}.md")
    with open(json_path) as src, open(jp, "w") as out:
        out.write(src.read())
    if md_path and os.path.isfile(md_path):
        with open(md_path) as src, open(mp, "w") as out:
            out.write(src.read())
    row = {"n": n, "label": (label or f"v{n}").strip()[:80],
           "created": time.time()}
    rows.append(row)
    _write_index(json_path, tier, rows)
    return row


def restore(json_path, md_path, tier, n, slug):
    """Write snapshot n back through grok.write_storyboard so json and md match."""
    rows = list_versions(json_path, tier)
    if not any(r.get("n") == n for r in rows):
        raise LookupError(f"no version {n}")
    src = os.path.join(_dir(json_path, tier), f"v{n}.json")
    if not os.path.isfile(src):
        raise LookupError(f"version {n} file is gone")
    sb = json.load(open(src))
    if not isinstance(sb, dict) or not isinstance(sb.get("scenes"), list):
        raise ValueError("version is not a storyboard")
    return _write(sb, os.path.dirname(json_path), slug, tier)


def delete(json_path, tier, n):
    rows = [r for r in list_versions(json_path, tier) if r.get("n") != n]
    dest = _dir(json_path, tier)
    for ext in (".json", ".md"):
        path = os.path.join(dest, f"v{n}{ext}")
        if os.path.isfile(path):
            os.remove(path)
    _write_index(json_path, tier, rows)
    return rows


def save_board(sb, outdir, slug, tier):
    """Validate and write a live board. Returns (json_path, md_path, scene_count)."""
    if not isinstance(sb, dict):
        raise ValueError("storyboard must be a JSON object")
    scenes = sb.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("storyboard needs a scenes list")
    if not str(sb.get("character_reference") or "").strip():
        raise ValueError("character_reference is required")
    jp, mp = _write(sb, outdir, slug, tier)
    return jp, mp, len(scenes)


def _write(sb, outdir, slug, tier):
    os.makedirs(outdir, exist_ok=True)
    base = os.path.join(outdir, f"{slug}_{tier}")
    jp, mp = base + ".json", base + ".md"
    with open(jp, "w") as f:
        json.dump(sb, f, indent=1)
    lines = ["# " + str(sb.get("title") or slug), ""]
    for s in sb.get("scenes") or []:
        lines.append(f"## {s.get('scene_number')}. {s.get('name') or ''}")
    with open(mp, "w") as f:
        f.write("\n".join(lines) + "\n")
    return jp, mp
