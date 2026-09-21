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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from worktree_review.core.identity import ReviewIdentity, ReviewRequestKey
from worktree_review.core.report import GateState
from worktree_review.server.audit import (
    AuditEvent,
    AuditEventPage,
    assert_safe_audit_payload,
    clamp_audit_page_size,
    parse_audit_cursor,
)

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
    """Durable job lifecycle: queued → running → completed | retryable → queued → failed.

    - QUEUED: claimable by a worker.
    - RUNNING: claimed; carries a lease (updated_at). A stale lease is recoverable.
    - RETRYABLE: execution raised; will be requeued while attempts remain.
    - COMPLETED: terminal; pipeline reached a terminal report and CAS finished.
    - FAILED: terminal; retry budget exhausted. Queryable, never silently stuck.
    - SUPERSEDED: terminal; a newer Attempt took authority.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUPERSEDED = "superseded"
    COMPLETED = "completed"
    RETRYABLE = "retryable"
    FAILED = "failed"


@dataclass(frozen=True)
class JobRecoveryReport:
    """Outcome of one recovery pass over retryable and stale-leased jobs."""

    requeued: tuple[str, ...] = ()
    lease_recovered: tuple[str, ...] = ()
    exhausted: tuple[str, ...] = ()


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
    lease_recovered: bool = False


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
    standing_revision: int = 0


class StateConflictError(RuntimeError):
    """A caller attempted an impossible or stale state transition."""


class BypassStatus(StrEnum):
    """Lifecycle of one per-finding risk acceptance (PRD §16)."""

    ACTIVE = "active"
    INVALIDATED = "invalidated"


class CheckSyncStatus(StrEnum):
    """Lifecycle of one standing Check synchronization intent (P3 §7)."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    PUBLISHED = "published"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    # Only ever means "this surface has no platform Check"; never a cover for
    # an unsynced GitHub Attempt.
    NOT_APPLICABLE = "not_applicable"


class BypassRecord(BaseModel):
    """Authorized per-finding risk acceptance bound to one Review Identity.

    The actor is split into the stable GitHub numeric user ID (the
    authorization correlation key) and the login captured at grant time
    (display only). The risk snapshot describes severity, band, and evidence
    locations; it never carries quoted source text. ``risk_digest`` is the
    SHA-256 of the canonical snapshot JSON: two snapshots are "substantively
    unchanged" only when every field matches.
    """

    model_config = ConfigDict(frozen=True)

    bypass_id: int = Field(ge=1)
    change_request: GitHubChangeRequestLocator
    attempt_id: str = Field(min_length=1)
    finding_fingerprint: str = Field(min_length=1)
    actor_id: int | None = Field(default=None, gt=0)
    actor_login: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    review_identity: ReviewIdentity
    review_policy_sha256: str = Field(min_length=1)
    risk_snapshot: dict[str, object]
    risk_digest: str = Field(min_length=1)
    status: BypassStatus = BypassStatus.ACTIVE
    invalidation_reason: str | None = None
    created_at: datetime
    invalidated_at: datetime | None = None


class BypassApplyResult(BaseModel):
    """Outcome of one transactional bypass write against the standing Attempt."""

    model_config = ConfigDict(frozen=True)

    record: BypassRecord
    standing_gate_state: GateState | None
    standing_revision: int = Field(ge=0)
    active_bypass_fingerprints: tuple[str, ...]
    remaining_blocking_count: int = Field(ge=0)
    check_sync_status: CheckSyncStatus
    gate_transitioned: bool = False
    replayed: bool = False


class StandingCheckSyncIntent(BaseModel):
    """One durable intent to PATCH the Attempt's existing Check to the current
    standing revision. Created in the same transaction as the standing change."""

    model_config = ConfigDict(frozen=True)

    intent_id: int = Field(ge=1)
    attempt_id: str = Field(min_length=1)
    standing_revision: int = Field(ge=0)
    check_run_id: int | None = None
    intent: str = Field(min_length=1)
    status: CheckSyncStatus
    attempt_count: int = Field(ge=0)
    next_retry_at: datetime | None = None
    last_error: str | None = None
    lease_expires_at: datetime | None = None
    payload: dict[str, object]
    created_at: datetime
    updated_at: datetime


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

    async def mark_job_retryable(self, *, attempt_id: str, error: str) -> None:
        """Move a RUNNING job to RETRYABLE after an execution exception."""
        ...

    async def recover_interrupted_jobs(
        self,
        *,
        max_attempts: int,
        lease_seconds: float,
    ) -> JobRecoveryReport:
        """Requeue RETRYABLE jobs and stale RUNNING leases; exhaust to FAILED."""
        ...

    async def finalize_attempt_job(
        self, attempt_id: str, *, status: JobStatus, reason: str
    ) -> None:
        """Force a non-terminal job into a terminal state (e.g. publication exhausted)."""
        ...

    async def job_status(self, attempt_id: str) -> JobStatus | None:
        """Current durable job state for one Attempt (diagnostics/recovery)."""
        ...

    async def job_last_error(self, attempt_id: str) -> str | None:
        """Last recorded job error detail (already bounded at write time)."""
        ...

    async def job_status_counts(self) -> dict[str, int]:
        """Count of durable jobs per status, across all attempts."""
        ...

    async def job_ids_with_status(self, status: JobStatus) -> tuple[str, ...]:
        """Attempt ids whose durable job currently holds the given status."""
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
        actor_id: int | None = None,
        actor_login: str | None = None,
    ) -> None: ...

    async def list_audit_events(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        event_type: str | None = None,
        attempt_id: str | None = None,
        repository: str | None = None,
        pull_request_number: int | None = None,
        installation_ids: tuple[int, ...] | None = None,
    ) -> AuditEventPage:
        """Newest-first keyset page of append-only audit events (D9).

        When ``installation_ids`` is provided, only events from those
        installations are returned — authorization and query must share the
        same installation set so a readable role on one installation cannot
        leak events from another.
        """
        ...

    async def audit_installations_for_repository(self, repository: str) -> tuple[int, ...]:
        """Installation IDs that have audit rows for one repository (read-scope checks)."""
        ...

    async def invalidate_standing_decision(
        self,
        change_request: GitHubChangeRequestLocator,
        *,
        reason: str,
    ) -> None: ...

    async def invalidate_standing_for_target(
        self, *, repository: str, target_ref: str, reason: str
    ) -> int: ...

    async def apply_finding_bypass(
        self,
        *,
        change_request: GitHubChangeRequestLocator,
        attempt_id: str,
        finding_fingerprint: str,
        actor_id: int | None,
        actor_login: str,
        reason: str,
        review_identity: ReviewIdentity,
        review_policy_sha256: str,
        blocking_fingerprints: tuple[str, ...],
        risk_snapshot: dict[str, object],
        risk_digest: str,
        check_run_id: int | None,
    ) -> BypassApplyResult:
        """CAS one per-finding bypass against the standing authoritative Attempt.

        One transaction: re-verify authority/standing/identity → insert the
        unique bypass → append the audit event → recompute the standing gate →
        bump ``standing_revision`` → enqueue the standing Check sync intent.
        Replays of the same (attempt, fingerprint, actor, reason) return the
        original record, but only after the standing checks pass.
        """
        ...

    async def list_bypasses(self, *, attempt_id: str) -> tuple[BypassRecord, ...]:
        """Return all bypass records for one Attempt, oldest first."""
        ...

    async def claim_standing_check_sync(
        self, *, now: datetime, lease_seconds: float
    ) -> StandingCheckSyncIntent | None:
        """Claim the oldest deliverable standing Check sync intent."""
        ...

    async def mark_standing_check_sync(
        self,
        intent_id: int,
        *,
        status: CheckSyncStatus,
        last_error: str | None = None,
        next_retry_at: datetime | None = None,
    ) -> None:
        """Record the outcome of one claimed standing Check sync intent."""
        ...

    async def list_pending_standing_check_syncs(
        self, *, now: datetime
    ) -> tuple[StandingCheckSyncIntent, ...]:
        """Intents awaiting delivery or with expired leases (recovery sweep)."""
        ...

    async def latest_standing_check_sync(
        self, *, attempt_id: str
    ) -> StandingCheckSyncIntent | None:
        """The newest standing Check sync intent for one Attempt, if any."""
        ...


def _scrub_job_error(error: str) -> str:
    """job.last_error is served to the browser: scrub credentials, bound length."""
    from worktree_review.application.review_events import scrub_secret_content

    return scrub_secret_content(error)[:1024]


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
    retry_count: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_error: str | None = None


@dataclass
class _MutableChangeRequest:
    change_request: GitHubChangeRequestLocator
    request_key: ReviewRequestKey
    authoritative_attempt_id: str
    standing_attempt_id: str | None = None
    standing_gate_state: GateState | None = None
    standing_revision: int = 0


