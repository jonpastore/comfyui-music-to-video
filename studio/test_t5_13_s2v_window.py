"""T5-13: skip_first_frames matches each s2v window's LTX slice.

docs/TRD-5 §5a: window k of a ≤15s LTX take skips k*LEN frames at
force_rate=FPS via LoadVideosFromFolder. Window 2 of a 15s take does
not start at frame 0. T5-12 hop emit in main() is not this slice.

Mutation: every window loads the LTX file from index 0 → red.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import build_song


SCENE = {
    "scene_number": 1, "name": "s", "camera": "wide", "lighting": "neon",
    "video_motion_prompt": "she walks", "negative_prompt": "",
    "duration_guidance": "5 sec", "image_prompt": "a rooftop",
}


def _control_loader(wf):
    nodes = [n for n in wf.values()
             if n.get("class_type") == "LoadVideosFromFolder"]
    assert len(nodes) == 1, nodes
    return nodes[0]


def test_t5_13_helper_window_2_of_15s_does_not_skip_0():
    skips = build_song.s2v_window_skips(15.0)
    assert len(skips) == len(build_song.split_to_ceiling(15.0, "s2v"))
    assert skips == [k * build_song.LEN for k in range(len(skips))]
    assert skips[0] == 0
    assert skips[2] != 0, "window 2 of a 15s LTX take must not start at frame 0"
    assert skips[2] == 2 * build_song.LEN


def test_t5_13_plan_carries_skip_per_window():
    scene = dict(SCENE, length_seconds=15.0, needs_lip_sync=True)
    plan = build_song.clip_chain_plan([scene])
    hops = [p for p in plan if p["model"] == "s2v"]
    want = build_song.s2v_window_skips(15.0)
    assert [h["skip_first_frames"] for h in hops] == want
    assert hops[2]["skip_first_frames"] != 0


def test_t5_13_workflow_wires_skip_into_control_loader():
    scene = dict(SCENE, start_s=0.0, length_seconds=build_song.CHUNK)
    skips = build_song.s2v_window_skips(15.0)
    graphs = []
    for k, skip in enumerate(skips):
        wf = build_song.workflow(
            k, scene, "still.png", "song.mp3", "c", "w", "",
            video_model="s2v", control_video="slug/clip_000",
            skip_first_frames=skip)
        loader = _control_loader(wf)
        ins = loader["inputs"]
        assert ins["force_rate"] == build_song.FPS
        assert ins["frame_load_cap"] == build_song.LEN
        assert ins["skip_first_frames"] == skip, (k, skip, ins)
        graphs.append(ins["skip_first_frames"])
    assert graphs[2] != 0
    # Mutation: every window loads from index 0 → red.
    assert not all(s == 0 for s in graphs), (
        "every window skip_first_frames=0 would re-read LTX frame 0")


def test_t5_13_ref_motion_stays_at_skip_0():
    scene = dict(SCENE, start_s=0.0, length_seconds=build_song.CHUNK)
    wf = build_song.workflow(
        0, scene, "still.png", "song.mp3", "c", "w", "",
        video_model="s2v", ref_motion="/m.mp4", control_video="/c.mp4",
        skip_first_frames=2 * build_song.LEN)
    by_id = {k: n for k, n in wf.items()
             if n.get("class_type") == "LoadVideosFromFolder"}
    assert by_id["20"]["inputs"]["skip_first_frames"] == 0
    assert by_id["21"]["inputs"]["skip_first_frames"] == 2 * build_song.LEN
