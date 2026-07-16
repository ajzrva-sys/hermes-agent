"""Adapted from macosxgeek's PR #33487; exercise the current credential owner."""

import errno
from unittest.mock import patch

import pytest


@pytest.mark.parametrize("error", [errno.ENOEXEC, errno.EACCES])
def test_setup_token_only_recovers_from_exec_format_error(monkeypatch, capsys, error):
    from agent import anthropic_credentials as credentials

    monkeypatch.setattr("shutil.which", lambda _: "/fixture/claude")
    monkeypatch.setattr(credentials, "read_claude_code_credentials",
                        lambda: pytest.fail("failed executable must not read credentials"))
    with patch.object(credentials.subprocess, "run", side_effect=OSError(error, "fixture")):
        if error == errno.ENOEXEC:
            assert credentials.run_oauth_setup_token() is None
            assert "claude setup-token" in capsys.readouterr().out
        else:
            with pytest.raises(OSError) as raised:
                credentials.run_oauth_setup_token()
            assert raised.value.errno == error


@pytest.mark.freebsd_only
def test_native_unrunnable_claude_returns_to_manual_auth(tmp_path, monkeypatch):
    from agent import anthropic_credentials as credentials

    binary = tmp_path / "claude"
    binary.write_bytes(b"not an executable format\n")
    binary.chmod(0o700)
    monkeypatch.setattr("shutil.which", lambda _: str(binary))
    monkeypatch.setattr(credentials, "read_claude_code_credentials",
                        lambda: pytest.fail("no credentials should be accessed"))
    assert credentials.run_oauth_setup_token() is None
