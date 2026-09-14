"""Authorized repositories, provider profiles, and trusted policies."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, get_args

from worktree_review.core.config import (
    LocalCliAdapterName,
    load_user_configuration,
    local_cli_configuration_fingerprint,
)
from worktree_review.core.errors import InvalidInvocationError
from worktree_review.core.git import repository_root
from worktree_review.core.identity import PolicyVersionIdentity
from worktree_review.core.policy import (
    ComputePolicy,
    load_compute_policy,
    load_review_policy,
)
from worktree_review.platform.web.local_store import SqliteReviewRunStore

_LOCAL_CLI_ADAPTERS = frozenset(get_args(LocalCliAdapterName))

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


def profile_command_argv(profile_row: dict[str, Any]) -> tuple[str, ...]:
    raw = profile_row.get("local_cli_command")
    if isinstance(raw, str) and raw:
        loaded = json.loads(raw)
        raw = loaded if isinstance(loaded, list) else []
    if not isinstance(raw, list):
        return ()
    return tuple(str(argument) for argument in raw)


def validate_provider_profile_shape(
    *,
    provider: str,
    endpoint: str | None,
    credential_reference: str | None,
    local_cli_adapter: str | None,
    local_cli_command: list[str] | None,
) -> None:
    """Reject profiles whose connection fields do not match the provider kind."""

    if provider not in ("anthropic", "openai", "local-cli"):
        raise TrustBoundaryError(f"unknown provider: {provider}")
    if provider == "local-cli":
        if not local_cli_command:
            raise TrustBoundaryError("local-cli profiles require a command argv")
        if any(not argument.strip() for argument in local_cli_command):
            raise TrustBoundaryError("local-cli command arguments must not be empty")
        adapter = local_cli_adapter or "worktree-json"
        if adapter not in _LOCAL_CLI_ADAPTERS:
            raise TrustBoundaryError(f"unknown local-cli adapter: {adapter}")
        if endpoint is not None or credential_reference is not None:
            raise TrustBoundaryError(
                "endpoint and credential_reference are only valid for remote providers"
            )
    else:
        if local_cli_adapter is not None or local_cli_command is not None:
            raise TrustBoundaryError(
                "local_cli_adapter and local_cli_command are only valid for local-cli"
            )
        if credential_reference is None:
            raise TrustBoundaryError(
                "remote provider profiles require a ${ENV_VAR} credential reference"
            )
        parse_credential_reference(credential_reference)
        if endpoint is not None:
            from urllib.parse import urlparse

            parsed_endpoint = urlparse(endpoint)
            if parsed_endpoint.scheme != "https" or not parsed_endpoint.hostname:
                raise TrustBoundaryError(
                    "provider endpoint must be an https:// URL; credentials must "
                    "never travel over plain HTTP"
                )


def local_cli_profile_fingerprint(
    profile_row: dict[str, Any], compute_policy: ComputePolicy
) -> str:
    command = profile_command_argv(profile_row)
    adapter = str(profile_row.get("local_cli_adapter") or "worktree-json")
    if adapter not in _LOCAL_CLI_ADAPTERS:
        raise TrustBoundaryError(f"unknown local-cli adapter: {adapter}")
    return local_cli_configuration_fingerprint(
        command=command,
        adapter=adapter,  # type: ignore[arg-type]
        model=compute_policy.model,
        data_destination=compute_policy.data_destination,
        known_retention=compute_policy.known_retention,
    )


def validate_compute_policy_binding(
    compute_policy: ComputePolicy, profile_row: dict[str, Any]
) -> None:
    """A trusted Compute Policy may only bind a compatible Provider Profile."""

    provider = str(profile_row.get("provider") or "")
    if provider != compute_policy.provider:
        raise TrustBoundaryError(
            f"provider profile provider {provider!r} does not match the Compute Policy "
            f"provider {compute_policy.provider!r}"
        )
    if compute_policy.provider == "local-cli":
        expected = local_cli_profile_fingerprint(profile_row, compute_policy)
        if compute_policy.provider_configuration_fingerprint is None:
            raise TrustBoundaryError(
                "binding a local-cli profile requires a Compute Policy with "
                "provider_configuration_fingerprint; derive one from the CLI "
                "user configuration so command identity is pinned"
            )
        if compute_policy.provider_configuration_fingerprint != expected:
            raise TrustBoundaryError(
                "local-cli profile command/adapter do not match the Compute Policy "
                "provider_configuration_fingerprint"
            )


async def register_local_repository(
    store: SqliteReviewRunStore,
    *,
    requested_root: Path,
    display_name: str,
) -> dict[str, str]:
    resolved = _resolved_dir(requested_root)
    root = await repository_root(resolved)
    canonical = str(root)
    # Both directions of the trust boundary: a trusted policy must not sit
    # inside a reviewed repository, and a repository must not swallow an
    # already-registered trusted policy (registering the policy first and
    # the repository second would otherwise bypass the check above).
    canonical_path = Path(canonical)
    for table in ("trusted_review_policies", "trusted_compute_policies"):
        for policy_row in await store.list_trusted_policies(table):
            if Path(policy_row["path"]).is_relative_to(canonical_path):
                raise TrustBoundaryError(
                    "repository would contain the already-registered trusted policy "
                    f"{policy_row['path']}; trusted policies must live outside every "
                    "reviewed repository"
                )
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
    provider_profile_id: str | None = None,
) -> dict[str, str | None]:
    resolved = _resolved_file(path)
    for row in await store.list_repositories():
        if resolved.is_relative_to(Path(row["canonical_root"])):
            raise TrustBoundaryError("trusted policy must not sit inside a reviewed repository")
    if kind == "review":
        if provider_profile_id is not None:
            raise TrustBoundaryError("a Review Policy does not bind a provider profile")
        _review_policy, identity = load_review_policy(resolved)
        table = "trusted_review_policies"
        source_format: str | None = None
    elif kind == "compute":
        compute_policy, identity, source_format = load_trusted_compute_document(resolved)
        table = "trusted_compute_policies"
        if provider_profile_id is not None:
            profile_row = await store.get_provider_profile(provider_profile_id)
            if profile_row is None:
                raise TrustBoundaryError(
                    f"unknown provider profile for compute policy binding: {provider_profile_id}"
                )
            validate_compute_policy_binding(compute_policy, profile_row)
    else:
        raise TrustBoundaryError("unknown policy kind")
    policy_id = str(uuid.uuid4())
    await store.insert_trusted_policy(
        table=table,
        policy_id=policy_id,
        path=str(resolved),
        version_semver=identity.semver,
        version_sha256=identity.sha256,
        provider_profile_id=provider_profile_id,
        source_format=source_format,
    )
    record: dict[str, str | None] = {
        "id": policy_id,
        "path": str(resolved),
        "version_semver": identity.semver,
        "version_sha256": identity.sha256,
        "source_format": source_format,
    }
    if provider_profile_id is not None:
        record["provider_profile_id"] = provider_profile_id
    return record


def load_trusted_compute_document(
    path: Path,
) -> tuple[ComputePolicy, PolicyVersionIdentity, str]:
    """Load a trusted compute document in either accepted format.

    ``compute-policy`` files are the advanced schema-checked form (remote
    providers only — the Core schema deliberately refuses local-cli there).
    ``user-config`` files (worktree-review.config/v1) are the only trusted
    source for local-cli: consent, disclosure and the command fingerprint are
    derived, mirroring the CLI path exactly.
    """

    import yaml  # local import keeps module import light

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        document = None
    if isinstance(document, dict) and document.get("schema") == "worktree-review.config/v1":
        compute_policy, identity, _provider_configuration = load_user_configuration(path)
        return compute_policy, identity, "user-config"
    compute_policy, identity = load_compute_policy(path)
    return compute_policy, identity, "compute-policy"
