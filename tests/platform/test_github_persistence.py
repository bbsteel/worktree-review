from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.application.review_events import ReviewEvent
from worktree_review.core.identity import PolicyVersionIdentity, ReviewRequestKey
from worktree_review.platform.github.persistence import (
    PUBLICATION_BACKOFF_CAP_SECONDS,
    InMemoryGitHubReviewStore,
    PostgresGitHubReviewStore,
    assert_snapshot_is_writable,
    publication_is_claimable,
)
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot, PublicationIntent
from worktree_review.server.state import GitHubChangeRequestLocator, StateConflictError


def _snapshot(attempt_id: str = "a1") -> AttemptExecutionSnapshot:
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
        proposed_ref="feature",
        review_policy_semver="1.0.0",
        review_policy_sha256="d" * 64,
        compute_policy_semver="1.0.0",
        compute_policy_sha256="e" * 64,
        provider_profile_id="profile-1",
        delivery_id="delivery-1",
    )


def _event(attempt_id: str, sequence: int) -> ReviewEvent:
    return ReviewEvent(
        sequence=sequence,
        occurred_at=datetime.now(UTC),
        attempt_id=attempt_id,
        surface="github",
        event_type="attempt.created",
        payload={"source": "github-pull-request"},
    )


@pytest.mark.asyncio
async def test_snapshot_and_queued_check_are_recoverable_before_result() -> None:
    store = InMemoryGitHubReviewStore()
    snapshot = _snapshot()
    await store.save_execution_snapshot(snapshot)
    await store.set_check_run_id("a1", 99)
    recovered = await store.list_recoverable_queued()
    assert recovered == (snapshot,)
    assert await store.get_check_run_id("a1") == 99
    dumped = snapshot.as_public_dict()
    assert "token" not in dumped
    assert "credential" not in dumped


@pytest.mark.asyncio
async def test_publication_failure_can_retry_same_check_without_republishing() -> None:
    now = datetime.now(UTC)

    def _clock() -> datetime:
        return now

    store = InMemoryGitHubReviewStore(clock=_clock)
    await store.save_execution_snapshot(_snapshot())
    await store.set_check_run_id("a1", 99)
    intent = PublicationIntent(
        attempt_id="a1",
        check_run_id=99,
        intent="terminal-check",
        payload={"check_run_id": 99},
    )
    await store.enqueue_publication(intent)
    claimed = await store.claim_publication("a1")
    assert claimed is not None
    await store.mark_publication("a1", status=PublicationStatus.FAILED, error="GitHub 502")
    # Bounded backoff: an immediate re-claim is not due yet.
    assert await store.claim_publication("a1") is None
    now += timedelta(seconds=PUBLICATION_BACKOFF_CAP_SECONDS + 1)
    retry = await store.claim_publication("a1")
    assert retry is not None
    assert retry.check_run_id == 99
    await store.mark_publication("a1", status=PublicationStatus.PUBLISHED)
    with pytest.raises(StateConflictError, match="already completed"):
        await store.enqueue_publication(intent)
    assert await store.claim_publication("a1") is None


@pytest.mark.asyncio
async def test_in_progress_publication_cannot_be_claimed_twice() -> None:
    store = InMemoryGitHubReviewStore()
    await store.enqueue_publication(
        PublicationIntent(
            attempt_id="a1",
            check_run_id=99,
            intent="terminal-check",
            payload={"check_run_id": 99},
        )
    )
    first = await store.claim_publication("a1")
    second = await store.claim_publication("a1")
    assert first is not None
    assert first.status is PublicationStatus.IN_PROGRESS
    assert second is None


def test_snapshot_write_and_claim_helpers_match_store_policy() -> None:
    original = _snapshot()
    assert_snapshot_is_writable(None, original)
    assert_snapshot_is_writable(original, original)
    with pytest.raises(StateConflictError, match="immutable"):
        assert_snapshot_is_writable(original, _snapshot("a2"))
    assert publication_is_claimable(PublicationStatus.QUEUED) is True
    assert publication_is_claimable(PublicationStatus.FAILED) is True
    assert publication_is_claimable(PublicationStatus.PUBLISHED) is False
    assert publication_is_claimable(PublicationStatus.IN_PROGRESS) is False


