"""Hermetic GitHub Gate path: webhook → Attempt → snapshot → Check → worker → Detail."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import subprocess
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.gitutil import head_oid
from tests.platform.postgres_harness import database_url_for_name, open_postgres_url

from worktree_review.application.lifecycle import Authority, PublicationStatus
from worktree_review.core.provider import (
    DEFAULT_MAX_OUTPUT_TOKENS_PER_CALL,
    ScriptedProvider,
    UsageRecord,
)
from worktree_review.platform.github.runtime import build_server_runtime
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot
from worktree_review.platform.github.tokens import InstallationTokenProvider
from worktree_review.server.app import create_app

pytest.importorskip("fastapi")
pytest.importorskip("asyncpg")


@pytest.fixture(scope="session")
def postgres_base_url() -> Any:
    yield from open_postgres_url()


@pytest.fixture
async def github_database_url(postgres_base_url: str) -> str:
    import asyncpg

    name = f"wr_gate_{uuid.uuid4().hex[:12]}"
    connection = await asyncpg.connect(postgres_base_url)
    try:
        await connection.execute(f"CREATE DATABASE {name}")
    finally:
        await connection.close()
    return database_url_for_name(postgres_base_url, name)


def _rsa_key(tmp_path: Path) -> str:
    key_path = tmp_path / "app.pem"
    subprocess.run(
        ["openssl", "genrsa", "-out", str(key_path), "2048"],
        check=True,
        capture_output=True,
    )
    return key_path.read_text(encoding="utf-8")


def _signed(payload: dict[str, object], secret: str) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, f"sha256={digest}"


def _pr_payload(
    *,
    action: str,
    oid: str,
    draft: bool = False,
) -> dict[str, object]:
    return {
        "action": action,
        "installation": {"id": 7},
        "repository": {"full_name": "octo/example", "clone_url": "unused"},
        "pull_request": {
            "number": 42,
            "title": "Harden webhook",
            "draft": draft,
            "user": {"login": "ada"},
            "base": {"ref": "main", "sha": oid},
            "head": {"ref": "feature", "sha": oid},
        },
        "sender": {"login": "ada"},
    }


class _GitHubMock:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_calls = 0
        self.created_checks: list[dict[str, Any]] = []
        self.patched: list[tuple[int, dict[str, Any], str]] = []
        self.next_check_id = 9001
        self.fail_next_completed = True
        self.tokens_issued: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path.startswith("/app/installations/"):
            self.token_calls += 1
            token = f"ghs_install_{self.token_calls}_" + ("x" * 24)
            self.tokens_issued.append(token)
            ttl = timedelta(seconds=30) if self.token_calls == 1 else timedelta(hours=1)
            expires = (datetime.now(UTC) + ttl).isoformat().replace("+00:00", "Z")
            return httpx.Response(201, json={"token": token, "expires_at": expires})
        if request.method == "POST" and path.endswith("/check-runs"):
            payload = json.loads(request.content)
            check_id = self.next_check_id
            self.next_check_id += 1
            self.created_checks.append({"id": check_id, "payload": payload, "path": path})
            return httpx.Response(201, json={"id": check_id})
        if request.method == "PATCH" and "/check-runs/" in path:
            payload = json.loads(request.content)
            check_id = int(path.rsplit("/", 1)[-1])
            authorization = request.headers.get("authorization", "")
            if (
                payload.get("status") == "completed"
                and check_id == 9002
                and self.fail_next_completed
            ):
                self.fail_next_completed = False
                return httpx.Response(502, json={"message": "GitHub 502"})
            self.patched.append((check_id, payload, authorization))
            return httpx.Response(200, json={"id": check_id})
        if request.method == "GET" and path == "/repos/octo/example":
            return httpx.Response(200, json={"clone_url": "unused", "full_name": "octo/example"})
        return httpx.Response(404, json={"message": f"unhandled {request.method} {path}"})


class _HoldingProvider:
    """Scripted provider that pauses the first Attempt until the test releases it."""

    def __init__(
        self,
        inner: ScriptedProvider,
        *,
        seen: asyncio.Event,
        release: asyncio.Event,
        hold: bool,
    ) -> None:
        self._inner = inner
        self._seen = seen
        self._release = release
        self._hold = hold
        self.provider_name = inner.provider_name
        self.model = inner.model

    def estimate_input_tokens(self, text: str) -> UsageRecord:
        return self._inner.estimate_input_tokens(text)

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        response_schema: dict[str, object],
        dimension_id: str,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS_PER_CALL,
    ) -> tuple[dict[str, object], UsageRecord]:
        if self._hold:
            self._seen.set()
            await self._release.wait()
        return await self._inner.complete_structured(
            system=system,
            user=user,
            response_schema=response_schema,
            dimension_id=dimension_id,
            max_output_tokens=max_output_tokens,
        )


async def _poll_until(
    condition: Callable[[], Awaitable[bool]],
    *,
    limit_seconds: float = 20.0,
    interval: float = 0.05,
) -> None:
    deadline = time.monotonic() + limit_seconds
    while time.monotonic() < deadline:
        if await condition():
            return
        await asyncio.sleep(interval)
    raise AssertionError("timed out waiting for GitHub Gate worker")


@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore::ResourceWarning")
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_ready_pr_webhook_through_web_detail_dto(
    tmp_path: Path,
    git_repository: Path,
    policy_dir: Path,
    github_database_url: str,
) -> None:
    oid = head_oid(git_repository)
    secret = "webhook-secret"
    public_base = "http://127.0.0.1:8000"
    mock = _GitHubMock()
    github_http = httpx.AsyncClient(
        transport=httpx.MockTransport(mock.handler),
        base_url="https://api.github.test",
    )
    environ = {
        "WORKTREE_REVIEW_GITHUB_AUTH_MODE": "app",
        "WORKTREE_REVIEW_GITHUB_APP_ID": "99",
        "WORKTREE_REVIEW_GITHUB_APP_PRIVATE_KEY": _rsa_key(tmp_path),
    }

    async def resolve_clone(_snapshot: AttemptExecutionSnapshot) -> str:
        return str(git_repository)

    first_seen = asyncio.Event()
    first_release = asyncio.Event()
    hold_first = True

    def provider_factory(_snapshot: AttemptExecutionSnapshot) -> ScriptedProvider:
        nonlocal hold_first
        inner = ScriptedProvider(payloads={"correctness": {"findings": []}})
        should_hold = hold_first
        hold_first = False
        return _HoldingProvider(  # type: ignore[return-value]
            inner, seen=first_seen, release=first_release, hold=should_hold
        )

    runtime = await build_server_runtime(
        database_url=github_database_url,
        github_api_url="https://api.github.test",
        review_policy_path=policy_dir / "review-policy.yaml",
        compute_policy_path=policy_dir / "compute-policy.yaml",
        public_base_url=public_base,
        mirror_root=tmp_path / "mirrors",
        environ=environ,
        http_client=github_http,
        clone_url_resolver=resolve_clone,
        provider_factory=provider_factory,
    )
    assert runtime.durable_worker is not None
    runtime.durable_worker.idle_seconds = 0.05

    async def builder() -> Any:
        return runtime

    application = create_app(
        github_webhook_secret=secret,
        runtime_builder=builder,
        enable_local_web=False,
        start_worker=False,
        start_github_worker=True,
        serve_frontend=False,
    )

    async def post_webhook(
        client: httpx.AsyncClient,
        payload: dict[str, object],
        *,
        delivery_id: str,
        event_name: str = "pull_request",
    ) -> httpx.Response:
        body, signature = _signed(payload, secret)
        return await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "x-hub-signature-256": signature,
                "x-github-event": event_name,
                "x-github-delivery": delivery_id,
            },
        )

    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url=public_base,
        ) as client:
            first = await post_webhook(
                client,
                _pr_payload(action="ready_for_review", oid=oid),
                delivery_id="delivery-ready",
            )
            assert first.status_code == 202, first.text
            body = first.json()
            assert body["status"] == "accepted"
            attempt_a = body["attempt_id"]
            assert attempt_a

            duplicate = await post_webhook(
                client,
                _pr_payload(action="ready_for_review", oid=oid),
                delivery_id="delivery-ready",
            )
            assert duplicate.status_code == 202
            assert duplicate.json()["attempt_id"] == attempt_a
            assert duplicate.json()["detail"] == "delivery was already processed"

            assert runtime.github_store is not None
            assert runtime.attempt_store is not None
            assert runtime.durable_worker is not None
            assert runtime.publisher is not None
            snapshot = await runtime.github_store.get_execution_snapshot(attempt_a)
            assert snapshot is not None
            dumped = snapshot.as_public_dict()
            assert "token" not in dumped
            assert "ghs_" not in json.dumps(dumped)
            check_a = await runtime.github_store.get_check_run_id(attempt_a)
            assert check_a == 9001
            assert mock.created_checks[0]["payload"]["status"] == "queued"
            assert mock.created_checks[0]["payload"]["details_url"] == (
                f"{public_base}/reviews/{attempt_a}"
            )

            queued_detail = await client.get(f"/api/v1/reviews/{attempt_a}")
            assert queued_detail.status_code == 200
            queued_dto = queued_detail.json()
            assert queued_dto["source"]["kind"] == "github-pull-request"
            assert queued_dto["authority"] == Authority.AUTHORITATIVE.value
            created_at = queued_dto["summary"]["created_at"]
            assert created_at

            await asyncio.wait_for(first_seen.wait(), timeout=20)

            second = await post_webhook(
                client, _pr_payload(action="synchronize", oid=oid), delivery_id="delivery-sync"
            )
            assert second.status_code == 202
            attempt_b = second.json()["attempt_id"]
            assert attempt_b != attempt_a

            async def _check_b_queued() -> bool:
                return await runtime.github_store.get_check_run_id(attempt_b) is not None

            await _poll_until(_check_b_queued)
            check_b = await runtime.github_store.get_check_run_id(attempt_b)
            assert check_b == 9002
            first_release.set()

            async def _b_published() -> bool:
                response = await client.get(f"/api/v1/reviews/{attempt_b}")
                if response.status_code != 200:
                    return False
                body = response.json()
                return (
                    body.get("publication_status") == PublicationStatus.PUBLISHED.value
                    and body.get("authority") == Authority.AUTHORITATIVE.value
                    and body.get("gate_state") == "passed"
                )

            await _poll_until(_b_published)

            async def _a_superseded() -> bool:
                response = await client.get(f"/api/v1/reviews/{attempt_a}")
                if response.status_code != 200:
                    return False
                body = response.json()
                return (
                    body.get("authority") == Authority.SUPERSEDED.value
                    and body.get("gate_state") == "passed"
                )

            await _poll_until(_a_superseded)

            standing = await runtime.attempt_store.get_change_request_state(snapshot.change_request)
            assert standing.authoritative_attempt_id == attempt_b
            assert standing.standing_attempt_id == attempt_b
            assert standing.standing_gate_state is not None
            assert standing.standing_gate_state.value == "Passed"
            assert mock.fail_next_completed is False
            completed_b = [
                item
                for item in mock.patched
                if item[0] == check_b and item[1].get("status") == "completed"
            ]
            assert completed_b
            assert completed_b[-1][1]["details_url"] == f"{public_base}/reviews/{attempt_b}"
            superseded_patches = [item for item in mock.patched if item[0] == check_a]
            assert superseded_patches

            later_a = (await client.get(f"/api/v1/reviews/{attempt_a}")).json()
            later_b = (await client.get(f"/api/v1/reviews/{attempt_b}")).json()
            assert later_a["summary"]["created_at"] == created_at
            assert later_b["attempt_id"] == attempt_b
            assert later_b["source"]["kind"] == "github-pull-request"
            assert later_b["source"]["check_url"] == (
                f"https://github.com/octo/example/runs/{check_b}"
            )
            assert later_b["source"]["pull_request_number"] == 42
            assert later_b["summary"]["authority"] == Authority.AUTHORITATIVE.value
            persisted_created = await runtime.github_store.get_attempt_created_at(attempt_a)
            assert persisted_created is not None
            assert later_a["summary"]["created_at"] == persisted_created.isoformat()

            assert mock.token_calls >= 2
            assert isinstance(runtime.token_provider, InstallationTokenProvider)
            provider_repr = repr(runtime.token_provider)
            assert "ghs_install" not in provider_repr
            assert "BEGIN PRIVATE" not in provider_repr
            for issued in mock.tokens_issued:
                assert issued not in provider_repr
            authorizations = [
                request.headers.get("authorization", "")
                for request in mock.requests
                if request.url.path.endswith("/check-runs") or "/check-runs/" in request.url.path
            ]
            assert any(mock.tokens_issued[0] in value for value in authorizations)
            assert any(mock.tokens_issued[-1] in value for value in authorizations)
