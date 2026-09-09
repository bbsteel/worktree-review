from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from worktree_review.application.review_service import ReviewApplicationService
from worktree_review.platform.web.registry import (
    register_local_repository,
    register_trusted_policy,
)
from worktree_review.platform.web.runtime import open_web_runtime
from worktree_review.server.app import create_app

pytest.importorskip("fastapi")


async def _prepared_client(tmp_path: Path, git_repository: Path, policy_dir: Path):
    from fastapi.testclient import TestClient

    runtime = await open_web_runtime(tmp_path / "api.sqlite")
    repository = await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )
    review = await register_trusted_policy(
        runtime.store, policy_dir / "review-policy.yaml", kind="review"
    )
    compute = await register_trusted_policy(
        runtime.store, policy_dir / "compute-policy.yaml", kind="compute"
    )
    application = create_app(web_runtime=runtime, enable_local_web=False)
    client = TestClient(application, base_url="http://127.0.0.1")
    return client, runtime, repository, review, compute


def _create_body(
    repository: dict[str, str], review: dict[str, str], compute: dict[str, str]
) -> dict[str, Any]:
    return {
        "repository_id": repository["id"],
        "source": {"kind": "local-worktree", "target_ref": "main"},
        "review_policy_id": review["id"],
        "compute_policy_id": compute["id"],
    }


def _headers(idempotency: str | None = "key-1") -> dict[str, str]:
    headers = {"X-CSRF-Token": "test-csrf", "Origin": "http://127.0.0.1"}
    if idempotency is not None:
        headers["Idempotency-Key"] = idempotency
    return headers


@pytest.mark.asyncio
async def test_create_review_persists_then_returns_202_without_running_pipeline(
    tmp_path: Path, git_repository: Path, policy_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    async def _forbidden(*_args: object, **_kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("pipeline must not run inside the HTTP request")

    monkeypatch.setattr(ReviewApplicationService, "execute", _forbidden)
    client, runtime, repository, review, compute = await _prepared_client(
        tmp_path, git_repository, policy_dir
    )
    with client:
        first = client.post(
            "/api/v1/reviews",
            json=_create_body(repository, review, compute),
            headers=_headers("same-key"),
        )
        assert first.status_code == 202
        attempt_id = first.json()["attempt_id"]
        stored = await runtime.store.get_run(attempt_id)
        assert stored is not None
        events = await runtime.store.list_events(attempt_id)
        assert len(events) == 1
        assert events[0].event_type == "attempt.created"
        again = client.post(
            "/api/v1/reviews",
            json=_create_body(repository, review, compute),
            headers=_headers("same-key"),
        )
        assert again.status_code == 202
        assert again.json()["attempt_id"] == attempt_id
        conflict = client.post(
            "/api/v1/reviews",
            json={
                **_create_body(repository, review, compute),
                "source": {"kind": "local-committed-ref", "proposed_ref": "HEAD"},
            },
            headers=_headers("same-key"),
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_conflict"
        detail = client.get(f"/api/v1/reviews/{attempt_id}")
        assert detail.status_code == 200
        assert detail.json()["attempt_id"] == attempt_id
        assert detail.json()["run_status"] == "queued"
        result = client.get(f"/api/v1/reviews/{attempt_id}/result")
        assert result.status_code == 409
        assert result.json()["error"]["code"] == "result_unavailable"
    assert calls == 0
    assert runtime.queue.qsize() == 1


@pytest.mark.asyncio
async def test_mutations_require_loopback_and_csrf(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    client, _runtime, repository, review, compute = await _prepared_client(
        tmp_path, git_repository, policy_dir
    )
    body = _create_body(repository, review, compute)
    with client:
        missing_key = client.post(
            "/api/v1/reviews", json=body, headers={"X-CSRF-Token": "test-csrf"}
        )
        assert missing_key.status_code == 400
        missing_csrf = client.post("/api/v1/reviews", json=body, headers={"Idempotency-Key": "k"})
        assert missing_csrf.status_code == 403
        assert missing_csrf.json()["error"]["code"] == "missing_csrf_token"
    from fastapi.testclient import TestClient

    remote = TestClient(client.app, base_url="http://example.com")
    with remote:
        forbidden = remote.post(
            "/api/v1/reviews",
            json=body,
            headers={"Idempotency-Key": "k", "X-CSRF-Token": "test-csrf"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "forbidden_host"


@pytest.mark.asyncio
async def test_overview_and_repository_registration(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    client, _runtime, repository, review, compute = await _prepared_client(
        tmp_path, git_repository, policy_dir
    )
    with client:
        listed = client.get("/api/v1/repositories")
        assert listed.status_code == 200
        assert listed.json()[0]["repository_id"] == repository["id"]
        created = client.post(
            "/api/v1/reviews",
            json=_create_body(repository, review, compute),
            headers=_headers(),
        )
        assert created.status_code == 202
        overview = client.get("/api/v1/overview")
        assert overview.status_code == 200
        assert overview.json()["stats"]["attempt_count"] == 1
        policies = client.get("/api/v1/review-policies")
        assert policies.status_code == 200
        assert policies.json()[0]["policy_id"] == review["id"]
        compute_policies = client.get("/api/v1/compute-policies")
        assert compute_policies.status_code == 200
        assert compute_policies.json()[0]["policy_id"] == compute["id"]
