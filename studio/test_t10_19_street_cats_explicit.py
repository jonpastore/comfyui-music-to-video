"""T10-19: Street Cats Rear Entrance explicit scene 1 is adult-only.

Checked-in rear_entrance_explicit.json is the adult wording source for
the live board. Scene 1 must screen clean at xxx so POST /api/anchors
is not blocked by baked PINNED age-lock enumeration.

Mutation: paste PINNED / "no minors, no children" into scene 1
image_prompt → red.
"""
import json
import os

import guardrail


JSON_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "Street Cats", "Rear Entrance", "rear_entrance_explicit.json",
)

SCENE_FIELDS = (
    "image_prompt", "video_motion_prompt", "story", "camera",
    "motion", "lighting", "location", "name",
)

AGE_LOCK = (
    "no minors", "no children", "no infants", "no teenagers",
    "playground", "nursery",
)


def test_t10_19_rear_entrance_explicit_scene1_screens_at_xxx():
    sb = json.load(open(JSON_PATH))
    scene = next(s for s in sb["scenes"] if s.get("scene_number") == 1)
    fields = []
    for key in SCENE_FIELDS:
        val = scene.get(key)
        if isinstance(val, str) and val.strip():
            fields.append((f"scene 1 {key}", val))
    assert fields, "scene 1 has no screened fields"
    guardrail.screen_escalation(fields, "xxx")
    ip = scene["image_prompt"]
    assert "adult" in ip.lower(), ip[:200]
    low = ip.lower()
    for term in AGE_LOCK:
        assert term not in low, term
