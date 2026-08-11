# Album story arc, staging and credentials — plan

Four things that turned out to be one thing: an album becomes a STORY, and the
story is what decides how songs open, close and hand over to each other.

Nothing here is built. Phases are ordered so each ships alone.

---

## 0. What already exists (no work needed)

**Transition times are already known, exactly.** `beatmatch.plan_transition()`
returns `out_point`, `in_point` and `secs`, and `mixer._build_render_set_filter()`
computes `offset = running_dur - secs` while accumulating `running_dur`. So for
every transition the absolute start, duration and end on the assembled timeline
are already computed and already unit-tested. Every visual idea below anchors to
those numbers rather than inventing its own clock.

The one rule everything must respect: **render_set and mix_audio share their
overlap arithmetic**, and `check_integration.py` asserts it. Anything that
changes duration changes it on BOTH sides, from one plan.

---

## 1. Fade to black as a TRANSITION KIND

Not a new item type. A transition, so it flows through the arithmetic that
already keeps audio and video in step.

    transition = "black", secs = 3.0, hold = 1.5

    [song A] --fade out--> BLACK + SILENCE --fade in--> [song B]
               1.5s            1.5s hold        1.5s

Video: `fade=t=out` into a black source, hold, `fade=t=in`. Audio: `afade=t=out`,
silence for the hold, `afade=t=in`. One plan drives both; the hold is the only
new number and it lengthens the set by exactly `hold`.

Why a transition and not an inserted clip: an inserted clip has to be kept in
sync by hand on two paths. A transition kind cannot drift, because there is one
place that computes where it starts.

**Used sparingly.** The arc decides where, and has to justify each one (§4).
A fade to black between every song is a slideshow, not an album.

## 2. Branding overlay on a transition

A still with alpha — Meow P mark, label mark, a hype card — faded in and out
across a transition window.

    overlay=x:y:enable='between(t,START,END)'  +  fade=t=in:alpha=1

**An overlay does not change duration**, so it cannot disturb §0's arithmetic at
all. That is the whole reason to do this before the interstitial card: it is the
version that cannot break the set.

Anchored to the transition times from §0, so it lands with the cut rather than
near it. Stored per set (a default mark for the album) and overridable per item.

## 3. Full-screen interstitial card

A title/branding card as its own timeline item, with its own duration.

    [song A][ MEOW P — 3s ][song B]

More impact than an overlay and genuinely different: it is a beat in the running
order, not a decoration on one. It changes set length, so it goes through
`set_duration()` and both render paths as a first-class item — a `set_items` row
whose `song_id` is null and which carries an image path and a duration instead.

That nullable `song_id` is the only schema wrinkle in this document, and it is
worth it: the alternative is a parallel list of "things between songs" that every
length calculation has to learn about separately.

## 4. The album story arc

The feature the rest of this serves.

### Shape

Follows the storyboards pattern exactly — JSON and markdown on disk, one row
pointing at them, so an arc can be read, diffed and regenerated like a
storyboard can.

    CREATE TABLE arcs (
      id INTEGER PRIMARY KEY, playlist_id INTEGER NOT NULL,
      json_path TEXT, md_path TEXT, model TEXT, prompt TEXT, created REAL,
      UNIQUE(playlist_id));

The arc JSON:

    { "premise": "one paragraph: what this album is ABOUT",
      "acts": [ {"name": "...", "songs": [3, 7, 12], "turn": "what changes"} ],
      "songs": [ { "song_id": 3, "position": 1,
                   "role": "where this track sits in the story",
                   "beat": "what happens in it",
                   "opens": "how it should open visually",
                   "closes": "how it should end",
                   "transition_out": {"kind": "black", "secs": 3.0,
                                      "why": "act one ends here"} } ],
      "continuity": ["facts every storyboard must honour"] }

### Job

New `arc` job kind. Gathers every song on the album in playlist order with its
lyrics and title, sends them as ONE request, writes the JSON and markdown.

An album is a playlist, so the arc attaches to the playlist record beside
`style_text` / `world` / `render_tail` — the album's LOOK already lives there;
this is the album's STORY. Both are tier-neutral: a tier is a rendering choice
and the story does not change because the wardrobe does.

