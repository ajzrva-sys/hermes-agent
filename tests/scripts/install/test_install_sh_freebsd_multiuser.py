"""Native root-install/non-root execution contract.

The public launcher must not depend on traversing root's private home.
The deliberately bad launcher is a negative control for the reported incident,
not an assertion that the current production installer still chooses that path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
pytestmark = [pytest.mark.freebsd_only, pytest.mark.integration]
NATIVE_PYTHON = Path("/usr/local/bin/python3.12")
NATIVE_UV = Path("/usr/local/bin/uv")
NATIVE_BASH = Path("/usr/local/bin/bash")
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin"
CANARY = "ROOT_ONLY_CANARY=not-a-real-credential\n"


def _run(argv, *, env, cwd, account=None, timeout=90):
    identity = {}
    if account is not None:
        identity = {
            "user": account[0],
            "group": account[1],
            "extra_groups": [],
        }
    return subprocess.run(
        [str(arg) for arg in argv],
        env=env,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **identity,
    )


def _checked(result, label):
    assert result.returncode == 0, (
        f"{label}: exit {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def _copy_tracked_worktree(destination):
    # Read current working-tree contents, not just HEAD: an implementation fix
    # under test must not accidentally be omitted from the candidate install.
    # Git provides the allowlist and executable bits; no venv, credentials or
    # ignored caches are copied. This executes copied code, not source assertions.
    listing = subprocess.check_output(
        ["git", "ls-files", "--stage", "-z"], cwd=ROOT
    )
    for record in listing.split(b"\0"):
        if not record:
            continue
        header, raw_path = record.split(b"\t", 1)
        mode, _object_id, stage = header.decode("ascii").split()
        assert stage == "0", "Resolve merge conflicts before native validation"
        relative = Path(os.fsdecode(raw_path))
        assert not relative.is_absolute() and ".." not in relative.parts
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "120000":
            target.symlink_to(os.readlink(source))
        else:
            assert mode in {"100644", "100755"}, (
                f"Unsupported Git entry in install fixture: {mode} {relative}"
            )
            shutil.copyfile(source, target)
            target.chmod(0o755 if mode == "100755" else 0o644)


def _generate_launchers(code, runtime, public_bin, root_env):
    # Keep real OS/UID/layout selection and real launcher construction. Relocate
    # only the destinations, so neither /usr/local nor a real home is modified.
    harness = r'''
set -e
umask 022
source "$1/scripts/install.sh" --manifest --hermes-home "$HERMES_HOME" >/dev/null
detect_os
resolve_install_layout
test "$ROOT_FHS_LAYOUT" = true
test "$INSTALL_DIR" = /usr/local/lib/hermes-agent
INSTALL_DIR="$2"
TEST_PUBLIC_BIN="$3"
get_command_link_dir() { printf '%s\n' "$TEST_PUBLIC_BIN"; }
get_command_link_display_dir() { printf '%s\n' "$TEST_PUBLIC_BIN"; }
setup_path
'''
    _checked(
        _run(
            [NATIVE_BASH, "-c", harness, "multiuser-launchers", code, runtime, public_bin],
            env=root_env,
            cwd=code,
        ),
        "root launcher generation",
    )
    for name in ("hermes", "hermes-agent", "hermes-acp"):
        launcher = public_bin / name
        assert launcher.is_file(), f"Missing generated launcher: {launcher}"
        assert launcher.stat().st_uid == 0
        assert stat.S_IMODE(launcher.stat().st_mode) & 0o022 == 0


@pytest.fixture(scope="module")
def installed_bundle():
    if os.geteuid() != 0:
        pytest.skip("native multi-user installation test requires root")
    # Import inside the native fixture: pwd is unavailable on Windows during
    # collection, even though these tests will subsequently be skipped there.
    import pwd

    try:
        account_record = pwd.getpwnam("nobody")
    except KeyError:
        pytest.fail("Native test host needs an existing unprivileged nobody account")
    account = (account_record.pw_uid, account_record.pw_gid)
    assert account[0] != 0 and account[1] != 0
    for executable in (NATIVE_PYTHON, NATIVE_UV, NATIVE_BASH):
        assert executable.is_file() and os.access(executable, os.X_OK), executable
    pkg = shutil.which("pkg", path=SYSTEM_PATH)
    assert pkg, "Provision native build packages before this integration test"

    # The warm-up command uses this exact cache under the disposable runner HOME.
    cache_base = Path(os.environ["HOME"]) / ".cache" / "hermes-freebsd-multiuser"
    assert (cache_base / "uv").is_dir(), "Run the explicit cache warm-up first"
    sandbox = None
    old_umask = os.umask(0o022)
    try:
        # Do not nest beneath pytest's root-private tmp_path ancestors. Opening
        # just the last directory would still prevent another UID traversing it.
        sandbox = Path(tempfile.mkdtemp(prefix="hermes-multiuser-", dir="/tmp")).resolve()
        sandbox.chmod(0o755)
        private_root = sandbox / "private-root"
        private_root.mkdir(mode=0o700)
        private_home = private_root / ".hermes"
        private_home.mkdir(mode=0o700)
        canary = private_home / ".env"
        canary.write_text(CANARY, encoding="utf-8")
        canary.chmod(0o600)
        consumer_home = sandbox / "consumer-home"
        consumer_home.mkdir(mode=0o700)
        workspace = consumer_home / "work"
        workspace.mkdir(mode=0o700)
        for path in (consumer_home, workspace):
            os.chown(path, *account)
        code = sandbox / "usr" / "local" / "lib" / "hermes-agent"
        code.mkdir(parents=True)
        public_bin = sandbox / "usr" / "local" / "bin"
        broken_public = sandbox / "broken-bin"
        public_bin.mkdir(parents=True)
        broken_public.mkdir()
        blockers = sandbox / "installer-tools"
        blockers.mkdir()
        # Query pkg normally, but categorically refuse package mutations even
        # if a future installer adds another native prerequisite.
        pkg_guard = blockers / "pkg"
        pkg_guard.write_text(
            '#!/bin/sh\n'
            'if [ "$1" = info ]; then exec ' + shlex.quote(pkg) + ' "$@"; fi\n'
            'printf "package mutation forbidden in multi-user test\\n" >&2\nexit 97\n',
            encoding="utf-8",
        )
        pkg_guard.chmod(0o755)
        for name in ("curl", "fetch", "wget", "npm", "npx"):
            blocked = blockers / name
            blocked.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
            blocked.chmod(0o755)
        _copy_tracked_worktree(code)
    except BaseException:
        if sandbox is not None:
            shutil.rmtree(sandbox)
        raise
    finally:
        os.umask(old_umask)

    root_env = {
        "HOME": str(private_root),
        "HERMES_HOME": str(private_home),
        "PATH": f"{blockers}:{SYSTEM_PATH}",
        "SHELL": str(NATIVE_BASH),
        "TERM": "dumb",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "UV_CACHE_DIR": str(cache_base / "uv"),
        "CARGO_HOME": str(cache_base / "cargo"),
        "UV_OFFLINE": "1",
        "CARGO_NET_OFFLINE": "true",
        "UV_PYTHON_DOWNLOADS": "never",
    }
    try:
        # Real installer stages, real native interpreter and locked application
        # dependencies. No no-deps shortcut, live-venv symlink or stand-in CLI.
        for stage in ("venv", "python-deps"):
            harness = 'umask 022; exec "$@"'
            result = _run(
                [NATIVE_BASH, "-c", harness, "root-install", NATIVE_BASH,
                 code / "scripts/install.sh", "--stage", stage,
                 "--dir", code, "--hermes-home", private_home, "--non-interactive"],
                env=root_env,
                cwd=code,
                timeout=600,
            )
            _checked(result, f"native {stage}; cache/prerequisite failure is not a valid RED")
            if stage == "python-deps":
                assert "Main package installed (hash-verified via uv.lock)" in result.stdout, (
                    "Native fixture must not fall back to unlocked dependency tiers\n"
                    + result.stdout + result.stderr
                )
        _generate_launchers(code, code, public_bin, root_env)
        # Same valid runtime, but through a root-private path: root can execute
        # it and the other UID cannot. Do not resolve this alias before passing it.
        private_alias = private_root / "runtime"
        private_alias.symlink_to(code, target_is_directory=True)
        _generate_launchers(code, private_alias, broken_public, root_env)
        yield {
            "code": code,
            "public": public_bin,
            "broken_public": broken_public,
            "root_env": root_env,
            "account": account,
            "consumer_home": consumer_home,
            "workspace": workspace,
            "private_root": private_root,
            "private_home": private_home,
            "canary": canary,
        }
    finally:
        # This unique task-owned root is the only removal target. No daemons or
        # background agents are started; all application commands are awaited.
        shutil.rmtree(sandbox)


def _consumer_env(bundle):
    # Do not inherit HERMES_HOME, API keys, root HOME, PYTHONPATH, PYTHONHOME,
    # VIRTUAL_ENV, or uv settings. Test normal per-user default-home resolution.
    return {
        "HOME": str(bundle["consumer_home"]),
        "PATH": f'{bundle["public"]}:{SYSTEM_PATH}',
        "SHELL": str(NATIVE_BASH),
        "TERM": "dumb",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        # Pytest ancestry arms the live-DB guard even with a clean environment.
        # This child's HOME is disposable, but deliberately uses the default
        # .hermes location: permit its real SessionDB, not any host profile.
        "HERMES_STATE_DB_GUARD_BYPASS": "1",
    }


def _consumer_identity(bundle):
    result = _checked(
        _run(
            [NATIVE_PYTHON, "-c",
             'import json,os; print(json.dumps({"uid":os.getuid(),"euid":os.geteuid(),'
             '"gid":os.getgid(),"groups":os.getgroups()}))'],
            env=_consumer_env(bundle),
            cwd=bundle["workspace"],
            account=bundle["account"],
        ),
        "kernel credential check",
    )
    identity = json.loads(result.stdout)
    assert identity["uid"] == identity["euid"] == bundle["account"][0]
    assert identity["gid"] == bundle["account"][1]
    assert 0 not in identity["groups"]


def _assert_working_launcher(bundle, launcher):
    result = _checked(
        _run([launcher, "--version"], env=_consumer_env(bundle),
             cwd=bundle["workspace"], account=bundle["account"]),
        "unprivileged launch failed",
    )
    assert "Hermes Agent" in result.stdout


def test_private_root_runtime_fails_only_after_privilege_drop(installed_bundle):
    bundle = installed_bundle
    bad = bundle["broken_public"] / "hermes"
    _checked(
        _run([bad, "--version"], env=bundle["root_env"], cwd=bundle["code"]),
        "negative-control launcher must actually work as root",
    )
    _consumer_identity(bundle)
    denied = _run([bad, "--version"], env=_consumer_env(bundle),
                  cwd=bundle["workspace"], account=bundle["account"])
    assert denied.returncode == 126, denied.stdout + denied.stderr
    assert "Permission denied" in denied.stderr, denied.stderr
    assert stat.S_IMODE(bundle["private_root"].stat().st_mode) == 0o700
    assert bundle["canary"].read_text(encoding="utf-8") == CANARY


def test_shared_root_runtime_runs_with_private_per_user_state(installed_bundle):
    bundle = installed_bundle
    _checked(
        _run([bundle["public"] / "hermes", "--version"],
             env=bundle["root_env"], cwd=bundle["code"]),
        "shared launcher must work as root too",
    )
    _consumer_identity(bundle)
    _assert_working_launcher(bundle, bundle["public"] / "hermes")
    probe = r'''
import json, os, sys
from pathlib import Path
import hermes_constants
from hermes_cli.config import ensure_hermes_home
from hermes_state import SessionDB
ensure_hermes_home()
home = hermes_constants.get_hermes_home()
try:
    with Path(sys.argv[1]).open(encoding="utf-8") as handle:
        handle.read(1)
    root_secret_readable = True
except PermissionError:
    root_secret_readable = False
db = SessionDB()
try:
    db_path = str(db.db_path)
finally:
    db.close()
print("MULTIUSER_PROBE=" + json.dumps({
    "uid": os.getuid(), "euid": os.geteuid(), "groups": os.getgroups(),
    "prefix": sys.prefix, "home": str(home), "db": db_path,
    "source": str(Path(hermes_constants.__file__).resolve().parent),
    "root_secret_readable": root_secret_readable,
}))
'''
    result = _checked(
        _run([bundle["code"] / "venv/bin/python", "-c", probe, bundle["canary"]],
             env=_consumer_env(bundle), cwd=bundle["workspace"], account=bundle["account"]),
        "unprivileged real-runtime/state probe",
    )
    records = [line.removeprefix("MULTIUSER_PROBE=") for line in result.stdout.splitlines()
               if line.startswith("MULTIUSER_PROBE=")]
    assert len(records) == 1, result.stdout
    record = json.loads(records[0])
    home = bundle["consumer_home"] / ".hermes"
    assert record["uid"] == record["euid"] == bundle["account"][0]
    assert 0 not in record["groups"]
    assert Path(record["prefix"]) == bundle["code"] / "venv"
    assert Path(record["source"]) == bundle["code"]
    assert Path(record["home"]) == home
    assert Path(record["db"]) == home / "state.db"
    assert record["root_secret_readable"] is False
    for path in (home, home / "state.db"):
        assert path.stat().st_uid == bundle["account"][0]
    assert bundle["code"].stat().st_uid == 0
    assert bundle["canary"].stat().st_uid == 0
    assert stat.S_IMODE(bundle["private_home"].stat().st_mode) == 0o700
    assert stat.S_IMODE(bundle["canary"].stat().st_mode) == 0o600
    assert bundle["canary"].read_text(encoding="utf-8") == CANARY
    _checked(
        _run([bundle["public"] / "hermes", "sessions", "list"],
             env=_consumer_env(bundle), cwd=bundle["workspace"], account=bundle["account"]),
        "normal CLI command with consumer-owned state",
    )
