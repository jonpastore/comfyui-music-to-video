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

HERE = os.path.dirname(os.path.abspath(__file__))


def test_cross_module_contracts():
    r = subprocess.run([sys.executable, os.path.join(HERE, "check_integration.py")],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    assert r.returncode == 0, f"check_integration.py failed:\n{r.stdout}\n{r.stderr}"
    assert "OK" in r.stdout, r.stdout
