#!/usr/bin/env python3
"""T6-19: operator-confirmed clip cleanup after a clean assembled render.

T6-18 stays: lifecycle *writes* never delete. This module is an explicit
operator-confirmed job. Dry-run lists targets and writes nothing. Confirm
is a separate act from assemble — first assemble does not silent-confirm.

Deletes song+tier clip *files* only:
  - local host (or no host): os.remove at clips.path
  - remote host: only when a known SWARM_INPUT_DIRS input→output twin maps
    the path; delete via ssh to that staging target. No mapping → skip with
    reason, never pretend deleted, never invent a remote path, never SSH-guess.
Keeps anchors, refs, storyboards, the confirmed assembled file, QC findings
rows, and artefacts rows (status cleaned so findings still join — T6-9).

    python3 cleanup_service.py   # self-check against a temporary database
"""
import os
import shlex
import subprocess
import time

import db
import jobs
import models
import pipeline

# Clip rows after files are gone: path kept so findings still join; status
# names the operator act so a re-render can overwrite the row.
STATUS_CLEANED = "cleaned"


class UnconfirmedError(ValueError):
    """Cleanup refused because no operator-confirmed render exists."""


class ProtectedPathError(ValueError):
    """Cleanup refused because a target is a kept artefact (anchor/ref/…)."""


