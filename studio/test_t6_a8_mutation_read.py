"""T6-A8: mutate the code and read what the mutation actually did.

docs/TRD-6 §0.4. Not "the check went red": *what changed*. One session's
mutation did not mutate anything and the check passed; another applied a
truthy str.replace that short-circuited an `or`. A flag believed without
reading it is a second unverified claim on top of the first.

Kill: drop the no-op refuse → silent pass on a mutation that changed
nothing. Differential: apply(old→new) reports n and the before/after
fragments; bool(source.replace(...)) is not accepted as evidence.
"""
import importlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

mutation_read = importlib.import_module("mutation_read")


def test_t6_a8_noop_when_old_absent_is_refused():
    """old not in source is a no-op. Believing the replace return is the bug."""
    source = "UNIQUE(path, check_name)\nINSERT OR IGNORE INTO findings"
    with pytest.raises(mutation_read.MutationNoOp, match="not found|unchanged"):
        mutation_read.apply(source, "UPSERT_THAT_IS_NOT_HERE", "broken")


def test_t6_a8_truthy_replace_is_not_evidence_of_mutation():
    """str.replace always returns the source when old is absent — truthy if
    non-empty. bool(replace(...)) therefore stays green on a no-op."""
    source = "def record(path, check_name): pass\n"
    replaced = source.replace("THIS_IS_NOT_IN_THE_SOURCE", "x")
    assert replaced == source
    assert bool(replaced), "non-empty source makes a no-op replace truthy"
    # The harness must still refuse — truthiness is not a reading.
    with pytest.raises(mutation_read.MutationNoOp):
        mutation_read.apply(source, "THIS_IS_NOT_IN_THE_SOURCE", "x")


def test_t6_a8_replace_or_source_short_circuit_is_a_silent_noop():
    """`source.replace(old, "") or source` restores the original when replace
    yields empty — the short-circuit that made a "mutation" do nothing."""
    source = "ONLY"
    trapped = source.replace("ONLY", "") or source
    assert trapped == source, "or-source trap restored the original"
    # apply with empty new must report the real change, not use the trap.
    report = mutation_read.apply(source, "ONLY", "")
    assert report["changed"] is True
    assert report["after"] == ""
    assert report["n"] == 1
    assert report["old"] == "ONLY"
    assert report["new"] == ""


def test_t6_a8_apply_reports_what_changed():
    """A real mutation returns n and the fragments — not only a flag."""
    source = (
        "def upsert(path, check_name):\n"
        "    INSERT OR IGNORE INTO findings\n"
        "    UNIQUE(path, check_name)\n"
    )
    report = mutation_read.apply(source, "INSERT OR IGNORE", "INSERT")
    assert report["changed"] is True
    assert report["n"] == 1
    assert report["old"] == "INSERT OR IGNORE"
    assert report["new"] == "INSERT"
    assert "INSERT OR IGNORE" in report["before"]
    assert "INSERT OR IGNORE" not in report["after"]
    assert "INSERT INTO findings" in report["after"]
    # read(before, after) is the shared entry (T6-A10): same report shape.
    again = mutation_read.read(report["before"], report["after"])
    assert again["changed"] is True
    assert again["n_chars_delta"] == len(report["after"]) - len(report["before"])


def test_t6_a8_read_unchanged_is_refused():
    """read(before, before) is the no-op form of the criterion."""
    src = "same\n"
    with pytest.raises(mutation_read.MutationNoOp, match="unchanged"):
        mutation_read.read(src, src)


def test_t6_a8_module_has_no_fastapi():
    """Methodology helper stays importable without a request (T6-A3 shape)."""
    import ast
    tree = ast.parse(open(mutation_read.__file__, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("fastapi"), alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("fastapi"), node.module
