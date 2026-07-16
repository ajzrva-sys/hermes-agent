"""Native FreeBSD runtime ownership and update boundaries (no host spoofing)."""

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from hermes_cli import managed_uv

pytestmark = pytest.mark.freebsd_only


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes"))
    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setattr(managed_uv, "_PROJECT_ROOT", root)
    return root


@pytest.mark.parametrize("existing_link", [False, True, "dangling"])
def test_pkg_uv_link_never_self_updates_or_refreshes_catalog(
    monkeypatch, existing_link
):
    uv_path = shutil.which("uv")
    assert uv_path, "native test host requires pkg install uv"
    native_uv = Path(uv_path).resolve()
    before = hashlib.sha256(native_uv.read_bytes()).digest()
    target = managed_uv.managed_uv_path()
    if existing_link:
        target.parent.mkdir(parents=True)
        target.symlink_to(native_uv if existing_link is True else target.parent / "missing-uv")
    run = subprocess.run
    forbidden = []

    def version_only(cmd, **kwargs):
        if cmd[1:] != ["--version"]:
            forbidden.append(cmd)
            raise AssertionError("pkg uv must never self-update or download")
        return run(cmd, **kwargs)

    monkeypatch.setattr(managed_uv.subprocess, "run", version_only)
    uv_bin = managed_uv.ensure_uv()
    assert uv_bin and str(uv_bin) == str(target)
    assert tuple(uv_bin) == (str(target), False)
    assert managed_uv.resolve_uv() == str(target)
    assert target.is_symlink() and target.resolve() == native_uv
    assert managed_uv.update_managed_uv(force=True) == str(target)
    assert managed_uv._refresh_managed_uv_catalog(str(target)) is False
    assert forbidden == []
    assert target.is_symlink() and target.resolve() == native_uv
    assert hashlib.sha256(native_uv.read_bytes()).digest() == before


def test_catalog_refresh_defers_to_pkg_without_invoking_installer(monkeypatch, capsys):
    installs = []
    monkeypatch.setattr(managed_uv, "_install_uv", lambda target: installs.append(target))
    assert managed_uv._refresh_managed_uv_catalog(str(managed_uv.managed_uv_path())) is False
    assert installs == []
    assert "pkg upgrade uv" in capsys.readouterr().out


def test_missing_native_uv_reports_pkg_remediation(monkeypatch, capsys):
    monkeypatch.setenv("PATH", "")
    calls = []
    monkeypatch.setattr(managed_uv.subprocess, "run", lambda *a, **kw: calls.append(a))
    assert not managed_uv.ensure_uv()
    assert calls == []
    assert "pkg install uv" in capsys.readouterr().out


def test_vulnerable_sqlite_defers_to_pkg_and_preserves_live_venv(
    isolated_runtime, monkeypatch, capsys
):
    import sys
    from dataclasses import replace

    root = isolated_runtime
    (root / "pyproject.toml").write_text("[project]\n")
    live = root / "venv"
    (live / "bin").mkdir(parents=True)
    python = live / "bin" / "python"
    python.symlink_to(sys.executable)
    info = managed_uv.probe_sqlite_runtime(python)
    assert info is not None
    vulnerable = replace(info, sqlite_version=(3, 50, 4), sqlite_version_string="3.50.4",
                         sqlite_source_id="unpatched")
    monkeypatch.setattr(managed_uv, "probe_sqlite_runtime", lambda _: vulnerable)
    provisioned = []
    monkeypatch.setattr(managed_uv, "_install_safe_python_generation",
                        lambda *a, **kw: provisioned.append(a))
    result = managed_uv.repair_vulnerable_runtime("uv", project_root=root)
    assert result.status == "skipped"
    assert result.sqlite_before == vulnerable.sqlite_version_string
    assert not result.repaired
    assert provisioned == []
    assert python.is_symlink() and python.resolve() == Path(sys.executable).resolve()
    assert not (root / ".hermes-runtime").exists()
    minor = "".join(map(str, info.python_version[:2]))
    assert f"pkg upgrade sqlite3 python{minor} py{minor}-sqlite3" in result.detail
    assert "out of WAL mode" in capsys.readouterr().out


