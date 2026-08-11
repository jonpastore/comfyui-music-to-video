# Sets: audio and video mixing — plan

The Sets page is currently a read-only shelf. A set is rendered from a playlist
card, lands as an `assets` row with `kind='set'`, and the page lists what exists.
There is no way to build one there, no per-song metadata, and the only transition
control is a name and a number stored on `playlist_items`.

This plans the build-out. Phases are ordered so each one ships something usable
on its own, and the earlier ones do not depend on the later ones landing.

---

## The one structural change everything else needs

**A set is currently a render, not a document.** The only record of what went
into it is the playlist as it stood at the time; edit the playlist and the
finished file no longer describes anything. Every feature below wants to edit a
set, re-render it, and compare — so a set has to become a row you can open.

    CREATE TABLE sets (
      id INTEGER PRIMARY KEY, name TEXT, playlist_id INTEGER,   -- nullable: a set
      tier TEXT, mode TEXT DEFAULT 'video',                     -- need not come
      created REAL, updated REAL);                              -- from a playlist
    CREATE TABLE set_items (
      id INTEGER PRIMARY KEY, set_id INTEGER NOT NULL, song_id INTEGER NOT NULL,
      position INTEGER NOT NULL,
      in_secs REAL, out_secs REAL,        -- the part of the song that plays
      transition TEXT, secs REAL,         -- how the NEXT one arrives
      gain_db REAL DEFAULT 0,
      effects_json TEXT);                 -- per-item audio/video effects

The rendered file stays an `assets` row pointing back at `set_id`, so re-rendering
a set produces a new file beside the old one rather than replacing it — the same
shape as anchors and refs, where the previous candidate survives until you pick.

`mixer.render_set()` and `mixer.mix_audio()` already take a list of items with
`transition`/`secs`; they need `in_secs`/`out_secs` and per-item gain, and
nothing else changes. **This is the whole reason the audio-only and video paths
share their overlap arithmetic — keep that.**

---

## Phase 1 — the set is editable (no new dependencies)

The UI the screenshot asks for, with nothing clever underneath.

- `/sets/new`, `/sets/{id}` — pick **audio** or **audio + video**, pick a tier,
  add songs from the library, drag to reorder. The drag-to-reorder handler in
  `app.js` for playlist rows is already generic; reuse it.
- Per item: in/out trim, gain, transition type and length. Every `xfade`
  transition ffmpeg offers is already reachable through `_XFADE_NAMES`.
- A running total: set length, computed by `mixer.set_duration()`, which is
  already pure arithmetic and already accounts for crossfade overlap.
- Render button → the existing job. Audio-only and video from one form.

Everything here is a form, a table and functions that already exist. **Ship this
before anything below it** — it is the part that is missing, rather than the part
that is interesting.

## Phase 2 — per-song metadata

`songs.bpm` has been in the schema since the beginning and **nothing has ever
written to it**. This fills it, plus key and energy.

One new dependency: **librosa** (ISC licence). `librosa.beat.beat_track()`
returns tempo and beat frames; key comes from `librosa.feature.chroma_cqt()`
scored against the Krumhansl–Schmuckler profiles; energy is RMS. Add it to the
studio's own venv in `deploy.sh` — not ComfyUI's.

- New `analyse` job kind, enqueued next to `transcribe` on upload, and runnable
  on demand for the 31 songs already here.
- Columns: `bpm`, `key` (as Camelot, e.g. `8A`), `beat_grid_json`, `energy`.
- Show them in the Library table (sortable — the header sort now works) and on
  each set item.

Why librosa over the alternatives, having looked: **madmom** has the best
downbeat detection by a wide margin but is unmaintained and does not import
against numpy 2, which is what is on the box. **Essentia** (`RhythmExtractor2013`,
`KeyExtractor`) is the best analysis available and is what Mixxx-class tools
reach for, but it is a heavy native build. **aubio** is light but weaker on key.
librosa is one pip install, works with numpy 2, and is good enough to *propose* a
BPM the user can correct — which is all phase 3 needs.

Downbeats are the weak point of that choice. Approximate bars as every 4th beat
from the first strong beat and **leave the offset editable**: a set built on a
wrong bar-one sounds wrong in a way no amount of tuning fixes, and a human
listening once fixes it in a second.

## Phase 3 — beat matching

With a beat grid per song, a transition can land on a bar rather than at an
arbitrary second.

- **Snap** the transition point to the nearest downbeat on both sides. This
  alone is most of what "beat matched" means to a listener, and it needs no
  time-stretching at all.
