"""CLI resolution: current worktree snapshots, Git refs, and trusted policies."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from worktree_review.core.config import (
    ProviderConfiguration,
    load_user_configuration,
)
from worktree_review.core.errors import InvalidInvocationError
from worktree_review.core.git import (
    GitCliError,
    repository_root,
    require_git_version,
    resolve_commit,
    snapshot_git_working_tree_as_commit,
    worktree_is_clean,
)
from worktree_review.core.identity import (
    PolicyVersionIdentity,
    ProposedSource,
    ResolvedCommitPair,
)
from worktree_review.core.policy import (
    ComputePolicy,
    ReviewPolicy,
    load_builtin_review_policy,
    load_compute_policy,
    load_review_policy,
)


def provider_transmission_disclosure(compute_policy: ComputePolicy) -> str:
    if compute_policy.provider == "local-cli":
        return (
            "Worktree Review local provider (no remote transmission):\n"
            f"  command: {compute_policy.model}"
        )
    return (
        "Worktree Review remote transmission (Compute Policy):\n"
        f"  provider: {compute_policy.provider}\n"
        f"  model: {compute_policy.model}\n"
        f"  data_destination: {compute_policy.data_destination}\n"
        f"  known_retention: {compute_policy.known_retention}"
    )


def require_remote_transmission_permit(compute_policy: ComputePolicy) -> None:
    if compute_policy.provider == "local-cli" or compute_policy.permit_remote_transmission:
        return
    raise InvalidInvocationError(
        provider_transmission_disclosure(compute_policy)
        + "\nCompute Policy does not permit remote transmission "
        "(set permit_remote_transmission: true in a trusted Compute Policy)."
    )


USER_CONFIG_FILENAME = "config.yaml"


class PreparedCliReview(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    resolved: ResolvedCommitPair
    review_policy: ReviewPolicy
    review_policy_version: PolicyVersionIdentity
    review_policy_path: Path | None = None
    compute_policy: ComputePolicy
    compute_policy_version: PolicyVersionIdentity
    compute_policy_path: Path | None = None
    config_path: Path | None = None
    provider_configuration: ProviderConfiguration | None = None


def default_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "worktree-review"
    return Path.home() / ".config" / "worktree-review"


def assert_trusted_file_outside_worktree(file_path: Path, worktree: Path) -> None:
    resolved_file = file_path.resolve()
    resolved_worktree = worktree.resolve()
    if resolved_file.is_relative_to(resolved_worktree):
        raise InvalidInvocationError(
            f"trusted configuration path {resolved_file} is inside the reviewed worktree "
            f"{resolved_worktree}; Review Policy, Compute Policy, and provider "
            "configuration must come from a trusted location outside the repository under review"
        )


def _resolve_default_file_path(
    explicit: Path | None,
    *,
    filename: str,
    flag: str,
) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    candidate = default_config_dir() / filename
    if candidate.is_file():
        return candidate
    raise InvalidInvocationError(
        f"no {flag} given and {candidate} does not exist; pass {flag} pointing "
        "at a trusted configuration file outside the reviewed repository"
    )


def _expand_user_path(path: Path) -> Path:
    return path.expanduser()


async def prepare_cli_review(
    *,
    repository: Path,
    target_ref: str | None = None,
    recent_commit_count: int | None = None,
    proposed_ref: str | None = None,
    policy_path: Path | None = None,
    compute_policy_path: Path | None = None,
    config_path: Path | None = None,
) -> PreparedCliReview:
    await require_git_version()
    root = await repository_root(repository)
    if target_ref is not None and recent_commit_count is not None:
        raise InvalidInvocationError(
            "--target and --commits cannot be used together; use --commits N to review "
            "the last N commits plus current worktree changes"
        )
    if recent_commit_count is not None and recent_commit_count < 0:
        raise InvalidInvocationError("--commits must be zero or greater")

    resolved_target_ref = (
        target_ref
        if target_ref is not None
        else "HEAD"
        if recent_commit_count is None or recent_commit_count == 0
        else f"HEAD~{recent_commit_count}"
    )
    if proposed_ref is not None and recent_commit_count is not None:
        raise InvalidInvocationError(
            "--proposed cannot be combined with --commits; --commits reviews the current "
            "worktree snapshot"
        )
    current_head_oid: str | None = None
    if proposed_ref is None or target_ref is None:
        current_head_oid = await resolve_commit("HEAD", root)
    if proposed_ref is not None and not await worktree_is_clean(root):
        raise InvalidInvocationError(
            f"worktree {root} has current changes; omit --proposed to review them, or "
            "clean the worktree before selecting an explicit committed proposed ref"
        )

    if policy_path is None:
        review_policy, review_version = load_builtin_review_policy()
        resolved_review_path: Path | None = None
    else:
        resolved_review_path = _expand_user_path(policy_path)
        assert_trusted_file_outside_worktree(resolved_review_path, root)
        if not resolved_review_path.is_file():
            raise InvalidInvocationError(f"review policy file not found: {resolved_review_path}")
        review_policy, review_version = load_review_policy(resolved_review_path)

    if compute_policy_path is not None and config_path is not None:
        raise InvalidInvocationError(
            "--config and --compute-policy cannot be used together; use --config for the "
            "minimal provider configuration or --compute-policy for an advanced Compute Policy"
        )
    resolved_compute_path: Path | None = None
    resolved_config_path: Path | None = None
    provider_configuration: ProviderConfiguration | None = None
    if compute_policy_path is not None:
        resolved_compute_path = _expand_user_path(compute_policy_path)
        assert_trusted_file_outside_worktree(resolved_compute_path, root)
        if not resolved_compute_path.is_file():
            raise InvalidInvocationError(f"compute policy file not found: {resolved_compute_path}")
        compute_policy, compute_version = load_compute_policy(resolved_compute_path)
    else:
        resolved_config_path = _resolve_default_file_path(
            config_path,
            filename=USER_CONFIG_FILENAME,
            flag="--config",
        )
        assert_trusted_file_outside_worktree(resolved_config_path, root)
        if not resolved_config_path.is_file():
            raise InvalidInvocationError(
                f"user configuration file not found: {resolved_config_path}"
            )
        (
            compute_policy,
            compute_version,
            provider_configuration,
        ) = load_user_configuration(resolved_config_path)
    target_head_oid = await resolve_commit(resolved_target_ref, root)
    if proposed_ref is not None:
        resolved_proposed_ref = proposed_ref
        proposed_head_oid = await resolve_commit(proposed_ref, root)
    else:
        resolved_proposed_ref = "WORKTREE"
        if current_head_oid is None:
            raise InvalidInvocationError(
                "cannot capture the current worktree without resolving its current HEAD"
            )
        try:
            proposed_head_oid = await snapshot_git_working_tree_as_commit(root, current_head_oid)
        except GitCliError as exc:
            raise InvalidInvocationError(f"cannot snapshot current worktree: {exc}") from exc

    return PreparedCliReview(
        resolved=ResolvedCommitPair(
            source_repository=str(root),
            target_ref=resolved_target_ref,
            target_head_oid=target_head_oid,
            proposed_ref=resolved_proposed_ref,
            proposed_head_oid=proposed_head_oid,
            proposed_source=(
                ProposedSource.COMMITTED_REF
                if proposed_ref is not None
                else ProposedSource.CURRENT_WORKTREE_SNAPSHOT
            ),
        ),
        review_policy=review_policy,
        review_policy_version=review_version,
        review_policy_path=(
            None if resolved_review_path is None else resolved_review_path.resolve()
        ),
        compute_policy=compute_policy,
        compute_policy_version=compute_version,
        compute_policy_path=(
            None if resolved_compute_path is None else resolved_compute_path.resolve()
        ),
        config_path=(None if resolved_config_path is None else resolved_config_path.resolve()),
        provider_configuration=provider_configuration,
    )
