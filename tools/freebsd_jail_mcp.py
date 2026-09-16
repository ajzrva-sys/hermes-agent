"""MCP stdio transport over the common jail launcher; no host server subprocess."""
from contextlib import asynccontextmanager

import anyio

from tools.freebsd_jail_launch import launch_async


@asynccontextmanager
async def stdio_client(server, errlog=None):
    from mcp import types
    from pydantic import TypeAdapter
    parser = TypeAdapter(types.JSONRPCMessage)
    from mcp.shared.message import SessionMessage
    process = await launch_async([server.command, *server.args], cwd=server.cwd,
                                 server_environment=server.env)
    incoming_send, incoming = anyio.create_memory_object_stream(0)
    outgoing, outgoing_receive = anyio.create_memory_object_stream(0)

    async def reader():
        async with incoming_send:
            while line := await process.stdout.readline():
                if len(line) > 1024 * 1024:
                    raise ValueError("oversized MCP frame")
                await incoming_send.send(SessionMessage(parser.validate_json(line)))

    async def writer():
        async with outgoing_receive:
            async for message in outgoing_receive:
                data = message.message.model_dump_json(by_alias=True, exclude_unset=True).encode() + b"\n"
                if len(data) > 1024 * 1024:
                    raise ValueError("oversized MCP request")
                process.stdin.write(data)
                await process.stdin.drain()

    async def drain_errors():
        # A server may print configured secrets. Do not persist them to a shared log.
        while await process.stderr.read(16384):
            pass

    async with anyio.create_task_group() as group:
        group.start_soon(reader)
        group.start_soon(writer)
        group.start_soon(drain_errors)
        try:
            yield incoming, outgoing
        finally:
            with anyio.CancelScope(shield=True):
                if process.returncode is None:
                    process.kill()
                with anyio.fail_after(10):
                    await process.wait()
                await incoming.aclose()
                await outgoing.aclose()
            group.cancel_scope.cancel()
