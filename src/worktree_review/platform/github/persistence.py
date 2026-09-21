"""GitHub review events, results, snapshots, and publication outbox."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.application.review_events import ReviewEvent
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot, PublicationIntent
from worktree_review.server.state import AttemptLease, StateConflictError

_CLAIMABLE_PUBLICATION = frozenset({PublicationStatus.QUEUED, PublicationStatus.FAILED})

# Bounded retry: at most this many delivery attempts per publication intent,
# with exponential backoff (5s * 2^n, capped at 5 minutes). When the budget is
# exhausted the intent stays FAILED with its last error — a queryable terminal
# state, never a silent stall.
MAX_PUBLICATION_ATTEMPTS = 8
PUBLICATION_BACKOFF_BASE_SECONDS = 5.0
PUBLICATION_BACKOFF_CAP_SECONDS = 300.0
# A claimed-but-never-finished delivery (process crash) becomes claimable again.
PUBLICATION_IN_PROGRESS_LEASE_SECONDS = 120.0


def publication_backoff_seconds(attempt_count: int) -> float:
    return float(
        min(
            PUBLICATION_BACKOFF_CAP_SECONDS,
            PUBLICATION_BACKOFF_BASE_SECONDS * (2 ** max(0, attempt_count)),
        )
    )


def assert_snapshot_is_writable(
    existing: AttemptExecutionSnapshot | None, new: AttemptExecutionSnapshot
) -> None:
    if existing is not None and existing != new:
        raise StateConflictError("execution snapshot is immutable")


def publication_is_claimable(status: PublicationStatus | None) -> bool:
    return status in _CLAIMABLE_PUBLICATION


def _parse_snapshot(payload: Any) -> AttemptExecutionSnapshot:
    if isinstance(payload, AttemptExecutionSnapshot):
        return payload
    if isinstance(payload, dict):
        return AttemptExecutionSnapshot.model_validate(payload)
    return AttemptExecutionSnapshot.model_validate_json(payload)


def _parse_review_event(payload: Any) -> ReviewEvent:
    """asyncpg returns JSONB as str or dict depending on codec configuration."""
    if isinstance(payload, ReviewEvent):
        return payload
    if isinstance(payload, dict):
        return ReviewEvent.model_validate(payload)
    return ReviewEvent.model_validate_json(payload)


def _parse_publication_intent(payload: Any) -> PublicationIntent:
    if isinstance(payload, PublicationIntent):
        return payload
    if isinstance(payload, dict):
        return PublicationIntent.model_validate(payload)
    return PublicationIntent.model_validate_json(payload)


GITHUB_PERSISTENCE_SQL = """
ALTER TABLE review_attempts ADD COLUMN IF NOT EXISTS check_run_id BIGINT;
ALTER TABLE review_attempts ADD COLUMN IF NOT EXISTS publication_status TEXT;
ALTER TABLE review_attempts ADD COLUMN IF NOT EXISTS execution_snapshot JSONB;

CREATE TABLE IF NOT EXISTS github_review_events (
    attempt_id UUID NOT NULL REFERENCES review_attempts(attempt_id),
    sequence INTEGER NOT NULL,
    event_json JSONB NOT NULL,
    PRIMARY KEY (attempt_id, sequence)
);

