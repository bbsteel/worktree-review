"""Authorized GitHub retry coordination (D14).

The coordinator only resolves platform provenance and schedules a new Attempt.
It does not alter ``ReviewRequestKey`` or ``ReviewIdentity`` semantics and it
does not retry individual provider calls; those remain inside the core review
Attempt under Compute Policy.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from worktree_review.core.identity import ReviewRequestKey
from worktree_review.server.state import (
    AttemptLease,
    AuthoritativeAttemptStore,
    GitHubChangeRequestLocator,
    StateConflictError,
)


class RetryAuthorizationError(RuntimeError):
    """The live GitHub actor is not authorized to request a retry."""


class RetryResolution(BaseModel):
    """Immutable request-key input resolved from current GitHub refs and policy."""

    model_config = ConfigDict(frozen=True)

    request_key: ReviewRequestKey


class RetryRequest(BaseModel):
    """A retry action received from an authorized GitHub actor."""

    model_config = ConfigDict(frozen=True)

    change_request: GitHubChangeRequestLocator
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    prior_attempt_id: str | None = Field(default=None, min_length=1)


class RetryAccepted(BaseModel):
    """The new authoritative Attempt and the request key it will review."""

    model_config = ConfigDict(frozen=True)

    lease: AttemptLease
    actor: str
    reason: str


class RetryAuthorizer(Protocol):
    async def may_retry(
        self,
        *,
        change_request: GitHubChangeRequestLocator,
        actor: str,
    ) -> bool:
        """Resolve current repository role/permission from GitHub, never comment text."""
        ...


class RetryRequestResolver(Protocol):
    async def resolve_current_request(
        self,
        change_request: GitHubChangeRequestLocator,
    ) -> RetryResolution:
        """Re-resolve refs and trusted policy outside the reviewed repository."""
        ...


AttemptEnqueuer = Callable[[AttemptLease], Awaitable[None]]


class GitHubRetryCoordinator:
    """Authorize, re-resolve, and atomically enqueue a new GitHub Attempt."""

    def __init__(
        self,
        *,
        state: AuthoritativeAttemptStore,
        authorizer: RetryAuthorizer,
        resolver: RetryRequestResolver,
        enqueue_attempt: AttemptEnqueuer | None = None,
    ) -> None:
        self._state = state
        self._authorizer = authorizer
        self._resolver = resolver
        self._enqueue_attempt = enqueue_attempt

    async def request_retry(self, retry_request: RetryRequest) -> RetryAccepted:
        authorized = await self._authorizer.may_retry(
            change_request=retry_request.change_request,
            actor=retry_request.actor,
        )
        if not authorized:
            await self._state.append_audit_event(
                event_type="retry_denied",
                change_request=retry_request.change_request,
                attempt_id=retry_request.prior_attempt_id,
                payload={"actor": retry_request.actor, "reason": retry_request.reason},
            )
            raise RetryAuthorizationError(
                f"GitHub actor {retry_request.actor!r} is not authorized to retry this review"
            )

        current_state = await self._state.get_change_request_state(retry_request.change_request)
        prior_attempt_id = retry_request.prior_attempt_id or current_state.authoritative_attempt_id
        if prior_attempt_id is None:
            raise StateConflictError("cannot retry a change request without a current Attempt")
        if current_state.authoritative_attempt_id != prior_attempt_id:
            raise StateConflictError(
                "retry action targets an Attempt that is no longer authoritative"
            )

        resolution = await self._resolver.resolve_current_request(retry_request.change_request)
        lease = await self._state.start_authoritative_attempt(
            change_request=retry_request.change_request,
            request_key=resolution.request_key,
            expected_authoritative_attempt_id=prior_attempt_id,
        )
        await self._state.append_audit_event(
            event_type="retry_authorized",
            change_request=retry_request.change_request,
            attempt_id=lease.attempt_id,
            payload={
                "actor": retry_request.actor,
                "reason": retry_request.reason,
                "prior_attempt_id": prior_attempt_id,
                "request_key": resolution.request_key.model_dump(mode="json"),
            },
        )
        if self._enqueue_attempt is not None:
            try:
                await self._enqueue_attempt(lease)
            except Exception as exc:
                await self._state.append_audit_event(
                    event_type="retry_enqueue_failed",
                    change_request=retry_request.change_request,
                    attempt_id=lease.attempt_id,
                    payload={"error": str(exc)},
                )
                raise
        return RetryAccepted(
            lease=lease,
            actor=retry_request.actor,
            reason=retry_request.reason,
        )
