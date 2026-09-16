"""Dedicated ordinary-user client processes for the shared native jail service."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from tools.freebsd_jail_policy import JailPolicy, worker_environment

MAX_REQUEST = 1024 * 1024


def bridge_path() -> Path:
    return Path(__file__).resolve().parent.parent / "native/freebsd-sandbox/bin/hermes-freebsd-sandbox"


def capabilities(bridge: Path | None = None) -> dict:
    if not sys.platform.startswith("freebsd"):
        raise RuntimeError("freebsd_jail requires native FreeBSD")
    result = subprocess.run([str(bridge or bridge_path()), "--probe"], env=worker_environment(),
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=True)
    if len(result.stdout) > MAX_REQUEST:
        raise ValueError("oversized jail capability response")
    value = json.loads(result.stdout)
    if value.get("service") != "codex-freebsd-sandboxd" or value.get("version") != 1:
        raise ValueError("incompatible jail service")
    return value


class JailProcess(subprocess.Popen):
    """The pipe is owned for the process lifetime, independently of its stdin."""
    _parent_writer: int | None = None

    def _close_parent(self):
        if self._parent_writer is not None:
            os.close(self._parent_writer)
            self._parent_writer = None

    def poll(self):
        result = super().poll()
        if result is not None:
            self._close_parent()
        return result

    def wait(self, timeout=None):
        result = super().wait(timeout=timeout)
        self._close_parent()
        return result

    def __del__(self):
        self._close_parent()
        super().__del__()


def launch_request(argv, policy, *, cwd=None, environment=None):
    if not sys.platform.startswith("freebsd"):
        raise RuntimeError("freebsd_jail requires native FreeBSD")
    if not argv or any(not isinstance(arg, str) or "\0" in arg for arg in argv):
        raise ValueError("invalid jail command arguments")
    # /tmp is private to the new jail. No host shell init or profile is sourced.
    command = ["/bin/sh", "-c", 'umask 077; mkdir -p "$HOME"; exec "$@"', "hermes-worker", *argv]
    request = json.dumps({"version": 1, "argv": command, "cwd": cwd or policy.workspace,
                          "policy": policy.wire(),
                          "env": worker_environment() if environment is None else environment}).encode()
    if len(request) > MAX_REQUEST:
        raise ValueError("jail launch request is too large")
    return request


def spawn(argv: list[str], policy: JailPolicy, *, cwd: str | None = None,
          environment: dict[str, str] | None = None, bridge: Path | None = None,
          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
          text: bool = False) -> JailProcess:
    request = launch_request(argv, policy, cwd=cwd, environment=environment)
    request_r, request_w = os.pipe()
    parent_r, parent_w = os.pipe()
    process = None
    try:
        process = JailProcess([str(bridge or bridge_path()), "--request-fd", str(request_r),
                               "--parent-fd", str(parent_r)],
                              stdin=stdin, stdout=stdout, stderr=stderr, text=text,
                              encoding="utf-8" if text else None,
                              errors="replace" if text else None,
                              pass_fds=(request_r, parent_r), close_fds=True,
                              start_new_session=True, env=worker_environment(), cwd="/")
        process._parent_writer = parent_w
        parent_w = -1
        with os.fdopen(request_w, "wb") as stream:
            request_w = -1
            stream.write(request)
        return process
    except BaseException:
        if process is not None:
            process.kill()
            process.wait()
        raise
    finally:
        for fd in (request_r, request_w, parent_r, parent_w):
            if fd >= 0:
                os.close(fd)
