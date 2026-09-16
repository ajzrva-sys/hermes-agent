"""Shared launch adapter for non-terminal subprocess execution surfaces."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import tempfile
import threading

from tools.freebsd_jail_policy import Grant, worker_environment
from tools.freebsd_jail_scope import configured_policy
from tools.terminal_scope import terminal_env


def required():
    """Whether the selected backend is the jail.

    Deliberately does NOT import the client module: the client subclasses
    ``subprocess.Popen`` at import time, and this predicate runs on every cron
    dispatch / hook / MCP bring-up, including under patched-subprocess tests.
    """
    return terminal_env("TERMINAL_ENV", "local") == "freebsd_jail"


def _workspace_root():
    workspace = terminal_env("TERMINAL_CWD", "")
    return workspace or str(Path.cwd())


def policy_for(cwd=None):
    # A server's requested cwd cannot broaden the configured project grant.
    return configured_policy(_workspace_root())


def launch(argv, *, cwd=None, server_environment=None, **stdio):
    from tools.freebsd_jail_client import spawn
    env = worker_environment()
    if server_environment:
        # Only an explicit server-specific configuration reaches this parameter.
        env.update(server_environment)
    return spawn(argv, policy_for(cwd), cwd=cwd, environment=env, **stdio)


STAGING_ROOT = "/var/tmp"


def _cleanup_staging(process, staging: Path):
    try:
        process.wait()
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def launch_script(argv, source_path, *, cwd=None, **stdio):
    """Run a controller-owned script inside the jail without mounting its directory.

    Cron scripts live under the profile, which stays denied to workers (credentials
    and controller state). The controller reads the already-validated script once and
    hands the jail a private staging copy at the same interpreter/argument shape.
    """
    source = Path(source_path)
    if argv[-1] != str(source):
        raise ValueError("script launch requires the script as the final argument")
    from tools.freebsd_jail_client import MAX_REQUEST, spawn
    data = source.read_bytes()
    if len(data) > MAX_REQUEST:
        raise ValueError("cron script exceeds the jail launch limit")
    staging = Path(tempfile.mkdtemp(prefix="hermes-jail-stage-", dir=STAGING_ROOT))
    staged = staging / source.name
    try:
        staged.write_bytes(data)
        staged.chmod(0o500)
        # The staged copy is the only extra authority, and it is read-only.
        policy = configured_policy(_workspace_root(), extra_grants=(Grant(str(staging), "read"),))
        process = spawn([*argv[:-1], str(staged)], policy, cwd=cwd or policy.workspace, **stdio)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    threading.Thread(target=_cleanup_staging, args=(process, staging), daemon=True).start()
    return process


async def launch_async(argv, *, cwd=None, server_environment=None):
    from tools.freebsd_jail_client import bridge_path, launch_request
    env = worker_environment()
    if server_environment:
        env.update(server_environment)
    payload = launch_request(argv, policy_for(cwd), cwd=cwd, environment=env)
    read_fd, write_fd = os.pipe()
    parent_read, parent_write = os.pipe()
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            str(bridge_path()), "--request-fd", str(read_fd), "--parent-fd", str(parent_read),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            pass_fds=(read_fd, parent_read), close_fds=True, start_new_session=True,
            env=worker_environment(), cwd="/", limit=1024 * 1024)
        # The bridge reads the bounded spec before beginning its stdio relay.
        def write_request():
            with os.fdopen(write_fd, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
        await asyncio.to_thread(write_request)
        os.close(write_fd)
        write_fd = -1
        owned_parent = parent_write
        parent_write = -1
        async def close_on_exit():
            try:
                await process.wait()
            finally:
                os.close(owned_parent)
        process._hermes_jail_parent_watch = asyncio.create_task(close_on_exit())
        return process
    except BaseException:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        raise
    finally:
        for fd in (read_fd, write_fd, parent_read, parent_write):
            if fd >= 0:
                os.close(fd)
