"""T2-6: deleting a version does not renumber the others.

docs/TRD-2 §3.3: version numbers are how a render is referred to after
the fact ("body v3"). Closing the gap would silently point an old note
at different text.

A check that only asserts remaining numbers were not compacted stays
green when delete is a no-op. The positive half is: row count drops by
one first, then the survivors keep the numbers they were saved with.

Mutation: make delete a no-op → row-count arm red.
Mutation: compact remaining numbers → survivors-arm red.
"""
import prompts


def test_t2_6_delete_drops_a_row_and_does_not_renumber():
    album = "T2-6 Delete Album"
    kind = "body"
    v1 = prompts.save(album, kind, "first wording", "first")
    v2 = prompts.save(album, kind, "second wording", "second")
    v3 = prompts.save(album, kind, "third wording", "third")
    assert [r["version_number"] for r in prompts.versions(album, kind)] == [3, 2, 1]
    before = len(prompts.versions(album, kind))
    assert before == 3

    deleted = prompts.delete(v2["id"])
    assert deleted["id"] == v2["id"]
    assert deleted["version_number"] == 2

    left = prompts.versions(album, kind)
    assert len(left) == before - 1, "delete was a no-op; a no-op renumbers nothing"
    assert [r["version_number"] for r in left] == [3, 1], (
        "remaining versions were renumbered; the gap is the honest record")
    assert prompts.get(v2["id"]) is None
    assert prompts.get(v1["id"])["version_number"] == 1
    assert prompts.get(v3["id"])["version_number"] == 3

    v4 = prompts.save(album, kind, "fourth wording", "fourth")
    assert v4["version_number"] == 4, "a deleted version's number was reused"
