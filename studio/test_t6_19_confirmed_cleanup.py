"""T6-19: operator-confirmed clip cleanup after a clean assembled render.

docs/TRD-6 §6. T6-18 stays: lifecycle writes never delete. This criterion
is an explicit confirm + dry-run + delete job.

Positive halves:
  dry-run lists clips (path, host, remote, can_delete, reason) and deletes none
  confirm + run deletes local clips and keeps anchors/refs/storyboard/assembled
  remote without known twin mapping is skipped, not deleted
  unconfirmed refuses

Mutations that must go red:
  skip dry-run default (dry_run=False by default)
  delete an anchor path as if it were a clip
  treating unknown remote host as local delete
"""
import inspect
import os
import shlex
import tempfile
import time

import pytest

import cleanup_service
import db
import jobs
import models
import mutation_read
import pipeline


def _isolate():
    data = tempfile.mkdtemp(prefix="t619_")
    db.DATA = data
    db.DB_PATH = os.path.join(data, "t.db")
    db._local.__dict__.clear()
    jobs.LOGS = os.path.join(data, "logs")
    cleanup_service._ensure_handler()
    return data


def _write(path, blob=b"x"):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(blob)
    return path


def _fixture(data, *, with_anchor=True, n_clips=2, remote_host=None):
    """Song + tier with assembled render, clips, ref, storyboard, optional anchor.

    Clips land on this box (SELF_HOST) unless remote_host is set for clip 1 —
    that clip exercises the remote-without-mapping skip path.
    """
    sid = db.upsert_song("t619", title="T6-19 Song", duration=12.3)
    tier = "r"
    now = time.time()
    assembled = _write(os.path.join(data, "renders", "t619_r.mp4"), b"assembled")
    rid = db.run(
        "INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
        sid, tier, assembled, now)
    clips = []
    for i in range(n_clips):
        # One under studio data, one under a ComfyUI/output-shaped path so both
        # recorded locations are exercised. Never invent remote paths.
        if i == 0:
            p = _write(os.path.join(data, "clips", f"clip_{i:03d}.mp4"),
                       f"clip{i}".encode())
            host = models.SELF_HOST
            via = "comfy"
        else:
            p = _write(os.path.join(data, "ComfyUI", "output", "t619",
                                    f"clip_{i:03d}.mp4"),
                       f"clip{i}".encode())
            host = remote_host if remote_host else models.SELF_HOST
            via = "swarm" if remote_host else "comfy"
        db.run("""INSERT INTO clips (song_id, tier, clip_idx, path, status)
                  VALUES (?,?,?,?,?)""", sid, tier, i, p, "done")
        jobs.land(p, host=host, via=via)
        clips.append(p)
    ref = _write(os.path.join(data, "refs", "ref_000.png"), b"ref")
    db.run("""INSERT INTO refs (song_id, tier, clip_idx, path, seed, created)
              VALUES (?,?,?,?,?,?)""", sid, tier, 0, ref, 1, now)
    sb_json = _write(os.path.join(data, "storyboards", "t619_r.json"), b"{}")
    sb_md = _write(os.path.join(data, "storyboards", "t619_r.md"), b"# sb")
    db.run("""INSERT INTO storyboards (song_id, tier, json_path, md_path,
                                       scene_count, created)
              VALUES (?,?,?,?,?,?)""", sid, tier, sb_json, sb_md, 1, now)
    anchor = None
    if with_anchor:
        anchor = _write(os.path.join(data, "anchors", "front.png"), b"anchor")
        db.run("""INSERT INTO anchors (scope_kind, scope_value, tier, view, path,
                                       chosen, created)
                  VALUES (?,?,?,?,?,1,?)""",
               "album", "Street Cats", tier, "front", anchor, now)
    # A finding on a clip so T6-9 / do-not-orphan is exerciseable.
    finding_path = jobs.canonical_path(clips[0])
    db.run("""INSERT INTO findings
                (path, kind, tier, check_name, verdict, status, created)
              VALUES (?,?,?,?,?,?,?)""",
           finding_path, "clip", 1, "size_floor", "flag", "open", now)
    return {
        "song_id": sid, "tier": tier, "render_id": rid,
        "assembled": assembled, "clips": clips, "ref": ref,
        "sb_json": sb_json, "sb_md": sb_md, "anchor": anchor,
        "finding_path": finding_path,
    }


