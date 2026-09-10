"""Durable GitHub Attempt worker loop: claim, restore, pipeline, publish."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.core.report import ReviewReport
from worktree_review.platform.github.persistence import GitHubReviewStore
from worktree_review.platform.github.publication import GitHubCheckPublisher
from worktree_review.platform.github.worker import GitHubReviewWorker
from worktree_review.server.state import PublishDisposition

Sleep = Callable[[float], Awaitable[None]]


class DurableGitHubAttemptWorker:
    """Claim persisted jobs, restore the frozen snapshot, run the worker, publish."""

    def __init__(
        self,
        *,
        github_store: GitHubReviewStore,
        review_worker: GitHubReviewWorker,
        publisher: GitHubCheckPublisher,
        idle_seconds: float = 0.5,
        sleep: Sleep | None = None,
    ) -> None:
        self._github_store = github_store
        self._review_worker = review_worker
        self._publisher = publisher
        self.idle_seconds = idle_seconds
        self._sleep: Sleep = sleep if sleep is not None else asyncio.sleep

    async def execute_attempt(self, attempt_id: str) -> ReviewReport | None:
        report = await self._review_worker.execute_claimed_attempt(attempt_id)
        if report is None:
            return None
        published = await self._publisher.publish_terminal(attempt_id=attempt_id, report=report)
        if published.disposition is PublishDisposition.PUBLISHED:
            status = await self._github_store.publication_status(attempt_id)
            if status is PublicationStatus.FAILED:
                await self._publisher.retry_outbox(attempt_id, report)
        return report

    async def recover_queued(self) -> tuple[str, ...]:
        recovered: list[str] = []
        for snapshot in await self._github_store.list_recoverable_queued():
            report = await self._run_one(snapshot.attempt_id)
            if report is not None:
                recovered.append(snapshot.attempt_id)
        return tuple(recovered)

    async def _run_one(self, attempt_id: str) -> ReviewReport | None:
        try:
            return await self.execute_attempt(attempt_id)
        except Exception:
            return None

    async def run_forever(self) -> None:
        while True:
            try:
                snapshots = await self._github_store.list_recoverable_queued()
            except Exception:
                await self._sleep(self.idle_seconds)
                continue
            if not snapshots:
                await self._sleep(self.idle_seconds)
                continue
            progressed = False
            for snapshot in snapshots:
                report = await self._run_one(snapshot.attempt_id)
                if report is None:
                    await self._sleep(self.idle_seconds)
                    continue
                progressed = True
            if not progressed:
                await self._sleep(self.idle_seconds)
