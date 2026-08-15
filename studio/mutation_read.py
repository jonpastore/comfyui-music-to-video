"""T6-A8: mutate the code and read what the mutation actually did.

docs/TRD-6 §0.4. A no-op mutation that still "passes" is the failure mode
this module exists to catch. str.replace returns the original string when
old is absent — truthy if the source is non-empty — so bool(replace(...))
is not evidence. `source.replace(old, new) or source` restores the
original when replace yields empty (the short-circuit that made one
session's mutation do nothing).

Callers apply or read through this module and assert on the report, not on
a bare flag.
"""
from __future__ import annotations


class MutationNoOp(ValueError):
    """Raised when a claimed mutation left the source unchanged."""


def read(before: str, after: str) -> dict:
    """Report what changed between before and after source text.

    Raises MutationNoOp when nothing changed. A flag without this reading
    is the second unverified claim T6-A8 forbids.
    """
    if before == after:
        raise MutationNoOp("source unchanged: mutation did not mutate")
    return {
        "changed": True,
        "before": before,
        "after": after,
        "before_len": len(before),
        "after_len": len(after),
        "n_chars_delta": len(after) - len(before),
    }


def apply(source: str, old: str, new: str, count: int | None = None) -> dict:
    """Apply old→new and return what actually changed.

    Never uses `replace(...) or source`. Empty `new` is allowed and
    reported when it truly removes `old`. Raises MutationNoOp when `old`
    is absent (the no-op that truthy str.replace would hide).
    """
    if old == "":
        raise ValueError("empty old is not a targeted mutation")
    n = source.count(old)
    if n == 0:
        raise MutationNoOp(f"old not found: {old!r}")
    if count is None:
        after = source.replace(old, new)
        n_applied = n
    else:
        after = source.replace(old, new, count)
        n_applied = min(n, count)
    # Do not write `after = source.replace(...) or source` — that trap
    # restores the original when new is empty and old matched the whole
    # string, turning a successful delete into a silent no-op.
    report = read(source, after)
    report["old"] = old
    report["new"] = new
    report["n"] = n_applied
    return report
