"""Run every module's demo() self-check as part of `pytest`.

Each module carries a demo() holding this codebase's real evidence -- the frame
differential that proves `layer` reaches the picture, the dB differential that
proves `duck` does not duck the whole set from t=0, the duration differential
for a fade to black, the negative-prompt drop at cfg 1.0. They are the checks
that can actually fail.

Nothing ran them. There is no CI, deploy.sh runs neither pytest nor a demo, and
`grep -rn "demo()"` across the test files found no caller: every one of those
numbers was reachable only by hand-typing `python3 mixer.py`, which is exactly
what a hurried session skips -- and the ffmpeg-heavy ones are both the slowest
to run and the most load-bearing.

Subprocesses, not imports: conftest.py replaces pipeline/grok/lyrics/mixer in
sys.modules for the whole session, so importing the real module here would get
the stub. A clean interpreter is the only way this checks what it claims to --
the same reason test_seams.py shells out to check_integration.py.
"""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))

# Fast, pure ones: string and arithmetic checks, no ffmpeg, no network.
PURE = ["effects", "video_fx", "beatmatch", "mixadvice", "tiers", "prompts",
        "publish", "models", "jobs", "gpu", "chat", "creds", "arc", "analyse"]

# No demo() and no __main__ -- running it just imports the module and builds the
# schema. That is still worth doing (an import error or a broken migration shows
# up here) but there is no OK line to look for, so it is checked on exit status
# alone rather than pretending it reports something it does not.
SMOKE = ["db"]

# These shell out to ffmpeg and take real seconds. They are also the ones
# holding the measurements the continuation docs quote, so they are worth the
# wait -- run `pytest -m "not slow"` to skip them.
SLOW = ["mixer", "pipeline"]

# The workflow BUILDERS live at the repo root, not in studio/, and their
# self-checks were in exactly the state this file's docstring describes: written,
# load-bearing, and run by nobody. make_postproc's holds the frame-rate
# arithmetic that decides whether an interpolated clip is the length it started;
# make_audio's holds the assertion that the image guardrail has not come back
# onto the audio path. Their demo is behind `--demo` because argparse owns argv.
ROOT = os.path.dirname(HERE)
ROOT_SCRIPTS = ["make_audio", "make_postproc"]


def _run(mod, timeout, argv=(), cwd=None):
    cwd = cwd or HERE
    path = os.path.join(cwd, f"{mod}.py")
    if not os.path.isfile(path):
        pytest.skip(f"{mod}.py not present")
    r = subprocess.run([sys.executable, path, *argv], capture_output=True, text=True,
                       timeout=timeout, cwd=cwd)
    assert r.returncode == 0, (
        f"{mod}.py self-check FAILED\n--- stdout ---\n{r.stdout[-3000:]}\n"
        f"--- stderr ---\n{r.stderr[-3000:]}")
    return r.stdout


@pytest.mark.parametrize("mod", PURE)
def test_module_selfcheck(mod):
    out = _run(mod, timeout=180)
    assert "OK" in out, f"{mod}.py did not report OK: {out[-300:]}"


@pytest.mark.parametrize("mod", SMOKE)
def test_module_imports_cleanly(mod):
    _run(mod, timeout=120)          # exit 0 is the whole contract here


@pytest.mark.slow
@pytest.mark.parametrize("mod", SLOW)
def test_module_selfcheck_slow(mod):
    out = _run(mod, timeout=900)
    assert "OK" in out, f"{mod}.py did not report OK: {out[-300:]}"


@pytest.mark.parametrize("mod", ROOT_SCRIPTS)
def test_root_script_selfcheck(mod):
    out = _run(mod, timeout=120, argv=["--demo"], cwd=ROOT)
    assert "OK" in out, f"{mod}.py did not report OK: {out[-300:]}"
