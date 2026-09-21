"""Authorized-deployment authentication: OAuth web flow, sessions, CSRF (P3 §4)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from worktree_review.platform.web.authentication import (
    LOGIN_NONCE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    AuthenticationError,
    GitHubAuthenticatedUser,
    GitHubWebAuthenticator,
    SessionStore,
    WebAuthConfiguration,
    _pkce_challenge,
    load_web_auth_configuration,
    read_session_cookie,
)


def _config(**overrides: Any) -> WebAuthConfiguration:
    fields: dict[str, Any] = {
        "public_base_url": "https://reviews.example.com",
        "github_oauth_client_id": "Iv1.testclient",
        "github_oauth_client_secret": "secret-value",
    }
    fields.update(overrides)
    return WebAuthConfiguration(**fields)


class _StubOAuthTransport:
    def __init__(self, *, user_id: int = 123456, login: str = "maintainer") -> None:
        self.user_id = user_id
        self.login = login
        self.exchanges: list[dict[str, str]] = []
        self.user_lookups = 0
        self.fail_exchange = False
        self.fail_user_lookup = False

    async def exchange_code_for_user_token(self, *, code: str, code_verifier: str) -> str:
        if self.fail_exchange:
            raise AuthenticationError("oauth_exchange_failed", "stub exchange failure")
        self.exchanges.append({"code": code, "code_verifier": code_verifier})
        return "stub-user-token"

    async def get_authenticated_user(self, *, user_token: str) -> GitHubAuthenticatedUser:
        self.user_lookups += 1
        if self.fail_user_lookup:
            raise AuthenticationError("github_identity_unavailable", "stub lookup failure")
        assert user_token == "stub-user-token"
        return GitHubAuthenticatedUser(user_id=self.user_id, login=self.login)


def _authenticator(
    transport: _StubOAuthTransport | None = None,
    *,
    clock: Any = None,
) -> GitHubWebAuthenticator:
    return GitHubWebAuthenticator(
        config=_config(),
        transport=transport or _StubOAuthTransport(),
        clock=clock,
    )


def test_config_requires_https_origin_without_path() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        _config(public_base_url="http://reviews.example.com")
    with pytest.raises(ValueError, match="origin without path"):
        _config(public_base_url="https://reviews.example.com/app")
    with pytest.raises(ValueError, match="HTTPS"):
        _config(github_web_url="http://github.example.com")


def test_load_web_auth_configuration_fails_closed_on_partial_config() -> None:
    assert (
        load_web_auth_configuration(
            {},
            public_base_url="https://reviews.example.com",
            github_api_url="https://api.github.com",
        )
        is None
    )
    with pytest.raises(ValueError, match="unsupported Web auth mode"):
        load_web_auth_configuration(
            {"WORKTREE_REVIEW_WEB_AUTH_MODE": "proxy-header"},
            public_base_url="https://reviews.example.com",
            github_api_url="https://api.github.com",
        )
    with pytest.raises(ValueError, match="OAUTH_CLIENT"):
        load_web_auth_configuration(
            {"WORKTREE_REVIEW_WEB_AUTH_MODE": "github-oauth"},
            public_base_url="https://reviews.example.com",
            github_api_url="https://api.github.com",
        )
    config = load_web_auth_configuration(
        {
            "WORKTREE_REVIEW_WEB_AUTH_MODE": "github-oauth",
            "WORKTREE_REVIEW_GITHUB_OAUTH_CLIENT_ID": "Iv1.x",
            "WORKTREE_REVIEW_GITHUB_OAUTH_CLIENT_SECRET": "s",
        },
        public_base_url="https://reviews.example.com",
        github_api_url="https://api.github.com",
    )
    assert config is not None
    assert config.allowed_origin == "https://reviews.example.com"
    assert config.callback_url == "https://reviews.example.com/api/v1/auth/github/callback"


def test_start_login_issues_one_time_state_and_pkce_s256() -> None:
    authenticator = _authenticator()
    login = authenticator.start_login()
    url = login.authorize_url
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.path == "/login/oauth/authorize"
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["Iv1.testclient"]
    assert query["redirect_uri"] == ["https://reviews.example.com/api/v1/auth/github/callback"]
    assert query["code_challenge_method"] == ["S256"]
    state = query["state"][0]
    challenge = query["code_challenge"][0]

    # The stored verifier matches the advertised S256 challenge.
    attempt = authenticator._login_attempts[state]
    assert _pkce_challenge(attempt.code_verifier) == challenge
    # The verifier itself never appears in the URL.
    assert attempt.code_verifier not in url
    # The state is bound to a browser nonce for the pre-login cookie.
    assert attempt.browser_nonce == login.browser_nonce


@pytest.mark.asyncio
async def test_complete_login_success_creates_session() -> None:
    transport = _StubOAuthTransport(user_id=42, login="octocat")
    authenticator = _authenticator(transport)
    login = authenticator.start_login()
    state = parse_qs(urlparse(login.authorize_url).query)["state"][0]

    session = await authenticator.complete_login(
        state=state, code="code-1", browser_nonce=login.browser_nonce
    )
    assert session.actor_id == 42
    assert session.actor_login == "octocat"
    assert session.csrf_token
    assert transport.exchanges[0]["code"] == "code-1"
    # PKCE verifier reached the exchange; the token is excluded from dumps.
    assert "user_token" not in session.model_dump()
    assert "stub-user-token" not in repr(session)

    # State is one-time: replay is rejected even with a valid code.
    with pytest.raises(AuthenticationError, match="oauth_state_mismatch"):
        await authenticator.complete_login(
            state=state, code="code-1", browser_nonce=login.browser_nonce
        )


@pytest.mark.asyncio
async def test_complete_login_rejects_unknown_state_and_failed_exchange() -> None:
    transport = _StubOAuthTransport()
    authenticator = _authenticator(transport)
    with pytest.raises(AuthenticationError, match="oauth_state_mismatch"):
        await authenticator.complete_login(state="forged", code="code-1", browser_nonce="x")

    transport.fail_exchange = True
    login = authenticator.start_login()
    state = parse_qs(urlparse(login.authorize_url).query)["state"][0]
    with pytest.raises(AuthenticationError, match="oauth_exchange_failed"):
        await authenticator.complete_login(
            state=state, code="bad-code", browser_nonce=login.browser_nonce
        )


@pytest.mark.asyncio
async def test_complete_login_rejects_expired_state() -> None:
    now = datetime.now(UTC)
    clock_values = [now]

    def clock() -> datetime:
        return clock_values[0]

    authenticator = _authenticator(clock=clock)
    login = authenticator.start_login()
    state = parse_qs(urlparse(login.authorize_url).query)["state"][0]
    clock_values[0] = now + timedelta(seconds=601)
    with pytest.raises(AuthenticationError, match="oauth_state_mismatch"):
        await authenticator.complete_login(
            state=state, code="code-1", browser_nonce=login.browser_nonce
        )


def test_session_store_expiry_rotation_and_revocation() -> None:
    now = datetime.now(UTC)
    clock_values = [now]
    store = SessionStore(clock=lambda: clock_values[0])

    first = store.create(actor_id=7, actor_login="a", user_token="t", ttl_seconds=30)
    second = store.create(actor_id=7, actor_login="a", user_token="t", ttl_seconds=30)
    assert first.session_id != second.session_id  # rotation on every login

    assert store.get(first.session_id) is not None
    clock_values[0] = now + timedelta(seconds=31)
    assert store.get(first.session_id) is None  # expired sessions are dropped

    third = store.create(actor_id=8, actor_login="b", user_token="t", ttl_seconds=30)
    assert store.revoke_actor(7) == 1  # only the second session for actor 7 remains
    assert store.get(second.session_id) is None
    assert store.get(third.session_id) is not None
    store.revoke(third.session_id)
    assert store.get(third.session_id) is None


def test_read_session_cookie_parses_only_the_session_name() -> None:
    assert read_session_cookie(None) is None
    assert read_session_cookie("other=1") is None
    assert read_session_cookie(f"other=1; {SESSION_COOKIE_NAME}=abc123; theme=dark") == "abc123"


@pytest.mark.asyncio
async def test_reverify_session_user_fails_closed_on_drift() -> None:
    transport = _StubOAuthTransport(user_id=42)
    authenticator = _authenticator(transport)
    login = authenticator.start_login()
    state = parse_qs(urlparse(login.authorize_url).query)["state"][0]
    session = await authenticator.complete_login(
        state=state, code="code-1", browser_nonce=login.browser_nonce
    )

    # Happy path: same numeric ID.
    await authenticator.reverify_session_user(session)

    # Token now resolves to a different user: session revoked, action refused.
    transport.user_id = 999
    with pytest.raises(AuthenticationError, match="authentication_required"):
        await authenticator.reverify_session_user(session)
    assert authenticator.session_for_cookie(f"{SESSION_COOKIE_NAME}={session.session_id}") is None

    # GitHub unreachable: no decision, no bypass.
    login = authenticator.start_login()
    state = parse_qs(urlparse(login.authorize_url).query)["state"][0]
    session = await authenticator.complete_login(
        state=state, code="code-2", browser_nonce=login.browser_nonce
    )
    transport.fail_user_lookup = True
    with pytest.raises(AuthenticationError, match="github_identity_unavailable"):
        await authenticator.reverify_session_user(session)


@pytest.mark.asyncio
async def test_assert_session_mutation_requires_origin_and_csrf() -> None:
    authenticator = _authenticator()
    login = authenticator.start_login()
    state = parse_qs(urlparse(login.authorize_url).query)["state"][0]
    session = await authenticator.complete_login(
        state=state, code="code-1", browser_nonce=login.browser_nonce
    )

    authenticator.assert_session_mutation(
        session, csrf_token=session.csrf_token, origin="https://reviews.example.com"
    )
    with pytest.raises(AuthenticationError, match="csrf_rejected"):
        authenticator.assert_session_mutation(
            session, csrf_token=session.csrf_token, origin="https://evil.example.com"
        )
    with pytest.raises(AuthenticationError, match="csrf_rejected"):
        authenticator.assert_session_mutation(session, csrf_token=None, origin=None)
    # A missing Origin is never silently allowed, even with a valid token.
    with pytest.raises(AuthenticationError, match="csrf_rejected"):
        authenticator.assert_session_mutation(session, csrf_token=session.csrf_token, origin=None)
    with pytest.raises(AuthenticationError, match="csrf_rejected"):
        authenticator.assert_session_mutation(
            session, csrf_token="forged", origin="https://reviews.example.com"
        )


def _build_app_with_auth(transport: _StubOAuthTransport) -> Any:
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
    authenticator = GitHubWebAuthenticator(config=_config(), transport=transport)
    runtime = ServerRuntime(
        retry_coordinator=GitHubRetryCoordinator(
            state=attempt_store,
            authorizer=_NoopAuthorizer(),
            resolver=_NoopResolver(),
        ),
        database_pool=None,  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(),
        attempt_store=attempt_store,  # type: ignore[arg-type]
        web_authenticator=authenticator,
    )
    application = create_app(enable_local_web=False)
    application.state.server_runtime = runtime
    return application


def test_auth_routes_unavailable_in_local_mode() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from worktree_review.server.app import create_app

    application = create_app(enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/auth/github/start").status_code == 501
        assert client.post("/api/v1/auth/logout").status_code == 501
        session = client.get("/api/v1/auth/session")
        assert session.status_code == 200
        assert session.json() == {
            "mode": "local",
            "authenticated": False,
            "capabilities": {"bypass": False, "audit": False},
        }


def test_auth_flow_end_to_end_over_http() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    application = _build_app_with_auth(_StubOAuthTransport(user_id=42, login="octocat"))
    with TestClient(application, base_url="http://127.0.0.1") as client:
        start = client.get("/api/v1/auth/github/start", follow_redirects=False)
        assert start.status_code == 302
        authorize_url = start.headers["location"]
        state = parse_qs(urlparse(authorize_url).query)["state"][0]
        nonce_value = re.search(rf"{LOGIN_NONCE_COOKIE_NAME}=([^;]+)", start.headers["set-cookie"])
        assert nonce_value is not None
        nonce_cookie = f"{LOGIN_NONCE_COOKIE_NAME}={nonce_value.group(1)}"

        # State mismatch is rejected before any exchange.
        mismatch = client.get(
            "/api/v1/auth/github/callback", params={"code": "c", "state": "forged"}
        )
        assert mismatch.status_code == 401
        assert mismatch.json()["error"]["code"] == "oauth_state_mismatch"

        callback = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "code-1", "state": state},
            headers={"Cookie": nonce_cookie},
            follow_redirects=False,
        )
        assert callback.status_code == 302
        assert callback.headers["location"] == "/"
        set_cookie = callback.headers["set-cookie"]
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert "SameSite=lax" in set_cookie
        cookie_value = re.search(rf"{SESSION_COOKIE_NAME}=([^;]+)", set_cookie)
        assert cookie_value is not None
        cookie_header = f"{SESSION_COOKIE_NAME}={cookie_value.group(1)}"

        session = client.get("/api/v1/auth/session", headers={"Cookie": cookie_header})
        assert session.status_code == 200
        body = session.json()
        assert body["authenticated"] is True
        assert body["actor_id"] == 42
        assert body["actor_login"] == "octocat"
        assert body["mode"] == "github-oauth"
        assert body["csrf_token"]
        # The user token never appears in any response body.
        assert "stub-user-token" not in session.text

        # Cross-origin or token-less logout is rejected; a same-origin logout
        # with the session CSRF token clears the session.
        cross = client.post(
            "/api/v1/auth/logout",
            headers={"Cookie": cookie_header, "Origin": "https://evil.example.com"},
        )
        assert cross.status_code == 403
        no_token = client.post(
            "/api/v1/auth/logout",
            headers={"Cookie": cookie_header, "Origin": "https://reviews.example.com"},
        )
        assert no_token.status_code == 403
        logout = client.post(
            "/api/v1/auth/logout",
            headers={
                "Cookie": cookie_header,
                "Origin": "https://reviews.example.com",
                "X-CSRF-Token": body["csrf_token"],
            },
        )
        assert logout.status_code == 200
        after = client.get("/api/v1/auth/session", headers={"Cookie": cookie_header})
        assert after.json()["authenticated"] is False


def test_dual_browser_callback_replay_cannot_steal_session() -> None:
    """Browser A starts the flow; browser B presenting A's callback URL (no
    pre-login cookie, or a nonce from its own start) never receives A's
    session (login CSRF / session swapping, P3 §4.2)."""

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    application = _build_app_with_auth(_StubOAuthTransport(user_id=42, login="octocat"))
    with TestClient(application, base_url="http://127.0.0.1") as browser_a:
        with TestClient(application, base_url="http://127.0.0.1") as browser_b:
            start_a = browser_a.get("/api/v1/auth/github/start", follow_redirects=False)
            state_a = parse_qs(urlparse(start_a.headers["location"]).query)["state"][0]
            callback_url_params = {"code": "code-1", "state": state_a}

            # B has no pre-login cookie at all.
            stolen = browser_b.get("/api/v1/auth/github/callback", params=callback_url_params)
            assert stolen.status_code == 401

            # B started its own flow: its nonce does not match A's state.
            start_b = browser_b.get("/api/v1/auth/github/start", follow_redirects=False)
            nonce_b = re.search(
                rf"{LOGIN_NONCE_COOKIE_NAME}=([^;]+)", start_b.headers["set-cookie"]
            )
            assert nonce_b is not None
            stolen = browser_b.get(
                "/api/v1/auth/github/callback",
                params=callback_url_params,
                headers={"Cookie": f"{LOGIN_NONCE_COOKIE_NAME}={nonce_b.group(1)}"},
            )
            assert stolen.status_code == 401
            assert b"wr_session" not in stolen.headers.get("set-cookie", "").encode()

            # A's own completion still works with a fresh login attempt.
            start_a2 = browser_a.get("/api/v1/auth/github/start", follow_redirects=False)
            state_a2 = parse_qs(urlparse(start_a2.headers["location"]).query)["state"][0]
            nonce_a = re.search(
                rf"{LOGIN_NONCE_COOKIE_NAME}=([^;]+)", start_a2.headers["set-cookie"]
            )
            assert nonce_a is not None
            legitimate = browser_a.get(
                "/api/v1/auth/github/callback",
                params={"code": "code-1", "state": state_a2},
                headers={"Cookie": f"{LOGIN_NONCE_COOKIE_NAME}={nonce_a.group(1)}"},
                follow_redirects=False,
            )
            assert legitimate.status_code == 302
