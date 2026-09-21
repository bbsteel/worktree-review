"""Deployment authentication for the authorized Web mode (P3 design §4).

The default local deployment keeps its loopback, process-level protections and
has no provable GitHub actor. The authorized deployment mode exists only when
an HTTPS public base URL, a GitHub App OAuth client, and exact origin values
are configured together; a partial configuration fails closed at startup.

Identity chain: GitHub App user-access-token web flow with one-time ``state``
and PKCE S256, server-side code exchange, ``GET /user`` for the stable numeric
user ID, then an opaque ``HttpOnly`` session cookie. The user token lives only
in the server-side session store — never in HTML, logs, journals, or audit
payloads — and every sensitive action re-verifies it against GitHub.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode, urlparse

from pydantic import BaseModel, ConfigDict, Field

SESSION_COOKIE_NAME = "wr_session"
# Short-lived pre-login cookie that binds the OAuth state to the browser that
# started the flow: a callback URL replayed in another browser is useless.
LOGIN_NONCE_COOKIE_NAME = "wr_login_nonce"
DEFAULT_SESSION_TTL_SECONDS = 1800  # 30 minutes; no refresh token by design
DEFAULT_LOGIN_STATE_TTL_SECONDS = 600
DEFAULT_GITHUB_WEB_URL = "https://github.com"
DEFAULT_GITHUB_API_URL = "https://api.github.com"

WEB_AUTH_MODE_ENV = "WORKTREE_REVIEW_WEB_AUTH_MODE"
OAUTH_CLIENT_ID_ENV = "WORKTREE_REVIEW_GITHUB_OAUTH_CLIENT_ID"
OAUTH_CLIENT_SECRET_ENV = "WORKTREE_REVIEW_GITHUB_OAUTH_CLIENT_SECRET"
GITHUB_WEB_URL_ENV = "WORKTREE_REVIEW_GITHUB_WEB_URL"
GITHUB_OAUTH_MODE = "github-oauth"


class AuthenticationError(RuntimeError):
    """Authentication/authorization failure; ``code`` is stable for API mapping."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


class WebAuthConfiguration(BaseModel):
    """Validated authorized-deployment configuration. Never log secrets."""

    model_config = ConfigDict(frozen=True)

    public_base_url: str = Field(min_length=1)
    github_oauth_client_id: str = Field(min_length=1)
    github_oauth_client_secret: str = Field(min_length=1, repr=False)
    github_web_url: str = DEFAULT_GITHUB_WEB_URL
    github_api_url: str = DEFAULT_GITHUB_API_URL
    session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS
    login_state_ttl_seconds: int = DEFAULT_LOGIN_STATE_TTL_SECONDS

    def model_post_init(self, __context: object, /) -> None:
        public = urlparse(self.public_base_url)
        if public.scheme != "https" or not public.netloc:
            raise ValueError("authorized Web mode requires an HTTPS public base URL")
        if public.path not in ("", "/") or public.query or public.fragment:
            raise ValueError("public base URL must be an origin without path or query")
        web = urlparse(self.github_web_url)
        api = urlparse(self.github_api_url)
        if web.scheme != "https" or api.scheme != "https":
            raise ValueError("GitHub web and API URLs must use HTTPS")

    @property
    def allowed_origin(self) -> str:
        """Exact origin string every mutation's Origin header must equal."""

        public = urlparse(self.public_base_url)
        return f"{public.scheme}://{public.netloc}"

    @property
    def callback_url(self) -> str:
        return f"{self.public_base_url}/api/v1/auth/github/callback"


def load_web_auth_configuration(
    environ: dict[str, str],
    *,
    public_base_url: str,
    github_api_url: str,
) -> WebAuthConfiguration | None:
    """Return the authorized-mode config, or ``None`` for the default local mode.

    Setting the mode without any single prerequisite raises instead of
    silently downgrading to an open deployment (fail closed).
    """

    mode = environ.get(WEB_AUTH_MODE_ENV, "").strip()
    if not mode:
        return None
    if mode != GITHUB_OAUTH_MODE:
        raise ValueError(f"unsupported Web auth mode: {mode!r}")
    client_id = environ.get(OAUTH_CLIENT_ID_ENV, "").strip()
    client_secret = environ.get(OAUTH_CLIENT_SECRET_ENV, "").strip()
    if not client_id or not client_secret:
        raise ValueError(
            f"{GITHUB_OAUTH_MODE} mode requires {OAUTH_CLIENT_ID_ENV} and {OAUTH_CLIENT_SECRET_ENV}"
        )
    return WebAuthConfiguration(
        public_base_url=public_base_url,
        github_oauth_client_id=client_id,
        github_oauth_client_secret=client_secret,
        github_web_url=environ.get(GITHUB_WEB_URL_ENV, DEFAULT_GITHUB_WEB_URL).rstrip("/")
        or DEFAULT_GITHUB_WEB_URL,
        github_api_url=github_api_url.rstrip("/") or DEFAULT_GITHUB_API_URL,
    )


