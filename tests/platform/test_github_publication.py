from __future__ import annotations

import pytest

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.core.identity import (
    MergeCandidateIdentity,
    PolicyVersionIdentity,
    ResolvedCommitPair,
    ReviewIdentity,
    ReviewRequestKey,
)
from worktree_review.core.report import (
    ComputePolicyDisclosure,
    ExecutionRecord,
    GateState,
    ReviewReport,
)
from worktree_review.platform.github.checks import CheckRunPayload
from worktree_review.platform.github.persistence import InMemoryGitHubReviewStore
from worktree_review.platform.github.publication import GitHubCheckPublisher
from worktree_review.platform.github.runtime import GitHubApiError
from worktree_review.server.state import (
    GitHubChangeRequestLocator,
    InMemoryAuthoritativeAttemptStore,
    PublishDisposition,
)


class _FakeChecks:
    def __init__(self) -> None:
        self.updates: list[int] = []
        self.fail_next = False

    async def create_check_run(self, *, repository: str, payload: CheckRunPayload) -> int:
        del repository, payload
        return 1

    async def update_check_run(
        self, *, repository: str, check_run_id: int, payload: CheckRunPayload
    ) -> None:
        del repository, payload
        if self.fail_next:
            self.fail_next = False
            raise GitHubApiError("GitHub 502")
        self.updates.append(check_run_id)


def _report(attempt_id: str, request_key: ReviewRequestKey) -> ReviewReport:
    resolved = ResolvedCommitPair(
        source_repository=request_key.source_repository,
        target_ref=request_key.target_ref,
        target_head_oid=request_key.target_head_oid,
        proposed_ref="feature",
        proposed_head_oid=request_key.proposed_head_oid,
    )
    identity = ReviewIdentity(
        candidate=MergeCandidateIdentity(
            source_repository=resolved.source_repository,
            target_ref=resolved.target_ref,
            target_head_oid=resolved.target_head_oid,
            proposed_head_oid=resolved.proposed_head_oid,
            merge_tree_oid="c" * 40,
        ),
        review_policy_version=request_key.review_policy_version,
    )
    return ReviewReport(
        gate_state=GateState.PASSED,
        attempt_id=attempt_id,
        request_key=request_key,
        resolved=resolved,
        merge_tree_oid="c" * 40,
        review_identity=identity,
        review_policy_version=request_key.review_policy_version,
        compute_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="e" * 64),
        compute_policy_disclosure=ComputePolicyDisclosure(
            provider="anthropic",
            model="claude",
            data_destination="https://api.anthropic.com",
            known_retention="none",
        ),
        execution=ExecutionRecord(),
        summary="ok",
        error_detail=None,
    )


@pytest.mark.asyncio
async def test_terminal_update_retries_same_check_and_does_not_rewrite_gate() -> None:
    state = InMemoryAuthoritativeAttemptStore()
    store = InMemoryGitHubReviewStore()
    locator = GitHubChangeRequestLocator(
        installation_id=7, repository="octo/example", pull_request_number=42
    )
    request_key = ReviewRequestKey(
        source_repository="octo/example",
        target_ref="main",
        target_head_oid="a" * 40,
        proposed_head_oid="b" * 40,
        review_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="d" * 64),
    )
    lease = await state.start_authoritative_attempt(change_request=locator, request_key=request_key)
    report = _report(lease.attempt_id, request_key)
    await state.record_review_identity(
        attempt_id=lease.attempt_id, review_identity=report.review_identity
    )
    await state.claim_attempt_job(lease.attempt_id)
    await store.set_check_run_id(lease.attempt_id, 99)
    checks = _FakeChecks()
    checks.fail_next = True
    publisher = GitHubCheckPublisher(state=state, github_store=store, checks=checks)
    first = await publisher.publish_terminal(attempt_id=lease.attempt_id, report=report)
    assert first.disposition is PublishDisposition.PUBLISHED
    assert first.gate_state is GateState.PASSED
    assert await store.publication_status(lease.attempt_id) is PublicationStatus.FAILED
    assert checks.updates == []
    retry = await publisher.retry_outbox(lease.attempt_id, report)
    assert retry.disposition is PublishDisposition.PUBLISHED
    assert checks.updates == [99]
    assert await store.publication_status(lease.attempt_id) is PublicationStatus.PUBLISHED
    again = await publisher.retry_outbox(lease.attempt_id, report)
    assert again.disposition is PublishDisposition.PUBLISHED
    assert checks.updates == [99]


@pytest.mark.asyncio
async def test_late_superseded_attempt_cannot_replace_standing_check() -> None:
    state = InMemoryAuthoritativeAttemptStore()
    store = InMemoryGitHubReviewStore()
    locator = GitHubChangeRequestLocator(
        installation_id=7, repository="octo/example", pull_request_number=42
    )
    request_key = ReviewRequestKey(
        source_repository="octo/example",
        target_ref="main",
        target_head_oid="a" * 40,
        proposed_head_oid="b" * 40,
        review_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="d" * 64),
    )
    older = await state.start_authoritative_attempt(change_request=locator, request_key=request_key)
    report = _report(older.attempt_id, request_key)
    await state.record_review_identity(
        attempt_id=older.attempt_id, review_identity=report.review_identity
    )
    await state.claim_attempt_job(older.attempt_id)
    await store.set_check_run_id(older.attempt_id, 11)
    newer = await state.start_authoritative_attempt(change_request=locator, request_key=request_key)
    checks = _FakeChecks()
    publisher = GitHubCheckPublisher(state=state, github_store=store, checks=checks)
    result = await publisher.publish_terminal(attempt_id=older.attempt_id, report=report)
    assert result.disposition is PublishDisposition.SUPERSEDED
    current = await state.get_change_request_state(locator)
    assert current.authoritative_attempt_id == newer.attempt_id
    assert current.standing_attempt_id is None
    assert checks.updates == [11]
