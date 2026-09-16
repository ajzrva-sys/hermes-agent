"""Persistent jailed Python with controller-authorized RPC over dedicated pipes."""
from __future__ import annotations

import atexit
import json
import io
import os
import select
import queue
import secrets
import threading
import time
from pathlib import Path

from tools.freebsd_jail_client import spawn
from tools.freebsd_jail_file_worker import read_message, write_message

_registry = {}
_registry_lock = threading.RLock()


class Kernel:
    def __init__(self, env, tools):
        from tools import freebsd_jail_file_worker
        from tools.code_execution_tool import generate_hermes_tools_module
        framing = Path(freebsd_jail_file_worker.__file__).read_text(encoding="utf-8").split('if __name__ == "__main__":')[0]
        source = framing + "\n" + Path(__file__).with_name("freebsd_jail_kernel_worker.py").read_text(encoding="utf-8")
        self.process = spawn(["/usr/local/bin/python3", "-I", "-u", "-c", source], env.policy,
                             cwd=env.cwd, bridge=env._bridge)
        self.lock = threading.Lock()
        self.responses = queue.Queue(maxsize=8)
        self.stopped = threading.Event()
        self.last_used = time.monotonic()
        self.identity = (env.policy.identity, env.cwd, tuple(sorted(tools)))
        self.stderr = bytearray()
        self.send({"stubs": generate_hermes_tools_module(list(tools))})
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._drain_errors, daemon=True).start()

    def send(self, value, timeout=10):
        buffer = io.BytesIO()
        write_message(buffer, value)
        data = memoryview(buffer.getvalue())
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("oversized kernel request")
        fd = self.process.stdin.fileno()
        os.set_blocking(fd, False)
        deadline = time.monotonic() + timeout
        while data:
            if time.monotonic() > deadline or self.stopped.is_set():
                raise TimeoutError("kernel input unavailable")
            if select.select([], [fd], [], .1)[1]:
                try:
                    data = data[os.write(fd, data[:16384]):]
                except BlockingIOError:
                    continue

    def _read(self):
        try:
            while not self.stopped.is_set():
                value = read_message(self.process.stdout, maximum=2 * 1024 * 1024)
                if not isinstance(value, dict) or len(json.dumps(value)) > 2 * 1024 * 1024:
                    raise ValueError("oversized kernel frame")
                self.responses.put(value, timeout=1)
        except Exception:
            self.stop()

    def _drain_errors(self):
        try:
            while data := self.process.stderr.read(4096):
                self.stderr.extend(data[:max(0, 10000 - len(self.stderr))])
        except (OSError, ValueError):
            pass

    def stop(self):
        self.stopped.set()
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)


def shutdown(owner=None):
    with _registry_lock:
        keys = [key for key in _registry if owner is None or key[1] == owner]
        kernels = [_registry.pop(key) for key in keys]
    for kernel in kernels:
        kernel.stop()


atexit.register(shutdown)


def execute(code, task_id, enabled_tools, reset=False):
    from hermes_constants import get_hermes_home
    from tools.code_execution_tool import (_get_or_create_env, _load_config, _sandbox_tools_for,
                                           _finish_remote_kernel_result)
    from tools.code_kernel import _resolve_owner
    from tools.code_execution_rpc import _handle_rpc_request, _default_dispatch
    from tools.interrupt import is_interrupted
    start = time.monotonic()
    config = _load_config()
    timeout = config.get("timeout", 300)
    max_calls = config.get("max_tool_calls", 50)
    allowed = frozenset(_sandbox_tools_for(None) if enabled_tools is None else
                        _sandbox_tools_for(None).intersection(enabled_tools))
    key = (str(get_hermes_home().resolve()), _resolve_owner(task_id or ""))
    kernel = None
    try:
        env, backend = _get_or_create_env(task_id or "default")
        if backend != "freebsd_jail":
            raise RuntimeError("jail kernel requires the jail backend")
        identity = (env.policy.identity, env.cwd, tuple(sorted(allowed)))
        with _registry_lock:
            kernel = _registry.get(key)
            if kernel is not None and (reset or kernel.identity != identity or kernel.stopped.is_set()
                                       or kernel.process.poll() is not None):
                kernel.stop()
                del _registry[key]
                kernel = None
            if kernel is None:
                # Keep the same existing configurable kernel count/idle limits.
                limit = max(1, int(config.get("max_session_kernels", 4)))
                for old_key, old in list(_registry.items()):
                    if time.monotonic() - old.last_used > config.get("kernel_idle_timeout", 1800):
                        if old.lock.acquire(blocking=False):
                            try:
                                old.stop()
                                del _registry[old_key]
                            finally:
                                old.lock.release()
                if len(_registry) >= limit:
                    raise RuntimeError("jail kernel capacity reached; close an idle session")
                kernel = _registry[key] = Kernel(env, allowed)
        with kernel.lock:
            cell, token = secrets.token_hex(16), secrets.token_urlsafe(32)
            if len(code.encode()) > 1024 * 1024:
                raise ValueError("code cell exceeds 1 MiB")
            kernel.send({"kind": "cell", "id": cell, "token": token, "code": code})
            deadline, calls, log = time.monotonic() + timeout, [0], []
            while True:
                if is_interrupted():
                    raise InterruptedError("jail kernel interrupted; state discarded")
                if time.monotonic() > deadline:
                    raise TimeoutError("jail kernel timed out; state discarded")
                if kernel.stopped.is_set():
                    raise RuntimeError("jail kernel disconnected")
                try:
                    reply = kernel.responses.get(timeout=.1)
                except queue.Empty:
                    continue
                if reply.get("cell") != cell or not secrets.compare_digest(str(reply.get("token", "")), token):
                    raise ValueError("unauthorized kernel frame")
                if reply.get("kind") == "tool":
                    if not isinstance(reply.get("args"), dict):
                        raise ValueError("invalid nested tool arguments")
                    # Hidden controller-only kwargs cannot be invoked through model RPC.
                    if any(name.startswith("_") for name in reply["args"]):
                        raise ValueError("controller-only tool arguments are forbidden")
                    result = _handle_rpc_request(reply, allowed_tools=allowed, tool_call_counter=calls,
                                                 max_tool_calls=max_calls, dispatch=_default_dispatch(task_id),
                                                 tool_call_log=log, call_start=time.monotonic(), where="jail kernel")
                    kernel.send({"kind": "tool_result", "cell": cell, "result": result})
                elif reply.get("kind") == "result":
                    kernel.last_used = time.monotonic()
                    reply["tool_calls_made"] = calls[0]
                    reply["kernel"] = {"backend": "freebsd_jail", "persistent": True,
                                       "execution_count": reply.get("execution_count")}
                    return _finish_remote_kernel_result(reply, timeout=timeout, exec_start=start)
                else:
                    raise ValueError("invalid kernel frame")
    except Exception as error:
        import logging
        logging.getLogger(__name__).exception("jailed kernel execution failed")
        if kernel is not None:
            kernel.stop()
        return json.dumps({"status": "error", "error": str(error), "output": "",
                           "kernel": {"backend": "freebsd_jail", "state_lost": True}})