- **Tempo ramp** for the overlap: pull the outgoing song's tempo toward the
  incoming one across the last N bars. ffmpeg's **`rubberband` filter is built
  into the ffmpeg on this box** (verified) — that is the good time-stretcher, not
  `atempo`, which chains badly past ±2× and smears transients.
- **Harmonic ordering**: offer a suggested running order by Camelot adjacency
  (±1 number, or same number switching A/B). A suggestion with a "why" beside
  it, never an automatic reorder.

`pyCrossfade` is the closest published implementation of exactly this — bar-level
beat matching with a gradual BPM shift across a given number of downbeats, plus
EQ modification through the transition. Read its transition logic; it is a small
codebase and the bar-alignment maths is the part worth taking. Mixxx's Auto DJ
and Sync Lock are the reference for behaviour: what it does when two tracks
disagree about bar one, and how much stretch is too much.

## Phase 4 — DJ effects, on ffmpeg only

Everything below is in the ffmpeg already installed here (562 filters; each of
these verified present). **No new dependency, no plugin build.**

| Effect | Filter | Where it earns its place |
|---|---|---|
| Filter sweep | `highpass`/`lowpass` with an expression on `f` | the classic build into a drop |
| 3-band EQ kill | `firequalizer` or three `equalizer` | bass-swap through a transition — what makes two kicks not fight |
| Echo out | `aecho` | outgoing track tails off instead of stopping |
| Level matching | `loudnorm` | two Suno tracks at different loudness ruin an otherwise good mix |
| Gain / duck | `volume`, `sidechaincompress` | per-item gain, and ducking a bed under a vocal |
| Phaser / flanger | `aphaser`, `flanger` | sparingly |

Level matching is the unglamorous one that matters most and should be **on by
default**. Every other effect is per-item and off by default.

`gl-transitions` gets suggested for fancier video transitions; it needs a custom
ffmpeg build and is **not** worth it — `xfade` already ships more than 50.

## Phase 5 — video mixing

The video side has no equivalent of a beat grid today, and it should reuse the
audio one rather than grow its own.

- **Cut on the beat.** Build the `xfade` offsets from the detected downbeats, so
  a video transition lands with the musical one. This falls out of phase 3 for
  free and is the single biggest visual improvement available.
- **Per-item look**: `eq`, `hue`, `colorbalance` for a grade; `rgbashift` and
  `chromashift` for glitch on a hit.
- **Layering**: `blend` (screen, overlay, difference) and `overlay` for VJ-style
  double exposure between two songs' footage through a long transition.
- Geometry normalisation already exists in `_build_render_set_filter` — mixed
  resolutions and frame rates are handled.

## What to read, and what to take from each

| Project | Take |
|---|---|
| [Mixxx](https://github.com/mixxxdj/mixxx) (GPL-2) | The beatgrid model, Auto DJ behaviour, Camelot compatibility rules. The reference implementation for all of this; read it for *decisions*, not code — it is C++. |
| [pyCrossfade](https://github.com/oguzhan-yilmaz/pyCrossfade) | Bar-level beat matching and the gradual BPM shift across downbeats. The closest thing to phase 3 that already exists in Python. |
| [AI-DJ-Mixing-System](https://github.com/kckDeepak/AI-DJ-Mixing-System) | Phrase-based transitions and dynamic overlap length — the idea that transition length should follow the music, not be a constant. |
| [Essentia](https://github.com/MTG/essentia) | `RhythmExtractor2013` and `KeyExtractor` if librosa's key detection proves too weak to trust. |
| [Velorn](https://github.com/VelornLabs/velorn) (GPL-3) | Timeline UI shape for the video side. It is the only comparable ComfyUI-driven tool with a real timeline — but note it has no multi-song set concept, so there is nothing to copy for phases 1–4. |

---

## Open questions

1. **Where does analysis run?** It is CPU work, but the box's CPU is already
   busy feeding the GPU during a render. Either it goes through the same
   serialized worker (simple, blocks renders) or it gets a second lane (correct,
   more machinery). Phase 2 should start simple and measure.
2. **Is `mode` per set or per render?** A playlist rendered audio-only and again
   with video is arguably one set with two outputs. Two rows is simpler and
   matches how tiers already work.
3. **How much tempo stretch is acceptable** before a transition should refuse to
   beatmatch and just crossfade? Mixxx uses a configurable range; pick one after
   listening, not before.
