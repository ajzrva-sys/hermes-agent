"""Installer behavior, with FreeBSD cases executed only on native FreeBSD.

Subprocesses get disposable homes; package/download commands are intercepted,
never uname or Python's platform detection. Native venv tests use pkg Python/uv.
"""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "scripts" / "install.sh"
BASH = shutil.which("bash")
assert BASH is not None, "installer tests require bash"


@pytest.fixture
def blocked_commands(tmp_path):
    """No package mutations or binary downloads, even on regression failures."""
    bin_dir = tmp_path / "blocked-bin"
    bin_dir.mkdir()
    calls = tmp_path / "external-calls"
    for command in ("pkg", "curl", "fetch", "wget", "npm", "npx", "node", "sudo", "doas", "cargo"):
        script = bin_dir / command
        script.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$CALLS"\nexit 91\n'
        )
        script.chmod(0o755)
    return {"PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(calls)}


def shell(tmp_path, body, *args, env=None):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    child_env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "SHELL": BASH,
        "LANG": "C.UTF-8",
        "TEST_PYTHON": sys.executable,
    }
    child_env.update(env or {})
    command = [BASH, str(INSTALLER), *args] if body is None else [
        BASH, "-c", 'source "$1" --manifest "${@:2}" >/dev/null\n' + body,
        "test-installer", str(INSTALLER), *args,
    ]
    return subprocess.run(
        command,
        cwd=tmp_path, env=child_env, text=True, capture_output=True, timeout=60,
    )