def test_t6_19_assemble_does_not_silent_confirm():
    """First assemble leaves confirmed=0/NULL. Silent confirm is the defect."""
    data = _isolate()
    fx = _fixture(data)
    row = db.one("SELECT * FROM renders WHERE id=?", fx["render_id"])
    assert not cleanup_service.is_confirmed(row), row
    assert cleanup_service.confirmed_render(fx["song_id"], fx["tier"]) is None


def test_t6_19_unconfirmed_refuses_cleanup():
    """Unconfirmed assembled render refuses plan and run."""
    data = _isolate()
    fx = _fixture(data)
    with pytest.raises(cleanup_service.UnconfirmedError, match="confirm"):
        cleanup_service.plan_clip_cleanup(fx["song_id"], fx["tier"])
    with pytest.raises(cleanup_service.UnconfirmedError, match="confirm"):
        cleanup_service.run_clip_cleanup(fx["song_id"], fx["tier"], dry_run=False)
    for p in fx["clips"]:
        assert os.path.isfile(p), "unconfirmed refuse must not delete clips"


def test_t6_19_dry_run_lists_clips_and_deletes_none():
    """Dry-run lists path/host/remote/can_delete/reason and writes nothing."""
    data = _isolate()
    fx = _fixture(data)
    cleanup_service.confirm_render(fx["render_id"])
    plan = cleanup_service.run_clip_cleanup(
        fx["song_id"], fx["tier"], dry_run=True)
    assert plan["dry_run"] is True
    assert plan["n_clips"] == 2, plan
    listed = {t["path"] for t in plan["would_delete"]}
    for p in fx["clips"]:
        assert jobs.canonical_path(p) in listed
    for t in plan["would_delete"]:
        assert "path" in t and "host" in t
        assert "remote" in t and "can_delete" in t and "reason" in t
        assert t["remote"] is False
        assert t["can_delete"] is True
        assert t["host"]  # artefacts.host recorded; never invent beyond it
    for p in fx["clips"]:
        assert os.path.isfile(p), "dry-run deleted a clip"
    assert os.path.isfile(fx["assembled"])
    assert os.path.isfile(fx["ref"])
    assert os.path.isfile(fx["sb_json"])
    assert os.path.isfile(fx["anchor"])
    # No status flip on dry-run.
    rows = db.q("SELECT status FROM clips WHERE song_id=?", fx["song_id"])
    assert all(r["status"] == "done" for r in rows), rows


def test_t6_19_confirm_and_run_deletes_local_clips_keeps_rest():
    """Confirm + dry_run=False deletes local clips; keeps assembled/refs/sb/anchor."""
    data = _isolate()
    fx = _fixture(data)
    cleanup_service.confirm_render(fx["render_id"])
    out = cleanup_service.run_clip_cleanup(
        fx["song_id"], fx["tier"], dry_run=False)
    assert out["dry_run"] is False
    assert out["n_deleted"] == 2, out
    assert out.get("n_skipped_remote", 0) == 0
    for p in fx["clips"]:
        assert not os.path.isfile(p), f"clip still present: {p}"
    assert os.path.isfile(fx["assembled"]), "assembled file was deleted"
    assert os.path.isfile(fx["ref"]), "ref was deleted"
    assert os.path.isfile(fx["sb_json"]), "storyboard json was deleted"
    assert os.path.isfile(fx["sb_md"]), "storyboard md was deleted"
    assert os.path.isfile(fx["anchor"]), "anchor was deleted"
    # Render still confirmed and listed.
    conf = cleanup_service.confirmed_render(fx["song_id"], fx["tier"])
    assert conf is not None and conf["id"] == fx["render_id"]
    assert conf["path"] and os.path.isfile(conf["path"])
    # Findings not orphaned: row still there and joins artefacts (T6-9).
    f = db.one("SELECT * FROM findings WHERE path=?", fx["finding_path"])
    assert f is not None and f["check_name"] == "size_floor"
    joined = db.one(
        """SELECT f.id FROM findings f JOIN artefacts a ON a.path = f.path
           WHERE f.path=?""", fx["finding_path"])
    assert joined, "findings orphaned from artefacts after cleanup"
    art = db.one("SELECT status FROM artefacts WHERE path=?", fx["finding_path"])
    assert art["status"] == cleanup_service.STATUS_CLEANED
    # Clip rows marked cleaned; path kept for findings join.
    clips = db.q("SELECT * FROM clips WHERE song_id=? ORDER BY clip_idx",
                 fx["song_id"])
    assert all(r["status"] == cleanup_service.STATUS_CLEANED for r in clips)
    assert all(r["path"] for r in clips)


