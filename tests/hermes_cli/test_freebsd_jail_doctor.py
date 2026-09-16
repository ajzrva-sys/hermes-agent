"""Native doctor report for the freebsd_jail backend against the real shared service."""
import pytest

pytestmark = pytest.mark.freebsd_only


def test_doctor_reports_jail_service_and_policy(tmp_path, capsys):
    from hermes_cli.doctor_tools import _check_freebsd_jail_backend
    from tools.terminal_scope import reset_terminal_scope, set_terminal_scope

    project = tmp_path / "project"
    project.mkdir()
    token = set_terminal_scope({"TERMINAL_ENV": "freebsd_jail", "TERMINAL_CWD": str(project),
                                "TERMINAL_FREEBSD_JAIL": "{}"})
    try:
        issues: list[str] = []
        _check_freebsd_jail_backend(issues)
        out = capsys.readouterr().out
        assert issues == [], out
        assert "FreeBSD jail service" in out and "codex-freebsd-sandboxd" in out
        assert "source-identities-v1" in out
        assert f"jail workspace: {project} (read/write)" in out
        assert "jail network: restricted" in out
        assert "Jailed surfaces:" in out and "Trusted controller" in out
    finally:
        reset_terminal_scope(token)
