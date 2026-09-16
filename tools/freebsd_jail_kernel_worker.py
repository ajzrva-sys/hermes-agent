"""Jailed kernel entrypoint, loaded only by the dedicated worker interpreter."""
if __name__ == "__main__":
    """Persistent Python runner appended to the standalone framing primitives."""
    import contextlib
    import io
    import threading
    import traceback
    import types

    # Protocol descriptors are separate from user-code stdout/stdin. A forged frame
    # can only ask the controller for an already allowed tool under this cell's token.
    wire_in = os.fdopen(os.dup(0), "rb", buffering=0)
    wire_out = os.fdopen(os.dup(1), "wb", buffering=0)
    null = os.open(os.devnull, os.O_RDWR)
    os.dup2(null, 0)
    os.dup2(2, 1)
    os.close(null)
    MAX_MESSAGE = 2 * 1024 * 1024
    call_lock = threading.Lock()
    active = None


    def rpc(tool, args):
        with call_lock:
            if active is None:
                raise RuntimeError("no active cell")
            write_message(wire_out, {"kind": "tool", "cell": active["id"],
                                    "token": active["token"], "tool": tool, "args": args})
            reply = read_message(wire_in)
            if reply.get("kind") != "tool_result" or reply.get("cell") != active["id"]:
                raise RuntimeError("invalid tool reply")
            value = reply["result"]
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except ValueError:
                    pass
            return value


    class Capture(io.StringIO):
        def write(self, text):
            room = max(0, 500000 - self.tell())
            super().write(text[:room])
            return len(text)


    initial = read_message(wire_in)
    module = types.ModuleType("hermes_tools")
    exec(initial["stubs"], module.__dict__)
    module._call = rpc
    sys.modules["hermes_tools"] = module
    globals_state = {"__name__": "__main__", "__builtins__": __builtins__}
    count = 0
    while True:
        try:
            active = read_message(wire_in)
        except (ValueError, EOFError):
            break
        if active.get("kind") != "cell":
            break
        count += 1
        output, errors = Capture(), Capture()
        status, trace = "ok", ""
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                exec(compile(active["code"], "<cell>", "exec"), globals_state)
        except BaseException:
            status, trace = "error", traceback.format_exc()[-10000:]
        with call_lock:
            write_message(wire_out, {"kind": "result", "cell": active["id"],
                                    "token": active["token"], "status": status,
                                    "stdout": output.getvalue(), "stderr": errors.getvalue(),
                                    "traceback": trace, "execution_count": count})
            active = None
