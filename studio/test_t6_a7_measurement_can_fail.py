"""T6-A7: A measurement that cannot fail is not evidence.

docs/TRD-6 §0.4. Every criterion is a differential — one variable changed,
an expected direction — or it names the mutation that must break it.

Kill: collapse the product function under test so control equals mutated
(e.g. `jobs.canonical_path` always returns the same string) → the
differential assertion goes red. A presence-only grep for the def name,
or `assert True`, stays green under that mutation and is refused as
evidence by the equal-pair check below.
"""
import pytest

import jobs


def _assert_differential(control, mutated, *, label="T6-A7"):
    """Evidence requires control and mutated to differ (one variable)."""
    assert control != mutated, (
        f"{label}: control equals mutated — measurement cannot fail; "
        f"not evidence (control={control!r} mutated={mutated!r})"
    )


def test_t6_a7_equal_pair_is_not_evidence():
    """Same value both sides is refused as a criterion proof.

    Mutation that must break a real check is named by that check; this
    asserts the project treats an equal pair as no evidence at all.
    """
    with pytest.raises(AssertionError, match="cannot fail"):
        _assert_differential(1, 1)
    with pytest.raises(AssertionError, match="cannot fail"):
        _assert_differential("same", "same")
    _assert_differential(1, 2)
    _assert_differential("left", "right")


def test_t6_a7_canonical_path_depends_on_its_argument():
    """Product exemplar: one variable (the path) changes the output.

    Mutation: make `jobs.canonical_path` return a constant. This test goes
    red. Grep for `def canonical_path` would stay green — not evidence.
    """
    left = jobs.canonical_path("/studio/data/clips/left.mp4")
    right = jobs.canonical_path("/studio/data/clips/right.mp4")
    _assert_differential(left, right, label="T6-A7/canonical_path")


def test_t6_a7_t6_a4_distinctive_stub_is_a_differential(monkeypatch):
    """T6-A4's stub is itself a T6-A7 differential on the queue page.

    Control: service says 3 running while the active list has length 1.
    Page must show the service value ("3 running"), not len(active).
    Mutation: template recomputes from list length → "1 running" appears
    and the distinctive-number assertion fails. Vacuous `assert "running"
    in html` stays green under that mutation and is not the criterion.
    """
    import app as appmod
    from fastapi.testclient import TestClient

    n_running = 3
    n_waiting = 7
    elapsed = "12.7s"
    desc = "T6-A7-STUB-77"
    row = {
        "job": {"id": 77, "status": "running", "progress": "sheet 3/9",
                "error": None},
        "desc": desc,
        "elapsed": elapsed,
    }
    stub = {
        "queue_active": [row],
        "queue_waiting": [{
            "job": {"id": 78, "status": "queued", "progress": "", "error": None},
            "desc": "T6-A7-WAIT-78",
            "elapsed": None,
        }],
        "queue_recent": [],
        "queue_rows": [row],
        "queue_n_running": n_running,
        "queue_n_waiting": n_waiting,
        "queue_refresh_secs": 4,
    }
    assert n_running != len(stub["queue_active"]), (
        "fixture must keep counts off list lengths — otherwise the "
        "differential collapses and T6-A7 has no mutation to name"
    )
    assert n_waiting != len(stub["queue_waiting"])

    monkeypatch.setattr(appmod, "queue_ctx", lambda: stub)
    with TestClient(appmod.app) as client:
        html = client.get("/queue").text

    # Differential evidence (can fail if template recomputes):
    assert f"{n_running} running" in html, html
    assert f"{n_waiting} waiting" in html, html
    assert elapsed in html, html
    assert desc in html, html
    assert "1 running" not in html
    # Vacuous presence of the word is not the criterion:
    assert "running" in html  # stays green under len()-recompute mutation
    # The criterion is the distinctive number, not the word.
    _assert_differential(n_running, len(stub["queue_active"]))
