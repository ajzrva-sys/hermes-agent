"""Profile-scoped, concrete authority for the FreeBSD execution adapter."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.freebsd_jail_policy import Grant, project_policy
from tools.terminal_scope import terminal_env


def settings():
    value = json.loads(terminal_env("TERMINAL_FREEBSD_JAIL", "{}"))
    if not isinstance(value, dict) or set(value) - {"grants", "read_only", "network"}:
        raise ValueError("invalid freebsd_jail configuration")
    grants = value.get("grants", [])
    if not isinstance(grants, list) or len(grants) > 512:
        raise ValueError("freebsd_jail grants must be a bounded list")
    concrete = []
    for grant in grants:
        if not isinstance(grant, dict) or set(grant) != {"path", "access"}:
            raise ValueError("jail grants require only path and access")
        concrete.append(Grant(**grant))
    readonly = value.get("read_only", False)
    network = value.get("network", "restricted")
    if type(readonly) is not bool or network not in {"restricted", "enabled"}:
        raise ValueError("unsupported freebsd_jail policy")
    return tuple(concrete), readonly, network


def cache_identity(task_id, session_key):
    from hermes_constants import get_hermes_home
    grants, readonly, network = settings()
    from tools.code_kernel import _resolve_owner
    identity = {
        "profile": str(get_hermes_home().resolve()),
        "conversation": _resolve_owner(task_id or "") or session_key or "default",
        "workspace": terminal_env("TERMINAL_CWD", "."),
        "grants": [g.wire() for g in grants],
        "read_only": readonly, "network": network,
    }
    return "freebsd:" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def configured_policy(workspace, extra_grants=()):
    """Concrete policy for *workspace* plus any caller-owned narrow grants.

    ``extra_grants`` is reserved for launch adapters that must expose one
    controller-owned resource (e.g. a staged cron script); it never widens
    profile/credential access.
    """
    from hermes_constants import get_hermes_home
    grants, readonly, network = settings()
    return project_policy(workspace, home=Path.home(), profile=get_hermes_home(),
                          approved=(*grants, *extra_grants), read_only=readonly, network=network)