@pytest.mark.parametrize("venv_name", ["venv", ".venv"])
@pytest.mark.parametrize("config_scope", ["default-user", "xdg-user", "system"])
def test_dependency_prefix_targets_native_venv_ignoring_hostile_uv_env(
    isolated_runtime, monkeypatch, venv_name, config_scope
):
    import json
    import os
    import sys
    from hermes_cli import main, update_cmd

    root = isolated_runtime
    live = root / venv_name
    foreign = root / "foreign"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(live)], check=True)
    subprocess.run([sys.executable, "-m", "venv", str(foreign)], check=True)
    monkeypatch.setattr(main, "PROJECT_ROOT", root)
    user_config = Path.home() / ".config"
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    if config_scope == "xdg-user":
        user_config = root / "user-config"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(user_config))
    system_config = root / "system-config"
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(system_config))
    config = (system_config if config_scope == "system" else user_config) / "uv" / "uv.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f'[pip]\npython = "{foreign / "bin" / "python"}"\n')
    uv_bin = managed_uv.ensure_uv()
    assert uv_bin, "native test host requires pkg install uv"
    # Prove real ambient config overrides VIRTUAL_ENV before using the updater.
    ambient = dict(os.environ, VIRTUAL_ENV=str(live), UV_PYTHON_DOWNLOADS="never")
    observed = subprocess.run([uv_bin, "pip", "list", "--format", "json"], cwd=root,
                              env=ambient, check=True, capture_output=True, text=True)
    foreign_packages = json.loads(observed.stdout)
    assert any(package["name"] == "pip" for package in foreign_packages)

    for key in ("UV_PYTHON", "UV_PYTHON_INSTALL_DIR", "PYTHONHOME", "PYTHONPATH",
                "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "UV_CONFIG_FILE"):
        monkeypatch.setenv(key, str(foreign))
    monkeypatch.setenv("UV_MANAGED_PYTHON", "1")
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "automatic")
    monkeypatch.setenv("UV_NO_CONFIG", "1")
    before = dict(os.environ)
    prefix, env = update_cmd._pip_install_prefix(uv_bin)
    assert dict(os.environ) == before
    assert env is not None
    assert env["VIRTUAL_ENV"] == str(live)
    assert env.get("UV_MANAGED_PYTHON") != "1"
    assert env["UV_PYTHON_DOWNLOADS"] == "never"
    assert env["UV_NO_MANAGED_PYTHON"] == "1"
    for key in ("UV_PYTHON_INSTALL_DIR", "PYTHONHOME", "PYTHONPATH",
                "UV_PROJECT_ENVIRONMENT", "UV_CONFIG_FILE", "UV_NO_CONFIG"):
        assert key not in env
    for key, value in before.items():
        if not key.startswith(("UV_", "CONDA_", "PYTHON")) and key not in (
            "VIRTUAL_ENV", "XDG_CONFIG_HOME", "XDG_CONFIG_DIRS"
        ):
            assert env[key] == value
    from hermes_cli.main_install_repair import _resolve_install_target_python
    assert _resolve_install_target_python(prefix, env) == live / "bin" / "python"
    result = subprocess.run(prefix + ["list", "--format", "json"], cwd=root, env=env,
                            check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == []
    assert env["UV_PYTHON"] == str(live / "bin" / "python")

    # Binding Python alone is insufficient: other ambient uv policy must be hidden too.
    config.write_text('required-version = "<0.0.0"\n' + config.read_text())
    subprocess.run(prefix + ["list"], cwd=root, env=env, check=True, capture_output=True)
    # A write operation must leave the unrelated, pip-seeded environment intact.
    subprocess.run(prefix + ["uninstall", "pip"], cwd=root, env=env,
                   check=True, capture_output=True)
    observed = subprocess.run([uv_bin, "--no-config", "pip", "list", "--format", "json",
                               "--python", str(foreign / "bin" / "python")], cwd=root,
                              env=ambient, check=True, capture_output=True, text=True)
    assert json.loads(observed.stdout) == foreign_packages
    # uv must still read pyproject policy, rather than bypassing it with UV_NO_CONFIG.
    (root / "pyproject.toml").write_text('[tool.uv]\nrequired-version = "<0.0.0"\n')
    policy = subprocess.run(prefix + ["list"], cwd=root, env=env,
                            check=False, capture_output=True, text=True)
    assert policy.returncode != 0 and "<0.0.0" in policy.stderr


@pytest.mark.parametrize("creation_fails", [False, True])
def test_bare_venv_repair_requires_successful_native_supported_python(
    isolated_runtime, monkeypatch, creation_fails
):
    from hermes_cli import main, update_cmd

    root = isolated_runtime
    (root / "pyproject.toml").write_text(
        '[project]\nname="native-repair-test"\nversion="0.0.0"\nrequires-python=">=3.11,<3.14"\n'
    )
    monkeypatch.setattr(main, "PROJECT_ROOT", root)
    installed = []
    monkeypatch.setattr(main, "_install_python_dependencies_with_optional_fallback",
                        lambda *a, **kw: installed.append((a, kw)))
    monkeypatch.setattr(main, "_refresh_active_lazy_features", lambda *a, **kw: True)
    monkeypatch.setattr(main, "_restore_active_tool_dependencies", lambda *a, **kw: None)
    monkeypatch.setattr(update_cmd, "_venv_core_imports_healthy", lambda: (True, ""))
    monkeypatch.setattr(update_cmd, "_repair_node_deps_on_current_checkout", lambda *a, **kw: True)
    monkeypatch.setenv("UV_PYTHON", str(root / "hostile-python"))
    monkeypatch.setenv("PYTHONHOME", str(root / "hostile-home"))
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", str(root / "hostile-store"))
    monkeypatch.setenv("UV_MANAGED_PYTHON", "1")
    run = subprocess.run
    creations = []

    def native_only(cmd, **kwargs):
        if cmd[1:2] == ["venv"]:
            creations.append((cmd, kwargs))
            assert "--no-python-downloads" in cmd
            assert "--no-managed-python" in cmd
            assert cmd[cmd.index("--python") + 1] == ">=3.11,<3.14"
            if creation_fails:
                if kwargs.get("check"):
                    raise subprocess.CalledProcessError(42, cmd)
                return subprocess.CompletedProcess(cmd, 42)
        return run(cmd, **kwargs)

    monkeypatch.setattr(update_cmd.subprocess, "run", native_only)
    kwargs = dict(assume_yes=True, gateway_mode=False, pre_update_snapshot_id=None,
                  had_desktop_app_before_update=False, active_lazy_features=[],
                  active_tool_dependencies=[], _windows_gateway_resume=None)
    if creation_fails:
        with pytest.raises(subprocess.CalledProcessError):
            update_cmd._repair_venv_on_current_checkout(**kwargs)
        assert installed == []
        assert (root / ".update-incomplete").exists()
    else:
        assert update_cmd._repair_venv_on_current_checkout(**kwargs) is True
        info = managed_uv.probe_sqlite_runtime(root / "venv" / "bin" / "python")
        assert info is not None and (3, 11) <= info.python_version[:2] < (3, 14)
        assert info.base_prefix != root / ".hermes-runtime"
        assert installed[0][1]["env"]["VIRTUAL_ENV"] == str(root / "venv")
    assert len(creations) == 1


@pytest.mark.integration
def test_system_etc_fallback_is_suppressed_in_isolated_chroot(isolated_runtime, monkeypatch, tmp_path):
    """An absent XDG candidate makes uv fall back to /etc/uv/uv.toml."""
    import os
    import re
    from hermes_cli import main, update_cmd

    if os.geteuid() != 0:
        pytest.skip("the disposable chroot probe requires root")
    monkeypatch.setattr(main, "PROJECT_ROOT", isolated_runtime)
    uv_path = shutil.which("uv")
    assert uv_path, "native test host requires pkg install uv"
    uv = Path(uv_path).resolve()
    _, env = update_cmd._pip_install_prefix(str(uv))
    assert env is not None
    jail = tmp_path / "chroot"
    libraries = subprocess.check_output(["ldd", str(uv)], text=True)
    paths = [uv, Path("/libexec/ld-elf.so.1")]
    paths.extend(Path(path) for path in re.findall(r"=> (/\S+)", libraries))
    for path in paths:
        target = jail / path.relative_to("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    # The FreeBSD port relocates upstream's /etc fallback under /usr/local.
    for prefix in ("etc", "usr/local/etc"):
        system_config = jail / prefix / "uv/uv.toml"
        system_config.parent.mkdir(parents=True)
        system_config.write_text('required-version = "<0.0.0"\n')
    candidate = Path(env["XDG_CONFIG_DIRS"]) / "uv/uv.toml"
    if candidate.is_file():
        target = jail / candidate.relative_to("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, target)
    cmd = ["/usr/sbin/chroot", str(jail), str(uv), "python", "list", "--only-installed"]
    # The poison file belongs only to this disposable root, never the host's /etc.
    exposed = subprocess.run(cmd, env={**env, "XDG_CONFIG_DIRS": "/missing"},
                             capture_output=True, text=True)
    assert exposed.returncode != 0 and "<0.0.0" in exposed.stderr
    isolated = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert isolated.returncode == 0, isolated.stderr


@pytest.mark.parametrize("entry", ["prefix", "post_pull"])
def test_updater_without_native_uv_fails_before_any_pip_mutation(
    isolated_runtime, monkeypatch, capsys, entry
):
    from hermes_cli import main, update_cmd, update_cmd_deps

    monkeypatch.setattr(main, "PROJECT_ROOT", isolated_runtime)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(update_cmd_deps, "_ensure_venv_pip",
                        lambda *a: pytest.fail("must not bootstrap pip in the caller's interpreter"))
    with pytest.raises(SystemExit) as exc:
        if entry == "prefix":
            update_cmd._pip_install_prefix(None)
        else:
            update_cmd_deps._sync_python_dependencies_after_pull(
                ["git"], "main", None, active_lazy_features=[], active_tool_dependencies=[],
                _windows_gateway_resume=None)
    assert exc.value.code == 1
    assert "pkg install uv" in capsys.readouterr().out


@pytest.mark.parametrize("entry", ["current", "pulled"])
def test_cli_only_update_skips_node_stages_but_keeps_completion_pipeline(
    isolated_runtime, monkeypatch, entry
):
    from types import SimpleNamespace
    from hermes_cli import main, update_cmd, update_cmd_deps
    from tools import browser_tool_install

    root = isolated_runtime
    for name in ("", "web", "ui-tui", "apps/desktop"):
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "package.json").write_text("{}")
    monkeypatch.setattr(main, "PROJECT_ROOT", root)
    monkeypatch.setattr(main, "_resolve_node_runtime_npm", lambda: "npm")
    node_calls = []
    monkeypatch.setattr(browser_tool_install, "warm_agent_browser_npx_cache",
                        lambda: node_calls.append("browser"))
    monkeypatch.setattr(main, "_run_npm_install_deterministic",
                        lambda *a, **kw: node_calls.append("npm") or subprocess.CompletedProcess(a, 0))
    monkeypatch.setattr(main, "_build_web_ui", lambda *a: node_calls.append("web"))
    monkeypatch.setattr(main, "_run_logged_subprocess",
                        lambda *a, **kw: node_calls.append("desktop") or subprocess.CompletedProcess(a, 0))
    phases = []
    if entry == "current":
        monkeypatch.setattr(update_cmd, "_check_and_apply_config_migration",
                            lambda **kw: phases.append("migration"))
        assert update_cmd_deps._repair_node_deps_on_current_checkout(
            lambda message: phases.append("completion") or True,
            had_desktop_app_before_update=True) is True
        assert phases == ["migration", "completion"]
    else:
        for name in ("_invalidate_update_cache", "_write_fleet_restart_pending_marker",
                     "_sweep_bytecode_after_update", "_resume_windows_gateways_and_merge_outcome"):
            monkeypatch.setattr(update_cmd, name, lambda *a, **kw: None)
        monkeypatch.setattr(update_cmd, "_verify_head_after_pull", lambda *a, **kw: "new-sha")
        monkeypatch.setattr(update_cmd, "_branch_head_suffix", lambda *a: "")
        monkeypatch.setattr(update_cmd, "_sync_python_dependencies_after_pull",
                            lambda *a, **kw: phases.append("python"))
        monkeypatch.setattr(update_cmd, "_run_post_update_maintenance",
                            lambda **kw: phases.append("maintenance") or True)
        monkeypatch.setattr(update_cmd, "_restart_gateway_fleet_after_update",
                            lambda *a: phases.append("restart"))
        monkeypatch.setattr(update_cmd, "_verify_fleet_after_update",
                            lambda *a, **kw: phases.append("verify"))
        opts = SimpleNamespace(active_lazy_features=[], active_tool_dependencies=[],
                               assume_yes=True, pre_update_version="old")
        update_cmd._apply_pulled_update(
            ["git"], "main", "old-sha", SimpleNamespace(in_place_update=False), opts,
            gateway_mode=False, is_fork=False, desktop_dir=root / "apps/desktop",
            had_desktop_app_before_update=True, pre_update_snapshot_id=None,
            _pre_update_plan=None, _windows_gateway_resume=None)
        assert phases == ["python", "maintenance", "restart", "verify"]
    assert node_calls == []
