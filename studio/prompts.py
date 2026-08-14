"""Versioned prompt text, for every kind of prompt this studio sends.

ONE table for all of them. Before this there were two half-systems: anchor
prompts lived in `anchor_prompts` with a `kind` column bolted on to make the
negative fit, and the component fields (identity, wardrobe, body) had no history
at all -- editing one overwrote the previous wording with nothing kept. So the
question "what did I have in the body field when that sheet came out right?" had
no answer, which is the question this table exists to answer.

A version is IMMUTABLE in the sense that matters: `text` may be corrected and
`label` renamed, but a new wording is a NEW version with the next number, never
an overwrite. Prompts are tuned by comparing renders, and the one you want back
is usually the one before last.

usage_count is incremented when a version is actually SENT to the renderer, not
when it is loaded into the form -- a wording you looked at and rejected is not a
wording you used, and a count that conflated the two would rank the ones you
scrolled past.

Scope: an album, optionally a tier, optionally a character. A tier of "" means
the type is album-wide (the negative prompt is: its terms are this release's
failure modes and they do not vary by rating). character_id NULL is the
protagonist, exactly as it is for anchors.
"""
import os
import sys
import time

import db

sys.path.insert(0, os.environ.get("STUDIO_SCRIPTS") or
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import make_anchor  # noqa: E402

# Every kind of prompt text that gets versioned, and whether it is scoped to a
# tier. The composer fields are the ones make_anchor.prompt_for assembles; the
# other two are the free text the anchor form sends alongside them.
#
# Adding a type here is all that is needed to give it history -- the CRUD below
# is type-agnostic on purpose, because the last two additions to this area
# (the negative, then the tier wording) each arrived as a bespoke route.
PROMPT_TYPES = {
    "identity":      {"tiered": False, "label": "Character identity"},
    "wardrobe":      {"tiered": False, "label": "Wardrobe"},
    "body":          {"tiered": False, "label": "Body consistency"},
    "nude_wardrobe": {"tiered": False, "label": "Nude wording"},
    "anatomy":       {"tiered": False, "label": "Anatomy on nude sheets"},
    # Constants until docs/TRD-7 T7-14/T7-15: the studio backdrop reaches every
    # sheet, and the composite clause decides whether several references are one
    # character or several. Untiered -- what a studio looks like and how many
    # people are in the frame are not functions of the rating.
    "backdrop":      {"tiered": False, "label": "Backdrop and framing"},
    "composite":     {"tiered": False, "label": "Multiple references"},
    # Optional, per-sheet: what the character is DOING. Untiered — an action is
    # not a function of the rating. Replaces the view's stance clause rather
    # than sitting beside it. docs/TRD-7 T7-16.
    "pose":          {"tiered": False, "label": "Pose"},
    "negative":      {"tiered": False, "label": "Negative prompt"},
    # The one that genuinely varies by rating: what R permits and XXX permits
    # are different sentences by definition.
    "tier_wording":  {"tiered": True,  "label": "Tier wording"},
    "positive":      {"tiered": True,  "label": "Full positive prompt"},
    # A QC finding's proposed remedy. docs/TRD-3 T3-20: the remedy is an
    # EDITABLE prompt and approving it is the human sign-off, so it gets the
    # same history as every other prompt here rather than a bespoke store.
    # Untiered: what is wrong with a render is not a function of its rating.
    "qc_remedy":     {"tiered": False, "label": "QC remedy"},
}
# T7-13: one type per view, generated from the view table so T7-1 still holds.
# Untiered — camera placement is not a function of the rating.
PROMPT_TYPES.update({
    f"view:{key}": {"tiered": False, "label": f"View framing ({spec['label']})"}
    for key, spec in make_anchor.VIEWS.items()
})

MAX_LABEL = 80
MAX_TEXT = 4000


def _norm(prompt_type, tier, character_id):
    if prompt_type not in PROMPT_TYPES:
        raise ValueError(f"unknown prompt type: {prompt_type!r}")
    # A type that is not tiered stores "" rather than whatever tier happened to
    # be ticked when it was saved. Without this the same negative saved from two
    # tier tabs became two histories of one thing.
    tier = (tier or "") if PROMPT_TYPES[prompt_type]["tiered"] else ""
    return tier, (int(character_id) if character_id else None)


def versions(album, prompt_type, tier="", character_id=None):
    """Every saved version of one prompt, newest FIRST."""
    tier, character_id = _norm(prompt_type, tier, character_id)
    return db.q("""SELECT * FROM prompt_versions
                   WHERE scope_value=? AND prompt_type=? AND tier=? AND character_id IS ?
                   ORDER BY version_number DESC""",
                album or "", prompt_type, tier, character_id)


def get(vid):
    return db.one("SELECT * FROM prompt_versions WHERE id=?", vid)


def latest(album, prompt_type, tier="", character_id=None):
    rows = versions(album, prompt_type, tier, character_id)
    return rows[0] if rows else None


def check(text, label):
    """Shared validation. Raises ValueError; the caller turns it into a 400."""
    text = (text or "").strip()
    label = " ".join((label or "").split())[:MAX_LABEL]
    if not text:
        raise ValueError("nothing to save -- the box is empty")
    if len(text) > MAX_TEXT:
        raise ValueError(f"that is {len(text)} characters; keep it under {MAX_TEXT}")
    if not label:
        # Versions are listed BY name. An unnamed one cannot be told from every
        # other unnamed one, which makes the history unusable at exactly the
        # point it becomes worth having -- when there are several.
        raise ValueError("name this version so it can be told from the others")
    return text, label


def save(album, prompt_type, text, label, tier="", character_id=None):
    """A NEW version, numbered from the last one for this exact scope."""
    if not album:
        raise ValueError("an album is needed to save a prompt")
    tier, character_id = _norm(prompt_type, tier, character_id)
    text, label = check(text, label)
    if prompt_type.startswith("view:") or prompt_type in (
            "identity", "wardrobe", "body", "nude_wardrobe", "anatomy",
            "backdrop", "composite", "pose", "positive", "tier_wording"):
        import tiers
        tiers.check_text(text, prompt_type)
        tiers.check_override(text)
    row = db.one("""SELECT MAX(version_number) AS n FROM prompt_versions
                    WHERE scope_value=? AND prompt_type=? AND tier=? AND character_id IS ?""",
                 album, prompt_type, tier, character_id)
    number = (row["n"] or 0) + 1
    now = time.time()
    vid = db.run("""INSERT INTO prompt_versions (scope_value, tier, character_id, prompt_type,
                                                  version_number, label, text, created, updated,
                                                  usage_count)
                    VALUES (?,?,?,?,?,?,?,?,?,0)""",
                 album, tier, character_id, prompt_type, number, label, text, now, now)
    return get(vid)


def update(vid, text=None, label=None):
    """Correct a version in place -- a typo, or a better name.

    NOT how a new wording is stored: that is save(), which takes the next
    number. This exists because a version whose label says "with the tail fix"
    and whose text has a typo in it is worth repairing rather than superseding.
    """
    row = get(vid)
    if not row:
        raise ValueError("that version no longer exists")
    new_text = row["text"] if text is None else text
    new_label = row["label"] if label is None else label
    new_text, new_label = check(new_text, new_label)
    db.run("UPDATE prompt_versions SET text=?, label=?, updated=? WHERE id=?",
           new_text, new_label, time.time(), vid)
    return get(vid)


def delete(vid):
    """Remove one version. Version NUMBERS are not renumbered afterwards.

    Deliberately: the number is how a render is referred to after the fact
    ("body v3"), and closing the gap would silently make an old note point at
    different text. Gaps in the sequence are the honest record.
    """
    row = get(vid)
    if not row:
        raise ValueError("that version no longer exists")
    db.run("DELETE FROM prompt_versions WHERE id=?", vid)
    return row


def mark_used(vids):
    """Count a version as USED -- called when a render is queued with it, never
    when it is merely loaded into the form.

    TOTAL BY CONSTRUCTION: anything that is not a version id is skipped rather
    than raising. This is a usage counter, and it is called AFTER the jobs are
    enqueued -- so an exception here does not prevent a bad render, it reports
    failure for renders that are already running. It did exactly that: the
    negative picker's "the generic starting point" option carries the sentinel
    value "default", int() raised on it, and a sweep 500'd with eleven jobs
    already queued while the batch panel said "Nothing was queued" and dropped
    their watch lines and their Cancel buttons.

    The sentinel is also filtered client-side, in markUsedVersion. Both, because
    a counter that can fail a render is the wrong shape whatever feeds it.
    """
    for raw in set(vids or ()):
        try:
            vid = int(raw)
        except (TypeError, ValueError):
            continue
        db.run("UPDATE prompt_versions SET usage_count = usage_count + 1 WHERE id=?", vid)


def summary(row):
    """One line for a picker: number, name, and how much it has been used."""
    used = row["usage_count"] or 0
    return (f"v{row['version_number']} · {row['label'] or 'unnamed'}"
            + (f" · used {used}x" if used else " · unused"))


def demo():
    """Self-check: numbering, scoping, and what counts as usage."""
    import os, tempfile
    db.DATA = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(db.DATA, "t.db")
    db._local.__dict__.clear()

    a = save("Street Cats", "body", "All black fur.", "first")
    b = save("Street Cats", "body", "All black fur, per limb.", "per limb")
    assert (a["version_number"], b["version_number"]) == (1, 2), (a["version_number"],
                                                                  b["version_number"])
    assert [r["version_number"] for r in versions("Street Cats", "body")] == [2, 1], "not newest-first"
    assert latest("Street Cats", "body")["label"] == "per limb"

    # a second album numbers from one again -- the sequence is per scope
    assert save("Catatonic", "body", "Ginger fur.", "ginger")["version_number"] == 1
    assert len(versions("Street Cats", "body")) == 2, "one album's history reached another"

    # an UNTIERED type ignores the tier it was saved from, or the same negative
    # saved from two tier tabs becomes two histories of one thing
    n1 = save("Street Cats", "negative", "white fur", "a", tier="r")
    n2 = save("Street Cats", "negative", "white fur, cream tail", "b", tier="xxx")
    assert n2["version_number"] == 2, "an untiered type split its history by tier"
    assert len(versions("Street Cats", "negative", tier="anything")) == 2

    # ...while a TIERED one keeps them apart, because what R and XXX permit are
    # different sentences by definition
    t1 = save("Street Cats", "tier_wording", "Club wear.", "r wording", tier="r")
    t2 = save("Street Cats", "tier_wording", "Explicit.", "xxx wording", tier="xxx")
    assert (t1["version_number"], t2["version_number"]) == (1, 1), "a tiered type merged two tiers"

    # a character's history is its own
    c1 = save("Street Cats", "identity", "The duet partner.", "duet", character_id=7)
    assert c1["version_number"] == 1
    assert not versions("Street Cats", "identity"), "a cast member's version reached the album"

    # naming is required, and an empty box is not a version
    for bad_text, bad_label, why in ((" ", "x", "empty text"), ("something", "  ", "no name")):
        try:
            save("Street Cats", "body", bad_text, bad_label)
            raise AssertionError(f"{why} was accepted")
        except ValueError:
            pass

    # update CORRECTS in place and does not take a new number
    fixed = update(b["id"], text="All black fur, per limb, uniformly.")
    assert fixed["version_number"] == 2 and "uniformly" in fixed["text"]
    assert fixed["updated"] >= fixed["created"]
    assert len(versions("Street Cats", "body")) == 2, "an update created a version"

    # usage is counted when a render USES it, not when it is looked at
    assert latest("Street Cats", "body")["usage_count"] == 0
    # deduped, and everything that is not an id is SKIPPED rather than raising:
    # this runs after the jobs are enqueued, so an exception here reports failure
    # for renders that are already running. "default" is the negative picker's
    # own sentinel and is exactly what took a sweep down with 11 jobs queued.
    mark_used([b["id"], b["id"], None, "", "default", "abc", 0])
    assert get(b["id"])["usage_count"] == 1, get(b["id"])["usage_count"]
    mark_used([b["id"]])
    assert get(b["id"])["usage_count"] == 2
    assert "used 2x" in summary(get(b["id"]))
    assert "unused" in summary(get(a["id"]))

    # deleting leaves a GAP rather than renumbering: the number is how a render
    # is referred to afterwards, and closing the gap would repoint an old note
    delete(a["id"])
    assert [r["version_number"] for r in versions("Street Cats", "body")] == [2]
    assert save("Street Cats", "body", "third try", "third")["version_number"] == 3, \
        "a deleted version's number was reused"

    try:
        save("Street Cats", "nonsense", "x", "y")
        raise AssertionError("an unknown prompt type was accepted")
    except ValueError:
        pass

    print("prompts.py OK")
    return True


if __name__ == "__main__":
    demo()