CREATE TABLE IF NOT EXISTS github_review_results (
    attempt_id UUID PRIMARY KEY REFERENCES review_attempts(attempt_id),
    result_json JSONB NOT NULL,
    saved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS webhook_idempotency (
    installation_id BIGINT NOT NULL,
    delivery_id TEXT NOT NULL,
    attempt_id UUID NOT NULL,
    request_digest TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (installation_id, delivery_id)
);

CREATE TABLE IF NOT EXISTS publication_outbox (
    attempt_id UUID PRIMARY KEY REFERENCES review_attempts(attempt_id),
    check_run_id BIGINT NOT NULL,
    intent TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL,
    last_error TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE publication_outbox ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
ALTER TABLE publication_outbox ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ
    NOT NULL DEFAULT CURRENT_TIMESTAMP;
"""


class GitHubReviewStore(Protocol):
    async def save_execution_snapshot(self, snapshot: AttemptExecutionSnapshot) -> None: ...

    async def get_execution_snapshot(self, attempt_id: str) -> AttemptExecutionSnapshot | None: ...

    async def set_check_run_id(self, attempt_id: str, check_run_id: int) -> None: ...

    async def get_check_run_id(self, attempt_id: str) -> int | None: ...

    async def append_review_event(self, event: ReviewEvent) -> None: ...

    async def append(self, event: ReviewEvent) -> None: ...

    async def list_review_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]: ...

    async def list_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]: ...

    async def save_review_result(self, attempt_id: str, result_json: str) -> None: ...

    async def get_review_result(self, attempt_id: str) -> str | None: ...

    async def record_webhook_idempotency(
        self, *, installation_id: int, delivery_id: str, attempt_id: str, request_digest: str
    ) -> str: ...

    async def enqueue_publication(self, intent: PublicationIntent) -> None: ...

    async def claim_publication(
        self, attempt_id: str, *, respect_backoff: bool = True
    ) -> PublicationIntent | None: ...

    async def mark_publication(
        self, attempt_id: str, *, status: PublicationStatus, error: str | None = None
    ) -> None: ...

    async def publication_status(self, attempt_id: str) -> PublicationStatus | None: ...

    async def list_pending_publications(self, now: datetime) -> tuple[str, ...]:
        """Attempts with a saved result whose publication is not durably published.

        Covers: result saved but intent never enqueued (crash window), queued
        intents, failed intents whose backoff has elapsed, and claimed intents
        whose lease expired. Bounded by MAX_PUBLICATION_ATTEMPTS.
        """
        ...

    async def list_recoverable_queued(self) -> tuple[AttemptExecutionSnapshot, ...]: ...

    async def list_exhausted_publications(self) -> tuple[str, ...]:
        """Attempts whose publication spent the whole retry budget (terminal FAILED)."""
        ...

    async def get_attempt_created_at(self, attempt_id: str) -> datetime | None: ...

    async def list_recent_attempt_ids(self, limit: int | None = 50) -> tuple[str, ...]:
        """Most recent GitHub Attempt ids for Web list/overview projections.

        ``limit=None`` returns every Attempt id (authorized Overview totals).
        The default remains a bounded recent window for list feeds.
        """
        ...

    async def overview_gate_counts(self) -> dict[str, int]:
        """Terminal gate counts across ALL GitHub Attempts with saved results."""
        ...


@dataclass
class _AttemptExtras:
    snapshot: AttemptExecutionSnapshot | None = None
    check_run_id: int | None = None
    publication_status: PublicationStatus | None = None
    events: list[ReviewEvent] = field(default_factory=list)
    result_json: str | None = None
    outbox: PublicationIntent | None = None
    outbox_updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class InMemoryGitHubReviewStore:
    """Local persistence for GitHub events/results/snapshots/outbox."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._lock = asyncio.Lock()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._attempts: dict[str, _AttemptExtras] = {}
        self._deliveries: dict[tuple[int, str], tuple[str, str]] = {}

    def _extras(self, attempt_id: str) -> _AttemptExtras:
        return self._attempts.setdefault(attempt_id, _AttemptExtras())

    async def save_execution_snapshot(self, snapshot: AttemptExecutionSnapshot) -> None:
        dumped = snapshot.as_public_dict()
        if any(key in dumped for key in ("token", "secret", "credential")):
            raise StateConflictError("execution snapshot must not contain credentials")
        async with self._lock:
            extras = self._extras(snapshot.attempt_id)
            assert_snapshot_is_writable(extras.snapshot, snapshot)
            extras.snapshot = snapshot

    async def get_execution_snapshot(self, attempt_id: str) -> AttemptExecutionSnapshot | None:
        async with self._lock:
            extras = self._attempts.get(attempt_id)
            return None if extras is None else extras.snapshot

    async def set_check_run_id(self, attempt_id: str, check_run_id: int) -> None:
        async with self._lock:
            extras = self._extras(attempt_id)
            if extras.check_run_id is not None and extras.check_run_id != check_run_id:
                raise StateConflictError("check_run_id is immutable once assigned")
            extras.check_run_id = check_run_id

    async def get_check_run_id(self, attempt_id: str) -> int | None:
        async with self._lock:
            extras = self._attempts.get(attempt_id)
            return None if extras is None else extras.check_run_id

    async def append_review_event(self, event: ReviewEvent) -> None:
        async with self._lock:
            extras = self._extras(event.attempt_id)
            extras.events.append(event)

    async def append(self, event: ReviewEvent) -> None:
        await self.append_review_event(event)

    async def list_review_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]:
        async with self._lock:
            extras = self._attempts.get(attempt_id)
            if extras is None:
                return ()
            return tuple(extras.events)

    async def list_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]:
        return await self.list_review_events(attempt_id)

    async def save_review_result(self, attempt_id: str, result_json: str) -> None:
        async with self._lock:
            extras = self._extras(attempt_id)
            if extras.result_json is not None:
                raise StateConflictError("review result is immutable")
            extras.result_json = result_json

    async def get_review_result(self, attempt_id: str) -> str | None:
        async with self._lock:
            extras = self._attempts.get(attempt_id)
            return None if extras is None else extras.result_json

    async def record_webhook_idempotency(
        self, *, installation_id: int, delivery_id: str, attempt_id: str, request_digest: str
    ) -> str:
        key = (installation_id, delivery_id)
        async with self._lock:
            existing = self._deliveries.get(key)
            if existing is not None:
                stored_attempt, stored_digest = existing
                if stored_digest != request_digest:
                    raise StateConflictError(
                        "delivery idempotency key reused with a different request"
                    )
                return stored_attempt
            self._deliveries[key] = (attempt_id, request_digest)
            return attempt_id

    async def enqueue_publication(self, intent: PublicationIntent) -> None:
        async with self._lock:
            extras = self._extras(intent.attempt_id)
            if extras.outbox is not None and extras.outbox.status is PublicationStatus.PUBLISHED:
                raise StateConflictError("standing publication already completed")
            extras.outbox = intent
            extras.outbox_updated_at = self._clock()
            extras.publication_status = intent.status

    async def claim_publication(
        self, attempt_id: str, *, respect_backoff: bool = True
    ) -> PublicationIntent | None:
        async with self._lock:
            extras = self._attempts.get(attempt_id)
            if extras is None or extras.outbox is None:
                return None
            now = self._clock()
            outbox = extras.outbox
            if outbox.status is PublicationStatus.IN_PROGRESS:
                stale = (now - extras.outbox_updated_at).total_seconds() > (
                    PUBLICATION_IN_PROGRESS_LEASE_SECONDS
                )
                if not stale:
                    return None
            elif not publication_is_claimable(outbox.status):
                return None
            if outbox.attempt_count >= MAX_PUBLICATION_ATTEMPTS:
                return None
            if respect_backoff and outbox.next_retry_at is not None and outbox.next_retry_at > now:
                return None
            extras.outbox = outbox.model_copy(
                update={
                    "status": PublicationStatus.IN_PROGRESS,
                    "attempt_count": outbox.attempt_count + 1,
                }
            )
            extras.outbox_updated_at = now
            extras.publication_status = PublicationStatus.IN_PROGRESS
            return extras.outbox

    async def mark_publication(
        self, attempt_id: str, *, status: PublicationStatus, error: str | None = None
    ) -> None:
        async with self._lock:
            extras = self._extras(attempt_id)
            now = self._clock()
            if extras.outbox is not None:
                next_retry_at = None
                if status is PublicationStatus.FAILED:
                    next_retry_at = now + timedelta(
                        seconds=publication_backoff_seconds(extras.outbox.attempt_count)
                    )
                extras.outbox = extras.outbox.model_copy(
                    update={
                        "status": status,
                        "last_error": error,
                        "next_retry_at": next_retry_at,
                    }
                )
                extras.outbox_updated_at = now
            extras.publication_status = status

    async def publication_status(self, attempt_id: str) -> PublicationStatus | None:
        async with self._lock:
            extras = self._attempts.get(attempt_id)
            return None if extras is None else extras.publication_status

    async def list_pending_publications(self, now: datetime) -> tuple[str, ...]:
        async with self._lock:
            pending: list[str] = []
            for attempt_id, extras in self._attempts.items():
                if extras.result_json is None:
                    continue
                if extras.outbox is None:
                    # Crash window: result saved before the intent was enqueued.
                    if extras.publication_status is not PublicationStatus.PUBLISHED:
                        pending.append(attempt_id)
                    continue
                outbox = extras.outbox
                if outbox.attempt_count >= MAX_PUBLICATION_ATTEMPTS:
                    continue
                if outbox.status is PublicationStatus.IN_PROGRESS:
                    stale = (now - extras.outbox_updated_at).total_seconds() > (
                        PUBLICATION_IN_PROGRESS_LEASE_SECONDS
                    )
                    if stale:
                        pending.append(attempt_id)
                    continue
                if publication_is_claimable(outbox.status) and (
                    outbox.next_retry_at is None or outbox.next_retry_at <= now
                ):
                    pending.append(attempt_id)
            return tuple(pending)

    async def list_exhausted_publications(self) -> tuple[str, ...]:
        async with self._lock:
            return tuple(
                attempt_id
                for attempt_id, extras in self._attempts.items()
                if extras.result_json is not None
                and extras.outbox is not None
                and extras.outbox.status is PublicationStatus.FAILED
                and extras.outbox.attempt_count >= MAX_PUBLICATION_ATTEMPTS
            )

    async def list_recoverable_queued(self) -> tuple[AttemptExecutionSnapshot, ...]:
        async with self._lock:
            recoverable: list[AttemptExecutionSnapshot] = []
            for extras in self._attempts.values():
                if (
                    extras.snapshot is not None
                    and extras.check_run_id is not None
                    and extras.result_json is None
                ):
                    recoverable.append(extras.snapshot)
            return tuple(recoverable)

    async def get_attempt_created_at(self, attempt_id: str) -> datetime | None:
        async with self._lock:
            extras = self._attempts.get(attempt_id)
            return None if extras is None else extras.created_at

    async def list_recent_attempt_ids(self, limit: int | None = 50) -> tuple[str, ...]:
        async with self._lock:
            ordered = sorted(
                self._attempts.items(), key=lambda item: item[1].created_at, reverse=True
            )
            if limit is None:
                return tuple(attempt_id for attempt_id, _ in ordered)
            return tuple(attempt_id for attempt_id, _ in ordered[:limit])

    async def overview_gate_counts(self) -> dict[str, int]:
        async with self._lock:
            counts = {"Passed": 0, "Blocked": 0, "Error": 0, "other": 0}
            for extras in self._attempts.values():
                if extras.result_json is None:
                    continue
                try:
                    gate = json.loads(extras.result_json).get("gate_state")
                except ValueError:
                    gate = None
                counts[gate if gate in counts else "other"] += 1
            return counts


