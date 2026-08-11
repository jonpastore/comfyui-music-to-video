#!/usr/bin/env python3
"""Load the songbook PDF into Meow P Studio: albums -> playlists, tracks -> songs.

The PDF is the source of truth for lyrics and Suno style prompts. Each album
section is a track list followed by one block per track:

    <n>. <Title>
    Lyrics
    ...
    Suno Style Prompt
    ...

Everything goes in through the app's own HTTP routes -- no direct database
writes -- so uploads, validation and slugging behave exactly as they do when a
human does it, and running this twice does not duplicate anything.

Use pypdf, NOT pdftotext: pdftotext truncates these style prompts at ~130
characters mid-word ("... metallic hats, industrial per"), which silently loses
half of every prompt. pypdf returns all 250.

usage:
  import_songbook.py                       # dry run against the live studio
  import_songbook.py --apply
  import_songbook.py --apply --album "Street Cats" --base http://127.0.0.1:8010
"""
import argparse, glob, os, re, sys

import httpx
import pypdf

PDF = "MeowP_StreetCats_Catatonic_Songbook.pdf"
BASE = "http://100.103.148.120:8000"
ALBUMS = ("Street Cats", "Catatonic")
TRACK_RE = re.compile(r"^(\d{1,2})\.\s+(.+?)\s*$")


def pdf_text(path):
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(path).pages)


def parse(text):
    """[(album, track_no, title, lyrics, style)] in book order."""
    lines = text.splitlines()
    album, out = None, []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line in ALBUMS:
            album = line
            i += 1
            continue
        m = TRACK_RE.match(line)
        # a track BLOCK is a numbered heading immediately followed by "Lyrics";
        # the same pattern in the track list at the top of an album is not
        if m and album and i + 1 < len(lines) and lines[i + 1].strip() == "Lyrics":
            no, title = int(m.group(1)), m.group(2)
            body, i = [], i + 2
            while i < len(lines):
                nxt = lines[i].strip()
                if nxt in ALBUMS:
                    break
                if TRACK_RE.match(nxt) and i + 1 < len(lines) and lines[i + 1].strip() == "Lyrics":
                    break
                body.append(lines[i])
                i += 1
            blob = "\n".join(body)
            lyrics, style = blob, ""
            if "Suno Style Prompt" in blob:
                lyrics, style = blob.split("Suno Style Prompt", 1)
            out.append((album, no, title, clean(lyrics), clean(style)))
            continue
        i += 1
    return out


def clean(text):
    # page furniture from the PDF, and runs of blank lines
    text = re.sub(r"^\s*Page \d+\s*$", "", text or "", flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def find_mp3(album, title):
    for pat in (f"{album}/{title}/*.mp3", f"{album}/{title}/{title}.mp3"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


class Studio:
    def __init__(self, base, apply_):
        self.c = httpx.Client(base_url=base, timeout=120, follow_redirects=True)
        self.apply = apply_
        self.songs = {}       # (album, lowercased title) -> id
        self.playlists = {}   # name -> id

    def load(self):
        # the app has no read API, so identity comes from the pages it renders.
        # The library lists album and title in the same row.
        for row in re.finditer(r"<tr>(.*?)</tr>", self.c.get("/").text, re.S):
            m = re.search(r'href="/songs/(\d+)">([^<]+)</a>', row.group(1))
            if not m:
                continue
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S)
            album = re.sub(r"<[^>]+>", "", cells[1]).strip() if len(cells) > 1 else ""
            self.songs[(album, m.group(2).strip().lower())] = int(m.group(1))
        page = self.c.get("/playlists").text
        for m in re.finditer(r'<strong>([^<]+)</strong>.*?/playlists/(\d+)/', page, re.S):
            self.playlists.setdefault(m.group(1).strip(), int(m.group(2)))

    def playlist(self, name):
        if name in self.playlists:
            return self.playlists[name]
        print(f"  + playlist {name!r}")
        if not self.apply:
            return None
        self.c.post("/playlists", data={"name": name, "kind": "playlist"})
        self.load()
        return self.playlists.get(name)

    def song(self, album, title, mp3):
        got = self.songs.get((album, title.lower()))
        if got:
            return got, False
        if not mp3:
            print(f"  - {title!r}: no mp3 in {album}/, skipped (a song needs its audio)")
            return None, False
        print(f"  + song {title!r} ({os.path.basename(mp3)})")
        if not self.apply:
            return None, True
        with open(mp3, "rb") as f:
            self.c.post("/songs", data={"title": title, "album": album, "genre": ""},
                        files={"mp3": (os.path.basename(mp3), f, "audio/mpeg")})
        self.load()
        return self.songs.get((album, title.lower())), True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default=PDF)
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--album", help="only this album")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = ap.parse_args()

    tracks = parse(pdf_text(args.pdf))
    if args.album:
        tracks = [t for t in tracks if t[0] == args.album]
    if not tracks:
        sys.exit("no tracks parsed -- has the songbook layout changed?")

    s = Studio(args.base, args.apply)
    s.load()
    print(f"{len(tracks)} tracks parsed; studio already knows {len(s.songs)} songs\n")

    made = added = texted = 0
    for album, no, title, lyrics, style in tracks:
        print(f"{album} {no:>2}. {title}  [lyrics {len(lyrics)}, style {len(style)}]")
        pid = s.playlist(album)
        sid, created = s.song(album, title, find_mp3(album, title))
        made += 1 if created else 0
        if sid and args.apply:
            if lyrics:
                s.c.post(f"/songs/{sid}/lyrics", data={"lyrics_text": lyrics})
            if style:
                s.c.post(f"/songs/{sid}/style-text", data={"style_text": style})
            texted += 1
            if pid:
                s.c.post(f"/playlists/{pid}/items", data={"song_id": sid})
                added += 1

    print(f"\n{'wrote' if args.apply else 'would write'}: {made} new songs, "
          f"{texted} lyric+style updates, {added} playlist entries")
    if not args.apply:
        print("dry run -- re-run with --apply")


if __name__ == "__main__":
    main()
