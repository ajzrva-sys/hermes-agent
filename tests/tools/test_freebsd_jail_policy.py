"""The concrete jail policy must not turn profile access into worker authority."""
from pathlib import Path

import pytest

from tools.freebsd_jail_policy import Grant, project_policy, worker_environment


def test_project_policy_excludes_private_state_and_preserves_read_only(tmp_path):
    home = tmp_path / "home"
    project = home / "project"
    project.mkdir(parents=True)
    profile = home / ".hermes/profiles/work"
    policy = project_policy(str(project), home=home, profile=profile, read_only=True)
    assert Grant(str(project), "read") in policy.grants
    assert Grant(str(home / ".hermes"), "deny") in policy.grants
    assert policy.network == "restricted"
    for denied in (home, profile):
        denied.mkdir(parents=True, exist_ok=True)
        with pytest.raises(ValueError):
            project_policy(str(denied), home=home, profile=profile)
    with pytest.raises(ValueError):
        project_policy(str(project), home=home, profile=profile,
                       approved=(Grant(str(profile / ".env"), "read"),))
    with pytest.raises(ValueError):
        Grant(str(project / "*.txt"), "write")
    with pytest.raises(ValueError):
        project_policy(str(project), home=home, profile=profile, network="managed_proxy")


def test_worker_environment_is_an_allowlist_not_a_secret_name_filter():
    env = worker_environment({"TERM": "xterm", "PROVIDER_PASSWORD": "fixture",
                              "UNRECOGNIZED_CREDENTIAL_NAME": "fixture", "HERMES_HOME": "/private",
                              "SSH_AUTH_SOCK": "/socket", "PATH": "/untrusted", "HOME": "/host"})
    assert env["TERM"] == "xterm"
    assert env["HOME"].startswith("/tmp/")
    assert env["PATH"].startswith("/usr/local/bin:")
    assert not ({"PROVIDER_PASSWORD", "UNRECOGNIZED_CREDENTIAL_NAME", "HERMES_HOME", "SSH_AUTH_SOCK"} & env.keys())