class PostgresGitHubReviewStore:
    """PostgreSQL GitHub events/results/snapshots/outbox on the App database."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def initialise(self) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(GITHUB_PERSISTENCE_SQL)

    async def save_execution_snapshot(self, snapshot: AttemptExecutionSnapshot) -> None:
        dumped = snapshot.model_dump_json()
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT execution_snapshot
                    FROM review_attempts
                    WHERE attempt_id = $1::uuid
                    FOR UPDATE
                    """,
                    snapshot.attempt_id,
                )
                if row is None:
                    raise StateConflictError(f"unknown Attempt: {snapshot.attempt_id}")
                existing = (
                    None
                    if row["execution_snapshot"] is None
                    else _parse_snapshot(row["execution_snapshot"])
                )
                assert_snapshot_is_writable(existing, snapshot)
                await connection.execute(
                    """
                    UPDATE review_attempts
                    SET execution_snapshot = $2::jsonb
                    WHERE attempt_id = $1::uuid
                    """,
                    snapshot.attempt_id,
                    dumped,
                )

    async def get_execution_snapshot(self, attempt_id: str) -> AttemptExecutionSnapshot | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT execution_snapshot FROM review_attempts WHERE attempt_id = $1::uuid",
                attempt_id,
            )
        if row is None or row["execution_snapshot"] is None:
            return None
        return _parse_snapshot(row["execution_snapshot"])

    async def set_check_run_id(self, attempt_id: str, check_run_id: int) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE review_attempts
                SET check_run_id = $2
                WHERE attempt_id = $1::uuid
                  AND (check_run_id IS NULL OR check_run_id = $2)
                """,
                attempt_id,
                check_run_id,
            )

    async def get_check_run_id(self, attempt_id: str) -> int | None:
        async with self._pool.acquire() as connection:
            value = await connection.fetchval(
                "SELECT check_run_id FROM review_attempts WHERE attempt_id = $1::uuid",
                attempt_id,
            )
        return None if value is None else int(value)

    async def append_review_event(self, event: ReviewEvent) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO github_review_events(attempt_id, sequence, event_json)
                VALUES ($1::uuid, $2, $3::jsonb)
                """,
                event.attempt_id,
                event.sequence,
                event.model_dump_json(by_alias=True),
            )

    async def append(self, event: ReviewEvent) -> None:
        await self.append_review_event(event)

    async def list_review_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT event_json FROM github_review_events
                WHERE attempt_id = $1::uuid ORDER BY sequence
                """,
                attempt_id,
            )
        return tuple(_parse_review_event(row["event_json"]) for row in rows)

    async def list_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]:
        return await self.list_review_events(attempt_id)

    async def save_review_result(self, attempt_id: str, result_json: str) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO github_review_results(attempt_id, result_json, saved_at)
                VALUES ($1::uuid, $2::jsonb, $3)
                """,
                attempt_id,
                result_json,
                datetime.now(UTC),
            )

    async def get_review_result(self, attempt_id: str) -> str | None:
        async with self._pool.acquire() as connection:
            value = await connection.fetchval(
                "SELECT result_json FROM github_review_results WHERE attempt_id = $1::uuid",
                attempt_id,
            )
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value)

    async def record_webhook_idempotency(
        self, *, installation_id: int, delivery_id: str, attempt_id: str, request_digest: str
    ) -> str:
        async with self._pool.acquire() as connection:
            existing = await connection.fetchrow(
                """
                SELECT attempt_id, request_digest FROM webhook_idempotency
                WHERE installation_id = $1 AND delivery_id = $2
                """,
                installation_id,
                delivery_id,
            )
            if existing is not None:
                if existing["request_digest"] != request_digest:
                    raise StateConflictError(
                        "delivery idempotency key reused with a different request"
                    )
                return str(existing["attempt_id"])
            await connection.execute(
                """
                INSERT INTO webhook_idempotency(
                    installation_id, delivery_id, attempt_id, request_digest
                ) VALUES ($1, $2, $3::uuid, $4)
                """,
                installation_id,
                delivery_id,
                attempt_id,
                request_digest,
            )
            return attempt_id

    async def enqueue_publication(self, intent: PublicationIntent) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO publication_outbox(
                    attempt_id, check_run_id, intent, payload, status, last_error, attempt_count
                ) VALUES ($1::uuid, $2, $3, $4::jsonb, $5, $6, $7)
                ON CONFLICT (attempt_id) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    status = EXCLUDED.status
                WHERE publication_outbox.status <> $8
                """,
                intent.attempt_id,
                intent.check_run_id,
                intent.intent,
                intent.model_dump_json(),
                intent.status.value,
                intent.last_error,
                intent.attempt_count,
                PublicationStatus.PUBLISHED.value,
            )

    async def claim_publication(
        self, attempt_id: str, *, respect_backoff: bool = True
    ) -> PublicationIntent | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT payload, status, attempt_count, next_retry_at, updated_at
                    FROM publication_outbox
                    WHERE attempt_id = $1::uuid
                    FOR UPDATE
                    """,
                    attempt_id,
                )
                if row is None:
                    return None
                status = PublicationStatus(row["status"])
                if status is PublicationStatus.IN_PROGRESS:
                    updated_at = row["updated_at"]
                    stale = (datetime.now(UTC) - updated_at).total_seconds() > (
                        PUBLICATION_IN_PROGRESS_LEASE_SECONDS
                    )
                    if not stale:
                        return None
                elif not publication_is_claimable(status):
                    return None
                if row["attempt_count"] >= MAX_PUBLICATION_ATTEMPTS:
                    return None
                if respect_backoff:
                    next_retry_at = row["next_retry_at"]
                    if next_retry_at is not None and next_retry_at > datetime.now(UTC):
                        return None
                # The FOR UPDATE row lock above makes this transition atomic.
                await connection.execute(
                    """
                    UPDATE publication_outbox
                    SET status = $2, attempt_count = attempt_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE attempt_id = $1::uuid AND status = $3
                    """,
                    attempt_id,
                    PublicationStatus.IN_PROGRESS.value,
                    status.value,
                )
                return _parse_publication_intent(row["payload"])

    async def mark_publication(
        self, attempt_id: str, *, status: PublicationStatus, error: str | None = None
    ) -> None:
        async with self._pool.acquire() as connection:
            if status is PublicationStatus.FAILED:
                await connection.execute(
                    """
                    UPDATE publication_outbox
                    SET status = $2, last_error = $3, updated_at = CURRENT_TIMESTAMP,
                        next_retry_at = CURRENT_TIMESTAMP + make_interval(
                            secs => LEAST($4, $5 * power(2, attempt_count))
                        )
                    WHERE attempt_id = $1::uuid
                    """,
                    attempt_id,
                    status.value,
                    error,
                    PUBLICATION_BACKOFF_CAP_SECONDS,
                    PUBLICATION_BACKOFF_BASE_SECONDS,
                )
            else:
                await connection.execute(
                    """
                    UPDATE publication_outbox
                    SET status = $2, last_error = $3, updated_at = CURRENT_TIMESTAMP,
                        next_retry_at = NULL
                    WHERE attempt_id = $1::uuid
                    """,
                    attempt_id,
                    status.value,
                    error,
                )
            await connection.execute(
                """
                UPDATE review_attempts SET publication_status = $2
                WHERE attempt_id = $1::uuid
                """,
                attempt_id,
                status.value,
            )

    async def publication_status(self, attempt_id: str) -> PublicationStatus | None:
        async with self._pool.acquire() as connection:
            value = await connection.fetchval(
                "SELECT publication_status FROM review_attempts WHERE attempt_id = $1::uuid",
                attempt_id,
            )
        return None if value is None else PublicationStatus(value)

    async def list_pending_publications(self, now: datetime) -> tuple[str, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT a.attempt_id
                FROM review_attempts AS a
                JOIN github_review_results AS r ON r.attempt_id = a.attempt_id
                LEFT JOIN publication_outbox AS o ON o.attempt_id = a.attempt_id
                WHERE (o.attempt_id IS NULL
                       AND a.publication_status IS DISTINCT FROM $1)
                   OR (o.status IN ('queued', 'failed')
                       AND o.attempt_count < $2
                       AND (o.next_retry_at IS NULL OR o.next_retry_at <= $3))
                   OR (o.status = 'in_progress'
                       AND o.attempt_count < $2
                       AND o.updated_at < $3 - make_interval(secs => $4))
                """,
                PublicationStatus.PUBLISHED.value,
                MAX_PUBLICATION_ATTEMPTS,
                now,
                PUBLICATION_IN_PROGRESS_LEASE_SECONDS,
            )
        return tuple(str(row["attempt_id"]) for row in rows)

    async def list_exhausted_publications(self) -> tuple[str, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT o.attempt_id
                FROM publication_outbox AS o
                JOIN github_review_results AS r ON r.attempt_id = o.attempt_id
                WHERE o.status = $1 AND o.attempt_count >= $2
                """,
                PublicationStatus.FAILED.value,
                MAX_PUBLICATION_ATTEMPTS,
            )
        return tuple(str(row["attempt_id"]) for row in rows)

    async def list_recoverable_queued(self) -> tuple[AttemptExecutionSnapshot, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT a.execution_snapshot FROM review_attempts AS a
                JOIN review_jobs AS j ON j.attempt_id = a.attempt_id
                WHERE a.execution_snapshot IS NOT NULL
                  AND a.check_run_id IS NOT NULL
                  AND a.attempt_id NOT IN (SELECT attempt_id FROM github_review_results)
                  AND j.status IN ('queued', 'retryable', 'running')
                """
            )
        snapshots: list[AttemptExecutionSnapshot] = []
        for row in rows:
            snapshots.append(_parse_snapshot(row["execution_snapshot"]))
        return tuple(snapshots)

    async def get_attempt_created_at(self, attempt_id: str) -> datetime | None:
        async with self._pool.acquire() as connection:
            value = await connection.fetchval(
                "SELECT created_at FROM review_attempts WHERE attempt_id = $1::uuid",
                attempt_id,
            )
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    async def list_recent_attempt_ids(self, limit: int | None = 50) -> tuple[str, ...]:
        async with self._pool.acquire() as connection:
            if limit is None:
                rows = await connection.fetch(
                    """
                    SELECT attempt_id FROM review_attempts
                    ORDER BY created_at DESC, attempt_id DESC
                    """
                )
            else:
                rows = await connection.fetch(
                    """
                    SELECT attempt_id FROM review_attempts
                    ORDER BY created_at DESC, attempt_id DESC LIMIT $1
                    """,
                    limit,
                )
        return tuple(str(row["attempt_id"]) for row in rows)

    async def overview_gate_counts(self) -> dict[str, int]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT result_json->>'gate_state' AS gate_state, COUNT(*) AS count
                FROM github_review_results
                GROUP BY result_json->>'gate_state'
                """
            )
        counts = {"Passed": 0, "Blocked": 0, "Error": 0, "other": 0}
        for row in rows:
            gate = row["gate_state"]
            counts[gate if gate in counts else "other"] += int(row["count"])
        return counts


def recoverable_from_snapshot(
    snapshot: AttemptExecutionSnapshot, *, check_run_id: int | None
) -> AttemptLease | None:
    if check_run_id is None:
        return None
    return AttemptLease(
        attempt_id=snapshot.attempt_id,
        change_request=snapshot.change_request,
        request_key=snapshot.request_key,
    )