def test_t6_19_remote_without_mapping_is_skipped_not_deleted(monkeypatch):
    """Remote host with no SWARM_INPUT_DIRS twin: skip, leave file, no cleaned."""
    data = _isolate()
    remote = "100.107.235.105"
    fx = _fixture(data, remote_host=remote)
    # No twin mapping configured — refuse remote delete by name.
    monkeypatch.setattr(pipeline, "SWARM_INPUT_DIRS", [])
    cleanup_service.confirm_render(fx["render_id"])
    plan = cleanup_service.plan_clip_cleanup(fx["song_id"], fx["tier"])
    by_idx = {t["clip_idx"]: t for t in plan["would_delete"]}
    assert by_idx[0]["remote"] is False and by_idx[0]["can_delete"] is True
    assert by_idx[1]["remote"] is True and by_idx[1]["can_delete"] is False
    assert "no known path mapping" in by_idx[1]["reason"]
    assert by_idx[1]["host"] == remote

    out = cleanup_service.run_clip_cleanup(
        fx["song_id"], fx["tier"], dry_run=False)
    assert out["n_deleted"] == 1, out
    assert out["n_skipped_remote"] == 1
    assert not os.path.isfile(fx["clips"][0]), "local clip should be gone"
    assert os.path.isfile(fx["clips"][1]), "remote-unmapped clip must remain"
    # Skipped remote stays status done (not cleaned) — do not pretend deleted.
    rows = {r["clip_idx"]: r for r in db.q(
        "SELECT clip_idx, status FROM clips WHERE song_id=?", fx["song_id"])}
    assert rows[0]["status"] == cleanup_service.STATUS_CLEANED
    assert rows[1]["status"] == "done"
    assert out["skipped_remote"][0]["host"] == remote


def test_t6_19_remote_with_twin_mapping_deletes_via_ssh(monkeypatch):
    """Remote host with known SWARM_INPUT_DIRS twin: ssh rm, not invent path."""
    data = _isolate()
    remote = "100.107.235.105"
    out_root = os.path.join(data, "ComfyUI", "output")
    monkeypatch.setattr(pipeline, "COMFY_OUTPUT", out_root)
    monkeypatch.setattr(
        pipeline, "SWARM_INPUT_DIRS",
        [f"jon@{remote}:/home/jon/comfy-backend/input"])
    # Clip under COMFY_OUTPUT so twin maps; land as remote host.
    sid = db.upsert_song("t619r", title="remote", duration=5.0)
    tier = "r"
    now = time.time()
    assembled = _write(os.path.join(data, "assembled.mp4"), b"a")
    rid = db.run(
        "INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
        sid, tier, assembled, now)
    clip = _write(os.path.join(out_root, "song_r", "clip_000.mp4"), b"clip")
    db.run("""INSERT INTO clips (song_id, tier, clip_idx, path, status)
              VALUES (?,?,?,?,?)""", sid, tier, 0, clip, "done")
    jobs.land(clip, host=remote, via="swarm")
    cleanup_service.confirm_render(rid)

    plan = cleanup_service.plan_clip_cleanup(sid, tier)
    t = plan["would_delete"][0]
    assert t["remote"] is True and t["can_delete"] is True
    assert t["remote_path"] == "/home/jon/comfy-backend/output/song_r/clip_000.mp4"
    assert t["ssh_target"] == f"jon@{remote}"
    assert t["reason"] == "remote twin via SWARM_INPUT_DIRS"

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    monkeypatch.setattr(cleanup_service.subprocess, "run", fake_run)
    out = cleanup_service.run_clip_cleanup(sid, tier, dry_run=False)
    assert out["n_deleted"] == 1
    assert not os.path.isfile(clip)
    assert calls, "ssh rm was not invoked"
    assert calls[0][0] == "ssh"
    assert f"jon@{remote}" in calls[0]
    remote_cmd = calls[0][-1]
    want = "/home/jon/comfy-backend/output/song_r/clip_000.mp4"
    assert remote_cmd == f"rm -f -- {shlex.quote(want)}", remote_cmd
    # Unquoted argv is the injection form; OpenSSH joins it through a shell.
    assert calls[0][3:] != ["rm", "-f", "--", want]
    # Never invent: ssh target and path come from the known twin only.
    assert "ComfyUI/output" not in " ".join(str(x) for x in calls[0])


