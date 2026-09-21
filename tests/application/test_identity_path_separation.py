from __future__ import annotations

from pathlib import Path

import pytest

from tests.gitutil import head_oid
from worktree_review.application.review_service import ReviewApplicationService
from worktree_review.core.candidate import construct_merge_candidate
from worktree_review.core.identity import ResolvedCommitPair
from worktree_review.core.pipeline import ReviewRequest
from worktree_review.core.policy import load_compute_policy, load_review_policy
from worktree_review.core.provider import ScriptedProvider
from worktree_review.core.report import GateState

CANONICAL_IDENTITY = "acme/payment-service"


def _resolved(git_repository: Path, oid: str) -> ResolvedCommitPair:
    return ResolvedCommitPair(
        source_repository=CANONICAL_IDENTITY,
        target_ref="main",
        target_head_oid=oid,
        proposed_ref="HEAD",
        proposed_head_oid=oid,
    )


@pytest.mark.asyncio
async def test_merge_uses_repository_path_not_identity_string(git_repository: Path) -> None:
    oid = head_oid(git_repository)
    candidate = await construct_merge_candidate(
        _resolved(git_repository, oid),
        repository_path=git_repository,
    )
    assert candidate.source_repository == CANONICAL_IDENTITY
    assert candidate.merge_tree_oid
    assert CANONICAL_IDENTITY == "acme/payment-service"


@pytest.mark.asyncio
async def test_application_service_keeps_attempt_id_and_canonical_identity(
    git_repository: Path, policy_dir: Path
) -> None:
    oid = head_oid(git_repository)
    review_policy, review_version = load_review_policy(policy_dir / "review-policy.yaml")
    compute_policy, compute_version = load_compute_policy(policy_dir / "compute-policy.yaml")
    service = ReviewApplicationService()
    attempt_id = service.allocate_attempt_id()
    report = await service.execute(
        ReviewRequest(
            resolved=_resolved(git_repository, oid),
            review_policy=review_policy,
            review_policy_version=review_version,
            compute_policy=compute_policy,
            compute_policy_version=compute_version,
            surface="cli",
        ),
        repository_path=git_repository,
        attempt_id=attempt_id,
        provider=ScriptedProvider(payloads={"correctness": {"findings": []}}),
    )
    assert report.attempt_id == attempt_id
    assert report.request_key.source_repository == CANONICAL_IDENTITY
    assert report.resolved.source_repository == CANONICAL_IDENTITY
    assert report.gate_state is GateState.PASSED
    assert report.review_identity is not None
    assert report.review_identity.candidate.source_repository == CANONICAL_IDENTITY


@pytest.mark.asyncio
async def test_service_allocates_attempt_id_when_caller_omits_it(
    git_repository: Path, policy_dir: Path
) -> None:
    oid = head_oid(git_repository)
    review_policy, review_version = load_review_policy(policy_dir / "review-policy.yaml")
    compute_policy, compute_version = load_compute_policy(policy_dir / "compute-policy.yaml")
    report = await ReviewApplicationService().execute(
        ReviewRequest(
            resolved=_resolved(git_repository, oid),
            review_policy=review_policy,
            review_policy_version=review_version,
            compute_policy=compute_policy,
            compute_policy_version=compute_version,
            surface="web",
        ),
        repository_path=git_repository,
        provider=ScriptedProvider(payloads={"correctness": {"findings": []}}),
    )
    assert report.attempt_id
    assert report.request_key.source_repository == CANONICAL_IDENTITY
