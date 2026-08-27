"""CLI pre-pipeline checks: git version, clean worktree, trusted policy paths (D2, D5, D10)."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from worktree_review.core.errors import InvalidInvocationError
from worktree_review.core.git import (
    repository_root,
    require_git_version,
    resolve_commit,
    worktree_is_clean,
)
from worktree_review.core.identity import PolicyVersionIdentity, ResolvedCommitPair
from worktree_review.core.policy import (
    ComputePolicy,
    ReviewPolicy,
    load_compute_policy,
    load_review_policy,
)


def remote_transmission_disclosure(compute_policy: ComputePolicy) -> str:
    return (
        "Worktree Review remote transmission (Compute Policy):\n"
        f"  provider: {compute_policy.provider}\n"
        f"  model: {compute_policy.model}\n"
        f"  data_destination: {compute_policy.data_destination}\n"
        f"  known_retention: {compute_policy.known_retention}"
    )


def require_remote_transmission_permit(compute_policy: ComputePolicy) -> None:
    if compute_policy.permit_remote_transmission:
        return
    raise InvalidInvocationError(
        remote_transmission_disclosure(compute_policy)
        + "\nCompute Policy does not permit remote transmission "
        "(set permit_remote_transmission: true in a trusted Compute Policy)."
    )


REVIEW_POLICY_FILENAME = "review-policy.yaml"
COMPUTE_POLICY_FILENAME = "compute-policy.yaml"


class PreparedCliReview(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    resolved: ResolvedCommitPair
    review_policy: ReviewPolicy
    review_policy_version: PolicyVersionIdentity
    review_policy_path: Path
    compute_policy: ComputePolicy
    compute_policy_version: PolicyVersionIdentity
    compute_policy_path: Path


def default_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "worktree-review"
    return Path.home() / ".config" / "worktree-review"


def assert_policy_outside_worktree(policy_path: Path, worktree: Path) -> None:
    resolved_policy = policy_path.resolve()
    resolved_worktree = worktree.resolve()
    if resolved_policy.is_relative_to(resolved_worktree):
        raise InvalidInvocationError(
            f"policy path {resolved_policy} is inside the reviewed worktree "
            f"{resolved_worktree}; Review Policy and Compute Policy must come from "
            "a trusted location outside the repository under review"
        )


def _resolve_policy_path(
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
        "at a trusted policy file outside the reviewed repository"
    )


async def prepare_cli_review(
    *,
    repository: Path,
    target_ref: str,
    proposed_ref: str,
    policy_path: Path | None,
    compute_policy_path: Path | None,
) -> PreparedCliReview:
    await require_git_version()
    root = await repository_root(repository)
    if not await worktree_is_clean(root):
        raise InvalidInvocationError(
            f"worktree {root} is dirty; the first-stage CLI only reviews committed Git objects"
        )

    review_path = _resolve_policy_path(
        policy_path, filename=REVIEW_POLICY_FILENAME, flag="--policy"
    )
    compute_path = _resolve_policy_path(
        compute_policy_path,
        filename=COMPUTE_POLICY_FILENAME,
        flag="--compute-policy",
    )
    assert_policy_outside_worktree(review_path, root)
    assert_policy_outside_worktree(compute_path, root)
    if not review_path.is_file():
        raise InvalidInvocationError(f"review policy file not found: {review_path}")
    if not compute_path.is_file():
        raise InvalidInvocationError(f"compute policy file not found: {compute_path}")

    review_policy, review_version = load_review_policy(review_path)
    compute_policy, compute_version = load_compute_policy(compute_path)
    target_head_oid = await resolve_commit(target_ref, root)
    proposed_head_oid = await resolve_commit(proposed_ref, root)

    return PreparedCliReview(
        resolved=ResolvedCommitPair(
            source_repository=str(root),
            target_ref=target_ref,
            target_head_oid=target_head_oid,
            proposed_ref=proposed_ref,
            proposed_head_oid=proposed_head_oid,
        ),
        review_policy=review_policy,
        review_policy_version=review_version,
        review_policy_path=review_path.resolve(),
        compute_policy=compute_policy,
        compute_policy_version=compute_version,
        compute_policy_path=compute_path.resolve(),
    )
