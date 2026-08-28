from __future__ import annotations

import pytest

from worktree_review.core.identity import (
    MergeCandidateIdentity,
    PolicyVersionIdentity,
    ReviewIdentity,
    ReviewRequestKey,
)
from worktree_review.core.report import GateState
from worktree_review.platform.github.retry import (
    GitHubRetryCoordinator,
    RetryAuthorizationError,
    RetryRequest,
    RetryResolution,
)
from worktree_review.server.state import (
    AttemptLease,
    GitHubChangeRequestLocator,
    InMemoryAuthoritativeAttemptStore,
    JobStatus,
    PublishDisposition,
    StateConflictError,
)


def _change_request() -> GitHubChangeRequestLocator:
    return GitHubChangeRequestLocator(
        installation_id=7,
        repository="octo/example",
        pull_request_number=42,
    )


def _request_key(*, proposed_head_oid: str = "b" * 40) -> ReviewRequestKey:
    return ReviewRequestKey(
        source_repository="octo/example",
        target_ref="refs/heads/main",
        target_head_oid="a" * 40,
        proposed_head_oid=proposed_head_oid,
        review_policy_version=PolicyVersionIdentity(
            semver="1.0.0",
            sha256="d" * 64,
        ),
    )


def _review_identity(request_key: ReviewRequestKey) -> ReviewIdentity:
    return ReviewIdentity(
        candidate=MergeCandidateIdentity(
            source_repository=request_key.source_repository,
            target_ref=request_key.target_ref,
            target_head_oid=request_key.target_head_oid,
            proposed_head_oid=request_key.proposed_head_oid,
            merge_tree_oid="c" * 40,
        ),
        review_policy_version=request_key.review_policy_version,
    )


@pytest.mark.asyncio
async def test_older_same_identity_attempt_cannot_publish_after_newer_attempt() -> None:
    state = InMemoryAuthoritativeAttemptStore()
    change_request = _change_request()
    request_key = _request_key()
    identity = _review_identity(request_key)

    older_attempt = await state.start_authoritative_attempt(
        change_request=change_request,
        request_key=request_key,
    )
    await state.record_review_identity(
        attempt_id=older_attempt.attempt_id,
        review_identity=identity,
    )
    assert await state.claim_attempt_job(older_attempt.attempt_id) == older_attempt

    newer_attempt = await state.start_authoritative_attempt(
        change_request=change_request,
        request_key=request_key,
        expected_authoritative_attempt_id=older_attempt.attempt_id,
    )
    assert newer_attempt.prior_authoritative_attempt_id == older_attempt.attempt_id
    # An in-flight job may finish, but it is no longer eligible to publish.
    assert await state.job_status(older_attempt.attempt_id) is JobStatus.RUNNING
    await state.record_review_identity(
        attempt_id=newer_attempt.attempt_id,
        review_identity=identity,
    )
    claimed_newer_attempt = await state.claim_attempt_job(newer_attempt.attempt_id)
    assert claimed_newer_attempt is not None
    assert claimed_newer_attempt.attempt_id == newer_attempt.attempt_id
    assert claimed_newer_attempt.request_key == newer_attempt.request_key

    newer_result = await state.publish_if_authoritative(
        attempt_id=newer_attempt.attempt_id,
        request_key=request_key,
        review_identity=identity,
        gate_state=GateState.PASSED,
    )
    older_result = await state.publish_if_authoritative(
        attempt_id=older_attempt.attempt_id,
        request_key=request_key,
        review_identity=identity,
        gate_state=GateState.BLOCKED,
    )

    assert newer_result.disposition is PublishDisposition.PUBLISHED
    assert older_result.disposition is PublishDisposition.SUPERSEDED
    standing_state = await state.get_change_request_state(change_request)
    assert standing_state.authoritative_attempt_id == newer_attempt.attempt_id
    assert standing_state.standing_attempt_id == newer_attempt.attempt_id
    assert standing_state.standing_gate_state is GateState.PASSED
    assert any(
        event["event_type"] == "attempt_publish_superseded"
        and event["attempt_id"] == older_attempt.attempt_id
        for event in await state.audit_events()
    )


class _StaticRetryAuthorizer:
    def __init__(self, authorized: bool) -> None:
        self.authorized = authorized

    async def may_retry(
        self,
        *,
        change_request: GitHubChangeRequestLocator,
        actor: str,
    ) -> bool:
        return self.authorized


