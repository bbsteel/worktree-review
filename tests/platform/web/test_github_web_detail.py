"""GitHub Attempts in the Web API: detail, SSE replay+poll tail, list merge."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from worktree_review.application.review_events import ReviewEvent, utc_now
from worktree_review.platform.github.persistence import InMemoryGitHubReviewStore
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot
from worktree_review.platform.web.runtime import open_web_runtime
from worktree_review.server.app import create_app
from worktree_review.server.state import (
    GitHubChangeRequestLocator,
    InMemoryAuthoritativeAttemptStore,
    JobStatus,
)

pytest.importorskip("fastapi")

from worktree_review.core.identity import PolicyVersionIdentity, ReviewRequestKey

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


def _snapshot(attempt_id: str) -> AttemptExecutionSnapshot:
    return AttemptExecutionSnapshot(
        attempt_id=attempt_id,
        change_request=_LOCATOR,
        request_key=_REQUEST_KEY,
        proposed_ref="HEAD",
        review_policy_semver="1.0.0",
        review_policy_sha256="d" * 64,
        compute_policy_semver="1.0.0",
        compute_policy_sha256="e" * 64,
        pull_request_title="Harden webhook authorization",
        author_login="octocat",
    )


def _event(attempt_id: str, sequence: int, event_type: str) -> ReviewEvent:
    return ReviewEvent(
        sequence=sequence,
        occurred_at=utc_now(),
        attempt_id=attempt_id,
        surface="github",
        event_type=event_type,
        payload={},
    )


async def _app_with_github(tmp_path: Path):
    from fastapi.testclient import TestClient

    runtime = await open_web_runtime(tmp_path / "gh.sqlite")
    runtime.csrf_token = "test-csrf"
    github_store = InMemoryGitHubReviewStore()
    attempt_store = InMemoryAuthoritativeAttemptStore()
    application = create_app(web_runtime=runtime, enable_local_web=False, serve_frontend=False)
    # Construct a minimal ServerRuntime shell with the in-memory GitHub stores.
    import httpx

    from worktree_review.platform.github.runtime import ServerRuntime

    application.state.server_runtime = ServerRuntime(
        retry_coordinator=None,  # type: ignore[arg-type]
        database_pool=None,  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(),
        github_store=github_store,  # type: ignore[arg-type]
        attempt_store=attempt_store,  # type: ignore[arg-type]
    )
    lease = await attempt_store.start_authoritative_attempt(
        change_request=_LOCATOR, request_key=_REQUEST_KEY
    )
    return (
        application,
        TestClient(application, base_url="http://127.0.0.1"),
        github_store,
        attempt_store,
        lease.attempt_id,
    )


@pytest.mark.asyncio
async def test_github_attempt_detail_and_events_come_from_postgres_store(tmp_path: Path) -> None:
    _application, client, github_store, _attempt_store, attempt_id = await _app_with_github(
        tmp_path
    )
    await github_store.save_execution_snapshot(_snapshot(attempt_id))
    await github_store.set_check_run_id(attempt_id, 99)
    await github_store.append_review_event(_event(attempt_id, 1, "attempt.created"))
    await github_store.append_review_event(_event(attempt_id, 2, "stage.started"))
    await github_store.append_review_event(_event(attempt_id, 3, "attempt.failed"))
    with client:
        detail = client.get(f"/api/v1/reviews/{attempt_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["attempt_id"] == attempt_id
        assert body["source"]["kind"] == "github-pull-request"
        assert body["source"]["pull_request_number"] == 42
        assert body["authority"] == "authoritative"
        # Web actions must not let a local user impersonate a GitHub actor.
        assert body["available_actions"]["retry"]["enabled"] is False
        assert body["available_actions"]["bypass"]["enabled"] is False

        # Non-terminal SSE: replays persisted PostgreSQL events.
        events_response = client.get(f"/api/v1/reviews/{attempt_id}/events?since=0")
        text = events_response.text
        assert "attempt.created" in text
        assert "stage.started" in text
        assert "attempt.failed" in text
        assert "id: 1" in text and "id: 2" in text and "id: 3" in text

        # A GitHub Attempt appears in the review list/history.
        listed = client.get("/api/v1/reviews")
        runs = listed.json()["runs"]
        assert any(run["attempt_id"] == attempt_id for run in runs)

        # And it is counted in the Overview statistics, not just the lists.
        from worktree_review.core.identity import ResolvedCommitPair
        from worktree_review.core.report import (
            ComputePolicyDisclosure,
            ExecutionRecord,
            ReviewReport,
        )
        from worktree_review.platform.cli.result import cli_result_document

        report = ReviewReport(
            attempt_id=attempt_id,
            resolved=ResolvedCommitPair(
                source_repository="octo/example",
                target_ref="main",
                target_head_oid="a" * 40,
                proposed_ref="HEAD",
                proposed_head_oid="b" * 40,
                proposed_source="committed-ref",
            ),
            request_key=_REQUEST_KEY,
            review_identity=None,
            merge_tree_oid=None,
            review_policy_version=_REQUEST_KEY.review_policy_version,
            compute_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="e" * 64),
            compute_policy_disclosure=ComputePolicyDisclosure(
                provider="anthropic",
                model="claude",
                max_output_tokens_per_call=1024,
                max_budget_usd=None,
                data_destination="https://api.anthropic.com",
                known_retention="none",
            ),
            execution=ExecutionRecord(),
            summary="blocked",
            error_detail=None,
            gate_state="Blocked",
        )
        await github_store.save_review_result(
            attempt_id,
            cli_result_document(report).model_dump_json(by_alias=True),
        )
        overview = client.get("/api/v1/overview")
        stats = overview.json()["stats"]
        assert stats["attempt_count"] == 1
        assert stats["blocked_count"] == 1
        assert stats["unknown_cost_record_count"] == 1

        # Local Web retry must not reach GitHub attempts.
        retry = client.post(
            f"/api/v1/reviews/{attempt_id}/retry",
            headers={"X-CSRF-Token": "test-csrf", "Idempotency-Key": "r1"},
        )
        assert retry.status_code == 404


@pytest.mark.asyncio
async def test_github_sse_tails_new_events_and_ends_at_terminal(tmp_path: Path) -> None:
    from worktree_review.platform.web.sse import iter_github_attempt_events

    store = InMemoryGitHubReviewStore()
    await store.append_review_event(_event("gh-2", 1, "attempt.created"))

    collected: list[ReviewEvent] = []

    async def _producer() -> None:
        await asyncio.sleep(0.05)
        await store.append_review_event(_event("gh-2", 2, "stage.started"))
        await asyncio.sleep(0.05)
        await store.append_review_event(_event("gh-2", 3, "attempt.completed"))

    producer = asyncio.create_task(_producer())
    async for item in iter_github_attempt_events(
        store, "gh-2", poll_seconds=0.02, heartbeat_seconds=60
    ):
        if item is not None:
            collected.append(item)
    await producer
    assert [event.sequence for event in collected] == [1, 2, 3]
    assert collected[-1].event_type == "attempt.completed"


@pytest.mark.asyncio
async def test_github_sse_reconnect_with_last_event_id(tmp_path: Path) -> None:
    from worktree_review.platform.web.sse import iter_github_attempt_events

    store = InMemoryGitHubReviewStore()
    for sequence in range(1, 4):
        await store.append_review_event(
            _event("gh-3", sequence, "stage.completed" if sequence < 3 else "attempt.completed")
        )
    collected: list[int] = []
    async for item in iter_github_attempt_events(
        store, "gh-3", last_event_id="2", poll_seconds=0.01
    ):
        if item is not None:
            collected.append(item.sequence)
    assert collected == [3]


@pytest.mark.asyncio
async def test_exhausted_github_attempt_detail_shows_failed_not_in_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After retry exhaustion the Detail must be a stable failed/error view."""
    _application, client, github_store, attempt_store, attempt_id = await _app_with_github(tmp_path)
    await github_store.save_execution_snapshot(_snapshot(attempt_id))
    await github_store.set_check_run_id(attempt_id, 99)
    await attempt_store.claim_attempt_job(attempt_id)

    # While the job is still RUNNING, an execution failure carrying a raw
    # credential lands in job.last_error — via the durable layer the payload
    # is already typed/scrubbed; direct store writes are scrubbed at the
    # persistence boundary. Covers both pattern- and env-value-based secrets.
    raw_pattern_secret = "sk-supersecret-credential-12345"
    custom_env_secret = "vendor-token-value-12345"
    monkeypatch.setenv("MY_VENDOR_PROVIDER_TOKEN", custom_env_secret)
    await attempt_store.mark_job_retryable(
        attempt_id=attempt_id,
        error=f"provider handshake failed with {raw_pattern_secret} and {custom_env_secret}",
    )
    persisted_error = await attempt_store.job_last_error(attempt_id)
    assert persisted_error is not None
    assert raw_pattern_secret not in persisted_error
    assert custom_env_secret not in persisted_error

    await attempt_store.recover_interrupted_jobs(max_attempts=1, lease_seconds=0.0)
    with client:
        detail = client.get(f"/api/v1/reviews/{attempt_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["run_status"] == "failed"
        assert body["gate_state"] == "error"
        assert body["failure"]["category"] == "retry-exhausted"
        assert "provider handshake failed" in body["failure"]["safe_detail"]
        assert raw_pattern_secret not in str(body)
        assert custom_env_secret not in str(body)

        # A refetch (page refresh) returns the same terminal view.
        refreshed = client.get(f"/api/v1/reviews/{attempt_id}").json()
        assert refreshed["run_status"] == "failed"
        assert refreshed["gate_state"] == "error"


@pytest.mark.asyncio
async def test_overview_counts_queued_running_and_failed_github_attempts(
    tmp_path: Path,
) -> None:
    from worktree_review.core.identity import PolicyVersionIdentity
    from worktree_review.core.identity import ReviewRequestKey as _RK
    from worktree_review.server.state import GitHubChangeRequestLocator as _Loc

    _application, client, github_store, attempt_store, first_id = await _app_with_github(tmp_path)
    await github_store.save_execution_snapshot(_snapshot(first_id))
    # A second, still-queued attempt (no result, no job claim).
    second = await attempt_store.start_authoritative_attempt(
        change_request=_Loc(installation_id=7, repository="octo/other", pull_request_number=7),
        request_key=_RK(
            source_repository="octo/other",
            target_ref="main",
            target_head_oid="a" * 40,
            proposed_head_oid="b" * 40,
            review_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="d" * 64),
        ),
    )
    await github_store.save_execution_snapshot(_snapshot(second.attempt_id))
    # The first attempt exhausts its retry budget without a result.
    await attempt_store.claim_attempt_job(first_id)
    await attempt_store.mark_job_retryable(attempt_id=first_id, error="mirror exploded")
    await attempt_store.recover_interrupted_jobs(max_attempts=1, lease_seconds=0.0)

    with client:
        stats = client.get("/api/v1/overview").json()["stats"]
        assert stats["attempt_count"] == 2
        assert stats["error_count"] == 1  # the exhausted one
        assert stats["passed_count"] == 0
        assert stats["unknown_cost_record_count"] == 2


