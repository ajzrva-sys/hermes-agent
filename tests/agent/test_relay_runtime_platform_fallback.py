"""Expected FreeBSD binding absence must not hide real Relay failures."""

import importlib.util
import logging
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from agent import relay_runtime


@pytest.mark.parametrize(
    "platform_name,error,expected",
    [
        ("freebsd15", ModuleNotFoundError("missing binding", name="nemo_relay"), True),
        ("freebsd14", ModuleNotFoundError("missing binding", name="nemo_relay"), True),
        ("linux", ModuleNotFoundError("missing binding", name="nemo_relay"), False),
        ("darwin", ModuleNotFoundError("missing binding", name="nemo_relay"), False),
        ("win32", ModuleNotFoundError("missing binding", name="nemo_relay"), False),
        ("openbsd7", ModuleNotFoundError("missing binding", name="nemo_relay"), False),
        ("freebsd15", ModuleNotFoundError("missing transitive", name="native_dependency"), False),
        ("freebsd15", ModuleNotFoundError("missing submodule", name="nemo_relay.native"), False),
        ("freebsd15", ModuleNotFoundError("nemo_relay"), False),
        ("freebsd15", ImportError("native loader failed", name="nemo_relay"), False),
        ("freebsd15", OSError("shared object unavailable"), False),
        ("freebsd15", RuntimeError("runtime initialization failed"), False),
    ],
)
def test_expected_binding_absence_is_narrow(platform_name, error, expected):
    # Platform strings are data, never a replacement for the interpreter's OS.
    assert relay_runtime._is_expected_missing_binding(error, platform_name) is expected


@pytest.fixture
def registry():
    registry = relay_runtime.RelayHostRegistry()
    try:
        yield registry
    finally:
        registry.shutdown_all()


def relay_records(caplog):
    return [record for record in caplog.records if record.name == "agent.relay_runtime"]


@pytest.mark.freebsd_only
def test_freebsd_missing_top_level_binding_is_informational(monkeypatch, caplog, registry):
    loader = Mock(side_effect=ModuleNotFoundError(
        "No module named 'nemo_relay'", name="nemo_relay"
    ))
    monkeypatch.setattr(relay_runtime, "_load_nemo_relay", loader)
    with caplog.at_level(logging.INFO, logger="agent.relay_runtime"):
        assert registry.for_profile("test-profile", create=False) is None
        loader.assert_not_called()
        host = registry.for_profile("test-profile")
        assert registry.for_profile("test-profile") is host
    assert isinstance(host, relay_runtime.NoopRelayRuntime)
    assert host.profile_key == "test-profile"
    assert "nemo_relay" in host.reason
    args = {"command": "true"}
    assert host.apply_tool_request_intercepts(
        session_id="session", tool_name="terminal", args=args
    ) is args
    assert host.managed_execution_enabled() is False
    loader.assert_called_once_with()
    records = relay_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert records[0].exc_info is None
    assert "FreeBSD" in records[0].getMessage()

    # The existing per-profile cache, not a process-global flag, owns the notice.
    with caplog.at_level(logging.INFO, logger="agent.relay_runtime"):
        other_host = registry.for_profile("other-profile")
        assert registry.for_profile("other-profile") is other_host
    assert other_host is not host
    assert other_host.profile_key == "other-profile"
    assert loader.call_count == 2
    assert len(relay_records(caplog)) == 2
    assert relay_records(caplog)[1].levelno == logging.INFO
    assert relay_records(caplog)[1].exc_info is None


@pytest.mark.parametrize(
    "error",
    [
        ModuleNotFoundError("missing transitive", name="native_dependency"),
        ModuleNotFoundError("missing submodule", name="nemo_relay.native"),
        ModuleNotFoundError("nemo_relay"),
        ImportError("native loader failed", name="nemo_relay"),
        OSError("shared object unavailable"),
        RuntimeError("runtime initialization failed"),
    ],
)
def test_unexpected_failures_keep_tracebacks(monkeypatch, caplog, registry, error):
    loader = Mock(side_effect=error)
    monkeypatch.setattr(relay_runtime, "_load_nemo_relay", loader)
    with caplog.at_level(logging.INFO, logger="agent.relay_runtime"):
        host = registry.for_profile("test-profile")
        assert registry.for_profile("test-profile") is host
    assert isinstance(host, relay_runtime.NoopRelayRuntime)
    assert host.reason == str(error)
    loader.assert_called_once_with()
    records = relay_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info[1] is error
    assert records[0].exc_info[2] is not None


@pytest.mark.freebsd_only
def test_freebsd_still_attempts_a_working_runtime(monkeypatch, caplog, registry):
    working_host = Mock()
    constructor = Mock(return_value=working_host)
    monkeypatch.setattr(relay_runtime, "RelayRuntime", constructor)
    with caplog.at_level(logging.INFO, logger="agent.relay_runtime"):
        assert registry.for_profile("test-profile") is working_host
        assert registry.for_profile("test-profile") is working_host
    constructor.assert_called_once_with(profile_key="test-profile")
    assert not relay_records(caplog)
    registry.shutdown_all()
    working_host.shutdown.assert_called_once_with()


@pytest.mark.freebsd_only
def test_real_freebsd_missing_binding_uses_noop_without_traceback(tmp_path):
    if importlib.util.find_spec("nemo_relay") is not None:
        pytest.skip("this regression requires the intentionally absent binding")
    env = os.environ.copy()
    env["HERMES_HOME"] = str(tmp_path / "hermes-home")
    source = """
import importlib.util
import logging
import sys
from pathlib import Path
from agent import relay_runtime
assert sys.platform.startswith("freebsd")
assert importlib.util.find_spec("nemo_relay") is None
assert Path(relay_runtime.__file__).resolve() == Path.cwd() / "agent" / "relay_runtime.py"
logging.basicConfig(level=logging.INFO)
registry = relay_runtime.RelayHostRegistry()
try:
    assert registry.for_profile("smoke-profile", create=False) is None
    host = registry.for_profile("smoke-profile")
    assert isinstance(host, relay_runtime.NoopRelayRuntime)
    assert "nemo_relay" in host.reason
    assert registry.for_profile("smoke-profile") is host
    assert not host.managed_execution_enabled()
    args = {"command": "true"}
    assert host.apply_tool_request_intercepts(
        session_id="session", tool_name="terminal", args=args
    ) is args
finally:
    registry.shutdown_all()
print("FreeBSD Relay fallback OK")
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", source],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "FreeBSD Relay fallback OK"
    assert "continuing with the no-op Relay host" in result.stderr
    assert result.stderr.count("continuing with the no-op Relay host") == 1
    assert "Traceback" not in result.stderr
    assert "WARNING" not in result.stderr