def _delivery_key(installation_id: int, delivery_id: str) -> tuple[int, str]:
    if not delivery_id:
        raise StateConflictError("GitHub delivery ID must not be empty")
    return installation_id, delivery_id


async def _lock_change_request(
    connection: asyncpg.Connection, change_request: GitHubChangeRequestLocator
) -> None:
    """Serialize all multi-row transitions for one change request (P3 §5.3).

    Every transaction that touches both ``review_attempts`` and
    ``change_requests`` takes this transaction-scoped advisory lock first, so
    the row-lock order inside can never deadlock across paths.
    """

    key = (
        f"change-request:{change_request.installation_id}:"
        f"{change_request.repository}:{change_request.pull_request_number}"
    )
    await connection.fetchval("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", key)


class InMemoryAuthoritativeAttemptStore:
    """Small transactional model for race tests and local server development."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        lease_seconds: float = 1800.0,
    ) -> None:
        self._lock = asyncio.Lock()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lease_seconds = lease_seconds
        self._change_requests: dict[GitHubChangeRequestLocator, _MutableChangeRequest] = {}
        self._attempts: dict[str, _MutableAttempt] = {}
        self._jobs: dict[str, _MutableJob] = {}
        self._delivery_attempts: dict[tuple[int, str], AttemptLease] = {}
        self._audit_events: list[AuditEvent] = []
        self._next_audit_event_id = 1
        self._bypasses: dict[tuple[str, str], BypassRecord] = {}
        self._next_bypass_id = 1
        self._standing_check_intents: dict[int, StandingCheckSyncIntent] = {}
        self._next_check_intent_id = 1

    def _record_audit_event_locked(
        self,
        *,
        event_type: str,
        change_request: GitHubChangeRequestLocator,
        attempt_id: str | None,
        payload: dict[str, object],
        actor_id: int | None = None,
        actor_login: str | None = None,
    ) -> None:
        """Append one sanitized audit event. Caller holds the lock."""

        assert_safe_audit_payload(payload)
        self._audit_events.append(
            AuditEvent(
                event_id=self._next_audit_event_id,
                event_type=event_type,
                occurred_at=self._clock(),
                installation_id=change_request.installation_id,
                repository=change_request.repository,
                pull_request_number=change_request.pull_request_number,
                attempt_id=attempt_id,
                actor_id=actor_id,
                actor_login=actor_login,
                payload=dict(payload),
            )
        )
        self._next_audit_event_id += 1

    def _locator_for_attempt_locked(self, attempt_id: str) -> GitHubChangeRequestLocator:
        attempt = self._attempts.get(attempt_id)
        if attempt is None:
            raise StateConflictError(f"unknown Attempt: {attempt_id}")
        return attempt.change_request

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
                # A new authoritative Attempt expires every prior bypass: same
                # Review Identity or not, the new candidate is re-reviewed in
                # full and risks must be re-accepted (P3 §5.2).
                self._invalidate_bypasses_locked(
                    change_request,
                    reason="new authoritative Attempt superseded the standing decision",
                )
                self._supersede_standing_check_intents_locked(prior_attempt_id)

            self._change_requests[change_request] = _MutableChangeRequest(
                change_request=change_request,
                request_key=request_key,
                authoritative_attempt_id=attempt_id,
                # Standing revisions are monotonic per change request; losing
                # the prior standing decision is itself a revision.
                standing_revision=(
                    current_state.standing_revision + 1 if current_state is not None else 0
                ),
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
            self._record_audit_event_locked(
                event_type="attempt_authoritative",
                change_request=change_request,
                attempt_id=attempt_id,
                payload={
                    "prior_attempt_id": prior_attempt_id,
                    "delivery_id": delivery_id,
                },
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
            if attempt is None or job is None:
                return None
            lease_recovered = False
            if job.status is JobStatus.RUNNING:
                # A worker died mid-flight: reclaim only after the lease expires.
                stale = (self._clock() - job.updated_at).total_seconds() > self._lease_seconds
                if not stale:
                    return None
                job.retry_count += 1
                job.status = JobStatus.QUEUED
                lease_recovered = True
                self._record_audit_event_locked(
                    event_type="job_lease_recovered",
                    change_request=attempt.change_request,
                    attempt_id=attempt_id,
                    payload={"retry_count": job.retry_count},
                )
            if job.status is not JobStatus.QUEUED:
                return None
            change_request = self._change_requests[attempt.change_request]
            if change_request.authoritative_attempt_id != attempt_id:
                job.status = JobStatus.SUPERSEDED
                job.updated_at = self._clock()
                attempt.status = AttemptStatus.SUPERSEDED
                return None
            job.status = JobStatus.RUNNING
            job.updated_at = self._clock()
            attempt.status = AttemptStatus.RUNNING
            return AttemptLease(
                attempt_id=attempt.attempt_id,
                change_request=attempt.change_request,
                request_key=attempt.request_key,
                lease_recovered=lease_recovered,
            )

    async def mark_job_retryable(self, *, attempt_id: str, error: str) -> None:
        async with self._lock:
            job = self._jobs.get(attempt_id)
            if job is None or job.status is not JobStatus.RUNNING:
                return
            job.status = JobStatus.RETRYABLE
            job.retry_count += 1
            job.last_error = _scrub_job_error(error)
            job.updated_at = self._clock()
            self._record_audit_event_locked(
                event_type="job_retryable",
                change_request=self._locator_for_attempt_locked(attempt_id),
                attempt_id=attempt_id,
                payload={"retry_count": job.retry_count, "error": job.last_error},
            )

    async def recover_interrupted_jobs(
        self,
        *,
        max_attempts: int,
        lease_seconds: float,
    ) -> JobRecoveryReport:
        async with self._lock:
            requeued: list[str] = []
            lease_recovered: list[str] = []
            exhausted: list[str] = []
            now = self._clock()
            for job in self._jobs.values():
                if job.status is JobStatus.RETRYABLE:
                    if job.retry_count >= max_attempts:
                        job.status = JobStatus.FAILED
                        job.updated_at = now
                        exhausted.append(job.attempt_id)
                        self._record_audit_event_locked(
                            event_type="job_failed",
                            change_request=self._locator_for_attempt_locked(job.attempt_id),
                            attempt_id=job.attempt_id,
                            payload={
                                "retry_count": job.retry_count,
                                "last_error": job.last_error,
                            },
                        )
                    else:
                        job.status = JobStatus.QUEUED
                        job.updated_at = now
                        requeued.append(job.attempt_id)
                elif job.status is JobStatus.RUNNING:
                    stale = (now - job.updated_at).total_seconds() > lease_seconds
                    if not stale:
                        continue
                    job.retry_count += 1
                    job.updated_at = now
                    if job.retry_count >= max_attempts:
                        job.status = JobStatus.FAILED
                        exhausted.append(job.attempt_id)
                        self._record_audit_event_locked(
                            event_type="job_failed",
                            change_request=self._locator_for_attempt_locked(job.attempt_id),
                            attempt_id=job.attempt_id,
                            payload={
                                "retry_count": job.retry_count,
                                "reason": "lease expired without recovery",
                            },
                        )
                    else:
                        job.status = JobStatus.QUEUED
                        lease_recovered.append(job.attempt_id)
                        self._record_audit_event_locked(
                            event_type="job_lease_recovered",
                            change_request=self._locator_for_attempt_locked(job.attempt_id),
                            attempt_id=job.attempt_id,
                            payload={"retry_count": job.retry_count},
                        )
            return JobRecoveryReport(
                requeued=tuple(requeued),
                lease_recovered=tuple(lease_recovered),
                exhausted=tuple(exhausted),
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
                if job is not None and job.status in (
                    JobStatus.QUEUED,
                    JobStatus.RUNNING,
                    JobStatus.RETRYABLE,
                ):
                    job.status = JobStatus.COMPLETED
                    job.updated_at = self._clock()
                detail = "Attempt was superseded before publication"
                self._record_audit_event_locked(
                    event_type="attempt_publish_superseded",
                    change_request=attempt.change_request,
                    attempt_id=attempt_id,
                    payload={"detail": detail},
                )
                return PublishResult(
                    disposition=PublishDisposition.SUPERSEDED,
                    attempt_id=attempt_id,
                    detail=detail,
                )

            attempt.status = AttemptStatus.PUBLISHED
            job = self._jobs.get(attempt_id)
            if job is not None and job.status in (
                JobStatus.QUEUED,
                JobStatus.RUNNING,
                JobStatus.RETRYABLE,
            ):
                job.status = JobStatus.COMPLETED
                job.updated_at = self._clock()
            current_state.standing_attempt_id = attempt_id
            current_state.standing_gate_state = gate_state
            current_state.standing_revision += 1
            self._record_audit_event_locked(
                event_type="standing_decision_published",
                change_request=attempt.change_request,
                attempt_id=attempt_id,
                payload={"gate_state": gate_state.value},
            )
            return PublishResult(
                disposition=PublishDisposition.PUBLISHED,
                attempt_id=attempt_id,
                gate_state=gate_state,
                detail="authoritative gate decision published",
            )

    async def finalize_attempt_job(
        self, attempt_id: str, *, status: JobStatus, reason: str
    ) -> None:
        if status not in (JobStatus.COMPLETED, JobStatus.FAILED):
            raise StateConflictError("finalize_attempt_job requires a terminal status")
        async with self._lock:
            job = self._jobs.get(attempt_id)
            if job is None or job.status in (
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.SUPERSEDED,
            ):
                return
            job.status = status
            job.last_error = _scrub_job_error(reason)
            job.updated_at = self._clock()
            self._record_audit_event_locked(
                event_type="job_finalized",
                change_request=self._locator_for_attempt_locked(attempt_id),
                attempt_id=attempt_id,
                payload={"status": status.value, "reason": _scrub_job_error(reason)},
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
                standing_revision=current_state.standing_revision,
            )

    async def append_audit_event(
        self,
        *,
        event_type: str,
        change_request: GitHubChangeRequestLocator,
        attempt_id: str | None,
        payload: dict[str, object],
        actor_id: int | None = None,
        actor_login: str | None = None,
    ) -> None:
        async with self._lock:
            self._record_audit_event_locked(
                event_type=event_type,
                change_request=change_request,
                attempt_id=attempt_id,
                payload=payload,
                actor_id=actor_id,
                actor_login=actor_login,
            )

    async def audit_events(self) -> tuple[dict[str, object], ...]:
        """Back-compatible dict view used by concurrency tests."""
        async with self._lock:
            return tuple(
                {
                    "event_type": event.event_type,
                    "change_request": {
                        "installation_id": event.installation_id,
                        "repository": event.repository,
                        "pull_request_number": event.pull_request_number,
                    },
                    "attempt_id": event.attempt_id,
                    "actor_id": event.actor_id,
                    "actor_login": event.actor_login,
                    "payload": event.payload,
                }
                for event in self._audit_events
            )

    async def list_audit_events(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        event_type: str | None = None,
        attempt_id: str | None = None,
        repository: str | None = None,
        pull_request_number: int | None = None,
        installation_ids: tuple[int, ...] | None = None,
    ) -> AuditEventPage:
        cursor_id = parse_audit_cursor(cursor)
        allowed_installations = None if installation_ids is None else frozenset(installation_ids)
        async with self._lock:
            matching = [
                event
                for event in self._audit_events
                if (cursor_id is None or event.event_id < cursor_id)
                and (event_type is None or event.event_type == event_type)
                and (attempt_id is None or event.attempt_id == attempt_id)
                and (repository is None or event.repository == repository)
                and (
                    pull_request_number is None or event.pull_request_number == pull_request_number
                )
                and (
                    allowed_installations is None or event.installation_id in allowed_installations
                )
            ]
            matching.sort(key=lambda event: event.event_id, reverse=True)
            page_size = clamp_audit_page_size(limit)
            page = matching[:page_size]
            next_cursor = str(page[-1].event_id) if len(matching) > page_size and page else None
            return AuditEventPage(events=tuple(page), next_cursor=next_cursor)

    async def audit_installations_for_repository(self, repository: str) -> tuple[int, ...]:
        async with self._lock:
            return tuple(
                dict.fromkeys(
                    event.installation_id
                    for event in self._audit_events
                    if event.repository == repository
                )
            )

    async def job_status(self, attempt_id: str) -> JobStatus | None:
        async with self._lock:
            job = self._jobs.get(attempt_id)
            return None if job is None else job.status

    async def job_last_error(self, attempt_id: str) -> str | None:
        async with self._lock:
            job = self._jobs.get(attempt_id)
            return None if job is None else job.last_error

    async def job_status_counts(self) -> dict[str, int]:
        async with self._lock:
            counts: dict[str, int] = {}
            for job in self._jobs.values():
                counts[job.status.value] = counts.get(job.status.value, 0) + 1
            return counts

    async def job_ids_with_status(self, status: JobStatus) -> tuple[str, ...]:
        async with self._lock:
            return tuple(job.attempt_id for job in self._jobs.values() if job.status is status)

    async def invalidate_standing_decision(
        self,
        change_request: GitHubChangeRequestLocator,
        *,
        reason: str,
    ) -> None:
        async with self._lock:
            current_state = self._change_requests.get(change_request)
            if current_state is None:
                return
            prior_standing = current_state.standing_attempt_id
            current_state.standing_attempt_id = None
            current_state.standing_gate_state = None
            current_state.standing_revision += 1
            self._invalidate_bypasses_locked(change_request, reason=reason)
            if prior_standing is not None:
                self._supersede_standing_check_intents_locked(prior_standing)
            self._record_audit_event_locked(
                event_type="standing_decision_invalidated",
                change_request=change_request,
                attempt_id=prior_standing,
                payload={"reason": reason},
            )

    async def invalidate_standing_for_target(
        self, *, repository: str, target_ref: str, reason: str
    ) -> int:
        count = 0
        aliases = {target_ref, f"refs/heads/{target_ref}"}
        if target_ref.startswith("refs/heads/"):
            aliases.add(target_ref.removeprefix("refs/heads/"))
        for locator, current_state in list(self._change_requests.items()):
            if locator.repository != repository:
                continue
            if current_state.request_key.target_ref not in aliases:
                continue
            await self.invalidate_standing_decision(locator, reason=reason)
            count += 1
        return count

    def _active_bypass_fingerprints(self, attempt_id: str) -> tuple[str, ...]:
        return tuple(
            record.finding_fingerprint
            for record in self._bypasses.values()
            if record.attempt_id == attempt_id and record.status is BypassStatus.ACTIVE
        )

    def _invalidate_bypasses_locked(
        self,
        change_request: GitHubChangeRequestLocator,
        *,
        reason: str,
    ) -> None:
        """Mark every active bypass on the change request expired. Caller holds the lock."""

        for key, record in list(self._bypasses.items()):
            if record.change_request != change_request or record.status is not BypassStatus.ACTIVE:
                continue
            self._bypasses[key] = record.model_copy(
                update={
                    "status": BypassStatus.INVALIDATED,
                    "invalidation_reason": reason,
                    "invalidated_at": self._clock(),
                }
            )
            self._record_audit_event_locked(
                event_type="bypass_invalidated",
                change_request=change_request,
                attempt_id=record.attempt_id,
                actor_id=record.actor_id,
                actor_login=record.actor_login,
                payload={
                    "finding_fingerprint": record.finding_fingerprint,
                    "reason": reason,
                },
            )

    def _enqueue_standing_check_intent_locked(
        self,
        *,
        attempt_id: str,
        standing_revision: int,
        check_run_id: int | None,
        payload: dict[str, object],
    ) -> CheckSyncStatus:
        """Create the durable Check sync intent for the new standing revision.

        Older intents for the same Attempt are terminal-superseded; only the
        current revision is ever delivered.
        """

        self._supersede_standing_check_intents_locked(attempt_id)
        now = self._clock()
        deliverable = check_run_id is not None
        intent = StandingCheckSyncIntent(
            intent_id=self._next_check_intent_id,
            attempt_id=attempt_id,
            standing_revision=standing_revision,
            check_run_id=check_run_id,
            intent="standing_check_sync",
            status=CheckSyncStatus.QUEUED if deliverable else CheckSyncStatus.NOT_APPLICABLE,
            attempt_count=0,
            payload=payload,
            created_at=now,
            updated_at=now,
        )
        self._standing_check_intents[intent.intent_id] = intent
        self._next_check_intent_id += 1
        return intent.status

    def _supersede_standing_check_intents_locked(self, attempt_id: str) -> None:
        now = self._clock()
        for intent_id, intent in list(self._standing_check_intents.items()):
            if intent.attempt_id != attempt_id or intent.status not in (
                CheckSyncStatus.QUEUED,
                CheckSyncStatus.IN_PROGRESS,
            ):
                continue
            self._standing_check_intents[intent_id] = intent.model_copy(
                update={"status": CheckSyncStatus.SUPERSEDED, "updated_at": now}
            )

    async def apply_finding_bypass(
        self,
        *,
        change_request: GitHubChangeRequestLocator,
        attempt_id: str,
        finding_fingerprint: str,
        actor_id: int | None,
        actor_login: str,
        reason: str,
        review_identity: ReviewIdentity,
        review_policy_sha256: str,
        blocking_fingerprints: tuple[str, ...],
        risk_snapshot: dict[str, object],
        risk_digest: str,
        check_run_id: int | None,
    ) -> BypassApplyResult:
        async with self._lock:
            attempt = self._attempts.get(attempt_id)
            if attempt is None or attempt.change_request != change_request:
                raise StateConflictError(f"unknown Attempt for change request: {attempt_id}")
            current_state = self._change_requests.get(attempt.change_request)
            if current_state is None:
                raise StateConflictError("change request disappeared before bypass")
            # Standing checks come first: even a legitimate replay must not
            # reach around the latest authority (P3 §5.3).
            if (
                current_state.authoritative_attempt_id != attempt_id
                or current_state.standing_attempt_id != attempt_id
            ):
                raise StateConflictError(
                    "bypass requires the current standing authoritative Attempt"
                )
            if attempt.review_identity is None or attempt.review_identity != review_identity:
                raise StateConflictError(
                    "Review Identity changed; a bypass binds to the identity it was granted on"
                )
            existing = self._bypasses.get((attempt_id, finding_fingerprint))
            if existing is not None:
                if (
                    existing.status is BypassStatus.ACTIVE
                    and existing.actor_id == actor_id
                    and existing.actor_login == actor_login
                    and existing.reason == reason
                ):
                    return BypassApplyResult(
                        record=existing,
                        standing_gate_state=current_state.standing_gate_state,
                        standing_revision=current_state.standing_revision,
                        active_bypass_fingerprints=self._active_bypass_fingerprints(attempt_id),
                        remaining_blocking_count=len(
                            [
                                fingerprint
                                for fingerprint in blocking_fingerprints
                                if fingerprint
                                not in set(self._active_bypass_fingerprints(attempt_id))
                            ]
                        ),
                        check_sync_status=self._latest_check_sync_status_locked(attempt_id),
                        replayed=True,
                    )
                raise StateConflictError(
                    "a different bypass already exists for this finding on this Attempt"
                )
            if current_state.standing_gate_state is not GateState.BLOCKED:
                raise StateConflictError("only a standing Blocked gate accepts finding bypass")
            record = BypassRecord(
                bypass_id=self._next_bypass_id,
                change_request=change_request,
                attempt_id=attempt_id,
                finding_fingerprint=finding_fingerprint,
                actor_id=actor_id,
                actor_login=actor_login,
                reason=reason,
                review_identity=review_identity,
                review_policy_sha256=review_policy_sha256,
                risk_snapshot=risk_snapshot,
                risk_digest=risk_digest,
                created_at=self._clock(),
            )
            self._next_bypass_id += 1
            self._bypasses[(attempt_id, finding_fingerprint)] = record
            self._record_audit_event_locked(
                event_type="bypass_authorized",
                change_request=change_request,
                attempt_id=attempt_id,
                actor_id=actor_id,
                actor_login=actor_login,
                payload={
                    "finding_fingerprint": finding_fingerprint,
                    "reason": reason,
                    "risk_digest": risk_digest,
                },
            )
            active = self._active_bypass_fingerprints(attempt_id)
            remaining = [
                fingerprint
                for fingerprint in blocking_fingerprints
                if fingerprint not in set(active)
            ]
            transitioned = False
            if not remaining:
                current_state.standing_gate_state = GateState.PASSED_WITH_BYPASS
                transitioned = True
                self._record_audit_event_locked(
                    event_type="gate_transition",
                    change_request=change_request,
                    attempt_id=attempt_id,
                    actor_id=actor_id,
                    actor_login=actor_login,
                    payload={
                        "from": GateState.BLOCKED.value,
                        "to": GateState.PASSED_WITH_BYPASS.value,
                        "cause": "finding_bypass",
                    },
                )
            current_state.standing_revision += 1
            sync_status = self._enqueue_standing_check_intent_locked(
                attempt_id=attempt_id,
                standing_revision=current_state.standing_revision,
                check_run_id=check_run_id,
                payload={
                    "standing_gate_state": current_state.standing_gate_state.value,
                    "accepted_count": len(active),
                    "remaining_blocking_count": len(remaining),
                },
            )
            self._record_audit_event_locked(
                event_type="check_sync_queued",
                change_request=change_request,
                attempt_id=attempt_id,
                payload={
                    "standing_revision": current_state.standing_revision,
                    "check_sync_status": sync_status.value,
                },
            )
            return BypassApplyResult(
                record=record,
                standing_gate_state=current_state.standing_gate_state,
                standing_revision=current_state.standing_revision,
                active_bypass_fingerprints=active,
                remaining_blocking_count=len(remaining),
                check_sync_status=sync_status,
                gate_transitioned=transitioned,
            )

    def _latest_check_sync_status_locked(self, attempt_id: str) -> CheckSyncStatus:
        intents = [
            intent
            for intent in self._standing_check_intents.values()
            if intent.attempt_id == attempt_id
        ]
        if not intents:
            return CheckSyncStatus.NOT_APPLICABLE
        return max(intents, key=lambda intent: intent.standing_revision).status

    async def list_bypasses(self, *, attempt_id: str) -> tuple[BypassRecord, ...]:
        async with self._lock:
            records = [
                record for record in self._bypasses.values() if record.attempt_id == attempt_id
            ]
            return tuple(sorted(records, key=lambda record: record.bypass_id))

    async def claim_standing_check_sync(
        self, *, now: datetime, lease_seconds: float
    ) -> StandingCheckSyncIntent | None:
        async with self._lock:
            candidates = []
            for intent in self._standing_check_intents.values():
                claimable = intent.status is CheckSyncStatus.QUEUED and (
                    intent.next_retry_at is None or intent.next_retry_at <= now
                )
                expired_lease = (
                    intent.status is CheckSyncStatus.IN_PROGRESS
                    and intent.lease_expires_at is not None
                    and intent.lease_expires_at <= now
                )
                if claimable or expired_lease:
                    candidates.append(intent)
            if not candidates:
                return None
            # Only the newest revision per Attempt is ever delivered.
            newest_revision = {intent.attempt_id: intent.standing_revision for intent in candidates}
            for intent in self._standing_check_intents.values():
                if intent.status in (CheckSyncStatus.QUEUED, CheckSyncStatus.IN_PROGRESS):
                    newest_revision[intent.attempt_id] = max(
                        newest_revision.get(intent.attempt_id, 0), intent.standing_revision
                    )
            deliverable = [
                intent
                for intent in candidates
                if intent.standing_revision == newest_revision[intent.attempt_id]
            ]
            if not deliverable:
                return None
            chosen = min(deliverable, key=lambda intent: intent.intent_id)
            claimed = chosen.model_copy(
                update={
                    "status": CheckSyncStatus.IN_PROGRESS,
                    "attempt_count": chosen.attempt_count + 1,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "updated_at": now,
                }
            )
            self._standing_check_intents[chosen.intent_id] = claimed
            return claimed

    async def mark_standing_check_sync(
        self,
        intent_id: int,
        *,
        status: CheckSyncStatus,
        last_error: str | None = None,
        next_retry_at: datetime | None = None,
    ) -> None:
        async with self._lock:
            intent = self._standing_check_intents.get(intent_id)
            if intent is None:
                return
            self._standing_check_intents[intent_id] = intent.model_copy(
                update={
                    "status": status,
                    "last_error": last_error,
                    "next_retry_at": next_retry_at,
                    "lease_expires_at": None,
                    "updated_at": self._clock(),
                }
            )

    async def list_pending_standing_check_syncs(
        self, *, now: datetime
    ) -> tuple[StandingCheckSyncIntent, ...]:
        async with self._lock:
            return tuple(
                intent
                for intent in self._standing_check_intents.values()
                if (
                    intent.status is CheckSyncStatus.QUEUED
                    and (intent.next_retry_at is None or intent.next_retry_at <= now)
                )
                or (
                    intent.status is CheckSyncStatus.IN_PROGRESS
                    and intent.lease_expires_at is not None
                    and intent.lease_expires_at <= now
                )
            )

    async def latest_standing_check_sync(
        self, *, attempt_id: str
    ) -> StandingCheckSyncIntent | None:
        async with self._lock:
            intents = [
                intent
                for intent in self._standing_check_intents.values()
                if intent.attempt_id == attempt_id
            ]
            if not intents:
                return None
            return max(intents, key=lambda intent: intent.standing_revision)


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

ALTER TABLE review_jobs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ
    NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE review_jobs ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE review_jobs ADD COLUMN IF NOT EXISTS last_error TEXT;

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

-- P3: the actor is split into the stable GitHub numeric user ID (correlation
-- key) and the login captured at write time (display only).
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS actor_id BIGINT;
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS actor_login TEXT;

-- P3: monotonic standing decision revision; every standing publish,
-- invalidation, or accepted bypass increments it exactly once.
ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS standing_revision BIGINT
    NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS bypasses (
    bypass_id BIGSERIAL PRIMARY KEY,
    installation_id BIGINT NOT NULL,
    repository TEXT NOT NULL,
    pull_request_number BIGINT NOT NULL,
    attempt_id UUID NOT NULL REFERENCES review_attempts(attempt_id),
    finding_fingerprint TEXT NOT NULL,
    actor_id BIGINT,
    actor_login TEXT NOT NULL,
    reason TEXT NOT NULL,
    review_identity JSONB NOT NULL,
    review_policy_sha256 TEXT NOT NULL,
    risk_snapshot JSONB NOT NULL,
    risk_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    invalidation_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    invalidated_at TIMESTAMPTZ,
    UNIQUE (attempt_id, finding_fingerprint)
);

-- P3: durable intent to PATCH the Attempt's existing Check to the current
-- standing revision. One row per (attempt, revision); older revisions go
-- terminal-superseded and only the newest is ever delivered.
CREATE TABLE IF NOT EXISTS standing_check_outbox (
    intent_id BIGSERIAL PRIMARY KEY,
    attempt_id UUID NOT NULL REFERENCES review_attempts(attempt_id),
    standing_revision BIGINT NOT NULL,
    check_run_id BIGINT,
    intent TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    last_error TEXT,
    lease_expires_at TIMESTAMPTZ,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (attempt_id, standing_revision)
);
"""


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    decoded = json.loads(str(value))
    if not isinstance(decoded, dict):
        raise StateConflictError("persisted state JSON is not an object")
    return decoded


