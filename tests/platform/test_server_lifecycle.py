from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from worktree_review.core.identity import PolicyVersionIdentity, ReviewRequestKey
from worktree_review.platform.github.retry import RetryAccepted, RetryRequest
from worktree_review.platform.github.runtime import ServerConfigurationError, ServerRuntime
from worktree_review.server.app import create_app
from worktree_review.server.state import AttemptLease, GitHubChangeRequestLocator


class _ClosableResource:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _ClosableDatabasePool:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _RetryCoordinatorStub:
    def __init__(self) -> None:
        self.requests: list[RetryRequest] = []

    async def request_retry(self, retry_request: RetryRequest) -> RetryAccepted:
        self.requests.append(retry_request)
        return RetryAccepted(
            lease=AttemptLease(
                attempt_id="runtime-attempt",
                change_request=retry_request.change_request,
                request_key=ReviewRequestKey(
                    source_repository="octo/example",
                    target_ref="main",
                    target_head_oid="a" * 40,
                    proposed_head_oid="b" * 40,
                    review_policy_version=PolicyVersionIdentity(
                        semver="1.0.0",
                        sha256="d" * 64,
                    ),
                ),
            ),
            actor=retry_request.actor,
            reason=retry_request.reason,
        )


@pytest.mark.asyncio
async def test_server_lifespan_installs_and_closes_injected_retry_runtime() -> None:
    database_pool = _ClosableDatabasePool()
    http_client = _ClosableResource()
    runtime = ServerRuntime(
        retry_coordinator=_RetryCoordinatorStub(),  # type: ignore[arg-type]
        database_pool=database_pool,  # type: ignore[arg-type]
        http_client=http_client,  # type: ignore[arg-type]
    )
    builder_calls = 0

    async def build_test_runtime() -> ServerRuntime:
        nonlocal builder_calls
        builder_calls += 1
        return runtime

    application = create_app(
        github_webhook_secret="test-secret",
        runtime_builder=build_test_runtime,
    )
    async with application.router.lifespan_context(application):
        assert application.state.retry_coordinator is runtime.retry_coordinator
        assert builder_calls == 1
        assert database_pool.closed is False
        assert http_client.closed is False

    assert database_pool.closed is True
    assert http_client.closed is True


@pytest.mark.asyncio
async def test_server_without_webhook_secret_explicitly_disables_retry() -> None:
    application = create_app()

    async with application.router.lifespan_context(application):
        assert application.state.retry_coordinator is None
        assert "not configured" in application.state.retry_disabled_reason


@pytest.mark.asyncio
async def test_lifespan_coordinator_handles_signed_retry_webhook() -> None:
    secret = "test-secret"
    payload = {
        "action": "requested_action",
        "requested_action": {"identifier": "worktree-review-retry"},
        "repository": {"full_name": "octo/example"},
        "installation": {"id": 7},
        "check_run": {"pull_requests": [{"number": 42}]},
        "sender": {"login": "maintainer"},
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    coordinator = _RetryCoordinatorStub()
    application = create_app(
        github_webhook_secret=secret,
        retry_coordinator=coordinator,  # type: ignore[arg-type]
    )

    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as http_client:
            response = await http_client.post(
                "/webhooks/github",
                content=body,
                headers={
                    "x-hub-signature-256": signature,
                    "x-github-delivery": "delivery-1",
                },
            )

    assert response.status_code == 202
    assert response.json()["attempt_id"] == "runtime-attempt"
    assert coordinator.requests[0].change_request == GitHubChangeRequestLocator(
        installation_id=7,
        repository="octo/example",
        pull_request_number=42,
    )


@pytest.mark.asyncio
async def test_configured_webhook_secret_fails_startup_without_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for environment_name in (
        "WORKTREE_REVIEW_DATABASE_URL",
        "WORKTREE_REVIEW_GITHUB_TOKEN",
        "WORKTREE_REVIEW_REVIEW_POLICY_PATH",
    ):
        monkeypatch.delenv(environment_name, raising=False)
    application = create_app(github_webhook_secret="test-secret")

    with pytest.raises(ServerConfigurationError, match="REVIEW_POLICY_PATH"):
        async with application.router.lifespan_context(application):
            pass
