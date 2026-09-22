"""Authorized repositories, provider profiles, and trusted policies."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
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


def managed_policies_root() -> Path:
    """Default directory for Web-created Policy templates (local loopback)."""

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "worktree-review" / "policies"
    return Path.home() / ".local" / "share" / "worktree-review" / "policies"


async def assert_policy_path_outside_repositories(
    store: SqliteReviewRunStore, policy_path: Path
) -> Path:
    """Resolve ``policy_path`` and require it sits outside every registered repo."""

    resolved = await asyncio.to_thread(lambda: policy_path.expanduser().resolve())
    for row in await store.list_repositories():
        if resolved.is_relative_to(Path(row["canonical_root"])):
            raise TrustBoundaryError("trusted policy must not sit inside a reviewed repository")
    return resolved


def _default_review_policy_template() -> str:
    return (
        "schema: worktree-review.review-policy/v1\n"
        "version: 0.1.0\n"
        "required_dimensions:\n"
        "  - correctness\n"
        "  - security\n"
        "blocking_severities:\n"
        "  - critical\n"
        "  - major\n"
        "minimum_blocking_evidence_band: supported\n"
        "context:\n"
        "  max_file_bytes: 1048576\n"
        "  excluded_globs: []\n"
        "  mandatory_globs: []\n"
        "  optional_globs: []\n"
    )


def _default_remote_compute_policy_template(*, provider: str) -> str:
    if provider == "openai":
        return (
            "schema: worktree-review.compute-policy/v1\n"
            "version: 0.1.0\n"
            "provider: openai\n"
            "model: gpt-4o\n"
            "max_output_tokens_per_call: 8192\n"
            "max_budget_usd: 2.00\n"
            "allow_start_under_uncertain_price: false\n"
            "permit_remote_transmission: true\n"
            "input_usd_per_million_tokens: 2.5\n"
            "output_usd_per_million_tokens: 10\n"
            "data_destination: https://api.openai.com/v1\n"
            'known_retention: "Set this to the retention terms approved for your deployment."\n'
        )
    return (
        "schema: worktree-review.compute-policy/v1\n"
        "version: 0.1.0\n"
        "provider: anthropic\n"
        "model: claude-sonnet-4-5\n"
        "max_output_tokens_per_call: 8192\n"
        "max_budget_usd: 2.00\n"
        "allow_start_under_uncertain_price: false\n"
        "permit_remote_transmission: true\n"
        "input_usd_per_million_tokens: 3\n"
        "output_usd_per_million_tokens: 15\n"
        "data_destination: https://api.anthropic.com\n"
        'known_retention: "Set this to the retention terms approved for your deployment."\n'
    )


def _local_cli_user_config_template(profile_row: dict[str, Any]) -> str:
    """Starter user-config that binds to the given local-cli Provider Profile."""

    import yaml

    command = profile_command_argv(profile_row)
    if not command:
        raise TrustBoundaryError("local-cli profiles require a command argv")
    adapter = str(profile_row.get("local_cli_adapter") or "worktree-json")
    if adapter not in _LOCAL_CLI_ADAPTERS:
        raise TrustBoundaryError(f"unknown local-cli adapter: {adapter}")
    document = {
        "schema": "worktree-review.config/v1",
        "version": "0.1.0",
        "provider": "local-cli",
        "command": list(command),
        "adapter": adapter,
        "model": command[0],
    }
    return yaml.safe_dump(document, sort_keys=False)


def _policy_template_text(kind: str, *, profile_row: dict[str, Any] | None = None) -> str:
    """Return starter YAML for a managed Policy create.

    When a Provider Profile is supplied for Compute, the template matches that
    provider so binding validation can succeed on first create.
    """

    if kind == "review":
        repo_examples = Path(__file__).resolve().parents[4] / "examples" / "review-policy.yaml"
        if repo_examples.is_file():
            return repo_examples.read_text(encoding="utf-8")
        return _default_review_policy_template()

    provider = str(profile_row.get("provider") or "anthropic") if profile_row else "anthropic"
    if provider == "local-cli":
        if profile_row is None:
            raise TrustBoundaryError("local-cli managed Compute Policy requires a Provider Profile")
        return _local_cli_user_config_template(profile_row)
    if provider == "openai":
        return _default_remote_compute_policy_template(provider="openai")
    if provider == "anthropic":
        repo_examples = Path(__file__).resolve().parents[4] / "examples" / "compute-policy.yaml"
        if repo_examples.is_file():
            return repo_examples.read_text(encoding="utf-8")
        return _default_remote_compute_policy_template(provider="anthropic")
    raise TrustBoundaryError(f"unsupported provider for managed Compute Policy: {provider}")


def _safe_managed_filename(filename: str, *, kind: str) -> str:
    cleaned = Path(filename).name.strip()
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise TrustBoundaryError("filename must be a plain file name without directories")
    if not cleaned.endswith((".yaml", ".yml")):
        cleaned = f"{cleaned}.yaml"
    if kind == "review" and "compute" in cleaned.lower():
        raise TrustBoundaryError("review policy filename must not look like a compute policy")
    return cleaned


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` via a same-directory temp file then replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.is_file():
            temporary.unlink(missing_ok=True)


def policy_document_content_sha256(text: str) -> str:
    """Raw UTF-8 document fingerprint for editor optimistic concurrency.

    Distinct from Policy identity sha256, which hashes the canonical parsed
    document and ignores comments / insignificant YAML formatting.
    """

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def exclusive_create_text(path: Path, text: str) -> None:
    """Create ``path`` only when absent (``O_CREAT|O_EXCL``) and write ``text``.

    Concurrent creators racing on the same name cannot overwrite each other:
    the loser raises ``TrustBoundaryError`` instead of replacing the winner's file.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags, 0o644)
    except FileExistsError as exc:
        raise TrustBoundaryError(f"managed policy file already exists: {path}") from exc
    except OSError as exc:
        raise TrustBoundaryError(f"cannot create managed policy file {path}: {exc}") from exc
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
    except Exception:
        path.unlink(missing_ok=True)
        raise