def _aware_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _optional_gate_state(value: object) -> GateState | None:
    return None if value is None else GateState(str(value))


def _audit_event_from_row(row: Mapping[str, Any]) -> AuditEvent:
    return AuditEvent(
        event_id=int(row["event_id"]),
        event_type=str(row["event_type"]),
        occurred_at=_aware_datetime(row["created_at"]),
        installation_id=int(row["installation_id"]),
        repository=str(row["repository"]),
        pull_request_number=int(row["pull_request_number"]),
        attempt_id=None if row["attempt_id"] is None else str(row["attempt_id"]),
        actor_id=None if row["actor_id"] is None else int(row["actor_id"]),
        actor_login=None if row["actor_login"] is None else str(row["actor_login"]),
        payload=_json_object(row["payload"]),
    )


def _bypass_record_from_row(row: Mapping[str, Any]) -> BypassRecord:
    """Assemble a BypassRecord from a bypasses row (asyncpg Record-like mapping)."""

    return BypassRecord(
        bypass_id=int(row["bypass_id"]),
        change_request=GitHubChangeRequestLocator(
            installation_id=int(row["installation_id"]),
            repository=str(row["repository"]),
            pull_request_number=int(row["pull_request_number"]),
        ),
        attempt_id=str(row["attempt_id"]),
        finding_fingerprint=str(row["finding_fingerprint"]),
        actor_id=None if row["actor_id"] is None else int(row["actor_id"]),
        actor_login=str(row["actor_login"]),
        reason=str(row["reason"]),
        review_identity=ReviewIdentity.model_validate(_json_object(row["review_identity"])),
        review_policy_sha256=str(row["review_policy_sha256"]),
        risk_snapshot=_json_object(row["risk_snapshot"]),
        risk_digest=str(row["risk_digest"]),
        status=BypassStatus(str(row["status"])),
        invalidation_reason=(
            None if row["invalidation_reason"] is None else str(row["invalidation_reason"])
        ),
        created_at=_aware_datetime(row["created_at"]),
        invalidated_at=(
            None if row["invalidated_at"] is None else _aware_datetime(row["invalidated_at"])
        ),
    )


