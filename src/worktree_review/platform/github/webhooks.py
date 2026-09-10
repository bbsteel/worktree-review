"""GitHub webhook validation and retry-action mapping (D14).

The handler only maps transport payloads to a retry request. Authorization is
performed by ``GitHubRetryCoordinator`` through a live role lookup, and all
review identities remain platform-independent core values.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from worktree_review.platform.github.retry import RetryRequest
from worktree_review.server.state import GitHubChangeRequestLocator

if TYPE_CHECKING:
    from worktree_review.platform.github.retry import GitHubRetryCoordinator
    from worktree_review.platform.github.triggers import GitHubTriggerCoordinator


RETRY_ACTION_IDENTIFIER = "worktree-review-retry"


class WebhookValidationError(ValueError):
    """The webhook signature or payload shape is invalid."""


class WebhookConfigurationError(RuntimeError):
    """A valid retry webhook has no configured retry coordinator."""


class GitHubWebhookEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_name: str | None = None
    delivery_id: str | None = None
    action: str | None = None
    payload: dict[str, object]


class WebhookDispatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    event_name: str | None = None
    attempt_id: str | None = None
    detail: str


def verify_github_signature(
    *,
    payload: bytes,
    signature_header: str | None,
    webhook_secret: str,
) -> bool:
    """Validate GitHub's ``X-Hub-Signature-256`` using constant-time comparison."""

    if not signature_header or not webhook_secret:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected_signature = (
        "sha256="
        + hmac.new(
            webhook_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(expected_signature, signature_header)


def parse_github_webhook(
    *,
    payload: bytes,
    signature_header: str | None,
    webhook_secret: str,
    event_name: str | None = None,
    delivery_id: str | None = None,
) -> GitHubWebhookEvent:
    if not verify_github_signature(
        payload=payload,
        signature_header=signature_header,
        webhook_secret=webhook_secret,
    ):
        raise WebhookValidationError("invalid GitHub webhook signature")
    try:
        decoded_payload = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookValidationError("GitHub webhook body is not valid JSON") from exc
    if not isinstance(decoded_payload, dict):
        raise WebhookValidationError("GitHub webhook body must be a JSON object")
    decoded_action = decoded_payload.get("action")
    return GitHubWebhookEvent(
        event_name=event_name,
        delivery_id=delivery_id,
        action=decoded_action if isinstance(decoded_action, str) else None,
        payload=decoded_payload,
    )


def _nested_object(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise WebhookValidationError(f"GitHub webhook is missing object field: {key}")
    return value


def _positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WebhookValidationError(
            f"GitHub webhook field {field_name} must be a positive integer"
        )
    return value


def _retry_request_from_event(event: GitHubWebhookEvent) -> RetryRequest:
    payload = event.payload
    requested_action = _nested_object(payload, "requested_action")
    identifier = requested_action.get("identifier")
    if identifier != RETRY_ACTION_IDENTIFIER:
        raise WebhookValidationError("GitHub requested action is not a Worktree Review retry")
    repository = _nested_object(payload, "repository")
    installation = _nested_object(payload, "installation")
    check_run = _nested_object(payload, "check_run")
    pull_requests = check_run.get("pull_requests")
    if not isinstance(pull_requests, list) or not pull_requests:
        raise WebhookValidationError("retry action does not identify a pull request")
    first_pull_request = pull_requests[0]
    if not isinstance(first_pull_request, dict):
        raise WebhookValidationError("retry action pull request payload is invalid")
    full_name = repository.get("full_name")
    actor = _nested_object(payload, "sender").get("login")
    if not isinstance(full_name, str) or not full_name:
        raise WebhookValidationError("GitHub webhook repository.full_name is required")
    if not isinstance(actor, str) or not actor:
        raise WebhookValidationError("GitHub webhook sender.login is required")
    if not event.delivery_id:
        raise WebhookValidationError("GitHub webhook delivery ID is required for retry actions")
    return RetryRequest(
        change_request=GitHubChangeRequestLocator(
            installation_id=_positive_integer(installation.get("id"), "installation.id"),
            repository=full_name,
            pull_request_number=_positive_integer(
                first_pull_request.get("number"),
                "check_run.pull_requests[0].number",
            ),
        ),
        actor=actor,
        reason="GitHub Checks requested action",
        delivery_id=event.delivery_id,
    )


async def handle_github_webhook(
    *,
    payload: bytes,
    signature_header: str | None,
    webhook_secret: str,
    event_name: str | None = None,
    delivery_id: str | None = None,
    retry_coordinator: GitHubRetryCoordinator | None = None,
    trigger_coordinator: GitHubTriggerCoordinator | None = None,
) -> WebhookDispatchResult:
    event = parse_github_webhook(
        payload=payload,
        signature_header=signature_header,
        webhook_secret=webhook_secret,
        event_name=event_name,
        delivery_id=delivery_id,
    )
    if event.event_name in {"pull_request", "push"} and trigger_coordinator is not None:
        return await trigger_coordinator.handle(event)
    if event.action != "requested_action":
        return WebhookDispatchResult(
            status="ignored",
            event_name=event.event_name,
            detail="GitHub event is not a Worktree Review retry action",
        )
    if retry_coordinator is None:
        raise WebhookConfigurationError("GitHub retry coordinator is not configured")
    accepted = await retry_coordinator.request_retry(_retry_request_from_event(event))
    return WebhookDispatchResult(
        status="accepted",
        event_name=event.event_name,
        attempt_id=accepted.lease.attempt_id,
        detail=(
            "retry delivery was already processed"
            if accepted.replayed
            else "authorized retry scheduled"
        ),
    )
