"""Authorized repositories, provider profiles, and trusted policies."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from worktree_review.core.errors import InvalidInvocationError
from worktree_review.core.git import repository_root
from worktree_review.core.policy import load_compute_policy, load_review_policy
from worktree_review.platform.web.local_store import SqliteReviewRunStore

_ENV_REFERENCE_PREFIX = "${"
_ENV_REFERENCE_SUFFIX = "}"


class TrustBoundaryError(InvalidInvocationError):
    pass


def _resolved_dir(path: Path) -> Path:
    if path.is_symlink():
        raise TrustBoundaryError("repository root must not be a symlink")
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise TrustBoundaryError(f"repository root does not exist: {resolved}")
    return resolved


def _resolved_file(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise TrustBoundaryError(f"policy not found: {resolved}")
    return resolved


def parse_credential_reference(value: str) -> str:
    if not (value.startswith(_ENV_REFERENCE_PREFIX) and value.endswith(_ENV_REFERENCE_SUFFIX)):
        raise TrustBoundaryError("credential_reference must be an ${ENV_VAR} reference")
    name = value[len(_ENV_REFERENCE_PREFIX) : -len(_ENV_REFERENCE_SUFFIX)]
    if not name or not name.replace("_", "").isalnum():
        raise TrustBoundaryError("credential_reference is not a valid environment variable")
    return name


def resolve_credential_reference(reference: str) -> str:
    name = parse_credential_reference(reference)
    value = os.environ.get(name)
    if not value:
        raise TrustBoundaryError(f"environment variable {name} is not set")
    return value


async def register_local_repository(
    store: SqliteReviewRunStore,
    *,
    requested_root: Path,
    display_name: str,
) -> dict[str, str]:
    resolved = _resolved_dir(requested_root)
    root = await repository_root(resolved)
    canonical = str(root)
    repositories = await store.list_repositories()
    existing = [row for row in repositories if row["canonical_root"] == canonical]
    if existing:
        return existing[0]
    repository_id = str(uuid.uuid4())
    await store.insert_repository(
        repository_id=repository_id,
        display_name=display_name,
        canonical_root=canonical,
    )
    return {
        "id": repository_id,
        "display_name": display_name,
        "canonical_root": canonical,
    }


async def require_registered_repository_path(
    store: SqliteReviewRunStore, repository_path: Path
) -> Path:
    resolved = _resolved_dir(repository_path)
    roots = {row["canonical_root"] for row in await store.list_repositories()}
    if str(resolved) not in roots:
        raise TrustBoundaryError("repository_path is not a registered repository")
    return resolved


async def register_trusted_policy(
    store: SqliteReviewRunStore,
    path: Path,
    *,
    kind: str,
) -> dict[str, str]:
    resolved = _resolved_file(path)
    for row in await store.list_repositories():
        if resolved.is_relative_to(Path(row["canonical_root"])):
            raise TrustBoundaryError("trusted policy must not sit inside a reviewed repository")
    if kind == "review":
        _policy, identity = load_review_policy(resolved)
        table = "trusted_review_policies"
    elif kind == "compute":
        _policy, identity = load_compute_policy(resolved)
        table = "trusted_compute_policies"
    else:
        raise TrustBoundaryError("unknown policy kind")
    policy_id = str(uuid.uuid4())
    await store.insert_trusted_policy(
        table=table,
        policy_id=policy_id,
        path=str(resolved),
        version_semver=identity.semver,
        version_sha256=identity.sha256,
    )
    return {
        "id": policy_id,
        "path": str(resolved),
        "version_semver": identity.semver,
        "version_sha256": identity.sha256,
    }