class _StaticRetryResolver:
    def __init__(self, request_key: ReviewRequestKey) -> None:
        self.request_key = request_key
        self.calls = 0

    async def resolve_current_request(
        self,
        change_request: GitHubChangeRequestLocator,
    ) -> RetryResolution:
        self.calls += 1
        return RetryResolution(request_key=self.request_key)


@pytest.mark.asyncio
async def test_authorized_retry_creates_new_attempt_and_enqueues_it() -> None:
    state = InMemoryAuthoritativeAttemptStore()
    change_request = _change_request()
    request_key = _request_key()
    initial_attempt = await state.start_authoritative_attempt(
        change_request=change_request,
        request_key=request_key,
    )
    enqueued_attempts: list[AttemptLease] = []

    async def record_enqueue(attempt: AttemptLease) -> None:
        enqueued_attempts.append(attempt)

    resolver = _StaticRetryResolver(request_key)
    coordinator = GitHubRetryCoordinator(
        state=state,
        authorizer=_StaticRetryAuthorizer(authorized=True),
        resolver=resolver,
        enqueue_attempt=record_enqueue,
    )

    accepted = await coordinator.request_retry(
        RetryRequest(
            change_request=change_request,
            actor="maintainer",
            reason="re-run after transient provider error",
            prior_attempt_id=initial_attempt.attempt_id,
        )
    )

    assert accepted.lease.attempt_id != initial_attempt.attempt_id
    assert accepted.lease.prior_authoritative_attempt_id == initial_attempt.attempt_id
    assert enqueued_attempts == [accepted.lease]
    assert resolver.calls == 1
    current_state = await state.get_change_request_state(change_request)
    assert current_state.authoritative_attempt_id == accepted.lease.attempt_id
    assert current_state.standing_gate_state is None
    assert any(
        event["event_type"] == "retry_authorized"
        and event["attempt_id"] == accepted.lease.attempt_id
        for event in await state.audit_events()
    )


@pytest.mark.asyncio
async def test_unauthorized_retry_does_not_replace_authoritative_attempt() -> None:
    state = InMemoryAuthoritativeAttemptStore()
    change_request = _change_request()
    initial_attempt = await state.start_authoritative_attempt(
        change_request=change_request,
        request_key=_request_key(),
    )
    resolver = _StaticRetryResolver(_request_key())
    coordinator = GitHubRetryCoordinator(
        state=state,
        authorizer=_StaticRetryAuthorizer(authorized=False),
        resolver=resolver,
    )

    with pytest.raises(RetryAuthorizationError):
        await coordinator.request_retry(
            RetryRequest(
                change_request=change_request,
                actor="contributor",
                reason="please retry",
                prior_attempt_id=initial_attempt.attempt_id,
            )
        )

    current_state = await state.get_change_request_state(change_request)
    assert current_state.authoritative_attempt_id == initial_attempt.attempt_id
    assert resolver.calls == 0
    assert any(event["event_type"] == "retry_denied" for event in await state.audit_events())


@pytest.mark.asyncio
async def test_retry_with_stale_prior_attempt_fails_before_resolution() -> None:
    state = InMemoryAuthoritativeAttemptStore()
    change_request = _change_request()
    request_key = _request_key()
    older_attempt = await state.start_authoritative_attempt(
        change_request=change_request,
        request_key=request_key,
    )
    current_attempt = await state.start_authoritative_attempt(
        change_request=change_request,
        request_key=request_key,
        expected_authoritative_attempt_id=older_attempt.attempt_id,
    )
    resolver = _StaticRetryResolver(request_key)
    coordinator = GitHubRetryCoordinator(
        state=state,
        authorizer=_StaticRetryAuthorizer(authorized=True),
        resolver=resolver,
    )

    with pytest.raises(StateConflictError, match="no longer authoritative"):
        await coordinator.request_retry(
            RetryRequest(
                change_request=change_request,
                actor="maintainer",
                reason="stale browser tab",
                prior_attempt_id=older_attempt.attempt_id,
            )
        )

    assert resolver.calls == 0
    current_state = await state.get_change_request_state(change_request)
    assert current_state.authoritative_attempt_id == current_attempt.attempt_id
