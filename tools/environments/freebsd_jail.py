"""Native job-per-command backend. Never inherit LocalEnvironment host shortcuts."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import threading

from hermes_constants import get_hermes_home
from tools.environments.base import BaseEnvironment
from tools.environments.base_output import _pipe_stdin
from tools.environments.base_session_env import _snapshot_bootstrap_script
from tools.freebsd_jail_client import capabilities, spawn
from tools.freebsd_jail_policy import Grant, JailPolicy, project_policy


class FreeBSDJailEnvironment(BaseEnvironment):
    _hermes_backend_name = "freebsd_jail"

    def __init__(self, cwd: str, timeout: int = 180, *, policy: JailPolicy | None = None,
                 bridge: Path | None = None):
        # Probe and validate authority before allocating any session state.
        capabilities(bridge)
        self.policy = policy or project_policy(cwd, home=Path.home(), profile=get_hermes_home())
        self._bridge = bridge
        self._process_lock = threading.Lock()
        self._processes = set()
        self._scratch = Path(tempfile.mkdtemp(prefix="hermes-jail-", dir="/var/tmp"))
        self.policy = JailPolicy(self.policy.workspace,
                                 (*self.policy.grants, Grant(str(self._scratch), "write")),
                                 self.policy.network)
        super().__init__(cwd=self.policy.workspace, timeout=timeout)

    def get_temp_dir(self) -> str:
        return str(self._scratch)

    def init_session(self):
        script = _snapshot_bootstrap_script(excluded_names=(), **self._snapshot_script_kwargs(self.cwd))
        process = self._run_bash(script)
        result = self._wait_for_process(process, timeout=self._snapshot_timeout)
        if result.get("returncode") != 0:
            raise RuntimeError("jailed shell initialization failed: " + result.get("output", ""))
        self._snapshot_ready = True
        self._update_cwd(result)

    def _run_bash(self, cmd_string: str, *, login=False, timeout=120, stdin_data=None):
        # Login/profile sourcing would expose controller configuration. Bash's
        # exported functions and aliases are restored only from the jailed snapshot.
        process = spawn(["/usr/local/bin/bash", "--noprofile", "--norc", "-c", cmd_string],
                        self.policy, cwd=self.cwd, bridge=self._bridge, text=True,
                        stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
                        stderr=subprocess.STDOUT)
        with self._process_lock:
            self._processes = {p for p in self._processes if p.poll() is None}
            self._processes.add(process)
        if stdin_data is not None:
            _pipe_stdin(process, stdin_data)
        return process

    def _kill_process(self, process):
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)

    def _prepare_command(self, command: str) -> tuple[str, str | None]:
        """Jail jobs never receive the controller's sudo material.

        The host sudo cache/prompt feeds a real password into the child, and the
        jail runs with no-new-privileges: rewriting ``sudo`` to ``sudo -S`` would
        only leak the password into an untrusted process and can never elevate.
        """
        return command, None

    def file_operations(self):
        from tools.freebsd_jail_files import JailFileOperations
        return JailFileOperations(self)

    def spawn_background(self, registry, **kwargs):
        from tools.freebsd_jail_background import spawn_background
        return spawn_background(self, registry, **kwargs)

    def cleanup(self):
        with self._process_lock:
            processes, self._processes = self._processes, set()
        for process in processes:
            self._kill_process(process)
        # This is a caller-owned source directory, never a daemon mount target.
        # Refuse a platform without fd-based deletion rather than follow a link.
        if not shutil.rmtree.avoids_symlink_attacks:
            raise RuntimeError("descriptor-relative scratch cleanup unavailable")
        if self._scratch.exists():
            shutil.rmtree(self._scratch)