def _row(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return {k: row[k] for k in row.keys()}


def _canon(path):
    return jobs.canonical_path(path) if path else path


def require_song(song_id):
    song = db.one("SELECT * FROM songs WHERE id=?", song_id)
    if not song:
        raise LookupError(f"no such song: {song_id}")
    return song


def require_render(render_id):
    row = db.one("SELECT * FROM renders WHERE id=?", render_id)
    if not row:
        raise LookupError(f"no such render: {render_id}")
    return row


def require_set_asset(asset_id):
    row = db.one("SELECT * FROM assets WHERE id=? AND kind='set'", asset_id)
    if not row:
        raise LookupError(f"no such set render: {asset_id}")
    return row


def is_confirmed(row):
    """True only when the operator set confirmed=1. NULL/0 is unconfirmed."""
    if row is None:
        return False
    try:
        return int(row["confirmed"] or 0) == 1
    except (KeyError, TypeError, ValueError):
        return False


def confirm_render(render_id):
    """Mark one assembled song video as operator-confirmed clean.

    Separate from assemble: h_render_song never sets this. T6-19.
    """
    row = require_render(render_id)
    path = _canon(row["path"])
    if not path or not os.path.isfile(path):
        raise ValueError(f"cannot confirm missing assembled file: {path!r}")
    now = time.time()
    db.run("UPDATE renders SET confirmed=1, confirmed_at=? WHERE id=?",
           now, render_id)
    return _row(db.one("SELECT * FROM renders WHERE id=?", render_id))


def confirm_set_asset(asset_id):
    """Mark one set output as operator-confirmed clean. Separate from render."""
    row = require_set_asset(asset_id)
    path = _canon(row["path"])
    if not path or not os.path.isfile(path):
        raise ValueError(f"cannot confirm missing set file: {path!r}")
    now = time.time()
    db.run("UPDATE assets SET confirmed=1, confirmed_at=? WHERE id=?",
           now, asset_id)
    return _row(db.one("SELECT * FROM assets WHERE id=?", asset_id))


def confirmed_render(song_id, tier):
    """Newest operator-confirmed assembled song for song+tier, or None."""
    require_song(song_id)
    return db.one(
        """SELECT * FROM renders
           WHERE song_id=? AND tier=? AND confirmed=1
           ORDER BY id DESC LIMIT 1""",
        song_id, tier)


def keep_paths(song_id, tier):
    """Paths that cleanup must never delete (T6-19 KEEP list).

    Anchors (album-scoped), refs, storyboards, assembled renders for this
    song+tier. Findings are rows, not paths — they stay regardless.
    """
    kept = {}
    for r in db.q("SELECT path FROM renders WHERE song_id=? AND tier=?",
                  song_id, tier):
        p = _canon(r["path"])
        if p:
            kept[p] = "render"
    for r in db.q("SELECT path FROM refs WHERE song_id=? AND tier=?",
                  song_id, tier):
        p = _canon(r["path"])
        if p:
            kept[p] = "ref"
    for r in db.q(
            "SELECT json_path, md_path FROM storyboards WHERE song_id=? AND tier=?",
            song_id, tier):
        for key in ("json_path", "md_path"):
            p = _canon(r[key]) if r[key] else None
            if p:
                kept[p] = "storyboard"
    for r in db.q("SELECT path FROM anchors"):
        p = _canon(r["path"])
        if p:
            kept[p] = "anchor"
    song = db.one("SELECT mp3_path, style_path, anchor_path FROM songs WHERE id=?",
                  song_id)
    if song:
        for key in ("mp3_path", "style_path", "anchor_path"):
            p = _canon(song[key]) if song[key] else None
            if p:
                kept[p] = key
    return kept


def _artefact_for(path):
    """Only the recorded artefacts row. Never invent a host or remote path."""
    path = _canon(path)
    if not path:
        return None
    return db.one("SELECT path, host, via, backend, status FROM artefacts WHERE path=?",
                  path)


def is_local_host(host):
    """True when the file is this box's (or unattributed → treat as local path)."""
    if not host:
        return True
    box = models.canonical_host(host)
    if not box or box == models.SELF_HOST:
        return True
    return False


def swarm_input_dest_for(host):
    """Known SWARM_INPUT_DIRS entry for host, or None.

    Returns (ssh_target, remote_input_base) exactly as configured — never
    invents a host root. Same rsync destinations install_input uses.
    """
    box = models.canonical_host(host) if host else None
    if not box:
        return None
    for dest in pipeline.SWARM_INPUT_DIRS:
        if ":" not in dest:
            continue
        left, remote_base = dest.split(":", 1)
        h = left.split("@")[-1].strip()
        if models.canonical_host(h) == box:
            return left.strip(), remote_base.rstrip("/")
    return None


def remote_output_twin(path, host):
    """Known remote output twin for path on host, or None.

    Twin mapping only: SWARM_INPUT_DIRS input base ending in /input → sibling
    /output, plus the path's relative position under pipeline.COMFY_OUTPUT.
    No mapping, path not under COMFY_OUTPUT, or non-/input base → None.
    Never invents a remote path outside that twin.
    """
    if is_local_host(host):
        return None
    entry = swarm_input_dest_for(host)
    if not entry:
        return None
    ssh_target, input_base = entry
    if not input_base.endswith("/input"):
        return None
    remote_output_root = input_base[: -len("input")] + "output"
    local_out = _canon(pipeline.COMFY_OUTPUT)
    local_path = _canon(path)
    if not local_out or not local_path:
        return None
    if local_path != local_out and not local_path.startswith(local_out + os.sep):
        return None
    rel = "" if local_path == local_out else local_path[len(local_out) + 1:]
    if not rel or ".." in rel.split(os.sep):
        return None
    remote_path = remote_output_root + "/" + rel.replace(os.sep, "/")
    return {
        "ssh_target": ssh_target,
        "remote_path": remote_path,
        "input_base": input_base,
    }


def classify_target(path, host):
    """Plan fields for one clip: remote / can_delete / reason.

    Local host → can_delete via os.remove. Remote → can_delete only when a
    known input→output twin exists; otherwise skip with a named reason.
    """
    path = _canon(path)
    remote = not is_local_host(host)
    if not remote:
        return {
            "remote": False,
            "can_delete": True,
            "reason": "local os.remove",
            "remote_path": None,
            "ssh_target": None,
        }
    twin = remote_output_twin(path, host)
    if twin:
        return {
            "remote": True,
            "can_delete": True,
            "reason": "remote twin via SWARM_INPUT_DIRS",
            "remote_path": twin["remote_path"],
            "ssh_target": twin["ssh_target"],
        }
    if not swarm_input_dest_for(host):
        reason = f"no known path mapping for host {host}"
    else:
        reason = (
            f"no output twin for path under COMFY_OUTPUT on host {host}"
        )
    return {
        "remote": True,
        "can_delete": False,
        "reason": reason,
        "remote_path": None,
        "ssh_target": None,
    }


def _remote_remove(ssh_target, remote_path):
    """Delete one remote file via the same host target install_input stages to.

    ssh_target is the left side of a SWARM_INPUT_DIRS entry (user@host or host).
    remote_path must already be a known twin — never constructed here.
    OpenSSH runs the remote argv through a shell, so the path is one quoted
    command — unquoted argv is injection (`;`, backticks, spaces).
    """
    if not ssh_target or not remote_path:
        raise ValueError("refusing remote delete without known target and path")
    if remote_path.endswith("/") or remote_path in (".", ".."):
        raise ValueError(f"refusing unsafe remote path: {remote_path!r}")
    if "\n" in remote_path or "\r" in remote_path or "\x00" in remote_path:
        raise ValueError(f"refusing unsafe remote path: {remote_path!r}")
    remote_cmd = f"rm -f -- {shlex.quote(remote_path)}"
    subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
         ssh_target, remote_cmd],
        check=True, capture_output=True, text=True, timeout=120,
    )


