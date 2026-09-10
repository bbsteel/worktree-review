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
