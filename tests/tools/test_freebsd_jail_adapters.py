"""Native protocol and hook adapters use the same authenticated jail service."""
import json
import shlex

import pytest

pytestmark = pytest.mark.freebsd_only


@pytest.mark.asyncio
async def test_native_mcp_stdio_and_async_launcher(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from tools.freebsd_jail_mcp import stdio_client
    from tools.freebsd_jail_launch import launch_async
    from tools.terminal_scope import set_terminal_scope, reset_terminal_scope
    project = tmp_path / "project"
    project.mkdir()
    token = set_terminal_scope({"TERMINAL_ENV": "freebsd_jail", "TERMINAL_CWD": str(project)})
    source = '''import json, sys, subprocess
assert subprocess.check_output(["sysctl", "-n", "security.jail.jailed"]).strip() == b"1"
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request: continue
    result = {"protocolVersion": request["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "jailed-fixture", "version": "1"}} if request["method"] == "initialize" else {"tools": []}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''
    try:
        probe = await launch_async(["/bin/sh", "-c", "id -u; sysctl -n security.jail.jailed"])
        probe_out, probe_err = await probe.communicate()
        assert probe.returncode == 0, probe_err
        assert probe_out.splitlines() == [b"1001", b"1"]
        async with stdio_client(StdioServerParameters(command="/usr/local/bin/python3", args=["-I", "-u", "-c", source])) as streams:
            async with ClientSession(*streams) as session:
                result = await session.initialize()
                assert result.model_dump(by_alias=True)["serverInfo"]["name"] == "jailed-fixture"
                assert (await session.list_tools()).tools == []
        process = await launch_async(["/bin/sh", "-c", 'test "$(id -u)" = 1001; read v; printf "%s" "$v"'])
        stdout, stderr = await process.communicate(b"async-input\n")
        assert process.returncode == 0 and stdout == b"async-input", stderr
    finally:
        reset_terminal_scope(token)


def test_native_hook_clean_environment(tmp_path, monkeypatch):
    from agent.shell_hooks import ShellHookSpec, _spawn
    from tools.terminal_scope import set_terminal_scope, reset_terminal_scope
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("PROVIDER_PASSWORD", "synthetic-secret")
    token = set_terminal_scope({"TERMINAL_ENV": "freebsd_jail", "TERMINAL_CWD": str(project)})
    script = 'test "$(sysctl -n security.jail.jailed)" = 1 && test -z "$PROVIDER_PASSWORD" && cat'
    try:
        result = _spawn(ShellHookSpec(event="pre_tool_call", command="/bin/sh -c " + shlex.quote(script)), '{"fixture":true}')
        assert result["returncode"] == 0, result
        assert json.loads(result["stdout"]) == {"fixture": True}
    finally:
        reset_terminal_scope(token)


@pytest.mark.asyncio
async def test_native_lsp_server_runs_in_jail(tmp_path):
    from agent.lsp.client import LSPClient
    from tools.terminal_scope import set_terminal_scope, reset_terminal_scope
    project = tmp_path / "project"
    project.mkdir()
    marker = project / "lsp-jail-proof.txt"
    server = project / "fake_lsp_server.py"
    server.write_text(f'''
import json, pathlib, subprocess, sys

jailed = subprocess.check_output(["sysctl", "-n", "security.jail.jailed"]).strip().decode()
uid = subprocess.check_output(["id", "-u"]).strip().decode()
pathlib.Path({str(marker)!r}).write_text(jailed + ":" + uid)


def read_message():
    length = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\\r\\n", b"\\n"):
            break
        name, _, value = line.decode().partition(":")
        if name.lower() == "content-length":
            length = int(value.strip())
    return json.loads(sys.stdin.buffer.read(length))


def write_message(message):
    data = json.dumps(message).encode()
    sys.stdout.buffer.write(b"Content-Length: %d\\r\\n\\r\\n" % len(data) + data)
    sys.stdout.buffer.flush()


while True:
    message = read_message()
    if message is None:
        break
    method = message.get("method")
    if method == "initialize":
        write_message({{"jsonrpc": "2.0", "id": message["id"], "result": {{
            "capabilities": {{"textDocumentSync": 1}},
            "serverInfo": {{"name": "jailed-fixture", "version": "1"}}}}}})
    elif method == "shutdown":
        write_message({{"jsonrpc": "2.0", "id": message["id"], "result": None}})
    elif method == "exit":
        break
''')
    token = set_terminal_scope({"TERMINAL_ENV": "freebsd_jail", "TERMINAL_CWD": str(project)})
    client = LSPClient(server_id="fixture", workspace_root=str(project),
                       command=["/usr/local/bin/python3", "-I", "-u", str(server)])
    try:
        await client.start()
        assert client.is_running
        assert marker.read_text() == "1:1001"
    finally:
        await client.shutdown()
        reset_terminal_scope(token)


def test_native_cron_script_runs_staged_in_jail(tmp_path, monkeypatch):
    """Cron scripts live under the profile; the adapter stages a jailed copy."""
    from cron.scheduler_script import _run_job_script
    from hermes_constants import get_hermes_home
    from tools.terminal_scope import set_terminal_scope, reset_terminal_scope
    project = tmp_path / "project"
    project.mkdir()
    profile = get_hermes_home()
    profile.mkdir(parents=True, exist_ok=True)
    (profile / ".env").write_text("PROVIDER_PASSWORD=synthetic-only\n")
    scripts = profile / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "jail-cron-probe.sh").write_text(
        "#!/bin/sh\nset -eu\n"
        'test "$(sysctl -n security.jail.jailed)" = 1\n'
        'test "$(id -u)" = 1001\n'
        'test -z "${PROVIDER_PASSWORD:-}"\n'
        f"test ! -r {shlex.quote(str(profile / '.env'))}\n"
        "printf 'jail-cron-ok\\n'\n")
    monkeypatch.setenv("PROVIDER_PASSWORD", "synthetic-secret")
    token = set_terminal_scope({"TERMINAL_ENV": "freebsd_jail", "TERMINAL_CWD": str(project)})
    try:
        ok, output = _run_job_script("jail-cron-probe.sh")
        assert ok, output
        assert "jail-cron-ok" in output
    finally:
        reset_terminal_scope(token)
