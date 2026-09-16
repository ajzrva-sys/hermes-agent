"""A jail session must never inherit a cached host backend or another profile."""
from tools.terminal_scope import reset_terminal_scope, set_terminal_scope


def test_jail_cache_identity_binds_profile_session_and_policy(monkeypatch, tmp_path):
    import hermes_constants
    import tools.terminal_tool as terminal
    monkeypatch.setattr(terminal, "_current_session_key", lambda: "conversation")
    monkeypatch.setattr(terminal, "_ensure_terminal_env_bridged", lambda: None)
    token = set_terminal_scope({"TERMINAL_ENV": "freebsd_jail", "TERMINAL_FREEBSD_JAIL": "{}"})
    try:
        monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path / "first")
        first = terminal._resolve_container_task_id("task")
        monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path / "second")
        second = terminal._resolve_container_task_id("task")
        assert first != second
        assert first.startswith("freebsd:") and second.startswith("freebsd:")
    finally:
        reset_terminal_scope(token)


def test_jail_cache_does_not_fall_back_to_raw_task_host_backend(monkeypatch):
    import tools.terminal_tool as terminal
    host_backend = object()
    monkeypatch.setattr(terminal, "_active_environments", {"task": host_backend})
    assert terminal._lookup_active_env("freebsd:concrete-policy", "task") is None
