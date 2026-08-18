#!/usr/bin/env python3
"""Move experiment trees into deprecated/<stamp>/. Never deletes.

    python3 scripts/deprecate.py 2026-08-16-pose-grind path [path...]
    python3 scripts/deprecate.py --list

Writes deprecated/<stamp>/MANIFEST.md (src → dest). Restore with mv
from the dest column back to src. After you verify, rm -rf that folder.

Spent one-off (already ran): the 2026-08-16 pose-grind path list lived
in scripts/deprecate_pose_junk.py. Use this instead of a new dated copy.
"""
from __future__ import annotations

import argparse
import shutil
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEPRECATED = REPO / "deprecated"


def dest_for(stamp: str) -> Path:
    return DEPRECATED / stamp


def move(src: Path, dest_root: Path, rel: str, rows: list) -> None:
    src = src.resolve()
    if not src.exists():
        rows.append((str(src), "(missing)", "skip"))
        return
    target = dest_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        rows.append((str(src), str(target), "exists"))
        return
    shutil.move(str(src), str(target))
    rows.append((str(src), str(target), "moved"))


def write_manifest(dest: Path, rows: list, note: str) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    man = dest / "MANIFEST.md"
    lines = [
        f"# {dest.name}",
        "",
        note,
        "",
        f"Moved {date.today().isoformat()}. Restore: `mv <dest> <src>`.",
        "",
        "| src | dest | status |",
        "|---|---|---|",
    ]
    for src, dst, status in rows:
        lines.append(f"| `{src}` | `{dst}` | {status} |")
    lines.append("")
    man.write_text("\n".join(lines))
    return man


def list_batches() -> None:
    if not DEPRECATED.is_dir():
        print("no deprecated/ yet")
        return
    for p in sorted(DEPRECATED.iterdir()):
        if p.is_dir() and p.name != "__pycache__":
            man = p / "MANIFEST.md"
            print(p.name, "manifest" if man.is_file() else "no-manifest")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stamp", nargs="?", help="dated folder name, e.g. 2026-08-16-pose-grind")
    ap.add_argument("paths", nargs="*", help="files or directories to move")
    ap.add_argument("--list", action="store_true", help="list deprecated/ batches")
    args = ap.parse_args()
    if args.list:
        list_batches()
        return
    if not args.stamp or not args.paths:
        raise SystemExit("usage: deprecate.py STAMP path [path...]  |  deprecate.py --list")
    dest = dest_for(args.stamp)
    rows = []
    for raw in args.paths:
        src = Path(raw)
        if not src.is_absolute():
            src = (REPO / src).resolve()
        move(src, dest, src.name, rows)
    man = write_manifest(dest, rows, "operator deprecate")
    print(man.read_text())


if __name__ == "__main__":
    main()
