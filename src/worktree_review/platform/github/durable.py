"""Durable GitHub Attempt worker loop: claim, restore, pipeline, publish.

Recovery contract:
- Jobs: queued → running → completed, with retryable → queued and a terminal
  failed once the retry budget is exhausted. Stale running leases (worker
  crash after claim) are recovered on every pass.
- Publications: attempts with a saved terminal result but no durable
  publication are scanned every pass (bounded backoff, one check_run_id).
- A crashed pass never strands an Attempt silently: it is requeued, or it
  lands in an explicit, queryable failed terminal state.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.application.review_events import (
    ReviewEvent,
    safe_error_payload,
)
from worktree_review.core.report import ReviewReport
from worktree_review.platform.cli.result import load_review_report_from_cli_result
from worktree_review.platform.github.persistence import GitHubReviewStore
from worktree_review.platform.github.publication import GitHubCheckPublisher
from worktree_review.platform.github.worker import GitHubReviewWorker
from worktree_review.server.state import (
    AuthoritativeAttemptStore,
    JobStatus,
    PublishDisposition,
)

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], datetime]

DEFAULT_MAX_JOB_ATTEMPTS = 5
DEFAULT_JOB_LEASE_SECONDS = 1800.0


class DurableGitHubAttemptWorker:
    """Claim persisted jobs, restore the frozen snapshot, run the worker, publish."""

    def __init__(
        self,
        *,
        github_store: GitHubReviewStore,
        review_worker: GitHubReviewWorker,
        publisher: GitHubCheckPublisher,
        state: AuthoritativeAttemptStore | None = None,
        idle_seconds: float = 0.5,
        sleep: Sleep | None = None,
        clock: Clock | None = None,
        max_job_attempts: int = DEFAULT_MAX_JOB_ATTEMPTS,
        job_lease_seconds: float = DEFAULT_JOB_LEASE_SECONDS,
    ) -> None:
        self._github_store = github_store
        self._review_worker = review_worker
        self._publisher = publisher
        self._state = state
        self.idle_seconds = idle_seconds
        self._sleep: Sleep = sleep if sleep is not None else asyncio.sleep
        self._clock: Clock = clock if clock is not None else (lambda: datetime.now(UTC))
        self.max_job_attempts = max_job_attempts
        self.job_lease_seconds = job_lease_seconds

    async def execute_attempt(self, attempt_id: str) -> ReviewReport | None:
        """One Attempt, one boundary: execution failures become RETRYABLE jobs.

        Publication failures never requeue the job — the result is already
        saved, and the bounded outbox scan owns remote retries. Re-running the
        pipeline here would silently re-bill the provider.
        """
        try:
            report = await self._review_worker.execute_claimed_attempt(attempt_id)
        except Exception as exc:
            if self._state is not None:
                try:
                    # Only typed, scrubbed error data is persisted: raw
                    # exception text must never reach jobs, audits, or the
                    # browser Detail (job_last_error is served by the API).
                    failure = safe_error_payload(exc)
                    await self._state.mark_job_retryable(
                        attempt_id=attempt_id,
                        error=f"{failure['category']}: {failure['safe_detail']}",
                    )
                except Exception:
                    logger.exception(
                        "failed to mark job retryable", extra={"attempt_id": attempt_id}
                    )
            return None
        if report is None:
            return None
        try:
            published = await self._publisher.publish_terminal(attempt_id=attempt_id, report=report)
        except Exception as exc:
            logger.exception("publication raised; outbox scan owns recovery")
            if self._state is not None:
                try:
                    snapshot = await self._github_store.get_execution_snapshot(attempt_id)
                    if snapshot is not None:
                        publication_failure: dict[str, object] = dict(safe_error_payload(exc))
                        await self._state.append_audit_event(
                            event_type="publication_error",
                            change_request=snapshot.change_request,
                            attempt_id=attempt_id,
                            payload=publication_failure,
                        )
                except Exception:
                    logger.exception("failed to audit publication error")
            return report
        if published is not None and published.disposition is PublishDisposition.PUBLISHED:
            status = await self._github_store.publication_status(attempt_id)
            if status is PublicationStatus.FAILED:
                # One immediate retry; further retries come from the bounded
                # background scan in run_forever.
                await self._publisher.retry_outbox(attempt_id, report)
        return report

    async def recover_queued(self) -> tuple[str, ...]:
        recovered: list[str] = []
        await self._recover_jobs()
        for snapshot in await self._github_store.list_recoverable_queued():
            report = await self._run_one(snapshot.attempt_id)
            if report is not None:
                recovered.append(snapshot.attempt_id)
        await self._scan_publications()
        return tuple(recovered)

    async def _recover_jobs(self) -> None:
        if self._state is None:
            return
        report = await self._state.recover_interrupted_jobs(
            max_attempts=self.max_job_attempts,
            lease_seconds=self.job_lease_seconds,
        )
        for attempt_id in (*report.requeued, *report.lease_recovered):
            await self._record_safe_event(
                attempt_id,
                "attempt.resumed_after_restart",
                {
                    "safe_detail": (
                        "Attempt is re-executed after worker recovery; provider "
                        "calls may be repeated and billed again. Prior results "
                        "are immutable and are never overwritten."
                    )
                },
            )
        for attempt_id in report.exhausted:
            await self._record_safe_event(
                attempt_id,
                "attempt.failed",
                {
                    "safe_detail": (
                        "Attempt exhausted its retry budget and is now in the "
                        "terminal failed job state."
                    )
                },
            )

    async def _record_safe_event(
        self, attempt_id: str, event_type: str, payload: dict[str, str]
    ) -> None:
        try:
            existing = await self._github_store.list_review_events(attempt_id)
            await self._github_store.append_review_event(
                ReviewEvent(
                    sequence=len(existing) + 1,
                    occurred_at=self._clock(),
                    attempt_id=attempt_id,
                    surface="github",
                    event_type=event_type,
                    payload=payload,
                )
            )
        except Exception:
            logger.exception("failed to record recovery event", extra={"attempt_id": attempt_id})

    async def _scan_publications(self) -> None:
        """Publish saved-but-unpublished results with bounded outbox retries."""
        try:
            pending = await self._github_store.list_pending_publications(self._clock())
        except Exception:
            logger.exception("publication scan failed")
            return
        for attempt_id in pending:
            try:
                result_json = await self._github_store.get_review_result(attempt_id)
                if not result_json:
                    continue
                report = load_review_report_from_cli_result(result_json)
                await self._publisher.retry_outbox(attempt_id, report)
            except Exception:
                logger.exception("publication recovery failed", extra={"attempt_id": attempt_id})
        # Attempts that spent the whole retry budget are terminal: the job
        # must not linger in a non-terminal state forever.
        if self._state is None:
            return
        try:
            exhausted = await self._github_store.list_exhausted_publications()
        except Exception:
            logger.exception("exhausted publication scan failed")
            return
        for attempt_id in exhausted:
            try:
                await self._state.finalize_attempt_job(
                    attempt_id,
                    status=JobStatus.FAILED,
                    reason="publication retry budget exhausted",
                )
            except Exception:
                logger.exception("failed to finalize job", extra={"attempt_id": attempt_id})

    async def _run_one(self, attempt_id: str) -> ReviewReport | None:
        try:
            return await self.execute_attempt(attempt_id)
        except Exception:
            logger.exception("attempt escaped its boundary", extra={"attempt_id": attempt_id})
            return None

    async def run_forever(self) -> None:
        while True:
            try:
                await self._recover_jobs()
                snapshots = await self._github_store.list_recoverable_queued()
            except Exception:
                await self._sleep(self.idle_seconds)
                continue
            if not snapshots:
                await self._scan_publications()
                await self._sleep(self.idle_seconds)
                continue
            progressed = False
            for snapshot in snapshots:
                report = await self._run_one(snapshot.attempt_id)
                if report is None:
                    await self._sleep(self.idle_seconds)
                    continue
                progressed = True
            await self._scan_publications()
            if not progressed:
                await self._sleep(self.idle_seconds)