def _check_sync_intent_from_row(row: Mapping[str, Any]) -> StandingCheckSyncIntent:
    return StandingCheckSyncIntent(
        intent_id=int(row["intent_id"]),
        attempt_id=str(row["attempt_id"]),
        standing_revision=int(row["standing_revision"]),
        check_run_id=None if row["check_run_id"] is None else int(row["check_run_id"]),
        intent=str(row["intent"]),
        status=CheckSyncStatus(str(row["status"])),
        attempt_count=int(row["attempt_count"]),
        next_retry_at=(
            None if row["next_retry_at"] is None else _aware_datetime(row["next_retry_at"])
        ),
        last_error=None if row["last_error"] is None else str(row["last_error"]),
        lease_expires_at=(
            None if row["lease_expires_at"] is None else _aware_datetime(row["lease_expires_at"])
        ),
        payload=_json_object(row["payload"]),
        created_at=_aware_datetime(row["created_at"]),
        updated_at=_aware_datetime(row["updated_at"]),
    )


class PostgresAuthoritativeAttemptStore:
    """PostgreSQL implementation of the D8 state transitions."""

    def __init__(self, pool: asyncpg.Pool, *, lease_seconds: float = 1800.0) -> None:
        self._pool = pool
        self._lease_seconds = lease_seconds

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
                # Every multi-row transition serializes on the change-request
                # advisory lock first; row locks then never deadlock (P3 §5.3).
                await _lock_change_request(connection, change_request)
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
                        SELECT authoritative_attempt_id, standing_attempt_id
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
                    prior_standing_attempt_id = (
                        None
                        if current_row["standing_attempt_id"] is None
                        else str(current_row["standing_attempt_id"])
                    )
                else:
                    prior_attempt_id = None
                    prior_standing_attempt_id = None
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
                    # A new authoritative Attempt expires every prior bypass:
                    # same identity or not, risks must be re-accepted (P3 §5.2).
                    await self._invalidate_bypasses_on_connection(
                        connection,
                        change_request,
                        reason="new authoritative Attempt superseded the standing decision",
                    )
                    if prior_standing_attempt_id is not None:
                        await self._supersede_standing_check_intents_on_connection(
                            connection, prior_standing_attempt_id
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
                        standing_attempt_id = NULL, standing_gate_state = NULL,
                        standing_revision = standing_revision + $6::bigint
                    WHERE installation_id = $1 AND repository = $2
                      AND pull_request_number = $3
                    """,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                    request_key_json,
                    attempt_id,
                    # Losing the prior standing decision is itself a revision;
                    # a brand-new change request starts at 0.
                    1 if prior_attempt_id is not None else 0,
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
                        c.authoritative_attempt_id,
                        j.status AS job_status, j.updated_at AS job_updated_at,
                        j.retry_count AS job_retry_count
                    FROM review_attempts AS a
                    JOIN change_requests AS c
                      ON c.installation_id = a.installation_id
                     AND c.repository = a.repository
                     AND c.pull_request_number = a.pull_request_number
                    JOIN review_jobs AS j ON j.attempt_id = a.attempt_id
                    WHERE a.attempt_id = $1::uuid
                      AND (j.status = $2
                           OR (j.status = $3 AND j.updated_at
                               < CURRENT_TIMESTAMP - make_interval(secs => $4)))
                    FOR UPDATE OF a, j, c
                    """,
                    attempt_id,
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    self._lease_seconds,
                )
                if row is None:
                    return None
                lease_recovered = row["job_status"] == JobStatus.RUNNING.value
                if lease_recovered:
                    await connection.execute(
                        """
                        UPDATE review_jobs
                        SET status = $2, retry_count = $3, updated_at = CURRENT_TIMESTAMP
                        WHERE attempt_id = $1::uuid
                        """,
                        attempt_id,
                        JobStatus.QUEUED.value,
                        row["job_retry_count"] + 1,
                    )
                    await self._append_audit_event_on_connection(
                        connection,
                        event_type="job_lease_recovered",
                        change_request=GitHubChangeRequestLocator(
                            installation_id=row["installation_id"],
                            repository=row["repository"],
                            pull_request_number=row["pull_request_number"],
                        ),
                        attempt_id=attempt_id,
                        payload={"retry_count": row["job_retry_count"] + 1},
                    )
                if str(row["authoritative_attempt_id"]) != attempt_id:
                    await connection.execute(
                        "UPDATE review_jobs SET status = $1, updated_at = CURRENT_TIMESTAMP "
                        "WHERE attempt_id = $2::uuid",
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
                    "UPDATE review_jobs SET status = $1, updated_at = CURRENT_TIMESTAMP "
                    "WHERE attempt_id = $2::uuid",
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
                    lease_recovered=lease_recovered,
                )

    async def mark_job_retryable(self, *, attempt_id: str, error: str) -> None:
        bounded_error = _scrub_job_error(error)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    UPDATE review_jobs
                    SET status = $2, retry_count = retry_count + 1, last_error = $3,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE attempt_id = $1::uuid AND status = $4
                    RETURNING retry_count
                    """,
                    attempt_id,
                    JobStatus.RETRYABLE.value,
                    bounded_error,
                    JobStatus.RUNNING.value,
                )
                if row is None:
                    return
                attempt_row = await connection.fetchrow(
                    """
                    SELECT installation_id, repository, pull_request_number
                    FROM review_attempts WHERE attempt_id = $1::uuid
                    """,
                    attempt_id,
                )
                if attempt_row is not None:
                    await self._append_audit_event_on_connection(
                        connection,
                        event_type="job_retryable",
                        change_request=GitHubChangeRequestLocator(
                            installation_id=attempt_row["installation_id"],
                            repository=attempt_row["repository"],
                            pull_request_number=attempt_row["pull_request_number"],
                        ),
                        attempt_id=attempt_id,
                        payload={"retry_count": row["retry_count"], "error": bounded_error},
                    )

    async def recover_interrupted_jobs(
        self,
        *,
        max_attempts: int,
        lease_seconds: float,
    ) -> JobRecoveryReport:
        requeued: list[str] = []
        lease_recovered: list[str] = []
        exhausted: list[str] = []
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                rows = await connection.fetch(
                    """
                    SELECT j.attempt_id, j.status, j.retry_count,
                           a.installation_id, a.repository, a.pull_request_number
                    FROM review_jobs AS j
                    JOIN review_attempts AS a ON a.attempt_id = j.attempt_id
                    WHERE j.status = $1
                       OR (j.status = $2 AND j.updated_at
                           < CURRENT_TIMESTAMP - make_interval(secs => $3))
                    FOR UPDATE OF j
                    """,
                    JobStatus.RETRYABLE.value,
                    JobStatus.RUNNING.value,
                    lease_seconds,
                )
                for row in rows:
                    attempt_id = str(row["attempt_id"])
                    retry_count = row["retry_count"]
                    from_stale_lease = row["status"] == JobStatus.RUNNING.value
                    if from_stale_lease:
                        retry_count += 1
                    locator = GitHubChangeRequestLocator(
                        installation_id=row["installation_id"],
                        repository=row["repository"],
                        pull_request_number=row["pull_request_number"],
                    )
                    if retry_count >= max_attempts:
                        await connection.execute(
                            "UPDATE review_jobs SET status = $2, retry_count = $3, "
                            "updated_at = CURRENT_TIMESTAMP WHERE attempt_id = $1::uuid",
                            attempt_id,
                            JobStatus.FAILED.value,
                            retry_count,
                        )
                        exhausted.append(attempt_id)
                        await self._append_audit_event_on_connection(
                            connection,
                            event_type="job_failed",
                            change_request=locator,
                            attempt_id=attempt_id,
                            payload={"retry_count": retry_count},
                        )
                    else:
                        await connection.execute(
                            "UPDATE review_jobs SET status = $2, retry_count = $3, "
                            "updated_at = CURRENT_TIMESTAMP WHERE attempt_id = $1::uuid",
                            attempt_id,
                            JobStatus.QUEUED.value,
                            retry_count,
                        )
                        if from_stale_lease:
                            lease_recovered.append(attempt_id)
                            event_type = "job_lease_recovered"
                        else:
                            requeued.append(attempt_id)
                            event_type = "job_requeued"
                        await self._append_audit_event_on_connection(
                            connection,
                            event_type=event_type,
                            change_request=locator,
                            attempt_id=attempt_id,
                            payload={"retry_count": retry_count},
                        )
        return JobRecoveryReport(
            requeued=tuple(requeued),
            lease_recovered=tuple(lease_recovered),
            exhausted=tuple(exhausted),
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
                # Locate the change request first (unlocked read), then take
                # the shared advisory lock before any row locks (P3 §5.3).
                locator_row = await connection.fetchrow(
                    """
                    SELECT installation_id, repository, pull_request_number
                    FROM review_attempts
                    WHERE attempt_id = $1::uuid
                    """,
                    attempt_id,
                )
                if locator_row is None:
                    raise StateConflictError(f"unknown Attempt: {attempt_id}")
                change_request = GitHubChangeRequestLocator(
                    installation_id=locator_row["installation_id"],
                    repository=locator_row["repository"],
                    pull_request_number=locator_row["pull_request_number"],
                )
                await _lock_change_request(connection, change_request)
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
                        "UPDATE review_jobs SET status = $1, updated_at = CURRENT_TIMESTAMP "
                        "WHERE attempt_id = $2::uuid "
                        "AND status IN ('queued', 'running', 'retryable')",
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
                    SET standing_attempt_id = $4::uuid, standing_gate_state = $5,
                        standing_revision = standing_revision + 1
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
                    "UPDATE review_jobs SET status = $1, updated_at = CURRENT_TIMESTAMP "
                    "WHERE attempt_id = $2::uuid AND status IN ('queued', 'running', 'retryable')",
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

    async def finalize_attempt_job(
        self, attempt_id: str, *, status: JobStatus, reason: str
    ) -> None:
        if status not in (JobStatus.COMPLETED, JobStatus.FAILED):
            raise StateConflictError("finalize_attempt_job requires a terminal status")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                updated = await connection.execute(
                    """
                    UPDATE review_jobs
                    SET status = $2, last_error = $3, updated_at = CURRENT_TIMESTAMP
                    WHERE attempt_id = $1::uuid
                      AND status NOT IN ('completed', 'failed', 'superseded')
                    """,
                    attempt_id,
                    status.value,
                    _scrub_job_error(reason),
                )
                if updated.endswith(" 0"):
                    return
                attempt_row = await connection.fetchrow(
                    """
                    SELECT installation_id, repository, pull_request_number
                    FROM review_attempts WHERE attempt_id = $1::uuid
                    """,
                    attempt_id,
                )
                if attempt_row is not None:
                    await self._append_audit_event_on_connection(
                        connection,
                        event_type="job_finalized",
                        change_request=GitHubChangeRequestLocator(
                            installation_id=attempt_row["installation_id"],
                            repository=attempt_row["repository"],
                            pull_request_number=attempt_row["pull_request_number"],
                        ),
                        attempt_id=attempt_id,
                        payload={"status": status.value, "reason": _scrub_job_error(reason)},
                    )

    async def job_status(self, attempt_id: str) -> JobStatus | None:
        async with self._pool.acquire() as connection:
            value = await connection.fetchval(
                "SELECT status FROM review_jobs WHERE attempt_id = $1::uuid",
                attempt_id,
            )
        return None if value is None else JobStatus(value)

    async def job_last_error(self, attempt_id: str) -> str | None:
        async with self._pool.acquire() as connection:
            value = await connection.fetchval(
                "SELECT last_error FROM review_jobs WHERE attempt_id = $1::uuid",
                attempt_id,
            )
        return None if value is None else str(value)

    async def job_status_counts(self) -> dict[str, int]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT status, COUNT(*) AS count FROM review_jobs GROUP BY status"
            )
        return {str(row["status"]): int(row["count"]) for row in rows}

    async def job_ids_with_status(self, status: JobStatus) -> tuple[str, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT attempt_id FROM review_jobs WHERE status = $1",
                status.value,
            )
        return tuple(str(row["attempt_id"]) for row in rows)

    async def get_change_request_state(
        self,
        change_request: GitHubChangeRequestLocator,
    ) -> AuthoritativeChangeRequestState:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT request_key, authoritative_attempt_id,
                       standing_attempt_id, standing_gate_state, standing_revision
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
            standing_revision=int(row["standing_revision"]),
        )

    async def append_audit_event(
        self,
        *,
        event_type: str,
        change_request: GitHubChangeRequestLocator,
        attempt_id: str | None,
        payload: dict[str, object],
        actor_id: int | None = None,
        actor_login: str | None = None,
    ) -> None:
        async with self._pool.acquire() as connection:
            await self._append_audit_event_on_connection(
                connection,
                event_type=event_type,
                change_request=change_request,
                attempt_id=attempt_id,
                payload=payload,
                actor_id=actor_id,
                actor_login=actor_login,
            )

    async def _append_audit_event_on_connection(
        self,
        connection: asyncpg.Connection,
        *,
        event_type: str,
        change_request: GitHubChangeRequestLocator,
        attempt_id: str | None,
        payload: dict[str, object],
        actor_id: int | None = None,
        actor_login: str | None = None,
    ) -> None:
        assert_safe_audit_payload(payload)
        await connection.execute(
            """
            INSERT INTO audit_events (
                event_type, installation_id, repository, pull_request_number,
                attempt_id, actor_id, actor_login, payload
            ) VALUES ($1, $2, $3, $4, $5::uuid, $6, $7, $8::jsonb)
            """,
            event_type,
            change_request.installation_id,
            change_request.repository,
            change_request.pull_request_number,
            attempt_id,
            actor_id,
            actor_login,
            json.dumps(payload, sort_keys=True),
        )

    async def list_audit_events(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        event_type: str | None = None,
        attempt_id: str | None = None,
        repository: str | None = None,
        pull_request_number: int | None = None,
        installation_ids: tuple[int, ...] | None = None,
    ) -> AuditEventPage:
        cursor_id = parse_audit_cursor(cursor)
        page_size = clamp_audit_page_size(limit)
        # Empty installation allowlist means "no visible installations" — return
        # no rows rather than falling through to an unscoped repository query.
        if installation_ids is not None and len(installation_ids) == 0:
            return AuditEventPage(events=(), next_cursor=None)
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT event_id, event_type, installation_id, repository,
                       pull_request_number, attempt_id, actor_id, actor_login,
                       payload, created_at
                FROM audit_events
                WHERE ($1::bigint IS NULL OR event_id < $1::bigint)
                  AND ($2::text IS NULL OR event_type = $2)
                  AND ($3::uuid IS NULL OR attempt_id = $3::uuid)
                  AND ($4::text IS NULL OR repository = $4)
                  AND ($5::bigint IS NULL OR pull_request_number = $5)
                  AND ($6::bigint[] IS NULL OR installation_id = ANY($6::bigint[]))
                ORDER BY event_id DESC
                LIMIT $7
                """,
                cursor_id,
                event_type,
                attempt_id,
                repository,
                pull_request_number,
                None if installation_ids is None else list(installation_ids),
                page_size + 1,
            )
        has_more = len(rows) > page_size
        page_rows = rows[:page_size]
        events = tuple(_audit_event_from_row(row) for row in page_rows)
        next_cursor = str(page_rows[-1]["event_id"]) if has_more and page_rows else None
        return AuditEventPage(events=events, next_cursor=next_cursor)

    async def audit_installations_for_repository(self, repository: str) -> tuple[int, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT DISTINCT installation_id FROM audit_events
                WHERE repository = $1
                ORDER BY installation_id
                """,
                repository,
            )
        return tuple(int(row["installation_id"]) for row in rows)

    async def invalidate_standing_decision(
        self,
        change_request: GitHubChangeRequestLocator,
        *,
        reason: str,
    ) -> None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await _lock_change_request(connection, change_request)
                row = await connection.fetchrow(
                    """
                    SELECT standing_attempt_id
                    FROM change_requests
                    WHERE installation_id = $1 AND repository = $2
                      AND pull_request_number = $3
                    FOR UPDATE
                    """,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                )
                if row is None:
                    return
                prior_standing = row["standing_attempt_id"]
                await connection.execute(
                    """
                    UPDATE change_requests
                    SET standing_attempt_id = NULL, standing_gate_state = NULL,
                        standing_revision = standing_revision + 1
                    WHERE installation_id = $1 AND repository = $2
                      AND pull_request_number = $3
                    """,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                )
                # The standing decision is gone: every bypass bound to it
                # expires, and any undelivered Check sync intent is terminal.
                await self._invalidate_bypasses_on_connection(
                    connection, change_request, reason=reason
                )
                if prior_standing is not None:
                    await self._supersede_standing_check_intents_on_connection(
                        connection, str(prior_standing)
                    )
                await self._append_audit_event_on_connection(
                    connection,
                    event_type="standing_decision_invalidated",
                    change_request=change_request,
                    attempt_id=None if prior_standing is None else str(prior_standing),
                    payload={"reason": reason},
                )

    async def invalidate_standing_for_target(
        self, *, repository: str, target_ref: str, reason: str
    ) -> int:
        aliases = (target_ref, f"refs/heads/{target_ref}", target_ref.removeprefix("refs/heads/"))
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT installation_id, repository, pull_request_number
                FROM change_requests
                WHERE repository = $1
                  AND request_key->>'target_ref' = ANY($2::text[])
                """,
                repository,
                list(aliases),
            )
        count = 0
        for row in rows:
            await self.invalidate_standing_decision(
                GitHubChangeRequestLocator(
                    installation_id=row["installation_id"],
                    repository=row["repository"],
                    pull_request_number=row["pull_request_number"],
                ),
                reason=reason,
            )
            count += 1
        return count

    async def apply_finding_bypass(
        self,
        *,
        change_request: GitHubChangeRequestLocator,
        attempt_id: str,
        finding_fingerprint: str,
        actor_id: int | None,
        actor_login: str,
        reason: str,
        review_identity: ReviewIdentity,
        review_policy_sha256: str,
        blocking_fingerprints: tuple[str, ...],
        risk_snapshot: dict[str, object],
        risk_digest: str,
        check_run_id: int | None,
    ) -> BypassApplyResult:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await _lock_change_request(connection, change_request)
                change_request_row = await connection.fetchrow(
                    """
                    SELECT authoritative_attempt_id, standing_attempt_id,
                           standing_gate_state, standing_revision
                    FROM change_requests
                    WHERE installation_id = $1 AND repository = $2
                      AND pull_request_number = $3
                    FOR UPDATE
                    """,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                )
                if change_request_row is None:
                    raise StateConflictError("change request disappeared before bypass")
                attempt_row = await connection.fetchrow(
                    """
                    SELECT review_identity
                    FROM review_attempts
                    WHERE attempt_id = $1::uuid AND installation_id = $2
                      AND repository = $3 AND pull_request_number = $4
                    FOR UPDATE
                    """,
                    attempt_id,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                )
                if attempt_row is None:
                    raise StateConflictError(f"unknown Attempt for change request: {attempt_id}")
                # Standing checks come first: even a legitimate replay must
                # not reach around the latest authority (P3 §5.3).
                if (
                    str(change_request_row["authoritative_attempt_id"]) != attempt_id
                    or str(change_request_row["standing_attempt_id"]) != attempt_id
                ):
                    raise StateConflictError(
                        "bypass requires the current standing authoritative Attempt"
                    )
                persisted_identity = (
                    None
                    if attempt_row["review_identity"] is None
                    else ReviewIdentity.model_validate(_json_object(attempt_row["review_identity"]))
                )
                if persisted_identity is None or persisted_identity != review_identity:
                    raise StateConflictError(
                        "Review Identity changed; a bypass binds to the identity it was granted on"
                    )
                existing_row = await connection.fetchrow(
                    """
                    SELECT *
                    FROM bypasses
                    WHERE attempt_id = $1::uuid AND finding_fingerprint = $2
                    """,
                    attempt_id,
                    finding_fingerprint,
                )
                if existing_row is not None:
                    existing_record = _bypass_record_from_row(existing_row)
                    if (
                        existing_record.status is BypassStatus.ACTIVE
                        and existing_record.actor_id == actor_id
                        and existing_record.actor_login == actor_login
                        and existing_record.reason == reason
                    ):
                        active = await self._active_bypass_fingerprints(connection, attempt_id)
                        latest_sync = await self._latest_standing_check_sync_on_connection(
                            connection, attempt_id
                        )
                        return BypassApplyResult(
                            record=existing_record,
                            standing_gate_state=_optional_gate_state(
                                change_request_row["standing_gate_state"]
                            ),
                            standing_revision=int(change_request_row["standing_revision"]),
                            active_bypass_fingerprints=active,
                            remaining_blocking_count=len(
                                [
                                    fingerprint
                                    for fingerprint in blocking_fingerprints
                                    if fingerprint not in set(active)
                                ]
                            ),
                            check_sync_status=(
                                CheckSyncStatus.NOT_APPLICABLE
                                if latest_sync is None
                                else latest_sync.status
                            ),
                            replayed=True,
                        )
                    raise StateConflictError(
                        "a different bypass already exists for this finding on this Attempt"
                    )
                if change_request_row["standing_gate_state"] != GateState.BLOCKED.value:
                    raise StateConflictError("only a standing Blocked gate accepts finding bypass")
                inserted_row = await connection.fetchrow(
                    """
                    INSERT INTO bypasses (
                        installation_id, repository, pull_request_number, attempt_id,
                        finding_fingerprint, actor_id, actor_login, reason,
                        review_identity, review_policy_sha256, risk_snapshot, risk_digest,
                        status
                    ) VALUES (
                        $1, $2, $3, $4::uuid, $5, $6, $7, $8, $9::jsonb, $10,
                        $11::jsonb, $12, $13
                    )
                    RETURNING bypass_id, created_at
                    """,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                    attempt_id,
                    finding_fingerprint,
                    actor_id,
                    actor_login,
                    reason,
                    review_identity.model_dump_json(),
                    review_policy_sha256,
                    json.dumps(risk_snapshot, sort_keys=True),
                    risk_digest,
                    BypassStatus.ACTIVE.value,
                )
                await self._append_audit_event_on_connection(
                    connection,
                    event_type="bypass_authorized",
                    change_request=change_request,
                    attempt_id=attempt_id,
                    actor_id=actor_id,
                    actor_login=actor_login,
                    payload={
                        "finding_fingerprint": finding_fingerprint,
                        "reason": reason,
                        "risk_digest": risk_digest,
                    },
                )
                active = await self._active_bypass_fingerprints(connection, attempt_id)
                remaining = [
                    fingerprint
                    for fingerprint in blocking_fingerprints
                    if fingerprint not in set(active)
                ]
                transitioned = False
                standing_gate_state = GateState.BLOCKED
                if not remaining:
                    standing_gate_state = GateState.PASSED_WITH_BYPASS
                    transitioned = True
                    await connection.execute(
                        """
                        UPDATE gate_decisions
                        SET gate_state = $2
                        WHERE attempt_id = $1::uuid AND standing = TRUE
                        """,
                        attempt_id,
                        GateState.PASSED_WITH_BYPASS.value,
                    )
                    await self._append_audit_event_on_connection(
                        connection,
                        event_type="gate_transition",
                        change_request=change_request,
                        attempt_id=attempt_id,
                        actor_id=actor_id,
                        actor_login=actor_login,
                        payload={
                            "from": GateState.BLOCKED.value,
                            "to": GateState.PASSED_WITH_BYPASS.value,
                            "cause": "finding_bypass",
                        },
                    )
                revision_row = await connection.fetchrow(
                    """
                    UPDATE change_requests
                    SET standing_gate_state = $5,
                        standing_revision = standing_revision + 1
                    WHERE installation_id = $1 AND repository = $2
                      AND pull_request_number = $3
                      AND standing_attempt_id = $4::uuid
                    RETURNING standing_revision
                    """,
                    change_request.installation_id,
                    change_request.repository,
                    change_request.pull_request_number,
                    attempt_id,
                    standing_gate_state.value,
                )
                if revision_row is None:
                    raise StateConflictError(
                        "standing decision moved while the bypass was being applied"
                    )
                standing_revision = int(revision_row["standing_revision"])
                sync_status = await self._enqueue_standing_check_intent_on_connection(
                    connection,
                    attempt_id=attempt_id,
                    standing_revision=standing_revision,
                    check_run_id=check_run_id,
                    payload={
                        "standing_gate_state": standing_gate_state.value,
                        "accepted_count": len(active),
                        "remaining_blocking_count": len(remaining),
                    },
                )
                await self._append_audit_event_on_connection(
                    connection,
                    event_type="check_sync_queued",
                    change_request=change_request,
                    attempt_id=attempt_id,
                    payload={
                        "standing_revision": standing_revision,
                        "check_sync_status": sync_status.value,
                    },
                )
                record = BypassRecord(
                    bypass_id=int(inserted_row["bypass_id"]),
                    change_request=change_request,
                    attempt_id=attempt_id,
                    finding_fingerprint=finding_fingerprint,
                    actor_id=actor_id,
                    actor_login=actor_login,
                    reason=reason,
                    review_identity=review_identity,
                    review_policy_sha256=review_policy_sha256,
                    risk_snapshot=risk_snapshot,
                    risk_digest=risk_digest,
                    created_at=_aware_datetime(inserted_row["created_at"]),
                )
                return BypassApplyResult(
                    record=record,
                    standing_gate_state=standing_gate_state,
                    standing_revision=standing_revision,
                    active_bypass_fingerprints=active,
                    remaining_blocking_count=len(remaining),
                    check_sync_status=sync_status,
                    gate_transitioned=transitioned,
                )

    async def _active_bypass_fingerprints(
        self, connection: asyncpg.Connection, attempt_id: str
    ) -> tuple[str, ...]:
        rows = await connection.fetch(
            """
            SELECT finding_fingerprint FROM bypasses
            WHERE attempt_id = $1::uuid AND status = $2
            ORDER BY bypass_id
            """,
            attempt_id,
            BypassStatus.ACTIVE.value,
        )
        return tuple(str(row["finding_fingerprint"]) for row in rows)

    async def _invalidate_bypasses_on_connection(
        self,
        connection: asyncpg.Connection,
        change_request: GitHubChangeRequestLocator,
        *,
        reason: str,
    ) -> None:
        rows = await connection.fetch(
            """
            UPDATE bypasses
            SET status = $4, invalidation_reason = $5, invalidated_at = CURRENT_TIMESTAMP
            WHERE installation_id = $1 AND repository = $2 AND pull_request_number = $3
              AND status = $6
            RETURNING attempt_id, finding_fingerprint, actor_id, actor_login
            """,
            change_request.installation_id,
            change_request.repository,
            change_request.pull_request_number,
            BypassStatus.INVALIDATED.value,
            reason,
            BypassStatus.ACTIVE.value,
        )
        for row in rows:
            await self._append_audit_event_on_connection(
                connection,
                event_type="bypass_invalidated",
                change_request=change_request,
                attempt_id=str(row["attempt_id"]),
                actor_id=None if row["actor_id"] is None else int(row["actor_id"]),
                actor_login=str(row["actor_login"]),
                payload={
                    "finding_fingerprint": row["finding_fingerprint"],
                    "reason": reason,
                },
            )

    async def _enqueue_standing_check_intent_on_connection(
        self,
        connection: asyncpg.Connection,
        *,
        attempt_id: str,
        standing_revision: int,
        check_run_id: int | None,
        payload: dict[str, object],
    ) -> CheckSyncStatus:
        await self._supersede_standing_check_intents_on_connection(connection, attempt_id)
        deliverable = check_run_id is not None
        status = CheckSyncStatus.QUEUED if deliverable else CheckSyncStatus.NOT_APPLICABLE
        assert_safe_audit_payload(payload)
        await connection.execute(
            """
            INSERT INTO standing_check_outbox (
                attempt_id, standing_revision, check_run_id, intent, status, payload
            ) VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb)
            """,
            attempt_id,
            standing_revision,
            check_run_id,
            "standing_check_sync",
            status.value,
            json.dumps(payload, sort_keys=True),
        )
        return status

    async def _supersede_standing_check_intents_on_connection(
        self, connection: asyncpg.Connection, attempt_id: str
    ) -> None:
        await connection.execute(
            """
            UPDATE standing_check_outbox
            SET status = $2, updated_at = CURRENT_TIMESTAMP
            WHERE attempt_id = $1::uuid AND status IN ('queued', 'in_progress')
            """,
            attempt_id,
            CheckSyncStatus.SUPERSEDED.value,
        )

    async def _latest_standing_check_sync_on_connection(
        self, connection: asyncpg.Connection, attempt_id: str
    ) -> StandingCheckSyncIntent | None:
        row = await connection.fetchrow(
            """
            SELECT * FROM standing_check_outbox
            WHERE attempt_id = $1::uuid
            ORDER BY standing_revision DESC
            LIMIT 1
            """,
            attempt_id,
        )
        return None if row is None else _check_sync_intent_from_row(row)

    async def list_bypasses(self, *, attempt_id: str) -> tuple[BypassRecord, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT * FROM bypasses
                WHERE attempt_id = $1::uuid
                ORDER BY bypass_id
                """,
                attempt_id,
            )
        return tuple(_bypass_record_from_row(row) for row in rows)

    async def claim_standing_check_sync(
        self, *, now: datetime, lease_seconds: float
    ) -> StandingCheckSyncIntent | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT * FROM standing_check_outbox
                    WHERE (
                        status = 'queued'
                        AND (next_retry_at IS NULL OR next_retry_at <= $1)
                    ) OR (
                        status = 'in_progress'
                        AND lease_expires_at IS NOT NULL
                        AND lease_expires_at <= $1
                    )
                    ORDER BY intent_id
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """,
                    now,
                )
                if row is None:
                    return None
                intent = _check_sync_intent_from_row(row)
                # Only the newest revision per Attempt is ever delivered;
                # anything older goes terminal-superseded instead.
                newer = await connection.fetchval(
                    """
                    SELECT MAX(standing_revision) FROM standing_check_outbox
                    WHERE attempt_id = $1::uuid AND status IN ('queued', 'in_progress')
                    """,
                    intent.attempt_id,
                )
                if newer is not None and int(newer) > intent.standing_revision:
                    await connection.execute(
                        """
                        UPDATE standing_check_outbox
                        SET status = $2, updated_at = CURRENT_TIMESTAMP
                        WHERE intent_id = $1
                        """,
                        intent.intent_id,
                        CheckSyncStatus.SUPERSEDED.value,
                    )
                    return None
                claimed_row = await connection.fetchrow(
                    """
                    UPDATE standing_check_outbox
                    SET status = 'in_progress',
                        attempt_count = attempt_count + 1,
                        lease_expires_at = $2,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE intent_id = $1
                    RETURNING *
                    """,
                    intent.intent_id,
                    now + timedelta(seconds=lease_seconds),
                )
                return _check_sync_intent_from_row(claimed_row)

    async def mark_standing_check_sync(
        self,
        intent_id: int,
        *,
        status: CheckSyncStatus,
        last_error: str | None = None,
        next_retry_at: datetime | None = None,
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE standing_check_outbox
                SET status = $2, last_error = $3, next_retry_at = $4,
                    lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE intent_id = $1
                """,
                intent_id,
                status.value,
                last_error,
                next_retry_at,
            )

    async def list_pending_standing_check_syncs(
        self, *, now: datetime
    ) -> tuple[StandingCheckSyncIntent, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT * FROM standing_check_outbox
                WHERE (
                    status = 'queued'
                    AND (next_retry_at IS NULL OR next_retry_at <= $1)
                ) OR (
                    status = 'in_progress'
                    AND lease_expires_at IS NOT NULL
                    AND lease_expires_at <= $1
                )
                ORDER BY intent_id
                """,
                now,
            )
        return tuple(_check_sync_intent_from_row(row) for row in rows)

    async def latest_standing_check_sync(
        self, *, attempt_id: str
    ) -> StandingCheckSyncIntent | None:
        async with self._pool.acquire() as connection:
            return await self._latest_standing_check_sync_on_connection(connection, attempt_id)
