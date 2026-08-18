"""T3-36: image-latent sheets that inherit source WxH are not resolution REJECT.

VAEEncode of a 1024x1024 photo against expect 896x1216 PASSes when
expect.latent == image. Empty or absent latent still exact-matches:
same sizes REJECT.

Mutation: delete the exemption from check_image → latent=image REJECT → red.
Mutation: empty latent also PASSes a size miss → red.
"""
from PIL import Image

import qc


def _png(path, size, colour=(40, 80, 120)):
    # Non-uniform, non-blank so not_uniform / not_blank stay out of the way.
    w, h = size
    im = Image.new("RGB", (w, h), colour)
    px = im.load()
    for x in range(min(8, w)):
        for y in range(min(8, h)):
            px[x, y] = (colour[0] + x * 10, colour[1] + y * 5, colour[2])
    im.save(path)
    return str(path)


def _res(findings):
    rows = [f for f in findings if f["check"] == "resolution"]
    assert rows, f"no resolution finding: {[f['check'] for f in findings]}"
    return rows[0]


def test_t3_36_image_latent_inherits_source_size(tmp_path):
    """1024x1024 vs expect 896x1216 with latent=image must not REJECT."""
    path = _png(tmp_path / "source.png", (1024, 1024))
    expect = {"width": 896, "height": 1216, "latent": "image"}
    row = _res(qc.check_image(path, expect))
    assert row["verdict"] != qc.REJECT, row
    assert row["verdict"] == qc.PASS, row
    assert row["measured"] == "1024x1024", row
    assert row["expected"] == "896x1216", row
    assert row["unit"] == "px", row


def test_t3_36_empty_latent_still_exact_match_rejects(tmp_path):
    """Empty latent same sizes still REJECT. Absent latent too."""
    path = _png(tmp_path / "empty.png", (1024, 1024))
    want = {"width": 896, "height": 1216}

    empty = _res(qc.check_image(path, {**want, "latent": "empty"}))
    assert empty["verdict"] == qc.REJECT, empty
    assert empty["measured"] == "1024x1024", empty
    assert empty["expected"] == "896x1216", empty

    absent = _res(qc.check_image(path, want))
    assert absent["verdict"] == qc.REJECT, absent
    assert absent["measured"] == "1024x1024", absent
    assert absent["expected"] == "896x1216", absent
