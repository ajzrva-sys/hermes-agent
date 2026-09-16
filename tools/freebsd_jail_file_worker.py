"""Standalone jailed file worker. Only stdlib imports; no profile initialization.

The controller supplies framed JSON over a dedicated pipe. Paths are walked with
O_NOFOLLOW directory descriptors, and mutations stay relative to the pinned parent.
"""
import base64
import hashlib
import json
import os
from pathlib import PurePosixPath
import secrets
import stat
import struct
import sys

CHUNK = 16384
MAX_BYTES = 50 * 1024 * 1024
MAX_MESSAGE = 72 * 1024 * 1024


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        part = stream.read(size - len(data))
        if not part:
            raise ValueError("truncated file-worker frame")
        data.extend(part)
    return bytes(data)


def read_message(stream, maximum=MAX_MESSAGE):
    data = bytearray()
    while True:
        size = struct.unpack("!I", read_exact(stream, 4))[0]
        if size == 0:
            return json.loads(data)
        if size > CHUNK or len(data) + size > maximum:
            raise ValueError("oversized file-worker message")
        data.extend(read_exact(stream, size))


def write_message(stream, value):
    data = json.dumps(value, ensure_ascii=True).encode()
    if len(data) > MAX_MESSAGE:
        raise ValueError("oversized file-worker response")
    for offset in range(0, len(data), CHUNK):
        chunk = data[offset:offset + CHUNK]
        stream.write(struct.pack("!I", len(chunk)))
        stream.write(chunk)
    stream.write(b"\0\0\0\0")
    stream.flush()


def parent_fd(path, create=False):
    parts = PurePosixPath(path).parts
    if not parts or parts[0] != "/" or len(parts) < 2 or ".." in parts:
        raise ValueError("file-worker paths must be absolute and normalized")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parts[1:-1]:
            if create:
                try:
                    os.mkdir(part, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def read_at(parent, name, limit=MAX_BYTES):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("file worker requires a regular file")
        if info.st_size > limit:
            raise ValueError("file exceeds the operation's byte limit")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("file grew beyond the operation's byte limit")
        return data, info


def current_state(parent, name):
    try:
        data, info = read_at(parent, name)
        return hashlib.sha256(data).hexdigest(), info
    except FileNotFoundError:
        return None, None


def operate(request):
    if not isinstance(request, dict) or request.get("version") != 1:
        raise ValueError("unsupported file-worker protocol")
    operation = request.get("operation")
    if operation not in {"read", "write", "delete", "move", "extract"}:
        raise ValueError("unsupported file-worker operation")
    path = request["path"]
    parent, name = parent_fd(path, create=operation == "write")
    try:
        if operation in {"read", "extract"}:
            limit = request.get("limit", MAX_BYTES)
            if type(limit) is not int or not 0 <= limit <= MAX_BYTES:
                raise ValueError("invalid file limit")
            data, _ = read_at(parent, name, limit)
            if operation == "extract":
                return {"path": path, "size": len(data), "text": extract_document_bytes(data, path)}
            return {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                    "data": base64.b64encode(data).decode()}
        before, info = current_state(parent, name)
        if "expected" in request and before != request["expected"]:
            raise ValueError("file changed since authorization/read")
        if operation == "delete":
            if info is not None:
                os.unlink(name, dir_fd=parent)
            return {"path": path, "size": 0, "before": before}
        if operation == "move":
            destination = request["destination"]
            dst_parent, dst_name = parent_fd(destination)
            try:
                # A symlink destination is never an alternate target.
                current_state(dst_parent, dst_name)
                os.rename(name, dst_name, src_dir_fd=parent, dst_dir_fd=dst_parent)
            finally:
                os.close(dst_parent)
            return {"path": path, "destination": destination, "size": info.st_size if info else 0}
        data = base64.b64decode(request["data"], validate=True)
        if len(data) > MAX_BYTES:
            raise ValueError("file exceeds write limit")
        temp = ".hermes-jail-" + secrets.token_hex(16)
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode) & 0o777 if info else 0o644)
                stream.flush()
                os.fsync(stream.fileno())
            after, _ = current_state(parent, name)
            if before != after:
                raise ValueError("file changed during write")
            os.rename(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            try:
                os.unlink(temp, dir_fd=parent)
            except FileNotFoundError:
                pass
        return {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "before": before}
    finally:
        os.close(parent)


def main():
    try:
        result = {"version": 1, "result": operate(read_message(sys.stdin.buffer))}
    except Exception as error:
        result = {"version": 1, "error": str(error)}
    write_message(sys.stdout.buffer, result)


if __name__ == "__main__":
    main()
