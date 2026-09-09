"""GitHub review events, results, snapshots, and publication outbox."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.application.review_events import ReviewEvent
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot, PublicationIntent
from worktree_review.server.state import AttemptLease, StateConflictError

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
"""


class GitHubReviewStore(Protocol):
    async def save_execution_snapshot(self, snapshot: AttemptExecutionSnapshot) -> None: ...

    async def get_execution_snapshot(self, attempt_id: str) -> AttemptExecutionSnapshot | None: ...

    async def set_check_run_id(self, attempt_id: str, check_run_id: int) -> None: ...

    async def get_check_run_id(self, attempt_id: str) -> int | None: ...

    async def append_review_event(self, event: ReviewEvent) -> None: ...

    async def list_review_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]: ...

    async def save_review_result(self, attempt_id: str, result_json: str) -> None: ...

    async def get_review_result(self, attempt_id: str) -> str | None: ...

    async def record_webhook_idempotency(
        self, *, installation_id: int, delivery_id: str, attempt_id: str, request_digest: str
    ) -> str: ...

    async def enqueue_publication(self, intent: PublicationIntent) -> None: ...

    async def claim_publication(self, attempt_id: str) -> PublicationIntent | None: ...

    async def mark_publication(
        self, attempt_id: str, *, status: PublicationStatus, error: str | None = None
    ) -> None: ...

    async def publication_status(self, attempt_id: str) -> PublicationStatus | None: ...

    async def list_recoverable_queued(self) -> tuple[AttemptExecutionSnapshot, ...]: ...


@dataclass
class _AttemptExtras:
    snapshot: AttemptExecutionSnapshot | None = None
    check_run_id: int | None = None
    publication_status: PublicationStatus | None = None
    events: list[ReviewEvent] = field(default_factory=list)
    result_json: str | None = None
    outbox: PublicationIntent | None = None


class InMemoryGitHubReviewStore:
    """Local persistence for GitHub events/results/snapshots/outbox."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
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
            if extras.snapshot is not None and extras.snapshot != snapshot:
                raise StateConflictError("execution snapshot is immutable")
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

    async def list_review_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]:
        async with self._lock:
            extras = self._attempts.get(attempt_id)
            if extras is None:
                return ()
            return tuple(extras.events)

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
            extras.publication_status = intent.status

    async def claim_publication(self, attempt_id: str) -> PublicationIntent | None:
        async with self._lock:
            extras = self._attempts.get(attempt_id)
            if extras is None or extras.outbox is None:
                return None
            if extras.outbox.status is PublicationStatus.PUBLISHED:
                return extras.outbox
            extras.outbox = extras.outbox.model_copy(
                update={
                    "status": PublicationStatus.IN_PROGRESS,
                    "attempt_count": extras.outbox.attempt_count + 1,
                }
            )
            extras.publication_status = PublicationStatus.IN_PROGRESS
            return extras.outbox

    async def mark_publication(
        self, attempt_id: str, *, status: PublicationStatus, error: str | None = None
    ) -> None:
        async with self._lock:
            extras = self._extras(attempt_id)
            if extras.outbox is None:
                raise StateConflictError(f"no publication intent for {attempt_id}")
            extras.outbox = extras.outbox.model_copy(
                update={"status": status, "last_error": error}
            )
            extras.publication_status = status

    async def publication_status(self, attempt_id: str) -> PublicationStatus | None:
        async with self._lock:
            extras = self._attempts.get(attempt_id)
            return None if extras is None else extras.publication_status

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
            await connection.execute(
                """
                UPDATE review_attempts
                SET execution_snapshot = $2::jsonb
                WHERE attempt_id = $1::uuid AND (
                    execution_snapshot IS NULL OR execution_snapshot = $2::jsonb
                )
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
        payload = row["execution_snapshot"]
        if not isinstance(payload, dict):
            payload = AttemptExecutionSnapshot.model_validate_json(payload).model_dump()
        return AttemptExecutionSnapshot.model_validate(payload)

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

    async def list_review_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT event_json FROM github_review_events
                WHERE attempt_id = $1::uuid ORDER BY sequence
                """,
                attempt_id,
            )
        return tuple(ReviewEvent.model_validate(row["event_json"]) for row in rows)

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
        return value if isinstance(value, str) else str(value)

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

    async def claim_publication(self, attempt_id: str) -> PublicationIntent | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM publication_outbox WHERE attempt_id = $1::uuid FOR UPDATE",
                attempt_id,
            )
            if row is None:
                return None
            await connection.execute(
                """
                UPDATE publication_outbox
                SET status = $2, attempt_count = attempt_count + 1
                WHERE attempt_id = $1::uuid AND status <> $3
                """,
                attempt_id,
                PublicationStatus.IN_PROGRESS.value,
                PublicationStatus.PUBLISHED.value,
            )
        return PublicationIntent.model_validate_json(row["payload"])

    async def mark_publication(
        self, attempt_id: str, *, status: PublicationStatus, error: str | None = None
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE publication_outbox
                SET status = $2, last_error = $3
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

    async def list_recoverable_queued(self) -> tuple[AttemptExecutionSnapshot, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT execution_snapshot FROM review_attempts
                WHERE execution_snapshot IS NOT NULL
                  AND check_run_id IS NOT NULL
                  AND attempt_id NOT IN (SELECT attempt_id FROM github_review_results)
                """
            )
        snapshots: list[AttemptExecutionSnapshot] = []
        for row in rows:
            payload = row["execution_snapshot"]
            snapshots.append(AttemptExecutionSnapshot.model_validate(payload))
        return tuple(snapshots)


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
