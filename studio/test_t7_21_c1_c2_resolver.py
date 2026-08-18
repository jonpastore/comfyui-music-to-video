"""T7-21: C1 vs C2 is one resolver.

C1 same-pose edit: image latent, denoise 1.0, pose text matches the
source. C2 new-pose: empty 896×1216, her keepers as image1, asked pose
replaces the standing clause (T7-16). Denoise / pose labels come from
the same decision as the graph.

Mutation: C2 uses image latent of a stranger plate → red.
Mutation: C1 empty latent while the label says same-pose → red.
Mutation: pose text sits beside the standing clause → red.
"""
import json
import os
import time

import app as appmod
import classification
import db
import make_anchor
import pose_generate
import storyboard_service
import tiers

from test_app import _emit_anchor_workflow, _png_bytes


def _image(iid, **over):
    row = {
        "id": iid,
        "path": f"{iid}.jpg",
        "kind": "operator",
        "view": "front",
        "pose": "standing",
        "wardrobe": "clothed",
        "usable": "identity",
    }
    row.update(over)
    return row


def _scene(n, pose, camera, wardrobe="clothed"):
    return {
        "scene_number": n,
        "name": f"Scene {n}",
        "cue": "Verse",
        "duration_guidance": "8 sec",
        "story": f"{pose} in the alley",
        "camera": camera,
        "motion": "hold",
        "lighting": "neon",
        "location": f"loc {n}",
        "pose": pose,
        "wardrobe": wardrobe,
        "image_prompt": f"Meow P {pose} in a neon alley",
        "video_motion_prompt": f"motion {n}",
        "negative_prompt": "",
        "characters": [],
    }


def _write_board(sid, slug, tier, scenes, album):
    outdir = os.path.join(db.DATA, "storyboards", slug)
    os.makedirs(outdir, exist_ok=True)
    sb = {
        "title": "T",
        "album": album,
        "version": tier,
        "character_reference": "a sleek black feline DJ",
        "scenes": scenes,
    }
    json_path = os.path.join(outdir, f"{slug}_{tier}.json")
    md_path = os.path.join(outdir, f"{slug}_{tier}.md")
    json.dump(sb, open(json_path, "w"))
    open(md_path, "w").write("# storyboard\n")
    db.run(
        """INSERT INTO storyboards
           (song_id, tier, json_path, md_path, scene_count, created, scene_seconds)
           VALUES (?,?,?,?,?,?,?)""",
        sid, tier, json_path, md_path, len(scenes), time.time(), 8.0)
    return json_path


def _song(stamp, album):
    sid = db.upsert_song(stamp, title=f"T7-21 {stamp}", album=album, duration=24.0)
    return db.one("SELECT * FROM songs WHERE id=?", sid)


def _job_args(song_id):
    out = []
    for row in db.q("SELECT * FROM jobs WHERE song_id=? ORDER BY id", song_id):
        out.append((row, json.loads(row["args_json"] or "{}")))
    return out


def _assert_label_matches_graph(resolved):
    """Pose label and denoise labels are the same decision as latent."""
    labels = dict(resolved["denoise_labels"])
    form = dict(appmod.denoise_choices(resolved["latent"]))
    assert labels == form, (resolved["latent"], labels, form)
    assert resolved["denoise"] == 1.0
    assert resolved["denoise_label"] == labels["1.0"]
    if resolved["pose_label"] == "same-pose":
        assert resolved["kind"] == "c1", resolved
        assert resolved["latent"] == "image", (
            "C1 empty latent while the label says same-pose: "
            f"{resolved}")
        assert "discards the reference" in resolved["denoise_label"]
    else:
        assert resolved["kind"] == "c2", resolved
        assert resolved["pose_label"] == "new-pose", resolved
        assert resolved["latent"] == "empty", resolved
        assert resolved["width"] == 896 and resolved["height"] == 1216, resolved
        assert "only correct value" in resolved["denoise_label"]
        assert "returns noise" in labels["0.55"]