def _clip_targets(song_id, tier):
    """Known delete targets for song+tier clips. artefacts.host/path only."""
    rows = db.q(
        """SELECT clip_idx, path, status FROM clips
           WHERE song_id=? AND tier=? AND path IS NOT NULL AND path != ''
           ORDER BY clip_idx""",
        song_id, tier)
    kept = keep_paths(song_id, tier)
    targets = []
    for r in rows:
        path = _canon(r["path"])
        if not path:
            continue
        kind = kept.get(path)
        if kind:
            raise ProtectedPathError(
                f"clip path is a kept {kind}, not a deletable clip: {path}")
        art = _artefact_for(path)
        host = art["host"] if art else None
        cls = classify_target(path, host)
        # Twin only when artefacts already records the same path (no invent).
        # studio path and ComfyUI/output path are the same key when one file
        # was landed; two spellings collapse via jobs.canonical_path (T6-8).
        targets.append({
            "clip_idx": r["clip_idx"],
            "path": path,
            "host": host,
            "via": art["via"] if art else None,
            "backend": art["backend"] if art else None,
            "exists": os.path.isfile(path),
            "artefact": bool(art),
            "remote": cls["remote"],
            "can_delete": cls["can_delete"],
            "reason": cls["reason"],
            "remote_path": cls["remote_path"],
            "ssh_target": cls["ssh_target"],
        })
    return targets, kept


def plan_clip_cleanup(song_id, tier):
    """Dry-run listing. Requires a confirmed render; writes nothing.

    Unconfirmed refuses. Dest ≠ src discipline is N/A here (delete-after-
    confirm, not overwrite) — kept assembled path is excluded from targets.
    Each would_delete entry carries path, host, remote, can_delete, reason.
    """
    require_song(song_id)
    conf = confirmed_render(song_id, tier)
    if not conf:
        raise UnconfirmedError(
            f"no operator-confirmed render for song {song_id} tier {tier!r}; "
            f"confirm the assembled file before cleanup")
    targets, kept = _clip_targets(song_id, tier)
    assembled = _canon(conf["path"])
    return {
        "song_id": song_id,
        "tier": tier,
        "dry_run": True,
        "confirmed_render_id": conf["id"],
        "confirmed_path": assembled,
        "would_delete": targets,
        "keep": [{"path": p, "kind": k} for p, k in sorted(kept.items())],
        "n_clips": len(targets),
        "n_existing": sum(1 for t in targets if t["exists"]),
        "n_can_delete": sum(1 for t in targets if t["can_delete"]),
        "n_remote_skip": sum(
            1 for t in targets if t["remote"] and not t["can_delete"]),
    }