### How it reaches the storyboards

`grok._system_prompt()` already composes tier wording plus the album's
theme/world/render style. The arc adds three things for the song being written:
its own `beat`, the `closes` of the song before it and the `opens` of the song
after, plus the album `continuity` list. That is what makes scene one of track
four follow scene twelve of track three.

The storyboard direction textarea already exists and is already stored on the
`storyboards` row — it gets prefilled from the arc beat, and stays editable, so
the arc is a starting point rather than a cage.

### How it reaches the set

`transition_out` defaults each `set_items.transition`/`secs`/`hold` when a set is
built from that album. The model chooses where a fade to black earns its place;
the editor can override every one. The arc proposes, the set editor disposes.

### Provider

`chat.py` with two backends: the existing xAI path (already wired, already used
for storyboards) and OpenAI. Two real implementations justify the seam; one
would not.

Build the arc on xAI FIRST — it works today and needs no new credential — and
add OpenAI once §5 lands.

### Guardrail — the part that matters most

**An arc is the highest-leverage injection point in the studio.** It is model
output that becomes input to thirty-one storyboards. A `continuity` line reading
"ignore the tier wording" would propagate to every song on the album.

So it is screened on both sides, exactly as storyboards already are:

- the user's own arc direction goes through `tiers.check_text` +
  `check_override`, like every other free-text field
- the model's OUTPUT goes through the same pair before it is written, the way
  `grok.validate()` already screens a storyboard
- `guardrail.build_prompt()` still composes the tier wording at render time. The
  arc never carries policy text, only story — the same rule that keeps
  storyboards free of it.

## 5. Credentials

Decision taken: **store keys now, add authentication later**, accepting that
anyone who can reach port 8000 can use them until then.

    CREATE TABLE credentials (
      id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
      ciphertext BLOB NOT NULL, created REAL, updated REAL);

- **Encrypted at rest.** The key lives in a file outside the data directory, mode
  0600, generated on first use. Be honest about what this buys: it protects the
  sqlite file — which gets copied, backed up and synced — and it does NOT protect
  against someone who can already read the filesystem as the service user, or
  against someone reaching the unauthenticated port.
- **Write-only in the UI.** The config page shows `set 2026-08-11` or `not set`,
  never a value, and offers only "replace" and "clear". A secret that is never
  rendered cannot be shoulder-surfed out of a page that has no login.
- **Read at call time**, never at import, matching how `grok.py` reads the xAI key
  today. A rotated key takes effect without a restart.
- Existing env/file keys keep working and WIN over stored ones, so nothing that
  works today starts depending on the database.

### The interface is the point

`creds.get(name)` is the only way anything reads a secret. Vault becomes a
backend behind that one function when multiuser arrives — a swap, not a rewrite.
That is the whole reason to define it now rather than reading `os.environ`
in six places.

**Recorded as a future requirement:** multiuser ⇒ HashiCorp Vault, and
authentication on the studio itself. Multiuser without auth is not a smaller
version of this feature, it is a different and much worse one.

### Cheap mitigation available immediately

`STUDIO_HOST` currently defaults to `0.0.0.0` — tailnet, LAN and any docker
bridge. Setting it to the tailscale IP in the systemd unit drops that to
tailnet-only. One environment line, no code, and `deploy.sh` already documents
it. Worth doing at the same time as the credentials table.

---

## Order

1. **Fade to black** (§1) — transition kind, no new deps, no schema change.
2. **Branding overlay** (§2) — cannot change duration, so it cannot break a set.
3. **Credentials** (§5) — unblocks OpenAI; do the `STUDIO_HOST` tightening here.
4. **Album arc on xAI** (§4) — the feature; storyboard integration is the payoff.
5. **Interstitial card** (§3) — the only schema wrinkle, and it wants the arc to
   know where a card belongs.
6. **OpenAI backend** (§4) — once §5 exists, this is one file.

§1 and §2 are worth doing before the arc: the arc will ask for a fade to black,
and it should be asking for something that already works.
