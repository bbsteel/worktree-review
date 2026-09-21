"""GitHub App installation tokens. Static PAT is smoke-only and explicit."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from worktree_review.platform.github.errors import GitHubApiError, ServerConfigurationError

SMOKE_PAT_MODE = "smoke-pat"
APP_MODE = "app"
_JWT_LIFETIME_SECONDS = 540
_REFRESH_SKEW = timedelta(seconds=60)
_MINIMAL_PERMISSIONS = {
    "checks": "write",
    "contents": "read",
    "metadata": "read",
    "pull_requests": "read",
}


class InstallationTokenTransport(Protocol):
    async def create_installation_token(
        self, *, installation_id: int, app_jwt: str, permissions: Mapping[str, str]
    ) -> dict[str, object]:
        """Exchange an App JWT for a short-lived installation token."""
        ...


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _redact(value: str) -> str:
    if len(value) <= 8:
        return "[redacted]"
    return f"{value[:4]}…[redacted]"


def sign_github_app_jwt(*, app_id: str, private_key_pem: str, now: int | None = None) -> str:
    """Create a GitHub App JWT with RS256 via openssl. The PEM never enters the token."""

    issued_at = (now if now is not None else int(time.time())) - 60
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps(
            {"iat": issued_at, "exp": issued_at + _JWT_LIFETIME_SECONDS, "iss": app_id},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(private_key_pem)
        key_path = handle.name
    try:
        os.chmod(key_path, 0o600)
        process = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=signing_input,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ServerConfigurationError("GitHub App private key could not sign a JWT") from exc
    finally:
        Path(key_path).unlink(missing_ok=True)
    return f"{header}.{payload}.{_b64url(process.stdout)}"


class HttpxInstallationTokenTransport:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http_client = http_client

    async def create_installation_token(
        self, *, installation_id: int, app_jwt: str, permissions: Mapping[str, str]
    ) -> dict[str, object]:
        response = await self._http_client.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {app_jwt}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"permissions": dict(permissions)},
        )
        if response.is_error:
            raise GitHubApiError(
                f"installation token request failed with HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise GitHubApiError("installation token response must be a JSON object")
        return payload


@dataclass
class _CachedInstallationToken:
    token: str
    expires_at: datetime
    installation_id: int

    def __repr__(self) -> str:
        return (
            f"_CachedInstallationToken(installation_id={self.installation_id}, "
            f"token={_redact(self.token)}, expires_at={self.expires_at.isoformat()})"
        )


class InstallationTokenProvider:
    """Issue per-installation tokens. Never logs or stringifies the secret."""

    def __init__(
        self,
        *,
        app_id: str,
        private_key_pem: str,
        transport: InstallationTokenTransport,
        permissions: Mapping[str, str] | None = None,
    ) -> None:
        self._app_id = app_id
        self._private_key_pem = private_key_pem
        self._transport = transport
        self._permissions = dict(permissions or _MINIMAL_PERMISSIONS)
        self._cache: dict[int, _CachedInstallationToken] = {}

    def __repr__(self) -> str:
        return f"InstallationTokenProvider(app_id={self._app_id!r}, cached={len(self._cache)})"

    async def token_for_installation(self, installation_id: int) -> str:
        cached = self._cache.get(installation_id)
        now = datetime.now(UTC)
        if cached is not None and cached.expires_at - _REFRESH_SKEW > now:
            return cached.token
        app_jwt = sign_github_app_jwt(app_id=self._app_id, private_key_pem=self._private_key_pem)
        payload = await self._transport.create_installation_token(
            installation_id=installation_id,
            app_jwt=app_jwt,
            permissions=self._permissions,
        )
        token = payload.get("token")
        expires_at_raw = payload.get("expires_at")
        if not isinstance(token, str) or not token:
            raise GitHubApiError("installation token response is missing token")
        if not isinstance(expires_at_raw, str) or not expires_at_raw:
            raise GitHubApiError("installation token response is missing expires_at")
        expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
        self._cache[installation_id] = _CachedInstallationToken(
            token=token, expires_at=expires_at, installation_id=installation_id
        )
        return token


class SmokePatTokenProvider:
    """Explicit Pre-Alpha single-repository smoke mode. Not the App execution path."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ServerConfigurationError("smoke PAT is empty")
        self._token = token

    def __repr__(self) -> str:
        return f"SmokePatTokenProvider(token={_redact(self._token)})"

    async def token_for_installation(self, installation_id: int) -> str:
        del installation_id
        return self._token


def load_github_token_provider(
    environ: Mapping[str, str] | None = None,
    *,
    transport: InstallationTokenTransport | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> InstallationTokenProvider | SmokePatTokenProvider:
    source = dict(os.environ if environ is None else environ)
    mode = source.get("WORKTREE_REVIEW_GITHUB_AUTH_MODE", APP_MODE)
    if mode == SMOKE_PAT_MODE:
        token = source.get("WORKTREE_REVIEW_GITHUB_TOKEN", "")
        if not token:
            raise ServerConfigurationError(
                "WORKTREE_REVIEW_GITHUB_TOKEN is required for smoke-pat mode"
            )
        return SmokePatTokenProvider(token)
    if mode != APP_MODE:
        raise ServerConfigurationError(f"unknown GitHub auth mode: {mode}")
    static_token = source.get("WORKTREE_REVIEW_GITHUB_TOKEN", "")
    if static_token and source.get("WORKTREE_REVIEW_GITHUB_ALLOW_STATIC_PAT") != "1":
        raise ServerConfigurationError(
            "static GitHub PAT is not the App execution path; "
            "set WORKTREE_REVIEW_GITHUB_AUTH_MODE=smoke-pat for Pre-Alpha smoke only"
        )
    app_id = source.get("WORKTREE_REVIEW_GITHUB_APP_ID", "")
    private_key = source.get("WORKTREE_REVIEW_GITHUB_APP_PRIVATE_KEY", "")
    private_key_path = source.get("WORKTREE_REVIEW_GITHUB_APP_PRIVATE_KEY_PATH", "")
    if private_key_path and not private_key:
        private_key = Path(private_key_path).expanduser().read_text(encoding="utf-8")
    if not app_id or not private_key:
        raise ServerConfigurationError(
            "WORKTREE_REVIEW_GITHUB_APP_ID and App private key are required"
        )
    if transport is None:
        if http_client is None:
            raise ServerConfigurationError("GitHub HTTP client is required for App tokens")
        transport = HttpxInstallationTokenTransport(http_client)
    return InstallationTokenProvider(
        app_id=app_id, private_key_pem=private_key, transport=transport
    )