@pytest.mark.asyncio
async def test_overview_counts_attempt_once_when_result_exists_but_job_failed(
    tmp_path: Path,
) -> None:
    """Result exists but publication exhausted → gate kept, counted once, no error."""
    from worktree_review.core.identity import ResolvedCommitPair
    from worktree_review.core.report import (
        ComputePolicyDisclosure,
        ExecutionRecord,
        ReviewReport,
    )
    from worktree_review.platform.cli.result import cli_result_document

    _application, client, github_store, attempt_store, attempt_id = await _app_with_github(tmp_path)
    await github_store.save_execution_snapshot(_snapshot(attempt_id))
    await github_store.set_check_run_id(attempt_id, 99)
    report = ReviewReport(
        attempt_id=attempt_id,
        resolved=ResolvedCommitPair(
            source_repository="octo/example",
            target_ref="main",
            target_head_oid="a" * 40,
            proposed_ref="HEAD",
            proposed_head_oid="b" * 40,
            proposed_source="committed-ref",
        ),
        request_key=_REQUEST_KEY,
        review_identity=None,
        merge_tree_oid=None,
        review_policy_version=_REQUEST_KEY.review_policy_version,
        compute_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="e" * 64),
        compute_policy_disclosure=ComputePolicyDisclosure(
            provider="anthropic",
            model="claude",
            max_output_tokens_per_call=1024,
            max_budget_usd=None,
            data_destination="https://api.anthropic.com",
            known_retention="none",
        ),
        execution=ExecutionRecord(),
        summary="passed",
        error_detail=None,
        gate_state="Passed",
    )
    await github_store.save_review_result(
        attempt_id, cli_result_document(report).model_dump_json(by_alias=True)
    )
    # Publication retry budget exhausted AFTER the result was saved: the job
    # lands in FAILED, but the Gate decision itself is unchanged.
    await attempt_store.claim_attempt_job(attempt_id)
    await attempt_store.finalize_attempt_job(
        attempt_id, status=JobStatus.FAILED, reason="publication retry budget exhausted"
    )
    with client:
        stats = client.get("/api/v1/overview").json()["stats"]
        assert stats["attempt_count"] == 1
        assert stats["passed_count"] == 1
        assert stats["error_count"] == 0
        assert stats["blocked_count"] == 0
