#!/usr/bin/env python3
"""Sort the Meow P mp3s into <Album>/<Song>/ folders with the video subdirs.

Filenames drift from the tracklists (version suffixes, typos, smart quotes,
'_' standing in for '?'), so matching is normalise-then-fuzzy, and anything
that does not match cleanly is reported rather than guessed at.

  --apply   actually move; without it, dry run.
"""
import argparse, difflib, glob, os, re, shutil, sys

ALBUMS = {
    "Nine Lives After Dark": [
        "The Pussy Comes Out at Night", "Shake the Bag", "Catnip", "In Heat",
        "Come When Called", "Tail Up", "Akung Kuting", "Gata Gostosa", "Play With Me",
        "Laser Pointer", "Curiosity", "Heavy Petting", "Full House", "On The Side",
        "Scratch Marks", "No Collar", "Bad Decisions", "Nine Lives", "Velvet Claws",
        "Come Closer", "Tongue Tied", "Lap It Up", "Purr",
    ],
    "Get Feral Tonight": [
        "Where My Cats At?", "Paws Up", "Big Cat Energy", "Cat Call", "Feral",
        "Lick the Beat", "Stray Together", "Gimme That Pounce", "Feline Fine",
        "Claws Out", "Cool Cats Only", "Sunrise Strays",
    ],
    "Street Cats": [
        "Back Alley Pussy", "Rear Entrance", "Down Low", "Hard to Handle",
        "After Hours Access", "Wet Concrete", "Pull My Chain", "Deep in the Warehouse",
        "No Safe Word", "Hit It From the Back", "Dirty Little Stray", "Last Cat Standing",
    ],
    "Catatonic": [
        "Catatonic", "Nine Lives High", "Gata Loca", "Trip the Kitty", "Claw Machine",
        "Purrgatory", "Ay, Gatita", "Third Eye Open", "Catamine", "Bass Has Nine Lives",
        "Scratch the Surface", "Gimme That Treat", "Gatita Mala", "Quantum Pussy",
        "Ritual Nine", "Touch My Frequencies", "Laser Eyes", "Pussy Hypnotized",
        "Nine Below", "Don't Wake the Cat",
    ],
}


# tracklist name -> actual filename stem, where fuzzy matching is not safe
ALIASES = {
    "Purr": "Purrrr",
}


def norm(s):
    s = s.lower().replace("’", "'")
    s = re.sub(r"\.mp3$", "", s)
    s = re.sub(r"\(remastered\)", "", s)
    s = re.sub(r"\bv\d+(\.\d+)?\b", "", s)      # v2, v3, v2.1
    s = re.sub(r"\(\d+\)", "", s)                # (1)
    s = re.sub(r"[^a-z0-9 ]", "", s)             # drops ' ? _ , .
    return re.sub(r"\s+", " ", s).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    os.chdir(args.root)

    files = sorted(f for f in os.listdir(".") if f.lower().endswith(".mp3"))
    # mp3s already sitting in a song folder (moved earlier, or hand-made) count too
    for pat in ("*/*.mp3", "*/*/*.mp3"):
        files += [p for p in glob.glob(pat) if not p.startswith(".")]

    index = {}
    for f in files:
        index.setdefault(norm(os.path.basename(f)), []).append(f)

    used, plan, unmatched = set(), [], []
    for album, tracks in ALBUMS.items():
        for song in tracks:
            key = norm(ALIASES.get(song, song))
            cands = index.get(key)
            if not cands:
                close = difflib.get_close_matches(key, [k for k in index if k not in used], 1, 0.82)
                cands = index.get(close[0]) if close else None
            if not cands:
                unmatched.append((album, song))
                continue
            # prefer a remastered take when the same song has several files
            src = sorted(cands, key=lambda p: ("remaster" not in p.lower(), len(p)))[0]
            used.add(norm(os.path.basename(src)))
            plan.append((album, song, src))

    planned = {os.path.abspath(s) for _, _, s in plan}
    extras = [f for f in files if os.path.abspath(f) not in planned]

    for album, song, src in plan:
        dest_dir = os.path.join(album, song)
        dest = os.path.join(dest_dir, f"{song}.mp3")
        if os.path.abspath(src) == os.path.abspath(dest):
            print(f"  ok   {album}/{song}")
            continue
        print(f"  move {src}  ->  {dest}")
        if args.apply:
            for sub in ("clean/clips", "explicit/clips"):
                os.makedirs(os.path.join(dest_dir, sub), exist_ok=True)
            shutil.move(src, dest)

    print(f"\nmatched {len(plan)}/{sum(len(t) for t in ALBUMS.values())} tracks")
    if unmatched:
        print("NO FILE FOUND for:")
        for a, s in unmatched:
            print(f"  {a}: {s}")
    if extras:
        print("mp3s not in any tracklist:")
        for e in extras:
            print(f"  {e}")
    if not args.apply:
        print("\n(dry run -- rerun with --apply)")


if __name__ == "__main__":
    main()
