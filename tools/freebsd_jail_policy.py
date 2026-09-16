"""Concrete authority for the native jail backend; no ambient credential inheritance."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os

MAX_GRANTS = 512
PROTECTED_METADATA = (".git", ".hermes", ".agents", ".codex", ".ca")
RUNTIME_ENV = frozenset({"TERM", "COLORTERM", "LANG", "LC_ALL", "LC_CTYPE", "TZ"})


@dataclass(frozen=True)
class Grant:
    path: str
    access: str

    def __post_init__(self):
        path = Path(self.path)
        if (self.access not in {"read", "write", "deny"} or not path.is_absolute()
                or self.path != str(path) or ".." in path.parts or path == Path("/")):
            raise ValueError("jail grants require a concrete absolute non-root path and read/write/deny access")
        if any(c in self.path for c in "\x00*?[]"):
            raise ValueError("glob and NUL paths are not supported by the jail backend")

    def wire(self):
        return {"path": self.path, "access": self.access}


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def private_roots(home: Path, profile: Path) -> tuple[Path, ...]:
    return tuple(dict.fromkeys(p.resolve() for p in (
        profile, home / ".hermes", home / ".ssh", home / ".codex",
        home / ".config/ca", home / ".local/share/ca", home / ".aws",
        home / ".config/gcloud", home / ".kube", home / ".gnupg",
    )))


@dataclass(frozen=True)
class JailPolicy:
    workspace: str
    grants: tuple[Grant, ...]
    network: str = "restricted"

    def __post_init__(self):
        if self.network not in {"restricted", "enabled"}:
            raise ValueError("the jail service does not support proxies or narrower network policies")
        if len(self.grants) > MAX_GRANTS:
            raise ValueError("too many concrete jail grants")

    @property
    def identity(self) -> str:
        return hashlib.sha256(json.dumps(self.wire(), sort_keys=True).encode()).hexdigest()

    def wire(self):
        return {"grants": [g.wire() for g in self.grants], "network": self.network}


def project_policy(workspace: str, *, home: Path, profile: Path,
                   approved: tuple[Grant, ...] = (), read_only: bool = False,
                   network: str = "restricted") -> JailPolicy:
    """Only the controller's approval path may supply ``approved`` authority."""
    root = Path(workspace).expanduser().resolve(strict=True)
    home = home.resolve()
    denied = private_roots(home, profile)
    if not root.is_dir() or root == Path("/") or root == home or any(_inside(root, p) for p in denied):
        raise ValueError("select a project directory outside private profile storage")
    grants = [Grant(str(root), "read" if read_only else "write")]
    for grant in approved:
        target = Path(grant.path)
        if grant.access != "deny" and any(_inside(target, p) for p in denied):
            raise ValueError("generic workers cannot receive private controller storage")
        grants.append(grant)
    # Metadata starts read-only. Exact approved metadata writes may override it,
    # but credential roots always remain denied, including nested exceptions.
    for grant in tuple(grants):
        if grant.access == "write":
            for name in PROTECTED_METADATA:
                metadata = Path(grant.path) / name
                grants.append(Grant(str(metadata), "read"))
    grants.extend(approved)
    grants.extend(Grant(str(path), "deny") for path in denied)
    # One rule per concrete path; approval can replace a metadata read rule,
    # while the final private-root denies cannot be overwritten.
    concrete = {grant.path: grant for grant in grants}
    return JailPolicy(str(root), tuple(concrete.values()), network)


def worker_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if source is None else source
    result = {key: value for key, value in source.items() if key in RUNTIME_ENV}
    result.update(PATH="/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin",
                  HOME="/tmp/hermes-home", TMPDIR="/tmp", LANG="C.UTF-8")
    return result
