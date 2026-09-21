"""Fault-injection tests for GitHub durable recovery (blocker 6).

Crash points covered:
1. after job claim;
2. mirror/provider initialisation failure;
3. after the terminal result is saved (no outbox intent);
4. after the outbox intent is saved (no remote delivery);
5. update_check_run failing repeatedly (bounded backoff, same check id);
6. an older Attempt finishing after a newer one took authority.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.core.identity import (
    MergeCandidateIdentity,
    PolicyVersionIdentity,
    ResolvedCommitPair,
    ReviewIdentity,
    ReviewRequestKey,
)
from worktree_review.core.report import (
    ComputePolicyDisclosure,
    ExecutionRecord,
    GateState,
    ReviewReport,
)
from worktree_review.platform.cli.result import cli_result_document
from worktree_review.platform.github.checks import CheckRunPayload
from worktree_review.platform.github.durable import DurableGitHubAttemptWorker
from worktree_review.platform.github.persistence import (
    MAX_PUBLICATION_ATTEMPTS,
    InMemoryGitHubReviewStore,
)
from worktree_review.platform.github.publication import GitHubCheckPublisher
from worktree_review.platform.github.runtime import GitHubApiError
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot
from worktree_review.server.state import (
    GitHubChangeRequestLocator,
    InMemoryAuthoritativeAttemptStore,
    JobStatus,
    PublishDisposition,
    StateConflictError,
)

LOCATOR = GitHubChangeRequestLocator(
    installation_id=7, repository="octo/example", pull_request_number=42
)
REQUEST_KEY = ReviewRequestKey(
    source_repository="octo/example",
    target_ref="main",
    target_head_oid="a" * 40,
    proposed_head_oid="b" * 40,
    review_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="d" * 64),
)


def _snapshot(attempt_id: str) -> AttemptExecutionSnapshot:
    return AttemptExecutionSnapshot(
        attempt_id=attempt_id,
        change_request=LOCATOR,
        request_key=REQUEST_KEY,
        proposed_ref="HEAD",
        review_policy_semver="1.0.0",
        review_policy_sha256="d" * 64,
        compute_policy_semver="1.0.0",
        compute_policy_sha256="e" * 64,
    )


def _report(attempt_id: str, gate: GateState = GateState.PASSED) -> ReviewReport:
    resolved = ResolvedCommitPair(
        source_repository="octo/example",
        target_ref="main",
        target_head_oid="a" * 40,
        proposed_ref="HEAD",
        proposed_head_oid="b" * 40,
        proposed_source="committed-ref",
    )
    identity = ReviewIdentity(
        candidate=MergeCandidateIdentity(
            source_repository="octo/example",
            target_ref="main",
            target_head_oid="a" * 40,
            proposed_head_oid="b" * 40,
            merge_tree_oid="c" * 40,
        ),
        review_policy_version=REQUEST_KEY.review_policy_version,
    )
    return ReviewReport(
        attempt_id=attempt_id,
        resolved=resolved,
        request_key=REQUEST_KEY,
        review_identity=identity,
        merge_tree_oid="c" * 40,
        review_policy_version=REQUEST_KEY.review_policy_version,
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
        summary="ok",
        error_detail=None,
        gate_state=gate,
    )


class _FakeChecks:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.updates: list[int] = []
        self.fail_times = fail_times

    async def create_check_run(self, *, repository: str, payload: CheckRunPayload) -> int:
        del repository, payload
        return 99

    async def update_check_run(
        self, *, repository: str, check_run_id: int, payload: CheckRunPayload
    ) -> None:
        del repository, payload
        self.updates.append(check_run_id)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise GitHubApiError("GitHub 502")


class _ScriptedReviewWorker:
    """Claims through the real state store, then follows the script."""

    def __init__(
        self,
        state: InMemoryAuthoritativeAttemptStore,
        store: InMemoryGitHubReviewStore,
        *,
        fail_once: set[str] | None = None,
    ) -> None:
        self._state = state
        self._store = store
        self._fail_once = set(fail_once or ())
        self.executed: list[str] = []

    async def execute_claimed_attempt(self, attempt_id: str) -> ReviewReport | None:
        lease = await self._state.claim_attempt_job(attempt_id)
        if lease is None:
            return None
        self.executed.append(attempt_id)
        if attempt_id in self._fail_once:
            self._fail_once.discard(attempt_id)
            raise RuntimeError("mirror/provider initialisation exploded")
        report = _report(attempt_id)
        await self._state.record_review_identity(
            attempt_id=attempt_id, review_identity=report.review_identity
        )
        await self._store.save_review_result(
            attempt_id, cli_result_document(report).model_dump_json(by_alias=True)
        )
        return report


class _Harness:
    def __init__(self, *, fail_once: set[str] | None = None, fail_times: int = 0) -> None:
        self.now = datetime.now(UTC)
        self.state = InMemoryAuthoritativeAttemptStore(clock=lambda: self.now, lease_seconds=60.0)
        self.store = InMemoryGitHubReviewStore(clock=lambda: self.now)
        self.checks = _FakeChecks(fail_times=fail_times)
        self.worker = _ScriptedReviewWorker(self.state, self.store, fail_once=fail_once)
        self.publisher = GitHubCheckPublisher(
            state=self.state, github_store=self.store, checks=self.checks
        )
        self.durable = DurableGitHubAttemptWorker(
            github_store=self.store,
            review_worker=self.worker,  # type: ignore[arg-type]
            publisher=self.publisher,
            state=self.state,
            idle_seconds=0.01,
            clock=lambda: self.now,
            job_lease_seconds=60.0,
        )

    async def start_attempt(self, attempt_id: str) -> str:
        lease = await self.state.start_authoritative_attempt(
            change_request=LOCATOR, request_key=REQUEST_KEY
        )
        await self.store.save_execution_snapshot(_snapshot(lease.attempt_id))
        await self.store.set_check_run_id(lease.attempt_id, 99)
        return lease.attempt_id


@pytest.mark.asyncio
async def test_crash_after_claim_recovers_and_publishes() -> None:
    harness = _Harness(fail_once={"will-crash"})
    attempt_id = await harness.start_attempt("unused")
    # The scripted worker crashes only when the attempt id matches; rename.
    harness.worker._fail_once = {attempt_id}

    first = await harness.durable.execute_attempt(attempt_id)
    assert first is None
    assert await harness.state.job_status(attempt_id) is JobStatus.RETRYABLE

    await harness.durable._recover_jobs()
    assert await harness.state.job_status(attempt_id) is JobStatus.QUEUED

    report = await harness.durable.execute_attempt(attempt_id)
    assert report is not None
    assert await harness.state.job_status(attempt_id) is JobStatus.COMPLETED
    assert harness.checks.updates == [99]
    assert await harness.store.publication_status(attempt_id) is PublicationStatus.PUBLISHED
    current = await harness.state.get_change_request_state(LOCATOR)
    assert current.standing_attempt_id == attempt_id


@pytest.mark.asyncio
async def test_retry_budget_exhaustion_lands_in_terminal_failed() -> None:
    harness = _Harness()
    attempt_id = await harness.start_attempt("x")
    harness.worker._fail_once = set()  # always fail
    harness.durable.max_job_attempts = 2

    async def _always_fail(aid: str) -> None:
        lease = await harness.state.claim_attempt_job(aid)
        assert lease is not None
        raise RuntimeError("permanent provider failure")

    harness.worker.execute_claimed_attempt = _always_fail  # type: ignore[method-assign]
    await harness.durable.execute_attempt(attempt_id)
    assert await harness.state.job_status(attempt_id) is JobStatus.RETRYABLE
    await harness.durable._recover_jobs()
    await harness.durable.execute_attempt(attempt_id)
    assert await harness.state.job_status(attempt_id) is JobStatus.RETRYABLE
    await harness.durable._recover_jobs()
    status = await harness.state.job_status(attempt_id)
    assert status is JobStatus.FAILED
    events = await harness.store.list_review_events(attempt_id)
    assert any(event.event_type == "attempt.failed" for event in events)


@pytest.mark.asyncio
async def test_crash_after_result_saved_recovers_publication_without_intent() -> None:
    harness = _Harness()
    attempt_id = await harness.start_attempt("x")
    # Simulate: pipeline completed, result persisted, process died before the
    # outbox intent was enqueued.
    report = await harness.worker.execute_claimed_attempt(attempt_id)
    assert report is not None
    assert await harness.store.get_review_result(attempt_id) is not None
    assert harness.checks.updates == []

    await harness.durable._scan_publications()
    assert harness.checks.updates == [99]
    assert await harness.store.publication_status(attempt_id) is PublicationStatus.PUBLISHED
    current = await harness.state.get_change_request_state(LOCATOR)
    assert current.standing_attempt_id == attempt_id


@pytest.mark.asyncio
async def test_crash_after_intent_saved_retries_same_check_run() -> None:
    harness = _Harness(fail_times=1)
    attempt_id = await harness.start_attempt("x")
    report = await harness.worker.execute_claimed_attempt(attempt_id)
    assert report is not None
    # Intent saved; the remote delivery itself failed (process died after).
    published = await harness.publisher.publish_terminal(attempt_id=attempt_id, report=report)
    assert published.disposition is PublishDisposition.PUBLISHED
    assert await harness.store.publication_status(attempt_id) is PublicationStatus.FAILED
    assert harness.checks.updates == [99]

    # Backoff gate: not due yet.
    await harness.durable._scan_publications()
    assert harness.checks.updates == [99]
    harness.now += timedelta(seconds=360)
    await harness.durable._scan_publications()
    assert harness.checks.updates == [99, 99]
    assert await harness.store.publication_status(attempt_id) is PublicationStatus.PUBLISHED


@pytest.mark.asyncio
async def test_repeated_remote_failures_back_off_and_never_create_a_new_check() -> None:
    harness = _Harness(fail_times=3)
    attempt_id = await harness.start_attempt("x")
    report = await harness.worker.execute_claimed_attempt(attempt_id)
    assert report is not None
    await harness.publisher.publish_terminal(attempt_id=attempt_id, report=report)
    for _ in range(2):
        harness.now += timedelta(seconds=360)
        await harness.durable._scan_publications()
        assert await harness.store.publication_status(attempt_id) is PublicationStatus.FAILED
    harness.now += timedelta(seconds=360)
    await harness.durable._scan_publications()
    assert harness.checks.updates == [99, 99, 99, 99]
    assert await harness.store.publication_status(attempt_id) is PublicationStatus.PUBLISHED


@pytest.mark.asyncio
async def test_publication_retry_budget_is_bounded_and_terminal() -> None:
    harness = _Harness(fail_times=100)
    attempt_id = await harness.start_attempt("x")
    report = await harness.worker.execute_claimed_attempt(attempt_id)
    assert report is not None
    await harness.publisher.publish_terminal(attempt_id=attempt_id, report=report)
    for _ in range(MAX_PUBLICATION_ATTEMPTS + 2):
        harness.now += timedelta(seconds=360)
        await harness.durable._scan_publications()
    assert await harness.store.publication_status(attempt_id) is PublicationStatus.FAILED
    deliveries = len(harness.checks.updates)
    assert deliveries == MAX_PUBLICATION_ATTEMPTS
    # Terminal: further scans change nothing.
    harness.now += timedelta(days=7)
    await harness.durable._scan_publications()
    assert len(harness.checks.updates) == deliveries


@pytest.mark.asyncio
async def test_late_old_attempt_cannot_overwrite_new_standing_decision() -> None:
    harness = _Harness()
    older_id = await harness.start_attempt("older")
    # The older attempt runs its pipeline to completion...
    older_report = await harness.worker.execute_claimed_attempt(older_id)
    assert older_report is not None
    # ...but before it publishes, a newer Attempt takes authority.
    newer = await harness.state.start_authoritative_attempt(
        change_request=LOCATOR, request_key=REQUEST_KEY
    )
    await harness.store.save_execution_snapshot(_snapshot(newer.attempt_id))
    await harness.store.set_check_run_id(newer.attempt_id, 100)

    await harness.durable._scan_publications()
    # The old Attempt's own check completed audit-only; no standing decision.
    assert harness.checks.updates == [99]
    current = await harness.state.get_change_request_state(LOCATOR)
    assert current.standing_attempt_id is None
    assert current.authoritative_attempt_id == newer.attempt_id
    assert await harness.store.publication_status(older_id) is PublicationStatus.SUPERSEDED

    newer_report = await harness.worker.execute_claimed_attempt(newer.attempt_id)
    assert newer_report is not None
    result = await harness.publisher.publish_terminal(
        attempt_id=newer.attempt_id, report=newer_report
    )
    assert result.disposition is PublishDisposition.PUBLISHED
    current = await harness.state.get_change_request_state(LOCATOR)
    assert current.standing_attempt_id == newer.attempt_id
    assert harness.checks.updates == [99, 100]


@pytest.mark.asyncio
async def test_publication_exception_never_requeues_the_pipeline() -> None:
    """A publish-time crash must not re-run the pipeline (no silent re-billing)."""
    harness = _Harness()

    async def _exploding_publish(*, attempt_id: str, report: object) -> None:
        raise RuntimeError("outbox database write exploded")

    harness.publisher.publish_terminal = _exploding_publish  # type: ignore[method-assign]
    attempt_id = await harness.start_attempt("x")
    result = await harness.durable.execute_attempt(attempt_id)
    assert result is not None
    # The pipeline ran exactly once (the result is saved), the job was NOT
    # marked retryable (no silent re-billing on the next recovery pass), and
    # an audit event records the publication failure.
    assert harness.worker.executed == [attempt_id]
    status = await harness.state.job_status(attempt_id)
    assert status is JobStatus.RUNNING  # publication CAS never ran; scan owns recovery
    audits = await harness.state.audit_events()
    assert any(event["event_type"] == "publication_error" for event in audits)


@pytest.mark.asyncio
async def test_exhausted_publication_finalizes_the_job() -> None:
    harness = _Harness(fail_times=100)
    attempt_id = await harness.start_attempt("x")
    report = await harness.worker.execute_claimed_attempt(attempt_id)
    assert report is not None
    # Crash window: result + intent saved, but the authoritative CAS never
    # ran — and it keeps raising on every recovery pass, so the job would
    # stay RUNNING forever without explicit finalization.
    from worktree_review.platform.github.snapshot import PublicationIntent

    await harness.store.enqueue_publication(
        PublicationIntent(
            attempt_id=attempt_id,
            check_run_id=99,
            intent="terminal-check",
            payload={},
        )
    )

    async def _broken_cas(**_kwargs: object) -> None:
        raise StateConflictError("authoritative store unavailable")

    harness.state.publish_if_authoritative = _broken_cas  # type: ignore[method-assign]
    for _ in range(MAX_PUBLICATION_ATTEMPTS + 2):
        harness.now += timedelta(seconds=360)
        await harness.durable._scan_publications()
    assert await harness.store.publication_status(attempt_id) is PublicationStatus.FAILED
    assert await harness.state.job_status(attempt_id) is JobStatus.FAILED


@pytest.mark.asyncio
async def test_retryable_failure_is_not_a_terminal_event_until_exhaustion() -> None:
    harness = _Harness()
    attempt_id = await harness.start_attempt("x")
    harness.worker._fail_once = {attempt_id}
    await harness.durable.execute_attempt(attempt_id)
    events = await harness.store.list_review_events(attempt_id)
    event_types = [event.event_type for event in events]
    assert "attempt.failed" not in event_types
    # The execution failure is visible, but as a retryable — not terminal — signal.
    # (The scripted worker raises before its own boundary records; the durable
    # layer owns retryability.)
    assert await harness.state.job_status(attempt_id) is JobStatus.RETRYABLE

    harness.durable.max_job_attempts = 1
    await harness.durable._recover_jobs()
    events = await harness.store.list_review_events(attempt_id)
    event_types = [event.event_type for event in events]
    assert "attempt.failed" in event_types
    assert await harness.state.job_status(attempt_id) is JobStatus.FAILED
