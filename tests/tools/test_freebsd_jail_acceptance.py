"""Native acceptance: containment, network policy, lifecycle, and project isolation."""
import shlex
import time

import pytest

from tools.freebsd_jail_client import spawn
from tools.freebsd_jail_policy import project_policy

pytestmark = pytest.mark.freebsd_only


def _environment(tmp_path, name, **kwargs):
    from tools.environments.freebsd_jail import FreeBSDJailEnvironment
    project = tmp_path / name
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    policy = project_policy(str(project), home=home, profile=home / ".hermes", **kwargs)
    return project, FreeBSDJailEnvironment(str(project), policy=policy)


def test_native_private_state_is_unreachable_through_every_surface(tmp_path, monkeypatch):
    from tools.freebsd_jail_policy import project_policy as build
    from tools.environments.freebsd_jail import FreeBSDJailEnvironment
    home = tmp_path / "home"
    project = home / "project"
    project.mkdir(parents=True)
    profile = home / ".hermes"
    (profile / "profiles" / "other").mkdir(parents=True)
    (profile / ".env").write_text("PROVIDER_PASSWORD=synthetic-only\n")
    ssh = home / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text("synthetic-private-key\n")
    (project / "escape").symlink_to(profile / ".env")
    monkeypatch.setenv("PROVIDER_PASSWORD", "synthetic-only")
    env = FreeBSDJailEnvironment(str(project), policy=build(str(project), home=home, profile=profile))
    try:
        env.init_session()
        private = [profile / ".env", ssh / "id_ed25519", profile / "profiles" / "other"]
        script = " && ".join([f"! cat {shlex.quote(str(path))} >/dev/null 2>&1" for path in private])
        script += (f" && ! cat escape >/dev/null 2>&1 && ! sh -c 'echo x > {shlex.quote(str(profile / '.env'))}'"
                   ' && echo contained')
        result = env.execute(f'test -z "$PROVIDER_PASSWORD" && {script}')
        assert result["returncode"] == 0 and "contained" in result["output"], result
        files = env.file_operations()
        assert files.read_file_raw(str(profile / ".env")).error
        assert files.read_file_raw(str(project / "escape")).error
        assert files._atomic_write(str(profile / ".env"), "changed").exit_code != 0
        assert (profile / ".env").read_text() == "PROVIDER_PASSWORD=synthetic-only\n"
    finally:
        env.cleanup()


@pytest.mark.parametrize("network, allowed", [("restricted", False), ("enabled", True)])
def test_native_network_policy(tmp_path, network, allowed):
    project = tmp_path / "project"
    project.mkdir()
    policy = project_policy(str(project), home=tmp_path, profile=tmp_path / ".hermes", network=network)
    probe = ("import socket\n"
             "listener = socket.socket()\n"
             "listener.bind(('127.0.0.1', 0))\n"
             "listener.listen(1)\n"
             "client = socket.create_connection(('127.0.0.1', listener.getsockname()[1]), timeout=3)\n"
             "print('network-ok')\n")
    process = spawn(["/usr/local/bin/python3", "-I", "-c", probe], policy, text=True)
    stdout, stderr = process.communicate(timeout=30)
    if allowed:
        assert process.returncode == 0 and "network-ok" in stdout, stderr
    else:
        assert process.returncode != 0, stdout


def test_native_relay_death_stops_detached_descendants(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    marker = project / "heartbeat"
    policy = project_policy(str(project), home=tmp_path, profile=tmp_path / ".hermes")
    process = spawn(["/bin/sh", "-c",
                     f"(while true; do date +%s >> {shlex.quote(str(marker))}; sleep 0.2; done) & "
                     "echo started; sleep 300"], policy, text=True)
    try:
        deadline = time.monotonic() + 20
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert marker.exists(), "background writer never started"
        time.sleep(1.0)
        process.kill()
        process.wait(timeout=10)
        time.sleep(1.0)
        settled = marker.stat().st_size
        time.sleep(1.5)
        assert marker.stat().st_size == settled, "descendant kept writing after relay death"
    finally:
        if process.poll() is None:
            process.kill()


def test_native_timeout_terminates_job_and_descendants(tmp_path):
    project, env = _environment(tmp_path, "project")
    marker = project / "timeout-heartbeat"
    try:
        env.init_session()
        script = (f"(while true; do date +%s >> {shlex.quote(str(marker))}; sleep 0.2; done) & sleep 300")
        started = time.monotonic()
        result = env.execute(script, timeout=5)
        assert time.monotonic() - started < 90, "timeout did not interrupt the job"
        assert result.get("returncode") != 0 or "timeout" in str(result.get("output", "")).lower(), result
        time.sleep(1.0)
        settled = marker.stat().st_size if marker.exists() else 0
        time.sleep(1.5)
        assert (marker.stat().st_size if marker.exists() else 0) == settled, "descendant survived the timeout"
        # The environment stays usable after a timed-out job.
        assert env.execute("echo alive")["output"].strip().endswith("alive")
    finally:
        env.cleanup()


def test_native_projects_do_not_share_authority(tmp_path):
    first, env_first = _environment(tmp_path, "first")
    second, env_second = _environment(tmp_path, "second")
    (first / "first-only.txt").write_text("first-only\n")
    (second / "second-only.txt").write_text("second-only\n")
    try:
        assert "first-only" in env_first.execute("cat first-only.txt")["output"]
        assert "second-only" in env_second.execute("cat second-only.txt")["output"]
        assert env_first.execute("cat ../second/second-only.txt")["returncode"] != 0
        assert env_second.execute("cat ../first/first-only.txt")["returncode"] != 0
        assert env_first.file_operations().read_file_raw(str(second / "second-only.txt")).error
    finally:
        env_first.cleanup()
        env_second.cleanup()
