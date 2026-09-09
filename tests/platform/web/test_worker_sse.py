from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from worktree_review.application.lifecycle import RunStatus
from worktree_review.application.review_events import ReviewEvent
from worktree_review.core.provider import ScriptedProvider
from worktree_review.platform.web.registry import (
    register_local_repository,
    register_trusted_policy,
)
from worktree_review.platform.web.runtime import open_web_runtime
from worktree_review.platform.web.sse import iter_attempt_events
from worktree_review.platform.web.worker import execute_attempt, recover_interrupted
from worktree_review.server.app import create_app

pytest.importorskip("fastapi")


def _event(attempt_id: str, sequence: int, event_type: str = "stage.started") -> ReviewEvent:
    return ReviewEvent(
        sequence=sequence,
        occurred_at=datetime.now(UTC),
        attempt_id=attempt_id,
        surface="web",
        event_type=event_type,
        payload={"stage": "derive-identity"},
    )


async def _runtime_with_repo(tmp_path: Path, git_repository: Path, policy_dir: Path):
    runtime = await open_web_runtime(tmp_path / "worker.sqlite")
    repository = await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )
    review = await register_trusted_policy(
        runtime.store, policy_dir / "review-policy.yaml", kind="review"
    )
    compute = await register_trusted_policy(
        runtime.store, policy_dir / "compute-policy.yaml", kind="compute"
    )
    runtime.provider_factory = lambda _policy, _config: ScriptedProvider(
        payloads={"correctness": {"findings": []}}
    )
    return runtime, repository, review, compute


@pytest.mark.asyncio
async def test_sse_replays_then_subscribes_without_dropping_events(
    tmp_path: Path,
) -> None:
    runtime = await open_web_runtime(tmp_path / "sse.sqlite")
    await runtime.store.create_attempt_with_initial_event_and_idempotency(
        attempt_id="a1",
        idempotency_key="k",
        request_digest="d",
        initial_event=_event("a1", 1, "attempt.created"),
    )
    await runtime.store.append_event(_event("a1", 2))

    async def _live() -> None:
        await asyncio.sleep(0.05)
        await runtime.broadcast(_event("a1", 3))
        await runtime.broadcast(_event("a1", 4, "attempt.completed"))

    task = asyncio.create_task(_live())
    received: list[int] = []
    async for item in iter_attempt_events(runtime, "a1"):
        if item is None:
            continue
        received.append(item.sequence)
        if item.event_type == "attempt.completed":
            break
    await task
    assert received == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_sse_last_event_id_skips_already_seen_sequences(tmp_path: Path) -> None:
    runtime = await open_web_runtime(tmp_path / "sse-id.sqlite")
    await runtime.store.create_attempt_with_initial_event_and_idempotency(
        attempt_id="a1",
        idempotency_key="k",
        request_digest="d",
        initial_event=_event("a1", 1, "attempt.created"),
    )
    await runtime.store.append_event(_event("a1", 2))
    await runtime.store.append_event(_event("a1", 3, "attempt.completed"))
    received = [
        item.sequence
        async for item in iter_attempt_events(runtime, "a1", last_event_id="2")
        if item is not None
    ]
    assert received == [3]


@pytest.mark.asyncio
async def test_worker_runs_pipeline_outside_http_and_http_still_does_not(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    from fastapi.testclient import TestClient

    runtime, repository, review, compute = await _runtime_with_repo(
        tmp_path, git_repository, policy_dir
    )
    application = create_app(web_runtime=runtime, enable_local_web=False, start_worker=False)
    body = {
        "repository_id": repository["id"],
        "source": {"kind": "local-worktree", "target_ref": "main"},
        "review_policy_id": review["id"],
        "compute_policy_id": compute["id"],
    }
    with TestClient(application, base_url="http://127.0.0.1") as client:
        created = client.post(
            "/api/v1/reviews",
            json=body,
            headers={"Idempotency-Key": "w1", "X-CSRF-Token": "test-csrf"},
        )
        assert created.status_code == 202
        assert runtime.pipeline_invocations == 0
        attempt_id = created.json()["attempt_id"]
    await execute_attempt(runtime, attempt_id)
    assert runtime.pipeline_invocations == 1
    stored = await runtime.store.get_run(attempt_id)
    assert stored is not None
    assert stored.result_json is not None
    events = await runtime.store.list_events(attempt_id)
    assert events[-1].event_type == "attempt.completed"


@pytest.mark.asyncio
async def test_restart_marks_running_attempts_interrupted(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    runtime, repository, review, compute = await _runtime_with_repo(
        tmp_path, git_repository, policy_dir
    )
    event = _event("run-1", 1, "attempt.created")
    await runtime.store.create_attempt_with_initial_event_and_idempotency(
        attempt_id="run-1",
        idempotency_key="k",
        request_digest="d",
        initial_event=event,
        request_json=(
            f'{{"repository_id":"{repository["id"]}",'
            '"source":{"kind":"local-worktree"},'
            f'"review_policy_id":"{review["id"]}",'
            f'"compute_policy_id":"{compute["id"]}"}}'
        ),
    )
    await runtime.store.update_run_status("run-1", RunStatus.RUNNING)
    await recover_interrupted(runtime)
    stored = await runtime.store.get_run("run-1")
    assert stored is not None
    assert stored.run_status is RunStatus.INTERRUPTED
    assert runtime.queue.qsize() == 1


@pytest.mark.asyncio
async def test_http_sse_endpoint_replays_by_last_event_id(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    runtime = await open_web_runtime(tmp_path / "sse-http.sqlite")
    await runtime.store.create_attempt_with_initial_event_and_idempotency(
        attempt_id="a1",
        idempotency_key="k",
        request_digest="d",
        initial_event=_event("a1", 1, "attempt.created"),
    )
    await runtime.store.append_event(_event("a1", 2, "attempt.completed"))
    application = create_app(web_runtime=runtime, enable_local_web=False, start_worker=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        response = client.get("/api/v1/reviews/a1/events", headers={"Last-Event-ID": "1"})
        assert response.status_code == 200
        assert "attempt.completed" in response.text
        assert "id: 2" in response.text
        assert "id: 1" not in response.text
