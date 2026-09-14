"""Behavioral coverage for project-aware locked syncs in the Unix installer."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALLER = REPO_ROOT / "scripts" / "install.sh"


def _bash_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    drive = path.drive.rstrip(":").lower()
    tail = path.as_posix().split(":", 1)[1].lstrip("/")
    return f"/mnt/{drive}/{tail}"


def test_installer_keeps_bootstrap_config_isolated(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")
    result = subprocess.run(
        [bash, "-c", 'source "$1" --manifest >/dev/null; test "$UV_NO_CONFIG" = 1',
         "test-installer", _bash_path(INSTALLER)],
        env={**os.environ, "HOME": str(tmp_path), "HERMES_HOME": str(tmp_path / "hermes")},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "hermes").exists()


def test_locked_sync_helper_sanitizes_only_its_subprocess(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")

    record = tmp_path / "uv-args.txt"
    fake_uv = tmp_path / "uv with spaces"
    fake_uv.write_text(
        """#!/bin/sh
test -z "${UV_NO_CONFIG+x}" || exit 10
test -z "${UV_CONFIG_FILE+x}" || exit 11
test -d "$XDG_CONFIG_HOME" || exit 12
test "$XDG_CONFIG_HOME" = "$XDG_CONFIG_DIRS" || exit 13
printf '%s\\n' "$@" > "$RECORD"
""",
        encoding="utf-8", newline="\n",
    )
    fake_uv.chmod(0o755)
    harness = tmp_path / "harness.sh"
    harness.write_text(
        """#!/usr/bin/env bash
set -eu
source "$3" --manifest >/dev/null
UV_CMD="$1"
RECORD="$2"
export UV_CMD RECORD
export UV_NO_CONFIG=1
export UV_CONFIG_FILE=/poison/uv.toml
export XDG_CONFIG_HOME=/poison/user
export XDG_CONFIG_DIRS=/poison/system
run_locked_uv_sync /tmp/hermes-venv
test "$UV_NO_CONFIG" = 1
test "$UV_CONFIG_FILE" = /poison/uv.toml
test "$XDG_CONFIG_HOME" = /poison/user
test "$XDG_CONFIG_DIRS" = /poison/system
""",
        encoding="utf-8", newline="\n",
    )
    result = subprocess.run(
        [bash, _bash_path(harness), _bash_path(fake_uv), _bash_path(record), _bash_path(INSTALLER)],
        env={**os.environ, "HOME": str(tmp_path), "HERMES_HOME": str(tmp_path / "hermes")},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert record.read_text(encoding="utf-8").splitlines() == [
        "sync", "--extra", "all", "--locked",
    ]


@pytest.mark.skipif(os.name == "nt", reason="Unix installer behavior")
def test_real_uv_accepts_lock_when_project_config_is_restored(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is unavailable")
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """[project]
name = "installer-lock-regression"
version = "0.1.0"
requires-python = ">=3.11"

[project.optional-dependencies]
all = []

[tool.uv]
package = false
exclude-newer = "14 days"
""",
        encoding="utf-8",
    )
    isolated_config = tmp_path / "isolated-config"
    isolated_config.mkdir()
    clean_env = os.environ.copy()
    clean_env.pop("UV_NO_CONFIG", None)
    clean_env.pop("UV_CONFIG_FILE", None)
    clean_env["XDG_CONFIG_HOME"] = str(isolated_config)
    clean_env["XDG_CONFIG_DIRS"] = str(isolated_config)
    clean_env["UV_OFFLINE"] = "1"
    locked = subprocess.run(
        [uv, "lock"], cwd=project, env=clean_env,
        capture_output=True, text=True, check=False,
    )
    assert locked.returncode == 0, locked.stderr
    hidden_config_env = {**clean_env, "UV_NO_CONFIG": "1"}
    rejected = subprocess.run(
        [uv, "lock", "--check"], cwd=project, env=hidden_config_env,
        capture_output=True, text=True, check=False,
    )
    assert rejected.returncode != 0
    accepted = subprocess.run(
        [uv, "lock", "--check"], cwd=project, env=clean_env,
        capture_output=True, text=True, check=False,
    )
    assert accepted.returncode == 0, accepted.stderr
