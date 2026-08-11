# Library: bulk genre editing, async saves, and where genre actually comes from

> **PENDING APPROVAL. Nothing here is built.** Written for the session that owns
> `studio/app.py` and the Library page — `templates/index.html`, `static/app.js`.
> Those files were being edited minutes before this was written, which is why it
> is a document and not a diff.

Asked for, from the annotated screenshot:

1. Checkboxes down the left of the song table, and a toggle-all in the header.
2. A genre bar **above** the header — genre / subgenre / genre2 / subgenre2 plus
   a Save button — that mass-applies to the checked rows.
3. Save **async**: no page refresh.
4. "Analyse all un-analysed songs" also async, updating rows in place.
5. AI to set genre / subgenre / genre2 / subgenre2.

---

## The finding that decides item 5

**Do not build audio genre classification. The genre is already written down.**

Queried against the deployed database (`cerberus:~/meowp-studio/data/studio.db`):

    songs: 31 | with style_text: 31 | with genre set: 1

`songs.style_text` is the style prompt that made the track, and on every row it
opens by naming the genre:

    'Dark minimal warehouse tech house, 127 BPM. True 32-bar DJ intro...'
    'Dark warehouse tech house / minimal tech, 128 BPM...'
    'Chunky tech house / UK garage-infused bass house, 130 BPM...'
    'Dark acid house / breakbeat tech house, 127 BPM...'

**That slash is genre and genre2.** The four columns this feature fills are
already latent in a column that 31 of 31 rows have populated and that nothing
reads.

`genres.json` is Beatport-shaped — 24 top-level genres, 168 subgenres — and
`Electronic` already contains `Tech House`, `Bass House`, `Deep House`,
`Breaks / Breakbeat / UK Bass`. The vocabulary matches the prose almost word for
word. So the classifier is:

> **an LLM given `style_text` (plus title and, if it helps, the first lines of
> lyrics) and the `genres.json` taxonomy, asked to return four values from that
> taxonomy and nothing else.**

Text in, text out. It runs on the **local litellm gateway** `vision.py` already
talks to, costs nothing, needs no GPU, no audio model, no new dependency, and
does not queue behind a render. An audio classifier (CLAP, MERT, Essentia) would
be a new dependency, a GPU tenant on a card that is already the bottleneck, and
**less accurate than reading the label off the tin**.

### It suggests, it does not apply

The AI fills the genre bar; the user reviews and presses Save. Two reasons, and
neither is squeamishness:

- The taxonomy is closed. A model asked for free text will return "warehouse tech
  house", which is not one of the 168. **Validate every returned value against
  `genres.json` and drop what does not match** rather than inventing a row.
- The mass-apply UI being built here *is* the review step. Auto-writing 31 rows
  and then asking someone to check them is strictly more work than proposing 31
  rows they approve in one click.

Follow the precedent in `app.py`'s audio-edit route, where a prompt is read by a
local model into the same five parameters the sliders set, **clamped by the same
validation**. Same shape: the model fills the form, the form is what saves.

---

## Schema

**No migration.** `songs.genre` is in the original `CREATE TABLE`, and
`subgenre`, `genre2`, `subgenre2` were added in `db.MIGRATIONS`
(`studio/db.py:150-152`). All four exist and are unused on 30 of 31 rows.

---

## The work

### 1 · Selection and the genre bar

- A checkbox column, and a toggle-all in the header. The header sort already
  works — **toggle-all must apply to the rows currently shown**, not to every
  song in the database, or a filtered view silently edits things off-screen.
- The genre bar sits above the header, as asked. Four selects populated from
  `genres.json`; subgenre repopulates when its genre changes.
- **Blank means "leave alone", not "clear".** Someone setting only `genre2` on
  twelve songs must not have their `genre` wiped. If clearing is wanted it needs
  its own explicit control, not an empty select.
- Save posts `{song_ids: [...], genre, subgenre, genre2, subgenre2}` to one
  route. Server-side, every value is validated against `genres.json` before it
  reaches sqlite — the select is a convenience, not a guarantee.

### 2 · Async save

One `fetch` POST, JSON in, JSON out, patch the affected `<td>`s from the
response. The page already carries htmx; a small `hx-post` with an
`hx-swap="none"` and an event to update the cells is equally good and matches
what the anchor form does. Either is fine — **what matters is that the response
carries the saved values and the cells are painted from that**, not from what
was typed. A UI that shows what you asked for rather than what was stored is how
a silent validation drop becomes invisible.

### 3 · Async analyse

"Analyse all un-analysed songs" enqueues jobs today and the page must be
reloaded to see them land. It should instead poll the existing jobs API and
patch BPM / Key / Energy into each row as it completes.

**There is exactly one job worker and one GPU** (`studio/jobs.py`) — the button
must not imply parallelism it does not have. Show the queue position or a simple
"3 of 31" so a long run looks like progress rather than a hang.

### 4 · The suggest route

`POST /songs/genres/suggest` with a list of song ids → for each, the four
proposed values, validated against the taxonomy, plus the `style_text` fragment
they were drawn from. **Return the evidence.** "Tech House, because it says
*dark minimal warehouse tech house*" is reviewable; a bare label is not.

Batch them into one model call where the context allows — 31 style_texts is a
small prompt, and one call is both faster and more consistent than 31 calls that
can disagree with each other about the same album.

---

## Tests

- `test_bulk_genre_applies_only_to_checked_songs`
- `test_blank_genre_field_leaves_the_existing_value_alone` — the destructive
  mistake, tested rather than trusted.
- `test_genre_values_outside_genres_json_are_refused` — server-side, not
  select-side.
- `test_suggest_drops_values_not_in_the_taxonomy` — the free-text failure mode.
- `test_suggest_never_writes` — it proposes; Save writes.
- `test_analyse_all_skips_songs_that_already_have_bpm` — the button says
  "un-analysed"; make it mean it.

---

## Open questions

1. **Does the AI read lyrics as well as `style_text`?** `style_text` alone looks
   sufficient and is one short string. Lyrics are long, and `lyrics.py`'s own
   docstring warns the Whisper transcripts are mediocre — feeding a garbled
   transcript to a classifier that already has a clean label is how a good answer
   gets talked out of itself. Start with `style_text` and title only.
2. **What about songs with no `style_text`?** All 31 have one today, but an
   uploaded mp3 need not. Those are the only rows where audio analysis would
   ever be justified, and they should simply be left for manual entry until there
   are enough of them to matter.
3. **Which model?** `vision.py` already picks a local model off the gateway and
   falls back to xAI. This is a small, structured, non-visual task — it should
   prefer the local one and never silently spend on the fallback for something
   this cheap.
4. **Should genre become a filter?** Once 31 rows are populated, filtering the
   Library by genre is the obvious next want, and it is also what makes
   `SETS_MIXING_PLAN.md`'s harmonic ordering usable — "show me 128 BPM tech house
   in 8A" is a set-building query, not a browsing one. Out of scope here; worth
   knowing the data lands in a shape that supports it.