class GitHubAuthenticatedUser(BaseModel):
    """The verified GitHub identity; the numeric ID is the correlation key."""

    model_config = ConfigDict(frozen=True)

    user_id: int = Field(gt=0)
    login: str = Field(min_length=1)


class OAuthTransport(Protocol):
    """Server-side GitHub OAuth calls; stubbed in tests."""

    async def exchange_code_for_user_token(self, *, code: str, code_verifier: str) -> str:
        """Exchange the callback code (with PKCE verifier) for a user token."""
        ...

    async def get_authenticated_user(self, *, user_token: str) -> GitHubAuthenticatedUser:
        """Resolve ``GET /user`` for one user token."""
        ...


class HttpxOAuthTransport:
    """Production OAuth transport; tokens and secrets never enter exceptions."""

    def __init__(self, *, config: WebAuthConfiguration, http_client: object) -> None:
        self._config = config
        self._http_client = http_client

    async def exchange_code_for_user_token(self, *, code: str, code_verifier: str) -> str:
        import httpx

        assert isinstance(self._http_client, httpx.AsyncClient)
        try:
            response = await self._http_client.post(
                f"{self._config.github_web_url}/login/oauth/access_token",
                data={
                    "client_id": self._config.github_oauth_client_id,
                    "client_secret": self._config.github_oauth_client_secret,
                    "code": code,
                    "redirect_uri": self._config.callback_url,
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
        except Exception as exc:
            raise AuthenticationError(
                "oauth_exchange_failed", "GitHub token exchange is unreachable"
            ) from exc
        if response.status_code != 200:
            raise AuthenticationError(
                "oauth_exchange_failed", "GitHub rejected the authorization code"
            )
        payload = response.json()
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise AuthenticationError(
                "oauth_exchange_failed", "GitHub returned no user access token"
            )
        return token

    async def get_authenticated_user(self, *, user_token: str) -> GitHubAuthenticatedUser:
        import httpx

        assert isinstance(self._http_client, httpx.AsyncClient)
        try:
            response = await self._http_client.get(
                f"{self._config.github_api_url}/user",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {user_token}",
                },
            )
        except Exception as exc:
            raise AuthenticationError(
                "github_identity_unavailable", "GitHub identity check is unreachable"
            ) from exc
        if response.status_code != 200:
            raise AuthenticationError(
                "github_identity_unavailable", "GitHub rejected the user token"
            )
        payload = response.json()
        user_id = payload.get("id")
        login = payload.get("login")
        if not isinstance(user_id, int) or user_id <= 0 or not isinstance(login, str):
            raise AuthenticationError(
                "github_identity_unavailable", "GitHub returned an incomplete identity"
            )
        return GitHubAuthenticatedUser(user_id=user_id, login=login)


class WebSession(BaseModel):
    """One authenticated browser session. ``user_token`` never leaves the server."""

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(min_length=1)
    actor_id: int = Field(gt=0)
    actor_login: str = Field(min_length=1)
    csrf_token: str = Field(min_length=1)
    expires_at: datetime
    user_token: str = Field(min_length=1, repr=False, exclude=True)


class _LoginAttempt(BaseModel):
    state: str
    code_verifier: str
    browser_nonce: str
    expires_at: datetime


class LoginStart(BaseModel):
    """The authorize URL plus the browser-bound nonce for the pre-login cookie."""

    model_config = ConfigDict(frozen=True)

    authorize_url: str
    browser_nonce: str
    max_age_seconds: int


class SessionStore:
    """In-memory single-process session store; restart requires re-login."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sessions: dict[str, WebSession] = {}

    def create(
        self,
        *,
        actor_id: int,
        actor_login: str,
        user_token: str,
        ttl_seconds: int,
    ) -> WebSession:
        # Fresh random ID on every login: session fixation cannot apply.
        session = WebSession(
            session_id=secrets.token_urlsafe(32),
            actor_id=actor_id,
            actor_login=actor_login,
            csrf_token=secrets.token_urlsafe(32),
            expires_at=self._clock() + timedelta(seconds=ttl_seconds),
            user_token=user_token,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str | None) -> WebSession | None:
        if not session_id:
            return None
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.expires_at <= self._clock():
            self._sessions.pop(session_id, None)
            return None
        return session

    def revoke(self, session_id: str | None) -> None:
        if session_id:
            self._sessions.pop(session_id, None)

    def revoke_actor(self, actor_id: int) -> int:
        """Drop every session for one GitHub user (e.g. App authorization revoked)."""

        doomed = [sid for sid, s in self._sessions.items() if s.actor_id == actor_id]
        for sid in doomed:
            self._sessions.pop(sid, None)
        return len(doomed)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def read_session_cookie(cookie_header: str | None) -> str | None:
    """Extract the session cookie without trusting any other client header."""

    return _read_cookie(cookie_header, SESSION_COOKIE_NAME)


def read_login_nonce_cookie(cookie_header: str | None) -> str | None:
    return _read_cookie(cookie_header, LOGIN_NONCE_COOKIE_NAME)


def _read_cookie(cookie_header: str | None, name: str) -> str | None:
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name and value:
            return value
    return None


class GitHubWebAuthenticator:
    """GitHub App user-token web flow plus opaque server-side sessions."""

    def __init__(
        self,
        *,
        config: WebAuthConfiguration,
        transport: OAuthTransport,
        sessions: SessionStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sessions = sessions or SessionStore(clock=self._clock)
        self._login_attempts: dict[str, _LoginAttempt] = {}

    @property
    def config(self) -> WebAuthConfiguration:
        return self._config

    @property
    def sessions(self) -> SessionStore:
        return self._sessions

    def start_login(self) -> LoginStart:
        """Begin the flow: one-time state + PKCE S256, fixed callback URL.

        The returned nonce must reach the browser as a short-lived HttpOnly
        cookie; the callback is only honored when the same browser presents it,
        so a leaked callback URL cannot be replayed from another browser
        (login CSRF / session swapping).
        """

        self._sweep_login_attempts()
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(48)
        browser_nonce = secrets.token_urlsafe(24)
        self._login_attempts[state] = _LoginAttempt(
            state=state,
            code_verifier=verifier,
            browser_nonce=browser_nonce,
            expires_at=self._clock() + timedelta(seconds=self._config.login_state_ttl_seconds),
        )
        query = urlencode(
            {
                "client_id": self._config.github_oauth_client_id,
                "redirect_uri": self._config.callback_url,
                "state": state,
                "code_challenge": _pkce_challenge(verifier),
                "code_challenge_method": "S256",
            }
        )
        return LoginStart(
            authorize_url=f"{self._config.github_web_url}/login/oauth/authorize?{query}",
            browser_nonce=browser_nonce,
            max_age_seconds=self._config.login_state_ttl_seconds,
        )

    async def complete_login(
        self, *, state: str, code: str, browser_nonce: str | None
    ) -> WebSession:
        attempt = self._login_attempts.pop(state, None)  # one-time, even on failure
        if (
            attempt is None
            or attempt.expires_at <= self._clock()
            or browser_nonce is None
            or not hmac.compare_digest(browser_nonce, attempt.browser_nonce)
        ):
            raise AuthenticationError(
                "oauth_state_mismatch", "login state is unknown, expired, or already used"
            )
        if not code:
            raise AuthenticationError("oauth_exchange_failed", "missing authorization code")
        try:
            user_token = await self._transport.exchange_code_for_user_token(
                code=code,
                code_verifier=attempt.code_verifier,
            )
            user = await self._transport.get_authenticated_user(user_token=user_token)
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError(
                "github_identity_unavailable", "GitHub identity verification failed"
            ) from exc
        return self._sessions.create(
            actor_id=user.user_id,
            actor_login=user.login,
            user_token=user_token,
            ttl_seconds=self._config.session_ttl_seconds,
        )

    def session_for_cookie(self, cookie_header: str | None) -> WebSession | None:
        return self._sessions.get(read_session_cookie(cookie_header))

    async def reverify_session_user(self, session: WebSession) -> WebSession:
        """Re-check ``GET /user`` before a sensitive action; any drift fails closed."""

        if session.expires_at <= self._clock():
            self._sessions.revoke(session.session_id)
            raise AuthenticationError("session_expired", "the session has expired")
        try:
            user = await self._transport.get_authenticated_user(user_token=session.user_token)
        except Exception as exc:
            raise AuthenticationError(
                "github_identity_unavailable", "GitHub identity verification failed"
            ) from exc
        if user.user_id != session.actor_id:
            self._sessions.revoke(session.session_id)
            raise AuthenticationError(
                "authentication_required", "the GitHub identity no longer matches the session"
            )
        return session

    async def revoke_actor_sessions(self, actor_id: int) -> int:
        return self._sessions.revoke_actor(actor_id)

    def logout(self, cookie_header: str | None) -> None:
        self._sessions.revoke(read_session_cookie(cookie_header))

    def assert_session_mutation(
        self,
        session: WebSession,
        *,
        csrf_token: str | None,
        origin: str | None,
    ) -> None:
        """Session-level CSRF: exact configured origin plus per-session token.

        Browsers always send Origin on cross-site-capable mutations, so a
        missing Origin is treated as a forged/non-browser request and rejected
        — never silently allowed.
        """

        if origin is None or origin != self._config.allowed_origin:
            raise AuthenticationError("csrf_rejected", "cross-origin mutation rejected")
        if not csrf_token or not hmac.compare_digest(csrf_token, session.csrf_token):
            raise AuthenticationError("csrf_rejected", "session CSRF token missing or invalid")

    def _sweep_login_attempts(self) -> None:
        now = self._clock()
        for state, attempt in list(self._login_attempts.items()):
            if attempt.expires_at <= now:
                self._login_attempts.pop(state, None)
