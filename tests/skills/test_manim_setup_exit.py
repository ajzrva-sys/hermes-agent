"""The shipped Manim prerequisite checker must signal missing dependencies."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_missing_manim_prerequisites_fail(tmp_path):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("Bash is not installed on this host")
    script = Path(__file__).resolve().parents[2] / "skills/creative/manim-video/scripts/setup.sh"
    assert script.is_file()
    # A PATH entry may be a WSL launcher, not a shell for native file paths.
    try:
        probe = subprocess.run(
            [bash, "-c", 'test -r "$1"', "bash", str(script)],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("Bash cannot run on this host")
    if probe.returncode != 0:
        pytest.skip("Bash cannot access the native checker path")
    env = dict(os.environ, PATH=str(tmp_path))
    result = subprocess.run(
        [bash, str(script)], env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=10,
    )
    assert "prerequisite(s) missing" in result.stdout
    assert result.returncode != 0
