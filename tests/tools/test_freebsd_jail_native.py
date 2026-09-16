"""Native acceptance against the real shared daemon, with synthetic private state."""
import shlex

import pytest

from tools.freebsd_jail_client import spawn
from tools.freebsd_jail_policy import project_policy

pytestmark = pytest.mark.freebsd_only


def test_native_backend_preserves_shell_state_without_host_file_authority(tmp_path, monkeypatch):
    from tools.environments.freebsd_jail import FreeBSDJailEnvironment
    from tools.environments.local import LocalEnvironment
    home = tmp_path / "home"
    project = home / "project"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    (project / ".git/control").write_text("protected")
    profile = home / ".hermes"
    profile.mkdir()
    (profile / ".env").write_text("synthetic-only")
    monkeypatch.setenv("PROVIDER_PASSWORD", "synthetic-only")
    policy = project_policy(str(project), home=home, profile=profile)
    env = FreeBSDJailEnvironment(str(project), policy=policy)
    try:
        assert not isinstance(env, LocalEnvironment)
        env.init_session()
        command = ('test "$(id -u)" = 1001 && test "$(sysctl -n security.jail.jailed)" = 1 && '
                   'test -z "$PROVIDER_PASSWORD" && test ! -r '+shlex.quote(str(profile / '.env'))+
                   ' && printf ok > ordinary.txt && ! (printf changed > .git/control)')
        result = env.execute(command)
        assert result["returncode"] == 0, result
        assert (project / "ordinary.txt").read_text() == "ok"
        assert (project / ".git/control").read_text() == "protected"
        assert env.execute("export JAIL_TEST_VALUE=retained; mkdir child; cd child")["returncode"] == 0
        result = env.execute('test "$JAIL_TEST_VALUE" = retained && pwd')
        assert result["returncode"] == 0 and str(project / "child") in result["output"], result
    finally:
        env.cleanup()


def test_native_read_only_and_clean_stdin_transport(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    policy = project_policy(str(project), home=tmp_path, profile=tmp_path / ".hermes", read_only=True)
    process = spawn(["/bin/sh", "-c", 'read value; printf "%s" "$value"; ! touch forbidden'], policy, text=True)
    try:
        stdout, stderr = process.communicate("pipe-fixture\n", timeout=20)
        assert process.returncode == 0, stderr
        assert stdout == "pipe-fixture"
        assert not (project / "forbidden").exists()
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
