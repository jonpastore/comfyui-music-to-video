"""T7-5: portrait omits head-to-toe and uses a head-and-shoulders latent.

docs/TRD-7 T7-5: BACKDROP's "full body head to toe" argues with head-and-
shoulders framing. Portrait must override that clause, not sit beside it,
and the empty latent must default to a head-and-shoulders size — a fixed
896×1216 full-body frame is what makes portrait render a distant figure.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import make_anchor

from fastapi.testclient import TestClient

import app as appmod
import db
import pipeline


def _png_bytes():
    # minimal 1x1 PNG
    import struct
    import zlib
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(
        ">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return sig + chunk(b"IHDR", ihdr) + chunk(
        b"IDAT", zlib.compress(b"\x00\x00\x00")) + chunk(b"IEND", b"")


def test_t7_5_portrait_compose_omits_head_to_toe():
    """Portrait prompt has head-and-shoulders and no full-body crop clause."""
    a = make_anchor.anchor_from({})
    port = make_anchor.prompt_for("portrait", a)
    nude = make_anchor.prompt_for("portrait_nude", a)
    front = make_anchor.prompt_for("front", a)

    for text in (port, nude):
        assert "head and shoulders" in text
        assert "full body head to toe inside the frame" not in text
        assert "stands upright and unsupported" not in text
        assert "under her feet" not in text
    # n_refs=2 must not reintroduce standing via COMPOSITE
    assert "standing by herself" not in make_anchor.prompt_for(
        "portrait", a, n_refs=2)
    # the four full-body shipped views still get the crop clause
    assert "full body head to toe inside the frame" in front
    assert "stands upright and unsupported" in front


def test_t7_5_portrait_default_latent_is_head_and_shoulders():
    """size_for_view: portrait is not the full-body 896×1216 default."""
    assert make_anchor.size_for_view("front") == make_anchor.DEFAULT_SIZE
    assert make_anchor.size_for_view("back") == make_anchor.DEFAULT_SIZE
    assert make_anchor.size_for_view("seated") == make_anchor.DEFAULT_SIZE
    assert make_anchor.size_for_view("portrait") == (1024, 1024)
    assert make_anchor.size_for_view("portrait_nude") == (1024, 1024)
    # full-body default is the tall standing sheet, not square
    assert make_anchor.DEFAULT_SIZE == (896, 1216)
    assert make_anchor.size_for_view("portrait") != make_anchor.DEFAULT_SIZE


def test_t7_5_studio_portrait_gets_head_and_shoulders_width_height(patch_stub):
    """Unset or full-body form size → gen_anchor sees width/height 1024×1024.

    A dead `size` key on the render dict is dropped by ANCHOR_RENDER_FLAGS;
    the flags that reach make_anchor are --width / --height.
    """
    seen = []

    def capture(images, view="front", n=4, progress=None, prefix=None,
                profile=None, guard="", prompt="", render=None):
        seen.append({"view": view, "render": dict(render or {})})
        return []

    patch_stub("pipeline", gen_anchor=capture)
    with TestClient(appmod.app) as client:
        client.post("/playlists", data={"name": "T75 Portrait Album"})
        base = {"album": "T75 Portrait Album", "tier": "r", "view": "portrait",
                "n": "1", "mode": "quality"}
        img = [("images", ("p.png", _png_bytes(), "image/png"))]

        # no size field: portrait must still size the latent
        client.post("/anchors", data=base, files=img)
        from test_app import wait_job
        wait_job(db.one("SELECT id FROM jobs WHERE kind='anchor' ORDER BY id DESC")["id"])
        assert seen[-1]["view"] == "portrait"
        r = seen[-1]["render"]
        assert r.get("width") == 1024 and r.get("height") == 1024, r
        assert "size" not in r or r["size"] is None
        assert set(r) <= set(pipeline.ANCHOR_RENDER_KEYS), (
            set(r) - set(pipeline.ANCHOR_RENDER_KEYS))

        # form's standing full-body default still upgrades for portrait
        client.post("/anchors", data={**base, "size": "896x1216"}, files=img)
        wait_job(db.one("SELECT id FROM jobs WHERE kind='anchor' ORDER BY id DESC")["id"])
        r = seen[-1]["render"]
        assert r.get("width") == 1024 and r.get("height") == 1024, r

        # operator-chosen non-default size wins
        client.post("/anchors", data={**base, "size": "1216x832"}, files=img)
        wait_job(db.one("SELECT id FROM jobs WHERE kind='anchor' ORDER BY id DESC")["id"])
        r = seen[-1]["render"]
        assert r.get("width") == 1216 and r.get("height") == 832, r

        # front stays on form size / make_anchor default — no forced square
        client.post("/anchors",
                    data={**base, "view": "front", "size": "896x1216"}, files=img)
        wait_job(db.one("SELECT id FROM jobs WHERE kind='anchor' ORDER BY id DESC")["id"])
        r = seen[-1]["render"]
        assert r.get("width") == 896 and r.get("height") == 1216, r


def test_t7_5_apply_view_default_size_is_the_single_resolver():
    """Studio path and unit path share one resolver; no twin size tables."""
    bare = appmod.apply_view_default_size("portrait", {})
    assert bare["width"] == 1024 and bare["height"] == 1024
    upgraded = appmod.apply_view_default_size(
        "portrait", {"width": 896, "height": 1216, "mode": "quality"})
    assert upgraded["width"] == 1024 and upgraded["height"] == 1024
    assert upgraded["mode"] == "quality"
    kept = appmod.apply_view_default_size(
        "portrait", {"width": 832, "height": 1216})
    assert kept["width"] == 832 and kept["height"] == 1216
    front = appmod.apply_view_default_size("front", {})
    assert "width" not in front and "height" not in front
