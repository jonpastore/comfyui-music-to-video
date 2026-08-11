#!/usr/bin/env python3
"""Comparison sheet: each row is one clip -> [committed original | 4 re-roll candidates].

usage: make_reroll_sheet.py <version> <clips_csv> <out.jpg>
  reads committed ref from  Street Cats/Rear Entrance/<version>/clip_NNN_00001_.png
  reads candidates from      reroll/out_<version>/clip_NNN_s<seed>_00001_.png
"""
import sys, glob, os, re
from PIL import Image, ImageDraw, ImageFont

VER = sys.argv[1]
CLIPS = [int(x) for x in sys.argv[2].split(",")]
OUT = sys.argv[3]
ORIG_DIR = f"Street Cats/Rear Entrance/{VER}"
CAND_DIR = f"reroll/out_{VER}"
SEEDS = [8000, 9000, 10000, 11000]

thumb_w = 300
label_h = 22

def load(path):
    if path and os.path.exists(path):
        return Image.open(path).convert("RGB")
    return None

# probe aspect
probe = load(f"{ORIG_DIR}/clip_{CLIPS[0]:03d}_00001_.png")
ar = probe.height/probe.width
thumb_h = int(thumb_w*ar)
cell_w, cell_h = thumb_w, thumb_h+label_h
cols = 5  # original + 4 candidates
rows = len(CLIPS)
sheet = Image.new("RGB", (cols*cell_w, rows*cell_h), (24,24,28))
draw = ImageDraw.Draw(sheet)
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
except Exception:
    font = ImageFont.load_default()

def cand_path(ci, seed):
    g = glob.glob(f"{CAND_DIR}/clip_{ci:03d}_s{seed+ci}_*.png")
    return g[0] if g else None

for r, ci in enumerate(CLIPS):
    cells = [(f"clip {ci} ORIG", f"{ORIG_DIR}/clip_{ci:03d}_00001_.png", (255,120,120))]
    for s in SEEDS:
        cells.append((f"s{s+ci}", cand_path(ci, s), (255,230,120)))
    for c,(lbl,path,col) in enumerate(cells):
        x,y = c*cell_w, r*cell_h
        im = load(path)
        if im is not None:
            sheet.paste(im.resize((thumb_w,thumb_h)), (x, y+label_h))
        else:
            draw.text((x+4,y+label_h+4),"(missing)",fill=(200,80,80),font=font)
        draw.text((x+4,y+3), lbl, fill=col, font=font)

sheet.save(OUT)
print("wrote", OUT, sheet.size)
