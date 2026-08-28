"""Authoritative GitHub attempt state and publish-time compare-and-set (D8).

This module is server infrastructure, not product identity logic. GitHub's pull
request locator is stored here so the platform identifier never becomes part of
``ReviewIdentity`` or ``ReviewRequestKey``. The in-memory implementation is
used for deterministic concurrency tests; the PostgreSQL implementation uses
the same state transitions and SQL row locks.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from worktree_review.core.identity import ReviewIdentity, ReviewRequestKey
from worktree_review.core.report import GateState

if TYPE_CHECKING:
    import asyncpg  # type: ignore[import-untyped]


class GitHubChangeRequestLocator(BaseModel):
    """Platform locator for state; deliberately absent from core identities."""

    model_config = ConfigDict(frozen=True)

    installation_id: int = Field(gt=0)
    repository: str = Field(min_length=1)
    pull_request_number: int = Field(gt=0)


class AttemptStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUPERSEDED = "superseded"
    PUBLISHED = "published"
    AUDIT_ONLY = "audit-only"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUPERSEDED = "superseded"
    COMPLETED = "completed"


class PublishDisposition(StrEnum):
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


class AttemptLease(BaseModel):
    """The immutable scheduling data a worker needs for one Attempt."""

    model_config = ConfigDict(frozen=True)

    attempt_id: str = Field(min_length=1)
    change_request: GitHubChangeRequestLocator
    request_key: ReviewRequestKey
    prior_authoritative_attempt_id: str | None = None
    delivery_replayed: bool = False


class PublishResult(BaseModel):
    """Whether stage 9 changed the standing decision or remained audit-only."""

    model_config = ConfigDict(frozen=True)

    disposition: PublishDisposition
    attempt_id: str
    gate_state: GateState | None = None
    detail: str


class AuthoritativeChangeRequestState(BaseModel):
    """Snapshot of the current authority and standing decision for one locator."""

    model_config = ConfigDict(frozen=True)

    change_request: GitHubChangeRequestLocator
    request_key: ReviewRequestKey | None = None
    authoritative_attempt_id: str | None = None
    standing_attempt_id: str | None = None
    standing_gate_state: GateState | None = None


class StateConflictError(RuntimeError):
    """A caller attempted an impossible or stale state transition."""


class AuthoritativeAttemptStore(Protocol):
    """Persistence boundary shared by retry scheduling and stage-9 publication."""

    async def start_authoritative_attempt(
        self,
        *,
        change_request: GitHubChangeRequestLocator,
        request_key: ReviewRequestKey,
        expected_authoritative_attempt_id: str | None = None,
        delivery_id: str | None = None,
    ) -> AttemptLease:
        """Create and designate an Attempt while invalidating the prior standing state."""
        ...

    async def get_delivery_attempt(
        self,
        *,
        installation_id: int,
        delivery_id: str,
    ) -> AttemptLease | None:
        """Return the Attempt already created for one GitHub delivery, if any."""
        ...

    async def record_review_identity(
        self,
        *,
        attempt_id: str,
        review_identity: ReviewIdentity,
    ) -> None:
        """Persist the identity produced by successful merge construction for an Attempt."""
        ...

    async def claim_attempt_job(self, attempt_id: str) -> AttemptLease | None:
        """Claim an attempt-keyed job, discarding queued jobs already superseded."""
        ...

    async def publish_if_authoritative(
        self,
        *,
        attempt_id: str,
        request_key: ReviewRequestKey,
        review_identity: ReviewIdentity | None,
        gate_state: GateState,
    ) -> PublishResult:
        """CAS the standing gate only while Attempt and identities still match."""
        ...

    async def get_change_request_state(
        self,
        change_request: GitHubChangeRequestLocator,
    ) -> AuthoritativeChangeRequestState: ...

    async def append_audit_event(
        self,
        *,
        event_type: str,
        change_request: GitHubChangeRequestLocator,
        attempt_id: str | None,
        payload: dict[str, object],
    ) -> None: ...


def _review_identity_matches_request_key(
    review_identity: ReviewIdentity,
    request_key: ReviewRequestKey,
) -> bool:
    candidate_identity = review_identity.candidate
    return (
        candidate_identity.source_repository == request_key.source_repository
        and candidate_identity.target_ref == request_key.target_ref
        and candidate_identity.target_head_oid == request_key.target_head_oid
        and candidate_identity.proposed_head_oid == request_key.proposed_head_oid
        and review_identity.review_policy_version == request_key.review_policy_version
    )


@dataclass
class _MutableAttempt:
    attempt_id: str
    change_request: GitHubChangeRequestLocator
    request_key: ReviewRequestKey
    status: AttemptStatus
    review_identity: ReviewIdentity | None = None


@dataclass
class _MutableJob:
    attempt_id: str
    status: JobStatus


@dataclass
class _MutableChangeRequest:
    change_request: GitHubChangeRequestLocator
    request_key: ReviewRequestKey
    authoritative_attempt_id: str
    standing_attempt_id: str | None = None
    standing_gate_state: GateState | None = None


def _delivery_key(installation_id: int, delivery_id: str) -> tuple[int, str]:
    if not delivery_id:
        raise StateConflictError("GitHub delivery ID must not be empty")
    return installation_id, delivery_id


class InMemoryAuthoritativeAttemptStore:
    """Small transactional model for race tests and local server development."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._change_requests: dict[GitHubChangeRequestLocator, _MutableChangeRequest] = {}
        self._attempts: dict[str, _MutableAttempt] = {}
        self._jobs: dict[str, _MutableJob] = {}
        self._delivery_attempts: dict[tuple[int, str], AttemptLease] = {}
        self._audit_events: list[dict[str, object]] = []

    async def start_authoritative_attempt(
        self,
        *,
        change_request: GitHubChangeRequestLocator,
        request_key: ReviewRequestKey,
        expected_authoritative_attempt_id: str | None = None,
        delivery_id: str | None = None,
    ) -> AttemptLease:
        async with self._lock:
            delivery_key = (
                None
                if delivery_id is None
                else _delivery_key(
                    change_request.installation_id,
                    delivery_id,
                )
            )
            if delivery_key is not None:
                previous_delivery_attempt = self._delivery_attempts.get(delivery_key)
                if previous_delivery_attempt is not None:
                    return previous_delivery_attempt.model_copy(update={"delivery_replayed": True})
            current_state = self._change_requests.get(change_request)
            prior_attempt_id = (
                current_state.authoritative_attempt_id if current_state is not None else None
            )
            if (
                expected_authoritative_attempt_id is not None
                and prior_attempt_id != expected_authoritative_attempt_id
            ):
                raise StateConflictError(
                    "retry target is no longer the authoritative Attempt: "
                    f"expected {expected_authoritative_attempt_id}, found {prior_attempt_id}"
                )

            attempt_id = str(uuid4())
            if prior_attempt_id is not None:
                prior_attempt = self._attempts[prior_attempt_id]
                prior_attempt.status = AttemptStatus.SUPERSEDED
                prior_job = self._jobs.get(prior_attempt_id)
                if prior_job is not None and prior_job.status is JobStatus.QUEUED:
                    prior_job.status = JobStatus.SUPERSEDED

            self._change_requests[change_request] = _MutableChangeRequest(
                change_request=change_request,
                request_key=request_key,
                authoritative_attempt_id=attempt_id,
            )
            self._attempts[attempt_id] = _MutableAttempt(
                attempt_id=attempt_id,
                change_request=change_request,
                request_key=request_key,
                status=AttemptStatus.QUEUED,
            )
            self._jobs[attempt_id] = _MutableJob(
                attempt_id=attempt_id,
                status=JobStatus.QUEUED,
            )
            attempt_lease = AttemptLease(
                attempt_id=attempt_id,
                change_request=change_request,
                request_key=request_key,
                prior_authoritative_attempt_id=prior_attempt_id,
            )
            if delivery_key is not None:
                self._delivery_attempts[delivery_key] = attempt_lease
            self._audit_events.append(
                {
                    "event_type": "attempt_authoritative",
                    "attempt_id": attempt_id,
                    "change_request": change_request.model_dump(mode="json"),
                    "prior_attempt_id": prior_attempt_id,
                    "delivery_id": delivery_id,
                }
            )
            return attempt_lease

    async def get_delivery_attempt(
        self,
        *,
        installation_id: int,
        delivery_id: str,
    ) -> AttemptLease | None:
        async with self._lock:
            previous_delivery_attempt = self._delivery_attempts.get(
                _delivery_key(installation_id, delivery_id)
            )
            if previous_delivery_attempt is None:
                return None
            return previous_delivery_attempt.model_copy(update={"delivery_replayed": True})

    async def record_review_identity(
        self,
        *,
        attempt_id: str,
        review_identity: ReviewIdentity,
    ) -> None:
        async with self._lock:
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise StateConflictError(f"unknown Attempt: {attempt_id}")
            if not _review_identity_matches_request_key(review_identity, attempt.request_key):
                raise StateConflictError(
                    "Review Identity does not match the Attempt's Review Request Key"
                )
            if attempt.review_identity is not None and attempt.review_identity != review_identity:
                raise StateConflictError("Review Identity for an Attempt is immutable")
            attempt.review_identity = review_identity

    async def claim_attempt_job(self, attempt_id: str) -> AttemptLease | None:
        async with self._lock:
            attempt = self._attempts.get(attempt_id)
            job = self._jobs.get(attempt_id)
            if attempt is None or job is None or job.status is not JobStatus.QUEUED:
                return None
            change_request = self._change_requests[attempt.change_request]
            if change_request.authoritative_attempt_id != attempt_id:
                job.status = JobStatus.SUPERSEDED
                attempt.status = AttemptStatus.SUPERSEDED
                return None
            job.status = JobStatus.RUNNING
            attempt.status = AttemptStatus.RUNNING
            return AttemptLease(
                attempt_id=attempt.attempt_id,
                change_request=attempt.change_request,
                request_key=attempt.request_key,
            )

    async def publish_if_authoritative(
        self,
        *,
        attempt_id: str,
        request_key: ReviewRequestKey,
        review_identity: ReviewIdentity | None,
        gate_state: GateState,
    ) -> PublishResult:
        async with self._lock:
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise StateConflictError(f"unknown Attempt: {attempt_id}")
            current_state = self._change_requests[attempt.change_request]
            authority_matches = current_state.authoritative_attempt_id == attempt_id
            request_key_matches = (
                current_state.request_key == request_key and attempt.request_key == request_key
            )
            identity_matches = review_identity == attempt.review_identity
            if review_identity is not None:
                identity_matches = identity_matches and _review_identity_matches_request_key(
                    review_identity,
                    request_key,
                )
            publication_inputs_match = (
                authority_matches and request_key_matches and identity_matches
            )

            if attempt.status is AttemptStatus.PUBLISHED:
                if not publication_inputs_match or current_state.standing_attempt_id != attempt_id:
                    raise StateConflictError(
                        "published Attempt is no longer the standing authoritative Attempt"
                    )
                published_gate_state = current_state.standing_gate_state
                if published_gate_state is None:
                    raise StateConflictError(
                        "published Attempt has no persisted standing gate state"
                    )
                if published_gate_state is not gate_state:
                    raise StateConflictError(
                        "published Attempt cannot be changed to a different gate state"
                    )
                return PublishResult(
                    disposition=PublishDisposition.PUBLISHED,
                    attempt_id=attempt_id,
                    gate_state=published_gate_state,
                    detail="authoritative gate decision was already published",
                )

            if attempt.status is not AttemptStatus.RUNNING:
                if publication_inputs_match:
                    raise StateConflictError(
                        "Attempt must be running before its gate decision can be published"
                    )
                if attempt.status is AttemptStatus.AUDIT_ONLY:
                    return PublishResult(
                        disposition=PublishDisposition.SUPERSEDED,
                        attempt_id=attempt_id,
                        detail="Attempt was superseded before publication",
                    )

            if not publication_inputs_match:
                attempt.status = AttemptStatus.AUDIT_ONLY
                job = self._jobs.get(attempt_id)
                if job is not None and job.status is JobStatus.RUNNING:
                    job.status = JobStatus.COMPLETED
                detail = "Attempt was superseded before publication"
                self._audit_events.append(
                    {
                        "event_type": "attempt_publish_superseded",
                        "attempt_id": attempt_id,
                        "detail": detail,
                    }
                )
                return PublishResult(
                    disposition=PublishDisposition.SUPERSEDED,
                    attempt_id=attempt_id,
                    detail=detail,
                )

            attempt.status = AttemptStatus.PUBLISHED
            job = self._jobs.get(attempt_id)
            if job is not None:
                job.status = JobStatus.COMPLETED
            current_state.standing_attempt_id = attempt_id
            current_state.standing_gate_state = gate_state
            self._audit_events.append(
                {
                    "event_type": "standing_decision_published",
                    "attempt_id": attempt_id,
                    "gate_state": gate_state.value,
                }
            )
            return PublishResult(
                disposition=PublishDisposition.PUBLISHED,
                attempt_id=attempt_id,
                gate_state=gate_state,
                detail="authoritative gate decision published",
            )

    async def get_change_request_state(
        self,
        change_request: GitHubChangeRequestLocator,
    ) -> AuthoritativeChangeRequestState:
        async with self._lock:
            current_state = self._change_requests.get(change_request)
            if current_state is None:
                return AuthoritativeChangeRequestState(change_request=change_request)
            return AuthoritativeChangeRequestState(
                change_request=change_request,
                request_key=current_state.request_key,
                authoritative_attempt_id=current_state.authoritative_attempt_id,
                standing_attempt_id=current_state.standing_attempt_id,
                standing_gate_state=current_state.standing_gate_state,
            )

    async def append_audit_event(
        self,
        *,
        event_type: str,
        change_request: GitHubChangeRequestLocator,
        attempt_id: str | None,
        payload: dict[str, object],
    ) -> None:
        async with self._lock:
            self._audit_events.append(
                {
                    "event_type": event_type,
                    "change_request": change_request.model_dump(mode="json"),
                    "attempt_id": attempt_id,
                    "payload": payload,
                }
            )

    async def audit_events(self) -> tuple[dict[str, object], ...]:
        async with self._lock:
            return tuple(self._audit_events)

    async def job_status(self, attempt_id: str) -> JobStatus | None:
        async with self._lock:
            job = self._jobs.get(attempt_id)
            return None if job is None else job.status