def test_selected_home_is_exported_to_config_and_skill_subprocesses(tmp_path):
    selected = tmp_path / "selected home"
    result = shell(
        tmp_path,
        '''"$TEST_PYTHON" -c 'import os; print(os.environ.get("HERMES_HOME", ""))' ''',
        "--hermes-home", str(selected),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(selected)
    assert not (tmp_path / "home" / ".hermes").exists()


@pytest.mark.freebsd_only
def test_native_bootstrap_uses_pkg_uv_and_sqlite_python(tmp_path, blocked_commands):
    # All packages are already installed for this case; any install/download is
    # a bug. Use actual native binaries, not a pretend uv or Python version.
    pkg = tmp_path / "blocked-bin" / "pkg"
    pkg.write_text('#!/bin/sh\n[ "$1" = info ] && exit 0\nexit 91\n')
    selected = tmp_path / "selected home"
    result = shell(
        tmp_path,
        '''detect_os
install_uv
check_python
"$PYTHON_PATH" -c 'import sqlite3, sys; assert sys.platform.startswith("freebsd"); sqlite3.connect(":memory:").execute("create virtual table x using fts5(t)")'
printf '%s\\n' "$OS" "$PYTHON_PATH" "$PYTHON_VERSION" "$UV_CMD"
"$UV_CMD" --version
''',
        "--hermes-home", str(selected), env=blocked_commands,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "freebsd\n" in result.stdout
    assert "/usr/local/bin/python3.12" in result.stdout
    assert (selected / "bin" / "uv").samefile("/usr/local/bin/uv")
    assert not Path(blocked_commands["CALLS"]).exists()


@pytest.mark.freebsd_only
@pytest.mark.parametrize("options", [
    ["--include-desktop"],
    ["--stage", "desktop", "--json"],
    ["--no-venv"],
])
def test_unsupported_requests_fail_before_writes_or_downloads(tmp_path, blocked_commands, options):
    selected = tmp_path / "selected home"
    install_dir = tmp_path / "install"
    result = shell(
        tmp_path,
        None,
        "--hermes-home", str(selected), "--dir", str(install_dir),
        "--non-interactive", *options, env=blocked_commands,
    )
    assert result.returncode != 0
    assert "FreeBSD" in result.stdout
    assert not selected.exists()
    assert not install_dir.exists()
    assert not Path(blocked_commands["CALLS"]).exists()


@pytest.mark.freebsd_only
@pytest.mark.parametrize("stage", ["node-deps", "gateway"])
def test_unsupported_default_stages_are_structured_skips(tmp_path, blocked_commands, stage):
    result = shell(tmp_path, None, "--stage", stage, "--json", env=blocked_commands)
    assert result.returncode == 0, result.stdout + result.stderr
    frame = json.loads(result.stdout.splitlines()[-1])
    assert frame["ok"] and frame["skipped"]
    assert frame["stage"] == stage
    assert "FreeBSD" in frame["reason"]
    assert not (tmp_path / "home" / ".hermes").exists()
    assert not Path(blocked_commands["CALLS"]).exists()


@pytest.mark.freebsd_only
@pytest.mark.parametrize("function", [
    "install_node_deps", "install_browser_use_cli",
    "install_computer_use_driver", "maybe_start_gateway",
])
def test_monolithic_optional_helpers_skip_on_freebsd(tmp_path, blocked_commands, function):
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    (install_dir / "package.json").write_text("{}")
    result = shell(
        tmp_path,
        f'detect_os\nHAS_NODE=true\n{function}\n',
        "--dir", str(install_dir), env=blocked_commands,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Skipping" in result.stdout and "FreeBSD" in result.stdout
    assert not Path(blocked_commands["CALLS"]).exists()


@pytest.mark.freebsd_only
def test_required_native_build_packages_fail_loudly(tmp_path, blocked_commands):
    result = shell(
        tmp_path, 'detect_os\ninstall_system_packages\nprintf "continued\\n"\n',
        env=blocked_commands,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "Required FreeBSD packages" in result.stdout
    assert "rust" in result.stdout and "libheif" in result.stdout
    assert "continued" not in result.stdout


@pytest.mark.freebsd_only
def test_native_build_environment_is_capped_and_uses_local_libraries(tmp_path, blocked_commands):
    pkg = tmp_path / "blocked-bin" / "pkg"
    pkg.write_text('#!/bin/sh\n[ "$1" = info ] && exit 0\nexit 91\n')
    result = shell(
        tmp_path,
        '''detect_os
install_system_packages
"$TEST_PYTHON" -c 'import os,json; print(json.dumps(dict(os.environ)))'
''',
        env={**blocked_commands, "CARGO_BUILD_JOBS": "9999", "UV_CONCURRENT_BUILDS": "9999",
             "CPPFLAGS": "-DUSER_FLAG=1", "LDFLAGS": "-Wl,--as-needed"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    build_env = json.loads(result.stdout.splitlines()[-1])
    for variable in ("CARGO_BUILD_JOBS", "UV_CONCURRENT_BUILDS", "CMAKE_BUILD_PARALLEL_LEVEL"):
        assert 1 <= int(build_env[variable]) <= 4
    assert "-I/usr/local/include" in build_env["CPPFLAGS"]
    assert "-DUSER_FLAG=1" in build_env["CPPFLAGS"]
    assert "-L/usr/local/lib" in build_env["LDFLAGS"]
    assert "-Wl,--as-needed" in build_env["LDFLAGS"]
    assert "/usr/local/lib/pkgconfig" in build_env["PKG_CONFIG_PATH"].split(":")
    assert build_env["UV_PYTHON_DOWNLOADS"] == "never"


@pytest.mark.freebsd_only
def test_native_venv_stage_uses_selected_python_with_spaces(tmp_path, blocked_commands):
    pkg = tmp_path / "blocked-bin" / "pkg"
    pkg.write_text('#!/bin/sh\n[ "$1" = info ] && exit 0\nexit 91\n')
    install_dir = tmp_path / "install dir"
    install_dir.mkdir()
    selected = tmp_path / "selected home"
    result = shell(
        tmp_path, None, "--stage", "venv", "--json", "--dir", str(install_dir),
        "--hermes-home", str(selected),
        env={**blocked_commands, "UV_PYTHON": "3.14", "UV_PYTHON_DOWNLOADS": "automatic"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["ok"]
    check = subprocess.run(
        [str(install_dir / "venv/bin/python"), "-c",
         'import sys,sqlite3; assert sys.version_info[:2] == (3,12); '
         'sqlite3.connect(":memory:").execute("create virtual table x using fts5(t)")'],
        text=True, capture_output=True, timeout=15,
    )
    assert check.returncode == 0, check.stderr
    assert not Path(blocked_commands["CALLS"]).exists()


@pytest.mark.freebsd_only
@pytest.mark.parametrize("check_exit", [0, 88])
def test_native_locked_sync_uses_build_environment_and_checks_dependencies(tmp_path, blocked_commands, check_exit):
    pkg = tmp_path / "blocked-bin" / "pkg"
    pkg.write_text('#!/bin/sh\n[ "$1" = info ] && exit 0\nexit 91\n')
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname="installer-test"\nversion="0.0.0"\n'
        'requires-python=">=3.12,<3.14"\n[project.optional-dependencies]\nall=[]\n'
        '[tool.uv]\npackage=false\n'
    )
    uv_env = {**blocked_commands, "HOME": str(tmp_path), "UV_PYTHON_DOWNLOADS": "never",
              "UV_NO_CONFIG": "1", "UV_CACHE_DIR": str(tmp_path / "uv-cache")}
    for args in (["lock", "--offline", "--python", "/usr/local/bin/python3.12"],
                 ["venv", "venv", "--python", "/usr/local/bin/python3.12"]):
        setup = subprocess.run(
            ["/usr/local/bin/uv", *args], cwd=project, env=uv_env,
            text=True, capture_output=True, timeout=20,
        )
        assert setup.returncode == 0, setup.stderr
    recorder = tmp_path / "uv recorder"
    recorder.write_text(
        f"#!{sys.executable}\nimport json,os,sys\n"
        'with open(os.environ["UV_CALLS"], "a") as f:\n'
        '    f.write(json.dumps({"args":sys.argv[1:], "env":dict(os.environ)}) + "\\n")\n'
        f'if sys.argv[1:3] == ["pip", "check"] and {check_exit}: sys.exit({check_exit})\n'
        'os.execv("/usr/local/bin/uv", ["/usr/local/bin/uv", *sys.argv[1:]])\n'
    )
    recorder.chmod(0o755)
    calls_path = tmp_path / "uv-calls.jsonl"
    result = shell(
        tmp_path,
        'detect_os\nrequire_install_dir\nUV_CMD="$UV_RECORDER"\n'
        'PYTHON_PATH=/usr/local/bin/python3.12\ninstall_deps\n',
        "--dir", str(project),
        env={**uv_env, "UV_RECORDER": str(recorder), "UV_CALLS": str(calls_path),
             "UV_PYTHON": "3.14", "UV_CONCURRENT_BUILDS": "9999"},
    )
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
    assert [row["args"][0] for row in calls] == ["sync", "pip"], result.stdout + result.stderr
    assert "--locked" in calls[0]["args"]
    assert calls[1]["args"][1] == "check"
    build_env = calls[0]["env"]
    assert build_env["UV_PYTHON"] == str(project / "venv/bin/python")
    assert 1 <= int(build_env["UV_CONCURRENT_BUILDS"]) <= 4
    assert "-I/usr/local/include" in build_env["CPPFLAGS"]
    assert (result.returncode == 0) == (check_exit == 0), result.stdout + result.stderr


@pytest.mark.freebsd_only
def test_prerequisites_stage_rejects_an_unusable_native_compiler(tmp_path, blocked_commands):
    pkg = tmp_path / "blocked-bin/pkg"
    pkg.write_text('#!/bin/sh\n[ "$1" = info ] && exit 0\nexit 91\n')
    for name in ("cc", "c++", "g++", "clang++"):
        compiler = tmp_path / "blocked-bin" / name
        compiler.write_text('#!/bin/sh\nexit 91\n')
        compiler.chmod(0o755)
    result = shell(tmp_path, None, "--stage", "prerequisites", "--json", env=blocked_commands)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "FreeBSD" in result.stdout and "compiler" in result.stdout
    assert not json.loads(result.stdout.splitlines()[-1])["ok"]


@pytest.mark.freebsd_only
def test_repository_stage_provisions_git_through_pkg(tmp_path, blocked_commands):
    git = tmp_path / "blocked-bin/git"
    git.write_text('#!/bin/sh\nexit 91\n')
    git.chmod(0o755)
    result = shell(
        tmp_path, None, "--stage", "repository", "--json",
        "--dir", str(tmp_path / "checkout"), env=blocked_commands,
    )
    assert result.returncode != 0
    assert "Required FreeBSD packages: git" in result.stdout
    assert not (tmp_path / "checkout").exists()


@pytest.mark.freebsd_only
@pytest.mark.parametrize("existing", [False, True])
def test_config_stage_defaults_to_cli_without_overwriting_preferences(tmp_path, blocked_commands, existing):
    import yaml

    project = tmp_path / "project"
    python_bin = project / "venv/bin/python"
    python_bin.parent.mkdir(parents=True)
    python_bin.write_text(
        f'#!/bin/sh\nPYTHONPATH={shlex.quote(str(ROOT))} exec {shlex.quote(sys.executable)} "$@"\n'
    )
    python_bin.chmod(0o755)
    shutil.copy(ROOT / "cli-config.yaml.example", project)
    (project / "tools").symlink_to(ROOT / "tools", target_is_directory=True)
    (project / "skills").symlink_to(ROOT / "skills", target_is_directory=True)
    selected = tmp_path / "selected home"
    selected.mkdir()
    original_env = "# keep this comment\nCUSTOM_PREF=untouched\n"
    (selected / ".env").write_text(original_env)
    config_path = selected / "config.yaml"
    original_config = "display:\n  interface: tui\nterminal:\n  backend: ssh\n"
    if existing:
        config_path.write_text(original_config)
    result = shell(
        tmp_path, None, "--stage", "config", "--json", "--dir", str(project),
        "--hermes-home", str(selected), env=blocked_commands,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    config = yaml.safe_load(config_path.read_text())
    if existing:
        assert config_path.read_text() == original_config
    else:
        assert config["display"]["interface"] == "cli"
        assert config["terminal"]["backend"] == "local"
    assert (selected / ".env").read_text() == original_env
    assert (selected / ".env").stat().st_mode & 0o777 == 0o600
    assert list((selected / "skills").rglob("SKILL.md"))
    assert not (tmp_path / "home/.hermes").exists()
    assert not Path(blocked_commands["CALLS"]).exists()


@pytest.mark.freebsd_only
def test_optional_system_packages_use_pkg(tmp_path, blocked_commands):
    pkg = tmp_path / "blocked-bin/pkg"
    pkg.write_text(
        '#!/bin/sh\n[ "$1" = info ] && exit 0\n'
        'printf "%s\\n" "$*" >> "$CALLS"\nexit 0\n'
    )
    result = shell(
        tmp_path,
        '''detect_os
command() {
    if [ "$1" = -v ] && { [ "$2" = rg ] || [ "$2" = ffmpeg ]; }; then return 1; fi
    builtin command "$@"
}
install_system_packages
''',
        env=blocked_commands,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = Path(blocked_commands["CALLS"]).read_text()
    assert "install -y ripgrep ffmpeg" in calls
    assert "cargo" not in calls


@pytest.mark.freebsd_only
@pytest.mark.parametrize("layout", ["fresh", "legacy", "explicit"])
def test_root_layout_preserves_existing_and_explicit_installations(tmp_path, layout):
    if os.geteuid() != 0:
        pytest.skip("root layout is exercised on the native root test host")
    selected = tmp_path / "data"
    args = ["--hermes-home", str(selected)]
    if layout == "legacy":
        (selected / "hermes-agent/.git").mkdir(parents=True)
    if layout == "explicit":
        args += ["--dir", str(tmp_path / "chosen")]
    result = shell(tmp_path, 'detect_os\nresolve_install_layout\n'
                   'printf "LAYOUT=%s|%s|%s\\n" "$INSTALL_DIR" "$ROOT_FHS_LAYOUT" "${UV_PYTHON_INSTALL_DIR:-}"\n', *args)
    assert result.returncode == 0, result.stderr
    expected = {"fresh": "/usr/local/lib/hermes-agent|true|",
                "legacy": f"{selected}/hermes-agent|false|",
                "explicit": f"{tmp_path}/chosen|false|"}
    assert f"LAYOUT={expected[layout]}" in result.stdout


@pytest.mark.freebsd_only
def test_completion_explains_cli_only_instead_of_node_repair(tmp_path):
    result = shell(tmp_path, 'detect_os\nHAS_NODE=false\nprint_success\n')
    assert result.returncode == 0, result.stderr
    assert "FreeBSD" in result.stdout and "CLI" in result.stdout
    assert "hermes gateway install" not in result.stdout
    assert "https://nodejs.org" not in result.stdout


@pytest.mark.freebsd_only
def test_installer_is_directly_executable_on_freebsd(tmp_path):
    try:
        result = subprocess.run(
            [str(INSTALLER), "--help"], env={"HOME": str(tmp_path), "PATH": os.environ["PATH"]},
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError as exc:
        pytest.fail(f"installer requires an unavailable shell: {exc}")
    assert result.returncode == 0, result.stderr


@pytest.mark.freebsd_only
@pytest.mark.parametrize("package_result", [0, 1])
def test_node_provisioning_uses_native_packages_not_downloads(tmp_path, blocked_commands, package_result):
    result = shell(tmp_path,
                   'detect_os\nensure_freebsd_packages() { printf "PACKAGES=%s\\n" "$*"; return '
                   + str(package_result) + '; }\ninstall_node\nprintf "HAS_NODE=%s\\n" "$HAS_NODE"\n',
                   env=blocked_commands)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PACKAGES=node24 npm-node24" in result.stdout
    assert f"HAS_NODE={'true' if package_result == 0 else 'false'}" in result.stdout
    assert not Path(blocked_commands["CALLS"]).exists()


@pytest.mark.freebsd_only
@pytest.mark.parametrize("dependency,missing_node", [("node", False), ("browser", False), ("browser", True)])
def test_optional_native_setup_never_downloads_foreign_binaries(tmp_path, dependency, missing_node):
    probe = 'check_node() { HAS_NODE=false; };\n' if missing_node else ''
    result = shell(tmp_path,
                   'curl() { return 91; }; npm() { return 91; }; npx() { return 91; }\n' + probe + 'ensure_mode\n',
                   "--ensure", dependency)
    assert result.returncode == 0, result.stdout + result.stderr
    if dependency == "browser":
        assert "pkg install chromium" in result.stdout
        assert "AGENT_BROWSER_EXECUTABLE_PATH" in result.stdout
        assert "manual" in result.stdout.lower()
    else:
        assert "Native Node.js" in result.stdout
    assert not (tmp_path / "home/.hermes/node").exists()
