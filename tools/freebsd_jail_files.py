"""Descriptor-relative file primitives behind Hermes's existing patch validation."""
from __future__ import annotations

import base64
import hashlib
import io
import os
from pathlib import Path
import selectors
import subprocess
import time

from tools.file_operations import ShellFileOperations
from tools.file_operations_common import ExecuteResult, ReadResult, WriteResult
from tools.freebsd_jail_client import spawn
from tools.freebsd_jail_file_worker import MAX_BYTES, MAX_MESSAGE, read_message, write_message


def exchange(process, request, timeout=120):
    outgoing = io.BytesIO()
    write_message(outgoing, request)
    data = memoryview(outgoing.getvalue())
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            for name in ("stdin", "stdout", "stderr"):
                stream = getattr(process, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_WRITE if name == "stdin" else selectors.EVENT_READ, name)
            while selector.get_map():
                if time.monotonic() > deadline:
                    raise TimeoutError("file-worker deadline exceeded")
                for key, _ in selector.select(min(1, max(0, deadline - time.monotonic()))):
                    stream, name = key.fileobj, key.data
                    if name == "stdin":
                        count = os.write(stream.fileno(), data[:16384])
                        data = data[count:]
                        if not data:
                            selector.unregister(stream)
                            stream.close()
                    else:
                        chunk = os.read(stream.fileno(), 16384)
                        if not chunk:
                            selector.unregister(stream)
                            stream.close()
                            continue
                        outputs[name].extend(chunk)
                        limit = MAX_MESSAGE + MAX_MESSAGE // 4096 + 4096 if name == "stdout" else 65536
                        if len(outputs[name]) > limit:
                            raise ValueError("oversized file-worker output")
        if process.wait(timeout=max(.1, deadline - time.monotonic())) != 0:
            raise RuntimeError("jailed file worker failed: " + outputs["stderr"].decode(errors="replace"))
        stream = io.BytesIO(outputs["stdout"])
        response = read_message(stream)
        if stream.read(1) or not isinstance(response, dict) or response.get("version") != 1:
            raise ValueError("invalid file-worker response")
        if "error" in response:
            raise RuntimeError(response["error"])
        return response["result"]
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        for name in ("stdin", "stdout", "stderr"):
            getattr(process, name).close()


class JailFileOperations(ShellFileOperations):
    def __init__(self, terminal_env, cwd=None):
        super().__init__(terminal_env, cwd)
        self._observed = {}

    def _expand_path(self, path):
        if path == "~" or path.startswith("~/"):
            path = "/tmp/hermes-home" + path[1:]
        return os.path.normpath(os.path.join(self.env.cwd, path))

    def _worker(self, operation, path, **arguments):
        from tools import freebsd_jail_file_worker
        path = os.path.abspath(self._expand_path(path))
        request = {"version": 1, "operation": operation, "path": path, **arguments}
        source = Path(freebsd_jail_file_worker.__file__).read_text(encoding="utf-8")
        if operation == "extract":
            from tools.freebsd_jail_parsing import extraction_bootstrap
            source = source.split('if __name__ == "__main__":')[0] + extraction_bootstrap() + "\nmain()\n"
        process = spawn(["/usr/local/bin/python3", "-I", "-c", source], self.env.policy,
                        cwd=self.env.cwd, bridge=self.env._bridge)
        response = exchange(process, request)
        if (not isinstance(response, dict) or response.get("path") != path
                or type(response.get("size")) is not int or not 0 <= response["size"] <= MAX_BYTES):
            raise ValueError("invalid file-worker receipt")
        if operation == "move" and response.get("destination") != arguments["destination"]:
            raise ValueError("invalid file-worker destination receipt")
        return response

    def extract_document(self, path):
        from tools.read_extract import ExtractionError
        try:
            result = self._worker("extract", path)
            if not isinstance(result.get("text"), str):
                raise ValueError("invalid extraction receipt")
            return result["text"], result["size"]
        except Exception as error:
            raise ExtractionError(str(error)) from error

    def read_file_bytes(self, path, max_bytes=None):
        try:
            result = self._worker("read", path, limit=min(MAX_BYTES, max_bytes if max_bytes is not None else MAX_BYTES))
            data = base64.b64decode(result["data"], validate=True)
            digest = hashlib.sha256(data).hexdigest()
            if len(data) != result["size"] or digest != result["sha256"]:
                raise ValueError("invalid file-worker content receipt")
            self._observed[self._expand_path(path)] = digest
            return ReadResult(base64_content=result["data"], file_size=len(data), is_binary=True)
        except Exception as error:
            return ReadResult(error=str(error))

    def read_file_raw(self, path):
        result = self.read_file_bytes(path)
        if result.error:
            return result
        data = base64.b64decode(result.base64_content)
        if self._is_likely_binary_bytes(data[:1000]):
            return ReadResult(error="Binary file cannot be displayed as text", is_binary=True, file_size=len(data))
        return ReadResult(content=data.decode("utf-8-sig", "surrogateescape"), file_size=len(data))

    def read_file(self, path, offset=1, limit=2000):
        from tools.file_operations_common import normalize_read_pagination
        offset, limit = normalize_read_pagination(offset, limit)
        result = self.read_file_raw(path)
        if result.error:
            return result
        lines = result.content.splitlines()
        page = "\n".join(lines[offset-1:offset-1+limit])
        result.content = self._add_line_numbers(page, offset) if page else ""
        result.total_lines = len(lines)
        result.truncated = offset - 1 + limit < len(lines)
        return result

    def _atomic_write(self, path, content):
        data = content.encode("utf-8", "surrogateescape")
        try:
            args = {"data": base64.b64encode(data).decode()}
            if path in self._observed:
                args["expected"] = self._observed[path]
            result = self._worker("write", path, **args)
            digest = hashlib.sha256(data).hexdigest()
            if result["size"] != len(data) or result.get("sha256") != digest:
                raise ValueError("invalid mutation receipt")
            self._observed[path] = digest
            return ExecuteResult(stdout="", exit_code=0)
        except Exception as error:
            return ExecuteResult(stdout=str(error), exit_code=1)

    def delete_file(self, path):
        from agent.file_safety import get_write_denied_error
        path = self._expand_path(path)
        denied = get_write_denied_error(path, verb="Delete")
        if denied:
            return WriteResult(error=denied)
        try:
            args = {"expected": self._observed[path]} if path in self._observed else {}
            self._worker("delete", path, **args)
            self._observed.pop(path, None)
            return WriteResult()
        except Exception as error:
            return WriteResult(error=str(error))

    def move_file(self, src, dst):
        from agent.file_safety import get_write_denied_error
        src, dst = self._expand_path(src), self._expand_path(dst)
        for path in (src, dst):
            if denied := get_write_denied_error(path, verb="Move"):
                return WriteResult(error=denied)
        try:
            args = {"expected": self._observed[src]} if src in self._observed else {}
            self._worker("move", src, destination=dst, **args)
            self._observed.pop(src, None)
            self._observed.pop(dst, None)
            return WriteResult()
        except Exception as error:
            return WriteResult(error=str(error))
