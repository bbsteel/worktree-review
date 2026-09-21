"""Durable GitHub worker isolates per-Attempt failures and never busy-loops."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.core.identity import PolicyVersionIdentity, ReviewRequestKey
from worktree_review.platform.github.durable import DurableGitHubAttemptWorker
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot
from worktree_review.server.state import (
    GitHubChangeRequestLocator,
    PublishDisposition,
    PublishResult,
)


def _snapshot(attempt_id: str) -> AttemptExecutionSnapshot:
    return AttemptExecutionSnapshot(
        attempt_id=attempt_id,
        change_request=GitHubChangeRequestLocator(
            installation_id=7, repository="octo/example", pull_request_number=42
        ),
        request_key=ReviewRequestKey(
            source_repository="octo/example",
            target_ref="main",
            target_head_oid="a" * 40,
            proposed_head_oid="b" * 40,
            review_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="d" * 64),
        ),
        proposed_ref="HEAD",
        review_policy_semver="1.0.0",
        review_policy_sha256="d" * 64,
        compute_policy_semver="1.0.0",
        compute_policy_sha256="e" * 64,
    )


class _QueueStore:
    def __init__(self, snapshots: list[AttemptExecutionSnapshot]) -> None:
        self.snapshots = snapshots
        self.completed: set[str] = set()

    async def list_recoverable_queued(self) -> tuple[AttemptExecutionSnapshot, ...]:
        return tuple(item for item in self.snapshots if item.attempt_id not in self.completed)

    async def publication_status(self, attempt_id: str) -> PublicationStatus | None:
        if attempt_id in self.completed:
            return PublicationStatus.PUBLISHED
        return None


class _ScriptedReviewWorker:
    def __init__(self, *, fail: set[str], unclaimable: set[str]) -> None:
        self.calls: list[str] = []
        self._fail = fail
        self._unclaimable = unclaimable

    async def execute_claimed_attempt(self, attempt_id: str) -> object | None:
        self.calls.append(attempt_id)
        if attempt_id in self._fail:
            raise RuntimeError(f"pipeline exploded for {attempt_id}")
        if attempt_id in self._unclaimable:
            return None
        return object()


class _RecordingPublisher:
    def __init__(self, store: _QueueStore) -> None:
        self.store = store
        self.published: list[str] = []

    async def publish_terminal(self, *, attempt_id: str, report: object) -> PublishResult:
        del report
        self.published.append(attempt_id)
        self.store.completed.add(attempt_id)
        return PublishResult(
            disposition=PublishDisposition.PUBLISHED,
            attempt_id=attempt_id,
            detail="published",
        )

    async def retry_outbox(self, attempt_id: str, report: object) -> PublishResult:
        del attempt_id, report
        raise AssertionError("retry_outbox should not run in these fixtures")


def _worker(
    store: _QueueStore,
    review: _ScriptedReviewWorker,
    publisher: _RecordingPublisher,
    sleep: Any,
) -> DurableGitHubAttemptWorker:
    return DurableGitHubAttemptWorker(
        github_store=store,  # type: ignore[arg-type]
        review_worker=review,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        idle_seconds=0.01,
        sleep=sleep,
    )


@pytest.mark.asyncio
async def test_pipeline_exception_does_not_stop_later_attempts() -> None:
    store = _QueueStore([_snapshot("bad"), _snapshot("good")])
    review = _ScriptedReviewWorker(fail={"bad"}, unclaimable=set())
    publisher = _RecordingPublisher(store)
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if "good" in publisher.published:
            raise asyncio.CancelledError

    worker = _worker(store, review, publisher, sleep)
    with pytest.raises(asyncio.CancelledError):
        await worker.run_forever()

    assert review.calls[0] == "bad"
    assert "good" in review.calls
    assert publisher.published == ["good"]
    assert sleeps
    assert all(item == 0.01 for item in sleeps)


@pytest.mark.asyncio
async def test_unclaimable_attempt_sleeps_then_later_attempt_still_runs() -> None:
    stuck = _snapshot("stuck")
    later = _snapshot("later")
    store = _QueueStore([stuck])
    review = _ScriptedReviewWorker(fail=set(), unclaimable={"stuck"})
    publisher = _RecordingPublisher(store)
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 3:
            store.snapshots.append(later)
        if "later" in publisher.published:
            raise asyncio.CancelledError
        if len(sleeps) > 50:
            raise AssertionError("busy loop: too many cycles without completing later work")

    worker = _worker(store, review, publisher, sleep)
    with pytest.raises(asyncio.CancelledError):
        await worker.run_forever()

    stuck_calls = [item for item in review.calls if item == "stuck"]
    assert stuck_calls
    assert len(sleeps) >= len(stuck_calls)
    assert "later" in review.calls
    assert publisher.published == ["later"]
    assert all(item == 0.01 for item in sleeps)


async def _seed_queued_sync_intent(state, attempt_id: str = "11111111-2222-3333-4444-555555555555"):  # type: ignore[no-untyped-def]
    """Seed one queued standing sync intent through the real bypass path."""

    from worktree_review.core.identity import MergeCandidateIdentity, ReviewIdentity
    from worktree_review.core.report import GateState

    identity = ReviewIdentity(
        candidate=MergeCandidateIdentity(
            source_repository="octo/example",
            target_ref="main",
            target_head_oid="a" * 40,
            proposed_head_oid="b" * 40,
            merge_tree_oid="c" * 40,
        ),
        review_policy_version=_snapshot(attempt_id).request_key.review_policy_version,
    )
    locator = _snapshot(attempt_id).change_request
    lease = await state.start_authoritative_attempt(
        change_request=locator, request_key=_snapshot(attempt_id).request_key
    )
    await state.record_review_identity(attempt_id=lease.attempt_id, review_identity=identity)
    await state.claim_attempt_job(lease.attempt_id)
    await state.publish_if_authoritative(
        attempt_id=lease.attempt_id,
        request_key=_snapshot(attempt_id).request_key,
        review_identity=identity,
        gate_state=GateState.BLOCKED,
    )
    await state.apply_finding_bypass(
        change_request=locator,
        attempt_id=lease.attempt_id,
        finding_fingerprint="fp-1",
        actor_id=1,
        actor_login="octocat",
        reason="accepted",
        review_identity=identity,
        review_policy_sha256="d" * 64,
        blocking_fingerprints=("fp-1",),
        risk_snapshot={},
        risk_digest="d" * 64,
        check_run_id=123,
    )
    intent = await state.latest_standing_check_sync(attempt_id=lease.attempt_id)
    assert intent is not None
    return lease.attempt_id, intent


@pytest.mark.asyncio
async def test_standing_sync_unexpected_error_backs_off_instead_of_hot_loop() -> None:
    """A non-GitHubApiError delivery failure (audit write, parse error, ...)
    must requeue with a future retry time — never an immediate reclaim loop."""

    from datetime import UTC, datetime

    from worktree_review.platform.github.persistence import InMemoryGitHubReviewStore
    from worktree_review.server.state import (
        CheckSyncStatus,
        InMemoryAuthoritativeAttemptStore,
    )

    state = InMemoryAuthoritativeAttemptStore()
    store = InMemoryGitHubReviewStore()
    _seeded_attempt_id, seeded = await _seed_queued_sync_intent(state)

    class _ExplodingPublisher:
        async def deliver_standing_check_sync(self, intent: object) -> None:
            raise RuntimeError("audit store exploded")

    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    worker = DurableGitHubAttemptWorker(
        github_store=store,  # type: ignore[arg-type]
        review_worker=_ScriptedReviewWorker(fail=set(), unclaimable=set()),  # type: ignore[arg-type]
        publisher=_ExplodingPublisher(),  # type: ignore[arg-type]
        state=state,
        idle_seconds=0.01,
        sleep=_sleep,
    )
    await worker._sync_standing_checks()
    latest = await state.latest_standing_check_sync(attempt_id=seeded.attempt_id)
    assert latest is not None
    assert latest.status is CheckSyncStatus.QUEUED
    # The retry is scheduled in the future: an immediate second pass finds
    # nothing claimable, so the loop exits instead of spinning.
    assert latest.next_retry_at is not None
    assert latest.next_retry_at > datetime.now(UTC)
    await worker._sync_standing_checks()
    later = await state.latest_standing_check_sync(attempt_id=seeded.attempt_id)
    assert later is not None
    assert later.attempt_count == latest.attempt_count  # not reclaimed instantly


@pytest.mark.asyncio
async def test_standing_sync_unexpected_error_exhausts_to_failed() -> None:
    from datetime import UTC, datetime

    from worktree_review.platform.github.persistence import (
        MAX_PUBLICATION_ATTEMPTS,
        InMemoryGitHubReviewStore,
    )
    from worktree_review.server.state import (
        CheckSyncStatus,
        InMemoryAuthoritativeAttemptStore,
        StandingCheckSyncIntent,
    )

    state = InMemoryAuthoritativeAttemptStore()
    store = InMemoryGitHubReviewStore()
    seeded_attempt_id, seeded = await _seed_queued_sync_intent(state)
    snapshot = _snapshot(seeded_attempt_id)
    await store.save_execution_snapshot(snapshot)
    now = datetime.now(UTC)
    exhausted_intent = StandingCheckSyncIntent(
        intent_id=seeded.intent_id,
        attempt_id=seeded_attempt_id,
        standing_revision=3,
        check_run_id=123,
        intent="standing_check_sync",
        status=CheckSyncStatus.IN_PROGRESS,
        attempt_count=MAX_PUBLICATION_ATTEMPTS,
        payload={},
        created_at=now,
        updated_at=now,
    )

    class _ExplodingPublisher:
        async def deliver_standing_check_sync(self, intent: object) -> None:
            raise RuntimeError("parse exploded")

    worker = DurableGitHubAttemptWorker(
        github_store=store,  # type: ignore[arg-type]
        review_worker=_ScriptedReviewWorker(fail=set(), unclaimable=set()),  # type: ignore[arg-type]
        publisher=_ExplodingPublisher(),  # type: ignore[arg-type]
        state=state,
        idle_seconds=0.01,
    )
    await worker._release_failed_sync(exhausted_intent)
    latest = await state.latest_standing_check_sync(attempt_id=seeded_attempt_id)
    assert latest is not None
    assert latest.status is CheckSyncStatus.FAILED
    events = await state.audit_events()
    assert any(event["event_type"] == "check_sync_failed" for event in events)


@pytest.mark.asyncio
async def test_standing_sync_runs_even_with_pending_review_jobs() -> None:
    """Fairness: steady review traffic must not starve the standing sync."""

    store = _QueueStore([_snapshot("busy-attempt")])
    sync_calls: list[int] = []
    worker = _worker(
        store,
        _ScriptedReviewWorker(fail=set(), unclaimable=set()),
        _RecordingPublisher(store),
        None,
    )

    class _CancelAfterFirstPass:
        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, seconds: float) -> None:
            self.calls += 1
            if self.calls >= 2:
                raise asyncio.CancelledError

    sleeper = _CancelAfterFirstPass()
    worker._sleep = sleeper  # type: ignore[method-assign]

    async def _record_sync() -> None:
        sync_calls.append(1)

    worker._sync_standing_checks = _record_sync  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        await worker.run_forever()
    assert sync_calls  # ran before the first sleep, despite the pending job
