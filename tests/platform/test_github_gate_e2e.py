"""Hermetic GitHub Gate path: webhook → Attempt → snapshot → Check → worker → Detail."""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.gitutil import head_oid
from tests.platform.postgres_harness import database_url_for_name, open_postgres_url

from worktree_review.application.lifecycle import Authority, PublicationStatus
from worktree_review.core.provider import ScriptedProvider
from worktree_review.core.report import GateState
from worktree_review.platform.github.runtime import build_server_runtime
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot
from worktree_review.platform.github.tokens import InstallationTokenProvider
from worktree_review.server.app import create_app
from worktree_review.server.state import PublishDisposition

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
        provider_factory=lambda _snapshot: ScriptedProvider(
            payloads={"correctness": {"findings": []}}
        ),
    )

    async def builder() -> Any:
        return runtime

    application = create_app(
        github_webhook_secret=secret,
        runtime_builder=builder,
        enable_local_web=False,
        start_worker=False,
        start_github_worker=False,
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
            assert queued_dto["publication_status"] == PublicationStatus.QUEUED.value

            report_a = await runtime.review_worker.execute_claimed_attempt(attempt_a)  # type: ignore[union-attr]
            assert report_a is not None
            assert report_a.attempt_id == attempt_a
            assert report_a.gate_state is GateState.PASSED

            second = await post_webhook(
                client, _pr_payload(action="synchronize", oid=oid), delivery_id="delivery-sync"
            )
            assert second.status_code == 202
            attempt_b = second.json()["attempt_id"]
            assert attempt_b != attempt_a
            check_b = await runtime.github_store.get_check_run_id(attempt_b)
            assert check_b == 9002

            late = await runtime.publisher.publish_terminal(attempt_id=attempt_a, report=report_a)
            assert late.disposition is PublishDisposition.SUPERSEDED
            standing = await runtime.attempt_store.get_change_request_state(snapshot.change_request)
            assert standing.authoritative_attempt_id == attempt_b
            assert standing.standing_attempt_id != attempt_a
            assert standing.standing_gate_state is None
            superseded_patches = [item for item in mock.patched if item[0] == check_a]
            assert superseded_patches
            assert superseded_patches[0][0] == check_a

            report_b = await runtime.durable_worker.execute_attempt(attempt_b)
            assert report_b is not None
            assert report_b.gate_state is GateState.PASSED
            assert (
                await runtime.github_store.publication_status(attempt_b) is PublicationStatus.FAILED
            )
            after_fail = await runtime.attempt_store.get_change_request_state(
                snapshot.change_request
            )
            assert after_fail.standing_gate_state is GateState.PASSED
            assert after_fail.standing_attempt_id == attempt_b

            retry = await runtime.publisher.retry_outbox(attempt_b, report_b)
            assert retry.disposition is PublishDisposition.PUBLISHED
            assert (
                await runtime.github_store.publication_status(attempt_b)
                is PublicationStatus.PUBLISHED
            )
            completed = [item for item in mock.patched if item[0] == check_b]
            assert completed
            assert all(item[0] == check_b for item in completed)
            assert completed[-1][1]["details_url"] == f"{public_base}/reviews/{attempt_b}"
            assert completed[-1][1]["status"] == "completed"

            detail_a = (await client.get(f"/api/v1/reviews/{attempt_a}")).json()
            detail_b = (await client.get(f"/api/v1/reviews/{attempt_b}")).json()
            assert detail_a["attempt_id"] == attempt_a
            assert detail_a["source"]["kind"] == "github-pull-request"
            assert detail_a["authority"] == Authority.SUPERSEDED.value
            assert detail_a["gate_state"] == "passed"
            assert detail_b["attempt_id"] == attempt_b
            assert detail_b["authority"] == Authority.AUTHORITATIVE.value
            assert detail_b["publication_status"] == PublicationStatus.PUBLISHED.value
            assert detail_b["gate_state"] == "passed"
            assert detail_b["source"]["check_url"] == (
                f"https://github.com/octo/example/runs/{check_b}"
            )
            assert detail_b["source"]["pull_request_number"] == 42
            assert detail_b["summary"]["authority"] == Authority.AUTHORITATIVE.value

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
