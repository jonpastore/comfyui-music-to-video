"""T6-19 UI: song page shows confirmed-cleanup dry-run; unconfirmed has none.

After Confirm clean, the assemble section's cleanup card interpolates
cleanup_service.plan_clip_cleanup (path, host, remote, can_delete, reason).
Real delete posts dry_run=0 + confirm=DELETE to the existing API.
Unconfirmed: no delete form / plan not offered as a run.
T6-A4: stub plan with distinctive reason / n_can_delete; inventing goes red.
T6-18 stays: lifecycle writes still never delete.
"""
import os
import re
import tempfile
import time

from fastapi.testclient import TestClient

import app as appmod
import cleanup_service
import db
import jobs
import models


# Distinctive stub values so a template that invents counts/reasons goes red.
_STUB_REASON = "T6-19-UI-STUB-REASON-7731"
_STUB_N_CAN_DELETE = 17
_STUB_PATH = "/tmp/t619_ui_UNIQUE_clip_path_9913.mp4"
# What a template inventing from len(would_delete)==1 would show — must not appear
# as n_can_delete when the stub says 17.
_INVENTED_FROM_LEN = 'data-cleanup-n-can-delete="1"'


def _isolate():
    data = tempfile.mkdtemp(prefix="t619ui_")
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


def _fixture(data, *, unique_clip_name="clip_000.mp4", confirmed=False):
    """Song + render + one local clip. unique_clip_name plants a path for HTML."""
    sid = db.upsert_song(f"t619ui-{time.time_ns()}", title="T6-19 UI Song",
                         duration=12.3)
    tier = "r"
    now = time.time()
    assembled = _write(os.path.join(data, "renders", f"t619ui_{sid}.mp4"),
                       b"assembled")
    rid = db.run(
        "INSERT INTO renders (song_id, tier, path, created) VALUES (?,?,?,?)",
        sid, tier, assembled, now)
    clip = _write(os.path.join(data, "clips", unique_clip_name), b"clip0")
    db.run("""INSERT INTO clips (song_id, tier, clip_idx, path, status)
              VALUES (?,?,?,?,?)""", sid, tier, 0, clip, "done")
    jobs.land(clip, host=models.SELF_HOST, via="comfy")
    if confirmed:
        cleanup_service.confirm_render(rid)
    return {
        "song_id": sid, "tier": tier, "render_id": rid,
        "assembled": assembled, "clip": clip,
    }


def test_t6_19_unconfirmed_no_cleanup_delete_form():
    """Unconfirmed render: no delete form / plan not offered as a run."""
    data = _isolate()
    fx = _fixture(data, confirmed=False)

    with TestClient(appmod.app) as client:
        r = client.get(f"/songs/{fx['song_id']}")
    assert r.status_code == 200, r.text
    html = r.text

    assert 'data-cleanup-delete-form' not in html
    assert 'class="card cleanup-card"' not in html
    assert 'name="dry_run"' not in html or 'cleanup-delete' not in html
    # Confirm clean is still offered for the unconfirmed render.
    assert f'/songs/{fx["song_id"]}/renders/{fx["render_id"]}/confirm' in html
    # No plan path offered as a run target.
    assert f'data-cleanup-path="{fx["clip"]}"' not in html
    assert os.path.isfile(fx["clip"]), "unconfirmed page load must not delete"


def test_t6_19_confirmed_shows_distinctive_clip_path():
    """Confirmed: HTML shows distinctive clip path from the real plan."""
    data = _isolate()
    unique = "t619_UI_PLANTED_CLIP_5521.mp4"
    fx = _fixture(data, unique_clip_name=unique, confirmed=True)
    assert unique in fx["clip"]

    with TestClient(appmod.app) as client:
        r = client.get(f"/songs/{fx['song_id']}")
    assert r.status_code == 200, r.text
    html = r.text

    assert 'class="card cleanup-card"' in html
    assert f'id="cleanup-{fx["tier"]}"' in html
    assert unique in html, html
    assert f'data-cleanup-path="{fx["clip"]}"' in html or unique in html
    assert f'data-cleanup-delete-form="{fx["tier"]}"' in html
    assert 'name="dry_run" value="0"' in html
    assert 'name="confirm"' in html
    assert 'action="/api/songs/' in html and '/cleanup"' in html
    # Still dry-run listing only — files stay.
    assert os.path.isfile(fx["clip"])
    assert os.path.isfile(fx["assembled"])


def test_t6_19_stubbed_plan_interpolated_unmodified(monkeypatch):
    """T6-A4: stub plan reason / n_can_delete; template must not invent."""
    data = _isolate()
    fx = _fixture(data, confirmed=True)

    stub_plan = {
        "song_id": fx["song_id"],
        "tier": fx["tier"],
        "dry_run": True,
        "confirmed_render_id": fx["render_id"],
        "confirmed_path": fx["assembled"],
        "would_delete": [{
            "clip_idx": 0,
            "path": _STUB_PATH,
            "host": models.SELF_HOST,
            "via": "comfy",
            "backend": None,
            "exists": True,
            "artefact": True,
            "remote": False,
            "can_delete": True,
            "reason": _STUB_REASON,
            "remote_path": None,
            "ssh_target": None,
        }],
        "keep": [],
        "n_clips": 1,
        "n_existing": 1,
        "n_can_delete": _STUB_N_CAN_DELETE,
        "n_remote_skip": 0,
    }
    monkeypatch.setattr(cleanup_service, "plan_clip_cleanup",
                        lambda sid, tier: stub_plan)
    # song_page imports plan via cleanup_service module attribute — same object.
    monkeypatch.setattr(appmod.cleanup_service, "plan_clip_cleanup",
                        lambda sid, tier: stub_plan)

    with TestClient(appmod.app) as client:
        r = client.get(f"/songs/{fx['song_id']}")
    assert r.status_code == 200, r.text
    html = r.text

    assert _STUB_REASON in html, html
    assert _STUB_PATH in html, html
    assert f'data-cleanup-n-can-delete="{_STUB_N_CAN_DELETE}"' in html
    assert re.search(
        rf'data-cleanup-reason="{re.escape(_STUB_REASON)}"', html), html
    # Template that recomputes n_can_delete from len(would_delete) goes red.
    assert _INVENTED_FROM_LEN not in html, (
        "template recomputed n_can_delete from list length; must interpolate")
    # Real delete form still present for confirmed.
    assert f'data-cleanup-delete-form="{fx["tier"]}"' in html
