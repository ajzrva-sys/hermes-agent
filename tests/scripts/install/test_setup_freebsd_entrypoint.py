"""The developer entrypoint reuses the native installer without updating Git."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.freebsd_only
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("fail_stage", ["", "venv"])
def test_developer_setup_reuses_stages_and_stops_on_failure(tmp_path, fail_stage):
    project = tmp_path / "checkout with spaces"
    (project / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "setup-hermes.sh", project)
    record = tmp_path / "calls.jsonl"
    recorder = project / "record.py"
    recorder.write_text(
        'import json,os,sys\n'
        'args=sys.argv[1:]\n'
        'with open(os.environ["RECORD"],"a") as f: f.write(json.dumps(args)+"\\n")\n'
        'sys.exit(19 if args[args.index("--stage")+1] == os.environ["FAIL_STAGE"] else 0)\n')
    installer = project / "scripts/install.sh"
    import shlex
    installer.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(recorder))} "$@"\n')
    installer.chmod(0o755)
    blockers = tmp_path / "bin"
    blockers.mkdir()
    for name in ("uv", "curl", "pkg", "npm"):
        command = blockers / name
        command.write_text("#!/bin/sh\nexit 91\n")
        command.chmod(0o755)
    result = subprocess.run(
        ["bash", str(project / "setup-hermes.sh"), "--skip-setup", "--hermes-home", str(tmp_path / "data")],
        env={"HOME": str(tmp_path), "PATH": str(blockers) + ":" + os.environ["PATH"], "RECORD": str(record),
             "FAIL_STAGE": fail_stage, "SHELL": "/usr/local/bin/bash"},
        capture_output=True, text=True, timeout=30)
    calls = [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []
    stages = [args[args.index("--stage") + 1] for args in calls]
    expected = ["prerequisites", "venv"] if fail_stage else [
        "prerequisites", "venv", "python-deps", "node-deps", "path", "config", "setup", "complete"]
    assert stages == expected, result.stdout + result.stderr
    assert result.returncode == (19 if fail_stage else 0)
    for args in calls:
        assert args[args.index("--dir") + 1] == str(project)
        assert "--skip-setup" in args
        assert args[args.index("--hermes-home") + 1] == str(tmp_path / "data")
