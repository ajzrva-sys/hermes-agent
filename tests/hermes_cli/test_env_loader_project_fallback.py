"""Optional install-tree dotenv failure must not block independent user profiles."""
import os
from pathlib import Path

import pytest

from hermes_cli import env_loader


@pytest.mark.parametrize("failure_at", ["stat", "load"])
def test_unreadable_project_is_optional_but_user_env_is_not(tmp_path, monkeypatch, failure_at):
    home = tmp_path / "user"
    home.mkdir()
    user_env = home / ".env"
    user_env.write_text("PROFILE_PROBE=user\n", encoding="utf-8")
    project = tmp_path / "shared-install" / ".env"
    project.parent.mkdir()
    original = b"INSTALL_PROBE=root-only-fixture\n"
    project.write_bytes(original)
    for key in ("PROFILE_PROBE", "INSTALL_PROBE"):
        monkeypatch.delenv(key, raising=False)

    # Inject the OS error at either boundary; the native multi-user installer
    # test separately exercises actual root-owned 0600 files after setuid.
    denied = project
    real_exists = Path.exists
    real_load = env_loader._load_dotenv_with_fallback

    def exists(path):
        if failure_at == "stat" and path == denied:
            raise PermissionError("fixture access denied")
        return real_exists(path)

    def load(path, *, override):
        if failure_at == "load" and path == denied:
            raise PermissionError("fixture access denied")
        return real_load(path, override=override)

    monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.setattr(env_loader, "_load_dotenv_with_fallback", load)
    loaded = env_loader.load_hermes_dotenv(
        hermes_home=home, project_env=project, load_external_secrets=False,
    )
    assert loaded == [user_env]
    assert os.environ["PROFILE_PROBE"] == "user"
    assert "INSTALL_PROBE" not in os.environ
    assert project.read_bytes() == original

    denied = user_env
    with pytest.raises(PermissionError):
        env_loader.load_hermes_dotenv(
            hermes_home=home, project_env=project, load_external_secrets=False,
        )


@pytest.mark.parametrize("has_user_env", [False, True])
def test_accessible_project_preserves_legacy_precedence(tmp_path, monkeypatch, has_user_env):
    home = tmp_path / "user"
    home.mkdir()
    user_env = home / ".env"
    if has_user_env:
        user_env.write_text("SHARED_PROBE=user\n", encoding="utf-8")
    project = tmp_path / "developer-checkout" / ".env"
    project.parent.mkdir()
    project.write_text(
        "SHARED_PROBE=project\nSHELL_PROBE=project\nPROJECT_ONLY_PROBE=project\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SHARED_PROBE", "shell")
    monkeypatch.setenv("SHELL_PROBE", "shell")
    monkeypatch.delenv("PROJECT_ONLY_PROBE", raising=False)

    loaded = env_loader.load_hermes_dotenv(
        hermes_home=home, project_env=project, load_external_secrets=False,
    )
    assert loaded == ([user_env] if has_user_env else []) + [project]
    assert os.environ["SHARED_PROBE"] == ("user" if has_user_env else "project")
    assert os.environ["SHELL_PROBE"] == ("shell" if has_user_env else "project")
    assert os.environ["PROJECT_ONLY_PROBE"] == "project"
