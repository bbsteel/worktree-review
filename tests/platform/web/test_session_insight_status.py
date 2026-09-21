"""Session Insight integration status, journal contract, and degradation."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from worktree_review.application.review_events import ReviewEvent, utc_now
from worktree_review.core.provider import ScriptedProvider
from worktree_review.platform.session_insight.journal import (
    METADATA_SCHEMA,
    SessionJournalWriter,
)
from worktree_review.platform.session_insight.status import (
    SessionInsightMonitor,
    SessionInsightState,
    session_insight_base_url_from_environment,
    session_insight_disabled_from_environment,
)
from worktree_review.platform.web.registry import (
    register_local_repository,
    register_trusted_policy,
)
from worktree_review.platform.web.runtime import open_web_runtime
from worktree_review.platform.web.worker import execute_attempt

pytest.importorskip("fastapi")


def _monitor_with(payload: object, status_code: int = 200) -> SessionInsightMonitor:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SessionInsightMonitor(base_url="http://127.0.0.1:5599", http_client=client)


@pytest.mark.asyncio
async def test_probe_connected_requires_the_worktree_review_reader() -> None:
    monitor = _monitor_with(
        [
            {"type": "worktree-review", "adapter_revision": 1, "discovered": True},
            {"type": "claude-code", "adapter_revision": 3},
        ]
    )
    result = await monitor.current()
    assert result.state is SessionInsightState.CONNECTED
    assert result.reader_revision == "1"
    assert (
        monitor.deep_link("attempt-1")
        == "http://127.0.0.1:5599/#/session/worktree-review/attempt-1"
    )


@pytest.mark.asyncio
async def test_probe_incompatible_when_reader_missing() -> None:
    monitor = _monitor_with([{"type": "claude-code"}])
    result = await monitor.current()
    assert result.state is SessionInsightState.INCOMPATIBLE


@pytest.mark.asyncio
async def test_probe_disconnected_on_network_and_http_failures() -> None:
    def failing(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(failing))
    monitor = SessionInsightMonitor(base_url="http://127.0.0.1:5599", http_client=client)
    assert (await monitor.current()).state is SessionInsightState.DISCONNECTED
    assert (await _monitor_with({}, status_code=503).current()).state is (
        SessionInsightState.DISCONNECTED
    )


@pytest.mark.asyncio
async def test_probe_disabled_and_unconfigured() -> None:
    disabled = SessionInsightMonitor(base_url="http://127.0.0.1:5599", disabled=True)
    assert (await disabled.current()).state is SessionInsightState.DISABLED
    unconfigured = SessionInsightMonitor(base_url=None)
    assert (await unconfigured.current()).state is SessionInsightState.DISCONNECTED
    assert unconfigured.deep_link("attempt-1") is None


def test_environment_parsing() -> None:
    assert session_insight_base_url_from_environment({}) is None
    assert (
        session_insight_base_url_from_environment(
            {"WORKTREE_REVIEW_SESSION_INSIGHT_URL": "http://127.0.0.1:5588/"}
        )
        == "http://127.0.0.1:5588"
    )
    assert (
        session_insight_base_url_from_environment(
            {"WORKTREE_REVIEW_SESSION_INSIGHT_URL": "file:///etc/passwd"}
        )
        is None
    )
    assert session_insight_disabled_from_environment(
        {"WORKTREE_REVIEW_SESSION_INSIGHT_DISABLED": "1"}
    )
    assert not session_insight_disabled_from_environment({})


@pytest.mark.asyncio
async def test_journal_contract_files(tmp_path: Path) -> None:
    journal = SessionJournalWriter(tmp_path / "sessions")
    event = ReviewEvent(
        sequence=1,
        occurred_at=utc_now(),
        attempt_id="attempt-j1",
        surface="web",
        event_type="attempt.created",
        payload={"source": "local-worktree"},
    )
    await journal.publish(event)
    journal.write_result("attempt-j1", json.dumps({"schema": "worktree-review.cli.result/v1"}))
    directory = tmp_path / "sessions" / "attempt-j1"
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["schema"] == METADATA_SCHEMA
    assert metadata["attempt_id"] == "attempt-j1"
    assert metadata["last_persisted_sequence"] == 1
    lines = (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["sequence"] == 1
    assert (directory / "result.json").is_file()
    # Result is immutable once written.
    journal.write_result("attempt-j1", json.dumps({"overwritten": True}))
    assert "overwritten" not in (directory / "result.json").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_journal_failure_is_observation_warning_not_gate_input(tmp_path: Path) -> None:
    journal = SessionJournalWriter(tmp_path / "sessions")
    # Make the journal root unusable by placing a file where a directory goes.
    blocker = tmp_path / "sessions" / "attempt-x"
    blocker.parent.mkdir(parents=True)
    blocker.write_text("not a directory", encoding="utf-8")
    event = ReviewEvent(
        sequence=1,
        occurred_at=utc_now(),
        attempt_id="attempt-x",
        surface="web",
        event_type="attempt.created",
        payload={},
    )
    await journal.publish(event)  # must not raise
    assert journal.last_error is not None


@pytest.mark.asyncio
async def test_disabled_session_insight_still_completes_reviews(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    runtime = await open_web_runtime(
        tmp_path / "si-off.sqlite",
        environ={"WORKTREE_REVIEW_SESSION_INSIGHT_DISABLED": "1"},
    )
    assert runtime.journal is None
    runtime.provider_factory = lambda _policy, _config: ScriptedProvider(
        payloads={"correctness": {"findings": []}}
    )
    repository = await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )
    review = await register_trusted_policy(
        runtime.store, policy_dir / "review-policy.yaml", kind="review"
    )
    await runtime.store.insert_provider_profile(
        profile_id="profile-test",
        name="test",
        provider="anthropic",
        credential_reference="${ANTHROPIC_API_KEY}",
    )
    compute = await register_trusted_policy(
        runtime.store,
        policy_dir / "compute-policy.yaml",
        kind="compute",
        provider_profile_id="profile-test",
    )
    attempt_id = "attempt-si-off"
    from worktree_review.application.lifecycle import RunStatus
    from worktree_review.application.review_events import ReviewEvent as _ReviewEvent

    await runtime.store.create_attempt_with_initial_event_and_idempotency(
        attempt_id=attempt_id,
        idempotency_key="si-off",
        request_digest="d",
        initial_event=_ReviewEvent(
            sequence=1,
            occurred_at=utc_now(),
            attempt_id=attempt_id,
            surface="web",
            event_type="attempt.created",
            payload={},
        ),
        run_status=RunStatus.QUEUED,
        request_json=json.dumps(
            {
                "repository_id": repository["id"],
                "source": {"kind": "local-worktree", "target_ref": "main"},
                "review_policy_id": review["id"],
                "compute_policy_id": compute["id"],
            }
        ),
    )
    await execute_attempt(runtime, attempt_id)
    run = await runtime.store.get_run(attempt_id)
    assert run is not None
    assert run.run_status.value == "completed"
    assert run.result_json is not None
