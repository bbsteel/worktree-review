from __future__ import annotations

import base64
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from worktree_review.platform.github.runtime import ServerConfigurationError
from worktree_review.platform.github.tokens import (
    InstallationTokenProvider,
    SmokePatTokenProvider,
    load_github_token_provider,
    sign_github_app_jwt,
)


def _rsa_key(tmp_path: Path) -> str:
    key_path = tmp_path / "app.pem"
    subprocess.run(
        ["openssl", "genrsa", "-out", str(key_path), "2048"],
        check=True,
        capture_output=True,
    )
    return key_path.read_text(encoding="utf-8")


def _decode_jwt_part(part: str) -> dict[str, object]:
    padded = part + "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode()))


class _RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[int] = []
        self.jwts: list[str] = []

    async def create_installation_token(
        self, *, installation_id: int, app_jwt: str, permissions: dict[str, str]
    ) -> dict[str, object]:
        self.calls.append(installation_id)
        self.jwts.append(app_jwt)
        assert permissions["checks"] == "write"
        expiry = (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        return {"token": f"ghs_secret_{installation_id}", "expires_at": expiry}


def test_app_jwt_is_rs256_and_does_not_embed_the_private_key(tmp_path: Path) -> None:
    pem = _rsa_key(tmp_path)
    token = sign_github_app_jwt(app_id="99", private_key_pem=pem, now=1_700_000_000)
    header_b64, payload_b64, _signature = token.split(".")
    header = _decode_jwt_part(header_b64)
    payload = _decode_jwt_part(payload_b64)
    assert header["alg"] == "RS256"
    assert payload["iss"] == "99"
    assert "BEGIN" not in token
    assert "PRIVATE" not in token


@pytest.mark.asyncio
async def test_installation_tokens_are_cached_per_installation(tmp_path: Path) -> None:
    transport = _RecordingTransport()
    provider = InstallationTokenProvider(
        app_id="99",
        private_key_pem=_rsa_key(tmp_path),
        transport=transport,
    )
    first = await provider.token_for_installation(7)
    second = await provider.token_for_installation(7)
    other = await provider.token_for_installation(8)
    assert first == second == "ghs_secret_7"
    assert other == "ghs_secret_8"
    assert transport.calls == [7, 8]
    assert "ghs_secret" not in repr(provider)
    assert "BEGIN PRIVATE" not in repr(provider)


def test_static_pat_is_rejected_unless_explicit_smoke_mode() -> None:
    with pytest.raises(ServerConfigurationError, match="smoke-pat"):
        load_github_token_provider(
            {
                "WORKTREE_REVIEW_GITHUB_TOKEN": "ghp_live_secret",
            }
        )
    smoke = load_github_token_provider(
        {
            "WORKTREE_REVIEW_GITHUB_AUTH_MODE": "smoke-pat",
            "WORKTREE_REVIEW_GITHUB_TOKEN": "ghp_live_secret",
        }
    )
    assert isinstance(smoke, SmokePatTokenProvider)
    assert "ghp_live_secret" not in repr(smoke)
