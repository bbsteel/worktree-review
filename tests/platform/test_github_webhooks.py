from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from worktree_review.core.identity import PolicyVersionIdentity, ReviewRequestKey
from worktree_review.platform.github.retry import RetryAccepted, RetryRequest
from worktree_review.platform.github.webhooks import (
    RETRY_ACTION_IDENTIFIER,
    WebhookValidationError,
    handle_github_webhook,
)
from worktree_review.server.state import (
    AttemptLease,
    GitHubChangeRequestLocator,
)


def _request_key() -> ReviewRequestKey:
    return ReviewRequestKey(
        source_repository="octo/example",
        target_ref="refs/heads/main",
        target_head_oid="a" * 40,
        proposed_head_oid="b" * 40,
        review_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="d" * 64),
    )


def _signed_payload(payload: dict[str, object], secret: str) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, f"sha256={digest}"


class _RecordingRetryCoordinator:
    def __init__(self) -> None:
        self.requests: list[RetryRequest] = []

    async def request_retry(self, retry_request: RetryRequest) -> RetryAccepted:
        self.requests.append(retry_request)
        return RetryAccepted(
            lease=AttemptLease(
                attempt_id="new-attempt",
                change_request=retry_request.change_request,
                request_key=_request_key(),
            ),
            actor=retry_request.actor,
            reason=retry_request.reason,
        )


def _retry_payload() -> dict[str, object]:
    return {
        "action": "requested_action",
        "requested_action": {"identifier": RETRY_ACTION_IDENTIFIER},
        "repository": {"full_name": "octo/example"},
        "installation": {"id": 7},
        "check_run": {"pull_requests": [{"number": 42}]},
        "sender": {"login": "maintainer"},
    }


@pytest.mark.asyncio
async def test_requested_action_webhook_maps_to_retry_request_after_signature_check() -> None:
    secret = "webhook-secret"
    body, signature = _signed_payload(_retry_payload(), secret)
    coordinator = _RecordingRetryCoordinator()

    result = await handle_github_webhook(
        payload=body,
        signature_header=signature,
        webhook_secret=secret,
        event_name="check_run",
        delivery_id="delivery-1",
        retry_coordinator=coordinator,  # type: ignore[arg-type]
    )

    assert result.status == "accepted"
    assert result.attempt_id == "new-attempt"
    assert coordinator.requests[0].change_request == GitHubChangeRequestLocator(
        installation_id=7,
        repository="octo/example",
        pull_request_number=42,
    )
    assert coordinator.requests[0].actor == "maintainer"
    assert coordinator.requests[0].delivery_id == "delivery-1"


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature_before_mapping() -> None:
    body, _ = _signed_payload(_retry_payload(), "webhook-secret")

    with pytest.raises(WebhookValidationError, match="invalid GitHub webhook signature"):
        await handle_github_webhook(
            payload=body,
            signature_header="sha256=not-valid",
            webhook_secret="webhook-secret",
            retry_coordinator=_RecordingRetryCoordinator(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_non_requested_action_webhook_is_ignored() -> None:
    payload = _retry_payload()
    payload["action"] = "completed"
    body, signature = _signed_payload(payload, "webhook-secret")

    result = await handle_github_webhook(
        payload=body,
        signature_header=signature,
        webhook_secret="webhook-secret",
        retry_coordinator=None,
    )

    assert result.status == "ignored"
    assert result.attempt_id is None


@pytest.mark.asyncio
async def test_retry_webhook_requires_delivery_id_for_idempotency() -> None:
    body, signature = _signed_payload(_retry_payload(), "webhook-secret")

    with pytest.raises(WebhookValidationError, match="delivery ID"):
        await handle_github_webhook(
            payload=body,
            signature_header=signature,
            webhook_secret="webhook-secret",
            retry_coordinator=_RecordingRetryCoordinator(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_app_authorization_revoked_drops_web_sessions() -> None:
    payload = {"action": "revoked", "sender": {"id": 123456, "login": "octocat"}}
    body, signature = _signed_payload(payload, "webhook-secret")
    revoked_ids: list[int] = []

    async def _revoke(actor_id: int) -> int:
        revoked_ids.append(actor_id)
        return 2

    result = await handle_github_webhook(
        payload=body,
        signature_header=signature,
        webhook_secret="webhook-secret",
        event_name="github_app_authorization",
        session_revoker=_revoke,
    )

    assert result.status == "accepted"
    assert revoked_ids == [123456]
    assert "2 web session(s)" in result.detail


@pytest.mark.asyncio
async def test_app_authorization_revoked_without_session_store_is_ignored() -> None:
    payload = {"action": "revoked", "sender": {"id": 123456, "login": "octocat"}}
    body, signature = _signed_payload(payload, "webhook-secret")

    result = await handle_github_webhook(
        payload=body,
        signature_header=signature,
        webhook_secret="webhook-secret",
        event_name="github_app_authorization",
    )

    assert result.status == "ignored"
