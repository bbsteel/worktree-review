"""Shared Attempt create/execute path for CLI, Web, and GitHub."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from worktree_review.application.context import ReviewExecutionContext
from worktree_review.core.errors import InvalidInvocationError
from worktree_review.core.pipeline import ReviewRequest, run_review_pipeline
from worktree_review.core.provider import ProviderClient
from worktree_review.core.report import ReviewCallPlan, ReviewProgressEvent, ReviewReport


def allocate_attempt_id() -> str:
    """Allocate an Attempt ID before enqueue or Pipeline execution."""

    return str(uuid.uuid4())


class ReviewApplicationService:
    """Prepare-independent executor: callers pass a resolved ReviewRequest."""

    def allocate_attempt_id(self) -> str:
        return allocate_attempt_id()

    async def execute(
        self,
        request: ReviewRequest,
        *,
        repository_path: Path,
        attempt_id: str | None = None,
        provider: ProviderClient | None = None,
        on_call_plan_ready: Callable[[ReviewCallPlan], None] | None = None,
        on_progress: Callable[[ReviewProgressEvent], None] | None = None,
    ) -> ReviewReport:
        allocated_attempt_id = attempt_id or self.allocate_attempt_id()
        execution = ReviewExecutionContext(
            repository_path=repository_path,
            attempt_id=allocated_attempt_id,
            surface=request.surface,
        )
        trusted_path = execution.repository_path.expanduser().resolve()
        if not trusted_path.is_dir():
            raise InvalidInvocationError(f"repository_path is not a directory: {trusted_path}")
        report = await run_review_pipeline(
            request,
            repository_path=trusted_path,
            attempt_id=execution.attempt_id,
            provider=provider,
            on_call_plan_ready=on_call_plan_ready,
            on_progress=on_progress,
        )
        if report.attempt_id != execution.attempt_id:
            raise RuntimeError(
                "pipeline returned a different attempt_id than the execution context"
            )
        return report
