"""T3-15: identity metric ranks the recorded pair; pixel distance must not.

docs/TRD-3 T3-15: a deliberate pose change is not an identity failure.
The correct anchored render must score better than the pose-plate render
that dragged a photoreal look through — the ordering pixel distance got
backwards (41.1 for the wrong image, 64.7 for the right one).

No threshold, no gate, no UI. The pair is painted so composition matches
the plate and identity matches the anchor; swapping the metric for pixel
distance must go red.
"""
import os

import numpy as np
from PIL import Image

import qc


# Fur / look colours. Beige is the shared stage so composition can agree
# while identity (black vs tabby) does not.
BG = (210, 180, 140)
BLACK = (15, 12, 18)
TABBY = (180, 110, 55)
SIZE = 32


def _paint(path, colour, standing):
    """Standing = vertical figure (the plate pose). Else reclining."""
    img = Image.new("RGB", (SIZE, SIZE), BG)
    px = img.load()
    if standing:
        cols, rows = range(8, 15), range(4, 28)
    else:
        cols, rows = range(4, 28), range(18, 26)
    for y in rows:
        for x in cols:
            px[x, y] = colour
    img.save(path)
    return path


def _recorded_pair(tmp_path):
    """Anchor + same-identity pose change + same-pose tabby plate look."""
    anchor = _paint(tmp_path / "anchor.png", BLACK, standing=True)
    anchored = _paint(tmp_path / "anchored.png", BLACK, standing=False)
    plate = _paint(tmp_path / "pose_plate_look.png", TABBY, standing=True)
    return str(anchor), str(anchored), str(plate)


def _pixel_distance(path, reference):
    """Mean per-pixel RGB Euclidean distance. Lower looks 'closer'."""
    a = np.asarray(Image.open(path).convert("RGB"), dtype="float32")
    b = np.asarray(Image.open(reference).convert("RGB"), dtype="float32")
    return float(np.mean(np.sqrt(np.sum((a - b) ** 2, axis=2))))


def test_t3_15_pixel_distance_fails_the_recorded_pair(tmp_path):
    """This pair is the inversion: pixel distance prefers the plate look."""
    anchor, anchored, plate = _recorded_pair(tmp_path)
    d_anchored = _pixel_distance(anchored, anchor)
    d_plate = _pixel_distance(plate, anchor)
    assert d_plate < d_anchored, (d_plate, d_anchored)


def test_t3_15_identity_ranks_anchored_sheet_above_pose_plate(tmp_path):
    """The identity metric must not agree with that inversion."""
    anchor, anchored, plate = _recorded_pair(tmp_path)
    ref = qc.identity_embed(anchor)
    s_anchored = qc.identity_score(anchored, ref)
    s_plate = qc.identity_score(plate, ref)
    assert s_anchored > s_plate, (s_anchored, s_plate)
    assert os.path.isfile(anchored) and os.path.isfile(plate)
