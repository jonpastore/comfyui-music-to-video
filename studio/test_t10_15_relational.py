"""T10-15: mixadvice advice is relational and names what it is relative to.

docs/TRD-10 T10-15. "what happens at item 3 depends on what item 2 did" is
the module's own framing, so advice quoted without its neighbours is advice
about a different set. The one-sided failure is a check that stays green if
no advice is shown. The positive half requires neighbour/context references
that change when the surrounding set changes.
"""
import mixadvice


def _items_abc():
    return [
        {"id": 1, "title": "A", "bpm": 123.0, "key": "10A", "energy": 0.16},
        {"id": 2, "title": "B", "bpm": 126.0, "key": "11A", "energy": 0.22},
        {"id": 3, "title": "C", "bpm": 90.0, "key": "5B", "energy": 0.08},
    ]


def _sug_for_one():
    return mixadvice.clean(
        {"items": [{"id": 1, "transition": "fade", "secs": 4.0, "why": "close tempo"}]},
        {1, 2, 3})


def test_t10_15_advice_names_what_it_is_relative_to():
    """Each suggestion names the neighbours the handover is judged against."""
    items = _items_abc()
    sug = mixadvice.clean(
        {"items": [
            {"id": 1, "transition": "fade", "secs": 4.0, "why": "close tempo to B"},
            {"id": 2, "transition": "cut", "why": "energy drop into C"},
        ]},
        {1, 2, 3})
    payload = mixadvice.interface_payload(sug, items)
    by_id = {rec["id"]: rec for rec in payload["items"]}

    assert "relative_to" in by_id[1], by_id[1]
    assert by_id[1]["relative_to"]["into"]["id"] == 2
    assert by_id[1]["relative_to"]["into"]["title"] == "B"
    assert "from" not in by_id[1]["relative_to"]

    assert by_id[2]["relative_to"]["from"]["id"] == 1
    assert by_id[2]["relative_to"]["from"]["title"] == "A"
    assert by_id[2]["relative_to"]["into"]["id"] == 3
    assert by_id[2]["relative_to"]["into"]["title"] == "C"

    assert payload["order"] == [
        {"id": 1, "title": "A"},
        {"id": 2, "title": "B"},
        {"id": 3, "title": "C"},
    ]


def test_t10_15_neighbours_change_when_the_set_changes():
    """Positive half: surrounding-set change rewrites the references."""
    abc = _items_abc()
    cab = [abc[2], abc[0], abc[1]]  # C, A, B
    sug = _sug_for_one()
    p_abc = mixadvice.interface_payload(sug, abc)
    p_cab = mixadvice.interface_payload(sug, cab)
    a_abc = next(r for r in p_abc["items"] if r["id"] == 1)
    a_cab = next(r for r in p_cab["items"] if r["id"] == 1)

    assert a_abc["relative_to"] != a_cab["relative_to"]
    assert "from" not in a_abc["relative_to"]
    assert a_abc["relative_to"]["into"]["id"] == 2
    assert a_cab["relative_to"]["from"]["id"] == 3
    assert a_cab["relative_to"]["from"]["title"] == "C"
    assert a_cab["relative_to"]["into"]["id"] == 2
    assert mixadvice.about_set(p_abc) != mixadvice.about_set(p_cab)
    assert mixadvice.about_set(p_abc) == (1, 2, 3)
    assert mixadvice.about_set(p_cab) == (3, 1, 2)


def test_t10_15_quote_without_neighbours_is_a_different_set():
    """Advice quoted without its neighbours is advice about a different set."""
    items = _items_abc()
    payload = mixadvice.interface_payload(_sug_for_one(), items)
    full = mixadvice.about_set(payload)
    assert full == (1, 2, 3), full

    bare = mixadvice.quote_without_neighbours(payload)
    assert mixadvice.about_set(bare) != full
    assert mixadvice.about_set(bare) == ()
    # the form values survive the quote; only the relational frame is gone
    assert bare["items"][0]["transition"] == "fade"
    assert "relative_to" not in bare["items"][0]
    assert "order" not in bare