@pytest.mark.asyncio
async def test_events_and_results_are_durable_and_results_immutable() -> None:
    store = InMemoryGitHubReviewStore()
    await store.append_review_event(_event("a1", 1))
    await store.append_review_event(_event("a1", 2))
    assert len(await store.list_review_events("a1")) == 2
    await store.save_review_result("a1", '{"gate_state":"Passed"}')
    with pytest.raises(StateConflictError, match="immutable"):
        await store.save_review_result("a1", '{"gate_state":"Blocked"}')
    assert await store.list_recoverable_queued() == ()
    same = await store.record_webhook_idempotency(
        installation_id=7, delivery_id="d1", attempt_id="a1", request_digest="abc"
    )
    again = await store.record_webhook_idempotency(
        installation_id=7, delivery_id="d1", attempt_id="ignored", request_digest="abc"
    )
    assert same == again == "a1"
    with pytest.raises(StateConflictError, match="different request"):
        await store.record_webhook_idempotency(
            installation_id=7, delivery_id="d1", attempt_id="a2", request_digest="other"
        )


class _Txn:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _FakeConnection:
        self._connection.in_transaction = True
        return self._connection

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _FakeConnection:
    def __init__(self) -> None:
        self.in_transaction = False
        self.executes: list[str] = []
        self.attempt_row: dict[str, object] | None = {"execution_snapshot": None}
        self.outbox_row: dict[str, object] | None = None

    def transaction(self) -> _Txn:
        return _Txn(self)

    async def fetchrow(self, sql: str, *_args: object) -> dict[str, object] | None:
        if "FROM review_attempts" in sql:
            return self.attempt_row
        if "FROM publication_outbox" in sql:
            return self.outbox_row
        return None

    async def execute(self, sql: str, *_args: object) -> str:
        self.executes.append(sql)
        return "UPDATE 1"


class _FakePool:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def acquire(self) -> _FakePool:
        return self

    async def __aenter__(self) -> _FakeConnection:
        return self._connection

    async def __aexit__(self, *_exc: object) -> bool:
        return False


@pytest.mark.asyncio
async def test_postgres_store_rejects_conflicting_snapshots_inside_a_transaction() -> None:
    connection = _FakeConnection()
    connection.attempt_row = {"execution_snapshot": _snapshot().model_dump(mode="json")}
    store = PostgresGitHubReviewStore(_FakePool(connection))
    with pytest.raises(StateConflictError, match="immutable"):
        await store.save_execution_snapshot(_snapshot("other"))
    assert connection.in_transaction is True
    assert connection.executes == []


@pytest.mark.asyncio
async def test_postgres_claim_does_not_return_published_intents() -> None:
    connection = _FakeConnection()
    connection.outbox_row = {
        "payload": {
            "attempt_id": "a1",
            "check_run_id": 99,
            "intent": "terminal-check",
            "payload": {},
            "status": "published",
            "last_error": None,
            "attempt_count": 1,
        },
        "status": PublicationStatus.PUBLISHED.value,
        "attempt_count": 1,
        "next_retry_at": None,
        "updated_at": datetime.now(UTC),
    }
    store = PostgresGitHubReviewStore(_FakePool(connection))
    claimed = await store.claim_publication("a1")
    assert claimed is None
    assert connection.in_transaction is True
    assert connection.executes == []


@pytest.mark.asyncio
async def test_postgres_claim_updates_queued_intent_atomically() -> None:
    connection = _FakeConnection()
    connection.outbox_row = {
        "payload": {
            "attempt_id": "a1",
            "check_run_id": 99,
            "intent": "terminal-check",
            "payload": {},
            "status": "queued",
            "last_error": None,
            "attempt_count": 0,
        },
        "status": PublicationStatus.QUEUED.value,
        "attempt_count": 0,
        "next_retry_at": None,
        "updated_at": datetime.now(UTC),
    }
    store = PostgresGitHubReviewStore(_FakePool(connection))
    claimed = await store.claim_publication("a1")
    assert claimed is not None
    assert claimed.check_run_id == 99
    assert connection.in_transaction is True
    assert any("attempt_count = attempt_count + 1" in sql for sql in connection.executes)