def test_t7_21_c1_encodes_her_same_pose_at_denoise_1():
    her = _image("her-stand", path="her-stand.jpg", pose="standing", view="front")
    got = pose_generate.resolve_c1_c2(
        {"pose": "standing", "view": "front", "wardrobe": "nude"},
        [her])
    assert got["kind"] == "c1", got
    assert got["latent"] == "image", got
    assert got["denoise"] == 1.0, got
    assert got["pose_label"] == "same-pose", got
    assert got["images"] == ["her-stand.jpg"], got
    assert got["source_path"] == "her-stand.jpg", got
    assert "standing" in got["pose"], got["pose"]
    _assert_label_matches_graph(got)


def test_t7_21_c2_empty_896x1216_uses_her_keepers_not_a_plate():
    her = _image("her-stand", path="her-stand.jpg", pose="standing", view="front")
    plate = _image("stranger", path="stranger-plate.jpg", kind="plate",
                   pose="kneeling", view="front", usable="pose")
    got = pose_generate.resolve_c1_c2(
        {"pose": "kneeling", "view": "front", "wardrobe": "clothed"},
        [her, plate])
    assert got["kind"] == "c2", got
    assert got["latent"] == "empty", got
    assert got["denoise"] == 1.0, got
    assert (got["width"], got["height"]) == (896, 1216), got
    assert got["pose_label"] == "new-pose", got
    assert got["images"] == ["her-stand.jpg"], got
    assert "stranger-plate.jpg" not in got["images"], got
    assert got["source_path"] is None, got
    assert "kneeling" in got["pose"], got["pose"]
    _assert_label_matches_graph(got)


def test_t7_21_c2_refuses_image_latent_of_a_stranger_plate():
    """Mutation: C2 uses image latent of a stranger plate → red."""
    plate = _image("stranger", path="stranger-plate.jpg", kind="plate",
                   pose="kneeling", view="front")
    her = _image("her-stand", path="her-front.jpg", pose="standing", view="front")
    got = pose_generate.resolve_c1_c2(
        {"pose": "kneeling", "view": "front"},
        [plate, her])
    assert got["latent"] != "image", got
    assert got["source_path"] != "stranger-plate.jpg", got
    assert got["images"][0] != "stranger-plate.jpg", got
    assert "stranger-plate.jpg" not in got["images"], got
    assert got["images"] == ["her-front.jpg"], got


def test_t7_21_same_pose_label_cannot_sit_on_empty_latent():
    """Mutation: C1 empty latent while the label says same-pose → red."""
    her = _image("her-stand", path="her-stand.jpg")
    got = pose_generate.resolve_c1_c2(
        {"pose": "standing", "view": "front"}, [her])
    assert got["pose_label"] == "same-pose", got
    assert got["latent"] == "image", got
    _assert_label_matches_graph(got)

    empty = pose_generate.resolve_c1_c2(
        {"pose": "all-fours", "view": "front"}, [her])
    assert empty["pose_label"] == "new-pose", empty
    assert empty["latent"] == "empty", empty
    _assert_label_matches_graph(empty)


def test_t7_21_c2_pose_replaces_standing_and_does_not_sit_beside_it():
    """Mutation: pose text sits beside the standing clause → red."""
    her = _image("her-stand", path="her-stand.jpg")
    got = pose_generate.resolve_c1_c2(
        {"pose": "kneeling", "view": "front"}, [her])
    prompt = make_anchor.prompt_for(
        "front", make_anchor.anchor_from({"pose": got["pose"]}))
    assert "kneeling" in prompt, prompt[:240]
    assert "standing upright" not in prompt, prompt[:240]
    assert "arms relaxed at their sides" not in prompt, prompt[:240]
    framing = make_anchor.VIEWS["front"]["framing"]
    replaced = make_anchor.apply_pose("front", framing, got["pose"])
    assert "kneeling" in replaced
    assert "standing upright facing the camera" not in replaced


def test_t7_21_c1_pose_text_matches_the_source():
    her = _image("her-kneel", path="her-kneel.jpg", pose="kneeling", view="front")
    got = pose_generate.resolve_c1_c2(
        {"pose": "kneel", "view": "front", "wardrobe": "nude"}, [her])
    assert got["kind"] == "c1", got
    assert "kneeling" in got["pose"], got["pose"]
    prompt = make_anchor.prompt_for(
        "front_nude", make_anchor.anchor_from({"pose": got["pose"]}))
    assert "kneeling" in prompt, prompt[:240]
    assert "standing upright" not in prompt, prompt[:240]


