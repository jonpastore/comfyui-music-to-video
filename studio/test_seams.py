"""Runs check_integration.py as a subprocess so plain `pytest` covers it too.

check_integration.py is a SCRIPT, not a pytest module: it performs its checks at
import time and calls sys.exit() on failure. Named test_*.py it was collected by
pytest, executed during collection, and its sys.exit aborted the whole run with
INTERNALERROR before a single test ran -- `pytest` with no arguments reported
"1 warning" and zero tests while every file passed individually.

It also cannot run in-process under pytest at all: conftest.py installs stubs
into sys.modules, so the cross-module contract checks would inspect the stubs
instead of the real modules and fail for the wrong reason. A subprocess gets a
clean interpreter, which is the only way it can check what it claims to check.
"""
import os
import subprocess
import sys

import mixer          # the STUB, installed by conftest

HERE = os.path.dirname(os.path.abspath(__file__))


def test_a_stub_serves_real_constants_and_refuses_real_functions():
    """The stub-gap fix, which has now cost five separate debugging sessions.

    A stub exists to keep ffmpeg, the GPU and the network out of the tests --
    not to hide constants. When app.py started reading a new constant off a
    stubbed module the whole suite died at IMPORT with a bare AttributeError
    pointing at conftest rather than at the line that needed changing.

    Both halves matter, so both are asserted. Only the first would leave a stub
    that silently shells out to ffmpeg."""
    import types
    assert isinstance(sys.modules["mixer"], types.ModuleType)
    assert not hasattr(sys.modules["mixer"], "__file__"), "this is not the stub"

    # plain data comes through from the real mixer.py, unmirrored
    assert "black" in mixer.TRANSITIONS and mixer.BLACK == "black"
    assert mixer._XFADE_NAMES["wipe"] == "wipeleft"
    from conftest import _real_module
    assert mixer.TRANSITIONS == _real_module("mixer").TRANSITIONS, \
        "the stub served a value that has drifted from the real module"

    # a callable the stub does not define is REFUSED, by name, with the fix
    try:
        mixer.apply_tempo_ramp
        raise AssertionError("the stub fell through to a real function")
    except AttributeError as e:
        assert "apply_tempo_ramp" in str(e) and "conftest.py" in str(e), e

    # and something that exists nowhere is still a plain missing attribute
    try:
        mixer.no_such_thing_at_all
        raise AssertionError("an invented attribute was served")
    except AttributeError as e:
        assert "no attribute" in str(e), e


def test_cross_module_contracts():
    r = subprocess.run([sys.executable, os.path.join(HERE, "check_integration.py")],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    assert r.returncode == 0, f"check_integration.py failed:\n{r.stdout}\n{r.stderr}"
    assert "OK" in r.stdout, r.stdout
