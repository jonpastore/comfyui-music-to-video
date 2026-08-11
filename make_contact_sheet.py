#!/usr/bin/env python3
"""Build a labeled contact sheet from clip_NNN_*.png reference images."""
import sys, glob, os, re
from PIL import Image, ImageDraw, ImageFont

def main():
    src = sys.argv[1]
    out = sys.argv[2]
    cols = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    thumb_w = 320
    files = sorted(glob.glob(os.path.join(src, "clip_*.png")))
    if not files:
        print("no files in", src); sys.exit(1)
    # derive thumb height from first image aspect
    im0 = Image.open(files[0])
    ar = im0.height / im0.width
    thumb_h = int(thumb_w * ar)
    label_h = 22
    cell_w, cell_h = thumb_w, thumb_h + label_h
    rows = (len(files) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), (24, 24, 28))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    for i, f in enumerate(files):
        r, c = divmod(i, cols)
        x, y = c * cell_w, r * cell_h
        im = Image.open(f).convert("RGB").resize((thumb_w, thumb_h))
        sheet.paste(im, (x, y + label_h))
        m = re.search(r"clip_(\d+)", os.path.basename(f))
        idx = m.group(1) if m else "?"
        draw.text((x + 4, y + 3), f"clip {idx}", fill=(255, 230, 120), font=font)
    sheet.save(out)
    print("wrote", out, sheet.size, "n=", len(files))

if __name__ == "__main__":
    main()