def test_t7_21_denoise_labels_are_the_t7_8_resolver():
    assert pose_generate.DENOISE_VALUES == appmod.DENOISE_VALUES
    for latent in ("empty", "image"):
        assert (pose_generate.denoise_labels(latent, appmod.DENOISE_VALUES)
                == appmod.denoise_choices(latent))


def test_t7_21_graph_matches_c1_and_c2_labels(tmp_path):
    d = str(tmp_path)
    her = os.path.join(d, "her.png")
    plate = os.path.join(d, "plate.png")
    open(her, "wb").write(_png_bytes())
    open(plate, "wb").write(_png_bytes())

    c1 = pose_generate.resolve_c1_c2(
        {"pose": "standing", "view": "front"},
        [_image("her", path=her, pose="standing", view="front")])
    flags = ["--latent", c1["latent"], "--denoise", str(c1["denoise"])]
    wf, _ = _emit_anchor_workflow(d, [her], flags)
    assert wf["15"]["class_type"] == "VAEEncode", wf["15"]
    assert wf["16"]["inputs"]["denoise"] == 1.0, wf["16"]["inputs"]
    _assert_label_matches_graph(c1)

    c2 = pose_generate.resolve_c1_c2(
        {"pose": "kneeling", "view": "front"},
        [_image("her", path=her, pose="standing", view="front"),
         _image("plate", path=plate, kind="plate", pose="kneeling",
                view="front")])
    render = pose_generate.c1_c2_render(c2)
    flags = [
        "--latent", render["latent"], "--denoise", str(render["denoise"]),
        "--width", str(render["width"]), "--height", str(render["height"]),
    ]
    wf, _ = _emit_anchor_workflow(d, c2["images"], flags)
    assert wf["15"]["class_type"] == "EmptySD3LatentImage", wf["15"]
    assert wf["15"]["inputs"]["width"] == 896, wf["15"]
    assert wf["15"]["inputs"]["height"] == 1216, wf["15"]
    assert wf["16"]["inputs"]["denoise"] == 1.0, wf["16"]["inputs"]
    loaded = {n["inputs"]["image"] for n in wf.values()
              if n["class_type"] == "LoadImage"}
    assert her in loaded, loaded
    assert plate not in loaded, loaded
    _assert_label_matches_graph(c2)


def test_t7_21_pose_gap_generate_wires_c1_and_c2():
    """Generate from holes uses the resolver, not a single empty-latent path."""
    tiers.ensure_builtins()
    stamp = f"t721-{time.time_ns()}"
    album = f"T721 {stamp}"
    song = _song(stamp, album)
    sid = song["id"]
    _write_board(sid, song["slug"], "r", [
        _scene(1, "standing", "wide", wardrobe="nude"),
        _scene(2, "kneeling", "medium"),
    ], album)
    classification.save(album, {"images": [
        _image("her-stand", path="her-stand.jpg", pose="standing",
               view="front", wardrobe="clothed"),
        _image("stranger", path="stranger-plate.jpg", kind="plate",
               pose="kneeling", view="back", usable="pose"),
    ]})

    got = storyboard_service.generate_poses(sid, ["r"])
    kinds = {(j["pose"], j["wardrobe"], j["job_kind"]) for j in got["jobs"]}
    assert ("standing", "nude", "c1") in kinds, got["jobs"]
    assert ("kneeling", "clothed", "c2") in kinds, got["jobs"]
    assert ("kneeling", "nude", "c2") in kinds, got["jobs"]

    for _row, args in _job_args(sid):
        render = args.get("render") or {}
        if args.get("job_kind") == "c1":
            assert args["pose_label"] == "same-pose", args
            assert render.get("latent") == "image", args
            assert float(render.get("denoise")) == 1.0, args
            assert args["images"] == ["her-stand.jpg"], args
            assert "standing" in args["pose"], args
        elif args.get("job_kind") == "c2":
            assert args["pose_label"] == "new-pose", args
            assert render.get("latent") == "empty", args
            assert float(render.get("denoise")) == 1.0, args
            assert render.get("width") == 896, args
            assert render.get("height") == 1216, args
            assert args["images"] == ["her-stand.jpg"], args
            assert "stranger-plate.jpg" not in args["images"], args
            assert "kneeling" in args["pose"], args
        else:
            raise AssertionError(f"pose-gap job skipped the resolver: {args}")
