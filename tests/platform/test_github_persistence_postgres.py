"""Real-PostgreSQL coverage for the GitHub persistence and state stores.

These tests exercise the production SQL (JSONB round-trips, outbox backoff,
job lease recovery) against a live database — never an in-memory stand-in.
They skip cleanly when no Docker/embedded Postgres is available.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from tests.platform.postgres_harness import database_url_for_name, open_postgres_url

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.application.review_events import ReviewEvent, utc_now
from worktree_review.core.identity import PolicyVersionIdentity, ReviewRequestKey
from worktree_review.platform.github.persistence import (
    MAX_PUBLICATION_ATTEMPTS,
    PUBLICATION_IN_PROGRESS_LEASE_SECONDS,
    PostgresGitHubReviewStore,
)
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot, PublicationIntent
from worktree_review.server.state import (
    GitHubChangeRequestLocator,
    JobStatus,
    PostgresAuthoritativeAttemptStore,
)


@pytest.fixture(scope="session")
def postgres_base_url() -> Any:
    yield from open_postgres_url()


@pytest.fixture
async def pg_pool(postgres_base_url: str) -> Any:
    asyncpg = pytest.importorskip("asyncpg")

    name = f"wr_persist_{uuid.uuid4().hex[:12]}"
    connection = await asyncpg.connect(postgres_base_url)
    try:
        await connection.execute(f"CREATE DATABASE {name}")
    finally:
        await connection.close()
    pool = await asyncpg.create_pool(database_url_for_name(postgres_base_url, name))
    try:
        yield pool
    finally:
        await pool.close()


_LOCATOR = GitHubChangeRequestLocator(
    installation_id=7, repository="octo/example", pull_request_number=42
)
_REQUEST_KEY = ReviewRequestKey(
    source_repository="octo/example",
    target_ref="main",
    target_head_oid="a" * 40,
    proposed_head_oid="b" * 40,
    review_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="d" * 64),
)


def _snapshot(attempt_id: str) -> AttemptExecutionSnapshot:
    return AttemptExecutionSnapshot(
        attempt_id=attempt_id,
        change_request=_LOCATOR,
        request_key=_REQUEST_KEY,
        proposed_ref="HEAD",
        review_policy_semver="1.0.0",
        review_policy_sha256="d" * 64,
        compute_policy_semver="1.0.0",
        compute_policy_sha256="e" * 64,
    )


def _event(attempt_id: str, sequence: int, event_type: str = "stage.started") -> ReviewEvent:
    return ReviewEvent(
        sequence=sequence,
        occurred_at=utc_now(),
        attempt_id=attempt_id,
        surface="github",
        event_type=event_type,
        payload={"stage": "derive-identity"},
    )


@pytest.mark.asyncio
async def test_postgres_event_result_and_snapshot_round_trip(pg_pool: Any) -> None:
    state = PostgresAuthoritativeAttemptStore(pg_pool)
    await state.initialise()
    store = PostgresGitHubReviewStore(pg_pool)
    await store.initialise()
    lease = await state.start_authoritative_attempt(
        change_request=_LOCATOR, request_key=_REQUEST_KEY
    )
    attempt_id = lease.attempt_id

    await store.save_execution_snapshot(_snapshot(attempt_id))
    loaded = await store.get_execution_snapshot(attempt_id)
    assert loaded is not None
    assert loaded.attempt_id == attempt_id

    for sequence in (1, 2, 3):
        await store.append_review_event(_event(attempt_id, sequence))
    events = await store.list_review_events(attempt_id)
    assert [event.sequence for event in events] == [1, 2, 3]
    assert events[0].payload["stage"] == "derive-identity"

    await store.save_review_result(attempt_id, '{"schema": "worktree-review.cli.result/v1"}')
    assert await store.get_review_result(attempt_id) is not None
    assert (await store.list_recent_attempt_ids())[0] == attempt_id


@pytest.mark.asyncio
async def test_postgres_outbox_backoff_lease_and_bounded_claim(pg_pool: Any) -> None:
    state = PostgresAuthoritativeAttemptStore(pg_pool)
    await state.initialise()
    store = PostgresGitHubReviewStore(pg_pool)
    await store.initialise()
    lease = await state.start_authoritative_attempt(
        change_request=_LOCATOR, request_key=_REQUEST_KEY
    )
    attempt_id = lease.attempt_id
    await store.save_review_result(attempt_id, "{}")
    await store.enqueue_publication(
        PublicationIntent(
            attempt_id=attempt_id, check_run_id=99, intent="terminal-check", payload={}
        )
    )

    # The new intent is due immediately.
    pending = await store.list_pending_publications(datetime.now(UTC))
    assert attempt_id in pending
    claimed = await store.claim_publication(attempt_id)
    assert claimed is not None
    # In-progress: not claimable again until the lease expires.
    assert await store.claim_publication(attempt_id) is None
    async with pg_pool.acquire() as connection:
        await connection.execute(
            "UPDATE publication_outbox SET updated_at = $2 WHERE attempt_id = $1::uuid",
            attempt_id,
            datetime.now(UTC) - timedelta(seconds=PUBLICATION_IN_PROGRESS_LEASE_SECONDS + 60),
        )
    reclaimed = await store.claim_publication(attempt_id)
    assert reclaimed is not None

    # Failure schedules a bounded backoff.
    await store.mark_publication(attempt_id, status=PublicationStatus.FAILED, error="GitHub 502")
    assert await store.claim_publication(attempt_id) is None
    assert await store.publication_status(attempt_id) is PublicationStatus.FAILED
    async with pg_pool.acquire() as connection:
        await connection.execute(
            "UPDATE publication_outbox SET next_retry_at = $2 WHERE attempt_id = $1::uuid",
            attempt_id,
            datetime.now(UTC) - timedelta(seconds=1),
        )
    retried = await store.claim_publication(attempt_id)
    assert retried is not None
    assert retried.check_run_id == 99

    # Exhaustion: no more claims, but visible in the terminal scan.
    async with pg_pool.acquire() as connection:
        await connection.execute(
            "UPDATE publication_outbox SET attempt_count = $2, status = $3, "
            "next_retry_at = $4 WHERE attempt_id = $1::uuid",
            attempt_id,
            MAX_PUBLICATION_ATTEMPTS,
            PublicationStatus.FAILED.value,
            datetime.now(UTC) - timedelta(seconds=1),
        )
    assert await store.claim_publication(attempt_id) is None
    assert attempt_id not in await store.list_pending_publications(datetime.now(UTC))
    assert attempt_id in await store.list_exhausted_publications()


@pytest.mark.asyncio
async def test_postgres_job_lease_recovery_and_finalize(pg_pool: Any) -> None:
    state = PostgresAuthoritativeAttemptStore(pg_pool, lease_seconds=60.0)
    await state.initialise()
    lease = await state.start_authoritative_attempt(
        change_request=_LOCATOR, request_key=_REQUEST_KEY
    )
    attempt_id = lease.attempt_id

    claimed = await state.claim_attempt_job(attempt_id)
    assert claimed is not None
    # A fresh RUNNING lease cannot be reclaimed.
    assert await state.claim_attempt_job(attempt_id) is None
    # Crash: lease goes stale → recovery requeues with an audit trail.
    async with pg_pool.acquire() as connection:
        await connection.execute(
            "UPDATE review_jobs SET updated_at = CURRENT_TIMESTAMP - make_interval(secs => 3600) "
            "WHERE attempt_id = $1::uuid",
            attempt_id,
        )
    recovery = await state.recover_interrupted_jobs(max_attempts=5, lease_seconds=60.0)
    assert attempt_id in recovery.lease_recovered
    reclaimed = await state.claim_attempt_job(attempt_id)
    assert reclaimed is not None
    # Recovery already requeued it: this is a normal (non-lease) claim.
    assert reclaimed.lease_recovered is False

    # The claim path itself also recovers a stale lease when no recovery ran.
    second = await state.start_authoritative_attempt(
        change_request=_LOCATOR, request_key=_REQUEST_KEY
    )
    second_claim = await state.claim_attempt_job(second.attempt_id)
    assert second_claim is not None
    async with pg_pool.acquire() as connection:
        await connection.execute(
            "UPDATE review_jobs SET updated_at = CURRENT_TIMESTAMP - make_interval(secs => 3600) "
            "WHERE attempt_id = $1::uuid",
            second.attempt_id,
        )
    reclaimed_stale = await state.claim_attempt_job(second.attempt_id)
    assert reclaimed_stale is not None
    assert reclaimed_stale.lease_recovered is True

    await state.finalize_attempt_job(
        attempt_id, status=JobStatus.FAILED, reason="publication retry budget exhausted"
    )
    assert await state.job_status(attempt_id) is JobStatus.FAILED
    # Terminal jobs are never claimable again.
    assert await state.claim_attempt_job(attempt_id) is None
