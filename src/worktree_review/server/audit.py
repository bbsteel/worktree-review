"""Append-only platform audit events (TECH-DESIGN D9; design doc §14.4).

Audit events record retry, authority, publication, and bypass activity. They
are written only by server-side state transitions, are never modifiable
through the API, and their payloads must not carry secrets or source code.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from worktree_review.application.review_events import scrub_secret_content


class AuditEventType(StrEnum):
    """Stable audit event names written by the platform today."""

    ATTEMPT_AUTHORITATIVE = "attempt_authoritative"
    ATTEMPT_PUBLISH_SUPERSEDED = "attempt_publish_superseded"
    STANDING_DECISION_PUBLISHED = "standing_decision_published"
    STANDING_DECISION_INVALIDATED = "standing_decision_invalidated"
    GATE_TRANSITION = "gate_transition"
    RETRY_AUTHORIZED = "retry_authorized"
    RETRY_DENIED = "retry_denied"
    RETRY_ENQUEUE_FAILED = "retry_enqueue_failed"
    PUBLICATION_ERROR = "publication_error"
    JOB_RETRYABLE = "job_retryable"
    JOB_REQUEUED = "job_requeued"
    JOB_LEASE_RECOVERED = "job_lease_recovered"
    JOB_FAILED = "job_failed"
    JOB_FINALIZED = "job_finalized"
    BYPASS_AUTHORIZED = "bypass_authorized"
    BYPASS_DENIED = "bypass_denied"
    BYPASS_INVALIDATED = "bypass_invalidated"
    CHECK_SYNC_QUEUED = "check_sync_queued"
    CHECK_SYNC_PUBLISHED = "check_sync_published"
    CHECK_SYNC_FAILED = "check_sync_failed"
    CHECK_SYNC_SUPERSEDED = "check_sync_superseded"
    AUTHORIZATION_REVOKED = "authorization_revoked"


class AuditEvent(BaseModel):
    """One immutable audit record. ``event_id`` is the pagination identity.

    The change-request locator is stored flat, mirroring the persistence
    schema; it is platform provenance, never part of core identity. The actor
    is split into the stable GitHub numeric user ID (the correlation key) and
    the login at write time (display only); either may be absent for
    server-side transitions with no human actor.
    """

    model_config = ConfigDict(frozen=True)

    event_id: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    occurred_at: datetime
    installation_id: int = Field(gt=0)
    repository: str = Field(min_length=1)
    pull_request_number: int = Field(gt=0)
    attempt_id: str | None = None
    actor_id: int | None = Field(default=None, gt=0)
    actor_login: str | None = None
    payload: dict[str, object]


class AuditEventPage(BaseModel):
    """One newest-first page of audit events with a keyset cursor."""

    model_config = ConfigDict(frozen=True)

    events: tuple[AuditEvent, ...]
    next_cursor: str | None = None


MAX_AUDIT_EVENTS_PER_PAGE = 200

_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "webhook_secret",
        "password",
        "credential",
        "credentials",
        "authorization",
        "api_key",
        "apikey",
        "private_key",
    }
)
_FORBIDDEN_PAYLOAD_KEY_SUFFIXES = ("_token", "_secret", "_password")
_MAX_AUDIT_PAYLOAD_BYTES = 32 * 1024


def assert_safe_audit_payload(payload: Mapping[str, object]) -> None:
    """Reject audit payloads that could carry secrets or unbounded content.

    Three lines of defense: secret-shaped keys are forbidden at any depth,
    every string value must survive ``scrub_secret_content`` unchanged
    (known credential values and token patterns fail closed), and the
    canonical encoding is size-capped.
    """

    _walk_payload(payload, path="payload")
    try:
        encoded = json.dumps(payload, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("audit payload must be JSON-serializable") from exc
    if len(encoded.encode("utf-8")) > _MAX_AUDIT_PAYLOAD_BYTES:
        raise ValueError("audit payload exceeds the maximum size")


def _walk_payload(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in _FORBIDDEN_PAYLOAD_KEYS or normalized.endswith(
                _FORBIDDEN_PAYLOAD_KEY_SUFFIXES
            ):
                raise ValueError(f"audit payload contains forbidden key: {path}.{key}")
            _walk_payload(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk_payload(item, path=f"{path}[{index}]")
    elif isinstance(value, str) and scrub_secret_content(value) != value:
        raise ValueError(f"audit payload contains secret-shaped content at {path}")


def clamp_audit_page_size(limit: int) -> int:
    return max(1, min(limit, MAX_AUDIT_EVENTS_PER_PAGE))


def parse_audit_cursor(cursor: str | None) -> int | None:
    """Decode a keyset cursor; anything but a positive event id is invalid."""

    if cursor is None:
        return None
    try:
        cursor_id = int(cursor)
    except ValueError as exc:
        raise ValueError("invalid audit event cursor") from exc
    if cursor_id < 1:
        raise ValueError("invalid audit event cursor")
    return cursor_id