POSTGRES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS change_requests (
    installation_id BIGINT NOT NULL,
    repository TEXT NOT NULL,
    pull_request_number BIGINT NOT NULL,
    request_key JSONB NOT NULL,
    authoritative_attempt_id UUID NOT NULL,
    standing_attempt_id UUID,
    standing_gate_state TEXT,
    PRIMARY KEY (installation_id, repository, pull_request_number)
);

CREATE TABLE IF NOT EXISTS review_attempts (
    attempt_id UUID PRIMARY KEY,
    installation_id BIGINT NOT NULL,
    repository TEXT NOT NULL,
    pull_request_number BIGINT NOT NULL,
    request_key JSONB NOT NULL,
    review_identity JSONB,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_jobs (
    attempt_id UUID PRIMARY KEY REFERENCES review_attempts(attempt_id),
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gate_decisions (
    decision_id BIGSERIAL PRIMARY KEY,
    installation_id BIGINT NOT NULL,
    repository TEXT NOT NULL,
    pull_request_number BIGINT NOT NULL,
    attempt_id UUID NOT NULL,
    request_key JSONB NOT NULL,
    review_identity JSONB,
    gate_state TEXT NOT NULL,
    standing BOOLEAN NOT NULL,
    UNIQUE (attempt_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS gate_decisions_one_per_attempt
    ON gate_decisions (attempt_id);

CREATE TABLE IF NOT EXISTS retry_deliveries (
    installation_id BIGINT NOT NULL,
    delivery_id TEXT NOT NULL,
    attempt_id UUID NOT NULL REFERENCES review_attempts(attempt_id),
    prior_authoritative_attempt_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (installation_id, delivery_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    installation_id BIGINT NOT NULL,
    repository TEXT NOT NULL,
    pull_request_number BIGINT NOT NULL,
    attempt_id UUID,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    decoded = json.loads(str(value))
    if not isinstance(decoded, dict):
        raise StateConflictError("persisted state JSON is not an object")
    return decoded


class PostgresAuthoritativeAttemptStore:
    """PostgreSQL implementation of the D8 state transitions."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def initialise(self) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(POSTGRES_SCHEMA_SQL)

    async def get_delivery_attempt(
        self,
        *,
        installation_id: int,
        delivery_id: str,
    ) -> AttemptLease | None:
        delivery_key = _delivery_key(installation_id, delivery_id)
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT d.attempt_id, d.prior_authoritative_attempt_id,
                       a.installation_id, a.repository, a.pull_request_number,
                       a.request_key
                FROM retry_deliveries AS d
                JOIN review_attempts AS a ON a.attempt_id = d.attempt_id
                WHERE d.installation_id = $1 AND d.delivery_id = $2
                """,
                delivery_key[0],
                delivery_key[1],
            )
        if row is None:
            return None
        return AttemptLease(
            attempt_id=str(row["attempt_id"]),
            change_request=GitHubChangeRequestLocator(
                installation_id=row["installation_id"],
                repository=row["repository"],
                pull_request_number=row["pull_request_number"],
            ),
            request_key=ReviewRequestKey.model_validate(_json_object(row["request_key"])),
            prior_authoritative_attempt_id=(
                None
                if row["prior_authoritative_attempt_id"] is None
                else str(row["prior_authoritative_attempt_id"])
            ),
            delivery_replayed=True,
        )

    async def start_authoritative_attempt(
        self,
        *,
        change_request: GitHubChangeRequestLocator,
        request_key: ReviewRequestKey,
        expected_authoritative_attempt_id: str | None = None,
        delivery_id: str | None = None,
    ) -> AttemptLease:
        attempt_id = str(uuid4())
        request_key_json = request_key.model_dump_json()
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                delivery_key = (
                    None
                    if delivery_id is None
                    else _delivery_key(
                        change_request.installation_id,
                        delivery_id,
                    )
                )
                if delivery_key is not None:
                    await connection.fetchval(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                        f"{delivery_key[0]}:{delivery_key[1]}",
                    )
                    previous_delivery = await connection.fetchrow(
                        """
                        SELECT d.attempt_id, d.prior_authoritative_attempt_id,
                               a.installation_id, a.repository, a.pull_request_number,
                               a.request_key
                        FROM retry_deliveries AS d
                        JOIN review_attempts AS a ON a.attempt_id = d.attempt_id
                        WHERE d.installation_id = $1 AND d.delivery_id = $2
                        """,
                        delivery_key[0],
                        delivery_key[1],
                    )
                    if previous_delivery is not None:
                        return AttemptLease(
                            attempt_id=str(previous_delivery["attempt_id"]),
                            change_request=GitHubChangeRequestLocator(
                                installation_id=previous_delivery["installation_id"],
                                repository=previous_delivery["repository"],
                                pull_request_number=previous_delivery["pull_request_number"],
                            ),
                            request_key=ReviewRequestKey.model_validate(
                                _json_object(previous_delivery["request_key"])
                            ),
                            prior_authoritative_attempt_id=(
                                None
                                if previous_delivery["prior_authoritative_attempt_id"] is None
                                else str(previous_delivery["prior_authoritative_attempt_id"])
                            ),
                            delivery_replayed=True,
                        )
                inserted_row = await connection.fetchrow(
                    """
                    INSERT INTO change_requests (
                        installation_id, repository, pull_request_number,
                        request_key, authoritative_attempt_id
                    ) VALUES ($1, $2, $3, $4::jsonb, $5::uuid)
                    ON CONFLICT (installation_id, repository, pull_request_number) DO NOTHING
                    RETURNING authoritative_attempt_id
                    """,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                    request_key_json,
                    attempt_id,
                )
                if inserted_row is None:
                    current_row = await connection.fetchrow(
                        """
                        SELECT authoritative_attempt_id
                        FROM change_requests
                        WHERE installation_id = $1 AND repository = $2
                          AND pull_request_number = $3
                        FOR UPDATE
                        """,
                        change_request.installation_id,
                        change_request.repository,
                        change_request.pull_request_number,
                    )
                    if current_row is None:
                        raise StateConflictError("change request disappeared during transaction")
                    prior_attempt_id = str(current_row["authoritative_attempt_id"])
                else:
                    prior_attempt_id = None
                if (
                    expected_authoritative_attempt_id is not None
                    and prior_attempt_id != expected_authoritative_attempt_id
                ):
                    raise StateConflictError(
                        "retry target is no longer the authoritative Attempt: "
                        f"expected {expected_authoritative_attempt_id}, found {prior_attempt_id}"
                    )
                if prior_attempt_id is not None:
                    await connection.execute(
                        """
                        UPDATE review_attempts
                        SET status = $1
                        WHERE attempt_id = $2::uuid AND status <> $3
                        """,
                        AttemptStatus.SUPERSEDED.value,
                        prior_attempt_id,
                        AttemptStatus.AUDIT_ONLY.value,
                    )
                    await connection.execute(
                        """
                        UPDATE review_jobs
                        SET status = $1
                        WHERE attempt_id = $2::uuid AND status = $3
                        """,
                        JobStatus.SUPERSEDED.value,
                        prior_attempt_id,
                        JobStatus.QUEUED.value,
                    )
                await connection.execute(
                    """
                    UPDATE gate_decisions
                    SET standing = FALSE
                    WHERE installation_id = $1 AND repository = $2
                      AND pull_request_number = $3 AND standing = TRUE
                    """,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                )
                await connection.execute(
                    """
                    UPDATE change_requests
                    SET request_key = $4::jsonb, authoritative_attempt_id = $5::uuid,
                        standing_attempt_id = NULL, standing_gate_state = NULL
                    WHERE installation_id = $1 AND repository = $2
                      AND pull_request_number = $3
                    """,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                    request_key_json,
                    attempt_id,
                )
                await connection.execute(
                    """
                    INSERT INTO review_attempts (
                        attempt_id, installation_id, repository, pull_request_number,
                        request_key, status
                    ) VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6)
                    """,
                    attempt_id,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                    request_key_json,
                    AttemptStatus.QUEUED.value,
                )
                await connection.execute(
                    """
                    INSERT INTO review_jobs (attempt_id, status)
                    VALUES ($1::uuid, $2)
                    """,
                    attempt_id,
                    JobStatus.QUEUED.value,
                )
                if delivery_key is not None:
                    await connection.execute(
                        """
                        INSERT INTO retry_deliveries (
                            installation_id, delivery_id, attempt_id,
                            prior_authoritative_attempt_id
                        ) VALUES ($1, $2, $3::uuid, $4::uuid)
                        """,
                        delivery_key[0],
                        delivery_key[1],
                        attempt_id,
                        prior_attempt_id,
                    )
                await self._append_audit_event_on_connection(
                    connection,
                    event_type="attempt_authoritative",
                    change_request=change_request,
                    attempt_id=attempt_id,
                    payload={
                        "prior_attempt_id": prior_attempt_id,
                        "delivery_id": delivery_id,
                    },
                )
        return AttemptLease(
            attempt_id=attempt_id,
            change_request=change_request,
            request_key=request_key,
            prior_authoritative_attempt_id=prior_attempt_id,
        )

    async def record_review_identity(
        self,
        *,
        attempt_id: str,
        review_identity: ReviewIdentity,
    ) -> None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                attempt_row = await connection.fetchrow(
                    """
                    SELECT request_key, review_identity
                    FROM review_attempts
                    WHERE attempt_id = $1::uuid
                    FOR UPDATE
                    """,
                    attempt_id,
                )
                if attempt_row is None:
                    raise StateConflictError(f"unknown Attempt: {attempt_id}")
                request_key = ReviewRequestKey.model_validate(
                    _json_object(attempt_row["request_key"])
                )
                if not _review_identity_matches_request_key(review_identity, request_key):
                    raise StateConflictError(
                        "Review Identity does not match the Attempt's Review Request Key"
                    )
                if attempt_row["review_identity"] is not None:
                    persisted_identity = ReviewIdentity.model_validate(
                        _json_object(attempt_row["review_identity"])
                    )
                    if persisted_identity != review_identity:
                        raise StateConflictError("Review Identity for an Attempt is immutable")
                await connection.execute(
                    """
                    UPDATE review_attempts
                    SET review_identity = $2::jsonb
                    WHERE attempt_id = $1::uuid
                    """,
                    attempt_id,
                    review_identity.model_dump_json(),
                )

    async def claim_attempt_job(self, attempt_id: str) -> AttemptLease | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT
                        a.attempt_id, a.installation_id, a.repository,
                        a.pull_request_number, a.request_key,
                        c.authoritative_attempt_id
                    FROM review_attempts AS a
                    JOIN change_requests AS c
                      ON c.installation_id = a.installation_id
                     AND c.repository = a.repository
                     AND c.pull_request_number = a.pull_request_number
                    JOIN review_jobs AS j ON j.attempt_id = a.attempt_id
                    WHERE a.attempt_id = $1::uuid AND j.status = $2
                    FOR UPDATE OF a, j, c
                    """,
                    attempt_id,
                    JobStatus.QUEUED.value,
                )
                if row is None:
                    return None
                if str(row["authoritative_attempt_id"]) != attempt_id:
                    await connection.execute(
                        "UPDATE review_jobs SET status = $1 WHERE attempt_id = $2::uuid",
                        JobStatus.SUPERSEDED.value,
                        attempt_id,
                    )
                    await connection.execute(
                        "UPDATE review_attempts SET status = $1 WHERE attempt_id = $2::uuid",
                        AttemptStatus.SUPERSEDED.value,
                        attempt_id,
                    )
                    return None
                await connection.execute(
                    "UPDATE review_jobs SET status = $1 WHERE attempt_id = $2::uuid",
                    JobStatus.RUNNING.value,
                    attempt_id,
                )
                await connection.execute(
                    "UPDATE review_attempts SET status = $1 WHERE attempt_id = $2::uuid",
                    AttemptStatus.RUNNING.value,
                    attempt_id,
                )
                return AttemptLease(
                    attempt_id=attempt_id,
                    change_request=GitHubChangeRequestLocator(
                        installation_id=row["installation_id"],
                        repository=row["repository"],
                        pull_request_number=row["pull_request_number"],
                    ),
                    request_key=ReviewRequestKey.model_validate(_json_object(row["request_key"])),
                )

    async def publish_if_authoritative(
        self,
        *,
        attempt_id: str,
        request_key: ReviewRequestKey,
        review_identity: ReviewIdentity | None,
        gate_state: GateState,
    ) -> PublishResult:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                attempt_row = await connection.fetchrow(
                    """
                    SELECT installation_id, repository, pull_request_number,
                           request_key, review_identity, status
                    FROM review_attempts
                    WHERE attempt_id = $1::uuid
                    FOR UPDATE
                    """,
                    attempt_id,
                )
                if attempt_row is None:
                    raise StateConflictError(f"unknown Attempt: {attempt_id}")
                change_request_row = await connection.fetchrow(
                    """
                    SELECT request_key, authoritative_attempt_id,
                           standing_attempt_id, standing_gate_state
                    FROM change_requests
                    WHERE installation_id = $1 AND repository = $2
                      AND pull_request_number = $3
                    FOR UPDATE
                    """,
                    attempt_row["installation_id"],
                    attempt_row["repository"],
                    attempt_row["pull_request_number"],
                )
                if change_request_row is None:
                    raise StateConflictError("change request disappeared before publication")
                persisted_attempt_key = ReviewRequestKey.model_validate(
                    _json_object(attempt_row["request_key"])
                )
                current_request_key = ReviewRequestKey.model_validate(
                    _json_object(change_request_row["request_key"])
                )
                persisted_identity = (
                    None
                    if attempt_row["review_identity"] is None
                    else ReviewIdentity.model_validate(_json_object(attempt_row["review_identity"]))
                )
                change_request = GitHubChangeRequestLocator(
                    installation_id=attempt_row["installation_id"],
                    repository=attempt_row["repository"],
                    pull_request_number=attempt_row["pull_request_number"],
                )
                is_authoritative = str(change_request_row["authoritative_attempt_id"]) == attempt_id
                identities_match = persisted_identity == review_identity
                if persisted_identity is not None:
                    identities_match = identities_match and _review_identity_matches_request_key(
                        persisted_identity,
                        request_key,
                    )
                publication_inputs_match = (
                    is_authoritative
                    and current_request_key == request_key
                    and persisted_attempt_key == request_key
                    and identities_match
                )
                attempt_status = AttemptStatus(attempt_row["status"])
                current_standing_attempt_id = change_request_row["standing_attempt_id"]
                if attempt_status is AttemptStatus.PUBLISHED:
                    if (
                        publication_inputs_match
                        and current_standing_attempt_id is not None
                        and str(current_standing_attempt_id) == attempt_id
                    ):
                        published_gate_state_value = change_request_row["standing_gate_state"]
                        if published_gate_state_value is None:
                            raise StateConflictError(
                                "published Attempt has no persisted standing gate state"
                            )
                        published_gate_state = GateState(published_gate_state_value)
                        if published_gate_state is not gate_state:
                            raise StateConflictError(
                                "published Attempt cannot be changed to a different gate state"
                            )
                        return PublishResult(
                            disposition=PublishDisposition.PUBLISHED,
                            attempt_id=attempt_id,
                            gate_state=published_gate_state,
                            detail="authoritative gate decision was already published",
                        )
                    if publication_inputs_match:
                        raise StateConflictError(
                            "published Attempt is no longer the standing authoritative Attempt"
                        )

                if attempt_status is not AttemptStatus.RUNNING:
                    if publication_inputs_match:
                        raise StateConflictError(
                            "Attempt must be running before its gate decision can be published"
                        )
                    if attempt_status is AttemptStatus.AUDIT_ONLY:
                        return PublishResult(
                            disposition=PublishDisposition.SUPERSEDED,
                            attempt_id=attempt_id,
                            detail="Attempt was superseded before publication",
                        )
                if not publication_inputs_match:
                    await connection.execute(
                        "UPDATE review_attempts SET status = $1 WHERE attempt_id = $2::uuid",
                        AttemptStatus.AUDIT_ONLY.value,
                        attempt_id,
                    )
                    await connection.execute(
                        "UPDATE review_jobs SET status = $1 WHERE attempt_id = $2::uuid",
                        JobStatus.COMPLETED.value,
                        attempt_id,
                    )
                    await self._append_audit_event_on_connection(
                        connection,
                        event_type="attempt_publish_superseded",
                        change_request=GitHubChangeRequestLocator(
                            installation_id=attempt_row["installation_id"],
                            repository=attempt_row["repository"],
                            pull_request_number=attempt_row["pull_request_number"],
                        ),
                        attempt_id=attempt_id,
                        payload={"detail": "Attempt was superseded before publication"},
                    )
                    return PublishResult(
                        disposition=PublishDisposition.SUPERSEDED,
                        attempt_id=attempt_id,
                        detail="Attempt was superseded before publication",
                    )
                await connection.execute(
                    """
                    UPDATE gate_decisions
                    SET standing = FALSE
                    WHERE installation_id = $1 AND repository = $2
                      AND pull_request_number = $3 AND standing = TRUE
                    """,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                )
                await connection.execute(
                    """
                    INSERT INTO gate_decisions (
                        installation_id, repository, pull_request_number,
                        attempt_id, request_key, review_identity, gate_state, standing
                    ) VALUES ($1, $2, $3, $4::uuid, $5::jsonb, $6::jsonb, $7, TRUE)
                    """,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                    attempt_id,
                    request_key.model_dump_json(),
                    None if review_identity is None else review_identity.model_dump_json(),
                    gate_state.value,
                )
                await connection.execute(
                    """
                    UPDATE change_requests
                    SET standing_attempt_id = $4::uuid, standing_gate_state = $5
                    WHERE installation_id = $1 AND repository = $2
                      AND pull_request_number = $3
                    """,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                    attempt_id,
                    gate_state.value,
                )
                await connection.execute(
                    "UPDATE review_attempts SET status = $1 WHERE attempt_id = $2::uuid",
                    AttemptStatus.PUBLISHED.value,
                    attempt_id,
                )
                await connection.execute(
                    "UPDATE review_jobs SET status = $1 WHERE attempt_id = $2::uuid",
                    JobStatus.COMPLETED.value,
                    attempt_id,
                )
                await self._append_audit_event_on_connection(
                    connection,
                    event_type="standing_decision_published",
                    change_request=change_request,
                    attempt_id=attempt_id,
                    payload={"gate_state": gate_state.value},
                )
                return PublishResult(
                    disposition=PublishDisposition.PUBLISHED,
                    attempt_id=attempt_id,
                    gate_state=gate_state,
                    detail="authoritative gate decision published",
                )

    async def get_change_request_state(
        self,
        change_request: GitHubChangeRequestLocator,
    ) -> AuthoritativeChangeRequestState:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT request_key, authoritative_attempt_id,
                       standing_attempt_id, standing_gate_state
                FROM change_requests
                WHERE installation_id = $1 AND repository = $2
                  AND pull_request_number = $3
                """,
                change_request.installation_id,
                change_request.repository,
                change_request.pull_request_number,
            )
        if row is None:
            return AuthoritativeChangeRequestState(change_request=change_request)
        return AuthoritativeChangeRequestState(
            change_request=change_request,
            request_key=ReviewRequestKey.model_validate(_json_object(row["request_key"])),
            authoritative_attempt_id=str(row["authoritative_attempt_id"]),
            standing_attempt_id=(
                None if row["standing_attempt_id"] is None else str(row["standing_attempt_id"])
            ),
            standing_gate_state=(
                None
                if row["standing_gate_state"] is None
                else GateState(row["standing_gate_state"])
            ),
        )

    async def append_audit_event(
        self,
        *,
        event_type: str,
        change_request: GitHubChangeRequestLocator,
        attempt_id: str | None,
        payload: dict[str, object],
    ) -> None:
        async with self._pool.acquire() as connection:
            await self._append_audit_event_on_connection(
                connection,
                event_type=event_type,
                change_request=change_request,
                attempt_id=attempt_id,
                payload=payload,
            )

    async def _append_audit_event_on_connection(
        self,
        connection: asyncpg.Connection,
        *,
        event_type: str,
        change_request: GitHubChangeRequestLocator,
        attempt_id: str | None,
        payload: dict[str, object],
    ) -> None:
        await connection.execute(
            """
            INSERT INTO audit_events (
                event_type, installation_id, repository, pull_request_number,
                attempt_id, payload
            ) VALUES ($1, $2, $3, $4, $5::uuid, $6::jsonb)
            """,
            event_type,
            change_request.installation_id,
            change_request.repository,
            change_request.pull_request_number,
            attempt_id,
            json.dumps(payload, sort_keys=True),
        )
