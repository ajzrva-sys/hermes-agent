"""Tracked jail relays, including a dedicated PTY rather than the user's terminal."""
from __future__ import annotations

import errno
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios

from tools.freebsd_jail_client import spawn


class JailPty:
    def __init__(self, process, master):
        self.process, self.fd = process, master
        self.pid = process.pid
        self.exitstatus = None

    def isalive(self):
        return self.process.poll() is None

    def read(self, size):
        try:
            data = os.read(self.fd, size)
        except OSError as error:
            if error.errno != errno.EIO:
                raise
            data = b""
        if not data:
            raise EOFError
        return data

    def write(self, data):
        view = memoryview(data)
        total = len(view)
        while view:
            written = os.write(self.fd, view)
            view = view[written:]
        return total

    def setwinsize(self, rows, cols):
        if not (1 <= rows <= 65535 and 1 <= cols <= 65535):
            raise ValueError("invalid terminal size")
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.process.send_signal(signal.SIGWINCH)

    def sendeof(self):
        self.write(b"\x04")

    def wait(self):
        self.exitstatus = self.process.wait()
        return self.exitstatus

    def terminate(self, force=False):
        if self.process.poll() is None:
            self.process.kill() if force else self.process.terminate()
        self.exitstatus = self.process.wait(timeout=10)
        return True

    def close(self):
        try:
            self.terminate(force=True)
        finally:
            if self.fd >= 0:
                os.close(self.fd)
                self.fd = -1


def spawn_background(env, registry, *, command, cwd, use_pty=False, **ownership):
    script = env._wrap_command(command, cwd or env.cwd)
    argv = ["/usr/local/bin/bash", "--noprofile", "--norc", "-c", script]
    master = slave = -1
    process = None
    try:
        if use_pty:
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
        process = spawn(argv, env.policy, cwd=cwd or env.cwd, bridge=env._bridge,
                        stdin=slave if use_pty else subprocess.PIPE,
                        stdout=slave if use_pty else subprocess.PIPE,
                        stderr=slave if use_pty else subprocess.STDOUT, text=not use_pty)
        with env._process_lock:
            env._processes.add(process)
        if not use_pty:
            return registry.adopt_local(process, command=command, cwd=cwd,
                                        notify_on_complete=False, **ownership)
        session = registry._new_session(command, ownership.get("task_id", ""),
                                        ownership.get("owner_task_id", ""),
                                        ownership.get("session_key", ""), cwd)
        session.pid = process.pid
        session.host_start_time = registry._safe_host_start_time(process.pid)
        session._pty = JailPty(process, master)
        master = -1
        registry._track_started(session, registry._pty_reader_loop, f"jail-pty-{session.id}")
        return session
    except BaseException:
        if process is not None:
            process.kill()
            process.wait(timeout=10)
        raise
    finally:
        for fd in (master, slave):
            if fd >= 0:
                os.close(fd)
