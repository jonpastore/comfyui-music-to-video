#!/usr/bin/env python3
"""Unpack an album storyboard zip into its per-song folders.

Songs are matched by the track_number inside each storyboard JSON against the
album's tracklist in organize_albums.ALBUMS -- not by the zip's folder names,
which are slugs and drift from the real titles.

usage:
  distribute_storyboards.py --album Catatonic \
      --zip "Catatonic/Catatonic_FullAlbum_ComfyUI_Storyboards.zip"
"""
import argparse, glob, json, os, shutil, sys, tempfile, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from organize_albums import ALBUMS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--album", required=True)
    ap.add_argument("--zip", required=True)
    ap.add_argument("--root", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()
    os.chdir(args.root)

    tracks = ALBUMS[args.album]
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(args.zip) as z:
            z.extractall(tmp)

        dirs = sorted({os.path.dirname(p) for p in
                       glob.glob(os.path.join(tmp, "**", "*.json"), recursive=True)})
        copied = missing = 0
        for d in dirs:
            js = sorted(glob.glob(os.path.join(d, "*.json")))
            if not js:
                continue
            tn = json.load(open(js[0])).get("track_number")
            if not tn or tn > len(tracks):
                print(f"  ?? {os.path.basename(d)}: track_number {tn} not in {args.album}")
                missing += 1
                continue
            song = tracks[tn - 1]
            dest = os.path.join(args.album, song)
            if not os.path.isdir(dest):
                print(f"  !! no folder for {args.album}/{song}")
                missing += 1
                continue
            files = [f for f in sorted(glob.glob(os.path.join(d, "*"))) if os.path.isfile(f)]
            for f in files:
                shutil.copy2(f, os.path.join(dest, os.path.basename(f)))
            copied += len(files)
            scenes = len(json.load(open(js[0]))["scenes"])
            print(f"  track {tn:2d}  {song:<26} {len(files)} files, {scenes} scenes")

    print(f"\n{args.album}: copied {copied} files"
          + (f", {missing} unresolved" if missing else ""))


if __name__ == "__main__":
    main()