@contextmanager
def _policy_document_lock(path: Path, *, exclusive: bool = True) -> Iterator[None]:
    """Flock for Policy document read/write on ``path``.

    Uses a sibling ``.<name>.lock``. Writers take ``LOCK_EX`` and must update
    the registry identity before releasing. Readers take ``LOCK_SH`` so text
    and sha256 are sampled from one stable generation.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), lock_mode)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


async def read_trusted_policy_document(
    store: SqliteReviewRunStore,
    *,
    kind: str,
    policy_id: str,
) -> dict[str, Any]:
    table = "trusted_review_policies" if kind == "review" else "trusted_compute_policies"
    row = await store.get_trusted_policy(table, policy_id)
    if row is None:
        raise TrustBoundaryError("unknown policy")
    path = Path(row["path"])
    await assert_policy_path_outside_repositories(store, path)

    def _load() -> tuple[str, dict[str, Any], str, str]:
        # Shared lock + identity/content digests from the same bytes as ``text``.
        with _policy_document_lock(path, exclusive=False):
            if not path.is_file():
                raise TrustBoundaryError(f"policy not found: {path}")
            text = path.read_text(encoding="utf-8")
            content_sha256 = policy_document_content_sha256(text)
            snapshot = path.with_name(
                f".read-{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
            )
            try:
                snapshot.write_text(text, encoding="utf-8")
                if kind == "review":
                    review_policy, identity = load_review_policy(snapshot)
                    summary = {
                        "version": review_policy.version,
                        "blocking_severities": [
                            item.value for item in review_policy.blocking_severities
                        ],
                        "required_dimensions": list(review_policy.required_dimensions),
                    }
                    return text, summary, identity.sha256, content_sha256
                compute_policy, identity, source_format = load_trusted_compute_document(
                    snapshot
                )
                summary = {
                    "version": compute_policy.version,
                    "provider": compute_policy.provider,
                    "model": compute_policy.model,
                    "source_format": source_format,
                }
                return text, summary, identity.sha256, content_sha256
            finally:
                snapshot.unlink(missing_ok=True)

    text, summary, sha256, content_sha256 = await asyncio.to_thread(_load)
    return {
        "policy_id": policy_id,
        "kind": kind,
        "path": str(path),
        "sha256": sha256,
        "content_sha256": content_sha256,
        "registered_sha256": row["version_sha256"],
        "text": text,
        "summary": summary,
    }


async def write_trusted_policy_document(
    store: SqliteReviewRunStore,
    *,
    kind: str,
    policy_id: str,
    expected_content_sha256: str,
    text: str,
) -> dict[str, Any]:
    table = "trusted_review_policies" if kind == "review" else "trusted_compute_policies"
    row = await store.get_trusted_policy(table, policy_id)
    if row is None:
        raise TrustBoundaryError("unknown policy")
    path = Path(row["path"])
    await assert_policy_path_outside_repositories(store, path)

    profile_row = None
    if kind == "compute" and row.get("provider_profile_id"):
        profile_row = await store.get_provider_profile(str(row["provider_profile_id"]))

    def _locked_validate_write_and_register() -> tuple[str, str, str | None]:
        with _policy_document_lock(path, exclusive=True):
            # Optimistic lock on raw UTF-8 bytes so comment/formatting edits
            # also conflict; Policy identity sha256 alone would miss those.
            if not path.is_file():
                raise TrustBoundaryError("policy_content_changed")
            disk_text = path.read_text(encoding="utf-8")
            if policy_document_content_sha256(disk_text) != expected_content_sha256:
                raise TrustBoundaryError("policy_content_changed")

            temporary_path = path.with_name(
                f".validate-{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            try:
                temporary_path.write_text(text, encoding="utf-8")
                if kind == "review":
                    _review, identity = load_review_policy(temporary_path)
                    source_format: str | None = None
                    semver = identity.semver
                    sha256 = identity.sha256
                else:
                    compute_policy, identity, source_format = load_trusted_compute_document(
                        temporary_path
                    )
                    if profile_row is not None:
                        validate_compute_policy_binding(compute_policy, profile_row)
                    semver = identity.semver
                    sha256 = identity.sha256
            finally:
                if temporary_path.is_file():
                    temporary_path.unlink(missing_ok=True)
            atomic_write_text(path, text)
            # Registry update stays inside the exclusive lock so a concurrent
            # writer cannot publish a newer disk generation while this request
            # still holds a stale identity write.
            store.update_trusted_policy_identity_sync(
                table=table,
                policy_id=policy_id,
                version_semver=semver,
                version_sha256=sha256,
                source_format=source_format,
            )
            return semver, sha256, source_format

    await asyncio.to_thread(_locked_validate_write_and_register)
    return await read_trusted_policy_document(store, kind=kind, policy_id=policy_id)


async def create_managed_trusted_policy(
    store: SqliteReviewRunStore,
    *,
    kind: str,
    filename: str,
    provider_profile_id: str | None = None,
) -> dict[str, str | None]:
    safe_name = _safe_managed_filename(filename, kind=kind)
    target = managed_policies_root() / safe_name
    await assert_policy_path_outside_repositories(store, target)
    profile_row: dict[str, Any] | None = None
    if provider_profile_id is not None:
        profile_row = await store.get_provider_profile(provider_profile_id)
        if profile_row is None:
            raise TrustBoundaryError(
                f"unknown provider profile for compute policy binding: {provider_profile_id}"
            )
    template = _policy_template_text(kind, profile_row=profile_row)
    # O_EXCL create: concurrent same-name creators cannot overwrite a winner,
    # so failed-register cleanup cannot delete another request's file.
    await asyncio.to_thread(exclusive_create_text, target, template)
    try:
        return await register_trusted_policy(
            store,
            target,
            kind=kind,
            provider_profile_id=provider_profile_id,
        )
    except Exception:
        # Only this creator holds the exclusive file; safe to remove on failure.
        if await asyncio.to_thread(target.is_file):
            await asyncio.to_thread(target.unlink)
        raise


async def unregister_trusted_policy(
    store: SqliteReviewRunStore, *, kind: str, policy_id: str
) -> bool:
    table = "trusted_review_policies" if kind == "review" else "trusted_compute_policies"
    return await store.delete_trusted_policy(table, policy_id)
