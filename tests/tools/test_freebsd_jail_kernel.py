"""Native persistent cells and controller-authorized nested tool calls."""
import json

import pytest

pytestmark = pytest.mark.freebsd_only


def test_native_kernel_state_and_nested_file_rpc(tmp_path):
    from tools.freebsd_jail_kernel import execute, shutdown
    from tools.terminal_scope import set_terminal_scope, reset_terminal_scope
    project = tmp_path / "project"
    project.mkdir()
    (project / "fixture.txt").write_text("nested-file-fixture")
    token = set_terminal_scope({"TERMINAL_ENV": "freebsd_jail", "TERMINAL_CWD": str(project),
                                "TERMINAL_FREEBSD_JAIL": "{}"})
    try:
        result = json.loads(execute('value = 41\nimport subprocess\nassert subprocess.check_output(["sysctl", "-n", "security.jail.jailed"]).strip() == b"1"',
                                    "native-kernel", ["read_file"], reset=True))
        assert result["status"] == "ok", result
        result = json.loads(execute('print(value + 1)\nfrom hermes_tools import read_file\nprint(read_file(path="fixture.txt"))',
                                    "native-kernel", ["read_file"]))
        assert result["status"] == "ok", result
        assert "42" in result["output"] and "nested-file-fixture" in result["output"], result
        assert result["tool_calls_made"] == 1
    finally:
        shutdown()
        from tools.terminal_tool import cleanup_all_environments
        cleanup_all_environments()
        reset_terminal_scope(token)
