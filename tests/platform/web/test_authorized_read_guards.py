"""Authorized-mode read boundaries: session + repository role on every remote
API, no existence probing, payload visibility by role (P3 §4.1/§8)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from worktree_review.core.identity import PolicyVersionIdentity, ReviewRequestKey
from worktree_review.platform.github.persistence import InMemoryGitHubReviewStore
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot
from worktree_review.platform.web.authentication import (
    SESSION_COOKIE_NAME,
    GitHubAuthenticatedUser,
    GitHubWebAuthenticator,
    WebAuthConfiguration,
)
from worktree_review.server.state import (
    GitHubChangeRequestLocator,
    InMemoryAuthoritativeAttemptStore,
)

pytest.importorskip("fastapi")

_LOCATOR = GitHubChangeRequestLocator(
    installation_id=7, repository="octo/example", pull_request_number=42
)
_REQUEST_KEY = ReviewRequestKey(
    source_repository="octo/example",
    target_ref="main",
    target_head_oid="a" * 40,
    proposed_head_oid="b" * 40,
    review_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="d" * 64),
)


class _StubOAuthTransport:
    async def exchange_code_for_user_token(self, *, code: str, code_verifier: str) -> str:
        return "stub-user-token"

    async def get_authenticated_user(self, *, user_token: str) -> GitHubAuthenticatedUser:
        return GitHubAuthenticatedUser(user_id=42, login="octocat")


class _ConfigurableRoleLookup:
    def __init__(self, role: str | None) -> None:
        self.role = role

    async def repository_role(
        self, *, installation_id: int, repository: str, actor: str
    ) -> str | None:
        return self.role


def _build_app(*, role: str | None) -> Any:
    import asyncio

    import httpx

    from worktree_review.platform.github.retry import GitHubRetryCoordinator
    from worktree_review.platform.github.runtime import ServerRuntime
    from worktree_review.server.app import create_app

    class _NoopAuthorizer:
        async def may_retry(self, *, change_request: object, actor: str) -> bool:
            return False

    class _NoopResolver:
        async def resolve_current_request(self, change_request: object) -> Any:
            raise AssertionError("not used")

    state = InMemoryAuthoritativeAttemptStore()
    store = InMemoryGitHubReviewStore()
    attempt_id = "11111111-2222-3333-4444-555555555555"

    async def _seed() -> None:
        await store.save_execution_snapshot(
            AttemptExecutionSnapshot(
                attempt_id=attempt_id,
                change_request=_LOCATOR,
                request_key=_REQUEST_KEY,
                proposed_ref="feature",
                review_policy_semver="1.0.0",
                review_policy_sha256="d" * 64,
                compute_policy_semver="1.0.0",
                compute_policy_sha256="e" * 64,
            )
        )
        await state.append_audit_event(
            event_type="bypass_authorized",
            change_request=_LOCATOR,
            attempt_id=attempt_id,
            actor_id=42,
            actor_login="octocat",
            payload={"finding_fingerprint": "fp-1", "reason": "sensitive rationale"},
        )

    asyncio.run(_seed())
    runtime = ServerRuntime(
        retry_coordinator=GitHubRetryCoordinator(
            state=state, authorizer=_NoopAuthorizer(), resolver=_NoopResolver()
        ),
        database_pool=None,  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(),
        github_store=store,  # type: ignore[arg-type]
        attempt_store=state,  # type: ignore[arg-type]
        web_authenticator=GitHubWebAuthenticator(
            config=WebAuthConfiguration(
                public_base_url="https://reviews.example.com",
                github_oauth_client_id="Iv1.testclient",
                github_oauth_client_secret="secret-value",
            ),
            transport=_StubOAuthTransport(),
        ),
        role_lookup=_ConfigurableRoleLookup(role),
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
    return {"Cookie": f"{SESSION_COOKIE_NAME}={cookie_value.group(1)}"}


def test_remote_apis_reject_anonymous_calls_in_authorized_mode() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    application = _build_app(role="write")
    with TestClient(application, base_url="http://127.0.0.1") as client:
        for method, url in (
            ("GET", "/api/v1/audit-events?repository=octo/example"),
            ("GET", "/api/v1/reviews"),
            ("GET", "/api/v1/reviews/11111111-2222-3333-4444-555555555555"),
            ("GET", "/api/v1/reviews/11111111-2222-3333-4444-555555555555/result"),
            ("GET", "/api/v1/overview"),
        ):
            response = client.request(method, url)
            assert response.status_code == 401, url
            assert response.json()["error"]["code"] == "authentication_required"
            assert response.headers["Cache-Control"] == "no-store"
        # The auth surface itself stays reachable for the login flow.
        assert client.get("/api/v1/auth/session").status_code == 200


def test_audit_requires_readable_repo_role_and_strips_payload_by_role() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    # No role at all: indistinguishable from a repository that does not exist.
    application = _build_app(role=None)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        headers = _login(client)
        denied = client.get(
            "/api/v1/audit-events", params={"repository": "octo/example"}, headers=headers
        )
        assert denied.status_code == 404
        assert denied.json()["error"]["code"] == "repository_not_found"

    # Read role: metadata only, the risk rationale never leaves the server.
    application = _build_app(role="read")
    with TestClient(application, base_url="http://127.0.0.1") as client:
        headers = _login(client)
        page = client.get(
            "/api/v1/audit-events", params={"repository": "octo/example"}, headers=headers
        )
        assert page.status_code == 200
        events = page.json()["events"]
        assert len(events) == 1
        assert events[0]["event_type"] == "bypass_authorized"
        assert events[0]["payload"] == {}
        assert "sensitive rationale" not in page.text

    # Write role: full sanitized payload.
    application = _build_app(role="write")
    with TestClient(application, base_url="http://127.0.0.1") as client:
        headers = _login(client)
        page = client.get(
            "/api/v1/audit-events", params={"repository": "octo/example"}, headers=headers
        )
        assert page.status_code == 200
        assert page.json()["events"][0]["payload"]["reason"] == "sensitive rationale"


def test_github_detail_and_result_are_404_without_repo_read_role() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    attempt_id = "11111111-2222-3333-4444-555555555555"
    application = _build_app(role=None)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        headers = _login(client)
        detail = client.get(f"/api/v1/reviews/{attempt_id}", headers=headers)
        assert detail.status_code == 404
        result = client.get(f"/api/v1/reviews/{attempt_id}/result", headers=headers)
        assert result.status_code == 404
        events = client.get(f"/api/v1/reviews/{attempt_id}/events", headers=headers)
        assert events.status_code == 404

    # With a readable role the detail is served (session-only gates passed).
    application = _build_app(role="read")
    with TestClient(application, base_url="http://127.0.0.1") as client:
        headers = _login(client)
        detail = client.get(f"/api/v1/reviews/{attempt_id}", headers=headers)
        # The attempt has no terminal result, but it exists for this actor.
        assert detail.status_code == 200


def _build_app_with_local_admin(*, role: str | None) -> Any:
    """Authorized deployment that also has a local WebRuntime attached.

    This is the misconfiguration / dual-runtime shape the Critical finding
    exploited: a logged-in user without a repository role could still read
    local Provider Profiles and obtain CSRF via a forged loopback Host.
    """

    import asyncio
    from pathlib import Path

    import httpx

    from worktree_review.platform.github.retry import GitHubRetryCoordinator
    from worktree_review.platform.github.runtime import ServerRuntime
    from worktree_review.platform.web.runtime import open_web_runtime
    from worktree_review.server.app import create_app
    from worktree_review.server.state import InMemoryAuthoritativeAttemptStore

    class _NoopAuthorizer:
        async def may_retry(self, *, change_request: object, actor: str) -> bool:
            return False

    class _NoopResolver:
        async def resolve_current_request(self, change_request: object) -> Any:
            raise AssertionError("not used")

    db_path = Path("/var/tmp/worktree-review") / "authorized-local-admin.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    web_runtime = asyncio.run(open_web_runtime(db_path))

    async def _seed_provider() -> None:
        await web_runtime.store.insert_provider_profile(
            profile_id="profile-1",
            name="openai-prod",
            provider="openai",
            credential_reference="env:OPENAI_API_KEY",
            endpoint="https://api.openai.com/v1",
            local_cli_adapter=None,
            local_cli_command=None,
            adapter_label=None,
        )

    asyncio.run(_seed_provider())
    state = InMemoryAuthoritativeAttemptStore()
    runtime = ServerRuntime(
        retry_coordinator=GitHubRetryCoordinator(
            state=state, authorizer=_NoopAuthorizer(), resolver=_NoopResolver()
        ),
        database_pool=None,  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(),
        attempt_store=state,  # type: ignore[arg-type]
        web_authenticator=GitHubWebAuthenticator(
            config=WebAuthConfiguration(
                public_base_url="https://reviews.example.com",
                github_oauth_client_id="Iv1.testclient",
                github_oauth_client_secret="secret-value",
            ),
            transport=_StubOAuthTransport(),
        ),
        role_lookup=_ConfigurableRoleLookup(role),
    )
    application = create_app(
        web_runtime=web_runtime, enable_local_web=True, start_worker=False, serve_frontend=False
    )
    application.state.server_runtime = runtime
    return application


_LOCAL_ADMIN_READS = (
    ("GET", "/api/v1/csrf-bootstrap"),
    ("GET", "/api/v1/provider-profiles"),
    ("GET", "/api/v1/repositories"),
    ("GET", "/api/v1/review-policies"),
    ("GET", "/api/v1/compute-policies"),
    ("GET", "/api/v1/integrations/session-insight"),
)


@pytest.mark.parametrize("role", [None, "read", "write"])
def test_authorized_mode_hides_local_admin_surface_for_every_role(role: str | None) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    application = _build_app_with_local_admin(role=role)
    with TestClient(application, base_url="https://reviews.example.com") as client:
        headers = _login(client)
        for method, url in _LOCAL_ADMIN_READS:
            response = client.request(
                method,
                url,
                headers={**headers, "Host": "127.0.0.1:8080"},
            )
            assert response.status_code == 404, (role, url, response.status_code, response.text)
            body = response.json()
            assert body["error"]["code"] == "not_found"
            leaked = response.text.lower()
            for fragment in (
                "csrf_token",
                "openai-prod",
                "openai_api_key",
                "provider-profiles",
                "worktree_review_web",
                "/home/",
                "env:",
            ):
                assert fragment not in leaked, (url, fragment)


def test_authorized_mode_hides_local_admin_from_anonymous_callers() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    application = _build_app_with_local_admin(role="write")
    with TestClient(application, base_url="https://reviews.example.com") as client:
        for method, url in _LOCAL_ADMIN_READS:
            response = client.request(method, url, headers={"Host": "127.0.0.1"})
            assert response.status_code == 404, url
            assert response.json()["error"]["code"] == "not_found"
            assert "csrf_token" not in response.text
            assert "authentication_required" not in response.text


class _FailingRoleLookup:
    async def repository_role(
        self, *, installation_id: int, repository: str, actor: str
    ) -> str | None:
        raise RuntimeError("github authorization timed out")


def test_review_list_propagates_authorization_unavailable_instead_of_empty() -> None:
    """A GitHub 503/timeout must not be disguised as an empty review list."""

    pytest.importorskip("fastapi")
    import asyncio

    import httpx
    from fastapi.testclient import TestClient

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

    state = InMemoryAuthoritativeAttemptStore()
    store = InMemoryGitHubReviewStore()
    attempt_id = "11111111-2222-3333-4444-555555555555"

    async def _seed() -> None:
        await store.save_execution_snapshot(
            AttemptExecutionSnapshot(
                attempt_id=attempt_id,
                change_request=_LOCATOR,
                request_key=_REQUEST_KEY,
                proposed_ref="feature",
                review_policy_semver="1.0.0",
                review_policy_sha256="d" * 64,
                compute_policy_semver="1.0.0",
                compute_policy_sha256="e" * 64,
            )
        )

    asyncio.run(_seed())
    runtime = ServerRuntime(
        retry_coordinator=GitHubRetryCoordinator(
            state=state, authorizer=_NoopAuthorizer(), resolver=_NoopResolver()
        ),
        database_pool=None,  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(),
        github_store=store,  # type: ignore[arg-type]
        attempt_store=state,  # type: ignore[arg-type]
        web_authenticator=GitHubWebAuthenticator(
            config=WebAuthConfiguration(
                public_base_url="https://reviews.example.com",
                github_oauth_client_id="Iv1.testclient",
                github_oauth_client_secret="secret-value",
            ),
            transport=_StubOAuthTransport(),
        ),
        role_lookup=_FailingRoleLookup(),
    )
    application = create_app(enable_local_web=False, serve_frontend=False)
    application.state.server_runtime = runtime
    with TestClient(application, base_url="https://reviews.example.com") as client:
        headers = _login(client)
        listed = client.get("/api/v1/reviews", headers=headers)
        assert listed.status_code == 503
        assert listed.json()["error"]["code"] == "github_authorization_unavailable"
        overview = client.get("/api/v1/overview", headers=headers)
        assert overview.status_code == 503
        assert overview.json()["error"]["code"] == "github_authorization_unavailable"


class _PerInstallationRoleLookup:
    """Return a different live role per installation_id."""

    def __init__(self, roles: dict[int, str | None]) -> None:
        self.roles = roles

    async def repository_role(
        self, *, installation_id: int, repository: str, actor: str
    ) -> str | None:
        return self.roles.get(installation_id)


def test_audit_events_are_scoped_to_authorized_installations_only() -> None:
    """A write role on Installation A must not expose Installation B events."""

    pytest.importorskip("fastapi")
    import asyncio

    import httpx
    from fastapi.testclient import TestClient

    from worktree_review.platform.github.retry import GitHubRetryCoordinator
    from worktree_review.platform.github.runtime import ServerRuntime
    from worktree_review.server.app import create_app
    from worktree_review.server.state import (
        GitHubChangeRequestLocator,
        InMemoryAuthoritativeAttemptStore,
    )

    class _NoopAuthorizer:
        async def may_retry(self, *, change_request: object, actor: str) -> bool:
            return False

    class _NoopResolver:
        async def resolve_current_request(self, change_request: object) -> Any:
            raise AssertionError("not used")

    visible = GitHubChangeRequestLocator(
        installation_id=7, repository="octo/example", pull_request_number=42
    )
    other = GitHubChangeRequestLocator(
        installation_id=99, repository="octo/example", pull_request_number=7
    )
    state = InMemoryAuthoritativeAttemptStore()

    async def _seed() -> None:
        await state.append_audit_event(
            event_type="bypass_authorized",
            change_request=visible,
            attempt_id="11111111-2222-3333-4444-555555555555",
            actor_id=42,
            actor_login="octocat",
            payload={"finding_fingerprint": "fp-visible", "reason": "visible-install-reason"},
        )
        await state.append_audit_event(
            event_type="bypass_authorized",
            change_request=other,
            attempt_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            actor_id=7,
            actor_login="other-actor",
            payload={"finding_fingerprint": "fp-hidden", "reason": "hidden-install-reason"},
        )

    asyncio.run(_seed())
    runtime = ServerRuntime(
        retry_coordinator=GitHubRetryCoordinator(
            state=state, authorizer=_NoopAuthorizer(), resolver=_NoopResolver()
        ),
        database_pool=None,  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(),
        attempt_store=state,  # type: ignore[arg-type]
        web_authenticator=GitHubWebAuthenticator(
            config=WebAuthConfiguration(
                public_base_url="https://reviews.example.com",
                github_oauth_client_id="Iv1.testclient",
                github_oauth_client_secret="secret-value",
            ),
            transport=_StubOAuthTransport(),
        ),
        # Write on installation 7 only; installation 99 is invisible.
        role_lookup=_PerInstallationRoleLookup({7: "write", 99: None}),
    )
    application = create_app(enable_local_web=False, serve_frontend=False)
    application.state.server_runtime = runtime
    with TestClient(application, base_url="https://reviews.example.com") as client:
        headers = _login(client)
        page = client.get(
            "/api/v1/audit-events", params={"repository": "octo/example"}, headers=headers
        )
        assert page.status_code == 200
        events = page.json()["events"]
        assert len(events) == 1
        assert events[0]["payload"]["reason"] == "visible-install-reason"
        assert "hidden-install-reason" not in page.text
        assert events[0]["installation_id"] == 7


def test_authorized_overview_counts_every_readable_attempt_not_just_recent_50() -> None:
    pytest.importorskip("fastapi")
    import asyncio
    import uuid

    import httpx
    from fastapi.testclient import TestClient

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

    state = InMemoryAuthoritativeAttemptStore()
    store = InMemoryGitHubReviewStore()

    async def _seed() -> None:
        # Snapshots only: Overview totals count every readable Attempt even
        # when the recent-list window is 50. Avoid terminal result documents
        # here so the recent-summary projection stays out of the way.
        for index in range(60):
            attempt_id = str(uuid.UUID(int=index + 1))
            await store.save_execution_snapshot(
                AttemptExecutionSnapshot(
                    attempt_id=attempt_id,
                    change_request=_LOCATOR,
                    request_key=_REQUEST_KEY,
                    proposed_ref="feature",
                    review_policy_semver="1.0.0",
                    review_policy_sha256="d" * 64,
                    compute_policy_semver="1.0.0",
                    compute_policy_sha256="e" * 64,
                )
            )

    asyncio.run(_seed())
    # Default list window is 50; Overview totals must still see all 60.
    assert len(asyncio.run(store.list_recent_attempt_ids())) == 50
    assert len(asyncio.run(store.list_recent_attempt_ids(limit=None))) == 60

    runtime = ServerRuntime(
        retry_coordinator=GitHubRetryCoordinator(
            state=state, authorizer=_NoopAuthorizer(), resolver=_NoopResolver()
        ),
        database_pool=None,  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(),
        github_store=store,  # type: ignore[arg-type]
        attempt_store=state,  # type: ignore[arg-type]
        web_authenticator=GitHubWebAuthenticator(
            config=WebAuthConfiguration(
                public_base_url="https://reviews.example.com",
                github_oauth_client_id="Iv1.testclient",
                github_oauth_client_secret="secret-value",
            ),
            transport=_StubOAuthTransport(),
        ),
        role_lookup=_ConfigurableRoleLookup("read"),
    )
    application = create_app(enable_local_web=False, serve_frontend=False)
    application.state.server_runtime = runtime
    with TestClient(application, base_url="https://reviews.example.com") as client:
        headers = _login(client)
        overview = client.get("/api/v1/overview", headers=headers)
        assert overview.status_code == 200
        stats = overview.json()["stats"]
        assert stats["attempt_count"] == 60
