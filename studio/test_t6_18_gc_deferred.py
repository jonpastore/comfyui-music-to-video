"""T6-18 honesty: GC is deferred by name; lifecycle re-render keeps predecessor.

docs/TRD-6 §6 / §7 / Status. Do not implement GC here. Positive halves that
must stay green without a GC job:
  TRD names **No automatic GC** under Explicitly not building
  Status marks `T6-18` **deferred** with GC out of scope named
  a set re-render leaves the predecessor file (reachability via T6-A5)
"""
import os
import tempfile
import time
from pathlib import Path

import db
import jobs


TRD = Path(__file__).resolve().parents[1] / "docs" / "TRD-6-QUEUE-LIFECYCLE-AND-STORAGE.md"


def _isolate():
    data = tempfile.mkdtemp(prefix="t618_")
    db.DATA = data
    db.DB_PATH = os.path.join(data, "t.db")
    db._local.__dict__.clear()
    jobs.LOGS = os.path.join(data, "logs")
    return data


def test_t6_18_trd_names_gc_deferred():
    text = TRD.read_text()
    assert "**No automatic GC.**" in text, (
        "TRD-6 §7 must name No automatic GC so absence of deletes is not "
        "read as storage working")
    assert "No automatic GC" in text.split("## 7. Explicitly not building", 1)[1].split(
        "## 8.", 1)[0], text
    status = text.split("## Status against the tree", 1)[1]
    assert "`T6-18`" in status and "**deferred**" in status, status
    row = [ln for ln in status.splitlines() if "`T6-18`" in ln]
    assert row, status
    assert "**deferred**" in row[0], row[0]
    assert "GC" in row[0] or "No automatic GC" in row[0], row[0]


def test_t6_18_rerender_leaves_predecessor_file(monkeypatch):
    """Lifecycle non-delete / predecessor reachability via T6-A5 set re-render."""
    import app as appmod

    data = _isolate()

    def _mix(items, out, progress=None):
        parent = os.path.dirname(out)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out, "wb") as f:
            f.write(b"ID3-mix")

    monkeypatch.setattr(appmod.mixer, "mix_audio", _mix)
    monkeypatch.setattr(appmod.mixer, "export_loudness",
                        lambda *a, **k: {"i": -14.0, "tp": -1.0, "ok": True})

    mp3 = os.path.join(data, "t618.mp3")
    with open(mp3, "wb") as f:
        f.write(b"ID3")
    sid = db.upsert_song("t618-set", title="T6-18 Set", mp3_path=mp3, duration=12.3)
    set_id = db.run(
        "INSERT INTO sets (name, created, updated, mode) VALUES (?,?,?,?)",
        "t618", time.time(), time.time(), "audio")
    db.run("INSERT INTO set_items (set_id, song_id, position, transition, secs) "
           "VALUES (?,?,?,?,?)", set_id, sid, 0, "cut", 0.0)
    items = [{"audio": mp3, "transition": "cut", "secs": 0}]
    first = appmod.h_render_set(
        {"set_id": set_id, "mode": "audio", "items": items}, lambda m: None)
    second = appmod.h_render_set(
        {"set_id": set_id, "mode": "audio", "items": items}, lambda m: None)
    pred = jobs.canonical_path(first["path"])
    succ = jobs.canonical_path(second["path"])
    assert pred != succ, (pred, succ)
    assert os.path.isfile(pred), (
        "re-render deleted or overwrote the predecessor; T6-18/T6-A5 require "
        f"both files: pred={pred!r} succ={succ!r}")
    assert os.path.isfile(succ), succ
