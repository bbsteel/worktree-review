"""Durable GitHub Attempt worker loop: claim, restore, pipeline, publish."""

from __future__ import annotations

import asyncio

from worktree_review.core.report import ReviewReport
from worktree_review.platform.github.persistence import GitHubReviewStore
from worktree_review.platform.github.publication import GitHubCheckPublisher
from worktree_review.platform.github.worker import GitHubReviewWorker


class DurableGitHubAttemptWorker:
    """Claim persisted jobs, restore the frozen snapshot, run the worker, publish."""

    def __init__(
        self,
        *,
        github_store: GitHubReviewStore,
        review_worker: GitHubReviewWorker,
        publisher: GitHubCheckPublisher,
        idle_seconds: float = 0.5,
    ) -> None:
        self._github_store = github_store
        self._review_worker = review_worker
        self._publisher = publisher
        self.idle_seconds = idle_seconds

    async def execute_attempt(self, attempt_id: str) -> ReviewReport | None:
        report = await self._review_worker.execute_claimed_attempt(attempt_id)
        if report is None:
            return None
        await self._publisher.publish_terminal(attempt_id=attempt_id, report=report)
        return report

    async def recover_queued(self) -> tuple[str, ...]:
        recovered: list[str] = []
        for snapshot in await self._github_store.list_recoverable_queued():
            report = await self.execute_attempt(snapshot.attempt_id)
            if report is not None:
                recovered.append(snapshot.attempt_id)
        return tuple(recovered)

    async def run_forever(self) -> None:
        await self.recover_queued()
        while True:
            snapshots = await self._github_store.list_recoverable_queued()
            if not snapshots:
                await asyncio.sleep(self.idle_seconds)
                continue
            for snapshot in snapshots:
                await self.execute_attempt(snapshot.attempt_id)
