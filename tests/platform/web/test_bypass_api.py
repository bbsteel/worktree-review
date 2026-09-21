"""Bypass HTTP contract: session auth, CSRF, error mapping (P3 §8.1)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from worktree_review.platform.github.bypass import (
    BypassAccepted,
    BypassAuthorizationError,
    BypassAuthorizationUnavailableError,
    BypassRejectionError,
    BypassRequest,
)
from worktree_review.platform.web.authentication import (
    SESSION_COOKIE_NAME,
    GitHubAuthenticatedUser,
    GitHubWebAuthenticator,
    WebAuthConfiguration,
)
from worktree_review.server.state import BypassApplyResult, CheckSyncStatus


def _config() -> WebAuthConfiguration:
    return WebAuthConfiguration(
        public_base_url="https://reviews.example.com",
        github_oauth_client_id="Iv1.testclient",
        github_oauth_client_secret="secret-value",
    )


class _StubOAuthTransport:
    async def exchange_code_for_user_token(self, *, code: str, code_verifier: str) -> str:
        return "stub-user-token"

    async def get_authenticated_user(self, *, user_token: str) -> GitHubAuthenticatedUser:
        return GitHubAuthenticatedUser(user_id=42, login="octocat")


class _StubBypassCoordinator:
    def __init__(self) -> None:
        self.requests: list[BypassRequest] = []
        self.error: Exception | None = None

    async def request_bypass(self, bypass_request: BypassRequest) -> BypassAccepted:
        self.requests.append(bypass_request)
        if self.error is not None:
            raise self.error
        from worktree_review.core.identity import (
            MergeCandidateIdentity,
            PolicyVersionIdentity,
            ReviewIdentity,
        )
        from worktree_review.core.report import GateState
        from worktree_review.server.state import BypassRecord

        identity = ReviewIdentity(
            candidate=MergeCandidateIdentity(
                source_repository="octo/example",
                target_ref="main",
                target_head_oid="a" * 40,
                proposed_head_oid="b" * 40,
                merge_tree_oid="c" * 40,
            ),
            review_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="d" * 64),
        )
        record = BypassRecord(
            bypass_id=42,
            change_request={
                "installation_id": 7,
                "repository": "octo/example",
                "pull_request_number": 42,
            },
            attempt_id=bypass_request.attempt_id,
            finding_fingerprint=bypass_request.finding_fingerprint,
            actor_id=bypass_request.actor_id,
            actor_login=bypass_request.actor_login,
            reason=bypass_request.reason,
            review_identity=identity,
            review_policy_sha256="d" * 64,
            risk_snapshot={},
            risk_digest="d" * 64,
            created_at=datetime.now(UTC),
        )
        return BypassAccepted(
            result=BypassApplyResult(
                record=record,
                standing_gate_state=GateState.BLOCKED,
                standing_revision=4,
                active_bypass_fingerprints=(bypass_request.finding_fingerprint,),
                remaining_blocking_count=1,
                check_sync_status=CheckSyncStatus.QUEUED,
            )
        )


def _build_app(coordinator: Any = None, *, with_auth: bool = True) -> Any:
    pytest.importorskip("fastapi")
    import httpx

    from worktree_review.platform.github.retry import GitHubRetryCoordinator
    from worktree_review.platform.github.runtime import ServerRuntime
    from worktree_review.server.app import create_app
    from worktree_review.server.state import InMemoryAuthoritativeAttemptStore

    class _NoopAuthorizer:
        async def may_retry(self, *, change_request: object, actor: str) -> bool:
            return False

    class _NoopResolver:
        async def resolve_current_request(self, change_request: object) -> Any:
            raise AssertionError("not used")

    attempt_store = InMemoryAuthoritativeAttemptStore()
    runtime = ServerRuntime(
        retry_coordinator=GitHubRetryCoordinator(
            state=attempt_store,
            authorizer=_NoopAuthorizer(),
            resolver=_NoopResolver(),
        ),
        database_pool=None,  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(),
        attempt_store=attempt_store,  # type: ignore[arg-type]
        web_authenticator=(
            GitHubWebAuthenticator(config=_config(), transport=_StubOAuthTransport())
            if with_auth
            else None
        ),
        bypass_coordinator=coordinator,
    )
    application = create_app(enable_local_web=False)
    application.state.server_runtime = runtime
    return application


def _login(client: Any) -> dict[str, str]:
    start = client.get("/api/v1/auth/github/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    nonce = re.search(r"wr_login_nonce=([^;]+)", start.headers["set-cookie"])
    assert nonce is not None
    callback = client.get(
        "/api/v1/auth/github/callback",
        params={"code": "code-1", "state": state},
        headers={"Cookie": f"wr_login_nonce={nonce.group(1)}"},
        follow_redirects=False,
    )
    cookie_value = re.search(rf"{SESSION_COOKIE_NAME}=([^;]+)", callback.headers["set-cookie"])
    assert cookie_value is not None
    cookie_header = f"{SESSION_COOKIE_NAME}={cookie_value.group(1)}"
    session = client.get("/api/v1/auth/session", headers={"Cookie": cookie_header})
    return {"Cookie": cookie_header, "X-CSRF-Token": session.json()["csrf_token"]}


def test_bypass_unavailable_without_platform_or_auth() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from worktree_review.server.app import create_app

    # No server runtime at all (pure local mode).
    application = create_app(enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        response = client.post("/api/v1/reviews/a1/findings/fp-1/bypass", json={"reason": "ok"})
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "capability_unavailable"

    # GitHub runtime but no authorized deployment mode.
    application = _build_app(_StubBypassCoordinator(), with_auth=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        response = client.post("/api/v1/reviews/a1/findings/fp-1/bypass", json={"reason": "ok"})
        assert response.status_code == 501

    # Authorized mode but no bypass coordinator.
    application = _build_app(None, with_auth=True)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        headers = _login(client)
        response = client.post(
            "/api/v1/reviews/a1/findings/fp-1/bypass",
            json={"reason": "ok"},
            headers=headers,
        )
        assert response.status_code == 501


def test_bypass_requires_session_and_csrf() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    coordinator = _StubBypassCoordinator()
    application = _build_app(coordinator)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        url = "/api/v1/reviews/a1/findings/fp-1/bypass"
        assert client.post(url, json={"reason": "ok"}).status_code == 401

        headers = _login(client)
        missing_csrf = client.post(
            url, json={"reason": "ok"}, headers={"Cookie": headers["Cookie"]}
        )
        assert missing_csrf.status_code == 403
        assert missing_csrf.json()["error"]["code"] == "csrf_rejected"

        cross_origin = client.post(
            url,
            json={"reason": "ok"},
            headers={**headers, "Origin": "https://evil.example.com"},
        )
        assert cross_origin.status_code == 403
        assert coordinator.requests == []


def test_bypass_success_response_shape() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    coordinator = _StubBypassCoordinator()
    application = _build_app(coordinator)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        headers = _login(client)
        response = client.post(
            "/api/v1/reviews/a1/findings/fp-1/bypass",
            json={"reason": "accepted: isolated endpoint, removal scheduled"},
            headers={**headers, "Origin": "https://reviews.example.com"},
        )
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        body = response.json()
        assert body["bypass_id"] == 42
        assert body["bypass_state"] == "active"
        assert body["standing_gate_state"] == "Blocked"
        assert body["remaining_blocking_count"] == 1
        assert body["standing_revision"] == 4
        assert body["check_sync_status"] == "queued"
        assert body["gate_transitioned"] is False
        assert body["replayed"] is False
        # The actor came from the verified session, never from the body.
        assert coordinator.requests[0].actor_id == 42
        assert coordinator.requests[0].actor_login == "octocat"


def test_bypass_error_mapping() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    coordinator = _StubBypassCoordinator()
    application = _build_app(coordinator)
    url = "/api/v1/reviews/a1/findings/fp-1/bypass"
    with TestClient(application, base_url="http://127.0.0.1") as client:
        headers = _login(client)

        cases = (
            # Denied looks identical to missing — no existence probing.
            (BypassAuthorizationError("no"), 404, "attempt_not_found"),
            (BypassAuthorizationUnavailableError("down"), 503, "github_authorization_unavailable"),
            (BypassRejectionError("attempt_not_found", "x"), 404, "attempt_not_found"),
            (BypassRejectionError("finding_not_found", "x"), 404, "finding_not_found"),
            (BypassRejectionError("bypass_reason_invalid", "x"), 422, "bypass_reason_invalid"),
            (BypassRejectionError("bypass_not_standing", "x"), 409, "bypass_not_standing"),
            (BypassRejectionError("bypass_policy_changed", "x"), 409, "bypass_policy_changed"),
            (BypassRejectionError("bypass_conflict", "x"), 409, "bypass_conflict"),
        )
        for error, expected_status, expected_code in cases:
            coordinator.error = error
            response = client.post(
                url,
                json={"reason": "ok"},
                headers={**headers, "Origin": "https://reviews.example.com"},
            )
            assert response.status_code == expected_status, error
            assert response.json()["error"]["code"] == expected_code, error