def test_t6_19_remote_remove_quotes_shell_metacharacters(monkeypatch):
    """OpenSSH shells the remote argv; an unquoted ; is injection."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    monkeypatch.setattr(cleanup_service.subprocess, "run", fake_run)
    nasty = "/home/jon/comfy-backend/output/song_r/clip;reboot.mp4"
    cleanup_service._remote_remove("jon@100.107.235.105", nasty)
    assert calls, "ssh was not invoked"
    remote_cmd = calls[0][-1]
    assert remote_cmd == f"rm -f -- {shlex.quote(nasty)}", remote_cmd
    # Unquoted form would let the remote shell see `;reboot`.
    assert ";reboot" not in remote_cmd.replace(shlex.quote(nasty), "")
    with pytest.raises(ValueError, match="unsafe"):
        cleanup_service._remote_remove("jon@host", "/out/clip\n.mp4")


def test_t6_19_run_default_is_dry_run():
    """run_clip_cleanup without dry_run= keyword is dry-run (safe default)."""
    data = _isolate()
    fx = _fixture(data)
    cleanup_service.confirm_render(fx["render_id"])
    out = cleanup_service.run_clip_cleanup(fx["song_id"], fx["tier"])
    assert out["dry_run"] is True
    for p in fx["clips"]:
        assert os.path.isfile(p)


def test_t6_19_protected_anchor_path_refuses():
    """A clip row whose path is an anchor is refused, not deleted."""
    data = _isolate()
    fx = _fixture(data)
    cleanup_service.confirm_render(fx["render_id"])
    # Plant a bad clips row pointing at the anchor (mutation shape in data).
    db.run("""INSERT INTO clips (song_id, tier, clip_idx, path, status)
              VALUES (?,?,?,?,?)""",
           fx["song_id"], fx["tier"], 99, fx["anchor"], "done")
    with pytest.raises(cleanup_service.ProtectedPathError, match="anchor|kept"):
        cleanup_service.plan_clip_cleanup(fx["song_id"], fx["tier"])
    assert os.path.isfile(fx["anchor"])


def test_t6_19_mutation_skip_dry_run_default_is_named():
    """Mutation: change dry_run default to False → signature check goes red.

    Source must default dry_run=True. A silent flip to False is the named
    mutation for this criterion.
    """
    src = open(cleanup_service.__file__, encoding="utf-8").read()
    sig = inspect.signature(cleanup_service.run_clip_cleanup)
    assert sig.parameters["dry_run"].default is True, sig
    # Named mutation via mutation_read: flipping the default is a real change.
    report = mutation_read.apply(
        "def run_clip_cleanup(song_id, tier, *, dry_run=True):",
        "dry_run=True",
        "dry_run=False",
    )
    assert report["n"] == 1
    assert "dry_run=False" in report["after"]
    # Production source still has the safe default (mutation was on a snippet).
    assert "dry_run=True" in src
    assert "dry_run=False):" not in inspect.getsource(
        cleanup_service.run_clip_cleanup)


def test_t6_19_mutation_delete_anchor_is_named():
    """Mutation: drop anchor from keep_paths → product refuse would go green
    wrongly. Production keep_paths must list anchors; deleting that check is
    the named mutation.
    """
    src = inspect.getsource(cleanup_service.keep_paths)
    assert "anchors" in src, "keep_paths must read the anchors table"
    report = mutation_read.apply(
        src,
        'kept[p] = "anchor"',
        'pass  # mutation: drop anchor protection',
    )
    assert report["n"] >= 1
    # Live function still protects anchors (mutation was on a copy).
    data = _isolate()
    fx = _fixture(data)
    kept = cleanup_service.keep_paths(fx["song_id"], fx["tier"])
    assert jobs.canonical_path(fx["anchor"]) in kept
    assert kept[jobs.canonical_path(fx["anchor"])] == "anchor"


def test_t6_19_mutation_unknown_host_as_local_delete_goes_red():
    """Mutation: treat unknown remote host as local → would wrongly os.remove.

    Product is_local_host must refuse non-SELF_HOST; collapsing remote to
    local is the named defect for #537.
    """
    remote = "100.107.235.105"
    assert cleanup_service.is_local_host(remote) is False
    assert cleanup_service.is_local_host(models.SELF_HOST) is True
    assert cleanup_service.is_local_host(None) is True
    assert cleanup_service.is_local_host("127.0.0.1") is True

    src = inspect.getsource(cleanup_service.is_local_host)
    # Named mutation: always return True (unknown host treated as local).
    report = mutation_read.apply(
        src,
        "return False",
        "return True  # mutation: treat remote as local",
    )
    assert report["n"] >= 1
    # Live function still classifies remote as not local.
    assert cleanup_service.is_local_host(remote) is False
    cls = cleanup_service.classify_target("/tmp/x.mp4", remote)
    assert cls["remote"] is True
    assert cls["can_delete"] is False
    assert "no known path mapping" in cls["reason"]


def test_t6_19_h_render_song_does_not_set_confirmed():
    """Assemble INSERT does not write confirmed=1 (silent confirm defect)."""
    import app as appmod
    src = inspect.getsource(appmod.h_render_song)
    assert "confirmed" not in src, (
        "h_render_song must not touch confirmed; confirm is a separate act")


def test_t6_19_service_imports_nothing_from_fastapi():
    import ast
    tree = ast.parse(open(cleanup_service.__file__, encoding="utf-8").read())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "fastapi" or alias.name.startswith("fastapi."):
                    names.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "fastapi" or node.module.startswith("fastapi."):
                names.append(node.module)
    assert names == [], f"cleanup_service imports FastAPI: {names}"


def test_t6_19_api_confirm_and_dry_run(monkeypatch):
    """JSON routes: confirm, dry-run GET, unconfirmed 400."""
    import app as appmod
    from fastapi.testclient import TestClient

    data = _isolate()
    fx = _fixture(data)
    # tiers table may be empty in isolated db; bypass valid_tier for this unit.
    monkeypatch.setattr(appmod, "valid_tier_or_400", lambda t: t)
    monkeypatch.setattr(appmod, "get_song_or_404",
                        lambda sid: db.one("SELECT * FROM songs WHERE id=?", sid))

    with TestClient(appmod.app) as client:
        r = client.get(f"/api/songs/{fx['song_id']}/cleanup",
                       params={"tier": fx["tier"]})
        assert r.status_code == 400, r.text
        assert "confirm" in r.text.lower() or "unconfirmed" in r.text.lower() \
            or "confirmed" in r.text.lower()

        r = client.post(f"/api/renders/{fx['render_id']}/confirm")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["confirmed"] == 1
        assert body["id"] == fx["render_id"]

        r = client.get(f"/api/songs/{fx['song_id']}/cleanup",
                       params={"tier": fx["tier"]})
        assert r.status_code == 200, r.text
        plan = r.json()
        assert plan["dry_run"] is True
        assert plan["n_clips"] == 2
        for t in plan["would_delete"]:
            assert "remote" in t and "can_delete" in t and "reason" in t
        for p in fx["clips"]:
            assert os.path.isfile(p)

        r = client.post(
            f"/api/songs/{fx['song_id']}/cleanup",
            data={"tier": fx["tier"], "dry_run": "0", "confirm": "DELETE"})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["dry_run"] is False
        assert out["n_deleted"] == 2
        for p in fx["clips"]:
            assert not os.path.isfile(p)
        assert os.path.isfile(fx["assembled"])
        assert os.path.isfile(fx["anchor"])
