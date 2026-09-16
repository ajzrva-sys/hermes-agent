"""Real process-registry interaction with dedicated jail relays."""
import time

import pytest

pytestmark = pytest.mark.freebsd_only


@pytest.mark.parametrize("use_pty", [False, True])
def test_background_input_and_jail_lifetime(tmp_path, use_pty):
    from tools.environments.freebsd_jail import FreeBSDJailEnvironment
    from tools.freebsd_jail_policy import project_policy
    from tools.process_registry import ProcessRegistry
    from tools.terminal_tool_background import _spawn
    project = tmp_path / "project"
    project.mkdir()
    policy = project_policy(str(project), home=tmp_path, profile=tmp_path / ".hermes")
    env = FreeBSDJailEnvironment(str(project), policy=policy)
    registry = ProcessRegistry()
    try:
        env.init_session()
        session = _spawn(registry, env=env, env_type="freebsd_jail",
                         command='test "$(sysctl -n security.jail.jailed)" = 1 || exit 77; '
                                 'printf "ready\\n"; read value; printf "answer=%s\\n" "$value"',
                         cwd=str(project), effective_task_id="jail-test", task_id="owner",
                         session_key="conversation", effective_pty=use_pty)
        deadline = time.monotonic() + 20
        while "ready" not in session.output_buffer and time.monotonic() < deadline:
            time.sleep(.05)
        assert "ready" in session.output_buffer, session.output_buffer
        assert registry.submit_stdin(session.id, "native-input")["status"] == "ok"
        while not session.exited and time.monotonic() < deadline:
            time.sleep(.05)
        assert session.exited and session.exit_code == 0, session.output_buffer
        assert "answer=native-input" in session.output_buffer
    finally:
        env.cleanup()
