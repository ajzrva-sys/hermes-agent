"""freebsd_jail registration across backend tables, plus the off-platform refusal arm."""
import sys

import pytest


def test_freebsd_jail_is_registered_in_every_backend_table():
    """One backend name, every surface: doctor, setup, dashboard, config schema, env bridge."""
    from hermes_cli import doctor_tools, setup_terminal, web_server_config, web_server_profiles
    from hermes_cli.config import TERMINAL_CONFIG_ENV_MAP
    from hermes_cli.config_defaults import DEFAULT_CONFIG
    from hermes_cli.web_routers import tools as web_tools
    from tools.terminal_tool_backends import _BACKEND_SPECS, _BUILTIN_BACKENDS, _ENV_BUILDERS

    assert "freebsd_jail" in _BUILTIN_BACKENDS.split(", ")
    assert "freebsd_jail" in _ENV_BUILDERS and "freebsd_jail" in _BACKEND_SPECS
    assert "freebsd_jail" in doctor_tools._BUILTIN_TERMINAL_BACKENDS
    assert "freebsd_jail" in doctor_tools._BACKEND_CHECKS
    assert "freebsd_jail" in setup_terminal._TERMINAL_BACKEND_SETUP
    assert "freebsd_jail" in web_tools._BACKEND_PROBES
    assert "freebsd_jail" in {row["name"] for row in web_server_profiles._TERMINAL_BACKENDS}
    assert "freebsd_jail" in web_server_config._SCHEMA_OVERRIDES["terminal.backend"]["options"]
    assert TERMINAL_CONFIG_ENV_MAP["freebsd_jail"] == "TERMINAL_FREEBSD_JAIL"
    assert DEFAULT_CONFIG["terminal"]["freebsd_jail"] == {"grants": [], "read_only": False, "network": "restricted"}


def test_freebsd_jail_requires_native_freebsd(capsys):
    """Off-platform the check fails closed instead of probing a non-existent service."""
    from hermes_cli.doctor_tools import _check_freebsd_jail_backend

    if sys.platform.startswith("freebsd"):
        pytest.skip("native arm covered by tests/hermes_cli/test_freebsd_jail_doctor.py")
    issues: list[str] = []
    _check_freebsd_jail_backend(issues)
    assert issues, "configuring freebsd_jail off FreeBSD must be an issue"
    assert "freebsd_jail backend requires native FreeBSD" in capsys.readouterr().out
