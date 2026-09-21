from __future__ import annotations

from pathlib import Path

import pytest

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
from worktree_review.platform.github.retry import (
    GitHubRetryCoordinator,
    RetryRequest,
    RetryResolution,
)
from worktree_review.platform.github.triggers import QueuedAttemptPreparer
from worktree_review.server.state import (
    AttemptLease,
    GitHubChangeRequestLocator,
    InMemoryAuthoritativeAttemptStore,
    PublishDisposition,
)


class _AllowAll:
    async def may_retry(self, *, change_request: object, actor: str) -> bool:
        del change_request, actor
        return True


class _Resolver:
    def __init__(self, request_key: ReviewRequestKey) -> None:
        self.request_key = request_key

    async def resolve_current_request(
        self, change_request: GitHubChangeRequestLocator
    ) -> RetryResolution:
        del change_request
        return RetryResolution(request_key=self.request_key)


class _FakeChecks:
    def __init__(self) -> None:
        self.created: list[int] = []
        self.updated: list[int] = []
        self._next = 20

    async def create_check_run(self, *, repository: str, payload: CheckRunPayload) -> int:
        del repository, payload
        self._next += 1
        self.created.append(self._next)
        return self._next

    async def update_check_run(
        self, *, repository: str, check_run_id: int, payload: CheckRunPayload
    ) -> None:
        del repository, payload
        self.updated.append(check_run_id)


def _request_key() -> ReviewRequestKey:
    return ReviewRequestKey(
        source_repository="octo/example",
        target_ref="main",
        target_head_oid="a" * 40,
        proposed_head_oid="b" * 40,
        review_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="d" * 64),
    )


def _report(attempt_id: str, request_key: ReviewRequestKey) -> ReviewReport:
    identity = ReviewIdentity(
        candidate=MergeCandidateIdentity(
            source_repository=request_key.source_repository,
            target_ref=request_key.target_ref,
            target_head_oid=request_key.target_head_oid,
            proposed_head_oid=request_key.proposed_head_oid,
            merge_tree_oid="c" * 40,
        ),
        review_policy_version=request_key.review_policy_version,
    )
    return ReviewReport(
        gate_state=GateState.BLOCKED,
        attempt_id=attempt_id,
        request_key=request_key,
        resolved=ResolvedCommitPair(
            source_repository=request_key.source_repository,
            target_ref=request_key.target_ref,
            target_head_oid=request_key.target_head_oid,
            proposed_ref="feature",
            proposed_head_oid=request_key.proposed_head_oid,
        ),
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
        summary="blocked",
        error_detail=None,
    )


@pytest.mark.asyncio
async def test_authorized_retry_supersedes_old_attempt_and_late_result(
    policy_dir: Path,
) -> None:
    state = InMemoryAuthoritativeAttemptStore()
    store = InMemoryGitHubReviewStore()
    checks = _FakeChecks()
    locator = GitHubChangeRequestLocator(
        installation_id=7, repository="octo/example", pull_request_number=42
    )
    request_key = _request_key()
    older = await state.start_authoritative_attempt(change_request=locator, request_key=request_key)
    report = _report(older.attempt_id, request_key)
    await state.record_review_identity(
        attempt_id=older.attempt_id, review_identity=report.review_identity
    )
    await state.claim_attempt_job(older.attempt_id)
    await store.set_check_run_id(older.attempt_id, 11)

    queued: list[str] = []

    async def _enqueue(lease: AttemptLease) -> None:
        queued.append(lease.attempt_id)

    coordinator = GitHubRetryCoordinator(
        state=state,
        authorizer=_AllowAll(),
        resolver=_Resolver(request_key),
        enqueue_attempt=_enqueue,
        prepare_queued_attempt=QueuedAttemptPreparer(
            github_store=store,
            checks=checks,
            review_policy_path=policy_dir / "review-policy.yaml",
            compute_policy_path=policy_dir / "compute-policy.yaml",
        ),
    )
    accepted = await coordinator.request_retry(
        RetryRequest(
            change_request=locator,
            actor="maintainer",
            reason="GitHub Checks requested action",
            prior_attempt_id=older.attempt_id,
            delivery_id="retry-1",
        )
    )
    assert accepted.lease.attempt_id != older.attempt_id
    assert queued == [accepted.lease.attempt_id]
    assert await store.get_check_run_id(accepted.lease.attempt_id) == 21
    current = await state.get_change_request_state(locator)
    assert current.authoritative_attempt_id == accepted.lease.attempt_id
    assert current.standing_attempt_id is None
    events = await state.audit_events()
    assert any(event["event_type"] == "retry_authorized" for event in events)
    assert any(event["event_type"] == "attempt_authoritative" for event in events)

    publisher = GitHubCheckPublisher(state=state, github_store=store, checks=checks)
    late = await publisher.publish_terminal(attempt_id=older.attempt_id, report=report)
    assert late.disposition is PublishDisposition.SUPERSEDED
    current = await state.get_change_request_state(locator)
    assert current.authoritative_attempt_id == accepted.lease.attempt_id
    assert current.standing_attempt_id is None
    assert checks.updated == [11]
    replay = await coordinator.request_retry(
        RetryRequest(
            change_request=locator,
            actor="maintainer",
            reason="GitHub Checks requested action",
            prior_attempt_id=older.attempt_id,
            delivery_id="retry-1",
        )
    )
    assert replay.replayed is True
    assert replay.lease.attempt_id == accepted.lease.attempt_id
    assert len(checks.created) == 1
