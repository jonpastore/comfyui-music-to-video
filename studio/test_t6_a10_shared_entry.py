"""T6-A10: Assert through the shared entry point, never through the function
it wraps.

docs/TRD-6 §0.4. Earned on T1-20d, 2026-08-13: correct, thorough checks aimed
one level too low stayed green through a call site deliberately set to the
wrong value, because they exercised the wrapped function directly. Two correct
call sites is not a property a per-function check can see.

Named collapse points: mixer.item_chains (wraps _audio_chain),
mixer.set_duration, build_song.clip_plan, effects.measure_loudness,
models.canonical_host, jobs.canonical_path, screen_prompt_field.

Kill: rewire item_chains to pass master=False always → the shared-entry
assertion goes red. A check that only calls _audio_chain(..., master=True)
stays green under that mutation and is refused as evidence by the bypass
demonstration below.
"""
import ast

import pytest

from conftest import _real_module


mixer = _real_module("mixer")
assert mixer is not None, "real mixer.py failed to import"


def _mixed_set():
    """One curved item + one bare: the T1-20d shape where wiring matters."""
    return [
        {"automation": {"suppress_loudnorm": True}},
        {"automation": {"suppress_loudnorm": False}},
    ]


def test_t6_a10_bypass_stays_green_under_broken_shared_entry(monkeypatch):
    """A check aimed at the wrapped function is blind to call-site wiring.

    Mutate item_chains to pass master=False (the T1-20d video-site bug).
    Direct _audio_chain(..., master=True) still looks correct — that is why
    T6-A10 forbids asserting there.
    """
    its = _mixed_set()

    def broken(items):
        return [
            mixer._audio_chain(
                it.get("gain_db"), it.get("effects_json"),
                it.get("automation"), master=False,
            )
            for it in items
        ]

    monkeypatch.setattr(mixer, "item_chains", broken)

    # Bypass construction (forbidden by T6-A10): stays green.
    for it in its:
        chain = mixer._audio_chain(
            0, None, it.get("automation"), master=True,
        )
        assert "loudnorm" not in chain, (
            "bypass check must stay green under broken wiring — if this "
            "fails, the trap demonstration itself is wrong"
        )

    # Same mutation, through the shared entry: the defect is visible.
    per = [c.count("loudnorm") for c in mixer.item_chains(its)]
    assert per == [0, 1], (
        f"broken master=False wiring must show on the uncurved item "
        f"through item_chains (got per-item={per})"
    )


def test_t6_a10_mixed_set_through_item_chains_is_levelled_once():
    """Product exemplar: the shared entry applies master_engaged to every item.

    one curved, one not → both lose per-item loudnorm; master carries the one.
    Asserted through item_chains, not _audio_chain. Mutation: item_chains
    forces master=False → worst signal path becomes 2 and this goes red.
    """
    its = _mixed_set()
    assert mixer.master_engaged(its) is True

    per = [c.count("loudnorm") for c in mixer.item_chains(its)]
    mls, _ = mixer._master_lines(its, [], "a0")
    n_master = sum(l.count("loudnorm") for l in mls)
    worst = max(p + n_master for p in per)

    assert per == [0, 0], (
        f"item_chains must strip per-item loudnorm when master is engaged "
        f"(per-item={per}); calling _audio_chain per item with the wrong "
        f"master flag is the T6-A10 defect"
    )
    assert n_master == 1, n_master
    assert worst == 1, (
        f"one curved, one not: {worst} loudnorms in series on one signal path "
        f"(per-item={per}, master={n_master}). A set is levelled ONCE."
    )


def test_t6_a10_production_has_one_audio_chain_call_inside_item_chains():
    """Structural half: the collapse point is the only production call site.

    A second production `_audio_chain(...)` outside item_chains re-opens the
    two-call-site smell T6-A10 exists to catch. `demo` selfchecks and the
    `if __name__` harness are not production wiring.
    """
    path = mixer.__file__
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)

    _SKIP_FUNCS = frozenset({"demo"})

    class _Finder(ast.NodeVisitor):
        def __init__(self):
            self.calls = []  # (lineno, in_item_chains)
            self._in_item_chains = False
            self._skip_depth = 0

        def visit_FunctionDef(self, node):
            if node.name in _SKIP_FUNCS:
                self._skip_depth += 1
                self.generic_visit(node)
                self._skip_depth -= 1
                return
            prev = self._in_item_chains
            if node.name == "item_chains":
                self._in_item_chains = True
            self.generic_visit(node)
            self._in_item_chains = prev

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_If(self, node):
            # Skip `if __name__ == "__main__":` harness entirely.
            t = node.test
            if (
                isinstance(t, ast.Compare)
                and isinstance(t.left, ast.Name)
                and t.left.id == "__name__"
            ):
                return
            self.generic_visit(node)

        def visit_Call(self, node):
            if self._skip_depth == 0:
                fn = node.func
                name = None
                if isinstance(fn, ast.Name):
                    name = fn.id
                elif isinstance(fn, ast.Attribute):
                    name = fn.attr
                if name == "_audio_chain":
                    self.calls.append((node.lineno, self._in_item_chains))
            self.generic_visit(node)

    finder = _Finder()
    finder.visit(tree)

    assert finder.calls, "_audio_chain must be called from item_chains"
    outside = [ln for ln, inside in finder.calls if not inside]
    inside = [ln for ln, inside in finder.calls if inside]
    assert outside == [], (
        f"production _audio_chain call outside item_chains at lines {outside}. "
        f"T6-A10: the shared entry is the only wiring point."
    )
    assert len(inside) == 1, (
        f"expected exactly one _audio_chain call inside item_chains, "
        f"got lines {inside}"
    )

    # Both render paths must go through item_chains (the collapse point).
    item_chains_callers = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in _SKIP_FUNCS or node.name == "item_chains":
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            fn = child.func
            name = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else None
            )
            if name == "item_chains":
                item_chains_callers.append(node.name)
    assert "mix_audio" in item_chains_callers or len(item_chains_callers) >= 2, (
        f"render paths must call item_chains; found callers {item_chains_callers}"
    )


def test_t6_a10_canonical_host_is_the_shared_host_identity():
    """Second named collapse point: models.canonical_host, not inlined splits.

    Two spellings of the same box (loopback vs SELF_HOST) collapse here.
    Assert through canonical_host; a check that only re-implements the split
    would stay green if a call site stopped using it.
    """
    import models

    self_host = models.SELF_HOST
    assert models.canonical_host("127.0.0.1") == self_host
    assert models.canonical_host(f"http://127.0.0.1:7801") == self_host
    assert models.canonical_host("http://gamingpc:7801") == "gamingpc"
    # Differential: two distinct non-loopback hosts stay distinct.
    assert models.canonical_host("http://a:1") != models.canonical_host("http://b:1")
