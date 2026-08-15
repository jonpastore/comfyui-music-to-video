"""T2-5: editing an arc prompt versions; restore puts the previous text back.

docs/TRD-2 §3.3. Versioning reuses prompts.py. A linear history with
restore is the whole requirement. Retrieval alone is the one-sided half:
get() stays green when restore is deleted.

Mutation: delete restore → current stays the edit and this fails.
Mutation: edit overwrites the row → the previous version is gone.
"""
import prompts
import arc


ALBUM = "Street Cats T2-5"
FIRST = "it should end somewhere colder than it started"
SECOND = "the city is louder and the collar is still brass"


def test_t2_5_edit_creates_version_restore_puts_previous_text_back():
    v1 = arc.save_prompt(ALBUM, FIRST, "first theme")
    assert v1["prompt_type"] == "arc"
    assert v1["text"] == FIRST
    assert v1["version_number"] == 1

    v2 = arc.save_prompt(ALBUM, SECOND, "louder city")
    assert v2["id"] != v1["id"]
    assert v2["version_number"] == 2
    assert arc.current_prompt(ALBUM)["text"] == SECOND

    previous = prompts.get(v1["id"])
    assert previous is not None
    assert previous["text"] == FIRST
    assert previous["version_number"] == 1

    restored = arc.restore_prompt(v1["id"])
    assert restored["text"] == FIRST
    assert arc.current_prompt(ALBUM)["text"] == FIRST
    assert prompts.get(v1["id"])["text"] == FIRST
    assert prompts.get(v2["id"])["text"] == SECOND