def run_clip_cleanup(song_id, tier, *, dry_run=True):
    """List (dry_run=True, default) or delete clip files for song+tier.

    dry_run=True is the only default. Explicit dry_run=False is required to
    remove files. Never deletes anchors/refs/storyboards/assembled; never
    deletes findings rows. Artefacts rows stay (status cleaned) so findings
    still join on path (T6-9); the file is what is gone.

    Local host: os.remove. Remote host: only a known twin path via
    SWARM_INPUT_DIRS; otherwise skip with reason and leave the file.
    """
    plan = plan_clip_cleanup(song_id, tier)
    if dry_run:
        # Reaffirm: dry-run writes nothing (no status flips, no deletes).
        return plan

    kept = keep_paths(song_id, tier)
    assembled = plan["confirmed_path"]
    deleted = []
    skipped_missing = []
    skipped_remote = []
    for t in plan["would_delete"]:
        path = t["path"]
        if path == assembled or path in kept:
            raise ProtectedPathError(
                f"refusing to delete kept path: {path}")
        if not t["can_delete"]:
            # Remote without a known twin: do not pretend deleted.
            skipped_remote.append({
                "path": path,
                "host": t["host"],
                "reason": t["reason"],
            })
            continue
        if t["remote"]:
            # Known twin only — classify_target already refused invents.
            _remote_remove(t["ssh_target"], t["remote_path"])
            if os.path.isfile(path):
                os.remove(path)
            deleted.append(path)
        elif os.path.isfile(path):
            os.remove(path)
            deleted.append(path)
        else:
            skipped_missing.append(path)
        # Clip row: status cleaned; path kept for findings join.
        db.run(
            """UPDATE clips SET status=? WHERE song_id=? AND tier=? AND clip_idx=?""",
            STATUS_CLEANED, song_id, tier, t["clip_idx"])
        # Keep artefacts row; mark cleaned. Findings join path (T6-9).
        if t["artefact"]:
            db.run("UPDATE artefacts SET status=? WHERE path=?",
                   STATUS_CLEANED, path)

    out = dict(plan)
    out["dry_run"] = False
    out["deleted"] = deleted
    out["skipped_missing"] = skipped_missing
    out["skipped_remote"] = skipped_remote
    out["n_deleted"] = len(deleted)
    out["n_skipped_remote"] = len(skipped_remote)
    return out


def enqueue_cleanup(song_id, tier, *, dry_run=True):
    """Queue a cleanup_clips job. Default remains dry-run."""
    require_song(song_id)
    if not dry_run and not confirmed_render(song_id, tier):
        raise UnconfirmedError(
            f"no operator-confirmed render for song {song_id} tier {tier!r}")
    return jobs.enqueue(
        "cleanup_clips",
        {"song_id": song_id, "tier": tier, "dry_run": bool(dry_run)},
        song_id=song_id)


# ---------------------------------------------------------------------------
# job handler — registered when app imports this module or on first use
# ---------------------------------------------------------------------------

def h_cleanup_clips(args, progress):
    """Job body. dry_run defaults True even if the key is omitted."""
    sid = int(args["song_id"])
    tier = args["tier"]
    dry = args.get("dry_run", True)
    if dry is None:
        dry = True
    progress(f"cleanup song={sid} tier={tier} dry_run={bool(dry)}")
    out = run_clip_cleanup(sid, tier, dry_run=bool(dry))
    if out.get("dry_run"):
        progress(f"dry-run: would delete {out['n_clips']} clip(s), "
                 f"{out['n_existing']} on disk, "
                 f"{out.get('n_can_delete', 0)} can_delete, "
                 f"{out.get('n_remote_skip', 0)} remote skip")
    else:
        progress(f"deleted {out.get('n_deleted', 0)} clip file(s), "
                 f"remote-skipped {out.get('n_skipped_remote', 0)}")
    return out


def _ensure_handler():
    if "cleanup_clips" not in jobs._handlers:
        jobs.handler("cleanup_clips")(h_cleanup_clips)


_ensure_handler()


if __name__ == "__main__":
    import tempfile

    data = tempfile.mkdtemp(prefix="cleanup_self_")
    db.DATA = data
    db.DB_PATH = os.path.join(data, "t.db")
    db._local.__dict__.clear()
    jobs.LOGS = os.path.join(data, "logs")

    sid = db.upsert_song("selfcheck", title="Self", duration=10.0)
    clip = os.path.join(data, "clip_000.mp4")
    render = os.path.join(data, "assembled.mp4")
    open(clip, "wb").write(b"clip")
    open(render, "wb").write(b"render")
    db.run("INSERT INTO clips (song_id, tier, clip_idx, path, status) VALUES (?,?,?,?,?)",
           sid, "r", 0, clip, "done")
    rid = db.run(
        "INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
        sid, "r", render, time.time())
    try:
        plan_clip_cleanup(sid, "r")
        raise SystemExit("unconfirmed should refuse")
    except UnconfirmedError:
        pass
    confirm_render(rid)
    plan = plan_clip_cleanup(sid, "r")
    assert plan["dry_run"] and plan["n_clips"] == 1 and os.path.isfile(clip)
    assert plan["would_delete"][0]["can_delete"] is True
    assert plan["would_delete"][0]["remote"] is False
    run_clip_cleanup(sid, "r", dry_run=False)
    assert not os.path.isfile(clip) and os.path.isfile(render)
    print("cleanup_service self-check ok")
